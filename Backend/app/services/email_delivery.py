"""Resend-backed email delivery for SkillSphere."""

import asyncio
import logging
from typing import Any

import resend

from app.config import settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Safe, user-displayable email delivery failure."""


def send_resend_email_sync(
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str | None = None,
) -> str:
    api_key = settings.resend_api_key.strip()
    sender = settings.resend_from_email.strip()
    if not api_key:
        raise EmailDeliveryError("RESEND_API_KEY is not configured.")
    if not sender:
        raise EmailDeliveryError("RESEND_FROM_EMAIL is not configured.")
    if not recipient or not recipient.strip():
        raise EmailDeliveryError("The recipient email address is empty.")

    params: dict[str, Any] = {
        "from": sender,
        "to": [recipient.strip()],
        "subject": subject,
        "text": text_content,
    }
    if html_content:
        params["html"] = html_content

    try:
        resend.api_key = api_key
        response = resend.Emails.send(params)
    except Exception as exc:
        # SDK exceptions may carry request details. Log only the exception type,
        # never the message, headers, or API key.
        logger.warning("Resend email request failed (%s).", type(exc).__name__)
        raise EmailDeliveryError(
            "Resend could not deliver the email. Check the API key, verified sender, and provider status."
        ) from None

    message_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
    if not isinstance(message_id, str) or not message_id.strip():
        raise EmailDeliveryError("Resend did not return an email ID.")
    return message_id


async def send_resend_email(
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str | None = None,
) -> str:
    return await asyncio.to_thread(
        send_resend_email_sync,
        recipient,
        subject,
        text_content,
        html_content,
    )
