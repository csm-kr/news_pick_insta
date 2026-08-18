"""Run with: browser-harness < scripts/browser_web_preflight.py"""

import json
import os
import re
import time


ACCOUNT = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", ACCOUNT):
    raise RuntimeError("IG_ACCOUNT 형식이 올바르지 않다")
PROFILE_URL = f"https://www.instagram.com/{ACCOUNT}/"
MAX_RENDER_ATTEMPTS = 15


def attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"]({"meta": "set_session", "session_id": session_id, "target_id": target_id})
    private["_mark_tab"]()


def read_state():
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
    has_archive:text.includes('\uBCF4\uAD00\uD568 \uBCF4\uAE30'),
    has_professional_dashboard:text.includes('\uD504\uB85C\uD398\uC154\uB110 \uB300\uC2DC\uBCF4\uB4DC') || !!document.querySelector('[aria-label="\uD504\uB85C\uD398\uC154\uB110 \uB300\uC2DC\uBCF4\uB4DC"]'),
    has_create:controls.some(x=>x.text==='\uC0C8\uB85C\uC6B4 \uAC8C\uC2DC\uBB3C' || x.aria==='\uC0C8\uB85C\uC6B4 \uAC8C\uC2DC\uBB3C'),
    login_wall:url.includes('/accounts/login') || !!document.querySelector('input[type=password]'),
    challenge:/(challenge|checkpoint)/.test(url),
    post_count:(text.match(/\uAC8C\uC2DC\uBB3C\\s+([0-9,]+)/)||[])[1]||null
  };
})()
""" % json.dumps(ACCOUNT))
    ax_nodes = cdp("Accessibility.getFullAXTree").get("nodes", [])
    ax_names = {str((node.get("name") or {}).get("value") or "") for node in ax_nodes}
    state["has_create"] = state["has_create"] or "\uC0C8\uB85C\uC6B4 \uAC8C\uC2DC\uBB3C" in ax_names
    state["has_professional_dashboard"] = (
        state["has_professional_dashboard"]
        or "\uD504\uB85C\uD398\uC154\uB110 \uB300\uC2DC\uBCF4\uB4DC" in ax_names
    )
    state["owner_controls"] = bool(
        state["has_edit_profile"] or state["has_archive"] or state["has_professional_dashboard"]
    )
    state["ready"] = bool(
        state["account_visible"]
        and state["owner_controls"]
        and state["has_create"]
        and not state["login_wall"]
        and not state["challenge"]
    )
    return state

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
    if js("document.hasFocus()") is not False:
        raise RuntimeError("preflight target unexpectedly has focus")
    state = None
    for attempt in range(1, MAX_RENDER_ATTEMPTS + 1):
        time.sleep(1)
        state = read_state()
        state["render_attempts"] = attempt
        if state["ready"] or state["login_wall"] or state["challenge"]:
            break
    print("INSTAGRAM_WEB_PREFLIGHT=" + json.dumps(state, ensure_ascii=True))
    if not state["ready"]:
        raise RuntimeError(f"configured Chrome profile is not ready for @{ACCOUNT}")
finally:
    cdp("Target.closeTarget", targetId=target_id)
    attach_without_focus(previous)
