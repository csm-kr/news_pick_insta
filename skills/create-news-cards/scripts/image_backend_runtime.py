from __future__ import annotations

import ast
import concurrent.futures
import json
import os
import re
import subprocess
from pathlib import Path


def configured_model(home: Path) -> str | None:
    config = home / "config.toml"
    if not config.is_file():
        return None
    for line in config.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            break
        match = re.match(r"^model\s*=\s*(.+?)\s*(?:#.*)?$", stripped)
        if match:
            try:
                value = ast.literal_eval(match.group(1))
            except (ValueError, SyntaxError) as error:
                raise ValueError("config.toml model을 읽을 수 없다. --imagegen-model을 명시한다.") from error
            if not isinstance(value, str):
                raise ValueError("config.toml model은 문자열이어야 한다.")
            return value
    return None


def resolve_runtime(auth_file=None, model=None, environment=None):
    child_env = dict(os.environ if environment is None else environment)
    home = Path(child_env.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    auth_source = "explicit_or_environment" if auth_file or child_env.get("CODEX_IMAGEGEN_AUTH_FILE") else "codex_home"
    auth_path = Path(auth_file or child_env.get("CODEX_IMAGEGEN_AUTH_FILE") or home / "auth.json").expanduser().resolve()
    if not auth_path.is_file():
        raise ValueError(f"인증 파일이 없다: {auth_path}. 실제 로그인 경로를 확인한다.")
    selected_model = model or child_env.get("CODEX_IMAGEGEN_MODEL") or child_env.get("CODEX_MODEL")
    model_source = "explicit_or_environment"
    if not selected_model:
        selected_model = configured_model(home)
        model_source = "codex_config"
    if not selected_model or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", selected_model):
        raise ValueError("지원 모델을 확인한 뒤 --imagegen-model을 명시한다. Tibo의 고정 기본 모델로 대체하지 않는다.")
    cache = home / "models_cache.json"
    cached_models = []
    if cache.is_file():
        cached_models = json.loads(cache.read_text(encoding="utf-8-sig")).get("models", [])
    listed_models = {item.get("slug") for item in cached_models if isinstance(item, dict)}
    if listed_models and selected_model not in listed_models:
        raise ValueError(f"모델 {selected_model!r}이 현재 로컬 지원 목록에 없다. Codex 모델 목록을 갱신·확인한다.")
    child_env["CODEX_IMAGEGEN_AUTH_FILE"] = str(auth_path)
    child_env["CODEX_IMAGEGEN_MODEL"] = selected_model
    report = {
        "codex_home": str(home),
        "auth_file": str(auth_path),
        "auth_file_source": auth_source,
        "model": selected_model,
        "model_source": model_source,
        "model_in_local_cache": selected_model in listed_models if listed_models else None,
        "credentials_recorded": False,
    }
    return child_env, report


def run_checked_batch(records, invoke, workers, dry_run=False):
    def checked_invoke(record):
        try:
            return invoke(record)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            return {**record, "ok": False, "error": f"{type(error).__name__}: {error}"}

    results = []
    remaining = list(records)
    if not dry_run:
        while remaining:
            record = remaining.pop(0)
            result = checked_invoke(record)
            results.append(result)
            if not result.get("ok"):
                return results + [
                    {**pending, "ok": False, "skipped": True, "error": "backend_preflight_failed"}
                    for pending in remaining
                ]
            if not result.get("reused"):
                break
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results.extend(pool.map(checked_invoke, remaining))
    return results
