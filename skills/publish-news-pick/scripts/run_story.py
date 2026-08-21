#!/usr/bin/env python3
"""Run the approved private Story worker without exposing browser cookies."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import carousel_queue
import private_story_task


TASK = Path(__file__).with_name("private_story_task.py")
PREFIX = private_story_task.PREFIX


def site_packages() -> Path:
    root = carousel_queue.LOCAL_ROOT / "private-venv"
    path = root / ("Lib/site-packages" if sys.platform == "win32" else "lib")
    if sys.platform != "win32":
        matches = sorted(path.glob("python*/site-packages"))
        path = matches[0] if matches else path
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError("project-local private backend is not installed")
    return path


def parse_result(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(PREFIX):
            return json.loads(line[len(PREFIX) :])
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe-account")
    mode.add_argument("--media", type=Path)
    parser.add_argument("--account")
    parser.add_argument("--sha256")
    parser.add_argument("--resize-mode", choices=("fit", "fill"), default="fit")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()

    try:
        if args.probe_account:
            account = carousel_queue.normalize_account(args.probe_account)
            private_mode = "probe"
            media = None
        else:
            account = carousel_queue.normalize_account(args.account)
            if not args.sha256:
                raise ValueError("--sha256 is required for Story publishing")
            media = private_story_task.validate_story_media(args.media, args.sha256)
            private_mode = "publish"
        packages = site_packages()
        harness = shutil.which("browser-harness")
        if not harness:
            raise FileNotFoundError("browser-harness CLI was not found")
    except Exception as exc:
        print(PREFIX + json.dumps({"ok": False, "confirmed": False, "submission_started": False, "error": str(exc)[:2000]}, ensure_ascii=True))
        return 2

    env = dict(os.environ)
    env.update(
        {
            "BH_DOMAIN_SKILLS": "0",
            "BH_RECORD": "0",
            "STORY_ACCOUNT": account,
            "STORY_PRIVATE_MODE": private_mode,
            "STORY_PRIVATE_SITE_PACKAGES": str(packages),
            "STORY_RESIZE_MODE": args.resize_mode,
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    if media is not None:
        env["STORY_MEDIA"] = str(media)
        env["STORY_MEDIA_SHA256"] = args.sha256.lower()

    try:
        process = subprocess.run(
            [harness],
            input=TASK.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        print(PREFIX + json.dumps({"ok": False, "confirmed": False, "submission_started": None, "error": f"Story worker timeout after {exc.timeout}s"}, ensure_ascii=True))
        return 124

    if process.stdout:
        print(process.stdout, end="" if process.stdout.endswith("\n") else "\n")
    if process.stderr:
        print(process.stderr, file=sys.stderr)
    result = parse_result(process.stdout)
    if result is None:
        print(PREFIX + json.dumps({"ok": False, "confirmed": False, "submission_started": None, "error": "Browser Harness Story result was missing"}, ensure_ascii=True))
        return process.returncode or 1
    if args.result:
        carousel_queue.atomic_json(args.result.resolve(), result)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
