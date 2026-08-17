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
    if card_count != 4:
        raise ValueError("현재 완성 세트는 정확히 4장이어야 한다.")
    plan = json.loads((work / "generation-plan.json").read_text(encoding="utf-8"))
    width, height = (int(value) for value in plan.get("target_size", "1024x1024").split("x"))
    expected_size = (width, height)
    candidate_paths = [work / "candidates" / direction / f"card-{index:02d}.png" for index in range(1, card_count + 1)]
    duplicate_qa = load_duplicate_checker().analyze_paths(candidate_paths)
    (work / "duplicate-qa.json").write_text(
        json.dumps(duplicate_qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not duplicate_qa["passed"]:
        failed_pairs = [f"{pair['left']}-{pair['right']}" for pair in duplicate_qa["failures"]]
        raise ValueError(f"중복·근접 중복 카드가 발견됐다: {', '.join(failed_pairs)}")

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
            "semantic_duplicate_visually_verified": True,
            "korean_numbers_charts_visually_verified": True},
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
