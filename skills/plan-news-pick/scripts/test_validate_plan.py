from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).with_name("validate_plan.py")
SPEC = importlib.util.spec_from_file_location("validate_plan", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class PlanTests(unittest.TestCase):
    def fixture(self):
        story = {"story_id": "s", "verification_status": "verified", "claims": [{"id": "c1"}, {"id": "c2"}]}
        candidates = [{"headline": f"후보{i}", "score": {"specificity": 2, "life_impact": 2, "immediacy": 2, "exaggeration_risk": 0}, "total": 6} for i in range(5)]
        sources = [
            {"publisher": "국토교통부", "url": "https://www.molit.go.kr/a"},
            {"publisher": "연합뉴스", "url": "https://www.yna.co.kr/b"},
        ]
        source_block = [
            {"publisher": "국토교통부", "date": "2026.8.18", "domain": "molit.go.kr"},
            {"publisher": "연합뉴스", "date": "2026.8.18", "domain": "yna.co.kr"},
        ]
        board = {"story_id": "s", "card_count": 3, "sources": sources, "hook": {"headline": "정부 수도권 주택 공급계획 공식 발표", "deck": "수도권 대상과 입주 시점은 아직 일부 정해지지 않았습니다"}, "hook_candidates": candidates, "cards": [
            {"index": 1, "role": "hook", "visual_role": "현장 사진 중심 훅", "copy": "정부가 공급계획을 발표했습니다.", "evidence_ids": ["c1"]},
            {"index": 2, "role": "facts_and_context", "visual_role": "수치 비교표", "copy": "확인된 내용입니다.", "evidence_ids": ["c1", "c2"]},
            {"index": 3, "role": "impact_unknowns_sources", "visual_role": "영향 체크리스트와 출처", "copy": "일부 일정은 미정입니다.", "evidence_ids": ["c2"], "source_block": source_block, "required_text": ["출처", "국토교통부 · 2026.8.18 · molit.go.kr", "연합뉴스 · 2026.8.18 · yna.co.kr"]},
        ], "qa": {"hard_fail_passed": True, "editorial_score": 13}}
        return story, board

    def test_valid(self):
        MOD.validate(*self.fixture())

    def test_forbidden_hook(self):
        story, board = self.fixture()
        board["cards"][0]["copy"] = "전 국민 충격"
        with self.assertRaises(ValueError):
            MOD.validate(story, board)

    def test_last_card_requires_all_sources(self):
        story, board = self.fixture()
        board["cards"][-1]["source_block"].pop()
        with self.assertRaisesRegex(ValueError, "모든 출처"):
            MOD.validate(story, board)

    def test_sources_are_visible_only_on_last_card(self):
        story, board = self.fixture()
        board["cards"][0]["required_text"] = ["출처: 국토교통부"]
        with self.assertRaisesRegex(ValueError, "마지막 카드에만"):
            MOD.validate(story, board)

    def test_visual_roles_must_be_unique(self):
        story, board = self.fixture()
        board["cards"][1]["visual_role"] = board["cards"][0]["visual_role"]
        with self.assertRaisesRegex(ValueError, "visual_role"):
            MOD.validate(story, board)


if __name__ == "__main__":
    unittest.main()
