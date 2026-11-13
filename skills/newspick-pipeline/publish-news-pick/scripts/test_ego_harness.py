from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ego_harness


class FakeTransport:
    """ego_bridge.mjs 대신 op 호출을 기록하고 정해진 응답을 돌려준다."""

    def __init__(self, tabs=None, window_state="normal"):
        self.tabs = tabs if tabs is not None else [
            {"label": "p1", "url": "https://www.instagram.com/newspick_studio/", "title": "IG"},
        ]
        self.window_state = window_state
        self.calls = []
        self.next_label = len(self.tabs) + 1

    def call(self, op):
        self.calls.append(op)
        kind = op["op"]
        if kind == "tabs":
            return [dict(t) for t in self.tabs]
        if kind == "new_page":
            label = f"p{self.next_label}"
            self.next_label += 1
            self.tabs.append({"label": label, "url": "about:blank", "title": ""})
            return {"label": label}
        if kind == "goto":
            for tab in self.tabs:
                if tab["label"] == op["page"]:
                    tab["url"] = op["url"]
            return {}
        if kind == "close_page":
            self.tabs = [t for t in self.tabs if t["label"] != op["page"]]
            return {}
        if kind == "page_cdp":
            method = op["method"]
            if method == "Browser.getWindowForTarget":
                return {"windowId": 7, "bounds": {"windowState": self.window_state}}
            if method == "Page.captureScreenshot":
                if self.window_state == "minimized":
                    raise RuntimeError("Cannot capture a screenshot while the window is minimized.")
                return {"data": "aGVsbG8="}
            return {"echo": method, "page": op["page"]}
        if kind == "task_cdp":
            if op["method"] == "Browser.setWindowBounds":
                self.window_state = op["params"]["bounds"]["windowState"]
                return {}
            return {"task": op["method"]}
        raise AssertionError(f"unexpected op {op}")

    def ops(self, kind):
        return [c for c in self.calls if c["op"] == kind]


