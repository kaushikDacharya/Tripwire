"""
Secret detection for Tripwire.

Scans text for sensitive information — PAN, Aadhaar, credit/debit cards,
IFSC codes, UPI IDs, API keys, phone numbers, email addresses, and
password-like patterns.  Returns masked values only.

Every candidate is validated with checksums where applicable (Verhoeff
for Aadhaar, Luhn for cards) to reduce false positives.  Context keywords
boost confidence.
"""

from __future__ import annotations
import re
from typing import List

from detect.models import Finding


# ═══════════════════════════════════════════════════════════════════════
#  Checksum validators
# ═══════════════════════════════════════════════════════════════════════

# ── Verhoeff (Aadhaar) ─────────────────────────────────────────────────
_D = [
    [0,1,2,3,4,5,6,7,8,9], [1,2,3,4,0,6,7,8,9,5],
    [2,3,4,0,1,7,8,9,5,6], [3,4,0,1,2,8,9,5,6,7],
    [4,0,1,2,3,9,5,6,7,8], [5,9,8,7,6,0,4,3,2,1],
    [6,5,9,8,7,1,0,4,3,2], [7,6,5,9,8,2,1,0,4,3],
    [8,7,6,5,9,3,2,1,0,4], [9,8,7,6,5,4,3,2,1,0],
]
_P = [
    [0,1,2,3,4,5,6,7,8,9], [1,5,7,6,2,8,3,0,9,4],
    [5,8,0,3,7,9,6,1,4,2], [8,9,1,6,0,4,3,5,2,7],
    [9,4,5,3,1,2,6,8,7,0], [4,2,8,6,5,7,3,9,0,1],
    [2,7,9,3,8,0,6,4,1,5], [7,0,4,6,9,1,3,2,5,8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def verhoeff_ok(num: str) -> bool:
    """Validate a number string using the Verhoeff checksum algorithm."""
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def make_aadhaar(first11: str) -> str:
    """Generate a valid 12-digit Aadhaar from 11 digits (for tests only)."""
    c = 0
    for i, ch in enumerate(reversed(first11)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return first11 + str(_INV[c])


# ── Luhn (credit/debit cards) ─────────────────────────────────────────
def luhn_ok(num: str) -> bool:
    """Validate a number string using the Luhn algorithm."""
    s = 0
    for i, ch in enumerate(reversed(num)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        s += n
    return s % 10 == 0


# ═══════════════════════════════════════════════════════════════════════
#  Regex patterns
# ═══════════════════════════════════════════════════════════════════════

# PAN: 5 letters + 4 digits + 1 letter
# 4th letter encodes entity type: C=Company, P=Person, H=HUF, etc.
_PAN_RE = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b")
_PAN_4TH_VALID = set("ABCFGHLJPT")  # valid 4th-letter codes

# Aadhaar: 12 digits, first digit 2-9, optionally spaced as 4-4-4
_AADHAAR_RE = re.compile(
    r"\b([2-9]\d{3})\s?(\d{4})\s?(\d{4})\b"
)
_AADHAAR_CONTEXT = re.compile(
    r"aadh?a?ar|uid|uidai|unique\s*id", re.IGNORECASE
)

# Credit/debit cards: 13-19 digits, optionally spaced/dashed in groups of 4
_CARD_RE = re.compile(
    r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{1,7})\b"
)

# IFSC: 4 letters + 0 + 6 alphanumeric
_IFSC_RE = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")

# UPI ID: name@bankcode
_UPI_RE = re.compile(
    r"\b([a-zA-Z0-9._\-]+@(?:ybl|paytm|okaxis|okhdfcbank|okicici|oksbi|"
    r"apl|axisb|ibl|icici|sbi|upi|barodampay|cnrb|csbpay|"
    r"dbs|federal|hdfcbank|idbi|idfcfirst|indus|kotak|mahb|"
    r"pnb|rbl|sc|tjsb|uco|union|utbi|yesbank|"
    r"axl|abfspay|freecharge|gpay|idfcbank|jupiteraxis|"
    r"kbl|ratn|slice|waaxis|waicici|wahdfcbank|wasbi))\b",
    re.IGNORECASE,
)

# Indian phone: +91 prefix optional, starts with 6-9
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+91[\s\-]?)?([6-9]\d{9})(?!\d)"
)

# Email addresses
_EMAIL_RE = re.compile(
    r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b"
)

# API keys — known prefixes
_API_KEY_PATTERNS = [
    # AWS Access Key
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    # OpenAI
    re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b"),
    # GitHub personal access token
    re.compile(r"\b(ghp_[a-zA-Z0-9]{36,})\b"),
    # GitHub OAuth
    re.compile(r"\b(gho_[a-zA-Z0-9]{36,})\b"),
    # Stripe
    re.compile(r"\b(sk_live_[a-zA-Z0-9]{24,})\b"),
    re.compile(r"\b(sk_test_[a-zA-Z0-9]{24,})\b"),
    # Generic long hex near "key"/"token"/"secret"/"password"
    re.compile(
        r"(?:key|token|secret|api_key|apikey|api-key|password|pwd)"
        r"[\s:=]+['\"]?([a-fA-F0-9]{32,})['\"]?",
        re.IGNORECASE,
    ),
    # Generic long base64 near "key"/"token"
    re.compile(
        r"(?:key|token|secret|api_key|apikey|api-key)"
        r"[\s:=]+['\"]?([A-Za-z0-9+/]{32,}={0,2})['\"]?",
        re.IGNORECASE,
    ),
]

# Password patterns
_PASSWORD_RE = re.compile(
    r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?(\S+)['\"]?",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════════
#  Masking helpers
# ═══════════════════════════════════════════════════════════════════════

def _mask(value: str, show_last: int = 4) -> str:
    """Mask a value, showing only the last `show_last` characters."""
    if len(value) <= show_last:
        return "X" * len(value)
    return "X" * (len(value) - show_last) + value[-show_last:]


def _mask_email(email: str) -> str:
    """Mask an email address: ka***@***.com"""
    parts = email.split("@")
    if len(parts) != 2:
        return _mask(email)
    local, domain = parts
    dparts = domain.rsplit(".", 1)
    masked_local = local[:2] + "***" if len(local) > 2 else "***"
    masked_domain = "***." + dparts[-1] if len(dparts) == 2 else "***"
    return f"{masked_local}@{masked_domain}"


# ═══════════════════════════════════════════════════════════════════════
#  Main detection function
# ═══════════════════════════════════════════════════════════════════════

def detect_secrets(text: str) -> List[Finding]:
    """Scan text for sensitive information.

    Returns a list of Finding objects with masked values.
    Never stores or logs the raw secret.

    Args:
        text: The text to scan.

    Returns:
        List of Finding objects, sorted by position.
    """
    findings: List[Finding] = []

    # ── PAN ─────────────────────────────────────────────────────────
    for m in _PAN_RE.finditer(text):
        pan = m.group(1)
        # Validate 4th letter
        if pan[3] in _PAN_4TH_VALID:
            findings.append(Finding(
                type="PAN",
                start=m.start(),
                end=m.end(),
                value_masked=_mask(pan),
                confidence="high",
            ))

    # ── Aadhaar ─────────────────────────────────────────────────────
    for m in _AADHAAR_RE.finditer(text):
        digits = m.group(1) + m.group(2) + m.group(3)
        if verhoeff_ok(digits):
            # Check context for confidence boost
            context_window = text[max(0, m.start() - 50):m.end() + 50]
            has_context = bool(_AADHAAR_CONTEXT.search(context_window))
            findings.append(Finding(
                type="AADHAAR",
                start=m.start(),
                end=m.end(),
                value_masked=f"XXXX-XXXX-{digits[-4:]}",
                confidence="high" if has_context else "medium",
            ))

    # ── Credit/debit cards ──────────────────────────────────────────
    for m in _CARD_RE.finditer(text):
        raw = m.group(1)
        digits = re.sub(r"[\s\-]", "", raw)
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            findings.append(Finding(
                type="CARD",
                start=m.start(),
                end=m.end(),
                value_masked=_mask(digits),
                confidence="high",
            ))

    # ── IFSC ────────────────────────────────────────────────────────
    for m in _IFSC_RE.finditer(text):
        findings.append(Finding(
            type="IFSC",
            start=m.start(),
            end=m.end(),
            value_masked=m.group(1)[:4] + "0XXXXXX",
            confidence="high",
        ))

    # ── UPI IDs ─────────────────────────────────────────────────────
    for m in _UPI_RE.finditer(text):
        findings.append(Finding(
            type="UPI_ID",
            start=m.start(),
            end=m.end(),
            value_masked=_mask(m.group(1)),
            confidence="high",
        ))

    # ── Phone numbers ───────────────────────────────────────────────
    for m in _PHONE_RE.finditer(text):
        phone = m.group(1)
        findings.append(Finding(
            type="PHONE",
            start=m.start(),
            end=m.end(),
            value_masked=_mask(phone),
            confidence="medium",
        ))

    # ── Email addresses ─────────────────────────────────────────────
    for m in _EMAIL_RE.finditer(text):
        findings.append(Finding(
            type="EMAIL",
            start=m.start(),
            end=m.end(),
            value_masked=_mask_email(m.group(1)),
            confidence="medium",
        ))

    # ── API keys ────────────────────────────────────────────────────
    for pattern in _API_KEY_PATTERNS:
        for m in pattern.finditer(text):
            key_val = m.group(1) if m.lastindex else m.group(0)
            findings.append(Finding(
                type="API_KEY",
                start=m.start(),
                end=m.end(),
                value_masked=_mask(key_val, show_last=4),
                confidence="high",
            ))

    # ── Passwords ───────────────────────────────────────────────────
    for m in _PASSWORD_RE.finditer(text):
        findings.append(Finding(
            type="PASSWORD",
            start=m.start(),
            end=m.end(),
            value_masked="password:****",
            confidence="high",
        ))

    # ── Deduplicate overlapping findings ────────────────────────────
    findings = _deduplicate(findings)

    # Sort by position
    findings.sort(key=lambda f: f.start)

    return findings


def _deduplicate(findings: List[Finding]) -> List[Finding]:
    """Remove findings that overlap in position, keeping higher priority."""
    if not findings:
        return findings

    # Priority order: AADHAAR > CARD > PAN > rest (to resolve overlaps)
    priority = {
        "AADHAAR": 0, "CARD": 1, "PAN": 2, "API_KEY": 3,
        "PASSWORD": 4, "IFSC": 5, "UPI_ID": 6, "PHONE": 7, "EMAIL": 8,
    }

    # Sort by start, then by priority
    findings.sort(key=lambda f: (f.start, priority.get(f.type, 99)))

    result: List[Finding] = []
    for f in findings:
        if result and f.start < result[-1].end:
            # Overlapping: keep the one with higher priority (lower number)
            existing = result[-1]
            if priority.get(f.type, 99) < priority.get(existing.type, 99):
                result[-1] = f
            # else keep existing
        else:
            result.append(f)

    return result
