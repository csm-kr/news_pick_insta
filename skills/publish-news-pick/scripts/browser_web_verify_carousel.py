"""Verify the public five-card 4:5 carousel in the approved Instagram target."""

import base64
import json
import os
import re
import time
from pathlib import Path


def capture_jpeg(path, quality):
    shot = cdp(
        "Page.captureScreenshot",
        format="jpeg",
        quality=quality,
        captureBeyondViewport=False,
    )
    path.write_bytes(base64.b64decode(shot["data"]))


post_url = os.environ["IG_POST_URL"].split("?", 1)[0].rstrip("/") + "/"
expected = int(os.environ["IG_CARD_COUNT"])
caption_prefix = os.environ["IG_CAPTION_PREFIX"]
account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
require_ai = os.environ.get("IG_REQUIRE_AI_LABEL", "1") != "0"
approved_publish_verify = os.environ.get("IG_APPROVED_PUBLISH_VERIFY", "0") == "1"
if expected != 5:
    raise RuntimeError("IG_CARD_COUNT must be 5")
if not approved_publish_verify:
    raise RuntimeError(
        "IG_APPROVED_PUBLISH_VERIFY=1 is required for same-target post-publish verification"
    )
if not re.fullmatch(r"[a-z0-9._]+", account):
    raise RuntimeError("IG_ACCOUNT 형식이 올바르지 않다")
shot_dir = Path(os.environ["IG_SCREENSHOT_DIR"]).expanduser().resolve()
shot_dir.mkdir(parents=True, exist_ok=True)

targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError(
        "approved Instagram page target must be exactly one; found " + str(len(targets))
    )
switch_tab(targets[0]["targetId"], activate=True)

states = []
for index in range(1, expected + 1):
    goto_url(post_url + "?img_index=" + str(index))
    wait_for_load()
    time.sleep(0.65)

    # A low-cost paint makes Instagram's lazy carousel image expose stable
    # natural and rendered dimensions before the verification loop.
    cdp(
        "Page.captureScreenshot",
        format="jpeg",
        quality=45,
        captureBeyondViewport=False,
    )

    expression = """
((captionPrefix, account, expectedIndex) => {
  const text=document.body?.innerText||'';
  const dots=[...document.querySelectorAll('div._acnb')].map(el=>{
    const r=el.getBoundingClientRect();
    return {w:r.width,h:r.height,active:el.classList.contains('_acnf')};
  }).filter(x=>x.w===6&&x.h===6);
  const candidates=[...document.images].map(img=>{
    const r=img.getBoundingClientRect();
    const naturalRatio=img.naturalHeight?img.naturalWidth/img.naturalHeight:0;
    return {
      src:img.currentSrc||img.src||'',alt:img.alt||'',
      natural_w:img.naturalWidth||0,natural_h:img.naturalHeight||0,
      natural_ratio:naturalRatio,x:r.x,y:r.y,w:r.width,h:r.height,
      render_ratio:r.height?r.width/r.height:0
    };
  }).filter(x=>
    x.w>400&&x.h>500&&x.y<700&&x.x<1200&&x.x+x.w>0&&x.y+x.h>0
    &&x.natural_ratio>=0.78&&x.natural_ratio<=0.82
  ).sort((a,b)=>
    (a.x>=0?a.x:100000+Math.abs(a.x))
    -(b.x>=0?b.x:100000+Math.abs(b.x))
  );
  const media=candidates[0]||null;
  const labels=[...document.querySelectorAll('[aria-label]')]
    .filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.right>0})
    .map(e=>e.getAttribute('aria-label')||'');
  const queryIndex=Number(new URL(location.href).searchParams.get('img_index'))-1;
  return {
    dot_count:dots.length,
    active_index:dots.length?dots.findIndex(x=>x.active):(media?queryIndex:-1),
    caption_match:text.includes(captionPrefix),
    account_visible:text.toLocaleLowerCase().includes(account),
    ai_label:text.includes('AI 콘텐츠')||text.includes('AI 크리에이터')||text.includes('Made with AI'),
    login_wall:location.href.includes('/accounts/login')||!!document.querySelector('input[type=password]'),
    challenge:/(challenge|checkpoint)/.test(location.href),
    media_ready:!!media,
    media_src:media?.src||'',
    media_alt:media?.alt||'',
    natural_w:media?.natural_w||0,
    natural_h:media?.natural_h||0,
    natural_ratio:media?.natural_ratio||0,
    render_ratio:media?.render_ratio||0,
    has_left:labels.includes('왼쪽 방향 아이콘'),
    has_right:labels.includes('오른쪽 방향 아이콘'),
    url:location.href,
    expected_index:expectedIndex-1
  };
})(%s,%s,%d)
""" % (
        json.dumps(caption_prefix, ensure_ascii=False),
        json.dumps(account),
        index,
    )

    deadline = time.monotonic() + (7 if index == expected else 5)
    attempts = 0
    state = None
    while time.monotonic() < deadline:
        state = js(expression)
        attempts += 1
        if (
            state.get("media_ready")
            and state.get("caption_match")
            and state.get("active_index") == index - 1
            and 0.78 <= state.get("natural_ratio", 0) <= 0.82
            and 0.78 <= state.get("render_ratio", 0) <= 0.82
        ) or state.get("login_wall") or state.get("challenge"):
            break
        time.sleep(0.3)
    state["render_attempts"] = attempts

    if index in {1, expected}:
        screenshot = shot_dir / f"public-card-{index:02d}.jpg"
        capture_jpeg(screenshot, quality=74)
        state["screenshot"] = str(screenshot)
    states.append(state)

