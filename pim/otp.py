"""One-time codes for the family portal. Codes are stored hashed, expire in
10 minutes, allow 5 wrong tries, and are delivered through the notification
outbox to the contact on record, never shown on screen unless the explicit
synthetic-demo switch is on."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from . import notify

TTL_MIN, MAX_TRIES = 10, 5
DDL = """
CREATE TABLE IF NOT EXISTS otp_codes (
  tracking_id TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
  tries INTEGER NOT NULL DEFAULT 0
);
"""


def ensure(conn):
    conn.executescript(DDL)


def _h(code, tid):
    return hashlib.sha256(f"{tid}:{code}".encode()).hexdigest()


def _now():
    return datetime.utcnow()


def issue(conn, tracking_id, lang="en"):
    """Create a code for a real tracking ID. Returns the code (only the demo
    switch ever shows it) or None when the reference is unknown."""
    row = conn.execute("SELECT case_id FROM appeals WHERE tracking_id=?", (tracking_id,)).fetchone()
    if not row:
        return None
    code = f"{secrets.randbelow(10**6):06d}"
    exp = (_now() + timedelta(minutes=TTL_MIN)).isoformat(timespec="seconds")
    conn.execute("INSERT OR REPLACE INTO otp_codes(tracking_id,code_hash,expires_at,tries) VALUES(?,?,?,0)",
                 (tracking_id, _h(code, tracking_id), exp))
    notify.enqueue(conn, row["case_id"], "otp", {"code": code}, lang=lang)
    return code


def check(conn, tracking_id, code):
    r = conn.execute("SELECT * FROM otp_codes WHERE tracking_id=?", (tracking_id,)).fetchone()
    if not r or r["tries"] >= MAX_TRIES or _now() > datetime.fromisoformat(r["expires_at"]):
        return False
    conn.execute("UPDATE otp_codes SET tries=tries+1 WHERE tracking_id=?", (tracking_id,))
    if hmac.compare_digest(_h((code or "").strip(), tracking_id), r["code_hash"]):
        conn.execute("DELETE FROM otp_codes WHERE tracking_id=?", (tracking_id,))
        return True
    return False
