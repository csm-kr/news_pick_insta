"""Upload one approved JPEG Story from the current Instagram browser session.

This file is executed inside Browser Harness. The Instagram session cookie is
kept in process memory and is never written to disk or included in output.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


PREFIX = "INSTAGRAM_PRIVATE_STORY_RESULT="
ORIGIN = "https://www.instagram.com"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_story_media(path: Path, expected_sha256: str) -> Path:
    media = path.resolve()
    if not media.is_file():
        raise ValueError("Story media file does not exist")
    if media.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("Story media must be JPEG")
    expected = str(expected_sha256 or "").lower()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError("Story media SHA-256 is invalid")
    if sha256(media) != expected:
        raise ValueError("Story media SHA-256 does not match")
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


def current_instagram_target(account: str) -> dict:
    target = current_tab()
    expected_url = f"{ORIGIN}/{account}"
    if str(target.get("url") or "").split("?", 1)[0].rstrip("/") != expected_url:
        raise RuntimeError("current visible tab is not the approved Instagram account profile")
    return target


def ensure_authenticated_account(session_id: str, account: str) -> None:
    state = evaluate(
        session_id,
        """
        (() => ({
          url:location.href,
          title:document.title,
          login:!!document.querySelector('input[name=username],input[name=password]'),
          challenge:/(challenge|checkpoint)/.test(location.href)
        }))()
        """,
    )
    if state.get("login") or state.get("challenge") or "/accounts/login" in state.get("url", ""):
        raise RuntimeError("Instagram login or security confirmation is required")
    if f"@{account}" not in str(state.get("title") or ""):
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
    pk = str(getattr(story, "pk", "") or "")
    code = str(getattr(story, "code", "") or "")
    return pk, code


def main() -> int:
    account = os.environ["STORY_ACCOUNT"].strip().lstrip("@").lower()
    mode = os.environ.get("STORY_PRIVATE_MODE", "probe")
    if mode not in {"probe", "publish"}:
        raise RuntimeError("STORY_PRIVATE_MODE must be probe or publish")

    media = None
    if mode == "publish":
        media = validate_story_media(
            Path(os.environ["STORY_MEDIA"]),
            os.environ["STORY_MEDIA_SHA256"],
        )
    resize_mode = os.environ.get("STORY_RESIZE_MODE", "fit")
    if resize_mode not in {"fit", "fill"}:
        raise RuntimeError("STORY_RESIZE_MODE must be fit or fill")

    site_packages = Path(os.environ["STORY_PRIVATE_SITE_PACKAGES"]).resolve()
    if not site_packages.is_dir():
        raise RuntimeError("project-local instagrapi site-packages was not found")
    sys.path.insert(0, str(site_packages))
    from instagrapi import Client

    active_before = None
    attached_target = None
    attached_session = None
    secret = None
    stage = "select_current_instagram_target"
    result = {
        "ok": False,
        "confirmed": False,
        "submission_started": False,
        "account": account,
        "backend": "private_story",
        "session_persisted": False,
    }
    try:
        target = current_instagram_target(account)
        active_before = target["targetId"]
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
        else:
            stage = "photo_upload_to_story"
            result["submission_started"] = True
            story = client.photo_upload_to_story(
                media,
                caption="",
                resize_mode=resize_mode,
            )
            story_pk, story_code = story_identity(story)
            if not story_pk:
                raise RuntimeError("private API did not return a Story identifier")
            stage = "verify_story_in_account"
            current_story_ids = {
                str(getattr(item, "pk", "") or "")
                for item in client.user_stories(client.user_id)
            }
            if story_pk not in current_story_ids:
                raise RuntimeError("uploaded Story was not found in the account Story list")
            result.update(
                {
                    "ok": True,
                    "confirmed": True,
                    "stage": "published",
                    "story_pk": story_pk,
                    "story_code": story_code or None,
                    "story_url": f"{ORIGIN}/stories/{account}/{story_pk}/",
                    "resize_mode": resize_mode,
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
        try:
            result["active_preserved"] = (
                active_before is None
                or active_before == current_tab().get("targetId")
            )
            targets = cdp("Target.getTargets").get("targetInfos", [])
            result["existing_target_preserved"] = any(
                item.get("targetId") == attached_target for item in targets
            )
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
