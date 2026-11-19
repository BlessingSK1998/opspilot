"""Node 2: mask PII before any LLM sees the text; flag prompt injection."""

import time
from typing import Any

from opspilot.nodes.common import Deps, finish
from opspilot.schemas.state import OpsState
from opspilot.security.injection import detect_injection
from opspilot.security.pii import mask_pii


def sanitize(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    safe, mapping = mask_pii(state.email_text)
    flags = detect_injection(state.email_text)
    summary = f"masked {len(mapping)} PII item(s); injection flags: {flags or 'none'}"
    return finish(
        "sanitize",
        state,
        t0,
        summary,
        {"safe_text": safe, "pii_map": mapping, "injection_flags": flags},
    )
