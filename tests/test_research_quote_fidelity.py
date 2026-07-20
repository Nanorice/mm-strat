"""Quote-fidelity tests, including the negative controls.

Without the negative controls a containment checker can silently become a rubber
stamp — normalise too hard, or match too short a fragment, and everything passes.
A real quote must pass, an altered figure must fail, an invention must fail.
"""

from pathlib import Path

import pytest

from src.research_quote_fidelity import (
    normalize,
    quote_is_grounded,
    score_report,
    unverified_claims,
)

REAL_RUN = Path.home() / '.tradingagents' / 'logs' / 'reports' / 'RKLB_20260719_212611'
EDGAR_CACHE = Path.home() / '.tradingagents' / 'cache' / 'edgar'

pytestmark = pytest.mark.skipif(
    not (REAL_RUN.exists() and (EDGAR_CACHE / 'RKLB').exists()),
    reason="real run / edgar cache not on this box",
)

# Verbatim from RKLB's cached item1a. The negative controls are derived from it
# so they differ from a passing quote by exactly one thing.
REAL_QUOTE = (
    "For the year ended December 31, 2025, our top five customers accounted for "
    "approximately 49% of our revenues and our top five backlog customers accounted "
    "for approximately 77% of our backlog in the aggregate as of December 31, 2025."
)


@pytest.fixture(scope='module')
def filing():
    from src.research_quote_fidelity import load_filing_text
    text, _ = load_filing_text('RKLB', cache_dir=EDGAR_CACHE)
    return text


# --- negative controls ------------------------------------------------------

def test_real_quote_passes(filing):
    assert quote_is_grounded(REAL_QUOTE, filing) is True


def test_altered_figure_fails(filing):
    """49% → 62%. One number moved; everything else verbatim."""
    assert quote_is_grounded(REAL_QUOTE.replace('49%', '62%'), filing) is False


def test_invented_sentence_fails(filing):
    invented = (
        "The Company expects Neutron to capture a majority share of the medium-lift "
        "launch market by the end of the 2027 fiscal year."
    )
    assert quote_is_grounded(invented, filing) is False


def test_altered_word_fails(filing):
    """Punctuation is forgiven; words are not."""
    assert quote_is_grounded(REAL_QUOTE.replace('top five', 'top three'), filing) is False


# --- the hard-won details ---------------------------------------------------

def test_trailing_full_stop_the_source_lacks_is_forgiven(filing):
    """The 8.7pp bug: a model-added terminal '.' is not fabrication."""
    truncated = REAL_QUOTE.rstrip('.')[:200]
    assert quote_is_grounded(truncated, filing) is True
    assert quote_is_grounded(truncated + '.', filing) is True


def test_curly_quotes_and_dashes_normalise(filing):
    assert normalize('“a–b”') == '"a-b"'
    assert normalize('  A   B \n C ') == 'a b c'


def test_single_and_double_quotes_fold_together(filing):
    """MRVL 2026-07-20: the filing defines terms as ("Marvell," "MTI,"); the
    model transcribed ('Marvell,' 'MTI,'). Every word verbatim, quote style
    swapped. Folding only curly→straight missed it — both were already straight
    — and it failed 10 of 28 claims, reporting 60.7% for a materially clean run.
    """
    assert normalize("'a' \"a\" ‘a’ “a”") == '"a" "a" "a" "a"'


def test_quote_style_swap_still_catches_an_altered_word(filing):
    """The fold must not become a blanket pass: same swap, one word changed."""
    swapped = REAL_QUOTE.replace('"', "'")
    assert 'customers' in swapped  # guard: the substitution below must bite
    assert quote_is_grounded(swapped, filing) is True
    assert quote_is_grounded(swapped.replace('customers', 'suppliers'), filing) is False


def test_ellipsis_elided_quote_checks_every_fragment(filing):
    """Both halves real → passes; one half invented → fails, even though the
    other half is verbatim."""
    both_real = (
        "For the year ended December 31, 2025, our top five customers accounted for "
        "approximately 49% of our revenues ... as of December 31, 2025"
    )
    assert quote_is_grounded(both_real, filing) is True

    one_invented = (
        "For the year ended December 31, 2025, our top five customers accounted for "
        "approximately 49% of our revenues ... and we guarantee a return to profitability "
        "within the next eighteen months"
    )
    assert quote_is_grounded(one_invented, filing) is False


def test_missing_cache_raises_rather_than_scoring_zero():
    """An unverifiable run must not look identical to a fabricated one."""
    from src.research_quote_fidelity import load_filing_text
    with pytest.raises(FileNotFoundError):
        load_filing_text('NOSUCHTICKER', cache_dir=EDGAR_CACHE)


# --- the known number -------------------------------------------------------

def test_real_run_scores_23_of_23(filing):
    scored = score_report(REAL_RUN / 'report.json', cache_dir=EDGAR_CACHE)
    assert scored['claims'] == 23
    assert scored['verified'] == 23
    assert scored['fidelity'] == 1.0
    assert unverified_claims(scored) == []


def test_every_claim_carries_quote_verified():
    scored = score_report(REAL_RUN / 'report.json', cache_dir=EDGAR_CACHE)
    assert all('quote_verified' in c for c in scored['results'])
    assert all(isinstance(c['quote_verified'], bool) for c in scored['results'])
