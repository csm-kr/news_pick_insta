"""Find the newly published profile post and normalize its scoped permalink."""

import json
import os
import re
import time


account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", account):
    raise RuntimeError("IG_ACCOUNT format is invalid")
tokens = [value.strip() for value in os.environ.get("IG_EXPECTED_ALT_TOKENS", "").split("|") if value.strip()]
# Instagram 자동 alt에는 카드 문구가 거의 안 들어가므로(11-20 사례) caption 앞부분으로 찾는 길을 둔다.
caption_prefix = os.environ.get("IG_EXPECTED_CAPTION_PREFIX", "").strip()
if not tokens and not caption_prefix:
    raise RuntimeError("IG_EXPECTED_ALT_TOKENS or IG_EXPECTED_CAPTION_PREFIX is required")


def alt_match(post):
    return bool(tokens) and all(token in " ".join(post.get("alts", [])) for token in tokens)


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
    if (caption_prefix and state["posts"]) or any(alt_match(post) for post in state["posts"]):
        break
    time.sleep(0.8)

posts = (state or {}).get("posts", [])
selected = None
if caption_prefix:
    # 최신 3개만 permalink를 열어 caption을 읽는다. 같은 target에서 읽기만 한다.
    for post in posts[:3]:
        found = re.search(r"/p/([A-Za-z0-9_-]+)/?", post["href"])
        if not found:
            continue
        goto_url(f"https://www.instagram.com/p/{found.group(1)}/")
        wait_for_load()
        page_deadline = time.monotonic() + 15
        while time.monotonic() < page_deadline:
            page = js("(()=>({url:location.href,text:document.body.innerText||''}))()")
            if caption_prefix in (page or {}).get("text", ""):
                selected = post
                break
            time.sleep(0.8)
        if selected:
            break
else:
    selected = next((post for post in posts if alt_match(post)), None)
if not selected:
    raise RuntimeError("newly shared post matching the expected caption or alt tokens was not found")
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
            "matched_caption_prefix": caption_prefix or None,
            "harness_processes": 1,
        },
        ensure_ascii=True,
    )
)
