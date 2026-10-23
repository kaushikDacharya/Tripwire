"""Tests for detect.secrets — secret detection with checksum validation."""

import pytest
from detect.secrets import (
    detect_secrets, verhoeff_ok, luhn_ok, make_aadhaar,
)


# ═══════════════════════════════════════════════════════════════════════
#  Checksum validators
# ═══════════════════════════════════════════════════════════════════════

class TestVerhoeff:
    def test_valid(self):
        assert verhoeff_ok("2363") is True

    def test_invalid(self):
        assert verhoeff_ok("2364") is False

    def test_generated_aadhaar(self):
        num = make_aadhaar("23456789012")
        assert num == "234567890124"
        assert verhoeff_ok(num) is True

    def test_generated_short(self):
        num = make_aadhaar("236")
        assert num == "2363"
        assert verhoeff_ok(num) is True


class TestLuhn:
    def test_valid_card(self):
        assert luhn_ok("4539578763621486") is True

    def test_invalid_card(self):
        assert luhn_ok("4539578763621487") is False

    def test_valid_short(self):
        # Visa test number
        assert luhn_ok("4111111111111111") is True

    def test_mastercard(self):
        assert luhn_ok("5500000000000004") is True


# ═══════════════════════════════════════════════════════════════════════
#  PAN detection
# ═══════════════════════════════════════════════════════════════════════

class TestPAN:
    def test_valid_pan_personal(self):
        results = detect_secrets("My PAN is ABCPD1234E")
        pans = [f for f in results if f.type == "PAN"]
        assert len(pans) == 1
        assert pans[0].confidence == "high"

    def test_valid_pan_company(self):
        results = detect_secrets("Company PAN: AABCC5678D")
        pans = [f for f in results if f.type == "PAN"]
        assert len(pans) == 1

    def test_invalid_pan_wrong_4th_letter(self):
        # 4th letter 'D' is not in the valid set
        results = detect_secrets("Wrong PAN: ABCDD1234E")
        pans = [f for f in results if f.type == "PAN"]
        assert len(pans) == 0

    def test_pan_not_in_word(self):
        # Should not match PAN inside a longer word
        results = detect_secrets("XABCPD1234EY")
        pans = [f for f in results if f.type == "PAN"]
        assert len(pans) == 0

    def test_no_false_positive_random_letters(self):
        results = detect_secrets("HELLOWORLD")
        pans = [f for f in results if f.type == "PAN"]
        assert len(pans) == 0


# ═══════════════════════════════════════════════════════════════════════
#  Aadhaar detection
# ═══════════════════════════════════════════════════════════════════════

class TestAadhaar:
    def test_valid_aadhaar_with_context(self):
        valid = make_aadhaar("23456789012")  # "234567890124"
        text = f"My aadhaar number is {valid}"
        results = detect_secrets(text)
        aadhaars = [f for f in results if f.type == "AADHAAR"]
        assert len(aadhaars) == 1
        assert aadhaars[0].confidence == "high"  # context keyword present

    def test_valid_aadhaar_no_context(self):
        valid = make_aadhaar("98765432101")
        text = f"Number: {valid}"
        results = detect_secrets(text)
        aadhaars = [f for f in results if f.type == "AADHAAR"]
        assert len(aadhaars) == 1
        assert aadhaars[0].confidence == "medium"  # no context

    def test_valid_aadhaar_spaced(self):
        valid = make_aadhaar("23456789012")  # "234567890124"
        spaced = f"{valid[:4]} {valid[4:8]} {valid[8:]}"
        text = f"Aadhaar: {spaced}"
        results = detect_secrets(text)
        aadhaars = [f for f in results if f.type == "AADHAAR"]
        assert len(aadhaars) == 1

    def test_invalid_aadhaar_checksum(self):
        # Change last digit to break checksum
        valid = make_aadhaar("23456789012")
        broken = valid[:-1] + str((int(valid[-1]) + 1) % 10)
        text = f"Aadhaar: {broken}"
        results = detect_secrets(text)
        aadhaars = [f for f in results if f.type == "AADHAAR"]
        assert len(aadhaars) == 0

    def test_first_digit_0_or_1_rejected(self):
        text = "Number: 012345678901"
        results = detect_secrets(text)
        aadhaars = [f for f in results if f.type == "AADHAAR"]
        assert len(aadhaars) == 0


# ═══════════════════════════════════════════════════════════════════════
#  Card detection
# ═══════════════════════════════════════════════════════════════════════

