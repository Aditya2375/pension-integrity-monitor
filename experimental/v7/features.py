# scoreV3: v3-generic scorer. Port of scoreN7 onto aggV3.pkl + matches_v3.csv,
# adding v3 feeds: pmjay (documentary), kyc_refresh / aadhaar_upd / epfo / mgnrega (strong alive),
# lic / nps / passport / dl (mid alive), ration / lpg / utility (household weak alive).
# DORMANT bank KYC is never death evidence. Family-kept SIM/bank/LIC after a registered
# death is reuse corroboration, not alive proof.
# Usage: python3 scoreV3.py DIR  (reads DIR/aggV3.pkl + DIR/matches_v3.csv,
#         writes DIR/flagged_pensioners.csv + DIR/reasoning.txt)
import csv, sys, math, pickle, difflib, os, json
from collections import defaultdict
DBG = set(os.environ.get("SC_DBG", "").split()) if os.environ.get("SC_DBG") else set()
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from pim import matching

BASE_RATE = 0.04
D = sys.argv[1] if len(sys.argv) > 1 else "/tmp/round3/"
if not D.endswith("/"): D += "/"
agg = pickle.load(open(D + "aggV3.pkl", "rb"))
if os.path.exists(D + "aggV3b.pkl"):
    agg.update(pickle.load(open(D + "aggV3b.pkl", "rb")))

