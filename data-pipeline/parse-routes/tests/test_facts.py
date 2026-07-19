"""Guide facts are loaded from config.yml and rendered into the block the
orchestrator injects into the ocr-cleaner subagents (#147). The wetterstein
block must stay equivalent to the guide facts the prompt used to hardcode, so
cleaning behaviour is unaffected."""

from __future__ import annotations

from conftest import run_cli
from pipeline.config import load_guide
from pipeline.facts import render_facts_block


def test_load_guide_reads_facts():
    facts = load_guide("wetterstein").facts
    assert facts.title == "Alpenvereinsführer Wetterstein"
    assert facts.author == "Beulke"
    assert facts.edition == "4. Auflage"
    assert facts.year == 1996
    assert facts.language == "German"


def test_karwendel_facts_flow_from_its_own_config():
    facts = load_guide("karwendel").facts
    assert facts.title == "Alpenvereinsführer Karwendel"
    assert facts.author == "Klier/Walter"
    assert facts.year == 2011


def test_render_block_carries_the_wetterstein_facts_the_prompt_used_to_hardcode():
    block = render_facts_block(load_guide("wetterstein").facts)
    # The facts the prompt body used to bake in must all be present in the block.
    for fact in ("Alpenvereinsführer Wetterstein", "Beulke", "1996", "German"):
        assert fact in block


def test_facts_cli_prints_the_block():
    result = run_cli("facts", "--guide", "wetterstein")
    assert result.returncode == 0, result.stderr
    assert "Alpenvereinsführer Wetterstein" in result.stdout
    assert "Beulke" in result.stdout
