import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import settings


class EmailDeliveryError(RuntimeError):
    pass


def send_smtp_email_sync(
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str | None = None,
) -> str:
    host = settings.smtp_host.strip()
    sender = settings.smtp_from_email.strip()
    if not host or not sender:
        raise EmailDeliveryError(
            "SMTP is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL."
        )
    if not recipient.strip():
        raise EmailDeliveryError("The recipient email address is empty.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.smtp_from_name.strip() or "SkillSphere", sender))
    message["To"] = recipient
    message["Message-ID"] = make_msgid()
    message.set_content(text_content)
    if html_content:
        message.add_alternative(html_content, subtype="html")

    context = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:
            connection = smtplib.SMTP_SSL(
                host,
                settings.smtp_port,
                timeout=15,
                context=context,
            )
        else:
            connection = smtplib.SMTP(host, settings.smtp_port, timeout=15)

        with connection as server:
            if settings.smtp_port != 465:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except Exception as exc:
        raise EmailDeliveryError(f"SMTP delivery failed: {str(exc)[:500]}") from exc

    return message["Message-ID"]


async def send_smtp_email(
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str | None = None,
) -> str:
    return await asyncio.to_thread(
        send_smtp_email_sync,
        recipient,
        subject,
        text_content,
        html_content,
    )
