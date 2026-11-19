"""Pure metric functions for the evaluation harness."""

import difflib
import math
from collections import Counter
from typing import Any

FUZZY_FIELDS = {"description", "question", "reason", "delivery_address", "system", "supplier_name"}
FUZZY_THRESHOLD = 0.85


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def classification_report(
    y_true: list[str], y_pred: list[str], labels: list[str]
) -> dict[str, Any]:
    idx = {lab: i for i, lab in enumerate(labels)}
    conf = [[0] * len(labels) for _ in labels]
    for t, p in zip(y_true, y_pred, strict=True):
        conf[idx[t]][idx[p]] += 1
    per_class: dict[str, dict[str, float]] = {}
    for lab in labels:
        i = idx[lab]
        tp = conf[i][i]
        fp = sum(conf[r][i] for r in range(len(labels))) - tp
        fn = sum(conf[i]) - tp
        per_class[lab] = {**prf(tp, fp, fn), "support": sum(conf[i])}
    present = [lab for lab in labels if per_class[lab]["support"] > 0]
    macro = sum(per_class[lab]["f1"] for lab in present) / len(present) if present else 0.0
    acc = sum(conf[i][i] for i in range(len(labels))) / len(y_true) if y_true else 0.0
    return {
        "accuracy": round(acc, 4),
        "macro_f1": round(macro, 4),
        "labels": labels,
        "confusion": conf,
        "per_class": per_class,
    }


def values_match(name: str, expected: Any, got: Any) -> bool:
    if isinstance(expected, list) or isinstance(got, list):
        return (
            isinstance(expected, list)
            and isinstance(got, list)
            and [str(x).strip().lower() for x in expected] == [str(x).strip().lower() for x in got]
        )
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected is got
    if isinstance(expected, int | float) and isinstance(got, int | float):
        return math.isclose(float(expected), float(got), abs_tol=0.01)
    a, b = str(expected).strip().lower(), str(got).strip().lower()
    if a == b:
        return True
    return name in FUZZY_FIELDS and difflib.SequenceMatcher(None, a, b).ratio() >= FUZZY_THRESHOLD


def field_counts(expected: dict[str, Any], got: dict[str, Any]) -> tuple[int, int, int, list[str]]:
    """(tp, fp, fn, error descriptions) for one message."""
    tp = fp = fn = 0
    errors: list[str] = []
    for name, val in expected.items():
        if name not in got:
            fn += 1
            errors.append(f"missed {name}")
        elif values_match(name, val, got[name]):
            tp += 1
        else:
            fp += 1
            fn += 1
            errors.append(f"{name}: expected {val!r}, got {got[name]!r}")
    for name in got.keys() - expected.keys():
        fp += 1
        errors.append(f"extra {name}={got[name]!r}")
    return tp, fp, fn, errors


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def binary_report(y_true: list[bool], y_pred: list[bool]) -> dict[str, Any]:
    c = Counter(zip(y_true, y_pred, strict=True))
    tp, fp, fn, tn = c[(True, True)], c[(False, True)], c[(True, False)], c[(False, False)]
    return {**prf(tp, fp, fn), "tp": tp, "fp": fp, "fn": fn, "tn": tn}
