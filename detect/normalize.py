"""
Text canonicalization for Tripwire's provenance matcher.

Every comparison is done on *normalized* text so that cosmetic tricks
(zero-width characters, homoglyphs, HTML entities, URL encoding,
spaced-out text) don't bypass matching.
"""

from __future__ import annotations
import re
import html
import unicodedata
from urllib.parse import unquote


# ── Zero-width & invisible character removal ───────────────────────────
_ZERO_WIDTH = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e"),
    None,
)

# ── Homoglyph mapping (Cyrillic → Latin, common confusables) ──────────
_HOMOGLYPHS: dict[str, str] = {
    "\u0430": "a",  # Cyrillic а
    "\u0435": "e",  # Cyrillic е
    "\u043e": "o",  # Cyrillic о
    "\u0440": "p",  # Cyrillic р
    "\u0441": "c",  # Cyrillic с
    "\u0443": "y",  # Cyrillic у (looks like y)
    "\u0445": "x",  # Cyrillic х
    "\u0456": "i",  # Cyrillic і
    "\u0458": "j",  # Cyrillic ј
    "\u04bb": "h",  # Cyrillic һ
    "\u0410": "A",
    "\u0412": "B",
    "\u0415": "E",
    "\u041a": "K",
    "\u041c": "M",
    "\u041d": "H",
    "\u041e": "O",
    "\u0420": "P",
    "\u0421": "C",
    "\u0422": "T",
    "\u0425": "X",
    "\u0130": "I",  # Latin capital I with dot above
    "\uff20": "@",  # fullwidth @
    "\uff0e": ".",  # fullwidth .
}
_HOMOGLYPH_TABLE = str.maketrans(_HOMOGLYPHS)



def normalize(text: str) -> str:
    """Full normalization pipeline for text comparison.

    Steps:
      1. Unicode NFKC normalization
      2. HTML entity decoding (&amp; → &, &#64; → @, etc.)
      3. URL percent-decoding (%40 → @, etc.)
      4. Zero-width / invisible character removal
      5. Homoglyph folding (Cyrillic → Latin)
      6. "at"/"dot" obfuscation expansion
      7. Spaced-out text collapse (a t t a c k e r → attacker)
      8. Lowercase + whitespace collapse
    """
    t = text

    # 1. Unicode NFKC
    t = unicodedata.normalize("NFKC", t)

    # 2. HTML entity decode (handles &#64; &amp; &lt; etc.)
    t = html.unescape(t)

    # 3. URL percent-decode
    t = unquote(t)

    # 4. Zero-width removal
    t = t.translate(_ZERO_WIDTH)

    # 5. Homoglyph folding
    t = t.translate(_HOMOGLYPH_TABLE)

    # 6. "at" / "dot" obfuscation  (attacker [at] mail [dot] com)
    t = re.sub(r"\s*\[at\]\s*", "@", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(at\)\s*", "@", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+at\s+", "@", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\[dot\]\s*", ".", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(dot\)\s*", ".", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+dot\s+", ".", t, flags=re.IGNORECASE)

    # 7. Spaced-out text collapse: "a t t a c k e r" → "attacker"
    #    Heuristic: if we see ≥4 single-char tokens separated by spaces
    t = _collapse_spaced(t)

    # 8. Lowercase + whitespace collapse
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()

    return t


def _collapse_spaced(text: str) -> str:
    """Collapse sequences of single characters separated by spaces.

    'a t t a c k e r @ m a i l . c o m' → 'attacker@mail.com'
    Only triggers when ≥4 consecutive single-char tokens are found.
    """
    def _replacer(m: re.Match) -> str:
        # Remove spaces between single characters
        return re.sub(r"\s+", "", m.group(0))

    # Match sequences of: (single_char space){3,} single_char
    return re.sub(
        r"(?<!\w)(\S\s){3,}\S(?!\w)",
        _replacer,
        text,
    )


def normalize_light(text: str) -> str:
    """Light normalization: NFKC + zero-width removal + lowercase + whitespace.

    Used where full normalization might be too aggressive (e.g. for
    entity extraction where we want to preserve structure).
    """
    t = unicodedata.normalize("NFKC", text)
    t = t.translate(_ZERO_WIDTH)
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t
