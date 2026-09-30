"""SQLAlchemy ORM models.

Concerns modelled here:
  * ``File``: an uploaded blob and its metadata.
  * ``ShareLink``: a UUID-addressed, optionally-expiring link to a file.
  * ``UploadEvent``: one row per upload attempt, capturing IP and fingerprint
    for abuse review (the landing page is public).
  * ``DownloadEvent``: one row per request to a share link, completed once the
    response ends with whether the client stayed for all of it.
  * ``DownloadClient``: the browser-fingerprint bundle behind a download,
    stored once per distinct client rather than per row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class DownloadEvent(Base):
    """One row per request to ``/d/{token}``.

    Written before the file starts streaming so a record exists even if the
    process dies mid-transfer, then completed once the response ends. That is
    the whole point of the table: ``share_links.download_count`` can only say a
    link was *asked for* N times, which over-reports badly when a browser
    ranges, retries, or aborts a large file. ``bytes_sent`` and ``completed``
    say what actually arrived.
    """

    __tablename__ = "download_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id"), nullable=True, index=True)
    share_token: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # Who / where from. Mirrors UploadEvent so both audit trails read alike.
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    accept_language: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referer: Mapped[str | None] = mapped_column(Text, nullable=True)
    ua_browser: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ua_os: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ua_device: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # PTR record for ``ip``, filled in after the response by a worker thread.
    # A name identifies a mail scanner or a crawler far better than a guessed
    # city does, and needs no database to obtain.
    reverse_dns: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Only set when the share page ran its script first. A null fingerprint on
    # an otherwise complete download is itself a signal: no browser ran here.
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # ``completed`` comes from the client disconnecting or not, which is the
    # only signal that survives: the server accepts writes silently after the
    # peer is gone, so a byte count cannot tell an abandoned transfer from a
    # finished one. ``bytes_streamed`` is therefore what the application wrote,
    # and equals what arrived only when ``completed`` is true. Bytes genuinely
    # on the wire are counted by the Caddy access log, a layer further out.
    bytes_streamed: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    completed: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    is_range_request: Mapped[bool] = mapped_column(Boolean, default=False)
    range_header: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def throughput_bps(self) -> float | None:
        """Delivered bytes per second, for transfers that actually finished.

        Deliberately ``None`` for an abandoned transfer: the duration is real
        but the byte count is not, so dividing them would invent a number.
        """
        if not self.completed or not self.duration_ms or self.bytes_streamed <= 0:
            return None
        return self.bytes_streamed / (self.duration_ms / 1000.0)


class DownloadClient(Base):
    """The fingerprint bundle behind a download, keyed by share link + hash.

    Kept out of :class:`DownloadEvent` so the bundle is stored once per distinct
    client instead of being copied onto every row. The share page posts it; a
    client that never runs the script simply has no entry.
    """

    __tablename__ = "download_clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    share_token: Mapped[str] = mapped_column(String(36), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("share_token", "fingerprint", name="uq_download_client"),)
