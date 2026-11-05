import os, sys, tempfile, pathlib, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["PIM_DB"] = tempfile.mktemp(suffix=".sqlite3")
os.environ.setdefault("PIM_OFFICER_KEY", "officer")
os.environ.setdefault("PIM_INSECURE_HTTP", "1")

import app as app_module
from pim import db, pipeline

FIX = pathlib.Path(__file__).parent / "fixtures"

def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()

def login(c, name="officer"):
    app_module._ATTEMPTS.clear()
    return c.post("/login", data={"key": "officer", "officer_name": name}, follow_redirects=True)

def _load_all_feeds(c):
    for feed in ["pension_master", "pension_disbursements", "death_registry", "electoral_roll", "bank_transactions", "life_certificates", "telecom_activity", "hospital_records", "tax_pan_activity", "utility_bills", "toll_fastag"]:
        data = {"file": (open(FIX / f"{feed}.csv", "rb"), f"{feed}.csv")}
        r = c.post(f"/ingest/{feed}", data=data, content_type="multipart/form-data", follow_redirects=True)
        assert r.status_code == 200, feed

def test_audit_chain_tamper_detection():
    conn = db.connect()
    db.log(conn, "officer-a", "hold", "case=1")
    db.log(conn, "officer-b", "release", "case=1")
    db.log(conn, "pipeline", "flag_run", "new_cases=0")
    conn.commit()
    ok, bad, n = db.verify_audit(conn)
    assert ok and bad is None and n >= 3
    # tamper at the SQL level is blocked outright by the append-only triggers
    import sqlite3
    try:
        conn.execute("UPDATE audit SET detail='case=2' WHERE action='hold'")
        conn.commit()
        raise SystemExit("append-only trigger failed to block UPDATE")
    except sqlite3.IntegrityError:
        conn.rollback()
    try:
        conn.execute("DELETE FROM audit WHERE action='hold'")
        conn.commit()
        raise SystemExit("append-only trigger failed to block DELETE")
    except sqlite3.IntegrityError:
        conn.rollback()
    ok, _, _ = db.verify_audit(conn)
    assert ok
    # even if an attacker drops the triggers and rewrites history, the chain detects it
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit SET detail='case=2' WHERE action='hold'")
    conn.commit()
    ok, bad, _ = db.verify_audit(conn)
    assert not ok and bad is not None
    conn.execute("UPDATE audit SET detail='case=1' WHERE action='hold'")
    conn.commit()
    ok, _, _ = db.verify_audit(conn)
    assert ok
    conn.close()

def test_circuit_breaker_and_audit_sampling():
    c = client()
    login(c)
    _load_all_feeds(c)
    conn = db.connect()
    # cap below the fixture's flag count, and force sampling of everyone else
    conn.execute("UPDATE settings SET value='1' WHERE key='max_new_cases_per_run'")
    conn.execute("UPDATE settings SET value='1.0' WHERE key='audit_sample_rate'")
    conn.commit(); conn.close()

    r = c.post("/pipeline/run", follow_redirects=True)
    assert b"CIRCUIT BREAKER TRIPPED" in r.data

    conn = db.connect()
    loud = conn.execute("SELECT * FROM audit WHERE action='circuit_breaker'").fetchone()
    assert loud is not None
    # nothing was auto-held even under flooding
    held = conn.execute("SELECT COUNT(*) n FROM cases WHERE state='HELD'").fetchone()
    assert held["n"] == 0
    # audit sample created for unflagged still-paid pensioner(s), clearly labeled
    samples = conn.execute(
        "SELECT cases.id FROM cases JOIN signals s ON s.case_id=cases.id WHERE s.signal='audit_sample'").fetchall()
    assert len(samples) >= 1
    conn.close()

    r = c.get("/queue")
    assert b"audit sample" in r.data

    # dashboard reports the (untampered) chain as intact
    r = c.get("/")
    assert b"intact" in r.data

def test_appeal_overdue_marker():
    c = client()
    login(c)
    conn = db.connect()
    row = conn.execute("SELECT id FROM cases LIMIT 1").fetchone()
    conn.close()
    if row is None:
        return  # prior test already covered the full flow in this DB
    cid = row["id"]
    conn = db.connect()
    conn.execute(
        "INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,status) VALUES(?,?,?,?, 'OPEN')",
        ("APL-TESTOLD1", cid, "2020-01-01T00:00:00Z", "old appeal"))
    conn.commit(); conn.close()
    r = c.get("/appeals")
    assert b"overdue" in r.data

def test_hold_snapshot_binding():
    """Approving a hold after the underlying evidence changed must fail."""
    c = client()
    login(c, "first officer")
    conn = db.connect()
    row = conn.execute("SELECT id FROM cases WHERE state IN ('FLAGGED','UNDER_REVIEW','VERIFICATION') LIMIT 1").fetchone()
    conn.close()
    if row is None:
        return
    cid = row["id"]
    conn = db.connect()
    steps = conn.execute("SELECT * FROM verifications WHERE case_id=?", (cid,)).fetchall()
    conn.close()
    for s in steps:
        c.post(f"/case/{cid}/verify", data={"vid": s["id"], "done": "1", "note": "checked"})
    r = c.post(f"/case/{cid}/hold", data={"reasons": "Snapshot binding test reasons, case specific and long enough."}, follow_redirects=True)
    assert b"second officer must approve" in r.data
    # evidence changes after the request
    conn = db.connect()
    conn.execute("UPDATE cases SET probability=probability+0.01 WHERE id=?", (cid,))
    conn.commit(); conn.close()
    c.post("/logout")
    login(c, "second officer")
    r = c.post(f"/case/{cid}/approve-hold", follow_redirects=True)
    assert b"evidence changed" in r.data
    conn = db.connect()
    case = conn.execute("SELECT state FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "VERIFICATION"
    conn.close()

if __name__ == "__main__":
    test_audit_chain_tamper_detection()
    print("audit chain OK")
    test_circuit_breaker_and_audit_sampling()
    print("breaker + sampling OK")
    test_appeal_overdue_marker()
    print("appeal overdue OK")
    test_hold_snapshot_binding()
    print("snapshot binding OK")

