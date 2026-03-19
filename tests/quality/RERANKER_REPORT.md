# Reranker Benchmark Report

**Generated**: 2026-02-17 14:41:19
**API Endpoint**: `http://localhost:8000`
**Gold Set Size**: 44 queries

---

## Executive Summary

This report compares retrieval quality **with and without** cross-encoder reranking.

| Metric         | Baseline   | Reranked   | Lift        | Status         |
|----------------|------------|------------|-------------|----------------|
| **MRR**        | 0.5318    | 0.4719    |     -11.3% | ❌ NEGATIVE     |
| **Recall@3**   | 0.6250    | 0.5682    |      -9.1% | ❌ NEGATIVE     |
| **Recall@5**   | 0.6705    | 0.6136    |      -8.5% | ❌ NEGATIVE     |
| **Hit Rate**   | 0.7273    | 0.7500    |      +3.1% | N/A            |

---

## Success Criteria Assessment

### Quality Metrics (Primary)
- **MRR Lift > 5%**: ❌ NEGATIVE (-11.3%)
- **Recall@3 Lift > 5%**: ❌ NEGATIVE (-9.1%)
- **Recall@5 Lift > 3%**: ❌ NEGATIVE (-8.5%)

### Overall Verdict
❌ **NEGATIVE LIFT DETECTED** — Reranker degrades quality.

**Recommendation**: Investigate reranker configuration. Do NOT deploy.

---

## Category Breakdown

| Category | Baseline MRR | Reranked MRR | Lift | Count |
|----------|--------------|--------------|------|-------|
| agent-interface      | 0.1667 | 0.2500 |   +50.0% |   2 |
| architecture         | 0.5152 | 0.4192 |   -18.6% |  11 |
| configuration        | 1.0000 | 0.3333 |   -66.7% |   2 |
| core-feature         | 0.6429 | 0.4728 |   -26.5% |   7 |
| data-model           | 1.0000 | 1.0000 |    +0.0% |   1 |
| feature-discovery    | 0.1111 | 0.5000 |  +350.0% |   3 |
| infrastructure       | 0.4800 | 0.5000 |    +4.2% |   5 |
| ingestion            | 0.5000 | 0.4000 |   -20.0% |   3 |
| integration          | 1.0000 | 1.0000 |    +0.0% |   1 |
| observability        | 0.0000 | 0.0000 |      N/A |   1 |
| operations           | 0.5833 | 0.2381 |   -59.2% |   2 |
| reliability          | 1.0000 | 1.0000 |    +0.0% |   2 |
| security             | 0.5000 | 0.5000 |    +0.0% |   2 |
| testing              | 0.0000 | 0.0000 |      N/A |   1 |
| visualization        | 0.5000 | 1.0000 |  +100.0% |   1 |

---

## Configuration

- **Baseline**: Vector search only (rerank=False)
- **Experiment**: Vector search + Cross-Encoder reranking (rerank=True)
- **Target Metrics**: MRR ≥ 0.7, Recall@3 ≥ 0.8


---

## Raw Results

### Baseline (No Reranking)
```json
{
  "total_queries": 44,
  "mrr": 0.5318,
  "mean_recall_at_3": 0.625,
  "mean_recall_at_5": 0.6705,
  "hit_rate": 0.7273,
  "targets": {
    "mrr": 0.7,
    "recall_at_3": 0.8
  },
  "meets_mrr_target": false,
  "meets_recall_target": false,
  "categories": {
    "agent-interface": {
      "count": 2,
      "mrr": 0.1667
    },
    "architecture": {
      "count": 11,
      "mrr": 0.5152
    },
    "configuration": {
      "count": 2,
      "mrr": 1.0
    },
    "core-feature": {
      "count": 7,
      "mrr": 0.6429
    },
    "data-model": {
      "count": 1,
      "mrr": 1.0
    },
    "feature-discovery": {
      "count": 3,
      "mrr": 0.1111
    },
    "infrastructure": {
      "count": 5,
      "mrr": 0.48
    },
    "ingestion": {
      "count": 3,
      "mrr": 0.5
    },
    "integration": {
      "count": 1,
      "mrr": 1.0
    },
    "observability": {
      "count": 1,
      "mrr": 0.0
    },
    "operations": {
      "count": 2,
      "mrr": 0.5833
    },
    "reliability": {
      "count": 2,
      "mrr": 1.0
    },
    "security": {
      "count": 2,
      "mrr": 0.5
    },
    "testing": {
      "count": 1,
      "mrr": 0.0
    },
    "visualization": {
      "count": 1,
      "mrr": 0.5
    }
  },
  "rerank_enabled": false
}
```

### Experiment (With Reranking)
```json
{
  "total_queries": 44,
  "mrr": 0.4719,
  "mean_recall_at_3": 0.5682,
  "mean_recall_at_5": 0.6136,
  "hit_rate": 0.75,
  "targets": {
    "mrr": 0.7,
    "recall_at_3": 0.8
  },
  "meets_mrr_target": false,
  "meets_recall_target": false,
  "categories": {
    "agent-interface": {
      "count": 2,
      "mrr": 0.25
    },
    "architecture": {
      "count": 11,
      "mrr": 0.4192
    },
    "configuration": {
      "count": 2,
      "mrr": 0.3333
    },
    "core-feature": {
      "count": 7,
      "mrr": 0.4728
    },
    "data-model": {
      "count": 1,
      "mrr": 1.0
    },
    "feature-discovery": {
      "count": 3,
      "mrr": 0.5
    },
    "infrastructure": {
      "count": 5,
      "mrr": 0.5
    },
    "ingestion": {
      "count": 3,
      "mrr": 0.4
    },
    "integration": {
      "count": 1,
      "mrr": 1.0
    },
    "observability": {
      "count": 1,
      "mrr": 0.0
    },
    "operations": {
      "count": 2,
      "mrr": 0.2381
    },
    "reliability": {
      "count": 2,
      "mrr": 1.0
    },
    "security": {
      "count": 2,
      "mrr": 0.5
    },
    "testing": {
      "count": 1,
      "mrr": 0.0
    },
    "visualization": {
      "count": 1,
      "mrr": 1.0
    }
  },
  "rerank_enabled": true
}
```
