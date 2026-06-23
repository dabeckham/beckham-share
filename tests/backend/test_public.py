"""Public pages: health, landing, and logged-in redirect."""


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_landing_anonymous(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "Send a file" in body          # hero copy
    assert 'href="/login"' in body         # login link is present
    assert "dropzone" in body              # upload component rendered


def test_landing_redirects_logged_in_member(client, member):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/app"
