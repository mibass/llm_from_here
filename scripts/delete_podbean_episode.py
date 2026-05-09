#!/usr/bin/env python3
"""Delete Podbean episode(s) whose title contains a substring (case-insensitive).

Uses PODBEAN_CLIENT_ID / PODBEAN_CLIENT_SECRET from the environment or repo-root .env.

Example:
  uv run python scripts/delete_podbean_episode.py --match "Episode 65"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import dotenv
import requests
from requests.auth import HTTPBasicAuth

REPO_ROOT = Path(__file__).resolve().parent.parent


def _token(client_id: str, client_secret: str, timeout: float) -> str:
    url = "https://api.podbean.com/v1/oauth/token"
    response = requests.post(
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
        auth=HTTPBasicAuth(client_id, client_secret),
        timeout=timeout,
    )
    if response.status_code != 200:
        sys.stderr.write(f"OAuth failed: {response.status_code} {response.text}\n")
        sys.exit(1)
    return response.json()["access_token"]


def _list_episodes(access_token: str, *, limit: int, timeout: float) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        url = "https://api.podbean.com/v1/episodes"
        response = requests.get(
            url,
            params={
                "access_token": access_token,
                "offset": offset,
                "limit": limit,
            },
            timeout=timeout,
        )
        if response.status_code != 200:
            sys.stderr.write(f"List episodes failed: {response.status_code} {response.text}\n")
            sys.exit(1)
        batch = response.json().get("episodes") or []
        out.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return out


def _delete_episode(access_token: str, episode_id: str, timeout: float) -> dict:
    url = f"https://api.podbean.com/v1/episodes/{episode_id}/delete"
    response = requests.post(
        url,
        data={"access_token": access_token, "delete_media_file": "yes"},
        timeout=timeout,
    )
    if response.status_code != 200:
        sys.stderr.write(f"Delete failed: {response.status_code} {response.text}\n")
        sys.exit(1)
    return response.json()


def main() -> None:
    dotenv.load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--match",
        default="Episode 65",
        help="Case-insensitive substring to match against episode titles.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching episodes but do not delete.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Page size for Podbean list endpoint.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout seconds.",
    )
    args = parser.parse_args()

    client_id = os.getenv("PODBEAN_CLIENT_ID")
    client_secret = os.getenv("PODBEAN_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.stderr.write("Missing PODBEAN_CLIENT_ID or PODBEAN_CLIENT_SECRET.\n")
        sys.exit(1)

    needle = args.match.lower()
    token = _token(client_id, client_secret, args.timeout)
    episodes = _list_episodes(token, limit=args.limit, timeout=args.timeout)
    hits = [e for e in episodes if needle in (e.get("title") or "").lower()]

    if not hits:
        print(f"No episodes matched {args.match!r} (searched {len(episodes)} episode(s)).")
        sys.exit(1)

    for e in hits:
        eid = e.get("id")
        title = e.get("title")
        print(f"{'Would delete' if args.dry_run else 'Deleting'}: id={eid} title={title!r}")

    if args.dry_run:
        return

    for e in hits:
        body = _delete_episode(token, str(e["id"]), args.timeout)
        print(f"Deleted ok: {body}")


if __name__ == "__main__":
    main()
