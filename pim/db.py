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
CREATE TABLE IF NOT EXISTS pensioners (
  pensioner_id TEXT PRIMARY KEY,
  name TEXT, gender TEXT, dob TEXT, address TEXT,
  scheme TEXT, monthly_amount REAL, last_life_cert_date TEXT,
  status TEXT DEFAULT 'active', source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS death_records (
  death_id TEXT PRIMARY KEY,
  name TEXT, gender TEXT, dob TEXT, address TEXT,
  date_of_death TEXT, registrar TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS electoral (
  epic TEXT PRIMARY KEY,
  name TEXT, gender TEXT, dob TEXT, address TEXT,
  status TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS bank_activity (
  account_ref TEXT PRIMARY KEY,
  pensioner_id TEXT, name TEXT, dob TEXT,
  last_txn_date TEXT, months_inactive REAL, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS life_certs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pensioner_id TEXT, cert_date TEXT, mode TEXT, source TEXT DEFAULT 'LIVE'
);
CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  death_id TEXT, pensioner_id TEXT,
  name_pct REAL, gender_ok INTEGER, dob_match TEXT, score REAL,
  UNIQUE(death_id, pensioner_id)
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
  ts TEXT, actor TEXT, action TEXT, detail TEXT
);
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
}

DEFAULT_WEIGHTS = {
    "death_registry_match": (12.0, 0.40),
    "electoral_deletion": (4.0, 0.90),
    "bank_inactivity": (2.5, 0.85),
    "life_cert_overdue": (2.0, 0.80),
    "age_over_90": (1.5, 0.95),
}

FEEDS = {
    "pension_disburser": ("Pension disburser roll", 30),
    "death_registry": ("Civil death registry", 7),
    "electoral_roll": ("Electoral roll", 90),
    "bank_inactivity": ("Bank inactivity report", 30),
    "life_certificates": ("Life certificate feed", 30),
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
    from datetime import datetime
    conn.execute("INSERT INTO audit(ts,actor,action,detail) VALUES(?,?,?,?)",
                 (datetime.utcnow().isoformat(timespec="seconds") + "Z", actor, action, detail))
