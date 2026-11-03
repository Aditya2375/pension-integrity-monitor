"""Ingestion adapters: one per department feed. Each adapter validates a CSV
against the feed's documented schema, normalises rows, upserts them and
records feed health. Adapters never fabricate records."""
import csv, io, codecs
from datetime import datetime
from . import db

def iter_text(binary_stream, encoding="utf-8-sig"):
    """Yield decoded text lines from any binary stream with read(), in
    constant memory. Works where io.TextIOWrapper cannot (SpooledTemporaryFile)."""
    dec = codecs.getincrementaldecoder(encoding)()
    buf = ""
    while True:
        chunk = binary_stream.read(65536)
        if not chunk:
            break
        buf += dec.decode(chunk)
        lines = buf.split("\n")
        buf = lines.pop()
        for ln in lines:
            yield ln + "\n"
    buf += dec.decode(b"", final=True)
    if buf:
        yield buf

FEED_SCHEMAS = {
    "pension_master": {
        "required": ["pensioner_id", "full_name", "dob", "gender", "aadhaar_number", "pan",
                     "bank_account", "ifsc", "mobile", "address", "district", "state",
                     "scheme_code", "monthly_amount", "pension_start_date", "pension_status"],
        "optional": [],
        "table": "pension_master", "key": "pensioner_id",
        "help": "One row per pensioner. scheme_code OPS|IGNOAPS|StateWidow|EPS95; pension_status ACTIVE|STOPPED.",
    },
    "pension_disbursements": {
        "required": ["pensioner_id", "month", "amount", "credit_date", "bank_account"],
        "optional": [], "table": "pension_disbursements", "key": None,
        "help": "One row per monthly pension credit. month as yyyy-mm.",
    },
    "death_registry": {
        "required": ["registration_no", "deceased_name", "dob", "gender", "date_of_death",
                     "registration_date", "place_of_death", "district", "aadhaar_number"],
        "optional": [], "table": "death_registry", "key": "registration_no",
        "help": "One row per registered death; aadhaar_number may be blank.",
    },
    "life_certificates": {
        "required": ["pensioner_id", "certificate_id", "submission_date", "channel", "status"],
        "optional": [], "table": "life_certificates", "key": None,
        "help": "One row per submitted life certificate.",
    },
    "bank_transactions": {
        "required": ["account_number", "txn_date", "txn_type", "amount", "channel", "narration"],
        "optional": [], "table": "bank_transactions", "key": None,
        "help": "Customer-initiated transactions only; pension credits arrive via pension_disbursements.",
    },
    "telecom_activity": {
        "required": ["mobile", "month", "calls_made", "sms_sent", "data_mb", "last_activity_date"],
        "optional": [], "table": "telecom_activity", "key": None,
        "help": "One row per mobile per month.",
    },
    "toll_fastag": {
        "required": ["tag_id", "vehicle_plate", "txn_timestamp", "toll_plaza", "amount"],
        "optional": [], "table": "toll_fastag", "key": None,
        "help": "FASTag toll transactions. No pensioner-joinable field; stored for record only.",
    },
    "utility_bills": {
        "required": ["consumer_id", "consumer_name", "service_address", "month", "units_kwh", "bill_paid_date"],
        "optional": [], "table": "utility_bills", "key": None,
        "help": "One row per electricity bill; links by consumer name and service address.",
    },
    "hospital_records": {
        "required": ["patient_name", "dob", "gender", "admit_date", "discharge_date", "outcome",
                     "hospital_name", "district"],
        "optional": [], "table": "hospital_records", "key": None,
        "help": "One row per admission; outcome DIED|DISCHARGED.",
    },
    "tax_pan_activity": {
        "required": ["pan", "financial_year", "itr_filed", "filing_date"],
        "optional": [], "table": "tax_pan_activity", "key": None,
        "help": "One row per PAN per financial year.",
    },
    "electoral_roll": {
        "required": ["epic_number", "name", "dob", "gender", "address", "district", "status", "deletion_date"],
        "optional": [], "table": "electoral_roll", "key": "epic_number",
        "help": "Electoral roll extract; status ACTIVE|DELETED.",
    },
}

BLANK_OK = {"death_registry": {"aadhaar_number"}, "electoral_roll": {"deletion_date"},
           "hospital_records": {"discharge_date"}, "tax_pan_activity": {"filing_date"}}

NUMERIC = {"pension_master": ["monthly_amount"], "pension_disbursements": ["amount"],
           "bank_transactions": ["amount"], "toll_fastag": ["amount"],
           "telecom_activity": ["calls_made", "sms_sent", "data_mb"],
           "utility_bills": ["units_kwh"]}

def template_csv(feed_id):
    s = FEED_SCHEMAS[feed_id]
    return ",".join(s["required"] + s["optional"]) + "\n"

BATCH = 5000

def ingest_csv(conn, feed_id, text, source="LIVE"):
    return ingest_csv_stream(conn, feed_id, io.StringIO(text), source=source)

def ingest_csv_stream(conn, feed_id, fileobj, source="LIVE"):
    """Stream a feed CSV from any text file object in constant memory:
    batched executemany inserts, one commit per batch. Millions of rows do
    not materialise in memory."""
    if feed_id not in FEED_SCHEMAS:
        raise ValueError("unknown feed: " + feed_id)
    s = FEED_SCHEMAS[feed_id]
    reader = csv.DictReader(fileobj)
    headers = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in s["required"] if c not in headers]
    if missing:
        raise ValueError("missing required columns: " + ", ".join(missing))
    loaded = rejected = 0
    table, key = s["table"], s["key"]
    cols = s["required"] + s["optional"]
    ph = ",".join("?" for _ in cols)
    if key:
        upd = ",".join(f"{c}=excluded.{c}" for c in cols if c != key)
        sql = (f"INSERT INTO {table}({','.join(cols)},source) VALUES({ph},?) "
               f"ON CONFLICT({key}) DO UPDATE SET {upd}, source=excluded.source")
    else:
        sql = f"INSERT INTO {table}({','.join(cols)},source) VALUES({ph},?)"
    batch = []
    for row in reader:
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        blanks_allowed = BLANK_OK.get(feed_id, set())
        if any(not row.get(c, "") for c in s["required"] if c not in blanks_allowed):
            rejected += 1
            continue
        vals = []
        bad = False
        for c in cols:
            v = row.get(c, "")
            if c in NUMERIC.get(table, []) and v:
                try:
                    v = float(v)
                except ValueError:
                    bad = True
                    break
            vals.append(v)
        if bad:
            rejected += 1
            continue
        batch.append(vals + [source])
        if len(batch) >= BATCH:
            conn.executemany(sql, batch)
            conn.commit()
            loaded += len(batch)
            batch = []
    if batch:
        conn.executemany(sql, batch)
        loaded += len(batch)
    conn.execute(
        "UPDATE feeds SET last_ingest_at=?, rows_loaded=rows_loaded+?, rows_rejected=rows_rejected+? WHERE feed_id=?",
        (datetime.utcnow().isoformat(timespec="seconds") + "Z", loaded, rejected, feed_id))
    db.log(conn, "ingest", f"ingest:{feed_id}", f"loaded={loaded} rejected={rejected} source={source}")
    return loaded, rejected
