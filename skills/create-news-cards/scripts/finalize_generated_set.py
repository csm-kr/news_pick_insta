#!/usr/bin/env python3
"""Copy one generated direction to final slides without altering pixels."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

from PIL import Image


def load_duplicate_checker():
    path = Path(__file__).with_name("check_visual_duplicates.py")
    spec = importlib.util.spec_from_file_location("check_visual_duplicates", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("중복 이미지 QA 모듈을 불러올 수 없다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_scene_similarity():
    path = Path(__file__).with_name("scene_similarity.py")
    spec = importlib.util.spec_from_file_location("scene_similarity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("장면 중복 검사 모듈을 불러올 수 없다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def job_references(work: Path, direction: str, card_count: int) -> list[list[Path]]:
    """카드별 job.json의 reference 목록. 첫 항목이 그 카드의 대표(content) reference다."""
    references = []
    for index in range(1, card_count + 1):
        job_path = work / "jobs" / direction / f"card-{index:02d}" / "job.json"
        if not job_path.is_file():
            raise ValueError(f"card {index}의 생성 job 기록이 없다: {job_path}")
        job = json.loads(job_path.read_text(encoding="utf-8"))
        paths = [Path(value) for value in job.get("references") or []]
        if not paths or not paths[0].is_file():
            raise ValueError(f"card {index} job의 대표 reference를 찾을 수 없다.")
        references.append(paths)
    return references


def scene_qa(candidate_paths: list[Path], references: list[list[Path]]) -> dict:
    """사실 reference의 장면 반복을 검사하고 보조 스타일·레이아웃은 구분한다."""
    scene = load_scene_similarity()
    primaries = [paths[0] for paths in references]
    primary_keys = {str(path.resolve()).casefold() for path in primaries}
    same_scene_pairs = scene.find_same_scene_pairs(primaries)
    unique: list[Path] = []
    seen: set[str] = set()
    excluded_styles: list[str] = []
    for paths in references:
        for path in paths:
            key = str(path.resolve()).casefold()
            if not path.is_file() or key in seen:
                continue
            seen.add(key)
            parts = [part.casefold() for part in path.resolve().parts]
            is_style = any(left == "references" and right == "style" for left, right in zip(parts, parts[1:]))
            # Crop-safe regeneration can reuse a generated page as a layout
            # reference. Its repeated typography must not connect unrelated
            # factual scenes. A first/primary reference remains checked even
            # when it has been placed in the style folder.
            if is_style and key not in primary_keys:
                excluded_styles.append(str(path))
                continue
            unique.append(path)
    groups = scene.scene_groups(unique)
    card_matches = scene.match_cards_to_references(candidate_paths, unique)
    card_groups = [sorted({groups[index - 1] for index in matched}) for matched in card_matches]
    sharing = []
    for left in range(len(card_groups)):
        for right in range(left + 1, len(card_groups)):
            if set(card_groups[left]) & set(card_groups[right]):
                sharing.append([left + 1, right + 1])
    return {
        "schema_version": "1.0",
        "passed": not same_scene_pairs and not sharing,
        "thresholds": {
            "dhash_near_max": scene.DHASH_NEAR_THRESHOLD,
            "orb_inliers_min": scene.ORB_INLIER_THRESHOLD,
        },
        "primary_references": [str(path) for path in primaries],
        "same_scene_reference_pairs": same_scene_pairs,
        "reference_pool": [str(path) for path in unique],
        "excluded_style_references": excluded_styles,
        "card_reference_matches": card_matches,
        "cards_sharing_reference": sharing,
    }


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def finalize(work: Path, board: dict, direction: str, visual_qa_passed: bool) -> dict:
    if not visual_qa_passed:
        raise ValueError("확대 육안 QA가 끝난 경우에만 --visual-qa-passed를 사용한다.")
    card_count = int(board.get("card_count", 0))
    if card_count != 5:
        raise ValueError("현재 완성 세트는 정확히 5장이어야 한다.")
    plan = json.loads((work / "generation-plan.json").read_text(encoding="utf-8"))
    width, height = (int(value) for value in plan.get("target_size", "1080x1350").split("x"))
    expected_size = (width, height)
    candidate_paths = [work / "candidates" / direction / f"card-{index:02d}.png" for index in range(1, card_count + 1)]
    duplicate_qa = load_duplicate_checker().analyze_paths(candidate_paths)
    duplicate_qa["scene_qa"] = scene_qa(candidate_paths, job_references(work, direction, card_count))
    (work / "duplicate-qa.json").write_text(
        json.dumps(duplicate_qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not duplicate_qa["passed"]:
        failed_pairs = [f"{pair['left']}-{pair['right']}" for pair in duplicate_qa["failures"]]
        raise ValueError(f"중복·근접 중복 카드가 발견됐다: {', '.join(failed_pairs)}")
    scene = duplicate_qa["scene_qa"]
    if scene["same_scene_reference_pairs"]:
        pairs = [f"{pair['left']}-{pair['right']}" for pair in scene["same_scene_reference_pairs"]]
        raise ValueError(
            f"대표 reference가 같은 장면인 카드가 있다: {', '.join(pairs)}. "
            "겹친 카드만 다른 장면의 사진·공식 화면을 첫 reference로 바꿔 재생성한다."
        )
    if scene["cards_sharing_reference"]:
        pairs = [f"{left}-{right}" for left, right in scene["cards_sharing_reference"]]
        raise ValueError(
            f"여러 카드가 같은 reference 이미지를 재현했다: {', '.join(pairs)}. "
            "겹친 카드만 다른 대표 reference와 visual_role로 재생성한다."
        )

    slides = work / "slides"
    slides.mkdir(parents=True, exist_ok=True)
    records = []
    for index in range(1, card_count + 1):
        source = candidate_paths[index - 1]
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"생성 후보가 없다: {source}")
        with Image.open(source) as image:
            size = image.size
            mode = image.mode
        if size != expected_size:
            raise ValueError(f"card {index} 크기 오류: {size}")
        target = slides / f"{index:02d}.png"
        shutil.copy2(source, target)
        if digest(source) != digest(target):
            raise ValueError(f"card {index} 픽셀 원본 복사 검증 실패")
        records.append({"index": index, "source": str(source.resolve()),
            "path": str(target.resolve()), "size": list(size), "mode": mode,
            "sha256": digest(target), "pixel_modification": False})
    selection = {"schema_version": "2.0", "story_id": board.get("story_id"),
        "direction_id": direction, "card_count": card_count,
        "rendering_mode": "model_generated_final_image", "slides": records}
    qa = {"schema_version": "2.0", "passed": True,
        "visual_qa_passed": True, "pixel_modification": False,
        "duplicate_qa": duplicate_qa,
        "code_role": "dimension_hash_and_manifest_qa_only",
        "checks": {"card_count": True, "size_matches_target": True,
            "hash_matches_source": True, "no_exact_or_near_duplicate": True,
            "no_same_scene_reference_reuse": True,
            "semantic_duplicate_visually_verified": True,
            "korean_numbers_tables_visually_verified": True,
            "readability_at_360px_visually_verified": True},
        "cards": records}
    (work / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (work / "qa-report.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return qa


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--direction", required=True)
    parser.add_argument("--visual-qa-passed", action="store_true")
    args = parser.parse_args()
    try:
        board = json.loads(args.storyboard.read_text(encoding="utf-8"))
        result = finalize(args.work_dir, board, args.direction, args.visual_qa_passed)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
