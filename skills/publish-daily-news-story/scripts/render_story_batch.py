#!/usr/bin/env python3
"""Render exactly three verified News Pick covers as three separate Story MP4s."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import render_story_video as legacy


STORY_COUNT = 3
EDITION_SLOTS = ("05:00", "12:00", "17:00")


def ordered_slot_sources(
    sources: list[legacy.Source], target_date: date
) -> list[legacy.Source]:
    by_slot: dict[str, legacy.Source] = {}
    for source in sources:
        if source.edition_at.date() != target_date:
            raise ValueError(
                f"Story source edition date must be {target_date}: {source.run_id}"
            )
        slot = source.edition_at.strftime("%H:%M")
        if slot not in EDITION_SLOTS:
            raise ValueError(
                f"Story source must be a 05:00, 12:00, or 17:00 edition: {source.run_id}"
            )
        if slot in by_slot:
            raise ValueError(f"more than one publicly verified Story source exists for {slot}")
        by_slot[slot] = source
    missing = [slot for slot in EDITION_SLOTS if slot not in by_slot]
    if missing:
        raise ValueError("missing publicly verified Story editions: " + ", ".join(missing))
    return [by_slot[slot] for slot in EDITION_SLOTS]


def batch_input_sha256(sources: list[legacy.Source], target_date: date) -> str:
    payload = {
        "mode": "three_separate_stories",
        "date": target_date.isoformat(),
        "sources": [source.record() for source in sources],
        "render": {
            "width": legacy.WIDTH,
            "height": legacy.HEIGHT,
            "fps": legacy.FPS,
            "frames_per_story": legacy.FRAME_COUNT,
        },
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def render_one(
    source: legacy.Source,
    index: int,
    output_dir: Path,
    ffmpeg: str,
    ffprobe: str,
) -> dict:
    video = output_dir / f"story-{index:02d}.mp4"
    temporary = output_dir / f"story-{index:02d}.rendering.mp4"
    proof = output_dir / f"proof-{index:02d}.jpg"
    if temporary.exists():
        temporary.unlink()
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(legacy.FPS),
        "-t",
        f"{legacy.DURATION:.3f}",
        "-i",
        str(source.cover),
        "-filter_complex_threads",
        "1",
        "-filter_complex",
        legacy.ffmpeg_filter(1),
        "-map",
        "[outv]",
        "-an",
        "-frames:v",
        str(legacy.FRAME_COUNT),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(legacy.FPS),
        "-movflags",
        "+faststart",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        str(temporary),
    ]
    legacy.run_checked(command, f"FFmpeg Story {index} render")
    os.replace(temporary, video)
    technical = legacy.probe_video(video, ffprobe)
    legacy.run_checked(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "3.000",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(proof),
        ],
        f"Story {index} proof",
    )
    return {
        "index": index,
        "source": source.record(),
        "path": str(video.resolve()),
        "sha256": legacy.sha256(video),
        "bytes": video.stat().st_size,
        "technical": technical,
        "proof": str(proof.resolve()),
    }


def validate_existing_story(record: dict, ffprobe: str) -> dict:
    video = Path(record.get("path") or "").resolve()
    proof = Path(record.get("proof") or "").resolve()
    if not video.is_file() or legacy.sha256(video) != record.get("sha256"):
        raise ValueError("existing Story batch video does not match its manifest")
    if not proof.is_file():
        raise ValueError("existing Story batch proof is missing")
    record["technical"] = legacy.probe_video(video, ffprobe)
    return record


def render(
    output_root: Path,
    target_date: date,
    explicit_runs: list[str] | None = None,
    force: bool = False,
    include_manual_editions: bool = False,
) -> dict:
    if include_manual_editions and os.environ.get("NEWS_PICK_DAILY_STORY_SCHEDULED_MODE") == "1":
        raise ValueError("scheduled Story runs cannot include manual editions")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise FileNotFoundError("ffmpeg and ffprobe must be available on PATH")
    sources = legacy.discover_sources(output_root, target_date, explicit_runs)
    if len(sources) != STORY_COUNT:
        raise ValueError(
            f"21:00 batch requires exactly {STORY_COUNT} publicly verified posts; found {len(sources)}"
        )
    if not include_manual_editions:
        sources = ordered_slot_sources(sources, target_date)
    set_hash = batch_input_sha256(sources, target_date)
    output_dir = output_root / "daily-story" / target_date.isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_file() and not force:
        existing = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if existing.get("input_set_sha256") != set_hash:
            raise FileExistsError(
                "daily Story inputs changed; inspect output and use --force-render explicitly"
            )
        stories = existing.get("stories", [])
        if len(stories) != STORY_COUNT:
            raise ValueError("existing manifest is not a three-Story batch")
        existing["stories"] = [validate_existing_story(item, ffprobe) for item in stories]
        existing["reused"] = True
        legacy.atomic_json(manifest_path, existing)
        return existing

    stories = [
        render_one(source, index, output_dir, ffmpeg, ffprobe)
        for index, source in enumerate(sources, start=1)
    ]
    payload = {
        "schema_version": "2.0",
        "status": "rendered",
        "mode": "three_separate_stories",
        "target_date": target_date.isoformat(),
        "timezone": "Asia/Seoul",
        "input_set_sha256": set_hash,
        "source_count": STORY_COUNT,
        "story_count": STORY_COUNT,
        "source_selection": "verified_date" if include_manual_editions else "fixed_editions",
        "sources": [source.record() for source in sources],
        "stories": stories,
        "layout": {
            "canvas": [legacy.WIDTH, legacy.HEIGHT],
            "foreground": [1024, 1024],
            "foreground_xy": [28, 448],
            "background": "same cover, aspect-fill, blur 60, darkened",
            "duration_seconds_each": legacy.DURATION,
        },
        "created_at": datetime.now(legacy.KST).isoformat(),
        "reused": False,
    }
    legacy.atomic_json(manifest_path, payload)
    return payload


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--date", dest="target_date")
    parser.add_argument("--run", action="append", dest="runs")
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument("--include-manual-editions", action="store_true")
    args = parser.parse_args()
    try:
        output_root = (args.output_root or legacy.default_output_root()).expanduser().resolve()
        target_date = (
            date.fromisoformat(args.target_date)
            if args.target_date
            else datetime.now(legacy.KST).date()
        )
        result = render(output_root, target_date, args.runs, args.force_render, args.include_manual_editions)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
