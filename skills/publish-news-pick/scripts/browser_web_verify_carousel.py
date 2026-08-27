"""Verify the public permalink and every carousel index in one Edge Harness run."""

import json
import os
import re
from pathlib import Path


def attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"]({"meta": "set_session", "session_id": session_id, "target_id": target_id})
    private["_mark_tab"]()


post_url = os.environ["IG_POST_URL"].split("?", 1)[0].rstrip("/") + "/"
expected = int(os.environ["IG_CARD_COUNT"])
caption_prefix = os.environ["IG_CAPTION_PREFIX"]
account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
require_ai = os.environ.get("IG_REQUIRE_AI_LABEL", "1") != "0"
if expected not in (3, 4):
    raise RuntimeError("IG_CARD_COUNT must be 3 or 4")
if not re.fullmatch(r"[a-z0-9._]+", account):
    raise RuntimeError("IG_ACCOUNT 형식이 올바르지 않다")
shot_dir = Path(os.environ["IG_SCREENSHOT_DIR"]).expanduser().resolve()
shot_dir.mkdir(parents=True, exist_ok=True)

previous_id = current_tab()["targetId"]
background_id = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
states = []
try:
    attach_without_focus(background_id)
    for index in range(1, expected + 1):
        goto_url(post_url + "?img_index=" + str(index))
        wait_for_load()
        if js("document.hasFocus()") is not False:
            raise RuntimeError("verification target unexpectedly has focus")
        state = js(
            """
(async (captionPrefix, account, expectedIndex, maxWait) => {
  const read = () => {
    const rect=e=>{const r=e.getBoundingClientRect();return {w:r.width,h:r.height}};
    const dots=[...document.querySelectorAll('div._acnb')].map(el=>({
      rect:rect(el),active:el.classList.contains('_acnf')
    })).filter(x=>x.rect.w===6&&x.rect.h===6);
    const text=document.body?.innerText||'';
    const images=[...document.images].filter(img=>{
      const r=img.getBoundingClientRect();
      return r.width>250&&r.height>250&&r.bottom>0&&r.right>0;
    });
    const mediaReady=images.some(img=>img.complete&&img.naturalWidth>400&&img.naturalHeight>400);
    return {
      dot_count:dots.length,
      active_index:dots.findIndex(x=>x.active),
      caption_match:text.includes(captionPrefix),
      account_visible:text.toLocaleLowerCase().includes(account),
      ai_label:text.includes('AI 콘텐츠'),
      login_wall:location.href.includes('/accounts/login')||!!document.querySelector('input[type=password]'),
      challenge:/(challenge|checkpoint)/.test(location.href),
      media_ready:mediaReady,
      url:location.href
    };
  };
  const deadline=performance.now()+maxWait;
  let attempts=0;
  let state=read();
  while ((!state.media_ready || !state.caption_match || state.active_index!==expectedIndex) &&
         !state.login_wall && !state.challenge && performance.now()<deadline) {
    attempts+=1;
    await new Promise(resolve=>setTimeout(resolve,220+Math.floor(Math.random()*181)));
    state=read();
  }
  return {...state,render_attempts:attempts+1};
})(%s,%s,%d,%d)
"""
            % (
                json.dumps(caption_prefix, ensure_ascii=False),
                json.dumps(account),
                index - 1,
                15000 if index == expected else 7000,
            )
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
    "account_match": all(state.get("account_visible") for state in states),
    "ai_label": all(state.get("ai_label") for state in states),
    "media_ready": all(state.get("media_ready") for state in states),
    "login_wall": any(state.get("login_wall") for state in states),
    "challenge": any(state.get("challenge") for state in states),
    "first_screenshot": states[0].get("screenshot"),
    "last_screenshot": states[-1].get("screenshot"),
    "visual_confirmation_required": True,
    "harness_processes": 1,
}
result["verified"] = bool(
    result["slide_count"] == expected
    and result["active_sequence"] == list(range(expected))
    and result["caption_match"]
    and result["account_match"]
    and (result["ai_label"] or not require_ai)
    and result["media_ready"]
    and not result["login_wall"]
    and not result["challenge"]
)
print("INSTAGRAM_CAROUSEL_VERIFY=" + json.dumps(result, ensure_ascii=True))
if not result["verified"]:
    raise RuntimeError("public carousel verification failed")
