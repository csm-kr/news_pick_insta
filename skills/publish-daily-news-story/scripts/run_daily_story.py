#!/usr/bin/env python3
"""Create today's six-second News Pick Story video and optionally publish it."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import publish_story_video
import render_story_video


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--date", dest="target_date")
    parser.add_argument("--run", action="append", dest="runs")
    parser.add_argument("--account", default=os.environ.get("IG_ACCOUNT"))
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Perform the externally mutating Instagram Story upload",
    )
    args = parser.parse_args()
    try:
        output_root = (args.output_root or render_story_video.default_output_root()).expanduser().resolve()
        target_date = (
            date.fromisoformat(args.target_date)
            if args.target_date
            else datetime.now(render_story_video.KST).date()
        )
        rendered = render_story_video.render(
            output_root,
            target_date,
            explicit_runs=args.runs,
            force=args.force_render,
        )
        response = {"render": rendered, "publish_requested": args.publish}
        if args.publish:
            if not args.account:
                raise ValueError("--account or IG_ACCOUNT is required with --publish")
            manifest = output_root / "daily-story" / target_date.isoformat() / "manifest.json"
            published = publish_story_video.publish(
                manifest,
                args.account,
                rendered["video"]["sha256"],
            )
            response["publish"] = published
            ok = published.get("status") == "published" and published.get("public_verified") is True
            print(json.dumps({"ok": ok, "result": response}, ensure_ascii=False, indent=2))
            return 0 if ok else (5 if published.get("submission_started") else 4)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": response}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
