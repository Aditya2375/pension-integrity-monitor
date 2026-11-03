import csv, io, pathlib
import pytest
from conftest import Client, as_user
import app as app_module
from pim import db

FIX = pathlib.Path(__file__).parent / "fixtures"
FEEDS = ["pension_master", "pension_disbursements", "death_registry", "electoral_roll", "bank_transactions",
         "life_certificates", "telecom_activity", "hospital_records", "tax_pan_activity", "utility_bills", "toll_fastag"]


def load(adm):
    for feed in FEEDS:
        r = adm.post(f"/ingest/{feed}", {"file": (open(FIX / f"{feed}.csv", "rb"), f"{feed}.csv")},
                     content_type="multipart/form-data", follow_redirects=True)
        assert r.status_code == 200, feed
    assert b"Pipeline complete" in adm.post("/pipeline/run", {}, follow_redirects=True).data


def top_case():
    c = db.connect()
    row = c.execute("SELECT * FROM cases ORDER BY probability DESC").fetchone()
    steps = c.execute("SELECT id FROM verifications WHERE case_id=?", (row["id"],)).fetchall()
    c.close()
    return row, steps


def test_end_to_end(fresh_db):
    adm, rev, rev2, sup, sup2 = (as_user(u) for u in ("adm1", "rev1", "rev2", "sup1", "sup2"))
    load(adm)
    q = rev.get("/queue").data
    assert b"T001" in q and b"T002" in q and b"T003" not in q
    assert b"Calibrated probability" not in q and b"%" not in rev.get("/queue").data.split(b"<main")[1].split(b"</main>")[0]
    top, steps = top_case()
    cid = top["id"]
    assert top["state"] == "FLAGGED"

    # proposal blocked until every verification step is done
    r = rev.post(f"/case/{cid}/propose", {"kind": "hold", "reason": "registry match"}, follow_redirects=True)
    assert b"verification steps" in r.data
    for s in steps:
        rev.post(f"/case/{cid}/verify", {"vid": s["id"], "done": "1", "note": "checked"})
    r = rev.post(f"/case/{cid}/propose", {"kind": "hold", "reason": ""}, follow_redirects=True)
    assert b"written reasons" in r.data
    rev.post(f"/case/{cid}/propose", {"kind": "hold", "reason": "Registry match verified on all steps."})

    # four-eyes: proposer's own role cannot approve, nor can an officer
    assert rev.post(f"/case/{cid}/decide", {"verdict": "approve"}).status_code == 403
    assert rev2.post(f"/case/{cid}/decide", {"verdict": "approve"}).status_code == 403
    r = sup.post(f"/case/{cid}/decide", {"verdict": "approve"}, follow_redirects=True)
    assert b"Approved" in r.data

    c = db.connect()
    case = c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "NOTICE" and case["payment_status"] == "ACTIVE"
    assert c.execute("SELECT pension_status FROM pension_master WHERE pensioner_id='T001'").fetchone()[0] == "ACTIVE"
    tid = c.execute("SELECT tracking_id FROM appeals WHERE case_id=?", (cid,)).fetchone()[0]
    c.close()

    # suspension refused during notice without a written reason
    r = sup.post(f"/case/{cid}/suspend", {}, follow_redirects=True)
    assert b"notice period runs until" in r.data

    # family portal: reference, one-time code, then appeal with evidence
    fam = Client()
    r = fam.post("/appeal", {"action": "send_code", "tracking_id": tid}, csrf="/appeal")
    assert b"Synthetic demo only" in r.data
    code = r.data.split(b"<b>")[1].split(b"</b>")[0].decode()
    bad = fam.post("/appeal", {"action": "check_code", "code": "000000"}, csrf="/appeal")
    assert b"not valid" in bad.data or b"Case" in bad.data
    r = fam.post("/appeal", {"action": "check_code", "code": code}, csrf="/appeal")
    assert b"Where your case stands" in r.data
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = fam.post("/appeal", {"action": "appeal", "statement": "He is alive.", "contact": "x",
                             "evidence": (io.BytesIO(png), "proof.png")}, content_type="multipart/form-data", csrf="/appeal")
    assert b"restored" in r.data.lower() or b"received" in r.data.lower()

    c = db.connect()
    case = c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "APPEAL_REVIEW" and case["payment_status"] == "PROVISIONALLY_RESTORED"
    assert c.execute("SELECT COUNT(*) FROM reinstatement_requests").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM appeal_evidence").fetchone()[0] == 1
    c.close()

    # independence: sup1 approved the hold, so sup1 cannot decide the appeal; sup2 can
    r = sup.post(f"/case/{cid}/appeal-decision", {"verdict": "reverse", "note": "alive"}, follow_redirects=True)
    assert b"took no part" in r.data
    r = sup2.post(f"/case/{cid}/appeal-decision", {"verdict": "reverse", "note": "Alive, confirmed by visit."}, follow_redirects=True)
    assert b"Appeal decided" in r.data
    c = db.connect()
    case = c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "RELEASED" and case["payment_status"] == "ACTIVE" and case["outcome"] == "confirmed_alive"
    assert [r[0] for r in c.execute("SELECT kind FROM reinstatement_requests ORDER BY id")] == ["PROVISIONAL", "FULL"]
    from pim import audit
    ok, why = audit.verify(c)
    assert ok
    c.close()

    # evidence is reachable by staff only, as a download
    assert Client().get("/evidence/1").status_code == 302
    r = rev.get("/evidence/1")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]

    # family sees the decision
    assert b"accepted" in fam.get("/appeal").data


