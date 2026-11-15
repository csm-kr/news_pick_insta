"""이미 열린 작성기를 읽기 위주로 확인한다. 만들기·업로드·공유는 누르지 않는다.

IG_COMPOSER_CHECK=gallery   : 업로드 직후 `미디어 갤러리 열기`로 썸네일 5장을 확인하고 갤러리를 반드시 닫는다.
IG_COMPOSER_CHECK=pre_share : caption 단계에서 caption·AI 라벨·공유 버튼을 대조하고 첫·마지막 카드를 캡처한다.
screenshot은 IG_COMPOSER_SCREENSHOT_DIR에 남긴다.
"""
import base64
import json
import os
import time
from pathlib import Path

mode = os.environ["IG_COMPOSER_CHECK"]
dest = Path(os.environ["IG_COMPOSER_SCREENSHOT_DIR"])
dest.mkdir(parents=True, exist_ok=True)

targets = [t for t in cdp("Target.getTargets").get("targetInfos", [])
           if t.get("type") == "page" and "instagram.com" in str(t.get("url") or "")]
if len(targets) != 1:
    raise RuntimeError("composer check requires one dedicated Instagram target")
switch_tab(targets[0]["targetId"], activate=True)


def shot(name):
    data = cdp("Page.captureScreenshot", format="jpeg", quality=72, captureBeyondViewport=False)["data"]
    (dest / name).write_bytes(base64.b64decode(data))


THUMBS = ("[...document.querySelector('[role=dialog]').querySelectorAll('*')].filter(e=>{const r=e.getBoundingClientRect();"
          "return /blob:/.test(getComputedStyle(e).backgroundImage)&&r.width>30&&r.width<160&&r.height>30&&r.height<180;})")


def gallery_control():
    return js("""/*gallery-control*/(()=>{const a=[...document.querySelectorAll('[role=dialog] svg[aria-label="미디어 갤러리 열기"]')];
if(a.length!==1)return null;const e=a[0].closest('button,[role=button]')||a[0];const r=e.getBoundingClientRect();
return {x:r.x+r.width/2,y:r.y+r.height/2};})()""")


def gallery_open():
    return js("/*gallery-open*/" + THUMBS + ".length>=5")


if mode == "gallery":
    control = gallery_control()
    if not control:
        raise RuntimeError("exact media gallery control is absent")
    if not gallery_open():
        click_at_xy(control["x"], control["y"])
        time.sleep(0.35)
    try:
        state = js("/*gallery-state*/(()=>{const nodes=" + THUMBS + r""";
const items=nodes.map(n=>{const m=getComputedStyle(n).backgroundImage.match(/url\(["']?(blob:[^"')]+)["']?\)/);return {source:m?.[1]};}).filter(v=>v.source);
let e=nodes[0]?.parentElement;const d=document.querySelector('[role=dialog]');
while(e&&d.contains(e)&&e.scrollWidth<=e.clientWidth+1)e=e.parentElement;
const scrollable=!!(e&&d.contains(e));if(scrollable)e.setAttribute('data-newspick-gallery-scroller','1');
return {count:new Set(items.map(v=>v.source)).size,items,scrollable};})()""")
        shot("gallery-left.jpg")
        if state.get("scrollable"):
            js("/*gallery-scroll*/document.querySelector('[data-newspick-gallery-scroller]').scrollLeft=100000")
            time.sleep(0.25)
            shot("gallery-right.jpg")
    finally:
        # 여기서는 갤러리가 열려 있으므로 결과와 상관없이 한 번 닫아 crop 단계로 돌려 둔다.
        control = gallery_control()
        if control:
            click_at_xy(control["x"], control["y"])
            time.sleep(0.25)
    if state.get("count") != 5:
        raise RuntimeError("gallery does not contain five distinct media: " + json.dumps(state))
    (dest / "gallery.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print("INSTAGRAM_COMPOSER_GALLERY=" + json.dumps({"count": state["count"], "closed": True}))

elif mode == "pre_share":
    expected = Path(os.environ["IG_CAPTION_FILE"]).read_text(encoding="utf-8").rstrip("\n")
    state = js("""/*pre-share-state*/(()=>{const d=document.querySelector('[role=dialog]');
const e=d?.querySelector('textarea,[role=textbox][contenteditable=true]');
return {caption:e?(typeof e.value==='string'?e.value:e.innerText):null,
ai:[...d.querySelectorAll('input[role=switch],[role=switch]')].map(s=>({checked:s.checked===true||s.getAttribute('aria-checked')==='true'})),
has_share:[...d.querySelectorAll('button,[role=button]')].some(b=>(b.innerText||b.getAttribute('aria-label')||'').trim()==='공유하기')};})()""")
    if (state.get("caption") or "").rstrip("\n") != expected:
        raise RuntimeError("pre-share caption does not match the approved caption")
    if not any(s.get("checked") for s in state.get("ai", [])):
        raise RuntimeError("AI label switch is not on")
    if not state.get("has_share"):
        raise RuntimeError("share button is not visible")

    def step(direction):
        label = "오른쪽 방향 아이콘" if direction == "right" else "왼쪽 방향 아이콘"
        point = js(f"""/*arrow:{direction}*/(()=>{{const a=[...document.querySelectorAll('[role=dialog] svg[aria-label="{label}"]')]
.map(s=>s.closest('button,[role=button]')||s).filter(e=>{{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.x>=0&&r.right<innerWidth;}});
if(a.length!==1)return null;const r=a[0].getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}};}})()""")
        if not point:
            raise RuntimeError(f"unambiguous {direction} carousel arrow is absent")
        click_at_xy(point["x"], point["y"])
        time.sleep(0.4)

    shot("pre-share-first.jpg")
    for _ in range(4):
        step("right")
    shot("pre-share-last.jpg")
    for _ in range(4):
        step("left")
    shot("pre-share-confirmed.jpg")
    print("INSTAGRAM_PRE_SHARE=" + json.dumps({"caption_chars": len(expected), "caption_matches": True,
                                               "ai_checked": True, "share_visible": True, "visited_first_and_last": True}))
else:
    raise RuntimeError("IG_COMPOSER_CHECK must be gallery or pre_share")
