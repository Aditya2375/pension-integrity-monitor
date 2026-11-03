"""Round three findings: evidence policy, OTP atomicity and grants."""
import io, os, hashlib
import pytest
from conftest import Client, as_user, make_png, make_pdf
from pim import db, otp, evidence, workflow as wf
from pim.workflow import Actor, WorkflowError
import app as app_module


def notice_case(c):
    from pim.pipeline import VERIFICATION_STEPS
    c.execute("INSERT INTO pension_master(pensioner_id,full_name,state,monthly_amount) VALUES('L','Local','TestState',100)")
    c.execute("INSERT INTO cases(pensioner_id,state,probability,created_at) VALUES('L','VERIFICATION',.5,'2026-11-01T00:00:00Z')")
    cid = c.execute("SELECT id FROM cases").fetchone()[0]
    for s in VERIFICATION_STEPS:
        c.execute("INSERT INTO verifications(case_id,step,done) VALUES(?,?,1)", (cid, s))
    wf.propose(c, cid, "hold", Actor("rev1", "officer", ("TestState",)), "r")
    wf.decide(c, cid, Actor("sup1", "supervisor", ("TestState",)), True)
    c.commit()
    return cid, c.execute("SELECT tracking_id FROM appeals").fetchone()[0]


def portal_login(tid):
    fam = Client()
    code = fam.post("/appeal", {"action": "send_code", "tracking_id": tid}, csrf="/appeal").data.split(b"<b>")[1].split(b"</b>")[0].decode()
    r = fam.post("/appeal", {"action": "check_code", "code": code}, csrf="/appeal")
    assert b"Where your case stands" in r.data
    return fam


def test_pdf_with_fake_objects_rejected():
    bad = b"%PDF-1.7\n1 0 obj\nnot a pdf object\nstartxref\n0\n%%EOF\n"
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(bad)
    # points at a real xref but objects never closed
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(make_pdf().replace(b"endobj", b"", 1))


def test_upload_disabled_by_default(fresh_db, monkeypatch):
    monkeypatch.setattr(app_module, "EVIDENCE_ENABLED", False)
    c = db.connect(); cid, tid = notice_case(c); c.close()
    fam = portal_login(tid)
    assert b'name="evidence"' not in fam.get("/appeal").data
    r = fam.post("/appeal", {"action": "appeal", "statement": "alive", "evidence": (io.BytesIO(make_png()), "a.png")},
                 content_type="multipart/form-data", csrf="/appeal")
    assert b"switched off" in r.data
    c = db.connect()
    assert c.execute("SELECT state FROM cases").fetchone()[0] == "NOTICE"          # nothing half-applied
    assert c.execute("SELECT COUNT(*) FROM appeal_evidence").fetchone()[0] == 0
    c.close()


def test_failed_filing_removes_written_file(fresh_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "EVIDENCE_DIR", str(tmp_path / "ev"))
    c = db.connect(); cid, tid = notice_case(c); c.close()
    fam = portal_login(tid)
    c = db.connect(); c.execute("DELETE FROM portal_grants"); c.commit(); c.close()   # grant vanishes after the file is written
    fam.post("/appeal", {"action": "appeal", "statement": "alive", "evidence": (io.BytesIO(make_png()), "a.png")},
             content_type="multipart/form-data", csrf="/appeal")
    q = tmp_path / "ev" / "quarantine"
    assert not q.exists() or list(q.iterdir()) == []
    c = db.connect()
    assert c.execute("SELECT state FROM cases").fetchone()[0] == "NOTICE"
    c.close()


def test_download_checks_digest_and_location(fresh_db, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "EVIDENCE_DIR", str(tmp_path / "ev"))
    c = db.connect(); cid, tid = notice_case(c); c.close()
    fam = portal_login(tid)
    fam.post("/appeal", {"action": "appeal", "statement": "alive", "evidence": (io.BytesIO(make_png()), "a.png")},
             content_type="multipart/form-data", csrf="/appeal")
    c = db.connect(); path = c.execute("SELECT stored_path FROM appeal_evidence").fetchone()[0]; c.close()
    sup = as_user("sup2")
    sup.post("/evidence/1/release", {"attest": "1"})
    assert as_user("rev1").get("/evidence/1").status_code == 200
    open(path, "ab").write(b"tampered")
    r = as_user("rev1").get("/evidence/1", follow_redirects=True)
    assert b"changed since upload" in r.data
    c = db.connect(); c.execute("UPDATE appeal_evidence SET stored_path='/etc/hostname'"); c.commit(); c.close()
    assert b"not where it should be" in as_user("rev1").get("/evidence/1", follow_redirects=True).data


# ---- OTP
def test_otp_wrong_tries_expire_and_single_use(fresh_db):
    c = db.connect(); cid, tid = notice_case(c)
    code2 = otp.issue(c, tid)
    for _ in range(otp.MAX_TRIES):
        otp.check(c, tid, "x")
    assert not otp.check(c, tid, code2)             # after the cap even the right code fails
    code3 = otp.issue(c, tid)
    assert otp.check(c, tid, code3) is True
    assert otp.check(c, tid, code3) is False        # single use


