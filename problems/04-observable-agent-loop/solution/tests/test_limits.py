"""T07: hard execution limits (AC5).

The loop checks the budget BEFORE asking the model, so a capped run makes
no further model call and no further tool call, and says why it stopped.
"""
from agent.loop import MAX_STEPS_EXCEEDED, Orchestrator
from agent.model import ScriptedModel
from agent.tools import build_default_registry
from agent.types import Decision


def _always_tools(n: int = 5):
    return [
        Decision.call(
            "search_logs",
            {"query": f"q{i}", "service": "checkout-api", "time_window": "1h"},
            summary=f"tool {i}",
        )
        for i in range(n)
    ]


def test_limit_stops_without_extra_model_or_tool_call():
    model = ScriptedModel(_always_tools())
    outcome = Orchestrator(model, build_default_registry()).run(
        "Why is checkout failing?", max_steps=2
    )
    assert outcome.status == "stopped"
    assert outcome.reason == MAX_STEPS_EXCEEDED
    assert outcome.final is None
    assert outcome.steps_used == 2
    assert model.calls == 2, "no model call may follow the exhausted budget"
    assert outcome.tool_calls == 2, "no tool call may follow the exhausted budget"
    assert outcome.trace.types()[-1] == "stopped"
    assert outcome.trace.events[-1].payload["reason"] == MAX_STEPS_EXCEEDED


def test_model_requested_stop_is_honored():
    model = ScriptedModel([Decision.stop("insufficient_evidence", summary="dry wells")])
    outcome = Orchestrator(model, build_default_registry()).run("q?", max_steps=6)
    assert outcome.status == "stopped"
    assert outcome.reason == "insufficient_evidence"
    assert outcome.tool_calls == 0
