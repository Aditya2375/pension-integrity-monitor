"""Thin adapter over security.audit (the reviewed hash-chained, append-only
store). Events hold bounded identifiers only: actor, action code, object ref.
Free-text reasons and notes live in their own tables, never in the chain.

A chain on its own does not stop a database administrator rewriting every
row. Export checkpoints (seq, hash) with checkpoint() to an independent
append-only store and pass them to verify().
"""
import re
from security import audit as _sec

_SAFE = re.compile(r"[^A-Za-z0-9_.:>=\-]")


# Fixed vocabulary. Nothing a person typed can reach the chain: actions come
# from this list and details from the shapes below.
ACTIONS = frozenset({
    "login", "login_failed", "start_review", "verify_step", "note", "dismiss", "auto_to_verification",
    "propose_hold", "propose_confirm_death", "approve_hold", "approve_death", "reject_hold",
    "reject_confirm_death", "suspend", "release", "appeal_filed", "appeal_upheld", "appeal_reversed",
    "survivor_step", "survivor_routing_complete", "finalize_death", "reopen", "late_appeal_accepted", "evidence_released", "reinstatement_requested", "evidence_viewed",
    "queue_export", "settings_changed", "session_revoked", "evidence_uploaded", "portal_code_requested", "user_created"})
_DETAIL = re.compile(r"^([A-Z_]+>[A-Z_]+|(step|evidence)\d+(_done[01])?|PROVISIONAL|FULL|)$")


def _clean(value, fallback):
    v = _SAFE.sub("", str(value or "").replace(" ", "_"))[:150]
    return v or fallback


def ensure(conn):
    _sec.initialize(conn)


def append(conn, actor, action, case_id=None, detail="", role=None):
    """detail must be a short code such as 'FLAGGED>VERIFICATION', not prose."""
    if action not in ACTIONS:
        raise ValueError("audit action is not in the fixed vocabulary")
    detail = str(detail or "").replace("=", "").replace(" ", "_")
    if not _DETAIL.match(detail):
        raise ValueError("audit detail must be a fixed code")
    code = action + (":" + detail if detail else "")
    ref = f"case:{int(case_id)}" if case_id is not None else "system"
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}", actor or ""):
        raise ValueError("audit actor must be an exact user identifier")   # never rewrite an identity
    return _sec.append(conn, actor, code[:200], ref)["event_hash"]


def events(conn):
    cur = conn.execute("SELECT seq,ts,actor,action,object_ref,prev_hash,event_hash FROM security_audit ORDER BY seq")
    return [dict(zip(("seq", "ts", "actor", "action", "object_ref", "prev_hash", "event_hash"), r)) for r in cur]


def checkpoint(conn):
    """(seq, hash) of the latest entry, to store outside the database."""
    row = conn.execute("SELECT seq,event_hash FROM security_audit ORDER BY seq DESC LIMIT 1").fetchone()
    return (row[0], row[1]) if row else None


def verify(conn, cp=None):
    ok, reason = _sec.verify(events(conn), cp)
    return ok, reason
