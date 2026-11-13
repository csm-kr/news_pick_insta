---
name: create-news-cards
description: 검증된 5장 뉴스 스토리보드와 실제 기사 사진·공식 화면을 받아, 10개 디렉터 풀에서 3개를 무작위 선택하고 하단 그라데이션 사진 표지·줄글+이미지+표 본문·출처 카드로 된 1080×1350 후보 15장을 생성·QA한다. 뉴스 카드 이미지 제작, 랜덤 디자인 디렉터, upload-news-pick 3단계에서 사용한다.
---

# Create News Cards

중간 카드의 제목·표·사진이 잘리면 [references/crop-loss-recovery.md](references/crop-loss-recovery.md)에 따라 실제 backend raw와 최종본을 비교한다. `audit_generated_crops.py`의 생존 영역·손실량은 진단값일 뿐 내용 QA 통과가 아니다. 잘린 후보는 게시하지 않고 해당 카드만 재생성한다.

이미지 생성의 401/400, 재로그인 후 동일 오류, 지원하지 않는 모델 오류는 [references/image-backend-recovery.md](references/image-backend-recovery.md)를 먼저 따른다. 실행기는 인증 경로와 현재 설정 모델을 기록하고 첫 미생성 후보 성공 후 나머지를 병렬 처리한다. 로그인 표시만으로 실제 인증 성공을 단정하거나 다른 인증 홈으로 자동 전환하지 않는다.

생성 모델이 완성 카드 전체를 만든다. 실제 기사 대표 사진과 공식 발표·공시 화면을 reference로 제공하고, 모델이 사진 재구성·한글 카피·핵심 수치·표를 한 이미지 안에서 완성하게 한다. 코드는 렌더링이나 오버레이에 쓰지 않고 크기·해시·장수·매니페스트 QA에만 쓴다.

모든 `--work-dir`은 `<NEWS_PICK_OUTPUT_ROOT>/runs/<run_id>/03-create`처럼 skill 폴더 밖에 둔다. Tibo는 `GOD_TIBO_SKILL_ROOT`, 형제 skill, `$CODEX_HOME/skills`, `~/.agents/skills` 순서로 찾고 없으면 생성 전에 중단한다. 기사 사진·공식 화면·스타일 reference의 공개 웹 수집에는 `aside-browser`와 Aside CLI를 사용한다. 각 원문의 실제 내용과 이미지 관계를 확인한 뒤 URL·locator·SHA-256을 기록한다. `newspick-instagram` ego 작업 공간은 Instagram 전용이며 공개 reference 수집에 사용하지 않는다.

## 1. 입력을 잠근다

`storyboard.json`은 정확히 5장이고 다음을 포함해야 한다.

- `verified_data`: 기준 기간·대상·단위가 붙은 검증 수치
- 각 카드의 `required_text`: 이미지에 정확히 들어갈 한글 문구·숫자. 출처 문구는 마지막 카드에만 포함
- 2~4장의 `chart_spec`: 2~4행·최대 3열의 표, 정렬, 이름/값 대응
- 각 카드의 `reference_images`: 기사 대표 사진과 공식 화면의 로컬 경로
- 각 카드의 서로 다른 `visual_role`: 현장 사진, 사실표, 분할 비교, 체크리스트처럼 장마다 다른 화면 문법
- 마지막 카드의 `source_block`: 사용한 모든 출처의 출처명·날짜·도메인
- `excluded_publishers`: 계정에서 사용하지 않을 매체. 뉴스픽 기본값에 `한국경제`, `한경`, `한경BUSINESS`를 둔다.

reference가 없거나 원문 출처가 불명확하면 생성하지 않는다. 첫 reference는 카드의 핵심 사진·내용 기준이고 나머지는 보조 근거다. 다섯 카드가 같은 파일 또는 동일 SHA-256의 이미지를 첫 reference로 함께 쓰면 job 생성을 차단한다. 파일이 달라도 `scene_similarity.py`의 dHash(축소본·재인코딩본)와 ORB 특징점 매칭(다른 crop·해상도·영상 캡처로 전재된 같은 장면)에 걸리면 같은 장면으로 보고 job 생성을 차단한다. 이 검사에는 OpenCV(`opencv-python`)와 numpy가 필요하며 없으면 생성 전에 중단한다. 실제 사진과 공식 화면의 취급 원칙은 [references/image-policy.md](references/image-policy.md)를 읽는다.

