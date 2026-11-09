"""Regression tests for each security finding on the portal branch."""
import io, os, stat
import pytest
from conftest import Client, as_user, make_png, make_pdf
from pim import db, workflow as wf, audit, evidence, users
from pim.workflow import Actor, WorkflowError
import app as app_module


def seed(c):
    c.execute("INSERT INTO pension_master(pensioner_id,full_name,state,monthly_amount,mobile) VALUES('PRIVATE-KA','CrossScope Secret Name','KA',100,'9876543210')")
    c.execute("INSERT INTO cases(pensioner_id,state,probability,priority,created_at) VALUES('PRIVATE-KA','FLAGGED',.99,1,'2026-11-01T00:00:00Z')")
    c.execute("INSERT INTO pension_master(pensioner_id,full_name,state,monthly_amount) VALUES('LOCAL','Local Person','TestState',100)")
    c.execute("INSERT INTO cases(pensioner_id,state,probability,created_at) VALUES('LOCAL','VERIFICATION',.5,'2026-11-01T00:00:00Z')")
    c.commit()
    return c.execute("SELECT id FROM cases WHERE pensioner_id='LOCAL'").fetchone()[0]


def add_steps(c, cid, steps=None, done=1):
    from pim.pipeline import VERIFICATION_STEPS
    for s in (steps if steps is not None else VERIFICATION_STEPS):
        c.execute("INSERT INTO verifications(case_id,step,done) VALUES(?,?,?)", (cid, s, done))
    c.commit()


# 1. jurisdiction scoping on every path
def test_dashboard_export_queue_appeals_scoped(fresh_db):
    c = db.connect(); seed(c); c.close()
    rev = as_user("rev1")
    for path in ("/", "/queue", "/queue/export", "/appeals"):
        body = rev.get(path).data
        assert b"CrossScope Secret Name" not in body and b"PRIVATE-KA" not in body, path
    kar = as_user("kar1")
    assert b"PRIVATE-KA" in kar.get("/queue/export").data
    assert b"Local Person" not in kar.get("/").data
    assert kar.get("/case/1").status_code in (200, 404)


# 2. no alternate release path around independent appeal review
def test_release_cannot_bypass_appeal_independence(fresh_db):
    c = db.connect(); cid = seed(c); add_steps(c, cid)
    o, s = Actor("rev1", "officer", ("TestState",)), Actor("sup1", "supervisor", ("TestState",))
    wf.propose(c, cid, "hold", o, "r"); wf.decide(c, cid, s, True)
    tid = c.execute("SELECT tracking_id FROM appeals WHERE case_id=?", (cid,)).fetchone()[0]
    wf.file_appeal(c, tid, "alive")
    with pytest.raises(WorkflowError):
        wf.release(c, cid, s, "alive")
    with pytest.raises(WorkflowError):
        wf.resolve_appeal(c, cid, s, False, "alive")
    assert c.execute("SELECT state FROM cases WHERE id=?", (cid,)).fetchone()[0] == "APPEAL_REVIEW"
    # the transition table itself refuses a wrong action on the edge
    case = c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    with pytest.raises(WorkflowError):
        wf._move(c, case, "RELEASED", s, "release")
    wf.resolve_appeal(c, cid, Actor("sup2", "supervisor", ("TestState",)), False, "alive")


def test_release_route_blocked_for_appeal(fresh_db):
    c = db.connect(); cid = seed(c); add_steps(c, cid)
    o, s = Actor("rev1", "officer", ("TestState",)), Actor("sup1", "supervisor", ("TestState",))
    wf.propose(c, cid, "hold", o, "r"); wf.decide(c, cid, s, True)
    wf.file_appeal(c, c.execute("SELECT tracking_id FROM appeals").fetchone()[0], "alive"); c.commit(); c.close()
    sup = as_user("sup1")
    r = sup.post(f"/case/{cid}/release", {"note": "alive"}, follow_redirects=True)
    assert b"independent appeal decision" in r.data
    c = db.connect()
    assert c.execute("SELECT state FROM cases WHERE id=?", (cid,)).fetchone()[0] == "APPEAL_REVIEW"


