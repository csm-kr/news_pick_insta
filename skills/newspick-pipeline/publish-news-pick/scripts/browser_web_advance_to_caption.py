"""Select Instagram 4:5 explicitly, then advance to the caption stage."""

import base64
import json
import os
import random
import time


def paced_wait(low=0.22, high=0.48):
    """Keep interaction brisk without producing zero-delay click bursts."""
    time.sleep(random.uniform(low, high))


def visible_control(names, selectors):
    """Return one exact, visible control from the active composer dialog."""
    return js(
        """
((args) => {
  const root=document.querySelector('[role=dialog]')||document;
  const visible=e=>{
    const r=e.getBoundingClientRect();
    const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&r.right>0&&r.bottom>0&&r.left<innerWidth&&r.top<innerHeight&&s.visibility!=='hidden'&&s.display!=='none';
  };
  const label=e=>(e.getAttribute('aria-label')||e.getAttribute('title')||e.querySelector('svg[aria-label]')?.getAttribute('aria-label')||e.innerText||'').trim();
  const matches=[...root.querySelectorAll(args.selectors)]
    .filter(e=>visible(e)&&args.names.includes(label(e)))
    .sort((a,b)=>a.getBoundingClientRect().width*a.getBoundingClientRect().height-b.getBoundingClientRect().width*b.getBoundingClientRect().height);
  const e=matches[0];
  if(!e)return null;
  const r=e.getBoundingClientRect();
  return {name:label(e),role:e.getAttribute('role')||e.tagName,x:r.x+r.width/2,y:r.y+r.height/2,source:'dom'};
})(%s)
"""
        % json.dumps({"names": list(names), "selectors": selectors}, ensure_ascii=False)
    )


def click_control(name, roles=("button", "link")):
    control = visible_control(
        [name], "button,a,[role=button],[role=link],[role=radio]"
    )
    if control:
        click_at_xy(control["x"], control["y"])
        return control

    # DOM is the fast path. AX is one bounded fallback for localized builds
    # where Instagram exposes the control name only through accessibility.
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
        return {
            "name": name,
            "role": role,
            "x": x,
            "y": y,
            "backendDOMNodeId": backend_id,
            "source": "ax_fallback",
        }
    raise RuntimeError(f"visible exact control not found: {name}")


def read_stage_state():
    return js(
        """
(() => {
  const root=document.querySelector('[role=dialog]')||document.body;
  const text=root?.innerText||'';
  return {
    url:location.href,
    has_filter:text.includes('필터'),
    has_adjust:text.includes('조정'),
    has_original:text.includes('원본'),
    has_caption:!!root?.querySelector('textarea,[role=textbox][contenteditable=true],[role=textbox][aria-label]'),
    has_share:text.includes('공유하기'),
    login_wall:location.href.includes('/accounts/login'),
    challenge:/(challenge|checkpoint)/.test(location.href)
  };
})()
"""
    )


