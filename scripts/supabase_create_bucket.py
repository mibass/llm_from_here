#!/usr/bin/env python3
"""Create the Storage bucket used by supabaseBucketManager (idempotent)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    load_dotenv(_REPO_ROOT / ".env", override=False)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bucket",
        default=os.getenv("SUPABASE_STORAGE_BUCKET", "llmfh"),
        help="Bucket name (default: llmfh or SUPABASE_STORAGE_BUCKET).",
    )
    args = parser.parse_args()

    try:
        from supabase import create_client

        from llm_from_here.supabase_env import require_supabase_credentials
    except ImportError:
        print("Run from repo root: uv run python scripts/supabase_create_bucket.py", file=sys.stderr)
        raise

    url, key = require_supabase_credentials()
    client = create_client(url, key)

    try:
        client.storage.create_bucket(args.bucket, options={"public": False})
        print(f"Created storage bucket: {args.bucket}")
    except Exception as e:
        err = str(e).lower()
        if "already exists" in err or "duplicate" in err or "409" in err:
            print(f"Storage bucket already exists (ok): {args.bucket}")
            return
        print(f"Failed to create bucket {args.bucket}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