# 3. exact expected checks
@pytest.mark.parametrize("variant", ["one_unexpected", "missing_one", "duplicate", "renamed", "one_done_only", "none"])
def test_exact_four_checks_required(fresh_db, variant):
    from pim.pipeline import VERIFICATION_STEPS as V
    c = db.connect(); cid = seed(c)
    steps = {"one_unexpected": ["ONE UNEXPECTED CHECK"], "missing_one": V[:3], "duplicate": V + [V[0]],
             "renamed": V[:3] + ["something else"], "none": []}.get(variant, V)
    add_steps(c, cid, steps, done=1)
    if variant == "one_done_only":
        c.execute("UPDATE verifications SET done=0 WHERE id=(SELECT MIN(id) FROM verifications)"); c.commit()
    with pytest.raises(WorkflowError):
        wf.propose(c, cid, "hold", Actor("rev1", "officer", ("TestState",)), "reason")


def test_step_must_belong_to_case(fresh_db):
    c = db.connect(); cid = seed(c); add_steps(c, cid)
    other = c.execute("SELECT id FROM cases WHERE pensioner_id='PRIVATE-KA'").fetchone()[0]
    with pytest.raises(WorkflowError):
        wf.complete_step(c, other, 1, True, "", Actor("rev1", "officer", ("TestState",)))


# 4. audit holds fixed codes only
def test_audit_vocabulary_and_exact_actor(fresh_db):
    c = db.connect(); cid = seed(c)
    with pytest.raises(ValueError):
        audit.append(c, "rev1", "dismiss private phone 9876543210", cid)
    with pytest.raises(ValueError):
        audit.append(c, "rev1", "dismiss", cid, "private phone 9876543210")
    with pytest.raises(ValueError):
        audit.append(c, "re v1!", "dismiss", cid)      # identities are never rewritten
    add_steps(c, cid)
    o = Actor("rev1", "officer", ("TestState",))
    wf.add_note(c, cid, o, "private phone 9876543210")
    wf.dismiss(c, cid, o, "private phone 9876543210")
    blob = " ".join(str(e) for e in audit.events(c))
    assert "9876543210" not in blob and "private" not in blob


def test_usernames_validated(fresh_db):
    c = db.connect()
    with pytest.raises(ValueError):
        users.create(c, "bad name!", "officer", "longenoughkey")


# 5. evidence: parsed, private, quarantined
def test_evidence_permissions_and_quarantine(fresh_db, tmp_path):
    c = db.connect(); cid = seed(c)
    c.execute("INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,status) VALUES('APL-X',?,?,?,?)", (cid, "2026-11-01T00:00:00Z", "n", "NOTICE"))
    c.commit()
    from werkzeug.datastructures import FileStorage
    app_module.EVIDENCE_DIR = str(tmp_path / "ev")
    app_module._store_evidence(c, 1, FileStorage(stream=io.BytesIO(make_png()), filename="x.png"))
    p = c.execute("SELECT stored_path, status FROM appeal_evidence").fetchone()
    assert stat.S_IMODE(os.stat(p[0]).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(p[0])).st_mode) == 0o700
    assert "quarantine" in p[0] and p[1] == "QUARANTINED"


@pytest.mark.parametrize("data", [
    b"%PDF-not a valid PDF",
    make_pdf().replace(b"/Catalog", b"/Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >>"),
    make_pdf().replace(b"/Catalog", b"/Catalog /J#61vaScript"),
    make_png()[:-5],                                   # truncated
    make_png()[:20] + b"X" + make_png()[21:],          # bad CRC
    make_png(2, 2) + b"trailing",                      # data after IEND
    b"\xff\xd8\xff\xe0" + b"0" * 40,                   # JPEG prefix, no structure
    b"MZ" + b"0" * 100,
    b"x" * (5 * 1024 * 1024 + 10),
])
def test_evidence_rejected(data):
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(data)


