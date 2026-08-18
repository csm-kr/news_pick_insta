"""Verify every public carousel index and capture the first and last cards."""

import json
import os
import time
from pathlib import Path


def attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"](
        {"meta": "set_session", "session_id": session_id, "target_id": target_id}
    )
    private["_mark_tab"]()


post_url = os.environ["IG_POST_URL"].split("?", 1)[0].rstrip("/") + "/"
expected = int(os.environ["IG_CARD_COUNT"])
caption_prefix = os.environ["IG_CAPTION_PREFIX"]
if expected not in (3, 4):
    raise RuntimeError("IG_CARD_COUNT must be 3 or 4")
shot_dir = Path(os.environ["IG_SCREENSHOT_DIR"]).expanduser().resolve()
shot_dir.mkdir(parents=True, exist_ok=True)
targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError("Instagram page target count is " + str(len(targets)))
previous_id = targets[0]["targetId"]
background_id = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
states = []
try:
    attach_without_focus(background_id)
    for index in range(1, expected + 1):
        goto_url(post_url + "?img_index=" + str(index))
        wait_for_load()
        time.sleep(5)
        if index == expected:
            time.sleep(10)
        if js("document.hasFocus()") is not False:
            raise RuntimeError("verification target unexpectedly has focus")
        state = js(
            """
((captionPrefix) => {
  const rect=e=>{const r=e.getBoundingClientRect();return {w:r.width,h:r.height}};
  const dots=[...document.querySelectorAll('div._acnb')].map(el=>({
    rect:rect(el),active:el.classList.contains('_acnf')
  })).filter(x=>x.rect.w===6&&x.rect.h===6);
  const text=document.body?.innerText||'';
  return {dot_count:dots.length,active_index:dots.findIndex(x=>x.active),caption_match:text.includes(captionPrefix),ai_label:text.includes('AI 콘텐츠'),url:location.href};
})(%s)
""" % json.dumps(caption_prefix, ensure_ascii=False)
        )
        if index in {1, expected}:
            screenshot = shot_dir / f"public-card-{index:02d}.png"
            capture_screenshot(str(screenshot), full=False, max_dim=1800)
            state["screenshot"] = str(screenshot)
        states.append(state)
finally:
    cdp("Target.closeTarget", targetId=background_id)
    attach_without_focus(previous_id)

result = {
    "slide_count": states[-1].get("dot_count"),
    "active_sequence": [state.get("active_index") for state in states],
    "caption_match": all(state.get("caption_match") for state in states),
    "ai_label": all(state.get("ai_label") for state in states),
    "first_screenshot": states[0].get("screenshot"),
    "last_screenshot": states[-1].get("screenshot"),
    "visual_confirmation_required": True,
}
print("INSTAGRAM_CAROUSEL_VERIFY=" + json.dumps(result, ensure_ascii=True))
if result["slide_count"] != expected or result["active_sequence"] != list(range(expected)) or not result["caption_match"] or not result["ai_label"]:
    raise RuntimeError("public carousel verification failed")
