"""Analytics — exploratory measures (IC, decile, score-trajectory) used by
M01-Hold and the whitepaper §2.3.3 deep-dive views. Strictly diagnostic; none
of these are promotion gates."""

from .rolling_ic import rolling_ic
from .decile_analysis import decile_analysis
from .score_trajectory import score_trajectory

__all__ = ["rolling_ic", "decile_analysis", "score_trajectory"]
