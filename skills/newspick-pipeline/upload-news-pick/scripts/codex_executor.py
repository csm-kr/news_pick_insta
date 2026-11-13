"""Native Codex CLI discovery and structured unattended execution contracts."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def codex_candidates() -> list[Path]:
    configured = os.environ.get("CODEX_EXECUTABLE")
    candidates = [Path(configured).expanduser()] if configured else []
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        npm = Path(os.environ["APPDATA"]) / "npm/node_modules/@openai/codex/node_modules"
        candidates.extend(sorted(npm.glob("@openai/codex-*/vendor/*/bin/codex.exe"), reverse=True))
    for name in ("codex.exe", "codex"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "OpenAI/Codex/bin/codex.exe")
    return candidates


def supports_exec(candidate: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(candidate), "--no-daemon", "exec", "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, check=False, creationflags=NO_WINDOW_FLAGS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = completed.stdout or ""
    return completed.returncode == 0 and all(
        flag in output for flag in ("--approve-for-me", "--output-schema", "--json")
    )


def find_codex() -> Path:
    checked: set[Path] = set()
    for candidate in codex_candidates():
        if not candidate.is_file() or candidate.suffix.lower() in {".cmd", ".ps1", ".bat"}:
            continue
        resolved = candidate.resolve()
        if resolved in checked:
            continue
        checked.add(resolved)
        if supports_exec(resolved):
            return resolved
    raise FileNotFoundError("구조화 exec를 지원하는 네이티브 Codex CLI를 찾을 수 없다. CODEX_EXECUTABLE을 확인한다.")


def build_command(
    codex_path: Path, root: Path, schema_path: Path, result_path: Path,
    output_root: Path,
) -> list[str]:
    command = [
        str(codex_path), "--no-daemon", "exec", "--ephemeral", "--json",
        "--approve-for-me", "--cd", str(root),
        "--output-schema", str(schema_path), "--output-last-message", str(result_path),
    ]
    model = (os.environ.get("NEWS_PICK_CODEX_MODEL") or "").strip()
    effort = (os.environ.get("NEWS_PICK_CODEX_EFFORT") or "").strip().lower()
    if model:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", model):
            raise ValueError("NEWS_PICK_CODEX_MODEL 형식이 올바르지 않다.")
        command.extend(["--model", model])
    if effort:
        if effort not in {"low", "medium", "high", "xhigh", "max", "ultra"}:
            raise ValueError("NEWS_PICK_CODEX_EFFORT 값이 올바르지 않다.")
        command.extend(["-c", f'model_reasoning_effort="{effort}"'])
    try:
        output_root.resolve().relative_to(root.resolve())
    except ValueError:
        command.extend(["--add-dir", str(output_root)])
    command.append("-")
    return command


def parse_stream_result(event_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Read Codex JSONL metadata; the output-schema result file remains authoritative."""
    meta: dict[str, Any] = {"thread_id": None, "is_error": False, "error": None, "usage": None}
    if event_path.is_file():
        for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "thread.started":
                meta["thread_id"] = event.get("thread_id")
            elif event.get("type") == "turn.completed":
                meta["usage"] = event.get("usage")
            elif event.get("type") in {"turn.failed", "error"}:
                meta["is_error"] = True
                error = event.get("error") or event.get("message")
                meta["error"] = error.get("message") if isinstance(error, dict) else str(error or "Codex execution failed")
    return None, meta


def read_result(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
