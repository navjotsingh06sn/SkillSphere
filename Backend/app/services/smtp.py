"""Deprecated import compatibility for existing integrations.

All delivery goes through Resend over HTTPS. New code should import from
``app.services.email_delivery``.
"""

from app.services.email_delivery import EmailDeliveryError, send_resend_email_sync
from app.services.email_delivery import send_resend_email as _send_resend_email


def send_smtp_email_sync(
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str | None = None,
) -> str:
    return send_resend_email_sync(recipient, subject, text_content, html_content)


async def send_smtp_email(
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str | None = None,
) -> str:
    return await _send_resend_email(recipient, subject, text_content, html_content)
