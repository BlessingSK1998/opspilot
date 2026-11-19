"""Structured outputs returned by the LLM layer."""

from pydantic import BaseModel, Field

from opspilot.schemas.enums import Category


class ClassificationResult(BaseModel):
    category: Category
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(description="One short sentence")


class RiskAssessment(BaseModel):
    """The LLM half of the hybrid priority decision. Rules decide; this only informs."""

    urgency: int = Field(ge=1, le=4, description="1 = critical ... 4 = routine")
    severity_signal: str = Field(description="low|medium|high")
    legal_language: bool
    rationale: str


class DraftResult(BaseModel):
    subject: str
    body: str


class Usage(BaseModel):
    model: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_eur: float = 0.0
    latency_ms: int = 0
