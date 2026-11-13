"""Find the newly published profile post and normalize its scoped permalink."""

import json
import os
import re
import time


account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", account):
    raise RuntimeError("IG_ACCOUNT format is invalid")
tokens = [value.strip() for value in os.environ.get("IG_EXPECTED_ALT_TOKENS", "").split("|") if value.strip()]
if not tokens:
    raise RuntimeError("IG_EXPECTED_ALT_TOKENS requires at least one stable token")

targets = [
    item for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError(f"writable Instagram page target must be exactly one; found {len(targets)}")
switch_tab(targets[0]["targetId"], activate=True)
goto_url(f"https://www.instagram.com/{account}/")
wait_for_load()

deadline = time.monotonic() + 30
state = None
while time.monotonic() < deadline:
    state = js(
        """
(() => ({
  url:location.href,
  posts:[...document.querySelectorAll('a[href*="/p/"]')]
    .map(a=>({href:a.href,alts:[...a.querySelectorAll('img')].map(i=>i.alt||'').filter(Boolean)}))
    .filter((x,i,a)=>a.findIndex(y=>y.href===x.href)===i)
    .slice(0,12)
}))()
"""
    )
    if any(all(token in " ".join(post.get("alts", [])) for token in tokens) for post in state["posts"]):
        break
    time.sleep(0.8)

selected = next(
    (
        post for post in (state or {}).get("posts", [])
        if all(token in " ".join(post.get("alts", [])) for token in tokens)
    ),
    None,
)
if not selected:
    raise RuntimeError("newly shared post matching every expected token was not found")
match = re.search(r"/p/([A-Za-z0-9_-]+)/?", selected["href"])
if not match:
    raise RuntimeError("Instagram shortcode was not found")
shortcode = match.group(1)
print(
    "INSTAGRAM_LATEST_POST="
    + json.dumps(
        {
            "shortcode": shortcode,
            "url": f"https://www.instagram.com/p/{shortcode}/",
            "observed_href": selected["href"],
            "matched_tokens": tokens,
            "harness_processes": 1,
        },
        ensure_ascii=True,
    )
)
