"""Tests for the ArenaHarness orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from bench.arena import ArenaHarness, load_workload
from bench.engines.base import ContextResult
from bench.models import ExperimentResult, Judgement, TokenUsage, Workload


class FakeContextEngine:
    """Deterministic context engine for testing."""

    def __init__(self, context: str = "# fake context", token_count: int = 100):
        self._context = context
        self._token_count = token_count
        self.call_count = 0

    async def query(self, instruction: str) -> ContextResult:
        self.call_count += 1
        return ContextResult(
            context=self._context,
            token_count=self._token_count,
            sources=["fake.py"],
        )

    async def close(self) -> None:
        pass


class FakeCodingLLM:
    """Deterministic coding LLM for testing."""

    def __init__(self, code: str = "# generated", input_tokens: int = 500, output_tokens: int = 200):
        self._code = code
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    async def generate(self, instruction: str, success_criteria: str, context: str) -> tuple[str, TokenUsage]:
        return self._code, TokenUsage(input_tokens=self._input_tokens, output_tokens=self._output_tokens)

    async def close(self) -> None:
        pass


class FakeJudgeLLM:
    """Deterministic judge for testing."""

    def __init__(self, correctness: int = 4, efficiency: int = 4, hallucinations: list[str] | None = None):
        self._correctness = correctness
        self._efficiency = efficiency
        self._hallucinations = hallucinations or []

    async def evaluate(self, instruction: str, success_criteria: str, code: str) -> Judgement:
        return Judgement(
            correctness=self._correctness,
            efficiency=self._efficiency,
            hallucinations=self._hallucinations,
            comments="fake judgement",
        )

    async def close(self) -> None:
        pass


@pytest.fixture()
def sample_workload():
    return Workload.from_dict(
        {
            "workload_id": "test-wl",
            "description": "Test",
            "track": "python",
            "epics": [
                {
                    "epic_id": "E-1",
                    "title": "Test Epic",
                    "tickets": [
                        {"id": "T-1", "instruction": "Do A", "success_criteria": "A done", "trap": False},
                        {"id": "T-2", "instruction": "Refactor A", "success_criteria": "A refactored", "trap": True},
                    ],
                }
            ],
        }
    )


class TestArenaHarness:
    @pytest.mark.asyncio()
    async def test_run_experiment_basic(self, sample_workload):
        control_engine = FakeContextEngine(context="# rag context", token_count=500)
        test_engine = FakeContextEngine(context="# clew context", token_count=50)
        coding = FakeCodingLLM()
        judge = FakeJudgeLLM()

        harness = ArenaHarness(
            workload=sample_workload,
            clew_engine=test_engine,
            standard_engine=control_engine,
            coding_llm=coding,
            judge=judge,
        )

        result = await harness.run_experiment(trial_number=1)

        assert isinstance(result, ExperimentResult)
        assert result.workload_id == "test-wl"
        assert result.trial_number == 1
        assert len(result.control.ticket_results) == 2
        assert len(result.test.ticket_results) == 2

    @pytest.mark.asyncio()
    async def test_engines_called_for_each_ticket(self, sample_workload):
        control_engine = FakeContextEngine()
        test_engine = FakeContextEngine()

        harness = ArenaHarness(
            workload=sample_workload,
            clew_engine=test_engine,
            standard_engine=control_engine,
            coding_llm=FakeCodingLLM(),
            judge=FakeJudgeLLM(),
        )

        await harness.run_experiment()

        assert control_engine.call_count == 2
        assert test_engine.call_count == 2

    @pytest.mark.asyncio()
    async def test_trap_tickets_tracked(self, sample_workload):
        harness = ArenaHarness(
            workload=sample_workload,
            clew_engine=FakeContextEngine(),
            standard_engine=FakeContextEngine(),
            coding_llm=FakeCodingLLM(),
            judge=FakeJudgeLLM(correctness=5),
        )

        result = await harness.run_experiment()

        assert result.test.refactor_total == 1
        assert result.test.refactor_successes == 1

    @pytest.mark.asyncio()
    async def test_compression_metrics(self, sample_workload):
        control_engine = FakeContextEngine(token_count=1000)
        test_engine = FakeContextEngine(token_count=100)

        harness = ArenaHarness(
            workload=sample_workload,
            clew_engine=test_engine,
            standard_engine=control_engine,
            coding_llm=FakeCodingLLM(input_tokens=2000),
            judge=FakeJudgeLLM(),
        )

        result = await harness.run_experiment()

        # Both agents use the same coding LLM with same tokens
        assert result.control.total_input_tokens == 4000  # 2 tickets * 2000
        assert result.test.total_input_tokens == 4000

    @pytest.mark.asyncio()
    async def test_hallucinations_tracked(self, sample_workload):
        harness = ArenaHarness(
            workload=sample_workload,
            clew_engine=FakeContextEngine(),
            standard_engine=FakeContextEngine(),
            coding_llm=FakeCodingLLM(),
            judge=FakeJudgeLLM(hallucinations=["import fake"]),
        )

        result = await harness.run_experiment()

        assert result.control.hallucination_count == 2
        assert result.test.hallucination_count == 2


class TestLoadWorkload:
    def test_load_auth_epic(self):
        path = Path(__file__).parent.parent.parent / "bench" / "workloads" / "auth_epic.json"
        workload = load_workload(path)
        assert workload.workload_id == "auth-epic-v1"
        assert len(workload.all_tickets) == 8

    def test_load_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            load_workload("/nonexistent/path.json")
