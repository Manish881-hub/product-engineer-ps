"""Tool registry: the validated seam between model decisions and tool code.

The model may only name a registered tool with structured arguments.
The registry rejects unknown tools, missing/extra/mistyped arguments, and
arguments outside their allowed values — before any tool code runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .types import ToolResult, ToolValidationError

ToolFn = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    required: List[str] = field(default_factory=list)
    optional: List[str] = field(default_factory=list)
    types: Dict[str, type] = field(default_factory=dict)
    allowed: Dict[str, List[Any]] = field(default_factory=dict)


def fingerprint(name: str, arguments: Dict[str, Any]) -> str:
    """Stable identity of one structured call, used to avoid repeat work."""
    return f"{name}:{json.dumps(arguments, sort_keys=True, default=str)}"


class Registry:
    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}
        self._fns: Dict[str, ToolFn] = {}

    def register(self, spec: ToolSpec, fn: ToolFn) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool already registered: {spec.name}")
        self._specs[spec.name] = spec
        self._fns[spec.name] = fn

    def list_specs(self) -> List[ToolSpec]:
        return [self._specs[name] for name in sorted(self._specs)]

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError:
            known = ", ".join(sorted(self._specs)) or "(none)"
            raise ToolValidationError(
                f"unknown tool {name!r}; registered tools: {known}"
            ) from None

    def validate(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        spec = self.get(name)
        if not isinstance(arguments, dict):
            raise ToolValidationError(f"tool {name!r} requires an arguments object")
        missing = [a for a in spec.required if a not in arguments]
        if missing:
            raise ToolValidationError(
                f"tool {name!r} missing required arguments: {', '.join(missing)}"
            )
        known = set(spec.required) | set(spec.optional)
        unexpected = [a for a in arguments if a not in known]
        if unexpected:
            raise ToolValidationError(
                f"tool {name!r} got unexpected arguments: {', '.join(unexpected)}"
            )
        for arg, expected in spec.types.items():
            if arg in arguments and not isinstance(arguments[arg], expected):
                raise ToolValidationError(
                    f"tool {name!r} argument {arg!r} must be "
                    f"{expected.__name__}, got {type(arguments[arg]).__name__}"
                )
        for arg, choices in spec.allowed.items():
            if arg in arguments and arguments[arg] not in choices:
                raise ToolValidationError(
                    f"tool {name!r} argument {arg!r} must be one of "
                    f"{choices}, got {arguments[arg]!r}"
                )
        return dict(arguments)

    def call(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        validated = self.validate(name, arguments)
        output = self._fns[name](validated)
        if not isinstance(output, dict):
            raise ToolValidationError(
                f"tool {name!r} must return a JSON-like object"
            )
        return ToolResult(tool=name, arguments=validated, output=output)
