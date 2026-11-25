"""One-time codes for the family portal. Codes are stored hashed, expire in
10 minutes, allow 5 wrong tries, and are delivered through the notification
outbox to the contact on record, never shown on screen unless the explicit
synthetic-demo switch is on."""
import hashlib
import hmac
import os
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


# A six-digit code has only a million values, so an unkeyed hash can be
# reversed instantly if the database leaks. Codes are stored as HMAC-SHA256
# under a server-side key derived from PIM_SECRET (a random per-boot key when
# it is unset, like the session key; codes then do not survive a restart).
_KEY = hashlib.sha256(b"pim-otp-v1|" + (os.environ.get("PIM_SECRET") or secrets.token_hex(32)).encode()).digest()


def _h(code, tid):
    return hmac.new(_KEY, f"{tid}:{code}".encode(), hashlib.sha256).hexdigest()


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
    """Redeem a code. Each statement is atomic and the final DELETE decides:
    of two simultaneous correct submissions exactly one deletes the row and
    wins. A wrong try is counted before the comparison, so tries cannot be
    skipped by racing."""
    now = _now().isoformat(timespec="seconds")
    counted = conn.execute("UPDATE otp_codes SET tries=tries+1 WHERE tracking_id=? AND tries<? AND expires_at>?",
                           (tracking_id, MAX_TRIES, now)).rowcount
    if counted != 1:
        return False
    won = conn.execute("DELETE FROM otp_codes WHERE tracking_id=? AND code_hash=? AND expires_at>?",
                       (tracking_id, _h((code or "").strip(), tracking_id), now)).rowcount
    return won == 1


GRANT_TTL_MIN = 30
GRANT_DDL = """
CREATE TABLE IF NOT EXISTS portal_grants (
  token_hash TEXT PRIMARY KEY, tracking_id TEXT NOT NULL, expires_at TEXT NOT NULL
);
"""


def grant(conn, tracking_id):
    """After a correct code: a short-lived server-side grant. The browser
    holds only a random token; expiry and revocation are decided here."""
    conn.executescript(GRANT_DDL)
    token = secrets.token_urlsafe(32)
    exp = (_now() + timedelta(minutes=GRANT_TTL_MIN)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM portal_grants WHERE expires_at<=?", (_now().isoformat(timespec="seconds"),))
    conn.execute("INSERT INTO portal_grants(token_hash,tracking_id,expires_at) VALUES(?,?,?)",
                 (hashlib.sha256(token.encode()).hexdigest(), tracking_id, exp))
    return token


def grant_tid(conn, token):
    """Tracking ID for a live grant, else None."""
    if not token:
        return None
    conn.executescript(GRANT_DDL)
    r = conn.execute("SELECT tracking_id FROM portal_grants WHERE token_hash=? AND expires_at>?",
                     (hashlib.sha256(str(token).encode()).hexdigest(), _now().isoformat(timespec="seconds"))).fetchone()
    return r["tracking_id"] if r else None


def consume_grant(conn, token):
    """Single use: returns True only for the one caller that deletes it."""
    if not token:
        return False
    return conn.execute("DELETE FROM portal_grants WHERE token_hash=? AND expires_at>?",
                        (hashlib.sha256(str(token).encode()).hexdigest(), _now().isoformat(timespec="seconds"))).rowcount == 1


def revoke_grant(conn, token):
    if token:
        conn.execute("DELETE FROM portal_grants WHERE token_hash=?", (hashlib.sha256(str(token).encode()).hexdigest(),))
