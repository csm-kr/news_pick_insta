#!/usr/bin/env python3
"""Run News Pick Browser Harness scripts on ego lite instead of a raw CDP port.

ego lite does not expose a remote-debugging port, so Browser Harness cannot attach
to it. This module keeps the Browser Harness helper surface (`cdp`, `js`,
`click_at_xy`, `switch_tab`, `_send` ...) that the News Pick helper scripts use,
and replaces only the transport: every CDP call goes through `ego_bridge.mjs`,
which runs inside `ego-browser nodejs` and forwards to the ego TaskSpace Page API.

Target/session concepts are mapped onto ego Page labels (`p1`, `p2`, ...):
a label is used as both targetId and sessionId.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

SPACE_NAME = "newspick-instagram"
DEFAULT_START_URL = "https://www.instagram.com/newspick_studio/"
BRIDGE_PATH = Path(__file__).resolve().parent / "ego_bridge.mjs"
PRODUCT = "ego-lite/bridge"
EGO_RUNTIME_GUARD = (
    '_news_pick_product = str(cdp("Browser.getVersion").get("product") or "")\n'
    'if not _news_pick_product.lower().startswith("ego-lite/"):\n'
    '    raise RuntimeError("News Pick ego harness target is not ego lite: " + _news_pick_product)\n'
)
# ego page.cdp 기본 제한 시간은 짧다. 소켓 대기(120초)보다 조금 짧게 잡아 오류가 브리지에서 먼저 돌아오게 한다.
DEFAULT_CDP_TIMEOUT_MS = 110_000
WINDOW_METHODS = {"Browser.getWindowForTarget", "Browser.setWindowBounds", "Browser.getWindowBounds"}
EGO_START_TIMEOUT_SECONDS = 90.0


def is_instagram_app_url(url: str) -> bool:
    """window.require가 있는 Instagram 웹앱 페이지만 고른다. CDN 이미지·API JSON 탭은 'R is not a function'을 낸다."""

    parsed = urlsplit(str(url or ""))
    return parsed.hostname in {"www.instagram.com", "instagram.com"} and not parsed.path.startswith("/api/")


def require_instagram_navigation(url: str) -> None:
    if url == "about:blank":
        return
    if urlsplit(url).scheme == "https" and is_instagram_app_url(url):
        return
    raise RuntimeError("News Pick ego space is for Instagram only; use Aside for public research and reference capture: " + url)


# --- ego lite process -------------------------------------------------------
def ego_executable(environment: Mapping[str, str] | None = None, exists: Callable[[Path], bool] = Path.is_file) -> Path | None:
    source = os.environ if environment is None else environment
    override = str(source.get("NEWS_PICK_EGO_EXE") or "").strip()
    if override:
        return Path(override)
    local = str(source.get("LOCALAPPDATA") or "").strip()
    if not local:
        return None
    candidate = Path(local) / "Citro Labs" / "ego lite" / "Application" / "ego.exe"
    return candidate if exists(candidate) else None


def ego_process_running() -> bool:
    if os.name != "nt":
        return True
    listed = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ego.exe", "/NH"], capture_output=True, text=True, errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return "ego.exe" in (listed.stdout or "").lower()


def ego_profile_id(environment: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if environment is None else environment
    selected = str(source.get("NEWS_PICK_EGO_PROFILE_ID") or "").strip()
    if not selected:
        output = Path(source.get("NEWS_PICK_OUTPUT_ROOT") or Path.cwd() / "output")
        workspace = output / "workspace.json"
        if workspace.is_file():
            settings = json.loads(workspace.read_text(encoding="utf-8-sig"))
            selected = str((settings.get("browser") or {}).get("ego_profile_id") or "").strip()
    if selected and (len(selected) > 128 or any(ord(character) < 32 for character in selected)):
        raise ValueError("Invalid configured ego profile id")
    return selected or None


def ego_session_log(environment: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environment is None else environment
    return Path(source.get("NEWS_PICK_OUTPUT_ROOT") or Path.cwd() / "output") / "logs" / "ego-sessions.jsonl"


def record_ego_session(transport: Any, space: str, log_path: Path | None = None, now: datetime | None = None) -> None:
    """이번 연결이 실제로 붙은 TaskSpace와 ego 프로필을 한 줄 남긴다. 일일 보고가 읽는다. 실패해도 연결은 계속한다."""
    try:
        info = transport.call({"op": "space_info"}) or {}
        path = log_path or ego_session_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"), "space": space,
               "space_id": info.get("spaceId"), "profile_id": info.get("profileId"), "profile_name": info.get("profileName")}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 기록은 보조 기능이라 게시·팔로우를 막지 않는다
        pass


def ego_ready() -> bool:
    executable = shutil.which("ego-browser")
    if not executable:
        return False
    try:
        probe = subprocess.run([executable, "nodejs", "-e", "console.log('ego-ready')"], capture_output=True, text=True,
                               errors="replace", timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False
    # ego-browser forwards console output to stderr on current Windows releases.
    output = (probe.stdout or "") + "\n" + (probe.stderr or "")
    return probe.returncode == 0 and "ego-ready" in output


def ensure_ego_running(timeout: float = EGO_START_TIMEOUT_SECONDS) -> bool:
    """ego lite가 꺼져 있으면 로그온 때와 같은 방식으로 켜고 응답할 때까지 기다린다. 켰으면 True."""

    if ego_process_running():
        return False
    executable = ego_executable()
    if executable is None:
        raise RuntimeError("ego lite가 꺼져 있는데 ego.exe를 찾지 못했다(NEWS_PICK_EGO_EXE로 지정할 수 있다).")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(executable), "--startup-ego-browser-service"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ego_ready():
            return True
        time.sleep(2)
    raise RuntimeError(f"ego lite를 켰지만 {int(timeout)}초 안에 ego-browser가 응답하지 않는다.")


class EgoSession:
    """Browser Harness `_send` semantics implemented over an ego bridge transport."""

    def __init__(self, transport: Any, start_url: str = DEFAULT_START_URL, cdp_timeout_ms: int = DEFAULT_CDP_TIMEOUT_MS):
        require_instagram_navigation(start_url)
        self.transport = transport
        self.start_url = start_url
        self.cdp_timeout_ms = int(cdp_timeout_ms)
        self.current = self._initial_page()

    # --- page bookkeeping -------------------------------------------------
    def _tabs(self) -> list[dict[str, Any]]:
        return [tab for tab in self.transport.call({"op": "tabs"}) if tab.get("label")]

    def _labels(self) -> set[str]:
        return {tab["label"] for tab in self._tabs()}

    def _initial_page(self) -> str:
        tabs = self._tabs()
        for tab in tabs:
            if is_instagram_app_url(tab.get("url")):
                return tab["label"]
        if not tabs:
            label = self.transport.call({"op": "new_page"})["label"]
        else:
            label = tabs[0]["label"]
        self.transport.call({"op": "goto", "page": label, "url": self.start_url})
        return label

    def _page_for(self, session_id: str | None) -> str:
        label = session_id or self.current
        if session_id and session_id not in self._labels():
            raise RuntimeError(f"ego page session not found: {session_id}")
        return label

    def _page_cdp(self, page: str, method: str, params: dict[str, Any]) -> Any:
        if method == "Page.navigate":
            require_instagram_navigation(str(params.get("url") or ""))
        return self.transport.call({"op": "page_cdp", "page": page, "method": method, "params": params, "timeout": self.cdp_timeout_ms})

    # --- Browser Harness protocol -----------------------------------------
    def send(self, req: dict[str, Any]) -> dict[str, Any]:
        if "meta" in req:
            return self._meta(req)
        method = str(req.get("method") or "")
        params = dict(req.get("params") or {})
        session_id = req.get("session_id")
        if method.startswith("Target."):
            return {"result": self._target(method, params)}
        if method == "Browser.getVersion":
            return {"result": {"product": PRODUCT, "protocolVersion": "1.3"}}
        if method in WINDOW_METHODS:
            target = params.pop("targetId", None)
            page = self._page_for(target or session_id)
            if method == "Browser.setWindowBounds":
                return {"result": self.transport.call({"op": "task_cdp", "method": method, "params": params})}
            return {"result": self._page_cdp(page, method, params)}
        if method.startswith("Browser."):
            raise RuntimeError(f"ego harness does not allow {method}")
        page = self._page_for(session_id)
        if method == "Page.captureScreenshot":
            return {"result": self._screenshot(page, params)}
        return {"result": self._page_cdp(page, method, params)}

    def _meta(self, req: dict[str, Any]) -> dict[str, Any]:
        meta = req["meta"]
        if meta == "current_tab":
            tab = next((t for t in self._tabs() if t["label"] == self.current), None)
            if tab is None:
                self.current = self._initial_page()
                tab = next(t for t in self._tabs() if t["label"] == self.current)
            return {"targetId": tab["label"], "url": tab.get("url", ""), "title": tab.get("title", "")}
        if meta == "set_session":
            target = req.get("target_id") or req.get("session_id")
            self.current = self._page_for(target)
            return {}
        if meta == "session":
            return {"session_id": self.current}
        if meta == "drain_events":
            return {"events": []}
        if meta == "pending_dialog":
            return {"dialog": None}
        raise RuntimeError(f"ego harness does not support meta {meta}")

    def _target(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "Target.getTargets":
            return {
                "targetInfos": [
                    {"targetId": t["label"], "type": "page", "url": t.get("url", ""), "title": t.get("title", ""), "attached": True}
                    for t in self._tabs()
                ]
            }
        if method == "Target.createTarget":
            url = str(params.get("url") or "about:blank")
            require_instagram_navigation(url)
            label = self.transport.call({"op": "new_page"})["label"]
            if params.get("newWindow"):
                # Edge의 '뒤쪽 새 창'처럼 보이는 탭이 필요할 때다. ego 새 탭은 창만 최소화가 아니면
                # 앞으로 가져오지 않아도 visible이라 포커스를 뺏지 않는다.
                self._restore_window(label)
            if url != "about:blank":
                self.transport.call({"op": "goto", "page": label, "url": url})
            return {"targetId": label}
        if method == "Target.attachToTarget":
            return {"sessionId": self._page_for(params.get("targetId"))}
        if method == "Target.detachFromTarget":
            return {}
        if method == "Target.activateTarget":
            self._page_cdp(self._page_for(params.get("targetId")), "Page.bringToFront", {})
            return {}
        if method == "Target.closeTarget":
            label = self._page_for(params.get("targetId"))
            self.transport.call({"op": "close_page", "page": label})
            if label == self.current:
                self.current = self._initial_page()
            return {"success": True}
        raise RuntimeError(f"ego harness does not allow {method}")

    def _restore_window(self, page: str) -> None:
        window = self._page_cdp(page, "Browser.getWindowForTarget", {})
        if (window.get("bounds") or {}).get("windowState") == "minimized":
            self.transport.call({"op": "task_cdp", "method": "Browser.setWindowBounds",
                                 "params": {"windowId": window["windowId"], "bounds": {"windowState": "normal"}}})

    def _screenshot(self, page: str, params: dict[str, Any]) -> Any:
        window = self._page_cdp(page, "Browser.getWindowForTarget", {})
        minimized = (window.get("bounds") or {}).get("windowState") == "minimized"
        if not minimized:
            return self._page_cdp(page, "Page.captureScreenshot", params)
        bounds = {"op": "task_cdp", "method": "Browser.setWindowBounds"}
        self.transport.call({**bounds, "params": {"windowId": window["windowId"], "bounds": {"windowState": "normal"}}})
        try:
            return self._page_cdp(page, "Page.captureScreenshot", params)
        finally:
            self.transport.call({**bounds, "params": {"windowId": window["windowId"], "bounds": {"windowState": "minimized"}}})


# --- Browser Harness helper surface ----------------------------------------
# Subset adapted from browser-harness helpers.py (MIT License) so the News Pick
# helper scripts run unchanged. Only functions those scripts call are included.
_HELPERS_SOURCE = r'''
import base64, json, math, os, time

INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://", "about:")


def cdp(method, session_id=None, **params):
    return _send({"method": method, "params": params, "session_id": session_id}).get("result", {})


def drain_events():
    return _send({"meta": "drain_events"})["events"]


def _js_snippet(expression, limit=160):
    snippet = expression.strip().replace("\n", "\\n")
    return snippet[:limit - 3] + "..." if len(snippet) > limit else snippet


def _js_exception_description(result, details):
    desc = result.get("description")
    exc = details.get("exception") if details else None
    if not desc and isinstance(exc, dict):
        desc = exc.get("description")
        if desc is None and "value" in exc:
            desc = str(exc["value"])
        if desc is None:
            desc = exc.get("className")
    if not desc and details:
        desc = details.get("text")
    return desc or "JavaScript evaluation failed"


def _decode_unserializable_js_value(value):
    if value == "NaN":
        return math.nan
    if value == "Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    if value == "-0":
        return -0.0
    if value.endswith("n"):
        return int(value[:-1])
    return value


def _runtime_value(response, expression):
    result = response.get("result", {})
    details = response.get("exceptionDetails")
    if details or result.get("subtype") == "error":
        desc = _js_exception_description(result, details)
        line = details.get("lineNumber") if details else None
        col = details.get("columnNumber") if details else None
        loc = f" at line {line}, column {col}" if line is not None and col is not None else ""
        raise RuntimeError(f"JavaScript evaluation failed{loc}: {desc}; expression: {_js_snippet(expression)}")
    if "value" in result:
        return result["value"]
    if "unserializableValue" in result:
        return _decode_unserializable_js_value(result["unserializableValue"])
    return None


def _runtime_evaluate(expression, session_id=None, await_promise=False):
    r = cdp("Runtime.evaluate", session_id=session_id, expression=expression, returnByValue=True, awaitPromise=await_promise)
    return _runtime_value(r, expression)


def js(expression, target_id=None):
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"] if target_id else None
    try:
        return _runtime_evaluate(expression, session_id=sid, await_promise=True)
    except RuntimeError as e:
        if "Illegal return statement" in str(e):
            return _runtime_evaluate(f"(function(){{{expression}}})()", session_id=sid, await_promise=True)
        raise


def goto_url(url):
    return cdp("Page.navigate", url=url)


def page_info():
    expression = "JSON.stringify({url:location.href,title:document.title,w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})"
    return json.loads(_runtime_evaluate(expression))


def click_at_xy(x, y, button="left", clicks=1):
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=clicks)
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=clicks)


def type_text(text):
    cdp("Input.insertText", text=text)


_KEYS = {
    "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", "\t"), "Backspace": (8, "Backspace", ""),
    "Escape": (27, "Escape", ""), "Delete": (46, "Delete", ""), " ": (32, "Space", " "),
    "ArrowLeft": (37, "ArrowLeft", ""), "ArrowUp": (38, "ArrowUp", ""),
    "ArrowRight": (39, "ArrowRight", ""), "ArrowDown": (40, "ArrowDown", ""),
    "Home": (36, "Home", ""), "End": (35, "End", ""),
    "PageUp": (33, "PageUp", ""), "PageDown": (34, "PageDown", ""),
}


def press_key(key, modifiers=0):
    vk, code, text = _KEYS.get(key, (ord(key[0]) if len(key) == 1 else 0, key, key if len(key) == 1 else ""))
    base = {"key": key, "code": code, "modifiers": modifiers, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    printable_char = len(key) == 1 and bool(text) and not (modifiers & (1 | 2 | 4))
    cdp("Input.dispatchKeyEvent", type="keyDown", **base, **({} if printable_char or not text else {"text": text}))
    if printable_char:
        cdp("Input.dispatchKeyEvent", type="char", text=text, **{k: v for k, v in base.items() if k != "text"})
    cdp("Input.dispatchKeyEvent", type="keyUp", **base)


def scroll(x, y, dy=-300, dx=0):
    cdp("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=dx, deltaY=dy)


def capture_screenshot(path=None, full=False, max_dim=None):
    path = path or os.path.join(os.environ.get("TEMP", "."), "ego-shot.png")
    r = cdp("Page.captureScreenshot", format="png", captureBeyondViewport=full)
    open(path, "wb").write(base64.b64decode(r["data"]))
    if max_dim:
        from PIL import Image
        img = Image.open(path)
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim))
            img.save(path)
    return path


def list_tabs(include_chrome=True):
    out = []
    for t in cdp("Target.getTargets")["targetInfos"]:
        if t["type"] != "page":
            continue
        url = t.get("url", "")
        if not include_chrome and url.startswith(INTERNAL):
            continue
        out.append({"targetId": t["targetId"], "target_id": t["targetId"], "title": t.get("title", ""), "url": url})
    return out


def current_tab():
    r = _send({"meta": "current_tab"})
    return {"targetId": r["targetId"], "target_id": r["targetId"], "url": r["url"], "title": r["title"]}


def _mark_tab():
    return None


def _target_id(target):
    return (target.get("targetId") or target.get("target_id")) if isinstance(target, dict) else target


def activate_tab(target):
    target_id = _target_id(target)
    cdp("Target.activateTarget", targetId=target_id)
    return target_id


def switch_tab(target, activate=False):
    target_id = _target_id(target)
    if activate:
        activate_tab(target_id)
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    _send({"meta": "set_session", "session_id": sid, "target_id": target_id})
    _mark_tab()
    return sid


def new_tab(url="about:blank"):
    tid = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    switch_tab(tid)
    if url != "about:blank":
        goto_url(url)
    return tid


def close_tab(target=None):
    target_id = _target_id(target)
    if target_id is None:
        target_id = current_tab()["targetId"]
    cdp("Target.closeTarget", targetId=target_id)


def wait(seconds=1.0):
    time.sleep(seconds)


def wait_for_load(timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js("document.readyState") == "complete":
            return True
        time.sleep(0.3)
    return False


def upload_file(selector, path):
    doc = cdp("DOM.getDocument", depth=-1)
    nid = cdp("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector=selector)["nodeId"]
    if not nid:
        raise RuntimeError(f"no element for {selector}")
    cdp("DOM.setFileInputFiles", files=[path] if isinstance(path, str) else list(path), nodeId=nid)
'''


def helper_namespace(send: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Return a fresh globals dict exposing Browser Harness helpers bound to `send`."""

    namespace: dict[str, Any] = {"__name__": "__main__", "_send": send}
    exec(compile(_HELPERS_SOURCE, "<ego_harness_helpers>", "exec"), namespace)
    return namespace


