# v3 generic aggregation: every feed optional; join-key aggregation; name-linked feeds
# are NOT loaded here (matchV3 reads those CSVs directly).
# Usage: python3 aggV3.py DIR [core|activity|all]
#   core     -> DIR/aggV3.pkl   (pensioners, documentary rows, kyc, disb, dlc, pan, gst,
#                                aadhaar, epfo, ration, vehicle, toll, utility)
#   activity -> DIR/aggV3b.pkl  (bank tx series, telecom series) - the memory-heavy part
#   all      -> both in aggV3.pkl (small datasets)
import csv, sys, os, resource
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from detector.aggregate_store import dump
from datetime import date
D = sys.argv[1] if len(sys.argv) > 1 else "/tmp/round3/"
if not D.endswith("/"): D += "/"
PART = sys.argv[2] if len(sys.argv) > 2 else "all"

def pdte(s):
    s = (s or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try: return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
        except ValueError: return None
    return None

def rows(fn):
    p = D + fn
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []

def stream(fn):
    p = D + fn
    return csv.DictReader(open(p)) if os.path.exists(p) else iter(())

def mx(dic, key, d):
    if d and (key not in dic or d > dic[key]): dic[key] = d

out = {}

if PART in ("core", "all"):
    pm = rows("pension_master.csv")
    out["pm"] = pm
    out["deaths"] = rows("death_registry.csv")
    out["hosp_dead"] = [r for r in rows("hospital_records.csv") if (r.get("outcome") or "").strip().upper() == "DIED"]
    out["pmjay_dead"] = [r for r in rows("pmjay_claims.csv") if (r.get("outcome") or "").strip().upper() == "DIED"]
    out["eroll_del"] = [r for r in rows("electoral_roll.csv") if (r.get("status") or "").strip().upper() == "DELETED"]

    # --- bank KYC (DORMANT is NOT death evidence; refresh = in-person alive) ---
    kyc_status, kyc_refresh = {}, {}
    for r in rows("bank_kyc.csv"):
        kyc_status[r["account_number"]] = (r.get("account_status") or "").strip().upper()
        mx(kyc_refresh, r["account_number"], pdte(r.get("last_kyc_refresh")))
    out["kyc_status"] = kyc_status; out["kyc_refresh"] = kyc_refresh

    # --- disbursements / DLC / PAN (by pensioner_id / pan) ---
    disb_months, last_credit, disb_cd = {}, {}, {}
    for r in stream("pension_disbursements.csv"):
        pid = r["pensioner_id"]; m = (r.get("month") or "").strip()
        if len(m) >= 7:
            disb_months.setdefault(pid, set()).add(int(m[:4]) * 100 + int(m[5:7]))
        d = pdte(r.get("credit_date"))
        if d:
            mx(last_credit, pid, d)
            if len(m) >= 7: disb_cd.setdefault(pid, {})[int(m[:4]) * 100 + int(m[5:7])] = d
    out["disb_months"] = disb_months; out["last_credit"] = last_credit; out["disb_cd"] = disb_cd

    dlc = {}
    for r in stream("life_certificates.csv"):
        if (r.get("status") or "").strip().upper() == "VERIFIED":
            mx(dlc, r["pensioner_id"], pdte(r.get("submission_date")))
    out["dlc"] = dlc

    pan_filed = {}
    for r in stream("tax_pan_activity.csv"):
        if (r.get("itr_filed") or "").strip().upper() in ("Y", "YES", "1", "TRUE"):
            mx(pan_filed, r["pan"], pdte(r.get("filing_date")))
    out["pan_filed"] = pan_filed

    gst_active = {}
    for r in rows("gst_registrations.csv"):
        if (r.get("status") or "").strip().upper() == "ACTIVE":
            gst_active[r["pan"]] = (r.get("registration_date") or "").strip()
    out["gst_active"] = gst_active

    # --- aadhaar-keyed alive signals ---
    aadhaar_upd, epfo_contrib, ration_months = {}, {}, {}
    for r in rows("aadhaar_registry.csv"):
        mx(aadhaar_upd, (r.get("aadhaar_number") or "").strip(), pdte(r.get("last_update_date")))
    for r in rows("epfo_uan.csv"):
        m = (r.get("last_contribution_month") or "").strip()
        if len(m) >= 7:
            epfo_contrib[(r.get("aadhaar_number") or "").strip()] = m[:7]
    for r in stream("ration_pds.csv"):
        a = (r.get("member_aadhaar") or "").strip(); m = (r.get("month") or "").strip()
        if a and len(m) >= 7:
            cur = ration_months.get(a)
            if cur is None or m[:7] > cur: ration_months[a] = m[:7]
    out["aadhaar_upd"] = aadhaar_upd; out["epfo_contrib"] = epfo_contrib; out["ration_months"] = ration_months

    # --- vehicle RC by owner aadhaar + toll via plate ---
    veh_reg, veh_fit, plate_aad = {}, {}, {}
    for r in rows("vehicle_rc.csv"):
        a = (r.get("owner_aadhaar") or "").strip()
        if not a: continue
        mx(veh_reg, a, pdte(r.get("registration_date")))
        mx(veh_fit, a, pdte(r.get("fitness_upto")))
        pl = (r.get("registration_no") or "").strip()
        if pl: plate_aad[pl] = a
    toll_last = {}
    for r in stream("toll_fastag.csv"):
        a = plate_aad.get((r.get("vehicle_plate") or "").strip())
        if a: mx(toll_last, a, pdte(r.get("txn_timestamp")))
    out["veh_reg"] = veh_reg; out["veh_fit"] = veh_fit; out["toll_last"] = toll_last

    # --- utility (household): name+address matching as before ---
    cons_full, util_m, seen = [], {}, {}
    for r in stream("utility_bills.csv"):
        cid = r["consumer_id"]
        if cid not in seen:
            seen[cid] = len(cons_full)
            cons_full.append([cid, r.get("consumer_name", ""), " ".join((r.get("service_address") or "").lower().split())])
        m = (r.get("month") or "").strip()
        if len(m) < 7: continue
        k = int(m[:4]) * 100 + int(m[5:7])
        try: units = float(r.get("units_kwh") or 0)
        except ValueError: units = 0.0
        util_m.setdefault(cid, {})[k] = (units, pdte(r.get("bill_paid_date")))
    out["cons_full"] = cons_full; out["util_m"] = util_m

if PART in ("activity", "all"):
    # --- bank transactions (customer-initiated DR only) ---
    bank_month, bank_last, bank_det, bank_tx = {}, {}, {}, {}
    for r in stream("bank_transactions.csv"):
        if (r.get("txn_type") or "").strip().upper() not in ("DR", "DEBIT"): continue
        d = pdte(r.get("txn_date"))
        if not d: continue
        a = r["account_number"]; k = d.year * 100 + d.month
        amt = float(r["amount"] or 0)
        bm = bank_month.setdefault(a, {}); bm[k] = bm.get(k, 0) + 1
        mx(bank_last, a, d)
        det = bank_det.setdefault(a, {}).setdefault(k, [0, 0.0, 0])
        det[0] += 1; det[1] += amt
        if (r.get("channel") or "").strip().upper() == "ATM": det[2] += 1
        tx = bank_tx.setdefault(a, {}).setdefault(k, [])
        if len(tx) < 60: tx.append((d, amt))
    out["bank_month"] = bank_month; out["bank_last"] = bank_last
    out["bank_det"] = bank_det; out["bank_tx"] = bank_tx

    # --- telecom ---
    tele_month, tele_last, tele_last_sig = {}, {}, {}
    for r in stream("telecom_activity.csv"):
        m = (r.get("month") or "").strip()
        if len(m) < 7: continue
        k = int(m[:4]) * 100 + int(m[5:7])
        act = float(r.get("calls_made") or 0) + float(r.get("sms_sent") or 0) + float(r.get("data_mb") or 0)
        tele_month.setdefault(r["mobile"], {})[k] = act
        ld = pdte(r.get("last_activity_date"))
        if act > 0 and ld:
            mx(tele_last, r["mobile"], ld)
            if act >= 30: mx(tele_last_sig, r["mobile"], ld)
    out["tele_month"] = tele_month; out["tele_last"] = tele_last; out["tele_last_sig"] = tele_last_sig

fn = "aggV3.db" if PART != "activity" else "aggV3b.db"
dump(out,D+fn)
print("part", PART, "keys", sorted(out))
print("counts", {k: len(v) for k, v in out.items()})
print("peak_rss_mb", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
