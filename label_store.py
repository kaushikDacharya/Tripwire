import re
from models import Span, UNTRUSTED, SECRET

PATTERNS = {
    "AADHAAR": r"^[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\s?[0-9]{4}$",
    "PAN": r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$",
    "IBAN": r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$",
    "API_KEY": r"(?:sk|gsk|AKIA)[-_A-Za-z0-9]{16,}",
}

class LabelStore:
    """Stores and retrieves text spans with security labels."""

    def __init__(self) -> None:
        self.spans: list[Span] = []

    def add(self, text: any, source: str, untrusted: bool = False, secret: bool = False) -> None:
        """Labels text and stores it if at least one label is present."""
        text_str = str(text)
        labels = set()

        if untrusted:
            labels.add(UNTRUSTED)

        # Check manual secret flag or regex patterns
        is_pattern_secret = any(re.search(pat, text_str) for pat in PATTERNS.values())
        if secret or is_pattern_secret:
            labels.add(SECRET)

        if labels:
            self.spans.append(Span(text=text_str, labels=labels, source=source))

    def with_label(self, label: str) -> list[Span]:
        """Returns all spans containing the specified label."""
        return [s for s in self.spans if label in s.labels]

    def clear(self) -> None:
        """Clears all stored spans."""
        self.spans = []
