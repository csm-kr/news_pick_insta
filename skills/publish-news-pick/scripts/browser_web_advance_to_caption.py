"""Advance a verified Instagram carousel from crop to the caption stage."""

import json
import random
import time


def paced_wait(low=0.25, high=0.55):
    time.sleep(random.uniform(low, high))


def click_ax(name, roles=("button", "link")):
    for node in cdp("Accessibility.getFullAXTree").get("nodes", []):
        label = str((node.get("name") or {}).get("value") or "").strip()
        role = str((node.get("role") or {}).get("value") or "").strip()
        backend_id = node.get("backendDOMNodeId")
        if label != name or role not in roles or not backend_id:
            continue
        try:
            box = cdp("DOM.getBoxModel", backendNodeId=backend_id)["model"]["content"]
        except Exception:
            continue
        x, y = sum(box[0::2]) / 4, sum(box[1::2]) / 4
        if x < 0 or y < 0:
            continue
        click_at_xy(x, y)
        return {"name": name, "role": role, "x": x, "y": y, "backendDOMNodeId": backend_id}
    control = js(
        """
((name) => {
  const e=[...document.querySelectorAll('button,a,[role=button],[role=link],div,span')]
    .find(x=>{
      const r=x.getBoundingClientRect();
      return (x.innerText||'').trim()===name && r.width>0 && r.height>0 && r.x>=0 && r.y>=0;
    });
  if(!e)return null;
  const r=e.getBoundingClientRect();
  return {name,role:e.getAttribute('role')||e.tagName,x:r.x+r.width/2,y:r.y+r.height/2};
})(%s)
""" % json.dumps(name, ensure_ascii=False)
    )
    if control:
        click_at_xy(control["x"], control["y"])
        return {**control, "source": "dom"}
    raise RuntimeError(f"visible exact control not found: {name}")


def wait_state(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    state = None
    while time.monotonic() < deadline:
        paced_wait(0.2, 0.4)
        state = js(
            """
(() => {
  const text=document.body?.innerText||'';
  return {
    url:location.href,
    text:text.slice(0,6000),
    has_filter:text.includes('필터'),
    has_adjust:text.includes('조정'),
    has_original:text.includes('원본'),
    has_caption:!!document.querySelector('textarea,[role=textbox][contenteditable=true],[role=textbox][aria-label]'),
    has_share:text.includes('공유하기'),
    login_wall:location.href.includes('/accounts/login'),
    challenge:/(challenge|checkpoint)/.test(location.href)
  };
})()
"""
        )
        if state["login_wall"] or state["challenge"] or predicate(state):
            return state
    return state


targets = [
    item for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError(f"writable Instagram page target must be exactly one; found {len(targets)}")
switch_tab(targets[0]["targetId"], activate=True)

crop_next = click_ax("다음")
edit_state = wait_state(lambda value: value["has_filter"] and value["has_adjust"] and value["has_original"])
if not edit_state or not edit_state["has_filter"] or not edit_state["has_adjust"] or not edit_state["has_original"]:
    raise RuntimeError("Instagram edit/filter stage was not confirmed")

try:
    original = click_ax("원본", roles=("button", "link", "radio", "generic"))
except RuntimeError:
    original = js(
        """
(() => {
  const e=[...document.querySelectorAll('button,[role=button],[role=radio],div,span')]
    .find(x=>(x.innerText||'').trim()==='원본'&&x.getBoundingClientRect().width>0&&x.getBoundingClientRect().height>0);
  if(!e)return null;
  const r=e.getBoundingClientRect();
  return {name:'원본',role:e.getAttribute('role')||e.tagName,x:r.x+r.width/2,y:r.y+r.height/2};
})()
"""
    )
    if not original:
        raise RuntimeError("Original filter control was not found")
    click_at_xy(original["x"], original["y"])
paced_wait(0.35, 0.7)

edit_next = click_ax("다음")
caption_state = wait_state(lambda value: value["has_caption"] and value["has_share"])
print("INSTAGRAM_ADVANCE_TO_CAPTION=" + json.dumps({"crop_next": crop_next, "original": original, "edit_next": edit_next, "state": caption_state, "harness_processes": 1}, ensure_ascii=True))
if not caption_state or not caption_state["has_caption"] or not caption_state["has_share"] or caption_state["login_wall"] or caption_state["challenge"]:
    raise RuntimeError("Instagram caption/share stage was not confirmed")
