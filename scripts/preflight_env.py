#!/usr/bin/env python3
"""Check required environment variables before running ShowRunner or release workflows."""

from __future__ import annotations

import argparse
import os
import shutil
import sys

DEFAULT_REQUIRED = [
    "OPENAI_API_KEY",
    "YT_API_KEY",
    "FREESOUND_API_KEY",
    "PODBEAN_CLIENT_ID",
    "PODBEAN_CLIENT_SECRET",
    "SUPASET_URL",
    "SUPASET_KEY",
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
        help="Do not require SUPASET_*.",
    )
    parser.add_argument(
        "--require-ffmpeg",
        action="store_true",
        help="Require ffmpeg and ffprobe on PATH.",
    )
    args = parser.parse_args()

    required = list(DEFAULT_REQUIRED)
    if args.skip_podbean:
        required = [k for k in required if not k.startswith("PODBEAN_")]
    if args.skip_supabase:
        required = [k for k in required if not k.startswith("SUPASET_")]

    missing = [k for k in required if not os.getenv(k)]

    if args.require_ffmpeg:
        for bin_name in ("ffmpeg", "ffprobe"):
            if shutil.which(bin_name) is None:
                missing.append(bin_name)

    if missing:
        print(f"Missing or not on PATH: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1 if args.strict else 0)

    print("Preflight OK: required variables (and optional ffmpeg tools) are present.")
    sys.exit(0)


if __name__ == "__main__":
    main()
