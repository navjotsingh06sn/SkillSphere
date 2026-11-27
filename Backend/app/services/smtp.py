import asyncio
import json
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings


class EmailDeliveryError(RuntimeError):
    pass


def send_resend_email_sync(
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str | None = None,
) -> str:
    api_key = settings.resend_api_key.strip()
    sender = settings.resend_from_email.strip() or settings.smtp_from_email.strip()
    if not api_key:
        raise EmailDeliveryError("RESEND_API_KEY is required for HTTPS email delivery.")
    if not sender:
        raise EmailDeliveryError(
            "Set RESEND_FROM_EMAIL to a sender address verified with the email provider."
        )
    if not recipient.strip():
        raise EmailDeliveryError("The recipient email address is empty.")

    payload = {
        "from": formataddr((settings.smtp_from_name.strip() or "SkillSphere", sender)),
        "to": [recipient.strip()],
        "subject": subject,
        "text": text_content,
    }
    if html_content:
        payload["html"] = html_content

    request = Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read(2000).decode("utf-8", errors="replace")
        raise EmailDeliveryError(
            f"HTTPS email provider rejected the message (HTTP {exc.code}): {details[:500]}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise EmailDeliveryError(
            "Could not reach the HTTPS email provider. Check backend internet access."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise EmailDeliveryError(
            "The HTTPS email provider returned an unreadable response."
        ) from exc

    message_id = result.get("id") if isinstance(result, dict) else None
    if not message_id:
        raise EmailDeliveryError("The HTTPS email provider did not return a message ID.")
    return message_id


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
                    f"Could not connect to SMTP server {host}:{settings.smtp_port}. "
                    "If this backend runs on Render Free, outbound SMTP ports 25, 465, and 587 are blocked. "
                    "Configure RESEND_API_KEY and RESEND_FROM_EMAIL for HTTPS email delivery, "
                    "or use a paid Render service with SMTP enabled."
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
    if settings.resend_api_key.strip():
        return await asyncio.to_thread(
            send_resend_email_sync,
            recipient,
            subject,
            text_content,
            html_content,
        )
    return await asyncio.to_thread(
        send_smtp_email_sync,
        recipient,
        subject,
        text_content,
        html_content,
    )
