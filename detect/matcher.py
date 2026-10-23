"""
Provenance matcher for Tripwire.

Given a tool-call argument (e.g. an email recipient or body) and a list
of context spans with trust labels, determine which spans the argument
derives from, using four layers:

  1. **Exact**: is the argument literally inside the span?
  2. **Entity**: do they share an email, URL, phone, or UPI ID?
  3. **N-gram**: what fraction of the argument's 3-word chunks appear
     in the span?  (Containment, not Jaccard.)
  4. **Fuzzy**: rapidfuzz partial_ratio for small edits and light rewording.

A **trust rule** ensures that entities explicitly provided by the trusted
user are not flagged just because an untrusted span also contains them.
"""

from __future__ import annotations
import re
import base64
import binascii
from typing import List, Optional, Dict, Set

from detect.models import Span, Match
from detect.normalize import normalize
from detect.entities import extract_all_entities, entity_overlap


# ═══════════════════════════════════════════════════════════════════════
#  N-gram (shingle) helpers
# ═══════════════════════════════════════════════════════════════════════

def _shingles(text: str, n: int = 3) -> set[str]:
    """Generate word-level n-grams (shingles) from text."""
    tokens = re.findall(r"\w+", text)
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


# ═══════════════════════════════════════════════════════════════════════
#  Span cache (precompute expensive operations at label-time)
# ═══════════════════════════════════════════════════════════════════════

class SpanCache:
    """Cache normalized text, shingles, and entities per span.

    Create one cache per session/agent-run and call .add() whenever a
    new span is labelled.  The matcher's trace() reads from this cache.
    """

    def __init__(self):
        self._cache: Dict[tuple, dict] = {}

    def _key(self, span: Span) -> tuple:
        return (span.text, span.source, span.trust, span.secret)

    def add(self, span: Span) -> None:
        """Precompute and cache normalized text, shingles, and entities."""
        key = self._key(span)
        if key in self._cache:
            return
        norm = normalize(span.text)
        self._cache[key] = {
            "norm": norm,
            "shingles": _shingles(norm),
            "entities": extract_all_entities(span.text),
        }

    def get(self, span: Span) -> dict:
        """Get cached data for a span, computing if necessary."""
        key = self._key(span)
        if key not in self._cache:
            self.add(span)
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()


# Module-level default cache
_default_cache = SpanCache()


# ═══════════════════════════════════════════════════════════════════════
#  Base64/hex decoding for derived spans
# ═══════════════════════════════════════════════════════════════════════

def _try_decode_base64(text: str) -> Optional[str]:
    """Try to decode base64 blobs in text, return decoded text if printable."""
    b64_re = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
    decoded_parts = []
    for m in b64_re.finditer(text):
        try:
            raw = base64.b64decode(m.group(), validate=True)
            decoded = raw.decode("utf-8", errors="strict")
            if decoded.isprintable() or "\n" in decoded or "\t" in decoded:
                decoded_parts.append(decoded)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
    return " ".join(decoded_parts) if decoded_parts else None


def _try_decode_hex(text: str) -> Optional[str]:
    """Try to decode hex blobs in text, return decoded text if printable."""
    hex_re = re.compile(r"[0-9a-fA-F]{32,}")
    decoded_parts = []
    for m in hex_re.finditer(text):
        try:
            raw = bytes.fromhex(m.group())
            decoded = raw.decode("utf-8", errors="strict")
            if decoded.isprintable() or "\n" in decoded:
                decoded_parts.append(decoded)
        except (ValueError, UnicodeDecodeError):
            continue
    return " ".join(decoded_parts) if decoded_parts else None


# ═══════════════════════════════════════════════════════════════════════
#  Core scoring
# ═══════════════════════════════════════════════════════════════════════

