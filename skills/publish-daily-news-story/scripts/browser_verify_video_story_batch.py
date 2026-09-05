"""Verify three published Instagram video Stories in one Edge background target."""

import base64
import json
import os
import re
import time
from pathlib import Path


PREFIX = "INSTAGRAM_VIDEO_STORY_BATCH_VERIFY="
STORY_COUNT = 3


def attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"](
        {"meta": "set_session", "session_id": sid, "target_id": target_id}
    )
    private["_mark_tab"]()


def read_state(story_url, pause=False):
    return js(
        """
(() => {
  const expected=EXPECTED_URL;
  const text=document.body?.innerText||'';
  const focus=document.hasFocus();
  const videos=[...document.querySelectorAll('video')];
  if(!focus && location.href===expected){
    for(const video of videos){
      video.muted=true;
      if(PAUSE_VIDEO){video.pause();}else{video.play().catch(()=>{});}
    }
  }
  return {
    url:location.href,
    focus,
    text:text.slice(0,3000),
    login:location.href.includes('/accounts/login')||!!document.querySelector('input[type=password]'),
    challenge:/(challenge|checkpoint)/.test(location.href),
    videos:videos.map(video=>({w:video.videoWidth,h:video.videoHeight,ready:video.readyState,duration:video.duration,paused:video.paused,currentTime:video.currentTime,error:video.error?.message||null}))
  };
})()
""".replace("EXPECTED_URL", json.dumps(story_url)).replace("PAUSE_VIDEO", json.dumps(pause))
    )


def video_loaded(state):
    return any(
        item.get("ready", 0) >= 2
        and item.get("w", 0) >= 500
        and item.get("h", 0) > item.get("w", 0)
        and 5.5 <= (item.get("duration") or 0) <= 6.5
        and (item.get("currentTime") or 0) > 0
        and not item.get("error")
        for item in state.get("videos", [])
    )


def state_failure(state, story_url, account):
    if state.get("focus") is not False:
        return "focus_changed"
    if state.get("login") or state.get("challenge"):
        return "authentication_required"
    if state.get("url") != story_url:
        return "story_url_mismatch"
    if not video_loaded(state) or account not in state.get("text", ""):
        return "video_not_ready"
    return None


account = os.environ["IG_ACCOUNT"].strip().lstrip("@").lower()
story_urls = json.loads(os.environ["IG_STORY_URLS_JSON"])
if not isinstance(story_urls, list) or len(story_urls) != STORY_COUNT:
    raise RuntimeError("Story public verification requires exactly three URLs")
expected_prefix = f"https://www.instagram.com/stories/{account}/"
if any(not re.fullmatch(re.escape(expected_prefix) + r"[0-9]+/", str(url)) for url in story_urls):
    raise RuntimeError("Story URL does not match IG_ACCOUNT")
if len(set(story_urls)) != STORY_COUNT:
    raise RuntimeError("Story public verification requires three distinct IDs")

shot_dir = Path(os.environ["IG_STORY_VERIFY_SCREENSHOT_DIR"]).resolve()
shot_dir.mkdir(parents=True, exist_ok=True)
previous = current_tab()["targetId"]
target_id = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
stories = []
try:
    attach_without_focus(target_id)
    for index, story_url in enumerate(story_urls, start=1):
        goto_url(story_url)
        wait_for_load()
        deadline = time.monotonic() + 20
        state = {}
        failure = "video_not_ready"
        while time.monotonic() < deadline:
            state = read_state(story_url)
            failure = state_failure(state, story_url, account)
            if failure != "video_not_ready":
                break
            time.sleep(0.35)
        screenshot = shot_dir / f"verified-{index:02d}.jpg"
        screenshot_error = None
        screenshot_written = False
        if failure is None:
            state = read_state(story_url, pause=True)
            failure = state_failure(state, story_url, account)
        if failure is None:
            try:
                shot = cdp(
                    "Page.captureScreenshot",
                    format="jpeg",
                    quality=72,
                    captureBeyondViewport=False,
                )
                screenshot.write_bytes(base64.b64decode(shot["data"], validate=True))
                screenshot_written = screenshot.stat().st_size > 0
            except Exception as exc:
                screenshot_error = f"{type(exc).__name__}: {exc}"[:1000]
            state = read_state(story_url, pause=True)
            failure = state_failure(state, story_url, account)
            if failure is None and not screenshot_written:
                failure = "screenshot_failed"
        record = {
            "index": index,
            "expected_url": story_url,
            "url": (state or {}).get("url"),
            "url_match": state.get("url") == story_url,
            "focus_preserved": (state or {}).get("focus") is False,
            "account_visible": account in (state or {}).get("text", ""),
            "video_loaded": video_loaded(state),
            "login_wall": bool((state or {}).get("login")),
            "challenge": bool((state or {}).get("challenge")),
            "videos": (state or {}).get("videos", []),
            "screenshot": str(screenshot) if screenshot_written else None,
            "screenshot_error": screenshot_error,
            "failure": failure,
        }
        record["ok"] = failure is None and screenshot_written
        stories.append(record)
        if not record["ok"]:
            break
finally:
    cdp("Target.closeTarget", targetId=target_id)
    attach_without_focus(previous)

result = {
    "ok": len(stories) == STORY_COUNT and all(item["ok"] for item in stories),
    "account": account,
    "story_count": len(stories),
    "stories": stories,
    "focus_preserved": all(item["focus_preserved"] for item in stories),
    "harness_processes": 1,
}
print(PREFIX + json.dumps(result, ensure_ascii=True))
if not result["ok"]:
    raise RuntimeError("published video Story batch verification failed")
