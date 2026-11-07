# v3 matcher v2: bucketed blocking.
#   dob feeds: (token, dob-year +-1) and (token, month, day) buckets (+soundex) - covers
#              every dob_pts>0 case (exact, year+month, day/month swap, year+-1, 1-digit year edit).
#   no-dob feeds: rarest-token intersection blocking with soundex cross terms.
# Usage: MATCH_FEEDS=a,b MATCH_OUT=out.csv python3 matchV4.py DIR
import csv, sys, pickle, difflib, time, os, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from pim import matching
D = sys.argv[1] if len(sys.argv) > 1 else "/tmp/round3/"
if not D.endswith("/"): D += "/"
agg = pickle.load(open(D + "aggV3.pkl", "rb"))
pm = agg["pm"]

def pdate(s):
    s = (s or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try: return int(s[:4]), int(s[5:7]), int(s[8:10])
        except ValueError: return None
    return None

def dob_pts(a, b):
    if not a or not b: return 0.0
    if a == b: return 1.0
    ya, ma, da = a; yb, mb, db = b
    if ya == yb and ma == mb: return 0.85
    if ya == yb and da == mb and ma == db: return 0.85
    if ma == mb and da == db and abs(ya - yb) <= 1: return 0.75
    sa, sb = str(ya), str(yb)
    if ma == mb and da == db and sum(1 for x, y in zip(sa, sb) if x != y) == 1: return 0.6
    if ya == yb: return 0.5
    return 0.0

def prep(rows_, namefield, dobfield="dob", addrfield=None):
    out = []
    for i, r in enumerate(rows_):
        toks = frozenset(matching.normalize_name(r.get(namefield) or "").split())
        sx = frozenset(matching.soundex(t) for t in toks if len(t) >= 4)
        pd = pdate(r.get(dobfield)) if dobfield else None
        ra = " ".join((r.get(addrfield) or "").lower().split()) if addrfield else ""
        out.append((i, r, toks, sx, (r.get("gender") or "").strip().lower()[:1], pd, ra))
    return out

def build_index(prepped, dob_mode):
    idx = {}
    for i, r, toks, sx, g, pd, _ra in prepped:
        for t in toks: idx.setdefault(("t", t), []).append(i)
        for s in sx: idx.setdefault(("s", s), []).append(i)
        if dob_mode and pd:
            y, mth, dy = pd
            for t in toks:
                idx.setdefault(("y", t, y), []).append(i)
                idx.setdefault(("md", t, mth, dy), []).append(i)
                if dy <= 12 and dy != mth:
                    idx.setdefault(("md", t, dy, mth), []).append(i)
            for s in sx:
                idx.setdefault(("xy", s, y), []).append(i)
                idx.setdefault(("xmd", s, mth, dy), []).append(i)
                if dy <= 12 and dy != mth:
                    idx.setdefault(("xmd", s, dy, mth), []).append(i)
    idx = {k: frozenset(v) for k, v in idx.items()}
    return idx

def scan(PP, prepped, idx, namefield, addrfield=None, need_dob=True, distfield=None):
    full_name, ptoks, psx, pg, pdob, paddr, tl, sl, pdist, pfirst = PP
    def bucket(kind, key, *rest):
        return idx.get((kind, key) + rest, frozenset())
    cand = set()
    if len(tl) >= 2:
        t0, t1 = tl[0], tl[1]
        s0 = sl[0] if sl else None
        s1 = sl[1] if len(sl) > 1 else None
        if need_dob and pdob:
            py, pmth, pdy = pdob
            for kind, key in (("y", py), ("md", (pmth, pdy))):
                if kind == "y":
                    A = lambda k: bucket("y", k, key); Ax = lambda k: bucket("xy", k, key)
                else:
                    A = lambda k: bucket("md", k, *key); Ax = lambda k: bucket("xmd", k, *key)
                cand |= A(t0) & A(t1)
                if s0:
                    cand |= Ax(s0) & A(t0)
                    cand |= Ax(s0) & A(t1)
                    if s1: cand |= Ax(s0) & Ax(s1)
        else:
            cand = set(bucket("t", t0) & bucket("t", t1))
            if s0 and len(bucket("t", t0)) <= 800 and len(bucket("t", t1)) <= 800:
                cand |= bucket("s", s0) & bucket("t", t0)
                cand |= bucket("s", s0) & bucket("t", t1)
                if s1: cand |= bucket("s", s0) & bucket("s", s1)
    elif tl:
        if need_dob and pdob:
            py, pmth, pdy = pdob
            cand = bucket("y", tl[0], py) | bucket("md", tl[0], pmth, pdy)
            for s in sl: cand |= bucket("xy", s, py) | bucket("xmd", s, pmth, pdy)
        else:
            cand = bucket("t", tl[0])
            for s in sl: cand |= bucket("s", s)
    # cheap pre-rank; expensive name_match_pct only for the top few
    scored = []
    for i in cand:
        _, r, toks, sx, g, rdob, ra = prepped[i]
        if need_dob and g and pg and g != pg: continue
        if distfield and pdist and (r.get(distfield) or "").strip() != pdist: continue
        ts = len(ptoks & toks); ss = len(psx & sx)
        if ts == 0 and ss == 0: continue
        dp = dob_pts(pdob, rdob) if need_dob else 0.0
        if need_dob and dp == 0.0: continue
        if not need_dob and addrfield and pfirst != (ra.split(" ", 1)[0] if ra else ""):
            continue
        token_sim = max(ts / max(len(ptoks), len(toks)),
                        0.8 * ss / max(len(psx), len(sx)) if ss else 0.0)
        cheap = (0.62 * token_sim + 0.38 * dp) if need_dob else token_sim
        scored.append((cheap, i, dp))
    scored.sort(key=lambda x: (-x[0],x[1]))
    best, best_r = 0.0, None
    options=[]
    rank_cut=scored[min(3,len(scored)-1)][0] if scored else 0
    for cheap, i, dp in scored:
        if cheap < rank_cut: break
        _, r, toks, sx, g, rdob, ra = prepped[i]
        nm = matching.name_match_pct(full_name, r.get(namefield) or "")
        if need_dob:
            if nm < 0.55: continue
            s = 0.62 * nm + 0.38 * dp
        else:
            if nm < 0.85: continue
            s = nm
        if distfield and pdist and (r.get(distfield) or "").strip() != pdist:
            continue
        if addrfield:
            ar = difflib.SequenceMatcher(None, paddr, ra).ratio()
            s = round(0.8 * s + 0.2 * ar, 4)
            if not need_dob:
                rfirst = ra.split(" ", 1)[0] if ra else ""
                if ar < 0.6 or (pfirst and rfirst and pfirst != rfirst): continue
        options.append((round(s,4),i,r))
        if s > best: best, best_r = round(s, 4), r
    options.sort(key=lambda x:(-x[0],x[1]))
    return best, best_r, options

for _i, _h in enumerate(agg["hosp_dead"]): _h["_hid"] = str(_i)
for _i, _h in enumerate(agg["pmjay_dead"]): _h["_hid"] = str(_i)
EVID = {"death": ("date_of_death",), "hosp": ("discharge_date", "admit_date"),
        "pmjay": ("discharge_date", "admission_date"), "eroll": ("deletion_date",)}
NF_EVID = {"lic_insurance": ("last_premium_date",), "nps_accounts": ("last_contribution_month",),
           "passport_registry": ("issue_date",), "driving_licence": ("issue_date",),
           "vehicle_rc": ("registration_date", "fitness_upto"),
           "municipal_property": ("mutation_date", "last_paid_date"),
           "mgnrega_work": ("month", "payment_date"), "lpg_refills": ("delivery_date", "booking_date")}
ADDR = {"eroll": "address", "municipal_property": "address", "lpg_refills": "address"}
DIST = {"death": "district", "hosp": "district", "pmjay": "district", "eroll": "district", "mgnrega_work": "district", "lic_insurance": None, "nps_accounts": None}
IDCOL = {"death": "registration_no", "hosp": "_hid", "pmjay": "_hid", "eroll": "epic_number"}
sets = {}
_requested = set(os.environ.get("MATCH_FEEDS", "").split(",")) - {""}
for key, rows_, nf, df, need in [
    ("death", agg["deaths"], "deceased_name", "dob", True),
    ("hosp", agg["hosp_dead"], "patient_name", "dob", True),
    ("pmjay", agg["pmjay_dead"], "patient_name", "dob", True),
    ("eroll", agg["eroll_del"], "name", "dob", True)]:
    if rows_ and (not _requested or key in _requested):
        pr = prep(rows_, nf, df if df else None, addrfield="address" if key == "eroll" else None)
        sets[key] = (pr, build_index(pr, need and bool(df)), nf, need)

def load_rows(fn):
    p = D + fn
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []
for fn, csvfn, namecol, dobc in [
    ("lic_insurance", "lic_insurance.csv", "name", "dob"),
    ("nps_accounts", "nps_accounts.csv", "name", "dob"),
    ("passport_registry", "passport_registry.csv", "name", "dob"),
    ("driving_licence", "driving_licence.csv", "name", "dob"),
    ("municipal_property", "municipal_property.csv", "owner_name", None),
    ("mgnrega_work", "mgnrega_work.csv", "name", None),
    ("lpg_refills", "lpg_refills.csv", "consumer_name", None),
]:
    if _requested and fn not in _requested: continue
    rs = load_rows(csvfn)
    if not rs: continue
    # Repeated monthly feeds: retain the latest observation per source identity.
    # Do not let file order turn an old work month into the current evidence.
    if fn in ("mgnrega_work", "lpg_refills"):
        idfield = "job_card_no" if fn == "mgnrega_work" else "consumer_id"
        datefield = "month" if fn == "mgnrega_work" else "delivery_date"
        latest = {}
        for r in rs:
            key = (r.get(idfield) or "", r.get(namecol) or "", r.get("district") or "", r.get("address") or "")
            if key not in latest or (r.get(datefield) or "") > (latest[key].get(datefield) or ""):
                latest[key] = r
        rs = list(latest.values())
    pr = prep(rs, namecol, dobc if dobc else None, addrfield=ADDR.get(fn))
    sets[fn] = (pr, build_index(pr, bool(dobc)), namecol, bool(dobc))

KEYS = list(sets)
_only = os.environ.get("MATCH_FEEDS")
if _only: KEYS = [k for k in KEYS if k in _only.split(",")]
hdr = ["pensioner_id"]
for k in KEYS: hdr += [f"{k}_conf", f"{k}_ev", f"{k}_id", f"{k}_candidates"]

gdf_t, gdf_s = {}, {}
for k in KEYS:
    for kk, lst in sets[k][1].items():
        if kk[0] == "t": gdf_t[kk[1]] = gdf_t.get(kk[1], 0) + len(lst)
        elif kk[0] == "s": gdf_s[kk[1]] = gdf_s.get(kk[1], 0) + len(lst)

t0 = time.time()
with open(D + os.environ.get("MATCH_OUT", "matches_v3.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(hdr)
    _skip = int(os.environ.get("PM_SKIP", "0"))
    for p in pm[_skip:]:
        paddr_full = " ".join((p["address"] or "").lower().split())
        ptoks = frozenset(matching.normalize_name(p["full_name"]).split())
        psx = frozenset(matching.soundex(t) for t in ptoks if len(t) >= 4)
        PP = (p["full_name"], ptoks, psx,
              (p["gender"] or "").strip().lower()[:1], pdate(p["dob"]),
              paddr_full,
              sorted(ptoks, key=lambda t: gdf_t.get(t, 0)),
              sorted(psx, key=lambda s: gdf_s.get(s, 0)),
              (p["district"] or "").strip(),
              paddr_full.split(" ", 1)[0])
        row = [p["pensioner_id"]]
        for k in KEYS:
            pr, idx, nf, need = sets[k]
            conf, br, opts = scan(PP, pr, idx, nf, addrfield=ADDR.get(k), need_dob=need, distfield=DIST.get(k))
            ev = ""
            if br:
                cols = EVID.get(k) or NF_EVID.get(k, ())
                ev = "|".join((br.get(c) or "").strip() for c in cols).rstrip("|")
            rid = (br.get(IDCOL[k]) or "").strip() if (br and k in IDCOL) else ""
            alternatives=[]
            if k in IDCOL:
                for cs,seq,cr in opts:
                    alternatives.append({'confidence':cs,'source_sequence':seq,'record_id':str(cr.get(IDCOL[k]) or ''),'evidence':'|'.join((cr.get(c) or '').strip() for c in EVID.get(k,())).rstrip('|')})
            row += [conf or "", ev, rid, json.dumps(alternatives,separators=(',',':'))]
        w.writerow(row)
print(f"matched {len(pm)} pensioners x {len(KEYS)} feeds in {time.time()-t0:.1f}s")