스타일은 [references/popular-cardnews-visual-patterns.md](references/popular-cardnews-visual-patterns.md)의 10개 디렉터 풀에서 시드 기반으로 3개를 중복 없이 무작위 선택한다. 디렉터는 팔레트·타입·본문 전개만 바꾸며, 1장의 `실제 사진 전면 + 하단 35~42% 그라데이션 + 2행 제목` 구조는 항상 고정한다. 스타일 reference는 내용 reference 뒤에 두고 구성만 참고하며 로고·문구·서체·색을 복제하지 않는다.

### reference 검수 실패 복구

빈 공식 화면이나 원문과 다른 스타일 이미지가 확인되면 그 파일을 생성 입력에서 제외하고, 생성 전에 정상적인 자료 수집을 수정한다. 같은 사건의 확인 가능한 다른 공식 발표·원문 사진, 또는 실제 원문 관계가 확인된 다른 스타일 자료로 대체하고 URL·locator·SHA-256을 다시 검사한다. 필요한 공식 근거를 관련 없는 기사로 대체하지 않는다. 제목 화면에 연락처가 포함됐다면 원문에서 제목·날짜 영역만 다시 캡처한다. reference가 바뀌면 job을 다시 준비해 새 reference hash를 반영한다. 필수 근거가 끝내 없거나 원문 관계가 불명확하면 생성·게시하지 않는다. 사실·개인정보·권한 QA를 낮추거나 통과 기록을 만들지 않는다.

## 2. 15개 reference-aware 작업을 만든다

사용자가 확인한 세로형 크기 `1080x1350`을 사용한다. 정방형으로 되돌리거나 기존 이미지를 사후 크롭해 맞추지 않는다.

```powershell
python scripts/prepare_reference_candidates.py `
  --storyboard <run>/02-plan/storyboard.json `
  --work-dir <run>/03-create `
  --target-size 1080x1350 `
  --confirm-size
```

10개 디렉터 풀에서 3개를 중복 없이 뽑고 선택된 3개 × 5장으로 정확히 15개 job을 만든다. `generation-plan.json`에는 `random_seed`, 선택 디렉터 ID·이름을 기록하며 같은 work-dir에서는 재사용한다. 후보가 생긴 뒤에는 재추첨하지 않는다. 모든 job은 `detail_level=3`, `batch_size=1`, `workers=1`, `size_mode=controllable`, `target_size=1080x1350`, `backend_size=1024x1536`, `resize_fit=cover`, `preserve_backend_raw=true`이고 카드별 reference를 가진다. Tibo의 크기 선택은 backend 요청값이며 실제 원본 크기를 보장하지 않으므로 `raw_size`와 중앙 4:5 crop을 반드시 비교한다. 패딩으로 글자와 이미지가 작아지는 `contain`은 기본 제작에 쓰지 않는다. 프롬프트는 모델에 다음을 요구한다.

