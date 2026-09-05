import ast
import contextlib
import io
import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS = Path(__file__).parent


def _send(_payload):
    return None


def _mark_tab():
    return None


def switch_tab(_target_id):
    raise AssertionError('diagnostics must not activate tabs')


class ComposerWaitTests(unittest.TestCase):
    def run_wait(self, ready_at, create_dialog=False, authentication=False):
        clock = SimpleNamespace(seconds=0)
        module = ast.parse((SCRIPTS / 'browser_web_upload_prepare.py').read_text(encoding='utf-8'))
        function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'wait_for_multiple_input')

        def pause(*_args):
            clock.seconds += 1

        namespace = {
            'json': json, 'time': SimpleNamespace(monotonic=lambda: clock.seconds),
            'paced_wait': pause,
            'js': lambda _expression: {'exists': clock.seconds >= ready_at, 'multiple': clock.seconds >= ready_at},
            'read_upload_state': lambda: {
                'has_create_dialog': create_dialog, 'dialog_present': create_dialog,
                'login_wall': authentication, 'file_inputs': [{'multiple': False}],
            },
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<composer-wait>', 'exec'), namespace)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                result = namespace['wait_for_multiple_input']()
            except RuntimeError as error:
                result = error
        return result, clock.seconds, output.getvalue()

    def test_delayed_input_in_verified_create_dialog_gets_bounded_grace(self):
        result, elapsed, output = self.run_wait(11, create_dialog=True)
        self.assertEqual(result, {'exists': True, 'multiple': True})
        self.assertEqual(elapsed, 11)
        self.assertEqual(output, '')

    def test_absent_dialog_stops_at_original_deadline(self):
        result, elapsed, output = self.run_wait(100)
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(elapsed, 8)
        self.assertIn('create_dialog_unavailable', output)
        self.assertIn('"retry_create": false', output)

    def test_missing_multiple_input_cannot_extend_wait_forever(self):
        result, elapsed, output = self.run_wait(100, create_dialog=True)
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(elapsed, 20)
        self.assertIn('create_dialog_input_missing', output)

    def test_authentication_stops_even_if_input_is_present(self):
        result, elapsed, _output = self.run_wait(0, authentication=True)
        self.assertIsInstance(result, RuntimeError)
        self.assertIn('authentication boundary', str(result))
        self.assertEqual(elapsed, 0)


class DomProbeTests(unittest.TestCase):
    def run_probe(self, root, product='Edg/152.0', targets=None, destination=None):
        calls = []
        if targets is None:
            targets = [{'type': 'page', 'url': 'https://www.instagram.com/newspick_studio/', 'targetId': 'instagram'}]

        def fake_cdp(method, **_kwargs):
            calls.append(method)
            if method == 'Browser.getVersion':
                return {'product': product}
            if method == 'Target.getTargets':
                return {'targetInfos': targets}
            if method == 'Target.attachToTarget':
                return {'sessionId': 'session'}
            raise AssertionError('unexpected CDP mutation: ' + method)

        with patch.dict(os.environ, {
            'NEWS_PICK_OUTPUT_ROOT': str(root),
            'IG_DOM_DIAGNOSTIC_PATH': str(destination or root / 'diagnostic.json'),
        }), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(str(SCRIPTS / 'browser_web_dom_probe.py'), init_globals={
                'cdp': fake_cdp, 'switch_tab': switch_tab,
                'js': lambda _expression: {'dialog_count': 1, 'file_inputs': [{'multiple': True}]},
            })
        return calls

    def test_report_is_read_only_and_does_not_activate_navigate_or_click(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = self.run_probe(root)
            report = json.loads((root / 'diagnostic.json').read_text(encoding='utf-8'))
            self.assertTrue(report['read_only'])
            self.assertEqual(report['connection'], 'edge9333')
            self.assertEqual(calls, ['Browser.getVersion', 'Target.getTargets', 'Target.attachToTarget'])

    def test_chrome_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, 'Microsoft Edge'):
            self.run_probe(Path(directory), product='Chrome/152.0')

    def test_multiple_targets_and_lookalike_host_are_rejected(self):
        for targets in (
            [{'type': 'page', 'url': 'https://www.instagram.com.evil.test/', 'targetId': 'wrong'}],
            [{'type': 'page', 'url': 'https://www.instagram.com/', 'targetId': str(index)} for index in range(2)],
        ):
            with self.subTest(targets=targets), tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, 'exactly one'):
                self.run_probe(Path(directory), targets=targets)

    def test_report_cannot_be_written_outside_output_root(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, 'NEWS_PICK_OUTPUT_ROOT'):
            root = Path(directory)
            self.run_probe(root / 'output', destination=root / 'outside.json')


if __name__ == '__main__':
    unittest.main()
