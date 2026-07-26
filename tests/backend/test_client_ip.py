"""Whose word we take for the client's address.

The anonymous rate limit and the upload audit trail are both keyed on the
client IP, so an address the client gets to choose is an address that resets
the budget. These cover which peers may speak for a client, and how a
forwarded chain is read once one of them does.
"""
import pytest
from starlette.requests import Request

from app import fingerprint
from app.config import settings

TRUSTED = "10.9.0.1"


def _request(peer, **headers) -> Request:
    raw = [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 51234) if peer else None})


@pytest.fixture
def behind_proxy(monkeypatch):
    """Trust one address, the way the deployment trusts the shared front."""
    monkeypatch.setattr(settings, "trusted_proxies", TRUSTED)


def test_forwarded_header_from_an_untrusted_peer_is_ignored(behind_proxy):
    # A neighbour on the container network can reach the app directly. It does
    # not get to name the client.
    req = _request("172.23.0.9", x_forwarded_for="203.0.113.5", x_real_ip="203.0.113.5")
    assert fingerprint.client_ip(req) == "172.23.0.9"


def test_forwarded_header_from_the_trusted_proxy_is_believed(behind_proxy):
    req = _request(TRUSTED, x_forwarded_for="203.0.113.5")
    assert fingerprint.client_ip(req) == "203.0.113.5"


def test_client_supplied_hops_are_discarded(behind_proxy):
    # The client sent its own X-Forwarded-For and the proxy appended the address
    # it saw. Reading left to right would return the client's invention.
    req = _request(TRUSTED, x_forwarded_for="198.51.100.1, 203.0.113.5")
    assert fingerprint.client_ip(req) == "203.0.113.5"


def test_trusted_hops_are_skipped(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "10.9.0.0/24")
    req = _request("10.9.0.1", x_forwarded_for="203.0.113.5, 10.9.0.7")
    assert fingerprint.client_ip(req) == "203.0.113.5"


def test_real_ip_is_used_when_there_is_no_forwarded_chain(behind_proxy):
    req = _request(TRUSTED, x_real_ip="203.0.113.5")
    assert fingerprint.client_ip(req) == "203.0.113.5"


def test_trusting_nothing_falls_back_to_the_socket_peer(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "")
    req = _request(TRUSTED, x_forwarded_for="203.0.113.5")
    assert fingerprint.client_ip(req) == TRUSTED


def test_unresolvable_entries_do_not_grant_trust(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "no-such-host.invalid")
    req = _request("172.23.0.9", x_forwarded_for="203.0.113.5")
    assert fingerprint.client_ip(req) == "172.23.0.9"


def test_rate_limit_survives_forwarded_header_rotation(client):
    # conftest sets ANON_UPLOADS_PER_HOUR=3. The test client is not a trusted
    # proxy, so rotating the header (and the browser fingerprint with it) must
    # not buy a fresh budget.
    for i in range(3):
        r = client.post("/api/anon-upload",
                        files={"file": ("a.txt", b"hi", "text/plain")},
                        data={"fp": f"fp-{i}"},
                        headers={"x-forwarded-for": f"203.0.113.{i}"})
        assert r.status_code == 200
    blocked = client.post("/api/anon-upload",
                          files={"file": ("a.txt", b"hi", "text/plain")},
                          data={"fp": "fp-fresh"},
                          headers={"x-forwarded-for": "203.0.113.200"})
    assert blocked.status_code == 429
