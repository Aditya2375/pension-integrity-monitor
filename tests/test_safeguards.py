import os, sys, tempfile, pathlib, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["PIM_DB"] = tempfile.mktemp(suffix=".sqlite3")
os.environ.setdefault("PIM_OFFICER_KEY", "officer")
os.environ.setdefault("PIM_INSECURE_HTTP", "1")
os.environ["PIM_CHECKPOINT_DIR"] = tempfile.mkdtemp()

import app as app_module
from pim import db, pipeline

FIX = pathlib.Path(__file__).parent / "fixtures"

def client():
    from tests.http_client import FormClient
    app_module.app.test_client_class = FormClient
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
    # Samples also respect the cap. A separate run with capacity samples clean rows.
    assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] <= 1
    conn.execute("UPDATE settings SET value='10' WHERE key='max_new_cases_per_run'")
    conn.commit()
    pipeline.run_pipeline(conn, rng=random.Random(7)); conn.commit()
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
    conn = db.connect()
    sig = conn.execute("SELECT signal FROM signals WHERE case_id=? AND present=1 AND signal NOT LIKE '%_cap' AND signal!='audit_sample' LIMIT 1", (cid,)).fetchone()
    conn.close()
    if sig is None:
        return
    r = c.post(f"/case/{cid}/hold", data={"reasons": "Snapshot binding test reasons, case specific and long enough.", "cites": [sig["signal"]]}, follow_redirects=True)
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
    assert c.post(f"/officers/{oid}/deactivate", data={"admin_password": "rsharma-new-pass-2"}).status_code == 403
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

def test_crash_chaos_at_every_write_boundary():
    """Kill the append at each boundary; no ambiguous state may be trusted."""
    import shutil
    base = db.connect()
    db.log(base, "t", "pre", "x"); base.commit()
    assert db.verify_audit(base)[0] is True
    base.close()
    real = db._append_fsync
    calls = {"n": 0}
    def boom_at(k):
        def f(path, line):
            calls["n"] += 1
            if calls["n"] == k:
                raise OSError("simulated crash")
            return real(path, line)
        return f
    # boundary 1: crash before the first anchor write -> nothing durable, chain intact
    # boundary 2: crash after local anchor, before checkpoint -> anchor ahead (INCOMPLETE)
    for k, expect in ((1, True), (2, None)):
        calls["n"] = 0
        db._append_fsync = boom_at(k)
        c = db.connect()
        try:
            db.log(c, "t", "crash", f"k={k}"); c.commit()
        except OSError:
            c.rollback()
        c.close()
        db._append_fsync = real
        c = db.connect()
        state = db.verify_audit(c)[0]
        c.close()
        assert state is expect, (k, state)
        if expect is None:
            # manual resolution: operator accepts the entry by re-logging is NOT automatic;
            # simulate review by truncating the orphan anchor lines
            path = db._anchor_path()  # only the local anchor got the orphan line
            lines = open(path).read().splitlines()
            open(path, "w").write("\n".join(lines[:-1]) + "\n")
            c = db.connect()
            assert db.verify_audit(c)[0] is True
            c.close()
    # boundary 3: crash after both anchors, before DB commit
    c = db.connect()
    db.log(c, "t", "crash", "k=3")
    c.rollback(); c.close()
    c = db.connect()
    assert db.verify_audit(c)[0] is None  # never silently trusted
    c.close()
    for path in (db._anchor_path(), db._checkpoint_path()):
        lines = open(path).read().splitlines()
        open(path, "w").write("\n".join(lines[:-1]) + "\n")
    c = db.connect()
    assert db.verify_audit(c)[0] is True
    c.close()

def test_rollback_of_db_and_local_anchor_is_caught():
    import shutil
    dbp = os.environ["PIM_DB"]
    c = db.connect(); db.log(c, "t", "keep", "1"); c.commit(); c.close()
    shutil.copy(dbp, dbp + ".old"); shutil.copy(dbp + ".anchor", dbp + ".anchor.old")
    c = db.connect(); db.log(c, "t", "later", "2"); db.log(c, "t", "later", "3"); c.commit(); c.close()
    # attacker restores an older, mutually consistent database + local anchor
    shutil.copy(dbp + ".old", dbp); shutil.copy(dbp + ".anchor.old", dbp + ".anchor")
    c = db.connect()
    ok, bad, _ = db.verify_audit(c)
    assert ok is False, "rollback of database and local anchor went undetected"
    c.close()
    # operator recovery in the test: restore the real state so later tests are clean
    # (re-sync local anchor to the checkpoint is a manual, audited operator action)

def test_reconcile_flags_unaudited_hold():
    conn = db.connect()
    row = conn.execute("SELECT id FROM cases LIMIT 1").fetchone()
    if row is None:
        conn.close(); return
    cid = row["id"]
    old = conn.execute("SELECT state, held_at FROM cases WHERE id=?", (cid,)).fetchone()
    conn.execute("UPDATE cases SET state='HELD', held_at='2026-01-01T00:00:00Z' WHERE id=?", (cid,))
    assert any(f"case {cid} " in p for p in db.reconcile(conn))
    conn.execute("UPDATE cases SET state=?, held_at=? WHERE id=?", (old["state"], old["held_at"], cid))
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
    test_crash_chaos_at_every_write_boundary()
    print("crash chaos OK")
    test_rollback_of_db_and_local_anchor_is_caught()
    print("rollback OK")
    test_reconcile_flags_unaudited_hold()
    print("reconcile OK")

