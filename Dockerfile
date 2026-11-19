FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY alembic ./alembic
COPY config ./config
COPY data ./data
COPY dashboard ./dashboard
COPY .streamlit ./.streamlit
COPY reports ./reports
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000 8501
CMD ["sh", "-c", "python -m opspilot.db.seed && python -m opspilot.demo_load --if-empty && uvicorn opspilot.api.app:create_app --factory --host 0.0.0.0 --port 8000"]