def test_otp_expiry(fresh_db):
    c = db.connect(); cid, tid = notice_case(c)
    code = otp.issue(c, tid)
    c.execute("UPDATE otp_codes SET expires_at='2020-01-01T00:00:00'")
    assert not otp.check(c, tid, code)


def test_otp_concurrent_redemption_has_one_winner(fresh_db):
    import threading
    c = db.connect(); cid, tid = notice_case(c); code = otp.issue(c, tid); c.commit(); c.close()
    results, gate = [], threading.Barrier(8)
    def run():
        conn = db.connect(); conn.execute("PRAGMA busy_timeout=5000")
        gate.wait()
        try:
            ok = otp.check(conn, tid, code); conn.commit()
        except Exception:
            ok = False
        conn.close(); results.append(ok)
    ts = [threading.Thread(target=run) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert results.count(True) == 1


def test_portal_grant_expires_and_is_single_use(fresh_db):
    c = db.connect(); cid, tid = notice_case(c)
    token = otp.grant(c, tid)
    assert otp.grant_tid(c, token) == tid
    c.execute("UPDATE portal_grants SET expires_at='2020-01-01T00:00:00'")
    assert otp.grant_tid(c, token) is None
    t2 = otp.grant(c, tid)
    assert otp.consume_grant(c, t2) is True and otp.consume_grant(c, t2) is False
    assert otp.grant_tid(c, t2) is None


def test_expired_grant_blocks_filing(fresh_db):
    c = db.connect(); cid, tid = notice_case(c); c.close()
    fam = portal_login(tid)
    c = db.connect(); c.execute("UPDATE portal_grants SET expires_at='2020-01-01T00:00:00'"); c.commit(); c.close()
    r = fam.post("/appeal", {"action": "appeal", "statement": "alive"}, csrf="/appeal")
    assert b"Where your case stands" not in r.data     # back at the start
    c = db.connect()
    assert c.execute("SELECT state FROM cases").fetchone()[0] == "NOTICE"


def test_grant_consumed_after_filing(fresh_db):
    c = db.connect(); cid, tid = notice_case(c); c.close()
    fam = portal_login(tid)
    fam.post("/appeal", {"action": "appeal", "statement": "alive"}, csrf="/appeal")
    c = db.connect()
    assert c.execute("SELECT COUNT(*) FROM portal_grants").fetchone()[0] == 0
    assert c.execute("SELECT state FROM cases").fetchone()[0] == "APPEAL_REVIEW"
    c.close()
    # the same browser can no longer act on the case
    r = fam.post("/appeal", {"action": "appeal", "statement": "again"}, csrf="/appeal")
    assert b"Where your case stands" not in r.data


def test_late_appeal_denied_through_the_portal(fresh_db):
    c = db.connect(); cid, tid = notice_case(c)
    c.execute("UPDATE cases SET appeal_deadline_at='2020-01-01T00:00:00Z'"); c.commit(); c.close()
    fam = portal_login(tid)
    r = fam.post("/appeal", {"action": "appeal", "statement": "late"}, csrf="/appeal")
    assert b"appeal period for this notice has ended" in r.data
    c = db.connect(); assert c.execute("SELECT state FROM cases").fetchone()[0] == "NOTICE"


def test_death_routes_through_http(fresh_db):
    c = db.connect()
    from pim.pipeline import VERIFICATION_STEPS
    c.execute("INSERT INTO pension_master(pensioner_id,full_name,state,monthly_amount) VALUES('L','Local','TestState',100)")
    c.execute("INSERT INTO cases(pensioner_id,state,probability,created_at) VALUES('L','VERIFICATION',.5,'2026-11-01T00:00:00Z')")
    for s in VERIFICATION_STEPS:
        c.execute("INSERT INTO verifications(case_id,step,done) VALUES(1,?,1)", (s,))
    c.commit(); c.close()
    rev, sup1, sup2 = as_user("rev1"), as_user("sup1"), as_user("sup2")
    rev.post("/case/1/propose", {"kind": "confirm_death", "reason": "registry"})
    sup1.post("/case/1/decide", {"verdict": "approve"})
    r = sup2.post("/case/1/finalize-death", {}, follow_redirects=True)
    assert b"cannot be finalised earlier" in r.data
    c = db.connect()
    assert c.execute("SELECT payment_status FROM cases").fetchone()[0] == "ACTIVE"
    c.execute("UPDATE cases SET notice_due_at='2020-01-01T00:00:00Z', appeal_deadline_at='2020-01-01T00:00:00Z'"); c.commit(); c.close()
    sup2.post("/case/1/finalize-death", {})
    c = db.connect(); assert c.execute("SELECT state FROM cases").fetchone()[0] == "SURVIVOR_ROUTING"; c.close()
    assert sup1.post("/case/1/reopen", {"note": "wrong"}, follow_redirects=True).status_code == 200
    c = db.connect(); assert c.execute("SELECT state FROM cases").fetchone()[0] == "SURVIVOR_ROUTING"; c.close()   # approver cannot reopen
