"""Core feature: upload, UUID share links, download, expiry, revoke, delete, email."""
from datetime import timedelta

from app.db import SessionLocal
from app.models import ShareLink, utcnow

CONTENT = b"the quick brown fox\n"
NAME = "report.txt"


def _anon_upload(client, content=CONTENT, name=NAME):
    return client.post("/api/anon-upload", files={"file": (name, content, "text/plain")}, data={"fp": "fp-a"})


def test_anon_upload_returns_uuid_link_without_filename(client):
    r = _anon_upload(client)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    token = data["token"]
    # Link is a UUID under the canonical host and never contains the filename.
    assert data["share_url"] == f"https://share.beckham.ai/s/{token}"
    assert NAME not in data["share_url"]
    assert len(token) == 36 and token.count("-") == 4
    assert data["expires_at"] is not None  # anonymous uploads always expire


def test_share_page_and_download_roundtrip(client):
    token = _anon_upload(client).json()["token"]

    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    assert NAME in page.text  # share page shows the real filename

    dl = client.get(f"/d/{token}")
    assert dl.status_code == 200
    assert dl.content == CONTENT  # exact bytes
    assert NAME in dl.headers.get("content-disposition", "")  # restored on save only


def test_expired_link_returns_410(client):
    token = _anon_upload(client).json()["token"]
    with SessionLocal() as s:
        link = s.get(ShareLink, token)
        link.expires_at = utcnow() - timedelta(hours=1)
        s.commit()
    assert client.get(f"/s/{token}").status_code == 410
    assert client.get(f"/d/{token}").status_code == 410


def test_unknown_link_returns_404(client):
    assert client.get("/s/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/d/00000000-0000-0000-0000-000000000000").status_code == 404


def test_member_upload_lists_and_shares(client, member):
    r = client.post(
        "/api/files",
        files={"file": (NAME, CONTENT, "text/plain")},
        data={"expiry_hours": "24", "fp": "fp-m"},
    )
    assert r.status_code == 200
    row = r.json()
    assert row["ok"] and row["token"] and row["share_url"].endswith(f"/s/{row['token']}")

    app_page = client.get("/app")
    assert app_page.status_code == 200
    assert NAME in app_page.text


def test_update_expiry_and_invalid_option(client, member):
    token = client.post("/api/files", files={"file": (NAME, CONTENT, "text/plain")},
                        data={"expiry_hours": "24"}).json()["token"]

    ok = client.post(f"/api/shares/{token}/expiry", data={"expiry_hours": "1"})
    assert ok.status_code == 200 and ok.json()["ok"]

    bad = client.post(f"/api/shares/{token}/expiry", data={"expiry_hours": "999"})
    assert bad.status_code == 400


def test_revoke_disables_link(client, member):
    token = client.post("/api/files", files={"file": (NAME, CONTENT, "text/plain")},
                        data={"expiry_hours": "24"}).json()["token"]
    assert client.post(f"/api/shares/{token}/revoke").status_code == 200
    assert client.get(f"/d/{token}").status_code == 410


def test_delete_removes_file(client, member):
    up = client.post("/api/files", files={"file": (NAME, CONTENT, "text/plain")},
                     data={"expiry_hours": "24"}).json()
    assert client.delete(f"/api/files/{up['id']}").status_code == 200
    assert client.get(f"/d/{up['token']}").status_code == 404


def test_email_share_falls_back_when_smtp_unconfigured(client, member):
    token = client.post("/api/files", files={"file": (NAME, CONTENT, "text/plain")},
                        data={"expiry_hours": "24"}).json()["token"]
    r = client.post(f"/api/shares/{token}/email", data={"to": "friend@example.com"})
    assert r.status_code == 503
    assert r.json()["reason"] == "email_not_configured"


def test_email_share_requires_member(client):
    # Anonymous callers cannot use the server relay (anti-spam); 403, not a send.
    token = _anon_upload(client).json()["token"]
    r = client.post(f"/api/shares/{token}/email", data={"to": "friend@example.com"})
    assert r.status_code == 403
