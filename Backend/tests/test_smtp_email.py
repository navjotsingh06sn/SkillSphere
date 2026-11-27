import json
import unittest
from unittest.mock import MagicMock, patch

from app.services import smtp


class SMTPEmailTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_multipart_message_over_starttls(self):
        connection = MagicMock()
        with (
            patch.object(smtp.settings, "smtp_host", "smtp.example.test"),
            patch.object(smtp.settings, "smtp_port", 587),
            patch.object(smtp.settings, "smtp_username", "user"),
            patch.object(smtp.settings, "smtp_password", "secret"),
            patch.object(smtp.settings, "smtp_from_email", "sender@example.test"),
            patch.object(smtp.settings, "smtp_from_name", "SkillSphere"),
            patch.object(smtp.settings, "resend_api_key", ""),
            patch.object(smtp.smtplib, "SMTP", return_value=connection) as smtp_client,
        ):
            message_id = await smtp.send_smtp_email(
                "candidate@example.test",
                "Interview invitation",
                "Plain text",
                "<p>HTML</p>",
            )

        smtp_client.assert_called_once_with("smtp.example.test", 587, timeout=20)
        connection.starttls.assert_called_once()
        connection.login.assert_called_once_with("user", "secret")
        message = connection.send_message.call_args.args[0]
        self.assertEqual(message["To"], "candidate@example.test")
        self.assertEqual(message["From"], "SkillSphere <sender@example.test>")
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        self.assertTrue(message_id)

    async def test_resend_https_delivery_is_selected_when_api_key_is_configured(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"id":"resend-message-id"}'
        with (
            patch.object(smtp.settings, "resend_api_key", "test-api-key"),
            patch.object(smtp.settings, "resend_from_email", "hello@example.test"),
            patch.object(smtp.settings, "smtp_from_email", ""),
            patch.object(smtp.settings, "smtp_from_name", "SkillSphere"),
            patch.object(smtp.smtplib, "SMTP") as smtp_client,
            patch.object(smtp, "urlopen", return_value=response) as http_client,
        ):
            message_id = await smtp.send_smtp_email(
                "candidate@example.test",
                "Interview invitation",
                "Plain text",
                "<p>HTML</p>",
            )

        self.assertEqual(message_id, "resend-message-id")
        smtp_client.assert_not_called()
        request = http_client.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-api-key")
        self.assertEqual(json.loads(request.data), {
            "from": "SkillSphere <hello@example.test>",
            "to": ["candidate@example.test"],
            "subject": "Interview invitation",
            "text": "Plain text",
            "html": "<p>HTML</p>",
        })

    async def test_missing_smtp_configuration_fails_explicitly(self):
        with (
            patch.object(smtp.settings, "smtp_host", ""),
            patch.object(smtp.settings, "smtp_from_email", ""),
            patch.object(smtp.settings, "resend_api_key", ""),
        ):
            with self.assertRaisesRegex(smtp.EmailDeliveryError, "SMTP_HOST"):
                await smtp.send_smtp_email("candidate@example.test", "Subject", "Text")

    async def test_unreachable_smtp_explains_render_free_block_and_https_fallback(self):
        with (
            patch.object(smtp.settings, "smtp_host", "smtp.gmail.com"),
            patch.object(smtp.settings, "smtp_port", 587),
            patch.object(smtp.settings, "smtp_from_email", "sender@example.test"),
            patch.object(smtp.settings, "resend_api_key", ""),
            patch.object(smtp.smtplib, "SMTP", side_effect=OSError("network unreachable")),
            patch.object(smtp.time, "sleep"),
        ):
            with self.assertRaises(smtp.EmailDeliveryError) as error:
                await smtp.send_smtp_email("candidate@example.test", "Subject", "Text")

        self.assertIn("smtp.gmail.com:587", str(error.exception))
        self.assertIn("Render Free", str(error.exception))
        self.assertIn("RESEND_API_KEY", str(error.exception))

    async def test_smtps_uses_port_465_without_starttls(self):
        connection = MagicMock()
        with (
            patch.object(smtp.settings, "smtp_host", "smtp.example.test"),
            patch.object(smtp.settings, "smtp_port", 465),
            patch.object(smtp.settings, "smtp_username", ""),
            patch.object(smtp.settings, "smtp_from_email", "sender@example.test"),
            patch.object(smtp.settings, "smtp_from_name", "SkillSphere"),
            patch.object(smtp.settings, "resend_api_key", ""),
            patch.object(smtp.smtplib, "SMTP_SSL", return_value=connection) as ssl_client,
        ):
            await smtp.send_smtp_email("candidate@example.test", "Subject", "Text")

        self.assertEqual(ssl_client.call_args.args[:2], ("smtp.example.test", 465))
        connection.starttls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
