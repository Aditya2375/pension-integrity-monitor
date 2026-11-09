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
    from pim.pipeline import VERIFICATION_STEPS
    for s in VERIFICATION_STEPS:
        conn.execute("INSERT INTO verifications(case_id,step) VALUES(1,?)", (s,))
    conn.commit()
    yield conn
    conn.close()


def verified(c):
    for vid in (1, 2, 3, 4):
        wf.complete_step(c, 1, vid, True, "", OFF)


def to_notice(c):
    verified(c)
    wf.propose(c, 1, "hold", OFF, "no life cert, no bank activity")
    wf.decide(c, 1, SUP, True)


def tid(c):
    return c.execute("SELECT tracking_id FROM appeals WHERE case_id=1").fetchone()["tracking_id"]


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
    wf.file_appeal(c, tid(c), "I am alive")
    k = case(c)
    assert k["state"] == "APPEAL_REVIEW" and k["payment_status"] == "PROVISIONALLY_RESTORED"
    with pytest.raises(WorkflowError):
        wf.resolve_appeal(c, 1, SUP, False, "x")   # approver conflict
    wf.resolve_appeal(c, 1, SUP2, False, "alive confirmed by visit")
    k = case(c)
    assert k["state"] == "RELEASED" and k["payment_status"] == "ACTIVE" and k["outcome"] == "confirmed_alive"


def test_appeal_upheld_resuspends(c):
    to_notice(c)
    wf.file_appeal(c, tid(c), "x")
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


def expire_notice(c):
    c.execute("UPDATE cases SET notice_due_at='2020-01-01T00:00:00Z', appeal_deadline_at='2020-01-01T00:00:00Z' WHERE id=1")


def test_survivor_routing(c):
    verified(c)
    wf.propose(c, 1, "confirm_death", OFF, "registry match plus hospital record")
    wf.decide(c, 1, SUP, True)
    k = case(c)
    assert k["state"] == "NOTICE" and k["case_kind"] == "death" and k["payment_status"] == "ACTIVE"
    expire_notice(c)
    wf.finalize_death(c, 1, SUP)
    assert case(c)["state"] == "SURVIVOR_ROUTING" and case(c)["payment_status"] == "STOP_DECEASED"
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
    ok, why = audit.verify(c)
    assert ok
    cp = audit.checkpoint(c)
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE security_audit SET actor='x' WHERE seq=1")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM security_audit WHERE seq=2")
    c.execute("DROP TRIGGER no_audit_update")
    c.execute("UPDATE security_audit SET action='forged' WHERE seq=2")
    ok, why = audit.verify(c, cp)
    assert not ok


def test_audit_holds_no_free_text(c):
    verified(c)
    wf.propose(c, 1, "hold", OFF, "SECRET-REASON mother name 1234")
    blob = " ".join(str(dict(e)) for e in audit.events(c))
    assert "SECRET" not in blob and "1234" not in blob


def test_reinstatement_is_a_request_not_a_payment(c):
    to_notice(c)
    wf.file_appeal(c, tid(c), "alive")
    r = c.execute("SELECT kind,status FROM reinstatement_requests").fetchall()
    assert [(x["kind"], x["status"]) for x in r] == [("PROVISIONAL", "REQUESTED")]
    wf.resolve_appeal(c, 1, SUP2, False, "alive")
    kinds = [x["kind"] for x in c.execute("SELECT kind FROM reinstatement_requests ORDER BY id")]
    assert kinds == ["PROVISIONAL", "FULL"]


def test_jurisdiction_scope(c):
    c.execute("UPDATE pension_master SET state='KA'")
    verified_actor = Actor("offx", "officer", ("MH",))
    with pytest.raises(WorkflowError):
        wf.complete_step(c, 1, 1, True, "", verified_actor)


def test_notice_enqueues_message_without_personal_data(c):
    to_notice(c)
    from pim import notify
    rows = notify.pending(c)
    assert [r["template"] for r in rows] == ["notice_issued"]
    text = notify.render(rows[0])
    assert tid(c) in text and "Test Person" not in text and "P1" not in text.split(tid(c))[0]


def test_one_appeal_per_notice_and_unknown_id(c):
    to_notice(c)
    wf.file_appeal(c, tid(c), "first")
    with pytest.raises(WorkflowError):
        wf.file_appeal(c, tid(c), "second")
    with pytest.raises(WorkflowError):
        wf.file_appeal(c, "APL-NOPE", "x")


def test_outbox_delivery_retries_then_fails(c):
    to_notice(c)
    from pim import notify
    class Bad(notify.Adapter):
        def send(self, row, text): raise RuntimeError("gateway down")
    for _ in range(notify.MAX_ATTEMPTS):
        notify.deliver(c, Bad())
    assert c.execute("SELECT status FROM notifications").fetchone()["status"] == "FAILED"


