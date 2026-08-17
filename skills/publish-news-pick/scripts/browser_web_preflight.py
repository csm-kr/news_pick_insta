"""Run with: browser-harness < scripts/browser_web_preflight.py"""

import json
import os
import re
import time


ACCOUNT = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", ACCOUNT):
    raise RuntimeError("IG_ACCOUNT 형식이 올바르지 않다")
PROFILE_URL = f"https://www.instagram.com/{ACCOUNT}/"


def attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"]({"meta": "set_session", "session_id": session_id, "target_id": target_id})
    private["_mark_tab"]()

targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError(f"writable Instagram page target must be exactly one; found {len(targets)}")

previous = current_tab()["targetId"]
target_id = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
try:
    attach_without_focus(target_id)
    goto_url(PROFILE_URL)
    wait_for_load()
    time.sleep(4)
    if js("document.hasFocus()") is not False:
        raise RuntimeError("preflight target unexpectedly has focus")
    state = js("""
(() => {
  const text = document.body?.innerText || '';
  const controls = [...document.querySelectorAll('a,button,[role=button]')].map(e => ({
    text:(e.innerText||'').trim(),
    aria:e.getAttribute('aria-label')||'',
    href:e.href||''
  }));
  const url = location.href;
  return {
    url,
    account_visible:text.includes(%s),
    has_edit_profile:text.includes('\uD504\uB85C\uD544 \uD3B8\uC9D1') || controls.some(x=>x.href.includes('/accounts/edit')),
    has_create:controls.some(x=>x.text==='\uC0C8\uB85C\uC6B4 \uAC8C\uC2DC\uBB3C' || x.aria==='\uC0C8\uB85C\uC6B4 \uAC8C\uC2DC\uBB3C'),
    login_wall:url.includes('/accounts/login') || !!document.querySelector('input[type=password]'),
    challenge:/(challenge|checkpoint)/.test(url),
    post_count:(text.match(/\uAC8C\uC2DC\uBB3C\\s+([0-9,]+)/)||[])[1]||null
  };
})()
""" % json.dumps(ACCOUNT))
    ax_nodes = cdp("Accessibility.getFullAXTree").get("nodes", [])
    ax_names = {str((node.get("name") or {}).get("value") or "") for node in ax_nodes}
    state["has_create"] = "\uC0C8\uB85C\uC6B4 \uAC8C\uC2DC\uBB3C" in ax_names
    state["ready"] = bool(
        state.get("account_visible")
        and state.get("has_edit_profile")
        and state.get("has_create")
        and not state.get("login_wall")
        and not state.get("challenge")
    )
    print("INSTAGRAM_WEB_PREFLIGHT=" + json.dumps(state, ensure_ascii=True))
    if not state["ready"]:
        raise RuntimeError(f"configured Chrome profile is not ready for @{ACCOUNT}")
finally:
    cdp("Target.closeTarget", targetId=target_id)
    attach_without_focus(previous)
