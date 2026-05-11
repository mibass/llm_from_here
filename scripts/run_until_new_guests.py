#!/usr/bin/env python3
"""
Run ShowRunner with --clear-cache; kill + retry if intro repeats the same guest multiset
as the latest lineup prior to this invocation (read from the newest ``outputs/*/show_runner.log``).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUTS = os.path.join(REPO, "outputs")


def iter_show_runner_logs(outputs_dir: str):
    try:
        subdirs = os.listdir(outputs_dir)
    except OSError:
        return
    for name in subdirs:
        p = os.path.join(outputs_dir, name, "show_runner.log")
        if os.path.isfile(p):
            yield p


def latest_show_runner_log(outputs_dir: str) -> str | None:
    paths = list(iter_show_runner_logs(outputs_dir))
    if not paths:
        return None
    return max(paths, key=lambda p: os.stat(p).st_mtime)


def latest_intro_guest_fingerprint(path: str | None) -> tuple[str, ...] | None:
    if not path:
        return None
    latest: tuple[str, ...] | None = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "introFromGuestlist" not in line or "Found guests:" not in line:
                    continue
                payload = line.split("Found guests:", 1)[1].strip()
                try:
                    data = ast.literal_eval(payload)
                    latest = tuple(sorted(x["guest_name"] for x in data))
                except (SyntaxError, ValueError, KeyError, TypeError):
                    continue
    except OSError:
        return None
    return latest


def main() -> int:
    yaml_rel = sys.argv[1] if len(sys.argv) > 1 else "configs/configv3.yaml"
    yaml_path = yaml_rel if os.path.isabs(yaml_rel) else os.path.join(REPO, yaml_rel)

    outputs_dir = DEFAULT_OUTPUTS
    baseline_path = latest_show_runner_log(outputs_dir)
    avoid = latest_intro_guest_fingerprint(baseline_path)
    print("Baseline lineup fingerprint (sorted guest names, multiset):", avoid)

    max_attempts = int(os.environ.get("LLMFH_MAX_GUEST_RETRY", "25"))
    poll_sec = float(os.environ.get("LLMFH_GUEST_POLL_SEC", "4"))
    per_attempt_deadline_sec = float(os.environ.get("LLMFH_ATTEMPT_DEADLINE_SEC", str(3 * 3600)))

    for attempt in range(1, max_attempts + 1):
        known_before = {p: os.stat(p).st_mtime for p in iter_show_runner_logs(outputs_dir)}
        print(f"\n=== Attempt {attempt}/{max_attempts} ===")

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
            path = latest_show_runner_log(outputs_dir)
            if path is None:
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            if path in known_before and st.st_mtime <= known_before[path]:
                continue

            guest_fp = latest_intro_guest_fingerprint(path)
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
