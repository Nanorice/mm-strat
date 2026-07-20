"""
Quote fidelity — does a claim's quote actually appear in the filing it cites?

The agent's schema requires every claim to carry a verbatim passage, and the
filing is cached on disk. So "did the model make this up?" is a string
containment check rather than a judgement, which turns model trust into a
measured number per run.

Verification belongs here, on the consumer side: a producer checking its own
quotes against its own input proves nothing.

No LLM, no network — pure functions over cached text.
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import config

# Normalisation is deliberately generous. Models reflow whitespace, swap curly
# quotes for straight ones and en-dashes for hyphens without changing a word.
# Those are not fabrications. Dropping or altering a *word* is, and survives all
# of this.
# EVERY quote character folds to one glyph, single and double alike. Observed on
# MRVL 2026-07-20: the 10-K defines terms as ("Marvell," "MTI,") and the model
# transcribed them as ('Marvell,' 'MTI,') - verbatim in every word, differing
# only in quote style. Folding curly-to-straight was not enough, because both
# forms were already straight. That one substitution failed 10 of 28 claims and
# reported 60.7% fidelity for a run that is materially clean.
_PUNCT = {
    '‘': '"', '’': '"', '“': '"', '”': '"',
    "'": '"', '`': '"',
    '–': '-', '—': '-', '‑': '-', ' ': ' ',
}

# A quote elided with "..." is two or more real fragments; each is checked.
_ELLIPSIS = re.compile(r'\s*(?:\.\.\.|…)\s*')

# Models routinely terminate a quote with a full stop the source lacks at that
# point. Verified on deepseek: two quotes matched 389/390 and 230/231 characters
# and diverged only on a trailing ".". Counting that as fabrication understated
# fidelity by 8.7pp — it reported 91.3% for a run that is actually 100%.
# Punctuation at the edges carries no claim; altering a word still fails.
_EDGE_PUNCT = ' \t\n.,;:!?\'"()[]-'

# Below this length a "fragment" is not a quote, it is a word or two that would
# match almost any filing by chance. Fragments this short are dropped rather
# than counted as evidence.
_MIN_FRAGMENT_CHARS = 25
_MIN_WHOLE_QUOTE_CHARS = 8


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', text)
    for src, dst in _PUNCT.items():
        text = text.replace(src, dst)
    return ' '.join(text.lower().split())


def load_filing_text(ticker: str, cache_dir=None) -> Tuple[str, str]:
    """Normalised text of every cached section for a ticker's latest filing.

    Returns (text, accession). Raises FileNotFoundError when nothing is cached —
    an unverifiable run must not silently score 0% and look like fabrication.
    """
    root = Path(cache_dir or config.EDGAR_CACHE_DIR) / ticker.upper()
    dirs = sorted(d for d in root.iterdir() if d.is_dir()) if root.exists() else []
    if not dirs:
        raise FileNotFoundError(f"no cached filing for {ticker} under {root}")
    latest = dirs[-1]
    body = ' '.join(
        p.read_text(encoding='utf-8') for p in sorted(latest.glob('item*.md'))
    )
    return normalize(body), latest.name


def walk_evidence(node, path: str = '') -> List[Tuple[str, dict]]:
    """Every Evidence object in a payload, with the field path carrying it."""
    found: List[Tuple[str, dict]] = []
    if isinstance(node, dict):
        if 'quote' in node and 'source' in node and 'strength' in node:
            found.append((path, node))
        for key, value in node.items():
            found.extend(walk_evidence(value, f"{path}.{key}" if path else key))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found.extend(walk_evidence(item, f"{path}[{i}]"))
    return found


def quote_is_grounded(quote: str, filing: str) -> bool:
    """True when every fragment of the quote appears verbatim in the filing."""
    fragments = [
        stripped
        for stripped in (normalize(f).strip(_EDGE_PUNCT) for f in _ELLIPSIS.split(quote))
        if len(stripped) > _MIN_FRAGMENT_CHARS
    ]
    if not fragments:
        fragment = normalize(quote).strip(_EDGE_PUNCT)
        return len(fragment) > _MIN_WHOLE_QUOTE_CHARS and fragment in filing
    return all(f in filing for f in fragments)


def score_profile(profile: dict, cache_dir=None) -> dict:
    """Score one BusinessProfile payload against its cached filing.

    Returns per-claim results plus the run's fidelity. Every claim carries
    quote_verified — an unverified claim must never reach the knowledge base
    silently, so the flag travels with the claim rather than being summarised away.
    """
    filing, accession = load_filing_text(profile['ticker'], cache_dir=cache_dir)
    evidence = walk_evidence(profile)

    claims = [
        {
            'path':           path,
            'quote':          ev['quote'],
            'source':         ev['source'],
            'strength':       ev['strength'],
            'quote_verified': quote_is_grounded(ev['quote'], filing),
        }
        for path, ev in evidence
    ]
    verified = sum(1 for c in claims if c['quote_verified'])

    return {
        'ticker':    profile['ticker'],
        'accession': accession,
        'claims':    len(claims),
        'verified':  verified,
        'fidelity':  verified / len(claims) if claims else 0.0,
        'results':   claims,
    }


def score_report(report_path, cache_dir=None) -> Optional[dict]:
    """Score the business_analyst payload of a report.json.

    Returns None when the agent produced no typed output (null or absent) —
    distinct from a profile that scored zero.
    """
    payload = json.loads(Path(report_path).read_text(encoding='utf-8'))
    profile = (payload.get('agents') or {}).get('business_analyst')
    if profile is None:
        return None
    return score_profile(profile, cache_dir=cache_dir)


def unverified_claims(scored: dict) -> List[Dict]:
    return [c for c in scored['results'] if not c['quote_verified']]