class EgoSessionTests(unittest.TestCase):
    def session(self, **kwargs):
        transport = FakeTransport(**kwargs)
        return ego_harness.EgoSession(transport, start_url="https://www.instagram.com/newspick_studio/"), transport

    def test_starts_on_existing_instagram_page_without_navigation(self):
        session, transport = self.session(tabs=[
            {"label": "p1", "url": "https://example.com/", "title": ""},
            {"label": "p2", "url": "https://www.instagram.com/x/", "title": ""},
        ])
        self.assertEqual(session.send({"meta": "current_tab"})["targetId"], "p2")
        self.assertEqual(transport.ops("goto"), [])

    def test_cdn_and_api_tabs_are_not_instagram_app_pages(self):
        # window.require가 없는 CDN 이미지·API JSON 탭을 고르면 'R is not a function'이 난다(10-25).
        session, transport = self.session(tabs=[
            {"label": "p1", "url": "https://scontent-ssn1-1.cdninstagram.com/v/t51/a.jpg", "title": ""},
            {"label": "p2", "url": "https://www.instagram.com/api/v1/users/web_profile_info/?username=x", "title": ""},
            {"label": "p3", "url": "https://www.google.com/search?q=instagram.com", "title": ""},
        ])
        self.assertEqual(session.send({"meta": "current_tab"})["targetId"], "p1")
        self.assertEqual(transport.ops("goto"), [{"op": "goto", "page": "p1", "url": "https://www.instagram.com/newspick_studio/"}])

    def test_navigates_first_page_to_start_url_when_no_instagram_page(self):
        session, transport = self.session(tabs=[{"label": "p1", "url": "about:blank", "title": ""}])
        self.assertEqual(transport.ops("goto"), [{"op": "goto", "page": "p1", "url": "https://www.instagram.com/newspick_studio/"}])
        self.assertEqual(session.send({"meta": "current_tab"})["url"], "https://www.instagram.com/newspick_studio/")

    def test_get_targets_lists_only_task_pages_by_label(self):
        session, _ = self.session()
        infos = session.send({"method": "Target.getTargets", "params": {}, "session_id": None})["result"]["targetInfos"]
        self.assertEqual(infos, [{"targetId": "p1", "type": "page", "url": "https://www.instagram.com/newspick_studio/", "title": "IG", "attached": True}])

    def test_create_target_opens_new_page_and_navigates(self):
        session, transport = self.session()
        result = session.send({"method": "Target.createTarget", "params": {"url": "https://www.instagram.com/p/x/", "background": True}, "session_id": None})["result"]
        self.assertEqual(result, {"targetId": "p2"})
        self.assertIn({"op": "goto", "page": "p2", "url": "https://www.instagram.com/p/x/"}, transport.calls)
        # 새 탭은 만들기만 하고 현재 세션은 바꾸지 않는다(harness 동작과 같음).
        self.assertEqual(session.send({"meta": "current_tab"})["targetId"], "p1")

    def test_public_news_and_style_navigation_never_reaches_instagram_transport(self):
        for request in (
            {"method": "Page.navigate", "params": {"url": "https://news.mt.co.kr/article/example"}, "session_id": "p1"},
            {"method": "Target.createTarget", "params": {"url": "https://www.korea.kr/cardnews/example", "background": True}, "session_id": None},
        ):
            with self.subTest(method=request['method']):
                session, transport = self.session()
                with self.assertRaisesRegex(RuntimeError, 'Aside'):
                    session.send(request)
                self.assertEqual(transport.ops('new_page'), [])
                self.assertEqual(transport.ops('goto'), [])
                self.assertEqual([x for x in transport.ops('page_cdp') if x['method'] == 'Page.navigate'], [])

    def test_instagram_public_post_navigation_remains_available(self):
        session, transport = self.session()
        session.send({'method': 'Page.navigate', 'params': {'url': 'https://www.instagram.com/p/approved/'}, 'session_id': 'p1'})
        self.assertEqual(transport.ops('page_cdp')[-1]['params']['url'], 'https://www.instagram.com/p/approved/')

    def test_new_window_request_restores_window_without_stealing_focus(self):
        # 스토리 검증은 화면에 보이는 탭이 필요해 newWindow를 쓴다. ego 새 탭은 앞으로 가져오지 않아도
        # visible·unfocused로 영상을 재생하므로(11-06 실측) 최소화된 창만 복원하고 bringToFront는 하지 않는다.
        session, transport = self.session(window_state="minimized")
        session.send({"method": "Target.createTarget", "params": {"url": "about:blank", "background": True, "newWindow": True}, "session_id": None})
        self.assertEqual([c for c in transport.ops("page_cdp") if c["method"] == "Page.bringToFront"], [])
        self.assertEqual(transport.window_state, "normal")

    def test_background_tab_request_does_not_touch_window(self):
        session, transport = self.session(window_state="minimized")
        session.send({"method": "Target.createTarget", "params": {"url": "about:blank", "background": True}, "session_id": None})
        self.assertEqual([c for c in transport.ops("page_cdp") if c["method"] == "Page.bringToFront"], [])
        self.assertEqual(transport.window_state, "minimized")

    def test_attach_returns_session_that_routes_cdp_to_that_page(self):
        session, transport = self.session()
        target = session.send({"method": "Target.createTarget", "params": {"url": "about:blank"}, "session_id": None})["result"]["targetId"]
        sid = session.send({"method": "Target.attachToTarget", "params": {"targetId": target, "flatten": True}, "session_id": None})["result"]["sessionId"]
        session.send({"method": "Runtime.evaluate", "params": {"expression": "1"}, "session_id": sid})
        self.assertEqual(transport.ops("page_cdp")[-1]["page"], target)
        self.assertEqual(transport.ops("goto"), [])

    def test_set_session_switches_current_page(self):
        session, transport = self.session()
        session.send({"method": "Target.createTarget", "params": {"url": "about:blank"}, "session_id": None})
        session.send({"meta": "set_session", "session_id": "p2", "target_id": "p2"})
        self.assertEqual(session.send({"meta": "session"})["session_id"], "p2")
        session.send({"method": "DOM.getDocument", "params": {}, "session_id": None})
        self.assertEqual(transport.ops("page_cdp")[-1]["page"], "p2")

    def test_close_target_closes_page_and_falls_back_to_instagram_page(self):
        session, transport = self.session()
        session.send({"method": "Target.createTarget", "params": {"url": "about:blank"}, "session_id": None})
        session.send({"meta": "set_session", "session_id": "p2", "target_id": "p2"})
        session.send({"method": "Target.closeTarget", "params": {"targetId": "p2"}, "session_id": None})
        self.assertEqual(transport.ops("close_page"), [{"op": "close_page", "page": "p2"}])
        self.assertEqual(session.send({"meta": "current_tab"})["targetId"], "p1")

    def test_activate_target_brings_page_to_front(self):
        session, transport = self.session()
        session.send({"method": "Target.activateTarget", "params": {"targetId": "p1"}, "session_id": None})
        self.assertEqual(transport.ops("page_cdp")[-1]["method"], "Page.bringToFront")

    def test_detach_is_a_noop(self):
        session, transport = self.session()
        before = len(transport.calls)
        self.assertEqual(session.send({"method": "Target.detachFromTarget", "params": {"sessionId": "p1"}, "session_id": None}), {"result": {}})
        self.assertEqual(len(transport.calls), before)

    def test_screenshot_restores_minimized_window_and_minimizes_again(self):
        session, transport = self.session(window_state="minimized")
        result = session.send({"method": "Page.captureScreenshot", "params": {"format": "png"}, "session_id": None})["result"]
        self.assertEqual(result, {"data": "aGVsbG8="})
        states = [c["params"]["bounds"]["windowState"] for c in transport.ops("task_cdp")]
        self.assertEqual(states, ["normal", "minimized"])
        self.assertEqual(transport.window_state, "minimized")

    def test_screenshot_on_visible_window_does_not_touch_window(self):
        session, transport = self.session()
        session.send({"method": "Page.captureScreenshot", "params": {}, "session_id": None})
        self.assertEqual(transport.ops("task_cdp"), [])

    def test_browser_version_identifies_ego_lite(self):
        session, _ = self.session()
        product = session.send({"method": "Browser.getVersion", "params": {}, "session_id": None})["result"]["product"]
        self.assertTrue(product.startswith("ego-lite/"))

    def test_window_lookup_maps_target_to_page(self):
        session, transport = self.session()
        session.send({"method": "Browser.getWindowForTarget", "params": {"targetId": "p1"}, "session_id": None})
        self.assertEqual(transport.ops("page_cdp")[-1], {"op": "page_cdp", "page": "p1", "method": "Browser.getWindowForTarget", "params": {}, "timeout": 110000})

    def test_page_cdp_carries_timeout_for_long_scripts(self):
        # ego page.cdp 기본 제한 시간은 짧아서, 몇 분 걸리는 팔로잉 목록 수집이 19초에 끊겼다(11-06).
        transport = FakeTransport()
        session = ego_harness.EgoSession(transport, start_url="https://www.instagram.com/newspick_studio/", cdp_timeout_ms=600000)
        session.send({"method": "Runtime.evaluate", "params": {"expression": "1"}, "session_id": None})
        self.assertEqual(transport.ops("page_cdp")[-1]["timeout"], 600000)

    def test_unsupported_target_and_browser_methods_fail_closed(self):
        session, _ = self.session()
        for method in ("Target.setDiscoverTargets", "Browser.close"):
            with self.assertRaises(RuntimeError):
                session.send({"method": method, "params": {}, "session_id": None})

    def test_unknown_session_fails_closed(self):
        session, _ = self.session()
        with self.assertRaises(RuntimeError):
            session.send({"method": "Runtime.evaluate", "params": {}, "session_id": "p9"})

    def test_meta_events_and_dialog_are_empty(self):
        session, _ = self.session()
        self.assertEqual(session.send({"meta": "drain_events"}), {"events": []})
        self.assertEqual(session.send({"meta": "pending_dialog"}), {"dialog": None})


