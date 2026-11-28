import time
import pytest
from conftest import as_user
import app as app_module
from security.web import client_ip


def test_idle_session_expires(fresh_db, monkeypatch):
    cl = as_user("adm1")
    assert cl.get("/staff").status_code == 200
    monkeypatch.setattr(app_module, "IDLE_SECONDS", 1)
    time.sleep(1.3)
    r = cl.get("/staff")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_active_session_stays(fresh_db):
    cl = as_user("adm1")
    for _ in range(3):
        assert cl.get("/staff").status_code == 200


def test_edge_header_only_trusted_from_trusted_peer():
    trusted = ("10.0.0.0/8",)
    # peer is the proxy: the edge header names the client
    assert client_ip("10.1.2.3", "1.1.1.1, 172.70.0.1", trusted, "203.0.113.9") == "203.0.113.9"
    # peer is NOT a trusted proxy: header is ignored, spoofing does not work
    assert client_ip("198.51.100.7", None, trusted, "203.0.113.9") == "198.51.100.7"
    # garbage header from a trusted peer: falls back, never raises
    assert client_ip("10.1.2.3", None, trusted, "not-an-ip") == "10.1.2.3"
    # nothing configured: socket peer, as before
    assert client_ip("10.1.2.3", "9.9.9.9", (), "203.0.113.9") == "10.1.2.3"
