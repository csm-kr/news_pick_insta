#!/usr/bin/env python3
"""Open the fixed visible News Pick Microsoft Edge profile with loopback CDP."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import edge_browser


def edge_candidates() -> list[Path]:
    configured = os.environ.get("EDGE_EXECUTABLE")
    values = [Path(configured).expanduser()] if configured else []
    discovered = shutil.which("msedge") or shutil.which("msedge.exe") or shutil.which("microsoft-edge")
    if discovered:
        values.append(Path(discovered))
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if base:
                values.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    elif sys.platform == "darwin":
        values.append(Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"))
    else:
        values.extend([Path("/usr/bin/microsoft-edge"), Path("/usr/bin/microsoft-edge-stable")])
    return values


def find_edge() -> Path:
    for candidate in edge_candidates():
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Microsoft Edge를 찾을 수 없다. EDGE_EXECUTABLE을 설정한다.")


def launch_command(edge: Path, account: str, user_data_dir: Path) -> list[str]:
    return [
        str(edge),
        f"--remote-debugging-port={edge_browser.EDGE_CDP_PORT}",
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={edge_browser.EDGE_PROFILE_NAME}",
        "--no-first-run",
        "--disable-default-apps",
        f"https://www.instagram.com/{account}/",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default=os.environ.get("IG_ACCOUNT", "newspick_studio"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    account = args.account.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9._]+", account):
        raise ValueError("Instagram account 형식이 올바르지 않다.")
    edge = find_edge()
    user_data_dir = edge_browser.default_edge_user_data_dir().resolve()
    command = launch_command(edge, account, user_data_dir)
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "edge": str(edge), "user_data_dir": str(user_data_dir), "command": command}, ensure_ascii=False))
        return 0

    try:
        probe = edge_browser.probe_edge_endpoint()
        reused = True
    except OSError:
        user_data_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(command)
        reused = False
        deadline = time.monotonic() + 15
        while True:
            try:
                probe = edge_browser.probe_edge_endpoint(timeout=1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Edge CDP가 15초 안에 준비되지 않았다.")
                time.sleep(0.25)
    print(
        json.dumps(
            {
                "ok": True,
                "reused": reused,
                "edge": str(edge),
                "user_data_dir": str(user_data_dir),
                "connection_name": edge_browser.EDGE_CONNECTION_NAME,
                "cdp_url": edge_browser.EDGE_CDP_URL,
                "browser": probe["browser"],
                "protocol_version": probe["protocol_version"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
