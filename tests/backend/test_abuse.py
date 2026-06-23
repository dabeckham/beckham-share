"""Abuse controls on the public upload form: rate limit, size cap, audit trail."""
from app.db import SessionLocal
from app.models import UploadEvent


def _upload(client, content=b"hi", fp="fp-x"):
    return client.post("/api/anon-upload", files={"file": ("a.txt", content, "text/plain")}, data={"fp": fp})


def test_anonymous_rate_limit(client):
    # conftest sets ANON_UPLOADS_PER_HOUR=3.
    for _ in range(3):
        assert _upload(client).status_code == 200
    blocked = _upload(client)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_anonymous_size_cap(client):
    # conftest sets ANON_MAX_UPLOAD_BYTES=2000.
    big = client.post("/api/anon-upload", files={"file": ("big.bin", b"x" * 3000, "application/octet-stream")},
                      data={"fp": "fp-big"})
    assert big.status_code == 413


def test_upload_is_audited_with_ip_and_fingerprint(client):
    _upload(client, fp="fp-audit")
    with SessionLocal() as s:
        events = s.query(UploadEvent).all()
        assert len(events) == 1
        ev = events[0]
        assert ev.is_anonymous is True
        assert ev.ip is not None
        assert ev.fingerprint is not None
        assert ev.user_agent is not None


def test_member_uploads_not_rate_limited(client, member):
    for _ in range(5):
        r = client.post("/api/files", files={"file": ("a.txt", b"hi", "text/plain")}, data={"expiry_hours": "24"})
        assert r.status_code == 200