- 기사 사진을 그대로 붙이지 말고 독창적인 포토에디토리얼 인포그래픽으로 재구성
- 첫 장은 지표명만 제시하지 않고 독자에게 생기는 결과와 비교 숫자를 완전한 문장으로 제시
- 첫 장은 실제 사진 전면, 하단 그라데이션, 좌측 정렬 2행 제목을 고정하고 부제의 조건·범위를 같은 화면에서 읽히게 함
- 2~4장은 각각 2~3문장 줄글 + 관련 실제 이미지 + 2~4행 표를 명확한 세 구역으로 구성
- 5장은 새 주장 없이 전체 출처·날짜·도메인·기준시각·정정 경로만 표시
- `required_text`의 한글·숫자·단위를 글자 그대로 생성
- `chart_spec`의 표 제목·열·행·값 대응을 정확히 생성
- Tibo 세로 원본의 중앙 4:5 영역을 최종 캔버스로 간주하고 모든 글자·숫자·표 테두리·로고를 최종 좌우·상하 72px 제작 안전영역 안에 완전히 배치
- 프롬프트 맨 앞에 카드 역할별 `SAFE AREA` 문구를 둔다(표지: 상단 160px 무문자·머리줄은 제목 바로 위, 본문: 상·하 110px 빈 배경·좌우 90px·사진 약 26%, 출처: 상·하 110px). 뒤쪽에 둔 같은 지시는 거의 무시됐다.
- reference에 없는 인물·건물·은행 표지·문서·사건을 새로 발명하지 않음
- 가짜 뉴스 로고·가짜 UI·랜덤 미세문자·무관한 3D 오브젝트를 넣지 않음
- 다른 장의 대표 사진 크롭·카메라 각도·주요 인물/사물·배경 구도·표 형식·텍스트 패널 배치를 반복하지 않음

상세 계약은 [references/god-tibo-15-candidate.md](references/god-tibo-15-candidate.md)를 읽는다.

## 3. 15장을 한 번에 생성한다

먼저 dry-run으로 reference·크기·job 계약을 검증한다.

```powershell
python scripts/generate_candidates.py --work-dir <run>/03-create --workers 15 --dry-run
python scripts/generate_candidates.py --work-dir <run>/03-create --workers 15 --approve-public-reference-egress
```

실제 생성 플래그는 사용자가 이번 run의 `references/content`와 `references/style` 아래 공개 기사·공식·스타일 이미지를 Tibo/GPT Image 백엔드로 보내는 것을 승인했을 때만 사용한다. 스크립트는 이 두 폴더 밖의 reference를 코드로 차단한다.

한 장의 실패가 다른 장의 성공물을 지우지 않는다. `visual-manifest.json.status=complete`이고 15장 모두 1080×1350일 때만 비교 단계로 간다.

## 4. 완성된 방향 세트를 비교한다

```powershell
python scripts/make_contact_sheets.py --work-dir <run>/03-create
```

낱장을 섞기 전에 5장 전체의 일관성을 평가한다. [references/visual-system.md](references/visual-system.md)와 [references/render-qa.md](references/render-qa.md)를 사용한다.

- 첫 장에서 핵심 수치와 이슈가 2초 안에 읽히는가
- 첫 장만 보고 독자에게 왜 중요한지 설명되는가
- 첫 장 제목의 결과·격차·반전이 사진·숫자와 한 덩어리로 시선을 장악하는가
- 강한 제목을 만들려고 경고 아이콘·붉은색·비명형 문구를 근거 없이 남용하지 않았는가
- 기사 사진이 해당 사건·분야와 직접 연결되는가
- 2~4장에 앞 장과 겹치지 않는 새 사실, 줄글, 실제 이미지, 표가 모두 있는가
- 카드마다 정보 역할이 다르면서 색·타입·그리드가 한 세트인가
- 같은 대표 사진·인물·장면·카메라 각도·주요 오브젝트가 크롭만 달리해 반복되지 않는가
- 한글이 자연스럽고 숫자·은행명·단위가 정확히 대응하는가
- 표의 행·열·이름/값 대응과 비교 방향이 정확한가
- 출처가 읽히며 제외 매체가 어디에도 남지 않았는가
- 마지막 카드에 `출처` 제목과 모든 출처명·날짜·도메인이 읽을 수 있게 들어갔는가
- 1~4장에는 반복되는 `출처:` footer가 없고 5장에만 출처가 모였는가
- 360px 폭에서 표지 제목·본문 줄글·표 셀·출처 행을 확대 없이 읽을 수 있는가
- `preserve_backend_raw=true`의 raw와 1080×1350 결과를 나란히 비교했을 때 중앙 cover crop으로 글자·표·로고·핵심 사진이 손실되지 않았는가

## 5. 실패한 카드만 재생성한다

