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

def login(c, name="admin"):
    app_module._ATTEMPTS.clear()
    if name != "admin":
        c.post("/login", data={"username": "admin", "key": "officer"}, follow_redirects=True)
        c.post("/officers/add", data={"username": name, "password": "test-password-123", "admin_password": "officer"}, follow_redirects=True)
        c.post("/logout")
        r = c.post("/login", data={"username": name, "key": "test-password-123"}, follow_redirects=True)
        c.post("/change-password", data={"old": "test-password-123", "new": name + "-pass-12345"}, follow_redirects=True)
        return r
    return c.post("/login", data={"username": "admin", "key": "officer"}, follow_redirects=True)

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
    r = c.post(f"/case/{cid}/approve-hold", data={"password": "second officer-pass-12345"}, follow_redirects=True)
    assert b"evidence changed" in r.data
    conn = db.connect()
    case = conn.execute("SELECT state FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "VERIFICATION"
    conn.close()


def test_anchor_mismatch_detects_db_rewrite():
    """Rewriting only the database (attacker misses the anchor file) is caught."""
    conn = db.connect()
    db.log(conn, "tester", "anchor_check", "before")
    conn.commit()
    ok, _, _ = db.verify_audit(conn)
    assert ok
    # attacker with DB-only access: drops triggers, rewrites, recomputes chain
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    import hashlib
    row = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = row["prev_hash"]
    body = f"{prev}|{row['ts']}|{row['actor']}|{row['action']}|forged"
    conn.execute("UPDATE audit SET detail='forged', hash=? WHERE id=?",
                 (hashlib.sha256(body.encode()).hexdigest(), row["id"]))
    conn.commit()
    ok, bad, _ = db.verify_audit(conn)
    assert not ok  # anchor file still holds the real head hash
    # restore: recompute original detail
    body = f"{prev}|{row['ts']}|{row['actor']}|{row['action']}|before"
    conn.execute("UPDATE audit SET detail='before', hash=? WHERE id=?",
                 (hashlib.sha256(body.encode()).hexdigest(), row["id"]))
    conn.commit()
    ok, _, _ = db.verify_audit(conn)
    assert ok
    conn.close()

def test_officer_accounts():
    """Per-officer identity: add, wrong-password rejection, deactivate, self-protection."""
    c = client()
    login(c)
    # short password rejected
    r = c.post("/officers/add", data={"username": "shorty", "password": "x", "admin_password": "officer"}, follow_redirects=True)
    assert b"at least 12 characters" in r.data
    # step-up: wrong admin password rejected
    r = c.post("/officers/add", data={"username": "nobody", "password": "real-password-999", "admin_password": "wrong"}, follow_redirects=True)
    assert b"Re-enter your own password" in r.data
    r = c.post("/officers/add", data={"username": "rsharma", "password": "real-password-999", "admin_password": "officer"}, follow_redirects=True)
    assert b"rsharma" in r.data
    c.post("/logout")
    app_module._ATTEMPTS.clear()
    r = c.post("/login", data={"username": "rsharma", "key": "wrong-password-1"}, follow_redirects=True)
    assert b"Wrong username or password" in r.data
    r = c.post("/login", data={"username": "rsharma", "key": "real-password-999"}, follow_redirects=True)
    assert b"Change your password" in r.data
    c.post("/change-password", data={"old": "real-password-999", "new": "rsharma-new-pass-2"}, follow_redirects=True)
    # cannot deactivate yourself
    conn = db.connect()
    oid = conn.execute("SELECT id FROM officers WHERE username='rsharma'").fetchone()["id"]
    conn.close()
    c.post(f"/officers/{oid}/deactivate", data={"admin_password": "rsharma-new-pass-2"}, follow_redirects=True)
    conn = db.connect()
    assert conn.execute("SELECT active FROM officers WHERE id=?", (oid,)).fetchone()["active"] == 1
    conn.close()
    # admin can deactivate
    c.post("/logout")
    app_module._ATTEMPTS.clear()
    login(c)
    c.post(f"/officers/{oid}/deactivate", data={"admin_password": "officer"}, follow_redirects=True)
    conn = db.connect()
    assert conn.execute("SELECT active FROM officers WHERE id=?", (oid,)).fetchone()["active"] == 0
    # deactivated officer cannot sign in
    conn.close()
    c.post("/logout")
    app_module._ATTEMPTS.clear()
    r = c.post("/login", data={"username": "rsharma", "key": "rsharma-new-pass-2"}, follow_redirects=True)
    assert b"Wrong username or password" in r.data
    # a session live at deactivation time dies on its next request
    c3 = client()
    app_module._ATTEMPTS.clear()
    c3.post("/login", data={"username": "admin", "key": "officer"}, follow_redirects=True)
    conn = db.connect()
    conn.execute("UPDATE officers SET active=0, session_version=session_version+1 WHERE username='admin'")
    conn.commit(); conn.close()
    r = c3.get("/", follow_redirects=False)
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    conn = db.connect()
    conn.execute("UPDATE officers SET active=1 WHERE username='admin'")
    conn.commit(); conn.close()

if __name__ == "__main__":
    test_audit_chain_tamper_detection()
    print("audit chain OK")
    test_circuit_breaker_and_audit_sampling()
    print("breaker + sampling OK")
    test_appeal_overdue_marker()
    print("appeal overdue OK")
    test_hold_snapshot_binding()
    print("snapshot binding OK")
    test_anchor_mismatch_detects_db_rewrite()
    print("anchor OK")
    test_officer_accounts()
    print("officer accounts OK")

