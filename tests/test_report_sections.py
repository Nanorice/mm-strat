"""Section splitting for agentic research reports (dashboard page 7)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard_utils import (  # noqa: E402
    escape_markdown_dollars, fell_back_to_free_text, split_report_sections,
)

# Shaped like a real complete_report.md: agent headings at ###, and agent BODIES
# carrying their own ## and ### headings — the thing a naive split shreds.
SAMPLE = """# Trading Analysis Report: GLW

## I. Analyst Team Reports

### Market Analyst
## GLW — Comprehensive Technical Analysis
### 1. Macro Market Context
Rallied from $53 to $271.78.

### Business Analyst
Relations follow.
### 2. Counterparties
Apple Inc, 16% of revenue.

## II. Research Team Decision

### Bull Researcher
### 🔥 Rebuttal: "overvalued"
Buy it.
"""


def test_splits_on_agent_headings_only():
    s = split_report_sections(SAMPLE)
    assert list(s) == ["Market Analyst", "Business Analyst", "Bull Researcher"]


def test_body_subheadings_stay_with_their_agent():
    s = split_report_sections(SAMPLE)
    assert "### 2. Counterparties" in s["Business Analyst"]
    assert "Apple Inc" in s["Business Analyst"]
    assert "Counterparties" not in s["Market Analyst"]


def test_no_agent_headings_yields_empty_so_caller_falls_back():
    assert split_report_sections("# Just prose\n\nNo agents here.") == {}
    assert split_report_sections("") == {}


def test_dollars_escaped_for_streamlit_latex():
    # Unescaped, Streamlit reads "$53 to $" as math and eats the spaces.
    assert escape_markdown_dollars("from $53 to $271.78") == r"from \$53 to \$271.78"
    assert escape_markdown_dollars(None) == ""


# ── free-text fallback detection ─────────────────────────────────────────────
# A structured call that fails leaves report.json's agent key NULL and drops the
# section to unconstrained prose — often a JSON dump that reads like a report.
# GLW/MRVL (pre-producer-fix) look exactly like this on disk.

def test_null_typed_output_is_a_fallback():
    assert fell_back_to_free_text(
        '{"agents": {"business_analyst": null}}', "Business Analyst") is True


def test_populated_typed_output_is_not():
    assert fell_back_to_free_text(
        '{"agents": {"business_analyst": {"relations": []}}}',
        "Business Analyst") is False


def test_absent_agent_is_not_a_failure():
    # Agent wasn't in the graph — different fact from "ran and produced nothing".
    assert fell_back_to_free_text('{"agents": {}}', "Business Analyst") is False


def test_prose_only_agents_never_warn():
    # Bull/Bear researchers have no typed schema; NULL says nothing about them.
    assert fell_back_to_free_text(
        '{"agents": {"business_analyst": null}}', "Bull Researcher") is False


def test_missing_or_unparseable_json_is_not_a_fallback():
    assert fell_back_to_free_text(None, "Business Analyst") is False
    assert fell_back_to_free_text("not json", "Business Analyst") is False
