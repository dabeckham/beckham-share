"""Access control: the workspace is gated to the `dropbox` group, and the
authenticated flow canonicalizes to share.beckham.ai."""


def test_app_requires_login(client):
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_app_denies_non_group_member(client, nonmember):
    r = client.get("/app")
    assert r.status_code == 403
    assert "Access required" in r.text


def test_member_reaches_app(client, member):
    assert client.get("/app").status_code == 200


def test_member_sees_source_link(client, member):
    from app.config import settings

    r = client.get("/app")
    assert r.status_code == 200
    assert settings.source_url
    assert settings.source_url in r.text


def test_api_upload_forbidden_for_anonymous(client):
    r = client.post("/api/files", files={"file": ("x.txt", b"x", "text/plain")}, data={"expiry_hours": "24"})
    assert r.status_code == 403


def test_api_upload_forbidden_for_non_member(client, nonmember):
    r = client.post("/api/files", files={"file": ("x.txt", b"x", "text/plain")}, data={"expiry_hours": "24"})
    assert r.status_code == 403


def test_app_canonicalizes_other_host(client):
    r = client.get("/app", headers={"host": "dropbox.beckham.ai"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://share.beckham.ai/app"


def test_login_canonicalizes_other_host(client):
    r = client.get("/login", headers={"host": "buckets.beckham.ai"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://share.beckham.ai/login"
