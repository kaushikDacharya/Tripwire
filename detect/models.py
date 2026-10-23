"""
Shared data models for Tripwire.

These dataclasses define the contract between Person A (Core), Person B
(Detection) and Person D (UI).  Any change to these *must* be communicated
to the whole team.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


# ── Span: a chunk of data with provenance ──────────────────────────────
@dataclass
class Span:
    """A piece of text with provenance and secrecy labels."""
    text: str
    source: str        # "user" | "email:3" | "web:url" | "file:payroll.xlsx"
    trust: str         # "TRUSTED" | "UNTRUSTED"
    secret: bool = False


# ── ToolCall / Decision (Person A's domain, included for reference) ────
@dataclass
class ToolCall:
    name: str          # "send_email", "http_post", ...
    args: dict = field(default_factory=dict)


@dataclass
class Decision:
    verdict: str       # "ALLOW" | "ASK" | "BLOCK"
    reason_code: str   # e.g. "RECIPIENT_FROM_UNTRUSTED"
    evidence: list = field(default_factory=list)


# ── Match: what trace() returns ────────────────────────────────────────
@dataclass
class Match:
    """A provenance match between an argument and a context span."""
    span: Span
    score: float          # 0..1, combined
    kind: str             # "exact" | "entity" | "ngram" | "fuzzy"
    snippet: str          # the overlapping text, for the evidence panel
    layer_scores: Optional[dict] = None  # {"exact": 0.0, "entity": 1.0, ...}


# ── Finding: what detect_secrets() returns ─────────────────────────────
@dataclass
class Finding:
    """A secret detected in text (PAN, Aadhaar, card number, etc.)."""
    type: str             # "PAN" | "AADHAAR" | "CARD" | "API_KEY" | ...
    start: int
    end: int
    value_masked: str     # never store or display the raw secret
    confidence: str = "high"  # "high" | "medium" | "low"
