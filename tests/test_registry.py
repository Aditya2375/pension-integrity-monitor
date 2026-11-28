"""Death registry reconciliation: read-only, never freezes, drafts only."""
import pytest
from conftest import as_user, Client
from test_flow import load
from pim import db, registry


def test_registry_page_needs_login(fresh_db):
    r = Client().get("/registry")
    assert r.status_code in (301, 302, 401, 403)


def test_reconcile_and_draft(fresh_db):
    adm, rev = as_user("adm1"), as_user("rev1")
    load(adm)
    c = db.connect()
    rec = registry.reconcile(c)
    assert rec["registrations"] >= 1
    assert rec["matched_registrations"] + rec["unmatched_registrations"] == rec["registrations"]
    row = c.execute("SELECT id FROM cases WHERE matched_death_id IS NOT NULL ORDER BY probability DESC").fetchone()
    assert row, "fixture should produce a registry-matched case"
    before = c.execute("SELECT state, hold_reasons, held_at FROM cases WHERE id=?", (row["id"],)).fetchone()
    n_audit = c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    d = registry.draft_reasons(c, row["id"])
    after = c.execute("SELECT state, hold_reasons, held_at FROM cases WHERE id=?", (row["id"],)).fetchone()
    # drafting and reconciling change nothing: no state move, no hold, no audit entry
    assert tuple(before) == tuple(after)
    assert c.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == n_audit
    assert "lead, not proof" in d and "registrar" in d and "appeal" in d
    c.close()
    page = rev.get("/registry")
    assert page.status_code == 200 and b"never freezes anything by itself" in page.data
    case = rev.get(f"/case/{row['id']}").data
    assert b"Draft from the death registry" in case


def test_hostile_registry_text_is_escaped(fresh_db):
    adm = as_user("adm1")
    load(adm)
    c = db.connect()
    c.execute("UPDATE death_registry SET district='<script>alert(1)</script>'")
    c.commit(); c.close()
    page = adm.get("/registry").data
    assert b"<script>alert(1)</script>" not in page
    cid = db.connect().execute("SELECT id FROM cases WHERE matched_death_id IS NOT NULL").fetchone()["id"]
    assert b"<script>alert(1)</script>" not in adm.get(f"/case/{cid}").data


def test_no_post_route_can_hold_from_registry(fresh_db):
    adm = as_user("adm1")
    for m in ("post", "put", "delete"):
        r = getattr(adm.c if m != "post" else adm, m)("/registry") if m != "post" else adm.post("/registry", {})
        assert r.status_code in (400, 404, 405)


def test_registry_page_respects_jurisdiction(fresh_db):
    """A user scoped to one state must not see registry-matched cases of another."""
    adm = as_user("adm1")
    load(adm)
    c = db.connect()
    full = registry.reconcile(c)
    assert full["rows"], "fixture should have matched cases"
    rows_scoped = registry.reconcile(c, {"ZZ_NOWHERE"})
    assert rows_scoped["rows"] == [] and rows_scoped["matched_registrations"] == 0
    assert rows_scoped["exposure_total"] == 0
    c.close()
    kar = as_user("kar1")
    page = kar.get("/registry").data
    for r in full["rows"]:
        st = db.connect().execute("SELECT COALESCE(p.state,'NA') s FROM cases c JOIN pension_master p USING(pensioner_id) WHERE c.id=?", (r["case_id"],)).fetchone()["s"]
        if st != "KA" and st != "Karnataka":
            assert f"/case/{r['case_id']}\"".encode() not in page
