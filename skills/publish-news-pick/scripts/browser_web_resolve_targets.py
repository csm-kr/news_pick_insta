"""Keep one configured-account Instagram page target and close only redundant Instagram targets.

Run with: browser-harness < scripts/browser_web_resolve_targets.py
"""

import json
import os
import re


account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", account):
    raise RuntimeError("IG_ACCOUNT 형식이 올바르지 않습니다")
profile_url = f"https://www.instagram.com/{account}/"
current_id = current_tab()["targetId"]


def instagram_targets():
    return [
        item
        for item in cdp("Target.getTargets").get("targetInfos", [])
        if item.get("type") == "page"
        and "instagram.com" in str(item.get("url") or "")
    ]


targets = instagram_targets()
if not targets:
    raise RuntimeError("Instagram page target이 없습니다")

exact_profiles = [
    item
    for item in targets
    if str(item.get("url") or "").split("?", 1)[0].rstrip("/")
    == profile_url.rstrip("/")
]
current_exact = [item for item in exact_profiles if item.get("targetId") == current_id]
current_instagram = [item for item in targets if item.get("targetId") == current_id]
if current_exact:
    keep = current_exact[0]
elif exact_profiles:
    keep = exact_profiles[0]
elif current_instagram:
    keep = current_instagram[0]
else:
    keep = targets[0]

closed = []
for item in targets:
    if item.get("targetId") == keep.get("targetId"):
        continue
    cdp("Target.closeTarget", targetId=item["targetId"])
    closed.append(
        {
            "targetId": item.get("targetId"),
            "url": item.get("url"),
            "title": item.get("title"),
        }
    )

remaining = instagram_targets()
if len(remaining) != 1 or remaining[0].get("targetId") != keep.get("targetId"):
    raise RuntimeError(
        f"Instagram target 정리 후 개수가 정확히 하나가 아닙니다: {len(remaining)}"
    )

print(
    "INSTAGRAM_TARGET_RESOLUTION="
    + json.dumps(
        {
            "before_count": len(targets),
            "kept": {
                "targetId": keep.get("targetId"),
                "url": keep.get("url"),
                "title": keep.get("title"),
            },
            "closed": closed,
            "after_count": len(remaining),
        },
        ensure_ascii=True,
    )
)
