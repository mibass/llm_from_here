#!/usr/bin/env python3
"""Pretty-print improv_debug.json from an ImprovAgent run (scene audit)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Inspect improv_debug.json from ImprovAgent.")
    p.add_argument(
        "path",
        nargs="?",
        default="improv_debug.json",
        help="Path to improv_debug.json (default: ./improv_debug.json)",
    )
    args = p.parse_args()
    path = Path(args.path)
    if not path.is_file():
        print(f"Not found: {path}", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    setup = data.get("scene_setup") or {}
    print("=== SCENE SETUP ===")
    print(f"Setting:   {setup.get('setting', '')}")
    print(f"Scenario:  {setup.get('scenario', '')}")
    print(f"Ambient:   {setup.get('background_sound', '')}")
    pal = setup.get("sfx_palette") or []
    print(f"SFX palette ({len(pal)}): {', '.join(str(x) for x in pal)}")
    print("\nCharacters:")
    for ch in setup.get("characters") or []:
        slot = ch.get("slot", "?")
        name = ch.get("name", "?")
        desc = ch.get("description", "")
        print(f"  slot {slot}: {name} — {desc}")

    print("\n=== TRANSCRIPT ===")
    print(data.get("transcript") or "")

    print("\n=== SEGMENTS (timeline rows) ===")
    for i, seg in enumerate(data.get("segments") or []):
        sp = seg.get("speaker", "")
        dlg = seg.get("dialog", "")
        extra = ""
        if seg.get("sfx_freesound_id") is not None:
            extra = f"  [freesound id={seg.get('sfx_freesound_id')}]"
        print(f"  {i:02d} [{sp}] {dlg}{extra}")

    print("\n=== AUDIT (turn / sfx) ===")
    for row in data.get("audit_log") or []:
        phase = row.get("phase", "?")
        if phase == "turn":
            print(
                f"  turn {row.get('turn_index')} slot {row.get('slot')} "
                f"{row.get('character')!r} attempt {row.get('attempt')}: "
                f"{(row.get('judgement') or {}).get('pass_turn')}"
            )
        elif phase == "sfx":
            print(
                f"  sfx cue={row.get('cue')!r} idx={row.get('chosen_index')} "
                f"id={row.get('freesound_id')}"
            )
        else:
            print(f"  {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
