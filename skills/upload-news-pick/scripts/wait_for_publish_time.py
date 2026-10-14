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
MAX_PUBLISH_OFFSET = timedelta(minutes=20)


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


def publish_offset(environment: dict[str, str]) -> timedelta:
    """회차 시각 뒤로 실제 공유를 미루는 편차. 매일 같은 초에 올라가지 않게 예약 실행기가 정한다."""
    offset = timedelta(seconds=int(environment.get("NEWS_PICK_PUBLISH_OFFSET_SECONDS") or 0))
    if not timedelta(0) <= offset <= MAX_PUBLISH_OFFSET:
        raise ValueError("NEWS_PICK_PUBLISH_OFFSET_SECONDS는 0~1200초여야 한다.")
    return offset


def validate_window(target: datetime, current: datetime, offset: timedelta = timedelta(0)) -> float:
    until_edition = (target - current).total_seconds()
    if until_edition > MAX_EARLY_WAIT.total_seconds():
        raise ValueError("게시 시각보다 35분 넘게 이르다.")
    if until_edition < -MAX_PUBLISH_LATENESS.total_seconds():
        raise ValueError("게시 시각에서 30분 넘게 지났다.")
    return until_edition + offset.total_seconds()


def wait_until(target: datetime, offset: timedelta = timedelta(0)) -> datetime:
    while True:
        current = datetime.now(target.tzinfo)
        remaining = validate_window(target, current, offset)
        if remaining <= 0:
            return current
        time.sleep(min(remaining, 30.0))


def main() -> int:
    try:
        target = scheduled_time(dict(os.environ))
        offset = publish_offset(dict(os.environ))
        released_at = wait_until(target, offset)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "scheduled_at": target.isoformat(),
                "publish_offset_seconds": int(offset.total_seconds()),
                "released_at": released_at.isoformat(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
