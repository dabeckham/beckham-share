"""Request fingerprinting for abuse review.

Combines the network address, request headers, and an optional client-computed
fingerprint (canvas/WebGL/screen/timezone hash from the browser) into a stable
identifier we can group and rate-limit on. None of this is treated as a
security boundary — it is a deterrent and an audit aid for a public upload form.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import socket
import time

from fastapi import Request
from ua_parser import user_agent_parser

from .config import settings

log = logging.getLogger("beckham_share.fingerprint")

# Hostnames in TRUSTED_PROXIES resolve to container addresses that Docker can
# reassign, so the parsed list is rebuilt periodically. It is also rebuilt
# whenever the setting itself changes, which keeps it honest under test.
_TRUST_TTL_SECONDS = 60.0
_trust_cache: tuple[str, float, list] = ("", -_TRUST_TTL_SECONDS, [])


def _trusted_networks() -> list:
    global _trust_cache
    configured = settings.trusted_proxies
    key, stamp, nets = _trust_cache
    if key == configured and time.monotonic() - stamp < _TRUST_TTL_SECONDS:
        return nets

    nets = []
    for entry in (e.strip() for e in configured.split(",")):
        if not entry:
            continue
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
            continue
        except ValueError:
            pass  # not an address or range — try resolving it as a hostname
        try:
            for info in socket.getaddrinfo(entry, None):
                nets.append(ipaddress.ip_network(info[4][0]))
        except OSError:
            log.warning("TRUSTED_PROXIES: cannot resolve %r; ignoring it", entry)
    _trust_cache = (configured, time.monotonic(), nets)
    return nets


def _is_trusted(address: str | None) -> bool:
    if not address:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in net for net in _trusted_networks())


def client_ip(request: Request) -> str | None:
    """The client's address, believed only as far as the infrastructure vouches.

    Proxy headers are honoured only when the request actually arrived from a
    trusted proxy — otherwise anyone who can open a socket to the app could
    claim any address, which would reset the anonymous rate-limit budget and
    poison the audit trail. ``X-Forwarded-For`` is read right to left: trusted
    hops are skipped and the first untrusted address is the closest one that a
    trusted proxy actually observed. Anything further left was appended by the
    client and means nothing.
    """
    peer = request.client.host if request.client else None
    if not _is_trusted(peer):
        return peer
    for hop in reversed(request.headers.get("x-forwarded-for", "").split(",")):
        hop = hop.strip()
        if hop and not _is_trusted(hop):
            return hop
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return peer


def parse_ua(user_agent: str | None) -> dict[str, str | None]:
    if not user_agent:
        return {"browser": None, "os": None, "device": None}
    parsed = user_agent_parser.Parse(user_agent)
    ua, os_, dev = parsed["user_agent"], parsed["os"], parsed["device"]
    browser = " ".join(p for p in [ua.get("family"), ua.get("major")] if p)
    os_str = " ".join(p for p in [os_.get("family"), os_.get("major")] if p)
    return {"browser": browser or None, "os": os_str or None, "device": dev.get("family")}


def compute_fingerprint(request: Request, client_fp: str | None, ip: str | None) -> str:
    """Return a 64-char hex fingerprint.

    Prefers the client-supplied fingerprint (richer signal); otherwise falls
    back to a header/network-derived hash so JS-less clients are still grouped.
    """
    if client_fp:
        return hashlib.sha256(client_fp.encode("utf-8", "ignore")).hexdigest()
    basis = "|".join([
        ip or "",
        request.headers.get("user-agent", ""),
        request.headers.get("accept-language", ""),
        request.headers.get("accept-encoding", ""),
    ])
    return hashlib.sha256(basis.encode("utf-8", "ignore")).hexdigest()


def collect(request: Request, client_fp: str | None, fp_components: dict | None) -> dict:
    """Bundle everything we record on an upload event."""
    ip = client_ip(request)
    ua_raw = request.headers.get("user-agent")
    ua = parse_ua(ua_raw)
    return {
        "ip": ip,
        "user_agent": ua_raw,
        "accept_language": request.headers.get("accept-language"),
        "fingerprint": compute_fingerprint(request, client_fp, ip),
        "fingerprint_data": json.dumps(fp_components, separators=(",", ":")) if fp_components else None,
        "ua_browser": ua["browser"],
        "ua_os": ua["os"],
        "ua_device": ua["device"],
    }
