"""Reversible PII masking applied before any text reaches an LLM."""

import re

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?\d{4}){4}(?:[ ]?\d{1,2})?\b|\bDE\d{20}\b")
PHONE_RE = re.compile(r"(?<![\w-])\+\d{1,3}(?:[ ./-]?\(?\d{1,5}\)?){2,6}(?!\d)")
PERSONAL_DOMAINS = r"(?:gmail|googlemail|gmx|web|yahoo|outlook|hotmail|icloud|t-online|freenet|protonmail)\.(?:com|de|net|at|ch)"
PERSONAL_EMAIL_RE = re.compile(rf"\b[\w.+-]+@{PERSONAL_DOMAINS}\b", re.I)

_PATTERNS = (("IBAN", IBAN_RE), ("PHONE", PHONE_RE), ("EMAIL", PERSONAL_EMAIL_RE))


def mask_pii(text: str) -> tuple[str, dict[str, str]]:
    """Replace IBANs, phone numbers and personal e-mails with `[KIND_n]`; return (text, mapping)."""
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}
    for kind, pattern in _PATTERNS:

        def repl(m: re.Match[str], kind: str = kind) -> str:
            original = m.group(0)
            for token, val in mapping.items():
                if val == original:
                    return token
            counters[kind] = counters.get(kind, 0) + 1
            token = f"[{kind}_{counters[kind]}]"
            mapping[token] = original
            return token

        text = pattern.sub(repl, text)
    return text, mapping


def unmask(text: str, mapping: dict[str, str]) -> str:
    for token, original in mapping.items():
        text = text.replace(token, original)
    return text
