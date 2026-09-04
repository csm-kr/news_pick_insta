"""Click Instagram Share exactly once and require the web success marker."""

import base64
import json
import os
import random
import re
import time
from datetime import datetime, timedelta


if os.environ.get("NEWS_PICK_SCHEDULED_MODE") == "1":
    raw_scheduled_at = os.environ.get("NEWS_PICK_EDITION_AT")
    if not raw_scheduled_at:
        raise RuntimeError(
            "scheduled mode requires NEWS_PICK_EDITION_AT; nothing was clicked"
        )
    normalized_scheduled_at = raw_scheduled_at.replace("Z", "+00:00")
    normalized_scheduled_at = re.sub(
        r"(\.\d{6})\d+(?=([+-]\d{2}:\d{2})?$)", r"\1", normalized_scheduled_at
    )
    scheduled_at = datetime.fromisoformat(normalized_scheduled_at)
    if scheduled_at.tzinfo is None:
        raise RuntimeError("NEWS_PICK_EDITION_AT requires timezone; nothing was clicked")
    current_time = datetime.now(scheduled_at.tzinfo)
    if current_time < scheduled_at:
        raise RuntimeError(
            "scheduled publish time has not arrived; run wait_for_publish_time.py first; nothing was clicked"
        )
    if current_time > scheduled_at + timedelta(minutes=30):
        raise RuntimeError(
            "scheduled publish window expired 30 minutes ago; nothing was clicked"
        )


shot = os.environ["IG_SCREENSHOT"]
targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError(
        f"writable Instagram page target must be exactly one; found {len(targets)}"
    )
switch_tab(targets[0]["targetId"], activate=True)

clicked = js(
    """
(() => {
  const root=document.querySelector('[role=dialog]')||document;
  const controls=[...root.querySelectorAll('button,[role=button]')].filter(e=>{
    const r=e.getBoundingClientRect();
    const label=(e.getAttribute('aria-label')||e.innerText||'').trim();
    return label==='공유하기'&&r.width>0&&r.height>0&&r.right>0&&r.bottom>0&&r.left<innerWidth&&r.top<innerHeight;
  });
  const e=controls[0];
  if(!e)return null;
  const r=e.getBoundingClientRect();
  return {x:r.x+r.width/2,y:r.y+r.height/2,source:'dom'};
})()
"""
)
if not clicked:
    nodes = cdp("Accessibility.getFullAXTree").get("nodes", [])
    candidates = [
        node
        for node in nodes
        if str((node.get("name") or {}).get("value") or "").strip() == "공유하기"
    ]
    for node in candidates:
        try:
            box = cdp(
                "DOM.getBoxModel", backendNodeId=node["backendDOMNodeId"]
            )["model"]["content"]
            x, y = sum(box[0::2]) / 4, sum(box[1::2]) / 4
            if x >= 0 and y >= 0:
                clicked = {
                    "x": x,
                    "y": y,
                    "backendDOMNodeId": node["backendDOMNodeId"],
                    "source": "ax_fallback",
                }
                break
        except Exception:
            pass
if not clicked:
    raise RuntimeError("visible Share control not found; nothing was clicked")
time.sleep(random.uniform(0.22, 0.48))
click_at_xy(clicked["x"], clicked["y"])

markers = (
    "게시물이 공유되었습니다",
    "게시물을 공유했습니다",
    "게시물이 공유됐습니다",
    "Your post has been shared",
)
deadline = time.time() + 120
state = None
while time.time() < deadline:
    time.sleep(random.uniform(0.35, 0.65))
    state = js(
        """
        (() => {
          const text=document.body?.innerText||'';
          const dialogs=[...document.querySelectorAll('[role=dialog]')]
            .map(d=>(d.innerText||'').slice(0,5000));
          return {text:text.slice(0,12000),dialogs,url:location.href};
        })()
        """
    )
    if any(marker in state["text"] for marker in markers):
        break

image = cdp("Page.captureScreenshot", format="jpeg", quality=72, captureBeyondViewport=False)
with open(shot, "wb") as handle:
    handle.write(base64.b64decode(image["data"]))
success = bool(state and any(marker in state["text"] for marker in markers))
print(
    "INSTAGRAM_WEB_SHARE_ONCE="
    + json.dumps(
        {
            "clicked": clicked,
            "success_marker": success,
            "url": (state or {}).get("url"),
            "screenshot": shot,
            "harness_processes": 1,
        },
        ensure_ascii=True,
    )
)
if not success:
    raise RuntimeError(
        "Share was clicked once but Instagram success marker was not confirmed; do not retry"
    )
