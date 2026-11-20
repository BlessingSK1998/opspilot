"""OpenAI implementation using Structured Outputs (`chat.completions.parse`)."""

import json
import logging
import random
import time
from typing import Any

import openai
from openai import OpenAI
from pydantic import BaseModel

from opspilot.llm.base import LLMResult, LLMUnavailableError
from opspilot.llm.pricing import cost_eur
from opspilot.prompts import load_prompt
from opspilot.schemas.enums import Category, DraftKind, Profile
from opspilot.schemas.extraction import SCHEMAS, CategoryExtraction
from opspilot.schemas.llm import ClassificationResult, DraftResult, RiskAssessment, Usage

log = logging.getLogger(__name__)

RETRYABLE = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


def _is_quota_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return (
        code == "insufficient_quota"
        or "no credits" in str(exc).lower()
        or "insufficient_quota" in str(exc)
    )


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        max_retries: int = 4,
        client: Any | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self.model = model
        self.max_retries = max_retries
        self._sleep = sleep
        self._client: Any = client or OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    # ---- core call ------------------------------------------------------
    def _call[M: BaseModel](
        self,
        prompt_name: str,
        user: str,
        model_cls: type[M],
        temperature: float,
        system_extra: str = "",
    ) -> LLMResult[M]:
        prompt = load_prompt(prompt_name)
        messages = [
            {"role": "system", "content": prompt.text + system_extra},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": model_cls,
        }
        if not self.model.startswith(
            ("gpt-5", "o1", "o3", "o4")
        ):  # reasoning models reject temperature
            kwargs["temperature"] = temperature
        start = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.chat.completions.parse(**kwargs)
                break
            except openai.AuthenticationError as exc:
                raise LLMUnavailableError(
                    "OpenAI rejected the API key (check OPENAI_API_KEY)"
                ) from exc
            except RETRYABLE as exc:
                if _is_quota_error(
                    exc
                ):  # permanent until billing is fixed: do not burn retries on it
                    raise LLMUnavailableError(
                        "The OpenAI account has no credits left. Add credits at "
                        "https://platform.openai.com/settings/organization/billing"
                    ) from exc
                if attempt == self.max_retries:
                    raise
                delay = min(2**attempt, 20) + random.random() * 0.25
                log.warning(
                    "openai retry %d after %s (%.1fs)", attempt + 1, type(exc).__name__, delay
                )
                self._sleep(delay)
        msg = resp.choices[0].message
        if msg.parsed is None:
            raise ValueError(
                f"model returned no parsed output (refusal={getattr(msg, 'refusal', None)})"
            )
        tin, tout = resp.usage.prompt_tokens, resp.usage.completion_tokens
        usage = Usage(
            model=self.model,
            prompt_version=prompt.version,
            tokens_in=tin,
            tokens_out=tout,
            cost_eur=cost_eur(self.model, tin, tout),
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        return LLMResult(msg.parsed, usage)

    # ---- tasks ----------------------------------------------------------
    def classify(
        self, email_text: str, profile: Profile = Profile.OPS
    ) -> LLMResult[ClassificationResult]:
        name = "classify_personal" if profile is Profile.PERSONAL else "classify"
        return self._call(name, f"<email>\n{email_text}\n</email>", ClassificationResult, 0.0)

    def extract(self, category: Category, email_text: str) -> LLMResult[CategoryExtraction]:
        cls = SCHEMAS[category]
        return self._call(
            "extract", f"Category: {category.value}\n<email>\n{email_text}\n</email>", cls, 0.0
        )

    def assess_risk(self, email_text: str) -> LLMResult[RiskAssessment]:
        return self._call("risk", f"<email>\n{email_text}\n</email>", RiskAssessment, 0.0)

    def draft(self, kind: DraftKind, facts: dict[str, Any]) -> LLMResult[DraftResult]:
        name = "draft_response" if kind is DraftKind.RESPONSE else "draft_info_request"
        if facts.get("profile") == Profile.PERSONAL.value:
            name = "draft_personal"
        user = "Facts (JSON):\n" + json.dumps(facts, ensure_ascii=False, default=str)
        return self._call(name, user, DraftResult, 0.3)
