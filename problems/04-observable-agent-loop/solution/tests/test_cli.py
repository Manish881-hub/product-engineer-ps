"""T09: the CLI the reviewer drives in the demo video."""
import os
import subprocess
import sys

SOLUTION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(*argv: str):
    return subprocess.run(
        [sys.executable, "-m", "agent", *argv],
        cwd=SOLUTION_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_list_tools_names_all_four():
    proc = _run("--list-tools")
    assert proc.returncode == 0
    for name in ("search_logs", "get_metrics", "get_status", "search_kb"):
        assert name in proc.stdout


def test_show_fixtures_summarizes_domain():
    proc = _run("--show-fixtures")
    assert proc.returncode == 0
    assert "checkout-api" in proc.stdout
    assert "payments-worker" in proc.stdout


def test_run_completes_with_evidence_and_conclusions():
    proc = _run("run", "Why is checkout failing?")
    assert proc.returncode == 0
    assert "Evidence (" in proc.stdout
    assert "Conclusions:" in proc.stdout
    assert "tool_result" in proc.stdout


def test_run_with_tiny_budget_stops_and_reports_why(tmp_path):
    trace = str(tmp_path / "trace.jsonl")
    proc = _run("run", "Why is checkout failing?", "--max-steps", "2", "--trace", trace)
    assert proc.returncode == 2
    assert "Stopped: max_steps_exceeded" in proc.stdout
    assert os.path.exists(trace)
    with open(trace, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    assert lines, "trace file must not be empty"
    import json

    types = [json.loads(ln)["type"] for ln in lines]
    assert types[0] == "run_started"
    assert types[-1] == "stopped"
    assert "final_response" not in types
