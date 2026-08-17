---
name: create-news-cards
description: 검증된 뉴스 스토리보드와 실제 기사 사진·공식 공시 화면을 reference로 받아, Tibo/GPT Image가 한글 카피·수치·차트까지 포함한 1024×1024 완성 카드 12개를 병렬 생성하고 정확한 4장 세트를 QA·확정한다. 뉴스 카드 이미지 제작, 실제 기사 이미지 기반 인포그래픽, 12개 디자인 후보, upload-news-pick 3단계에서 사용한다.
---

# Create News Cards

생성 모델이 완성 카드 전체를 만든다. 실제 기사 대표 사진과 공식 발표·공시 화면을 reference로 제공하고, 모델이 사진 재구성·한글 카피·핵심 수치·차트를 한 이미지 안에서 완성하게 한다. 코드는 렌더링이나 오버레이에 쓰지 않고 크기·해시·장수·매니페스트 QA에만 쓴다.

모든 `--work-dir`은 `<NEWS_PICK_OUTPUT_ROOT>/runs/<run_id>/03-create`처럼 skill 폴더 밖에 둔다. Tibo는 `GOD_TIBO_SKILL_ROOT`, 형제 skill, `$CODEX_HOME/skills`, `~/.agents/skills` 순서로 찾고 없으면 생성 전에 중단한다.

## 1. 입력을 잠근다

`storyboard.json`은 정확히 4장이고 다음을 포함해야 한다.

- `verified_data`: 기준 기간·대상·단위가 붙은 검증 수치
- 각 카드의 `required_text`: 이미지에 정확히 들어갈 한글 문구·숫자. 출처 문구는 마지막 카드에만 포함
- 각 카드의 `chart_spec`: 차트 유형, 정렬, 축, 평균선, 수치 대응
- 각 카드의 `reference_images`: 기사 대표 사진과 공식 화면의 로컬 경로
- 각 카드의 서로 다른 `visual_role`: 현장 사진, 차트, 분할 비교, 체크리스트처럼 장마다 다른 화면 문법
- 마지막 카드의 `source_block`: 사용한 모든 출처의 출처명·날짜·도메인
- `excluded_publishers`: 계정에서 사용하지 않을 매체. 뉴스픽 기본값에 `한국경제`, `한경`, `한경BUSINESS`를 둔다.

reference가 없거나 원문 출처가 불명확하면 생성하지 않는다. 첫 reference는 카드의 핵심 사진·내용 기준이고 나머지는 보조 근거다. 네 카드가 같은 파일 또는 동일 SHA-256의 이미지를 첫 reference로 함께 쓰면 job 생성을 차단한다. 실제 사진과 공식 화면의 취급 원칙은 [references/image-policy.md](references/image-policy.md)를 읽는다.

스타일 방향을 정할 때는 [references/popular-cardnews-visual-patterns.md](references/popular-cardnews-visual-patterns.md)를 읽고, 실제 인기 표본의 `인간 영향 포토뉴스`, `강조 답변형 해설`, `증거 주석형`을 3개 방향으로 사용한다. 스타일 reference는 내용 reference 뒤에 두고 구성만 참고하며 로고·문구·서체·색을 복제하지 않는다.

## 2. 12개 reference-aware 작업을 만든다

사용자가 확인한 정방형 크기 `1024x1024`를 사용한다. 기존 4:5 결과를 단순 크롭하지 않고 정방형 구도로 다시 생성한다.

```powershell
python scripts/prepare_reference_candidates.py `
  --storyboard <run>/02-plan/storyboard.json `
  --work-dir <run>/03-create `
  --target-size 1024x1024 `
  --confirm-size
```

3개 비주얼 방향 × 4장으로 정확히 12개 job을 만든다. 모든 job은 `detail_level=3`, `batch_size=1`, `workers=1`, `size_mode=controllable`이고 카드별 reference를 가진다. 프롬프트는 모델에 다음을 요구한다.

- 기사 사진을 그대로 붙이지 말고 독창적인 포토에디토리얼 인포그래픽으로 재구성
- 첫 장은 지표명만 제시하지 않고 독자에게 생기는 결과와 비교 숫자를 완전한 문장으로 제시
- 2~4장은 앞 장에 없던 새 사실을 최소 하나씩 추가
- `required_text`의 한글·숫자·단위를 글자 그대로 생성
- `chart_spec`의 값·순서·평균선·공식을 정확히 생성
- reference에 없는 인물·건물·은행 표지·문서·사건을 새로 발명하지 않음
- 가짜 뉴스 로고·가짜 UI·랜덤 미세문자·무관한 3D 오브젝트를 넣지 않음
- 다른 장의 대표 사진 크롭·카메라 각도·주요 인물/사물·배경 구도·차트 형식·텍스트 패널 배치를 반복하지 않음

