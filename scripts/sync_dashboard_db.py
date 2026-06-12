"""Upload data/dashboard.duckdb to Cloudflare R2 for remote dashboard serving.

Uploads to two keys in the bucket:
  latest/dashboard.duckdb   — always overwritten (what the cloud host pulls)
  archive/YYYY-MM-DD/dashboard.duckdb — dated snapshot (optional, --no-archive to skip)

Credentials read from env / .env:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME

Usage:
    python scripts/sync_dashboard_db.py [--db PATH] [--no-archive] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "dashboard.duckdb"


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


def upload(db_path: Path, bucket: str, key: str, dry_run: bool) -> None:
    size_mb = db_path.stat().st_size / 1024 ** 2
    print(f"  {'[DRY-RUN] ' if dry_run else ''}upload {db_path.name} ({size_mb:,.0f} MB) -> s3://{bucket}/{key}")
    if dry_run:
        return
    client = _r2_client()
    client.upload_file(
        str(db_path),
        bucket,
        key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync dashboard.duckdb to Cloudflare R2")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to dashboard.duckdb")
    parser.add_argument("--no-archive", action="store_true", help="Skip dated archive copy")
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

    print(f"[SYNC] {args.db.name} -> R2 bucket '{bucket}'")
    upload(args.db, bucket, "latest/dashboard.duckdb", args.dry_run)

    if not args.no_archive:
        archive_key = f"archive/{date.today().isoformat()}/dashboard.duckdb"
        upload(args.db, bucket, archive_key, args.dry_run)

    print("[OK] Sync complete")


if __name__ == "__main__":
    main()
