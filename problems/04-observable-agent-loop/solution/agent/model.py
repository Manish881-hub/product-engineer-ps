"""Model adapters behind one interface.

The orchestrator never branches on which model it holds: it asks for the
next structured decision given the objective plus accumulated evidence.
``HeuristicModel`` is the deterministic local stand-in used by the CLI;
``ScriptedModel`` replays canned decisions so tests never touch a live model.
A provider-backed LLM would be a third adapter — the loop would not change.
"""
from __future__ import annotations

import abc
import re
from typing import Any, Dict, List, Optional, Tuple

from .registry import fingerprint
from .tools import SERVICE_CATALOG
from .types import Decision, EvidenceItem, FinalResponse, RunState

STOPWORDS = {
    "the", "and", "for", "with", "what", "why", "how", "are", "our",
    "was", "were", "has", "have", "had", "this", "that", "from", "into",
    "failing", "failed", "fail", "wrong", "with", "about", "please",
}

INTENT_STATUS = ("status", "health", "healthy", "down", "degraded")
INTENT_METRICS = ("metric", "error_rate", "error rate", "latency", "p95", "throughput", "spike")
INTENT_KB = ("runbook", "playbook", "docs", "documentation", "how to", "guide")


class Model(abc.ABC):
    """Decides the next step from state. Reads state; never mutates it."""

    @abc.abstractmethod
    def decide(self, state: RunState) -> Decision:
        raise NotImplementedError


class ScriptedModel(Model):
    """Deterministic replay for tests. Counts calls so tests can prove
    the loop made no extra model call after a limit."""

    def __init__(self, script: List[Decision]) -> None:
        self._script = list(script)
        self.calls = 0

    def decide(self, state: RunState) -> Decision:
        self.calls += 1
        if self._script:
            return self._script.pop(0)
        return Decision.stop("script_exhausted", summary="test script exhausted")


def keywords(objective: str, limit: int = 6) -> str:
    words: List[str] = []
    for raw in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", objective.lower()):
        if len(raw) > 2 and raw not in STOPWORDS and raw not in words:
            words.append(raw)
    return " ".join(words[:limit]) or "error"


def _has_any(text: str, phrases: Tuple[str, ...]) -> bool:
    return any(p in text for p in phrases)


def _metric_for(text: str) -> str:
    if "latency" in text or "p95" in text:
        return "latency_p95_ms"
    if "throughput" in text or "rps" in text:
        return "throughput_rps"
    return "error_rate"


def _topic_for(text: str) -> str:
    if "retr" in text:
        return "payment-retries"
    return "checkout-timeout"


class HeuristicModel(Model):
    """Deterministic local policy: intent fast-path, then logs -> metrics ->
    status -> runbook, skipping anything already tried or already known,
    and finalizing only from collected evidence."""

    def __init__(self, services: Optional[List[str]] = None) -> None:
        self.services = list(services or SERVICE_CATALOG)

    def decide(self, state: RunState) -> Decision:
        attempted = set(state.attempted)
        known = state.successful_tools()
        for name, args, summary in self._candidates(state):
            if name in known:
                continue
            if fingerprint(name, args) in attempted:
                continue
            return Decision.call(name, args, summary=summary)
        if state.evidence:
            primary, implicated = self._subjects(state)
            return Decision.finalize(
                self._finalize(state, primary, implicated),
                summary=f"Evidence from {len(known)} sources; answering.",
            )
        return Decision.stop(
            "insufficient_evidence",
            summary="Every source was tried without usable evidence.",
        )

    def _subjects(self, state: RunState) -> Tuple[str, List[str]]:
        low_obj = state.objective.lower()
        mentioned = [s for s in self.services if s in low_obj]
        primary = mentioned[0] if mentioned else "checkout-api"
        blob = " ".join(e.excerpt for e in state.evidence).lower() + " " + low_obj
        implicated = [s for s in self.services if s != primary and s in blob]
        return primary, implicated

    def _candidates(self, state: RunState) -> List[Tuple[str, Dict[str, Any], str]]:
        primary, implicated = self._subjects(state)
        low = state.objective.lower()
        cands: List[Tuple[str, Dict[str, Any], str]] = []
        if _has_any(low, INTENT_STATUS):
            cands.append((
                "get_status", {"service": primary},
                f"Check the current status of {primary}.",
            ))
        elif _has_any(low, INTENT_METRICS):
            cands.append((
                "get_metrics",
                {"service": primary, "metric": _metric_for(low), "window": "15m"},
                f"Check {primary} metrics first, as asked.",
            ))
        elif _has_any(low, INTENT_KB):
            cands.append((
                "search_kb", {"topic": _topic_for(low)},
                "Look up the requested runbook guidance.",
            ))
        cands.append((
            "search_logs",
            {"query": keywords(state.objective), "service": primary, "time_window": "1h"},
            f"Search {primary} logs for failure signals.",
        ))
        metric_target = primary
        if self._errored_for(state, "get_metrics", primary):
            metric_target = implicated[0] if implicated else "inventory-svc"
        cands.append((
            "get_metrics",
            {"service": metric_target, "metric": "error_rate", "window": "15m"},
            f"Check error-rate metrics for {metric_target}.",
        ))
        status_target = implicated[0] if implicated else primary
        cands.append((
            "get_status", {"service": status_target},
            f"Read the health status of {status_target}.",
        ))
        blob = " ".join(e.excerpt for e in state.evidence) + " " + state.objective
        cands.append((
            "search_kb", {"topic": _topic_for(blob.lower())},
            "Look up the matching incident runbook.",
        ))
        return cands

    @staticmethod
    def _errored_for(state: RunState, tool: str, service: str) -> bool:
        return any(
            e.get("tool") == tool and e.get("arguments", {}).get("service") == service
            for e in state.errors
        )

    def _finalize(
        self, state: RunState, primary: str, implicated: List[str]
    ) -> FinalResponse:
        evidence = list(state.evidence)
        cause = self._likely_cause(evidence, primary, implicated)
        sources = sorted({e.source_tool for e in evidence})
        conclusions = (
            f"Most likely cause: {cause} is unhealthy. "
            f"Grounded in {len(evidence)} evidence items from "
            f"{', '.join(sources)}."
        )
        kb_hit = next(
            (e for e in evidence if e.source_tool == "search_kb"), None
        )
        if kb_hit:
            recommendations = (
                "Follow the retrieved runbook guidance (quoted in evidence): "
                "confirm the down dependency, shed authorize retries, and page "
                "the owning on-call before raising timeouts."
            )
        else:
            recommendations = (
                f"Restore {cause} to healthy, then watch {primary} error_rate "
                "fall back under 1% over 15m before closing out."
            )
        return FinalResponse(
            evidence=evidence,
            conclusions=conclusions,
            recommendations=recommendations,
        )

    @staticmethod
    def _likely_cause(
        evidence: List[EvidenceItem], primary: str, implicated: List[str]
    ) -> str:
        for e in evidence:
            if e.source_tool == "get_status":
                text = e.excerpt.lower()
                for svc in SERVICE_CATALOG:
                    if svc in text and (" is down" in text or "degraded" in text):
                        return svc
        if implicated:
            return implicated[0]
        return primary
