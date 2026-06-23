"""Pytest fixtures: a TestClient bound to a throwaway database, plus auth helpers.

Tests run against a real PostgreSQL database (matching production semantics,
including timezone-aware timestamps) supplied via DATABASE_URL — see
scripts/run-tests.sh for the host runner and .github/workflows/ci.yml for CI.
"""
import os
import tempfile

# Configure the app via the environment BEFORE importing it (settings are read at
# import time). Keep the abuse limits low so they are cheap to exercise.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://share:share@localhost:5432/testdb")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="bshare-test-")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["BASE_URL"] = "https://share.beckham.ai"
os.environ["ANON_MAX_UPLOAD_BYTES"] = "2000"
os.environ["ANON_UPLOADS_PER_HOUR"] = "3"
os.environ["ANON_UPLOADS_PER_DAY"] = "5"
os.environ["SMTP_HOST"] = ""  # email disabled -> exercises the mailto fallback path

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as appdb  # noqa: E402
from app import main  # noqa: E402
from app.auth import CurrentUser  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    appdb.Base.metadata.create_all(bind=appdb.engine)
    yield
    appdb.Base.metadata.drop_all(bind=appdb.engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    """Isolate tests: wipe all rows after each one."""
    yield
    with appdb.engine.begin() as conn:
        for table in reversed(appdb.Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def client():
    # Use the canonical host as the base URL so the host-canonicalization
    # redirect doesn't fire on every request.
    with TestClient(main.app, base_url="https://share.beckham.ai") as c:
        yield c


def _as_user(monkeypatch, groups):
    user = CurrentUser({"sub": "u-test", "email": "test@beckham.ai", "name": "Test User", "groups": groups})
    monkeypatch.setattr(main, "get_current_user", lambda request: user)
    return user


@pytest.fixture
def member(monkeypatch):
    """Authenticated user in the required `dropbox` group."""
    return _as_user(monkeypatch, ["dropbox"])


@pytest.fixture
def nonmember(monkeypatch):
    """Authenticated user NOT in the required group."""
    return _as_user(monkeypatch, ["other"])


@pytest.fixture
def db_session():
    s = appdb.SessionLocal()
    try:
        yield s
    finally:
        s.close()
