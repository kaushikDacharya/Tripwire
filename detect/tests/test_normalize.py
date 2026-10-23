"""Tests for detect.normalize — text canonicalization."""

import pytest
from detect.normalize import normalize, normalize_light


class TestNormalize:
    def test_lowercase(self):
        assert normalize("HELLO WORLD") == "hello world"

    def test_whitespace_collapse(self):
        assert normalize("hello   world") == "hello world"

    def test_zero_width_removal(self):
        assert normalize("att\u200backer") == "attacker"
        assert normalize("att\u200cacker") == "attacker"
        assert normalize("att\u200dacker") == "attacker"
        assert normalize("att\u2060acker") == "attacker"
        assert normalize("att\ufeffacker") == "attacker"

    def test_html_entity_decode(self):
        assert "@" in normalize("user&#64;example.com")
        assert "&" in normalize("a&amp;b")

    def test_url_decode(self):
        assert "@" in normalize("attacker%40mail.com")

    def test_homoglyph_cyrillic_a(self):
        # Cyrillic 'а' (U+0430) → Latin 'a'
        result = normalize("\u0430ttacker")
        assert result == "attacker"

    def test_at_dot_brackets(self):
        result = normalize("attacker [at] mail [dot] com")
        assert result == "attacker@mail.com"

    def test_at_dot_parens(self):
        result = normalize("attacker (at) mail (dot) com")
        assert result == "attacker@mail.com"

    def test_spaced_out_text(self):
        result = normalize("a t t a c k e r")
        assert "attacker" in result

    def test_combined_obfuscation(self):
        """Multiple obfuscation techniques combined."""
        result = normalize("att\u200backer%40m\u0430il[dot]com")
        assert "attacker@mail.com" in result

    def test_nfkc_normalization(self):
        # Fullwidth @ → regular @
        result = normalize("user\uff20example.com")
        assert "@" in result

    def test_empty_string(self):
        assert normalize("") == ""

    def test_plain_text_unchanged(self):
        assert normalize("hello world") == "hello world"


class TestNormalizeLight:
    def test_lowercase(self):
        assert normalize_light("HELLO") == "hello"

    def test_zero_width_removal(self):
        assert normalize_light("he\u200bllo") == "hello"

    def test_preserves_structure(self):
        # Light normalize should NOT expand [at]/[dot]
        result = normalize_light("user [at] example [dot] com")
        assert "[at]" in result
