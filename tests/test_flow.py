import os, sys, tempfile, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["PIM_DB"] = tempfile.mktemp(suffix=".sqlite3")
os.environ.setdefault("PIM_OFFICER_KEY", "officer")
os.environ.setdefault("PIM_INSECURE_HTTP", "1")
os.environ["PIM_CHECKPOINT_DIR"] = tempfile.mkdtemp()

import app as app_module
from pim import db, health

FIX = pathlib.Path(__file__).parent / "fixtures"

def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()

def login(c, username="admin"):
    app_module._ATTEMPTS.clear()
    return c.post("/login", data={"username": username, "key": "officer"}, follow_redirects=True)

def test_end_to_end():
    c = client()
    r = c.get("/")
    assert r.status_code == 302  # dashboard is officer-only; redirects to login
    login(c)
    r = c.get("/")
    assert r.status_code == 200

    login(c)

    for feed in ["pension_master", "pension_disbursements", "death_registry", "electoral_roll", "bank_transactions", "life_certificates", "telecom_activity", "hospital_records", "tax_pan_activity", "utility_bills", "toll_fastag"]:
        data = {"file": (open(FIX / f"{feed}.csv", "rb"), f"{feed}.csv")}
        r = c.post(f"/ingest/{feed}", data=data, content_type="multipart/form-data", follow_redirects=True)
        assert r.status_code == 200, feed

    # rejected-row accounting: all fixture rows valid
    conn = db.connect()
    fh = {f["feed_id"]: f for f in health.feed_health(conn)}
    assert fh["pension_master"]["rows_loaded"] == 3
    assert fh["death_registry"]["rows_loaded"] == 1
    conn.close()

    conn = db.connect()
    conn.execute("UPDATE settings SET value='0' WHERE key='audit_sample_rate'")
    conn.commit(); conn.close()
    r = c.post("/pipeline/run", follow_redirects=True)
    assert b"Pipeline complete" in r.data

    r = c.get("/queue")
    assert b"T001" in r.data and b"T002" in r.data
    assert b"T003" not in r.data  # clean pensioner never flagged

    conn = db.connect()
    cases = conn.execute("SELECT * FROM cases ORDER BY probability DESC").fetchall()
    assert len(cases) == 2
    top = cases[0]
    assert top["pensioner_id"] == "T001"          # registry match outranks
    assert top["state"] == "FLAGGED"              # never auto-held
    sig = conn.execute("SELECT signal,present FROM signals WHERE case_id=?", (top["id"],)).fetchall()
    sigd = {s["signal"]: s["present"] for s in sig}
    assert sigd["death_registry_match"] == 1
    assert sigd["electoral_deletion"] == 1
    steps = conn.execute("SELECT * FROM verifications WHERE case_id=?", (top["id"],)).fetchall()
    assert len(steps) == 4
    conn.close()

    cid = top["id"]
    # hold blocked before verification completes (reason long enough to reach the verification check)
    r = c.post(f"/case/{cid}/hold", data={"reasons": "matched registry entry, verified against the district registrar record"}, follow_redirects=True)
    assert b"All verification steps" in r.data

    for s in steps:
        c.post(f"/case/{cid}/verify", data={"vid": s["id"], "done": "1", "note": "checked"})

    # hold blocked without written reasons
    r = c.post(f"/case/{cid}/hold", data={"reasons": ""}, follow_redirects=True)
    assert b"Written reasons are required" in r.data

    # boilerplate/short reasons rejected
    r = c.post(f"/case/{cid}/hold", data={"reasons": "too short"}, follow_redirects=True)
    assert b"at least 40 characters" in r.data

    # a hold must cite evidence present on the case
    r = c.post(f"/case/{cid}/hold", data={"reasons": "Registry match verified on all four steps against district records."}, follow_redirects=True)
    assert b"Cite at least one evidence signal" in r.data
    r = c.post(f"/case/{cid}/hold", data={"reasons": "Registry match verified on all four steps against district records.", "cites": ["not_a_signal"]}, follow_redirects=True)
    assert b"Cite at least one evidence signal" in r.data
    # hold request only pends; no tracking ID yet
    r = c.post(f"/case/{cid}/hold", data={"reasons": "Registry match verified on all four steps against district records.", "cites": ["death_registry_match"]}, follow_redirects=True)
    assert b"second officer must approve" in r.data
    conn = db.connect()
    case = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "HOLD_PENDING"
    conn.close()

    # step-up re-auth is required before any approval check runs
    r = c.post(f"/case/{cid}/approve-hold", follow_redirects=True)
    assert b"Re-enter your password" in r.data
    # the requesting officer cannot approve their own hold
    r = c.post(f"/case/{cid}/approve-hold", data={"password": "officer"}, follow_redirects=True)
    assert b"cannot approve it" in r.data

    # duplicate (boilerplate) reasons on the other case are rejected
    cases2 = db.connect().execute("SELECT id FROM cases WHERE pensioner_id='T002'").fetchone()
    for s in db.connect().execute("SELECT * FROM verifications WHERE case_id=?", (cases2["id"],)).fetchall():
        c.post(f"/case/{cases2['id']}/verify", data={"vid": s["id"], "done": "1", "note": "checked"})
    r = c.post(f"/case/{cases2['id']}/hold", data={"reasons": "Registry match verified on all four steps against district records."}, follow_redirects=True)
    assert b"boilerplate" in r.data

    # a second, different officer approves - a real account, not a typed name
    r = c.post("/officers/add", data={"username": "bverma", "password": "second-officer-pass", "admin_password": "officer"}, follow_redirects=True)
    assert b"bverma" in r.data
    c.post("/logout")
    login2 = c.post("/login", data={"username": "bverma", "key": "second-officer-pass"}, follow_redirects=True)
    assert b"Change your password" in login2.data  # forced at first sign-in
    r = c.post("/change-password", data={"old": "second-officer-pass", "new": "bverma-new-pass-1"}, follow_redirects=True)
    assert b"Password changed" in r.data
    # step-up: approval without re-entering the password is refused
    r = c.post(f"/case/{cid}/approve-hold", follow_redirects=True)
    assert b"Re-enter your password" in r.data
    r = c.post(f"/case/{cid}/approve-hold", data={"password": "bverma-new-pass-1"}, follow_redirects=True)
    assert b"Family appeal tracking ID" in r.data

    conn = db.connect()
    case = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "HELD"
    p = conn.execute("SELECT pension_status FROM pension_master WHERE pensioner_id='T001'").fetchone()
    assert p["pension_status"] == "HELD"
    notice = conn.execute("SELECT * FROM appeals WHERE case_id=? AND status='NOTICE'", (cid,)).fetchone()
    tid = notice["tracking_id"]
    conn.close()

    # family appeal portal: public, no login
    c2 = client()
    r = c2.post("/appeal", data={"tracking_id": tid})
    assert b"Case status" in r.data and b"HELD" in r.data
    r = c2.post("/appeal", data={"tracking_id": tid, "statement": "He is alive; here is proof.", "contact": "family@example.test"})
    assert b"has been submitted" in r.data

    r = c.get("/appeals")
    assert b"He is alive" in r.data

    # resolve appeal and release with full arrears
    conn = db.connect()
    open_appeal = conn.execute("SELECT * FROM appeals WHERE case_id=? AND status='OPEN'", (cid,)).fetchone()
    conn.close()
    r = c.post(f"/appeals/{open_appeal['id']}/resolve", data={"status": "RELEASED", "decision": "verified alive"})
    r = c.post(f"/case/{cid}/release", follow_redirects=True)
    assert b"full arrears" in r.data

    conn = db.connect()
    case = conn.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "RELEASED" and case["arrears"] > 0
    conn.close()

    # outcome feedback path
    r = c.post(f"/case/{cid}/outcome", data={"outcome": "confirmed_alive", "note": "appeal verified"}, follow_redirects=True)
    assert r.status_code == 200
    r = c.post("/feedback/recalibrate", follow_redirects=True)
    assert b"need at least 30 resolved cases" in r.data

    # feed health page renders
    r = c.get("/health")
    assert b"Pension master roll" in r.data

def test_empty_states():
    os.environ["PIM_DB"] = tempfile.mktemp(suffix=".sqlite3")
    import importlib
    importlib.reload(db)
    importlib.reload(app_module)
    c = client()
    login(c)
    r = c.get("/queue")
    assert b"The queue is empty" in r.data
    r = c.get("/appeals")
    assert b"No appeals" in r.data
    r = c.get("/templates/death_registry.csv")
    assert r.data.startswith(b"registration_no,deceased_name,dob,gender,date_of_death")

if __name__ == "__main__":
    test_end_to_end()
    print("end-to-end OK")
    test_empty_states()
    print("empty-state OK")
