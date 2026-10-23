"""
Entity extraction for Tripwire.

Extracts structured entities (emails, URLs, phone numbers, UPI IDs) from
text so the matcher's *entity layer* can compare them exactly.  This catches
attacks where the wording around a copied address is changed but the
address itself is preserved.
"""

from __future__ import annotations
import re
from detect.normalize import normalize_light


# ── Compiled patterns ──────────────────────────────────────────────────

# Email: standard RFC-ish pattern
EMAIL_RE = re.compile(
    r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}",
    re.IGNORECASE,
)

# URL: http/https with optional path
URL_RE = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)

# Indian phone: +91 prefix optional, starts with 6-9
PHONE_RE = re.compile(
    r"(?:\+91[\s\-]?)?[6-9]\d{9}(?!\d)",
)

# UPI ID: name@bank (e.g. user@ybl, kaushik@paytm)
UPI_RE = re.compile(
    r"[a-z0-9._\-]+@(?:ybl|paytm|okaxis|okhdfcbank|okicici|oksbi|"
    r"apl|axisb|ibl|icici|sbi|upi|barodampay|cnrb|csbpay|"
    r"dbs|federal|hdfcbank|idbi|idfcfirst|indus|kotak|mahb|"
    r"pnb|rbl|sc|tjsb|uco|union|utbi|yesbank|"
    r"axl|abfspay|freecharge|gpay|idfcbank|jupiteraxis|"
    r"kbl|ratn|slice|waaxis|waicici|wahdfcbank|wasbi)(?![a-z])",
    re.IGNORECASE,
)


def extract_emails(text: str) -> set[str]:
    """Extract all email addresses (lowercased)."""
    return set(EMAIL_RE.findall(normalize_light(text)))


def extract_urls(text: str) -> set[str]:
    """Extract all URLs (lowercased)."""
    return set(URL_RE.findall(normalize_light(text)))


def extract_phones(text: str) -> set[str]:
    """Extract all Indian phone numbers (digits only)."""
    raw = PHONE_RE.findall(normalize_light(text))
    # Normalize to 10-digit form
    out = set()
    for p in raw:
        digits = re.sub(r"\D", "", p)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) == 10:
            out.add(digits)
    return out


def extract_upi_ids(text: str) -> set[str]:
    """Extract all UPI IDs (lowercased)."""
    return set(UPI_RE.findall(normalize_light(text)))


def extract_all_entities(text: str) -> dict[str, set[str]]:
    """Extract all entity types from text.

    Returns:
        dict with keys "emails", "urls", "phones", "upi_ids",
        each mapping to a set of normalized values.
    """
    return {
        "emails": extract_emails(text),
        "urls": extract_urls(text),
        "phones": extract_phones(text),
        "upi_ids": extract_upi_ids(text),
    }


def entity_overlap(entities_a: dict[str, set[str]],
                    entities_b: dict[str, set[str]]) -> set[str]:
    """Return the set of entities that appear in both A and B.

    Used by the matcher's entity layer: if the argument and a span share
    an email/URL/phone/UPI-ID, that's strong evidence of derivation.
    """
    overlap: set[str] = set()
    for key in entities_a:
        overlap |= entities_a.get(key, set()) & entities_b.get(key, set())
    return overlap
