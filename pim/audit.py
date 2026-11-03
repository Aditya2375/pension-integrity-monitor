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


def _clean(value, fallback):
    v = _SAFE.sub("", str(value or "").replace(" ", "_"))[:150]
    return v or fallback


def ensure(conn):
    _sec.initialize(conn)


def append(conn, actor, action, case_id=None, detail="", role=None):
    """detail must be a short code such as 'FLAGGED>VERIFICATION', not prose."""
    code = _clean(action, "event") + (":" + _clean(detail, "") if detail else "")
    ref = f"case:{int(case_id)}" if case_id is not None else "system"
    return _sec.append(conn, _clean(actor, "unknown"), code[:200], ref)["event_hash"]


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