class HelperNamespaceTests(unittest.TestCase):
    def test_private_send_pattern_used_by_helpers_reaches_ego_session(self):
        transport = FakeTransport()
        session = ego_harness.EgoSession(transport, start_url="https://www.instagram.com/newspick_studio/")
        namespace = ego_harness.helper_namespace(session.send)
        script = (
            "wrapped = switch_tab\n"
            "inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped\n"
            "private = inner.__globals__\n"
            "tid = cdp('Target.createTarget', url='about:blank', background=True)['targetId']\n"
            "sid = cdp('Target.attachToTarget', targetId=tid, flatten=True)['sessionId']\n"
            "private['_send']({'meta': 'set_session', 'session_id': sid, 'target_id': tid})\n"
            "RESULT = current_tab()['targetId']\n"
        )
        exec(compile(script, "<test>", "exec"), namespace)
        self.assertEqual(namespace["RESULT"], "p2")

    def test_js_returns_runtime_value(self):
        class JsTransport(FakeTransport):
            def call(self, op):
                if op["op"] == "page_cdp" and op["method"] == "Runtime.evaluate":
                    self.calls.append(op)
                    return {"result": {"type": "string", "value": "ok"}}
                return super().call(op)

        transport = JsTransport()
        session = ego_harness.EgoSession(transport, start_url="https://www.instagram.com/newspick_studio/")
        namespace = ego_harness.helper_namespace(session.send)
        self.assertEqual(namespace["js"]("document.title"), "ok")
        self.assertTrue(transport.ops("page_cdp")[-1]["params"]["returnByValue"])

    def test_click_at_xy_dispatches_press_and_release(self):
        transport = FakeTransport()
        session = ego_harness.EgoSession(transport, start_url="https://www.instagram.com/newspick_studio/")
        namespace = ego_harness.helper_namespace(session.send)
        namespace["click_at_xy"](10, 20)
        types = [c["params"]["type"] for c in transport.ops("page_cdp") if c["method"] == "Input.dispatchMouseEvent"]
        self.assertEqual(types, ["mousePressed", "mouseReleased"])


