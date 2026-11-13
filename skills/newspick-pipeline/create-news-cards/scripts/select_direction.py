#!/usr/bin/env python3
"""Lock one complete candidate direction for deterministic rendering."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--direction", required=True)
    parser.add_argument("--score", type=int, required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        board = json.loads(args.storyboard.read_text(encoding="utf-8"))
        count = board["card_count"]
        cards = sorted((args.work_dir / "candidates" / args.direction).glob("card-*.png"))
        if len(cards) != count:
            raise ValueError("선택한 direction이 완결된 세트가 아니다.")
        if not 0 <= args.score <= 12 or args.score < 9:
            raise ValueError("세트 score는 9/12 이상이어야 한다.")
        selection = {"schema_version": "1.0", "story_id": board["story_id"], "direction_id": args.direction, "card_count": count, "score": args.score, "reason": args.reason, "selected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "backgrounds": [str(p.resolve()) for p in cards]}
        (args.work_dir / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": selection}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

