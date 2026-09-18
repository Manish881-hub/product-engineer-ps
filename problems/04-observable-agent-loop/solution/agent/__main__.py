"""CLI: the reviewer's handle on the loop.

    python -m agent --list-tools
    python -m agent --show-fixtures
    python -m agent run "why is checkout failing?" [--max-steps N] [--trace PATH]

Exit status: 0 = completed with a final response, 2 = stopped (limit or
insufficient evidence), 1 = usage error.
"""
from __future__ import annotations

import argparse
import json
import sys

from .loop import COMPLETED, Orchestrator
from .model import HeuristicModel
from .tools import (
    KB_TOPICS,
    METRICS_OUTAGE,
    SERVICE_CATALOG,
    build_default_registry,
    load_fixture,
)

DEFAULT_MAX_STEPS = 6


def cmd_list_tools() -> int:
    for spec in build_default_registry().list_specs():
        req = ", ".join(spec.required)
        print(f"- {spec.name}({req})")
        print(f"    {spec.description}")
    return 0


def cmd_show_fixtures() -> int:
    logs = load_fixture("logs")
    metrics = load_fixture("metrics")
    status = load_fixture("status")
    kb = load_fixture("kb")
    print(f"services: {', '.join(SERVICE_CATALOG)}")
    for svc, entries in logs.items():
        print(f"logs[{svc}]: {len(entries)} entries")
    print(f"metrics: {', '.join(sorted(metrics))} "
          f"(outage: {', '.join(sorted(METRICS_OUTAGE)) or 'none'})")
    for svc, info in status.items():
        print(f"status[{svc}]: {info['state']}")
    print(f"kb topics: {', '.join(sorted(kb))} "
          f"(registered: {', '.join(KB_TOPICS)})")
    return 0


def _short(payload: dict, limit: int = 160) -> str:
    text = json.dumps(payload, sort_keys=True, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def present(outcome) -> None:
    for event in outcome.trace.events:
        print(f"[{event.seq:02d}] {event.type}: {_short(event.payload)}")
    print()
    if outcome.status == COMPLETED and outcome.final is not None:
        print(f"Evidence ({len(outcome.final.evidence)}):")
        for item in outcome.final.evidence:
            print(f"  - [{item.source_tool}] {item.excerpt}")
        print("Conclusions:")
        print(f"  {outcome.final.conclusions}")
        print("Recommendations:")
        print(f"  {outcome.final.recommendations}")
    else:
        print(f"Stopped: {outcome.reason} "
              f"(after {outcome.steps_used} steps, "
              f"{outcome.tool_calls} tool calls)")


def cmd_run(objective: str, max_steps: int, trace_path: str | None) -> int:
    outcome = Orchestrator(HeuristicModel(), build_default_registry()).run(
        objective, max_steps=max_steps
    )
    present(outcome)
    if trace_path:
        outcome.trace.write_jsonl(trace_path)
        print(f"\ntrace written to {trace_path}")
    return 0 if outcome.status == COMPLETED else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent",
        description="Observable incident-investigation agent loop.",
    )
    parser.add_argument("--list-tools", action="store_true")
    parser.add_argument("--show-fixtures", action="store_true")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="investigate an objective")
    run.add_argument("objective", help="the investigation question")
    run.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    run.add_argument("--trace", default=None, help="write JSONL trace here")
    return parser


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_tools:
        return cmd_list_tools()
    if args.show_fixtures:
        return cmd_show_fixtures()
    if args.command == "run":
        return cmd_run(args.objective, args.max_steps, args.trace)
    build_parser().print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
