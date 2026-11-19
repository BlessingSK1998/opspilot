"""LLM layer: provider protocol, OpenAI + mock implementations, factory."""

from opspilot.llm.base import LLMProvider, LLMResult
from opspilot.llm.mock_provider import MockProvider
from opspilot.llm.openai_provider import OpenAIProvider
from opspilot.settings import Settings, get_settings


def get_provider(settings: Settings | None = None, force: str | None = None) -> LLMProvider:
    """OpenAI when a key is configured (or forced), otherwise the offline mock."""
    s = settings or get_settings()
    choice = force or s.llm_provider
    if choice == "openai":
        if s.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY is required for the openai provider")
        return OpenAIProvider(
            s.openai_api_key.get_secret_value(),
            s.openai_model,
            s.llm_timeout_seconds,
            s.llm_max_retries,
        )
    return MockProvider()


__all__ = ["LLMProvider", "LLMResult", "MockProvider", "OpenAIProvider", "get_provider"]
