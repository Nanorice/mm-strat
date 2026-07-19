"""Upload dashboard assets to Cloudflare R2 for remote dashboard serving.

Syncs two things, both overwriting in place (no versioned archive — 782 MB/day
would exhaust the 10 GB R2 free tier in under 2 weeks):
  - latest/dashboard.duckdb        the slim DB (tables + materialized views)
  - latest/model_cards/<file>      model card HTML/JSON (~700 KB) so the cloud
                                   Model Lab renders cards (they're disk files,
                                   not DB rows)

Credentials read from env / .env:
  R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET_NAME

Usage:
    python scripts/sync_dashboard_db.py [--db PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "dashboard.duckdb"

# Anchor to project root so creds load regardless of CWD (standalone runs from
# Task Scheduler launch with CWD=C:\Windows\System32).
load_dotenv(PROJECT_ROOT / ".env")

# Disk-file dirs the dashboard pages read but that aren't in the DB. Each is
# mirrored (recursively) under latest/<r2_prefix>/ on R2, filtered to render
# assets only — never model.json (we don't want live-scoring resurrected) or
# raw data files. data/backtest/ is intentionally omitted (WIP, 112 MB) — add
# it here once local space is cleaned up. Keep in sync with dashboard_utils
# ASSET_DIRS (the pull-on-boot side).
#   (local_dir, r2_prefix, allowed_suffixes)
ASSET_DIRS: list[tuple[Path, str, tuple[str, ...]]] = [
    (PROJECT_ROOT / "model_cards",        "model_cards",   (".html", ".json")),
    (PROJECT_ROOT / "data" / "audit_reports", "audit_reports", (".json",)),
    (PROJECT_ROOT / "docs" / "reports",   "docs_reports",  (".html",)),
    # Model artifact plots/reports for the Model Lab plot + report tabs. Includes
    # .md/.json reports (results.json, diffs, report_*.md) but NOT model.json —
    # the weights are filtered by name in upload_asset_dir so live-scoring can't
    # be resurrected on the serving host.
    (PROJECT_ROOT / "models",             "model_artifacts", (".png", ".html", ".csv", ".txt", ".md", ".json")),
    # Cone fan: one equity curve per sweep cell. ~2.5k files / 22 MB, and they are
    # FROZEN research artifacts — the ETag skip above makes this a one-time cost,
    # ~0 MB/day after. Without it the remote cone renders no fan (the page says so).
    # Deliberately equity-only: trades.parquet + rejections.parquet are another
    # 78 MB and only feed the per-cell zoom, which stays dev-box-local
    # (cone_and_studio_design.md §4). If the zoom is ever wanted remotely, ship a
    # materialized rejection SUMMARY in the slim DB, not 125k raw rows per cell.
    (PROJECT_ROOT / "data" / "selection_sweep" / "starttime", "sweep_starttime", (".parquet",)),
]

# Filenames allowed through for sweep_starttime — the suffix filter alone would
# pull trades/rejections too.
SWEEP_KEEP = {"equity.parquet"}


def _r2_client():
    import boto3

    account_id = os.environ["R2_ACCOUNT_ID"]
    endpoint = os.environ.get("R2_JURI_ENDPOINT_URL") or f"https://{account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
    )


def upload(db_path: Path, bucket: str, key: str, dry_run: bool, client=None) -> None:
    size_mb = db_path.stat().st_size / 1024 ** 2
    print(f"  {'[DRY-RUN] ' if dry_run else ''}upload {db_path.name} ({size_mb:,.0f} MB) -> s3://{bucket}/{key}")
    if dry_run:
        return
    client = client or _r2_client()
    client.upload_file(
        str(db_path),
        bucket,
        key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )


_CTYPE = {".html": "text/html", ".json": "application/json", ".png": "image/png",
          ".csv": "text/csv", ".txt": "text/plain"}


def _list_remote(client, bucket: str, prefix: str) -> dict[str, tuple[int, str]]:
    """Map key -> (size, etag) for every object under prefix (paginated).

    One list call replaces a HEAD-per-file: lets the asset sync skip unchanged
    files instead of re-uploading the (frozen) model-artifact tree every day.
    """
    remote: dict[str, tuple[int, str]] = {}
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = client.list_objects_v2(**kw)
        for o in resp.get("Contents", []):
            remote[o["Key"]] = (o["Size"], o["ETag"].strip('"'))
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return remote


def _file_md5(path: Path) -> str:
    import hashlib

    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unchanged(local: Path, remote: tuple[int, str] | None) -> bool:
    """True if the R2 object already matches local. Single-part ETag is the
    content MD5 (exact compare); multipart ETag (">8MB, has '-') falls back to
    size — safe here because asset files are frozen artifacts, not the
    daily-rebuilt DB (which is uploaded unconditionally)."""
    if remote is None:
        return False
    size, etag = remote
    if local.stat().st_size != size:
        return False
    if "-" in etag:
        return True
    return _file_md5(local) == etag


def upload_asset_dir(local_dir: Path, r2_prefix: str, suffixes: tuple[str, ...],
                     bucket: str, dry_run: bool, client=None,
                     remote: dict[str, tuple[int, str]] | None = None) -> int:
    """Mirror local_dir (recursively) to latest/<r2_prefix>/, keeping relative
    paths and only files whose suffix is in `suffixes`. Skips files already
    present unchanged on R2. Returns the count actually uploaded."""
    remote = remote or {}
    if not local_dir.exists():
        print(f"  [SKIP] {local_dir.name}/ not found")
        return 0
    # model.json is the trained weights — never ship it (keeps the serving host
    # read-only and stops live-scoring creeping back). All other .json (cards,
    # results, diffs) are fine.
    # The sweep tree is suffix-uniform (.parquet), so it needs a name allowlist on
    # top: equity feeds the cone fan, trades/rejections are 78 MB of dev-box zoom.
    keep = SWEEP_KEEP if r2_prefix == "sweep_starttime" else None
    files = sorted(
        f for f in local_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in suffixes and f.name != "model.json"
        and (keep is None or f.name in keep)
    )
    if not files:
        print(f"  [SKIP] {local_dir.name}/ — no matching files")
        return 0
    pending = [
        (f, f"latest/{r2_prefix}/{f.relative_to(local_dir).as_posix()}")
        for f in files
    ]
    pending = [(f, key) for f, key in pending if not _unchanged(f, remote.get(key))]
    skipped = len(files) - len(pending)
    total_mb = sum(f.stat().st_size for f, _ in pending) / 1024 ** 2
    print(f"  {'[DRY-RUN] ' if dry_run else ''}upload {len(pending)} files "
          f"({total_mb:,.1f} MB), skip {skipped} unchanged -> s3://{bucket}/latest/{r2_prefix}/")
    if dry_run:
        return len(pending)
    client = client or _r2_client()
    for f, key in pending:
        ctype = _CTYPE.get(f.suffix.lower(), "application/octet-stream")
        client.upload_file(str(f), bucket, key, ExtraArgs={"ContentType": ctype})
    return len(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync dashboard.duckdb to Cloudflare R2")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to dashboard.duckdb")
    parser.add_argument("--dry-run", action="store_true", help="Print actions, don't upload")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"[ERR] DB not found: {args.db}")
        sys.exit(1)

    missing = [k for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET_NAME") if not os.environ.get(k)]
    if missing:
        print(f"[ERR] Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    bucket = os.environ["R2_BUCKET_NAME"]
    print(f"[SYNC] -> R2 bucket '{bucket}'")
    # One client for everything. Listing is read-only, so we do it even on
    # dry-run to report the real changed/unchanged split. The slim DB is
    # rebuilt fresh daily, so it always uploads (no skip check).
    client = _r2_client()
    remote = _list_remote(client, bucket, "latest/")
    upload(args.db, bucket, "latest/dashboard.duckdb", args.dry_run, client=client)
    for local_dir, prefix, suffixes in ASSET_DIRS:
        upload_asset_dir(local_dir, prefix, suffixes, bucket, args.dry_run,
                         client=client, remote=remote)
    print("[OK] Sync complete")


if __name__ == "__main__":
    main()
