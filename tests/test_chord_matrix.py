"""_chord_matrix must survive a read-only (cached) correlation frame.

Regression: the remote Supply-chain page crashed with
`ValueError: underlying array is read-only` from np.fill_diagonal, because
@st.cache_data hands back an immutable buffer and .clip() does not always copy
it (pandas-version dependent — it did locally, it didn't on Streamlit Cloud).
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_chord_matrix():
    """Import _chord_matrix without executing the page body (Streamlit calls)."""
    src = (ROOT / "scripts" / "pages" / "6_Supply_Chain.py").read_text(encoding="utf-8")
    # Keep only the function under test + its imports; the module top level
    # renders the page (st.tabs, DB reads) and can't run headless.
    start = src.index("def _chord_matrix")
    end = src.index("def _render_chord")
    ns: dict = {"np": np, "pd": pd}
    exec(compile(src[start:end], "_chord_matrix", "exec"), ns)
    return ns["_chord_matrix"]


_chord_matrix = _load_chord_matrix()

SECTORS = ["Technology", "Energy", "Utilities", "Healthcare"]


def _corr(read_only: bool) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    arr = pd.DataFrame(rng.normal(size=(300, len(SECTORS))), columns=SECTORS).corr().to_numpy()
    if read_only:
        arr.setflags(write=False)
    return pd.DataFrame(arr, index=SECTORS, columns=SECTORS, copy=False)


@pytest.mark.parametrize("read_only", [False, True], ids=["writable", "read_only"])
def test_chord_matrix_zeroes_diagonal(read_only: bool) -> None:
    corr = _corr(read_only)
    order, m = _chord_matrix(corr)

    assert (np.diag(m.to_numpy()) == 0).all(), "diagonal not zeroed"
    assert (m.to_numpy() >= 0).all(), "negative correlation survived the clip"
    assert list(m.index) == order and list(m.columns) == order, "hub order not applied"
    assert set(order) == set(SECTORS), "sectors lost"


def test_source_frame_not_mutated() -> None:
    """The cached frame is shared — zeroing the diagonal must not write through."""
    corr = _corr(read_only=False)
    before = corr.to_numpy(copy=True)
    _chord_matrix(corr)
    np.testing.assert_array_equal(corr.to_numpy(), before)


def test_hub_ordering_is_descending_mean_offdiagonal() -> None:
    order, _ = _chord_matrix(_corr(read_only=False))
    corr = _corr(read_only=False)
    means = [corr[s].drop(s).mean() for s in order]
    assert means == sorted(means, reverse=True), "not hub-first"
