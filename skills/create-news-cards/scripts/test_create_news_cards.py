from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

PREP_PATH = Path(__file__).with_name("prepare_candidates.py")
SPEC = importlib.util.spec_from_file_location("prepare_candidates", PREP_PATH)
PREP = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(PREP)


def load_module(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


CONTACT = load_module("make_contact_sheets")
SELECT = load_module("select_direction")
RENDER = load_module("render_cards")


class CreateCardsTests(unittest.TestCase):
    def board(self, count):
        roles = ["hook", "facts_and_context", "impact_unknowns_sources"] if count == 3 else ["hook", "verified_facts", "context_and_positions", "impact_unknowns_sources"]
        return {"story_id": "s", "card_count": count, "cards": [{"index": i + 1, "role": role, "copy": f"copy {i}"} for i, role in enumerate(roles)]}

    def test_always_prepares_twelve_jobs_for_three_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = PREP.prepare(self.board(3), Path(tmp), "1024x1024")
            self.assertEqual(plan["candidate_count"], 12)
            self.assertEqual(plan["direction_count"], 4)

    def test_always_prepares_twelve_jobs_for_four_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = PREP.prepare(self.board(4), Path(tmp), "1024x1024")
            self.assertEqual(plan["candidate_count"], 12)
            self.assertEqual(plan["direction_count"], 3)
            job = json.loads(Path(plan["jobs"][0]["job"]).read_text(encoding="utf-8"))
            self.assertEqual(job["batch_size"], 1)
            self.assertEqual(job["workers"], 1)

    def test_render_selected_complete_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            board = self.board(3)
            board.update({"hook": {"headline": "정부 수도권 주택 공급계획 공식 발표"}, "basis_time_kst": "2026-08-17 17:00"})
            board["cards"][-1]["source_block"] = [
                {"publisher": "기관", "date": "2026.08.17", "domain": "example.go.kr"}
            ]
            for direction in range(1, 5):
                folder = work / "candidates" / f"direction-{direction:02d}"
                folder.mkdir(parents=True)
                for card in range(1, 4):
                    Image.new("RGB", (1024, 1024), (30 * direction, 40 * card, 80)).save(folder / f"card-{card:02d}.png")
            selection = {"schema_version": "1.0", "story_id": "s", "direction_id": "direction-01", "card_count": 3, "backgrounds": [str((work / "candidates" / "direction-01" / f"card-{i:02d}.png").resolve()) for i in range(1, 4)]}
            (work / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
            qa = RENDER.render(work, board)
            self.assertTrue(qa["passed"])
            self.assertEqual(qa["candidate_count"], 12)
            self.assertEqual(len(list((work / "slides").glob("*.png"))), 3)


if __name__ == "__main__":
    unittest.main()