def _score_pair(arg_norm: str, arg_shingles: set, arg_entities: dict,
                span_norm: str, span_shingles: set, span_entities: dict,
                arg_raw: str = "", span_raw: str = "",
                ) -> dict[str, float]:
    """Score a single (argument, span) pair across all layers."""
    scores: dict[str, float] = {}

    # 1. Exact: is the argument (≥8 chars) literally inside the span?
    # Run exact matching on raw, pre-canonicalization text first
    arg_raw_strip = arg_raw.strip() if arg_raw else ""
    if len(arg_raw_strip) >= 8 and (arg_raw_strip in span_raw or arg_raw_strip.lower() in span_raw.lower()):
        scores["exact"] = 1.0
    elif len(arg_norm) >= 8 and arg_norm in span_norm:
        scores["exact"] = 1.0

    # 2. Entity: shared emails/URLs/phones/UPI-IDs
    shared = entity_overlap(arg_entities, span_entities)
    if shared:
        scores["entity"] = 1.0

    # 3. N-gram containment
    if arg_shingles:
        common = arg_shingles & span_shingles
        containment = len(common) / len(arg_shingles)
        if containment > 0:
            scores["ngram"] = round(containment, 4)

    # N-gram containment is already computed above

    # 4. Fuzzy (rapidfuzz partial_ratio), only for strings ≥ 12 chars
    if len(arg_norm) >= 12:
        # Fast path guard clause against O(N^2) latency spikes on long text.
        # If text length exceeds limits, skip expensive fuzzy matching
        # unless n-gram containment already indicates significant overlap.
        MAX_FUZZY_ARG_LEN = 300
        MAX_FUZZY_SPAN_LEN = 800
        is_long = len(arg_norm) > MAX_FUZZY_ARG_LEN or len(span_norm) > MAX_FUZZY_SPAN_LEN
        should_run_fuzzy = not is_long or (scores.get("ngram", 0.0) >= 0.20)

        # Guard: if argument looks like a pure email, don't fuzzy partial-match
        # against body text that doesn't even contain '@'
        if "@" in arg_norm and "@" not in span_norm:
            should_run_fuzzy = False

        if should_run_fuzzy:
            try:
                from rapidfuzz import fuzz
                ratio = fuzz.partial_ratio(arg_norm, span_norm, score_cutoff=65.0) / 100.0
                if ratio >= 0.70:  # ignore low coincidental scores to prevent false positives
                    scores["fuzzy"] = round(ratio, 4)
            except ImportError:
                # rapidfuzz not installed — skip fuzzy layer
                pass

    return scores


# ═══════════════════════════════════════════════════════════════════════
#  Main trace() function
# ═══════════════════════════════════════════════════════════════════════

