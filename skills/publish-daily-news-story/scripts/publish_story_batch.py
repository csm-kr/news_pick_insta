#!/usr/bin/env python3
"""Publish and verify exactly three rendered Story videos without retries."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import publish_story_video as legacy


KST = legacy.KST
STORY_COUNT = 3
TASK = Path(__file__).with_name("private_video_story_batch_task.py")
VERIFY_TASK = Path(__file__).with_name("browser_verify_video_story_batch.py")
PRIVATE_PREFIX = "INSTAGRAM_PRIVATE_VIDEO_STORY_BATCH_RESULT="
VERIFY_PREFIX = "INSTAGRAM_VIDEO_STORY_BATCH_VERIFY="


def load_manifest(path: Path) -> tuple[dict, list[dict], Path]:
    manifest_path = path.expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if (
        manifest.get("status") != "rendered"
        or manifest.get("mode") != "three_separate_stories"
        or manifest.get("story_count") != STORY_COUNT
    ):
        raise ValueError("Story manifest is not a rendered three-Story batch")
    stories = manifest.get("stories", [])
    if len(stories) != STORY_COUNT:
        raise ValueError("Story manifest must contain exactly three videos")
    required = {
        "codec": "h264",
        "width": 1080,
        "height": 1920,
        "pixel_format": "yuv420p",
        "frame_rate": "30/1",
    }
    normalized = []
    for expected_index, record in enumerate(stories, start=1):
        video = Path(record.get("path") or "").resolve()
        proof = Path(record.get("proof") or "").resolve()
        digest = str(record.get("sha256") or "").lower()
        technical = record.get("technical", {})
        if record.get("index") != expected_index:
            raise ValueError("Story batch order is invalid")
        if not video.is_file() or video.suffix.lower() != ".mp4" or legacy.sha256(video) != digest:
            raise ValueError("Story batch media does not match its SHA-256")
        if not proof.is_file() or proof.suffix.lower() not in {".jpg", ".jpeg"}:
            raise ValueError("Story batch proof is missing")
        if any(technical.get(key) != value for key, value in required.items()):
            raise ValueError("Story batch technical validation is incomplete")
        if abs(float(technical.get("duration_seconds") or 0) - 6.0) > 0.04:
            raise ValueError("each Story video must be six seconds")
        normalized.append(
            {
                "index": expected_index,
                "path": str(video),
                "sha256": digest,
                "proof": str(proof),
                "source_run_id": str((record.get("source") or {}).get("run_id") or ""),
            }
        )
    return manifest, normalized, manifest_path.parent


def verify_existing(result: dict, result_path: Path, account: str, entries: list[dict]) -> dict:
    stories = result.get("stories", [])
    urls = [str(item.get("story_url") or "") for item in stories]
    pks = [str(item.get("story_pk") or "") for item in stories]
    if len(urls) != STORY_COUNT or not all(urls) or len(pks) != STORY_COUNT or not all(pks):
        raise RuntimeError("existing Story batch has no complete three-item identity")
    screenshot_dir = result_path.parent / "verified-stories"
    verify_code, verification, verify_diagnostic = legacy.harness_call(
        VERIFY_TASK,
        {
            "IG_ACCOUNT": account,
            "IG_STORY_URLS_JSON": json.dumps(urls),
            "IG_STORY_VERIFY_SCREENSHOT_DIR": str(screenshot_dir.resolve()),
        },
        VERIFY_PREFIX,
        timeout=240,
    )
    metadata_code, metadata, metadata_diagnostic = legacy.harness_call(
        TASK,
        {
            "STORY_ACCOUNT": account,
            "STORY_PRIVATE_SITE_PACKAGES": str(
                legacy.private_site_packages(Path(entries[0]["path"]).resolve().parents[2])
            ),
            "STORY_PRIVATE_MODE": "verify_batch",
            "STORY_BATCH_JSON": json.dumps(entries),
            "STORY_PKS_JSON": json.dumps(pks),
            "STORY_HELPER_SCRIPTS": str(Path(__file__).resolve().parent),
        },
        PRIVATE_PREFIX,
        timeout=180,
    )
    result["public_verification"] = verification
    result["metadata_verification"] = metadata
    result["updated_at"] = datetime.now(KST).isoformat()
    public_ok = bool(
        verify_code == 0
        and verification.get("ok")
        and verification.get("story_count") == STORY_COUNT
    )
    metadata_ok = bool(
        metadata_code == 0
        and metadata.get("ok")
        and metadata.get("confirmed")
        and len(metadata.get("stories", [])) == STORY_COUNT
        and all(
            item.get("media_type") == 2
            and item.get("video_url_present") is True
            and 5.5 <= float(item.get("video_duration") or 0) <= 6.5
            for item in metadata.get("stories", [])
        )
    )
    if public_ok and metadata_ok:
        result.update(
            {
                "status": "published",
                "public_verified": True,
                "verified_at": datetime.now(KST).isoformat(),
                "story_count": STORY_COUNT,
                "verification_mode": "edge_background_batch_plus_private_metadata",
            }
        )
        result.pop("diagnostic", None)
    else:
        result["status"] = "needs_review"
        result["public_verified"] = False
        result["diagnostic"] = "\n".join(
            value for value in (verify_diagnostic, metadata_diagnostic) if value
        )[-10000:]
    legacy.atomic_json(result_path, result)
    return result


def publish(manifest_path: Path, account: str, expected_input_sha256: str | None = None) -> dict:
    manifest, entries, output_dir = load_manifest(manifest_path)
    account = legacy.normalize_account(account)
    input_hash = str(manifest.get("input_set_sha256") or "").lower()
    if expected_input_sha256 and expected_input_sha256.lower() != input_hash:
        raise ValueError("approved input SHA-256 does not match the rendered Story batch")
    result_path = output_dir / "result.json"
    if result_path.is_file():
        existing = json.loads(result_path.read_text(encoding="utf-8-sig"))
        if existing.get("status") == "published":
            if existing.get("input_set_sha256") != input_hash:
                raise ValueError("a different Story batch is already recorded as published")
            existing["reused"] = True
            return existing
        if existing.get("submission_started") is True or existing.get("status") == "needs_review":
            if existing.get("input_set_sha256") == input_hash and len(existing.get("stories", [])) == STORY_COUNT:
                return verify_existing(existing, result_path, account, entries)
            raise RuntimeError("a previous Story batch may have started; inspect Instagram before retry")

    site_packages = legacy.private_site_packages(Path(entries[0]["path"]).resolve().parents[2])
    publish_code, submitted, diagnostic = legacy.harness_call(
        TASK,
        {
            "STORY_ACCOUNT": account,
            "STORY_PRIVATE_SITE_PACKAGES": str(site_packages),
            "STORY_PRIVATE_MODE": "publish_batch",
            "STORY_BATCH_JSON": json.dumps(entries),
            "STORY_HELPER_SCRIPTS": str(Path(__file__).resolve().parent),
        },
        PRIVATE_PREFIX,
        timeout=600,
    )
    submission_started = submitted.get("submission_started") is True
    result = {
        "schema_version": "2.0",
        "status": "needs_review" if submission_started else "failed_pre_submit",
        "public_verified": False,
        "submission_started": submission_started,
        "account": account,
        "backend": "private_video_story_batch",
        "manifest": str(manifest_path.resolve()),
        "input_set_sha256": input_hash,
        "source_runs": [entry["source_run_id"] for entry in entries],
        "story_count": STORY_COUNT,
        "stories": submitted.get("stories", []),
        "submission": submitted,
        "updated_at": datetime.now(KST).isoformat(),
    }
    legacy.atomic_json(result_path, result)
    if (
        publish_code != 0
        or not submitted.get("ok")
        or not submitted.get("confirmed")
        or len(result["stories"]) != STORY_COUNT
    ):
        result["diagnostic"] = diagnostic
        legacy.atomic_json(result_path, result)
        return result
    return verify_existing(result, result_path, account, entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--account", default=os.environ.get("IG_ACCOUNT"))
    parser.add_argument("--expected-input-sha256")
    args = parser.parse_args()
    try:
        if not args.account:
            raise ValueError("--account or IG_ACCOUNT is required")
        result = publish(args.manifest, args.account, args.expected_input_sha256)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    ok = result.get("status") == "published" and result.get("public_verified") is True
    print(json.dumps({"ok": ok, "result": result}, ensure_ascii=False, indent=2))
    return 0 if ok else (5 if result.get("submission_started") else 4)


if __name__ == "__main__":
    raise SystemExit(main())
