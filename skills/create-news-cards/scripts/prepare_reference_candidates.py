#!/usr/bin/env python3
"""Prepare 12 reference-aware, fully generated infographic card jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


DIRECTIONS = [
    {
        "name": "human-impact-photo-news",
        "style": "high-impact Korean photo-news carousel, full-bleed factual editorial photography, strong bottom gradient, one concrete human consequence and comparison number in a bold two-to-three-line headline",
        "palette": "natural photo colors, charcoal gradient, crisp white, one restrained signal red",
    },
    {
        "name": "highlight-answer-explainer",
        "style": "popular Korean explanatory card-news, factual photo cover with high-contrast answer blocks, then warm clean pages using question, highlighted answer, and substantial but readable evidence text",
        "palette": "warm white, ink black, one vivid orange answer highlight, restrained navy",
    },
    {
        "name": "annotated-evidence-news",
        "style": "credible Korean evidence-led news carousel, one real article photo or official disclosure as the dominant proof, direct boxes, labels, arrows and comparison marks that show exactly what to inspect",
        "palette": "documentary photo colors, deep charcoal, clean white, one evidence yellow accent",
    },
]


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_content_reference(value: str, board_dir: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (board_dir / path).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"유효하지 않은 content reference 이미지: {path}")
    return path


def validate_set_diversity(cards: list[dict], board_dir: Path) -> list[str]:
    visual_roles = [str(card.get("visual_role") or "").strip() for card in cards]
    if any(not role for role in visual_roles):
        raise ValueError("모든 카드에는 서로 다른 visual_role이 필요하다.")
    if len({role.casefold() for role in visual_roles}) != len(cards):
        raise ValueError("한 세트 안에서 visual_role을 중복할 수 없다.")

    primary_hashes: dict[str, int] = {}
    for card in cards:
        references = card.get("reference_images") or []
        if not references:
            raise ValueError(f"card {card.get('index')}에 reference_images가 없다.")
        primary = resolve_content_reference(str(references[0]), board_dir)
        digest = file_digest(primary)
        if digest in primary_hashes:
            raise ValueError(
                f"card {card.get('index')}와 card {primary_hashes[digest]}가 같은 대표 reference를 사용한다. "
                "서로 다른 사건 사진·공식 화면을 첫 reference로 지정한다."
            )
        primary_hashes[digest] = int(card.get("index", 0))
    return visual_roles


def resolve_references(card: dict, board_dir: Path, direction_id: str) -> list[str]:
    content_references = card.get("reference_images") or []
    if not content_references:
        raise ValueError(f"card {card.get('index')}에 reference_images가 없다.")
    style_map = card.get("style_reference_images") or {}
    if not isinstance(style_map, dict):
        raise ValueError(f"card {card.get('index')}의 style_reference_images는 direction별 객체여야 한다.")
    style_references = style_map.get(direction_id) or []
    if not style_references:
        raise ValueError(f"card {card.get('index')}에 {direction_id} style reference가 없다.")
    references = [*content_references, *style_references]
    resolved = []
    for value in references:
        path = Path(value)
        if not path.is_absolute():
            path = (board_dir / path).resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"유효하지 않은 reference 이미지: {path}")
        resolved.append(str(path))
    return resolved


def card_prompt(direction: dict, card: dict, card_count: int, target: str, visual_roles: list[str]) -> str:
    required = card.get("required_text") or []
    if not required:
        raise ValueError(f"card {card.get('index')}에 required_text가 없다.")
    exact_copy = "\n".join(f'- "{text}"' for text in required)
    chart_spec = card.get("chart_spec") or "No chart; create a photo-led headline cover."
    width, height = (int(value) for value in target.split("x"))
    canvas = f"Square {width}x{height}" if width == height else f"Portrait {width}x{height}"
    photo_share = "25-40%" if width == height else "35-55%"
    return f"""
Create a FINISHED Instagram news infographic card, card {card['index']} of a coherent {card_count}-card carousel.

VISUAL DIRECTION
- {direction['style']}.
- Palette: {direction['palette']}.
- Use the supplied real Korean news article photograph and official disclosure screenshot as factual visual references.
- The first references are factual content references. The final reference is a successful card-news STYLE reference only: study its composition and reading order, but never copy its logo, wording, typeface, color identity, people, event, or publisher branding.
- Recompose them into an original editorial infographic; do not merely paste the source screenshot and do not reproduce an agency watermark.
- Preserve the recognizable factual context of the references. Do not invent people, buildings, organization signs, logos, documents, or events that are absent from the references.
- The carousel must feel like one professional Korean newsroom package, not an AI illustration and not a generic presentation template.

