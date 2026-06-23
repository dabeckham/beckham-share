"""Browser E2E for the public landing page (no auth required).

Exercises the same `[hidden]` CSS rule and button wiring that the workspace
share modal depends on — i.e. the class of bug that shipped as a stuck modal.
Target host via E2E_BASE (default: the live deployment).
"""
import os

from playwright.sync_api import expect

BASE = os.environ.get("E2E_BASE", "https://share.beckham.ai")


def test_hidden_elements_are_not_visible_on_load(page):
    page.goto(BASE + "/")
    expect(page.get_by_text("Send a file")).to_be_visible()
    expect(page.locator("#dropzone")).to_be_visible()
    # Toggled-by-`hidden` components must start hidden (the modal-bug class).
    expect(page.locator("#result")).to_be_hidden()
    expect(page.locator("#dropzone .dz-progress")).to_be_hidden()


def test_anonymous_upload_yields_share_link_and_buttons(page):
    page.goto(BASE + "/")
    page.set_input_files(
        "#fileInput",
        files=[{"name": "e2e-upload.txt", "mimeType": "text/plain", "buffer": b"end-to-end content"}],
    )
    # Result card appears with a UUID link (and no filename in it).
    expect(page.locator("#result")).to_be_visible(timeout=20000)
    link = page.locator("#shareLink").input_value()
    assert "/s/" in link and "e2e-upload.txt" not in link
    # The action buttons are present and clickable.
    expect(page.locator('[data-copy="#shareLink"]')).to_be_visible()
    expect(page.locator("#emailBtn")).to_be_visible()


def test_login_link_points_at_auth(page):
    page.goto(BASE + "/")
    assert page.locator('a.btn:has-text("Log in")').get_attribute("href") == "/login"
