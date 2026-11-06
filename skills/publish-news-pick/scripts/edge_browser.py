#!/usr/bin/env python3
"""News Pick browser entry point.

2026-11-06부터 뉴스픽은 Microsoft Edge를 쓰지 않고 ego lite만 쓴다. 이 모듈 이름은
여러 스크립트가 import하고 있어 그대로 두었고, 모든 helper 실행은 `ego_harness`로 간다.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


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


def selected_browser(environment: Mapping[str, str] | None = None) -> str:
    """뉴스픽 브라우저는 ego lite 하나다. 다른 값이 들어오면 브라우저를 건드리기 전에 실패한다."""

    source = os.environ if environment is None else environment
    value = str(source.get("NEWS_PICK_BROWSER") or "ego").strip()
    if value != "ego":
        raise ValueError(f"NEWS_PICK_BROWSER는 'ego'만 허용한다: {value!r}")
    return value


def run_script(
    script: Path,
    *,
    capture_output: bool = False,
    timeout: float | None = None,
    extra_env: Mapping[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    """Run one bounded browser phase (one helper script) on ego lite."""

    script = script.expanduser().resolve()
    if not script.is_file():
        raise FileNotFoundError(f"browser helper script가 없다: {script}")
    selected_browser()
    import ego_harness

    return ego_harness.run_script(script, capture_output=capture_output, timeout=timeout, extra_env=extra_env, check=check)


def decode_output(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")
