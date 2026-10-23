"""
Tripwire Detection Module (Person B)

Provides:
  - Secret detection (PAN, Aadhaar, cards, API keys, etc.)
  - Provenance matching (exact, entity, n-gram, fuzzy)
  - Injection classification (heuristic + ML)
"""

from detect.models import Span, Match, Finding
from detect.secrets import detect_secrets
from detect.matcher import trace
from detect.injection import injection_score

__all__ = [
    "Span", "Match", "Finding",
    "detect_secrets", "trace", "injection_score",
]
