"""Case workflow: one explicit state machine, four-eyes decisions, notice
period, provisional restore on appeal, and independent appeal review.

Rules enforced here (not in the routes), so every caller gets them:
  * A flag never changes a pension. Only a supervisor's approval of an
    officer's proposal can start a notice, and suspension needs the notice
    period to have run or a supervisor's recorded override.
  * The approver must be a different user from the proposer.
  * An appeal restores the pension provisionally at once.
  * The appeal reviewer is a supervisor who took no part in the original
    proposal or approval.
  * Every change writes a hash-chained audit entry in the same transaction.
"""
from datetime import datetime, timedelta
from . import audit

ROLES = ("officer", "supervisor", "auditor", "admin")

TRANSITIONS = {
    "FLAGGED": {"UNDER_REVIEW", "VERIFICATION", "DISMISSED"},
    "UNDER_REVIEW": {"VERIFICATION", "DISMISSED"},
    "VERIFICATION": {"HOLD_PROPOSED", "DEATH_PROPOSED", "DISMISSED"},
    "HOLD_PROPOSED": {"NOTICE", "VERIFICATION"},
    "DEATH_PROPOSED": {"SURVIVOR_ROUTING", "VERIFICATION"},
    "NOTICE": {"HELD", "APPEAL_REVIEW", "RELEASED"},
    "HELD": {"APPEAL_REVIEW", "RELEASED"},
    "APPEAL_REVIEW": {"RELEASED", "HELD"},
    "SURVIVOR_ROUTING": {"CLOSED_CONFIRMED"},
    "RELEASED": set(), "DISMISSED": set(), "CLOSED_CONFIRMED": set(),
}
OPEN_STATES = ("FLAGGED", "UNDER_REVIEW", "VERIFICATION")
# Recommended payment status per state, recorded on the case. The source
# pension feed is immutable; the payment system reads this via the API.
PAYMENT_STATUS = {"HELD": "SUSPENDED", "APPEAL_REVIEW": "PROVISIONALLY_RESTORED", "RELEASED": "ACTIVE",
                  "SURVIVOR_ROUTING": "STOP_DECEASED", "CLOSED_CONFIRMED": "STOP_DECEASED"}

NOTICE_DAYS_DEFAULT = 30
SLA_DAYS = {"FLAGGED": 3, "UNDER_REVIEW": 7, "VERIFICATION": 14, "HOLD_PROPOSED": 2,
            "DEATH_PROPOSED": 2, "APPEAL_REVIEW": 15}

SURVIVOR_CHECKLIST = [
    "Death certificate verified with the registrar",
    "Family pension eligibility checked under the scheme rules",
    "Nominee / eligible family member identified",
    "Claim form and document checklist shared with the family",
    "Pension stopped from the correct month and any excess payment recorded",
]

