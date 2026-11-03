"""Outcome feedback: verified case outcomes recalibrate per-signal
likelihood ratios with Laplace smoothing, and the base rate from the
confirmed-deceased share of resolved cases."""
from datetime import datetime
from . import db

OUTCOMES = ("confirmed_deceased", "confirmed_alive")

def record_outcome(conn, case_id, outcome, note=""):
    assert outcome in OUTCOMES
    conn.execute("UPDATE cases SET outcome=?, outcome_note=? WHERE id=?", (outcome, note, case_id))
    db.log(conn, "officer", "outcome", f"case={case_id} outcome={outcome}")

def recalibrate(conn):
    resolved = conn.execute(
        "SELECT id, outcome FROM cases WHERE outcome IS NOT NULL").fetchall()
    if len(resolved) < 5:
        return None, "need at least 5 resolved cases to recalibrate"
    dec = {r["id"] for r in resolved if r["outcome"] == "confirmed_deceased"}
    alive = {r["id"] for r in resolved if r["outcome"] == "confirmed_alive"}
    base_rate = round(len(dec) / len(resolved), 4)
    db.set_setting(conn, "base_rate", base_rate)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    for sig in db.DEFAULT_WEIGHTS:
        rows = conn.execute(
            "SELECT case_id, present FROM signals WHERE signal=?", (sig,)).fetchall()
        p_given_dec = (sum(1 for r in rows if r["case_id"] in dec and r["present"]) + 1) / (len(dec) + 2)
        p_given_alive = (sum(1 for r in rows if r["case_id"] in alive and r["present"]) + 1) / (len(alive) + 2)
        lr_plus = round(p_given_dec / p_given_alive, 4)
        lr_minus = round((1 - p_given_dec) / (1 - p_given_alive), 4)
        conn.execute("UPDATE weights SET lr_plus=?, lr_minus=?, updated_at=? WHERE signal=?",
                     (max(lr_plus, 0.05), max(lr_minus, 0.05), now, sig))
    conn.commit()
    db.log(conn, "feedback", "recalibrate", f"resolved={len(resolved)} base_rate={base_rate}")
    return base_rate, f"recalibrated from {len(resolved)} resolved cases"

def stats(conn):
    rows = conn.execute(
        "SELECT outcome, COUNT(*) n FROM cases WHERE outcome IS NOT NULL GROUP BY outcome").fetchall()
    return {r["outcome"]: r["n"] for r in rows}
