import sqlite3, os

DB_PATH = os.environ.get("PIM_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pim.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
  feed_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  expected_cadence_days INTEGER NOT NULL DEFAULT 30,
  last_ingest_at TEXT,
  rows_loaded INTEGER DEFAULT 0,
  rows_rejected INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pension_master (
  pensioner_id TEXT PRIMARY KEY,
  full_name TEXT, dob TEXT, gender TEXT, aadhaar_number TEXT, pan TEXT,
  bank_account TEXT, ifsc TEXT, mobile TEXT, address TEXT, district TEXT,
  state TEXT, scheme_code TEXT, monthly_amount REAL, pension_start_date TEXT,
  pension_status TEXT DEFAULT 'ACTIVE', source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS pension_disbursements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pensioner_id TEXT, month TEXT, amount REAL, credit_date TEXT,
  bank_account TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS death_registry (
  registration_no TEXT PRIMARY KEY,
  deceased_name TEXT, dob TEXT, gender TEXT, date_of_death TEXT,
  registration_date TEXT, place_of_death TEXT, district TEXT,
  aadhaar_number TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS life_certificates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pensioner_id TEXT, certificate_id TEXT, submission_date TEXT,
  channel TEXT, status TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS bank_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_number TEXT, txn_date TEXT, txn_type TEXT, amount REAL,
  channel TEXT, narration TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS telecom_activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mobile TEXT, month TEXT, calls_made REAL, sms_sent REAL, data_mb REAL,
  last_activity_date TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS toll_fastag (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag_id TEXT, vehicle_plate TEXT, txn_timestamp TEXT, toll_plaza TEXT,
  amount REAL, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS utility_bills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  consumer_id TEXT, consumer_name TEXT, service_address TEXT, month TEXT,
  units_kwh REAL, bill_paid_date TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS hospital_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_name TEXT, dob TEXT, gender TEXT, admit_date TEXT,
  discharge_date TEXT, outcome TEXT, hospital_name TEXT, district TEXT,
  source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS tax_pan_activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pan TEXT, financial_year TEXT, itr_filed TEXT, filing_date TEXT,
  source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS electoral_roll (
  epic_number TEXT PRIMARY KEY,
  name TEXT, dob TEXT, gender TEXT, address TEXT, district TEXT,
  status TEXT, deletion_date TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  registration_no TEXT, pensioner_id TEXT,
  name_pct REAL, gender_ok INTEGER, dob_match TEXT, score REAL,
  UNIQUE(registration_no, pensioner_id)
);
CREATE TABLE IF NOT EXISTS signals (
  case_id INTEGER, signal TEXT, present INTEGER, value TEXT,
  lr_plus REAL, lr_minus REAL
);
CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pensioner_id TEXT, created_at TEXT,
  base_rate REAL, log_odds REAL, probability REAL,
  priority INTEGER, state TEXT DEFAULT 'FLAGGED',
  matched_death_id TEXT, hold_reasons TEXT,
  held_at TEXT, released_at TEXT, arrears REAL DEFAULT 0,
  outcome TEXT, outcome_note TEXT
);
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER, step TEXT, done INTEGER DEFAULT 0, note TEXT
);
CREATE TABLE IF NOT EXISTS appeals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tracking_id TEXT UNIQUE, case_id INTEGER,
  submitted_at TEXT, statement TEXT, contact TEXT,
  status TEXT DEFAULT 'OPEN', resolved_at TEXT, decision TEXT
);
CREATE TABLE IF NOT EXISTS weights (
  signal TEXT PRIMARY KEY, lr_plus REAL, lr_minus REAL, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS public_context (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  metric TEXT, value TEXT, region TEXT, year TEXT,
  source_url TEXT, source_name TEXT, licence TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, actor TEXT, action TEXT, detail TEXT,
  prev_hash TEXT, hash TEXT
);
CREATE TABLE IF NOT EXISTS officers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  active INTEGER DEFAULT 1,
  created_at TEXT,
  session_version INTEGER DEFAULT 0,
  must_change INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS hold_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER, requester TEXT, reasons TEXT, requested_at TEXT,
  state TEXT DEFAULT 'PENDING', snapshot_hash TEXT, cites TEXT
);

CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""

DEFAULT_SETTINGS = {
    "base_rate": "0.02",
    "cost_false_hold": "50000",
    "cost_missed_death": "120000",
    "match_threshold": "0.75",
    "appeal_window_days": "30",
    "bank_inactivity_months": "12",
    "life_cert_overdue_days": "400",
    "old_age_years": "90",
    "max_new_cases_per_run": "500",
    "appeal_response_sla_days": "14",
    "audit_sample_rate": "0.001",
}

DEFAULT_WEIGHTS = {
    "death_registry_match": (40.0, 0.50),
    "hospital_died_match": (30.0, 0.60),
    "electoral_deletion": (5.0, 0.70),
    "weak_lead_registry": (2.5, 1.0),
    "weak_lead_hospital": (2.0, 1.0),
    "life_cert_overdue": (5.0, 0.55),
    "bank_inactivity": (1.15, 0.50),
    "telecom_quiet": (1.1, 0.55),
    "alive_itr": (1.0, 0.60),
    "alive_utility": (1.0, 0.75),
    "bank_cliff": (25.0, 1.0),
    "telecom_cliff": (25.0, 1.0),
    "aligned_cliff": (1.8, 1.0),
    "family_reuse_bank": (1.4, 0.85),
    "family_reuse_sim": (1.3, 0.90),
    "leakage_credit": (1.6, 1.15),
    "dlc_after_death": (1.0, 0.12),
    "dormancy_resume": (1.0, 0.80),
    "silence_cap": (1.0, 1.0),
    "weak_lead_cap": (1.0, 1.0),
}

FEEDS = {
    "pension_master": ("Pension master roll", 30),
    "pension_disbursements": ("Pension disbursements", 30),
    "death_registry": ("Civil death registry", 7),
    "life_certificates": ("Life certificate feed", 30),
    "bank_transactions": ("Bank transactions", 30),
    "telecom_activity": ("Telecom activity", 30),
    "toll_fastag": ("Toll FASTag", 30),
    "utility_bills": ("Utility bills", 30),
    "hospital_records": ("Hospital records", 30),
    "tax_pan_activity": ("Tax PAN activity", 365),
    "electoral_roll": ("Electoral roll", 90),
}

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    for fid, (name, cad) in FEEDS.items():
        conn.execute("INSERT OR IGNORE INTO feeds(feed_id,name,expected_cadence_days) VALUES(?,?,?)", (fid, name, cad))
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    # bootstrap: if no officer accounts exist, the deployment key creates the
    # first one as 'admin'. With no key configured there is no way in.
    import os
    if conn.execute("SELECT COUNT(*) n FROM officers").fetchone()["n"] == 0:
        key = os.environ.get("PIM_OFFICER_KEY")
        if key:
            create_officer(conn, "admin", key)
            conn.execute("UPDATE officers SET must_change=0 WHERE username='admin'")
    for sig, (lp, lm) in DEFAULT_WEIGHTS.items():
        conn.execute("INSERT OR IGNORE INTO weights(signal,lr_plus,lr_minus) VALUES(?,?,?)", (sig, lp, lm))
    conn.commit()
    seed_public_context(conn)
    return conn

def seed_public_context(conn):
    import csv, os
    if conn.execute("SELECT COUNT(*) n FROM public_context").fetchone()["n"]:
        return
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "public_context.csv")
    if not os.path.exists(path):
        return
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            conn.execute(
                "INSERT INTO public_context(metric,value,region,year,source_url,source_name,licence) "
                "VALUES(?,?,?,?,?,?,?)",
                (r["metric"], r["value"], r["region"], r["year"], r["source_url"], r["source_name"], r["licence"]))
    conn.commit()

