"""Naming the client behind a download.

A PTR record distinguishes a person from a mail scanner or a crawler, which a
guessed city does not. These use a stubbed resolver: the behaviour under test is
the caching, the off-request timing, and what happens when there is no answer,
none of which should depend on CI having working reverse DNS.
"""
import socket

import pytest

from app import reversedns
from app.db import SessionLocal
from app.models import DownloadEvent

CONTENT = b"payload for reverse dns tests"


@pytest.fixture(autouse=True)
def _fresh_cache():
    reversedns.clear_cache()
    yield
    reversedns.drain()
    reversedns.clear_cache()


def test_lookup_returns_the_name(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyaddr", lambda ip: ("host.example.net", [], [ip]))
    assert reversedns.lookup("203.0.113.5") == "host.example.net"


def test_lookup_is_cached_per_address(monkeypatch):
    calls = []

    def fake(ip):
        calls.append(ip)
        return ("host.example.net", [], [ip])

    monkeypatch.setattr(socket, "gethostbyaddr", fake)
    for _ in range(4):
        reversedns.lookup("203.0.113.5")
    assert calls == ["203.0.113.5"]


def test_an_address_with_no_ptr_record_resolves_to_nothing(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyaddr", lambda ip: (_ for _ in ()).throw(socket.herror()))
    assert reversedns.lookup("203.0.113.5") is None


def test_a_failing_resolver_is_not_retried_immediately(monkeypatch):
    calls = []

    def fake(ip):
        calls.append(ip)
        raise OSError("resolver down")

    monkeypatch.setattr(socket, "gethostbyaddr", fake)
    reversedns.lookup("203.0.113.5")
    reversedns.lookup("203.0.113.5")
    assert len(calls) == 1  # the miss is cached too, so a dead resolver is asked once


def test_lookup_of_nothing_is_nothing():
    assert reversedns.lookup(None) is None
    assert reversedns.lookup("") is None


def test_a_download_gets_its_client_named(client, monkeypatch):
    monkeypatch.setattr(socket, "gethostbyaddr",
                        lambda ip: ("mail-scanner.example.net", [], [ip]))
    r = client.post("/api/anon-upload",
                    files={"file": ("a.txt", CONTENT, "text/plain")},
                    data={"fp": "fp-rdns"})
    token = r.json()["token"]
    client.get(f"/d/{token}")

    reversedns.drain()  # the lookup is deliberately off the request path
    with SessionLocal() as s:
        event = s.query(DownloadEvent).filter(DownloadEvent.share_token == token).one()
        assert event.reverse_dns == "mail-scanner.example.net"


def test_a_download_from_an_unnamed_address_records_no_name(client, monkeypatch):
    monkeypatch.setattr(socket, "gethostbyaddr", lambda ip: (_ for _ in ()).throw(socket.herror()))
    r = client.post("/api/anon-upload",
                    files={"file": ("a.txt", CONTENT, "text/plain")},
                    data={"fp": "fp-rdns-none"})
    token = r.json()["token"]
    client.get(f"/d/{token}")

    reversedns.drain()
    with SessionLocal() as s:
        event = s.query(DownloadEvent).filter(DownloadEvent.share_token == token).one()
        assert event.reverse_dns is None


def test_the_resolver_never_delays_the_download(client, monkeypatch):
    # The whole reason the lookup is off the request path. A resolver that hangs
    # must not hold the response open.
    import time as _time

    def slow(ip):
        _time.sleep(1.5)
        return ("slow.example.net", [], [ip])

    monkeypatch.setattr(socket, "gethostbyaddr", slow)
    r = client.post("/api/anon-upload",
                    files={"file": ("a.txt", CONTENT, "text/plain")},
                    data={"fp": "fp-slow"})
    token = r.json()["token"]

    started = _time.perf_counter()
    assert client.get(f"/d/{token}").content == CONTENT
    assert _time.perf_counter() - started < 1.0

    reversedns.drain()
    with SessionLocal() as s:
        event = s.query(DownloadEvent).filter(DownloadEvent.share_token == token).one()
        assert event.reverse_dns == "slow.example.net"
