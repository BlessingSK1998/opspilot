"""Heuristic prompt-injection detection. Detection only flags; the real defence is that all
email content is passed to the model as delimited data and every outcome is rule-checked."""

import re

PATTERNS: dict[str, re.Pattern[str]] = {
    "override_instructions": re.compile(
        r"(?i)\b(?:ignore|disregard|forget)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all)\b[^.\n]{0,30}\b(?:instructions?|rules?|everything)\b|forget everything above"
    ),
    "role_override": re.compile(
        r"(?i)system override|admin mode|you are now|developer mode|new instructions?:|this is an instruction from"
    ),
    "prompt_exfiltration": re.compile(
        r"(?i)reveal (?:your|the) (?:system )?prompt|print your (?:system )?prompt|show (?:me )?your instructions"
    ),
    "classification_steering": re.compile(
        r"(?i)(?:classify|mark|set|treat)\s+(?:this|it)\b[^.\n]{0,40}\b(?:as|to)\b[^.\n]{0,20}\b(?:spam|P[1-4]|resolved|urgent)\b|do not escalate|don't escalate"
    ),
    "data_exfiltration": re.compile(
        r"(?i)(?:reply|respond|send)\b[^.\n]{0,40}\b(?:customer list|all (?:customers|passwords|ibans)|full customer)"
    ),
}


def detect_injection(text: str) -> list[str]:
    return [name for name, pat in PATTERNS.items() if pat.search(text)]
