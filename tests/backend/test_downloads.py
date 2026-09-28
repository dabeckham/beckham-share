"""What a download actually delivered.

`share_links.download_count` counts requests, which over-reports whenever a
browser ranges, retries, or aborts. These cover the per-request record that
says what really went out.
"""
import json

from app.db import SessionLocal
from app.models import DownloadClient, DownloadEvent, ShareLink

CONTENT = b"beckham-share download payload"


def _shared_file(client):
    r = client.post("/api/anon-upload",
                    files={"file": ("report.txt", CONTENT, "text/plain")},
                    data={"fp": "fp-uploader"})
    assert r.status_code == 200
    return r.json()["token"]


def _events(token):
    with SessionLocal() as s:
        return s.query(DownloadEvent).filter(DownloadEvent.share_token == token).all()


def test_download_writes_an_event(client):
    token = _shared_file(client)
    assert client.get(f"/d/{token}").content == CONTENT

    events = _events(token)
    assert len(events) == 1
    ev = events[0]
    assert ev.ip is not None
    assert ev.user_agent is not None
    assert ev.is_range_request is False


def test_completed_download_records_the_bytes_that_went_out(client):
    token = _shared_file(client)
    client.get(f"/d/{token}")

    ev = _events(token)[0]
    assert ev.bytes_streamed == len(CONTENT)
    assert ev.expected_bytes == len(CONTENT)
    assert ev.completed is True
    assert ev.duration_ms is not None


def test_range_request_is_recorded_against_the_range_not_the_file(client):
    token = _shared_file(client)
    r = client.get(f"/d/{token}", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206

    ev = _events(token)[0]
    assert ev.is_range_request is True
    assert ev.range_header == "bytes=0-9"
    # Ten bytes of a thirty-byte file is a complete *range*, and saying
    # otherwise would report every partial fetch as a failure.
    assert ev.bytes_streamed == 10
    assert ev.expected_bytes == 10
    assert ev.completed is True


def test_the_counter_still_counts_requests(client):
    # download_count feeds the max_downloads quota, so its meaning is
    # deliberately unchanged: an aborted transfer still spent the bandwidth.
    token = _shared_file(client)
    for _ in range(3):
        client.get(f"/d/{token}")
    with SessionLocal() as s:
        assert s.get(ShareLink, token).download_count == 3
    assert len(_events(token)) == 3


def test_fingerprint_from_the_share_page_lands_on_the_download(client):
    token = _shared_file(client)
    client.get(f"/d/{token}?fp=abc12345")
    assert _events(token)[0].fingerprint == "abc12345"


def test_download_without_a_fingerprint_is_recorded_as_such(client):
    # A link fetched by a scanner or curl runs no script. The null is a signal,
    # not a gap.
    token = _shared_file(client)
    client.get(f"/d/{token}")
    assert _events(token)[0].fingerprint is None


def test_share_page_can_report_its_client(client):
    token = _shared_file(client)
    body = json.dumps({"hash": "deadbeef", "components": {"tz": "America/Chicago", "canvas": "x"}})
    assert client.post(f"/api/shares/{token}/client", content=body).status_code == 200

    with SessionLocal() as s:
        rows = s.query(DownloadClient).filter(DownloadClient.share_token == token).all()
    assert len(rows) == 1
    assert rows[0].fingerprint == "deadbeef"
    assert "America/Chicago" in rows[0].fingerprint_data


def test_repeat_reports_from_one_client_do_not_duplicate(client):
    token = _shared_file(client)
    body = json.dumps({"hash": "deadbeef", "components": {"tz": "UTC"}})
    for _ in range(3):
        client.post(f"/api/shares/{token}/client", content=body)
    with SessionLocal() as s:
        assert s.query(DownloadClient).filter(DownloadClient.share_token == token).count() == 1


def test_client_report_rejected_for_an_unknown_link(client):
    body = json.dumps({"hash": "deadbeef", "components": {}})
    assert client.post("/api/shares/not-a-token/client", content=body).status_code == 404


def test_recording_does_not_change_what_the_client_receives(client):
    token = _shared_file(client)
    r = client.get(f"/d/{token}")
    assert r.status_code == 200
    assert r.content == CONTENT
    assert 'filename="report.txt"' in r.headers["content-disposition"]


def test_a_client_that_leaves_mid_stream_is_recorded_as_incomplete(tmp_path):
    """The case the counter cannot see, driven at the ASGI layer.

    A live client aborting cannot be reproduced through TestClient, and the
    byte count is no help: uvicorn accepts writes silently once the peer is
    gone, so an abandoned transfer still totals the whole file. Completion
    therefore comes from ``http.disconnect``, and this drives that channel
    directly so the behaviour is pinned in CI rather than only in a manual test.
    """
    import anyio

    from app.downloads import RecordedFileResponse

    blob = tmp_path / "payload.bin"
    blob.write_bytes(b"x" * (512 * 1024))  # several 64 KiB chunks

    with SessionLocal() as s:
        event = DownloadEvent(share_token="tok-abandoned")
        s.add(event)
        s.commit()
        event_id = event.id

    async def drive():
        gone = anyio.Event()
        bodies = 0

        async def receive():
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal bodies
            if message["type"] == "http.response.body":
                bodies += 1
                if bodies == 2:  # walk away part way through
                    gone.set()
                    await anyio.sleep(0.05)  # let the watcher observe it

        response = RecordedFileResponse(blob, event_id=event_id)
        await response({"type": "http", "method": "GET", "headers": []}, receive, send)

    anyio.run(drive)

    with SessionLocal() as s:
        recorded = s.get(DownloadEvent, event_id)
        assert recorded.completed is False
        # The duration is real but the byte count is not, so refuse to divide.
        assert recorded.throughput_bps is None


def test_a_finished_transfer_reports_throughput(client):
    token = _shared_file(client)
    client.get(f"/d/{token}")
    ev = _events(token)[0]
    assert ev.completed is True
    assert ev.throughput_bps is None or ev.throughput_bps > 0


def test_workspace_reports_completed_downloads_not_the_request_count(client, member):
    # The bug that started this: a column headed "Downloads" showing the
    # request tally, so six requests from two people read as six downloads.
    r = client.post("/api/files",
                    files={"file": ("minutes.txt", CONTENT, "text/plain")},
                    data={"expiry_hours": "24"})
    token = r.json()["token"]
    for _ in range(3):
        client.get(f"/d/{token}")

    page = client.get("/app")
    assert page.status_code == 200
    assert "3 requests from 1 client" in page.text
