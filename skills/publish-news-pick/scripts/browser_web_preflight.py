"""Fast read-only Instagram preflight for the fixed Edge Browser Harness connection."""

import json
import os
import re


ACCOUNT = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", ACCOUNT):
    raise RuntimeError("IG_ACCOUNT 형식이 올바르지 않다")
PROFILE_URL = f"https://www.instagram.com/{ACCOUNT}/"
DUPLICATE_TOKENS = [
    value.strip()
    for value in os.environ.get("IG_DUPLICATE_TOKENS", "").split("|")
    if value.strip()
]


def attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"]({"meta": "set_session", "session_id": session_id, "target_id": target_id})
    private["_mark_tab"]()


previous = current_tab()["targetId"]
target_id = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
try:
    attach_without_focus(target_id)
    goto_url(PROFILE_URL)
    wait_for_load()
    if js("document.hasFocus()") is not False:
        raise RuntimeError("preflight target unexpectedly has focus")
    state = js(
        """
(async (account, duplicateTokens) => {
  const read = () => {
    const text = document.body?.innerText || '';
    const controls = [...document.querySelectorAll('a[href],button,[role=button]')];
    const normalized = value => String(value || '').trim().toLocaleLowerCase();
    const createNames = new Set(['새로운 게시물','만들기','create','new post']);
    const hasCreate = controls.some(e =>
      String(e.getAttribute('href') || '').includes('/create/') ||
      createNames.has(normalized(e.innerText)) ||
      createNames.has(normalized(e.getAttribute('aria-label')))
    ) || !!document.querySelector('svg[aria-label="새로운 게시물"],svg[aria-label="만들기"],svg[aria-label="New post"]');
    const url = location.href;
    const pathAccount = decodeURIComponent(location.pathname).split('/').filter(Boolean)[0] || '';
    const ownerControls =
      text.includes('프로필 편집') || text.includes('보관함 보기') ||
      text.includes('프로페셔널 대시보드') ||
      controls.some(e => String(e.getAttribute('href') || '').includes('/accounts/edit'));
    const loginWall = url.includes('/accounts/login') || !!document.querySelector('input[type=password]');
    const challenge = /(challenge|checkpoint)/.test(url);
    const accountVisible = pathAccount.toLocaleLowerCase() === account || text.toLocaleLowerCase().includes(account);
    const posts = [...document.querySelectorAll('a[href*="/p/"]')]
      .map(a=>({
        href:a.href,
        alts:[...a.querySelectorAll('img')].map(img=>String(img.alt||'').slice(0,500)).filter(Boolean)
      }))
      .filter((value,index,all)=>all.findIndex(other=>other.href===value.href)===index)
      .slice(0,12);
    const duplicate = posts.find(post=>{
      const haystack=post.alts.join(' ').toLocaleLowerCase();
      return duplicateTokens.length>0 && duplicateTokens.every(token=>haystack.includes(token.toLocaleLowerCase()));
    }) || null;
    return {
      url,
      account_visible: accountVisible,
      owner_controls: ownerControls,
      has_create: hasCreate,
      login_wall: loginWall,
      challenge,
      posts_ready: posts.length>0,
      duplicate_match: !!duplicate,
      duplicate_href: duplicate?.href||null,
      recent_posts: posts.slice(0,6),
      ready: accountVisible && ownerControls && hasCreate && !loginWall && !challenge
    };
  };
  const deadline = performance.now() + 8000;
  let attempts = 0;
  let state = read();
  while ((!state.ready || (duplicateTokens.length>0 && !state.posts_ready)) &&
         !state.login_wall && !state.challenge && performance.now() < deadline) {
    attempts += 1;
    await new Promise(resolve => setTimeout(resolve, 220 + Math.floor(Math.random() * 181)));
    state = read();
  }
  return {...state, render_attempts: attempts + 1, round_trips: 1};
})(%s,%s)
"""
        % (json.dumps(ACCOUNT), json.dumps(DUPLICATE_TOKENS, ensure_ascii=False))
    )
    print("INSTAGRAM_WEB_PREFLIGHT=" + json.dumps(state, ensure_ascii=True))
    if not state["ready"]:
        raise RuntimeError(f"configured Microsoft Edge profile is not ready for @{ACCOUNT}")
    if DUPLICATE_TOKENS and state["duplicate_match"]:
        raise RuntimeError("duplicate post matched every IG_DUPLICATE_TOKENS value")
finally:
    cdp("Target.closeTarget", targetId=target_id)
    attach_without_focus(previous)
