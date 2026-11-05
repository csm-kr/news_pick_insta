from __future__ import annotations

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
        self.assertEqual(transport.ops("page_cdp")[-1], {"op": "page_cdp", "page": "p1", "method": "Browser.getWindowForTarget", "params": {}})

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