# ---- death confirmation has the same safeguards as a hold
def death_notice(c):
    verified(c)
    wf.propose(c, 1, "confirm_death", OFF, "registry match")
    wf.decide(c, 1, SUP, True)


def test_death_not_final_on_first_approval(c):
    death_notice(c)
    assert case(c)["payment_status"] == "ACTIVE" and tid(c)
    from pim import notify
    assert "death_notice_issued" in [r["template"] for r in notify.pending(c)]
    with pytest.raises(WorkflowError):
        wf.finalize_death(c, 1, SUP2)          # period has not ended, no override exists
    with pytest.raises(WorkflowError):
        wf.suspend(c, 1, SUP, "override")      # death notices are not suspended
    with pytest.raises(WorkflowError):
        wf.finalize_death(c, 1, OFF)           # wrong role


def test_death_appeal_independent_review_and_reinstatement(c):
    death_notice(c)
    wf.file_appeal(c, tid(c), "he is alive")
    assert case(c)["state"] == "APPEAL_REVIEW" and case(c)["payment_status"] == "PROVISIONALLY_RESTORED"
    with pytest.raises(WorkflowError):
        wf.resolve_appeal(c, 1, SUP, False, "alive")
    wf.resolve_appeal(c, 1, SUP2, False, "alive, seen by visit")
    assert case(c)["state"] == "RELEASED" and case(c)["payment_status"] == "ACTIVE"
    kinds = [x["kind"] for x in c.execute("SELECT kind FROM reinstatement_requests ORDER BY id")]
    assert kinds == ["PROVISIONAL", "FULL"]


def test_death_appeal_upheld_goes_to_survivor_routing(c):
    death_notice(c)
    wf.file_appeal(c, tid(c), "x")
    wf.resolve_appeal(c, 1, SUP2, True, "documents confirm the death")
    assert case(c)["state"] == "SURVIVOR_ROUTING" and case(c)["payment_status"] == "STOP_DECEASED"


def test_wrongly_declared_death_can_be_reopened(c):
    death_notice(c)
    expire_notice(c)
    wf.finalize_death(c, 1, SUP2)
    with pytest.raises(WorkflowError):
        wf.reopen(c, 1, SUP, "mistake")        # approved the original, so cannot reopen
    with pytest.raises(WorkflowError):
        wf.reopen(c, 1, SUP2, "")              # needs a written reason
    wf.reopen(c, 1, SUP2, "family shows the pensioner is alive")
    assert case(c)["state"] == "APPEAL_REVIEW" and case(c)["payment_status"] == "PROVISIONALLY_RESTORED"
    with pytest.raises(WorkflowError):
        wf.resolve_appeal(c, 1, SUP2, False, "x")   # the reopener cannot also decide
    wf.resolve_appeal(c, 1, Actor("sup3", "supervisor", ("NA",)), False, "alive confirmed")
    assert case(c)["state"] == "RELEASED" and case(c)["outcome"] == "confirmed_alive"
    assert c.execute("SELECT COUNT(*) FROM reinstatement_requests").fetchone()[0] == 2


# ---- universal late-appeal denial
def test_late_appeal_denied_for_every_kind_and_state(c):
    to_notice(c)
    c.execute("UPDATE cases SET appeal_deadline_at='2020-01-01T00:00:00Z' WHERE id=1")
    with pytest.raises(WorkflowError):
        wf.file_appeal(c, tid(c), "late")
    assert case(c)["state"] == "NOTICE"
    wf.suspend(c, 1, SUP, "override")             # a held case is denied just the same
    with pytest.raises(WorkflowError):
        wf.file_appeal(c, tid(c), "late")


def test_missing_deadline_is_denied_not_allowed(c):
    to_notice(c)
    c.execute("UPDATE cases SET appeal_deadline_at=NULL WHERE id=1")
    with pytest.raises(WorkflowError):
        wf.file_appeal(c, tid(c), "x")


def test_changing_the_setting_cannot_extend_an_issued_notice(c):
    to_notice(c)
    dl = case(c)["appeal_deadline_at"]
    c.execute("UPDATE settings SET value='3650' WHERE key='appeal_window_days'")
    c.execute("UPDATE cases SET appeal_deadline_at='2020-01-01T00:00:00Z' WHERE id=1")
    with pytest.raises(WorkflowError):
        wf.file_appeal(c, tid(c), "late")
    assert dl and dl > "2026"


def test_double_filing_is_single(c):
    to_notice(c)
    wf.file_appeal(c, tid(c), "one")
    with pytest.raises(WorkflowError):
        wf.file_appeal(c, tid(c), "two")
    assert c.execute("SELECT COUNT(*) FROM reinstatement_requests").fetchone()[0] == 1
