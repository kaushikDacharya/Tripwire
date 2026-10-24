"""Gmail mailbox connector using IMAP (Python standard library only).

Allows the Tripwire agent and tools to access real Gmail messages instead
of mock emails.

Configuration:
  Set environment variables or create a `.env` / `gmail_config.json` file:
    GMAIL_ADDRESS = your_email@gmail.com
    GMAIL_APP_PASSWORD = xxxx xxxx xxxx xxxx (16-character Google App Password)

How to get a Google App Password:
  1. Go to your Google Account (myaccount.google.com) -> Security.
  2. Under "How you sign in to Google", ensure "2-Step Verification" is ON.
  3. Search for "App passwords" (or visit: myaccount.google.com/apppasswords).
  4. Create an App password (e.g. named "Tripwire Agent").
  5. Copy the generated 16-character code into GMAIL_APP_PASSWORD.
"""
from __future__ import annotations

import email
import email.header
import html
import imaplib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
TRUST_UNTRUSTED = "UNTRUSTED"


def _decode_mime_header(header_value: Optional[str]) -> str:
    """Safely decode RFC2047 MIME encoded headers like '=?UTF-8?B?...?='."""
    if not header_value:
        return ""
    try:
        decoded_fragments = email.header.decode_header(header_value)
        parts = []
        for text, encoding in decoded_fragments:
            if isinstance(text, bytes):
                encoding = encoding or "utf-8"
                try:
                    parts.append(text.decode(encoding, errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    parts.append(text.decode("latin-1", errors="replace"))
            else:
                parts.append(str(text))
        return "".join(parts)
    except Exception:
        return str(header_value)


def _strip_html(html_text: str) -> str:
    """Convert HTML content into readable plain text."""
    # Remove script and style elements
    clean = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", "", html_text)
    # Replace line breaks and paragraph ends with newlines
    clean = re.sub(r"(?i)<br\s*/?>", "\n", clean)
    clean = re.sub(r"(?i)</p>", "\n\n", clean)
    clean = re.sub(r"(?i)</div>", "\n", clean)
    # Strip remaining tags
    clean = re.sub(r"<[^>]+>", " ", clean)
    # Unescape HTML entities (&amp;, &lt;, etc.)
    clean = html.unescape(clean)
    # Clean up excess whitespace
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n\s*\n+", "\n\n", clean)
    return clean.strip()


def _extract_body_from_message(msg: email.message.Message) -> str:
    """Extract plain text body, falling back to converted HTML."""
    plain_parts: List[str] = []
    html_parts: List[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                continue

            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if payload is None:
                continue

            try:
                decoded_text = payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                decoded_text = payload.decode("latin-1", errors="replace")

            if content_type == "text/plain":
                plain_parts.append(decoded_text)
            elif content_type == "text/html":
                html_parts.append(decoded_text)
    else:
        content_type = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload is not None:
            try:
                decoded_text = payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                decoded_text = payload.decode("latin-1", errors="replace")
            if content_type == "text/plain":
                plain_parts.append(decoded_text)
            elif content_type == "text/html":
                html_parts.append(decoded_text)

    if plain_parts:
        return "\n\n".join(p.strip() for p in plain_parts if p.strip())
    if html_parts:
        combined_html = "\n\n".join(html_parts)
        return _strip_html(combined_html)

    return "(No readable text body found in email)"


def load_gmail_credentials() -> Tuple[str, str]:
    """Retrieve Gmail credentials from environment, .env file, or config.json.

    Returns:
        (email_address, app_password)
    """
    email_addr = os.getenv("GMAIL_ADDRESS") or os.getenv("GMAIL_USER") or ""
    password = os.getenv("GMAIL_APP_PASSWORD") or os.getenv("GMAIL_PASSWORD") or ""

    if email_addr and password:
        return email_addr.strip(), password.strip().replace(" ", "")

    # Look for .env file in current or parent dirs
    search_paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env"),
    ]

    for p in search_paths:
        abs_p = os.path.abspath(p)
        if os.path.exists(abs_p):
            try:
                with open(abs_p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k in ("GMAIL_ADDRESS", "GMAIL_USER") and not email_addr:
                            email_addr = v
                        elif k in ("GMAIL_APP_PASSWORD", "GMAIL_PASSWORD") and not password:
                            password = v
            except Exception:
                pass

    # Look for gmail_config.json
    json_paths = [
        os.path.join(os.getcwd(), "gmail_config.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gmail_config.json"),
    ]
    for jp in json_paths:
        abs_jp = os.path.abspath(jp)
        if os.path.exists(abs_jp):
            try:
                with open(abs_jp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    email_addr = email_addr or data.get("email", "")
                    password = password or data.get("app_password", "")
            except Exception:
                pass

    return email_addr.strip(), password.strip().replace(" ", "")


@dataclass
class GmailHeader:
    index: int               # 1-based index (1 = newest email)
    uid: str                 # Gmail IMAP UID
    sender: str              # Decoded From header
    subject: str             # Decoded Subject
    date: str                # Decoded Date


class GmailMailbox:
    """Connects to real Gmail via IMAP and serves emails to Tripwire tools.

    Provides the same interface as Mock Mailbox:
        read(email_id) -> {"ok": True, "content": ..., "meta": ...}

    Supports:
        * email_id = 1, 2, ...: Accesses the latest Nth email from inbox (1 = newest).
        * email_id = "UID": Accesses by Gmail IMAP UID string.
        * list_emails(limit): Returns recent email headers for agent / UI inspection.
    """

    def __init__(
        self,
        email_address: Optional[str] = None,
        app_password: Optional[str] = None,
        imap_server: str = IMAP_SERVER,
        imap_port: int = IMAP_PORT,
        max_cache_size: int = 50,
    ):
        creds_email, creds_pwd = load_gmail_credentials()
        self.email_address = (creds_email if email_address is None else email_address).strip()
        self.app_password = (creds_pwd if app_password is None else app_password).strip().replace(" ", "")
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.max_cache_size = max_cache_size

        # In-memory mapping: 1-indexed number -> UID, and UID -> parsed message cache
        self._index_to_uid: Dict[int, str] = {}
        self._uid_to_header: Dict[str, GmailHeader] = {}
        self._msg_cache: Dict[str, dict] = {}
        self._inbox_initialized = False

    def is_configured(self) -> bool:
        """Check whether email and app password have been supplied."""
        return bool(self.email_address and self.app_password)

    def _connect(self) -> imaplib.IMAP4_SSL:
        """Establish an authenticated IMAP SSL connection."""
        if not self.is_configured():
            raise ValueError(
                "Gmail credentials not configured. Please set GMAIL_ADDRESS and "
                "GMAIL_APP_PASSWORD in environment variables or a .env file."
            )
        try:
            client = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            client.login(self.email_address, self.app_password)
            return client
        except imaplib.IMAP4.error as exc:
            msg = str(exc)
            if "AUTHENTICATIONFAILED" in msg.upper() or "INVALID CREDENTIALS" in msg.upper():
                raise ConnectionError(
                    f"Gmail IMAP authentication failed for {self.email_address}. "
                    "Make sure you are using a 16-character Google App Password (not your "
                    "regular Google password) and that 2-Step Verification is enabled. "
                    f"Details: {exc}"
                ) from exc
            raise ConnectionError(f"Failed to connect to Gmail IMAP ({self.imap_server}): {exc}") from exc

    def refresh_inbox(self, limit: int = 25) -> List[GmailHeader]:
        """Fetch latest email UIDs and headers from INBOX (newest first)."""
        client = self._connect()
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise RuntimeError(f"Could not open INBOX: {status}")

            # Search all messages in INBOX
            status, data = client.uid("search", None, "ALL")
            if status != "OK" or not data or not data[0]:
                self._index_to_uid.clear()
                self._inbox_initialized = True
                return []

            all_uids = data[0].split()
            # Newest emails are at the end of the list; reverse so index 1 = newest
            recent_uids = list(reversed(all_uids[-limit:]))

            self._index_to_uid.clear()
            self._uid_to_header.clear()
            headers_list: List[GmailHeader] = []

            for idx, uid_bytes in enumerate(recent_uids, start=1):
                uid_str = uid_bytes.decode("ascii", errors="ignore")
                self._index_to_uid[idx] = uid_str

                # Fetch header only for speed
                res, header_data = client.uid(
                    "fetch", uid_bytes, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
                )
                sender = "Unknown Sender"
                subject = "(No Subject)"
                date_str = ""

                if res == "OK" and header_data:
                    for part in header_data:
                        if isinstance(part, tuple) and len(part) > 1:
                            hdr_msg = email.message_from_bytes(part[1])
                            sender = _decode_mime_header(hdr_msg.get("From")) or sender
                            subject = _decode_mime_header(hdr_msg.get("Subject")) or subject
                            date_str = _decode_mime_header(hdr_msg.get("Date")) or date_str

                hdr = GmailHeader(
                    index=idx,
                    uid=uid_str,
                    sender=sender.strip(),
                    subject=subject.strip(),
                    date=date_str.strip(),
                )
                self._uid_to_header[uid_str] = hdr
                headers_list.append(hdr)

            self._inbox_initialized = True
            return headers_list
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

    def list_emails(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return a user/agent-friendly summary list of latest emails."""
        headers = self.refresh_inbox(limit=limit)
        return [
            {
                "index": h.index,
                "uid": h.uid,
                "sender": h.sender,
                "subject": h.subject,
                "date": h.date,
            }
            for h in headers
        ]

    def _resolve_uid(self, email_id: Any) -> Optional[str]:
        """Convert 1-based index (e.g. 1, 2) or UID string to a Gmail UID."""
        # Fast path: large integers (> 500) are IMAP UIDs, not 1-based inbox indices
        try:
            val_int = int(email_id)
            if val_int > 500:
                return str(val_int)
        except (ValueError, TypeError):
            pass

        if not self._inbox_initialized:
            self.refresh_inbox(limit=self.max_cache_size)

        # Check if email_id is an integer or stringified integer
        try:
            key_int = int(email_id)
            if key_int in self._index_to_uid:
                return self._index_to_uid[key_int]
        except (ValueError, TypeError):
            pass

        # Check if it matches a UID directly
        uid_str = str(email_id).strip()
        if uid_str in self._uid_to_header or uid_str in self._index_to_uid.values():
            return uid_str

        # If not found yet, try refreshing inbox once in case new emails arrived
        self.refresh_inbox(limit=self.max_cache_size)
        try:
            key_int = int(email_id)
            if key_int in self._index_to_uid:
                return self._index_to_uid[key_int]
        except (ValueError, TypeError):
            pass

        return uid_str if uid_str in self._uid_to_header else uid_str if uid_str.isdigit() else None

    def read(self, email_id: Any) -> dict:
        """Fetch an email and return tool output matching Tripwire standard.

        Format:
            {
                "ok": True,
                "content": "From: ...\\nSubject: ...\\nDate: ...\\n\\n...",
                "meta": {
                    "source": "gmail:1",
                    "trust_hint": "UNTRUSTED",
                    "email_id": 1,
                    "sender": ...,
                    "subject": ...,
                    "date": ...
                }
            }
        """
        if not self.is_configured():
            return {
                "ok": False,
                "error": (
                    "Gmail credentials not configured. Please set GMAIL_ADDRESS "
                    "and GMAIL_APP_PASSWORD in .env or environment variables."
                ),
            }

        uid = self._resolve_uid(email_id)
        if not uid:
            return {
                "ok": False,
                "error": f"Email not found for id/index: {email_id!r} (available indices: {list(self._index_to_uid.keys())[:10]})",
            }

        # Check cache
        if uid in self._msg_cache:
            return self._msg_cache[uid]

        client = None
        try:
            client = self._connect()
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                return {"ok": False, "error": f"Could not select INBOX: {status}"}

            status, data = client.uid("fetch", uid.encode("ascii"), "(RFC822)")
            if status != "OK" or not data:
                return {"ok": False, "error": f"Failed to fetch email UID {uid}: {status}"}

            raw_email = None
            for part in data:
                if isinstance(part, tuple) and len(part) > 1:
                    raw_email = part[1]
                    break

            if not raw_email:
                return {"ok": False, "error": f"Empty message data for UID {uid}"}

            msg = email.message_from_bytes(raw_email)
            sender = _decode_mime_header(msg.get("From")) or "Unknown Sender"
            subject = _decode_mime_header(msg.get("Subject")) or "(No Subject)"
            date_str = _decode_mime_header(msg.get("Date")) or ""
            body_text = _extract_body_from_message(msg)

            full_text = f"From: {sender}\nSubject: {subject}\nDate: {date_str}\n\n{body_text}"

            result = {
                "ok": True,
                "content": full_text,
                "meta": {
                    "source": f"gmail:{email_id}",
                    "trust_hint": TRUST_UNTRUSTED,
                    "email_id": email_id,
                    "sender": sender,
                    "subject": subject,
                    "date": date_str,
                    "uid": uid,
                },
            }

            self._msg_cache[uid] = result
            return result

        except Exception as exc:
            return {"ok": False, "error": f"Gmail fetch error: {exc}"}
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
                try:
                    client.logout()
                except Exception:
                    pass

    def ids(self) -> List[int]:
        """Return available email numeric indices (1, 2, ...)."""
        if not self._inbox_initialized:
            try:
                self.refresh_inbox(limit=10)
            except Exception:
                return []
        return sorted(self._index_to_uid.keys())
