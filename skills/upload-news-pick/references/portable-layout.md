# 이동 가능한 설치·output 계약

## 소스와 실행물을 분리한다

```text
<installation>/skills/
  search-news/
  plan-news-pick/
  create-news-cards/
  publish-news-pick/
  upload-news-pick/

<workspace>/output/
  runs/<run_id>/
  publish-news-pick/
  profile-candidates/
  cache/
  logs/
```

`skills/`는 읽기 전용 소스로 취급한다. 생성 이미지, 기사 reference, manifest, 게시 job, browser screenshot, 가상환경, cookie·session을 skill 폴더 안에 쓰지 않는다.

## 경로 결정

1. 명령의 명시적 `--output-root`
2. 환경변수 `NEWS_PICK_OUTPUT_ROOT`
3. 현재 작업공간의 `<cwd>/output`

모든 단계는 하나의 절대 `NEWS_PICK_OUTPUT_ROOT`를 공유한다. 명령은 사용자 작업공간에서 실행하고 skill 디렉터리로 `cd`하지 않는다.

PowerShell 예시:

```powershell
$env:NEWS_PICK_OUTPUT_ROOT = (Resolve-Path ./output)
$env:IG_ACCOUNT = 'newspick_studio'
$env:NEWS_PICK_CHROME_PROFILE = 'Profile 3'
```

## 설치 단위

다섯 전문 스킬은 같은 `skills` 부모 아래에 형제 폴더로 설치한다. `upload-news-pick`이 상대 경로로 나머지 네 스킬을 찾기 때문이다. 한 폴더만 복사한 상태라면 실행하지 않고 전체 pack을 설치한다.

필수 외부 실행기는 다음과 같다.

- Python 3.10 이상과 Pillow
- Node.js
- Browser Harness CLI와 사용자가 로그인한 표시형 Chrome profile
- `god-tibo-gpt-image2-skill`; 필요하면 `GOD_TIBO_SKILL_ROOT`로 위치 지정

외부 실행기의 설치 폴더와 Chrome profile은 output이 아니다. 로그인 비밀번호·cookie·session 문자열은 workspace 설정에도 기록하지 않는다.
