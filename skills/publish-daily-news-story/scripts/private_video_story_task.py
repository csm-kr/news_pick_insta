"""Upload one approved MP4 Story using the current Instagram browser session.

Executed inside Browser Harness. The session cookie stays in process memory and
is never persisted or included in output.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


PREFIX = "INSTAGRAM_PRIVATE_VIDEO_STORY_RESULT="
ORIGIN = "https://www.instagram.com"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_story_video(path: Path, expected_sha256: str) -> Path:
    media = path.resolve()
    if not media.is_file():
        raise ValueError("Story video file does not exist")
    if media.suffix.lower() != ".mp4":
        raise ValueError("Story video must be MP4")
    if media.stat().st_size <= 0 or media.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("Story video size is invalid")
    expected = str(expected_sha256 or "").lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("Story video SHA-256 is invalid")
    if sha256(media) != expected:
        raise ValueError("Story video SHA-256 does not match")
    return media


def safe_error(exc: Exception, secret: str | None) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if secret:
        message = message.replace(secret, "[redacted-session]")
    return message[:2000]


def evaluate(session_id: str, expression: str):
    response = cdp(
        "Runtime.evaluate",
        session_id=session_id,
        expression=expression,
        returnByValue=True,
        awaitPromise=True,
    )
    if response.get("exceptionDetails"):
        raise RuntimeError(str(response["exceptionDetails"]))
    return (response.get("result") or {}).get("value")


def instagram_target(account: str) -> tuple[dict, bool]:
    expected_url = f"{ORIGIN}/{account}"
    targets = cdp("Target.getTargets").get("targetInfos", [])
    matches = [
        target
        for target in targets
        if target.get("type") == "page"
        and str(target.get("url") or "").split("?", 1)[0].rstrip("/") == expected_url
    ]
    if matches:
        return matches[0], False
    created = cdp(
        "Target.createTarget",
        url=expected_url + "/",
        background=True,
    )["targetId"]
    return {"targetId": created, "url": expected_url + "/"}, True


def ensure_authenticated_account(session_id: str, account: str) -> None:
    deadline = time.time() + 20
    state = None
    while time.time() < deadline:
        state = evaluate(
            session_id,
            """
            (() => ({
              url:location.href,
              title:document.title,
              ready:document.readyState,
              text:(document.body?.innerText||'').slice(0,5000),
              login:!!document.querySelector('input[name=username],input[name=password]'),
              challenge:/(challenge|checkpoint)/.test(location.href)
            }))()
            """,
        )
        if (
            state.get("login")
            or state.get("challenge")
            or (
                state.get("ready") == "complete"
                and account in str(state.get("text") or "").lower()
                and any(
                    control in str(state.get("text") or "")
                    for control in ("프로필 편집", "보관함 보기", "프로페셔널 대시보드")
                )
            )
        ):
            break
        time.sleep(0.25)
    if state is None:
        raise RuntimeError("Instagram profile did not load")
    if state.get("login") or state.get("challenge") or "/accounts/login" in state.get("url", ""):
        raise RuntimeError("Instagram login or security confirmation is required")
    visible_text = str(state.get("text") or "")
    title_matches = f"@{account}" in str(state.get("title") or "")
    owner_matches = account in visible_text.lower() and any(
        control in visible_text
        for control in ("프로필 편집", "보관함 보기", "프로페셔널 대시보드")
    )
    if not title_matches and not owner_matches:
        raise RuntimeError("visible Instagram profile account does not match")


def session_secret(session_id: str) -> str:
    cookies = cdp(
        "Network.getCookies",
        session_id=session_id,
        urls=[f"{ORIGIN}/"],
    ).get("cookies", [])
    cookie = next(
        (
            item
            for item in cookies
            if item.get("name") == "sessionid"
            and str(item.get("domain") or "").lstrip(".").endswith("instagram.com")
        ),
        None,
    )
    secret = str((cookie or {}).get("value") or "")
    if len(secret) <= 30:
        raise RuntimeError("valid Instagram session cookie was not found")
    return secret


def story_identity(story) -> tuple[str, str]:
    return (
        str(getattr(story, "pk", "") or ""),
        str(getattr(story, "code", "") or ""),
    )


def main() -> int:
    account = os.environ["STORY_ACCOUNT"].strip().lstrip("@").lower()
    mode = os.environ.get("STORY_PRIVATE_MODE", "probe")
    if mode not in {"probe", "publish", "verify"}:
        raise RuntimeError("STORY_PRIVATE_MODE must be probe, publish, or verify")
    media = None
    thumbnail = None
    if mode == "publish":
        media = validate_story_video(
            Path(os.environ["STORY_MEDIA"]),
            os.environ["STORY_MEDIA_SHA256"],
        )
        thumbnail = Path(os.environ["STORY_THUMBNAIL"]).resolve()
        if (
            not thumbnail.is_file()
            or thumbnail.suffix.lower() not in {".jpg", ".jpeg"}
            or thumbnail.parent != media.parent
        ):
            raise RuntimeError("approved Story thumbnail is invalid")

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
        "backend": "private_video_story",
        "session_persisted": False,
    }
    try:
        active_before = current_tab().get("targetId")
        target, created_target = instagram_target(account)
        attached_target = target["targetId"]
        stage = "attach_current_instagram_target"
        attached_session = cdp(
            "Target.attachToTarget", targetId=attached_target, flatten=True
        )["sessionId"]
        cdp("Runtime.enable", session_id=attached_session)
        cdp("Network.enable", session_id=attached_session)
        stage = "confirm_visible_account"
        ensure_authenticated_account(attached_session, account)
        stage = "read_session_cookie"
        secret = session_secret(attached_session)
        stage = "confirm_private_client_account"
        client = Client()
        client.request_timeout = 45
        if not client.login_by_sessionid(secret):
            raise RuntimeError("private client login failed")
        if str(client.username or "").casefold() != account.casefold():
            raise RuntimeError("private client account does not match")

        if mode == "probe":
            result.update(
                {
                    "ok": True,
                    "confirmed": True,
                    "probe_only": True,
                    "stage": "private_session_confirmed",
                }
            )
        elif mode == "verify":
            stage = "verify_video_story_metadata"
            expected_pk = str(os.environ.get("STORY_PK") or "")
            stories = client.user_stories(client.user_id)
            story = next(
                (item for item in stories if str(getattr(item, "pk", "") or "") == expected_pk),
                None,
            )
            if story is None:
                raise RuntimeError("Story ID was not found in the current account Story list")
            duration = float(getattr(story, "video_duration", 0) or 0)
            video_url = str(getattr(story, "video_url", "") or "")
            thumbnail_url = str(getattr(story, "thumbnail_url", "") or "")
            media_type = int(getattr(story, "media_type", 0) or 0)
            if media_type != 2 or not video_url or not (5.5 <= duration <= 6.5):
                raise RuntimeError("Story video metadata does not match the approved six-second video")
            result.update(
                {
                    "ok": True,
                    "confirmed": True,
                    "probe_only": True,
                    "stage": "video_story_metadata_verified",
                    "story_pk": expected_pk,
                    "story_code": str(getattr(story, "code", "") or "") or None,
                    "media_type": media_type,
                    "video_duration": duration,
                    "video_url_present": True,
                    "video_host": urlparse(video_url).hostname,
                    "thumbnail_url_present": bool(thumbnail_url),
                }
            )
        else:
            stage = "video_upload_to_story"
            result["submission_started"] = True
            story = client.video_upload_to_story(
                media,
                caption="",
                thumbnail=thumbnail,
                resize_mode="fill",
            )
            story_pk, story_code = story_identity(story)
            if not story_pk:
                raise RuntimeError("private API did not return a Story identifier")
            stage = "verify_story_in_account"
            current_ids = {
                str(getattr(item, "pk", "") or "")
                for item in client.user_stories(client.user_id)
            }
            if story_pk not in current_ids:
                raise RuntimeError("uploaded Story was not found in the account Story list")
            result.update(
                {
                    "ok": True,
                    "confirmed": True,
                    "stage": "published",
                    "story_pk": story_pk,
                    "story_code": story_code or None,
                    "story_url": f"{ORIGIN}/stories/{account}/{story_pk}/",
                    "resize_mode": "fill_preformatted_9x16",
                    "media_sha256": os.environ["STORY_MEDIA_SHA256"].lower(),
                }
            )
    except Exception as exc:
        result["error"] = safe_error(
            RuntimeError(f"{stage}: {type(exc).__name__}: {exc}"),
            secret,
        )
    finally:
        secret = None
        if attached_session:
            try:
                cdp("Target.detachFromTarget", sessionId=attached_session)
            except Exception as exc:
                result["cleanup_error"] = safe_error(exc, None)
        if created_target and attached_target:
            try:
                cdp("Target.closeTarget", targetId=attached_target)
                deadline = time.time() + 3
                while time.time() < deadline:
                    targets = cdp("Target.getTargets").get("targetInfos", [])
                    if not any(item.get("targetId") == attached_target for item in targets):
                        break
                    time.sleep(0.1)
            except Exception as exc:
                result["cleanup_error"] = safe_error(exc, None)
        try:
            result["active_preserved"] = (
                active_before is None or active_before == current_tab().get("targetId")
            )
            targets = cdp("Target.getTargets").get("targetInfos", [])
            target_exists = any(item.get("targetId") == attached_target for item in targets)
            result["target_cleanup_ok"] = not target_exists if created_target else target_exists
            result["existing_target_preserved"] = result["target_cleanup_ok"]
        except Exception:
            result["active_preserved"] = active_before is None
            result["existing_target_preserved"] = False
        if not result.get("active_preserved") or not result.get("existing_target_preserved"):
            result["ok"] = False
            result["confirmed"] = False
            result.setdefault("error", "browser target or focus preservation failed")

    print(PREFIX + json.dumps(result, ensure_ascii=True))
    if result["ok"] and result["confirmed"]:
        return 0
    return 5 if result.get("submission_started") else 4


if __name__ == "__main__" or "cdp" in globals():
    raise SystemExit(main())
