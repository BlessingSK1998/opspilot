"""Provider-agnostic LLM interface. Nodes depend on this protocol, never on a vendor SDK."""

from dataclasses import dataclass
from typing import Any, Protocol

from opspilot.schemas.enums import Category, DraftKind, Profile
from opspilot.schemas.extraction import CategoryExtraction
from opspilot.schemas.llm import ClassificationResult, DraftResult, RiskAssessment, Usage


@dataclass(frozen=True)
class LLMResult[T]:
    parsed: T
    usage: Usage


class LLMProvider(Protocol):
    name: str
    model: str

    def classify(
        self, email_text: str, profile: Profile = Profile.OPS
    ) -> LLMResult[ClassificationResult]: ...

    def extract(self, category: Category, email_text: str) -> LLMResult[CategoryExtraction]: ...

    def assess_risk(self, email_text: str) -> LLMResult[RiskAssessment]: ...

    def draft(self, kind: DraftKind, facts: dict[str, Any]) -> LLMResult[DraftResult]: ...
