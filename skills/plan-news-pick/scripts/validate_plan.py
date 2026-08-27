#!/usr/bin/env python3
"""Validate a news-card storyboard against a verified story."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROLES_4 = ["hook", "verified_facts", "context_and_positions", "impact_unknowns_sources"]
ROLES_3 = ["hook", "facts_and_context", "impact_unknowns_sources"]
FORBIDDEN = (
    "전 국민 충격",
    "발칵",
    "난리",
    "역대급",
    "초비상",
    "끝났다",
    "대체 무슨 일이",
    "결국 터졌다",
    "알고 보니",
    "숨긴 진실",
    "국민만 바보",
    "세금 퍼준다",
    "외국인 특혜",
)
CARD_INDEX_CAPTION = re.compile(r"(?m)^\s*[1-4]\s*장\s*[|:]", re.UNICODE)
HOOK_TYPES = {
    "immediate_consequence",
    "reversal_contrast",
    "loss_gap",
    "decision_deadline",
    "answerable_question",
}
SCORE_RANGES = {
    "specificity": (0, 2),
    "life_impact": (0, 2),
    "immediacy": (0, 2),
    "tension": (0, 2),
    "curiosity_gap": (0, 2),
    "visual_grip": (0, 2),
    "continuation_value": (0, 2),
    "exaggeration_risk": (-2, 0),
}


def validate(story: dict[str, Any], board: dict[str, Any]) -> None:
    if story.get("verification_status") != "verified":
        raise ValueError("입력 story가 verified가 아니다.")
    if board.get("story_id") != story.get("story_id"):
        raise ValueError("story_id가 입력과 다르다.")
    count = board.get("card_count")
    if count not in (3, 4):
        raise ValueError("card_count는 3 또는 4다.")
    cards = board.get("cards", [])
    if len(cards) != count:
        raise ValueError("cards 장수가 card_count와 다르다.")
    roles = [c.get("role") for c in cards]
    expected = ROLES_3 if count == 3 else ROLES_4
    if roles != expected:
        raise ValueError(f"card role 순서는 {expected}여야 한다.")
    visual_roles = [str(card.get("visual_role") or "").strip() for card in cards]
    if any(not role for role in visual_roles):
        raise ValueError("모든 카드에는 visual_role이 필요하다.")
    if len({role.casefold() for role in visual_roles}) != count:
        raise ValueError("한 세트 안에서 visual_role을 중복할 수 없다.")
    sources = board.get("sources", [])
    if len(sources) < 2 or any(not str(source.get("publisher") or "").strip() or not str(source.get("url") or "").strip() for source in sources):
        raise ValueError("storyboard sources에는 publisher와 URL이 있는 근거가 2개 이상 필요하다.")
    source_claims = {c.get("id") for c in story.get("claims", [])}
    if not source_claims:
        raise ValueError("입력 claim이 없다.")
    for index, card in enumerate(cards, 1):
        if card.get("index") != index:
            raise ValueError("card index가 연속적이지 않다.")
        copy = str(card.get("copy") or "").strip()
        if not copy:
            raise ValueError(f"card {index} copy가 비었다.")
        if len(copy) > 220:
            raise ValueError(f"card {index} copy가 과도하게 길다.")
        if any(word in copy for word in FORBIDDEN):
            raise ValueError(f"card {index}에 금지 후킹 표현이 있다.")
        evidence = set(card.get("evidence_ids", []))
        if not evidence or not evidence <= source_claims:
            raise ValueError(f"card {index} evidence_ids가 story claim과 맞지 않는다.")
    source_block = cards[-1].get("source_block", [])
    if len(source_block) != len(sources):
        raise ValueError("마지막 카드 source_block은 storyboard의 모든 출처를 포함해야 한다.")
    block_publishers = {str(item.get("publisher") or "").strip() for item in source_block}
    source_publishers = {str(item.get("publisher") or "").strip() for item in sources}
    if block_publishers != source_publishers:
        raise ValueError("마지막 카드 source_block의 출처명이 storyboard sources와 다르다.")
    if any(not str(item.get("date") or "").strip() or not str(item.get("domain") or "").strip() for item in source_block):
        raise ValueError("마지막 카드 source_block에는 각 출처의 date와 domain이 필요하다.")
    required_text = [str(value).strip() for value in cards[-1].get("required_text", [])]
    if not any(value == "출처" or value.startswith("출처:") for value in required_text):
        raise ValueError("마지막 카드 required_text에 출처 제목이 필요하다.")
    for card in cards[:-1]:
        visible_text = [str(value).strip() for value in card.get("required_text", [])]
        if any(value == "출처" or value.startswith("출처:") for value in visible_text):
            raise ValueError("1~3장에는 보이는 출처 행을 넣지 않고 마지막 카드에만 모아야 한다.")
    hook = board.get("hook", {})
    headline = str(hook.get("headline") or "")
    deck = str(hook.get("deck") or "")
    if not 12 <= len(headline.replace(" ", "")) <= 26:
        raise ValueError("hook headline은 공백 제외 12~26자다.")
    if not 20 <= len(deck.replace(" ", "")) <= 45:
        raise ValueError("hook deck은 공백 제외 20~45자다.")
    candidates = board.get("hook_candidates", [])
    if len(candidates) != 5:
        raise ValueError("hook 후보는 정확히 5개여야 한다.")
    candidate_types = [str(candidate.get("hook_type") or "") for candidate in candidates]
    if set(candidate_types) != HOOK_TYPES or len(set(candidate_types)) != 5:
        raise ValueError("hook 후보는 다섯 가지 hook_type을 하나씩 사용해야 한다.")
    for candidate in candidates:
        score = candidate.get("score", {})
        if set(score) != set(SCORE_RANGES):
            raise ValueError("hook candidate score 항목이 고강도 사실형 기준과 맞지 않는다.")
        values = {}
        for key, (minimum, maximum) in SCORE_RANGES.items():
            value = int(score[key])
            if not minimum <= value <= maximum:
                raise ValueError(f"hook candidate {key} 점수 범위가 맞지 않는다.")
            values[key] = value
        total = sum(values.values())
        if candidate.get("total") != total:
            raise ValueError("hook candidate total 계산이 맞지 않는다.")
    selected = [candidate for candidate in candidates if candidate.get("headline") == headline]
    if len(selected) != 1:
        raise ValueError("선택한 hook headline은 후보 5개 중 하나와 정확히 같아야 한다.")
    best_total = max(int(candidate["total"]) for candidate in candidates)
    if int(selected[0]["total"]) != best_total:
        raise ValueError("선택한 hook은 최고점 후보가 아니다.")
    tied = [candidate for candidate in candidates if int(candidate["total"]) == best_total]
    shortest = min(len(str(candidate.get("headline") or "").replace(" ", "")) for candidate in tied)
    if len(headline.replace(" ", "")) != shortest:
        raise ValueError("최고점 동점에서는 가장 짧은 hook을 선택해야 한다.")
    if best_total < 11:
        raise ValueError("선택 hook은 고강도 사실형 기준 11/14 이상이어야 한다.")
    caption = str(board.get("caption") or "").strip()
    if not caption:
        raise ValueError("caption이 비었다.")
    if CARD_INDEX_CAPTION.search(caption):
        raise ValueError("caption 본문은 장별 목차가 아니라 하나의 뉴스 문단이어야 한다.")
    marker = "기준시각:"
    if marker not in caption:
        raise ValueError("caption에 기준시각이 필요하다.")
    narrative = caption.split(marker, 1)[0].strip()
    if not narrative or "\n\n" in narrative:
        raise ValueError("caption의 뉴스 본문은 기준시각 앞에서 하나의 문단이어야 한다.")
    qa = board.get("qa", {})
    if qa.get("hard_fail_passed") is not True or int(qa.get("editorial_score", 0)) < 16:
        raise ValueError("기획 QA가 통과되지 않았다.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story", type=Path, required=True)
    parser.add_argument("--storyboard", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate(json.loads(args.story.read_text(encoding="utf-8")), json.loads(args.storyboard.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": {"valid": True}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
