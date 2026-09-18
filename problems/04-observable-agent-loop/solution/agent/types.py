"""Domain contracts: the shared language of the loop.

These types are the highest seam in the design — tests, the model
adapters, the tool registry, and the orchestrator all speak through them.
Nothing here touches I/O, fixtures, or model heuristics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TOOL_CALL = "tool_call"
FINAL = "final"
STOP = "stop"
DECISION_KINDS = (TOOL_CALL, FINAL, STOP)


class ToolError(Exception):
    """A tool ran but failed. Carries a machine-readable kind.

    kind="transient"  -> may succeed later or via another source
                         (timeout, rate_limited, pipeline_unavailable).
    kind="permanent"  -> retrying identical args will not help
                         (not_found, unknown_topic).
    kind="validation" -> arguments failed registry validation; the model
                         should fix the arguments, not blindly retry.
    """

    def __init__(self, message: str, kind: str = "transient") -> None:
        super().__init__(message)
        self.kind = kind


class ToolValidationError(ToolError):
    """Raised by the registry when a tool call is malformed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, kind="validation")


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    tool: str
    arguments: Dict[str, Any]
    output: Dict[str, Any]


@dataclass(frozen=True)
class EvidenceItem:
    """One verbatim-grounded fact: which tool produced it and with what args."""

    source_tool: str
    arguments: Dict[str, Any]
    excerpt: str


@dataclass(frozen=True)
class FinalResponse:
    """Evidence (what tools said) kept separate from inference (what we think)."""

    evidence: List[EvidenceItem]
    conclusions: str
    recommendations: str = ""


@dataclass(frozen=True)
class Decision:
    """The only three things a model may ask the loop to do."""

    kind: str
    summary: str = ""
    tool_call: Optional[ToolCall] = None
    final: Optional[FinalResponse] = None
    stop_reason: str = ""

    @staticmethod
    def call(name: str, arguments: Dict[str, Any], summary: str = "") -> "Decision":
        if not name or not isinstance(name, str):
            raise ValueError("tool_call decision requires a non-empty tool name")
        if not isinstance(arguments, dict):
            raise ValueError("tool_call decision requires an arguments dict")
        return Decision(kind=TOOL_CALL, summary=summary,
                        tool_call=ToolCall(name=name, arguments=dict(arguments)))

    @staticmethod
    def finalize(final: FinalResponse, summary: str = "") -> "Decision":
        if not isinstance(final, FinalResponse) or not final.evidence:
            raise ValueError("final decision requires a FinalResponse with evidence")
        if not final.conclusions:
            raise ValueError("final decision requires conclusions")
        return Decision(kind=FINAL, summary=summary, final=final)

    @staticmethod
    def stop(reason: str, summary: str = "") -> "Decision":
        if not reason:
            raise ValueError("stop decision requires a reason")
        return Decision(kind=STOP, summary=summary, stop_reason=reason)


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunState:
    """Mutable accumulator owned by the orchestrator; models read it, never write it."""

    objective: str
    max_steps: int
    steps_used: int = 0
    evidence: List[EvidenceItem] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    attempted: List[str] = field(default_factory=list)  # fingerprints, in order

    def successful_tools(self) -> set:
        return {e.source_tool for e in self.evidence}

    def errored(self) -> List[Dict[str, Any]]:
        return list(self.errors)
