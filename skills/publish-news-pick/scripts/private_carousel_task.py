"""Executed inside Browser Harness; keeps Instagram sessionid in memory."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PREFIX = "INSTAGRAM_PRIVATE_CAROUSEL_RESULT="
ORIGIN = "https://www.instagram.com"
LOGIN_MARKERS = ("log in", "로그인", "sign up", "가입하기")
CHALLENGE_MARKERS = ("captcha", "challenge", "confirm it's you", "security code", "verification code", "인증 코드", "본인 확인", "보안 코드")


def evaluate(session_id, expression):
    response = cdp("Runtime.evaluate", session_id=session_id, expression=expression, returnByValue=True, awaitPromise=True)
    if response.get("exceptionDetails"):
        raise RuntimeError(str(response["exceptionDetails"]))
    return response.get("result", {}).get("value")


def wait_until(session_id, expression, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if evaluate(session_id, expression):
            return True
        time.sleep(0.35)
    return False


def page_targets():
    return {x["targetId"] for x in cdp("Target.getTargets")["targetInfos"] if x.get("type") == "page"}


def instagram_target(account):
    targets = [
        item
        for item in cdp("Target.getTargets").get("targetInfos", [])
        if item.get("type") == "page"
        and str(item.get("url") or "").startswith(("https://www.instagram.com/", "https://instagram.com/"))
    ]
    if len(targets) == 1:
        return targets[0]

    expected_paths = {
        f"https://www.instagram.com/{account}/",
        f"https://instagram.com/{account}/",
    }
    exact = [item for item in targets if str(item.get("url") or "").split("?", 1)[0] in expected_paths]
    if len(exact) == 1:
        return exact[0]
    raise RuntimeError(
        f"게시 계정 @{account}의 기존 Instagram 프로필 탭을 하나로 특정할 수 없다: "
        f"전체 {len(targets)}개, 정확한 프로필 {len(exact)}개"
    )


def state(session_id):
    return json.loads(evaluate(session_id, "JSON.stringify({url:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,30000)})"))


def contains(value, markers):
    lowered = f"{value.get('title','')}\n{value.get('text','')}".casefold()
    return any(marker.casefold() in lowered for marker in markers)


def ensure_account(session_id, account):
    value = state(session_id)
    login_form = evaluate(session_id, "!!document.querySelector('input[name=username],input[name=password]')")
    # An authenticated Instagram shell can contain labels such as "로그인 활동" in
    # hidden settings/navigation text.  Treat only the actual login form/URL as a
    # login wall; the private client below still verifies the exact username.
    if "/accounts/login" in value["url"] or "/challenge" in value["url"] or "/checkpoint" in value["url"] or contains(value, CHALLENGE_MARKERS) or login_form:
        raise RuntimeError("Instagram 로그인 또는 보안 확인이 필요하다.")


def ensure_expected_profile(session_id):
    expected = os.environ.get("CAROUSEL_EXPECTED_PROFILE_SUFFIX")
    if not expected:
        return
    cdp("Page.navigate", session_id=session_id, url="chrome://version/")
    if not wait_until(session_id, "['interactive','complete'].includes(document.readyState)"):
        raise RuntimeError("Chrome profile 확인 timeout")
    body = str(evaluate(session_id, "document.body?.innerText||''") or "")
    normalized = body.replace("\\", "/").casefold()
    if f"/{expected.casefold()}" not in normalized:
        raise RuntimeError(f"현재 Browser Harness 연결이 기대 프로필 {expected}가 아니다.")


def session_secret(session_id):
    cookies = cdp("Network.getAllCookies", session_id=session_id).get("cookies", [])
    cookie = next((x for x in cookies if x.get("name") == "sessionid" and str(x.get("domain") or "").lstrip(".").endswith("instagram.com")), None)
    secret = str((cookie or {}).get("value") or "")
    if len(secret) <= 30:
        raise RuntimeError("유효한 Instagram session cookie를 찾지 못했다.")
    return secret


def safe_error(exc, secret):
    message = f"{type(exc).__name__}: {exc}"
    return message.replace(secret, "[redacted-session]")[:2000] if secret else message[:2000]


def main():
    site_packages = Path(os.environ["CAROUSEL_PRIVATE_SITE_PACKAGES"]).resolve()
    if not site_packages.is_dir():
        raise RuntimeError("project-local instagrapi site-packages가 없다.")
    sys.path.insert(0, str(site_packages))
    from instagrapi import Client

    mode = os.environ.get("CAROUSEL_PRIVATE_MODE", "publish")
    account = os.environ["CAROUSEL_ACCOUNT"].strip().lstrip("@").lower()
    job = None
    paths = []
    if mode == "publish":
        job_path = Path(os.environ["CAROUSEL_JOB"]).resolve()
        job = json.loads(job_path.read_text(encoding="utf-8"))
        if job.get("backend") != "private_carousel" or job.get("status") != "submitting" or job.get("account") != account:
            raise RuntimeError("worker job 계약이 올바르지 않다.")
        if len(job.get("media", [])) not in (3, 4):
            raise RuntimeError("carousel은 PNG 3~4장이어야 한다.")
        for item in job["media"]:
            path = (job_path.parent / item["path"]).resolve()
            path.relative_to(job_path.parent.resolve())
            if not path.is_file() or path.suffix.lower() != ".png":
                raise RuntimeError("carousel media가 유효하지 않다.")
            paths.append(path)

    baseline = page_targets()
    try:
        active_before = current_tab().get("targetId")
    except Exception:
        active_before = None
    attached_target = None
    attached_session = None
    secret = None
    stage = "select_instagram_target"
    result = {"ok": False, "confirmed": False, "submission_started": False, "account": account, "backend": "private_carousel", "browser_mode": "existing_instagram_target_read_only", "session_persisted": False}
    try:
        target_info = instagram_target(account)
        stage = "attach_instagram_target"
        attached_target = target_info["targetId"]
        attached_session = cdp("Target.attachToTarget", targetId=attached_target, flatten=True)["sessionId"]
        session = attached_session
        stage = "enable_cdp_domains"
        cdp("Page.enable", session_id=session); cdp("Runtime.enable", session_id=session); cdp("Network.enable", session_id=session)
        profile = f"{ORIGIN}/{account}/"
        stage = "wait_for_existing_instagram_page"
        if not wait_until(session, "['interactive','complete'].includes(document.readyState)"):
            raise RuntimeError("기존 Instagram 탭 준비 timeout")
        ensure_account(session, account)
        stage = "read_session_cookie"
        secret = session_secret(session)
        stage = "confirm_private_client_account"
        client = Client(); client.request_timeout = 30
        if not client.login_by_sessionid(secret) or str(client.username or "").casefold() != account.casefold():
            raise RuntimeError("private client account 확인이 실패했다.")
        if mode == "probe":
            result.update({"ok": True, "confirmed": True, "probe_only": True, "stage": "private_session_confirmed", "final_url": profile})
        else:
            stage = "album_upload"
            result["submission_started"] = True
            published = client.album_upload(paths, job["caption"])
            code = str(getattr(published, "code", "") or "")
            pk = str(getattr(published, "pk", "") or "")
            if not code or not pk:
                raise RuntimeError("private API가 carousel 식별자를 반환하지 않았다.")
            result.update({"ok": True, "confirmed": True, "stage": "submitted", "confirmation_method": "private_album_upload_response", "media_pk": pk, "shortcode": code, "card_count": len(paths), "final_url": f"{ORIGIN}/p/{code}/"})
    except Exception as exc:
        result["error"] = safe_error(RuntimeError(f"{stage}: {type(exc).__name__}: {exc}"), secret)
    finally:
        secret = None
        if attached_session:
            try: cdp("Target.detachFromTarget", sessionId=attached_session)
            except Exception as exc: result["cleanup_error"] = safe_error(exc, None)
        try:
            after = page_targets()
            result["target_mode"] = "attached_existing_instagram_read_only"
            result["owned_target_closed"] = True
            result["existing_target_preserved"] = attached_target in after
            result["baseline_preserved"] = baseline.issubset(after)
            result["active_preserved"] = active_before == current_tab().get("targetId")
        except Exception:
            result["active_preserved"] = active_before is None
        if not (result.get("owned_target_closed") and result.get("existing_target_preserved") and result.get("baseline_preserved") and result.get("active_preserved")):
            result["ok"] = False; result["confirmed"] = False
            result.setdefault("error", "CDP target 정리 또는 focus 보존 검증에 실패했다.")
    print(PREFIX + json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] and result["confirmed"] else (5 if result["submission_started"] else 4)


raise SystemExit(main())
