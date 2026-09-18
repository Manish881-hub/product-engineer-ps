"""T02+T03: registry validation seam + fixture-backed tools.

Covers the brief's "tool registration, selection, or argument validation"
category, plus the deterministic failure case get_metrics needs later.
"""
import pytest

from agent.registry import Registry, ToolSpec
from agent.tools import SERVICE_CATALOG, build_default_registry
from agent.types import ToolError, ToolValidationError


@pytest.fixture()
def reg() -> Registry:
    return build_default_registry()


def test_all_four_tools_registered(reg: Registry):
    names = [s.name for s in reg.list_specs()]
    assert names == ["get_metrics", "get_status", "search_kb", "search_logs"]


def test_unknown_tool_rejected(reg: Registry):
    with pytest.raises(ToolValidationError):
        reg.call("restart_service", {"service": "checkout-api"})


def test_missing_required_argument_rejected(reg: Registry):
    with pytest.raises(ToolValidationError):
        reg.call("get_metrics", {"service": "checkout-api"})


def test_wrong_type_rejected(reg: Registry):
    with pytest.raises(ToolValidationError):
        reg.call("get_status", {"service": 42})


def test_unexpected_argument_rejected(reg: Registry):
    with pytest.raises(ToolValidationError):
        reg.call("get_status", {"service": "checkout-api", "token": "abc"})


def test_disallowed_value_rejected(reg: Registry):
    with pytest.raises(ToolValidationError):
        reg.call("get_status", {"service": "no-such-svc"})


def test_search_logs_finds_checkout_errors(reg: Registry):
    res = reg.call(
        "search_logs",
        {"query": "timeout payments", "service": "checkout-api", "time_window": "1h"},
    )
    assert res.output["match_count"] >= 2
    assert any("payments-worker" in m["msg"] for m in res.output["matches"])


def test_get_metrics_returns_checkout_error_rate(reg: Registry):
    res = reg.call(
        "get_metrics",
        {"service": "checkout-api", "metric": "error_rate", "window": "15m"},
    )
    assert res.output["value"] == 12.4
    assert res.output["unit"] == "percent"


def test_get_metrics_for_down_worker_fails_transiently(reg: Registry):
    with pytest.raises(ToolError) as exc:
        reg.call(
            "get_metrics",
            {"service": "payments-worker", "metric": "error_rate", "window": "15m"},
        )
    assert exc.value.kind == "transient"


def test_unknown_kb_topic_rejected_at_validation(reg: Registry):
    assert "checkout-api" in SERVICE_CATALOG
    with pytest.raises(ToolValidationError) as exc:
        reg.call("search_kb", {"topic": "no-such-topic"})
    assert exc.value.kind == "validation"


def test_search_kb_returns_runbook(reg: Registry):
    res = reg.call("search_kb", {"topic": "checkout-timeout"})
    assert "payments-worker" in res.output["body"]
