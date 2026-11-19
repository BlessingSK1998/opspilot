"""Markdown rendering of an evaluation report."""

from typing import Any


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def render_markdown(r: dict[str, Any]) -> str:
    c, e, m, inj = r["classification"], r["escalation"], r["missing_info"], r["injection"]
    L: list[str] = [
        "# OpsPilot evaluation report",
        "",
        f"- Provider: **{r['provider']}** (`{r['model']}`)",
        f"- Messages: **{r['n_messages']}** · generated {r['generated_at']}",
    ]
    if r["provider"] == "mock":
        L += [
            "",
            "> **Read this first.** The mock provider's rules were written against the same synthetic templates used to generate this data set, so near-perfect scores here are a *regression check*, not evidence of generalisation. Run `make eval PROVIDER=openai` for real-model numbers.",
        ]
    L += [
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Classification accuracy | {_pct(c['accuracy'])} |",
        f"| Macro-F1 | {c['macro_f1']:.3f} |",
        f"| Escalation recall (system) | {_pct(e['recall'])} ({e['fn']} missed) |",
        f"| Escalation precision (system) | {_pct(e['precision'])} ({e['fp']} unneeded) |",
        f"| Missing-info precision / recall (field level) | {_pct(m['precision'])} / {_pct(m['recall'])} |",
        f"| Extraction F1 (micro, all fields) | {r['extraction_micro']['f1']:.3f} |",
        f"| Injection resistance | {inj['resisted']}/{inj['attempts']} |",
        f"| PII leaked to the model | {r['pii_leaks']['count']} |",
        f"| End-to-end latency p50 / p95 | {r['end_to_end_ms']['p50']} / {r['end_to_end_ms']['p95']} ms |",
        f"| Tokens per message | {r['tokens_per_message']:.0f} |",
        f"| Cost per message | €{r['cost_per_message_eur']:.5f} |",
    ]
    L += [
        "",
        "## Classification",
        "",
        "| Category | Precision | Recall | F1 | Support |",
        "|---|---|---|---|---|",
    ]
    L += [
        f"| {k} | {v['precision']:.2f} | {v['recall']:.2f} | {v['f1']:.2f} | {int(v['support'])} |"
        for k, v in c["per_class"].items()
    ]
    L += [
        "",
        "### Confusion matrix (rows = actual, columns = predicted)",
        "",
        "| actual \\ predicted | " + " | ".join(c["labels"]) + " |",
        "|---" * (len(c["labels"]) + 1) + "|",
    ]
    L += [
        f"| **{lab}** | " + " | ".join(str(x) for x in row) + " |"
        for lab, row in zip(c["labels"], c["confusion"], strict=True)
    ]
    L += [
        "",
        "## Field extraction (per category)",
        "",
        "| Category | Precision | Recall | F1 | TP | FP | FN |",
        "|---|---|---|---|---|---|---|",
    ]
    L += [
        f"| {k} | {v['precision']:.2f} | {v['recall']:.2f} | {v['f1']:.2f} | {v['tp']} | {v['fp']} | {v['fn']} |"
        for k, v in r["extraction"].items()
    ]
    L += [
        "",
        "## Missing-information detection",
        "",
        f"- Field level: precision {_pct(m['precision'])}, recall {_pct(m['recall'])} (TP {m['tp']}, FP {m['fp']}, FN {m['fn']})",
        f"- Message level: precision {_pct(m['message_level']['precision'])}, recall {_pct(m['message_level']['recall'])}",
        f"- Validation issues (wrong invoice, amount mismatch, ...): precision {_pct(r['validation_issues']['precision'])}, recall {_pct(r['validation_issues']['recall'])}",
    ]
    L += [
        "",
        "## Escalation (recall matters most)",
        "",
        f"- System behaviour (what actually reaches a human): recall **{_pct(e['recall'])}**, precision {_pct(e['precision'])}",
        f"- Hard rules only (excluding the low-confidence safety net): recall {_pct(e['rules_only']['recall'])}, precision {_pct(e['rules_only']['precision'])}",
        "",
        "| Reason | Support | Recall |",
        "|---|---|---|",
    ]
    L += [f"| {k} | {v['support']} | {_pct(v['recall'])} |" for k, v in e["per_reason"].items()]
    L += ["", "### False negatives (escalations that should have happened)", ""]
    L += [
        f"- **{f['id']}** ({f['category']}): expected {', '.join(f['expected_reasons'])}"
        for f in e["false_negatives"]
    ] or ["None."]
    L += ["", "### False positives (escalated, but not required)", ""]
    L += [
        f"- {f['id']} ({f['category']}): {', '.join(f['predicted_reasons'])}"
        for f in e["false_positives"]
    ] or ["None."]
    L += [
        "",
        "## Injection resistance",
        "",
        f"{inj['resisted']} of {inj['attempts']} injected emails kept their true category, were escalated and flagged. Failures: {', '.join(inj['failed_ids']) or 'none'}.",
    ]
    L += ["", "## Latency per node", "", "| Node | p50 ms | p95 ms | n |", "|---|---|---|---|"]
    L += [f"| {k} | {v['p50']} | {v['p95']} | {v['n']} |" for k, v in r["latency_ms"].items()]
    L += ["", "## Error analysis: worst 5 cases", ""]
    L += [
        f"{i}. **{x['id']}** ({x['category']}): {x['reason']}"
        for i, x in enumerate(r["error_analysis"], 1)
    ] or ["No errors."]
    return "\n".join(L) + "\n"
