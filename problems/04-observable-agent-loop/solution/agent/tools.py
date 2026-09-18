"""Fixture-backed evidence tools. Read-only, deterministic, no network.

The deliberate failure: the metrics pipeline has no data for
``payments-worker`` (it went down with the worker's host), so
``get_metrics`` for that service raises a transient ToolError. The loop
must observe the failure and recover through another source.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from .registry import Registry, ToolSpec
from .types import ToolError

SERVICE_CATALOG = ["checkout-api", "payments-worker", "inventory-svc"]

# Services whose metrics pipeline is down: deterministic, data-driven failure.
METRICS_OUTAGE = {"payments-worker": "metrics pipeline unreachable for 'payments-worker' (collector went down with the worker host)"}

METRIC_NAMES = ["error_rate", "latency_p95_ms", "throughput_rps"]
WINDOWS = ["5m", "15m", "1h"]
KB_TOPICS = ["checkout-timeout", "payment-retries"]

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_cache: Dict[str, Any] = {}


def load_fixture(name: str) -> Any:
    if name not in _cache:
        path = os.path.join(_FIXTURE_DIR, f"{name}.json")
        with open(path, encoding="utf-8") as fh:
            _cache[name] = json.load(fh)
    return _cache[name]


def _tokens(query: str) -> List[str]:
    return [t for t in query.lower().split() if len(t) > 2]


def search_logs(args: Dict[str, Any]) -> Dict[str, Any]:
    logs = load_fixture("logs")
    service = args["service"]
    if service not in logs:
        raise ToolError(f"no logs for unknown service {service!r}", kind="permanent")
    query = args.get("query", "")
    toks = _tokens(query)
    matches = [
        e for e in logs[service]
        if not toks or any(t in e["msg"].lower() for t in toks)
    ]
    return {
        "service": service,
        "query": query,
        "time_window": args.get("time_window", "1h"),
        "match_count": len(matches),
        "matches": matches[:10],
    }


def get_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    service = args["service"]
    if service in METRICS_OUTAGE:
        raise ToolError(METRICS_OUTAGE[service], kind="transient")
    metrics = load_fixture("metrics")
    if service not in metrics:
        raise ToolError(f"no metrics for unknown service {service!r}", kind="permanent")
    metric = args["metric"]
    window = args.get("window", "15m")
    series = metrics[service].get(metric, {})
    if window not in series:
        raise ToolError(
            f"metric {metric!r} has no {window!r} window for {service!r}",
            kind="permanent",
        )
    return {
        "service": service,
        "metric": metric,
        "window": window,
        "value": series[window],
        "unit": series.get("unit", ""),
    }


def get_status(args: Dict[str, Any]) -> Dict[str, Any]:
    statuses = load_fixture("status")
    service = args["service"]
    if service not in statuses:
        raise ToolError(f"no status for unknown service {service!r}", kind="permanent")
    return {"service": service, **statuses[service]}


def search_kb(args: Dict[str, Any]) -> Dict[str, Any]:
    kb = load_fixture("kb")
    topic = args["topic"]
    if topic not in kb:
        raise ToolError(
            f"unknown topic {topic!r}; available: {', '.join(sorted(kb))}",
            kind="permanent",
        )
    return {"topic": topic, **kb[topic]}


def summarize(tool: str, output: Dict[str, Any]) -> str:
    """One-line operational excerpt of a tool output for evidence + trace."""
    if tool == "search_logs":
        matches = output.get("matches", [])
        if not matches:
            return (
                f"0 matches in {output['service']} logs "
                f"({output.get('time_window', '1h')}) for query "
                f"'{output.get('query', '')}'"
            )
        top = next(
            (m for m in matches if m.get("level") == "ERROR"), matches[0]
        )
        return (
            f"{output['match_count']} matches in {output['service']} logs; "
            f"top: [{top['level']}] {top['msg']}"
        )
    if tool == "get_metrics":
        unit = output.get("unit", "")
        value = f"{output['value']} {unit}".strip()
        return (
            f"{output['service']} {output['metric']} = "
            f"{value} over {output['window']}"
        )
    if tool == "get_status":
        return (
            f"{output['service']} is {output['state']}: {output['detail']}"
        )
    if tool == "search_kb":
        return f"runbook '{output['title']}': {output['body']}"
    return str(output)


def build_default_registry() -> Registry:
    reg = Registry()
    reg.register(
        ToolSpec(
            name="search_logs",
            description="Search application logs for a service (OR over query tokens).",
            required=["query", "service"],
            optional=["time_window"],
            types={"query": str, "service": str, "time_window": str},
            allowed={"service": SERVICE_CATALOG, "time_window": WINDOWS},
        ),
        search_logs,
    )
    reg.register(
        ToolSpec(
            name="get_metrics",
            description="Look up a service metric over a window.",
            required=["service", "metric"],
            optional=["window"],
            types={"service": str, "metric": str, "window": str},
            allowed={
                "service": SERVICE_CATALOG,
                "metric": METRIC_NAMES,
                "window": WINDOWS,
            },
        ),
        get_metrics,
    )
    reg.register(
        ToolSpec(
            name="get_status",
            description="Read the current health status of a service.",
            required=["service"],
            optional=[],
            types={"service": str},
            allowed={"service": SERVICE_CATALOG},
        ),
        get_status,
    )
    reg.register(
        ToolSpec(
            name="search_kb",
            description="Search the incident knowledge base by topic.",
            required=["topic"],
            optional=[],
            types={"topic": str},
            allowed={"topic": KB_TOPICS},
        ),
        search_kb,
    )
    return reg
