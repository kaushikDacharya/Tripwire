"""Simulated outbox + HTTP request log.

Only SUCCESSFUL simulated actions are recorded here. If Tripwire blocks a call,
the tool is never invoked, so nothing lands in these lists. That makes the
outbox a trustworthy "what really left the building" record for the eval.
"""
from __future__ import annotations

from typing import List, Optional


class Outbox:
    def __init__(self):
        self.emails: List[dict] = []
        self.http_requests: List[dict] = []

    def record_email(self, to: str, body: str,
                     attachment_name: Optional[str] = None,
                     attachment_text: Optional[str] = None) -> dict:
        entry = {
            "id": len(self.emails) + 1,
            "to": to,
            "body": body,
            "attachment_name": attachment_name,
            "attachment_text": attachment_text,
        }
        self.emails.append(entry)
        return entry

    def record_http_post(self, url: str, body: str) -> dict:
        entry = {"id": len(self.http_requests) + 1, "url": url, "body": body}
        self.http_requests.append(entry)
        return entry

    def total_sent(self) -> int:
        return len(self.emails) + len(self.http_requests)
