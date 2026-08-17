"""Click Instagram Share exactly once and require the web success marker."""

import json
import os
import time


shot = os.environ["IG_SCREENSHOT"]
targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError(f"writable Instagram page target must be exactly one; found {len(targets)}")
switch_tab(targets[0]["targetId"])

nodes = cdp("Accessibility.getFullAXTree").get("nodes", [])
candidates = [node for node in nodes if str((node.get("name") or {}).get("value") or "") == "공유하기"]
clicked = None
for node in candidates:
    try:
        box = cdp("DOM.getBoxModel", backendNodeId=node["backendDOMNodeId"])["model"]["content"]
        x, y = sum(box[0::2]) / 4, sum(box[1::2]) / 4
        if x >= 0 and y >= 0:
            click_at_xy(x, y)
            clicked = {"x": x, "y": y, "backendDOMNodeId": node["backendDOMNodeId"]}
            break
    except Exception:
        pass
if not clicked:
    raise RuntimeError("visible Share control not found; nothing was clicked")

markers = ("게시물이 공유되었습니다", "게시물을 공유했습니다", "Your post has been shared")
deadline = time.time() + 120
state = None
while time.time() < deadline:
    time.sleep(1)
    state = js("""
    (() => {
      const text=document.body?.innerText||'';
      const dialogs=[...document.querySelectorAll('[role=dialog]')].map(d=>(d.innerText||'').slice(0,5000));
      return {text:text.slice(0,12000),dialogs,url:location.href};
    })()
    """)
    if any(marker in state["text"] for marker in markers):
        break

capture_screenshot(shot, full=False, max_dim=1800)
success = bool(state and any(marker in state["text"] for marker in markers))
print("INSTAGRAM_WEB_SHARE_ONCE=" + json.dumps({"clicked": clicked, "success_marker": success, "url": (state or {}).get("url"), "screenshot": shot}, ensure_ascii=True))
if not success:
    raise RuntimeError("Share was clicked once but Instagram success marker was not confirmed; do not retry")
