import os, sys, tempfile, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
_d = tempfile.mkdtemp()
os.environ["PIM_DB"] = os.path.join(_d, "t.sqlite3")
os.environ["PIM_LIMITER_DB"] = os.path.join(_d, "limits.sqlite3")
os.environ["PIM_EVIDENCE_DIR"] = os.path.join(_d, "evidence")
os.environ["PIM_INSECURE_HTTP"] = "1"
os.environ["PIM_DEMO_SHOW_OTP"] = "1"
os.environ["PIM_USERS"] = ("rev1:officer:TestState:reviewer-key-1;rev2:officer:TestState:reviewer-key-2;"
                           "sup1:supervisor:TestState:supervisor-key-1;sup2:supervisor:TestState:supervisor-key-2;"
                           "aud1:auditor:TestState:auditor-key-1;adm1:admin:TestState:admin-key-1;"
                           "kar1:officer:KA:karnataka-key-1")
import pytest
import app as app_module

TOKEN = re.compile(r'name="csrf_token" value="([0-9a-f]{64})"')


class Client:
    """Test client that carries the CSRF token like a browser does."""
    def __init__(self):
        app_module.app.config["TESTING"] = True
        self.c = app_module.app.test_client()

    def token(self, path="/login"):
        r = self.c.get(path)
        m = TOKEN.search(r.get_data(as_text=True))
        assert m, f"no csrf token on {path}"
        return m.group(1)

    def post(self, path, data=None, token=True, **kw):
        data = dict(data or {})
        if token is True:
            data["csrf_token"] = self.token("/login" if "csrf" not in kw else kw.pop("csrf"))
        return self.c.post(path, data=data, **kw)

    def get(self, path, **kw):
        return self.c.get(path, **kw)

    def login(self, user, key):
        app_module._limiter = None
        r = self.post("/login", {"username": user, "key": key}, follow_redirects=True)
        return r


def as_user(user):
    cl = Client()
    keys = dict(rev1="reviewer-key-1", rev2="reviewer-key-2", sup1="supervisor-key-1", sup2="supervisor-key-2",
                aud1="auditor-key-1", adm1="admin-key-1", kar1="karnataka-key-1")
    r = cl.login(user, keys[user])
    assert b"Sign out" in r.data, user
    return cl


@pytest.fixture
def fresh_db():
    from pim import db, workflow
    import importlib, tempfile
    path = os.path.join(tempfile.mkdtemp(), "x.sqlite3")
    db.DB_PATH = path
    db.init_db()
    c = db.connect()
    workflow.ensure_schema(c)
    from pim import users
    users.bootstrap_from_env(c)
    c.close()
    app_module._limiter = None
    os.environ["PIM_LIMITER_DB"] = path + ".limits"
    return path


import struct, zlib


def make_png(w=2, h=2):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_pdf():
    return (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
            b"xref\n0 3\n0000000000 65535 f \ntrailer\n<< /Root 1 0 R /Size 3 >>\nstartxref\n9\n%%EOF\n")
