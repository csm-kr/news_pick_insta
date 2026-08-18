import json
import os
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


def click_ax_name(name):
    nodes = cdp("Accessibility.getFullAXTree").get("nodes", [])
    for node in nodes:
        if (
            str((node.get("name") or {}).get("value") or "") != name
            or not node.get("backendDOMNodeId")
        ):
            continue
        try:
            box = cdp(
                "DOM.getBoxModel", backendNodeId=node["backendDOMNodeId"]
            )["model"]["content"]
            x = sum(box[0::2]) / 4
            y = sum(box[1::2]) / 4
            if x >= 0 and y >= 0:
                click_at_xy(x, y)
                return {"name": name, "x": x, "y": y}
        except Exception:
            continue
    raise RuntimeError("visible AX control not found: " + name)


targets = [
    item
    for item in cdp("Target.getTargets").get("targetInfos", [])
    if item.get("type") == "page" and "instagram.com" in str(item.get("url") or "")
]
if len(targets) != 1:
    raise RuntimeError("Instagram page target count is " + str(len(targets)))
attach_without_focus(targets[0]["targetId"])

media = os.environ["IG_MEDIA_FILES"].split("|")
if len(media) not in (3, 4):
    raise RuntimeError("exactly three or four media files are required")

clicked = click_ax_name("새로운 게시물")
time.sleep(2)
selector = "input[type=file][multiple]"
input_state = js(
    """
(() => {
  const input=document.querySelector('input[type=file][multiple]');
  return {exists:!!input, multiple:input?.multiple===true};
})()
"""
)
if not input_state.get("exists") or input_state.get("multiple") is not True:
    raise RuntimeError("multiple file input was not found")
upload_file(selector, media)
time.sleep(7)

state = js(
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
capture_screenshot(os.environ["IG_CROP_SCREENSHOT"], full=False, max_dim=1800)
print(
    "INSTAGRAM_WEB_UPLOAD_PREPARE="
    + json.dumps({"clicked": clicked, "state": state}, ensure_ascii=True)
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
