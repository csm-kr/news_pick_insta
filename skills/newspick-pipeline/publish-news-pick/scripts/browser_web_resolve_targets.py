"""Select one configured-account Instagram target without closing any existing tab.

Run with: python scripts/invoke_edge_browser_harness.py scripts/browser_web_resolve_targets.py
"""

import json
import os
import re


account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", account):
    raise RuntimeError("IG_ACCOUNT 형식이 올바르지 않습니다")
profile_url = f"https://www.instagram.com/{account}/"


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
if len(exact_profiles) != 1:
    raise RuntimeError(
        f"@{account}의 정확한 프로필 target이 하나여야 합니다: {len(exact_profiles)}"
    )
keep = exact_profiles[0]

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
            "closed": [],
            "after_count": len(targets),
            "existing_tabs_preserved": True,
        },
        ensure_ascii=True,
    )
)
