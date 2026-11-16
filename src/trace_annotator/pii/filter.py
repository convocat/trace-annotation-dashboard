"""PII regex filter — Dutch, US English, British English.

Deterministic, offline, auditable — no LLM in the loop.

Each pattern is tagged with:
  - the locales it applies to (nl / us / uk / "any")
  - a confidence level (high / medium)

Confidence drives what gets scrubbed in LENIENT mode (high only) vs. STRICT (all).
Locale scoping lets a project opt in to only the pattern sets relevant to its data.

Known limitations:
  - Does not catch names (ambiguous without context).
  - Does not catch rare / context-dependent identifiers.

Pair with Langfuse's ingest-time PII filter for defence-in-depth. This module runs
at render time inside the dashboard as the second line of defence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Pattern


class PIIMode(str, Enum):
    STRICT = "strict"    # scrub everything matched for the active locales
    LENIENT = "lenient"  # scrub only high-confidence patterns
    OFF = "off"          # no filtering


class Locale(str, Enum):
    NL = "nl"   # Dutch
    US = "us"   # US English
    UK = "uk"   # British English
    ANY = "any" # locale-agnostic (email, credit card)


# --- Patterns ---------------------------------------------------------------
#
# Structure: name → (compiled regex, confidence, locales, optional validator)
# `validator(match_text) -> bool`: if present, must return True for the match to be scrubbed.

_PATTERNS: dict[str, tuple[Pattern[str], str, frozenset[Locale], object]] = {
    # ============ Locale-agnostic ============

    "email": (
        re.compile(r"\b[\w.\-+]+@[\w\-]+\.[\w.\-]+\b"),
        "high",
        frozenset({Locale.ANY}),
        None,
    ),

    # 13-19 digit numbers with optional spaces/dashes — validated via Luhn
    "credit_card": (
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        "high",
        frozenset({Locale.ANY}),
        "luhn",
    ),

    # ============ Dutch (NL) ============

    # BSN: 9 standalone digits + 11-proof
    "bsn": (
        re.compile(r"(?<!\d)\d{9}(?!\d)"),
        "high",
        frozenset({Locale.NL}),
        "bsn_11proof",
    ),

    # Dutch IBAN: NL + 2 check digits + 4 bank letters + 10 digits, mod-97 verified
    "iban_nl": (
        re.compile(r"\bNL\d{2}[A-Z]{4}\d{10}\b", re.IGNORECASE),
        "high",
        frozenset({Locale.NL}),
        "iban_mod97",
    ),

    # Dutch phone: +31 or 0 prefix, 9 digits
    "phone_nl": (
        re.compile(
            r"(?<!\d)(?:\+31[\s-]?|0)(?:[1-9][\s-]?)(?:\d[\s-]?){7}\d(?!\d)"
        ),
        "medium",
        frozenset({Locale.NL}),
        None,
    ),

    # Dutch postcode (1234 AB), optionally followed by house number
    "postcode_nl": (
        re.compile(r"\b\d{4}\s?[A-Z]{2}(?:\s+\d+[a-zA-Z]?)?\b"),
        "medium",
        frozenset({Locale.NL}),
        None,
    ),

    # Dutch-style date dd-mm-yyyy or dd/mm/yyyy (day first)
    "date_nl": (
        re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[-/](?:0?[1-9]|1[0-2])[-/](?:19|20)\d{2}\b"),
        "medium",
        frozenset({Locale.NL}),
        None,
    ),

    # ============ United States (US) ============

    # SSN: XXX-XX-XXXX, excludes known invalid ranges
    "ssn": (
        re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
        "high",
        frozenset({Locale.US}),
        None,
    ),

    # EIN: XX-XXXXXXX
    "ein": (
        re.compile(r"\b\d{2}-\d{7}\b"),
        "medium",
        frozenset({Locale.US}),
        None,
    ),

    # US phone: optional +1 or (###), 10 digits total, common formats
    "phone_us": (
        re.compile(
            r"(?<!\d)"
            r"(?:\+?1[\s.\-]?)?"
            r"(?:\(\d{3}\)|\d{3})[\s.\-]?"
            r"\d{3}[\s.\-]?"
            r"\d{4}"
            r"(?!\d)"
        ),
        "medium",
        frozenset({Locale.US}),
        None,
    ),

    # ZIP code: 5 digits or 5+4
    "zip_us": (
        re.compile(r"\b\d{5}(?:-\d{4})?\b"),
        "medium",
        frozenset({Locale.US}),
        None,
    ),

    # US-style date mm/dd/yyyy (month first) — overlaps with dd/mm but tagged separately
    "date_us": (
        re.compile(r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:19|20)\d{2}\b"),
        "medium",
        frozenset({Locale.US}),
        None,
    ),

    # ============ United Kingdom (UK) ============

    # National Insurance: AB 123456 C (prefix excludes certain letters per HMRC spec,
    # but regex here is permissive; full validation would need a prefix lookup table)
    "ni_number": (
        re.compile(
            r"\b[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]"
            r"\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b",
            re.IGNORECASE,
        ),
        "high",
        frozenset({Locale.UK}),
        None,
    ),

    # UK IBAN: GB + 2 check + 4 letters + 14 digits, mod-97 verified
    "iban_uk": (
        re.compile(r"\bGB\d{2}[A-Z]{4}\d{14}\b", re.IGNORECASE),
        "high",
        frozenset({Locale.UK}),
        "iban_mod97",
    ),

    # NHS number: 10 digits, often grouped 3-3-4, mod-11 check
    "nhs": (
        re.compile(r"\b\d{3}[\s-]?\d{3}[\s-]?\d{4}\b"),
        "high",
        frozenset({Locale.UK}),
        "nhs_mod11",
    ),

    # UK phone: +44 or 0 prefix, 10 digits after the leading digit
    "phone_uk": (
        re.compile(
            r"(?<!\d)"
            r"(?:\+44[\s-]?|0)"
            r"(?:\d[\s-]?){9,10}\d"
            r"(?!\d)"
        ),
        "medium",
        frozenset({Locale.UK}),
        None,
    ),

    # UK postcode — covers all standard formats (SW1A 1AA, M1 1AE, B33 8TH, EC1A 1BB, etc.)
    # See https://en.wikipedia.org/wiki/Postcodes_in_the_United_Kingdom#Validation
    "postcode_uk": (
        re.compile(
            r"\b(?:GIR\s?0AA|"
            r"[A-PR-UWYZ](?:[0-9]{1,2}"
            r"|[A-HK-Y][0-9]{1,2}"
            r"|[0-9][A-HJKPS-UW]"
            r"|[A-HK-Y][0-9][ABEHMNPRV-Y])"
            r"\s?[0-9][ABD-HJLNP-UW-Z]{2})\b",
            re.IGNORECASE,
        ),
        "high",
        frozenset({Locale.UK}),
        None,
    ),
}


# --- Validators -------------------------------------------------------------

def _bsn_11proof(bsn: str) -> bool:
    """Dutch BSN 11-proof checksum. 9 digits, weighted sum mod 11 must be 0."""
    if len(bsn) != 9 or not bsn.isdigit():
        return False
    weights = [9, 8, 7, 6, 5, 4, 3, 2, -1]
    return sum(int(d) * w for d, w in zip(bsn, weights)) % 11 == 0


def _iban_mod97(iban: str) -> bool:
    """Mod-97 IBAN checksum, works for any country."""
    iban = re.sub(r"\s", "", iban).upper()
    if len(iban) < 15 or not iban[:2].isalpha():
        return False
    rearranged = iban[4:] + iban[:4]
    try:
        numeric = "".join(str(int(c, 36)) for c in rearranged)
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def _luhn(number: str) -> bool:
    """Luhn checksum for credit-card-like numbers."""
    digits = [int(c) for c in re.sub(r"\D", "", number)]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _nhs_mod11(nhs: str) -> bool:
    """NHS number mod-11 check. 10 digits; weighted sum mod 11 must be 0 (or 11)."""
    digits = re.sub(r"\D", "", nhs)
    if len(digits) != 10:
        return False
    weights = [10, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    check = (11 - (total % 11)) % 11
    return check != 10 and check == int(digits[9])


_VALIDATORS = {
    "bsn_11proof": _bsn_11proof,
    "iban_mod97": _iban_mod97,
    "luhn": _luhn,
    "nhs_mod11": _nhs_mod11,
}


# --- Public API -------------------------------------------------------------

@dataclass
class PIIFilter:
    """Configurable PII scrubber.

    Usage:
        f = PIIFilter(locales={Locale.NL, Locale.US})
        clean = f.scrub("Call 020-1234567 or 555-123-4567, email a@b.nl")
    """

    mode: PIIMode = PIIMode.STRICT
    locales: frozenset[Locale] = field(default_factory=lambda: frozenset({Locale.ANY, Locale.NL}))
    """Which locale pattern sets to apply. Always keep Locale.ANY for email + credit card."""

    replacement: str = "[{type}]"
    """Replacement template. `{type}` becomes the pattern name (bsn, email, ssn, ...)."""

    enabled_patterns: frozenset[str] | None = None
    """If set, only these pattern names are applied, overriding locale defaults."""

    def scrub(self, text: str) -> str:
        if self.mode == PIIMode.OFF or not text:
            return text

        for name in self._active_patterns():
            pattern, _conf, _locales, validator = _PATTERNS[name]
            if validator is None:
                text = pattern.sub(self._replace(name), text)
            else:
                check = _VALIDATORS[validator]
                text = pattern.sub(
                    lambda m, n=name, chk=check: self._replace(n) if chk(m.group(0)) else m.group(0),
                    text,
                )
        return text

    def _active_patterns(self) -> list[str]:
        if self.enabled_patterns is not None:
            names = [p for p in _PATTERNS if p in self.enabled_patterns]
        else:
            names = [
                name for name, (_p, _conf, locales, _v) in _PATTERNS.items()
                if locales & self.locales
            ]
            if self.mode == PIIMode.LENIENT:
                names = [n for n in names if _PATTERNS[n][1] == "high"]

        # Run validated patterns first — a mod-11 NHS number must not be eaten by a
        # loose phone regex, and a Luhn-valid credit card must not be eaten by SSN.
        return sorted(names, key=lambda n: (_PATTERNS[n][3] is None, n))

    def _replace(self, pattern_name: str) -> str:
        return self.replacement.format(type=pattern_name)


# --- Convenience ------------------------------------------------------------

_DEFAULT = PIIFilter()

def scrub(text: str) -> str:
    """Scrub with default settings (strict mode, NL + locale-agnostic patterns)."""
    return _DEFAULT.scrub(text)