distinct_media_count = len(
    {state.get("media_src") for state in states if state.get("media_src")}
)
dot_counts = [state.get("dot_count") for state in states if state.get("dot_count")]
slide_count = dot_counts[-1] if dot_counts else distinct_media_count
navigation_boundary = bool(
    states[0].get("has_right")
    and not states[0].get("has_left")
    and states[-1].get("has_left")
    and not states[-1].get("has_right")
)
portrait_4x5 = all(
    0.78 <= state.get("natural_ratio", 0) <= 0.82
    and 0.78 <= state.get("render_ratio", 0) <= 0.82
    for state in states
)
result = {
    "slide_count": slide_count,
    "active_sequence": [state.get("active_index") for state in states],
    "distinct_media_count": distinct_media_count,
    "navigation_boundary": navigation_boundary,
    "caption_match": all(state.get("caption_match") for state in states),
    "account_match": all(state.get("account_visible") for state in states),
    "ai_label": all(state.get("ai_label") for state in states),
    "media_ready": all(state.get("media_ready") for state in states),
    "portrait_4x5": portrait_4x5,
    "natural_dimensions": [
        [state.get("natural_w"), state.get("natural_h")] for state in states
    ],
    "render_ratios": [round(state.get("render_ratio", 0), 6) for state in states],
    "login_wall": any(state.get("login_wall") for state in states),
    "challenge": any(state.get("challenge") for state in states),
    "first_screenshot": states[0].get("screenshot"),
    "last_screenshot": states[-1].get("screenshot"),
    "first_alt": states[0].get("media_alt"),
    "last_alt": states[-1].get("media_alt"),
    "visual_confirmation_required": True,
    "harness_processes": 1,
}
result["verified"] = bool(
    result["slide_count"] == expected
    and result["active_sequence"] == list(range(expected))
    and result["distinct_media_count"] == expected
    and result["caption_match"]
    and result["account_match"]
    and (result["ai_label"] or not require_ai)
    and result["media_ready"]
    and result["portrait_4x5"]
    and not result["login_wall"]
    and not result["challenge"]
)
print("INSTAGRAM_CAROUSEL_VERIFY=" + json.dumps(result, ensure_ascii=True))
if not result["verified"]:
    raise RuntimeError("public carousel verification failed")
