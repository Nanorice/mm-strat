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

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "dashboard.duckdb"

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
    # Model artifact plots/reports for the Model Lab plot tabs. Excludes
    # model.json (the weights) by suffix allow-list.
    (PROJECT_ROOT / "models",             "model_artifacts", (".png", ".html", ".csv", ".txt")),
]


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


def upload_asset_dir(local_dir: Path, r2_prefix: str, suffixes: tuple[str, ...],
                     bucket: str, dry_run: bool, client=None) -> int:
    """Mirror local_dir (recursively) to latest/<r2_prefix>/, keeping relative
    paths and only files whose suffix is in `suffixes`. Returns file count."""
    if not local_dir.exists():
        print(f"  [SKIP] {local_dir.name}/ not found")
        return 0
    files = sorted(
        f for f in local_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in suffixes
    )
    if not files:
        print(f"  [SKIP] {local_dir.name}/ — no matching files")
        return 0
    total_mb = sum(f.stat().st_size for f in files) / 1024 ** 2
    print(f"  {'[DRY-RUN] ' if dry_run else ''}upload {len(files)} files "
          f"({total_mb:,.1f} MB) -> s3://{bucket}/latest/{r2_prefix}/")
    if dry_run:
        return len(files)
    client = client or _r2_client()
    for f in files:
        rel = f.relative_to(local_dir).as_posix()
        ctype = _CTYPE.get(f.suffix.lower(), "application/octet-stream")
        client.upload_file(str(f), bucket, f"latest/{r2_prefix}/{rel}",
                           ExtraArgs={"ContentType": ctype})
    return len(files)


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
    # One client for all uploads (skip construction entirely on dry-run).
    client = None if args.dry_run else _r2_client()
    upload(args.db, bucket, "latest/dashboard.duckdb", args.dry_run, client=client)
    for local_dir, prefix, suffixes in ASSET_DIRS:
        upload_asset_dir(local_dir, prefix, suffixes, bucket, args.dry_run, client=client)
    print("[OK] Sync complete")


if __name__ == "__main__":
    main()
