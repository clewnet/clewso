# Retrieval Quality Baseline Report

**Date:** 2026-02-12
**Test Run:** Initial baseline measurement
**Gold Set:** 44 queries across 15 categories

## Results

| Metric | Actual | Target | Status |
|--------|--------|--------|--------|
| **MRR** | 0.0256 | 0.7 | ❌ FAIL |
| **Recall@3** | 0.0114 | 0.8 | ❌ FAIL |
| **Recall@5** | 0.0114 | - | - |
| **Hit Rate** | 0.0455 | - | - |

## Key Findings

### ✅ Infrastructure Status
- Vector database: **10,953 points indexed**
- Embedding model: **text-embedding-3-small** (1536-dim, OpenAI)
- API: **Healthy and responding**
- Collection: **codebase** (Cosine distance)

### 🔴 Issues Identified
1. **Poor semantic matching**: Queries return test files instead of source files
2. **Low similarity scores**: 0.05-0.07 range (should be > 0.5 for good matches)
3. **Wrong granularity**: Indexed content may be code blocks rather than file-level context
4. **Only 2/44 queries** returned expected results

### Sample Query Analysis
- **Query**: "database connection setup"
  **Expected**: `packages/clew-api/src/config.py`
  **Got**: `packages/clew-ingestion/tests/test_parser.py` (score: 0.059)

- **Query**: "FastAPI router registration"
  **Expected**: `packages/clew-api/src/main.py`
  **Got**: `packages/clew-api/tests/adapters/test_neo4j.py` (score: 0.070)

## Recommendations

### Immediate Actions
1. **Re-index with better chunking**: Use file-level or larger semantic chunks
2. **Filter test files**: Exclude test/* from retrieval results or lower their rank
3. **Add metadata filtering**: Use file type/path filters to improve precision
4. **Consider reranking**: Add a reranker model to improve top-k results

### Future Enhancements
5. **Fine-tune embeddings**: Train on code-specific corpus
6. **Hybrid search**: Combine vector search with BM25 keyword matching
7. **Query expansion**: Add synonyms and code-specific terminology
8. **Context windows**: Index with surrounding code context

## Conclusion

The gold set measurement tool is **working correctly** and has established a baseline. The poor scores indicate real quality issues that need to be addressed before alpha release. This is a **blocker for Phase 2.1** and should be prioritized immediately.

**Status**: 🔴 **BLOCKED** - Retrieval quality below acceptable threshold
**Next Step**: Implement reindexing with improved chunking strategy