def pdte(s):
    s = (s or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try: return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
        except ValueError: return None
    return None
def evd(s):
    """first date from a pipe-joined evidence cell"""
    return pdte((s or "").split("|")[0])
def logit(p): return math.log(p / (1 - p))
def sig(x): return 1 / (1 + math.exp(-x))
def lr_interp(conf, lo, hi): return lo ** (1 - conf) * hi ** conf

def _detect_window(agg):
    tb = list(agg["bank_last"].values())
    tt = list(agg["tele_last"].values())
    snap = date.fromisoformat(os.environ["PIM_SNAPSHOT_DATE"]) if os.environ.get("PIM_SNAPSHOT_DATE") else max(tb + tt)
    y, m = snap.year, snap.month
    def prev(y, m, k):
        for _ in range(k):
            m -= 1
            if m == 0: y, m = y - 1, 12
        return y * 100 + m
    return snap, prev(y, m, 2), prev(y, m, 1), y * 100 + m

SNAP, M1, M2, M3 = _detect_window(agg)
pm = agg["pm"]
def fld(p, *names):
    for n in names:
        v = p.get(n)
        if v: return v
    return ""
for p in pm:  # normalize join fields across schema variants
    p["_acct"] = fld(p, "bank_account", "account_number")
    p["_mob"] = fld(p, "mobile", "mobile_number", "phone")
    p["_aad"] = (fld(p, "aadhaar_number", "aadhaar") or "").strip()
    p["_pan"] = (fld(p, "pan") or "").strip()
    p["_amt"] = fld(p, "monthly_amount", "pension_amount", "amount")
matches = {r["pensioner_id"]: r for r in csv.DictReader(open(D + "matches_v3.csv"))}

death_by_rid={r["registration_no"]:r for r in agg["deaths"]}
pm_aad = {p["_aad"]: p["pensioner_id"] for p in pm if p["_aad"]}
def assign(idcol, confcol, aadhaar_rows=None, rowkey=None, min_conf=0.8):
    from detector.assignment import Candidate,assign as global_assign
    prefix=confcol.removesuffix('_conf');edges=[];edge_keys=set();exact_keys=set()
    by_identity=defaultdict(list)
    for p in pm:
        if p['_aad']:by_identity[p['_aad']].append(p['pensioner_id'])
    source_lookup={str(r[rowkey]):r for r in (aadhaar_rows or [])} if rowkey else {}
    if aadhaar_rows is not None:
        for seq,d in enumerate(aadhaar_rows):
            key=(d.get('aadhaar_number') or '').strip()
            for pid in by_identity.get(key,[]):
                rid=str(d[rowkey]);edges.append(Candidate(pid,rid,1.,seq,True));edge_keys.add((pid,rid));exact_keys.add((pid,rid))
    option_lookup={}
    for p in pm:
        pid=p['pensioner_id'];m=matches[pid]
        options=json.loads(m.get(prefix+'_candidates') or '[]')
        if not options and m.get(idcol):options=[{'confidence':float(m.get(confcol) or 0),'record_id':str(m[idcol]),'source_sequence':0,'evidence':m.get(prefix+'_ev','')}]
        for o in options:
            conf=float(o['confidence']);rid=o['record_id'];option_lookup[(pid,rid)]=o
            if conf<min_conf or not rid or (pid,rid) in edge_keys:continue
            edges.append(Candidate(pid,rid,conf,int(o['source_sequence'])));edge_keys.add((pid,rid))
    result=global_assign([p['pensioner_id'] for p in pm],edges);out={}
    for pid,r in result.items():
        rid=r['record_id']
        if rid is None:continue
        grade='exact' if r['status']=='exact' else 'strong' if r['confidence']>=.9 else 'weak'
        out[pid]=(grade,r['confidence'],rid)
        o=option_lookup.get((pid,rid))
        if o:
            matches[pid][prefix+'_ev']=o['evidence'];matches[pid][confcol]=str(r['confidence']);matches[pid][idcol]=rid
    return out

reg_by_pid = assign("death_id", "death_conf", aadhaar_rows=agg["deaths"], rowkey="registration_no")
hosp_by_pid = assign("hosp_id", "hosp_conf")
pmjay_by_pid = assign("pmjay_id", "pmjay_conf") if "pmjay_conf" in next(iter(matches.values()), {}) else {}
eroll_by_pid = assign("eroll_id", "eroll_conf", min_conf=0.9)

cons = []
for cid, cname, caddr in agg["cons_full"]:
    paid = None
    for k, (u, pd) in agg["util_m"].get(cid, {}).items():
        if pd and (paid is None or pd > paid): paid = pd
    cons.append([cid, cname, caddr, paid])
cons_toks = [frozenset(matching.normalize_name(c[1]).split()) for c in cons]
util_hn = {}
for i, c in enumerate(cons):
    hn = c[2].split(" ", 1)[0] if c[2] else ""
    util_hn.setdefault(hn, []).append(i)

def det_amt(p, ym):
    det = agg["bank_det"].get(p["_acct"], {})
    return det.get(ym, [0, 0.0, 0])[1]

def util_match(p):
    ptoks = frozenset(matching.normalize_name(p["full_name"]).split())
    paddr = " ".join((p["address"] or "").lower().split())
    hn = paddr.split(" ", 1)[0] if paddr else ""
    candidates = []
    for ci in util_hn.get(hn, ()):
        if not (ptoks & cons_toks[ci]): continue
        _cid, cname, caddr, cpaid = cons[ci]
        caddr = " ".join((caddr or "").lower().split())
        ns = matching.name_match_pct(p["full_name"], cname)
        ads = difflib.SequenceMatcher(None, paddr, caddr).ratio()
        if ns >= 0.8 and ads >= 0.9:
            candidates.append((ads, ns, ci))
    candidates.sort(reverse=True)
    if not candidates: return None
    if len(candidates) > 1 and candidates[0][0:2] == candidates[1][0:2]: return None
    return candidates[0][2]

def mrecent(ym_str, within=6):
    """YYYY-MM within `within` months of snapshot month."""
    if not ym_str or len(ym_str) < 7: return False
    y, m = int(ym_str[:4]), int(ym_str[5:7])
    diff = (SNAP.year - y) * 12 + (SNAP.month - m)
    return 0 <= diff <= within

household_members=defaultdict(list)
for member in pm:
    address=' '.join((member.get('address') or '').casefold().split())
    if address:household_members[(member.get('district',''),address)].append(member)
lag_by_district=defaultdict(list)
for record in agg['deaths']:
    died=pdte(record.get('date_of_death'));registered=pdte(record.get('registration_date'))
    if died and registered and died<=registered<=SNAP:lag_by_district[record.get('district','')].append((registered-died).days)
rows_out = []
feature_file = open(os.environ["FEATURES_OUT"],"w",newline="") if os.environ.get("FEATURES_OUT") else None
feature_writer = None
stats = {"reg_exact":0,"reg_strong":0,"reg_weak":0,"hosp_strong":0,"hosp_weak":0,"pmjay_strong":0,
         "pmjay_weak":0,"eroll":0,"bank_stop":0,"aligned":0,"shape_bank":0,"shape_tele":0,
         "shape_aligned":0,"chanmix":0,"strip":0,"util_drop":0,"util_unpaid":0,"joint_dark":0,
         "dlc_miss":0,"cap_chronic":0,"cap_weak":0,"gate":0,"dlc_alive":0,
         "alive_kyc":0,"alive_aad":0,"alive_epfo":0,"alive_mgnrega":0,"alive_lic":0,
         "alive_household":0,"reuse_lic":0,"alive_nps":0,"alive_passport":0,"alive_dl":0,
         "alive_vehicle":0,"reuse_vehicle":0,"reuse_toll":0,"mun_mutation":0,"alive_municipal":0}

for p in pm[int(os.environ.get("SC_SKIP","0")):int(os.environ.get("SC_SKIP","0"))+int(os.environ.get("SC_LIMIT",str(len(pm))))]:
    pid = p["pensioner_id"]
    m = matches[pid]
    lo = logit(BASE_RATE)
    notes = []
    death_dates = []
    doc_grades = []

    if pid in reg_by_pid:
        g, conf, rid = reg_by_pid[pid]
        if g == "exact": lo += math.log(60); notes.append("death registry aadhaar-linked"); stats["reg_exact"] += 1
        elif g == "strong": lo += math.log(lr_interp(conf, 0.5, 40)); notes.append(f"death registry match conf={conf:.2f}"); stats["reg_strong"] += 1
        else: lo += math.log(2.5); notes.append(f"weak registry lead conf={conf:.2f}"); stats["reg_weak"] += 1
        doc_grades.append(g)
        dd = pdte(death_by_rid.get(rid,{}).get("date_of_death")) if g == "exact" else evd(m.get("death_ev"))
        if dd: death_dates.append((dd, g))
    if pid in hosp_by_pid:
        g, conf, hid = hosp_by_pid[pid]
        if g == "strong": lo += math.log(lr_interp(conf, 0.6, 30)); notes.append(f"hospital DIED conf={conf:.2f}"); stats["hosp_strong"] += 1
        else: lo += math.log(2.0); notes.append(f"weak hospital DIED lead conf={conf:.2f}"); stats["hosp_weak"] += 1
        doc_grades.append(g)
        hd = evd(m.get("hosp_ev"))
        if hd: death_dates.append((hd, g))
    if pid in pmjay_by_pid:
        g, conf, jid = pmjay_by_pid[pid]
        if g == "strong": lo += math.log(lr_interp(conf, 0.6, 30)); notes.append(f"PM-JAY DIED conf={conf:.2f}"); stats["pmjay_strong"] += 1
        else: lo += math.log(2.0); notes.append(f"weak PM-JAY DIED lead conf={conf:.2f}"); stats["pmjay_weak"] += 1
        doc_grades.append(g)
        jd = evd(m.get("pmjay_ev"))
        if jd: death_dates.append((jd, g))
    if pid in eroll_by_pid:
        g, conf, eid = eroll_by_pid[pid]
        ed = evd(m.get("eroll_ev"))
        if ed is None or ed <= SNAP:
            lo += math.log(lr_interp(conf, 0.7, 5)); notes.append(f"electoral DELETED conf={conf:.2f}")
            doc_grades.append("strong"); stats["eroll"] += 1
            if ed: death_dates.append((ed, "strong"))
    mun_conf = float(m.get("municipal_property_conf") or 0)
    mun_ev = (m.get("municipal_property_ev") or "").split("|")
    mun_mut = pdte(mun_ev[0]) if mun_ev and mun_ev[0] else None
    if mun_conf >= 0.85 and mun_mut and mun_mut <= SNAP:
        lo += math.log(3.0); notes.append("municipal property mutation (lags death, weak lead)"); stats["mun_mutation"] += 1
        doc_grades.append("weak"); death_dates.append((mun_mut, "weak"))

    bm = agg["bank_month"].get(p["_acct"], {})
    tm = agg["tele_month"].get(p["_mob"], {})
    bS, bO = bm.get(M1, 0), bm.get(M2, 0)
    tS, tO = tm.get(M1, 0), tm.get(M2, 0)
    bank_stop = None
    bank_chronic = not any(v > 0 for v in bm.values())
    tele_chronic = p["_mob"] not in agg["tele_month"] or not any(v > 0 for v in tm.values())
    # --- day-precise self-activity timeline (strip-pattern debits excluded) ---
    pension_amt = float(p["_amt"] or 0)
    tx_all = agg["bank_tx"].get(p["_acct"], {})
    cd_all = agg["disb_cd"].get(pid, {})
    self_dates, strip_dates = [], []
    for ym, txns in tx_all.items():
        cd = cd_all.get(ym)
        for d, a in txns:
            if d > SNAP: continue
            if cd and pension_amt and 0 <= (d - cd).days <= 2 and a >= 0.85 * pension_amt and len(txns) <= 2:
                strip_dates.append(d)
            else:
                self_dates.append(d)
    tl_any = agg["tele_last"].get(p["_mob"])
    last_bank_self = max(self_dates) if self_dates else None
    last_bank_strip = max(strip_dates) if strip_dates else None
    ev = [d for d in (last_bank_self, tl_any) if d]
    ci0 = util_match(p)
    cpaid0 = cons[ci0][3] if ci0 is not None else None
    # Household bill payments cannot establish personal activity.
    lc0 = agg["dlc"].get(pid)
    if lc0 and lc0<=SNAP: ev.append(lc0)
    pf0 = agg["pan_filed"].get(p["_pan"])
    # Filing can be done by a representative, not personal presence.
    ev = [d for d in ev if d <= SNAP]
    last_self = max(ev) if ev else None
    quiet_days = (SNAP - last_self).days if last_self else None
    established = (sum(1 for v in bm.values() if v > 0) + sum(1 for v in tm.values() if v > 0)) >= 2
    if quiet_days is None:
        qlr = None
    elif quiet_days < 14: qlr = 1.0
    elif quiet_days < 30: qlr = 2.5
    elif quiet_days < 45: qlr = 8.0
    elif quiet_days < 75: qlr = 25.0
    elif quiet_days < 120: qlr = 40.0
    elif quiet_days < 240: qlr = 25.0
    else: qlr = 12.0
    if qlr and not established:
        qlr = min(qlr, 3.0)
    if qlr and qlr > 1.0:
        lo += math.log(qlr); notes.append(f"self-activity ceased {quiet_days}d before snapshot"); stats["bank_stop"] += 1
        bank_stop = last_self
    if last_bank_self and tl_any and abs((last_bank_self - tl_any).days) <= 15 and qlr and qlr >= 8:
        lo += math.log(2.2); notes.append("bank+telecom cessation aligned"); stats["aligned"] += 1
    if bank_chronic: lo += math.log(1.15); notes.append("no customer bank activity in window")
    if tele_chronic: lo += math.log(1.1); notes.append("no telecom activity in window")

    shape_b = shape_t = False
    if bank_stop is None and bS >= 5 and bO >= 1:
        amt1 = det_amt(p, M1); amt2 = det_amt(p, M2)
        if (bO <= 0.34 * bS) or (amt1 > 0 and amt2 <= 0.3 * amt1):
            lo += math.log(2.0); shape_b = True
            notes.append(f"bank debit pattern collapsed {bS}->{bO}"); stats["shape_bank"] += 1
    if tS >= 200 and tO >= 1 and tO <= 0.25 * tS:
        lo += math.log(2.0); shape_t = True
        notes.append(f"telecom volume collapsed {tS:.0f}->{tO:.0f}"); stats["shape_tele"] += 1
    if shape_b and shape_t:
        lo += math.log(1.6); notes.append("bank+telecom shape change aligned"); stats["shape_aligned"] += 1
    det = agg["bank_det"].get(p["_acct"], {})
    if M1 in det and M2 in det and det[M1][0] >= 4 and det[M2][0] >= 2:
        sh1 = det[M1][2] / det[M1][0]; sh2 = det[M2][2] / det[M2][0]
        if sh1 >= 0.5 and sh2 <= 0.3 * sh1:
            lo += math.log(1.5); notes.append(f"ATM share collapsed {sh1:.2f}->{sh2:.2f}"); stats["chanmix"] += 1
    def strip_ratio(ym):
        if ym not in tx_all or ym not in cd_all: return None
        tot = sum(a for _, a in tx_all[ym])
        if tot <= 0: return None
        near = sum(a for d, a in tx_all[ym] if 0 <= (d - cd_all[ym]).days <= 2)
        return near / tot
    r1, r2, r3 = strip_ratio(M1), strip_ratio(M2), strip_ratio(M3)
    strip_months = sum(1 for r in (r1, r2, r3) if r is not None and r >= 0.8)
    if strip_months >= 2:
        lo += math.log(10.0); notes.append(f"pension stripped within 2 days of credit in {strip_months} months"); stats["strip"] += 1
    elif strip_months == 1:
        lo += math.log(2.0); notes.append("pension-strip pattern appeared"); stats["strip"] += 1
    if last_bank_strip and quiet_days is not None and quiet_days >= 30 and (SNAP - last_bank_strip).days <= 45:
        lo += math.log(6.0); notes.append("account active only to strip pension (family reuse)"); stats["strip"] += 1

    ci = ci0
    if ci is not None:
        umon = agg["util_m"].get(cons[ci][0], {})
        u1 = umon.get(M1); u2 = umon.get(M2); u3 = umon.get(M3)
        if u1 and u2 and u1[0] >= 150 and u2[0] <= 0.35 * u1[0]:
            lo += math.log(1.4); notes.append(f"electricity consumption dropped {u1[0]:.0f}->{u2[0]:.0f} kWh"); stats["util_drop"] += 1
        paid_ms = [k for k, (u, pd) in umon.items() if pd and k != M3]
        unpaid_late = [k for k, (u, pd) in umon.items() if not pd and k >= M2 - 1]
        if len(paid_ms) >= 2 and unpaid_late:
            lo += math.log(2.5); notes.append("utility bill unpaid after regular payment"); stats["util_unpaid"] += 1
    dd_pool = [d for d, g in death_dates]
    if bank_stop: dd_pool.append(bank_stop)
    ddate = min(dd_pool) if dd_pool else None
    exact_death = any(g == "exact" for _, g in death_dates)

    lc_d = agg["dlc"].get(pid)
    dlc_missing = lc_d is None
    if lc_d and ddate and lc_d > ddate:
        lo += math.log(0.12); notes.append("VERIFIED life certificate after death/cessation date (alive)"); stats["dlc_alive"] += 1
    elif dlc_missing:
        if bank_stop: lo += math.log(4.0); notes.append("no life certificate in annual wave + cessation")
        else: lo += math.log(2.5); notes.append("no life certificate in annual wave")
        stats["dlc_miss"] += 1
    elif not ddate:
        lo += math.log(0.55)

    blast = agg["bank_last"].get(p["_acct"])
    bank_after = bool(ddate and blast and blast > ddate)
    tl = agg["tele_last"].get(p["_mob"])
    tele_after = bool(ddate and tl and tl > ddate)
    if ddate:
        if exact_death or strip_months >= 1:
            if bank_after: lo += math.log(1.4); notes.append("bank account used after registered death (family reuse)")
            if tele_after: lo += math.log(1.3); notes.append("SIM used after registered death (family reuse)")
        else:
            if bank_after and tele_after: lo += math.log(0.6); notes.append("bank+SIM active after fuzzy death date (match doubtful)")
            elif bank_after: lo += math.log(0.85); notes.append("bank active after fuzzy death date")
            elif tele_after: lo += math.log(0.9); notes.append("SIM active after fuzzy death date")
        dm = agg["disb_months"].get(pid, set())
        dkey = ddate.year * 100 + ddate.month
        if any(k > dkey for k in dm):
            if exact_death: lo += math.log(1.6); notes.append("pension credited after registered death month (leakage)")
            else: lo += math.log(1.15); notes.append("pension credited after death/cessation month")
        pfd = agg["pan_filed"].get(p["_pan"])
        if pfd and ddate < pfd <= SNAP:
            lo += math.log(0.8); notes.append("PAN filing after death/cessation date")
    else:
        if quiet_days is not None and quiet_days <= 14: lo += math.log(0.4)
        pfd = agg["pan_filed"].get(p["_pan"])
        if pfd and (SNAP - pfd).days <= 730: lo += math.log(0.6)
        if ci is not None:
            cpaid = cons[ci][3]
            if cpaid and (SNAP - cpaid).days <= 62:
                lo += math.log(0.75); notes.append("utility bill paid recently at same address")

    # --- v3 alive/reuse signals ---
    def post_or_recent(d, days):
        if not d: return False
        if ddate: return ddate < d <= SNAP
        return 0 <= (SNAP - d).days <= days
    kyc_d = agg["kyc_refresh"].get(p["_acct"])
    if post_or_recent(kyc_d, 60):
        lo += math.log(0.2); notes.append("in-person KYC refresh (alive)"); stats["alive_kyc"] += 1
    aad_d = agg["aadhaar_upd"].get(p["_aad"])
    if post_or_recent(aad_d, 60):
        lo += math.log(0.25); notes.append("Aadhaar detail update (alive)"); stats["alive_aad"] += 1
    epfo_m = agg["epfo_contrib"].get(p["_aad"])
    if epfo_m and mrecent(epfo_m, 1) and (not ddate or epfo_m[:7] > ddate.isoformat()[:7]):
        lo += math.log(0.3); notes.append("EPFO contribution in last 6 months (alive)"); stats["alive_epfo"] += 1
    mgr_conf = float(m.get("mgnrega_work_conf") or 0)
    mgr_ev = (m.get("mgnrega_work_ev") or "").split("|")
    mgr_d = pdte(mgr_ev[1]) if len(mgr_ev) > 1 and mgr_ev[1] else None
    mgr_m = mgr_ev[0] if mgr_ev else ""
    mgr_alive = bool(mgr_m and mrecent(mgr_m, 1))
    if ddate:
        mgr_alive = bool(mgr_m and mgr_m[:7] > ddate.isoformat()[:7] and mrecent(mgr_m, 12))
    if mgr_conf >= 0.85 and mgr_alive:
        lo += math.log(0.3); notes.append("MGNREGA work month after cessation or recent (alive)"); stats["alive_mgnrega"] += 1
    nps_conf = float(m.get("nps_accounts_conf") or 0)
    nps_m = (m.get("nps_accounts_ev") or "").split("|")[0]
    if nps_conf >= 0.85 and mrecent(nps_m, 1) and (not ddate or nps_m[:7] > ddate.isoformat()[:7]):
        lo += math.log(0.4); notes.append("NPS contribution in last 6 months (alive)"); stats["alive_nps"] += 1
    lic_conf = float(m.get("lic_insurance_conf") or 0)
    lic_d = evd(m.get("lic_insurance_ev"))
    if lic_conf >= 0.85 and lic_d:
        if exact_death and ddate and lic_d > ddate:
            lo += math.log(1.2); notes.append("LIC premium after registered death (family keeping policy)"); stats["reuse_lic"] += 1
        elif post_or_recent(lic_d, 90):
            lo += math.log(0.7); notes.append("LIC premium paid recently"); stats["alive_lic"] += 1
    pp_conf = float(m.get("passport_registry_conf") or 0)
    pp_d = evd(m.get("passport_registry_ev"))
    if pp_conf >= 0.9 and pp_d and post_or_recent(pp_d, 60):
        lo += math.log(0.3); notes.append("passport issued recently (in-person alive)"); stats["alive_passport"] += 1
    dl_conf = float(m.get("driving_licence_conf") or 0)
    dl_d = evd(m.get("driving_licence_ev"))
    if dl_conf >= 0.9 and dl_d and post_or_recent(dl_d, 60):
        lo += math.log(0.35); notes.append("driving licence issued/renewed recently (alive)"); stats["alive_dl"] += 1
    veh_d = agg["veh_reg"].get(p["_aad"])
    if veh_d:
        if exact_death and ddate and veh_d > ddate:
            lo += math.log(1.2); notes.append("vehicle registered after registered death (family reuse)"); stats["reuse_vehicle"] += 1
        elif post_or_recent(veh_d, 60):
            lo += math.log(0.5); notes.append("vehicle registration recent"); stats["alive_vehicle"] += 1
    toll_d = agg["toll_last"].get(p["_aad"])
    if toll_d and ddate and toll_d > ddate:
        lo += math.log(1.2); notes.append("FASTag toll after death date (family keeping tag)"); stats["reuse_toll"] += 1
    hh_alive = False
    rat_m = agg["ration_months"].get(p["_aad"])
    if rat_m and mrecent(rat_m, 3): hh_alive = True
    lpg_conf = float(m.get("lpg_refills_conf") or 0)
    lpg_d = evd(m.get("lpg_refills_ev"))
    if lpg_conf >= 0.85 and lpg_d and (SNAP - lpg_d).days <= 92: hh_alive = True
    if hh_alive:
        lo += math.log(0.85); notes.append("household ration/LPG activity recent (weak alive)"); stats["alive_household"] += 1
    mun_paid = pdte(mun_ev[1]) if len(mun_ev) > 1 and mun_ev[1] else None
    if mun_conf >= 0.85 and mun_paid and 0 <= (SNAP - mun_paid).days <= 120:
        lo += math.log(0.85); notes.append("municipal tax paid recently (household, weak alive)"); stats["alive_municipal"] += 1
    # DORMANT bank KYC status: explicitly ignored (dormancy is not death evidence)

    # joint-dark: credits flow while every life signal stays dark
    credit = agg["last_credit"].get(pid)
    still_paid = credit is not None and (SNAP - credit).days <= 92
    util_recent_paid = ci is not None and cons[ci][3] and (SNAP - cons[ci][3]).days <= 92
    dark_credit_months = sum(1 for ym in cd_all if ym not in tx_all or not tx_all.get(ym))
    if (still_paid and dlc_missing and (quiet_days is None or quiet_days >= 60) and not util_recent_paid):
        jlr = min(6.0 ** max(1, dark_credit_months), 60.0)
        lo += math.log(jlr); notes.append(f"pension credits continue while all life signals dark ({dark_credit_months} uncredited-touch months)"); stats["joint_dark"] += 1

    if os.environ.get("FEATURES_OUT"):
        fr = {"pensioner_id":pid, "log_odds":lo, "quiet_days": quiet_days if quiet_days is not None else -1,
              "bank_quiet": (SNAP-last_bank_self).days if last_bank_self else -1,
              "tele_quiet": (SNAP-tl_any).days if tl_any else -1,
              "bank_months":len(bm), "tele_months":len(tm), "bank_chronic":int(bank_chronic),
              "tele_chronic":int(tele_chronic), "established":int(established), "strip_months":strip_months,
              "dark_months":dark_credit_months, "dlc_missing":int(dlc_missing),
              "dlc_age":(SNAP-lc_d).days if lc_d else -1,
              "utility_paid_age":(SNAP-cpaid0).days if cpaid0 else -1,
              "utility_months":len(agg["util_m"].get(cons[ci][0],{})) if ci is not None else 0,
              "documentary_count":len(doc_grades), "exact_death":int(exact_death),
              "strong_docs":sum(g=="strong" for g in doc_grades), "weak_docs":sum(g=="weak" for g in doc_grades),
              "death_age":(SNAP-ddate).days if ddate else -1,
              "hh_active":int(hh_alive), "still_paid":int(still_paid),
              "bank_after":int(bank_after), "tele_after":int(tele_after),
              "bS":bS, "bO":bO, "tS":tS, "tO":tO,
              "r1":r1 if r1 is not None else -1, "r2":r2 if r2 is not None else -1,
              "r3":r3 if r3 is not None else -1,
              "kyc_age":(SNAP-kyc_d).days if kyc_d else -1,
              "aad_age":(SNAP-aad_d).days if aad_d else -1,
              "lic_age":(SNAP-lic_d).days if lic_d else -1,
              "pan_age":(SNAP-pf0).days if pf0 else -1,
              "mgr_conf":mgr_conf, "mgr_alive":int(mgr_alive), "mun_conf":mun_conf,
              "mun_mut_age":(SNAP-mun_mut).days if mun_mut else -1,
              "lpg_conf":lpg_conf, "nps_conf":nps_conf,
              "epfo_recent":int(bool(epfo_m and mrecent(epfo_m,1))),
              "nps_recent":int(bool(nps_m and mrecent(nps_m,1)))}
        fr['last_credit_age']=(SNAP-credit).days if credit else -1
        fr['payment_status_stopped']=int((p.get('pension_status') or '').upper()=='STOPPED')
        for label in ['death','hosp','pmjay','eroll']:
            fr[label+'_conf']=float(m.get(label+'_conf') or 0)
            dd=evd(m.get(label+'_ev'))
            fr[label+'_age']=(SNAP-dd).days if dd else -1
            fr[label+'_bank_after']=int(bool(dd and last_bank_self and last_bank_self>dd))
            fr[label+'_tele_after']=int(bool(dd and tl_any and tl_any>dd))
        fr['doc_date_span']=(max(d for d,g in death_dates)-min(d for d,g in death_dates)).days if len(death_dates)>1 else 0
        personal_dates=[d for d in [last_bank_self,tl_any,kyc_d,aad_d,pp_d,dl_d] if d and d<=SNAP]
        fr['personal_latest_age']=(SNAP-max(personal_dates)).days if personal_dates else -1
        fr['personal_sources_present']=sum(d is not None for d in [last_bank_self,tl_any,kyc_d,aad_d,pp_d,dl_d])
        fr['bank_tele_gap']=abs((last_bank_self-tl_any).days) if last_bank_self and tl_any else -1
        fr['bank_active_months']=sum(v>0 for v in bm.values())
        fr['tele_active_months']=sum(v>0 for v in tm.values())
        fr['unpaid_utility_months']=sum(not paid for units,paid in agg['util_m'].get(cons[ci][0],{}).values()) if ci is not None else 0
        fr['paid_utility_months']=sum(bool(paid) for units,paid in agg['util_m'].get(cons[ci][0],{}).values()) if ci is not None else 0
        for label,d in [('kyc',kyc_d),('aadhaar',aad_d),('passport',pp_d),('licence',dl_d)]:
            fr[label+'_post_doc']=int(bool(d and death_dates and d>max(x for x,g in death_dates)))
        for days in [7,14,30,60,90,180]:
            fr[f'bank_self_count_{days}']=sum(0 <= (SNAP-d).days <= days for d in self_dates)
            fr[f'bank_strip_count_{days}']=sum(0 <= (SNAP-d).days <= days for d in strip_dates)
        fr['bank_self_dates']=len(set(self_dates))
        fr['bank_self_span']=(max(self_dates)-min(self_dates)).days if self_dates else 0
        if self_dates:
            counts={}
            for d in self_dates:counts[(d.year,d.month)]=counts.get((d.year,d.month),0)+1
            fr['bank_mean_self_month']=len(self_dates)/max(len(counts),1)
            fr['bank_max_self_month']=max(counts.values())
        else:fr['bank_mean_self_month']=fr['bank_max_self_month']=0
        fr['tele_peak_month']=max(tm.values()) if tm else 0
        fr['tele_mean_month']=sum(tm.values())/max(len(tm),1)
        fr['personal_recent7']=sum(d is not None and 0<=(SNAP-d).days<=7 for d in [last_bank_self,tl_any,kyc_d,aad_d,pp_d,dl_d])
        fr['personal_recent30']=sum(d is not None and 0<=(SNAP-d).days<=30 for d in [last_bank_self,tl_any,kyc_d,aad_d,pp_d,dl_d])
        um=agg['util_m'].get(cons[ci][0],{}) if ci is not None else {}
        monthkeys=sorted(k for k in set(bm)|set(tm)|set(um) if k<=M3)
        utility_paid_dates=[paid for units,paid in um.values() if paid and paid<=SNAP]
        fr['utility_last_payment_age']=(SNAP-max(utility_paid_dates)).days if utility_paid_dates else -1
        fr['utility_latest_units']=um[max(um)][0] if um else -1
        fr['utility_peak_units']=max(units for units,paid in um.values()) if um else -1
        fr['utility_drop_ratio']=fr['utility_latest_units']/max(fr['utility_peak_units'],1) if um else -1
        bk=sorted(bm);tk=sorted(tm)
        fr['bank_before_cessation_months']=sum((k//100,k%100)<(last_bank_self.year,last_bank_self.month) for k in bk) if last_bank_self else 0
        fr['tele_before_cessation_months']=sum((k//100,k%100)<(tl_any.year,tl_any.month) for k in tk) if tl_any else 0
        for days in [14,30,45,60,90]:
            bs=last_bank_self is not None and (SNAP-last_bank_self).days>=days
            ts=tl_any is not None and (SNAP-tl_any).days>=days
            us=bool(utility_paid_dates and (SNAP-max(utility_paid_dates)).days>=days)
            fr[f'cessation_sources_{days}']=int(bs)+int(ts)+int(us)
            fr[f'bank_tele_joint_{days}']=int(bs and ts)
            fr[f'bank_tele_utility_joint_{days}']=int(bs and ts and us)
        fr['bank_tele_aligned7']=int(bool(last_bank_self and tl_any and abs((last_bank_self-tl_any).days)<=7))
        fr['bank_tele_aligned3']=int(bool(last_bank_self and tl_any and abs((last_bank_self-tl_any).days)<=3))
        fr['strip_to_self_ratio']=len(strip_dates)/max(1,len(self_dates))
        fr['registry_without_personal_conflict']=int(bool(exact_death and not any(d>min(x for x,g in death_dates) for d in [kyc_d,aad_d,pp_d,dl_d,lc_d] if d)))
        all_bank_dates=[d for txns in tx_all.values() for d,a in txns if d<=SNAP]
        fr['bank_any_quiet']=(SNAP-max(all_bank_dates)).days if all_bank_dates else -1
        fr['bank_any_dates']=len(set(all_bank_dates))
        fr['bank_strip_only']=int(bool(strip_dates and not self_dates))
        fr['bank_strip_fraction']=len(strip_dates)/max(1,len(all_bank_dates))
        fr['bank_to_tele_gap_any']=abs((max(all_bank_dates)-tl_any).days) if all_bank_dates and tl_any else -1
        for days in [7,14,30,60,90]:
            fr[f'bank_any_count_{days}']=sum(0<=(SNAP-d).days<=days for d in all_bank_dates)
        for threshold in [1,5,15,50,100]:
            active=[ym for ym,volume in tm.items() if volume>=threshold and ym<=M3]
            fr[f'tele_active_months_above_{threshold}']=len(active)
            fr[f'tele_latest_active_month_{threshold}']=((SNAP.year-active[-1]//100)*12+SNAP.month-active[-1]%100) if active else -1
        fr['recent_personal_conflicts']=sum(d is not None and 0<=(SNAP-d).days<=30 for d in [kyc_d,aad_d,pp_d,dl_d,lc_d])
        for label,series in [('bank',bm),('tele',tm)]:
            history=[]
            for j in range(1,7):
                key=SNAP.year*12+SNAP.month-1-j;ym=(key//12)*100+key%12+1
                history.append(float(series.get(ym,0)))
            baseline=sorted(history[2:])[len(history[2:])//2]
            fr[label+'_personal_baseline']=baseline
            fr[label+'_recent_ratio']=sum(history[:2])/max(1.,2*baseline)
            fr[label+'_prior_active_fraction']=sum(x>0 for x in history[2:])/4
            fr[label+'_joint_drop90']=int(baseline>0 and max(history[:2])<=.2*baseline)
            mean=sum(history[2:])/4
            fr[label+'_baseline_variation']=sum((x-mean)**2 for x in history[2:])/max(1.,4*mean*mean)
        address=' '.join((p.get('address') or '').casefold().split())
        members=household_members.get((p.get('district',''),address),[]) if address else []
        fr['household_master_members']=len(members)
        other_active=0
        for member in members:
            if member['pensioner_id']==pid:continue
            b=agg['bank_last'].get(member['_acct']);t=agg['tele_last'].get(member['_mob'])
            other_active+=int(any(d and 0<=(SNAP-d).days<=30 for d in [b,t]))
        fr['household_other_persons_active']=other_active
        fr['household_continues_person_stopped']=int(other_active>0 and quiet_days is not None and quiet_days>=30)
        lags=sorted(lag_by_district.get(p.get('district',''),[]))
        fr['district_registry_lag_median']=lags[len(lags)//2] if lags else -1
        fr['district_registry_lag_p90']=lags[min(len(lags)-1,int(.9*len(lags)))] if lags else -1
        fr['lag_observation_count']=len(lags)
        fr['cessation_inside_lag_window']=int(bool(lags and quiet_days is not None and 0<=quiet_days<=lags[min(len(lags)-1,int(.9*len(lags)))]))
        # Silence surprise is relative to each person's own observed frequency.
        # Capped evidence avoids treating correlated sources as independent proof.
        history_start=date(SNAP.year, max(1,SNAP.month-5),1)
        for window in [14,30,45,60]:
            prior=[d for d in self_dates if window < (SNAP-d).days <= 180]
            exposure=max(1,180-window)
            rate=len(prior)/exposure
            recent=sum(0<=(SNAP-d).days<=window for d in self_dates)
            fr[f'bank_silence_surprise_{window}']=min(20.,rate*window) if recent==0 else 0.
            fr[f'bank_relative_rate_{window}']=(recent/window)/max(rate,.001)
        fr['joint_personal_baseline_drop']=fr['bank_joint_drop90']*fr['tele_joint_drop90']
        fr['aligned_joint_baseline_drop']=fr['joint_personal_baseline_drop']*fr['bank_tele_aligned7']
        for j in range(7):
            ky=(SNAP.year*12+SNAP.month-1)-j; ym=(ky//12)*100+(ky%12+1)
            fr[f"bank_n_{j}"]=bm.get(ym,0);fr[f"tele_n_{j}"]=tm.get(ym,0)
        if feature_writer is None:
            feature_writer=csv.DictWriter(feature_file,fieldnames=list(fr));feature_writer.writeheader()
        feature_writer.writerow(fr)
    if pid in DBG:
        print("DBG", pid, "lo", round(lo,3), "notes:", notes, "quiet_days", quiet_days, "established", established)
    prob = sig(lo)
    has_cessation = bank_stop is not None
    joint_dark = any("life signals dark" in n for n in notes)
    if not doc_grades and not has_cessation:
        cap = (0.8 if strip_months >= 2 else 0.65) if joint_dark else 0.45
        if prob > cap:
            prob = cap; notes.append(f"capped at {cap}: " + ("joint dark with credits" if joint_dark else "silence alone cannot convict"))
            if not joint_dark: stats["cap_chronic"] += 1
    elif doc_grades and all(g == "weak" for g in doc_grades):
        aligned_to_weak = has_cessation and bank_stop and any(
            abs((bank_stop.year*12 + bank_stop.month) - (d.year*12 + d.month)) <= 1
            for d, g in death_dates if g == "weak")
        cap = 0.70 if aligned_to_weak else 0.55
        if prob > cap:
            prob = cap; notes.append(f"capped at {cap}: weak documentary lead only"); stats["cap_weak"] += 1
    if not still_paid: stats["gate"] += 1
    score = prob if still_paid else round(prob * 0.05, 6)
    rows_out.append((pid, round(score, 6), prob, still_paid, "; ".join(notes)))

rows_out.sort(key=lambda r: -r[1])
with open(D + "flagged_pensioners.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["pensioner_id", "score"])
    for pid, s, _, _, _ in rows_out: w.writerow([pid, s])
with open(D + "reasoning.txt", "w") as f:
    for pid, s, prob, sp, notes in rows_out[:120]:
        f.write(f"{pid} score={s} p_deceased={prob:.3f} still_paid={sp} :: {notes}\n")
print(stats)
for t in (0.9, 0.7, 0.5, 0.45, 0.2):
    print(f"score>={t}:", sum(1 for r in rows_out if r[1] >= t))
band = [r for r in rows_out if r[1] >= 0.5]
nd = sum(1 for r in band if "registry" not in r[4] and "hospital" not in r[4] and "electoral" not in r[4] and "PM-JAY" not in r[4])
print(">=0.5 without documentary evidence:", nd)

if feature_file: feature_file.close()
