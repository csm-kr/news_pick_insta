import ast
import contextlib
import io
import json
import os
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("browser_web_fill_caption_ai.py")


def load_functions(**namespace):
    module = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SCRIPT), "exec"), namespace)
    return namespace


def switch_state(**overrides):
    return {"label": "AI 레이블 추가", "checked": False, "visible": True,
            "disabled": False, "hit_matches": True, "x": 1000, "y": 520, **overrides}


class AiSwitchTests(unittest.TestCase):
    def exercise(self, reader):
        clock = SimpleNamespace(seconds=0)
        clicks = []

        def sleep(seconds):
            clock.seconds += seconds

        namespace = load_functions(
            json=json, random=SimpleNamespace(uniform=lambda *_args: 0.3),
            time=SimpleNamespace(monotonic=lambda: clock.seconds, sleep=sleep),
            js=lambda _expression: reader(clock.seconds, len(clicks)),
            click_at_xy=lambda *point: clicks.append(point),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                result = namespace["ensure_ai_label"]()
            except RuntimeError as error:
                result = error
        return result, clicks, clock.seconds

    def test_already_enabled_never_toggles_off(self):
        result, clicks, _elapsed = self.exercise(lambda *_args: switch_state(checked=True))
        self.assertEqual(result["clicks"], 0)
        self.assertEqual(clicks, [])

    def test_delayed_state_settles_without_second_click(self):
        result, clicks, elapsed = self.exercise(lambda elapsed, _clicks: switch_state(checked=elapsed >= 2))
        self.assertEqual(result["clicks"], 1)
        self.assertEqual(len(clicks), 1)
        self.assertGreaterEqual(elapsed, 2)

    def test_ignored_first_click_allows_one_confirmed_off_recovery(self):
        result, clicks, elapsed = self.exercise(lambda _elapsed, clicks: switch_state(checked=clicks == 2))
        self.assertTrue(result["checked"])
        self.assertEqual(len(clicks), 2)
        self.assertGreaterEqual(elapsed, 3)

    def test_recovery_stops_after_two_clicks(self):
        result, clicks, elapsed = self.exercise(lambda *_args: switch_state())
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(len(clicks), 2)
        self.assertLess(elapsed, 7)

    def test_obscured_disabled_hidden_or_ambiguous_switch_is_not_clicked(self):
        for state in (None, switch_state(hit_matches=False), switch_state(visible=False), switch_state(disabled=True)):
            with self.subTest(state=state):
                result, clicks, _elapsed = self.exercise(lambda *_args: state)
                self.assertIsInstance(result, RuntimeError)
                self.assertEqual(clicks, [])

    def test_disappearance_after_click_does_not_retry(self):
        result, clicks, _elapsed = self.exercise(lambda _elapsed, clicks: None if clicks else switch_state())
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(len(clicks), 1)

    def test_reread_before_recovery_preserves_late_enabled_state(self):
        reads = []

        def reader(elapsed, _clicks):
            reads.append(elapsed)
            return switch_state(checked=elapsed >= 3 and len(reads) >= 13)

        result, clicks, _elapsed = self.exercise(reader)
        self.assertTrue(result["checked"])
        self.assertEqual(len(clicks), 1)


class AiSwitchDomTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required for DOM fixture")
    def test_observed_unlabelled_input_uses_dialog_label_and_hit_test(self):
        expressions = []
        load_functions(js=lambda expression: expressions.append(expression))["read_ai_switch"]()
        fixture = """
const settings=JSON.parse(process.argv[1]);
const element={checked:settings.checked,disabled:false,contains:()=>false,
 getAttribute:name=>name==='aria-checked'?'true':null,
 getBoundingClientRect:()=>({x:980,y:500,width:40,height:24})};
globalThis.innerWidth=1302;globalThis.innerHeight=698;
globalThis.getComputedStyle=()=>({display:'block',visibility:'visible'});
globalThis.document={
 querySelector:()=>({innerText:['계정',settings.label,'설명'].join(String.fromCharCode(10)),querySelectorAll:()=>Array(settings.count).fill(element)}),
 elementFromPoint:()=>settings.hit?element:{}
};
"""
        for label, count, hit in (("AI 레이블 추가", 1, True), ("AI 라벨 추가", 1, False), ("다른 설정", 1, True), ("AI 레이블 추가", 2, True)):
            with self.subTest(label=label, count=count, hit=hit):
                settings = json.dumps({"label": label, "count": count, "hit": hit, "checked": False})
                output = subprocess.check_output(["node", "-e", fixture + "console.log(JSON.stringify(" + expressions[0] + "));", settings], text=True, encoding="utf-8")
                state = json.loads(output)
                if label == "다른 설정" or count != 1:
                    self.assertIsNone(state)
                else:
                    self.assertFalse(state["checked"])
                    self.assertEqual(state["hit_matches"], hit)


class CaptionResumeTests(unittest.TestCase):
    def test_matching_caption_is_preserved_while_enabling_ai(self):
        caption = "승인된 본문\n\n출처와 기준시각"
        clicks = []
        activations = []

        def fake_js(expression):
            if "const labels=['AI" in expression:
                return switch_state(checked=bool(clicks))
            if "has_share:text.includes" in expression:
                return {"caption": caption, "has_share": True}
            if "return {x:r.x" in expression:
                return {"x": 10, "y": 10, "text": caption + "\n"}
            return caption + "\n"

        def unexpected_input(*_args, **_kwargs):
            raise AssertionError("existing exact caption must not be edited")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caption.txt"
            path.write_text(caption, encoding="utf-8")
            output = io.StringIO()
            with patch.dict(os.environ, {"IG_CAPTION_FILE": str(path)}), patch("time.sleep", return_value=None), contextlib.redirect_stdout(output):
                runpy.run_path(str(SCRIPT), init_globals={
                    "cdp": lambda method: {"targetInfos": [{"type": "page", "url": "https://www.instagram.com/newspick_studio/", "targetId": "instagram"}]},
                    "switch_tab": lambda target, activate=False: activations.append((target, activate)),
                    "js": fake_js, "click_at_xy": lambda *point: clicks.append(point),
                    "press_key": unexpected_input, "type_text": unexpected_input,
                })
            result = json.loads(output.getvalue().split("INSTAGRAM_CAPTION_AI=", 1)[1])
        self.assertEqual(activations, [("instagram", True)])
        self.assertEqual(clicks, [(1000, 520)])
        self.assertTrue(result["caption_matches"])
        self.assertTrue(result["ai_checked"])
        self.assertEqual(result["input_method"], "existing_exact_caption")


if __name__ == "__main__":
    unittest.main()
