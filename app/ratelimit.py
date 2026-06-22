"""Rolling-window rate limiting for anonymous uploads.

Limits are enforced against the upload-event audit trail (one row per upload),
keyed by IP *or* client fingerprint so that rotating one signal alone does not
reset the budget. Backed by the database, so it holds across workers/restarts.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import UploadEvent, utcnow


class RateLimited(Exception):
    def __init__(self, retry_after_seconds: int, message: str):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.message = message


def _count_since(db: Session, ip: str | None, fingerprint: str | None, since) -> int:
    keys = []
    if ip:
        keys.append(UploadEvent.ip == ip)
    if fingerprint:
        keys.append(UploadEvent.fingerprint == fingerprint)
    if not keys:
        return 0
    stmt = (
        select(UploadEvent.id)
        .where(UploadEvent.is_anonymous.is_(True))
        .where(UploadEvent.created_at >= since)
        .where(or_(*keys))
    )
    return len(db.execute(stmt).all())


def check_anonymous(db: Session, ip: str | None, fingerprint: str | None) -> None:
    """Raise :class:`RateLimited` if this client is over its anon-upload budget."""
    now = utcnow()
    hour_count = _count_since(db, ip, fingerprint, now - timedelta(hours=1))
    if hour_count >= settings.anon_uploads_per_hour:
        raise RateLimited(3600, "Too many uploads from this connection in the last hour. Please try again later.")
    day_count = _count_since(db, ip, fingerprint, now - timedelta(days=1))
    if day_count >= settings.anon_uploads_per_day:
        raise RateLimited(86400, "Daily upload limit reached for this connection. Please try again tomorrow.")
