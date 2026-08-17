#!/usr/bin/env python3
"""Detect exact and near-duplicate news-card images before finalization."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash(image: Image.Image, crop: tuple[float, float, float, float] | None = None) -> int:
    if crop:
        width, height = image.size
        box = tuple(int(value * limit) for value, limit in zip(crop, (width, height, width, height)))
        image = image.crop(box)
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.get_flattened_data()) if hasattr(gray, "get_flattened_data") else list(gray.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return value


def normalized_mae(left: Image.Image, right: Image.Image, crop: tuple[float, float, float, float] | None = None) -> float:
    if crop:
        values = []
        for image in (left, right):
            width, height = image.size
            box = tuple(int(value * limit) for value, limit in zip(crop, (width, height, width, height)))
            values.append(image.crop(box))
        left, right = values
    left = left.convert("RGB").resize((32, 32), Image.Resampling.LANCZOS)
    right = right.convert("RGB").resize((32, 32), Image.Resampling.LANCZOS)
    return sum(ImageStat.Stat(ImageChops.difference(left, right)).mean) / 3.0


def analyze_paths(paths: list[Path], hamming_threshold: int = 7, mae_threshold: float = 18.0) -> dict:
    if len(paths) not in (3, 4):
        raise ValueError("중복 QA는 정확히 3~4장 세트가 필요하다.")
    images = []
    records = []
    for index, path in enumerate(paths, 1):
        if not path.is_file() or path.suffix.lower() != ".png":
            raise ValueError(f"유효한 PNG가 아니다: {path}")
        with Image.open(path) as raw:
            image = raw.convert("RGB")
        images.append(image)
        records.append({"index": index, "path": str(path.resolve()), "sha256": sha256(path), "size": list(image.size)})

    pairs = []
    failures = []
    top_crop = (0.0, 0.0, 1.0, 0.60)
    for (left_index, left), (right_index, right) in combinations(enumerate(images), 2):
        full_hamming = (dhash(left) ^ dhash(right)).bit_count()
        top_hamming = (dhash(left, top_crop) ^ dhash(right, top_crop)).bit_count()
        full_mae = normalized_mae(left, right)
        top_mae = normalized_mae(left, right, top_crop)
        exact = records[left_index]["sha256"] == records[right_index]["sha256"]
        near = (full_hamming <= hamming_threshold and full_mae <= mae_threshold) or (
            top_hamming <= hamming_threshold - 1 and top_mae <= mae_threshold - 2
        )
        pair = {
            "left": left_index + 1,
            "right": right_index + 1,
            "exact_duplicate": exact,
            "near_duplicate": near,
            "full_dhash_distance": full_hamming,
            "top_dhash_distance": top_hamming,
            "full_mae": round(full_mae, 3),
            "top_mae": round(top_mae, 3),
        }
        pairs.append(pair)
        if exact or near:
            failures.append(pair)
    return {
        "schema_version": "1.0",
        "passed": not failures,
        "thresholds": {"dhash_hamming_max": hamming_threshold, "rgb_mae_max": mae_threshold},
        "cards": records,
        "pairs": pairs,
        "failures": failures,
        "manual_checks_required": [
            "같은 인물·사진·공시 화면의 유사 crop 반복",
            "같은 카메라 각도·배경·주요 오브젝트 반복",
            "텍스트만 바뀌고 비주얼 서사가 같은 카드 반복",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--hamming-threshold", type=int, default=7)
    parser.add_argument("--mae-threshold", type=float, default=18.0)
    args = parser.parse_args()
    try:
        paths = sorted(args.slides.glob("*.png"))
        result = analyze_paths(paths, args.hamming_threshold, args.mae_threshold)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not result["passed"]:
            raise ValueError("exact 또는 near-duplicate 카드가 발견됐다.")
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
