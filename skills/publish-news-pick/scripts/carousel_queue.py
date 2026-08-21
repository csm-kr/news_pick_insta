#!/usr/bin/env python3
"""Prepare, approve, submit, and publicly verify private carousel jobs."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def default_output_root() -> Path:
    configured = os.environ.get("NEWS_PICK_OUTPUT_ROOT")
    output = Path(configured).expanduser().resolve() if configured else (Path.cwd() / "output").resolve()
    skills_root = Path(__file__).resolve().parents[2]
    try:
        output.relative_to(skills_root)
    except ValueError:
        return output
    raise ValueError("NEWS_PICK_OUTPUT_ROOT는 설치된 skills 폴더 밖에 있어야 한다.")


LOCAL_ROOT = Path(os.environ.get("NEWS_PICK_PUBLISH_ROOT") or (default_output_root() / "publish-news-pick")).expanduser().resolve()
JOBS_ROOT = LOCAL_ROOT / "jobs"
CONFIG_PATH = LOCAL_ROOT / "config.json"
LOCK_PATH = LOCAL_ROOT / "queue.lock"
RUNNER = Path(__file__).with_name("run_carousel.py")
PREFIX = "INSTAGRAM_PRIVATE_CAROUSEL_RESULT="
MAX_CAPTION = 2200
FORBIDDEN_CAPTION_FRAGMENTS = (
    "AI로 재구성한 인포그래픽",
    "기사·공식 이미지를 참고해 AI로 재구성",
    "기사 이미지를 참고해 AI로 재구성",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    """Read JSON written by either Python or Windows PowerShell."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_account(value: str) -> str:
    account = str(value or "").strip().lstrip("@").lower()
    if not account or any(not (c.isalnum() or c in "._") for c in account):
        raise ValueError("Instagram account 형식이 올바르지 않다.")
    return account


def schedule(value: str, timezone_name: str | None) -> tuple[str, str]:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if not timezone_name:
            raise ValueError("timezone 없는 시각에는 --timezone이 필요하다.")
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), timezone_name or str(parsed.tzinfo)


def normalize_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("CDP endpoint는 credential 없는 loopback http 주소여야 한다.")
    port = parsed.port
    if port is None or not 1024 <= port <= 65535:
        raise ValueError("CDP port는 1024~65535다.")
    host = "127.0.0.1" if parsed.hostname in {"127.0.0.1", "localhost"} else "[::1]"
    return urlunsplit(("http", f"{host}:{port}", "", "", ""))


def probe_endpoint(endpoint: str) -> dict[str, Any]:
    with urllib.request.urlopen(endpoint.rstrip("/") + "/json/version", timeout=2) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not value.get("webSocketDebuggerUrl") or not any(x in str(value.get("Browser")) for x in ("Chrome", "Chromium")):
        raise ValueError("endpoint가 Chrome CDP가 아니다.")
    return {"browser": value.get("Browser"), "protocol_version": value.get("Protocol-Version")}


