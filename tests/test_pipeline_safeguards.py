"""Safeguards for the pipeline and the local audit chain, ported to the
named-user staff model: queue-flooding circuit breaker, randomized audit
sampling, tamper-evident chain with anchors, crash boundaries, rollback
detection and reconcile. Each test uses one fresh database per module so the
chain state is deterministic."""
import os, sys, tempfile, pathlib, random, shutil, hashlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="module")
def dbs():
    d = tempfile.mkdtemp()
    os.environ["PIM_CHECKPOINT_DIR"] = os.path.join(d, "checkpoints")
    from pim import db, workflow, users
    old_path = db.DB_PATH
    db.DB_PATH = os.path.join(d, "safeguards.sqlite3")
    db.init_db().close()
    c = db.connect()
    workflow.ensure_schema(c)
    users.bootstrap_from_env(c)
    c.close()
    yield db
    db.DB_PATH = old_path


def test_audit_chain_tamper_detection(dbs):
    db = dbs
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


def test_anchor_mismatch_detects_db_rewrite(dbs):
    """Rewriting only the database (attacker misses the anchor file) is caught."""
    db = dbs
    conn = db.connect()
    db.log(conn, "tester", "anchor_check", "before")
    conn.commit()
    ok, _, _ = db.verify_audit(conn)
    assert ok
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    row = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = row["prev_hash"]
    body = f"{prev}|{row['ts']}|{row['actor']}|{row['action']}|forged"
    conn.execute("UPDATE audit SET detail='forged', hash=? WHERE id=?",
                 (hashlib.sha256(body.encode()).hexdigest(), row["id"]))
    conn.commit()
    ok, bad, _ = db.verify_audit(conn)
    assert not ok  # anchor file still holds the real head hash
    body = f"{prev}|{row['ts']}|{row['actor']}|{row['action']}|before"
    conn.execute("UPDATE audit SET detail='before', hash=? WHERE id=?",
                 (hashlib.sha256(body.encode()).hexdigest(), row["id"]))
    conn.commit()
    ok, _, _ = db.verify_audit(conn)
    assert ok
    conn.close()


def test_inconsistent_audit_cannot_be_extended(dbs):
    db = dbs
    import sqlite3
    c = db.connect()
    db.log(c, 'tester', 'baseline', '')
    c.commit()
    anchor = db._anchor_path()
    original = pathlib.Path(anchor).read_text()
    pathlib.Path(anchor).write_text('malformed\n')
    try:
        assert db.verify_audit(c)[0] is False
        with pytest.raises(sqlite3.IntegrityError):
            db.log(c, 'tester', 'should-fail', '')
        c.rollback()
    finally:
        pathlib.Path(anchor).write_text(original)
        c.close()


def test_default_anchor_tracks_database_path(dbs):
    assert dbs._anchor_path() == dbs.DB_PATH + '.anchor'


def test_crash_chaos_at_every_write_boundary(dbs):
    """Kill the append at each boundary; no ambiguous state may be trusted."""
    db = dbs
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


def test_reconcile_flags_unaudited_hold(dbs):
    db = dbs
    conn = db.connect()
    conn.execute("INSERT INTO pension_master(pensioner_id,state,full_name) VALUES('RS1','TestState','Synthetic')")
    conn.execute("INSERT INTO cases(pensioner_id,state,probability,created_at) VALUES('RS1','VERIFICATION',0.5,'2026-11-01T00:00:00Z')")
    cid = conn.execute("SELECT max(id) m FROM cases").fetchone()["m"]
    conn.execute("UPDATE cases SET state='HELD', held_at='2026-01-01T00:00:00Z' WHERE id=?", (cid,))
    assert any(f"case {cid} " in p for p in db.reconcile(conn))
    conn.execute("DELETE FROM cases WHERE id=?", (cid,))
    conn.execute("DELETE FROM pension_master WHERE pensioner_id='RS1'")
    conn.commit(); conn.close()


def test_pipeline_cap_not_shadowed_by_weak_evidence(dbs):
    import inspect
    from pim import pipeline
    source = inspect.getsource(pipeline.run_pipeline)
    assert 'made >= case_cap' in source
    assert 'made + sampled >= case_cap' in source
    assert "'VERIFICATION','HELD','HOLD_PENDING'" in source


def test_circuit_breaker_and_audit_sampling(dbs):
    from conftest import as_user
    c = as_user("adm1")
    for feed in ["pension_master", "pension_disbursements", "death_registry", "electoral_roll",
                 "bank_transactions", "life_certificates", "telecom_activity", "hospital_records",
                 "tax_pan_activity", "utility_bills", "toll_fastag"]:
        data = {"file": (open(FIX / f"{feed}.csv", "rb"), f"{feed}.csv")}
        r = c.post(f"/ingest/{feed}", data=data, content_type="multipart/form-data", follow_redirects=True)
        assert r.status_code == 200, feed
    db = dbs
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
    from pim import pipeline
    pipeline.run_pipeline(conn, rng=random.Random(7)); conn.commit()
    samples = conn.execute(
        "SELECT cases.id FROM cases JOIN signals s ON s.case_id=cases.id WHERE s.signal='audit_sample'").fetchall()
    assert len(samples) >= 1
    conn.close()

    # dashboard reports the (untampered) chain as intact
    r = c.get("/")
    assert b"intact" in r.data


def test_appeal_overdue_marker(dbs):
    from conftest import as_user
    c = as_user("adm1")
    db = dbs
    conn = db.connect()
    row = conn.execute("SELECT id FROM cases LIMIT 1").fetchone()
    assert row is not None
    cid = row["id"]
    conn.execute(
        "INSERT INTO appeals(tracking_id,case_id,submitted_at,statement,status) VALUES(?,?,?,?, 'OPEN')",
        ("APL-TESTOLD1", cid, "2020-01-01T00:00:00Z", "old appeal"))
    conn.commit(); conn.close()
    r = c.get("/")
    m = re.search(rb'class="n">(\d+)</div><div class="l">Appeals open past the response SLA', r.data)
    assert m and int(m.group(1)) >= 1


def test_rollback_of_db_and_local_anchor_is_caught(dbs):
    db = dbs
    dbp = db.DB_PATH
    c = db.connect(); db.log(c, "t", "keep", "1"); c.commit(); c.close()
    shutil.copy(dbp, dbp + ".old"); shutil.copy(dbp + ".anchor", dbp + ".anchor.old")
    c = db.connect(); db.log(c, "t", "later", "2"); db.log(c, "t", "later", "3"); c.commit(); c.close()
    # attacker restores an older, mutually consistent database + local anchor
    shutil.copy(dbp + ".old", dbp); shutil.copy(dbp + ".anchor.old", dbp + ".anchor")
    c = db.connect()
    ok, bad, _ = db.verify_audit(c)
    assert ok is False, "rollback of database and local anchor went undetected"
    c.close()
