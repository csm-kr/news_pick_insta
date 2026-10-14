#!/usr/bin/env python3
"""Prepare 15 reference-aware portrait news-card jobs from three random directors."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import re
import secrets
import sys
from pathlib import Path


DIRECTION_POOL = [
    {
        "direction_id": "direction-01",
        "name": "human-impact-photo-news",
        "style": "human-impact Korean photo-news body pages with documentary imagery, direct factual prose and compact comparison tables",
        "palette": "natural photo colors, charcoal gradient, crisp white, one restrained signal red",
        "style_reference_key": "direction-01",
    },
    {
        "direction_id": "direction-02",
        "name": "highlight-answer-explainer",
        "style": "popular Korean explanatory body pages using question, highlighted answer, factual prose, editorial image and a compact table",
        "palette": "warm white, ink black, one vivid orange answer highlight, restrained navy",
        "style_reference_key": "direction-02",
    },
    {
        "direction_id": "direction-03",
        "name": "annotated-evidence-news",
        "style": "credible Korean evidence-led body pages with one factual image, short annotations, clear prose and a proof table",
        "palette": "documentary photo colors, deep charcoal, clean white, one evidence yellow accent",
        "style_reference_key": "direction-03",
    },
    {
        "direction_id": "direction-04",
        "name": "stat-first-visual-brief",
        "style": "ultra-readable Korean mobile brief with a clear factual image, one emphasized result, concise prose and an airy numeric table",
        "palette": "high-contrast cream, near-black, one electric blue accent",
        "style_reference_key": "direction-02",
    },
    {
        "direction_id": "direction-05",
        "name": "timeline-process-map",
        "style": "clear Korean process-news pages built around ordered steps, current-status labels, factual images, short prose and a chronological table",
        "palette": "clean white, deep forest green, one coral status accent",
        "style_reference_key": "direction-03",
    },
    {
        "direction_id": "direction-06",
        "name": "split-screen-editorial",
        "style": "bold Korean split editorial body pages with clearly attributed sides, documentary image fragments, short prose and a two-sided comparison table",
        "palette": "warm gray, ink black, crisp white, one cobalt accent",
        "style_reference_key": "direction-01",
    },
    {
        "direction_id": "direction-07",
        "name": "typography-led-news-poster",
        "style": "type-led Korean editorial body pages with strong hierarchy, a factual photo block, readable prose and one restrained table",
        "palette": "paper white, ink black, one vivid vermilion accent",
        "style_reference_key": "direction-02",
    },
    {
        "direction_id": "direction-08",
        "name": "one-question-one-answer",
        "style": "minimal Korean question-and-answer body pages with one factual answer, editorial image, short explanatory prose and a compact fact table",
        "palette": "soft ivory, midnight navy, one clear cyan accent",
        "style_reference_key": "direction-02",
    },
    {
        "direction_id": "direction-09",
        "name": "modular-checklist-brief",
        "style": "mobile-first Korean checklist body pages with strict reading order, one factual image, short prose and a clear status table",
        "palette": "bright neutral, deep teal, one amber status accent",
        "style_reference_key": "direction-03",
    },
    {
        "direction_id": "direction-10",
        "name": "asymmetric-magazine-cutout",
        "style": "premium asymmetric Korean magazine-news body pages with one factual editorial image, generous whitespace, readable prose and an aligned table",
        "palette": "warm off-white, graphite, muted cobalt, one coral accent",
        "style_reference_key": "direction-01",
    },
]

SELECTED_DIRECTION_COUNT = 3


def load_scene_similarity():
    path = Path(__file__).with_name("scene_similarity.py")
    spec = importlib.util.spec_from_file_location("scene_similarity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("장면 중복 검사 모듈을 불러올 수 없다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    primaries: list[Path] = []
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
        primaries.append(primary)
    same_scene = load_scene_similarity().find_same_scene_pairs(primaries)
    if same_scene:
        pair = same_scene[0]
        left = cards[pair["left"] - 1].get("index")
        right = cards[pair["right"] - 1].get("index")
        raise ValueError(
            f"card {left}와 card {right}의 대표 reference가 같은 장면이다"
            f"(ORB inlier {pair['orb_inliers']}, dHash 거리 {pair['dhash_distance']}). "
            "다른 매체의 전재본·축소본·영상 캡처는 다른 장면이 아니다. "
            "다른 장면의 사진이나 공식 화면·문서를 첫 reference로 지정한다."
        )
    return visual_roles


def resolve_references(card: dict, board_dir: Path, direction: dict) -> list[str]:
    content_references = card.get("reference_images") or []
    if not content_references:
        raise ValueError(f"card {card.get('index')}에 reference_images가 없다.")
    style_map = card.get("style_reference_images") or {}
    if not isinstance(style_map, dict):
        raise ValueError(f"card {card.get('index')}의 style_reference_images는 direction별 객체여야 한다.")
    direction_id = direction["direction_id"]
    style_key = direction.get("style_reference_key") or direction_id
    style_references = style_map.get(direction_id) or style_map.get(style_key) or []
    if not style_references:
        raise ValueError(
            f"card {card.get('index')}에 {direction_id} 또는 fallback {style_key} style reference가 없다."
        )
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
    chart_value = card.get("chart_spec") or "No chart."
    chart_spec = json.dumps(chart_value, ensure_ascii=False) if isinstance(chart_value, dict) else str(chart_value)
    width, height = (int(value) for value in target.split("x"))
    if (width, height) != (1080, 1350):
        raise ValueError("뉴스픽 기본 캔버스는 정확히 1080x1350이어야 한다.")
    index = int(card["index"])
    if index == 1:
        page_contract = """
