"""Versioned prompt files. Prompts are never inline strings; every LLM call logs its version."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent
TONE_PATH = Path(__file__).resolve().parents[3] / "config" / "tone.md"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str  # e.g. "classify.v1"
    text: str


@lru_cache
def load_prompt(name: str) -> Prompt:
    """`load_prompt("classify")` loads the highest-versioned `classify.vN.md`."""
    candidates = sorted(
        (int(m.group(1)), p)
        for p in PROMPT_DIR.glob(f"{name}.v*.md")
        if (m := re.fullmatch(rf"{re.escape(name)}\.v(\d+)\.md", p.name))
    )
    if not candidates:
        raise FileNotFoundError(f"no prompt file for '{name}'")
    n, path = candidates[-1]
    text = path.read_text()
    if "{tone}" in text:
        text = text.replace("{tone}", TONE_PATH.read_text() if TONE_PATH.exists() else "")
    return Prompt(name=name, version=f"{name}.v{n}", text=text.strip())
