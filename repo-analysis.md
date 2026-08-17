# 당일 뉴스 포토뉴스·Instagram 자동 업로드를 위한 저장소 분석

조사일: 2026-08-17 (Asia/Seoul)  
조사 범위: 각 저장소의 `main` 기본 브랜치 최신 커밋, README 유무, `SKILL.md`/`AGENTS.md`, 디렉터리 구조, 의존성 선언, 핵심 스크립트, 설정·예제·테스트. 세 저장소 모두 GitHub 화면에서 `Private`로 표시됐으며, 현재 인증된 계정으로 원문을 clone해 조사했다. 따라서 아래 GitHub 근거 링크도 로그인 권한이 필요할 수 있다.

| 저장소 | 조사 커밋 | 한 줄 결론 |
|---|---|---|
| `instagram-upload-skill` | [`954f404`](https://github.com/csm-kr/instagram-upload-skill/commit/954f40485fcd98150e7c7879e926415d5180f82d) | 사진 게시기가 아니라 **승인된 MP4/MOV 한 개를 올리는 비공식 private Reel 게시기**다. 승인·중복 방지 상태 머신은 재사용 가치가 높다. |
| `research-master` | [`461d04f`](https://github.com/csm-kr/research-master/commit/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09) | 20분 동안 AI 트렌드 30~40개를 9개 lane으로 조사해 단일 HTML로 만드는 시스템이다. 새 스킬에는 **증거·중복 제거·외부 쓰기 승인 규칙만 축소 이식**해야 한다. |
| `god-tibo-image-lab` | [`3ea5e4b`](https://github.com/csm-kr/god-tibo-image-lab/commit/3ea5e4be61b14f624e01744ac2f3e63cd1c0622e) | 표면 CLI는 이미지 편집용이지만 내부 `tibo.py`는 reference 없는 `controllable` 생성도 허용한다. **장당 한 번 호출하는 얇은 뉴스 이미지 어댑터**가 적합하다. |

세 저장소 모두 최상위 README가 없고, `instagram-upload-skill`과 `research-master`에는 최상위 라이선스 파일도 없다. 코드를 외부 배포할 계획이면 소유자가 같더라도 라이선스 정책을 먼저 명문화해야 한다.

## 먼저 내릴 설계 결론

세 저장소를 합치는 방식은 피해야 한다. 목표에 필요한 최소 경계는 다음 세 개다.

1. **뉴스 조사 코어**: `research-master`의 candidate→verified 승격, 원문 URL·발행 시각·locator, 중복 제거, 반증 보존 규칙만 쓴다. 30~40개 수집, 9개 lane, YouTube 자막, 논문 분석, HTML renderer는 쓰지 않는다.
2. **포토뉴스 제작 코어**: `god-tibo-image-lab/image_lab/tibo.py`의 job 검증·실행·manifest 검증만 감싼다. AI에는 배경/삽화만 생성시키고, 한국어 제목·요약·출처·날짜는 Pillow/HTML 같은 결정적 합성으로 올린다. 이미지 안의 텍스트와 사실을 모델에 맡기면 안 된다.
3. **게시 코어**: v1은 PNG 3~4장을 짧은 MP4로 합쳐 기존 Reel 게시기를 재사용하는 편이 가장 작고 검증 가능하다. 정말 정적 사진 캐러셀을 원한다면 기존 저장소를 재사용한다고 표현할 수 없고, 별도 `carousel` backend와 별도 실게시 검증이 필요하다.

권장 v1 파이프라인은 `당일 후보 수집 → 핵심 기사 1건 검증 → 3~4장 스토리보드 확정 → 장별 배경 생성 → 결정적 카피 합성·QA → MP4 변환 → payload 승인 → Reel 게시 → 공개 결과 확인`이다. 포토뉴스 PNG는 그대로 보존하고, 게시용 MP4는 파생 산출물로 만든다.

## 1. `instagram-upload-skill`

### 목적과 실제 범위

루트 [`SKILL.md`](https://github.com/csm-kr/instagram-upload-skill/blob/954f40485fcd98150e7c7879e926415d5180f82d/SKILL.md)는 검색, 이미지 생성, 사진 게시를 명시적으로 제외하고, 로그인된 전용 Chrome의 session을 메모리로 읽어 **MP4/MOV 한 개**를 Reel로 게시하는 스킬이다. [`publish-policy.json`](https://github.com/csm-kr/instagram-upload-skill/blob/954f40485fcd98150e7c7879e926415d5180f82d/publish-policy.json)도 `media_files_per_job: 1`, 지원 확장자 `.mp4`/`.mov`, 캡션 2,200자 상한을 고정한다.

따라서 현재 코드로 PNG/JPEG 3~4장 캐러셀을 게시할 수 없다. 사용 가능한 경로는 다음 둘뿐이다.

- v1 권장: 이미지 3~4장을 H.264/AAC 1080×1920 MP4로 합쳐 Reel로 게시한다. 저장소가 실제 성공 경로로 기록한 것도 약 15초짜리 1080×1920 Reel이다([`successful-process.md`](https://github.com/csm-kr/instagram-upload-skill/blob/954f40485fcd98150e7c7879e926415d5180f82d/references/successful-process.md)).
- 정적 캐러셀: `album_upload`류의 별도 backend를 새로 설계·검증한다. 기존 `private_reel` job과 상태를 억지로 재사용하지 말고 별도 스키마와 제출 경계를 둬야 한다.

### 핵심 워크플로와 진입점

주 진입점은 [`scripts/reel_queue.py`](https://github.com/csm-kr/instagram-upload-skill/blob/954f40485fcd98150e7c7879e926415d5180f82d/scripts/reel_queue.py)다.

1. `configure --endpoint ... --dedicated-profile`: loopback HTTP CDP endpoint만 받아 `.local/config.json`에 기록한다.
2. `setup_backend.py`: project-local venv에 [`instagrapi==2.18.12`](https://github.com/csm-kr/instagram-upload-skill/blob/954f40485fcd98150e7c7879e926415d5180f82d/requirements.txt)를 설치한다.
3. `probe --account`: 게시 없이 로그인 계정, private session, background target 정리, 포커스 보존을 확인한다.
4. `prepare`: 원본 영상을 job 폴더로 복사하고 account·예약 시각·timezone·caption·파일명·크기·SHA-256을 하나의 `payload_sha256`으로 고정한다.
5. `approve JOB_ID --sha256 ...`: 현재 payload hash가 같을 때만 `approved`로 전환한다.
6. `run-due` 또는 명시적으로 요청된 `daemon`: due job만 실행한다.

[`run_reel.py`](https://github.com/csm-kr/instagram-upload-skill/blob/954f40485fcd98150e7c7879e926415d5180f82d/scripts/run_reel.py)는 ffmpeg로 1초 지점 임시 JPEG cover를 만들고 Browser Harness에 worker 코드를 전달한다. [`private_reel_task.py`](https://github.com/csm-kr/instagram-upload-skill/blob/954f40485fcd98150e7c7879e926415d5180f82d/scripts/private_reel_task.py)는 background target에서 `sessionid`를 읽어 `Client.login_by_sessionid()`에 메모리로만 넘기고 `clip_upload()`를 호출한다.

### 입력·출력 계약

- 입력: Instagram account, ISO-8601 예약 시각/timezone, caption, MP4/MOV 한 개.
- 영속 job: `.local/jobs/<job_id>/job.json`과 복사된 `media/01.mp4|mov`.
- 불변성: media SHA-256·size와 payload SHA-256이 바뀌면 승인 무효.
- 상태: `draft → approved → submitting → published | failed_pre_submit | needs_review`.
- 결과: 성공 시 private API가 반환한 media PK, shortcode, Reel URL을 attempt 기록에 보존한다.
- 재시도 경계: `clip_upload()` 전 실패만 재승인 가능하며, 호출 뒤 오류·timeout은 `needs_review`이고 자동 재시도하지 않는다.

### 인증·비밀값·외부 의존성

- 사용자가 직접 로그인한 **전용 Chrome profile**, loopback CDP, Browser Harness가 필요하다.
- password, MFA, CAPTCHA, 동의는 자동 처리하지 않는다.
- raw cookie·Authorization·full client settings는 출력하거나 저장하지 않는다.
- `sessionid`는 worker 메모리에서만 `instagrapi`로 전달한다.
- 외부 의존성: Chrome/Chromium, Browser Harness, Python 3.10+, `uv`, ffmpeg/ffprobe, `instagrapi` private API.

### 테스트·검증 상태

[`test_reel_publisher.py`](https://github.com/csm-kr/instagram-upload-skill/blob/954f40485fcd98150e7c7879e926415d5180f82d/scripts/test_reel_publisher.py)의 8개 테스트가 현재 환경에서 모두 통과했다. loopback endpoint, 단일 영상·hash, 이미지 거부, due job 필터, 제출 전/후 실패 상태, 세션 비저장·포커스 보존 정적 검사를 다룬다. 다만 테스트는 실제 Instagram 게시 회귀 테스트가 아니며, 공개 프로필 교차 검증도 코드에 구현돼 있지 않다. 현재 `published` 판정은 `clip_upload()`의 PK/shortcode 응답과 target 정리 성공에 기반한다.

### 그대로 재사용할 부분

- immutable payload와 사용자 승인 hash.
- 제출 직전/직후를 가르는 상태 머신과 비멱등 쓰기 자동 재시도 금지.
- 전용 profile, loopback CDP, background-owned target, 포커스 보존.
- session cookie 비저장·오류 redaction.
- job별 media 복사·hash 재검증과 attempt 감사 기록.

### 얇게 감쌀 부분

- `slides/*.png → publish.mp4` 변환기만 앞에 둔다. 그 뒤에는 기존 `prepare/approve/run-due` 계약을 유지한다.
- 고정된 1초 cover 대신 승인된 첫 장을 cover로 쓰도록 작은 옵션을 추가할 수 있다.
- `published` 뒤 공개 Reel URL/프로필 최신 항목을 읽기 전용으로 확인하는 verifier를 추가한다.
- Windows 호환 venv executable resolver와 파일 lock 어댑터가 필요하다.

### 제외할 부분과 위험

- 매일 상주하는 `daemon`, OS 시작 항목 등록은 v1에서 제외한다. 먼저 1회 실행과 예약 1건을 검증한다.
- 이 저장소는 Windows에서 그대로 동작하기 어렵다. venv Python을 `.local/private-venv/bin/python`으로 고정하고, queue lock은 Unix 전용 `fcntl`을 사용한다. 현재 작업 환경은 Windows이므로 각각 `Scripts/python.exe` 탐색과 cross-platform lock으로 고쳐야 한다.
- 최초 Chrome 실행 예시도 macOS `open -na` 명령이다.
- `instagrapi`는 비공식 private API이므로 계약 변경·계정 제한 위험이 있다. 사용자의 별도 위험 승인 없이는 설치·게시하면 안 된다.
- 정적 사진 캐러셀, 이미지 저작권, 뉴스 팩트 검증, 게시 후 공개 검증은 이 저장소 범위 밖이다.

## 2. `research-master`

### 목적과 실제 범위

루트 [`SKILL.md`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/SKILL.md)는 일반 당일 뉴스가 아니라 AI/LLM/코딩 에이전트/생성 모델/논문 트렌드 전용이다. 기본 계약은 20분, 30~40개 고유 신호, 9개 lane, 3개 영상 전문 lane, 정확한 대중 관심도 지표, 단 하나의 self-contained HTML이다. 새 포토뉴스 한 건에는 대부분 과설계다.

### 핵심 워크플로와 진입점

- [`bootstrap_local.py`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/scripts/bootstrap_local.py): 로컬 bundle의 8개 engine 이름·필수 파일·SKILL hash를 검사한다.
- [`resource_profile.py`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/scripts/resource_profile.py), [`preflight.py`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/scripts/preflight.py): 자원과 `agent-reach`, `gh`, `hf`, `yt-dlp`, ffmpeg 등을 진단한다.
- worker가 [`trend-contract.md`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/references/trend-contract.md)의 JSONL record를 작성한다.
- main agent가 URL/사건을 중복 제거하고 원문·locator·반증을 검토한다.
- [`render_trend_report.py`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/scripts/render_trend_report.py)와 [`validate_trend_report.py`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/scripts/validate_trend_report.py)가 단일 HTML을 만든다.

`researchctl.py`와 deep-research engines는 빠른 trend path의 필수 진입점이 아니다. 루트 스킬도 깊은 조사가 명시적으로 요청된 경우에만 사용하라고 제한한다.

### 입력·출력 계약

trend worker record는 `topic_key`, 제목, 근거에 한정된 요약, 의미, 원문 URL/제목/publisher, platform/source type, 발행·관측 시각, locator, verification status, primary 여부, 실제 metric 이름·값, retrieval layer를 요구한다. 검색 snippet은 candidate일 뿐 verified가 될 수 없다. 같은 upstream 발표의 미러·번역·영상은 한 사건으로 dedupe한다.

별도의 [`evidence-contract.md`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/references/evidence-contract.md)는 atomic claim, supports/contradicts/context, primary·quality, exact locator, 독립 출처, unresolved contradiction을 보존한다. 이 부분이 포토뉴스에 가장 유용하다.

### 인증·외부 의존성

[`trend-sources.md`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/references/trend-sources.md)에 따르면 X는 구성된 platform credential, Facebook은 이미 승인된 read-only access가 있을 때만 쓴다. 로그인·동의·MFA가 나타나면 lane을 unavailable로 표시하고 중단한다. fast path는 Browser Harness를 금지하고 API/RSS/CLI/원문 reader를 우선한다.

로컬 bundle은 `agent-reach`, `watch`, `insane-search`, 2개 insane-research, `paper-scout`, `paper-reading`, `run-auto-research-sm`의 8개 engine을 pin한다([`manifest.lock.json`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/engines/manifest.lock.json)). 실행 환경에는 선택적으로 `agent-reach`, `gh`, `mcporter`, `opencli`, `twitter`, `hf`, `yt-dlp`, ffmpeg/ffprobe가 필요하다.

### 테스트·검증 상태

- `python -m unittest discover -s scripts -p 'test_*.py'`: 19개 통과.
- `bootstrap_local.py --json`: 8개 bundled engine 모두 `ok`.
- 테스트 실행 중 생성된 `engines/watch/scripts/__pycache__`가 배포 제외 경고로 잡혔다. bundle 검증기가 생성 runtime path를 실제로 감지한다는 뜻이며 소스 결함은 아니다.

### 그대로 재사용할 부분

- 검색 결과는 candidate, 원문을 열고 날짜·identity·locator·entailment를 확인해야 verified라는 규칙.
- `published_at`과 `observed_at` 분리, canonical URL과 stable work/event ID dedupe.
- 한 문장에 하나의 검증 가능한 주장, 출처 URL, 근거 요약, 제한·반증 유지.
- 인기와 사실 신뢰도를 분리하고, 없는 metric을 0으로 꾸미지 않는 규칙.
- 외부 쓰기 전에 target/account/action/exact payload/count/verification을 고정하고 승인받는 규칙([`automation-gates.md`](https://github.com/csm-kr/research-master/blob/461d04ffd6aba1ce9451e3cc5d4324ccc0db2f09/references/automation-gates.md)).

### 얇게 감쌀 부분

포토뉴스용 `news-item.json`을 별도로 정의하는 편이 낫다. 최소 필드는 다음이면 충분하다.

```json
{
  "edition_date": "YYYY-MM-DD",
  "timezone": "Asia/Seoul",
  "story_id": "stable-id",
  "headline": "검증된 한 문장",
  "summary": "2~3문장",
  "why_it_matters": "독자 관점 한 문장",
  "published_at": "ISO-8601",
  "sources": [{"url": "https://...", "publisher": "...", "locator": "...", "primary": true}],
  "limitations": [],
  "visual_policy": "editorial-illustration",
  "verification_status": "verified"
}
```

선정 단계는 당일 후보 5~10건 → 상위 1건(또는 명시된 소수) → 원문과 독립 보강 출처 → 반증/업데이트 확인 정도로 제한한다. 속보에서 독립 출처가 아직 없으면 강제로 채우지 말고 `developing`으로 표시해 자동 게시를 막는다.

### 제외할 부분과 위험

- 30~40개 quota, 9개 lane, 3개 YouTube 자막 lane, 논문 분석, attention scoring, 단일 HTML renderer, deep-research engines는 v1에서 제외한다.
- 원 저장소의 source map은 AI 트렌드에 최적화돼 있다. 정치·경제·사회 등 일반 뉴스에는 정부/기관 원문, 공시, 법원, 통계, 통신사·언론사 같은 beat별 source policy가 새로 필요하다.
- 일반 뉴스의 이미지 사용권·초상권·명예훼손·정정 처리 계약은 없다.
- “당일 뉴스”의 지역, 분야, 언어, 마감 시각이 아직 정해지지 않았다. 이 범위가 정해지기 전에는 완전 자동 선택을 약속할 수 없다.

## 3. `god-tibo-image-lab`

### 목적과 실제 범위

루트 [`AGENTS.md`](https://github.com/csm-kr/god-tibo-image-lab/blob/3ea5e4be61b14f624e01744ac2f3e63cd1c0622e/AGENTS.md)는 반드시 project-local `image-lab` launcher를 사용하고 runtime·cache를 저장소 안에 두도록 한다. 실제 스킬 [`god-tibo-image-lab/SKILL.md`](https://github.com/csm-kr/god-tibo-image-lab/blob/3ea5e4be61b14f624e01744ac2f3e63cd1c0622e/god-tibo-image-lab/SKILL.md)는 인페인트, 아웃페인트, 사이즈 베리에이션, 크랍의 네 모드다. 시퀀스·애니메이션은 범위 밖이다.

그러나 저수준 [`image_lab/tibo.py`](https://github.com/csm-kr/god-tibo-image-lab/blob/3ea5e4be61b14f624e01744ac2f3e63cd1c0622e/god-tibo-image-lab/image_lab/tibo.py)는 포토뉴스 생성에 쓸 수 있는 더 작은 계약을 제공한다.

- prompt 형식은 `prompt`, `prompts`, `items` 중 정확히 하나.
- `size_mode`는 `invariant` 또는 `controllable`.
- `invariant`는 reference가 필수이고 `target_size`가 금지된다.
- `controllable`은 `WxH` target size가 필수이며 reference는 필수가 아니다.
- `batch_size`와 `workers`는 1~8.
- Node의 `tibo-batch.mjs --job`을 실행하고 schema v2 manifest의 image path·warning·size check를 읽는다.
- non-dry-run 결과 파일이 없거나 0 byte면 성공으로 인정하지 않는다.

즉 UI나 인페인팅 파이프라인을 가져오지 않고 `build_job()`과 `run_job()`/`run_job_resilient()`만 호출해 뉴스 배경을 처음부터 생성할 수 있다. 단, 이것은 현재 CLI에 공개된 명령이 아니므로 새 스킬의 명시적 adapter가 필요하다.

### 진입점과 입력·출력

- 저장소 진입점: Windows `image-lab.cmd`, POSIX `./image-lab`.
- 공개 CLI([`cli.py`](https://github.com/csm-kr/god-tibo-image-lab/blob/3ea5e4be61b14f624e01744ac2f3e63cd1c0622e/god-tibo-image-lab/image_lab/cli.py)): `preflight`, `doctor`, `inpaint`, `ui`만 노출한다.
- 저수준 생성 입력: UTF-8 prompt, optional references, detail level, batch/workers, size mode, target size, output directory.
- 실행 중간물: job directory의 `job.json`, 생성 backend output/manifest.
- 출력: 검증된 PNG path tuple, raw manifest, backend·size warning.
- timeout: 생성 1건의 기본 상한은 900초.

`run_job_resilient()`는 동일 prompt의 `batch_size`를 한 장짜리 job N개로 쪼개 일부 성공을 보존한다. 하지만 서로 다른 `prompts` 목록은 이 함수가 쪼개지 않는다. 포토뉴스 3~4장은 **서로 다른 프롬프트를 장별 job으로 직접 반복 호출**해야 한 장 실패가 전체를 삼키지 않는다.

### 인증·비밀값·외부 의존성

[`preflight.py`](https://github.com/csm-kr/god-tibo-image-lab/blob/3ea5e4be61b14f624e01744ac2f3e63cd1c0622e/god-tibo-image-lab/image_lab/preflight.py)는 `CODEX_HOME/auth.json`의 ChatGPT access token, account ID, JWT 만료를 읽고, token을 갱신하거나 복사하지 않는다. `installation_id` 부재는 warning이다. 토큰이 만료되면 사용자가 Codex 로그인을 갱신해야 한다.

[`toolchain/versions.env`](https://github.com/csm-kr/god-tibo-image-lab/blob/3ea5e4be61b14f624e01744ac2f3e63cd1c0622e/toolchain/versions.env)는 Node 24.19.0, uv 0.11.29, Python 3.12.13, `god-tibo-gpt-image2-skill` commit `3f10c8d...`를 pin한다. [`pyproject.toml`](https://github.com/csm-kr/god-tibo-image-lab/blob/3ea5e4be61b14f624e01744ac2f3e63cd1c0622e/god-tibo-image-lab/pyproject.toml)의 Python 의존성은 Pillow 12.x, NumPy 2.x, OpenCV 4.10+이며 setup은 project-local Node, ffmpeg/ffprobe와 dependency checkout도 준비한다.

### 테스트·검증 상태

- 전체 스위트는 530개 테스트를 수집했다. 120초 제한의 전체 실행은 완료되지 않아 통과 증거로 쓰지 않는다.
- 핵심 job/run/preflight/mode/variation/CLI 계약 114개는 모두 통과했다.
- 공식 smoke 선택과 거의 같은 CLI/preflight/tibo/studio-contract 묶음 98개도 모두 통과했다. clone에는 project-local toolchain이 설치되지 않아 `test_local_scripts.py`와 실제 유료 생성은 실행하지 않았다.
- 실제 생성은 크레딧을 소모하므로 수행하지 않았다. 로컬 unit test 통과는 private backend의 현재 가용성을 보장하지 않는다.

### 그대로 재사용할 부분

- UTF-8 `job.json`, job key allowlist, size/batch validation.
- project-local runtime·pinned dependency 원칙과 Codex credential 비복사 원칙.
- manifest schema 검사, output file 존재·0-byte 검사, backend warning 보존.
- batch 부분 실패를 숨기지 않는 `RunResult`와 장당 격리 아이디어.
- `preflight`/`doctor`의 인증·runtime 사전 점검.

### 얇게 감쌀 부분

- `generate_news_slide.py`: slide마다 `build_job(prompt=..., size_mode="controllable", target_size=..., batch_size=1)`을 만들어 실행하고, 결과 PNG와 manifest hash를 반환한다.
- 생성 모델에는 사진처럼 보이는 “사실 증거”를 만들게 하지 말고 editorial illustration/abstract visual/background를 요청한다. 실재 인물·사건을 합성 다큐멘터리 사진처럼 제시해야 하는 주제는 자동 생성을 차단하거나 명확히 `AI 생성 이미지`로 표시한다.
- 제목, 숫자, 인용, 출처, 날짜, 로고는 생성 후 결정적으로 합성한다. 원문 근거에 없는 사물·수치·인용은 visual prompt에도 넣지 않는다.
- 각 장별 output directory를 분리하고 장별 재시도/실패를 기록한다. 유료 재시도는 명시한 상한 안에서만 허용한다.

### 제외할 부분과 위험

- from-scratch 뉴스 배경 생성에는 Studio UI, mask editor, inpaint/outpaint/crop, session history, 디자인 reference kit, `ab-test` 자산을 제외한다.
- Tibo backend 자체가 비공식 private 경로이고 경고를 노출한다. 계약이 예고 없이 바뀔 수 있다.
- 자동 token refresh가 없고, 생성 취소도 없으며, 한 건이 최대 900초 걸릴 수 있다.
- 모델이 한글·숫자·정확한 색을 틀릴 수 있다. 그래서 카피를 이미지 생성 프롬프트에 렌더링시키면 안 된다.
- 생성 이미지는 뉴스의 사실 근거가 아니다. 실제 보도사진을 사용하려면 별도의 사용권·출처·편집 허용 범위를 확인해야 한다.

## 권장 결합 계약

새 스킬은 세 저장소 내부 포맷을 서로 직접 알게 하지 말고, 하나의 `edition.json`을 정본으로 두는 편이 안전하다.

```text
research adapter
  → edition.json (검증된 주장·원문·locator·제한)
  → storyboard.json (3~4장 카피·visual prompt·출처 표시)
  → image adapter (장당 1 job, 배경 PNG)
  → deterministic compositor (한국어·출처·AI 표시)
  → QA + asset hashes
  → Reel adapter (PNG→MP4)
  → immutable publish job
  → explicit approval
  → publish + public verification
```

필수 gate는 다음과 같다.

1. **연구 gate**: 모든 외부 사실은 verified 원문 URL과 locator가 있어야 한다. `developing`, contradiction, 핵심 출처 접근 실패는 자동 게시 금지.
2. **편집 gate**: 제목·요약·수치·날짜가 edition의 claim과 정확히 일치해야 한다. 이미지가 사실 증거가 아니라는 표시 정책을 적용한다.
3. **자산 gate**: 정확히 3~4장, 규격·색상 모드·파일 존재·hash·텍스트 overflow·출처 표기·금지된 합성 사진 여부를 검사한다.
4. **게시 gate**: account, 시각, caption, 모든 slide hash, 파생 MP4 hash를 하나의 승인 payload에 포함한다. 승인 후 어느 하나라도 바뀌면 다시 승인한다.
5. **제출 gate**: Instagram 제출 시작 뒤 모호한 실패는 자동 재시도하지 않는다. 공개 URL을 확인하기 전에는 “게시 완료”를 단정하지 않는다.

## v1에서 만들 파일의 최소 범위 제안

이 문서는 계획서가 아니지만, 과설계를 피하기 위한 구현 경계는 다음 정도가 적절하다.

- `SKILL.md`: 전체 오케스트레이션과 승인·실패 규칙.
- `references/news-contract.md`: news item/edition/storyboard schema, source·정정·이미지 표시 정책.
- `scripts/research_news.py`: 소수 후보 정규화·검증 record 검사·dedupe.
- `scripts/generate_slides.py`: Image Lab `tibo.py` 장당 호출과 manifest 검증.
- `scripts/compose_slides.py`: 결정적 한글 카피·출처 합성, 3~4장 QA.
- `scripts/render_reel.py`: slide PNG를 게시용 MP4로 변환.
- `scripts/publish_queue.py`: Instagram 저장소의 queue/state/hash 로직을 Windows 호환으로 최소 이식.
- `tests/`: schema, claim→slide 일치, hash 승인 무효화, 장수·크기·텍스트 overflow, 제출 후 비재시도 테스트.

Research Master의 8개 engine bundle, Image Lab의 Studio 전체, Instagram daemon을 새 스킬 안으로 복사하지 않는다. 필요할 때 외부 저장소의 명시적 경로/commit을 dependency로 고정하고 얇은 adapter로 호출하는 것이 업데이트와 책임 경계를 가장 선명하게 만든다.

## 계획 전에 반드시 정할 미해결 선택

1. Instagram 산출물이 **정적 캐러셀**이어야 하는가, 아니면 **3~4장 포토뉴스를 담은 Reel**이어도 되는가? 현재 코드 재사용성은 Reel 쪽이 압도적으로 높다.
2. 뉴스 범위가 국내 종합, 경제, 테크/AI, 국제 중 무엇인가? `research-master` 원형은 AI 전용이다.
3. 완전 자동 게시인가, exact payload를 매일 사람이 승인하는 반자동인가? 두 참조 저장소의 안전 계약은 후자다.
4. 게시 시각·계정·caption/hashtag 톤·정정/삭제 정책은 무엇인가?
5. AI 삽화만 쓸지, 사용권이 확인된 실제 보도사진도 받을지? 실제 사진을 받으면 별도 provenance와 편집 허용 범위가 필요하다.

이 다섯 선택 가운데 1~3이 정해져야 다음 `plan.md`의 구현 순서와 acceptance criteria를 정확히 잠글 수 있다.
