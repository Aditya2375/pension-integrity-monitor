"""Round four findings: concurrency and the late-appeal intake path."""
import threading
import pytest
from conftest import Client
from pim import db, workflow as wf
from pim.pipeline import VERIFICATION_STEPS
from pim.workflow import Actor, WorkflowError

OFF = lambda n: Actor(n, "officer", ("TestState",))
SUP = lambda n: Actor(n, "supervisor", ("TestState",))


def make_case(state="VERIFICATION", steps=True):
    c = db.connect()
    c.execute("INSERT OR IGNORE INTO pension_master(pensioner_id,full_name,state,monthly_amount) VALUES('L','Local','TestState',100)")
    c.execute("INSERT INTO cases(pensioner_id,state,probability,created_at) VALUES('L',?,.5,'2026-11-01T00:00:00Z')", (state,))
    cid = c.execute("SELECT max(id) FROM cases").fetchone()[0]
    if steps:
        for s in VERIFICATION_STEPS:
            c.execute("INSERT INTO verifications(case_id,step,done) VALUES(?,?,1)", (cid, s))
    c.commit(); c.close()
    return cid


def race(monkeypatch, jobs):
    """Run each job in its own thread and connection, all released together
    at the first case read (before any lock)."""
    gate = threading.Barrier(len(jobs))
    local = threading.local()
    orig = wf._lock
    def gated(conn):
        if not getattr(local, "waited", False):
            local.waited = True
            gate.wait(timeout=10)
        return orig(conn)
    monkeypatch.setattr(wf, "_lock", gated)
    out = []
    def run(job):
        conn = db.connect()
        try:
            job(conn); conn.commit(); out.append(("ok", None))
        except WorkflowError as e:
            conn.rollback(); out.append(("err", str(e)))
        except Exception as e:           # a lock timeout also means no double write
            conn.rollback(); out.append(("exc", repr(e)))
        finally:
            conn.close()
    ts = [threading.Thread(target=run, args=(j,)) for j in jobs]
    [t.start() for t in ts]; [t.join() for t in ts]
    return out


def count(sql, *a):
    c = db.connect(); n = c.execute(sql, a).fetchone()[0]; c.close(); return n


def test_concurrent_proposals_make_one(fresh_db, monkeypatch):
    cid = make_case()
    out = race(monkeypatch, [lambda c, n=n: wf.propose(c, cid, "hold", OFF(n), "r") for n in ("o1", "o2")])
    assert [o[0] for o in out].count("ok") == 1
    assert count("SELECT COUNT(*) FROM decisions WHERE case_id=?", cid) == 1
    assert count("SELECT COUNT(*) FROM decisions WHERE status='PENDING'") == 1


def test_concurrent_hold_and_death_proposals(fresh_db, monkeypatch):
    cid = make_case()
    out = race(monkeypatch, [lambda c: wf.propose(c, cid, "hold", OFF("o1"), "r"),
                             lambda c: wf.propose(c, cid, "confirm_death", OFF("o2"), "r")])
    assert [o[0] for o in out].count("ok") == 1
    assert count("SELECT COUNT(*) FROM decisions WHERE case_id=?", cid) == 1


def test_pending_uniqueness_enforced_by_database(fresh_db):
    cid = make_case()
    c = db.connect()
    c.execute("INSERT INTO decisions(case_id,kind,proposer,reason,proposed_at) VALUES(?,?,?,?,?)", (cid, "hold", "a", "r", "t"))
    with pytest.raises(Exception):
        c.execute("INSERT INTO decisions(case_id,kind,proposer,reason,proposed_at) VALUES(?,?,?,?,?)", (cid, "hold", "b", "r", "t"))
    c.close()


def test_concurrent_approvals_issue_one_notice(fresh_db, monkeypatch):
    cid = make_case()
    c = db.connect(); wf.propose(c, cid, "hold", OFF("o1"), "r"); c.commit(); c.close()
    out = race(monkeypatch, [lambda c, n=n: wf.decide(c, cid, SUP(n), True) for n in ("s1", "s2")])
    assert [o[0] for o in out].count("ok") == 1
    assert count("SELECT COUNT(*) FROM appeals WHERE case_id=?", cid) == 1
    assert count("SELECT COUNT(*) FROM decisions WHERE status='APPROVED'") == 1


def test_approve_races_reject(fresh_db, monkeypatch):
    cid = make_case()
    c = db.connect(); wf.propose(c, cid, "hold", OFF("o1"), "r"); c.commit(); c.close()
    out = race(monkeypatch, [lambda c: wf.decide(c, cid, SUP("s1"), True),
                             lambda c: wf.decide(c, cid, SUP("s2"), False, "no")])
    assert [o[0] for o in out].count("ok") == 1


def _noticed(kind="hold"):
    cid = make_case()
    c = db.connect()
    wf.propose(c, cid, "hold" if kind == "hold" else "confirm_death", OFF("o1"), "r")
    wf.decide(c, cid, SUP("s1"), True)
    tid = c.execute("SELECT tracking_id FROM appeals WHERE case_id=?", (cid,)).fetchone()[0]
    c.commit(); c.close()
    return cid, tid


