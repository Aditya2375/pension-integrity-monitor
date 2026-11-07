"""Outcome feedback: verified case outcomes recalibrate per-signal
likelihood ratios with Laplace smoothing.

Two safeguards against feedback-loop bias:
- A large minimum sample in BOTH outcome classes before anything changes.
  Officer-resolved cases are a selected sample (high-confidence cases get
  resolved first), so small-sample recalibration reinforces itself.
- The configured base rate is NEVER updated from the deceased share of
  resolved cases: resolved cases are all flagged cases, so that share is
  the queue's precision, not the population base rate. The base rate stays
  a configured assumption. Unresolved cases are never treated as negative.
"""
from datetime import datetime
from . import db

MIN_RESOLVED = 30
MIN_PER_CLASS = 5

OUTCOMES = ("confirmed_deceased", "confirmed_alive")

def record_outcome(conn, case_id, outcome, note="", actor="officer"):
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome!r}")
    conn.execute("UPDATE cases SET outcome=?, outcome_note=? WHERE id=?", (outcome, note, case_id))
    db.log(conn, actor, "outcome", f"case={case_id} outcome={outcome}")

def recalibrate(conn):
    resolved = conn.execute(
        "SELECT id, outcome FROM cases WHERE outcome IS NOT NULL").fetchall()
    dec = {r["id"] for r in resolved if r["outcome"] == "confirmed_deceased"}
    alive = {r["id"] for r in resolved if r["outcome"] == "confirmed_alive"}
    if len(resolved) < MIN_RESOLVED or len(dec) < MIN_PER_CLASS or len(alive) < MIN_PER_CLASS:
        return None, (f"need at least {MIN_RESOLVED} resolved cases with {MIN_PER_CLASS}+ "
                      f"confirmed deceased and {MIN_PER_CLASS}+ confirmed alive to recalibrate")
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
    db.log(conn, "feedback", "recalibrate", f"resolved={len(resolved)} (base rate unchanged)")
    return None, f"recalibrated LRs from {len(resolved)} resolved cases; base rate unchanged"

def audit_stats(conn):
    """Observed counts only, not a population estimate. Retain samples even if
    subsequent rescoring replaces their signals; unresolved cases stay visible."""
    rows = conn.execute(
        "SELECT c.outcome, COUNT(*) n FROM audit_samples a JOIN cases c ON c.id=a.case_id "
        "GROUP BY c.outcome").fetchall()
    result = {(r["outcome"] or "unresolved"): r["n"] for r in rows}
    result["selected"] = sum(result.values())
    return result

def stats(conn):
    rows = conn.execute(
        "SELECT outcome, COUNT(*) n FROM cases WHERE outcome IS NOT NULL GROUP BY outcome").fetchall()
    return {r["outcome"]: r["n"] for r in rows}