한글 오자, 잘못된 숫자, 표 대응 오류, 무관한 이미지, 가짜 UI, crop 손실 또는 다른 장과 겹치는 이미지가 하나라도 있으면 그 카드 job의 prompt와 reference 순서를 고쳐 해당 카드만 다시 실행한다. crop 재생성은 통과한 같은 세트의 1080×1350 카드를 마지막 보조 reference로 추가해 상단 여백·제목 크기·이미지 패널·표 종료 위치만 본받게 한다. 첫 reference는 계속 해당 카드의 사실 기준 이미지여야 한다. 중복 카드 재생성 때는 첫 reference와 `visual_role`을 함께 바꾸고, 단순히 seed나 문장만 바꾸지 않는다. 코드로 글자나 표를 덮어 고치지 않는다.

재생성 뒤 동일한 확대 육안 QA를 다시 수행한다. `cover` 원본에는 필수 문구·표·사진이 모두 정확하지만, 통과한 4:5 카드 reference를 붙인 crop-safe 재생성에서도 중앙 crop만 같은 핵심 요소를 자를 때는 카드 1장에 한해 제한적 폴백을 허용한다. 보존된 backend raw를 비례 축소하고 원본 가장자리 배경색과 일치하는 단색으로 1080×1350 좌우만 채우는 `contain` 결과를 만든다. 새 글자·표·이미지를 덧그리거나 원본 내용을 수정해서는 안 된다. 좌우 띠 경계가 눈에 띄거나, 본문·표가 360px에서 읽히지 않거나, 여백 때문에 세트 리듬이 깨지면 폴백도 실패다. 선택 manifest에는 `resize_fit=contain`, raw sha256, 최종 sha256, 패딩 색, `fallback_reason=repeated_cover_crop_loss`를 기록한다. 그 외에는 모델 결과가 정확해질 때까지 최종 세트로 확정하지 않는다.

## 6. 픽셀을 바꾸지 않고 최종 세트를 확정한다

```powershell
python scripts/finalize_generated_set.py `
  --work-dir <run>/03-create `
  --storyboard <run>/02-plan/storyboard.json `
  --direction <selected-direction-id> `
  --visual-qa-passed
```

이 단계는 선택된 생성물에 대해 원본 SHA-256, 전체 이미지 dHash/MAE, 상단 60% 주요 이미지 dHash/MAE를 비교한다. exact 또는 near duplicate가 발견되면 `duplicate-qa.json`을 남기고 복사를 차단한다. 같은 파일의 `scene_qa`에는 각 카드 job의 대표 reference끼리의 장면 중복과, 여러 카드가 같은 reference 이미지를 재현했는지(카드↔reference ORB 매칭)를 기록하며 하나라도 걸리면 `passed=false`로 복사를 차단한다. 재생성한 카드가 다른 매체의 전재본을 새 reference로 쓰면 여기서 다시 걸린다. AI가 재구성한 인물 사진은 ORB로 reference와 잘 매칭되지 않으므로 같은 인물·장면 반복의 육안 검수는 계속 필요하다. 자동 검사를 통과하고 의미상 같은 인물·장면·크롭 반복에 대한 육안 QA까지 끝난 뒤에만 `slides/01.png`~`05.png`로 그대로 복사한다. `qa-report.json.passed=true`, `checks.no_exact_or_near_duplicate=true`, `pixel_modification=false`가 아니면 게시 단계로 넘기지 않는다.

## 금지

- 무문자 추상 배경을 만든 뒤 Pillow·HTML·CSS로 한글·숫자·표를 합성하지 않는다.
- 기사와 관계없는 생성 사진, 실제 사건처럼 보이는 가짜 현장, 가짜 문서·로고를 만들지 않는다.
- 정확하지 않은 생성 텍스트를 코드로 가려서 통과시키지 않는다.
- QA 전 후보나 서로 다른 방향의 낱장을 섞어 게시하지 않는다.
- 같은 사진을 확대·좌우 반전·색 보정·다른 텍스트로 위장해 여러 장에 재사용하지 않는다.
