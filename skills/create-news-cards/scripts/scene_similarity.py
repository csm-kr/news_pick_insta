#!/usr/bin/env python3
"""같은 사진의 전재본·축소본·다른 crop, 같은 장면의 다른 프레임을 판별한다.

- dHash(64bit): 같은 파일의 축소본·재인코딩본처럼 거의 동일한 이미지를 잡는다.
- ORB 특징점 + RANSAC homography inlier: 다른 crop·해상도·영상 캡처로 전재된 같은 장면을 잡는다.

실측(2026-09-07): 같은 장면은 inlier 70~589, 무관한 사진·화면은 11 이하였다.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

from PIL import Image, ImageOps

DHASH_NEAR_THRESHOLD = 6
ORB_INLIER_THRESHOLD = 40
ORB_FEATURES = 2000
MAX_DIMENSION = 900
RATIO_TEST = 0.75
MIN_GOOD_MATCHES = 8


def _require_cv2():
    try:
        import cv2  # type: ignore
        import numpy  # type: ignore
    except ImportError as error:  # pragma: no cover - 환경 의존
        raise RuntimeError(
            "장면 중복 검사에는 OpenCV와 numpy가 필요하다: pip install opencv-python numpy"
        ) from error
    return cv2, numpy


def load_gray(path: Path, max_dimension: int = MAX_DIMENSION) -> Image.Image:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("L")
    width, height = image.size
    scale = max_dimension / max(width, height)
    if scale < 1:
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    return image


def dhash64(image: Image.Image) -> int:
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.get_flattened_data()) if hasattr(gray, "get_flattened_data") else list(gray.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return value


def dhash_distance(left: Image.Image, right: Image.Image) -> int:
    return (dhash64(left) ^ dhash64(right)).bit_count()


def features(image: Image.Image):
    cv2, numpy = _require_cv2()
    array = numpy.asarray(image, dtype=numpy.uint8)
    orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
    keypoints, descriptors = orb.detectAndCompute(array, None)
    return keypoints, descriptors


def orb_inliers(left_features, right_features) -> int:
    cv2, numpy = _require_cv2()
    left_keypoints, left_descriptors = left_features
    right_keypoints, right_descriptors = right_features
    if left_descriptors is None or right_descriptors is None:
        return 0
    if len(left_keypoints) < MIN_GOOD_MATCHES or len(right_keypoints) < MIN_GOOD_MATCHES:
        return 0
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    good = []
    for pair in matcher.knnMatch(left_descriptors, right_descriptors, k=2):
        if len(pair) == 2 and pair[0].distance < RATIO_TEST * pair[1].distance:
            good.append(pair[0])
    if len(good) < MIN_GOOD_MATCHES:
        return 0
    source = numpy.float32([left_keypoints[match.queryIdx].pt for match in good])
    target = numpy.float32([right_keypoints[match.trainIdx].pt for match in good])
    _, mask = cv2.findHomography(source, target, cv2.RANSAC, 5.0)
    return int(mask.sum()) if mask is not None else 0


class _Analyzed:
    __slots__ = ("path", "image", "hash", "features")

    def __init__(self, path: Path):
        self.path = Path(path)
        self.image = load_gray(self.path)
        self.hash = dhash64(self.image)
        self.features = features(self.image)


def _compare(left: _Analyzed, right: _Analyzed) -> dict:
    distance = (left.hash ^ right.hash).bit_count()
    inliers = orb_inliers(left.features, right.features)
    return {
        "dhash_distance": distance,
        "orb_inliers": inliers,
        "same_scene": distance <= DHASH_NEAR_THRESHOLD or inliers >= ORB_INLIER_THRESHOLD,
    }


def compare(left_path: Path, right_path: Path) -> dict:
    return _compare(_Analyzed(left_path), _Analyzed(right_path))


def same_scene(left_path: Path, right_path: Path) -> bool:
    return compare(left_path, right_path)["same_scene"]


def find_same_scene_pairs(paths: list[Path]) -> list[dict]:
    analyzed = [_Analyzed(path) for path in paths]
    pairs = []
    for (left_index, left), (right_index, right) in combinations(enumerate(analyzed, 1), 2):
        result = _compare(left, right)
        if result["same_scene"]:
            pairs.append({"left": left_index, "right": right_index, **result})
    return pairs


def match_cards_to_references(card_paths: list[Path], reference_paths: list[Path]) -> list[list[int]]:
    """카드별로 ORB inlier가 임계값 이상인 reference의 1-based index 목록을 돌려준다."""
    references = [_Analyzed(path) for path in reference_paths]
    matches = []
    for card_path in card_paths:
        card = _Analyzed(card_path)
        matched = []
        for index, reference in enumerate(references, 1):
            if orb_inliers(card.features, reference.features) >= ORB_INLIER_THRESHOLD:
                matched.append(index)
        matches.append(matched)
    return matches


def scene_groups(paths: list[Path]) -> list[int]:
    """같은 장면끼리 같은 그룹 번호를 준다(union-find). 반환값은 path 순서대로의 그룹 id."""
    parent = list(range(len(paths)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for pair in find_same_scene_pairs(paths):
        left, right = find(pair["left"] - 1), find(pair["right"] - 1)
        if left != right:
            parent[right] = left
    return [find(index) for index in range(len(paths))]
