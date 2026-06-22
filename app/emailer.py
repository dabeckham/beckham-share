"""Send a share link by email over SMTP.

Disabled until SMTP credentials are configured (see ``settings.email_enabled``).
The front end falls back to a ``mailto:`` link in that case, so the feature is
usable before the dedicated mailbox exists.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import settings


class EmailNotConfigured(Exception):
    pass


def send_share_email(to_address: str, share_url: str, filename: str, sender_name: str | None = None) -> None:
    if not settings.email_enabled:
        raise EmailNotConfigured("SMTP is not configured")

    who = sender_name or "Someone"
    msg = EmailMessage()
    msg["Subject"] = f"{who} shared a file with you via {settings.app_name}"
    msg["From"] = settings.smtp_from
    msg["To"] = to_address
    msg.set_content(
        f"{who} shared a file with you: {filename}\n\n"
        f"Download it here:\n{share_url}\n\n"
        f"This link may expire. Sent via {settings.app_name} ({settings.brand_domain})."
    )
    msg.add_alternative(
        f"""<html><body style="font-family:Helvetica,Arial,sans-serif;color:#1e1919">
        <p><strong>{who}</strong> shared a file with you: <strong>{filename}</strong></p>
        <p><a href="{share_url}"
              style="background:#0061fe;color:#fff;padding:12px 20px;border-radius:8px;
                     text-decoration:none;display:inline-block">Download file</a></p>
        <p style="color:#637282;font-size:13px">This link may expire.
           Sent via {settings.app_name} ({settings.brand_domain}).</p>
        </body></html>""",
        subtype="html",
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        if settings.smtp_use_tls:
            server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
