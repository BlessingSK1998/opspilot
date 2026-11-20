"""Application configuration, loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every variable is documented in `.env.example`."""

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", extra="ignore", populate_by_name=True
    )

    database_url: str = "postgresql+psycopg://opspilot:opspilot@localhost:5432/opspilot"
    api_key: SecretStr = Field(default=SecretStr("dev-key"), alias="OPSPILOT_API_KEY")
    api_url: str = Field(default="http://127.0.0.1:8000", alias="OPSPILOT_API_URL")

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 4

    # Name used to sign drafts in the personal profile (leave empty for a generic sign-off).
    owner_name: str | None = Field(default=None, alias="OPSPILOT_OWNER_NAME")

    # Mailbox sync (read-only IMAP). Leave IMAP_USER / IMAP_PASSWORD empty to disable.
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str | None = None
    imap_password: SecretStr | None = None
    imap_folder: str = "INBOX"
    imap_profile: Literal["ops", "personal"] = "personal"
    imap_since_days: int = 14
    imap_max_per_run: int = 50
    sync_interval_seconds: int = 120
    sync_state_path: str = ".opspilot-sync.json"

    slack_webhook_url: str | None = None
    langsmith_tracing: bool = False

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @property
    def llm_provider(self) -> Literal["openai", "mock"]:
        """Real model only when a key is present; otherwise the offline mock."""
        return "openai" if self.openai_api_key else "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
