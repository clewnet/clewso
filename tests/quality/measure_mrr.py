#!/usr/bin/env python3
"""
Retrieval Quality Measurement Tool for Clew Engine.

Measures Mean Reciprocal Rank (MRR) and Recall@K against the gold set.

Usage:
    # Against a running Clew instance (default: http://localhost:8000)
    python tests/quality/measure_mrr.py

    # Against a specific instance
    python tests/quality/measure_mrr.py --api-url https://api.clewengine.dev

    # With a specific gold set file
    python tests/quality/measure_mrr.py --gold-set tests/quality/gold_set.json

    # Show per-query details
    python tests/quality/measure_mrr.py --verbose

Alpha Blocker: Pre-Release Hardening Item #3 (Retrieval Quality Baseline)
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result of evaluating a single gold-set query."""

    query_id: str
    query: str
    reciprocal_rank: float
    recall_at_3: float
    recall_at_5: float
    top_paths: list[str]
    expected_paths: list[str]
    found_paths: list[str]
    missing_paths: list[str]


def compute_reciprocal_rank(result_paths: list[str], expected_paths: list[str]) -> float:
    """
    Compute Reciprocal Rank: 1/rank of first relevant result.

    Args:
        result_paths: Ordered list of file paths returned by search
        expected_paths: Set of expected relevant paths

    Returns:
        1/rank of first match, or 0 if no match found
    """
    expected_set = {p.lower() for p in expected_paths}

    for rank, path in enumerate(result_paths, start=1):
        # Check for exact match or suffix match (handles different path prefixes)
        path_lower = path.lower()
        for expected in expected_set:
            if path_lower.endswith(expected) or expected.endswith(path_lower):
                return 1.0 / rank

    return 0.0


def compute_recall_at_k(result_paths: list[str], expected_paths: list[str], k: int) -> float:
    """
    Compute Recall@K: fraction of expected paths found in top K results.

    Args:
        result_paths: Ordered list of file paths returned by search
        expected_paths: Set of expected relevant paths
        k: Number of top results to consider

    Returns:
        Fraction of expected paths found (0.0 to 1.0)
    """
    if not expected_paths:
        return 1.0

    top_k = [p.lower() for p in result_paths[:k]]
    expected_set = {p.lower() for p in expected_paths}

    found = 0
    for expected in expected_set:
        for result in top_k:
            if result.endswith(expected) or expected.endswith(result):
                found += 1
                break

    return found / len(expected_set)


def find_matches(result_paths: list[str], expected_paths: list[str]) -> tuple[list[str], list[str]]:
    """Return (found, missing) paths from expected set."""
    found = []
    missing = []

    for expected in expected_paths:
        matched = False
        for result in result_paths:
            if result.lower().endswith(expected.lower()) or expected.lower().endswith(result.lower()):
                found.append(expected)
                matched = True
                break
        if not matched:
            missing.append(expected)

    return found, missing


def evaluate_query(
    client: httpx.Client,
    api_url: str,
    query_entry: dict,
    limit: int = 10,
    rerank: bool = False,
) -> QueryResult:
    """
    Evaluate a single gold-set query against the live API.

    Args:
        client: HTTP client
        api_url: Base URL of the Clew API
        query_entry: Gold set query entry
        limit: Number of results to fetch
        rerank: Enable cross-encoder reranking

    Returns:
        QueryResult with metrics
    """
    query_id = query_entry["id"]
    query = query_entry["query"]
    expected_paths = query_entry["expected_paths"]

    try:
        response = client.post(
            f"{api_url}/v1/search/",
            json={"query": query, "limit": limit, "rerank": rerank},
            timeout=30.0,
        )
        response.raise_for_status()
        results = response.json()
    except httpx.HTTPError as e:
        logger.warning(f"  [{query_id}] API error: {e}")
        return QueryResult(
            query_id=query_id,
            query=query,
            reciprocal_rank=0.0,
            recall_at_3=0.0,
            recall_at_5=0.0,
            top_paths=[],
            expected_paths=expected_paths,
            found_paths=[],
            missing_paths=expected_paths,
        )

    # Extract paths from results
    result_paths = [r.get("metadata", {}).get("path", r.get("id", "")) for r in results]

    rr = compute_reciprocal_rank(result_paths, expected_paths)
    r3 = compute_recall_at_k(result_paths, expected_paths, k=3)
    r5 = compute_recall_at_k(result_paths, expected_paths, k=5)
    found, missing = find_matches(result_paths, expected_paths)

    return QueryResult(
        query_id=query_id,
        query=query,
        reciprocal_rank=rr,
        recall_at_3=r3,
        recall_at_5=r5,
        top_paths=result_paths[:5],
        expected_paths=expected_paths,
        found_paths=found,
        missing_paths=missing,
    )


def _compute_aggregate_metrics(results: list[QueryResult]) -> dict[str, float]:
    """Compute aggregate metrics (MRR, Recall, Hit Rate) from query results."""
    n = len(results)
    if n == 0:
        return {
            "mrr": 0.0,
            "mean_recall_at_3": 0.0,
            "mean_recall_at_5": 0.0,
            "hit_rate": 0.0,
        }

    mrr = sum(r.reciprocal_rank for r in results) / n
    mean_r3 = sum(r.recall_at_3 for r in results) / n
    mean_r5 = sum(r.recall_at_5 for r in results) / n
    hit_rate = sum(1 for r in results if r.reciprocal_rank > 0) / n

    return {
        "mrr": round(mrr, 4),
        "mean_recall_at_3": round(mean_r3, 4),
        "mean_recall_at_5": round(mean_r5, 4),
        "hit_rate": round(hit_rate, 4),
    }


