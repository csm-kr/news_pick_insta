"""Upload or verify exactly three Story videos in one Edge Harness process."""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


PREFIX = "INSTAGRAM_PRIVATE_VIDEO_STORY_BATCH_RESULT="
ORIGIN = "https://www.instagram.com"
STORY_COUNT = 3

helper_root = Path(os.environ["STORY_HELPER_SCRIPTS"]).resolve()
if str(helper_root) not in sys.path:
    sys.path.insert(0, str(helper_root))
import private_video_story_task as helper

helper.cdp = cdp
helper.current_tab = current_tab


def load_entries() -> list[dict]:
    entries = json.loads(os.environ["STORY_BATCH_JSON"])
    if not isinstance(entries, list) or len(entries) != STORY_COUNT:
        raise RuntimeError("Story batch must contain exactly three entries")
    validated = []
    for expected_index, entry in enumerate(entries, start=1):
        if int(entry.get("index") or 0) != expected_index:
            raise RuntimeError("Story batch order is invalid")
        media = helper.validate_story_video(
            Path(entry["path"]),
            str(entry["sha256"]),
        )
        thumbnail = Path(entry["proof"]).resolve()
        if (
            not thumbnail.is_file()
            or thumbnail.suffix.lower() not in {".jpg", ".jpeg"}
            or thumbnail.parent != media.parent
        ):
            raise RuntimeError("approved Story batch proof is invalid")
        validated.append(
            {
                "index": expected_index,
                "media": media,
                "sha256": str(entry["sha256"]).lower(),
                "thumbnail": thumbnail,
                "source_run_id": str(entry.get("source_run_id") or ""),
            }
        )
    return validated


def story_record(story, entry: dict) -> dict:
    story_pk, story_code = helper.story_identity(story)
    if not story_pk:
        raise RuntimeError("private API did not return a Story identifier")
    duration = float(getattr(story, "video_duration", 0) or 0)
    video_url = str(getattr(story, "video_url", "") or "")
    return {
        "index": entry["index"],
        "source_run_id": entry["source_run_id"],
        "story_pk": story_pk,
        "story_code": story_code or None,
        "story_url": f"{ORIGIN}/stories/{os.environ['STORY_ACCOUNT'].strip().lstrip('@').lower()}/{story_pk}/",
        "media_sha256": entry["sha256"],
        "media_type": int(getattr(story, "media_type", 0) or 0),
        "video_duration": duration,
        "video_url_present": bool(video_url),
        "video_host": urlparse(video_url).hostname if video_url else None,
    }