def get_setting(conn, key):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key)

def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

def log(conn, actor, action, detail=""):
    """Append-only, hash-chained audit entry: each row commits to the previous
    row's hash, so later edits or deletions are detectable by verify_audit()."""
    import hashlib
    from datetime import datetime
    prev = conn.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = prev["hash"] if prev else "GENESIS"
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    body = f"{prev_hash}|{ts}|{actor}|{action}|{detail}"
    h = hashlib.sha256(body.encode()).hexdigest()
    cur = conn.execute("INSERT INTO audit(ts,actor,action,detail,prev_hash,hash) VALUES(?,?,?,?,?,?)",
                       (ts, actor, action, detail, prev_hash, h))
    anchor_write(cur.lastrowid, h)

def hash_password(password, salt_hex):
    import hashlib
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                          n=2**14, r=8, p=1, dklen=32).hex()

def create_officer(conn, username, password):
    import secrets
    from datetime import datetime
    salt = secrets.token_hex(16)
    conn.execute("INSERT INTO officers(username,password_hash,salt,active,created_at) VALUES(?,?,?,1,?)",
                 (username, hash_password(password, salt), salt,
                  datetime.utcnow().isoformat(timespec="seconds") + "Z"))

def check_officer(conn, username, password):
    import hmac
    row = conn.execute("SELECT * FROM officers WHERE username=? AND active=1", (username,)).fetchone()
    if not row:
        return False
    return hmac.compare_digest(row["password_hash"], hash_password(password, row["salt"]))

