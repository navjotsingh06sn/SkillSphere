import asyncio
import smtplib
import ssl
import time
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
    password = settings.smtp_password.strip()
    # Google displays app passwords in four-character groups; SMTP expects the
    # same credential without the visual separators.
    if host.lower().endswith("gmail.com"):
        password = "".join(password.split())
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
    server = None
    for attempt in range(2):
        try:
            if settings.smtp_port == 465:
                server = smtplib.SMTP_SSL(
                    host,
                    settings.smtp_port,
                    timeout=20,
                    context=context,
                )
            else:
                server = smtplib.SMTP(host, settings.smtp_port, timeout=20)
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            if settings.smtp_username:
                server.login(settings.smtp_username.strip(), password)
            break
        except (OSError, ssl.SSLError, smtplib.SMTPServerDisconnected) as exc:
            if server is not None:
                try:
                    server.close()
                except Exception:
                    pass
                server = None
            if attempt == 1:
                raise EmailDeliveryError(
                    "SMTP server could not be reached after one retry. "
                    "Check backend internet access, firewall/VPN rules, and the configured SMTP host and port."
                ) from exc
            time.sleep(1)
        except Exception as exc:
            if server is not None:
                try:
                    server.close()
                except Exception:
                    pass
            raise EmailDeliveryError(f"SMTP connection or authentication failed: {str(exc)[:500]}") from exc

    try:
        # Do not retry send_message: if the remote server accepted a message
        # before a connection failure, resending could deliver a duplicate.
        server.send_message(message)
        server.close()
    except Exception as exc:
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
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