class HelperPythonTests(unittest.TestCase):
    """Edge 경로는 browser-harness(3.12)로 helper를 돌렸다. ego 경로도 instagrapi private-venv(3.12)와 같은 python을 쓴다."""

    def test_prefers_private_venv_python_under_output_root(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            python = Path(tmp) / "publish-news-pick" / "private-venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"")
            self.assertEqual(ego_harness.helper_python({"NEWS_PICK_OUTPUT_ROOT": tmp}), str(python))

    def test_explicit_override_wins(self):
        self.assertEqual(ego_harness.helper_python({"NEWS_PICK_HELPER_PYTHON": "C:/py312/python.exe", "NEWS_PICK_OUTPUT_ROOT": "C:/nowhere"}), "C:/py312/python.exe")

    def test_falls_back_to_current_python_without_private_venv(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ego_harness.helper_python({"NEWS_PICK_OUTPUT_ROOT": tmp}), sys.executable)

    def test_run_script_uses_selected_python(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "task.py"
            script.write_text("print(1)\n", encoding="utf-8")
            with patch.object(ego_harness, "helper_python", return_value="C:/py312/python.exe"), patch.object(ego_harness.subprocess, "run") as run:
                ego_harness.run_script(script)
            self.assertEqual(run.call_args.args[0][0], "C:/py312/python.exe")


class EgoProfileTests(unittest.TestCase):
    def test_existing_task_is_resumed_without_creation_only_profile_option(self):
        import json
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for bridge profile checks')
        script = """
const fs=await import('node:fs');const input=JSON.parse(fs.readFileSync(0,'utf8'));
globalThis.listTaskSpaces=async()=>[{id:7,name:'newspick-instagram',taskId:'newspick-instagram',profileId:'Profile 1',ownership:'agent'}];
let chosen;globalThis.taskSpace=async(name,options)=>{chosen={name,options};if(options?.profileId)throw new Error('profileId is only valid when creating a new space');return {spaceId:7}};
const bridge=await import(input.module);let error=null;
try{await bridge.openTask({space:'newspick-instagram',profileId:'Profile 1'})}catch(e){error=e.message}
console.log(JSON.stringify({chosen,error}));
"""
        result = subprocess.run([node, '--input-type=module', '-e', script],
            input=json.dumps({'module': ego_harness.BRIDGE_PATH.as_uri()}), capture_output=True,
            text=True, encoding='utf-8', timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
        observed = json.loads(result.stdout)
        self.assertIsNone(observed['error'])
        self.assertEqual(observed['chosen']['name'], 7)
        self.assertNotIn('profileId', observed['chosen'].get('options') or {})

    def test_workspace_profile_is_used_when_no_override_is_set(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'workspace.json').write_text(
                json.dumps({'browser': {'ego_profile_id': 'Profile 1'}}), encoding='utf-8'
            )
            self.assertEqual(ego_harness.ego_profile_id({'NEWS_PICK_OUTPUT_ROOT': directory}), 'Profile 1')
            self.assertEqual(ego_harness.ego_profile_id({'NEWS_PICK_OUTPUT_ROOT': directory, 'NEWS_PICK_EGO_PROFILE_ID': 'Default'}), 'Default')

    def test_missing_workspace_keeps_legacy_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(ego_harness.ego_profile_id({'NEWS_PICK_OUTPUT_ROOT': directory}))

    def test_bridge_passes_profile_and_rejects_a_different_existing_space(self):
        import json
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for bridge profile checks')
        script = """
const fs=await import('node:fs');const input=JSON.parse(fs.readFileSync(0,'utf8'));
let chosen;globalThis.taskSpace=async(name,options)=>{chosen={name,options};return {spaceId:7}};
globalThis.listTaskSpaces=async()=>[{id:7,profileId:input.profile}];
const bridge=await import(input.module);
let error=null;try{await bridge.openTask({space:'newspick-instagram',profileId:'Profile 1'})}catch(e){error=e.message}
console.log(JSON.stringify({chosen,error}));
"""
        for profile in ('Profile 1', 'Default'):
            with self.subTest(profile=profile):
                result = subprocess.run([node, '--input-type=module', '-e', script],
                    input=json.dumps({'module': ego_harness.BRIDGE_PATH.as_uri(), 'profile': profile}),
                    capture_output=True, text=True, encoding='utf-8', timeout=10,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
                observed = json.loads(result.stdout)
                if profile == 'Profile 1':
                    self.assertIsNone(observed['error'])
                    self.assertEqual(observed['chosen']['options'], {'profileId': 'Profile 1'})
                else:
                    self.assertIn('profile mismatch', observed['error'])


class EgoReadinessTests(unittest.TestCase):
    def probe_result(self, returncode=0, stdout="", stderr=""):
        from subprocess import CompletedProcess
        from unittest.mock import patch

        with patch.object(ego_harness.shutil, "which", return_value="ego-browser.exe"), patch.object(
            ego_harness.subprocess, "run", return_value=CompletedProcess([], returncode, stdout, stderr)
        ):
            return ego_harness.ego_ready()

    def test_ready_marker_on_stderr_is_accepted(self):
        self.assertTrue(self.probe_result(stderr="ego-ready\n[ego-browser:notice] Update available\n"))

    def test_ready_marker_on_stdout_is_accepted(self):
        self.assertTrue(self.probe_result(stdout="ego-ready\n"))

    def test_failed_probe_is_rejected_even_with_marker(self):
        self.assertFalse(self.probe_result(returncode=1, stderr="ego-ready\nconnection failed\n"))

    def test_success_without_marker_is_rejected(self):
        self.assertFalse(self.probe_result(stderr="[ego-browser:notice] Update available\n"))


class EgoAutostartTests(unittest.TestCase):
    """ego lite가 꺼져 있으면 실행기가 직접 켠다(사용자 요청 11-06)."""

    def test_running_ego_is_left_alone(self):
        from unittest.mock import patch
        with patch.object(ego_harness, "ego_process_running", return_value=True), patch.object(ego_harness.subprocess, "Popen") as popen:
            self.assertFalse(ego_harness.ensure_ego_running())
        popen.assert_not_called()

    def test_stopped_ego_is_started_with_service_flag_and_waited_for(self):
        from unittest.mock import patch
        ready = iter([False, False, True])
        with patch.object(ego_harness, "ego_process_running", return_value=False), patch.object(
            ego_harness, "ego_executable", return_value=Path("C:/ego/ego.exe")
        ), patch.object(ego_harness, "ego_ready", side_effect=lambda: next(ready)), patch.object(
            ego_harness.subprocess, "Popen"
        ) as popen, patch.object(ego_harness.time, "sleep"):
            self.assertTrue(ego_harness.ensure_ego_running(timeout=30))
        args = popen.call_args.args[0]
        self.assertEqual(args, [str(Path("C:/ego/ego.exe")), "--startup-ego-browser-service"])

    def test_start_that_never_becomes_ready_fails_clearly(self):
        from unittest.mock import patch
        clock = iter(range(0, 1000, 10))
        with patch.object(ego_harness, "ego_process_running", return_value=False), patch.object(
            ego_harness, "ego_executable", return_value=Path("C:/ego/ego.exe")
        ), patch.object(ego_harness, "ego_ready", return_value=False), patch.object(ego_harness.subprocess, "Popen"), patch.object(
            ego_harness.time, "sleep"
        ), patch.object(ego_harness.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(RuntimeError, "ego lite"):
                ego_harness.ensure_ego_running(timeout=30)

    def test_missing_executable_fails_clearly(self):
        from unittest.mock import patch
        with patch.object(ego_harness, "ego_process_running", return_value=False), patch.object(ego_harness, "ego_executable", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ego.exe"):
                ego_harness.ensure_ego_running()

    def test_executable_override_and_default_location(self):
        self.assertEqual(ego_harness.ego_executable({"NEWS_PICK_EGO_EXE": "D:/ego/ego.exe"}, exists=lambda p: True), Path("D:/ego/ego.exe"))
        default = ego_harness.ego_executable({"LOCALAPPDATA": "C:/Users/x/AppData/Local"}, exists=lambda p: True)
        self.assertEqual(default, Path("C:/Users/x/AppData/Local/Citro Labs/ego lite/Application/ego.exe"))
        self.assertIsNone(ego_harness.ego_executable({"LOCALAPPDATA": "C:/none"}, exists=lambda p: False))

    def test_bridge_start_ensures_ego_first(self):
        from unittest.mock import patch
        with patch.object(ego_harness, "ensure_ego_running", side_effect=RuntimeError("ego lite stopped")) as ensure, patch.object(
            ego_harness.shutil, "which", return_value="C:/bin/ego-browser.exe"
        ), patch.object(ego_harness.subprocess, "Popen") as popen:
            with self.assertRaises(RuntimeError):
                ego_harness.BridgeTransport()
        ensure.assert_called_once()
        popen.assert_not_called()


class BridgeCleanupTests(unittest.TestCase):
    """연결이 실패하거나 강제로 끝나도 임시 폴더를 남기지 않는다(11-13 오후 팔로우 실패 때 남았다)."""

    def test_bridge_that_dies_before_start_removes_its_temp_folder(self):
        import tempfile
        from unittest.mock import MagicMock, patch
        base = Path(tempfile.mkdtemp())
        real_mkdtemp = tempfile.mkdtemp
        dead = MagicMock()
        dead.poll.return_value = 1
        dead.stderr.read.return_value = b"Cannot find module"
        with patch.object(ego_harness, "ensure_ego_running"), patch.object(
            ego_harness.shutil, "which", return_value="C:/bin/ego-browser.exe"
        ), patch.object(ego_harness.tempfile, "gettempdir", return_value=str(base)), patch.object(
            ego_harness.tempfile, "mkdtemp", side_effect=lambda prefix: real_mkdtemp(prefix=prefix, dir=base)
        ), patch.object(ego_harness.subprocess, "Popen", return_value=dead):
            with self.assertRaisesRegex(RuntimeError, "Cannot find module"):
                ego_harness.BridgeTransport()
        self.assertEqual(list(base.glob("newspick-ego-*")), [])

    def test_stale_temp_folders_are_swept_but_fresh_ones_kept(self):
        import os
        import tempfile
        base = Path(tempfile.mkdtemp())
        stale = base / "newspick-ego-old"
        fresh = base / "newspick-ego-new"
        other = base / "someone-else-old"
        for folder in (stale, fresh, other):
            folder.mkdir()
            (folder / "entry.mjs").write_text("x", encoding="utf-8")
        now = 1_000_000.0
        for folder in (stale, other):
            os.utime(folder, (now - 7 * 3600, now - 7 * 3600))
        os.utime(fresh, (now - 60, now - 60))
        removed = ego_harness.sweep_stale_bridge_dirs(base, now=now)
        self.assertEqual(removed, 1)
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(other.exists())


class EgoSessionRecordTests(unittest.TestCase):
    """실제로 어느 ego 프로필에 붙었는지 연결마다 남긴다. 일일 보고가 게시 시각과 맞춰 읽는다(사용자 요청 11-13)."""

    def test_appends_space_and_profile_of_the_connection(self):
        import tempfile
        from datetime import datetime, timezone

        class InfoTransport:
            def call(self, op):
                assert op == {"op": "space_info"}
                return {"spaceId": 91, "name": "newspick-instagram", "profileId": "Profile 2", "profileName": "뉴스픽"}

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "logs" / "ego-sessions.jsonl"
            when = datetime(2026, 11, 13, 7, 8, tzinfo=timezone.utc)
            ego_harness.record_ego_session(InfoTransport(), "newspick-instagram", log, now=when)
            row = json.loads(log.read_text(encoding="utf-8").strip())
            self.assertEqual(row, {"at": "2026-11-13T07:08:00+00:00", "space": "newspick-instagram", "space_id": 91,
                                   "profile_id": "Profile 2", "profile_name": "뉴스픽"})

    def test_recording_failure_never_blocks_the_connection(self):
        import tempfile

        class BrokenTransport:
            def call(self, op):
                raise RuntimeError("unknown op: space_info")

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "ego-sessions.jsonl"
            ego_harness.record_ego_session(BrokenTransport(), "newspick-growth", log)
            self.assertFalse(log.exists())

    def test_log_lives_under_output_root(self):
        self.assertEqual(ego_harness.ego_session_log({"NEWS_PICK_OUTPUT_ROOT": "D:/np/output"}), Path("D:/np/output/logs/ego-sessions.jsonl"))

    def test_bridge_answers_space_info(self):
        source = ego_harness.BRIDGE_PATH.read_text(encoding="utf-8")
        self.assertIn('case "space_info"', source)
        self.assertIn("profileName", source)


class RuntimeGuardTests(unittest.TestCase):
    def test_guard_rejects_non_ego_product(self):
        namespace = {"cdp": lambda method, **_: {"product": "Edg/150.0"}}
        with self.assertRaises(RuntimeError):
            exec(compile(ego_harness.EGO_RUNTIME_GUARD, "<guard>", "exec"), namespace)

    def test_guard_accepts_ego_product(self):
        namespace = {"cdp": lambda method, **_: {"product": "ego-lite/2.2.0"}}
        exec(compile(ego_harness.EGO_RUNTIME_GUARD, "<guard>", "exec"), namespace)


if __name__ == "__main__":
    unittest.main()