def test_concurrent_appeals_file_once(fresh_db, monkeypatch):
    cid, tid = _noticed()
    out = race(monkeypatch, [lambda c: wf.file_appeal(c, tid, "alive") for _ in range(3)])
    assert [o[0] for o in out].count("ok") == 1
    assert count("SELECT COUNT(*) FROM reinstatement_requests WHERE case_id=?", cid) == 1


def test_finalise_races_appeal_death_not_lost(fresh_db, monkeypatch):
    cid, tid = _noticed("death")
    c = db.connect()
    past = "2020-01-01T00:00:00Z"
    c.execute("UPDATE cases SET notice_due_at=? WHERE id=?", (past, cid)); c.commit(); c.close()
    # deadline still in the future: finalise must refuse, appeal must win
    out = race(monkeypatch, [lambda c: wf.finalize_death(c, cid, SUP("s2")),
                             lambda c: wf.file_appeal(c, tid, "I am alive")])
    c = db.connect(); st = c.execute("SELECT state FROM cases WHERE id=?", (cid,)).fetchone()[0]; c.close()
    assert st == "APPEAL_REVIEW"


def test_finalise_races_finalise_and_late_intake(fresh_db, monkeypatch):
    cid, tid = _noticed("death")
    c = db.connect()
    past = "2020-01-01T00:00:00Z"
    c.execute("UPDATE cases SET notice_due_at=?, appeal_deadline_at=? WHERE id=?", (past, past, cid)); c.commit(); c.close()
    out = race(monkeypatch, [lambda c: wf.finalize_death(c, cid, SUP("s2")),
                             lambda c: wf.accept_late_appeal(c, cid, SUP("s3"), "ILLNESS", "was in hospital")])
    assert [o[0] for o in out].count("ok") == 1
    c = db.connect(); st = c.execute("SELECT state FROM cases WHERE id=?", (cid,)).fetchone()[0]; c.close()
    assert st in ("SURVIVOR_ROUTING", "APPEAL_REVIEW")


def test_concurrent_reopen_once(fresh_db, monkeypatch):
    cid, tid = _noticed("death")
    c = db.connect()
    past = "2020-01-01T00:00:00Z"
    c.execute("UPDATE cases SET notice_due_at=?, appeal_deadline_at=? WHERE id=?", (past, past, cid))
    wf.finalize_death(c, cid, SUP("s2")); c.commit(); c.close()
    out = race(monkeypatch, [lambda c, n=n: wf.reopen(c, cid, SUP(n), "wrong") for n in ("s3", "s4")])
    assert [o[0] for o in out].count("ok") == 1
    assert count("SELECT COUNT(*) FROM reinstatement_requests WHERE case_id=?", cid) == 1


def test_revoked_actor_cannot_act(fresh_db):
    cid = make_case()
    c = db.connect()
    c.execute("INSERT INTO users(username,role,salt,key_hash,active,jurisdictions) VALUES('o9','officer','s','h',1,'TestState')")
    c.commit()
    stale = OFF("o9")                         # identity read before revocation
    c.execute("UPDATE users SET active=0 WHERE username='o9'"); c.commit()
    with pytest.raises(WorkflowError):
        wf.propose(c, cid, "hold", stale, "r")
    c.rollback()
    assert c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    c.execute("UPDATE users SET active=1, role='auditor' WHERE username='o9'"); c.commit()
    with pytest.raises(WorkflowError):
        wf.propose(c, cid, "hold", stale, "r")
    c.close()


def test_late_appeal_portal_still_refused_but_officer_can_intake(fresh_db):
    cid, tid = _noticed()
    c = db.connect()
    past = "2020-01-01T00:00:00Z"
    c.execute("UPDATE cases SET appeal_deadline_at=? WHERE id=?", (past, cid)); c.commit()
    with pytest.raises(WorkflowError):
        wf.file_appeal(c, tid, "late")
    c.rollback()
    with pytest.raises(WorkflowError):
        wf.accept_late_appeal(c, cid, SUP("s1"), "ILLNESS", "x")      # approver cannot
    c.rollback()
    with pytest.raises(WorkflowError):
        wf.accept_late_appeal(c, cid, SUP("s2"), "MADE_UP", "x")
    c.rollback()
    with pytest.raises(WorkflowError):
        wf.accept_late_appeal(c, cid, SUP("s2"), "ILLNESS", "")
    c.rollback()
    wf.accept_late_appeal(c, cid, SUP("s2"), "ILLNESS", "hospital letter seen"); c.commit()
    case = c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    assert case["state"] == "APPEAL_REVIEW" and case["payment_status"] == "PROVISIONALLY_RESTORED"
    assert c.execute("SELECT COUNT(*) FROM reinstatement_requests WHERE kind='PROVISIONAL'").fetchone()[0] == 1
    with pytest.raises(WorkflowError):
        wf.resolve_appeal(c, cid, SUP("s2"), False, "n")               # intake supervisor cannot decide
    c.rollback()
    wf.resolve_appeal(c, cid, SUP("s3"), False, "alive confirmed"); c.commit()
    assert c.execute("SELECT state FROM cases WHERE id=?", (cid,)).fetchone()[0] == "RELEASED"
    c.close()


def test_late_intake_refused_while_period_open(fresh_db):
    cid, tid = _noticed()
    c = db.connect()
    with pytest.raises(WorkflowError):
        wf.accept_late_appeal(c, cid, SUP("s2"), "ILLNESS", "x")
    c.close()
