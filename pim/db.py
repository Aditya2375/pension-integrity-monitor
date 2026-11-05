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
CREATE TABLE IF NOT EXISTS hold_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER, requester TEXT, reasons TEXT, requested_at TEXT,
  state TEXT DEFAULT 'PENDING', snapshot_hash TEXT
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
    conn.execute("INSERT INTO audit(ts,actor,action,detail,prev_hash,hash) VALUES(?,?,?,?,?,?)",
                 (ts, actor, action, detail, prev_hash, h))

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
    return True, None, len(rows)
