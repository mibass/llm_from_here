#!/usr/bin/env python3
"""Quality eval for ``guest_agent`` with LLM-as-judge (manual / pre-release).

Requires ``OPENROUTER_API_KEY``, ``YT_API_KEY``, and keys configured for ``get_structured_model()``.
Judge uses OpenRouter ``openrouter:openai/gpt-4o`` by default (override via ``LLMFH_EVAL_JUDGE_MODEL``).

Examples::

    uv run python evals/eval_guest_agent.py
    uv run python evals/eval_guest_agent.py --guest \"Yo-Yo Ma\"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from llm_from_here.agents.guest_agent import (  # noqa: E402
    GuestAgentDeps,
    clear_guest_agent_cache_for_tests,
    get_guest_agent,
    strip_guest_queue_prefix,
)
from llm_from_here.llm_session import LlmSession  # noqa: E402
from llm_from_here.models.guest_models import GuestSegment  # noqa: E402
from llm_from_here.plugins.ytfetch import YtFetch  # noqa: E402


class JudgeScores(BaseModel):
    relevance: int = Field(ge=0, le=4)
    appropriateness: int = Field(ge=0, le=4)
    intro_quality: int = Field(ge=0, le=4)


def load_fixture_guests(path: Path, guest_filter: str | None) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if guest_filter:
        rows = [r for r in rows if r.get("guest_name") == guest_filter]
        if not rows:
            raise SystemExit(f"No fixture guest named {guest_filter!r}")
    return rows


def run_guest_agent_row(row: dict) -> GuestSegment:
    yt = YtFetch(video_ids_supaset_autoexpire_days=90)
    try:
        raw_name = str(row.get("guest_name") or "")
        deps = GuestAgentDeps(
            yt_fetch=yt,
            duration_min_sec=180,
            duration_max_sec=660,
            guest_category=row["guest_category"],
            guest_name=raw_name,
            guest_match_name=strip_guest_queue_prefix(raw_name),
        )
        agent = get_guest_agent()
        user_msg = (
            f'Guest category: {row["guest_category"]}. Guest name: {row["guest_name"]!r}. '
            "Find one appropriate YouTube clip for this guest."
        )
        result = agent.run_sync(user_msg, deps=deps)
        return result.output
    finally:
        yt.finalize()


def fetch_video_meta(yt: YtFetch, video_id: str) -> dict[str, str]:
    return yt.get_video_basic_info(video_id)


def judge_row(judge: LlmSession, row: dict, segment: GuestSegment, meta: dict[str, str]) -> JudgeScores:
    prompt = f"""Score this clip selection for a nostalgic uplifting variety show (0-4 each dimension).

Guest fixture:
  name: {row["guest_name"]}
  category: {row["guest_category"]}

Agent output GuestSegment:
  video_id: {segment.video_id}
  intro_sentence: {segment.intro_sentence}
  duration_seconds: {segment.duration_seconds}

YouTube metadata:
  title: {meta["title"]}
  channel: {meta["channel_title"]}
  description (truncated): {meta["description"][:1200]}

Dimensions:
- relevance: does the clip match the named guest and category?
- appropriateness: uplifting / avoids controversy & politics?
- intro_quality: does intro_sentence mention the guest and read like a host intro?

Respond ONLY via structured output JudgeScores with integer fields relevance, appropriateness, intro_quality.
"""
    out = judge.run_structured(prompt, JudgeScores, log_prompt=False)
    return JudgeScores.model_validate(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="guest_agent LLM-as-judge eval")
    ap.add_argument("--guest", type=str, default=None, help="single fixture guest_name")
    ap.add_argument(
        "--fixtures",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "guests.json",
    )
    args = ap.parse_args()

    if not os.getenv("OPENROUTER_API_KEY") or not os.getenv("YT_API_KEY"):
        print("Set OPENROUTER_API_KEY and YT_API_KEY", file=sys.stderr)
        return 2

    rows = load_fixture_guests(args.fixtures, args.guest)
    judge_model = os.getenv(
        "LLMFH_EVAL_JUDGE_MODEL", "openrouter:openai/gpt-4o"
    ).strip()
    judge = LlmSession(system_message="You score podcast clip selections precisely.", model_slug=judge_model)

    results: list[dict] = []
    yt_probe = YtFetch(video_ids_supaset_autoexpire_days=90)
    try:
        for row in rows:
            clear_guest_agent_cache_for_tests()
            segment = run_guest_agent_row(row)
            meta = fetch_video_meta(yt_probe, segment.video_id)
            scores = judge_row(judge, row, segment, meta)
            passed = (
                scores.relevance >= 2
                and scores.appropriateness >= 2
                and scores.intro_quality >= 2
            )
            results.append(
                {
                    "guest_name": row["guest_name"],
                    "guest_category": row["guest_category"],
                    "video_id": segment.video_id,
                    "title": meta["title"],
                    "scores": scores.model_dump(),
                    "pass": passed,
                }
            )
            flag = "PASS" if passed else "FAIL"
            print(
                f"{flag} {row['guest_name']!r} vid={segment.video_id} "
                f"R={scores.relevance} A={scores.appropriateness} I={scores.intro_quality}"
            )
    finally:
        yt_probe.finalize()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(__file__).parent / "results" / f"eval_guest_agent_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": ts, "judge_model": judge_model, "results": results}
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")

    passes = sum(1 for r in results if r["pass"])
    need = 6 if len(results) >= 8 else max(1, int(len(results) * 0.75))
    ok = passes >= need
    print(f"Suite pass count {passes}/{len(results)} (need >= {need} when running full fixture)")
    return 0 if ok else 1


if __name__ == "__main__":
    # ``os._exit`` avoids hung daemon threads / asyncio teardown sometimes raising odd shell exit codes (e.g. 138).
    code = int(main())
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
