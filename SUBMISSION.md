# Product Engineering Challenge Submission

## Candidate

- **Name:** Manish Bhakti Sagar
- **Email:** [same address that received the Caygnus assignment — fill before submitting]
- **GitHub:** Manish881-hub
- **Selected problem:** Problem 4 — Observable Agent Loop
- **Demo video:** [TBD — 3–5 min screen recording; record after final test run]

## Run the project

Prerequisites: Python 3.11+ only. No install step, no API keys, no network.
`pytest` is needed only to run the test suite (dev/test-only; `agent/` never imports it).

```text
cd problems/04-observable-agent-loop/solution
python3 --version            # expect 3.11+
python3 -m agent --list-tools
python3 -m agent --show-fixtures
python3 -m agent run "Why is checkout authorize timing out?" --trace trace.jsonl
```

Successful scenario (AC1/AC2/AC3/AC6): the command above performs 4 tool
calls (logs → metrics → status → knowledge base), prints the ordered trace
plus a final response with separate `Evidence`, `Conclusions`, and
`Recommendations` sections, exits `0`, and writes `trace.jsonl` whose event
types are `run_started, model_decision, tool_call, tool_result, …, final_response`.

Failure/recovery scenario (AC4):

```text
python3 -m agent run "Is payments-worker error_rate spiking?"
```

The metrics pipeline for `payments-worker` is down by fixture design, so the
first tool call raises a transient error. The run records a `tool_error`
event, the model switches to alternate sources (other-service metrics,
status, logs, runbook), and the run still completes with exit `0`.

Execution-limit scenario (AC5):

```text
python3 -m agent run "Why is checkout authorize timing out?" --max-steps 2
```

Exits `2`, prints `Stopped: max_steps_exceeded`, and the trace ends with a
`stopped` event and no `final_response`.

## Run the tests

```text
cd problems/04-observable-agent-loop/solution
python3 -m pytest        # 39 tests, <1s, deterministic, no network/services
```

Coverage by brief category: tool registration/selection/argument validation
(`test_registry_tools.py`, `test_contracts.py`); multi-step loop with a
deterministic scripted model (`test_loop_multistep.py`); tool failure
handling incl. heuristic self-recovery (`test_recovery.py`); execution-limit
enforcement incl. a no-extra-model-call assertion (`test_limits.py`);
evidence/conclusion separation with per-token output grounding
(`test_evidence.py`); CLI behavior incl. exit codes and trace file
(`test_cli.py`); model-decision behavior (`test_model.py`).

## Architecture and data flow

```text
CLI (__main__)
  │ objective, max_steps, trace path
  ▼
Orchestrator (loop.py) ── owns steps, termination, state, trace
  │  ① budget check (stop BEFORE next model call when exhausted)
  │  ② ask model → Decision(tool_call | final | stop)
  │  ③ validate + execute via Registry → ToolResult | ToolError
  │  ④ append evidence/error, emit trace events, repeat
  ▼
Model interface (model.py) ── owns NEXT-STEP choice only
  ├─ HeuristicModel  deterministic local policy (used by CLI)
  └─ ScriptedModel   canned decisions (used by tests)
  ▼
Registry (registry.py) ── the validated seam: rejects unknown tools,
missing/extra/mistyped/out-of-enum arguments BEFORE tool code runs
  ▼
Tools (tools.py + fixtures/*.json) ── own fixture access, tool-specific
errors (transient vs permanent), and one-line output summarizers that
become evidence excerpts
  ▼
TraceRecorder (trace.py) ── append-only, sequence-numbered operational
events (run_started, model_decision, tool_call, tool_result, tool_error,
final_response, stopped) with credential redaction; JSONL-serializable
```

State retained between steps (`RunState`): the objective, `steps_used`
against `max_steps`, accumulated `evidence` (tool + args + excerpt),
`errors`, and `attempted` call fingerprints so the model never repeats a
failed structured call. Models receive the state read-only.

## Technology choices

Python standard library only (`argparse`, `dataclasses`, `json`), `pytest`
for tests. Alternatives considered: TypeScript/Node (nicer CLI polish, but
heavier for reviewers and weaker for deterministic fixtures), SQLite
persistence (unneeded — JSONL traces satisfy inspectability at this scale),
a real LLM adapter (explicitly rejected: the brief requires deterministic
tests with no paid API, and portability is documented as an extension, not
implemented). Trade-off accepted: the local model is a transparent heuristic
rather than a general reasoner — appropriate for a controls-and-observability
exercise, and the `Model` interface is exactly where an LLM adapter would plug
in without touching the loop, tools, or trace.

