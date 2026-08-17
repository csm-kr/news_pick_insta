"""Read-only permalink verification in a background Browser Harness target."""

import json
import os
import re
import time


def attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"]({"meta": "set_session", "session_id": session_id, "target_id": target_id})
    private["_mark_tab"]()


post_url = os.environ["IG_POST_URL"]
caption_prefix = os.environ["IG_CAPTION_PREFIX"]
account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", account):
    raise RuntimeError("IG_ACCOUNT 형식이 올바르지 않다")
require_ai = os.environ.get("IG_REQUIRE_AI_LABEL", "1") != "0"
shot = os.environ.get("IG_SCREENSHOT")
previous = current_tab()["targetId"]
target_id = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
try:
    attach_without_focus(target_id)
    goto_url(post_url)
    wait_for_load()
    time.sleep(4)
    if js("document.hasFocus()") is not False:
        raise RuntimeError("verification target unexpectedly has focus")
    state = js("""
    (() => {
      const text=document.body?.innerText||'';
      return {
        url:location.href,
        account_visible:text.includes(%s),
        caption_match:text.includes(%s),
        ai_label:text.includes('AI \uCF58\uD150\uCE20'),
        login_wall:location.href.includes('/accounts/login') || !!document.querySelector('input[type=password]'),
        challenge:/(challenge|checkpoint)/.test(location.href)
      };
    })()
    """ % (json.dumps(account), json.dumps(caption_prefix, ensure_ascii=False)))
    state["verified"] = bool(
        state.get("account_visible")
        and state.get("caption_match")
        and (state.get("ai_label") or not require_ai)
        and not state.get("login_wall")
        and not state.get("challenge")
    )
    if shot:
        capture_screenshot(shot, full=False, max_dim=1800)
        state["screenshot"] = shot
    print("INSTAGRAM_WEB_VERIFY=" + json.dumps(state, ensure_ascii=True))
    if not state["verified"]:
        raise RuntimeError("public permalink verification failed")
finally:
    cdp("Target.closeTarget", targetId=target_id)
    attach_without_focus(previous)
