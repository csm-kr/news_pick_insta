#!/usr/bin/env python3
"""Publish one rendered daily Story MP4 and verify it without automatic retries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
TASK = Path(__file__).with_name("private_video_story_task.py")
VERIFY_TASK = Path(__file__).with_name("browser_verify_video_story.py")
PRIVATE_PREFIX = "INSTAGRAM_PRIVATE_VIDEO_STORY_RESULT="
VERIFY_PREFIX = "INSTAGRAM_VIDEO_STORY_VERIFY="


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
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def normalize_account(value: str) -> str:
    account = str(value or "").strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9._]+", account):
        raise ValueError("Instagram account is invalid")
    return account


def parse_prefixed(stdout: str, prefix: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            return json.loads(line[len(prefix) :])
    return None


def private_site_packages(output_root: Path) -> Path:
    root = output_root / "publish-news-pick" / "private-venv"
    if sys.platform == "win32":
        path = root / "Lib" / "site-packages"
    else:
        matches = sorted((root / "lib").glob("python*/site-packages"))
        path = matches[0] if matches else root / "lib"
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(
            "publish-news-pick project-local private backend is not installed"
        )
    return path


def harness_call(
    script: Path,
    environment: dict[str, str],
    prefix: str,
    timeout: int,
) -> tuple[int, dict, str]:
    harness = shutil.which("browser-harness")
    if not harness:
        raise FileNotFoundError("browser-harness CLI was not found")
    env = dict(os.environ)
    env.update(
        {
            "BH_DOMAIN_SKILLS": "0",
            "BH_RECORD": "0",
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            **environment,
        }
    )
    try:
        process = subprocess.run(
            [harness],
            input=script.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, {
            "ok": False,
            "confirmed": False,
            "submission_started": None,
            "error": f"Browser Harness timeout after {exc.timeout}s",
        }, ""
    result = parse_prefixed(process.stdout, prefix)
    if result is None:
        result = {
            "ok": False,
            "confirmed": False,
            "submission_started": None,
            "error": "Browser Harness contract result was missing",
        }
    diagnostic = "\n".join(
        value for value in (process.stdout, process.stderr) if value
    )[-6000:]
    return process.returncode, result, diagnostic


def load_manifest(path: Path) -> tuple[dict, Path, str, Path]:
    manifest_path = path.expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != "rendered":
        raise ValueError("Story manifest is not in rendered state")
    video = Path(manifest.get("video", {}).get("path") or "").resolve()
    if not video.is_file() or video.suffix.lower() != ".mp4":
        raise ValueError("Story manifest video is missing or not MP4")
    expected = str(manifest.get("video", {}).get("sha256") or "").lower()
    if sha256(video) != expected:
        raise ValueError("Story video does not match manifest SHA-256")
    technical = manifest.get("video", {}).get("technical", {})
    required = {
        "codec": "h264",
        "width": 1080,
        "height": 1920,
        "pixel_format": "yuv420p",
        "frame_rate": "30/1",
    }
    if any(technical.get(key) != value for key, value in required.items()):
        raise ValueError("Story manifest technical validation is incomplete")
    if abs(float(technical.get("duration_seconds") or 0) - 6.0) > 0.04:
        raise ValueError("Story video is not six seconds")
    output_root = video.parents[2]
    return manifest, video, expected, output_root


def proven_local_pre_submit_failure(result: dict) -> bool:
    error = str((result.get("submission") or {}).get("error") or "")
    return (
        result.get("status") == "needs_review"
        and "StoryBuilder requires MoviePy" in error
        and "video_upload_to_story" in error
    )


def verify_existing_story(result: dict, result_path: Path, account: str) -> dict:
    story_url = str(result.get("story_url") or "")
    if not story_url:
        raise RuntimeError("existing submission has no Story URL to verify")
    screenshot = result_path.parent / "verified.png"
    verify_code, verification, diagnostic = harness_call(
        VERIFY_TASK,
        {
            "IG_ACCOUNT": account,
            "IG_STORY_URL": story_url,
            "IG_STORY_VERIFY_SCREENSHOT": str(screenshot.resolve()),
        },
        VERIFY_PREFIX,
        timeout=150,
    )
    video = Path(result.get("media") or "").resolve()
    output_root = video.parents[2]
    metadata_code, metadata, metadata_diagnostic = harness_call(
        TASK,
        {
            "STORY_ACCOUNT": account,
            "STORY_PRIVATE_SITE_PACKAGES": str(private_site_packages(output_root)),
            "STORY_PRIVATE_MODE": "verify",
            "STORY_PK": str(result.get("story_pk") or ""),
        },
        PRIVATE_PREFIX,
        timeout=180,
    )
    result["verification"] = verification
    result["video_metadata_verification"] = metadata
    result["updated_at"] = datetime.now(KST).isoformat()
    public_url_confirmed = bool(
        verification.get("focus_preserved")
        and verification.get("account_visible")
        and not verification.get("login_wall")
        and not verification.get("challenge")
        and str(verification.get("url") or "").startswith(
            f"https://www.instagram.com/stories/{account}/"
        )
    )
    metadata_confirmed = bool(
        metadata_code == 0
        and metadata.get("ok")
        and metadata.get("confirmed")
        and metadata.get("media_type") == 2
        and 5.5 <= float(metadata.get("video_duration") or 0) <= 6.5
        and metadata.get("video_url_present") is True
    )
    if (verify_code == 0 and verification.get("ok")) or (
        public_url_confirmed and metadata_confirmed
    ):
        result.update(
            {
                "status": "published",
                "public_verified": True,
                "verified_at": datetime.now(KST).isoformat(),
                "visual_verification": str(screenshot.resolve()),
                "verification_mode": (
                    "background_video_playback"
                    if verification.get("video_loaded")
                    else "public_url_plus_private_video_metadata"
                ),
            }
        )
        result.pop("diagnostic", None)
    else:
        result["status"] = "needs_review"
        result["public_verified"] = False
        result["diagnostic"] = "\n".join(
            item for item in (diagnostic, metadata_diagnostic) if item
        )[-10000:]
    atomic_json(result_path, result)
    return result


def publish(manifest_path: Path, account: str, expected_sha256: str | None = None) -> dict:
    manifest, video, video_sha, output_root = load_manifest(manifest_path)
    account = normalize_account(account)
    if expected_sha256 and expected_sha256.lower() != video_sha:
        raise ValueError("approved SHA-256 does not match the rendered Story video")
    output_dir = video.parent
    result_path = output_dir / "result.json"
    prior_pre_submit = None
    if result_path.is_file():
        existing = json.loads(result_path.read_text(encoding="utf-8-sig"))
        if existing.get("status") == "published":
            if existing.get("media_sha256") != video_sha:
                raise ValueError("a different daily Story is already recorded as published")
            existing["reused"] = True
            return existing
        if proven_local_pre_submit_failure(existing):
            prior_pre_submit = {
                "recorded_status": existing.get("status"),
                "corrected_status": "failed_pre_submit",
                "reason": "instagrapi StoryBuilder failed before video_rupload was called",
                "error": (existing.get("submission") or {}).get("error"),
            }
        elif existing.get("submission_started") is True or existing.get("status") == "needs_review":
            if (
                existing.get("story_url")
                and existing.get("media_sha256") == video_sha
                and existing.get("account") == account
            ):
                return verify_existing_story(existing, result_path, account)
            raise RuntimeError(
                "a previous Story submission may have started; inspect Instagram before any retry"
            )

    site_packages = private_site_packages(output_root)
    common_env = {
        "STORY_ACCOUNT": account,
        "STORY_PRIVATE_SITE_PACKAGES": str(site_packages),
    }
    probe_code, probe, probe_diagnostic = harness_call(
        TASK,
        {**common_env, "STORY_PRIVATE_MODE": "probe"},
        PRIVATE_PREFIX,
        timeout=180,
    )
    if probe_code != 0 or not probe.get("ok") or not probe.get("confirmed"):
        result = {
            "schema_version": "1.0",
            "status": "failed_pre_submit",
            "public_verified": False,
            "submission_started": False,
            "account": account,
            "media": str(video),
            "media_sha256": video_sha,
            "manifest": str(manifest_path.resolve()),
            "probe": probe,
            "diagnostic": probe_diagnostic,
            "updated_at": datetime.now(KST).isoformat(),
        }
        atomic_json(result_path, result)
        return result

    publish_code, submitted, publish_diagnostic = harness_call(
        TASK,
        {
            **common_env,
            "STORY_PRIVATE_MODE": "publish",
            "STORY_MEDIA": str(video),
            "STORY_MEDIA_SHA256": video_sha,
            "STORY_THUMBNAIL": str((output_dir / "proof-01.jpg").resolve()),
        },
        PRIVATE_PREFIX,
        timeout=420,
    )
    submission_started = submitted.get("submission_started") is True
    base = {
        "schema_version": "1.0",
        "status": "needs_review" if submission_started else "failed_pre_submit",
        "public_verified": False,
        "submission_started": submission_started,
        "account": account,
        "backend": "private_video_story",
        "media": str(video),
        "media_sha256": video_sha,
        "manifest": str(manifest_path.resolve()),
        "source_runs": [item.get("run_id") for item in manifest.get("sources", [])],
        "probe": probe,
        "submission": submitted,
        "updated_at": datetime.now(KST).isoformat(),
    }
    if prior_pre_submit:
        base["prior_pre_submit"] = prior_pre_submit
    if publish_code != 0 or not submitted.get("ok") or not submitted.get("confirmed"):
        base["diagnostic"] = publish_diagnostic
        atomic_json(result_path, base)
        return base

    story_url = str(submitted.get("story_url") or "")
    base.update(
        {
            "story_pk": submitted.get("story_pk"),
            "story_code": submitted.get("story_code"),
            "story_url": story_url,
        }
    )
    atomic_json(result_path, base)
    return verify_existing_story(base, result_path, account)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--account", default=os.environ.get("IG_ACCOUNT"))
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    try:
        if not args.account:
            raise ValueError("--account or IG_ACCOUNT is required")
        result = publish(args.manifest, args.account, args.expected_sha256)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    ok = result.get("status") == "published" and result.get("public_verified") is True
    print(json.dumps({"ok": ok, "result": result}, ensure_ascii=False, indent=2))
    return 0 if ok else (5 if result.get("submission_started") else 4)


if __name__ == "__main__":
    raise SystemExit(main())
