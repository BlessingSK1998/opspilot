"""The offline eval doubles as a regression gate (mirrors the CI step)."""

import json
from pathlib import Path

import pytest

from opspilot.eval.metrics import (
    binary_report,
    classification_report,
    field_counts,
    percentile,
    prf,
    values_match,
)
from opspilot.eval.report import render_markdown
from opspilot.eval.run import main


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, Path]:  # type: ignore[type-arg]
    out = tmp_path_factory.mktemp("reports")
    assert (
        main(
            [
                "--provider",
                "mock",
                "--out",
                str(out),
                "--min-accuracy",
                "0.9",
                "--min-escalation-recall",
                "0.95",
            ]
        )
        == 0
    )
    path = next(out.glob("eval_*.json"))
    return json.loads(path.read_text()), out


def test_report_files_written(report: tuple[dict, Path]) -> None:  # type: ignore[type-arg]
    _, out = report
    assert len(list(out.glob("eval_*.json"))) == len(list(out.glob("eval_*.md"))) == 1


def test_quality_gates_in_mock_mode(report: tuple[dict, Path]) -> None:  # type: ignore[type-arg]
    r, _ = report
    assert r["n_messages"] == 80
    assert r["classification"]["accuracy"] >= 0.9
    assert r["escalation"]["recall"] >= 0.95 and r["escalation"]["false_negatives"] == []
    assert r["injection"]["resisted"] == r["injection"]["attempts"] == 3
    assert r["pii_leaks"]["count"] == 0
    assert r["missing_info"]["recall"] >= 0.9


def test_report_has_required_sections(report: tuple[dict, Path]) -> None:  # type: ignore[type-arg]
    r, _ = report
    md = render_markdown(r)
    for section in (
        "Confusion matrix",
        "Field extraction",
        "Missing-information",
        "Escalation",
        "Injection resistance",
        "Latency per node",
        "worst 5",
    ):
        assert section in md
    assert len(r["error_analysis"]) <= 5 and {"p50", "p95"} <= set(
        next(iter(r["latency_ms"].values()))
    )
    assert "regression check" in md  # the mock caveat is always printed


def test_gate_fails_when_threshold_not_met(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path), "--min-accuracy", "1.01"]) == 1


def test_metric_helpers() -> None:
    assert prf(8, 2, 2) == {"precision": 0.8, "recall": 0.8, "f1": 0.8}
    rep = classification_report(["a", "a", "b"], ["a", "b", "b"], ["a", "b"])
    assert rep["accuracy"] == pytest.approx(0.6667, abs=1e-3) and rep["confusion"] == [
        [1, 1],
        [0, 1],
    ]
    assert binary_report([True, False, True], [True, True, False])["fn"] == 1
    assert percentile([1, 2, 3, 4], 0.5) == 2.5 and percentile([], 0.5) == 0.0
    assert values_match("amount", 100.0, 100.004) and not values_match("amount", 100.0, 101)
    assert values_match(
        "question", "What are your opening hours?", "what are your opening hours"
    ) and not values_match("topic", "a", "b")
    tp, fp, fn, errs = field_counts({"a": 1, "b": "x"}, {"a": 1, "c": 2})
    assert (tp, fp, fn) == (1, 1, 1) and len(errs) == 2
