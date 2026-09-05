import json
import os
import random
import time


def read_ai_switch():
    return js(
        """
(() => {
  const root=document.querySelector('[role=dialog]');
  if(!root)return null;
  const labels=['AI 라벨 추가','AI 레이블 추가','Add AI label'];
  const lines=(root.innerText||'').split('\\n').map(line=>line.trim());
  const label=labels.find(value=>lines.includes(value));
  const switches=[...root.querySelectorAll('[role=switch],input[type=checkbox]')];
  if(!label||switches.length!==1)return null;
  const element=switches[0];
  const rect=element.getBoundingClientRect();
  const style=getComputedStyle(element);
  const x=rect.x+rect.width/2,y=rect.y+rect.height/2;
  const hit=document.elementFromPoint(x,y);
  return {
    label,x,y,
    checked:typeof element.checked==='boolean'?element.checked:element.getAttribute('aria-checked')==='true',
    visible:rect.width>0&&rect.height>0&&x>=0&&y>=0&&x<innerWidth&&y<innerHeight&&style.display!=='none'&&style.visibility!=='hidden',
    disabled:element.disabled===true||element.getAttribute('aria-disabled')==='true',
    hit_matches:!!hit&&(hit===element||element.contains(hit))
  };
})()
"""
    )


def ensure_ai_label():
    clicks = 0
    while True:
        state = read_ai_switch()
        if not state:
            raise RuntimeError("unambiguous AI label switch was not found")
        if state["checked"]:
            return {**state, "clicks": clicks}
        if clicks >= 2 or not state["visible"] or state["disabled"] or not state["hit_matches"]:
            print("INSTAGRAM_AI_SWITCH_DIAGNOSTIC=" + json.dumps({**state, "clicks": clicks}, ensure_ascii=True))
            raise RuntimeError("AI label remains off or is not actionable; preserve caption and do not share")
        click_at_xy(state["x"], state["y"])
        clicks += 1
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            time.sleep(random.uniform(0.22, 0.36))
            state = read_ai_switch()
            if not state:
                raise RuntimeError("AI label switch disappeared; do not retry")
            if state["checked"]:
                return {**state, "clicks": clicks}


targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError("Instagram page target count is " + str(len(targets)))
switch_tab(targets[0]["targetId"], activate=True)

with open(os.environ["IG_CAPTION_FILE"], "r", encoding="utf-8") as handle:
    caption = handle.read()
if "AI로 재구성한 인포그래픽" in caption:
    raise RuntimeError("forbidden caption disclosure phrase is present")


def normalize_editor_text(value):
    return str(value or "").replace("\r\n", "\n").rstrip("\n")


def read_caption():
    return js(
        """
(() => {
  const e=document.querySelector('textarea,[role=textbox][contenteditable=true],[role=textbox][aria-label]');
  return e?(typeof e.value==='string'?e.value:(e.innerText||e.textContent||'')):'';
})()
"""
    )


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
input_method = "existing_exact_caption"
if normalize_editor_text(field.get("text")) != normalize_editor_text(caption):
    click_at_xy(field["x"] + 18, field["y"] + 18)
    press_key("a", modifiers=2)
    press_key("Backspace")
    type_text(caption)
    time.sleep(random.uniform(0.45, 0.85))
    input_method = "type_text"

# Instagram의 Lexical 편집기는 CDP text insertion에서 줄바꿈만 남기는 경우가 있다.
# 실제 값이 다를 때만 사용자가 붙여넣은 것과 같은 paste event로 한 번 대체한다.
if normalize_editor_text(read_caption()) != normalize_editor_text(caption):
    click_at_xy(field["x"] + 18, field["y"] + 18)
    press_key("a", modifiers=2)
    press_key("Backspace")
    paste = js(
        """
((text) => {
  const e=document.querySelector('textarea,[role=textbox][contenteditable=true],[role=textbox][aria-label]');
  if(!e) return {ok:false,error:'caption textbox disappeared'};
  e.focus();
  if(typeof DataTransfer==='undefined' || typeof ClipboardEvent==='undefined') {
    return {ok:false,error:'clipboard event API unavailable'};
  }
  const data=new DataTransfer();
  data.setData('text/plain',text);
  const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});
  e.dispatchEvent(event);
  return {ok:true};
})(%s)
"""
        % json.dumps(caption, ensure_ascii=False)
    )
    if not paste or not paste.get("ok"):
        raise RuntimeError("caption paste fallback failed: " + str((paste or {}).get("error")))
    input_method = "clipboard_event"
    time.sleep(random.uniform(0.65, 1.15))

if normalize_editor_text(read_caption()) != normalize_editor_text(caption):
    raise RuntimeError("caption mismatch; AI label and Share were not touched")
ai_switch = ensure_ai_label()

state = js(
    """
(() => {
  const e=document.querySelector('textarea,[role=textbox][contenteditable=true],[role=textbox][aria-label]');
  const caption=e?(typeof e.value==='string'?e.value:(e.innerText||e.textContent||'')):'';
  const text=document.body?.innerText||'';
  return {
    caption,caption_chars:caption.length,
    has_share:text.includes('공유하기'),url:location.href
  };
})()
"""
)
state["caption_matches"] = normalize_editor_text(state.get("caption")) == normalize_editor_text(caption)
state["ai_checked"] = bool((read_ai_switch() or {}).get("checked"))
state["ai_switch_clicks"] = ai_switch["clicks"]
state["expected_chars"] = len(caption)
state["input_method"] = input_method
state["harness_processes"] = 1
print("INSTAGRAM_CAPTION_AI=" + json.dumps(state, ensure_ascii=True))
if not state["caption_matches"] or not state["ai_checked"] or not state["has_share"]:
    raise RuntimeError("caption or AI label pre-submit verification failed")
