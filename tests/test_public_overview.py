from conftest import Client, as_user


def test_root_is_public_overview(fresh_db):
    r = Client().get("/")
    assert r.status_code == 200
    t = r.get_data(as_text=True)
    assert "Staff sign in" in t and "Synthetic demo" in t
    assert "No real-world accuracy has been measured" in t
    assert "Manual pipeline" in t
    # no credentials or staff data on the public page
    for needle in ("rev1", "sup1", "adm1", "reviewer-key", "admin-key", "Dashboard"):
        assert needle not in t, needle


def test_benchmark_page_separate_from_app_scorer(fresh_db):
    t = Client().get("/benchmark").get_data(as_text=True)
    assert "99.13%" in t and "88.81%" in t and "synthetic" in t.lower()
    assert "not the score the app shows" in t


def test_staff_dashboard_still_authenticated(fresh_db):
    r = Client().get("/staff")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert as_user("adm1").get("/staff").status_code == 200


def test_login_lands_on_staff_dashboard(fresh_db):
    c = Client()
    r = c.post("/login", {"username": "adm1", "key": "admin-key-1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff")