def test_export_neutralises_formulas(fresh_db):
    adm, rev = as_user("adm1"), as_user("rev1")
    load(adm)
    c = db.connect()
    c.execute("UPDATE pension_master SET full_name='=HYPERLINK(\"http://x\")' WHERE pensioner_id='T001'")
    c.commit(); c.close()
    body = rev.get("/queue/export").data.decode()
    for row in csv.reader(io.StringIO(body)):
        for cell in row:
            assert not cell.lstrip().startswith(("=", "+", "@")), cell


def test_settings_validation_all_or_nothing(fresh_db):
    adm = as_user("adm1")
    before = {k: None for k in ("base_rate",)}
    r = adm.post("/settings", {"base_rate": "0.05", "cost_false_hold": "nan"}, follow_redirects=True)
    assert b"out of range" in r.data
    c = db.connect()
    assert db.get_setting(c, "base_rate") == "0.02"   # nothing applied
    c.close()
    r = adm.post("/settings", {"appeal_window_days": "-3"}, follow_redirects=True)
    assert b"out of range" in r.data
    r = adm.post("/settings", {"base_rate": "0.03", "notice_period_days": "14"}, follow_redirects=True)
    assert b"Settings saved" in r.data


def test_evidence_rejects_wrong_type(fresh_db):
    adm = as_user("adm1")
    load(adm)
    top, steps = top_case()
    rev, sup = as_user("rev1"), as_user("sup1")
    for s in steps:
        rev.post(f"/case/{top['id']}/verify", {"vid": s["id"], "done": "1"})
    rev.post(f"/case/{top['id']}/propose", {"kind": "hold", "reason": "r"})
    sup.post(f"/case/{top['id']}/decide", {"verdict": "approve"})
    c = db.connect(); tid = c.execute("SELECT tracking_id FROM appeals").fetchone()[0]; c.close()
    fam = Client()
    code = fam.post("/appeal", {"action": "send_code", "tracking_id": tid}, csrf="/appeal").data.split(b"<b>")[1].split(b"</b>")[0].decode()
    fam.post("/appeal", {"action": "check_code", "code": code}, csrf="/appeal")
    r = fam.post("/appeal", {"action": "appeal", "statement": "alive", "evidence": (io.BytesIO(b"MZ\x90 exe"), "a.pdf")},
                 content_type="multipart/form-data", csrf="/appeal")
    assert b"Only PDF, JPG or PNG" in r.data
    c = db.connect()
    assert c.execute("SELECT state FROM cases WHERE id=?", (top["id"],)).fetchone()[0] == "NOTICE"   # nothing half-applied
    c.close()


def test_unknown_reference_does_not_leak(fresh_db):
    fam = Client()
    r = fam.post("/appeal", {"action": "send_code", "tracking_id": "APL-NOPE"}, csrf="/appeal")
    assert b"If that reference is valid" in r.data and b"Synthetic demo only" not in r.data


def test_jurisdiction_isolation(fresh_db):
    adm = as_user("adm1")
    load(adm)
    top, _ = top_case()
    c = db.connect()
    c.execute("UPDATE pension_master SET state='MH'"); c.commit(); c.close()
    kar = as_user("kar1")
    assert kar.get(f"/case/{top['id']}").status_code == 404
    assert b"T001" not in kar.get("/queue").data
