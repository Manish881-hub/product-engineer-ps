# Observable Agent Loop — solution (Problem 4)

Deterministic, observable incident-investigation loop. No network, no API keys,
no runtime dependencies — Python 3.11+ standard library only.

## Setup (under 2 minutes)

```bash
cd problems/04-observable-agent-loop/solution
python3 --version   # 3.11+
```

No install step. Tests need `pytest` (dev/test only, never imported by `agent/`):

```bash
python3 -m pytest        # 39 tests, <1s, no network
```

## Run

```bash
python3 -m agent --list-tools
python3 -m agent --show-fixtures
python3 -m agent run "Why is checkout authorize timing out?" --trace trace.jsonl
```

Exit status: `0` = completed with a final response, `2` = stopped
(limit reached or insufficient evidence), `1` = usage error.

## Demo sequence (mirrors the brief's checklist)

```bash
# 1. tools + synthetic data
python3 -m agent --list-tools
python3 -m agent --show-fixtures
# 2+3+6. multi-source investigation, ordered trace, evidence-linked answer
python3 -m agent run "Why is checkout authorize timing out?" --trace trace.jsonl
# 4. tool failure + recovery (metrics pipeline for payments-worker is down
#    by fixture design; the loop records the error and recovers via status/logs)
python3 -m agent run "Is payments-worker error_rate spiking?"
# 5. execution limit: stops with max_steps_exceeded, no extra model/tool call
python3 -m agent run "Why is checkout authorize timing out?" --max-steps 2
```

## Layout

```text
agent/
  types.py      domain contracts (Decision, EvidenceItem, FinalResponse, RunState, …)
  trace.py      ordered TraceRecorder + credential redaction, JSONL output
  registry.py   validated tool seam (unknown/missing/mistyped args rejected pre-call)
  tools.py      4 fixture-backed tools + per-tool output summarizers (evidence excerpts)
  fixtures/     static JSON: logs, metrics, status, knowledge base
  model.py      Model interface; HeuristicModel (CLI) + ScriptedModel (tests)
  loop.py       generic orchestrator: steps, termination, state, trace
  __main__.py   CLI (run / --list-tools / --show-fixtures / --max-steps / --trace)
tests/          focused pytest suite, one file per behavior slice
```

See `/SUBMISSION.md` (repo root) for architecture, decisions, trade-offs,
production notes, AI-usage disclosure, and the credibility note.