def test_evidence_accepts_clean_files():
    assert evidence.validate(make_png())[0] == "png"
    assert evidence.validate(make_pdf())[0] == "pdf"


def test_evidence_png_dimension_bomb():
    import struct, zlib
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    bomb = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 60000, 60000, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b""))
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(bomb)


def test_evidence_download_is_opaque(fresh_db):
    from conftest import make_png
    c = db.connect(); cid = seed(c); add_steps(c, cid)
    o, s = Actor("rev1", "officer", ("TestState",)), Actor("sup1", "supervisor", ("TestState",))
    wf.propose(c, cid, "hold", o, "r"); wf.decide(c, cid, s, True)
    tid = c.execute("SELECT tracking_id FROM appeals").fetchone()[0]; c.commit(); c.close()
    fam = Client()
    code = fam.post("/appeal", {"action": "send_code", "tracking_id": tid}, csrf="/appeal").data.split(b"<b>")[1].split(b"</b>")[0].decode()
    fam.post("/appeal", {"action": "check_code", "code": code}, csrf="/appeal")
    fam.post("/appeal", {"action": "appeal", "statement": "alive", "evidence": (io.BytesIO(make_png()), "a.png")},
             content_type="multipart/form-data", csrf="/appeal")
    sup = as_user("sup1")
    assert as_user("rev1").get("/evidence/1").status_code == 302          # quarantined: refused
    assert sup.post("/evidence/1/release", {}).status_code == 302          # no attestation: stays quarantined
    c = db.connect(); assert c.execute("SELECT status FROM appeal_evidence").fetchone()[0] == "QUARANTINED"; c.close()
    sup.post("/evidence/1/release", {"attest": "1"})
    r = as_user("rev1").get("/evidence/1")
    assert r.headers["Content-Type"].startswith("application/octet-stream")
    assert "attachment" in r.headers["Content-Disposition"] and r.headers["X-Content-Type-Options"] == "nosniff"


# 6. stale sessions
def test_disabled_user_session_dies(fresh_db):
    cl = as_user("rev1")
    assert cl.get("/queue").status_code == 200
    c = db.connect(); c.execute("UPDATE users SET active=0 WHERE username='rev1'"); c.commit(); c.close()
    r = cl.get("/queue")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_role_and_scope_change_applies_immediately(fresh_db):
    c = db.connect(); seed(c); c.close()
    cl = as_user("sup1")
    assert cl.get("/appeals").status_code == 200
    c = db.connect(); c.execute("UPDATE users SET role='auditor' WHERE username='sup1'"); c.commit(); c.close()
    assert cl.post("/case/1/decide", {"verdict": "approve"}).status_code == 403
    c = db.connect(); c.execute("UPDATE users SET jurisdictions='KA' WHERE username='sup1'"); c.commit(); c.close()
    assert b"Local Person" not in cl.get("/").data


# honest UI: nothing claims a message was sent
def test_ui_does_not_claim_delivery(fresh_db):
    c = db.connect(); cid = seed(c); add_steps(c, cid); c.close()
    app_module.app.config["NOTIFY_ADAPTER"] = None
    rev, sup = as_user("rev1"), as_user("sup1")
    rev.post(f"/case/{cid}/propose", {"kind": "hold", "reason": "r"})
    r = sup.post(f"/case/{cid}/decide", {"verdict": "approve"}, follow_redirects=True)
    t = r.get_data(as_text=True)
    assert "nothing has been sent" in t and "has been sent a notice" not in t
    assert "Queued, not sent" in t and "not been sent" in t
    c = db.connect(); tid = c.execute("SELECT tracking_id FROM appeals").fetchone()[0]; c.close()
    fam = Client()
    r = fam.post("/appeal", {"action": "send_code", "tracking_id": tid}, csrf="/appeal")
    t = r.get_data(as_text=True)
    assert "cannot be delivered here" in t and "has been sent" not in t
    r = fam.post("/appeal", {"action": "send_code", "tracking_id": "APL-NOPE"}, csrf="/appeal")
    assert "cannot be delivered here" in r.get_data(as_text=True)   # same answer for unknown references
