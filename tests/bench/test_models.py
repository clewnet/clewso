"""Tests for bench data models."""

import json
from pathlib import Path

import pytest

from bench.models import (
    AgentStats,
    AgentType,
    ExperimentResult,
    Judgement,
    TicketResult,
    TokenUsage,
    Workload,
)


class TestTokenUsage:
    def test_total(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total == 150

    def test_defaults(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total == 0


class TestJudgement:
    def test_avg_score(self):
        j = Judgement(correctness=4, efficiency=5)
        assert j.avg_score == 4.5

    def test_avg_score_low(self):
        j = Judgement(correctness=1, efficiency=2, hallucinations=["import foo"])
        assert j.avg_score == 1.5

    def test_defaults(self):
        j = Judgement(correctness=3, efficiency=3)
        assert j.hallucinations == []
        assert j.comments == ""


class TestAgentStats:
    def _make_result(self, input_tokens=100, correctness=4, efficiency=4, hallucinations=None, is_trap=False):
        return TicketResult(
            ticket_id="T-1",
            agent_type=AgentType.CONTROL,
            code="# code",
            context="# context",
            context_tokens=50,
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=50),
            judgement=Judgement(
                correctness=correctness,
                efficiency=efficiency,
                hallucinations=hallucinations or [],
            ),
            is_trap=is_trap,
        )

    def test_total_tokens(self):
        stats = AgentStats(agent_type=AgentType.CONTROL)
        stats.ticket_results = [self._make_result(100), self._make_result(200)]
        assert stats.total_input_tokens == 300
        assert stats.total_output_tokens == 100

    def test_mean_quality(self):
        stats = AgentStats(agent_type=AgentType.TEST)
        stats.ticket_results = [
            self._make_result(correctness=5, efficiency=5),
            self._make_result(correctness=3, efficiency=3),
        ]
        assert stats.mean_quality == 4.0

    def test_hallucination_count(self):
        stats = AgentStats(agent_type=AgentType.CONTROL)
        stats.ticket_results = [
            self._make_result(hallucinations=["import foo", "bar()"]),
            self._make_result(hallucinations=[]),
            self._make_result(hallucinations=["baz"]),
        ]
        assert stats.hallucination_count == 3

    def test_hallucination_rate(self):
        stats = AgentStats(agent_type=AgentType.CONTROL)
        stats.ticket_results = [
            self._make_result(hallucinations=["import foo"]),
            self._make_result(hallucinations=[]),
            self._make_result(hallucinations=[]),
        ]
        assert stats.hallucination_rate == pytest.approx(1 / 3)

    def test_refactor_success(self):
        stats = AgentStats(agent_type=AgentType.TEST)
        stats.ticket_results = [
            self._make_result(correctness=5, is_trap=True),
            self._make_result(correctness=2, is_trap=True),
            self._make_result(correctness=4, is_trap=False),
        ]
        assert stats.refactor_total == 2
        assert stats.refactor_successes == 1  # Only correctness >= 4 counts

    def test_empty_stats(self):
        stats = AgentStats(agent_type=AgentType.TEST)
        assert stats.total_input_tokens == 0
        assert stats.mean_quality == 0.0
        assert stats.hallucination_rate == 0.0

    def test_to_dict(self):
        stats = AgentStats(agent_type=AgentType.TEST)
        stats.ticket_results = [self._make_result()]
        d = stats.to_dict()
        assert d["agent_type"] == "test"
        assert d["total_input_tokens"] == 100
        assert len(d["tickets"]) == 1


class TestWorkload:
    @pytest.fixture()
    def workload_data(self):
        return {
            "workload_id": "test-workload",
            "description": "Test workload",
            "track": "python-fastapi",
            "epics": [
                {
                    "epic_id": "E-1",
                    "title": "Test Epic",
                    "tickets": [
                        {
                            "id": "T-1",
                            "instruction": "Do something",
                            "success_criteria": "It works",
                            "trap": False,
                        },
                        {
                            "id": "T-2",
                            "instruction": "Refactor it",
                            "success_criteria": "Still works",
                            "trap": True,
                            "notes": "Trap ticket",
                        },
                    ],
                }
            ],
        }

    def test_from_dict(self, workload_data):
        w = Workload.from_dict(workload_data)
        assert w.workload_id == "test-workload"
        assert len(w.epics) == 1
        assert len(w.all_tickets) == 2
        assert w.trap_count == 1

    def test_ticket_fields(self, workload_data):
        w = Workload.from_dict(workload_data)
        trap = w.all_tickets[1]
        assert trap.id == "T-2"
        assert trap.trap is True
        assert trap.notes == "Trap ticket"

    def test_load_auth_epic(self):
        """Verify the actual workload file is valid."""
        path = Path(__file__).parent.parent.parent / "bench" / "workloads" / "auth_epic.json"
        with open(path) as f:
            data = json.load(f)
        w = Workload.from_dict(data)
        assert w.workload_id == "auth-epic-v1"
        assert len(w.epics) == 3
        assert w.trap_count == 2
        assert len(w.all_tickets) == 8


class TestExperimentResult:
    def test_compression_ratio(self):
        control = AgentStats(agent_type=AgentType.CONTROL)
        control.ticket_results = [
            TicketResult(
                ticket_id="T-1",
                agent_type=AgentType.CONTROL,
                code="",
                context="",
                context_tokens=0,
                usage=TokenUsage(input_tokens=10000, output_tokens=500),
            )
        ]
        test = AgentStats(agent_type=AgentType.TEST)
        test.ticket_results = [
            TicketResult(
                ticket_id="T-1",
                agent_type=AgentType.TEST,
                code="",
                context="",
                context_tokens=0,
                usage=TokenUsage(input_tokens=1000, output_tokens=500),
            )
        ]
        result = ExperimentResult(workload_id="test", control=control, test=test)
        assert result.compression_ratio == 10.0
        assert result.compression_pct == 90.0

    def test_to_dict(self):
        control = AgentStats(agent_type=AgentType.CONTROL)
        test = AgentStats(agent_type=AgentType.TEST)
        result = ExperimentResult(workload_id="test", control=control, test=test)
        d = result.to_dict()
        assert "workload_id" in d
        assert "compression_ratio" in d
        assert "control" in d
        assert "test" in d
