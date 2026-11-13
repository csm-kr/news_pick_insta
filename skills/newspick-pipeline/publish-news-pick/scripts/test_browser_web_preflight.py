"""Replay the observed logged-out profile dialog through the real preflight JS."""
import ast
import json
import shutil
import subprocess
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name('browser_web_preflight.py')


class PreflightAuthenticationTests(unittest.TestCase):
    def probe(self, scenario):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for the captured DOM fixture')
        tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
        assignment = next(item for item in ast.walk(tree) if isinstance(item, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'state' for target in item.targets)
                          and isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Name)
                          and item.value.func.id == 'js')
        expression = eval(compile(ast.Expression(assignment.value.args[0]), '<preflight-probe>', 'eval'),
                          {'json': json, 'ACCOUNT': 'newspick_studio', 'DUPLICATE_TOKENS': []})
        fixture = r'''
const fs=require('node:fs');
const mode=process.argv[1];
const loggedIn=mode==='logged_in_text'||mode==='hidden_dialog';
const button=label=>({innerText:label,getAttribute:()=>null});
const buttons=[button('가입하기'),button('로그인')];
const dialog={innerText:'newspick_studio님의 사진, 동영상 등 다양한 콘텐츠를 확인해보세요\n가입하여 newspick_studio님의 게시물을 놓치지 마세요.\n계속하면 Instagram 이용 약관 및 개인정보처리방침에 동의하게 됩니다.\n가입하기\n로그인',
 getBoundingClientRect:()=>({width:mode==='hidden_dialog'?0:540,height:480}),
 querySelectorAll:()=>buttons};
global.getComputedStyle=()=>({display:'block',visibility:'visible'});
global.location={href:mode==='login_route'?'https://www.instagram.com/accounts/login/':'https://www.instagram.com/newspick_studio/',pathname:mode==='login_route'?'/accounts/login/':'/newspick_studio/'};
let tick=0;global.performance={now:()=>tick+=10000};
global.document={body:{innerText:loggedIn?'newspick_studio 프로필 편집 게시물: 로그인·가입하기 안내':'newspick_studio '+dialog.innerText},
 querySelectorAll:selector=>{
  if(selector==='[role="dialog"]'||selector==="[role='dialog']")return mode==='login_dialog'||mode==='hidden_dialog'?[dialog]:[];
  if(selector.includes('/p/'))return [{href:'https://www.instagram.com/newspick_studio/p/previous/',querySelectorAll:()=>[{alt:'Previous post'}]}];
  return loggedIn?[button('만들기')]:buttons;
 },
 querySelector:selector=>selector.includes('svg[')&&loggedIn?{}:null};
Promise.resolve(eval(fs.readFileSync(0,'utf8'))).then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error);process.exitCode=1});
'''
        completed = subprocess.run([node, '-e', fixture, scenario], input=expression,
                                   text=True, encoding='utf-8', capture_output=True, timeout=10,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
        return json.loads(completed.stdout)

    def test_observed_login_signup_dialog_is_an_authentication_boundary(self):
        state = self.probe('login_dialog')
        self.assertTrue(state['login_wall'])
        self.assertFalse(state['ready'])
        self.assertEqual(state['render_attempts'], 1)

    def test_logged_in_caption_words_do_not_create_a_login_boundary(self):
        state = self.probe('logged_in_text')
        self.assertFalse(state['login_wall'])
        self.assertTrue(state['ready'])

    def test_hidden_login_dialog_does_not_block_logged_in_owner(self):
        state = self.probe('hidden_dialog')
        self.assertFalse(state['login_wall'])
        self.assertTrue(state['ready'])

    def test_existing_login_route_still_blocks(self):
        state = self.probe('login_route')
        self.assertTrue(state['login_wall'])
        self.assertFalse(state['ready'])


if __name__ == '__main__':
    unittest.main()
