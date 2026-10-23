import pytest
from label_store import LabelStore
from models import SECRET, UNTRUSTED

def test_regex_patterns():
    ls = LabelStore()
    # AADHAAR
    ls.add("2345 6789 1234 5678", "src")
    assert len(ls.with_label(SECRET)) == 1
    ls.clear()
    
    # PAN
    ls.add("ABCDE1234F", "src")
    assert len(ls.with_label(SECRET)) == 1
    ls.clear()
    
    # IBAN
    ls.add("GB12ABCD12345678901234", "src")
    assert len(ls.with_label(SECRET)) == 1
    ls.clear()
    
    # API KEY
    ls.add("sk-1234567890123456", "src")
    assert len(ls.with_label(SECRET)) == 1

def test_plain_text_not_stored():
    ls = LabelStore()
    ls.add("Hello world", "src")
    assert len(ls.spans) == 0

def test_untrusted_flag():
    ls = LabelStore()
    ls.add("Untrusted info", "src", untrusted=True)
    assert len(ls.with_label(UNTRUSTED)) == 1

def test_phone_number_not_secret():
    ls = LabelStore()
    ls.add("9876543210", "src")
    assert len(ls.with_label(SECRET)) == 0

def test_with_label_and_clear():
    ls = LabelStore()
    ls.add("Secret data", "src", secret=True)
    ls.add("Untrusted data", "src", untrusted=True)
    assert len(ls.with_label(SECRET)) == 1
    assert len(ls.with_label(UNTRUSTED)) == 1
    ls.clear()
    assert len(ls.spans) == 0
