#!/usr/bin/env python3
"""Check required environment variables before running ShowRunner or release workflows."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from llm_from_here.plugins.ytfetch import _resolved_deno_executable
from llm_from_here.supabase_env import get_supabase_service_role_key, get_supabase_url


def _load_repo_dotenv() -> None:
    """Match ShowRunner/plugins: read repo-root `.env` so preflight sees the same keys."""
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env")

DEFAULT_REQUIRED = [
    "OPENROUTER_API_KEY",
    "YT_API_KEY",
    "FREESOUND_API_KEY",
    "PODBEAN_CLIENT_ID",
    "PODBEAN_CLIENT_SECRET",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify LLM From Here external-service environment variables.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 1 if any required variable is missing or empty.",
    )
    parser.add_argument(
        "--skip-podbean",
        action="store_true",
        help="Do not require PODBEAN_* (e.g. non-prod run without publishing).",
    )
    parser.add_argument(
        "--skip-supabase",
        action="store_true",
        help="Do not require Supabase URL + API key (SUPABASE_* or SUPASET_*).",
    )
    parser.add_argument(
        "--require-ffmpeg",
        action="store_true",
        help="Require ffmpeg and ffprobe on PATH.",
    )
    parser.add_argument(
        "--require-deno",
        action="store_true",
        help="Require Deno for yt-dlp YouTube JS/EJS (YT_DLP_DENO, PATH, or ~/.deno/bin/deno).",
    )
    args = parser.parse_args()
    _load_repo_dotenv()

    required = list(DEFAULT_REQUIRED)
    if args.skip_podbean:
        required = [k for k in required if not k.startswith("PODBEAN_")]
    missing = [k for k in required if not os.getenv(k)]
    if not args.skip_supabase:
        if not get_supabase_url():
            missing.append("SUPABASE_URL (or SUPASET_URL)")
        if not get_supabase_service_role_key():
            missing.append("SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_API_KEY or SUPASET_KEY)")

    if args.require_ffmpeg:
        for bin_name in ("ffmpeg", "ffprobe"):
            if shutil.which(bin_name) is None:
                missing.append(bin_name)

    if args.require_deno and _resolved_deno_executable() is None:
        missing.append("deno")

    if missing:
        print(f"Missing or not on PATH: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1 if args.strict else 0)

    print(
        "Preflight OK: required variables (and optional ffmpeg/deno checks) are present."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
