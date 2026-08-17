#!/usr/bin/env python3
"""Install the approved private carousel backend in a project-local venv."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = Path(os.environ.get("NEWS_PICK_OUTPUT_ROOT") or (Path.cwd() / "output")).expanduser().resolve()
try:
    OUTPUT_ROOT.relative_to(Path(__file__).resolve().parents[2])
except ValueError:
    pass
else:
    raise ValueError("NEWS_PICK_OUTPUT_ROOT는 설치된 skills 폴더 밖에 있어야 한다.")
RUNTIME_ROOT = Path(os.environ.get("NEWS_PICK_PUBLISH_ROOT") or (OUTPUT_ROOT / "publish-news-pick")).expanduser().resolve()
VENV = RUNTIME_ROOT / "private-venv"
REQUIREMENTS = ROOT / "requirements.txt"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def version(executable: Path) -> tuple[int, int] | None:
    if not executable.is_file():
        return None
    try:
        probe = subprocess.run([str(executable), "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"], capture_output=True, text=True, timeout=20, check=True)
        major, minor = probe.stdout.strip().split(".")
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def browser_harness_python() -> Path:
    uv = shutil.which("uv")
    if uv:
        try:
            probe = subprocess.run([uv, "tool", "dir"], capture_output=True, text=True, timeout=20, check=True)
            tools = Path(probe.stdout.strip())
            candidate = tools / "browser-harness" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            if version(candidate) and version(candidate) >= (3, 10):
                return candidate
        except (OSError, subprocess.SubprocessError):
            pass
    return Path(sys.executable)


def main() -> int:
    python = venv_python()
    uv = shutil.which("uv")
    selected = browser_harness_python()
    VENV.parent.mkdir(parents=True, exist_ok=True)
    if uv:
        if version(python) != version(selected):
            subprocess.run([uv, "venv", "--clear", str(VENV), "--python", str(selected)], check=True)
        subprocess.run([uv, "pip", "install", "--python", str(python), "--requirement", str(REQUIREMENTS)], check=True)
    else:
        if version(python) != version(selected):
            subprocess.run([str(selected), "-m", "venv", "--clear", str(VENV)], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True)
    probe = subprocess.run([str(python), "-c", "import importlib.metadata,json,sysconfig;print(json.dumps({'version':importlib.metadata.version('instagrapi'),'site_packages':sysconfig.get_paths()['purelib']}))"], capture_output=True, text=True, encoding="utf-8", check=True)
    result = json.loads(probe.stdout)
    print(json.dumps({"ok": True, "venv": str(VENV.resolve()), "python": str(python.resolve()), "python_version": ".".join(map(str, version(python) or ())), "matched_browser_harness_python": str(selected.resolve()), "instagrapi": result["version"], "site_packages": result["site_packages"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