def trace(arg_text: str,
          spans: List[Span],
          threshold: float = 0.5,
          cache: Optional[SpanCache] = None,
          trusted_entities: Optional[dict] = None,
          ) -> List[Match]:
    """Trace provenance of an argument against context spans.

    Args:
        arg_text: The text from a tool-call argument (recipient, body, URL).
        spans: All context spans the agent has seen so far.
        threshold: Minimum combined score to include a match.
        cache: Optional SpanCache for performance.  If None, uses a
               module-level default cache (fine for tests).
        trusted_entities: Entities explicitly from trusted spans.
            If an entity appears in both trusted and untrusted spans,
            trusted wins and the untrusted match is suppressed.

    Returns:
        List of Match objects sorted by score descending.
    """
    if cache is None:
        cache = _default_cache

    # Precompute argument features
    arg_norm = normalize(arg_text)
    arg_shingles = _shingles(arg_norm)
    arg_entities = extract_all_entities(arg_text)

    # Also try decoded versions of the argument
    decoded_b64 = _try_decode_base64(arg_text)
    decoded_hex = _try_decode_hex(arg_text)
    extra_arg_texts = []
    if decoded_b64:
        extra_arg_texts.append(decoded_b64)
    if decoded_hex:
        extra_arg_texts.append(decoded_hex)

    # Build trusted entity set for the trust rule
    if trusted_entities is None:
        trusted_entities = _build_trusted_entities(spans)
    flat_trusted = _flatten_entities(trusted_entities)

    matches: List[Match] = []

    for span in spans:
        cached = cache.get(span)

        # Score the primary argument
        layer_scores = _score_pair(
            arg_norm, arg_shingles, arg_entities,
            cached["norm"], cached["shingles"], cached["entities"],
            arg_raw=arg_text, span_raw=span.text,
        )

        # Score decoded versions too (base64/hex evasion)
        for extra in extra_arg_texts:
            extra_norm = normalize(extra)
            extra_shingles = _shingles(extra_norm)
            extra_entities = extract_all_entities(extra)
            extra_scores = _score_pair(
                extra_norm, extra_shingles, extra_entities,
                cached["norm"], cached["shingles"], cached["entities"],
                arg_raw=extra, span_raw=span.text,
            )
            # Merge: take max per layer
            for k, v in extra_scores.items():
                layer_scores[k] = max(layer_scores.get(k, 0), v)

        if not layer_scores:
            continue

        # Combined score: max of all layers
        combined = max(layer_scores.values())

        if combined < threshold:
            continue

        # Trust rule: suppress untrusted matches if entity or argument was provided by trusted user
        if span.trust == "UNTRUSTED":
            shared_with_untrusted = entity_overlap(arg_entities, cached["entities"])
            # If ALL shared entities also appear in trusted spans, suppress entity layer
            if shared_with_untrusted and shared_with_untrusted <= flat_trusted:
                layer_scores.pop("entity", None)
            # If the argument is an entity provided by trusted user or appears in trusted text,
            # suppress accidental fuzzy/ngram matches against untrusted spans
            if arg_norm in flat_trusted or arg_text.strip().lower() in [s.text.strip().lower() for s in spans if s.trust == "TRUSTED"]:
                layer_scores.pop("fuzzy", None)
                layer_scores.pop("ngram", None)

            if not layer_scores:
                continue
            combined = max(layer_scores.values())
            if combined < threshold:
                continue

        # Find the best matching layer for the snippet
        best_kind = max(layer_scores, key=layer_scores.get)
        snippet = _extract_snippet(arg_norm, cached["norm"], best_kind, arg_entities, cached["entities"])

        matches.append(Match(
            span=span,
            score=round(combined, 4),
            kind=best_kind,
            snippet=snippet,
            layer_scores=dict(layer_scores),
        ))

    # Sort by score descending
    matches.sort(key=lambda m: m.score, reverse=True)

    return matches


# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════

def _build_trusted_entities(spans: List[Span]) -> dict[str, set[str]]:
    """Collect all entities from TRUSTED spans."""
    trusted: dict[str, set[str]] = {
        "emails": set(), "urls": set(), "phones": set(), "upi_ids": set(),
    }
    for span in spans:
        if span.trust == "TRUSTED":
            ents = extract_all_entities(span.text)
            for key in trusted:
                trusted[key] |= ents.get(key, set())
    return trusted


def _flatten_entities(entities: dict[str, set[str]]) -> set[str]:
    """Flatten entity dict into a single set of all values."""
    flat: set[str] = set()
    for vals in entities.values():
        flat |= vals
    return flat


def _extract_snippet(arg_norm: str, span_norm: str,
                     kind: str, arg_entities: dict, span_entities: dict,
                     max_len: int = 120) -> str:
    """Extract the overlapping text snippet for evidence display."""
    if kind == "exact":
        # Find the argument within the span
        idx = span_norm.find(arg_norm)
        if idx >= 0:
            start = max(0, idx - 10)
            end = min(len(span_norm), idx + len(arg_norm) + 10)
            return span_norm[start:end]

    if kind == "entity":
        shared = entity_overlap(arg_entities, span_entities)
        if shared:
            return f"shared: {', '.join(list(shared)[:3])}"

    if kind in ("ngram", "fuzzy"):
        # Show a window around likely overlap
        # Simple heuristic: find first common word
        arg_words = set(re.findall(r"\w+", arg_norm))
        span_words = re.findall(r"\w+", span_norm)
        for i, w in enumerate(span_words):
            if w in arg_words and len(w) > 3:
                # Show context around this word
                start_idx = span_norm.find(w)
                if start_idx >= 0:
                    start = max(0, start_idx - 20)
                    end = min(len(span_norm), start_idx + max_len - 20)
                    return span_norm[start:end]

    # Fallback: beginning of span
    return span_norm[:max_len]
