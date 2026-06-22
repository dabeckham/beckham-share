"""SQLAlchemy ORM models.

Three concerns are modelled:
  * ``File``        — an uploaded blob and its metadata.
  * ``ShareLink``   — a UUID-addressed, optionally-expiring link to a file.
  * ``UploadEvent`` — one row per upload attempt, capturing IP + fingerprint
                      for abuse review (the landing page is public).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class File(Base):
    __tablename__ = "files"

    # The id doubles as the on-disk storage key — it is never exposed in URLs.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    original_filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Owner identity. NULL owner == anonymous (landing-page) upload.
    owner_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    owner_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Hard expiry for the blob itself (anonymous uploads always get one).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    shares: Mapped[list["ShareLink"]] = relationship(back_populates="file", cascade="all, delete-orphan")
    events: Mapped[list["UploadEvent"]] = relationship(back_populates="file")


class ShareLink(Base):
    __tablename__ = "share_links"

    # The public token — the only identifier that ever appears in a URL.
    token: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)

    created_by_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    download_count: Mapped[int] = mapped_column(Integer, default=0)
    max_downloads: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    file: Mapped["File"] = relationship(back_populates="shares")

    @property
    def is_expired(self) -> bool:
        if self.revoked:
            return True
        if self.expires_at is not None and utcnow() >= self.expires_at:
            return True
        if self.max_downloads is not None and self.download_count >= self.max_downloads:
            return True
        return False


class UploadEvent(Base):
    """One row per upload — the abuse-review audit trail."""

    __tablename__ = "upload_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id"), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Who / where from.
    actor_sub: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    accept_language: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Client fingerprint: a stable hash plus the raw signal bundle for review.
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fingerprint_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lightweight UA breakdown for human-readable review.
    ua_browser: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ua_os: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ua_device: Mapped[str | None] = mapped_column(String(128), nullable=True)

    file: Mapped["File"] = relationship(back_populates="events")
