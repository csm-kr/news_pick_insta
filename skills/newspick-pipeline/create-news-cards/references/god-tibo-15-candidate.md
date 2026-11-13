# Tibo reference-aware 15장 계약

## 실행 구조

- 10개 디자인 디렉터 풀에서 시드 기반으로 중복 없이 무작위 선택한 3개 디렉터 × 5장 = 15개 독립 job
- `generation-plan.json`에 `random_seed`, 선택 디렉터 ID·이름을 기록한다.
- 같은 work-dir을 다시 준비하면 저장된 시드와 디렉터를 재사용한다. 후보 PNG가 생긴 뒤에는 재추첨하지 않는다.
- top-level worker는 최대 15개, 각 child job은 `batch_size=1`, `workers=1`이다.
- `size_mode=controllable`, `target_size=1080x1350`, `backend_size=1024x1536`, `resize_fit=cover`, `preserve_backend_raw=true`, `detail_level=3`을 사용한다. Tibo 크기 선택은 backend 요청값일 뿐 실제 원본 크기를 잠그지 않으므로 manifest의 `raw_size`와 중앙 4:5 crop을 반드시 검수한다. `contain` 패딩은 글자·이미지를 축소하므로 기본 제작에 쓰지 않는다.
- 각 job은 카드별 reference를 1개 이상 가지며 첫 reference의 경로와 SHA-256은 세트 안에서 서로 달라야 한다.

## 고정 카드 구조

1. 실제 기사 사진 전면 + 하단 35~42% 다크 그라데이션 + 좌측 2행 제목 + 짧은 부제/상태
2. 2~3문장 줄글 + 관련 실제 이미지 + 2~4행·최대 3열 사실표
3. 2~3문장 줄글 + 다른 실제 이미지 + 2~4행·최대 3열 비교표
4. 2~3문장 줄글 + 다른 실제 이미지 + 2~4행·최대 3열 영향/입장표
5. `출처` 제목 + 모든 출처명·날짜·도메인 + 기준시각 + 정정 경로

디렉터는 팔레트·타입·본문의 구역 배치만 변화시킨다. 1장의 하단 그라데이션 표지 구조와 2~4장의 `줄글 + 이미지 + 표`, 5장의 출처 전용 역할은 변경할 수 없다.

## 가독성 계약

- 최종 제작 안전영역은 `x=72..1008`, `y=72..1278`이다. 모든 글자·숫자·표 테두리·로고는 이 안에 완전히 들어가야 한다.
- 표지 제목 86~108px, 본문 제목 58~72px, 본문 34~40px, 표·출처 30~36px를 목표로 한다.
- 360px 폭 미리보기에서 제목·본문·모든 표 셀·출처 행이 확대 없이 읽혀야 한다.
- raw와 최종 이미지를 비교했을 때 cover crop은 배경·사진의 비핵심 가장자리만 제거해야 하고 제목·본문·표·로고·핵심 사진을 하나도 잘라서는 안 된다.
- 본문이 넘치면 글자를 줄이지 말고 기획 단계로 되돌린다.
- 일반 텍스트 대비는 4.5:1 이상을 목표로 한다.

## 금지

- 상단 제목 패널, 정방형 회귀, 2:3 장포스터, 중앙 포스터형 표지
- 무문자 배경만 생성하거나 코드 오버레이로 한글·표를 고치는 행위
- reference가 없는 사건 사진·인물·건물·문서·로고 생성
- 본문을 칩·구호·미세문자로 분해하거나 한 카드에 표 외의 보조 차트를 함께 배치
- 1~4장에 출처 footer를 반복하거나 5장에 새 주장·CTA를 추가
- 같은 hero 사진·인물 crop·카메라 각도·표 형식을 여러 장에 반복

## 완료 조건

- `visual-manifest.json.status=complete`
- 후보 15장 모두 1080×1350
- 모든 후보 manifest에서 `backend_request_size=1024x1536`, `resize_fit=cover`, `preserve_backend_raw=true`, 유효한 `backend_raw.path`·`raw_size`, `result_source=final`
- raw/최종 확대 비교에서 crop 손실 없음. 실패 카드는 통과한 4:5 카드의 레이아웃만 마지막 보조 reference로 추가해 재생성
- 선택한 5장 전체의 한글·숫자·표·출처 확대 검수 통과
- 360px 가독성 육안 검수 통과
- `duplicate-qa.json.passed=true`와 의미상 이미지 반복 육안 검수 통과
- `finalize_generated_set.py` 후 `pixel_modification=false`
