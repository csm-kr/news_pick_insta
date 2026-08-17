#!/usr/bin/env python3
"""Create and validate upload-news-pick run checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGES = ("search-news", "plan-news-pick", "create-news-cards", "publish-news-pick")
DIRS = {
    "search-news": "01-search",
    "plan-news-pick": "02-plan",
    "create-news-cards": "03-create",
    "publish-news-pick": "04-publish",
}


def default_output_root() -> Path:
    configured = os.environ.get("NEWS_PICK_OUTPUT_ROOT")
    return Path(configured).expanduser().resolve() if configured else (Path.cwd() / "output").resolve()


def initialize_output_root(output_root: Path) -> Path:
    output_root = output_root.expanduser().resolve()
    skills_root = Path(__file__).resolve().parents[2]
    try:
        output_root.relative_to(skills_root)
    except ValueError:
        pass
    else:
        raise ValueError("output root는 설치된 skills 폴더 밖에 있어야 한다.")
    for dirname in ("runs", "publish-news-pick", "profile-candidates", "cache", "logs"):
        (output_root / dirname).mkdir(parents=True, exist_ok=True)
    return output_root


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        if item.name.endswith(".tmp"):
            continue
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_stage(run: Path, stage: str) -> None:
    folder = run / DIRS[stage]
    if stage == "search-news":
        story = load_json(folder / "selected-story.json")
        if story.get("verification_status") != "verified":
            raise ValueError("selected story가 verified가 아니다.")
        press = {s.get("publisher") for s in story.get("sources", []) if s.get("source_type") == "press_article"}
        if len({x for x in press if x}) < 2:
            raise ValueError("서로 독립적인 언론사 원문 두 곳이 필요하다.")
    elif stage == "plan-news-pick":
        board = load_json(folder / "storyboard.json")
        count = board.get("card_count")
        if count not in (3, 4) or len(board.get("cards", [])) != count:
            raise ValueError("storyboard는 정확히 3장 또는 4장이어야 한다.")
        if not board.get("qa", {}).get("hard_fail_passed") or board.get("qa", {}).get("editorial_score", 0) < 13:
            raise ValueError("기획 QA가 통과되지 않았다.")
        for card in board["cards"]:
            if not card.get("evidence_ids"):
                raise ValueError(f"card {card.get('index')}에 evidence_ids가 없다.")
    elif stage == "create-news-cards":
        selection = load_json(folder / "selection.json")
        qa = load_json(folder / "qa-report.json")
        duplicate_qa = load_json(folder / "duplicate-qa.json")
        candidates = [p for p in (folder / "candidates").rglob("*.png")]
        slides = [p for p in (folder / "slides").glob("*.png")]
        if len(candidates) != 12:
            raise ValueError("후보 이미지는 정확히 12장이어야 한다.")
        if len(slides) not in (3, 4) or selection.get("card_count") != len(slides):
            raise ValueError("선택된 최종 slides 장수가 올바르지 않다.")
        if qa.get("passed") is not True:
            raise ValueError("이미지 QA가 통과되지 않았다.")
        if duplicate_qa.get("passed") is not True or qa.get("checks", {}).get("no_exact_or_near_duplicate") is not True:
            raise ValueError("이미지 중복 QA가 통과되지 않았다.")
    else:
        result = load_json(folder / "result.json")
        if result.get("status") != "published" or result.get("public_verified") is not True:
            raise ValueError("Instagram 공개 검증이 완료되지 않았다.")


def init_run(runs_root: Path, edition_at: str, account: str) -> dict[str, Any]:
    datetime.fromisoformat(edition_at.replace("Z", "+00:00"))
    account = account.strip().lstrip("@").lower()
    if not account:
        raise ValueError("account가 필요하다.")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run = runs_root / run_id
    for dirname in DIRS.values():
        (run / dirname).mkdir(parents=True, exist_ok=False)
    state = {
        "schema_version": "1.0",
        "run_id": run_id,
        "edition_at": edition_at,
        "timezone": "Asia/Seoul",
        "account": account,
        "status": "in_progress",
        "current_stage": STAGES[0],
        "created_at": now_iso(),
        "stages": {name: {"status": "pending", "output_sha256": None} for name in STAGES},
    }
    atomic_json(run / "run.json", state)
    return {"run": str(run.resolve()), **state}


def complete_stage(run: Path, stage: str) -> dict[str, Any]:
    state = load_json(run / "run.json")
    if stage not in STAGES:
        raise ValueError(f"알 수 없는 stage: {stage}")
    current = state["current_stage"]
    if current != stage:
        raise ValueError(f"현재 stage는 {current}이며 {stage}를 완료할 수 없다.")
    validate_stage(run, stage)
    record = state["stages"][stage]
    record.update({"status": "completed", "output_sha256": tree_hash(run / DIRS[stage]), "completed_at": now_iso()})
    index = STAGES.index(stage)
    if index + 1 == len(STAGES):
        state["status"] = "completed"
        state["current_stage"] = None
        state["completed_at"] = now_iso()
    else:
        state["current_stage"] = STAGES[index + 1]
    atomic_json(run / "run.json", state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    root_group = init.add_mutually_exclusive_group()
    root_group.add_argument("--output-root", type=Path, help="Runtime output root. Runs are created below <output-root>/runs.")
    root_group.add_argument("--runs-root", type=Path, help=argparse.SUPPRESS)
    init.add_argument("--edition-at", required=True)
    init.add_argument("--account", default="newspick_studio")
    status = commands.add_parser("status")
    status.add_argument("--run", type=Path, required=True)
    complete = commands.add_parser("complete-stage")
    complete.add_argument("--run", type=Path, required=True)
    complete.add_argument("--stage", choices=STAGES, required=True)
    validate = commands.add_parser("validate-stage")
    validate.add_argument("--run", type=Path, required=True)
    validate.add_argument("--stage", choices=STAGES, required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            if args.runs_root:
                runs_root = args.runs_root
            else:
                runs_root = initialize_output_root(args.output_root or default_output_root()) / "runs"
            result = init_run(runs_root.resolve(), args.edition_at, args.account)
        elif args.command == "status":
            result = load_json(args.run / "run.json")
        elif args.command == "complete-stage":
            result = complete_stage(args.run, args.stage)
        else:
            validate_stage(args.run, args.stage)
            result = {"valid": True, "stage": args.stage}
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
