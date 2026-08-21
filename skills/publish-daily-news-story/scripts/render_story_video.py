#!/usr/bin/env python3
"""Render every verified News Pick cover for one edition date into a six-second Story MP4."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image


KST = ZoneInfo("Asia/Seoul")
WIDTH = 1080
HEIGHT = 1920
FPS = 30
FRAME_COUNT = 180
DURATION = 6.0
FADE = 0.4


@dataclass(frozen=True)
class Source:
    run_id: str
    run_dir: Path
    cover: Path
    cover_sha256: str
    post_url: str
    shortcode: str
    edition_at: datetime
    verified_at: datetime

    def record(self) -> dict:
        return {
            "run_id": self.run_id,
            "edition_at": self.edition_at.isoformat(),
            "verified_at": self.verified_at.isoformat(),
            "post_url": self.post_url,
            "shortcode": self.shortcode,
            "cover": str(self.cover),
            "cover_sha256": self.cover_sha256,
        }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def parse_timestamp(value: str, field_name: str = "timestamp") -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(KST)


def default_output_root() -> Path:
    configured = os.environ.get("NEWS_PICK_OUTPUT_ROOT")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path.cwd() / "output")
    try:
        candidates.append(Path(__file__).resolve().parents[3] / "output")
    except IndexError:
        pass
    for candidate in candidates:
        if (candidate / "runs").is_dir():
            return candidate.resolve()
    raise FileNotFoundError(
        "NEWS_PICK_OUTPUT_ROOT was not set and an output/runs directory was not found"
    )


def validate_cover(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"cover does not exist: {path}")
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ValueError(f"cover must be PNG: {path}")
        if image.size != (1024, 1024):
            raise ValueError(f"cover must be 1024x1024: {path} is {image.size}")


def source_from_run(run_dir: Path) -> Source:
    run_path = run_dir / "run.json"
    result_path = run_dir / "04-publish" / "result.json"
    if not run_path.is_file():
        raise ValueError(f"run metadata is missing: {run_dir.name}")
    if not result_path.is_file():
        raise ValueError(f"publish result is missing: {run_dir.name}")
    run = json.loads(run_path.read_text(encoding="utf-8-sig"))
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    if result.get("status") != "published":
        raise ValueError(f"run is not published: {run_dir.name}")
    if result.get("public_verified") is not True:
        raise ValueError(f"run is not publicly verified: {run_dir.name}")
    if result.get("first_card_match") is not True:
        raise ValueError(f"run first card is not verified: {run_dir.name}")
    edition_at = parse_timestamp(run.get("edition_at"), "edition_at")
    verified_at = parse_timestamp(result.get("verified_at"), "verified_at")
    cover = (run_dir / "03-create" / "slides" / "01.png").resolve()
    validate_cover(cover)
    post_url = str(result.get("url") or "")
    shortcode = str(result.get("shortcode") or "")
    if not post_url.startswith("https://www.instagram.com/p/") or not shortcode:
        raise ValueError(f"run has no verified Instagram permalink: {run_dir.name}")
    return Source(
        run_id=run_dir.name,
        run_dir=run_dir.resolve(),
        cover=cover,
        cover_sha256=sha256(cover),
        post_url=post_url,
        shortcode=shortcode,
        edition_at=edition_at,
        verified_at=verified_at,
    )


def discover_sources(
    output_root: Path, target_date: date, explicit_runs: list[str] | None = None
) -> list[Source]:
    runs_root = output_root / "runs"
    if not runs_root.is_dir():
        raise FileNotFoundError(f"runs directory does not exist: {runs_root}")
    if explicit_runs:
        candidates = [source_from_run(runs_root / run_id) for run_id in explicit_runs]
    else:
        candidates = []
        for result_path in sorted(runs_root.glob("*/04-publish/result.json")):
            try:
                source = source_from_run(result_path.parents[1])
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if source.verified_at.date() == target_date:
                candidates.append(source)
    if not candidates:
        raise ValueError(f"no posts were publicly verified on {target_date}")
    outside_date = [
        item.run_id for item in candidates if item.verified_at.date() != target_date
    ]
    if outside_date:
        raise ValueError(
            f"selected runs must all have verified_at on {target_date}: {outside_date}"
        )
    return sorted(candidates, key=lambda item: (item.verified_at, item.edition_at))


def input_set_sha256(sources: list[Source], target_date: date) -> str:
    payload = {
        "date": target_date.isoformat(),
        "sources": [source.record() for source in sources],
        "render": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "frames": FRAME_COUNT,
            "fade_seconds": FADE,
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def input_duration(source_count: int) -> float:
    if source_count < 1:
        raise ValueError("at least one Story source is required")
    return (DURATION + (source_count - 1) * FADE) / source_count


def proof_times(source_count: int) -> tuple[float, ...]:
    if source_count < 1:
        raise ValueError("at least one Story source is required")
    return tuple((index + 0.5) * DURATION / source_count for index in range(source_count))


def ffmpeg_filter(source_count: int) -> str:
    clip_duration = input_duration(source_count)
    chains = []
    for index in range(source_count):
        chains.extend(
            [
                f"[{index}:v]split=2[bg{index}][fg{index}]",
                (
                    f"[bg{index}]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                    f"crop={WIDTH}:{HEIGHT},gblur=sigma=60,"
                    f"eq=brightness=-0.34:saturation=0.78[back{index}]"
                ),
                (
                    f"[fg{index}]scale=1024:1024:flags=lanczos,setsar=1[front{index}]"
                ),
                (
                    f"[back{index}][front{index}]overlay=28:448,"
                    f"fps={FPS},format=yuv420p,setsar=1[v{index}]"
                ),
            ]
        )
    if source_count == 1:
        chains.append("[v0]null[outv]")
        return ";".join(chains)
    previous = "v0"
    for index in range(1, source_count):
        output = "outv" if index == source_count - 1 else f"x{index}"
        suffix = ",format=yuv420p" if output == "outv" else ""
        offset = index * (clip_duration - FADE)
        chains.append(
            f"[{previous}][v{index}]xfade=transition=fade:duration={FADE:.6f}:"
            f"offset={offset:.9f}{suffix}[{output}]"
        )
        previous = output
    return ";".join(chains)


def run_checked(command: list[str], label: str) -> subprocess.CompletedProcess:
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        diagnostic = (process.stderr or process.stdout)[-6000:]
        raise RuntimeError(f"{label} failed ({process.returncode}): {diagnostic}")
    return process


def probe_video(path: Path, ffprobe: str) -> dict:
    process = run_checked(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        "ffprobe",
    )
    payload = json.loads(process.stdout)
    videos = [stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"]
    if len(videos) != 1:
        raise ValueError("Story MP4 must contain exactly one video stream")
    video = videos[0]
    duration = float(video.get("duration") or payload.get("format", {}).get("duration") or 0)
    frame_count = int(video.get("nb_frames") or 0)
    checks = {
        "codec": video.get("codec_name") == "h264",
        "width": video.get("width") == WIDTH,
        "height": video.get("height") == HEIGHT,
        "pixel_format": video.get("pix_fmt") == "yuv420p",
        "frame_rate": video.get("r_frame_rate") == f"{FPS}/1",
        "duration": abs(duration - DURATION) <= 0.04,
        "frame_count": frame_count in {0, FRAME_COUNT},
    }
    if not all(checks.values()):
        raise ValueError(
            "Story MP4 validation failed: "
            + json.dumps({"checks": checks, "stream": video}, ensure_ascii=False)
        )
    return {
        "codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "pixel_format": video.get("pix_fmt"),
        "frame_rate": video.get("r_frame_rate"),
        "duration_seconds": duration,
        "frame_count": frame_count or FRAME_COUNT,
        "has_audio": any(
            stream.get("codec_type") == "audio" for stream in payload.get("streams", [])
        ),
    }


def make_proofs(
    video: Path, output_dir: Path, ffmpeg: str, timestamps: tuple[float, ...]
) -> list[str]:
    proofs = []
    for index, timestamp in enumerate(timestamps, start=1):
        target = output_dir / f"proof-{index:02d}.jpg"
        run_checked(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(target),
            ],
            f"proof frame {index}",
        )
        proofs.append(str(target.resolve()))
    return proofs


def render(
    output_root: Path,
    target_date: date,
    explicit_runs: list[str] | None = None,
    force: bool = False,
) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise FileNotFoundError("ffmpeg and ffprobe must be available on PATH")
    sources = discover_sources(output_root, target_date, explicit_runs)
    source_count = len(sources)
    clip_duration = input_duration(source_count)
    proof_timestamps = proof_times(source_count)
    set_hash = input_set_sha256(sources, target_date)
    output_dir = output_root / "daily-story" / target_date.isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    video = output_dir / "story.mp4"
    manifest_path = output_dir / "manifest.json"

    if manifest_path.is_file() and video.is_file() and not force:
        existing = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if existing.get("input_set_sha256") != set_hash:
            raise FileExistsError(
                "daily Story inputs changed; inspect the existing output and use --force-render explicitly"
            )
        if existing.get("video", {}).get("sha256") != sha256(video):
            raise ValueError("existing Story MP4 does not match its manifest")
        technical = probe_video(video, ffprobe)
        proofs = make_proofs(video, output_dir, ffmpeg, proof_timestamps)
        existing["reused"] = True
        existing["video"]["technical"] = technical
        existing["proof_frames"] = proofs
        atomic_json(manifest_path, existing)
        return existing

    temporary = output_dir / "story.rendering.mp4"
    if temporary.exists():
        temporary.unlink()
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for source in sources:
        command.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-t",
                f"{clip_duration:.9f}",
                "-i",
                str(source.cover),
            ]
        )
    command.extend(
        [
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            ffmpeg_filter(source_count),
            "-map",
            "[outv]",
            "-an",
            "-frames:v",
            str(FRAME_COUNT),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(FPS),
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
    )
    run_checked(command, "FFmpeg Story render")
    os.replace(temporary, video)
    technical = probe_video(video, ffprobe)
    proofs = make_proofs(video, output_dir, ffmpeg, proof_timestamps)
    payload = {
        "schema_version": "1.0",
        "status": "rendered",
        "target_date": target_date.isoformat(),
        "timezone": "Asia/Seoul",
        "input_set_sha256": set_hash,
        "sources": [source.record() for source in sources],
        "source_count": source_count,
        "video": {
            "path": str(video.resolve()),
            "sha256": sha256(video),
            "bytes": video.stat().st_size,
            "technical": technical,
        },
        "layout": {
            "canvas": [WIDTH, HEIGHT],
            "foreground": [1024, 1024],
            "foreground_xy": [28, 448],
            "background": "same cover, aspect-fill, blur 60, darkened",
            "transition": "crossfade",
            "transition_seconds": FADE,
        },
        "proof_times_seconds": list(proof_timestamps),
        "proof_frames": proofs,
        "created_at": datetime.now(KST).isoformat(),
        "reused": False,
    }
    atomic_json(manifest_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--date", dest="target_date")
    parser.add_argument("--run", action="append", dest="runs")
    parser.add_argument("--force-render", action="store_true")
    args = parser.parse_args()
    try:
        output_root = (args.output_root or default_output_root()).expanduser().resolve()
        target_date = (
            date.fromisoformat(args.target_date)
            if args.target_date
            else datetime.now(KST).date()
        )
        result = render(output_root, target_date, args.runs, args.force_render)
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
