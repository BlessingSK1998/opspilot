"""Node 3: LLM classification (structured output), constrained to the mailbox profile's categories."""

import time
from typing import Any

from opspilot.nodes.common import Deps, finish
from opspilot.schemas.enums import CATEGORIES_BY_PROFILE, Category, Profile
from opspilot.schemas.llm import ClassificationResult
from opspilot.schemas.state import OpsState

FALLBACK = {Profile.OPS: Category.GENERAL_INQUIRY, Profile.PERSONAL: Category.PERSONAL_MESSAGE}
OUT_OF_PROFILE_CONFIDENCE = 0.5


def classify(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    res = deps.provider.classify(state.safe_text, state.profile)
    c = res.parsed
    if c.category not in CATEGORIES_BY_PROFILE[state.profile]:
        # The model picked a category that does not exist for this mailbox: do not trust it, send to a human.
        c = ClassificationResult(
            category=FALLBACK[state.profile], confidence=min(c.confidence, OUT_OF_PROFILE_CONFIDENCE),
            rationale=f"Model chose '{c.category.value}', which is not a {state.profile.value}-profile category.",
        )  # fmt: skip
    return finish(
        "classify",
        state,
        t0,
        f"{c.category.value} ({c.confidence:.2f}): {c.rationale}",
        {"classification": c},
        res.usage,
    )
