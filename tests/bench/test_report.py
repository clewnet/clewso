"""Tests for report generation."""

import json
import tempfile
from pathlib import Path

from bench.models import (
    AgentStats,
    AgentType,
    ExperimentResult,
    Judgement,
    TicketResult,
    TokenUsage,
)
from bench.report import (
    format_text_report,
    write_json_report,
    write_text_report,
)


def _make_result(
    control_input=10000,
    test_input=1000,
    control_correctness=3,
    test_correctness=5,
    control_hallucinations=None,
    test_hallucinations=None,
    is_trap=False,
) -> ExperimentResult:
    """Helper to build an ExperimentResult for testing."""
    control = AgentStats(agent_type=AgentType.CONTROL)
    control.ticket_results = [
        TicketResult(
            ticket_id="T-1",
            agent_type=AgentType.CONTROL,
            code="# control code",
            context="# control context",
            context_tokens=control_input,
            usage=TokenUsage(input_tokens=control_input, output_tokens=500),
            judgement=Judgement(
                correctness=control_correctness,
                efficiency=control_correctness,
                hallucinations=control_hallucinations or [],
            ),
            is_trap=is_trap,
        )
    ]
    test = AgentStats(agent_type=AgentType.TEST)
    test.ticket_results = [
        TicketResult(
            ticket_id="T-1",
            agent_type=AgentType.TEST,
            code="# test code",
            context="# test context",
            context_tokens=test_input,
            usage=TokenUsage(input_tokens=test_input, output_tokens=500),
            judgement=Judgement(
                correctness=test_correctness,
                efficiency=test_correctness,
                hallucinations=test_hallucinations or [],
            ),
            is_trap=is_trap,
        )
    ]
    return ExperimentResult(workload_id="test-wl", control=control, test=test)


class TestFormatTextReport:
    def test_contains_header(self):
        result = _make_result()
        report = format_text_report(result)
        assert "CLEW-BENCH RESULTS" in report

    def test_shows_token_usage(self):
        result = _make_result(control_input=10000, test_input=1000)
        report = format_text_report(result)
        assert "10,000" in report
        assert "1,000" in report

    def test_shows_compression_ratio(self):
        result = _make_result(control_input=10000, test_input=1000)
        report = format_text_report(result)
        assert "10.0x" in report
        assert "PASS" in report

    def test_shows_fail_when_below_target(self):
        result = _make_result(control_input=1000, test_input=500)
        report = format_text_report(result)
        assert "FAIL" in report

    def test_shows_quality_scores(self):
        result = _make_result(control_correctness=3, test_correctness=5)
        report = format_text_report(result)
        assert "QUALITY SCORES" in report

    def test_shows_hallucination_rate(self):
        result = _make_result(control_hallucinations=["foo", "bar"])
        report = format_text_report(result)
        assert "HALLUCINATION RATE" in report
        assert "2 total" in report

    def test_verdict_all_pass(self):
        result = _make_result(control_input=20000, test_input=1000)
        report = format_text_report(result)
        assert "ALL TARGETS MET" in report

    def test_verdict_fail(self):
        result = _make_result(control_input=1000, test_input=500)
        report = format_text_report(result)
        assert "TARGETS NOT MET" in report


class TestWriteJsonReport:
    def test_writes_valid_json(self):
        result = _make_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results" / "test.json"
            write_json_report(result, path)

            assert path.exists()
            with open(path) as f:
                data = json.load(f)
            assert data["workload_id"] == "test-wl"
            assert "compression_ratio" in data

    def test_creates_parent_dirs(self):
        result = _make_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "deep" / "nested" / "result.json"
            write_json_report(result, path)
            assert path.exists()


class TestWriteTextReport:
    def test_writes_text_file(self):
        result = _make_result()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.txt"
            write_text_report(result, path)

            assert path.exists()
            content = path.read_text()
            assert "CLEW-BENCH RESULTS" in content
