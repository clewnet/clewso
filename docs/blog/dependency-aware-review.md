# Building a Dependency-Aware Code Reviewer: What Line-Level Tools Miss

*March 2026*

Every AI code review tool on the market does the same thing: read the diff, comment on the lines. "This function is too long." "Consider adding error handling." "Variable name is unclear." It's high-volume, low-signal noise that developers learn to skim past.

But that's not what a senior reviewer actually does. When an experienced engineer reviews a PR, they ask one question: **"What does this change break downstream?"**

That question requires a dependency graph. And until now, no open-source tool had one.

## The problem with line-level review

Here's a real example. I'm refactoring a Rust workspace called `monastic` — 10 crates, 191 files. The PR touches 30 files across 8 source modules: deleting a content module, changing a constructor from static to dynamic, updating function signatures, and migrating data from embedded arrays to CSV files.

A line-level tool (CodeRabbit, Copilot, etc.) would generate 50+ comments across those 30 files. "Consider adding documentation for this new struct." "This function has too many parameters." None of them would tell me the one thing I actually need to know: **did I update every caller of the functions I changed?**

## What a graph-based reviewer sees

[Clewso](https://clewso.sh) indexes your repo into a dependency graph (Neo4j) and embedding store (Qdrant). When you run `clewso review --staged`, it doesn't just read the diff — it queries the graph:

1. For each changed file, find every file that imports from it or calls its functions
2. Check whether those downstream consumers are *also changed in this diff*
3. If they are, read the consumer's changes to verify they accommodate the breakage
4. Send the full context (diff + consumer list + co-change annotations) to an LLM

The result isn't "this function is too long." It's: **"You changed the `process_tick` signature in `tick_handler.rs`. Two downstream files call it (`performance.rs`, `full_day.rs`). Both are also changed in this diff and have been updated to pass the new `Lectionary` parameter. SAFE."**

That's the review that matters.

## Five iterations to get it right

I didn't get here in one shot. Here's the actual progression across five review runs on the same 30-file PR, with the tool improving between each run:

### Run 1: Zero graph awareness

Every file returned SAFE with "0 downstream files found." The review tool was searching for graph nodes via vector similarity (Qdrant) instead of querying the actual dependency graph (Neo4j). Path mismatches meant it never found any nodes.

**Result**: 0/5 files correctly assessed. Useless.

### Run 2: Direct graph queries

Replaced the vector search with direct Neo4j Cypher queries. Three strategies: module-stem imports, function callers, and symbol imports. Now the tool found real dependencies.

But it swung too far — everything with downstream consumers was flagged HIGH, even when the consumers were updated in the same diff.

**Result**: 5/5 non-SAFE files found, but 4 false positives. Too noisy.

### Run 3: Same-diff awareness

Added co-change detection: if a downstream consumer is also modified in this diff, annotate it in the LLM prompt. The LLM can now see "this caller was updated too" and reason about whether the update addresses the breakage.

`tick_handler.rs` flipped from HIGH to SAFE with excellent reasoning: *"The downstream files `performance.rs` and `full_day.rs` already define their own `StubLectionary` implementations and have been updated to pass these as arguments to `process_tick`."*

**Result**: 2 false positives remain.

### Run 4: Deletion coherence

The remaining false positives were deletion cases: `content/mod.rs` was deleted, and all 7 files that imported from it were also deleted. The tool saw "7 downstream consumers" but couldn't tell they were being removed too.

Added deletion detection: files absent from disk but present in the diff are marked `**(DELETED in this diff)**` in the prompt. The system prompt now includes: *"If a file is deleted AND all consumers are also deleted, the removal is coordinated — flag SAFE."*

`content/mod.rs` flipped from HIGH to SAFE: *"The deletion of `mod.rs` and its contents is coordinated with the deletion of all its downstream consumers within the same diff."*

**Result**: 1 false positive remains.

### Run 5: Workspace detection + symbol grep

The last false positive: `lib.rs` removed `pub mod content`. The LLM hedged about "potential unseen external consumers." But this is a workspace-internal crate — no one outside the repo can import from it.

Added two verified signals: (1) check `Cargo.toml` for workspace membership, (2) grep the entire codebase for `::content` / `mod content` / `use content` references.

The LLM now sees:
```
# Analysis Notes (verified facts)
- This crate is a workspace member with path dependencies — no external consumers.
- Removed public symbol `content` has zero remaining references in the codebase.
```

**Result**: 0 false positives. Clean sweep.

## The final scorecard

| File | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|------|-------|-------|-------|-------|-------|
| `content/mod.rs` | SAFE ✗ | HIGH | HIGH | HIGH | **SAFE** ✓ |
| `lib.rs` | SAFE ✗ | HIGH | HIGH | HIGH | **SAFE** ✓ |
| `trappist.rs` | SAFE ✗ | HIGH | HIGH | **SAFE** ✓ | SAFE ✓ |
| `tick_handler.rs` | SAFE ✗ | HIGH | **SAFE** ✓ | SAFE ✓ | SAFE ✓ |
| `monk_object.rs` | SAFE ✓ | SAFE ✓ | SAFE ✓ | SAFE ✓ | SAFE ✓ |

From "every file is SAFE because I can't find the graph" to "every file is correctly assessed with evidence-based reasoning" in five iterations.

The `monk_object.rs` result is my favorite. It found 2 downstream consumers (`main.rs` and a test file), read their source code, verified that both already accommodate the new `lectionary` field, and concluded: *"No action needed as the change is safely encapsulated within the existing architecture and downstream files seem prepared for this change."* That's not a rubber stamp — it's a reasoned assessment with evidence.

## What this means for the review tool market

The AI code review market is split between **line-level commenters** (CodeRabbit, Copilot, Ellipsis) and **agentic assistants** (Cursor, Devin, Codex). Neither category does what a senior reviewer does: trace the dependency graph.

Clewso sits in a different quadrant entirely: **architectural understanding + self-hosted**. It doesn't tell you your variable names are bad. It tells you whether your refactor broke something downstream — and if all the callers are updated, it shuts up.

For a 30-file refactor, that's the difference between 50 noise comments and 0 false positives.

## Try it

```bash
uv tool install clewso
clewso init
clewso index ./your-repo
clewso review --staged
```

Open source. Local-first. AGPL-3.0.

**[clewso.sh](https://clewso.sh)** | **[GitHub](https://github.com/clewnet/clewso)**
