import os, sys, tempfile, pathlib, sqlite3
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["PIM_DB"] = tempfile.mktemp(suffix=".sqlite3")
from pim import db, audit, workflow as wf
from pim.workflow import Actor, WorkflowError

OFF, OFF2 = Actor("off1", "officer"), Actor("off2", "officer")
SUP, SUP2, AUD = Actor("sup1", "supervisor"), Actor("sup2", "supervisor"), Actor("aud", "auditor")


@pytest.fixture
def c():
    path = tempfile.mktemp(suffix=".sqlite3")
    db.DB_PATH = path
    db.init_db()
    conn = db.connect()
    wf.ensure_schema(conn)
    conn.execute("INSERT INTO pension_master(pensioner_id,full_name,monthly_amount,pension_status) VALUES('P1','Test Person',30000,'ACTIVE')")
    conn.execute("INSERT INTO cases(pensioner_id,created_at,state) VALUES('P1','2026-01-01T00:00:00Z','FLAGGED')")
    for s in ("a", "b"):
        conn.execute("INSERT INTO verifications(case_id,step) VALUES(1,?)", (s,))
    conn.commit()
    yield conn
    conn.close()


def verified(c):
    for vid in (1, 2):
        wf.complete_step(c, 1, vid, True, "", OFF)


def to_notice(c):
    verified(c)
    wf.propose(c, 1, "hold", OFF, "no life cert, no bank activity")
    wf.decide(c, 1, SUP, True)


def case(c):
    return c.execute("SELECT * FROM cases WHERE id=1").fetchone()


def test_hold_needs_verification_rows_and_steps(c):
    with pytest.raises(WorkflowError):
        wf.propose(c, 1, "hold", OFF, "reason")
    c.execute("DELETE FROM verifications")
    with pytest.raises(WorkflowError):
        wf.propose(c, 1, "hold", OFF, "reason")  # zero rows must not pass


def test_four_eyes(c):
    verified(c)
    wf.propose(c, 1, "hold", OFF, "reason")
    with pytest.raises(WorkflowError):
        wf.decide(c, 1, OFF, True)           # proposer cannot approve
    with pytest.raises(WorkflowError):
        wf.decide(c, 1, OFF2, True)          # officer role cannot approve
    wf.decide(c, 1, SUP, True)
    assert case(c)["state"] == "NOTICE"


def test_flag_never_touches_pension_feed(c):
    to_notice(c)
    wf.suspend(c, 1, SUP, "urgent fraud evidence")
    assert case(c)["payment_status"] == "SUSPENDED"
    row = c.execute("SELECT pension_status FROM pension_master").fetchone()
    assert row["pension_status"] == "ACTIVE"   # source feed untouched


def test_notice_period_enforced(c):
    to_notice(c)
    with pytest.raises(WorkflowError):
        wf.suspend(c, 1, SUP)                  # notice not run, no override
    wf.suspend(c, 1, SUP, "override reason")
    assert case(c)["state"] == "HELD"


def test_appeal_restores_and_independent_review(c):
    to_notice(c)
    wf.suspend(c, 1, SUP, "override")
    wf.file_appeal(c, 1, "I am alive")
    k = case(c)
    assert k["state"] == "APPEAL_REVIEW" and k["payment_status"] == "PROVISIONALLY_RESTORED"
    with pytest.raises(WorkflowError):
        wf.resolve_appeal(c, 1, SUP, False, "x")   # approver conflict
    wf.resolve_appeal(c, 1, SUP2, False, "alive confirmed by visit")
    k = case(c)
    assert k["state"] == "RELEASED" and k["payment_status"] == "ACTIVE" and k["outcome"] == "confirmed_alive"


def test_appeal_upheld_resuspends(c):
    to_notice(c)
    wf.file_appeal(c, 1, "x")
    wf.resolve_appeal(c, 1, SUP2, True, "documents forged")
    assert case(c)["state"] == "HELD" and case(c)["payment_status"] == "SUSPENDED"


def test_release_pays_arrears(c):
    to_notice(c)
    wf.suspend(c, 1, SUP, "override")
    c.execute("UPDATE cases SET suspended_at='2026-01-01T00:00:00Z' WHERE id=1")
    arrears = wf.release(c, 1, SUP2, "alive")
    assert arrears > 30000 * 9 and case(c)["payment_status"] == "ACTIVE"


def test_illegal_and_role_checks(c):
    with pytest.raises(WorkflowError):
        wf.suspend(c, 1, SUP)                  # wrong state
    with pytest.raises(WorkflowError):
        wf.dismiss(c, 1, AUD, "x")             # auditor read-only
    with pytest.raises(WorkflowError):
        wf.decide(c, 1, SUP, True)             # nothing pending
    wf.dismiss(c, 1, OFF, "duplicate")
    with pytest.raises(WorkflowError):
        wf.propose(c, 1, "hold", OFF, "r")     # terminal


def test_survivor_routing(c):
    verified(c)
    wf.propose(c, 1, "confirm_death", OFF, "registry match plus hospital record")
    wf.decide(c, 1, SUP, True)
    assert case(c)["state"] == "SURVIVOR_ROUTING"
    for s in c.execute("SELECT id FROM survivor_steps").fetchall():
        wf.complete_survivor_step(c, 1, s["id"], True, "", OFF)
    assert case(c)["state"] == "CLOSED_CONFIRMED"


def test_reject_returns_to_verification(c):
    verified(c)
    wf.propose(c, 1, "hold", OFF, "r")
    with pytest.raises(WorkflowError):
        wf.decide(c, 1, SUP, False, "")
    wf.decide(c, 1, SUP, False, "evidence thin")
    assert case(c)["state"] == "VERIFICATION"


def test_audit_chain_detects_tampering(c):
    to_notice(c)
    ok, n, bad = audit.verify(c)
    assert ok and n > 3
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE audit_chain SET actor='x' WHERE id=1")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM audit_chain WHERE id=2")
    c.execute("DROP TRIGGER audit_chain_no_update")
    c.execute("UPDATE audit_chain SET detail='forged' WHERE id=2")
    ok, _, bad = audit.verify(c)
    assert not ok and bad == 2
