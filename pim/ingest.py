"""Ingestion adapters: one per department feed. Each adapter validates a CSV
against the feed's documented schema, normalises rows, upserts them and
records feed health. Adapters never fabricate records."""
import csv, io
from datetime import datetime
from . import db

FEED_SCHEMAS = {
    "pension_disburser": {
        "required": ["pensioner_id", "name", "gender", "dob", "scheme", "monthly_amount"],
        "optional": ["address", "last_life_cert_date"],
        "table": "pensioners",
        "key": "pensioner_id",
        "help": "One row per pensioner on the disburser's roll. dob as YYYY-MM-DD or DD-MM-YYYY.",
    },
    "death_registry": {
        "required": ["death_id", "name", "gender", "dob", "date_of_death"],
        "optional": ["address", "registrar"],
        "table": "death_records",
        "key": "death_id",
        "help": "One row per registered death from the civil registry.",
    },
    "electoral_roll": {
        "required": ["epic", "name", "gender", "dob", "status"],
        "optional": ["address"],
        "table": "electoral",
        "key": "epic",
        "help": "Electoral roll extract; status is active or deleted.",
    },
    "bank_inactivity": {
        "required": ["account_ref", "pensioner_id", "months_inactive"],
        "optional": ["name", "dob", "last_txn_date"],
        "table": "bank_activity",
        "key": "account_ref",
        "help": "One row per pension bank account, with months since last customer transaction.",
    },
    "life_certificates": {
        "required": ["pensioner_id", "cert_date"],
        "optional": ["mode"],
        "table": "life_certs",
        "key": None,
        "help": "One row per submitted life certificate (DLC), mode face/manual/camp.",
    },
}

def template_csv(feed_id):
    s = FEED_SCHEMAS[feed_id]
    return ",".join(s["required"] + s["optional"]) + "\n"

def _row_ok(feed_id, row):
    s = FEED_SCHEMAS[feed_id]
    for col in s["required"]:
        if not (row.get(col) or "").strip():
            return False
    return True

def ingest_csv(conn, feed_id, text, source="LIVE"):
    if feed_id not in FEED_SCHEMAS:
        raise ValueError("unknown feed: " + feed_id)
    s = FEED_SCHEMAS[feed_id]
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in s["required"] if c not in headers]
    if missing:
        raise ValueError("missing required columns: " + ", ".join(missing))
    loaded = rejected = 0
    table, key = s["table"], s["key"]
    for row in reader:
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if not _row_ok(feed_id, row):
            rejected += 1
            continue
        cols = s["required"] + s["optional"]
        vals = [row.get(c, "") for c in cols]
        if table == "pensioners":
            if "monthly_amount" in row:
                try:
                    vals[cols.index("monthly_amount")] = float(row["monthly_amount"])
                except ValueError:
                    rejected += 1
                    continue
        if key:
            ph = ",".join("?" for _ in cols)
            upd = ",".join(f"{c}=excluded.{c}" for c in cols if c != key)
            conn.execute(
                f"INSERT INTO {table}({','.join(cols)},source) VALUES({ph},?) "
                f"ON CONFLICT({key}) DO UPDATE SET {upd}, source=excluded.source",
                vals + [source])
        else:
            ph = ",".join("?" for _ in cols)
            conn.execute(f"INSERT INTO {table}({','.join(cols)},source) VALUES({ph},?)", vals + [source])
        loaded += 1
    conn.execute(
        "UPDATE feeds SET last_ingest_at=?, rows_loaded=rows_loaded+?, rows_rejected=rows_rejected+? WHERE feed_id=?",
        (datetime.utcnow().isoformat(timespec="seconds") + "Z", loaded, rejected, feed_id))
    db.log(conn, "ingest", f"ingest:{feed_id}", f"loaded={loaded} rejected={rejected} source={source}")
    return loaded, rejected