COVER INVARIANT — overrides director variation
- Use the factual editorial photograph full-bleed across the entire 4:5 canvas.
- Keep the upper 58-65% visually open so the subject is recognized before the headline.
- Add a smooth transparent-to-near-black navy gradient only across the lower 35-42%.
- Put a small restrained NEWS PICK label at the upper-left.
- Put the exact Korean headline in the lower gradient, left aligned, bold, at most two lines.
- Put the deck and status/date below the headline. Do not use a top headline panel, centered poster title, mosaic, or many small widgets.
- The photograph, headline, deck and status must all be readable in one sightline without covering the key face, object, building sign or evidence.
""".strip()
    elif index in (2, 3, 4):
        page_contract = """
ARTICLE PAGE INVARIANT — prose + factual image + table
- Build exactly three clear zones: (1) short title and one 2-3 sentence Korean paragraph, (2) one relevant factual editorial image occupying 35-50% of the card, (3) one compact table with 2-4 data rows and no more than 3 columns.
- The paragraph must read as continuous article prose, not chips, slogans, or fragmented bullet spam.
- The table must be a real aligned table with a clear header, not a cluster of floating cards. Do not place both a table and a second chart on the same card.
- Use a different image crop, zone order and table treatment from cards 2-4 while preserving the shared type scale and grid.
""".strip()
    else:
        page_contract = """
SOURCE PAGE INVARIANT
- Make this a calm source-only closing card headed 출처.
- List every source name, date and domain exactly, plus basis time and correction route when supplied.
- Use a highly legible single-column or two-column list with generous row spacing. Do not add a new claim, CTA, quote, chart or decorative microtext.
- Any factual reference image may appear only as a faint restrained background texture; source text is the priority.
""".strip()
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

FIXED PAGE CONTRACT
{page_contract}

SET DIVERSITY — HARD REQUIREMENT
- This card's unique visual role is: {card.get('visual_role')}.
- The five visual roles in reading order are: {' | '.join(visual_roles)}.
- Do not reuse another card's dominant photo crop, camera angle, main person/object, background composition, chart form, or text-panel geometry.
- If a supporting reference also appears elsewhere in the set, use it only as factual context; it must not become this card's dominant visual.
- Visual consistency comes from palette, type hierarchy, spacing, and grid—not from repeating the same hero image or layout.

LAYOUT AND READABILITY — HARD REQUIREMENT
- Portrait 1080x1350, mobile-first. Tibo is explicitly requested at 1024x1536 and the final output uses a centered 4:5 cover crop. Compose the finished card for the central 4:5 region, keep every text glyph, number, table border, page marker, logo and other essential element inside the final x=72..1008 and y=72..1278 production-safe rectangle, and leave crop-risk outer bands as background or non-essential photo only.
- For a 4:5 target with 1024x1536 raw, the surviving crop is x=0..1024, y=128..1408, NOT the full raw canvas. Every glyph, logo and table border must be inside raw x=69..955, y=197..1339; use extra breathing room x=95..929, y=230..1290 when possible. Do not treat a 72px raw margin as sufficient.
- For a 4:5 target, do not compose body cards as tall 2:3 posters. Fit the complete title, readable prose, factual image, ALL table rows and basis date into the central 4:5 design. Reduce oversized headings and photo-panel height before losing text, the last table row, or the date. Do not solve overflow by making prose or table cells tiny.
- One dominant message per card. The main statistic or headline must be readable at Instagram feed size.
- Card 1 must lead with a verified consequence, loss, gap, reversal, or deadline plus the strongest comparison number. Put this tension in the first visual reading beat; never stop at an institution name, policy name, indicator name, or percentage.
- On card 1, make the headline forceful while the deck immediately states the affected group, eligibility condition, procedure, or basis time that keeps it accurate. Never postpone a crucial limitation to a later card.
- Cards 2-4 must each add at least one new fact that did not appear on the previous card.
- On card 1, build one dominant sightline linking the headline, one key number, and the factual hero image. Do not dilute the cover with many small panels or decorative widgets.
- Korean typography must be crisp, correctly spaced, and not cropped. Keep the cover headline to at most two lines.
- At a 360px-wide preview, the cover headline, article paragraph, every table cell and every source row must remain readable without zoom. Never shrink text to fit. Shorten nothing and omit nothing; use the specified hierarchy and whitespace.
- Target type scale: cover headline 86-108px; article title 58-72px; article paragraph 34-40px with 1.4-1.55 line height; table/source text 30-36px. Maintain at least 4.5:1 contrast for ordinary text.
- Render all text, numbers, units, table rules and labels specified for this card directly in the generated final image.

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
- No siren, flame, breaking-glass effect, warning triangle, panic-red wash, or outrage cue unless the verified event itself is a documented emergency or hazard.
- Do not include 한국경제, 한경, 한경BUSINESS, or their logos anywhere.
""".strip()


