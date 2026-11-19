import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from opspilot.db.seed_data import REQUIRED, generate


@pytest.fixture(scope="module")
def seed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("seed")
    generate(out)
    return out


def _load(seed: Path, name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((seed / "reference" / f"{name}.json").read_text())
    return data


def _gt(seed: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in (seed / "ground_truth.jsonl").read_text().splitlines()]


def test_reference_sizes(seed: Path) -> None:
    assert len(_load(seed, "customers")) == 40
    assert sum(c["vip"] for c in _load(seed, "customers")) == 5
    assert len(_load(seed, "products")) == 120
    assert len(_load(seed, "orders")) == 300
    assert len(_load(seed, "invoices")) == 200
    assert [p["priority"] for p in _load(seed, "sla_policies")] == ["P1", "P2", "P3", "P4"]


def test_reference_integrity(seed: Path) -> None:
    custs = {c["id"] for c in _load(seed, "customers")}
    skus = {p["sku"] for p in _load(seed, "products")}
    orders = {o["order_number"]: o for o in _load(seed, "orders")}
    assert len(orders) == 300
    for o in orders.values():
        assert o["customer_id"] in custs
        assert all(ln["sku"] in skus for ln in o["lines"])
    for inv in _load(seed, "invoices"):
        o = orders[inv["order_number"]]
        assert inv["customer_id"] == o["customer_id"]
        assert inv["amount"] == pytest.approx(o["total_net"] * 1.19, abs=0.01)
        assert re.fullmatch(r"INV-\d{4}-\d{5}", inv["invoice_number"])


def test_email_and_ground_truth_shape(seed: Path) -> None:
    gt = _gt(seed)
    assert len(gt) == 80 == len(list((seed / "emails").glob("*.json")))
    counts = Counter(g["category"] for g in gt)
    assert set(counts) == set(REQUIRED)
    assert counts["spam_or_irrelevant"] == 5
    assert sum(g["is_injection"] for g in gt) == 3
    assert sum(g["vip"] for g in gt) >= 5


def test_ground_truth_is_self_consistent(seed: Path) -> None:
    for g in _gt(seed):
        email = json.loads((seed / "emails" / f"{g['id']}.json").read_text())
        for a in email["attachments"]:
            assert (seed / "attachments" / a["filename"]).exists()
        assert g["should_escalate"] == bool(g["escalation_reasons"])
        assert set(g["missing_fields"]) <= set(g["required_fields"])
        # a required field is either present in the labelled fields or declared missing
        for f in g["required_fields"]:
            assert (f in g["fields"]) != (f in g["missing_fields"]), (g["id"], f)


def test_field_values_appear_in_source_text(seed: Path) -> None:
    """Typos must never corrupt a value we expect extraction to find."""
    for g in _gt(seed):
        email = json.loads((seed / "emails" / f"{g['id']}.json").read_text())
        if email["attachments"] or g["category"] in ("supplier_document", "order_request"):
            continue
        for key in ("invoice_number", "order_number", "company"):
            if key in g["fields"]:
                assert g["fields"][key] in email["body"], (g["id"], key)


def test_known_hard_cases_present(seed: Path) -> None:
    gt = _gt(seed)
    assert any("invoice_not_found" in g["validation_issues"] for g in gt)
    assert any("amount_mismatch" in g["validation_issues"] for g in gt)
    assert any(g["pii"]["iban"] for g in gt)
    assert any(g["secondary_category"] for g in gt)
    assert sum("unresolved_thread" in g["escalation_reasons"] for g in gt) >= 3


def test_generation_is_deterministic(tmp_path: Path, seed: Path) -> None:
    generate(tmp_path)
    assert (tmp_path / "ground_truth.jsonl").read_text() == (
        seed / "ground_truth.jsonl"
    ).read_text()
    pdfs = sorted(p.name for p in (seed / "attachments").glob("*.pdf"))
    assert pdfs
    assert (tmp_path / "attachments" / pdfs[0]).read_bytes() == (
        seed / "attachments" / pdfs[0]
    ).read_bytes()
