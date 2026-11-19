"""Thin HTTP client: the dashboard talks to the OpsPilot API only, never to the database."""

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx

BASE = os.environ.get("OPSPILOT_API_URL", "http://localhost:8000")
KEY = os.environ.get("OPSPILOT_API_KEY", "dev-key")


class ApiError(RuntimeError):
    pass


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, headers={"X-API-Key": KEY}, timeout=60.0)


def request(method: str, path: str, **kw: Any) -> Any:
    try:
        with _client() as c:
            r = c.request(method, path, **kw)
    except httpx.HTTPError as exc:
        raise ApiError(
            f"Cannot reach the OpsPilot API at {BASE} ({exc.__class__.__name__}). Is it running?"
        ) from exc
    if r.status_code >= 400:
        detail = (
            r.json().get("detail", r.text)
            if r.headers.get("content-type", "").startswith("application/json")
            else r.text
        )
        raise ApiError(f"{r.status_code}: {detail}")
    return r.json()


def get(path: str, **params: Any) -> Any:
    return request(
        "GET", path, params={k: v for k, v in params.items() if v not in (None, "", "All")}
    )


def post(path: str, body: dict[str, Any]) -> Any:
    return request("POST", path, json=body)


def stream_simulation(raw: dict[str, Any]) -> Iterator[dict[str, Any]]:
    try:
        with _client() as c, c.stream("POST", "/simulate/stream", json=raw) as r:
            if r.status_code >= 400:
                raise ApiError(f"{r.status_code}: {r.read().decode()}")
            for line in r.iter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])
    except httpx.HTTPError as exc:
        raise ApiError(f"Cannot reach the OpsPilot API at {BASE}.") from exc
