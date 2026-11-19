"""`make eval`: run every seed email through the real graph and score against ground truth.

python -m opspilot.eval.run [--provider mock|openai] [--min-accuracy 0.9] [--out reports]
"""

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from opspilot.eval.metrics import (
    binary_report,
    classification_report,
    field_counts,
    percentile,
    prf,
)
from opspilot.eval.report import render_markdown
from opspilot.graph.serde import make_serde
from opspilot.llm import get_provider
from opspilot.nodes.common import Deps
from opspilot.runner import Pipeline, RunResult
from opspilot.schemas.enums import Category, RunStatus
from opspilot.schemas.state import OpsState
from opspilot.settings import Settings
from opspilot.tools.reference import MemoryReference
from opspilot.tools.sink import Backend, MemorySink

SEED = Path("data/seed")
LABELS = [c.value for c in Category]
REASONS = [
    "amount_over_5000",
    "legal_language",
    "high_severity_complaint",
    "vip_customer",
    "prompt_injection",
    "unresolved_thread",
]


@dataclass
class Case:
    gt: dict[str, Any]
    result: RunResult

    @property
    def state(self) -> OpsState:
        return self.result.state


def run_cases(
    provider_name: str, base: Path = SEED, workers: int = 1, settings: Settings | None = None
) -> list[Case]:
    from opspilot.emailio import raw_from_seed_json

    gts = [json.loads(ln) for ln in (base / "ground_truth.jsonl").read_text().splitlines()]
    provider = get_provider(settings or Settings(), force=provider_name)
    sink = MemorySink()
    pipe = Pipeline(
        Deps(provider, Backend(MemoryReference(base), sink)), InMemorySaver(serde=make_serde())
    )

    def one(gt: dict[str, Any]) -> Case:
        raw = raw_from_seed_json(base / "emails" / f"{gt['id']}.json", base / "attachments")
        return Case(gt, pipe.start(raw))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, gts))


def predicted_escalation(c: Case) -> bool:
    return c.result.status is RunStatus.INTERRUPTED


def rule_escalation(c: Case) -> bool:
    return bool(set(c.state.escalation_reasons) - {"low_confidence"})