def prepare(
    board: dict,
    board_path: Path,
    work: Path,
    target: str,
    seed: int | None = None,
    selected_direction_ids: list[str] | None = None,
) -> dict:
    work = work.resolve()
    try:
        work.relative_to(Path(__file__).resolve().parent.parent)
    except ValueError:
        pass
    else:
        raise ValueError("work-dir은 create-news-cards skill 폴더 밖에 있어야 한다.")
    if not re.fullmatch(r"\d{2,5}x\d{2,5}", target):
        raise ValueError("target_size는 WxH 형식이어야 한다.")
    if target != "1080x1350":
        raise ValueError("뉴스픽 기본 크기는 1080x1350이다.")
    count = board.get("card_count")
    if count != 5 or len(board.get("cards", [])) != 5:
        raise ValueError("reference-aware 뉴스 인포그래픽은 정확히 5장이어야 한다.")
    cards = board["cards"]
    visual_roles = validate_set_diversity(cards, board_path.parent)
    if seed is None:
        seed = secrets.randbits(64)
    if selected_direction_ids is None:
        selected = random.Random(seed).sample(DIRECTION_POOL, SELECTED_DIRECTION_COUNT)
        selection_strategy = "seeded_random_without_replacement"
    else:
        if len(selected_direction_ids) != SELECTED_DIRECTION_COUNT or len(set(selected_direction_ids)) != SELECTED_DIRECTION_COUNT:
            raise ValueError("저장된 director 선택은 중복 없는 3개여야 한다.")
        by_id = {item["direction_id"]: item for item in DIRECTION_POOL}
        missing = [direction_id for direction_id in selected_direction_ids if direction_id not in by_id]
        if missing:
            raise ValueError("현재 director 풀에 없는 저장 ID: " + ", ".join(missing))
        selected = [by_id[direction_id] for direction_id in selected_direction_ids]
        selection_strategy = "persisted_selected_directions"
    jobs = []
    for direction in selected:
        direction_id = direction["direction_id"]
        bible = {"schema_version": "3.0", **direction,
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
                "references": resolve_references(card, board_path.parent, direction),
                "detail_level": 3,
                "batch_size": 1,
                "workers": 1,
                "size_mode": "controllable",
                "target_size": target,
                # Tibo exposes only square, landscape, and 2:3 portrait backend
                # choices. Request portrait explicitly, retain the raw result,
                # and reject any candidate whose centered 4:5 crop loses content.
                "backend_size": "1024x1536",
                "resize_fit": "cover",
                "preserve_backend_raw": True,
                "output_dir": "output",
            }
            job_path = job_dir / "job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            jobs.append({"direction_id": direction_id, "card_index": card_index,
                "job": str(job_path.resolve())})
    plan = {"schema_version": "3.0", "mode": "reference_aware_full_image_generation",
        "target_size": target, "card_count": 5, "direction_pool_count": len(DIRECTION_POOL),
        "direction_count": len(selected),
        "selected_direction_ids": [item["direction_id"] for item in selected],
        "selected_direction_names": [item["name"] for item in selected],
        "selected_director_ids": [item["direction_id"] for item in selected],
        "selected_director_names": [item["name"] for item in selected],
        "selection_strategy": selection_strategy, "random_seed": seed,
        "candidate_count": len(jobs), "concurrency": 15, "jobs": jobs}
    (work / "generation-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--target-size", required=True)
    parser.add_argument("--confirm-size", action="store_true")
    parser.add_argument("--seed", type=int, help="Reproduce an exact director selection.")
    parser.add_argument("--reroll-directions", action="store_true", help="Draw a new director set before candidates exist.")
    args = parser.parse_args()
    try:
        if not args.confirm_size:
            raise ValueError("사용자가 확인한 출력 크기에만 --confirm-size를 사용한다.")
        board_path = args.storyboard.resolve()
        board = json.loads(board_path.read_text(encoding="utf-8"))
        work_dir = args.work_dir.resolve()
        seed = args.seed
        existing_plan = work_dir / "generation-plan.json"
        previous = json.loads(existing_plan.read_text(encoding="utf-8")) if existing_plan.is_file() else None
        has_candidates = any((work_dir / "candidates").rglob("card-*.png"))
        if has_candidates and (
            args.reroll_directions
            or (seed is not None and previous and seed != previous.get("random_seed"))
        ):
            raise ValueError("생성 후보가 있는 work-dir은 director를 재추첨할 수 없다. 새 work-dir을 사용한다.")
        stored_direction_ids = None
        if previous and not args.reroll_directions:
            if seed is None:
                seed = previous.get("random_seed")
            if seed == previous.get("random_seed"):
                stored_direction_ids = previous.get("selected_direction_ids")
        plan = prepare(
            board,
            board_path,
            work_dir,
            args.target_size,
            seed=seed,
            selected_direction_ids=stored_direction_ids,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": plan}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
