#!/usr/bin/env python3
"""Local Supabase provisioning CLI; see docs/supabase.md."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _supabase_argv(extra: list[str]) -> list[str]:
    if shutil.which("supabase"):
        return ["supabase", *extra]
    if shutil.which("npx"):
        return ["npx", "--yes", "supabase@latest", *extra]
    print(
        "Install Supabase CLI: https://supabase.com/docs/guides/cli "
        "or ensure `npx` is available.",
        file=sys.stderr,
    )
    sys.exit(1)


def _run(
    argv: list[str],
    *,
    check: bool = True,
    capture_text: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        argv,
        cwd=_REPO_ROOT,
        env=env,
        text=capture_text,
        capture_output=capture_text,
        check=check,
    )


def _run_supabase(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return _run(_supabase_argv(args), **kwargs)  # type: ignore[arg-type]


def _projects_list_json() -> list[dict[str, object]]:
    proc = _run_supabase(["projects", "list", "-o", "json"], check=False)
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout or "projects list failed", file=sys.stderr)
        sys.exit(proc.returncode or 1)
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Could not parse `supabase projects list -o json` output.", file=sys.stderr)
        print(raw[:2000], file=sys.stderr)
        sys.exit(1)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _wait_for_project_ready(project_ref: str, timeout_s: int = 900) -> None:
    deadline = time.time() + timeout_s
    print(f"Waiting for project {project_ref} to become healthy (timeout {timeout_s}s)...")
    while time.time() < deadline:
        rows = _projects_list_json()
        match = None
        for row in rows:
            ref = str(row.get("id") or row.get("ref") or "")
            if ref == project_ref:
                match = row
                break
        if match is None:
            print("Project not listed yet — waiting...")
            time.sleep(10)
            continue
        status = str(match.get("status") or match.get("project_status") or "")
        print(f"Project status: {status or 'unknown'}")
        st = status.upper().replace(" ", "_")
        if "ACTIVE_HEALTHY" in st:
            return
        if "FAILED" in st and "RESTORE" not in st:
            print("Project reports a failure status.", file=sys.stderr)
            sys.exit(1)
        time.sleep(10)
    print("Timed out waiting for project to become active.", file=sys.stderr)
    sys.exit(1)


def _resolve_project_ref_after_create(name: str) -> str:
    for row in _projects_list_json():
        if str(row.get("name") or "") == name:
            ref = str(row.get("id") or row.get("ref") or "")
            if ref:
                return ref
    print(
        f"Could not find project ref for name {name!r} in `supabase projects list`.",
        file=sys.stderr,
    )
    sys.exit(1)


def _fetch_api_keys(project_ref: str) -> tuple[str | None, str | None]:
    proc = _run_supabase(
        ["projects", "api-keys", "--project-ref", project_ref, "-o", "json"],
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout or "api-keys failed", file=sys.stderr)
        sys.exit(proc.returncode or 1)
    raw = (proc.stdout or "").strip()
    anon_key: str | None = None
    service_key: str | None = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Could not parse api-keys JSON; paste keys manually from the dashboard.", file=sys.stderr)
        print(raw[:2000], file=sys.stderr)
        sys.exit(1)

    rows: list[dict[str, object]] = []
    if isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        rows = [data]

    for row in rows:
        name = str(row.get("name") or row.get("type") or row.get("id") or "").lower()
        key = row.get("api_key") or row.get("apiKey") or row.get("key")
        if not isinstance(key, str):
            continue
        if "anon" in name:
            anon_key = key
        if "service" in name:
            service_key = key

    return anon_key, service_key


def _link(project_ref: str) -> None:
    proc = _run_supabase(["link", "--project-ref", project_ref], check=False)
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout or "link failed", file=sys.stderr)
        sys.exit(proc.returncode or 1)


def _db_push(dry_run: bool) -> None:
    args = ["db", "push"]
    if dry_run:
        args.append("--dry-run")
    proc = _run_supabase(args, check=False)
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout or "db push failed", file=sys.stderr)
        sys.exit(proc.returncode or 1)
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)


def _create_bucket(url: str, service_key: str, bucket: str) -> None:
    env = os.environ.copy()
    env["SUPABASE_URL"] = url
    env["SUPABASE_SERVICE_ROLE_KEY"] = service_key
    proc = subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "supabase_create_bucket.py"), "--bucket", bucket],
        cwd=_REPO_ROOT,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        sys.exit(proc.returncode)


def _print_outputs(url: str, service_key: str, anon_key: str | None, bucket: str) -> None:
    print("\n" + "=" * 72)
    print("# Add or merge into local .env (do not commit real secrets)")
    print("=" * 72)
    print(f"SUPABASE_URL={url}")
    print(f"SUPABASE_SERVICE_ROLE_KEY={service_key}")
    if anon_key:
        print(f"SUPABASE_ANON_KEY={anon_key}")
    print(f"# Legacy aliases (workflows may still expect these names)")
    print(f"SUPASET_URL={url}")
    print(f"SUPASET_KEY={service_key}")
    print(f"# Storage bucket used by configs/configv3.yaml supabaseBucketManager")
    print(f"SUPABASE_STORAGE_BUCKET={bucket}")

    print("\n" + "=" * 72)
    print("# GitHub Actions repository secrets (paste values from above)")
    print("# Do NOT add SUPABASE_ACCESS_TOKEN here — keep PAT local for bootstrap only.")
    print("=" * 72)
    print("SUPABASE_URL")
    print("SUPABASE_SERVICE_ROLE_KEY")
    print("# Or keep existing secret names until you rename workflows:")
    print("SUPASET_URL   # same value as SUPABASE_URL")
    print("SUPASET_KEY   # same value as SUPABASE_SERVICE_ROLE_KEY")

    print("\n" + "=" * 72)


def main() -> None:
    load_dotenv(_REPO_ROOT / ".env", override=False)

    parser = argparse.ArgumentParser(
        description=(
            "Provision hosted Supabase: optional projects create, db push migrations, "
            "storage bucket, then print .env / GitHub secret hints."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Loads repo-root .env (dotenv, override=False). Requires Supabase CLI or npx.\n"
            "Bootstrap env: SUPABASE_ACCESS_TOKEN; create mode also needs ORG_ID, REGION, "
            "DB_PASSWORD, PROJECT_NAME (or positional). Link-only: set SUPABASE_PROJECT_REF.\n"
            "Do not put SUPABASE_ACCESS_TOKEN in GitHub Actions."
        ),
    )
    parser.add_argument(
        "project_name",
        nargs="?",
        default=os.getenv("SUPABASE_PROJECT_NAME"),
        help="Project display name for create mode (else SUPABASE_PROJECT_NAME).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass --dry-run to supabase db push.",
    )
    parser.add_argument(
        "--skip-bucket",
        action="store_true",
        help="Skip storage bucket creation.",
    )
    parser.add_argument(
        "--bucket",
        default=os.getenv("SUPABASE_STORAGE_BUCKET", "llmfh"),
        help="Storage bucket to create (default llmfh).",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=int(os.getenv("SUPABASE_BOOTSTRAP_WAIT_S", "900")),
        help="Seconds to wait for new project to become active.",
    )
    args = parser.parse_args()

    token = os.getenv("SUPABASE_ACCESS_TOKEN")
    if not token:
        print("SUPABASE_ACCESS_TOKEN is required for CLI operations.", file=sys.stderr)
        sys.exit(1)

    project_ref = (os.getenv("SUPABASE_PROJECT_REF") or "").strip()
    project_name = (args.project_name or "").strip()

    if not project_ref:
        org = os.getenv("SUPABASE_ORG_ID")
        region = os.getenv("SUPABASE_REGION")
        db_pass = os.getenv("SUPABASE_DB_PASSWORD")
        if not project_name:
            print(
                "Provide SUPABASE_PROJECT_REF for link-only mode, or set "
                "SUPABASE_PROJECT_NAME / pass NAME for create mode.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not org or not region or not db_pass:
            print(
                "Create mode requires SUPABASE_ORG_ID, SUPABASE_REGION, SUPABASE_DB_PASSWORD.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Creating hosted project {project_name!r}...")
        proc = _run_supabase(
            [
                "projects",
                "create",
                project_name,
                "--org-id",
                org,
                "--region",
                region,
                "--db-password",
                db_pass,
            ],
            check=False,
        )
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout or "projects create failed", file=sys.stderr)
            if proc.stdout:
                print(proc.stdout, file=sys.stderr)
            print(
                "\nIf the name already exists, set SUPABASE_PROJECT_REF to that project's ref "
                "and rerun without create inputs.",
                file=sys.stderr,
            )
            sys.exit(proc.returncode or 1)
        if proc.stdout:
            print(proc.stdout)
        project_ref = _resolve_project_ref_after_create(project_name)

    assert project_ref
    print(f"Using project ref: {project_ref}")

    _wait_for_project_ready(project_ref, timeout_s=args.wait_timeout)

    anon_key, service_key = _fetch_api_keys(project_ref)
    if not service_key:
        print("Could not read service_role API key from CLI output.", file=sys.stderr)
        sys.exit(1)

    url = f"https://{project_ref}.supabase.co"

    print("Linking CLI to project...")
    _link(project_ref)

    print("Pushing migrations...")
    _db_push(args.dry_run)

    if args.dry_run:
        print("Dry-run: skipping bucket creation. Printing keys for reference.")
        _print_outputs(url, service_key, anon_key, args.bucket)
        return

    if not args.skip_bucket:
        print("Creating storage bucket...")
        _create_bucket(url, service_key, args.bucket)

    _print_outputs(url, service_key, anon_key, args.bucket)


if __name__ == "__main__":
    main()
