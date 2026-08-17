#!/usr/bin/env python3
"""Open a visible Instagram tab in a user-selected Chrome profile."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def chrome_candidates() -> list[Path]:
    configured = os.environ.get("CHROME_EXECUTABLE")
    values = [Path(configured).expanduser()] if configured else []
    discovered = shutil.which("chrome") or shutil.which("chrome.exe") or shutil.which("google-chrome") or shutil.which("chromium")
    if discovered:
        values.append(Path(discovered))
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                values.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        values.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        values.extend([Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium"), Path("/usr/bin/chromium-browser")])
    return values


def find_chrome() -> Path:
    for candidate in chrome_candidates():
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Chrome을 찾을 수 없다. CHROME_EXECUTABLE을 설정한다.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=os.environ.get("NEWS_PICK_CHROME_PROFILE", "Profile 3"))
    parser.add_argument("--account", default=os.environ.get("IG_ACCOUNT", "newspick_studio"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    profile = args.profile.strip()
    account = args.account.strip().lstrip("@").lower()
    if not profile or any(value in profile for value in ("/", "\\")):
        raise ValueError("profile에는 Chrome profile 폴더명만 사용한다.")
    if not re.fullmatch(r"[a-z0-9._]+", account):
        raise ValueError("Instagram account 형식이 올바르지 않다.")
    chrome = find_chrome()
    command = [str(chrome), f"--profile-directory={profile}", f"https://www.instagram.com/{account}/"]
    if not args.dry_run:
        subprocess.Popen(command)
    print(json.dumps({"ok": True, "chrome": str(chrome), "profile": profile, "account": account, "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
