"""
Benchmark runner for Tripwire's detection module.

Reads cases.jsonl, runs the provenance matcher, and reports:
  - Overall recall on attack cases and false-positive rate on clean cases
  - Per-attack-type recall
  - Latency percentiles
  - Ablation chart (exact → +entity → +ngram → +fuzzy → +normalization)

Usage:
    python -m detect.bench.run_bench
    python -m detect.bench.run_bench --threshold 0.5
    python -m detect.bench.run_bench --ablation
"""

from __future__ import annotations
import json
import time
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from typing import List

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from detect.models import Span
from detect.matcher import trace, SpanCache
from detect.normalize import normalize


def load_cases(path: str | Path | None = None) -> list[dict]:
    """Load benchmark cases from JSONL file."""
    if path is None:
        path = Path(__file__).parent / "cases.jsonl"
    else:
        path = Path(path)

    cases = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [WARN] Skipping line {i}: {e}")
    return cases


def _make_spans(raw_spans: list[dict]) -> list[Span]:
    """Convert raw span dicts to Span objects."""
    return [
        Span(
            text=s["text"],
            source=s.get("source", "unknown"),
            trust=s.get("trust", "UNTRUSTED"),
            secret=s.get("secret", False),
        )
        for s in raw_spans
    ]


def run_benchmark(
    cases: list[dict],
    threshold: float = 0.5,
    disabled_layers: set[str] | None = None,
) -> dict:
    """Run the benchmark and return metrics.

    Args:
        cases: List of benchmark case dicts.
        threshold: Minimum match score to consider a detection.
        disabled_layers: Set of layer names to disable for ablation
            (e.g. {"fuzzy", "ngram"}).

    Returns:
        Dict with metrics: recall, fpr, per_type recall, latencies, etc.
    """
    tp, fn, fp, tn = 0, 0, 0, 0
    per_type: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fn": 0})
    latencies: list[float] = []

    cache = SpanCache()

    for case in cases:
        arg = case["arg"]
        spans = _make_spans(case["spans"])
        expected = case["expected"]  # "leak" or "clean"
        attack_type = case.get("attack_type", "unknown")

        # Precompute cache
        for s in spans:
            cache.add(s)

        # Time the trace call
        t0 = time.perf_counter()
        matches = trace(arg, spans, threshold=threshold, cache=cache)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)  # ms

        # Filter by disabled layers for ablation
        if disabled_layers:
            matches = [
                m for m in matches
                if m.kind not in disabled_layers
                and not all(
                    k in disabled_layers
                    for k in (m.layer_scores or {}).keys()
                    if (m.layer_scores or {}).get(k, 0) >= threshold
                )
            ]

        # A detection in Tripwire benchmark is a leak from UNTRUSTED or SECRET spans
        leak_matches = [m for m in matches if m.span.trust == "UNTRUSTED" or m.span.secret]
        detected = len(leak_matches) > 0

        if expected == "leak":
            if detected:
                tp += 1
                per_type[attack_type]["tp"] += 1
            else:
                fn += 1
                per_type[attack_type]["fn"] += 1
        elif expected == "clean":
            if detected:
                fp += 1
            else:
                tn += 1

    # Compute metrics
    total_attacks = tp + fn
    total_clean = fp + tn
    recall = tp / total_attacks if total_attacks > 0 else 0.0
    fpr = fp / total_clean if total_clean > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    per_type_recall = {}
    for atype, counts in per_type.items():
        total = counts["tp"] + counts["fn"]
        per_type_recall[atype] = counts["tp"] / total if total > 0 else 0.0

    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0

    return {
        "threshold": threshold,
        "total_cases": len(cases),
        "attacks": total_attacks,
        "clean": total_clean,
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "recall": round(recall, 4),
        "fpr": round(fpr, 4),
        "precision": round(precision, 4),
        "per_type_recall": {k: round(v, 4) for k, v in sorted(per_type_recall.items())},
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "latency_p99_ms": round(p99, 2),
    }


def run_ablation(cases: list[dict], threshold: float = 0.5) -> list[dict]:
    """Run ablation study: cumulatively enable layers.

    Returns a list of result dicts, one per ablation step.
    """
    steps = [
        ("exact_only",      {"entity", "ngram", "fuzzy"}),
        ("+entity",         {"ngram", "fuzzy"}),
        ("+ngram",          {"fuzzy"}),
        ("+fuzzy (full)",   set()),
    ]

    results = []
    for name, disabled in steps:
        metrics = run_benchmark(cases, threshold=threshold, disabled_layers=disabled)
        metrics["ablation_step"] = name
        results.append(metrics)

    return results


def print_results(metrics: dict) -> None:
    """Pretty-print benchmark results."""
    print("\n" + "=" * 60)
    print(f"  BENCHMARK RESULTS (threshold={metrics['threshold']})")
    print("=" * 60)
    print(f"  Total cases:    {metrics['total_cases']}")
    print(f"  Attack cases:   {metrics['attacks']}")
    print(f"  Clean cases:    {metrics['clean']}")
    print(f"  TP: {metrics['tp']}  FN: {metrics['fn']}  FP: {metrics['fp']}  TN: {metrics['tn']}")
    print(f"  Recall:         {metrics['recall']:.1%}")
    print(f"  False-pos rate: {metrics['fpr']:.1%}")
    print(f"  Precision:      {metrics['precision']:.1%}")
    print()
    print("  Per-attack-type recall:")
    for atype, rec in metrics["per_type_recall"].items():
        print(f"    {atype:30s} {rec:.1%}")
    print()
    print(f"  Latency p50: {metrics['latency_p50_ms']:.1f} ms")
    print(f"  Latency p95: {metrics['latency_p95_ms']:.1f} ms")
    print(f"  Latency p99: {metrics['latency_p99_ms']:.1f} ms")
    print("=" * 60)


def print_ablation(ablation: list[dict]) -> None:
    """Pretty-print ablation results."""
    print("\n" + "=" * 60)
    print("  ABLATION STUDY")
    print("=" * 60)
    print(f"  {'Step':<25s} {'Recall':>8s} {'FPR':>8s} {'Precision':>10s}")
    print("  " + "-" * 55)
    for step in ablation:
        print(f"  {step['ablation_step']:<25s} "
              f"{step['recall']:>7.1%} "
              f"{step['fpr']:>7.1%} "
              f"{step['precision']:>9.1%}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Tripwire matcher benchmark")
    parser.add_argument("--cases", type=str, help="Path to cases.jsonl")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--ablation", action="store_true",
                        help="Run ablation study")
    parser.add_argument("--sweep", action="store_true",
                        help="Sweep thresholds from 0.3 to 0.9")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    print(f"Loaded {len(cases)} benchmark cases")

    if args.sweep:
        print("\n  Threshold sweep:")
        print(f"  {'Threshold':>10s} {'Recall':>8s} {'FPR':>8s} {'Precision':>10s}")
        for t in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            m = run_benchmark(cases, threshold=t)
            print(f"  {t:>10.1f} {m['recall']:>7.1%} {m['fpr']:>7.1%} {m['precision']:>9.1%}")
    elif args.ablation:
        ablation = run_ablation(cases, threshold=args.threshold)
        print_ablation(ablation)
    else:
        metrics = run_benchmark(cases, threshold=args.threshold)
        print_results(metrics)


if __name__ == "__main__":
    main()
