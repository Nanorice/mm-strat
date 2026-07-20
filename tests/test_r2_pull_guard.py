"""The R2 pull must never overwrite anything but the slim DB.

Regression test for 2026-07-18: `_ensure_local_db()` downloads the slim
`dashboard.duckdb` from R2 but writes it to whatever `DASHBOARD_DB_PATH` names.
`_on_cloud()` is true on the dev/ops boxes (it only proves R2 creds exist), so
`DASHBOARD_DB_PATH=data/market_data.duckdb` — which reads like "run against the
full DB" — silently `os.replace`d ~892 MB of slim data over the 67 GB main
database, destroying 23 years of history.

⚠️ These tests deliberately do NOT import `dashboard_utils`. That module calls
`_ensure_local_db()` at module scope, so importing it under R2 creds performs a
real pull — the very behaviour under test. An import-based test would either hit
the network or need reload gymnastics that test the harness, not the guard.
Instead the guard's source is read and its predicate re-evaluated, which is
possible precisely because the guard is one filename comparison with no state.

Mutation-checked: deleting the `target.name != _SLIM_DB_NAME` block from
`dashboard_utils.py` makes `test_guard_exists_before_client` fail.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "dashboard_utils.py"

SLIM_NAME = "dashboard.duckdb"


def _guard_predicate(target_name: str, slim_name: str = SLIM_NAME) -> bool:
    """The guard's condition, mirrored. True = refuse the pull."""
    return target_name != slim_name


def test_refuses_the_path_that_destroyed_the_db():
    """The exact misconfiguration that caused the incident."""
    assert _guard_predicate("market_data.duckdb") is True


def test_allows_the_slim_db():
    """A guard that refused everything would 'pass' the test above while
    silently breaking the remote app."""
    assert _guard_predicate("dashboard.duckdb") is False


def test_guard_exists_before_client_construction():
    """Structural check on the real source: the refusal must sit BEFORE
    `_r2_client()`, or the download starts regardless of the destination.

    Reading the source is the honest way to pin ordering here — the alternative
    is importing a module whose import IS the dangerous action.
    """
    src = SRC.read_text(encoding="utf-8")
    body = src.split("def _ensure_local_db()", 1)[1].split("\ndef ", 1)[0]

    guard = body.find("_SLIM_DB_NAME")
    client = body.find("_r2_client()")

    assert guard != -1, "destructive-overwrite guard is MISSING from _ensure_local_db"
    assert client != -1, "expected _r2_client() inside _ensure_local_db"
    assert guard < client, (
        "guard must precede _r2_client() — otherwise the R2 download begins "
        "before the destination is validated"
    )


def test_guard_raises_rather_than_returns():
    """A silent `return` would leave the app reading a full DB it never pulled —
    confusing, but survivable. The incident needs a LOUD failure."""
    src = SRC.read_text(encoding="utf-8")
    body = src.split("def _ensure_local_db()", 1)[1].split("\ndef ", 1)[0]
    guard_block = body[body.find("_SLIM_DB_NAME"):]
    assert re.search(r"raise\s+RuntimeError", guard_block), (
        "guard must raise, not return silently"
    )


def test_pull_requires_explicit_opt_in_not_credentials():
    """Barrier 1 — the ONE-WAY rule (user, 2026-07-18).

    Data flows local → slim → R2 → remote viewer, never back. A pull must
    therefore require an explicit opt-in that only the cloud deployment sets.
    Gating on R2 CREDENTIALS is what caused the incident: the dev and ops boxes
    both hold them, so both "were the cloud app" as far as the code could tell.
    """
    src = SRC.read_text(encoding="utf-8")
    body = src.split("def _on_cloud()", 1)[1].split("\ndef ", 1)[0]

    assert "DASHBOARD_PULL_FROM_R2" in body, (
        "_on_cloud() must gate on an explicit opt-in env var, not credentials"
    )
    assert "R2_ACCOUNT_ID" not in body and "R2_ACCESS_KEY" not in body, (
        "_on_cloud() must NOT infer 'am the cloud app' from R2 credentials — "
        "creds mean 'can reach R2', which is true on every box that syncs"
    )


def test_opt_in_is_hydrated_from_streamlit_secrets():
    """Every env var the app gates on must be in _SECRET_KEYS.

    Streamlit Cloud exposes config as `st.secrets`, NOT os.environ — dashboard_utils
    copies a fixed list across at import. `DASHBOARD_PULL_FROM_R2` was gated on but
    never listed, so _on_cloud() was unconditionally False on the only host meant to
    pull: setting the secret in the Cloud UI was a silent no-op and the R2 asset pull
    (model cards, audit reports, cone equity curves) never ran.
    """
    import ast

    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    secret_keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "_SECRET_KEYS" for t in node.targets
        ):
            secret_keys = {
                e.value for e in node.value.elts if isinstance(e, ast.Constant)
            }
    assert secret_keys, "_SECRET_KEYS not found or not a literal tuple"
    assert "DASHBOARD_PULL_FROM_R2" in secret_keys, (
        "DASHBOARD_PULL_FROM_R2 is read from os.environ by _on_cloud() but is not "
        "hydrated from st.secrets — the Cloud secret would be ignored"
    )
    assert "DASHBOARD_DB_PATH" in secret_keys


def test_upload_path_still_uses_credentials():
    """The LEGITIMATE direction (local → R2) must keep working.

    A fix that disabled the nightly upload would trade a data-loss bug for a
    stale-remote bug. `sync_dashboard_db.py` is the writer and must still gate on
    credentials, not on the viewer opt-in.
    """
    sync = (ROOT / "scripts" / "sync_dashboard_db.py").read_text(encoding="utf-8")
    assert "R2_ACCOUNT_ID" in sync, "upload path lost its credential check"
    assert "DASHBOARD_PULL_FROM_R2" not in sync, (
        "the uploader must not require the viewer's pull opt-in"
    )


def test_slim_name_constant_matches_manifest_output():
    """The guard's allowed filename must equal what build_dashboard_db writes,
    or the guard blocks the legitimate remote pull."""
    builder = (ROOT / "scripts" / "build_dashboard_db.py").read_text(encoding="utf-8")
    assert SLIM_NAME in builder, (
        f"{SLIM_NAME!r} not referenced by build_dashboard_db.py — the guard and "
        "the builder disagree on the slim DB filename"
    )
    src = SRC.read_text(encoding="utf-8")
    assert f'_SLIM_DB_NAME = "{SLIM_NAME}"' in src
