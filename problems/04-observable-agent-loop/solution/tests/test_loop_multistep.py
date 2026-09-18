"""T05: the generic loop — multi-step investigation with an ordered trace.

AC2 (multi-step) + AC3 (observable trace), driven by a deterministic
ScriptedModel so the loop mechanics are pinned without model behavior.
"""
from agent.loop import Orchestrator
from agent.model import ScriptedModel
from agent.tools import build_default_registry
from agent.types import Decision, EvidenceItem, FinalResponse


def _final() -> FinalResponse:
    return FinalResponse(
        evidence=[
            EvidenceItem(
                source_tool="search_logs",
                arguments={"service": "checkout-api"},
                excerpt="ERROR upstream timeout calling payments-worker",
            ),
            EvidenceItem(
                source_tool="get_metrics",
                arguments={"service": "checkout-api"},
                excerpt="checkout-api error_rate = 12.4percent over 15m",
            ),
        ],
        conclusions="Most likely cause: payments-worker is unhealthy.",
        recommendations="Page payments on-call.",
    )


def test_multistep_run_combines_two_sources():
    model = ScriptedModel([
        Decision.call(
            "search_logs",
            {"query": "timeout", "service": "checkout-api", "time_window": "1h"},
            summary="Need logs first.",
        ),
        Decision.call(
            "get_metrics",
            {"service": "checkout-api", "metric": "error_rate", "window": "15m"},
            summary="Confirm with metrics.",
        ),
        Decision.finalize(_final(), summary="Two sources agree."),
    ])
    outcome = Orchestrator(model, build_default_registry()).run(
        "Why is checkout failing?", max_steps=6
    )
    assert outcome.status == "completed"
    assert outcome.steps_used == 2
    assert outcome.tool_calls == 2
    assert outcome.model_calls == 3
    assert len(outcome.final.evidence) == 2


def test_trace_is_ordered_and_distinguishable():
    model = ScriptedModel([
        Decision.call(
            "search_logs",
            {"query": "timeout", "service": "checkout-api", "time_window": "1h"},
            summary="Need logs first.",
        ),
        Decision.finalize(_final(), summary="Done."),
    ])
    outcome = Orchestrator(model, build_default_registry()).run("q?", max_steps=6)
    kinds = outcome.trace.types()
    assert kinds == [
        "run_started",
        "model_decision",
        "tool_call",
        "tool_result",
        "model_decision",
        "final_response",
    ]
    seqs = [e.seq for e in outcome.trace.events]
    assert seqs == sorted(seqs) == list(range(len(seqs)))
    call = outcome.trace.events[2]
    assert call.payload["tool"] == "search_logs"
    assert call.payload["arguments"]["service"] == "checkout-api"
    result = outcome.trace.events[3]
    assert "output" in result.payload and "excerpt" in result.payload