class TestCards:
    def test_valid_visa(self):
        results = detect_secrets("Card: 4539578763621486")
        cards = [f for f in results if f.type == "CARD"]
        assert len(cards) == 1

    def test_valid_card_with_spaces(self):
        results = detect_secrets("Card: 4539 5787 6362 1486")
        cards = [f for f in results if f.type == "CARD"]
        assert len(cards) == 1

    def test_valid_card_with_dashes(self):
        results = detect_secrets("Card: 4539-5787-6362-1486")
        cards = [f for f in results if f.type == "CARD"]
        assert len(cards) == 1

    def test_invalid_card_luhn(self):
        results = detect_secrets("Card: 4539578763621487")
        cards = [f for f in results if f.type == "CARD"]
        assert len(cards) == 0

    def test_no_false_on_short_number(self):
        results = detect_secrets("Order: 12345")
        cards = [f for f in results if f.type == "CARD"]
        assert len(cards) == 0


# ═══════════════════════════════════════════════════════════════════════
#  IFSC / UPI / Phone / Email / API key / Password
# ═══════════════════════════════════════════════════════════════════════

class TestIFSC:
    def test_valid_ifsc(self):
        results = detect_secrets("IFSC: SBIN0001234")
        ifscs = [f for f in results if f.type == "IFSC"]
        assert len(ifscs) == 1

    def test_invalid_ifsc_wrong_5th(self):
        results = detect_secrets("Code: SBIN1001234")
        ifscs = [f for f in results if f.type == "IFSC"]
        assert len(ifscs) == 0


class TestUPI:
    def test_valid_upi(self):
        results = detect_secrets("Pay to user@ybl")
        upis = [f for f in results if f.type == "UPI_ID"]
        assert len(upis) == 1

    def test_valid_upi_paytm(self):
        results = detect_secrets("UPI: kaushik@paytm")
        upis = [f for f in results if f.type == "UPI_ID"]
        assert len(upis) == 1


class TestPhone:
    def test_valid_indian_phone(self):
        results = detect_secrets("Call me at 9876543210")
        phones = [f for f in results if f.type == "PHONE"]
        assert len(phones) == 1

    def test_valid_with_country_code(self):
        results = detect_secrets("Phone: +91-9876543210")
        phones = [f for f in results if f.type == "PHONE"]
        assert len(phones) == 1

    def test_invalid_starts_with_5(self):
        results = detect_secrets("Number: 5234567890")
        phones = [f for f in results if f.type == "PHONE"]
        assert len(phones) == 0


class TestEmail:
    def test_valid_email(self):
        results = detect_secrets("Email: user@example.com")
        emails = [f for f in results if f.type == "EMAIL"]
        assert len(emails) == 1
        assert "***" in emails[0].value_masked


class TestAPIKey:
    def test_aws_key(self):
        results = detect_secrets("Key: AKIAIOSFODNN7EXAMPLE")
        keys = [f for f in results if f.type == "API_KEY"]
        assert len(keys) == 1

    def test_openai_key(self):
        results = detect_secrets("api_key: sk-abcdefghijklmnopqrstuvwxyz12345")
        keys = [f for f in results if f.type == "API_KEY"]
        assert len(keys) >= 1

    def test_github_pat(self):
        results = detect_secrets("Token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij1234")
        keys = [f for f in results if f.type == "API_KEY"]
        assert len(keys) == 1

    def test_generic_hex_key(self):
        results = detect_secrets("api_key = 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2'")
        keys = [f for f in results if f.type == "API_KEY"]
        assert len(keys) >= 1


class TestPassword:
    def test_password_colon(self):
        results = detect_secrets("password: mysecretpass123")
        pwds = [f for f in results if f.type == "PASSWORD"]
        assert len(pwds) == 1

    def test_pwd_equals(self):
        results = detect_secrets("pwd=hunter2")
        pwds = [f for f in results if f.type == "PASSWORD"]
        assert len(pwds) == 1


# ═══════════════════════════════════════════════════════════════════════
#  Masking
# ═══════════════════════════════════════════════════════════════════════

class TestMasking:
    def test_aadhaar_masked(self):
        valid = make_aadhaar("23456789012")
        results = detect_secrets(f"Aadhaar: {valid}")
        aadhaars = [f for f in results if f.type == "AADHAAR"]
        assert len(aadhaars) == 1
        assert valid not in aadhaars[0].value_masked
        assert aadhaars[0].value_masked.startswith("XXXX")

    def test_pan_masked(self):
        results = detect_secrets("PAN: ABCPD1234E")
        pans = [f for f in results if f.type == "PAN"]
        assert "ABCPD1234E" not in pans[0].value_masked
