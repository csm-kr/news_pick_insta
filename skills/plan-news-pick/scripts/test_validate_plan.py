from __future__ import annotations

import importlib.util
import random
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

PATH = Path(__file__).with_name("validate_plan.py")
SPEC = importlib.util.spec_from_file_location("validate_plan", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class PlanTests(unittest.TestCase):
    def fixture(self):
        story = {"story_id": "s", "verification_status": "verified", "claims": [{"id": "c1"}, {"id": "c2"}]}
        headline = "정부 수도권 주택 공급계획 공식 발표"
        hook_types = ["immediate_consequence", "reversal_contrast", "loss_gap", "decision_deadline", "answerable_question"]
        candidates = []
        for i, hook_type in enumerate(hook_types):
            score = {
                "specificity": 2,
                "life_impact": 2,
                "immediacy": 2,
                "tension": 2 if i == 0 else 1,
                "curiosity_gap": 2 if i == 0 else 1,
                "visual_grip": 2,
                "continuation_value": 2,
                "exaggeration_risk": 0,
            }
            candidates.append({
                "headline": headline if i == 0 else f"수도권 공급계획 결과를 묻는 후보 문장 {i}",
                "hook_type": hook_type,
                "score": score,
                "total": sum(score.values()),
            })
        sources = [
            {"publisher": "국토교통부", "url": "https://www.molit.go.kr/a"},
            {"publisher": "연합뉴스", "url": "https://www.yna.co.kr/b"},
        ]
        source_block = [
            {"publisher": "국토교통부", "date": "2026.8.18", "domain": "molit.go.kr"},
            {"publisher": "연합뉴스", "date": "2026.8.18", "domain": "yna.co.kr"},
        ]
        board = {"story_id": "s", "card_count": 5, "sources": sources, "hook": {"headline": headline, "deck": "수도권 대상과 입주 시점은 아직 일부 정해지지 않았습니다"}, "hook_candidates": candidates, "cards": [
            {"index": 1, "role": "hook", "visual_role": "하단 그라데이션 현장 사진 표지", "copy": "정부가 공급계획을 발표했습니다.", "evidence_ids": ["c1"]},
            {"index": 2, "role": "verified_facts", "visual_role": "현장 사진과 핵심 사실표", "copy": "정부는 수도권 주택 공급 후보지를 공개했습니다. 대상 지역과 물량은 공식 발표에 명시됐고 세부 입주 일정은 추가 절차를 거칩니다.", "evidence_ids": ["c1", "c2"], "reference_requirements": ["후보지 실제 사진"], "chart_spec": {"type": "fact table", "columns": ["구분", "내용"], "rows": [["발표", "후보지"], ["상태", "절차 중"]]}},
            {"index": 3, "role": "numbers_and_context", "visual_role": "다른 지역 사진과 비교표", "copy": "발표 물량은 지역별로 차이가 있습니다. 공급 방식과 사업 단계가 달라 실제 입주 가능 시점은 같은 숫자만으로 비교하기 어렵습니다.", "evidence_ids": ["c1", "c2"], "reference_requirements": ["지역별 다른 실제 사진"], "chart_spec": {"type": "comparison table", "columns": ["지역", "단계"], "rows": [["A", "발표"], ["B", "검토"]]}},
            {"index": 4, "role": "impact_and_reactions", "visual_role": "수요자 사진과 영향표", "copy": "수요자는 청약 대상과 발표 일정을 따로 확인해야 합니다. 지자체와 시장의 반응은 엇갈리지만 확정되지 않은 일정은 단정할 수 없습니다.", "evidence_ids": ["c1", "c2"], "reference_requirements": ["수요자 관련 실제 사진"], "chart_spec": {"type": "impact table", "columns": ["대상", "확인점"], "rows": [["수요자", "청약"], ["지자체", "일정"]]}},
            {"index": 5, "role": "sources", "visual_role": "출처 전용 목록", "copy": "사용한 원문과 기준시각을 확인합니다.", "evidence_ids": ["c2"], "source_block": source_block, "required_text": ["출처", "국토교통부 · 2026.8.18 · molit.go.kr", "연합뉴스 · 2026.8.18 · yna.co.kr"]},
        ], "caption": "정부가 수도권 주택 공급계획을 발표했지만 대상과 입주 시점은 일부 정해지지 않았습니다. 세부 조건은 원문에서 확인해야 합니다.\n\n기준시각: 2026.8.18 오전 9:00 KST\n\n원문\n- 국토교통부: https://www.molit.go.kr/a", "qa": {"hard_fail_passed": True, "editorial_score": 16}}
        return story, board

    def test_valid(self):
        MOD.validate(*self.fixture())

    def textured_image(self, seed: int) -> Image.Image:
        rng = random.Random(seed)
        image = Image.new("RGB", (320, 240), (40, 40, 60))
        draw = ImageDraw.Draw(image)
        for _ in range(60):
            x0, y0 = rng.randint(0, 300), rng.randint(0, 220)
            draw.rectangle((x0, y0, x0 + rng.randint(6, 60), y0 + rng.randint(6, 60)), fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
        return image

    def attach_reference_images(self, board: dict, root: Path) -> list[Path]:
        paths = []
        for index, card in enumerate(board["cards"], 1):
            path = root / f"ref-{index}.png"
            self.textured_image(index).save(path)
            card["reference_images"] = [str(path)]
            paths.append(path)
        return paths

    def test_distinct_primary_reference_images_are_accepted(self):
        story, board = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            self.attach_reference_images(board, Path(tmp))
            MOD.validate(story, board)

    def test_identical_primary_reference_path_is_blocked(self):
        story, board = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            self.attach_reference_images(board, Path(tmp))
            board["cards"][2]["reference_images"] = list(board["cards"][0]["reference_images"])
            with self.assertRaisesRegex(ValueError, "첫 reference"):
                MOD.validate(story, board)

    def test_relative_reference_paths_resolve_against_storyboard_directory(self):
        story, board = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.attach_reference_images(board, root)
            copy = root / "republished.png"
            Image.open(paths[0]).resize((240, 180), Image.Resampling.LANCZOS).save(copy)
            for card, path in zip(board["cards"], paths):
                card["reference_images"] = [path.name]
            board["cards"][3]["reference_images"] = [copy.name]
            with self.assertRaisesRegex(ValueError, "같은 사진"):
                MOD.validate(story, board, board_dir=root)

    def test_resized_copy_primary_reference_is_blocked(self):
        story, board = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.attach_reference_images(board, root)
            copy = root / "republished.png"
            Image.open(paths[0]).resize((240, 180), Image.Resampling.LANCZOS).save(copy)
            board["cards"][3]["reference_images"] = [str(copy)]
            with self.assertRaisesRegex(ValueError, "같은 사진"):
                MOD.validate(story, board)

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
        with self.assertRaisesRegex(ValueError, "5장에만"):
            MOD.validate(story, board)

    def test_required_text_without_an_as_of_date_is_blocked(self):
        # 2026-09-25 17시·09-24 17시 표지가 기준시각 줄 없이 생성돼 카드 하단이 비어 나갔다.
        story, board = self.fixture()
        board["cards"][0]["required_text"] = ["36년 만의 금메달,", "0.317초 차였다", "아시안게임 남자 K2 500m"]
        with self.assertRaisesRegex(ValueError, "기준시각"):
            MOD.validate(story, board)

    def test_required_text_accepts_either_as_of_wording(self):
        for line in ("2026년 9월 25일 발표 기준", "기준시각 · 2026-09-25 17:00 KST", "2026-09-25 기준"):
            with self.subTest(line=line):
                story, board = self.fixture()
                board["cards"][0]["required_text"] = ["36년 만의 금메달,", "0.317초 차였다", line]
                MOD.validate(story, board)

    def test_cards_without_required_text_stay_valid(self):
        story, board = self.fixture()
        self.assertNotIn("required_text", board["cards"][0])
        MOD.validate(story, board)

    def test_visual_roles_must_be_unique(self):
        story, board = self.fixture()
        board["cards"][1]["visual_role"] = board["cards"][0]["visual_role"]
        with self.assertRaisesRegex(ValueError, "visual_role"):
            MOD.validate(story, board)

    def test_caption_rejects_card_index_outline(self):
        story, board = self.fixture()
        board["caption"] = "한 줄 요약입니다.\n\n1장 | 핵심 수치\n2장 | 영향\n\n기준시각: 2026.8.18 오전 9:00 KST"
        with self.assertRaisesRegex(ValueError, "장별 목차"):
            MOD.validate(story, board)

    def test_caption_requires_one_news_paragraph(self):
        story, board = self.fixture()
        board["caption"] = "첫 번째 뉴스 문단입니다.\n\n두 번째 뉴스 문단입니다.\n\n기준시각: 2026.8.18 오전 9:00 KST"
        with self.assertRaisesRegex(ValueError, "하나의 문단"):
            MOD.validate(story, board)

    def test_all_high_impact_score_fields_are_required(self):
        story, board = self.fixture()
        board["hook_candidates"][0]["score"].pop("tension")
        with self.assertRaisesRegex(ValueError, "고강도 사실형"):
            MOD.validate(story, board)

    def test_selected_hook_must_be_highest_scoring_candidate(self):
        story, board = self.fixture()
        board["hook_candidates"][1]["score"]["tension"] = 2
        board["hook_candidates"][1]["score"]["curiosity_gap"] = 2
        board["hook_candidates"][1]["total"] = sum(board["hook_candidates"][1]["score"].values())
        board["hook_candidates"][1]["score"]["immediacy"] = 2
        board["hook_candidates"][1]["total"] = sum(board["hook_candidates"][1]["score"].values())
        board["hook_candidates"][0]["score"]["visual_grip"] = 1
        board["hook_candidates"][0]["total"] = sum(board["hook_candidates"][0]["score"].values())
        with self.assertRaisesRegex(ValueError, "최고점"):
            MOD.validate(story, board)

    def test_editorial_score_requires_sixteen_of_twenty(self):
        story, board = self.fixture()
        board["qa"]["editorial_score"] = 15
        with self.assertRaisesRegex(ValueError, "기획 QA"):
            MOD.validate(story, board)


if __name__ == "__main__":
    unittest.main()
