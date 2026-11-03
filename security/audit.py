"""Hash-chained audit evidence with external checkpoint verification.

A chain is NOT tamper-proof: a database administrator can rewrite all entries.
Anchor checkpoints outside the database in a department-controlled append-only
store. Only an independently retained checkpoint detects full rewrite/truncation.
No personal evidence, tokens, secrets or free-text notes in event fields.
Caller owns transaction commit so business mutation and audit entry are atomic.
"""
import hashlib
import json
from datetime import datetime, timezone

GENESIS = '0' * 64
FIELDS = ('seq', 'ts', 'actor', 'action', 'object_ref', 'prev_hash')

def _digest(event):
    raw = json.dumps({k: event[k] for k in FIELDS}, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def initialize(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS security_audit (seq INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, object_ref TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL)')
    # Defense against ordinary application UPDATE/DELETE, not a DBA boundary.
    for operation in ('UPDATE', 'DELETE'):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS no_audit_{operation.lower()} BEFORE {operation} ON security_audit BEGIN SELECT RAISE(ABORT, 'append-only audit'); END")

def append(conn, actor, action, object_ref, timestamp=None):
    for value in (actor, action, object_ref):
        if not isinstance(value, str) or not value or len(value) > 200 or any(ord(ch) < 32 for ch in value):
            raise ValueError('Audit fields must be bounded identifiers')
    # Acquire the write lock before looking at the tail, including when the
    # caller is already in a deferred transaction. Caller must handle rollback.
    conn.execute('UPDATE security_audit SET seq=seq WHERE 0')
    tail = conn.execute('SELECT seq,event_hash FROM security_audit ORDER BY seq DESC LIMIT 1').fetchone()
    event = dict(seq=(tail[0] + 1 if tail else 1),
                 ts=timestamp or datetime.now(timezone.utc).isoformat(timespec='seconds'),
                 actor=actor, action=action, object_ref=object_ref,
                 prev_hash=tail[1] if tail else GENESIS)
    event['event_hash'] = _digest(event)
    conn.execute('INSERT INTO security_audit VALUES(?,?,?,?,?,?,?)', tuple(event[k] for k in FIELDS) + (event['event_hash'],))
    return event

def verify(events, checkpoint=None):
    """Return (valid, reason). checkpoint is independently stored (seq, hash)."""
    prev, seq = GENESIS, 0
    seen = checkpoint is None
    for event in events:
        if (event['seq'] != seq + 1 or event['prev_hash'] != prev
                or event['event_hash'] != _digest(event)):
            return False, 'chain mismatch'
        seq, prev = event['seq'], event['event_hash']
        if checkpoint and seq == checkpoint[0]:
            if prev != checkpoint[1]:
                return False, 'checkpoint mismatch'
            seen = True
    return (True, 'verified') if seen else (False, 'checkpoint missing or chain truncated')