# --- real transport ----------------------------------------------------------
class BridgeTransport:
    """Start ego_bridge.mjs under `ego-browser nodejs` and talk JSON lines over loopback TCP."""

    def __init__(self, space: str = SPACE_NAME, startup_timeout: float = 30.0, call_timeout: float = 120.0):
        executable = shutil.which("ego-browser")
        if not executable:
            raise FileNotFoundError("ego-browser CLI가 없다.")
        ensure_ego_running()
        self.workdir = Path(tempfile.mkdtemp(prefix="newspick-ego-"))
        port_file = self.workdir / "bridge.port"
        entry = self.workdir / "entry.mjs"
        config = {"space": space, "portFile": port_file.as_posix()}
        profile_id = ego_profile_id()
        if profile_id:
            config["profileId"] = profile_id
        entry.write_text(
            f"import {{ serve }} from {json.dumps(BRIDGE_PATH.as_uri())};\nawait serve({json.dumps(config)});\n",
            encoding="utf-8",
        )
        # ego nodejs는 셸 환경변수를 상속하지 않으므로 설정은 entry 파일에 넣고, 진입 인자는 ASCII 한 줄만 쓴다.
        self.process = subprocess.Popen(
            [executable, "nodejs", "-e", f"await import('{entry.as_uri()}')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.time() + startup_timeout
        while not port_file.exists():
            if self.process.poll() is not None:
                err = (self.process.stderr.read() or b"").decode("utf-8", "replace")
                raise RuntimeError(f"ego bridge가 시작 전에 종료됐다: {err[:800]}")
            if time.time() > deadline:
                self.close()
                raise TimeoutError("ego bridge 시작 시간 초과")
            time.sleep(0.05)
        time.sleep(0.05)
        port = int(port_file.read_text(encoding="utf-8").strip())
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=call_timeout)
        self.reader = self.sock.makefile("r", encoding="utf-8")
        self._next_id = 0
        record_ego_session(self, space)

    def call(self, op: dict[str, Any]) -> Any:
        self._next_id += 1
        payload = {**op, "id": self._next_id}
        self.sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        line = self.reader.readline()
        if not line:
            raise RuntimeError("ego bridge 연결이 끊겼다")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "ego bridge error"))
        return response.get("result")

    def close(self) -> None:
        try:
            if getattr(self, "sock", None):
                try:
                    self.call({"op": "exit"})
                except Exception:
                    pass
                self.sock.close()
        finally:
            if self.process.poll() is None:
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            shutil.rmtree(self.workdir, ignore_errors=True)


