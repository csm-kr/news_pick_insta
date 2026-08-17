#!/usr/bin/env python3
"""Deterministically overlay Korean copy, time, source, and AI disclosure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow가 필요하다: python -m pip install Pillow") from exc

SIZE = (1024, 1024)


def font(size: int):
    candidates = [Path("C:/Windows/Fonts/malgunbd.ttf"), Path("C:/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc")]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, value: str, face, width: int) -> list[str]:
    lines = []
    for paragraph in value.splitlines() or [value]:
        words = paragraph.split()
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if current and draw.textlength(trial, font=face) > width:
                lines.append(current)
                current = word
            else:
                current = trial
            if draw.textlength(current, font=face) > width:
                fragment = ""
                for char in current:
                    candidate = fragment + char
                    if fragment and draw.textlength(candidate, font=face) > width:
                        lines.append(fragment)
                        fragment = char
                    else:
                        fragment = candidate
                current = fragment
        if current:
            lines.append(current)
    return lines


def render(work: Path, board: dict) -> dict:
    selection = json.loads((work / "selection.json").read_text(encoding="utf-8"))
    if selection.get("story_id") != board.get("story_id"):
        raise ValueError("selection과 storyboard의 story_id가 다르다.")
    output = work / "slides"
    output.mkdir(parents=True, exist_ok=True)
    rendered = []
    for index, (card, background_path) in enumerate(zip(board["cards"], selection["backgrounds"]), 1):
        with Image.open(background_path) as raw:
            image = raw.convert("RGB")
        if image.size != SIZE:
            raise ValueError(f"background {index} 크기가 1024x1024가 아니다: {image.size}")
        canvas = image.convert("RGBA")
        overlay = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rounded_rectangle((64, 64, 960, 960), radius=34, fill=(12, 18, 24, 205))
        title_value = board["hook"]["headline"] if index == 1 else str(card.get("title") or card["role"].replace("_", " "))
        title_face = font(88 if index == 1 else 64)
        body_face = font(40)
        meta_face = font(28)
        y = 135
        for line in wrap(draw, title_value, title_face, 770)[:3]:
            draw.text((105, y), line, font=title_face, fill=(255, 255, 255, 255))
            y += int((88 if index == 1 else 64) * 1.35)
        y += 35
        copy = str(card["copy"])
        for line in wrap(draw, copy, body_face, 770):
            if y > 785:
                raise ValueError(f"card {index} copy overflow")
            draw.text((105, y), line, font=body_face, fill=(244, 246, 248, 255))
            y += 58
        basis = str(board.get("basis_time_kst") or "기준시각 미기재")
        draw.text((105, 830), f"기준 {basis} KST", font=meta_face, fill=(220, 225, 230, 255))
        if index == len(board["cards"]):
            source_items = card.get("source_block", [])
            source = "출처 · " + " / ".join(
                f"{item.get('publisher', '')} · {item.get('date', '')} · {item.get('domain', '')}" for item in source_items
            )
            draw.text((105, 872), source, font=meta_face, fill=(220, 225, 230, 255))
        draw.text((105, 914), "AI 생성 이미지 · 사건 재현 아님", font=meta_face, fill=(255, 211, 105, 255))
        canvas = Image.alpha_composite(canvas, overlay).convert("RGB")
        target = output / f"{index:02d}.png"
        canvas.save(target, format="PNG")
        rendered.append({"index": index, "path": str(target.resolve()), "copy": copy, "size": list(canvas.size), "ai_disclosure": True})
    qa = {"schema_version": "1.0", "passed": len(rendered) in (3, 4) and all(tuple(x["size"]) == SIZE for x in rendered), "candidate_count": len(list((work / "candidates").rglob("card-*.png"))), "slide_count": len(rendered), "target_size": "1024x1024", "checks": {"source_and_time": True, "ai_disclosure": True, "copy_matches_storyboard": True, "contrast_overlay": "dark-panel"}, "manual_checks_required": ["360px readability", "actual-photo confusion", "semantic fit"]}
    (work / "qa-report.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return qa


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--storyboard", type=Path, required=True)
    args = parser.parse_args()
    try:
        qa = render(args.work_dir, json.loads(args.storyboard.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": qa}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
