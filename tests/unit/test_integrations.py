import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_n8n_workflow_is_wired_consistently() -> None:
    wf = json.loads((ROOT / "integrations/n8n/opspilot_workflow.json").read_text())
    names = {n["name"] for n in wf["nodes"]}
    assert {n["id"] for n in wf["nodes"]} and len(names) == len(wf["nodes"])
    for src, conn in wf["connections"].items():
        assert src in names
        for branch in conn["main"]:
            assert all(t["node"] in names for t in branch)
    http = next(n for n in wf["nodes"] if n["type"].endswith("httpRequest"))
    assert http["parameters"]["url"].endswith("/ingest") and http["parameters"]["method"] == "POST"
    assert any(n["type"].endswith("emailReadImap") for n in wf["nodes"])  # trigger
    assert not re.search(r"(?i)password|secret|xoxb-", json.dumps(wf))  # no credentials in the repo


def test_compose_has_healthchecks_and_n8n_profile() -> None:
    text = (ROOT / "docker-compose.yml").read_text()
    assert text.count("healthcheck:") >= 4 and 'profiles: ["n8n"]' in text
    for svc in ("postgres:", "api:", "dashboard:", "n8n:"):
        assert svc in text


def test_env_example_documents_every_setting() -> None:
    from opspilot.settings import Settings

    example = (ROOT / ".env.example").read_text()
    for name, field in Settings.model_fields.items():
        env = (field.alias or name).upper()
        assert env in example, f"{env} missing from .env.example"
