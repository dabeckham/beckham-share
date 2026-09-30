"""Reverse DNS for download records.

"Who fetched this?" is usually better answered by a name than by a place. A
free city database guesses a location and is often wrong at street level, while
a PTR record says `mail-...outbound.protection.outlook.com` or
`ec2-...compute.amazonaws.com` outright, which is what distinguishes a person
from a mail scanner or a crawler. It also needs no database, no licence, and no
attribution notice on the page.

The lookup happens off the download path. A PTR query can take seconds against
an unresponsive resolver, and nobody's download is going to wait for one, so the
record is written first and the name filled in afterwards by a small pool of
worker threads. Results are cached per address, so a link fetched repeatedly
from one place costs one query.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

log = logging.getLogger("beckham_share.reversedns")

_TTL_SECONDS = 3600.0
_MAX_CACHE = 2048

_lock = threading.Lock()
_cache: dict[str, tuple[float, str | None]] = {}
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reversedns")


def _cached(ip: str) -> tuple[bool, str | None]:
    with _lock:
        entry = _cache.get(ip)
    if entry and time.monotonic() - entry[0] < _TTL_SECONDS:
        return True, entry[1]
    return False, None


def _remember(ip: str, name: str | None) -> None:
    with _lock:
        if len(_cache) >= _MAX_CACHE:
            _cache.clear()  # crude, but this is a convenience cache, not state
        _cache[ip] = (time.monotonic(), name)


def lookup(ip: str | None) -> str | None:
    """Resolve one address to a name. Blocking; cached. None when there is none."""
    if not ip:
        return None
    hit, name = _cached(ip)
    if hit:
        return name
    try:
        name = socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        name = None  # no PTR, or the resolver would not say
    _remember(ip, name)
    return name


def resolve_in_background(ip: str | None, on_resolved: Callable[[str], None]) -> None:
    """Look ``ip`` up on a worker thread and hand the name to ``on_resolved``.

    Fire and forget by design: this runs after the response has already gone, so
    a failure here costs an enrichment field and nothing else.
    """
    if not ip:
        return
    hit, name = _cached(ip)
    if hit:
        if name:
            on_resolved(name)
        return

    def work() -> None:
        try:
            name = lookup(ip)
            if name:
                on_resolved(name)
        except Exception as exc:  # noqa: BLE001
            log.warning("reverse lookup for %s failed: %s", ip, exc)

    try:
        _executor.submit(work)
    except RuntimeError:
        pass  # interpreter shutting down; nothing worth doing about it


def drain(timeout: float | None = None) -> None:
    """Wait for outstanding lookups. For tests and orderly shutdown."""
    global _executor
    _executor.shutdown(wait=True, cancel_futures=False)
    _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reversedns")


def clear_cache() -> None:
    with _lock:
        _cache.clear()
