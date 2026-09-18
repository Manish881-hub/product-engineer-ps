"""T08: evidence vs conclusions (AC6), end to end with the real model.

Every evidence excerpt must be grounded in an actual tool output for the
recorded arguments — the response may not invent facts. Operationalized:
each substantive token (word of 6+ chars, or number) in an excerpt must
appear in the JSON of the tool output, except a tiny glue-word list.
If fixtures evolve, this test points at exactly the ungrounded word.
"""
import json
import re

from agent.loop import Orchestrator
from agent.model import HeuristicModel
from agent.tools import build_default_registry

GLUE_WORDS = {"matches", "runbook"}


def _substantive_tokens(text: str) -> list:
    toks = re.findall(r"[A-Za-z0-9_.%]+", text)
    return [t for t in toks if len(t) >= 6 or t[:1].isdigit()]


def test_final_response_separates_evidence_from_inference():
    outcome = Orchestrator(HeuristicModel(), build_default_registry()).run(
        "Why is checkout failing?", max_steps=6
    )
    assert outcome.status == "completed"
    final = outcome.final
    assert len(final.evidence) >= 2
    assert len({e.source_tool for e in final.evidence}) >= 2
    assert "Most likely cause" in final.conclusions
    assert final.recommendations != ""

    registry = build_default_registry()
    for item in final.evidence:
        assert item.arguments, "evidence must cite the structured arguments used"
        assert item.excerpt, "evidence must quote what the tool returned"
        actual_json = json.dumps(
            registry.call(item.source_tool, dict(item.arguments)).output
        )
        for tok in _substantive_tokens(item.excerpt):
            assert tok in actual_json or tok.lower() in GLUE_WORDS, (
                f"ungrounded token {tok!r} in {item.source_tool} excerpt"
            )
