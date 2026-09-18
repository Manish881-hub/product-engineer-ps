"""Ordered operational trace. No hidden chain-of-thought, no secrets."""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

from .types import TraceEvent

RUN_STARTED = "run_started"
MODEL_DECISION = "model_decision"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
TOOL_ERROR = "tool_error"
FINAL_RESPONSE = "final_response"
STOPPED = "stopped"

EVENT_TYPES = (
    RUN_STARTED,
    MODEL_DECISION,
    TOOL_CALL,
    TOOL_RESULT,
    TOOL_ERROR,
    FINAL_RESPONSE,
    STOPPED,
)

_REDACTED = "***REDACTED***"
_SENSITIVE_SUBSTRINGS = ("token", "secret", "password", "api_key", "apikey", "authorization")


def redact(obj: Any) -> Any:
    """Recursively mask values whose key looks like a credential."""
    if isinstance(obj, dict):
        return {
            k: (_REDACTED if _is_sensitive(k) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def _is_sensitive(key: Any) -> bool:
    name = str(key).lower().replace("-", "_")
    return any(part in name for part in _SENSITIVE_SUBSTRINGS)


class TraceRecorder:
    """Append-only, sequence-numbered record of what the run did."""

    def __init__(self) -> None:
        self._events: List[TraceEvent] = []

    def record(self, event_type: str, **payload: Any) -> TraceEvent:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown trace event type: {event_type!r}")
        event = TraceEvent(
            seq=len(self._events),
            type=event_type,
            payload=copy.deepcopy(redact(payload)),
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> List[TraceEvent]:
        return list(self._events)

    def to_jsonl(self) -> str:
        lines = [
            json.dumps(
                {"seq": e.seq, "type": e.type, "payload": e.payload},
                sort_keys=True,
            )
            for e in self._events
        ]
        return "\n".join(lines) + ("\n" if lines else "")

    def write_jsonl(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_jsonl())

    def types(self) -> List[str]:
        return [e.type for e in self._events]
