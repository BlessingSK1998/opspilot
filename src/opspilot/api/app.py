"""FastAPI application factory. Routes are added milestone by milestone."""

from fastapi import FastAPI
from pydantic import BaseModel

from opspilot import __version__
from opspilot.logging_setup import configure_logging
from opspilot.settings import get_settings


class HealthResponse(BaseModel):
    status: str
    version: str
    llm_provider: str


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="OpsPilot API",
        version=__version__,
        description="AI operations assistant for Northwind Supply GmbH.",
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__, llm_provider=settings.llm_provider)

    return app


app = create_app()
