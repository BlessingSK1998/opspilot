import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_results_match_latest_eval_report() -> None:
    """The README quotes headline numbers; fail if someone re-runs eval and forgets the README."""
    latest = json.loads(
        Path(sorted(glob.glob(str(ROOT / "reports" / "eval_*.json")))[-1]).read_text()
    )
    readme = (ROOT / "README.md").read_text()
    c, e, m = latest["classification"], latest["escalation"], latest["missing_info"]
    assert f"{c['accuracy']:.1%} / {c['macro_f1']:.3f}" in readme
    assert f"{e['recall']:.1%}, {e['fn']} missed" in readme
    assert f"{e['precision']:.1%}" in readme
    assert f"{m['precision']:.1%} / {m['recall']:.1%}" in readme
    assert f"{latest['extraction_micro']['f1']:.3f}" in readme
    assert f"{latest['injection']['resisted']} / {latest['injection']['attempts']}" in readme


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