DDL = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, role TEXT NOT NULL, salt TEXT NOT NULL, key_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, kind TEXT NOT NULL,
  proposer TEXT NOT NULL, reason TEXT NOT NULL, proposed_at TEXT NOT NULL,
  approver TEXT, decided_at TEXT, status TEXT NOT NULL DEFAULT 'PENDING', decision_note TEXT
);
CREATE TABLE IF NOT EXISTS case_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, ts TEXT NOT NULL,
  author TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS survivor_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, step TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0, note TEXT
);
CREATE TABLE IF NOT EXISTS appeal_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT, appeal_id INTEGER NOT NULL, ts TEXT NOT NULL,
  filename TEXT, mime TEXT, size INTEGER, sha256 TEXT, stored_path TEXT
);
"""
CASE_COLUMNS = {
    "proposed_by": "TEXT", "approved_by": "TEXT", "notice_issued_at": "TEXT",
    "notice_due_at": "TEXT", "suspended_at": "TEXT", "restored_at": "TEXT",
    "state_changed_at": "TEXT", "payment_status": "TEXT DEFAULT 'ACTIVE'", "review_reasons": "TEXT", "source_feed_refs": "TEXT",
}


class WorkflowError(Exception):
    pass


def _now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", ""))


def ensure_schema(conn):
    conn.executescript(DDL)
    audit.ensure(conn)
    have = {r["name"] for r in conn.execute("PRAGMA table_info(cases)")}
    for col, typ in CASE_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {col} {typ}")
    conn.commit()


class Actor:
    def __init__(self, username, role):
        self.username, self.role = username, role


def _need(actor, *roles):
    if actor.role not in roles:
        raise WorkflowError(f"role '{actor.role}' cannot do this; needs {' or '.join(roles)}")


def _case(conn, cid):
    c = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    if not c:
        raise WorkflowError("case not found")
    return c


def _move(conn, case, new, actor, action, detail="", **fields):
    old = case["state"]
    if new not in TRANSITIONS.get(old, set()):
        raise WorkflowError(f"illegal transition {old} -> {new}")
    sets = {"state": new, "state_changed_at": _now(), **fields}
    cols = ", ".join(f"{k}=?" for k in sets)
    conn.execute(f"UPDATE cases SET {cols} WHERE id=?", (*sets.values(), case["id"]))
    # Payment status lives on the case, never on the source feed table.
    if new in PAYMENT_STATUS:
        conn.execute("UPDATE cases SET payment_status=? WHERE id=?", (PAYMENT_STATUS[new], case["id"]))
    audit.append(conn, actor.username, action, case["id"], f"{old}->{new} {detail}".strip(), actor.role)


def _setting_days(conn, key, default):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return int(r["value"]) if r else default


def _arrears(conn, case, until):
    """Pension owed for the period payment was actually suspended."""
    if not case["suspended_at"]:
        return float(case["arrears"] or 0)
    amt = conn.execute("SELECT monthly_amount FROM pension_master WHERE pensioner_id=?",
                       (case["pensioner_id"],)).fetchone()["monthly_amount"] or 0
    days = max((_parse(until) - _parse(case["suspended_at"])).days, 0)
    return round(float(case["arrears"] or 0) + days / 30.44 * float(amt), 2)


# ---- officer actions -----------------------------------------------------
def start_review(conn, cid, actor):
    _need(actor, "officer", "supervisor")
    c = _case(conn, cid)
    _move(conn, c, "UNDER_REVIEW", actor, "start_review")


def add_note(conn, cid, actor, body):
    _need(actor, "officer", "supervisor")
    body = (body or "").strip()
    if not body:
        raise WorkflowError("note is empty")
    _case(conn, cid)
    conn.execute("INSERT INTO case_notes(case_id,ts,author,body) VALUES(?,?,?,?)",
                 (cid, _now(), actor.username, body[:4000]))
    audit.append(conn, actor.username, "note", cid, f"{len(body)} chars", actor.role)


def complete_step(conn, cid, vid, done, note, actor):
    _need(actor, "officer", "supervisor")
    c = _case(conn, cid)
    if c["state"] not in OPEN_STATES:
        raise WorkflowError("verification is closed for this case")
    conn.execute("UPDATE verifications SET done=?, note=? WHERE id=? AND case_id=?",
                 (1 if done else 0, note or "", vid, cid))
    if c["state"] in ("FLAGGED", "UNDER_REVIEW"):
        _move(conn, c, "VERIFICATION", actor, "verify_step", f"step={vid} done={int(bool(done))}")
    else:
        audit.append(conn, actor.username, "verify_step", cid, f"step={vid} done={int(bool(done))}", actor.role)


def dismiss(conn, cid, actor, note):
    _need(actor, "officer", "supervisor")
    if not (note or "").strip():
        raise WorkflowError("a reason is required to dismiss")
    c = _case(conn, cid)
    _move(conn, c, "DISMISSED", actor, "dismiss", note[:200], outcome_note=note.strip())


def _steps_complete(conn, cid):
    r = conn.execute("SELECT COUNT(*) t, COALESCE(SUM(done),0) d FROM verifications WHERE case_id=?", (cid,)).fetchone()
    return r["t"] > 0 and r["t"] == r["d"]


def propose(conn, cid, kind, actor, reason):
    """kind: 'hold' or 'confirm_death'. Needs written reasons and every
    verification step done."""
    _need(actor, "officer")
    if kind not in ("hold", "confirm_death"):
        raise WorkflowError("unknown proposal kind")
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("written reasons are required")
    c = _case(conn, cid)
    if c["state"] not in OPEN_STATES:
        raise WorkflowError(f"cannot propose from {c['state']}")
    if not _steps_complete(conn, cid):
        raise WorkflowError("verification steps must exist and all be completed first")
    if c["state"] != "VERIFICATION":
        _move(conn, c, "VERIFICATION", actor, "auto_to_verification")
        c = _case(conn, cid)
    new = "HOLD_PROPOSED" if kind == "hold" else "DEATH_PROPOSED"
    conn.execute("INSERT INTO decisions(case_id,kind,proposer,reason,proposed_at) VALUES(?,?,?,?,?)",
                 (cid, kind, actor.username, reason[:4000], _now()))
    _move(conn, c, new, actor, f"propose_{kind}", "", proposed_by=actor.username)


def _pending(conn, cid):
    d = conn.execute("SELECT * FROM decisions WHERE case_id=? AND status='PENDING' ORDER BY id DESC", (cid,)).fetchone()
    if not d:
        raise WorkflowError("no pending proposal")
    return d


def decide(conn, cid, actor, approve, note=""):
    """Supervisor approves or rejects the pending proposal. Never the proposer."""
    _need(actor, "supervisor")
    c = _case(conn, cid)
    d = _pending(conn, cid)
    if d["proposer"] == actor.username:
        raise WorkflowError("the approver must be a different person from the proposer")
    if not approve and not (note or "").strip():
        raise WorkflowError("a reason is required to reject")
    conn.execute("UPDATE decisions SET approver=?, decided_at=?, status=?, decision_note=? WHERE id=?",
                 (actor.username, _now(), "APPROVED" if approve else "REJECTED", note, d["id"]))
    if not approve:
        _move(conn, c, "VERIFICATION", actor, f"reject_{d['kind']}", note[:200])
        return
    now = _now()
    if d["kind"] == "hold":
        days = _setting_days(conn, "notice_period_days", NOTICE_DAYS_DEFAULT)
        due = (_parse(now) + timedelta(days=days)).isoformat(timespec="seconds") + "Z"
        _move(conn, c, "NOTICE", actor, "approve_hold", f"notice_days={days}",
              approved_by=actor.username, notice_issued_at=now, notice_due_at=due,
              hold_reasons=d["reason"])
    else:
        _move(conn, c, "SURVIVOR_ROUTING", actor, "approve_death", "", approved_by=actor.username,
              outcome="confirmed_deceased", outcome_note=d["reason"])
        for s in SURVIVOR_CHECKLIST:
            conn.execute("INSERT INTO survivor_steps(case_id,step) VALUES(?,?)", (cid, s))


def suspend(conn, cid, actor, override_reason=""):
    """Start suspending payment once the notice period has run. A supervisor
    may shorten it only with a written, audited reason."""
    _need(actor, "supervisor")
    c = _case(conn, cid)
    if c["state"] != "NOTICE":
        raise WorkflowError("only a case in notice can be suspended")
    now = _now()
    if _parse(now) < _parse(c["notice_due_at"]) and not (override_reason or "").strip():
        raise WorkflowError(f"notice period runs until {c['notice_due_at']}; give a written reason to override")
    _move(conn, c, "HELD", actor, "suspend", f"override={override_reason[:200]}" if override_reason else "",
          held_at=now, suspended_at=now)


def file_appeal(conn, cid, statement, contact=""):
    """Family appeal. Restores payment provisionally straight away."""
    c = _case(conn, cid)
    if c["state"] not in ("NOTICE", "HELD"):
        raise WorkflowError("this case is not open to appeal")
    window = _setting_days(conn, "appeal_window_days", 30)
    start = c["notice_issued_at"] or c["held_at"]
    if start and _parse(_now()) > _parse(start) + timedelta(days=window):
        raise WorkflowError("the appeal window for this case has closed")
    actor = Actor("family", "family")
    now = _now()
    arrears = _arrears(conn, c, now)
    conn.execute("UPDATE cases SET arrears=?, suspended_at=NULL, restored_at=? WHERE id=?", (arrears, now, cid))
    _move(conn, _case(conn, cid), "APPEAL_REVIEW", actor, "appeal_filed", "provisional restore")
    return arrears


def resolve_appeal(conn, cid, actor, uphold, note):
    _need(actor, "supervisor")
    c = _case(conn, cid)
    if c["state"] != "APPEAL_REVIEW":
        raise WorkflowError("case is not under appeal review")
    if actor.username in (c["proposed_by"], c["approved_by"]):
        raise WorkflowError("the appeal must be decided by a supervisor who took no part in the original decision")
    if not (note or "").strip():
        raise WorkflowError("a written decision is required")
    now = _now()
    if uphold:
        _move(conn, c, "HELD", actor, "appeal_upheld", note[:200], held_at=now, suspended_at=now, restored_at=None)
    else:
        _move(conn, c, "RELEASED", actor, "appeal_reversed", note[:200], released_at=now,
              outcome="confirmed_alive", outcome_note=note.strip())


def release(conn, cid, actor, note):
    """Release a case in notice or held when the evidence clears the pensioner."""
    _need(actor, "supervisor")
    if not (note or "").strip():
        raise WorkflowError("a reason is required to release")
    c = _case(conn, cid)
    now = _now()
    arrears = _arrears(conn, c, now)
    _move(conn, c, "RELEASED", actor, "release", f"arrears={arrears}", released_at=now, arrears=arrears,
          suspended_at=None, outcome="confirmed_alive", outcome_note=note.strip())
    return arrears


def complete_survivor_step(conn, cid, step_id, done, note, actor):
    _need(actor, "officer", "supervisor")
    c = _case(conn, cid)
    if c["state"] != "SURVIVOR_ROUTING":
        raise WorkflowError("case is not in survivor routing")
    conn.execute("UPDATE survivor_steps SET done=?, note=? WHERE id=? AND case_id=?",
                 (1 if done else 0, note or "", step_id, cid))
    audit.append(conn, actor.username, "survivor_step", cid, f"step={step_id} done={int(bool(done))}", actor.role)
    r = conn.execute("SELECT COUNT(*) t, SUM(done) d FROM survivor_steps WHERE case_id=?", (cid,)).fetchone()
    if r["t"] and r["t"] == (r["d"] or 0):
        _move(conn, _case(conn, cid), "CLOSED_CONFIRMED", actor, "survivor_routing_complete")


def sla_status(case, now=None):
    """('ok'|'due_soon'|'overdue', days_left) from the state's SLA."""
    days = SLA_DAYS.get(case["state"])
    if not days or not case["state_changed_at"] and not case["created_at"]:
        return None
    start = _parse(case["state_changed_at"] or case["created_at"])
    left = (start + timedelta(days=days) - (now or datetime.utcnow())).total_seconds() / 86400
    return ("overdue" if left < 0 else "due_soon" if left < 1 else "ok", round(left, 1))
