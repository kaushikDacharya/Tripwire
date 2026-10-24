"""Unit tests for GmailMailbox (HTML stripping, MIME decoding, body parsing, IMAP mock)."""
from __future__ import annotations

import email
import email.mime.multipart
import email.mime.text
import unittest
from unittest import mock

from mock_tools.gmail_mailbox import (
    GmailMailbox,
    _decode_mime_header,
    _extract_body_from_message,
    _strip_html,
    load_gmail_credentials,
)


class TestGmailMailboxHelpers(unittest.TestCase):
    def test_decode_mime_header_plain(self):
        self.assertEqual(_decode_mime_header("Hello World"), "Hello World")
        self.assertEqual(_decode_mime_header(""), "")
        self.assertEqual(_decode_mime_header(None), "")

    def test_decode_mime_header_encoded(self):
        # RFC2047 UTF-8 Base64: "Project Update"
        encoded = "=?UTF-8?B?UHJvamVjdCBVcGRhdGU=?="
        self.assertEqual(_decode_mime_header(encoded), "Project Update")

    def test_strip_html(self):
        html_doc = "<html><body><h1>Title</h1><p>First paragraph.</p><br><div>Second &amp; third.</div></body></html>"
        text = _strip_html(html_doc)
        self.assertIn("Title", text)
        self.assertIn("First paragraph.", text)
        self.assertIn("Second & third.", text)
        self.assertNotIn("<p>", text)
        self.assertNotIn("</h1>", text)

    def test_extract_body_plain_text(self):
        msg = email.mime.text.MIMEText("Hello plain text body", "plain", "utf-8")
        body = _extract_body_from_message(msg)
        self.assertEqual(body, "Hello plain text body")

    def test_extract_body_html_fallback(self):
        msg = email.mime.text.MIMEText("<p>HTML only message</p>", "html", "utf-8")
        body = _extract_body_from_message(msg)
        self.assertEqual(body, "HTML only message")

    def test_extract_body_multipart_prefers_plain(self):
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg.attach(email.mime.text.MIMEText("Plain version", "plain", "utf-8"))
        msg.attach(email.mime.text.MIMEText("<p>HTML version</p>", "html", "utf-8"))
        body = _extract_body_from_message(msg)
        self.assertIn("Plain version", body)


class TestGmailMailboxIntegration(unittest.TestCase):
    def test_unconfigured_read_fails_gracefully(self):
        mb = GmailMailbox(email_address="", app_password="")
        res = mb.read(1)
        self.assertFalse(res["ok"])
        self.assertIn("credentials not configured", res["error"].lower())

    @mock.patch("mock_tools.gmail_mailbox.imaplib.IMAP4_SSL")
    def test_mocked_imap_fetch(self, mock_imap_cls):
        mock_imap = mock.MagicMock()
        mock_imap_cls.return_value = mock_imap

        # Mock select and search
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.uid.side_effect = [
            ("OK", [b"101 102"]),  # search returns UIDs 101, 102
            # fetch header for 102 (newest)
            ("OK", [(b"1 (UID 102 BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {40}",
                     b"From: boss@example.com\r\nSubject: Urgent Review\r\nDate: Mon, 20 Oct 2026 10:00:00\r\n\r\n")]),
            # fetch header for 101 (second)
            ("OK", [(b"2 (UID 101 BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {40}",
                     b"From: newsletter@example.com\r\nSubject: Weekly\r\nDate: Sun, 19 Oct 2026 09:00:00\r\n\r\n")]),
            # fetch full email RFC822 for UID 102 (when read(1) is called)
            ("OK", [(b"1 (UID 102 RFC822 {100}",
                     b"From: boss@example.com\r\nSubject: Urgent Review\r\n\r\nPlease review the report immediately.")]),
        ]

        mb = GmailMailbox("test@gmail.com", "mock_app_password_123")
        headers = mb.refresh_inbox(limit=10)

        self.assertEqual(len(headers), 2)
        self.assertEqual(headers[0].index, 1)
        self.assertEqual(headers[0].uid, "102")
        self.assertEqual(headers[0].subject, "Urgent Review")

        # Read email #1 (newest)
        res = mb.read(1)
        self.assertTrue(res["ok"])
        self.assertIn("Please review the report immediately.", res["content"])
        self.assertEqual(res["meta"]["email_id"], 1)
        self.assertEqual(res["meta"]["sender"], "boss@example.com")
        self.assertEqual(res["meta"]["trust_hint"], "UNTRUSTED")


if __name__ == "__main__":
    unittest.main()
