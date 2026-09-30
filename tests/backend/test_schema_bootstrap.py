"""Bootstrap keeps existing tables in step with the models.

`create_all` creates missing tables and never alters ones that already exist,
so a column added to a live table is simply absent while every INSERT still
names it. This reproduces that exactly, because it happened in production: the
recording path swallows its own errors, so downloads kept working and nothing
was recorded.
"""
from sqlalchemy import inspect, text

from app.db import engine, init_db


def _columns(table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_a_column_missing_from_a_live_table_is_added_back():
    assert "reverse_dns" in _columns("download_events")
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE download_events DROP COLUMN reverse_dns'))
    assert "reverse_dns" not in _columns("download_events")

    init_db()

    assert "reverse_dns" in _columns("download_events")


def test_recording_works_again_after_the_column_is_restored(client):
    # The failure this guards against was invisible: the download succeeded and
    # the audit row did not appear.
    from app.db import SessionLocal
    from app.models import DownloadEvent

    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE download_events DROP COLUMN reverse_dns'))
    init_db()

    r = client.post("/api/anon-upload",
                    files={"file": ("a.txt", b"after the repair", "text/plain")},
                    data={"fp": "fp-bootstrap"})
    token = r.json()["token"]
    assert client.get(f"/d/{token}").status_code == 200

    with SessionLocal() as s:
        assert s.query(DownloadEvent).filter(DownloadEvent.share_token == token).count() == 1


def test_a_not_null_column_is_added_with_the_models_default():
    # bytes_streamed is NOT NULL with a Python-side default of 0. Existing rows
    # need a value, so the default has to come along or the ALTER fails.
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO download_events (id, created_at, bytes_streamed, is_range_request) "
            "VALUES ('keep-me', now(), 7, false)"))
        conn.execute(text('ALTER TABLE download_events DROP COLUMN bytes_streamed'))
    assert "bytes_streamed" not in _columns("download_events")

    init_db()

    assert "bytes_streamed" in _columns("download_events")
    with engine.begin() as conn:
        value = conn.execute(text("SELECT bytes_streamed FROM download_events WHERE id='keep-me'")).scalar()
    assert value == 0  # the pre-existing row got the model's default, not a null


def test_bootstrap_is_repeatable():
    before = _columns("download_events")
    init_db()
    init_db()
    assert _columns("download_events") == before