SET DIVERSITY — HARD REQUIREMENT
- This card's unique visual role is: {card.get('visual_role')}.
- The four visual roles in reading order are: {' | '.join(visual_roles)}.
- Do not reuse another card's dominant photo crop, camera angle, main person/object, background composition, chart form, or text-panel geometry.
- If a supporting reference also appears elsewhere in the set, use it only as factual context; it must not become this card's dominant visual.
- Visual consistency comes from palette, type hierarchy, spacing, and grid—not from repeating the same hero image or layout.

LAYOUT AND READABILITY
- {canvas}, mobile-first, generous safe margins, exact vertical alignment and strong negative space.
- One dominant message per card. The main statistic or headline must be readable at Instagram feed size.
- Card 1 must state a concrete human consequence plus the strongest comparison number; never stop at an indicator name and a percentage.
- Cards 2-4 must each add at least one new fact that did not appear on the previous card.
- Use real editorial photography as an integrated visual anchor occupying roughly {photo_share} of the composition, with chart or text panels layered in a controlled way.
- Korean typography must be crisp, correctly spaced, and not cropped. Keep each headline to at most two lines.
- Render all text, numbers, units, chart marks, labels, and source footer directly in the generated final image.

EXACT KOREAN COPY — reproduce every character and number exactly as written, without paraphrasing, translation, omission, duplication, or extra words:
{exact_copy}

DATA VISUALIZATION
- {chart_spec}
- Every number, unit, label/value pairing, comparison direction, and formula must be mathematically and semantically exact.
- Do not invent axes, dates, percentages, rankings, annotations, or financial claims.

CARD-SPECIFIC ART DIRECTION
- {card.get('visual_brief', '')}

FORBIDDEN
- No Korean spelling errors or malformed glyphs.
- No logo, wording, typeface, publisher mark, or color identity copied from the style reference.
- No English placeholder text, lorem ipsum, random microtext, fake news logo, fake bank logo, fake UI, extra watermark, chart distortion, decorative 3D icon set, abstract staircase, or unrelated house illustration.
- Do not include 한국경제, 한경, 한경BUSINESS, or their logos anywhere.
""".strip()


def prepare(board: dict, board_path: Path, work: Path, target: str) -> dict:
    if not re.fullmatch(r"\d{2,5}x\d{2,5}", target):
        raise ValueError("target_size는 WxH 형식이어야 한다.")
    count = board.get("card_count")
    if count != 4 or len(board.get("cards", [])) != 4:
        raise ValueError("reference-aware 뉴스 인포그래픽은 현재 정확히 4장이어야 한다.")
    cards = board["cards"]
    visual_roles = validate_set_diversity(cards, board_path.parent)
    jobs = []
    for d_index, direction in enumerate(DIRECTIONS, 1):
        direction_id = f"direction-{d_index:02d}"
        bible = {"schema_version": "2.0", "direction_id": direction_id, **direction,
            "target_size": target, "mode": "reference_aware_full_image_generation",
            "code_role": "qa_only"}
        bible_path = work / "directions" / f"{direction_id}.json"
        bible_path.parent.mkdir(parents=True, exist_ok=True)
        bible_path.write_text(json.dumps(bible, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for card in cards:
            card_index = int(card["index"])
            job_dir = work / "jobs" / direction_id / f"card-{card_index:02d}"
            job_dir.mkdir(parents=True, exist_ok=True)
            job = {
                "prompt": card_prompt(direction, card, count, target, visual_roles),
                "references": resolve_references(card, board_path.parent, direction_id),
                "detail_level": 3,
                "batch_size": 1,
                "workers": 1,
                "size_mode": "controllable",
                "target_size": target,
                "output_dir": "output",
            }
            job_path = job_dir / "job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            jobs.append({"direction_id": direction_id, "card_index": card_index,
                "job": str(job_path.resolve())})
    plan = {"schema_version": "2.0", "mode": "reference_aware_full_image_generation",
        "target_size": target, "card_count": 4, "direction_count": 3,
        "candidate_count": len(jobs), "concurrency": 12, "jobs": jobs}
    (work / "generation-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
            raise ValueError("사용자가 확인한 출력 크기에만 --confirm-size를 사용한다.")
        board_path = args.storyboard.resolve()
        board = json.loads(board_path.read_text(encoding="utf-8"))
        plan = prepare(board, board_path, args.work_dir.resolve(), args.target_size)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": plan}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