## Important decisions

1. **The loop is generic; only the adapters are specific.** The orchestrator
   never branches on question content — it enforces validate → execute →
   record → repeat plus termination. All question-specific behavior lives in
   the model adapter. I deliberately did not name it `RuleRouter`: the loop
   asks for the next structured decision from objective + accumulated
   evidence, so adding a tool or reordering an investigation means changing
   an adapter, never the control flow. Reviewers can verify this by reading
   `loop.py` (no fixture/service names appear in it).
2. **Budget is checked before the next model call, and `stopped` beats a
   partial answer.** A capped run emits `stopped: max_steps_exceeded` with
   zero further model/tool calls (asserted in `test_limits.py`), rather than
   squeezing out an under-evidenced final. This matches AC5 literally and
   keeps the failure mode honest and observable.
3. **Evidence grounding is tested per token.** `summarize()` paraphrase plus
   a grounding test (every substantive excerpt token must occur in the
   re-executed tool output) caught a real bug during development — a summary
   artifact (`12.4percent`) that existed nowhere in the data. The fix was in
   the formatter, not the test.

## Assumptions and limitations

- Tools are read-only evidence sources, so retries/alternate-source recovery
  carry no side-effect risk; a consequential (write) tool would need
  idempotency keys plus the human-approval gate described below.
- Fixtures are static JSON; there is no pagination, streaming, or time-based
  flakiness — the one failure (metrics outage for `payments-worker`) is
  deterministic by design so the demo and tests are reproducible.
- Single-process, single-run execution; concurrent runs, durable resume, and
  parallel tool calls are out of scope (see production notes).
- `HeuristicModel` finalizes only from collected evidence and stops with
  `insufficient_evidence` when every source is exhausted without usable
  evidence; it does not ask clarifying questions.
- Trace redaction masks credential-like keys (`token/secret/password/api_key…`);
  fixtures contain no secrets by construction.

## Production and scale

- **What prevents indefinite calls:** the `max_steps` budget (checked before
  each model call), the model's no-repeat rule over attempted fingerprints,
  and terminal `final`/`stop` decisions. All three are unit-tested.
- **Human approval for consequential tools:** add a fourth decision kind
  (`await_approval` with tool + args + rationale), persist the run, and
  resume on approve/deny; deny becomes a `tool_error(kind=denied)` the model
  must route around. The registry already distinguishes tools, so approval
  can be per-tool policy (`read` vs `write`).
- **Concurrent cloud jobs:** the orchestrator is already stateless apart from
  `RunState` — serialize state + trace to a run store (e.g. Postgres row per
  run, JSONL trace in object storage), execute each step as a queued job, and
  keep tool adapters pure functions of `(args, fixture/service handle)` so
  workers are interchangeable. Idempotency keys on tool calls make
  at-least-once job execution safe.
- **Persist per run:** the ordered trace (debugging + evals), per-step
  latency and token counts when an LLM adapter lands (cost analysis), tool
  error kinds/frequencies (alerts: spike in `transient` = dependency trouble;
  `max_steps_exceeded` rate = budget or policy problem), and final
  evidence-vs-conclusion pairs (grounding evals).

## AI usage

Built with Muse Spark (via OpenCode) plus the Matt Pocock skills collection
as process scaffolding: `ask-matt` routing (problem selection against prior
work), `grilling` (two decision rounds before code), `codebase-design`
vocabulary (deep modules, seams — the four seams above), and `tdd`
(red→green per ticket, behavior tested through public interfaces). All code,
fixtures, and tests were reviewed and executed locally; I own the design and
can walk through or change any part.

## Credibility note

- **System:** radiology-focused agent harness (private Applied-AI assessment
  pipeline converting telegraphic dictation into structured `FINDINGS` +
  `IMPRESSION` reports, with ingestion → parsing → extraction → routing →
  minimal editing → impression → validation stages plus parser/renderer/
  validator tests and a CLI entrypoint).
- **My contribution:** building and improving the evidence collection and
  verification flow around tool-using agent behavior — the orchestration and
  recovery logic needed to make multi-step agent actions observable and
  verifiable rather than relying on a single opaque model response.
- **Scale/operations:** [owner to fill with one real figure if available —
  e.g. cases handled — otherwise delete this line; do not invent scale].
- **Hard decision:** introducing explicit verification and bounded recovery
  instead of allowing the agent to continue indefinitely.
- **Evidence:** private work; can be discussed or demonstrated on request.