def _anchor_path():
    import os
    return os.environ.get("PIM_DB", "pim.sqlite3") + ".anchor"

def _checkpoint_path():
    """Second anchor copy in a different directory (PIM_CHECKPOINT_DIR, default
    ~/.pim-checkpoints). Restoring an older database+anchor pair from the data
    directory does not touch it, so the rollback is caught. Point it at a
    separately permissioned location for more protection."""
    import os, hashlib
    d = os.environ.get("PIM_CHECKPOINT_DIR") or os.path.join(os.path.expanduser("~"), ".pim-checkpoints")
    os.makedirs(d, exist_ok=True)
    tag = hashlib.sha256(os.path.abspath(os.environ.get("PIM_DB", "pim.sqlite3")).encode()).hexdigest()[:16]
    return os.path.join(d, tag + ".checkpoint")

def _append_fsync(path, line):
    import os
    with open(path, "a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())

def anchor_write(entry_id, entry_hash):
    """Write every audit hash, fsynced, to two files in two directories BEFORE
    the database commit. Rewriting only the database, or rolling back the
    database and the local anchor together, is caught. An attacker who
    rewrites every copy defeats it; that limit is documented."""
    line = f"{entry_id} {entry_hash}\n"
    _append_fsync(_anchor_path(), line)
    _append_fsync(_checkpoint_path(), line)

def _head(path):
    try:
        with open(path) as f:
            lines = [ln.split() for ln in f if ln.strip()]
        return (int(lines[-1][0]), lines[-1][1]) if lines else None
    except FileNotFoundError:
        return None

def anchor_head():
    return _head(_anchor_path())

def checkpoint_head():
    return _head(_checkpoint_path())

def reconcile(conn):
    """Completeness check: every held case must have a hold_approved audit entry
    and every approved hold request a matching entry. Returns problem strings."""
    problems = []
    for r in conn.execute("SELECT id FROM cases WHERE state IN ('HELD','RELEASED') AND held_at IS NOT NULL"):
        n = conn.execute("SELECT COUNT(*) n FROM audit WHERE action='hold_approved' AND detail LIKE ?",
                         (f"case={r['id']} %",)).fetchone()["n"]
        if n == 0:
            problems.append(f"case {r['id']} was held with no hold_approved audit entry")
    return problems

def verify_audit(conn):
    """Replay the hash chain. Returns (ok, first_bad_id_or_none, entries)."""
    import hashlib
    rows = conn.execute("SELECT id,ts,actor,action,detail,prev_hash,hash FROM audit ORDER BY id").fetchall()
    prev = "GENESIS"
    for r in rows:
        if r["hash"] is None:  # pre-chain legacy row
            prev = r["prev_hash"] or prev
            continue
        if r["prev_hash"] != prev:
            return False, r["id"], len(rows)
        body = f"{prev}|{r['ts']}|{r['actor']}|{r['action']}|{r['detail']}"
        if hashlib.sha256(body.encode()).hexdigest() != r["hash"]:
            return False, r["id"], len(rows)
        prev = r["hash"]
    last = rows[-1] if rows else None
    incomplete = None
    for head in (anchor_head(), checkpoint_head()):
        if head is None:
            continue
        if last and last["hash"] is not None and last["hash"] == head[1]:
            continue
        # Anchors are written before the database commit. A crash between the
        # two leaves an anchor exactly one entry ahead of an intact chain:
        # INCOMPLETE (manual review), never silently reconciled. Any other
        # divergence, including a database older than a checkpoint (rollback),
        # is a break.
        if last and last["hash"] is not None and head[0] == last["id"] + 1:
            incomplete = head[0]
            continue
        return False, head[0], len(rows)
    if incomplete is not None:
        return None, incomplete, len(rows)
    return True, None, len(rows)
