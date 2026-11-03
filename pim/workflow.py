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
import secrets
import string
from . import audit, notify
from security import identity

ROLES = ("officer", "supervisor", "auditor", "admin")

TRANSITIONS = {
    "FLAGGED": {"UNDER_REVIEW", "VERIFICATION", "DISMISSED"},
    "UNDER_REVIEW": {"VERIFICATION", "DISMISSED"},
    "VERIFICATION": {"HOLD_PROPOSED", "DEATH_PROPOSED", "DISMISSED"},
    "HOLD_PROPOSED": {"NOTICE", "VERIFICATION"},
    "DEATH_PROPOSED": {"NOTICE", "VERIFICATION"},
    "NOTICE": {"HELD", "APPEAL_REVIEW", "RELEASED", "SURVIVOR_ROUTING"},
    "HELD": {"APPEAL_REVIEW", "RELEASED"},
    "APPEAL_REVIEW": {"RELEASED", "HELD", "SURVIVOR_ROUTING"},
    "SURVIVOR_ROUTING": {"CLOSED_CONFIRMED", "APPEAL_REVIEW"},
    "CLOSED_CONFIRMED": {"APPEAL_REVIEW"},
    "RELEASED": set(), "DISMISSED": set(),
}
# Which action may take each edge. A route can never move a case along an
# edge unless the matching workflow function is the one doing it.
EDGE_ACTIONS = {
    ("FLAGGED", "UNDER_REVIEW"): {"start_review"},
    ("FLAGGED", "VERIFICATION"): {"verify_step"},
    ("UNDER_REVIEW", "VERIFICATION"): {"verify_step"},
    ("FLAGGED", "DISMISSED"): {"dismiss"}, ("UNDER_REVIEW", "DISMISSED"): {"dismiss"},
    ("VERIFICATION", "DISMISSED"): {"dismiss"},
    ("VERIFICATION", "HOLD_PROPOSED"): {"propose_hold"},
    ("VERIFICATION", "DEATH_PROPOSED"): {"propose_confirm_death"},
    ("HOLD_PROPOSED", "NOTICE"): {"approve_hold"},
    ("HOLD_PROPOSED", "VERIFICATION"): {"reject_hold"},
    ("DEATH_PROPOSED", "NOTICE"): {"approve_death"},
    ("NOTICE", "SURVIVOR_ROUTING"): {"finalize_death"},
    ("APPEAL_REVIEW", "SURVIVOR_ROUTING"): {"appeal_upheld"},
    ("SURVIVOR_ROUTING", "APPEAL_REVIEW"): {"reopen"},
    ("CLOSED_CONFIRMED", "APPEAL_REVIEW"): {"reopen"},
    ("DEATH_PROPOSED", "VERIFICATION"): {"reject_confirm_death", "reject_death"},
    ("NOTICE", "HELD"): {"suspend"},
    ("NOTICE", "APPEAL_REVIEW"): {"appeal_filed", "late_appeal_accepted"},
    ("HELD", "APPEAL_REVIEW"): {"appeal_filed", "late_appeal_accepted"},
    ("NOTICE", "RELEASED"): {"release"},
    ("HELD", "RELEASED"): {"release"},
    ("APPEAL_REVIEW", "RELEASED"): {"appeal_reversed"},
    ("APPEAL_REVIEW", "HELD"): {"appeal_upheld"},
    ("SURVIVOR_ROUTING", "CLOSED_CONFIRMED"): {"survivor_routing_complete"},
    ("VERIFICATION", "VERIFICATION"): set(),
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
  active INTEGER NOT NULL DEFAULT 1, jurisdictions TEXT NOT NULL DEFAULT 'NA'
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, kind TEXT NOT NULL,
  proposer TEXT NOT NULL, reason TEXT NOT NULL, proposed_at TEXT NOT NULL,
  approver TEXT, decided_at TEXT, status TEXT NOT NULL DEFAULT 'PENDING', decision_note TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_decision ON decisions(case_id) WHERE status='PENDING';
CREATE TABLE IF NOT EXISTS case_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, ts TEXT NOT NULL,
  author TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS survivor_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, step TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0, note TEXT
);
CREATE TABLE IF NOT EXISTS reinstatement_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, kind TEXT NOT NULL,
  requested_at TEXT NOT NULL, requested_by TEXT NOT NULL, arrears_due REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'REQUESTED'
);
CREATE TABLE IF NOT EXISTS appeal_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT, appeal_id INTEGER NOT NULL, ts TEXT NOT NULL,
  filename TEXT, mime TEXT, size INTEGER, sha256 TEXT, stored_path TEXT
);
"""
CASE_COLUMNS = {
    "proposed_by": "TEXT", "approved_by": "TEXT", "notice_issued_at": "TEXT",
    "notice_due_at": "TEXT", "suspended_at": "TEXT", "restored_at": "TEXT", "case_kind": "TEXT DEFAULT 'hold'", "appeal_deadline_at": "TEXT", "reopened_by": "TEXT",
    "state_changed_at": "TEXT", "override_reason": "TEXT", "payment_status": "TEXT DEFAULT 'ACTIVE'", "review_reasons": "TEXT", "source_feed_refs": "TEXT",
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
    notify.ensure(conn)
    from . import otp
    otp.ensure(conn)
    have = {r["name"] for r in conn.execute("PRAGMA table_info(cases)")}
    for col, typ in CASE_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {col} {typ}")
    ev = {r["name"] for r in conn.execute("PRAGMA table_info(appeal_evidence)")}
    if "status" not in ev:
        conn.execute("ALTER TABLE appeal_evidence ADD COLUMN status TEXT NOT NULL DEFAULT 'QUARANTINED'")
    conn.commit()


# Portal role -> security.identity role. Authorization itself is delegated to
# security.identity.authorized so there is one rule set.
ROLE_MAP = {"officer": "reviewer", "supervisor": "approver", "auditor": "auditor", "admin": "ingestor"}


class Actor:
    """A server-owned identity (never built from a form or client header)."""
    def __init__(self, username, role, jurisdictions=("NA",)):
        self.username, self.role = username, role
        self.jurisdictions = frozenset(jurisdictions)

    def principal(self):
        r = ROLE_MAP.get(self.role)
        return identity.Principal(self.username, frozenset([r] if r else []), self.jurisdictions)


def jurisdiction_of(conn, case):
    r = conn.execute("SELECT state FROM pension_master WHERE pensioner_id=?", (case["pensioner_id"],)).fetchone()
    return (r["state"] if r and r["state"] else "NA")


def _need(conn, actor, action, case):
    # Re-check the account inside the transaction: a revoked or re-roled user
    # cannot finish an action that was started before the change.
    row = conn.execute("SELECT role, active, jurisdictions FROM users WHERE username=?", (actor.username,)).fetchone()
    if row is not None and (not row["active"] or row["role"] != actor.role):
        raise WorkflowError(f"'{actor.username}' is no longer authorised")
    if not identity.authorized(actor.principal(), action, jurisdiction_of(conn, case)):
        raise WorkflowError(f"'{actor.username}' ({actor.role}) is not authorised for {action} on this case")


def new_tracking_id():
    return "APL-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(10))


def _lock(conn):
    """Take the database write lock before reading anything a decision depends
    on, so two actors cannot both act on the same state."""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _case(conn, cid):
    _lock(conn)
    c = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    if not c:
        raise WorkflowError("case not found")
    return c


def _move(conn, case, new, actor, action, **fields):
    old = case["state"]
    if new not in TRANSITIONS.get(old, set()):
        raise WorkflowError(f"illegal transition {old} -> {new}")
    if action not in EDGE_ACTIONS.get((old, new), set()) and action != "auto_to_verification":
        raise WorkflowError(f"{action} cannot move a case from {old} to {new}")
    sets = {"state": new, "state_changed_at": _now(), **fields}
    cols = ", ".join(f"{k}=?" for k in sets)
    conn.execute(f"UPDATE cases SET {cols} WHERE id=?", (*sets.values(), case["id"]))
    # Payment status lives on the case, never on the source feed table.
    if new in PAYMENT_STATUS:
        conn.execute("UPDATE cases SET payment_status=? WHERE id=?", (PAYMENT_STATUS[new], case["id"]))
    audit.append(conn, actor.username, action, case["id"], f"{old}>{new}", actor.role)


def _setting_days(conn, key, default):
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return int(r["value"]) if r else default


def _request_reinstatement(conn, cid, kind, who, arrears):
    """Record a request for the payment system to restore payment. This
    system never moves money; the payer acts on the request and confirms."""
    conn.execute("INSERT INTO reinstatement_requests(case_id,kind,requested_at,requested_by,arrears_due) VALUES(?,?,?,?,?)",
                 (cid, kind, _now(), who, arrears))
    audit.append(conn, who, "reinstatement_requested", cid, kind)


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
    c = _case(conn, cid)
    _need(conn, actor, "verify", c)
    _move(conn, c, "UNDER_REVIEW", actor, "start_review")


def add_note(conn, cid, actor, body):
    body = (body or "").strip()
    if not body:
        raise WorkflowError("note is empty")
    c = _case(conn, cid)
    _need(conn, actor, "verify", c)
    conn.execute("INSERT INTO case_notes(case_id,ts,author,body) VALUES(?,?,?,?)",
                 (cid, _now(), actor.username, body[:4000]))
    audit.append(conn, actor.username, "note", cid, "", actor.role)


def complete_step(conn, cid, vid, done, note, actor):
    c = _case(conn, cid)
    _need(conn, actor, "verify", c)
    if c["state"] not in OPEN_STATES:
        raise WorkflowError("verification is closed for this case")
    cur = conn.execute("UPDATE verifications SET done=?, note=? WHERE id=? AND case_id=?",
                       (1 if done else 0, note or "", vid, cid))
    if cur.rowcount != 1:
        raise WorkflowError("that verification step does not belong to this case")
    if c["state"] in ("FLAGGED", "UNDER_REVIEW"):
        _move(conn, c, "VERIFICATION", actor, "verify_step")
    else:
        audit.append(conn, actor.username, "verify_step", cid, f"step{int(vid)}_done{int(bool(done))}", actor.role)


def dismiss(conn, cid, actor, note):
    if not (note or "").strip():
        raise WorkflowError("a reason is required to dismiss")
    c = _case(conn, cid)
    _need(conn, actor, "verify", c)
    _move(conn, c, "DISMISSED", actor, "dismiss", outcome_note=note.strip())


def expected_steps():
    from .pipeline import VERIFICATION_STEPS
    return sorted(VERIFICATION_STEPS)


def _steps_complete(conn, cid):
    """The case must carry exactly the expected checks, each once, all done.
    A missing, extra, duplicated or renamed row fails."""
    rows = conn.execute("SELECT step, done FROM verifications WHERE case_id=?", (cid,)).fetchall()
    return sorted(r["step"] for r in rows) == expected_steps() and all(r["done"] == 1 for r in rows)


def propose(conn, cid, kind, actor, reason):
    """kind: 'hold' or 'confirm_death'. Needs written reasons and every
    verification step done."""
    if kind not in ("hold", "confirm_death"):
        raise WorkflowError("unknown proposal kind")
    reason = (reason or "").strip()
    if not reason:
        raise WorkflowError("written reasons are required")
    c = _case(conn, cid)
    _need(conn, actor, "propose_decision", c)
    if c["state"] not in OPEN_STATES:
        raise WorkflowError(f"cannot propose from {c['state']}")
    if not _steps_complete(conn, cid):
        raise WorkflowError("all four required verification checks must be present and completed first")
    if c["state"] != "VERIFICATION":
        _move(conn, c, "VERIFICATION", actor, "auto_to_verification")
        c = _case(conn, cid)
    new = "HOLD_PROPOSED" if kind == "hold" else "DEATH_PROPOSED"
    conn.execute("INSERT INTO decisions(case_id,kind,proposer,reason,proposed_at) VALUES(?,?,?,?,?)",
                 (cid, kind, actor.username, reason[:4000], _now()))
    _move(conn, c, new, actor, f"propose_{kind}", proposed_by=actor.username)


def _pending(conn, cid):
    d = conn.execute("SELECT * FROM decisions WHERE case_id=? AND status='PENDING' ORDER BY id DESC", (cid,)).fetchone()
    if not d:
        raise WorkflowError("no pending proposal")
    return d


def decide(conn, cid, actor, approve, note=""):
    """Supervisor approves or rejects the pending proposal. Never the proposer."""
    c = _case(conn, cid)
    _need(conn, actor, "approve_decision", c)
    d = _pending(conn, cid)
    if d["proposer"] == actor.username:
        raise WorkflowError("the approver must be a different person from the proposer")
    if not approve and not (note or "").strip():
        raise WorkflowError("a reason is required to reject")
    conn.execute("UPDATE decisions SET approver=?, decided_at=?, status=?, decision_note=? WHERE id=?",
                 (actor.username, _now(), "APPROVED" if approve else "REJECTED", note, d["id"]))
    if not approve:
        _move(conn, c, "VERIFICATION", actor, f"reject_{d['kind']}")
        return
    now = _now()
    days = _setting_days(conn, "notice_period_days", NOTICE_DAYS_DEFAULT)
    window = _setting_days(conn, "appeal_window_days", 30)
    due = (_parse(now) + timedelta(days=days)).isoformat(timespec="seconds") + "Z"
    deadline = (_parse(now) + timedelta(days=window)).isoformat(timespec="seconds") + "Z"
    kind = "death" if d["kind"] == "confirm_death" else "hold"
    # Both kinds go through the same notice, appeal and independent review.
    # A death is never final on first approval; payment continues meanwhile.
    _move(conn, c, "NOTICE", actor, "approve_hold" if kind == "hold" else "approve_death",
          approved_by=actor.username, notice_issued_at=now, notice_due_at=due, appeal_deadline_at=deadline,
          case_kind=kind, hold_reasons=d["reason"])
    tid = new_tracking_id()
    conn.execute("INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,status) VALUES(?,?,?,?,'NOTICE')",
                 (tid, cid, now, "Notice issued"))
    notify.enqueue(conn, cid, "notice_issued" if kind == "hold" else "death_notice_issued",
                   {"tracking_id": tid, "due": deadline[:10]})


def _start_survivor_routing(conn, cid):
    conn.execute("DELETE FROM survivor_steps WHERE case_id=? AND done=0", (cid,))
    have = {r["step"] for r in conn.execute("SELECT step FROM survivor_steps WHERE case_id=?", (cid,))}
    for st in SURVIVOR_CHECKLIST:
        if st not in have:
            conn.execute("INSERT INTO survivor_steps(case_id,step) VALUES(?,?)", (cid, st))


def finalize_death(conn, cid, actor):
    """Make a death confirmation final. Only after the whole appeal period
    has ended with no appeal. Never before, and no override."""
    c = _case(conn, cid)
    _need(conn, actor, "approve_decision", c)
    if c["case_kind"] != "death" or c["state"] != "NOTICE":
        raise WorkflowError("only a death notice that has had no appeal can be finalised")
    if actor.username in (c["proposed_by"],):
        raise WorkflowError("the person who proposed the confirmation cannot finalise it")
    now = _now()
    end = max(c["notice_due_at"] or "", c["appeal_deadline_at"] or "")
    if not end or now < end:
        raise WorkflowError(f"the notice and appeal period runs until {end[:10]}; a death cannot be finalised earlier")
    _move(conn, c, "SURVIVOR_ROUTING", actor, "finalize_death", suspended_at=now,
          outcome="confirmed_deceased", outcome_note=c["hold_reasons"])
    _start_survivor_routing(conn, cid)
    tid = conn.execute("SELECT tracking_id FROM appeals WHERE case_id=? ORDER BY id DESC", (cid,)).fetchone()["tracking_id"]
    notify.enqueue(conn, cid, "death_finalized", {"tracking_id": tid})


def reopen(conn, cid, actor, reason):
    """A supervisor reopens a death that may be wrong, at any time. Payment is
    requested back provisionally and an independent supervisor decides."""
    c = _case(conn, cid)
    _need(conn, actor, "resolve_appeal", c)
    if not (reason or "").strip():
        raise WorkflowError("a written reason is required to reopen")
    if actor.username in (c["proposed_by"], c["approved_by"]):
        raise WorkflowError("someone who took part in the original decision cannot reopen it")
    now = _now()
    arrears = _arrears(conn, c, now)
    tid = new_tracking_id()
    conn.execute("INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,status) VALUES(?,?,?,?,'OPEN')",
                 (tid, cid, now, "Reopened by a supervisor"))
    conn.execute("UPDATE cases SET arrears=?, suspended_at=NULL, restored_at=? WHERE id=?", (arrears, now, cid))
    _move(conn, c, "APPEAL_REVIEW", actor, "reopen", reopened_by=actor.username, outcome=None)
    conn.execute("INSERT INTO case_notes(case_id,ts,author,body) VALUES(?,?,?,?)",
                 (cid, now, actor.username, "Reopened: " + reason.strip()[:3900]))
    _request_reinstatement(conn, cid, "PROVISIONAL", actor.username, arrears)


LATE_REASONS = {
    "NOT_RECEIVED": "Notice not received",
    "ILLNESS": "Illness or hospital stay",
    "ADDRESS": "Address or contact changed",
    "NEW_EVIDENCE": "New evidence found",
    "OTHER_RECORDED": "Other, explained in the note",
}


def accept_late_appeal(conn, cid, actor, code, note):
    """Demo policy, not statutory: the appeal window is a configurable setting.
    A supervisor may still take a late appeal into review, with a fixed reason
    code and a written note. Payment is restored provisionally and a different
    supervisor decides it."""
    c = _case(conn, cid)
    _need(conn, actor, "resolve_appeal", c)
    if code not in LATE_REASONS:
        raise WorkflowError("choose one of the listed reason codes")
    if not (note or "").strip():
        raise WorkflowError("a written note is required")
    if c["state"] not in ("NOTICE", "HELD") or c["case_kind"] == "death" and c["state"] != "NOTICE":
        raise WorkflowError("this case is not open to a late appeal")
    if actor.username in (c["proposed_by"], c["approved_by"]):
        raise WorkflowError("someone who took part in the original decision cannot take it in late")
    dl = c["appeal_deadline_at"]
    if dl and _parse(_now()) <= _parse(dl):
        raise WorkflowError("the appeal period is still open; the family can file normally")
    now = _now()
    arrears = _arrears(conn, c, now)
    row = conn.execute("SELECT * FROM appeals WHERE case_id=? AND status='NOTICE' ORDER BY id DESC", (cid,)).fetchone()
    stmt = "Late appeal accepted by a supervisor: " + LATE_REASONS[code]
    if row:
        if conn.execute("UPDATE appeals SET status='OPEN', statement=?, submitted_at=? WHERE id=? AND status='NOTICE'",
                        (stmt, now, row["id"])).rowcount != 1:
            raise WorkflowError("an appeal has already been filed for this notice")
        tid = row["tracking_id"]
    else:
        tid = new_tracking_id()
        conn.execute("INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,status) VALUES(?,?,?,?,'OPEN')",
                     (tid, cid, now, stmt))
    conn.execute("UPDATE cases SET arrears=?, suspended_at=NULL, restored_at=? WHERE id=?", (arrears, now, cid))
    _move(conn, c, "APPEAL_REVIEW", actor, "late_appeal_accepted", reopened_by=actor.username)
    conn.execute("INSERT INTO case_notes(case_id,ts,author,body) VALUES(?,?,?,?)",
                 (cid, now, actor.username, f"Late appeal accepted [{code}]: " + note.strip()[:3800]))
    _request_reinstatement(conn, cid, "PROVISIONAL", actor.username, arrears)
    notify.enqueue(conn, cid, "appeal_received", {"tracking_id": tid})


def suspend(conn, cid, actor, override_reason=""):
    """Start suspending payment once the notice period has run. A supervisor
    may shorten it only with a written, audited reason."""
    c = _case(conn, cid)
    _need(conn, actor, "approve_decision", c)
    if c["state"] != "NOTICE" or c["case_kind"] == "death":
        raise WorkflowError("only a hold notice can be suspended; a death notice is finalised separately")
    now = _now()
    if _parse(now) < _parse(c["notice_due_at"]) and not (override_reason or "").strip():
        raise WorkflowError(f"notice period runs until {c['notice_due_at']}; give a written reason to override")
    _move(conn, c, "HELD", actor, "suspend",
          held_at=now, suspended_at=now,
          override_reason=(override_reason or "").strip()[:500] or None)


def file_appeal(conn, tracking_id, statement, contact=""):
    """Family appeal against a notice. Restores payment provisionally at
    once. Returns the case id."""
    _lock(conn)
    n = conn.execute("SELECT * FROM appeals WHERE tracking_id=?", (tracking_id,)).fetchone()
    if not n:
        raise WorkflowError("no case found for that tracking ID")
    if n["status"] != "NOTICE":
        raise WorkflowError("an appeal has already been filed for this notice")
    statement = (statement or "").strip()
    if not statement:
        raise WorkflowError("please describe why the decision is wrong")
    cid = n["case_id"]
    c = _case(conn, cid)
    if c["state"] not in ("NOTICE", "HELD"):
        raise WorkflowError("this case is not open to appeal")
    dl = c["appeal_deadline_at"]
    if not dl or _parse(_now()) > _parse(dl):
        raise WorkflowError("The appeal period for this notice has ended. Please contact your pension office, which can still take a late appeal into review.")
    actor = Actor("appellant", "family")
    now = _now()
    arrears = _arrears(conn, c, now)
    claimed = conn.execute("UPDATE appeals SET status='OPEN', statement=?, contact=?, submitted_at=? WHERE id=? AND status='NOTICE'",
                           (statement[:5000], (contact or "")[:200], now, n["id"])).rowcount
    if claimed != 1:   # lost a race with another submission of the same notice
        raise WorkflowError("an appeal has already been filed for this notice")
    conn.execute("UPDATE cases SET arrears=?, suspended_at=NULL, restored_at=? WHERE id=?", (arrears, now, cid))
    _move(conn, _case(conn, cid), "APPEAL_REVIEW", actor, "appeal_filed")
    _request_reinstatement(conn, cid, "PROVISIONAL", "appellant", arrears)
    notify.enqueue(conn, cid, "appeal_received", {"tracking_id": tracking_id})
    return cid


def resolve_appeal(conn, cid, actor, uphold, note):
    c = _case(conn, cid)
    _need(conn, actor, "resolve_appeal", c)
    if c["state"] != "APPEAL_REVIEW":
        raise WorkflowError("case is not under appeal review")
    if actor.username in (c["proposed_by"], c["approved_by"], c["reopened_by"]):
        raise WorkflowError("the appeal must be decided by a supervisor who took no part in the original decision")
    if not (note or "").strip():
        raise WorkflowError("a written decision is required")
    now = _now()
    conn.execute("UPDATE appeals SET status=?, decision=?, resolved_at=? WHERE case_id=? AND status='OPEN'",
                 ("UPHELD" if uphold else "RELEASED", note.strip()[:2000], now, cid))
    tid = conn.execute("SELECT tracking_id FROM appeals WHERE case_id=? ORDER BY id DESC", (cid,)).fetchone()["tracking_id"]
    notify.enqueue(conn, cid, "appeal_upheld" if uphold else "appeal_reversed", {"tracking_id": tid})
    if uphold and c["case_kind"] == "death":
        _move(conn, c, "SURVIVOR_ROUTING", actor, "appeal_upheld", suspended_at=now, restored_at=None,
              outcome="confirmed_deceased", outcome_note=note.strip())
        _start_survivor_routing(conn, cid)
    elif uphold:
        _move(conn, c, "HELD", actor, "appeal_upheld", held_at=now, suspended_at=now, restored_at=None)
    else:
        _move(conn, c, "RELEASED", actor, "appeal_reversed", released_at=now,
              outcome="confirmed_alive", outcome_note=note.strip())
        _request_reinstatement(conn, cid, "FULL", actor.username, float(c["arrears"] or 0))


def release(conn, cid, actor, note):
    """Release a case in notice or held when the evidence clears the pensioner."""
    if not (note or "").strip():
        raise WorkflowError("a reason is required to release")
    c = _case(conn, cid)
    _need(conn, actor, "approve_decision", c)
    if c["state"] == "APPEAL_REVIEW":
        raise WorkflowError("a case under appeal can only be released through the independent appeal decision")
    now = _now()
    arrears = _arrears(conn, c, now)
    _move(conn, c, "RELEASED", actor, "release", released_at=now, arrears=arrears,
          suspended_at=None, outcome="confirmed_alive", outcome_note=note.strip())
    _request_reinstatement(conn, cid, "FULL", actor.username, arrears)
    return arrears


def complete_survivor_step(conn, cid, step_id, done, note, actor):
    c = _case(conn, cid)
    _need(conn, actor, "verify", c)
    if c["state"] != "SURVIVOR_ROUTING":
        raise WorkflowError("case is not in survivor routing")
    conn.execute("UPDATE survivor_steps SET done=?, note=? WHERE id=? AND case_id=?",
                 (1 if done else 0, note or "", step_id, cid))
    audit.append(conn, actor.username, "survivor_step", cid, f"step{int(step_id)}_done{int(bool(done))}", actor.role)
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
