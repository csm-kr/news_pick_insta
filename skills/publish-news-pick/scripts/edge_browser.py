#!/usr/bin/env python3
"""Strict Microsoft Edge connection helpers for News Pick Browser Harness runs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


EDGE_CONNECTION_NAME = "edge9333"
EDGE_CDP_URL = "http://127.0.0.1:9333"
EDGE_CDP_PORT = 9333
EDGE_PROFILE_NAME = "Default"
EDGE_RUNTIME_GUARD = b'''_news_pick_product = str(cdp("Browser.getVersion").get("product") or "")\nif not (_news_pick_product.lower().startswith("edg/") or _news_pick_product.lower().startswith("microsoftedge/")):\n    raise RuntimeError("News Pick Browser Harness target is not Microsoft Edge: " + _news_pick_product)\n'''


def canonical_instagram_post_url(value: str) -> tuple[str, str]:
    """Return (canonical URL, shortcode) for canonical or account-scoped post links."""

    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {
        "instagram.com",
        "www.instagram.com",
    }:
        raise ValueError("Instagram https 게시물 URL이 아니다.")
    match = re.fullmatch(r"/(?:[A-Za-z0-9._]+/)?p/([A-Za-z0-9_-]+)/?", parsed.path)
    if not match:
        raise ValueError("Instagram 사진 게시물 permalink 형식이 아니다.")
    shortcode = match.group(1)
    return f"https://www.instagram.com/p/{shortcode}/", shortcode


def default_edge_user_data_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "NewsPick" / "EdgeProfile"
    return Path.home() / ".newspick" / "edge-profile"


def _require_fixed(value: str | None, expected: str, label: str) -> str:
    selected = str(value or expected).strip()
    if selected != expected:
        raise ValueError(f"{label}는 뉴스픽 고정값 {expected!r}만 허용한다.")
    return selected


def connection_settings(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environment is None else environment
    for key in ("NEWS_PICK_BROWSER_HARNESS_NAME", "BU_NAME"):
        if source.get(key):
            _require_fixed(source[key], EDGE_CONNECTION_NAME, key)
    for key in ("NEWS_PICK_EDGE_CDP_URL", "BU_CDP_URL"):
        if source.get(key):
            _require_fixed(source[key], EDGE_CDP_URL, key)
    if source.get("NEWS_PICK_BROWSER"):
        _require_fixed(source["NEWS_PICK_BROWSER"], "edge", "NEWS_PICK_BROWSER")
    name = EDGE_CONNECTION_NAME
    endpoint = EDGE_CDP_URL
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != EDGE_CDP_PORT:
        raise ValueError("뉴스픽 Edge CDP는 credential 없는 127.0.0.1:9333만 허용한다.")
    return {"name": name, "endpoint": endpoint}


def probe_edge_endpoint(endpoint: str = EDGE_CDP_URL, timeout: float = 2.0) -> dict[str, str]:
    endpoint = _require_fixed(endpoint, EDGE_CDP_URL, "Edge CDP URL")
    with urllib.request.urlopen(endpoint + "/json/version", timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    product = str(value.get("Browser") or "")
    websocket = str(value.get("webSocketDebuggerUrl") or "")
    if not websocket or not re.match(r"^(Edg|MicrosoftEdge)/", product, re.IGNORECASE):
        raise ValueError(f"127.0.0.1:9333의 브라우저가 Microsoft Edge가 아니다: {product or 'unknown'}")
    return {
        "browser": product,
        "protocol_version": str(value.get("Protocol-Version") or ""),
        "websocket_debugger_url": websocket,
    }


def browser_harness_environment(
    base: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    settings = connection_settings(env)
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
        connection_settings(env)
    env.update(
        {
            "BU_NAME": settings["name"],
            "BU_CDP_URL": settings["endpoint"],
            "NEWS_PICK_BROWSER": "edge",
            "NEWS_PICK_BROWSER_HARNESS_NAME": settings["name"],
            "NEWS_PICK_EDGE_CDP_URL": settings["endpoint"],
            "BH_DOMAIN_SKILLS": "0",
            "BH_RECORD": "0",
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def run_script(
    script: Path,
    *,
    capture_output: bool = False,
    timeout: float | None = None,
    extra_env: Mapping[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    """Run one bounded browser phase in one Harness process using exact source bytes."""

    script = script.expanduser().resolve()
    if not script.is_file():
        raise FileNotFoundError(f"Browser Harness script가 없다: {script}")
    harness = shutil.which("browser-harness")
    if not harness:
        raise FileNotFoundError("browser-harness CLI가 없다.")
    settings = connection_settings()
    probe_edge_endpoint(settings["endpoint"])
    source = EDGE_RUNTIME_GUARD + script.read_bytes()
    return subprocess.run(
        [harness],
        input=source,
        capture_output=capture_output,
        env=browser_harness_environment(extra=extra_env),
        timeout=timeout,
        check=check,
    )


def decode_output(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")