상세 계약은 [references/god-tibo-12-candidate.md](references/god-tibo-12-candidate.md)를 읽는다.

## 3. 12장을 한 번에 생성한다

먼저 dry-run으로 reference·크기·job 계약을 검증한다.

```powershell
python scripts/generate_candidates.py --work-dir <run>/03-create --workers 12 --dry-run
python scripts/generate_candidates.py --work-dir <run>/03-create --workers 12
```

한 장의 실패가 다른 장의 성공물을 지우지 않는다. `visual-manifest.json.status=complete`이고 12장 모두 1024×1024일 때만 비교 단계로 간다.

## 4. 완성된 방향 세트를 비교한다

```powershell
python scripts/make_contact_sheets.py --work-dir <run>/03-create
```

낱장을 섞기 전에 4장 전체의 일관성을 평가한다. [references/visual-system.md](references/visual-system.md)와 [references/render-qa.md](references/render-qa.md)를 사용한다.

- 첫 장에서 핵심 수치와 이슈가 2초 안에 읽히는가
- 첫 장만 보고 독자에게 왜 중요한지 설명되는가
- 기사 사진이 해당 사건·분야와 직접 연결되는가
- 2~4장에 앞 장과 겹치지 않는 새 사실이 실제로 있는가
- 카드마다 정보 역할이 다르면서 색·타입·그리드가 한 세트인가
- 같은 대표 사진·인물·장면·카메라 각도·주요 오브젝트가 크롭만 달리해 반복되지 않는가
- 한글이 자연스럽고 숫자·은행명·단위가 정확히 대응하는가
- 차트가 0 기준·순서·비교 방향을 왜곡하지 않는가
- 출처가 읽히며 제외 매체가 어디에도 남지 않았는가
- 마지막 카드에 `출처` 제목과 모든 출처명·날짜·도메인이 읽을 수 있게 들어갔는가
- 1~3장에는 반복되는 `출처:` footer가 없고 마지막 카드에만 출처가 모였는가

## 5. 실패한 카드만 재생성한다

한글 오자, 잘못된 숫자, 차트 대응 오류, 무관한 이미지, 가짜 UI 또는 다른 장과 겹치는 이미지가 하나라도 있으면 그 카드 job의 prompt와 reference 순서를 고쳐 해당 카드만 다시 실행한다. 중복 카드 재생성 때는 첫 reference와 `visual_role`을 함께 바꾸고, 단순히 seed나 문장만 바꾸지 않는다. 코드로 글자나 차트를 덮어 고치지 않는다.

재생성 뒤 동일한 확대 육안 QA를 다시 수행한다. 모델 결과가 정확해질 때까지 최종 세트로 확정하지 않는다.

## 6. 픽셀을 바꾸지 않고 최종 세트를 확정한다

```powershell
python scripts/finalize_generated_set.py `
  --work-dir <run>/03-create `
  --storyboard <run>/02-plan/storyboard.json `
  --direction direction-02 `
  --visual-qa-passed
```

이 단계는 선택된 생성물에 대해 원본 SHA-256, 전체 이미지 dHash/MAE, 상단 60% 주요 이미지 dHash/MAE를 비교한다. exact 또는 near duplicate가 발견되면 `duplicate-qa.json`을 남기고 복사를 차단한다. 자동 검사를 통과하고 의미상 같은 인물·장면·크롭 반복에 대한 육안 QA까지 끝난 뒤에만 `slides/01.png`~`04.png`로 그대로 복사한다. `qa-report.json.passed=true`, `checks.no_exact_or_near_duplicate=true`, `pixel_modification=false`가 아니면 게시 단계로 넘기지 않는다.

## 금지

- 무문자 추상 배경을 만든 뒤 Pillow·HTML·CSS로 한글·숫자·차트를 합성하지 않는다.
- 기사와 관계없는 생성 사진, 실제 사건처럼 보이는 가짜 현장, 가짜 문서·로고를 만들지 않는다.
- 정확하지 않은 생성 텍스트를 코드로 가려서 통과시키지 않는다.
- QA 전 후보나 서로 다른 방향의 낱장을 섞어 게시하지 않는다.
- 같은 사진을 확대·좌우 반전·색 보정·다른 텍스트로 위장해 여러 장에 재사용하지 않는다.