def wait_state(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    state = None
    while time.monotonic() < deadline:
        paced_wait(0.22, 0.36)
        state = read_stage_state()
        if state["login_wall"] or state["challenge"] or predicate(state):
            return state
    return state


def read_portrait_media_state():
    expected_ratio = float(os.environ.get("IG_EXPECTED_MEDIA_RATIO", "0.8"))
    if not 0.78 <= expected_ratio <= 0.82:
        raise RuntimeError("IG_EXPECTED_MEDIA_RATIO must describe exact 4:5 input media")
    return js(
        r"""
((expectedRatio) => {
  const root=document.querySelector('[role=dialog]')||document;
  const visible=r=>r.width>350&&r.height>450&&r.right>0&&r.bottom>0&&r.left<innerWidth&&r.top<innerHeight;
  const images=[...root.querySelectorAll('img')].map(img=>{
    const r=img.getBoundingClientRect();
    return {
      source:'img',natural_w:img.naturalWidth||0,natural_h:img.naturalHeight||0,
      natural_ratio:img.naturalHeight?img.naturalWidth/img.naturalHeight:0,
      natural_verified_by:'dom_image',x:r.x,y:r.y,w:r.width,h:r.height,
      render_ratio:r.height?r.width/r.height:0,area:r.width*r.height
    };
  }).filter(x=>visible({width:x.w,height:x.h,right:x.x+x.w,bottom:x.y+x.h,left:x.x,top:x.y}));
  const backgrounds=[...root.querySelectorAll('div,section,article')].map(el=>{
    const r=el.getBoundingClientRect();
    const background=getComputedStyle(el).backgroundImage||'';
    if(!visible(r)||background==='none'||!/^url\(/.test(background))return null;
    const match=background.match(/^url\(["']?(.*?)["']?\)$/);
    return {
      source:'css_background',background_url_scheme:(match?.[1]||'').split(':',1)[0]||'unknown',
      natural_w:0,natural_h:0,natural_ratio:expectedRatio,
      natural_verified_by:'expected_4x5_input',x:r.x,y:r.y,w:r.width,h:r.height,
      render_ratio:r.height?r.width/r.height:0,area:r.width*r.height
    };
  }).filter(Boolean);
  return [...images,...backgrounds].sort((a,b)=>b.area-a.area)[0]||null;
})(%s)
"""
        % json.dumps(expected_ratio)
    )


def select_portrait_4x5():
    option_selectors = "button,[role=button],[role=radio],[role=option],li,div,span"
    option = visible_control(["4:5"], option_selectors)
    control = None
    if not option:
        allowed = [
            "자르기",
            "자르기 선택",
            "비율 선택",
            "화면 비율 선택",
            "가로 세로 비율 선택",
            "Crop",
            "Select crop",
            "Select aspect ratio",
        ]
        control = visible_control(allowed, "button,[role=button]")
        if control:
            click_at_xy(control["x"], control["y"])
        else:
            for node in cdp("Accessibility.getFullAXTree").get("nodes", []):
                label = str((node.get("name") or {}).get("value") or "").strip()
                role = str((node.get("role") or {}).get("value") or "").strip()
                backend_id = node.get("backendDOMNodeId")
                if label not in allowed or role not in {"button", "link", "generic"} or not backend_id:
                    continue
                try:
                    box = cdp("DOM.getBoxModel", backendNodeId=backend_id)["model"]["content"]
                except Exception:
                    continue
                x, y = sum(box[0::2]) / 4, sum(box[1::2]) / 4
                if x < 0 or y < 0:
                    continue
                control = {
                    "name": label,
                    "role": role,
                    "x": x,
                    "y": y,
                    "backendDOMNodeId": backend_id,
                    "source": "ax_fallback",
                }
                click_at_xy(x, y)
                break
        if not control:
            raise RuntimeError("Instagram crop ratio control was not found; nothing advanced")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            paced_wait(0.22, 0.36)
            option = visible_control(["4:5"], option_selectors)
            if option:
                break
    if not option:
        raise RuntimeError("exact Instagram 4:5 option was not found; nothing advanced")

    click_at_xy(option["x"], option["y"])
    deadline = time.monotonic() + 5
    media = None
    while time.monotonic() < deadline:
        paced_wait(0.22, 0.36)
        media = read_portrait_media_state()
        if (
            media
            and 0.78 <= media.get("natural_ratio", 0) <= 0.82
            and 0.78 <= media.get("render_ratio", 0) <= 0.82
        ):
            break
    if (
        not media
        or not 0.78 <= media.get("natural_ratio", 0) <= 0.82
        or not 0.78 <= media.get("render_ratio", 0) <= 0.82
    ):
        raise RuntimeError("Instagram 4:5 selection did not produce a portrait media frame; nothing advanced")

    screenshot_path = os.environ.get("IG_RATIO_SCREENSHOT")
    if not screenshot_path:
        raise RuntimeError("IG_RATIO_SCREENSHOT is required after explicit 4:5 selection; nothing advanced")
    shot = cdp("Page.captureScreenshot", format="jpeg", quality=80, captureBeyondViewport=False)
    with open(screenshot_path, "wb") as handle:
        handle.write(base64.b64decode(shot["data"]))
    return {"control": control, "option": option, "media": media, "screenshot": screenshot_path}


targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError(f"writable Instagram page target must be exactly one; found {len(targets)}")
switch_tab(targets[0]["targetId"], activate=True)

portrait_4x5 = select_portrait_4x5()
crop_next = click_control("다음")
edit_state = wait_state(
    lambda value: value["has_filter"] and value["has_adjust"] and value["has_original"]
)
if not edit_state or not edit_state["has_filter"] or not edit_state["has_adjust"] or not edit_state["has_original"]:
    raise RuntimeError("Instagram edit/filter stage was not confirmed")

original = click_control("원본", roles=("button", "link", "radio", "generic"))
paced_wait()

edit_next_attempts = [click_control("다음")]
caption_state = wait_state(
    lambda value: value["has_caption"] and value["has_share"], seconds=4
)
if not caption_state or not caption_state["has_caption"] or not caption_state["has_share"]:
    if caption_state and caption_state["has_filter"] and caption_state["has_adjust"]:
        edit_next_attempts.append(click_control("다음"))
        caption_state = wait_state(
            lambda value: value["has_caption"] and value["has_share"], seconds=6
        )

print(
    "INSTAGRAM_ADVANCE_TO_CAPTION="
    + json.dumps(
        {
            "portrait_4x5": portrait_4x5,
            "crop_next": crop_next,
            "original": original,
            "edit_next_attempts": edit_next_attempts,
            "state": caption_state,
            "harness_processes": 1,
        },
        ensure_ascii=True,
    )
)
if (
    not caption_state
    or not caption_state["has_caption"]
    or not caption_state["has_share"]
    or caption_state["login_wall"]
    or caption_state["challenge"]
):
    raise RuntimeError("Instagram caption/share stage was not confirmed")
