"""T04: the model seam — scripted replay + heuristic policy.

The loop (T05) will treat both adapters identically; these tests pin the
decision behavior each adapter promises.
"""
import pytest

from agent.model import HeuristicModel, ScriptedModel, keywords
from agent.registry import fingerprint
from agent.types import Decision, EvidenceItem, FinalResponse, RunState


def _state(**kw) -> RunState:
    base = {"objective": "Why is checkout failing?", "max_steps": 6}
    base.update(kw)
    return RunState(**base)


def _ev(tool: str, excerpt: str, service: str = "checkout-api") -> EvidenceItem:
    return EvidenceItem(
        source_tool=tool, arguments={"service": service}, excerpt=excerpt
    )


def test_scripted_model_replays_then_stops():
    script = [
        Decision.call("search_logs", {"service": "x"}, summary="first"),
        Decision.call("get_status", {"service": "x"}, summary="second"),
    ]
    model = ScriptedModel(script)
    state = _state()
    assert model.decide(state).tool_call.name == "search_logs"
    assert model.decide(state).tool_call.name == "get_status"
    tail = model.decide(state)
    assert tail.kind == "stop" and tail.stop_reason == "script_exhausted"
    assert model.calls == 3


def test_heuristic_picks_logs_for_checkout_question():
    d = HeuristicModel().decide(_state())
    assert d.kind == "tool_call"
    assert d.tool_call.name == "search_logs"
    assert d.tool_call.arguments["service"] == "checkout-api"
    assert d.summary != ""


def test_heuristic_honors_status_intent():
    d = HeuristicModel().decide(
        _state(objective="What is the status of inventory-svc?")
    )
    assert d.tool_call.name == "get_status"
    assert d.tool_call.arguments["service"] == "inventory-svc"


def test_heuristic_avoids_repeating_errored_call():
    model = HeuristicModel()
    state = _state()
    first = model.decide(state)
    assert first.tool_call.name == "search_logs"
    # Simulate the loop having run logs ok, then metrics failing for primary.
    fp_logs = fingerprint("search_logs", first.tool_call.arguments)
    metrics_args = {"service": "checkout-api", "metric": "error_rate", "window": "15m"}
    state.evidence.append(
        _ev("search_logs", "ERROR upstream timeout calling payments-worker")
    )
    state.attempted.extend([fp_logs, fingerprint("get_metrics", metrics_args)])
    state.errors.append(
        {"tool": "get_metrics", "arguments": metrics_args, "kind": "transient"}
    )
    nxt = model.decide(state)
    assert nxt.kind == "tool_call"
    assert fingerprint(nxt.tool_call.name, nxt.tool_call.arguments) not in set(
        state.attempted
    )


def test_heuristic_finalizes_from_collected_evidence():
    model = HeuristicModel()
    state = _state(
        evidence=[
            _ev("search_logs", "ERROR upstream timeout calling payments-worker"),
            _ev("get_status", "payments-worker is down: crash-looping", service="payments-worker"),
        ]
    )
    d = model.decide(state)
    # logs+status known; metrics+kb untried -> still investigating
    assert d.kind == "tool_call"
    state.evidence.extend([
        _ev("get_metrics", "checkout-api error_rate = 12.4percent over 15m"),
        _ev("search_kb", "runbook 'Checkout authorize timeouts runbook'", service=""),
    ])
    done = model.decide(state)
    assert done.kind == "final"
    assert "payments-worker" in done.final.conclusions
    assert len(done.final.evidence) == 4


def test_heuristic_stops_when_everything_tried_without_evidence():
    model = HeuristicModel()
    state = _state()
    state.attempted.extend(
        fingerprint(name, args) for name, args, _ in model._candidates(state)
    )
    d = model.decide(state)
    assert d.kind == "stop"
    assert d.stop_reason == "insufficient_evidence"


def test_keywords_skips_stopwords():
    assert "checkout" in keywords("Why is checkout failing?")
