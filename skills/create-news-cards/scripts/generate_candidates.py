#!/usr/bin/env python3
"""Run 12 isolated Tibo jobs concurrently from one top-level command."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tibo_roots() -> list[Path]:
    candidates = []
    configured = os.environ.get("GOD_TIBO_SKILL_ROOT")
    if configured:
        candidates.append(Path(configured).expanduser())
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    candidates.extend(
        [
            Path(__file__).resolve().parents[2] / "god-tibo-gpt-image2-skill",
            codex_home / "skills" / "god-tibo-gpt-image2-skill",
            Path.home() / ".agents" / "skills" / "god-tibo-gpt-image2-skill",
        ]
    )
    unique = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def tibo_root() -> Path:
    for candidate in tibo_roots():
        if (candidate / "scripts" / "tibo-batch.mjs").is_file():
            return candidate
    searched = ", ".join(str(path) for path in tibo_roots())
    raise FileNotFoundError(
        "god-tibo-gpt-image2-skill을 찾을 수 없다. GOD_TIBO_SKILL_ROOT를 설정한다. "
        f"검색 위치: {searched}"
    )


def run_one(record: dict, work: Path, script: Path, dry_run: bool, force: bool) -> dict:
    job_path = Path(record["job"])
    target = work / "candidates" / record["direction_id"] / f"card-{record['card_index']:02d}.png"
    if not dry_run and not force and target.is_file() and target.stat().st_size > 0:
        return {
            **record,
            "returncode": 0,
            "ok": True,
            "reused": True,
            "path": str(target.resolve()),
            "sha256": sha256(target),
        }
    command = [os.environ.get("GOD_TIBO_NODE", "node"), str(script), "--job", str(job_path)]
    if dry_run:
        command.append("--dry-run")
    completed = subprocess.run(command, cwd=str(job_path.parent), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200)
    result = {**record, "returncode": completed.returncode}
    if completed.returncode != 0:
        result["error"] = (completed.stderr or completed.stdout)[-2000:]
        return result
    if dry_run:
        result["dry_run"] = True
        return result
    manifest_path = job_path.parent / "output" / "manifest.json"
    if not manifest_path.is_file():
        result["error"] = "manifest.json이 없다."
        return result
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images = manifest.get("images") or []
    if len(images) != 1:
        result["error"] = "단일 이미지 manifest가 아니다."
        return result
    source = Path(images[0]["path"])
    if not source.is_absolute():
        source = (job_path.parent / source).resolve()
    if not source.is_file() or source.stat().st_size == 0:
        result["error"] = "생성 이미지가 없거나 비었다."
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    result.update({"ok": True, "path": str(target.resolve()), "sha256": sha256(target), "manifest": str(manifest_path.resolve())})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Regenerate candidates even when a valid output file exists.")
    args = parser.parse_args()
    try:
        if not 1 <= args.workers <= 12:
            raise ValueError("--workers는 1~12다.")
        plan = json.loads((args.work_dir / "generation-plan.json").read_text(encoding="utf-8"))
        jobs = plan.get("jobs", [])
        if len(jobs) != 12:
            raise ValueError("generation plan은 정확히 12개 job이어야 한다.")
        script = (tibo_root() / "scripts" / "tibo-batch.mjs").resolve()
        if not script.is_file():
            raise ValueError(f"Tibo 실행기를 찾을 수 없다: {script}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_one, record, args.work_dir, script, args.dry_run, args.force) for record in jobs]
            results = [future.result() for future in futures]
        failures = [item for item in results if not item.get("ok") and not item.get("dry_run")]
        manifest = {"schema_version": "1.0", "candidate_count": len(results), "concurrency": args.workers, "dry_run": args.dry_run, "status": "complete" if not failures else "incomplete", "results": results}
        (args.work_dir / "visual-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if failures:
            raise RuntimeError(f"12장 중 {len(failures)}장이 실패했다.")
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": {"candidates": len(results), "dry_run": args.dry_run}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
