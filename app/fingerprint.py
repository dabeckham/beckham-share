"""Request fingerprinting for abuse review.

Combines the network address, request headers, and an optional client-computed
fingerprint (canvas/WebGL/screen/timezone hash from the browser) into a stable
identifier we can group and rate-limit on. None of this is treated as a
security boundary — it is a deterrent and an audit aid for a public upload form.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import Request
from ua_parser import user_agent_parser

from .config import settings


def client_ip(request: Request) -> str | None:
    if settings.trust_forwarded_for:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()
    return request.client.host if request.client else None


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
