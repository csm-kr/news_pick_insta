#!/usr/bin/env python3
"""Initialize a portable news-pick workspace or install all bundled skills."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_SKILLS = REPO_ROOT / "skills"
SKILL_NAMES = (
    "search-news",
    "plan-news-pick",
    "create-news-cards",
    "publish-news-pick",
    "publish-daily-news-story",
    "upload-news-pick",
)
OUTPUT_DIRS = ("runs", "publish-news-pick", "daily-story", "profile-candidates", "cache", "logs")


def default_skills_dir() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    return codex_home / "skills"


def validate_account(value: str) -> str:
    account = value.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9._]+", account):
        raise ValueError("Instagram account 형식이 올바르지 않다.")
    return account


def initialize(workspace: Path, output_dir: str, account: str, profile: str) -> dict:
    workspace = workspace.expanduser().resolve()
    if Path(output_dir).is_absolute() or ".." in Path(output_dir).parts:
        raise ValueError("--output-dir은 workspace 내부 상대경로여야 한다.")
    output_root = (workspace / output_dir).resolve()
    output_root.relative_to(workspace)
    try:
        output_root.relative_to(SOURCE_SKILLS.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("output은 skills 폴더 밖에 있어야 한다.")
    account = validate_account(account)
    if not profile.strip() or any(value in profile for value in ("/", "\\")):
        raise ValueError("Chrome profile에는 폴더명만 사용한다.")
    output_root.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_DIRS:
        (output_root / name).mkdir(exist_ok=True)
    config = {
        "schema_version": "1.0",
        "workspace": str(workspace),
        "output_root": str(output_root),
        "account": account,
        "chrome_profile": profile.strip(),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contains_secrets": False,
    }
    (output_root / "workspace.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        **config,
        "environment": {
            "NEWS_PICK_OUTPUT_ROOT": str(output_root),
            "IG_ACCOUNT": account,
            "NEWS_PICK_CHROME_PROFILE": profile.strip(),
        },
    }


def install(skills_dir: Path) -> dict:
    skills_dir = skills_dir.expanduser().resolve()
    missing = [name for name in SKILL_NAMES if not (SOURCE_SKILLS / name / "SKILL.md").is_file()]
    if missing:
        raise FileNotFoundError(f"source skill이 없다: {missing}")
    conflicts = [name for name in SKILL_NAMES if (skills_dir / name).exists()]
    if conflicts:
        raise FileExistsError(f"기존 skill을 덮어쓰지 않는다: {conflicts}")
    skills_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    for name in SKILL_NAMES:
        target = skills_dir / name
        shutil.copytree(
            SOURCE_SKILLS / name,
            target,
            ignore=shutil.ignore_patterns(".local", "__pycache__", "*.pyc", "*.pyo"),
        )
        installed.append(str(target))
    return {"skills_dir": str(skills_dir), "installed": installed}


def dependency_status() -> dict:
    tibo_names = [
        Path(os.environ["GOD_TIBO_SKILL_ROOT"]).expanduser() if os.environ.get("GOD_TIBO_SKILL_ROOT") else None,
        default_skills_dir() / "god-tibo-gpt-image2-skill",
        Path.home() / ".agents" / "skills" / "god-tibo-gpt-image2-skill",
    ]
    tibo = next((path for path in tibo_names if path and (path / "scripts" / "tibo-batch.mjs").is_file()), None)
    status = {
        "python": {"ok": sys.version_info >= (3, 10), "version": ".".join(map(str, sys.version_info[:3]))},
        "pillow": {"ok": importlib.util.find_spec("PIL") is not None},
        "node": {"ok": shutil.which("node") is not None, "path": shutil.which("node")},
        "ffmpeg": {"ok": shutil.which("ffmpeg") is not None, "path": shutil.which("ffmpeg")},
        "ffprobe": {"ok": shutil.which("ffprobe") is not None, "path": shutil.which("ffprobe")},
        "browser_harness": {"ok": shutil.which("browser-harness") is not None, "path": shutil.which("browser-harness")},
        "god_tibo": {"ok": tibo is not None, "path": str(tibo.resolve()) if tibo else None},
    }
    return {"ready": all(record["ok"] for record in status.values()), "dependencies": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--workspace", type=Path, default=Path.cwd())
    init.add_argument("--output-dir", default="output")
    init.add_argument("--account", default="newspick_studio")
    init.add_argument("--chrome-profile", default="Profile 3")
    installer = commands.add_parser("install")
    installer.add_argument("--skills-dir", type=Path, default=default_skills_dir())
    commands.add_parser("check")
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args.workspace, args.output_dir, args.account, args.chrome_profile)
        elif args.command == "install":
            result = install(args.skills_dir)
        else:
            result = dependency_status()
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
