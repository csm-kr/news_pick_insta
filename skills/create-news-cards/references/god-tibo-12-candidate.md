# Tibo reference-aware 12장 계약

## 실행 구조

- 3개 디자인 방향 × 4장 = 12개 독립 job
- top-level worker 12개로 동시 실행
- 각 child job은 `batch_size=1`, `workers=1`
- `size_mode=controllable`, `target_size=1024x1024`, `detail_level=3`
- 각 job은 카드별 `references`를 1개 이상 가진다.
- 첫 reference는 사진·내용의 canonical 기준이고 이후 이미지는 공식 화면·보조 기사 근거다.
- 카드별 첫 reference는 파일 경로뿐 아니라 SHA-256도 서로 달라야 한다.
- 각 카드는 세트 안에서 고유한 `visual_role`을 가진다.

## 완성 이미지 요구

모델은 배경만 만드는 것이 아니라 다음을 포함한 최종 카드 전체를 생성한다.

- 정확한 한국어 제목·부제·출처
- 검증된 수치·날짜·단위
- 비교 막대·변화선·평균선·구성식
- 실제 기사 사진을 재구성한 포토에디토리얼 비주얼
- 1024×1024 모바일 안전영역과 4장 세트의 공통 그리드

`required_text`는 글자 하나도 바꾸지 않는다. `chart_spec`에 없는 축·수치·주석을 추가하지 않는다.

## 금지

- 무문자 배경만 생성
- reference가 없는 사건 사진·인물·건물·문서·로고 생성
- 가짜 뉴스 UI, 가짜 은행 로고, 랜덤 미세문자, 워터마크 복제
- 한국경제·한경·한경BUSINESS의 이름·로고·기사 화면 포함
- 한글이나 차트 오류를 코드 오버레이로 은폐
- 같은 hero 사진·인물 크롭·카메라 각도·배경 구도·차트 형식을 여러 장에 반복

## 실패 처리

12장 중 실패한 job만 재실행한다. 재생성 전에 오류를 `한글`, `숫자`, `차트 대응`, `reference 무관`, `레이아웃/크롭`, `세트 내 이미지 중복`으로 분류한다. 중복이면 해당 카드의 첫 reference·visual role·구도를 모두 바꾼다. 모든 결과가 생성되어도 확대 육안 QA 전에는 세트를 확정하지 않는다.

## 완료 조건

- `visual-manifest.json.status=complete`
- 후보 12장 모두 1024×1024
- 선택한 4장 전체의 한글·숫자·차트·출처 확대 검수 통과
- `duplicate-qa.json.passed=true`와 의미상 이미지 반복 육안 검수 통과
- `finalize_generated_set.py` 후 `pixel_modification=false`
