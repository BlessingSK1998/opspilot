"""Node 4: LLM extraction into the category schema, with confidence + source span per field."""

import time
from typing import Any

from opspilot.nodes.common import Deps, finish
from opspilot.schemas.enums import JUNK_CATEGORIES
from opspilot.schemas.state import OpsState


def extract(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    assert state.classification is not None
    cat = state.classification.category
    if (
        cat in JUNK_CATEGORIES
    ):  # nothing worth extracting (and their schemas are empty, which strict structured outputs reject)
        return finish("extract", state, t0, f"{cat.value}: nothing to extract", {"fields": {}})
    res = deps.provider.extract(cat, state.safe_text)
    fields: dict[str, dict[str, Any]] = {}
    for name in type(res.parsed).model_fields:
        f = getattr(res.parsed, name)
        if f is not None and f.value is not None:
            fields[name] = {
                "value": f.value,
                "confidence": f.confidence,
                "source_span": f.source_span,
            }
    return finish(
        "extract",
        state,
        t0,
        f"{len(fields)} field(s): {', '.join(fields) or 'none'}",
        {"fields": fields},
        res.usage,
    )
