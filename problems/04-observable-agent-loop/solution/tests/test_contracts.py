"""T01: domain contracts — decisions, trace ordering, redaction.

Seam under test: agent.types + agent.trace (no tools, no model, no loop).
"""
import pytest

from agent.trace import TraceRecorder, redact
from agent.types import (
    Decision,
    EvidenceItem,
    FinalResponse,
    ToolCall,
    ToolError,
    TraceEvent,
)


def _evidence() -> list:
    return [
        EvidenceItem(
            source_tool="search_logs",
            arguments={"service": "checkout-api"},
            excerpt="ERROR upstream timeout calling payments-worker",
        )
    ]


def test_tool_call_decision_requires_name_and_args():
    d = Decision.call("search_logs", {"service": "checkout-api"}, summary="need logs")
    assert d.kind == "tool_call"
    assert isinstance(d.tool_call, ToolCall)
    assert d.tool_call.name == "search_logs"
    assert d.tool_call.arguments["service"] == "checkout-api"


def test_tool_call_decision_rejects_empty_name():
    with pytest.raises(ValueError):
        Decision.call("", {}, summary="bad")


def test_final_decision_requires_evidence():
    with pytest.raises(ValueError):
        Decision.finalize(
            FinalResponse(evidence=[], conclusions="nothing", recommendations=""),
            summary="empty",
        )


def test_final_decision_holds_evidence_and_conclusions():
    final = FinalResponse(
        evidence=_evidence(),
        conclusions="payments-worker looks down",
        recommendations="follow the checkout-timeout runbook",
    )
    d = Decision.finalize(final, summary="enough evidence")
    assert d.kind == "final"
    assert d.final.conclusions != ""
    assert len(d.final.evidence) == 1


def test_stop_decision_requires_reason():
    with pytest.raises(ValueError):
        Decision.stop("", summary="no reason")
    d = Decision.stop("max_steps_exceeded", summary="budget gone")
    assert d.kind == "stop"
    assert d.stop_reason == "max_steps_exceeded"


def test_trace_events_are_ordered_and_typed():
    rec = TraceRecorder()
    rec.record("run_started", objective="q", max_steps=6)
    rec.record("model_decision", summary="s")
    rec.record("tool_call", tool="search_logs", arguments={})
    types = [e.type for e in rec.events]
    assert types == ["run_started", "model_decision", "tool_call"]
    assert [e.seq for e in rec.events] == [0, 1, 2]
    assert isinstance(rec.events[0], TraceEvent)


def test_trace_rejects_unknown_event_type():
    rec = TraceRecorder()
    with pytest.raises(ValueError):
        rec.record("hidden_chain_of_thought", text="must never exist")


def test_redact_masks_secret_keys_recursively():
    payload = {
        "service": "checkout-api",
        "api_token": "sk-live-123",
        "nested": {"password": "hunter2", "count": 3},
    }
    out = redact(payload)
    assert out["service"] == "checkout-api"
    assert out["api_token"] == "***REDACTED***"
    assert out["nested"]["password"] == "***REDACTED***"
    assert out["nested"]["count"] == 3


def test_tool_error_carries_kind():
    err = ToolError("metrics pipeline unavailable", kind="transient")
    assert err.kind == "transient"
    assert "unavailable" in str(err)
