#!/usr/bin/env python3
"""Score a completed improv scene (from improv_debug.json) with an LLM judge."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

# Allow running without installing package cwd
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from llm_from_here.llm_session import LlmSession  # noqa: E402


class ImprovSceneScores(BaseModel):
    """Structured scores for a full scene (eval artifact)."""

    scene_coherence: int = Field(..., ge=1, le=4)
    improv_principles: int = Field(..., ge=1, le=4)
    sfx_relevance: int = Field(..., ge=1, le=4)
    sfx_match: int = Field(
        ...,
        ge=1,
        le=4,
        description=(
            "How well the foley resolution matched intent: cued sounds actually "
            "fetched, reasonably on-topic, and did not pull focus. If no foley_audit "
            "is provided, score the match implied by the cues and ambience alone."
        ),
    )
    character_consistency: int = Field(..., ge=1, le=4)
    pass_scene: bool = Field(
        ...,
        description="Overall pass for the episode",
    )


class ImprovSceneEval(BaseModel):
    scores: ImprovSceneScores
    rationale: str = ""


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM-judge eval for ImprovAgent debug JSON.")
    ap.add_argument("debug_json", type=Path, help="Path to improv_debug.json")
    ap.add_argument(
        "--judge-model",
        default=os.getenv("IMPROV_EVAL_JUDGE_MODEL", "deepseek/deepseek-v4-flash"),
        help="OpenRouter model slug for the judge",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: evals/results/eval_improv_agent_<ts>.json)",
    )
    args = ap.parse_args()
    if not args.debug_json.is_file():
        print(f"Not found: {args.debug_json}", file=sys.stderr)
        return 1

    payload = json.loads(args.debug_json.read_text(encoding="utf-8"))
    transcript = payload.get("transcript") or ""
    segments = json.dumps(payload.get("segments") or [], indent=2, default=str)
    setup = json.dumps(payload.get("scene_setup") or {}, indent=2, default=str)

    foley_path = args.debug_json.parent / "foley_audit.json"
    foley_audit = []
    if foley_path.is_file():
        loaded = json.loads(foley_path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            foley_audit = loaded
    foley_audit_text = (
        json.dumps(foley_audit, indent=2, default=str) if foley_audit else "(none recorded)"
    )

    judge_slug = args.judge_model.strip()
    if judge_slug and not judge_slug.startswith("openrouter:"):
        judge_slug = f"openrouter:{judge_slug}"
    judge = LlmSession(
        "You score full improv scenes for audio variety shows. Be fair and concise.",
        model_slug=judge_slug,
    )
    prompt = (
        "Score this completed improv scene (1=weak, 4=strong).\n"
        "- scene_coherence: setting, scenario, and arc hang together\n"
        "- improv_principles: yes-and, listening, playable beats\n"
        "- sfx_relevance: bracket cues and ambient choice fit the fiction\n"
        "- sfx_match: whether the foley_audit shows cued sounds matched intent and "
        "were fetched (or, without an audit, whether the cues are fetchable and apt)\n"
        "- character_consistency: distinct voices and wants sustained\n"
        "pass_scene: true only if overall it would air on a quality improv podcast.\n\n"
        f"scene_setup:\n{setup}\n\n"
        f"transcript:\n{transcript}\n\n"
        f"segments:\n{segments}\n\n"
        f"foley_audit:\n{foley_audit_text}\n\n"
        "Return structured ImprovSceneEval with scores and a short rationale."
    )
    raw = judge.run_structured(prompt, ImprovSceneEval, log_prompt=True)
    ev = ImprovSceneEval.model_validate(raw)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = args.out
    if out_path is None:
        out_dir = _REPO_ROOT / "evals" / "results"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"eval_improv_agent_{ts}.json"

    blob = {
        "generated_at": ts,
        "judge_model": f"openrouter:{args.judge_model}",
        "source_debug_json": str(args.debug_json.resolve()),
        "foley_audit_entries": len(foley_audit),
        "scores": ev.scores.model_dump(),
        "pass": ev.scores.pass_scene,
        "rationale": ev.rationale,
    }
    out_path.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
