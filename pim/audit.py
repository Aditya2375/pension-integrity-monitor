"""Append-only, hash-chained audit trail.

Each entry stores the SHA-256 of its own content plus the previous entry's
hash. Editing or deleting any past row breaks the chain, and verify() reports
the first broken row. SQLite triggers also refuse UPDATE and DELETE.
"""
import hashlib
import json
from datetime import datetime

DDL = """
CREATE TABLE IF NOT EXISTS audit_chain (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, actor TEXT NOT NULL, role TEXT, action TEXT NOT NULL,
  case_id INTEGER, detail TEXT, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_chain_no_update BEFORE UPDATE ON audit_chain
BEGIN SELECT RAISE(ABORT, 'audit trail is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_chain_no_delete BEFORE DELETE ON audit_chain
BEGIN SELECT RAISE(ABORT, 'audit trail is append-only'); END;
"""
GENESIS = "0" * 64


def ensure(conn):
    conn.executescript(DDL)


def _digest(prev, ts, actor, role, action, case_id, detail):
    body = json.dumps([prev, ts, actor, role, action, case_id, detail], ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def append(conn, actor, action, case_id=None, detail="", role=None):
    """Add one entry. The caller commits, so the entry lands in the same
    transaction as the change it records."""
    row = conn.execute("SELECT hash FROM audit_chain ORDER BY id DESC LIMIT 1").fetchone()
    prev = row["hash"] if row else GENESIS
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    h = _digest(prev, ts, actor, role, action, case_id, detail)
    conn.execute(
        "INSERT INTO audit_chain(ts,actor,role,action,case_id,detail,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?)",
        (ts, actor, role, action, case_id, detail, prev, h))
    return h


def verify(conn):
    """Return (ok, entries_checked, first_bad_id or None)."""
    prev, n = GENESIS, 0
    for r in conn.execute("SELECT * FROM audit_chain ORDER BY id"):
        n += 1
        expect = _digest(prev, r["ts"], r["actor"], r["role"], r["action"], r["case_id"], r["detail"])
        if r["prev_hash"] != prev or r["hash"] != expect:
            return False, n, r["id"]
        prev = r["hash"]
    return True, n, None
