import os, tempfile, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["PIM_DB"] = tempfile.mkstemp(suffix=".sqlite3")[1]
os.environ.setdefault("PIM_OFFICER_KEY", "officer")
os.environ.setdefault("PIM_INSECURE_HTTP", "1")
os.environ["PIM_CHECKPOINT_DIR"] = tempfile.mkdtemp()
from app import app
from tests.http_client import FormClient
app.test_client_class = FormClient

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
    ("GET", "/officers"), ("POST", "/officers/add"),
    ("POST", "/officers/1/deactivate"),
    ("POST", "/case/1/approve-hold"), ("POST", "/case/1/reject-hold"),
]

def test_logged_out_denied():
    c = app.test_client()
    for method, path in PROTECTED:
        r = c.open(path, method=method)
        assert r.status_code in (302, 400, 401, 403), f"{method} {path} -> {r.status_code}"
        if r.status_code == 302:
            assert "/login" in r.headers["Location"], f"{method} {path} redirects elsewhere"

def test_public_pages_ok():
    c = app.test_client()
    for path in ["/login", "/appeal", "/context", "/templates/pension_master.csv"]:
        r = c.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"

def test_no_bootstrap_without_key():
    """With no PIM_OFFICER_KEY at first start, no officer account is created
    and sign-in stays closed."""
    import importlib, app as appmod
    from pim import db
    os.environ["PIM_DB"] = tempfile.mkstemp(suffix=".sqlite3")[1]
    saved_db = db.DB_PATH
    old_key = os.environ.pop("PIM_OFFICER_KEY", None)
    importlib.reload(db)
    importlib.reload(appmod)
    appmod.app.test_client_class = FormClient
    c = appmod.app.test_client()
    r = c.post("/login", data={"username": "admin", "key": "anything"})
    assert r.status_code == 200 and b"No officer account" in r.data
    os.environ["PIM_DB"] = saved_db
    if old_key is not None: os.environ["PIM_OFFICER_KEY"] = old_key
    importlib.reload(db)
    importlib.reload(appmod)

def test_login_throttle():
    import app as appmod
    appmod.app.test_client_class = FormClient
    c = appmod.app.test_client()
    for _ in range(6):
        r = c.post("/login", data={"username": "admin", "key": "wrong"})
    assert b"Too many attempts" in r.data
    import app as appmod
    appmod._ATTEMPTS.clear()
