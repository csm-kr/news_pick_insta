import json
import os
import time


def attach_target(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"](
        {"meta": "set_session", "session_id": session_id, "target_id": target_id}
    )
    private["_mark_tab"]()


targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError("Instagram page target count is " + str(len(targets)))
attach_target(targets[0]["targetId"])

caption = open(os.environ["IG_CAPTION_FILE"], "r", encoding="utf-8").read()
if "AI로 재구성한 인포그래픽" in caption:
    raise RuntimeError("forbidden caption disclosure phrase is present")
field = js(
    """
(() => {
  const e=document.querySelector('textarea,[role=textbox][contenteditable=true],[role=textbox][aria-label]');
  if(!e) return null;
  const r=e.getBoundingClientRect();
  const text=typeof e.value==='string'?e.value:(e.innerText||e.textContent||'');
  return {x:r.x,y:r.y,w:r.width,h:r.height,text};
})()
"""
)
if not field:
    raise RuntimeError("caption textbox was not found")
click_at_xy(field["x"] + 18, field["y"] + 18)
press_key("a", modifiers=2)
press_key("Backspace")
type_text(caption)
time.sleep(3)

switch = js(
    """
(() => {
  const e=document.querySelector('[role=switch],input[type=checkbox]');
  if(!e) return null;
  const r=e.getBoundingClientRect();
  return {x:r.x,y:r.y,w:r.width,h:r.height,checked:e.checked===true||e.getAttribute('aria-checked')==='true'};
})()
"""
)
if not switch:
    raise RuntimeError("AI label switch was not found")
if not switch["checked"]:
    click_at_xy(switch["x"] + switch["w"] / 2, switch["y"] + switch["h"] / 2)
    time.sleep(2)

state = js(
    """
(() => {
  const e=document.querySelector('textarea,[role=textbox][contenteditable=true],[role=textbox][aria-label]');
  const caption=e?(typeof e.value==='string'?e.value:(e.innerText||e.textContent||'')):'';
  const s=document.querySelector('[role=switch],input[type=checkbox]');
  const text=document.body?.innerText||'';
  return {
    caption,caption_chars:caption.length,
    ai_checked:!!(s&&(s.checked===true||s.getAttribute('aria-checked')==='true')),
    has_share:text.includes('공유하기'),url:location.href
  };
})()
"""
)
state["caption_matches"] = state.get("caption") == caption
state["expected_chars"] = len(caption)
print("INSTAGRAM_CAPTION_AI=" + json.dumps(state, ensure_ascii=True))
if not state["caption_matches"] or not state["ai_checked"] or not state["has_share"]:
    raise RuntimeError("caption or AI label pre-submit verification failed")
