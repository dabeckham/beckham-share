"""Browser E2E for the authenticated workspace, focused on the share modal.

Directly encodes the regression that shipped: the modal must be HIDDEN on load,
open when "Share" is clicked, and close via the X. Requires a forged session
cookie (E2E_SECRET = the app's SECRET_KEY), so it runs against a local instance
with a known secret (see scripts/run-e2e.sh / CI), not the live site.
"""
import base64
import json
import os
from urllib.parse import urlsplit

import pytest

BASE = os.environ.get("E2E_BASE", "http://localhost:8000")
SECRET = os.environ.get("E2E_SECRET")

pytestmark = pytest.mark.skipif(not SECRET, reason="E2E_SECRET not set (needs a forged session)")


def _session_cookie(secret: str, data: dict) -> str:
    from itsdangerous import TimestampSigner

    raw = base64.b64encode(json.dumps(data).encode())
    return TimestampSigner(secret).sign(raw).decode()


@pytest.fixture
def member_page(page, context):
    value = _session_cookie(
        SECRET,
        {"user": {"sub": "e2e", "email": "e2e@beckham.ai", "name": "E2E", "groups": ["dropbox"]}},
    )
    context.add_cookies([{"name": "session", "value": value, "domain": urlsplit(BASE).hostname, "path": "/"}])
    return page


def test_share_modal_hidden_until_opened(member_page):
    from playwright.sync_api import expect

    page = member_page
    # Seed a file (same session) so there is a row to share.
    page.request.post(
        BASE + "/api/files",
        multipart={"file": {"name": "m.txt", "mimeType": "text/plain", "buffer": b"hi"}, "expiry_hours": "24"},
    )
    page.goto(BASE + "/app")

    modal = page.locator("#shareModal")
    expect(modal).to_be_hidden()                 # regression: was visible on load
    page.locator(".act-share").first.click()
    expect(modal).to_be_visible()
    page.locator("#modalClose").click()
    expect(modal).to_be_hidden()                 # regression: X could not close it
