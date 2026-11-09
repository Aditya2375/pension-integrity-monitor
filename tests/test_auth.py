import pytest
from conftest import Client, as_user
import app as app_module

PUBLIC_GET = ["/login", "/appeal", "/context", "/templates/pension_master.csv", "/static/style.css"]
PROTECTED_GET = ["/", "/queue", "/queue/export", "/case/1", "/appeals", "/feedback", "/health", "/ingest", "/settings", "/evidence/1"]
PROTECTED_POST = ["/pipeline/run", "/ingest/pension_master", "/case/1/propose", "/case/1/decide", "/case/1/release",
                  "/case/1/dismiss", "/case/1/verify", "/case/1/suspend", "/case/1/appeal-decision", "/case/1/note",
                  "/feedback/recalibrate", "/settings", "/logout"]


def test_logged_out_denied(fresh_db):
    cl = Client()
    for p in PROTECTED_GET:
        r = cl.get(p)
        assert r.status_code == 302 and "/login" in r.headers["Location"], p
    for p in PROTECTED_POST:
        r = cl.post(p, {})            # with a valid CSRF token, still no session
        assert r.status_code in (302, 401, 403), p


def test_posts_without_csrf_rejected(fresh_db):
    cl = as_user("rev1")
    for p in PROTECTED_POST + ["/login", "/appeal"]:
        r = cl.post(p, {}, token=False)
        assert r.status_code == 400, p
    r = cl.post("/appeal", {"action": "send_code", "tracking_id": "X"}, token=False)
    assert r.status_code == 400


def test_public_pages_ok(fresh_db):
    cl = Client()
    for p in PUBLIC_GET:
        assert cl.get(p).status_code == 200, p


def test_wrong_key_and_unknown_user(fresh_db):
    cl = Client()
    assert b"Wrong username or key" in cl.post("/login", {"username": "rev1", "key": "nope"}).data
    assert b"Wrong username or key" in cl.post("/login", {"username": "ghost", "key": "reviewer-key-1"}).data


def test_login_throttle(fresh_db):
    cl = Client()
    for _ in range(12):
        r = cl.post("/login", {"username": "rev1", "key": "wrong"})
    assert b"Too many attempts" in r.data


def test_logout_is_post_only_and_clears_session(fresh_db):
    cl = as_user("rev1")
    assert cl.get("/logout").status_code == 405
    cl.post("/logout", {})
    assert cl.get("/queue").status_code == 302


def test_session_and_csrf_rotate_on_login(fresh_db):
    cl = Client()
    before = cl.token()
    cl.post("/login", {"username": "rev1", "key": "reviewer-key-1"})
    after = cl.token("/queue")
    assert before != after


def test_role_gates(fresh_db):
    rev, aud = as_user("rev1"), as_user("aud1")
    assert rev.get("/settings").status_code == 403
    assert rev.post("/pipeline/run", {}).status_code == 403
    assert aud.post("/case/1/dismiss", {"note": "x"}).status_code == 403
    assert aud.get("/queue").status_code == 200


def test_untrusted_forwarded_header_does_not_change_limit_bucket(fresh_db):
    cl = Client()
    for i in range(12):
        r = cl.c.post("/login", data={"username": "rev1", "key": "bad", "csrf_token": cl.token()},
                      headers={"X-Forwarded-For": f"10.0.0.{i}"})
    assert b"Too many attempts" in r.data
