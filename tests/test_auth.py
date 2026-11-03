import os, tempfile, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["PIM_DB"] = tempfile.mkstemp(suffix=".sqlite3")[1]
os.environ.setdefault("PIM_OFFICER_KEY", "officer")
os.environ.setdefault("PIM_INSECURE_HTTP", "1")
from app import app

PUBLIC_GET = {"/login", "/appeal", "/context", "/templates/pension_master.csv", "/static/style.css"}

PROTECTED = [
    ("GET", "/"), ("GET", "/queue"), ("GET", "/queue/export"),
    ("GET", "/case/1"), ("GET", "/appeals"), ("GET", "/feedback"),
    ("GET", "/health"), ("GET", "/ingest"), ("GET", "/settings"),
    ("POST", "/pipeline/run"), ("POST", "/ingest/pension_master"),
    ("POST", "/case/1/hold"), ("POST", "/case/1/release"),
    ("POST", "/case/1/dismiss"), ("POST", "/case/1/verify"),
    ("POST", "/case/1/outcome"), ("POST", "/appeals/1/resolve"),
    ("POST", "/feedback/recalibrate"), ("POST", "/settings"),
]

def test_logged_out_denied():
    c = app.test_client()
    for method, path in PROTECTED:
        r = c.open(path, method=method)
        assert r.status_code in (302, 401, 403), f"{method} {path} -> {r.status_code}"
        if r.status_code == 302:
            assert "/login" in r.headers["Location"], f"{method} {path} redirects elsewhere"

def test_public_pages_ok():
    c = app.test_client()
    for path in ["/login", "/appeal", "/context", "/templates/pension_master.csv"]:
        r = c.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"

def test_officer_disabled_without_key(monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, "OFFICER_KEY", None)
    c = app.test_client()
    r = c.post("/login", data={"key": "anything"})
    assert r.status_code == 200 and b"not configured" in r.data

def test_login_throttle():
    c = app.test_client()
    for _ in range(6):
        r = c.post("/login", data={"key": "wrong"})
    assert b"Too many attempts" in r.data
    import app as appmod
    appmod._ATTEMPTS.clear()
