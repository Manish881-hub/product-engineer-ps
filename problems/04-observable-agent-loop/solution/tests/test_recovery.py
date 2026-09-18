"""T06: deliberate failure handling — visible error, then recovery or a
clear stop (AC4). Scripted paths pin the mechanics; the heuristic path
proves the real model recovers from the metrics outage on its own.
"""
from agent.loop import Orchestrator
from agent.model import HeuristicModel, ScriptedModel
from agent.tools import build_default_registry
from agent.types import Decision, EvidenceItem, FinalResponse


def _final_from_status() -> FinalResponse:
    return FinalResponse(
        evidence=[
            EvidenceItem(
                source_tool="get_status",
                arguments={"service": "payments-worker"},
                excerpt="payments-worker is down: crash-looping",
            ),
            EvidenceItem(
                source_tool="search_logs",
                arguments={"service": "checkout-api"},
                excerpt="ERROR upstream timeout calling payments-worker",
            ),
        ],
        conclusions="Most likely cause: payments-worker is unhealthy.",
        recommendations="Page payments on-call.",
    )


def test_transient_failure_is_visible_then_recovered():
    model = ScriptedModel([
        Decision.call(
            "get_metrics",
            {"service": "payments-worker", "metric": "error_rate", "window": "15m"},
            summary="Try victim metrics first.",
        ),
        Decision.call(
            "get_status", {"service": "payments-worker"}, summary="Fall back to status."
        ),
        Decision.call(
            "search_logs",
            {"query": "timeout", "service": "checkout-api", "time_window": "1h"},
            summary="Corroborate with logs.",
        ),
        Decision.finalize(_final_from_status(), summary="Recovered via status+logs."),
    ])
    outcome = Orchestrator(model, build_default_registry()).run(
        "Why is checkout failing?", max_steps=6
    )
    assert outcome.status == "completed"
    errors = [e for e in outcome.trace.events if e.type == "tool_error"]
    assert len(errors) == 1
    assert errors[0].payload["kind"] == "transient"
    assert errors[0].payload["tool"] == "get_metrics"
    assert outcome.tool_calls == 2  # the failed call never became evidence


def test_validation_failure_is_visible_then_recovered():
    model = ScriptedModel([
        Decision.call(
            "get_status",
            {"service": "checkout-api", "bogus": True},
            summary="Malformed call.",
        ),
        Decision.call(
            "get_status", {"service": "checkout-api"}, summary="Fixed arguments."
        ),
        Decision.finalize(
            FinalResponse(
                evidence=[
                    EvidenceItem(
                        source_tool="get_status",
                        arguments={"service": "checkout-api"},
                        excerpt="checkout-api is degraded",
                    )
                ],
                conclusions="c",
                recommendations="r",
            ),
            summary="Done.",
        ),
    ])
    outcome = Orchestrator(model, build_default_registry()).run("q?", max_steps=6)
    kinds = [e.payload.get("kind") for e in outcome.trace.events if e.type == "tool_error"]
    assert kinds == ["validation"]
    assert outcome.status == "completed"


def test_heuristic_recovers_from_metrics_outage_alone():
    outcome = Orchestrator(HeuristicModel(), build_default_registry()).run(
        "Is payments-worker error_rate spiking?", max_steps=6
    )
    assert outcome.status == "completed"
    kinds = [e.type for e in outcome.trace.events]
    assert "tool_error" in kinds  # the outage is on the record
    assert kinds[-1] == "final_response"
    tools = {e.source_tool for e in outcome.final.evidence}
    assert len(tools) >= 2