def execute(script: Path, start_url: str = DEFAULT_START_URL) -> None:
    """Execute one helper script in-process against ego lite."""

    transport = BridgeTransport()
    try:
        session = EgoSession(transport, start_url=start_url)
        namespace = helper_namespace(session.send)
        # guard를 따로 실행해 helper traceback의 줄 번호가 원본 파일과 같게 한다.
        exec(compile(EGO_RUNTIME_GUARD, "<ego_runtime_guard>", "exec"), namespace)
        exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), namespace)
    finally:
        transport.close()


def helper_python(environment: dict[str, str] | None = None) -> str:
    """helper를 돌릴 python. private API helper가 쓰는 instagrapi private-venv(3.12)와 버전을 맞춘다."""

    source = os.environ if environment is None else environment
    override = str(source.get("NEWS_PICK_HELPER_PYTHON") or "").strip()
    if override:
        return override
    output_root = Path(source.get("NEWS_PICK_OUTPUT_ROOT") or Path(__file__).resolve().parents[4] / "output")
    scripts = "Scripts" if os.name == "nt" else "bin"
    candidate = output_root / "publish-news-pick" / "private-venv" / scripts / ("python.exe" if os.name == "nt" else "python")
    return str(candidate) if candidate.is_file() else sys.executable


def run_script(
    script: Path,
    *,
    capture_output: bool = False,
    timeout: float | None = None,
    extra_env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    """Same contract as edge_browser.run_script: one helper script in one child process."""

    script = script.expanduser().resolve()
    if not script.is_file():
        raise FileNotFoundError(f"ego harness script가 없다: {script}")
    env = dict(os.environ)
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    env.update({"NEWS_PICK_BROWSER": "ego", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    return subprocess.run(
        [helper_python(env), str(Path(__file__).resolve()), str(script)],
        capture_output=capture_output,
        env=env,
        timeout=timeout,
        check=check,
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: ego_harness.py <helper-script.py>", file=sys.stderr)
        return 2
    account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@") or "newspick_studio"
    execute(Path(args[0]).resolve(), start_url=f"https://www.instagram.com/{account}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
