"""Recording what a download actually delivered.

``share_links.download_count`` counts requests to ``/d/{token}`` and always
has. That is the right input for the ``max_downloads`` quota, but it is a poor
answer to "how many people got this file": a browser that ranges, retries, or
aborts and starts over is several requests and one download. Measured on a
105 MB recording, the counter read 6 against two distinct clients and roughly
three complete transfers.

So the counter keeps its meaning and every request additionally writes a
:class:`~app.models.DownloadEvent`. The row is inserted before the file starts
streaming, so a record survives a crash mid-transfer, and is completed when the
response ends with the bytes that actually went out.
"""
from __future__ import annotations

import logging
import time

import anyio
from fastapi import Request
from fastapi.responses import FileResponse

from . import fingerprint, reversedns
from .db import SessionLocal
from .models import DownloadClient, DownloadEvent, utcnow

log = logging.getLogger("beckham_share.downloads")


def record_request(request: Request, *, file_id: str, token: str, client_fp: str | None) -> str | None:
    """Insert the event row for this request and return its id.

    Returns ``None`` if the write failed. Recording is an audit concern, never
    a reason to fail someone's download, so every path here swallows its errors
    and logs them.
    """
    range_header = request.headers.get("range")
    ua_raw = request.headers.get("user-agent")
    ua = fingerprint.parse_ua(ua_raw)
    event = DownloadEvent(
        file_id=file_id,
        share_token=token,
        ip=fingerprint.client_ip(request),
        user_agent=ua_raw,
        accept_language=request.headers.get("accept-language"),
        referer=request.headers.get("referer"),
        ua_browser=ua["browser"],
        ua_os=ua["os"],
        ua_device=ua["device"],
        fingerprint=client_fp or None,
        is_range_request=bool(range_header),
        range_header=range_header[:255] if range_header else None,
    )
    try:
        with SessionLocal() as db:
            db.add(event)
            db.commit()
            return event.id
    except Exception as exc:  # noqa: BLE001 - auditing must not break downloads
        log.warning("could not record download request for %s: %s", token, exc)
        return None


def _finalize(event_id: str, *, bytes_streamed: int, expected_bytes: int | None,
              duration_ms: int, completed: bool) -> None:
    """Complete the row once the response has ended, however it ended."""
    address: str | None = None
    try:
        with SessionLocal() as db:
            event = db.get(DownloadEvent, event_id)
            if event is None:
                return
            event.bytes_streamed = bytes_streamed
            event.expected_bytes = expected_bytes
            event.duration_ms = duration_ms
            event.completed = completed
            address = event.ip
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not finalize download event %s: %s", event_id, exc)
        return
    # Off the request path: the response has already gone, so a slow resolver
    # costs an enrichment field rather than somebody's download.
    reversedns.resolve_in_background(
        address, lambda name: _record_reverse_dns(event_id, name)
    )


def _record_reverse_dns(event_id: str, name: str) -> None:
    try:
        with SessionLocal() as db:
            event = db.get(DownloadEvent, event_id)
            if event is not None:
                event.reverse_dns = name[:255]
                db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not store reverse dns for %s: %s", event_id, exc)


class RecordedFileResponse(FileResponse):
    """A :class:`FileResponse` that reports whether the client actually got it.

    Completion is taken from ``http.disconnect`` on the ASGI receive channel,
    not from the byte count, because the byte count cannot answer it. Uvicorn
    returns from ``send()`` **without writing** once the peer is gone
    (``h11_impl``: ``if self.disconnected: return``), so every remaining chunk
    of an abandoned transfer is accepted silently and the application appears
    to have sent the whole file. Measured: a 60 MB download cut off after about
    6 MB still totalled 62,914,560 bytes at this layer.

    ``FileResponse`` never reads ``receive`` itself (unlike ``StreamingResponse``,
    which has its own ``listen_for_disconnect``), so nothing else is consuming
    that channel and a watcher here is free to.

    The bytes counted are therefore what the *application* wrote, which equals
    what the client received only when ``completed`` is true. For bytes
    genuinely on the wire, see the Caddy access log, which is the only layer
    that can count them.
    """

    def __init__(self, *args, event_id: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._event_id = event_id

    async def __call__(self, scope, receive, send) -> None:
        if not self._event_id or scope.get("type") != "http":
            await super().__call__(scope, receive, send)
            return

        streamed = 0
        expected: int | None = None
        started = time.perf_counter()
        finished = False
        disconnected = False

        async def recording_send(message) -> None:
            nonlocal streamed, expected, finished
            if message["type"] == "http.response.start":
                for key, value in message.get("headers") or []:
                    if key.lower() == b"content-length":
                        try:
                            expected = int(value)
                        except (TypeError, ValueError):
                            expected = None
            elif message["type"] == "http.response.body":
                streamed += len(message.get("body") or b"")
                # Mark completion here rather than after the response call
                # returns: ``send`` awaits, which lets the watcher run, and
                # uvicorn yields http.disconnect the moment the response is
                # complete. Setting the flag before that await is what keeps a
                # finished download from being recorded as an abandoned one.
                if not message.get("more_body", False):
                    finished = True
            await send(message)

        async def watch_for_disconnect() -> None:
            # Uvicorn also yields http.disconnect once the response is
            # complete, so `finished` is what distinguishes "the client left"
            # from "we got to the end". It is set as the final body message is
            # handed over, before the await that could let this task run.
            nonlocal disconnected
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    if not finished:
                        disconnected = True
                    return

        async def run_response() -> None:
            try:
                await super(RecordedFileResponse, self).__call__(scope, receive, recording_send)
            finally:
                task_group.cancel_scope.cancel()

        try:
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(watch_for_disconnect)
                task_group.start_soon(run_response)
        finally:
            # Deliberately synchronous: this runs while a cancellation may be
            # unwinding, and awaiting here could be interrupted before the row
            # is written. The statement is a single indexed UPDATE.
            _finalize(
                self._event_id,
                bytes_streamed=streamed,
                expected_bytes=expected,
                duration_ms=int((time.perf_counter() - started) * 1000),
                completed=not disconnected,
            )


def remember_client(request: Request, *, token: str, fp_hash: str, fp_data: str | None) -> None:
    """Upsert the fingerprint bundle the share page reported for this link."""
    try:
        with SessionLocal() as db:
            existing = (
                db.query(DownloadClient)
                .filter(DownloadClient.share_token == token, DownloadClient.fingerprint == fp_hash)
                .one_or_none()
            )
            if existing is None:
                db.add(DownloadClient(
                    share_token=token,
                    fingerprint=fp_hash,
                    fingerprint_data=fp_data,
                    ip=fingerprint.client_ip(request),
                    user_agent=request.headers.get("user-agent"),
                ))
            else:
                existing.last_seen = utcnow()
                if fp_data:
                    existing.fingerprint_data = fp_data
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not record download client for %s: %s", token, exc)
