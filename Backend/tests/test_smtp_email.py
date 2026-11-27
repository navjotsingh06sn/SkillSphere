import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import smtp


class ResendEmailTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_email_interface_uses_official_resend_sdk(self):
        with (
            patch.object(smtp.settings, "resend_api_key", "test-api-key"),
            patch.object(smtp.settings, "resend_from_email", "SkillSphere <hello@example.test>"),
            patch.object(smtp.resend.Emails, "send", return_value=SimpleNamespace(id="resend-message-id")) as send,
        ):
            message_id = await smtp.send_resend_email(
                "candidate@example.test",
                "Interview invitation",
                "Plain text",
                "<p>HTML</p>",
            )

        self.assertEqual(message_id, "resend-message-id")
        self.assertEqual(smtp.resend.api_key, "test-api-key")
        send.assert_called_once_with({
            "from": "SkillSphere <hello@example.test>",
            "to": ["candidate@example.test"],
            "subject": "Interview invitation",
            "text": "Plain text",
            "html": "<p>HTML</p>",
        })

    async def test_sdk_error_is_safe_and_does_not_expose_secret(self):
        with (
            patch.object(smtp.settings, "resend_api_key", "never-log-this-key"),
            patch.object(smtp.settings, "resend_from_email", "hello@example.test"),
            patch.object(smtp.resend.Emails, "send", side_effect=RuntimeError("never-log-this-key")),
        ):
            with self.assertRaises(smtp.EmailDeliveryError) as error:
                await smtp.send_smtp_email("candidate@example.test", "Subject", "Text")

        self.assertNotIn("never-log-this-key", str(error.exception))
        self.assertIn("verified sender", str(error.exception))

    async def test_missing_resend_configuration_fails_explicitly(self):
        with (
            patch.object(smtp.settings, "resend_api_key", ""),
            patch.object(smtp.settings, "resend_from_email", ""),
        ):
            with self.assertRaisesRegex(smtp.EmailDeliveryError, "RESEND_API_KEY"):
                await smtp.send_smtp_email("candidate@example.test", "Subject", "Text")

    async def test_sync_compatibility_interface_uses_resend(self):
        with (
            patch.object(smtp.settings, "resend_api_key", "test-api-key"),
            patch.object(smtp.settings, "resend_from_email", "hello@example.test"),
            patch.object(smtp.resend.Emails, "send", return_value={"id": "sync-message-id"}),
        ):
            message_id = smtp.send_smtp_email_sync("candidate@example.test", "Subject", "Text")

        self.assertEqual(message_id, "sync-message-id")


if __name__ == "__main__":
    unittest.main()
