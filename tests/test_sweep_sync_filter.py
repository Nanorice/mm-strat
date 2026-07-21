"""The sweep-tree sync ships equity.parquet ONLY.

trades.parquet + rejections.parquet are ~78 MB of dev-box-local zoom detail
(cone_and_studio_design.md §4). A regression that lets them through would quadruple
the asset sync; a regression that drops equity.parquet blanks the remote cone fan.
Both directions are pinned here.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sync_dashboard_db as sync  # noqa: E402

SWEEP_PREFIX = "sweep_starttime"


def _sweep_entry():
    for local_dir, prefix, suffixes in sync.ASSET_DIRS:
        if prefix == SWEEP_PREFIX:
            return local_dir, prefix, suffixes
    pytest.fail(f"{SWEEP_PREFIX} missing from sync ASSET_DIRS — remote cone fan is blank")


def test_sweep_dir_is_registered_for_upload():
    local_dir, _, suffixes = _sweep_entry()
    assert local_dir.name == "starttime"
    assert suffixes == (".parquet",)


def test_only_equity_is_allowlisted():
    assert sync.SWEEP_KEEP == {"equity.parquet"}, (
        "SWEEP_KEEP controls 78 MB of trades/rejections — widen it deliberately"
    )
    assert "trades.parquet" not in sync.SWEEP_KEEP
    assert "rejections.parquet" not in sync.SWEEP_KEEP


def test_upload_filter_selects_equity_only(tmp_path):
    """Drive the real filter over a fake sweep tree."""
    cell = tmp_path / "champion" / "grid_a" / "cell_1"
    cell.mkdir(parents=True)
    for name in ("equity.parquet", "trades.parquet", "rejections.parquet", "config.json"):
        (cell / name).write_bytes(b"x" * 16)

    uploaded: list[str] = []

    class _Client:
        def upload_file(self, path, bucket, key, ExtraArgs=None):
            uploaded.append(key)

    n = sync.upload_asset_dir(tmp_path, SWEEP_PREFIX, (".parquet",),
                              bucket="b", dry_run=False, client=_Client(), remote={})

    assert n == 1, f"expected 1 upload, got {n}: {uploaded}"
    assert uploaded == [f"latest/{SWEEP_PREFIX}/champion/grid_a/cell_1/equity.parquet"]
    joined = " ".join(uploaded)
    assert "trades" not in joined and "rejections" not in joined


def test_other_asset_dirs_keep_all_suffixes(tmp_path):
    """The allowlist must be scoped to the sweep prefix, not applied globally."""
    (tmp_path / "a.html").write_bytes(b"x")
    (tmp_path / "b.json").write_bytes(b"x")

    uploaded: list[str] = []

    class _Client:
        def upload_file(self, path, bucket, key, ExtraArgs=None):
            uploaded.append(key)

    n = sync.upload_asset_dir(tmp_path, "model_cards", (".html", ".json"),
                              bucket="b", dry_run=False, client=_Client(), remote={})
    assert n == 2, f"model_cards must not inherit SWEEP_KEEP: {uploaded}"


def test_pull_side_mirrors_push_side():
    """A push with no matching pull entry uploads bytes nobody downloads."""
    import dashboard_utils
    # _ASSET_DIRS became a {prefix: Path} dict in the ensure_assets refactor.
    pull_prefixes = set(dashboard_utils._ASSET_DIRS)
    push_prefixes = {p for _, p, _ in sync.ASSET_DIRS}
    assert push_prefixes <= pull_prefixes, (
        f"pushed but never pulled: {sorted(push_prefixes - pull_prefixes)}"
    )
