"""PII filter tests across NL, US, and UK patterns."""

import pytest

from trace_annotator.pii.filter import Locale, PIIFilter, PIIMode


@pytest.fixture
def nl():
    return PIIFilter(locales=frozenset({Locale.ANY, Locale.NL}))


@pytest.fixture
def us():
    return PIIFilter(locales=frozenset({Locale.ANY, Locale.US}))


@pytest.fixture
def uk():
    return PIIFilter(locales=frozenset({Locale.ANY, Locale.UK}))


@pytest.fixture
def all_locales():
    return PIIFilter(locales=frozenset({Locale.ANY, Locale.NL, Locale.US, Locale.UK}))


# --- Locale-agnostic ---------------------------------------------------------

class TestLocaleAgnostic:
    def test_email(self, nl):
        assert nl.scrub("Mail me at jane.doe@example.com please") == "Mail me at [email] please"

    def test_credit_card_valid_luhn(self, nl):
        # Known Luhn-valid test number
        assert "[credit_card]" in nl.scrub("Card: 4111 1111 1111 1111")

    def test_credit_card_invalid_luhn_not_scrubbed(self, nl):
        # Random non-Luhn 16 digits → not scrubbed
        out = nl.scrub("Not a card: 1234 5678 9012 3456")
        assert "[credit_card]" not in out


# --- Dutch -------------------------------------------------------------------

class TestDutch:
    def test_bsn_valid_11proof(self, nl):
        # 111222333 passes 11-proof: 9+16+7+12+10+8+9+6-3 = 74? Let's use known valid BSN
        # 123456782: 9+16+21+24+25+24+21+16-2 = 154, /11 = 14.0 ✓
        assert "[bsn]" in nl.scrub("BSN: 123456782")

    def test_bsn_invalid_11proof_not_scrubbed(self, nl):
        assert nl.scrub("ID: 123456789") == "ID: 123456789"

    def test_iban_nl_valid(self, nl):
        # NL91ABNA0417164300 is a canonical valid NL IBAN
        assert "[iban_nl]" in nl.scrub("IBAN: NL91ABNA0417164300")

    def test_phone_nl(self, nl):
        assert "[phone_nl]" in nl.scrub("Bel 06-12345678")
        assert "[phone_nl]" in nl.scrub("Of +31 20 1234567")

    def test_postcode_nl(self, nl):
        assert "[postcode_nl]" in nl.scrub("Adres: 1234 AB Amsterdam")
        assert "[postcode_nl]" in nl.scrub("Adres: 1234AB 42")

    def test_date_nl(self, nl):
        assert "[date_nl]" in nl.scrub("Geboren 15-03-1985")


# --- United States -----------------------------------------------------------

class TestUS:
    def test_ssn(self, us):
        assert "[ssn]" in us.scrub("SSN: 123-45-6789")

    def test_ssn_invalid_prefix_not_scrubbed(self, us):
        # 000-xx-xxxx and 666-xx-xxxx and 9xx-xx-xxxx are known invalid
        assert "[ssn]" not in us.scrub("Fake: 000-45-6789")
        assert "[ssn]" not in us.scrub("Fake: 666-45-6789")

    def test_ein(self, us):
        assert "[ein]" in us.scrub("EIN: 12-3456789")

    def test_phone_us_paren(self, us):
        assert "[phone_us]" in us.scrub("Call (555) 123-4567")

    def test_phone_us_plus1(self, us):
        assert "[phone_us]" in us.scrub("Call +1 555-123-4567")

    def test_zip_short(self, us):
        assert "[zip_us]" in us.scrub("ZIP 90210")

    def test_zip_plus4(self, us):
        assert "[zip_us]" in us.scrub("ZIP 90210-1234")

    def test_date_us(self, us):
        assert "[date_us]" in us.scrub("Born 03/15/1985")


# --- United Kingdom ----------------------------------------------------------

class TestUK:
    def test_ni_number(self, uk):
        # AB123456C is a well-formed NI number per HMRC spec
        assert "[ni_number]" in uk.scrub("NI: AB123456C")
        # With spacing: AB 12 34 56 C
        assert "[ni_number]" in uk.scrub("NI: AB 12 34 56 C")

    def test_ni_number_invalid_prefix_not_scrubbed(self, uk):
        # Q, D, F, I, U, V are excluded as the first letter of a valid NI prefix
        assert "[ni_number]" not in uk.scrub("NI: QQ123456C")

    def test_iban_uk(self, uk):
        # GB82WEST12345698765432 is the canonical valid UK IBAN
        assert "[iban_uk]" in uk.scrub("IBAN: GB82WEST12345698765432")

    def test_nhs_valid(self, uk):
        # 943 476 5919 is a canonical valid NHS test number
        assert "[nhs]" in uk.scrub("NHS: 943 476 5919")

    def test_nhs_invalid_not_scrubbed(self, uk):
        # Random 10 digits unlikely to pass mod-11
        assert "[nhs]" not in uk.scrub("Random: 123 456 7890")

    def test_phone_uk(self, uk):
        assert "[phone_uk]" in uk.scrub("Call 020 7946 0958")
        assert "[phone_uk]" in uk.scrub("Call +44 20 7946 0958")

    def test_postcode_uk_formats(self, uk):
        for pc in ["SW1A 1AA", "M1 1AE", "B33 8TH", "W1A 0AX", "EC1A 1BB"]:
            out = uk.scrub(f"Address: {pc}")
            assert "[postcode_uk]" in out, f"Failed on {pc}: {out}"


# --- Locale scoping ---------------------------------------------------------

class TestLocaleScoping:
    def test_nl_filter_ignores_ssn(self, nl):
        # NL-only filter should leave US SSN alone
        assert nl.scrub("SSN: 123-45-6789") == "SSN: 123-45-6789"

    def test_us_filter_ignores_bsn(self, us):
        assert us.scrub("BSN 123456782") == "BSN 123456782"

    def test_all_locales(self, all_locales):
        mixed = "Email a@b.com, BSN 123456782, SSN 123-45-6789, NHS 943 476 5919"
        out = all_locales.scrub(mixed)
        assert "[email]" in out
        assert "[bsn]" in out
        assert "[ssn]" in out
        assert "[nhs]" in out


# --- Modes -------------------------------------------------------------------

class TestModes:
    def test_off_mode(self):
        f = PIIFilter(mode=PIIMode.OFF, locales=frozenset({Locale.NL}))
        assert f.scrub("BSN 123456782 Phone 06-12345678") == "BSN 123456782 Phone 06-12345678"

    def test_lenient_mode_skips_medium(self):
        # Phone is "medium" confidence — lenient should leave it alone
        f = PIIFilter(mode=PIIMode.LENIENT, locales=frozenset({Locale.NL}))
        out = f.scrub("06-12345678")
        assert "[phone_nl]" not in out

    def test_strict_scrubs_both(self, nl):
        out = nl.scrub("Email a@b.com, phone 06-12345678")
        assert "[email]" in out
        assert "[phone_nl]" in out


# --- Replacement template ---------------------------------------------------

class TestReplacement:
    def test_single_token_replacement(self):
        f = PIIFilter(
            replacement="[REDACTED]",
            locales=frozenset({Locale.ANY, Locale.NL}),
        )
        assert f.scrub("Mail a@b.com") == "Mail [REDACTED]"

    def test_typed_replacement_default(self, nl):
        assert nl.scrub("Mail a@b.com") == "Mail [email]"