def configure(endpoint: str | None, connection: str | None, expected_profile: str | None, dedicated: bool, path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not dedicated:
        raise ValueError("--dedicated-profile 확인이 필요하다.")
    if bool(endpoint) == bool(connection):
        raise ValueError("--endpoint 또는 --browser-harness-connection 중 하나만 필요하다.")
    if endpoint:
        endpoint = normalize_endpoint(endpoint)
        value = {"schema_version": "1.0", "connection_mode": "cdp_endpoint", "endpoint": endpoint, "dedicated_profile_confirmed": True, "configured_at": now(), **probe_endpoint(endpoint)}
    else:
        if connection != "default":
            raise ValueError("현재는 Browser Harness default 연결만 지원한다.")
        if not expected_profile or any(x in expected_profile for x in ("/", "\\")):
            raise ValueError("--expected-profile에는 Profile 3 같은 profile 폴더명만 넣는다.")
        value = {"schema_version": "1.0", "connection_mode": "browser_harness", "browser_harness_connection": connection, "expected_profile_suffix": expected_profile, "dedicated_profile_confirmed": True, "configured_at": now()}
    atomic_json(path, value)
    return value


def read_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    value = read_json(path)
    if value.get("dedicated_profile_confirmed") is not True:
        raise ValueError("전용 Chrome 확인이 없다.")
    if value.get("connection_mode") == "cdp_endpoint":
        value["endpoint"] = normalize_endpoint(value["endpoint"])
    elif value.get("connection_mode") == "browser_harness":
        if value.get("browser_harness_connection") != "default" or not value.get("expected_profile_suffix"):
            raise ValueError("Browser Harness 연결 설정이 올바르지 않다.")
    else:
        raise ValueError("알 수 없는 connection_mode다.")
    return value


def payload_core(job: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": job["schema_version"], "backend": "private_carousel", "account": job["account"], "scheduled_at_utc": job["scheduled_at_utc"], "timezone": job["timezone"], "caption": job["caption"], "media": [{"order": x["order"], "name": x["name"], "sha256": x["sha256"], "size": x["size"]} for x in job["media"]]}


def payload_hash(job: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload_core(job), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_job(job: dict[str, Any], path: Path) -> None:
    if job.get("backend") != "private_carousel" or len(job.get("media", [])) not in (3, 4):
        raise ValueError("private_carousel은 PNG 3~4장이어야 한다.")
    root = path.parent.resolve()
    for expected, item in enumerate(job["media"], 1):
        media = (root / item["path"]).resolve()
        media.relative_to(root)
        if item.get("order") != expected or media.suffix.lower() != ".png" or not media.is_file() or media.stat().st_size != item["size"] or sha256(media) != item["sha256"]:
            raise ValueError(f"media {expected}가 변경됐거나 순서가 올바르지 않다.")
    if payload_hash(job) != job.get("payload_sha256"):
        raise ValueError("현재 payload hash가 저장값과 다르다.")
    if job.get("status") in {"approved", "submitting", "submitted", "published"} and not hmac.compare_digest(job.get("approved_sha256") or "", job["payload_sha256"]):
        raise ValueError("승인 hash가 현재 payload와 다르다.")


def prepare(account: str, scheduled_at: str, timezone_name: str | None, media: list[Path], caption: str, jobs_root: Path = JOBS_ROOT) -> dict[str, Any]:
    if len(media) not in (3, 4):
        raise ValueError("PNG 3~4장이 필요하다.")
    if len(caption) > MAX_CAPTION:
        raise ValueError("caption은 2200자를 넘을 수 없다.")
    forbidden = next((fragment for fragment in FORBIDDEN_CAPTION_FRAGMENTS if fragment in caption), None)
    if forbidden:
        raise ValueError(f"caption 금지 문구가 포함되어 있다: {forbidden}")
    sources = [p.resolve() for p in media]
    if any(not p.is_file() or p.suffix.lower() != ".png" for p in sources):
        raise ValueError("모든 media는 존재하는 PNG여야 한다.")
    scheduled_utc, zone = schedule(scheduled_at, timezone_name)
    identifier = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:10]
    directory = jobs_root / identifier
    (directory / "media").mkdir(parents=True)
    items = []
    for index, source in enumerate(sources, 1):
        target = directory / "media" / f"{index:02d}.png"
        shutil.copy2(source, target)
        items.append({"order": index, "name": source.name, "path": str(target.relative_to(directory)), "sha256": sha256(target), "size": target.stat().st_size})
    job = {"schema_version": "1.0", "job_id": identifier, "status": "draft", "backend": "private_carousel", "account": normalize_account(account), "scheduled_at_utc": scheduled_utc, "timezone": zone, "caption": caption, "media": items, "created_at": now(), "approved_at": None, "approved_sha256": None, "attempts": [], "private_result": None}
    job["payload_sha256"] = payload_hash(job)
    atomic_json(directory / "job.json", job)
    return job


def load_job(identifier: str, jobs_root: Path = JOBS_ROOT) -> tuple[Path, dict[str, Any]]:
    if not identifier or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in identifier):
        raise ValueError("job_id 형식이 올바르지 않다.")
    path = jobs_root / identifier / "job.json"
    return path, read_json(path)


def approve(identifier: str, supplied: str, jobs_root: Path = JOBS_ROOT) -> dict[str, Any]:
    path, job = load_job(identifier, jobs_root)
    if job["status"] not in {"draft", "failed_pre_submit"}:
        raise ValueError(f"승인할 수 없는 상태: {job['status']}")
    validate_job(job, path)
    if not hmac.compare_digest(job["payload_sha256"], supplied.lower()):
        raise ValueError("payload SHA-256이 일치하지 않는다.")
    job.update({"status": "approved", "approved_at": now(), "approved_sha256": job["payload_sha256"]})
    atomic_json(path, job)
    return job


def parse_result(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(PREFIX):
            try: return json.loads(line[len(PREFIX):])
            except json.JSONDecodeError: return None
    return None


def execute(path: Path, config: Path = CONFIG_PATH) -> dict[str, Any]:
    job = read_json(path)
    validate_job(job, path)
    if job["status"] != "approved":
        raise ValueError("approved job만 실행한다.")
    job["status"] = "submitting"
    attempt = {"started_at": now(), "submission_started": False}
    job["attempts"].append(attempt)
    atomic_json(path, job)
    completed = subprocess.run([sys.executable, str(RUNNER), "--job", str(path), "--config", str(config)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    result = parse_result(completed.stdout) or {"ok": False, "submission_started": None, "error": "publisher result가 없다."}
    attempt.update({"finished_at": now(), "submission_started": result.get("submission_started"), "returncode": completed.returncode, "error": result.get("error")})
    if result.get("ok") and result.get("confirmed") and result.get("shortcode"):
        job["status"] = "submitted"
        job["private_result"] = {k: result.get(k) for k in ("media_pk", "shortcode", "card_count", "final_url", "confirmation_method")}
    elif result.get("submission_started") is False:
        job["status"] = "failed_pre_submit"
    else:
        job["status"] = "needs_review"
    atomic_json(path, job)
    return job


def probe(account: str, config: Path = CONFIG_PATH) -> dict[str, Any]:
    completed = subprocess.run([sys.executable, str(RUNNER), "--probe-account", normalize_account(account), "--config", str(config)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    result = parse_result(completed.stdout)
    if not result or not result.get("ok"):
        raise RuntimeError((result or {}).get("error") or "probe가 실패했다.")
    return result


def run_publish_result_path(run_dir: Path, account: str) -> Path:
    run = run_dir.expanduser().resolve()
    runs_root = (default_output_root() / "runs").resolve()
    try:
        run.relative_to(runs_root)
    except ValueError as exc:
        raise ValueError("run directory는 NEWS_PICK_OUTPUT_ROOT/runs 아래에 있어야 한다.") from exc
    state_path = run / "run.json"
    if not state_path.is_file():
        raise ValueError("run directory에 run.json이 없다.")
    state = read_json(state_path)
    if normalize_account(state.get("account")) != normalize_account(account):
        raise ValueError("run account와 publish job account가 다르다.")
    return run / "04-publish" / "result.json"


def verify_published(identifier: str, shortcode: str, card_count: int, caption_match: bool, first_card_match: bool, jobs_root: Path = JOBS_ROOT, run_dir: Path | None = None) -> dict[str, Any]:
    path, job = load_job(identifier, jobs_root)
    if job["status"] not in {"submitted", "needs_review"}:
        raise ValueError(f"공개 확인할 수 없는 상태: {job['status']}")
    run_result_path = run_publish_result_path(run_dir, job["account"]) if run_dir else None
    submitted_code = str(((job.get("submission_result") or job.get("private_result") or {}).get("shortcode")) or "")
    if submitted_code and shortcode != submitted_code:
        raise ValueError("공개 shortcode가 private 응답과 다르다.")
    if card_count != len(job["media"]) or not caption_match or not first_card_match:
        raise ValueError("공개 게시물이 준비 payload와 일치하지 않는다.")
    result = {"schema_version": "1.0", "status": "published", "public_verified": True, "verified_at": now(), "shortcode": shortcode, "url": f"https://www.instagram.com/p/{shortcode}/", "card_count": card_count, "caption_match": True, "first_card_match": True, "payload_sha256": job["payload_sha256"]}
    job["status"] = "published"
    job["public_result"] = result
    atomic_json(path, job)
    atomic_json(path.parent / "result.json", result)
    if run_result_path:
        atomic_json(run_result_path, result)
    return result


def record_web_submitted(identifier: str, shortcode: str, card_count: int, jobs_root: Path = JOBS_ROOT) -> dict[str, Any]:
    """Record an already-confirmed Browser Harness web submission without re-uploading it."""
    path, job = load_job(identifier, jobs_root)
    if job["status"] not in {"approved", "failed_pre_submit", "needs_review", "submitted"}:
        raise ValueError(f"웹 제출을 기록할 수 없는 상태: {job['status']}")
    validate_job(job, path)
    if not hmac.compare_digest(job.get("approved_sha256") or "", job["payload_sha256"]):
        raise ValueError("현재 payload에 대한 기존 사용자 승인이 없습니다.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,64}", shortcode):
        raise ValueError("Instagram shortcode 형식이 올바르지 않습니다.")
    if card_count != len(job["media"]):
        raise ValueError("공개 카드 수가 승인된 payload와 다릅니다.")

    recorded_at = now()
    submission = {
        "backend": "browser_harness_web_ui",
        "shortcode": shortcode,
        "card_count": card_count,
        "final_url": f"https://www.instagram.com/p/{shortcode}/",
        "confirmation_method": "instagram_web_success_marker",
        "recorded_at": recorded_at,
    }
    job["status"] = "submitted"
    job["submission_result"] = submission
    job["attempts"].append({
        "started_at": recorded_at,
        "finished_at": recorded_at,
        "submission_started": True,
        "backend": "browser_harness_web_ui",
        "confirmation_method": "instagram_web_success_marker",
        "shortcode": shortcode,
        "error": None,
    })
    atomic_json(path, job)
    return job


def due(jobs_root: Path = JOBS_ROOT) -> list[Path]:
    current = datetime.now(timezone.utc)
    paths = []
    for path in jobs_root.glob("*/job.json") if jobs_root.is_dir() else []:
        try:
            job = read_json(path)
            when = datetime.fromisoformat(job["scheduled_at_utc"].replace("Z", "+00:00"))
            if job.get("status") == "approved" and when <= current: paths.append(path)
        except Exception: pass
    return sorted(paths)


@contextmanager
def lock(path: Path = LOCK_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("다른 carousel runner가 실행 중이거나 stale lock이 있다.") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} at={now()}".encode())
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def summary(job: dict[str, Any]) -> dict[str, Any]:
    return {"job_id": job["job_id"], "status": job["status"], "account": job["account"], "scheduled_at_utc": job["scheduled_at_utc"], "timezone": job["timezone"], "media": [{"order": x["order"], "name": x["name"], "sha256": x["sha256"], "size": x["size"]} for x in job["media"]], "caption_chars": len(job["caption"]), "payload_sha256": job["payload_sha256"], "attempts": len(job["attempts"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    conf = commands.add_parser("configure"); connection = conf.add_mutually_exclusive_group(required=True); connection.add_argument("--endpoint"); connection.add_argument("--browser-harness-connection"); conf.add_argument("--expected-profile"); conf.add_argument("--dedicated-profile", action="store_true")
    pro = commands.add_parser("probe"); pro.add_argument("--account", required=True)
    prep = commands.add_parser("prepare"); prep.add_argument("--account", required=True); prep.add_argument("--scheduled-at", required=True); prep.add_argument("--timezone"); prep.add_argument("--media", type=Path, action="append", required=True); group = prep.add_mutually_exclusive_group(required=True); group.add_argument("--caption"); group.add_argument("--caption-file", type=Path)
    app = commands.add_parser("approve"); app.add_argument("job_id"); app.add_argument("--sha256", required=True)
    stat = commands.add_parser("status"); stat.add_argument("job_id", nargs="?")
    commands.add_parser("run-due")
    ver = commands.add_parser("verify-published"); ver.add_argument("job_id"); ver.add_argument("--shortcode", required=True); ver.add_argument("--card-count", type=int, required=True); ver.add_argument("--caption-match", action="store_true"); ver.add_argument("--first-card-match", action="store_true"); ver.add_argument("--run-dir", type=Path)
    web = commands.add_parser("record-web-submitted"); web.add_argument("job_id"); web.add_argument("--shortcode", required=True); web.add_argument("--card-count", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "configure": result = configure(args.endpoint, args.browser_harness_connection, args.expected_profile, args.dedicated_profile)
        elif args.command == "probe": result = probe(args.account)
        elif args.command == "prepare": result = summary(prepare(args.account, args.scheduled_at, args.timezone, args.media, args.caption if args.caption is not None else args.caption_file.read_text(encoding="utf-8")))
        elif args.command == "approve": result = summary(approve(args.job_id, args.sha256))
        elif args.command == "status": result = summary(load_job(args.job_id)[1]) if args.job_id else [summary(read_json(x)) for x in sorted(JOBS_ROOT.glob("*/job.json"))]
        elif args.command == "record-web-submitted": result = summary(record_web_submitted(args.job_id, args.shortcode, args.card_count))
        elif args.command == "verify-published": result = verify_published(args.job_id, args.shortcode, args.card_count, args.caption_match, args.first_card_match, run_dir=args.run_dir)
        else:
            with lock(): result = [summary(execute(path)) for path in due()]
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
