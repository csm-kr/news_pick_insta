---
name: plan-news-pick
description: 검증된 단일 뉴스 JSON을 사진 중심 하단 그라데이션 표지, 줄글·실제 이미지·단순 표가 결합된 본문 3장, 전용 출처 카드로 구성된 가독성 높은 5장 Instagram 스토리보드로 바꾼다. 뉴스 카드 기획, 강한 헤드라인 후보 작성, upload-news-pick 2단계를 요청할 때 사용한다.
---

# Plan News Pick

`search-news`의 `selected-story.json`에 이미 있는 사실만 편집한다. 검색·이미지 생성·게시를 하지 않고, 이미지 생성기가 문구나 사실을 새로 만들지 못하도록 copy, 수치, 표 명세와 evidence ID를 이 단계에서 잠근다.

## 1. 입력을 확인한다

- `verification_status=verified`
- 핵심 claim마다 evidence 2개 이상
- 사건 하나만 포함
- topic과 공식 근거 필요 여부가 명시됨

입력에 빈칸이나 충돌이 있으면 추측하지 말고 `search-news`로 되돌린다.

## 2. 5장 구조를 고정한다

- 카드 수는 정확히 5장이다.
- 1장은 사진 중심 표지, 2~4장은 본문, 5장은 출처 전용 카드다.
- 단순 사건도 본문 3장을 억지로 반복하지 않는다. 2~4장에 넣을 새 사실이 부족하면 제작하지 않고 더 설명력 있는 사건을 다시 고른다.

장별 역할과 관찰 사례는 [references/card-news-formulas.md](references/card-news-formulas.md)를 읽는다.

## 3. 고강도 사실형 후킹 후보 5개를 만든다

기본 톤은 `고강도 사실형`이다. 제목은 감정어 대신 결과·손실·격차·반전·마감시점에서 긴장을 만들고, 부제는 그 결과가 성립하는 조건·주체·범위를 바로 밝혀 오해를 막는다. 제목만 밋밋하게 사실을 요약하거나 기관 발표명을 옮기지 않는다. [references/hook-patterns.md](references/hook-patterns.md)의 허용 공식과 제목-부제 계약을 사용하고 금지 공식을 피한다. 반드시 [references/popular-cardnews-benchmark.md](references/popular-cardnews-benchmark.md)를 읽고, 지표명보다 사람에게 생긴 결과를 먼저 쓴다.

후보 5개는 각각 다음 `hook_type`을 하나씩 사용한다.

- `immediate_consequence`: 지금 누구에게 무엇이 생기는가
- `reversal_contrast`: 기존 상식·상태와 확인된 결과가 어떻게 달라졌는가
- `loss_gap`: 누가 더 내고, 덜 받고, 기다리거나 제외되는가
- `decision_deadline`: 어떤 결정·시점이 결과를 가르는가
- `answerable_question`: 다음 장에서 바로 답할 구체 질문은 무엇인가

각 후보를 다음으로 채점한다.

- 사실 구체성 0~2
- 생활 영향 0~2
- 즉시 이해 0~2
- 긴장도 0~2
- 호기심 간극 0~2
- 시각 장악력 0~2
- 다음 장의 새 정보 약속 0~2
- 과장 위험 0~-2

`score` 키는 `specificity`, `life_impact`, `immediacy`, `tension`, `curiosity_gap`, `visual_grip`, `continuation_value`, `exaggeration_risk`를 정확히 사용한다.

14점 만점에서 11점 이상인 최고점 후보만 선택한다. 최고점이 같으면 더 짧은 제목을 선택한다. 제목의 모든 명사·동사·숫자·최상급을 evidence ID에 연결한다. 11점 후보가 없으면 같은 사실로 후보를 다시 쓰고, 그래도 없으면 해당 사건을 약한 카드로 억지 제작하지 않는다.

## 4. 스토리보드를 쓴다

5장 고정:

1. `hook`: 실제 기사 사진을 전면에 두는 하단 그라데이션 표지. 사람에게 생긴 결과 + 가장 강한 비교 숫자·격차·반전 중 하나를 하단 35~42% 안에 넣고, 제목은 2행 이내로 쓴다.
2. `verified_facts`: 정확히 무슨 일이 있었는지 답하는 2~3문장 줄글 + 관련 실제 이미지 + 2~4행 핵심 사실표.
3. `numbers_and_context`: 기준선·추세·원인·비교를 설명하는 2~3문장 줄글 + 다른 실제 이미지 + 단순 비교표.
4. `impact_and_reactions`: 영향 대상·반응·쟁점·미정 사항을 분리한 2~3문장 줄글 + 다른 실제 이미지 + 영향/입장 비교표. 공개 반응은 선정 맥락으로만 쓰고 사건 사실과 섞지 않는다.
5. `sources`: `출처` 제목, 모든 출처명·날짜·도메인, 기준시각, 정정 경로만 담는다. 새 주장·CTA·장식용 인용을 넣지 않는다.

