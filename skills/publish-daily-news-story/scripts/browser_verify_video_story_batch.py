"""Verify three published Instagram video Stories in one Edge background target."""

import base64
import json
import os
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


account = os.environ["IG_ACCOUNT"].strip().lstrip("@").lower()
story_urls = json.loads(os.environ["IG_STORY_URLS_JSON"])
if not isinstance(story_urls, list) or len(story_urls) != STORY_COUNT:
    raise RuntimeError("Story public verification requires exactly three URLs")
expected_prefix = f"https://www.instagram.com/stories/{account}/"
if any(not str(url).startswith(expected_prefix) for url in story_urls):
    raise RuntimeError("Story URL does not match IG_ACCOUNT")

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
        if js("document.hasFocus()") is not False:
            raise RuntimeError("Story verification target unexpectedly has focus")
        deadline = time.monotonic() + 20
        state = None
        while time.monotonic() < deadline:
            state = js(
                """
(() => {
  const text=document.body?.innerText||'';
  const videos=[...document.querySelectorAll('video')];
  for(const video of videos){video.muted=true;video.play().catch(()=>{});}
  return {
    url:location.href,
    focus:document.hasFocus(),
    text:text.slice(0,3000),
    login:location.href.includes('/accounts/login')||!!document.querySelector('input[type=password]'),
    challenge:/(challenge|checkpoint)/.test(location.href),
    videos:videos.map(e=>({w:e.videoWidth,h:e.videoHeight,ready:e.readyState,duration:e.duration,paused:e.paused,currentTime:e.currentTime,error:e.error?.message||null}))
  };
})()
"""
            )
            loaded = any(
                item.get("ready", 0) >= 2
                and item.get("w", 0) >= 500
                and item.get("h", 0) >= 500
                for item in state.get("videos", [])
            )
            if loaded and account in state.get("text", ""):
                break
            time.sleep(0.35)
        screenshot = shot_dir / f"verified-{index:02d}.jpg"
        screenshot_error = None
        try:
            shot = cdp(
                "Page.captureScreenshot",
                format="jpeg",
                quality=72,
                captureBeyondViewport=False,
            )
            with open(screenshot, "wb") as handle:
                handle.write(base64.b64decode(shot["data"]))
        except Exception as exc:
            screenshot_error = f"{type(exc).__name__}: {exc}"[:1000]
        loaded = bool(
            state
            and any(
                item.get("ready", 0) >= 2
                and item.get("w", 0) >= 500
                and item.get("h", 0) >= 500
                for item in state.get("videos", [])
            )
        )
        record = {
            "index": index,
            "expected_url": story_url,
            "url": (state or {}).get("url"),
            "focus_preserved": (state or {}).get("focus") is False,
            "account_visible": account in (state or {}).get("text", ""),
            "video_loaded": loaded,
            "login_wall": bool((state or {}).get("login")),
            "challenge": bool((state or {}).get("challenge")),
            "videos": (state or {}).get("videos", []),
            "screenshot": str(screenshot),
            "screenshot_error": screenshot_error,
        }
        record["ok"] = bool(
            record["focus_preserved"]
            and record["account_visible"]
            and record["video_loaded"]
            and not record["login_wall"]
            and not record["challenge"]
            and screenshot.is_file()
        )
        stories.append(record)
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
