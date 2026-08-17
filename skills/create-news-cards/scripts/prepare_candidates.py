#!/usr/bin/env python3
"""Prepare 12 isolated Tibo jobs grouped into coherent visual directions."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DIRECTIONS = [
    {"name": "editorial-paper", "palette": "warm ivory, charcoal, one vermilion accent", "style": "premium Korean editorial paper collage, restrained geometric cut-paper depth, soft studio light"},
    {"name": "clean-data", "palette": "off-white, deep navy, one cyan accent", "style": "clean dimensional information design, architectural shapes, precise negative space, calm daylight"},
    {"name": "symbolic-depth", "palette": "graphite, muted teal, one amber accent", "style": "cinematic symbolic still life, tactile materials, measured depth, soft directional light"},
    {"name": "public-service", "palette": "bright neutral, forest green, one orange accent", "style": "clear public-service editorial illustration, friendly physical forms, open space, natural soft shadows"},
]


def prepare(board: dict, work: Path, target: str) -> dict:
    if not re.fullmatch(r"\d{2,5}x\d{2,5}", target):
        raise ValueError("target_size는 WxH 형식이어야 한다.")
    count = board.get("card_count")
    if count not in (3, 4) or len(board.get("cards", [])) != count:
        raise ValueError("storyboard는 정확히 3장 또는 4장이어야 한다.")
    direction_count = 12 // count
    selected = DIRECTIONS[:direction_count]
    jobs = []
    for d_index, direction in enumerate(selected, 1):
        direction_id = f"direction-{d_index:02d}"
        bible = {
            "schema_version": "1.0",
            "direction_id": direction_id,
            **direction,
            "target_size": target,
            "rules": ["no text, letters, numbers, logos, documents or watermarks", "no real people or actual-event reconstruction", "clear text-safe negative space", "no gritty grain, speckle or glitter noise"],
        }
        bible_path = work / "directions" / f"{direction_id}.json"
        bible_path.parent.mkdir(parents=True, exist_ok=True)
        bible_path.write_text(json.dumps(bible, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for c_index, card in enumerate(board["cards"], 1):
            role = card["role"]
            visual = str(card.get("visual_brief") or card.get("copy") or "abstract verified news concept")
            prompt = (
                f"{direction['style']}. Palette: {direction['palette']}. Create card {c_index} of a coherent {count}-card news carousel. "
                f"Narrative role: {role}. Visual concept only: {visual}. Maintain the same material language and motif family across the set, "
                "but vary composition naturally for this card. Reserve a large quiet center-left text-safe area and keep key objects crop-safe. "
                "Editorial illustration, not documentary photography. No text, letters, numbers, charts, logos, documents, maps, watermarks, real persons, politicians, victims, or actual-event reconstruction. "
                "No gritty grain, random speckle, glitter-like noise, or excessive micro-contrast."
            )
            job_dir = work / "jobs" / direction_id / f"card-{c_index:02d}"
            job_dir.mkdir(parents=True, exist_ok=True)
            job = {"prompt": prompt, "detail_level": 2, "batch_size": 1, "workers": 1, "size_mode": "controllable", "target_size": target, "output_dir": "output"}
            job_path = job_dir / "job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            jobs.append({"direction_id": direction_id, "card_index": c_index, "job": str(job_path.resolve())})
    plan = {"schema_version": "1.0", "target_size": target, "card_count": count, "direction_count": direction_count, "candidate_count": len(jobs), "concurrency": 12, "jobs": jobs}
    (work / "generation-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--target-size", required=True)
    parser.add_argument("--confirm-size", action="store_true")
    args = parser.parse_args()
    try:
        if not args.confirm_size:
            raise ValueError("사용자의 출력 크기 확인 후 --confirm-size가 필요하다.")
        board = json.loads(args.storyboard.read_text(encoding="utf-8"))
        plan = prepare(board, args.work_dir, args.target_size)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": plan}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