def _compute_category_metrics(queries: list[dict], results: list[QueryResult]) -> dict[str, dict[str, float]]:
    """Group results by category and compute category-level MRR."""
    categories: dict[str, list[QueryResult]] = {}
    for entry, result in zip(queries, results, strict=False):
        cat = entry.get("category", "uncategorized")
        categories.setdefault(cat, []).append(result)

    category_summary = {}
    for cat, cat_results in sorted(categories.items()):
        cat_n = len(cat_results)
        cat_mrr = sum(r.reciprocal_rank for r in cat_results) / cat_n
        category_summary[cat] = {
            "count": cat_n,
            "mrr": round(cat_mrr, 4),
        }
    return category_summary


def run_evaluation(
    api_url: str,
    gold_set_path: str,
    verbose: bool = False,
    rerank: bool = False,
) -> dict:
    """
    Run the full gold-set evaluation.

    Args:
        api_url: Base URL of the Clew API
        gold_set_path: Path to gold_set.json
        verbose: Show per-query details
        rerank: Enable cross-encoder reranking

    Returns:
        Summary dict with aggregate metrics
    """
    # Load gold set
    with open(gold_set_path) as f:
        gold_set = json.load(f)

    queries = gold_set["queries"]
    targets = gold_set["_meta"]["target_metrics"]

    rerank_status = "ON" if rerank else "OFF"
    logger.info(f"Loaded {len(queries)} gold-set queries")
    logger.info(f"Target MRR: {targets['mrr']}, Target Recall@3: {targets['recall_at_3']}")
    logger.info(f"API: {api_url}")
    logger.info(f"Reranking: {rerank_status}\n")

    results: list[QueryResult] = []

    with httpx.Client() as client:
        for entry in queries:
            result = evaluate_query(client, api_url, entry, rerank=rerank)
            results.append(result)

            if verbose:
                status = "PASS" if result.reciprocal_rank > 0 else "MISS"
                logger.info(
                    f"  [{result.query_id}] {status} | "
                    f"RR={result.reciprocal_rank:.2f} "
                    f"R@3={result.recall_at_3:.2f} "
                    f"R@5={result.recall_at_5:.2f} | "
                    f"{result.query[:50]}"
                )
                if result.missing_paths:
                    logger.info(f"           Missing: {result.missing_paths}")

    # Compute aggregates
    metrics = _compute_aggregate_metrics(results)
    category_summary = _compute_category_metrics(queries, results)

    summary = {
        "total_queries": len(results),
        **metrics,
        "targets": targets,
        "meets_mrr_target": metrics["mrr"] >= targets["mrr"],
        "meets_recall_target": metrics["mean_recall_at_3"] >= targets["recall_at_3"],
        "categories": category_summary,
        "rerank_enabled": rerank,
    }

    return summary


def print_summary(summary: dict) -> None:
    """Print a formatted evaluation summary."""
    rerank_status = "ON" if summary.get("rerank_enabled", False) else "OFF"
    print("\n" + "=" * 60)
    print(f"CLEW ENGINE — RETRIEVAL QUALITY REPORT (Reranking: {rerank_status})")
    print("=" * 60)

    mrr_status = "PASS" if summary["meets_mrr_target"] else "FAIL"
    r3_status = "PASS" if summary["meets_recall_target"] else "FAIL"

    print(f"\n  Queries evaluated:  {summary['total_queries']}")
    print(f"  MRR:                {summary['mrr']:.4f}  (target: {summary['targets']['mrr']})  [{mrr_status}]")
    print(
        f"  Mean Recall@3:      {summary['mean_recall_at_3']:.4f}  "
        f"(target: {summary['targets']['recall_at_3']})  [{r3_status}]"
    )
    print(f"  Mean Recall@5:      {summary['mean_recall_at_5']:.4f}")
    print(f"  Hit Rate:           {summary['hit_rate']:.4f}")

    print("\n  Category Breakdown:")
    for cat, stats in summary["categories"].items():
        print(f"    {cat:25s}  n={stats['count']:2d}  MRR={stats['mrr']:.4f}")

    print("\n" + "=" * 60)

    if summary["meets_mrr_target"] and summary["meets_recall_target"]:
        print("  RESULT: ALL TARGETS MET — Ready for alpha.")
    else:
        print("  RESULT: TARGETS NOT MET — Consider reranker or tuning.")
        if not summary["meets_mrr_target"]:
            print(f"    - MRR {summary['mrr']:.4f} < {summary['targets']['mrr']} target")
        if not summary["meets_recall_target"]:
            print(f"    - Recall@3 {summary['mean_recall_at_3']:.4f} < {summary['targets']['recall_at_3']} target")

    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Measure Clew Engine retrieval quality against the gold set")
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
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-query results",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    rerank_group = parser.add_mutually_exclusive_group()
    rerank_group.add_argument(
        "--rerank",
        action="store_true",
        default=False,
        help="Enable cross-encoder reranking",
    )
    rerank_group.add_argument(
        "--no-rerank",
        action="store_false",
        dest="rerank",
        help="Disable cross-encoder reranking (default)",
    )
    args = parser.parse_args()

    summary = run_evaluation(args.api_url, args.gold_set, verbose=args.verbose, rerank=args.rerank)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_summary(summary)

    # Exit with non-zero if targets not met
    if not (summary["meets_mrr_target"] and summary["meets_recall_target"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
