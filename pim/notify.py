"""Notification outbox. The workflow writes a message here in the same
transaction as the state change. A delivery adapter (SMS, email, post) reads
the outbox and reports back. This module sends nothing itself.

The outbox stores a template code, the case reference and non-personal
parameters. Recipient contact details are resolved by the adapter from the
source system at send time, so no phone number or address is copied here.
"""
import json
from datetime import datetime
from . import i18n

DDL = """
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, template TEXT NOT NULL,
  params TEXT NOT NULL, lang TEXT NOT NULL DEFAULT 'en', channel TEXT NOT NULL DEFAULT 'sms',
  created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
  attempts INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT, last_error TEXT
);
"""
MAX_ATTEMPTS = 5
TEMPLATES = ("notice_issued", "death_notice_issued", "death_finalized", "appeal_received", "appeal_reversed", "appeal_upheld", "otp")


def ensure(conn):
    conn.executescript(DDL)


def _now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def enqueue(conn, case_id, template, params, lang="en", channel="sms"):
    if template not in TEMPLATES:
        raise ValueError("unknown template")
    conn.execute("INSERT INTO notifications(case_id,template,params,lang,channel,created_at) VALUES(?,?,?,?,?,?)",
                 (case_id, template, json.dumps(params, sort_keys=True), lang, channel, _now()))


def render(row):
    return i18n.t("msg_" + row["template"], row["lang"], **json.loads(row["params"]))


def pending(conn, limit=100):
    return conn.execute("SELECT * FROM notifications WHERE status='PENDING' AND attempts<? ORDER BY id LIMIT ?",
                        (MAX_ATTEMPTS, limit)).fetchall()


def mark_sent(conn, nid):
    conn.execute("UPDATE notifications SET params='{}' WHERE id=? AND template='otp'", (nid,))  # drop the code once sent
    conn.execute("UPDATE notifications SET status='SENT', last_attempt_at=?, attempts=attempts+1 WHERE id=?", (_now(), nid))


def mark_failed(conn, nid, error):
    conn.execute("UPDATE notifications SET attempts=attempts+1, last_attempt_at=?, last_error=?, "
                 "status=CASE WHEN attempts+1>=? THEN 'FAILED' ELSE 'PENDING' END WHERE id=?",
                 (_now(), str(error)[:200], MAX_ATTEMPTS, nid))


class Adapter:
    """Interface for the integration lane. send() returns on success and
    raises on failure. Implementations look up the recipient themselves."""
    def send(self, notification_row, text):
        raise NotImplementedError


def deliver(conn, adapter):
    sent = 0
    for row in pending(conn):
        try:
            adapter.send(row, render(row))
            mark_sent(conn, row["id"])
            sent += 1
        except Exception as e:  # noqa: BLE001 - adapter errors are recorded, not raised
            mark_failed(conn, row["id"], e)
    conn.commit()
    return sent
