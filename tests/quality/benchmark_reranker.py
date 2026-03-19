#!/usr/bin/env python3
"""
Reranker Benchmark Orchestration Script for Clew Engine.

Compares retrieval quality with and without cross-encoder reranking.
Generates comprehensive side-by-side analysis with statistical metrics.

Usage:
    python tests/quality/benchmark_reranker.py
    python tests/quality/benchmark_reranker.py --api-url http://localhost:8000
    python tests/quality/benchmark_reranker.py --output CUSTOM_REPORT.md
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def run_measurement(api_url: str, gold_set: str, rerank: bool) -> dict:
    """
    Run measure_mrr.py and return JSON results.

    Args:
        api_url: Base URL of the Clew API
        gold_set: Path to gold_set.json
        rerank: Enable reranking

    Returns:
        Summary dict from measurement script
    """
    mode = "WITH reranking" if rerank else "WITHOUT reranking (baseline)"
    logger.info(f"Running measurement {mode}...")

    cmd = [
        sys.executable,
        str(Path(__file__).parent / "measure_mrr.py"),
        "--api-url",
        api_url,
        "--gold-set",
        gold_set,
        "--json",
    ]

    if rerank:
        cmd.append("--rerank")
    else:
        cmd.append("--no-rerank")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode not in [0, 1]:  # 1 is expected if targets not met
            logger.error(f"Measurement failed:\n{result.stderr}")
            sys.exit(1)

        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        logger.error(f"Failed to run measurement: {e}")
        sys.exit(1)


def calculate_lift(baseline: float, experiment: float) -> tuple[float, str]:
    """
    Calculate percentage lift from baseline to experiment.

    Args:
        baseline: Baseline metric value
        experiment: Experiment metric value

    Returns:
        Tuple of (absolute_lift, formatted_percentage)
    """
    if baseline == 0:
        return 0.0, "N/A"

    lift = ((experiment - baseline) / baseline) * 100
    sign = "+" if lift >= 0 else ""
    return lift, f"{sign}{lift:.1f}%"


def format_status_badge(lift: float, threshold: float = 5.0) -> str:
    """Format a status badge for lift percentage."""
    if lift >= threshold:
        return "✅ PASS"
    elif lift >= 0:
        return "⚠️  MARGINAL"
    else:
        return "❌ NEGATIVE"


def generate_category_table(baseline: dict, experiment: dict) -> str:
    """Generate category-level comparison table."""
    baseline_cats = baseline.get("categories", {})
    experiment_cats = experiment.get("categories", {})

    all_categories = sorted(set(baseline_cats.keys()) | set(experiment_cats.keys()))

    lines = ["## Category Breakdown\n"]
    lines.append("| Category | Baseline MRR | Reranked MRR | Lift | Count |")
    lines.append("|----------|--------------|--------------|------|-------|")

    for cat in all_categories:
        baseline_mrr = baseline_cats.get(cat, {}).get("mrr", 0.0)
        experiment_mrr = experiment_cats.get(cat, {}).get("mrr", 0.0)
        count = baseline_cats.get(cat, {}).get("count", 0)
        _, lift_pct = calculate_lift(baseline_mrr, experiment_mrr)

        lines.append(f"| {cat:20s} | {baseline_mrr:.4f} | {experiment_mrr:.4f} | {lift_pct:>8s} | {count:3d} |")

    return "\n".join(lines)


def generate_report(baseline: dict, experiment: dict, output_path: Path, api_url: str):
    """
    Generate comprehensive Markdown benchmark report.

    Args:
        baseline: Results without reranking
        experiment: Results with reranking
        output_path: Path to write report
        api_url: API URL tested
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Calculate lifts
    mrr_lift, mrr_lift_pct = calculate_lift(baseline["mrr"], experiment["mrr"])
    r3_lift, r3_lift_pct = calculate_lift(baseline["mean_recall_at_3"], experiment["mean_recall_at_3"])
    r5_lift, r5_lift_pct = calculate_lift(baseline["mean_recall_at_5"], experiment["mean_recall_at_5"])
    hr_lift, hr_lift_pct = calculate_lift(baseline["hit_rate"], experiment["hit_rate"])

    # Status badges
    mrr_status = format_status_badge(mrr_lift)
    r3_status = format_status_badge(r3_lift)
    r5_status = format_status_badge(r5_lift, threshold=3.0)

    # Precompute formatted metric values for use in the report table
    b_mrr = f"{baseline['mrr']:.4f}"
    b_r3 = f"{baseline['mean_recall_at_3']:.4f}"
    b_r5 = f"{baseline['mean_recall_at_5']:.4f}"
    b_hr = f"{baseline['hit_rate']:.4f}"
    e_mrr = f"{experiment['mrr']:.4f}"
    e_r3 = f"{experiment['mean_recall_at_3']:.4f}"
    e_r5 = f"{experiment['mean_recall_at_5']:.4f}"
    e_hr = f"{experiment['hit_rate']:.4f}"

    # Generate report
    report = f"""# Reranker Benchmark Report

**Generated**: {timestamp}
**API Endpoint**: `{api_url}`
**Gold Set Size**: {baseline["total_queries"]} queries

---

## Executive Summary

This report compares retrieval quality **with and without** cross-encoder reranking.

| Metric         | Baseline   | Reranked   | Lift        | Status         |
|----------------|------------|------------|-------------|----------------|
| **MRR**        | {b_mrr}    | {e_mrr}    | {mrr_lift_pct:>10s} | {mrr_status:14s} |
| **Recall@3**   | {b_r3}    | {e_r3}    | {r3_lift_pct:>10s} | {r3_status:14s} |
| **Recall@5**   | {b_r5}    | {e_r5}    | {r5_lift_pct:>10s} | {r5_status:14s} |
| **Hit Rate**   | {b_hr}    | {e_hr}    | {hr_lift_pct:>10s} | N/A            |

---

## Success Criteria Assessment

### Quality Metrics (Primary)
- **MRR Lift > 5%**: {mrr_status} ({mrr_lift_pct})
- **Recall@3 Lift > 5%**: {r3_status} ({r3_lift_pct})
- **Recall@5 Lift > 3%**: {r5_status} ({r5_lift_pct})

### Overall Verdict
"""

    # Determine overall verdict
    if mrr_lift >= 5.0 and r3_lift >= 5.0 and r5_lift >= 3.0:
        report += "✅ **ALL CRITERIA MET** — Reranker provides significant quality improvement.\n\n"
        report += "**Recommendation**: Enable reranking for production deployment.\n"
    elif mrr_lift >= 0 and r3_lift >= 0:
        report += "⚠️  **MARGINAL IMPROVEMENT** — Reranker shows positive lift but below target threshold.\n\n"
        report += "**Recommendation**: Consider tuning reranker model or expanding gold set for validation.\n"
    else:
        report += "❌ **NEGATIVE LIFT DETECTED** — Reranker degrades quality.\n\n"
        report += "**Recommendation**: Investigate reranker configuration. Do NOT deploy.\n"

    report += "\n---\n\n"

    # Add category breakdown
    report += generate_category_table(baseline, experiment)

    # Add configuration details
    report += "\n\n---\n\n"
    report += "## Configuration\n\n"
    report += "- **Baseline**: Vector search only (rerank=False)\n"
    report += "- **Experiment**: Vector search + Cross-Encoder reranking (rerank=True)\n"
    mrr_target = baseline["targets"]["mrr"]
    r3_target = baseline["targets"]["recall_at_3"]
    report += f"- **Target Metrics**: MRR ≥ {mrr_target}, Recall@3 ≥ {r3_target}\n"

    # Add raw results
    report += "\n\n---\n\n"
    report += "## Raw Results\n\n"
    report += "### Baseline (No Reranking)\n"
    report += f"```json\n{json.dumps(baseline, indent=2)}\n```\n\n"
    report += "### Experiment (With Reranking)\n"
    report += f"```json\n{json.dumps(experiment, indent=2)}\n```\n"

    # Write report
    output_path.write_text(report)
    logger.info(f"Report generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Clew reranker quality improvement")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Clew API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--gold-set",
        default=str(Path(__file__).parent / "gold_set.json"),
        help="Path to gold_set.json",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "RERANKER_REPORT.md"),
        help="Output report path (default: tests/quality/RERANKER_REPORT.md)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("CLEW ENGINE — RERANKER BENCHMARK")
    print("=" * 70 + "\n")

    # Run baseline measurement
    baseline = run_measurement(args.api_url, args.gold_set, rerank=False)
    logger.info(f"  Baseline MRR: {baseline['mrr']:.4f}, Recall@3: {baseline['mean_recall_at_3']:.4f}\n")

    # Run reranked measurement
    experiment = run_measurement(args.api_url, args.gold_set, rerank=True)
    logger.info(f"  Reranked MRR: {experiment['mrr']:.4f}, Recall@3: {experiment['mean_recall_at_3']:.4f}\n")

    # Calculate and display summary
    mrr_lift, mrr_lift_pct = calculate_lift(baseline["mrr"], experiment["mrr"])
    r3_lift, r3_lift_pct = calculate_lift(baseline["mean_recall_at_3"], experiment["mean_recall_at_3"])

    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"  MRR:       {baseline['mrr']:.4f} → {experiment['mrr']:.4f}  (Lift: {mrr_lift_pct})")
    b_r3 = f"{baseline['mean_recall_at_3']:.4f}"
    e_r3 = f"{experiment['mean_recall_at_3']:.4f}"
    print(f"  Recall@3:  {b_r3} → {e_r3}  (Lift: {r3_lift_pct})")
    print("=" * 70 + "\n")

    # Generate report
    output_path = Path(args.output)
    generate_report(baseline, experiment, output_path, args.api_url)

    print(f"\n✅ Benchmark complete! Report saved to: {output_path}\n")

    # Exit with status code based on success criteria
    if mrr_lift >= 5.0 and r3_lift >= 5.0:
        sys.exit(0)
    else:
        logger.warning("⚠️  Reranker did not meet target improvement thresholds")
        sys.exit(1)


if __name__ == "__main__":
    main()
