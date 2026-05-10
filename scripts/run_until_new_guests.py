#!/usr/bin/env python3
"""
Run ShowRunner with --clear-cache; kill + retry if intro repeats the same guest multiset
as the latest lineup prior to this invocation (detected via showRunner.log).
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "showRunner.log")


def line_count(path: str) -> int:
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def fingerprint_intro_guests_after(path: str, min_line: int) -> tuple[str, ...] | None:
    latest: tuple[str, ...] | None = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, start=1):
            if i <= min_line:
                continue
            if "introFromGuestlist" not in line or "Found guests:" not in line:
                continue
            payload = line.split("Found guests:", 1)[1].strip()
            try:
                data = ast.literal_eval(payload)
                latest = tuple(sorted(x["guest_name"] for x in data))
            except (SyntaxError, ValueError, KeyError, TypeError):
                continue
    return latest


def last_fingerprint(path: str) -> tuple[str, ...] | None:
    return fingerprint_intro_guests_after(path, 0)


def main() -> int:
    yaml_rel = sys.argv[1] if len(sys.argv) > 1 else "configs/configv3.yaml"
    yaml_path = yaml_rel if os.path.isabs(yaml_rel) else os.path.join(REPO, yaml_rel)

    avoid = last_fingerprint(LOG)
    print("Baseline lineup fingerprint (sorted guest names, multiset):", avoid)

    max_attempts = int(os.environ.get("LLMFH_MAX_GUEST_RETRY", "25"))
    poll_sec = float(os.environ.get("LLMFH_GUEST_POLL_SEC", "4"))
    per_attempt_deadline_sec = float(os.environ.get("LLMFH_ATTEMPT_DEADLINE_SEC", str(3 * 3600)))

    for attempt in range(1, max_attempts + 1):
        lines_before = line_count(LOG)
        print(f"\n=== Attempt {attempt}/{max_attempts} (log lines before: {lines_before}) ===")

        proc = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "-m",
                "llm_from_here.showRunner",
                yaml_path,
                "--clear-cache",
            ],
            cwd=REPO,
        )

        start = time.monotonic()
        guest_fp: tuple[str, ...] | None = None

        while proc.poll() is None:
            if time.monotonic() - start > per_attempt_deadline_sec:
                print("Attempt deadline exceeded — killing")
                proc.terminate()
                try:
                    proc.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break

            time.sleep(poll_sec)
            guest_fp = fingerprint_intro_guests_after(LOG, lines_before)
            if guest_fp is None:
                continue

            if avoid is not None and guest_fp == avoid:
                print("Duplicate lineup vs baseline — terminating run:", guest_fp)
                proc.terminate()
                try:
                    proc.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break

            print("New lineup vs baseline — letting run finish:", guest_fp)
            rc = proc.wait()
            print(f"ShowRunner finished with exit code {rc}")
            return rc if rc == 0 else 1

        rc = proc.poll()
        if rc is not None and rc != 0 and guest_fp is None:
            print(f"ShowRunner exited early with code {rc} before intro guests appeared")

        if attempt == max_attempts:
            print("Exceeded max attempts")
            return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
