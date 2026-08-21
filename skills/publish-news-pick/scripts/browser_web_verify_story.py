"""Verify a published Instagram Story in a background browser target."""

import json
import os
import time


def _attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"](
        {"meta": "set_session", "session_id": sid, "target_id": target_id}
    )
    private["_mark_tab"]()
    return sid


def new_background_tab(url):
    previous = current_tab()["targetId"]
    target_id = cdp(
        "Target.createTarget", url="about:blank", background=True
    )["targetId"]
    _attach_without_focus(target_id)
    goto_url(url)
    wait_for_load()
    return {"targetId": target_id, "previousTargetId": previous}


def close_background_tab(context):
    cdp("Target.closeTarget", targetId=context["targetId"])
    _attach_without_focus(context["previousTargetId"])


account = os.environ["IG_ACCOUNT"].strip().lstrip("@").lower()
story_url = os.environ["IG_STORY_URL"]
expected_prefix = f"https://www.instagram.com/stories/{account}/"
if not story_url.startswith(expected_prefix):
    raise RuntimeError("Story URL does not match IG_ACCOUNT")

context = new_background_tab(story_url)
try:
    if js("document.hasFocus()") is not False:
        raise RuntimeError("focus safety failure")
    deadline = time.time() + 15
    state = None
    while time.time() < deadline:
        state = js(
            """
            (() => {
              const text=document.body?.innerText||'';
              return {
                url:location.href,
                title:document.title,
                focus:document.hasFocus(),
                text:text.slice(0,3000),
                login:location.href.includes('/accounts/login')||!!document.querySelector('input[type=password]'),
                challenge:/(challenge|checkpoint)/.test(location.href),
                images:[...document.querySelectorAll('img')].map(e=>({alt:e.alt||'',w:e.naturalWidth,h:e.naturalHeight})).filter(e=>e.w>0&&e.h>0),
                surfaces:[...document.querySelectorAll('*')].map(e=>{const r=e.getBoundingClientRect();const bg=getComputedStyle(e).backgroundImage;return {tag:e.tagName,w:Math.round(r.width),h:Math.round(r.height),bg:bg&&bg!=='none'};}).filter(e=>e.w>=300&&e.h>=300&&e.bg),
                videos:[...document.querySelectorAll('video')].map(e=>({w:e.videoWidth,h:e.videoHeight,ready:e.readyState}))
              };
            })()
            """
        )
        media_loaded = (
            any(image.get("w", 0) >= 500 for image in state.get("images", []))
            or state.get("surfaces")
            or any(video.get("ready", 0) >= 2 for video in state.get("videos", []))
        )
        if account in state.get("text", "") and media_loaded:
            break
        time.sleep(0.5)
    media_loaded = bool(
        state
        and (
            any(image.get("w", 0) >= 500 for image in state.get("images", []))
            or state.get("surfaces")
            or any(video.get("ready", 0) >= 2 for video in state.get("videos", []))
        )
    )
    shot = os.environ["IG_STORY_VERIFY_SCREENSHOT"]
    capture_screenshot(shot, full=False, max_dim=1800)
    result = {
        "account": account,
        "url": (state or {}).get("url"),
        "focus_preserved": (state or {}).get("focus") is False,
        "account_visible": account in (state or {}).get("text", ""),
        "media_loaded": media_loaded,
        "login_wall": bool((state or {}).get("login")),
        "challenge": bool((state or {}).get("challenge")),
        "images": (state or {}).get("images", []),
        "screenshot": shot,
    }
    result["ok"] = bool(
        result["focus_preserved"]
        and result["account_visible"]
        and result["media_loaded"]
        and not result["login_wall"]
        and not result["challenge"]
    )
    print("INSTAGRAM_STORY_VERIFY=" + json.dumps(result, ensure_ascii=True))
    if not result["ok"]:
        raise RuntimeError("published Story verification failed")
finally:
    close_background_tab(context)
