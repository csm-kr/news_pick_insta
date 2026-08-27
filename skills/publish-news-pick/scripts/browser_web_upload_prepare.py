import base64
import json
import os
import random
import re
import time


def attach_without_focus(target_id):
    wrapped = switch_tab
    inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
    private = inner.__globals__
    session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    private["_send"](
        {"meta": "set_session", "session_id": session_id, "target_id": target_id}
    )
    private["_mark_tab"]()


def attach_writable_target(target_id):
    cdp("Target.activateTarget", targetId=target_id)
    return attach_without_focus(target_id)


def paced_wait(low=0.28, high=0.62):
    time.sleep(random.uniform(low, high))


def click_named_control(name):
    control = js(
        """
((name) => {
  const candidates=[...document.querySelectorAll('a,button,[role=button]')];
  const e=candidates.find(x=>{
    const r=x.getBoundingClientRect();
    const label=(x.getAttribute('aria-label')||x.innerText||'').trim();
    return label===name && r.width>0 && r.height>0;
  });
  if(!e)return null;
  const r=e.getBoundingClientRect();
  return {x:r.x+r.width/2,y:r.y+r.height/2,label:name};
})(%s)
"""
        % json.dumps(name, ensure_ascii=False)
    )
    if control:
        click_at_xy(control["x"], control["y"])
        return {**control, "source": "dom"}

    # Instagram can expose the create link in the accessibility tree while its
    # link wrapper reports no visible DOM box. Use the exact AX name as the
    # bounded fallback instead of widening the selector or taking screenshots.
    nodes = cdp("Accessibility.getFullAXTree").get("nodes", [])
    for node in nodes:
        label = str((node.get("name") or {}).get("value") or "").strip()
        role = str((node.get("role") or {}).get("value") or "").strip()
        backend_id = node.get("backendDOMNodeId")
        if label != name or role not in {"button", "link"} or not backend_id:
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
            "x": x,
            "y": y,
            "label": name,
            "source": "accessibility",
            "backendDOMNodeId": backend_id,
        }
    raise RuntimeError("visible control not found: " + name)


def read_upload_state():
    return js(
        """
(() => {
  const text=document.body?.innerText||'';
  const input=document.querySelector('input[type=file][multiple]');
  return {
    url:location.href,
    input_present:!!input,
    file_count:input?.files?.length||0,
    file_names:input?[...input.files].map(f=>f.name):[],
    multiple:input?.multiple===true,
    has_next:text.includes('다음'),
    has_crop:text.includes('자르기'),
    has_media_gallery:text.includes('미디어 갤러리 열기'),
    login_wall:location.href.includes('/accounts/login'),
    challenge:/(challenge|checkpoint)/.test(location.href)
  };
})()
"""
    )


targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError("Instagram page target count is " + str(len(targets)))
attach_writable_target(targets[0]["targetId"])

account = os.environ.get("IG_ACCOUNT", "newspick_studio").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]+", account):
    raise RuntimeError("IG_ACCOUNT format is invalid")
profile_url = f"https://www.instagram.com/{account}/"

# The current URL may be another public profile even while the intended account
# is logged in. Confirm the fixed sidebar profile link before opening Composer,
# then navigate the writable target to the intended profile for an unambiguous
# pre-submit screenshot and account boundary.
active_account = js(
    """
((account) => {
  const expected=`https://www.instagram.com/${account}/`;
  const candidates=[...document.querySelectorAll('a[href]')]
    .map(a=>{
      const r=a.getBoundingClientRect();
      return {
        href:a.href,
        image_alts:[...a.querySelectorAll('img')].map(img=>img.alt||'').filter(Boolean),
        x:r.x,y:r.y,w:r.width,h:r.height
      };
    })
    .filter(x=>x.href===expected && x.x>=0 && x.x<120 && x.w>0 && x.w<=120 && x.h>0);
  return candidates[0]||null;
})(%s)
""" % json.dumps(account)
)
if not active_account or not any(account in value.lower() for value in active_account.get("image_alts", [])):
    raise RuntimeError("active Instagram sidebar account does not match IG_ACCOUNT")
if js(r"location.href.split('?',1)[0].replace(/\/$/,'')") != profile_url.rstrip("/"):
    goto_url(profile_url)
    wait_for_load()

media = os.environ["IG_MEDIA_FILES"].split("|")
if len(media) not in (3, 4):
    raise RuntimeError("exactly three or four media files are required")

selector = "input[type=file][multiple]"
input_state = js("(() => { const input=document.querySelector('input[type=file][multiple]'); return {exists:!!input,multiple:input?.multiple===true}; })()")
if input_state.get("exists"):
    clicked = {"source": "existing_create_modal"}
else:
    try:
        clicked = click_named_control("새로운 게시물")
    except RuntimeError:
        clicked = click_named_control("만들기")
    paced_wait(0.55, 1.05)
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    input_state = js("(() => { const input=document.querySelector('input[type=file][multiple]'); return {exists:!!input,multiple:input?.multiple===true}; })()")
    if input_state.get("exists"):
        break
    paced_wait(0.18, 0.38)
if not input_state.get("exists") or input_state.get("multiple") is not True:
    raise RuntimeError("multiple file input was not found")
upload_file(selector, media)
deadline = time.monotonic() + 12
state = read_upload_state()
while not state.get("has_next") and not state.get("login_wall") and not state.get("challenge") and time.monotonic() < deadline:
    paced_wait(0.28, 0.58)
    state = read_upload_state()
shot = cdp("Page.captureScreenshot", format="jpeg", quality=72, captureBeyondViewport=False)
with open(os.environ["IG_CROP_SCREENSHOT"], "wb") as handle:
    handle.write(base64.b64decode(shot["data"]))
print(
    "INSTAGRAM_WEB_UPLOAD_PREPARE="
    + json.dumps({"account": account, "active_account": active_account, "clicked": clicked, "state": state, "harness_processes": 1}, ensure_ascii=True)
)
if (
    not state.get("has_next")
    or not state.get("has_crop")
    or state.get("login_wall")
    or state.get("challenge")
):
    raise RuntimeError("multi-card crop session was not confirmed")
if state.get("input_present") and (
    state.get("file_count") != len(media) or state.get("multiple") is not True
):
    raise RuntimeError("retained multiple input does not contain the expected media")
print("MANUAL_GATE=Open the media gallery and visually confirm every thumbnail before continuing")