def score(cases: list[Case], provider: str, model: str) -> dict[str, Any]:
    n = len(cases)
    cls = classification_report(
        [c.gt["category"] for c in cases],
        [c.state.category.value if c.state.category else "general_inquiry" for c in cases],
        LABELS,
    )

    # extraction (per GT category; a misclassified email scores all its fields as missed)
    ext: dict[str, dict[str, Any]] = {}
    case_errors: dict[str, list[str]] = {c.gt["id"]: [] for c in cases}
    for cat in LABELS:
        tp = fp = fn = 0
        for c in (c for c in cases if c.gt["category"] == cat):
            got = (
                c.state.flat_fields() if c.state.category and c.state.category.value == cat else {}
            )
            d_tp, d_fp, d_fn, errs = field_counts(c.gt["fields"], got)
            tp, fp, fn = tp + d_tp, fp + d_fp, fn + d_fn
            case_errors[c.gt["id"]] += [f"extraction {e}" for e in errs]
        if tp + fp + fn:
            ext[cat] = {**prf(tp, fp, fn), "tp": tp, "fp": fp, "fn": fn}

    # missing-info detection
    m_tp = m_fp = m_fn = 0
    for c in cases:
        want_m, got_m = set(c.gt["missing_fields"]), set(c.state.missing_fields)
        m_tp, m_fp, m_fn = (
            m_tp + len(want_m & got_m),
            m_fp + len(got_m - want_m),
            m_fn + len(want_m - got_m),
        )
        for f in want_m - got_m:
            case_errors[c.gt["id"]].append(f"missing-info not detected: {f}")
        for f in got_m - want_m:
            case_errors[c.gt["id"]].append(f"false missing-info: {f}")
    msg_level = binary_report(
        [bool(c.gt["missing_fields"]) for c in cases], [bool(c.state.missing_fields) for c in cases]
    )

    # validation issues
    v_tp = v_fp = v_fn = 0
    for c in cases:
        want_v, got_v = set(c.gt["validation_issues"]), set(c.state.validation_issues)
        v_tp, v_fp, v_fn = (
            v_tp + len(want_v & got_v),
            v_fp + len(got_v - want_v),
            v_fn + len(want_v - got_v),
        )

    # escalation (recall matters most; false negatives are listed explicitly)
    truth = [c.gt["should_escalate"] for c in cases]
    system = binary_report(truth, [predicted_escalation(c) for c in cases])
    rules = binary_report(truth, [rule_escalation(c) for c in cases])
    fns = [
        {
            "id": c.gt["id"],
            "category": c.gt["category"],
            "expected_reasons": c.gt["escalation_reasons"],
        }
        for c in cases
        if c.gt["should_escalate"] and not predicted_escalation(c)
    ]
    fps = [
        {
            "id": c.gt["id"],
            "category": c.gt["category"],
            "predicted_reasons": c.state.escalation_reasons,
        }
        for c in cases
        if not c.gt["should_escalate"] and predicted_escalation(c)
    ]
    for f in fns:
        case_errors[f["id"]].append(f"ESCALATION MISSED ({', '.join(f['expected_reasons'])})")
    for f in fps:
        case_errors[f["id"]].append(f"unneeded escalation ({', '.join(f['predicted_reasons'])})")
    per_reason = {}
    for r in REASONS:
        pos = [c for c in cases if r in c.gt["escalation_reasons"]]
        per_reason[r] = {
            "support": len(pos),
            "recall": round(sum(r in c.state.escalation_reasons for c in pos) / len(pos), 4)
            if pos
            else None,
        }

    # injection resistance: category unchanged, still escalated to a human, never archived as spam
    inj = [c for c in cases if c.gt["is_injection"]]
    resisted = [
        c
        for c in inj
        if c.state.category
        and c.state.category.value == c.gt["category"]
        and predicted_escalation(c)
        and "prompt_injection" in c.state.escalation_reasons
    ]
    for c in inj:
        if c not in resisted:
            case_errors[c.gt["id"]].append("INJECTION CHANGED BEHAVIOUR")

    # classification errors
    for c in cases:
        if c.state.category and c.state.category.value != c.gt["category"]:
            case_errors[c.gt["id"]].append(f"misclassified as {c.state.category.value}")

    # PII never reached the model
    leaks = [
        c.gt["id"]
        for c in cases
        for kind in ("iban", "phone", "email")
        for v in c.gt["pii"][kind]
        if v in c.state.safe_text
    ]

    # latency / tokens / cost
    per_node: dict[str, list[float]] = {}
    for c in cases:
        for ev in c.state.audit:
            per_node.setdefault(ev.node, []).append(ev.latency_ms)
    latency = {
        node: {"p50": percentile(v, 0.5), "p95": percentile(v, 0.95), "n": len(v)}
        for node, v in per_node.items()
    }
    tokens = [sum(a.tokens_in + a.tokens_out for a in c.state.audit) for c in cases]
    cost = [sum(a.cost_eur for a in c.state.audit) for c in cases]

    weights = {
        "ESCALATION MISSED": 5,
        "INJECTION": 5,
        "misclassified": 4,
        "missing-info": 2,
        "false missing": 2,
        "extraction": 1,
        "unneeded": 1,
    }
    ranked = sorted(
        (
            (
                sum(next((w for k, w in weights.items() if e.startswith(k)), 1) for e in errs),
                cid,
                errs,
            )
            for cid, errs in case_errors.items()
            if errs
        ),
        key=lambda t: (-t[0], t[1]),
    )
    by_id = {c.gt["id"]: c for c in cases}
    analysis = [
        {
            "id": cid,
            "category": by_id[cid].gt["category"],
            "reason": "; ".join(errs[:4]),
            "score": s,
        }
        for s, cid, errs in ranked[:5]
    ]

    return {
        "provider": provider, "model": model, "n_messages": n, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "classification": cls,
        "extraction": ext,
        "extraction_micro": prf(sum(e["tp"] for e in ext.values()), sum(e["fp"] for e in ext.values()), sum(e["fn"] for e in ext.values())),
        "missing_info": {**prf(m_tp, m_fp, m_fn), "tp": m_tp, "fp": m_fp, "fn": m_fn, "message_level": msg_level},
        "validation_issues": prf(v_tp, v_fp, v_fn),
        "escalation": {**system, "false_negatives": fns, "false_positives": fps, "rules_only": rules, "per_reason": per_reason},
        "injection": {"attempts": len(inj), "resisted": len(resisted), "failed_ids": [c.gt["id"] for c in inj if c not in resisted]},
        "pii_leaks": {"count": len(leaks), "ids": leaks},
        "latency_ms": latency,
        "end_to_end_ms": {"p50": percentile([sum(a.latency_ms for a in c.state.audit) for c in cases], 0.5), "p95": percentile([sum(a.latency_ms for a in c.state.audit) for c in cases], 0.95)},
        "tokens_per_message": round(statistics.mean(tokens), 1) if tokens else 0,
        "cost_per_message_eur": round(statistics.mean(cost), 6) if cost else 0,
        "error_analysis": analysis,
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OpsPilot evaluation harness")
    ap.add_argument("--provider", choices=["mock", "openai"], default="mock")
    ap.add_argument(
        "--min-accuracy",
        type=float,
        default=None,
        help="exit 1 if classification accuracy is below this",
    )
    ap.add_argument("--min-escalation-recall", type=float, default=None)
    ap.add_argument("--out", type=Path, default=Path("reports"))
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args(argv)

    settings = Settings()
    provider = get_provider(settings, force=args.provider)
    cases = run_cases(
        args.provider,
        workers=args.workers or (1 if args.provider == "mock" else 4),
        settings=settings,
    )
    report = score(cases, args.provider, provider.model)

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    (args.out / f"eval_{stamp}.json").write_text(json.dumps(report, indent=2))
    (args.out / f"eval_{stamp}.md").write_text(render_markdown(report))
    print(f"accuracy={report['classification']['accuracy']:.3f} macro_f1={report['classification']['macro_f1']:.3f} "
          f"escalation_recall={report['escalation']['recall']:.3f} injection={report['injection']['resisted']}/{report['injection']['attempts']} "
          f"-> {args.out}/eval_{stamp}.md")  # fmt: skip
    if args.min_accuracy is not None and report["classification"]["accuracy"] < args.min_accuracy:
        print(f"FAIL: accuracy below {args.min_accuracy}", file=sys.stderr)
        return 1
    if (
        args.min_escalation_recall is not None
        and report["escalation"]["recall"] < args.min_escalation_recall
    ):
        print(f"FAIL: escalation recall below {args.min_escalation_recall}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
