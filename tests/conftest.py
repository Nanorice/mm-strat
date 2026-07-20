"""Global pytest fixtures and the production-DB write guard.

The guard is the structural defence against tests writing to
data/market_data.duckdb. Every connection in the project funnels through
duckdb.connect (src.db.connect wraps it), so patching that one symbol catches
raw duckdb.connect() and src.db.connect() calls alike.

It is installed in pytest_configure — before collection — so that a module that
opens the DB at import time is caught too. A session-scoped fixture would run
after collection and miss those.
"""

import os
from pathlib import Path

import duckdb
import pytest

import config as project_config  # aliased: pytest hooks take a `config` argument

PROD_DB_PATH = Path(project_config.DUCKDB_PATH).resolve()

_ALLOW_ENV_VAR = "MM_STRAT_ALLOW_PROD_DB"

# Set by the autouse fixture so the error names the offending test.
_current_test = {"nodeid": "<import or collection>"}

_real_connect = None


def _is_prod_db(database) -> bool:
    if database is None:
        return False
    text = str(database)
    if not text or text.startswith(":memory:"):
        return False
    try:
        return Path(text).resolve() == PROD_DB_PATH
    except (OSError, ValueError):
        return False


def pytest_configure(config):
    """Patch duckdb.connect to reject write-mode opens of the production DB.

    Read-only opens are allowed: several tests legitimately inspect the real DB
    and skip when it is absent. Write mode is never legitimate from a test — it
    creates tables in (and can write rows to) the live database, and on the ops
    box it can race the nightly Prefect job. A write-mode open also CREATES the
    file when absent, which is how a bare test run silently produced a stub
    production DB.
    """
    global _real_connect
    if os.getenv(_ALLOW_ENV_VAR) == "1" or _real_connect is not None:
        return

    _real_connect = duckdb.connect

    def guarded_connect(database=":memory:", *args, **kwargs):
        if _is_prod_db(database) and not kwargs.get("read_only", False):
            raise RuntimeError(
                "Test attempted to open the PRODUCTION database in WRITE mode.\n"
                f"  path: {database}\n"
                f"  test: {_current_test['nodeid']}\n"
                "Pass an explicit db_path under tmp_path (see the temp_db fixture "
                "in tests/test_phase1_backfill.py), or open with read_only=True. "
                f"Override with {_ALLOW_ENV_VAR}=1 only if you are certain."
            )
        return _real_connect(database, *args, **kwargs)

    duckdb.connect = guarded_connect


def pytest_unconfigure(config):
    global _real_connect
    if _real_connect is not None:
        duckdb.connect = _real_connect
        _real_connect = None


@pytest.fixture(autouse=True)
def _track_current_test(request):
    """Record the running test's id so the guard error can name it."""
    _current_test["nodeid"] = request.node.nodeid
    yield
    _current_test["nodeid"] = "<between tests>"


@pytest.fixture
def temp_db_path(tmp_path) -> str:
    """Path to a DuckDB file under tmp_path that does NOT yet exist.

    DuckDB refuses to open a pre-created zero-byte file, so the file must be left
    for DuckDB to create — this is why NamedTemporaryFile is the wrong tool.
    """
    return str(tmp_path / "test.duckdb")
