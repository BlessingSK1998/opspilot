import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _latest(provider: str, dataset: str = "ops") -> dict:  # type: ignore[type-arg]
    reports = [
        json.loads(Path(f).read_text())
        for f in sorted(glob.glob(str(ROOT / "reports" / "eval*_*.json")))
    ]
    return [r for r in reports if r["provider"] == provider and r.get("dataset", "ops") == dataset][
        -1
    ]  # type: ignore[no-any-return]


def test_readme_results_match_latest_eval_reports() -> None:
    """The README quotes headline numbers for both providers; fail if eval is re-run and README is not."""
    readme = (ROOT / "README.md").read_text()
    for provider in ("mock", "openai"):
        r = _latest(provider)
        c, e, m = r["classification"], r["escalation"], r["missing_info"]
        for needle in (
            f"{c['accuracy']:.1%} / {c['macro_f1']:.3f}",
            f"{m['precision']:.1%} / {m['recall']:.1%}",
            f"{r['extraction_micro']['f1']:.3f}",
            f"{r['tokens_per_message']:.0f}",
        ):
            assert needle in readme, (provider, needle)
        assert (
            f"{e['precision']:.1%}" in readme and f"{e['recall']:.1%}, {e['fn']} missed" in readme
        )


def test_readme_personal_results_match_latest_personal_reports() -> None:
    readme = (ROOT / "README.md").read_text()
    for provider in ("mock", "openai"):
        r = _latest(provider, "personal")
        c, e = r["classification"], r["escalation"]
        for needle in (
            f"{c['accuracy']:.1%} / {c['macro_f1']:.3f}",
            f"{r['outcome']['accuracy']:.1%}",
            f"{e['recall']:.1%} / {e['precision']:.1%}",
            f"{r['extraction_micro']['f1']:.3f}",
            f"{r['tokens_per_message']:.0f}",
        ):
            assert needle in readme, (provider, needle)


def test_docs_exist_and_cover_required_sections() -> None:
    pm = (ROOT / "docs/PROCESS_MAP.md").read_text()
    for s in ("As-is", "To-be", "RACI", "KPI definitions"):
        assert s in pm
    readme = (ROOT / "README.md").read_text()
    for s in (
        "The business problem",
        "The outcome",
        "Quickstart",
        "Key design decisions",
        "Limitations and roadmap",
        "What this demonstrates",
    ):
        assert s in readme
    assert readme.count("```mermaid") >= 2
