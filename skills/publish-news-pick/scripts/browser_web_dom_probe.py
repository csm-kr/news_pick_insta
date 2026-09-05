import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def inspect_dom():
    return js(
        """
(() => {
  const names=new Set(['새로운 게시물','만들기','게시물','새 게시물 만들기',
    '컴퓨터에서 선택','자르기','자르기 선택','다음','공유하기','공유',
    '미디어 갤러리 열기','AI 라벨 추가','Create','New post','Post',
    'Select from computer','Next','Share']);
  const visible=element=>{
    const rect=element.getBoundingClientRect();
    const style=getComputedStyle(element);
    return rect.width>0&&rect.height>0&&rect.right>0&&rect.bottom>0&&
      rect.left<innerWidth&&rect.top<innerHeight&&style.visibility!=='hidden'&&style.display!=='none';
  };
  const controls=[...document.querySelectorAll('a,button,[role=button],[role=menuitem],svg[aria-label]')]
    .filter(visible).flatMap(element=>{
      const host=element.closest('a,button,[role=button],[role=menuitem]')||element;
      const labels=[host.getAttribute('aria-label'),host.innerText,
        element.getAttribute('aria-label'),host.querySelector('svg[aria-label]')?.getAttribute('aria-label')]
        .map(label=>(label||'').trim()).filter(label=>names.has(label));
      if(!labels.length)return [];
      const rect=host.getBoundingClientRect();
      const hit=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);
      return [{tag:host.tagName,role:host.getAttribute('role'),labels:[...new Set(labels)],
        href_path:host.href?new URL(host.href).pathname:null,
        in_dialog:!!host.closest('[role=dialog]'),in_menu:!!host.closest('[role=menu]'),
        disabled:host.disabled===true||host.getAttribute('aria-disabled')==='true',
        hit_matches:!!hit&&(host===hit||host.contains(hit)),
        rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height}}];
    }).slice(0,40);
  const body=document.body?.innerText||'';
  return {url:location.origin+location.pathname,has_focus:document.hasFocus(),
    dialog_count:[...document.querySelectorAll('[role=dialog]')].filter(visible).length,controls,
    file_inputs:[...document.querySelectorAll('input[type=file]')].slice(0,10).map(input=>({
      multiple:input.multiple,accept:input.accept,disabled:input.disabled,
      file_count:input.files?.length||0,in_dialog:!!input.closest('[role=dialog]')})),
    state:{has_crop:body.includes('자르기'),has_next:body.includes('다음'),
      has_caption:!!document.querySelector('textarea,[role=textbox][contenteditable=true]'),
      shared:body.includes('게시물이 공유되었습니다')||body.includes('Your post has been shared'),
      login_wall:location.pathname.includes('/accounts/login'),
      challenge:/(challenge|checkpoint)/.test(location.pathname)}};
})()
"""
    )


product = str(cdp('Browser.getVersion').get('product') or '')
if not product.lower().startswith(('edg/', 'microsoftedge/')):
    raise RuntimeError('DOM diagnostics require Microsoft Edge')
targets = [target for target in cdp('Target.getTargets').get('targetInfos', [])
           if target.get('type') == 'page'
           and urlsplit(target.get('url') or '').hostname in {'instagram.com', 'www.instagram.com'}]
if len(targets) != 1:
    raise RuntimeError('DOM diagnostics require exactly one Instagram page; existing tabs are preserved')
wrapped = switch_tab
inner = wrapped.__closure__[0].cell_contents if wrapped.__closure__ else wrapped
private = inner.__globals__
target_id = targets[0]['targetId']
session_id = cdp('Target.attachToTarget', targetId=target_id, flatten=True)['sessionId']
private['_send']({'meta': 'set_session', 'session_id': session_id, 'target_id': target_id})
private['_mark_tab']()
report = {'schema_version': '1.0', 'observed_at': datetime.now(timezone.utc).isoformat(),
          'browser': product, 'connection': 'edge9333', 'target_id': target_id,
          'read_only': True, 'snapshot': inspect_dom()}
destination = os.environ.get('IG_DOM_DIAGNOSTIC_PATH')
if destination:
    output_root = Path(os.environ.get('NEWS_PICK_OUTPUT_ROOT', str(Path.cwd() / 'output'))).resolve()
    path = Path(destination).resolve()
    if not path.is_relative_to(output_root):
        raise RuntimeError('DOM diagnostic must stay under NEWS_PICK_OUTPUT_ROOT')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('INSTAGRAM_DOM_DIAGNOSTIC=' + json.dumps(report, ensure_ascii=True))