def main() -> int:
    account = os.environ["STORY_ACCOUNT"].strip().lstrip("@").lower()
    mode = os.environ.get("STORY_PRIVATE_MODE", "publish_batch")
    if mode not in {"publish_batch", "verify_batch"}:
        raise RuntimeError("STORY_PRIVATE_MODE must be publish_batch or verify_batch")
    entries = load_entries()
    site_packages = Path(os.environ["STORY_PRIVATE_SITE_PACKAGES"]).resolve()
    if not site_packages.is_dir():
        raise RuntimeError("project-local instagrapi site-packages was not found")
    sys.path.insert(0, str(site_packages))
    from instagrapi import Client

    active_before = None
    attached_target = None
    attached_session = None
    created_target = False
    secret = None
    stage = "select_current_instagram_target"
    result = {
        "ok": False,
        "confirmed": False,
        "submission_started": False,
        "account": account,
        "backend": "private_video_story_batch",
        "story_count": STORY_COUNT,
        "stories": [],
        "session_persisted": False,
    }
    try:
        active_before = current_tab().get("targetId")
        target, created_target = helper.instagram_target(account)
        attached_target = target["targetId"]
        stage = "attach_current_instagram_target"
        attached_session = cdp(
            "Target.attachToTarget", targetId=attached_target, flatten=True
        )["sessionId"]
        cdp("Runtime.enable", session_id=attached_session)
        cdp("Network.enable", session_id=attached_session)
        stage = "confirm_visible_account"
        helper.ensure_authenticated_account(attached_session, account)
        stage = "read_session_cookie"
        secret = helper.session_secret(attached_session)
        stage = "confirm_private_client_account"
        client = Client()
        client.request_timeout = 45
        if not client.login_by_sessionid(secret):
            raise RuntimeError("private client login failed")
        if str(client.username or "").casefold() != account.casefold():
            raise RuntimeError("private client account does not match")

        if mode == "verify_batch":
            expected_pks = [str(value) for value in json.loads(os.environ["STORY_PKS_JSON"])]
            if len(expected_pks) != STORY_COUNT:
                raise RuntimeError("Story verification requires exactly three IDs")
            current = {
                str(getattr(item, "pk", "") or ""): item
                for item in client.user_stories(client.user_id)
            }
            for entry, story_pk in zip(entries, expected_pks):
                story = current.get(story_pk)
                if story is None:
                    raise RuntimeError("Story ID was not found in the current account Story list")
                record = story_record(story, entry)
                if (
                    record["media_type"] != 2
                    or not record["video_url_present"]
                    or not 5.5 <= record["video_duration"] <= 6.5
                ):
                    raise RuntimeError("Story batch video metadata is invalid")
                result["stories"].append(record)
            result.update(
                {
                    "ok": True,
                    "confirmed": True,
                    "stage": "story_batch_metadata_verified",
                    "probe_only": True,
                }
            )
        else:
            result["submission_started"] = True
            for offset, entry in enumerate(entries):
                stage = f"video_upload_to_story_{entry['index']}"
                story = client.video_upload_to_story(
                    entry["media"],
                    caption="",
                    thumbnail=entry["thumbnail"],
                    resize_mode="fill",
                )
                record = story_record(story, entry)
                current_ids = {
                    str(getattr(item, "pk", "") or "")
                    for item in client.user_stories(client.user_id)
                }
                if record["story_pk"] not in current_ids:
                    raise RuntimeError("uploaded Story was not found in the account Story list")
                result["stories"].append(record)
                if offset + 1 < len(entries):
                    time.sleep(random.uniform(1.8, 3.2))
            result.update(
                {
                    "ok": True,
                    "confirmed": True,
                    "stage": "published",
                    "published_count": len(result["stories"]),
                    "random_jitter_seconds": "1.8-3.2",
                }
            )
    except Exception as exc:
        result["error"] = helper.safe_error(
            RuntimeError(f"{stage}: {type(exc).__name__}: {exc}"),
            secret,
        )
        result["published_count"] = len(result["stories"])
    finally:
        secret = None
        if attached_session:
            try:
                cdp("Target.detachFromTarget", sessionId=attached_session)
            except Exception as exc:
                result["cleanup_error"] = helper.safe_error(exc, None)
        if created_target and attached_target:
            try:
                cdp("Target.closeTarget", targetId=attached_target)
            except Exception as exc:
                result["cleanup_error"] = helper.safe_error(exc, None)
        try:
            result["active_preserved"] = (
                active_before is None or active_before == current_tab().get("targetId")
            )
            targets = cdp("Target.getTargets").get("targetInfos", [])
            exists = any(item.get("targetId") == attached_target for item in targets)
            result["existing_target_preserved"] = not exists if created_target else exists
        except Exception:
            result["active_preserved"] = active_before is None
            result["existing_target_preserved"] = False
        if not result["active_preserved"] or not result["existing_target_preserved"]:
            result["ok"] = False
            result["confirmed"] = False
            result.setdefault("error", "browser target or focus preservation failed")

    print(PREFIX + json.dumps(result, ensure_ascii=True))
    if result["ok"] and result["confirmed"]:
        return 0
    return 5 if result.get("submission_started") else 4


if __name__ == "__main__" or "cdp" in globals():
    raise SystemExit(main())
