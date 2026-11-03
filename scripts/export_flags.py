"""Export ranked flags with probability and per-signal breakdown to CSV.
Usage: python scripts/export_flags.py [out.csv]"""
import csv, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from pim import db

SIGNALS = ["death_registry_match", "hospital_died_match", "electoral_deletion",
           "bank_cliff", "telecom_cliff", "aligned_cliff", "life_cert_overdue",
           "bank_inactivity", "telecom_quiet", "alive_itr", "alive_utility"]

def export(path, states=("FLAGGED", "UNDER_REVIEW", "VERIFICATION")):
    conn = db.connect()
    ph = ",".join("?" for _ in states)
    cases = conn.execute(
        f"SELECT * FROM cases WHERE state IN ({ph}) ORDER BY priority DESC, probability DESC",
        states).fetchall()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "case_id", "pensioner_id", "probability", "priority",
                    "base_rate"] + [f"sig_{s}" for s in SIGNALS] + [f"logodds_{s}" for s in SIGNALS])
        for i, c in enumerate(cases, 1):
            sigs = {r["signal"]: r for r in conn.execute("SELECT * FROM signals WHERE case_id=?", (c["id"],))}
            w.writerow([i, c["id"], c["pensioner_id"], c["probability"], c["priority"], c["base_rate"]]
                       + [int(sigs[s]["present"]) if s in sigs else "" for s in SIGNALS]
                       + [sigs[s]["value"] if s in sigs else "" for s in SIGNALS])
    conn.close()
    return len(cases)

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "flags.csv"
    n = export(out)
    print(f"exported {n} ranked flags to {out}")