2~4장은 각각 앞 장에 없던 새 사실을 최소 하나 넣는다. 같은 표 형식과 같은 사진 crop을 반복하지 않는다.

정치·부동산이면 [references/politics-realestate-guide.md](references/politics-realestate-guide.md)를 반드시 읽는다.

## 5. 카피와 caption을 잠근다

- 표지 제목: 12~26자, 2행 예상
- 부제: 20~45자, 최대 2행 예상
- 본문 2~4장: 카드당 60~110자, 2~3문장, 문단 하나
- 본문 2~4장: `chart_spec`을 2~4행·최대 3열의 표로 제한
- 본문 2~4장: 관련 실제 이미지가 카드 면적 35~50%를 차지하도록 `reference_requirements`와 `visual_role`에 명시
- 모든 장: 기준시각
- 1~4장: 보이는 출처 문구를 반복하지 않고 evidence ID로만 연결
- 5장과 caption: 공식 1 + 독립 언론 2 또는 독립 언론 2 이상을 한 번에 표시
- 각 카드: `required_text`, `chart_spec`, `reference_requirements`
- 뉴스픽 제외 매체: `한국경제`, `한경`, `한경BUSINESS`

`required_text`에는 모델이 최종 이미지에 글자 그대로 생성해야 할 제목·숫자·단위·출처를 배열로 둔다. 호환성을 위해 이름을 유지하는 `chart_spec`에는 표의 열 이름, 행 순서와 이름/값 대응만 명시한다. `reference_requirements`에는 필요한 기사 대표 사진과 공식 공시 화면을 적는다.

각 카드에는 비어 있지 않은 `visual_role`을 하나씩 두고 한 세트 안에서 중복하지 않는다. 같은 사진을 크롭만 달리해 반복하는 기획은 금지한다. 카드별 첫 번째 `reference_images`가 될 대표 이미지 요구사항은 서로 다른 사건 사진·공식 화면으로 적고, 공통 사진이 필요하면 두 번째 이후의 보조 reference로만 사용한다.

첫 reference는 파일이 아니라 **장면**이 달라야 한다. 통신사 사진을 다른 매체가 전재한 복사본, 축소본, 같은 순간의 다른 프레임, 영상 캡처는 다른 장면이 아니다. 사건 사진이 사실상 한 장뿐이면(출국·회견·사과 발표처럼 통신사 사진 한 장을 모든 매체가 쓰는 경우) 그 사진은 1장에만 쓰고 2~4장은 공식 보도자료·문서·통계·지도·서비스 화면처럼 사건과 직접 연결된 다른 이미지를 첫 reference로 쓴다. `validate_plan.py`는 `reference_images`가 있으면 첫 reference의 파일 중복과 전재본·축소본(dHash)을 차단하고, 3단계 `prepare_reference_candidates.py`는 특징점 매칭으로 다른 crop·프레임까지 같은 장면을 차단한다.

1~4장의 `required_text`에는 `출처:` 행을 넣지 않는다. 5장에는 `source_block`을 필수로 두고 사용한 모든 근거를 `publisher`, `date`, `domain`으로 적는다. 5장의 `required_text`에만 `출처` 제목과 각 항목의 `출처명 · 날짜 · 도메인`을 그대로 넣는다. 카드에는 전체 URL을 길게 넣지 않고, 전체 URL과 locator는 storyboard의 `sources`, caption과 manifest에 보존한다.

가독성은 하드 요구사항이다. 표지 하단 텍스트와 본문 카드의 줄글·표가 360px 폭에서도 확대 없이 읽혀야 한다. 제목·본문·표가 서로 겹치거나, 본문을 작은 글자로 억지로 넣거나, 한 카드에 표 외의 보조 차트를 더 넣는 기획은 금지한다.

caption의 본문은 장별 목차가 아니라 뉴스 기사처럼 이어지는 하나의 문단으로 쓴다. `1장 |`, `2장:`, `다음 장` 같은 카드 번호·순서 안내는 넣지 않는다. 첫 문장에서 사건을 요약하고, 이후 핵심 수치·피해나 영향·남은 위험 또는 행동 정보를 자연스럽게 연결한다. 본문 뒤에 기준시각, 원문 URL, 이미지 출처와 정정 제보 경로를 별도 블록으로 둔다. `AI로 재구성한 인포그래픽`과 그 변형 문구는 넣지 않는다. AI 공개 표시는 게시 단계의 Instagram `AI 콘텐츠` 라벨로 처리한다.

## 6. QA하고 출력한다

[references/copy-qa.md](references/copy-qa.md)의 hard fail을 모두 통과하고 편집 품질 16/20 이상이어야 한다.

```powershell
python scripts/validate_plan.py --story <selected-story.json> --storyboard <storyboard.json>
```

출력:

```text
02-plan/editorial-plan.json
02-plan/storyboard.json
```

검증 실패 시 3단계로 넘기지 않는다.
