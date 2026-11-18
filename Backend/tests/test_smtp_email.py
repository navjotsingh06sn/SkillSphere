import unittest
from unittest.mock import MagicMock, patch

from app.services import smtp


class SMTPEmailTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_multipart_message_over_starttls(self):
        server = MagicMock()
        connection = MagicMock()
        connection.__enter__.return_value = server
        with (
            patch.object(smtp.settings, "smtp_host", "smtp.example.test"),
            patch.object(smtp.settings, "smtp_port", 587),
            patch.object(smtp.settings, "smtp_username", "user"),
            patch.object(smtp.settings, "smtp_password", "secret"),
            patch.object(smtp.settings, "smtp_from_email", "sender@example.test"),
            patch.object(smtp.settings, "smtp_from_name", "SkillSphere"),
            patch.object(smtp.smtplib, "SMTP", return_value=connection) as smtp_client,
        ):
            message_id = await smtp.send_smtp_email(
                "candidate@example.test",
                "Interview invitation",
                "Plain text",
                "<p>HTML</p>",
            )

        smtp_client.assert_called_once_with("smtp.example.test", 587, timeout=15)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("user", "secret")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "candidate@example.test")
        self.assertEqual(message["From"], "SkillSphere <sender@example.test>")
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        self.assertTrue(message_id)

    async def test_missing_smtp_configuration_fails_explicitly(self):
        with (
            patch.object(smtp.settings, "smtp_host", ""),
            patch.object(smtp.settings, "smtp_from_email", ""),
        ):
            with self.assertRaisesRegex(smtp.EmailDeliveryError, "SMTP_HOST"):
                await smtp.send_smtp_email("candidate@example.test", "Subject", "Text")

    async def test_smtps_uses_port_465_without_starttls(self):
        server = MagicMock()
        connection = MagicMock()
        connection.__enter__.return_value = server
        with (
            patch.object(smtp.settings, "smtp_host", "smtp.example.test"),
            patch.object(smtp.settings, "smtp_port", 465),
            patch.object(smtp.settings, "smtp_username", ""),
            patch.object(smtp.settings, "smtp_from_email", "sender@example.test"),
            patch.object(smtp.settings, "smtp_from_name", "SkillSphere"),
            patch.object(smtp.smtplib, "SMTP_SSL", return_value=connection) as ssl_client,
        ):
            await smtp.send_smtp_email("candidate@example.test", "Subject", "Text")

        self.assertEqual(ssl_client.call_args.args[:2], ("smtp.example.test", 465))
        server.starttls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
