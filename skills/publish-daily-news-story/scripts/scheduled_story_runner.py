#!/usr/bin/env python3
"""Run the verified three-cover daily Instagram Story at 21:00 KST."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
STORY_TIME = time(21, 0)
MAX_START_LATENESS = timedelta(minutes=30)
STALE_LOCK_AGE = timedelta(hours=2)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_account(value: str) -> str:
    account = value.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9._]+", account):
        raise ValueError("Instagram account 형식이 올바르지 않다.")
    return account


def story_at(target_date: date) -> datetime:
    return datetime.combine(target_date, STORY_TIME, tzinfo=KST)


def within_start_window(target: datetime, now: datetime) -> bool:
    return target <= now <= target + MAX_START_LATENESS


def workspace_settings(
    root: Path,
    output_override: Path | None = None,
    account_override: str | None = None,
) -> dict[str, Any]:
    config_path = root / "output" / "workspace.json"
    config = load_json(config_path) if config_path.is_file() else {}
    output_root = (
        output_override or Path(config.get("output_root", root / "output"))
    ).expanduser().resolve()
    skills_root = (root / "skills").resolve()
    try:
        output_root.relative_to(skills_root)
    except ValueError:
        pass
    else:
        raise ValueError("NEWS_PICK_OUTPUT_ROOT는 skills 폴더 밖이어야 한다.")
    return {
        "output_root": output_root,
        "account": validate_account(
            account_override or config.get("account", "newspick_studio")
        ),
    }


def dependency_paths(root: Path, output_root: Path) -> dict[str, str]:
    runner = (
        root
        / "skills"
        / "publish-daily-news-story"
        / "scripts"
        / "run_daily_story.py"
    )
    private_site_packages = (
        output_root
        / "publish-news-pick"
        / "private-venv"
        / "Lib"
        / "site-packages"
    )
    dependencies = {
        "story_runner": str(runner.resolve()) if runner.is_file() else "",
        "ffmpeg": shutil.which("ffmpeg") or "",
        "ffprobe": shutil.which("ffprobe") or "",
        "browser_harness": shutil.which("browser-harness") or "",
        "private_site_packages": (
            str(private_site_packages.resolve()) if private_site_packages.is_dir() else ""
        ),
    }
    missing = [name for name, value in dependencies.items() if not value]
    if missing:
        raise FileNotFoundError(
            "21시 Story 예약 실행 의존성이 없다: " + ", ".join(missing)
        )
    return dependencies


def story_command(
    root: Path, target_date: date, settings: dict[str, Any]
) -> list[str]:
    runner = (
        root
        / "skills"
        / "publish-daily-news-story"
        / "scripts"
        / "run_daily_story.py"
    )
    return [
        sys.executable,
        str(runner),
        "--output-root",
        str(settings["output_root"]),
        "--date",
        target_date.isoformat(),
        "--account",
        settings["account"],
        "--publish",
    ]


@contextmanager
def exclusive_lock(path: Path, now: datetime) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        age = now - datetime.fromtimestamp(path.stat().st_mtime, tz=KST)
        if age > STALE_LOCK_AGE:
            stale = path.with_name(
                f"{path.name}.stale-{now.strftime('%Y%m%d-%H%M%S')}"
            )
            os.replace(path, stale)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("다른 일일 Story 예약 실행이 진행 중이다.") from exc
    try:
        os.write(
            descriptor,
            f"pid={os.getpid()}\nstarted_at={now.isoformat()}\n".encode(),
        )
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)


def published_result(payload: dict[str, Any]) -> bool:
    publish = (payload.get("result") or {}).get("publish") or {}
    return bool(
        payload.get("ok") is True
        and publish.get("status") == "published"
        and publish.get("public_verified") is True
    )


def run_job(
    root: Path,
    target: datetime,
    settings: dict[str, Any],
    now: datetime,
    dry_run: bool = False,
) -> tuple[int, dict[str, Any]]:
    output_root: Path = settings["output_root"]
    dependencies = dependency_paths(root, output_root)
    slot_id = target.strftime("%Y-%m-%d-2100")
    scheduler_root = output_root / "scheduler" / "daily-story"
    state_path = scheduler_root / "editions" / f"{slot_id}.json"
    command = story_command(root, target.date(), settings)
    if dry_run:
        return 0, {
            "status": "dry_run",
            "slot_id": slot_id,
            "scheduled_at": target.isoformat(),
            "command": command,
            "settings": {**settings, "output_root": str(output_root)},
            "dependencies": dependencies,
        }
    if state_path.exists():
        previous = load_json(state_path)
        return 0, {
            "status": "duplicate_suppressed",
            "slot_id": slot_id,
            "previous_status": previous.get("status"),
            "state_path": str(state_path),
        }
    if not within_start_window(target, now):
        skipped = {
            "schema_version": "1.0",
            "slot_id": slot_id,
            "scheduled_at": target.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "status": "skipped",
            "reason": "outside_start_window",
        }
        atomic_json(state_path, skipped)
        return 0, skipped

    log_root = output_root / "logs" / "scheduler" / "daily-story"
    stdout_path = log_root / f"{slot_id}.stdout.log"
    stderr_path = log_root / f"{slot_id}.stderr.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    started = {
        "schema_version": "1.0",
        "slot_id": slot_id,
        "scheduled_at": target.isoformat(),
        "started_at": now.isoformat(),
        "status": "running",
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "NEWS_PICK_OUTPUT_ROOT": str(output_root),
            "IG_ACCOUNT": settings["account"],
            "NEWS_PICK_DAILY_STORY_SCHEDULED_MODE": "1",
        }
    )
    with exclusive_lock(scheduler_root / "daily-story.lock", now):
        atomic_json(state_path, started)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    try:
        response = json.loads(completed.stdout) if completed.stdout else None
    except json.JSONDecodeError:
        response = None
    publish = ((response or {}).get("result") or {}).get("publish") or {}
    if published_result(response or {}) and completed.returncode == 0:
        status = "published"
    elif publish.get("submission_started") is True:
        status = "needs_review"
    else:
        status = "failed_pre_submit"
    ended = {
        **started,
        "completed_at": datetime.now(KST).isoformat(),
        "status": status,
        "exit_code": completed.returncode,
        "final_result": response,
    }
    atomic_json(state_path, ended)
    return (0 if status == "published" else 2), ended


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--account")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        root = project_root()
        now = datetime.now(KST)
        target = story_at(args.date or now.date())
        settings = workspace_settings(root, args.output_root, args.account)
        exit_code, result = run_job(root, target, settings, now, args.dry_run)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"ok": exit_code == 0, "result": result},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
