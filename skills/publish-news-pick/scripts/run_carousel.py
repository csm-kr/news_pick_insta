#!/usr/bin/env python3
"""Run a private carousel worker through Browser Harness without exposing sessionid."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import carousel_queue

TASK = Path(__file__).with_name("private_carousel_task.py")
PREFIX = "INSTAGRAM_PRIVATE_CAROUSEL_RESULT="


def venv_python() -> Path:
    root = carousel_queue.LOCAL_ROOT / "private-venv"
    return root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def site_packages() -> Path:
    python = venv_python()
    if not python.is_file():
        raise FileNotFoundError("project-local backend가 없다. setup_backend.py를 실행한다.")
    probe = subprocess.run(
        [str(python), "-c", "import json,sysconfig;print(json.dumps(sysconfig.get_paths()['purelib'], ensure_ascii=True))"],
        capture_output=True,
        text=True,
        encoding="ascii",
        timeout=20,
        check=True,
    )
    path = Path(json.loads(probe.stdout)).resolve()
    if not path.is_dir():
        raise FileNotFoundError("private backend site-packages를 찾을 수 없다.")
    return path


def fallback(message, started=False):
    return {"ok": False, "confirmed": False, "submission_started": started, "backend": "private_carousel", "error": str(message)[:2000]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--job", type=Path)
    mode.add_argument("--probe-account")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = carousel_queue.read_config(args.config)
        if config["connection_mode"] == "cdp_endpoint":
            carousel_queue.probe_endpoint(config["endpoint"])
        packages = site_packages()
        if args.job:
            job_path = args.job.resolve()
            job = json.loads(job_path.read_text(encoding="utf-8"))
            carousel_queue.validate_job(job, job_path)
            if job.get("status") != "submitting":
                raise ValueError("worker는 submitting job만 받는다.")
            account = job["account"]
        else:
            job_path = None
            account = carousel_queue.normalize_account(args.probe_account)
        harness = shutil.which("browser-harness")
        if not harness:
            raise FileNotFoundError("browser-harness CLI가 없다.")
    except Exception as exc:
        print(PREFIX + json.dumps(fallback(exc), ensure_ascii=False))
        return 2
    env = dict(os.environ)
    env.update({"BH_AGENT_WORKSPACE": str((carousel_queue.LOCAL_ROOT / "browser-harness").resolve()), "BH_DOMAIN_SKILLS": "0", "BH_RECORD": "0", "CAROUSEL_ACCOUNT": account, "CAROUSEL_PRIVATE_MODE": "publish" if job_path else "probe", "CAROUSEL_PRIVATE_SITE_PACKAGES": str(packages), "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if config["connection_mode"] == "cdp_endpoint":
        env["BU_NAME"] = "instagram-private-carousel-publisher"
        env["BU_CDP_URL"] = config["endpoint"]
    else:
        env.pop("BU_NAME", None)
        env.pop("BU_CDP_URL", None)
        env["CAROUSEL_EXPECTED_PROFILE_SUFFIX"] = config["expected_profile_suffix"]
    if job_path:
        env["CAROUSEL_JOB"] = str(job_path)
    try:
        if config["connection_mode"] == "cdp_endpoint":
            subprocess.run([harness, "--reload"], capture_output=True, text=True, env=env, timeout=20, check=True)
        result = subprocess.run([harness], input=TASK.read_text(encoding="utf-8"), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=540)
        if result.stdout: print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr: print(result.stderr, file=sys.stderr)
        if not any(line.startswith(PREFIX) for line in result.stdout.splitlines()):
            print(PREFIX + json.dumps(fallback("Browser Harness 결과가 없다.", None), ensure_ascii=False))
            return result.returncode or 1
        return result.returncode
    except subprocess.TimeoutExpired as exc:
        print(PREFIX + json.dumps(fallback(f"publisher timeout after {exc.timeout}s", None), ensure_ascii=False))
        return 124
    except subprocess.SubprocessError as exc:
        print(PREFIX + json.dumps(fallback(exc), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
