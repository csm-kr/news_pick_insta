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
# 공유가 실패하고 미게시가 확인된 회차의 복구 공유: 지연 등록을 기다린 뒤 회차+60분 안에서만 허용한다.
RECOVERY_DELAY = timedelta(minutes=10)
MAX_RECOVERY_LATENESS = timedelta(minutes=60)


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


def recovery_failed_at(environment: dict[str, str]) -> datetime | None:
    if environment.get("NEWS_PICK_SHARE_RECOVERY") != "1":
        return None
    raw = environment.get("NEWS_PICK_SHARE_FAILED_AT")
    if not raw:
        raise ValueError("복구 공유에는 NEWS_PICK_SHARE_FAILED_AT이 필요하다.")
    failed_at = parse_iso_datetime(raw)
    if failed_at.tzinfo is None:
        raise ValueError("NEWS_PICK_SHARE_FAILED_AT에는 timezone이 필요하다.")
    return failed_at


def validate_recovery_window(target: datetime, current: datetime, failed_at: datetime) -> float:
    if failed_at < target:
        raise ValueError("공유 실패 시각이 회차 시각보다 이르다.")
    if current > target + MAX_RECOVERY_LATENESS:
        raise ValueError("게시 시각에서 60분 넘게 지나 복구 공유를 하지 않는다.")
    return (failed_at + RECOVERY_DELAY - current).total_seconds()


def wait_until(target: datetime, offset: timedelta = timedelta(0), failed_at: datetime | None = None) -> datetime:
    while True:
        current = datetime.now(target.tzinfo)
        if failed_at is None:
            remaining = validate_window(target, current, offset)
        else:
            remaining = validate_recovery_window(target, current, failed_at)
        if remaining <= 0:
            return current
        time.sleep(min(remaining, 30.0))


def main() -> int:
    try:
        target = scheduled_time(dict(os.environ))
        offset = publish_offset(dict(os.environ))
        released_at = wait_until(target, offset, recovery_failed_at(dict(os.environ)))
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
