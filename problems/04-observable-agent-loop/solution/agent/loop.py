"""The generic control loop. Owns steps, termination, state, and trace.

The loop never decides *what* to do next — it asks the model. It only
enforces *how* execution proceeds: validate, execute, record, repeat,
and stop exactly when told to or when the budget is gone.

Termination, in order:
  1. ``final``   -> record final_response, outcome completed.
  2. ``stop``    -> record stopped with the model's reason.
  3. budget gone -> record stopped(max_steps_exceeded) BEFORE asking the
     model again, so a capped run makes no further model or tool call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .model import Model
from .registry import Registry, fingerprint
from .tools import summarize
from .trace import (
    FINAL_RESPONSE,
    MODEL_DECISION,
    RUN_STARTED,
    STOPPED,
    TOOL_CALL,
    TOOL_ERROR,
    TOOL_RESULT,
    TraceRecorder,
)
from .types import (
    FINAL,
    STOP,
    TOOL_CALL as DECISION_TOOL_CALL,
    EvidenceItem,
    FinalResponse,
    RunState,
    ToolError,
    ToolValidationError,
)

COMPLETED = "completed"
STOPPED_STATUS = "stopped"
MAX_STEPS_EXCEEDED = "max_steps_exceeded"


@dataclass
class RunOutcome:
    status: str  # completed | stopped
    reason: str
    final: Optional[FinalResponse]
    trace: TraceRecorder
    steps_used: int
    model_calls: int
    tool_calls: int


class Orchestrator:
    def __init__(self, model: Model, registry: Registry) -> None:
        self.model = model
        self.registry = registry

    def run(self, objective: str, max_steps: int = 6) -> RunOutcome:
        if not objective or not objective.strip():
            raise ValueError("objective must be a non-empty question")
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        trace = TraceRecorder()
        state = RunState(objective=objective, max_steps=max_steps)
        trace.record(RUN_STARTED, objective=objective, max_steps=max_steps)
        model_calls = 0
        tool_calls = 0

        while True:
            # AC5: the budget check happens BEFORE the next model call.
            if state.steps_used >= max_steps:
                trace.record(
                    STOPPED, reason=MAX_STEPS_EXCEEDED, steps_used=state.steps_used
                )
                return RunOutcome(
                    status=STOPPED_STATUS,
                    reason=MAX_STEPS_EXCEEDED,
                    final=None,
                    trace=trace,
                    steps_used=state.steps_used,
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                )

            decision = self.model.decide(state)
            model_calls += 1

            if decision.kind == FINAL:
                assert decision.final is not None
                trace.record(
                    MODEL_DECISION, summary=decision.summary, decision="final"
                )
                trace.record(
                    FINAL_RESPONSE,
                    evidence=[e.__dict__ for e in decision.final.evidence],
                    conclusions=decision.final.conclusions,
                    recommendations=decision.final.recommendations,
                )
                return RunOutcome(
                    status=COMPLETED,
                    reason="final",
                    final=decision.final,
                    trace=trace,
                    steps_used=state.steps_used,
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                )

            if decision.kind == STOP:
                trace.record(
                    MODEL_DECISION, summary=decision.summary, decision="stop"
                )
                trace.record(
                    STOPPED, reason=decision.stop_reason, steps_used=state.steps_used
                )
                return RunOutcome(
                    status=STOPPED_STATUS,
                    reason=decision.stop_reason,
                    final=None,
                    trace=trace,
                    steps_used=state.steps_used,
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                )

            # Tool path: validate -> execute -> record. Every processed
            # tool_call consumes one budgeted step, success or failure.
            assert decision.tool_call is not None
            name = decision.tool_call.name
            args = dict(decision.tool_call.arguments)
            trace.record(
                MODEL_DECISION,
                summary=decision.summary,
                decision="tool_call",
                tool=name,
                arguments=args,
            )
            state.attempted.append(fingerprint(name, args))
            trace.record(TOOL_CALL, tool=name, arguments=args)
            try:
                result = self.registry.call(name, args)
            except ToolValidationError as exc:
                state.errors.append(
                    {"tool": name, "arguments": args,
                     "kind": "validation", "error": str(exc)}
                )
                state.steps_used += 1
                trace.record(
                    TOOL_ERROR, tool=name, arguments=args,
                    kind="validation", error=str(exc),
                )
                continue
            except ToolError as exc:
                state.errors.append(
                    {"tool": name, "arguments": args,
                     "kind": exc.kind, "error": str(exc)}
                )
                state.steps_used += 1
                trace.record(
                    TOOL_ERROR, tool=name, arguments=args,
                    kind=exc.kind, error=str(exc),
                )
                continue
            except Exception as exc:  # a tool must never kill the run silently
                state.errors.append(
                    {"tool": name, "arguments": args,
                     "kind": "unexpected", "error": f"{type(exc).__name__}: {exc}"}
                )
                state.steps_used += 1
                trace.record(
                    TOOL_ERROR, tool=name, arguments=args,
                    kind="unexpected", error=f"{type(exc).__name__}: {exc}",
                )
                continue

            tool_calls += 1
            excerpt = summarize(name, result.output)
            state.evidence.append(
                EvidenceItem(source_tool=name, arguments=args, excerpt=excerpt)
            )
            state.steps_used += 1
            trace.record(
                TOOL_RESULT, tool=name, arguments=args,
                output=result.output, excerpt=excerpt,
            )
