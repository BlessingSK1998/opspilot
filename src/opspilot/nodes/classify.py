"""Node 3: LLM classification (structured output)."""

import time
from typing import Any

from opspilot.nodes.common import Deps, finish
from opspilot.schemas.state import OpsState


def classify(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    res = deps.provider.classify(state.safe_text)
    c = res.parsed
    return finish(
        "classify",
        state,
        t0,
        f"{c.category.value} ({c.confidence:.2f}): {c.rationale}",
        {"classification": c},
        res.usage,
    )
