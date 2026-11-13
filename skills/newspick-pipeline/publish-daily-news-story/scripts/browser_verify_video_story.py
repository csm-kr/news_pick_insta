"""Verify a published Instagram video Story in a background target."""

import json
import os
import time


PREFIX = "INSTAGRAM_VIDEO_STORY_VERIFY="


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
    target_id = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
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
    deadline = time.time() + 20
    state = None
    while time.time() < deadline:
        state = js(
            """
            (() => {
              const text=document.body?.innerText||'';
              const videos=[...document.querySelectorAll('video')];
              for (const video of videos) {
                video.muted=true;
                video.play().catch(()=>{});
              }
              return {
                url:location.href,
                title:document.title,
                focus:document.hasFocus(),
                text:text.slice(0,3000),
                login:location.href.includes('/accounts/login')||!!document.querySelector('input[type=password]'),
                challenge:/(challenge|checkpoint)/.test(location.href),
                videos:videos.map(e=>({
                  w:e.videoWidth,h:e.videoHeight,ready:e.readyState,duration:e.duration,
                  paused:e.paused,currentTime:e.currentTime,networkState:e.networkState,
                  error:e.error?.message||null
                }))
              };
            })()
            """
        )
        video_loaded = any(
            video.get("ready", 0) >= 2
            and video.get("w", 0) >= 500
            and video.get("h", 0) >= 500
            for video in state.get("videos", [])
        )
        if account in state.get("text", "") and video_loaded:
            break
        time.sleep(0.5)
    video_loaded = bool(
        state
        and any(
            video.get("ready", 0) >= 2
            and video.get("w", 0) >= 500
            and video.get("h", 0) >= 500
            for video in state.get("videos", [])
        )
    )
    screenshot = os.environ["IG_STORY_VERIFY_SCREENSHOT"]
    screenshot_error = None
    screenshot_reused = os.path.isfile(screenshot)
    if not screenshot_reused:
        try:
            capture_screenshot(screenshot, full=False, max_dim=1800)
        except Exception as exc:
            screenshot_error = f"{type(exc).__name__}: {exc}"[:1000]
    result = {
        "account": account,
        "url": (state or {}).get("url"),
        "focus_preserved": (state or {}).get("focus") is False,
        "account_visible": account in (state or {}).get("text", ""),
        "video_loaded": video_loaded,
        "login_wall": bool((state or {}).get("login")),
        "challenge": bool((state or {}).get("challenge")),
        "videos": (state or {}).get("videos", []),
        "screenshot": screenshot,
        "screenshot_reused": screenshot_reused,
        "screenshot_error": screenshot_error,
    }
    result["ok"] = bool(
        result["focus_preserved"]
        and result["account_visible"]
        and result["video_loaded"]
        and not result["login_wall"]
        and not result["challenge"]
    )
    print(PREFIX + json.dumps(result, ensure_ascii=True))
    if not result["ok"]:
        raise RuntimeError("published video Story verification failed")
finally:
    close_background_tab(context)
