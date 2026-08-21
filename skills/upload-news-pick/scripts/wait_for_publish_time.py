#!/usr/bin/env python3
"""Wait until the scheduled edition time without allowing late catch-up posts."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta


MAX_EARLY_WAIT = timedelta(minutes=35)
MAX_PUBLISH_LATENESS = timedelta(minutes=30)


def parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    normalized = re.sub(r"(\.\d{6})\d+(?=([+-]\d{2}:\d{2})?$)", r"\1", normalized)
    return datetime.fromisoformat(normalized)


def scheduled_time(environment: dict[str, str]) -> datetime:
    if environment.get("NEWS_PICK_SCHEDULED_MODE") != "1":
        raise ValueError("예약 게시 모드가 아니다.")
    raw = environment.get("NEWS_PICK_EDITION_AT")
    if not raw:
        raise ValueError("NEWS_PICK_EDITION_AT이 없다.")
    target = parse_iso_datetime(raw)
    if target.tzinfo is None:
        raise ValueError("NEWS_PICK_EDITION_AT에는 timezone이 필요하다.")
    return target


def validate_window(target: datetime, current: datetime) -> float:
    remaining = (target - current).total_seconds()
    if remaining > MAX_EARLY_WAIT.total_seconds():
        raise ValueError("게시 시각보다 35분 넘게 이르다.")
    if remaining < -MAX_PUBLISH_LATENESS.total_seconds():
        raise ValueError("게시 시각에서 30분 넘게 지났다.")
    return remaining


def wait_until(target: datetime) -> datetime:
    while True:
        current = datetime.now(target.tzinfo)
        remaining = validate_window(target, current)
        if remaining <= 0:
            return current
        time.sleep(min(remaining, 30.0))


def main() -> int:
    try:
        target = scheduled_time(dict(os.environ))
        released_at = wait_until(target)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "scheduled_at": target.isoformat(),
                "released_at": released_at.isoformat(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
