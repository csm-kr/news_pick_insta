---
name: plan-news-pick
description: 검증된 단일 뉴스 JSON을 중립적이고 강한 첫 카드 후킹, 3~4장 Instagram 카드뉴스 스토리보드, caption과 근거 연결로 바꾼다. 뉴스 카드 기획, 헤드라인 후보 작성, 정치·부동산 중립 문안, upload-news-pick 2단계를 요청할 때 사용한다.
---

# Plan News Pick

`search-news`의 `selected-story.json`에 이미 있는 사실만 편집한다. 검색·이미지 생성·게시를 하지 않고, 이미지 생성기가 문구나 사실을 새로 만들지 못하도록 copy, 수치, 차트 명세와 evidence ID를 이 단계에서 잠근다.

## 1. 입력을 확인한다

- `verification_status=verified`
- 핵심 claim마다 evidence 2개 이상
- 사건 하나만 포함
- topic과 공식 근거 필요 여부가 명시됨

입력에 빈칸이나 충돌이 있으면 추측하지 말고 `search-news`로 되돌린다.

## 2. 장수를 정한다

- 3장: 공식 발표가 명확하고 쟁점이 하나인 단순 사실·속보 후속형
- 4장: 정치, 부동산, 갈등, 조건·예외가 있는 정책, 사실과 입장을 분리해야 하는 해설형

장별 역할과 관찰 사례는 [references/card-news-formulas.md](references/card-news-formulas.md)를 읽는다.

## 3. 후킹 후보 5개를 만든다

후킹은 감정어가 아니라 숫자, 결정, 시점, 영향 대상, 기존 상태와의 차이에서 만든다. [references/hook-patterns.md](references/hook-patterns.md)의 허용 공식을 사용하고 금지 공식을 피한다. 반드시 [references/popular-cardnews-benchmark.md](references/popular-cardnews-benchmark.md)를 읽고, 지표명보다 사람에게 생긴 결과를 먼저 쓴다.

각 후보를 다음으로 채점한다.

- 사실 구체성 0~2
- 생활 영향 0~2
- 즉시 이해 0~2
- 과장 위험 0~-2
- 인간 영향 0~2
- 사진-카피 결속 0~2
- 다음 장의 새 정보 약속 0~2

최고점이 같으면 더 짧은 제목을 선택한다. 제목의 모든 명사·동사·숫자·최상급을 evidence ID에 연결한다.

## 4. 스토리보드를 쓴다

4장 기본:

1. `hook`: 사람에게 생긴 결과 + 가장 강한 비교 숫자. `visual_role`은 현장·인물·사건 사진 중심 훅
2. `verified_facts`: 첫 장에 없던 기준선·추세·확정 사실. `visual_role`은 수치 차트·전후 비교
3. `context_and_positions`: 원인·쟁점·주요 입장과 반론. `visual_role`은 분할 화면·입장 비교·증거 주석
4. `impact_unknowns_sources`: 독자가 비교할 것·적용 조건·미정 + 전체 출처 블록. `visual_role`은 체크리스트·영향표·출처 요약

3장에서는 2장과 3장을 합친다. 한 장에는 결론 하나만 두되 각 장에는 앞 장에 없던 새 사실을 최소 하나 넣는다. 마지막 장을 CTA만으로 쓰지 않는다.

정치·부동산이면 [references/politics-realestate-guide.md](references/politics-realestate-guide.md)를 반드시 읽는다.

## 5. 카피와 caption을 잠근다

- 제목: 12~26자, 2~3행 예상
- 부제: 20~45자, 최대 2행 예상
- 본문: 카드당 55~110자, 2~4문장
- 모든 장: 기준시각
- 1~3장: 보이는 출처 문구를 반복하지 않고 evidence ID로만 연결
- 마지막 장과 caption: 공식 1 + 독립 언론 2 또는 독립 언론 2 이상을 한 번에 표시
- 각 카드: `required_text`, `chart_spec`, `reference_requirements`
- 뉴스픽 제외 매체: `한국경제`, `한경`, `한경BUSINESS`

`required_text`에는 모델이 최종 이미지에 글자 그대로 생성해야 할 제목·숫자·단위·출처를 배열로 둔다. `chart_spec`에는 비교 순서, 축 기준, 평균선, 이름/값 대응을 명시한다. `reference_requirements`에는 필요한 기사 대표 사진과 공식 공시 화면을 적는다.

각 카드에는 비어 있지 않은 `visual_role`을 하나씩 두고 한 세트 안에서 중복하지 않는다. 같은 사진을 크롭만 달리해 반복하는 기획은 금지한다. 카드별 첫 번째 `reference_images`가 될 대표 이미지 요구사항은 서로 다른 사건 사진·공식 화면으로 적고, 공통 사진이 필요하면 두 번째 이후의 보조 reference로만 사용한다.

1~3장의 `required_text`에는 `출처:` 행을 넣지 않는다. 마지막 카드에는 `source_block`을 필수로 두고 사용한 모든 근거를 `publisher`, `date`, `domain`으로 적는다. 마지막 카드의 `required_text`에만 `출처` 제목과 각 항목의 `출처명 · 날짜 · 도메인`을 그대로 넣는다. 카드에는 전체 URL을 길게 넣지 않고, 전체 URL과 locator는 storyboard의 `sources`, caption과 manifest에 보존한다.

caption의 본문은 장별 목차가 아니라 뉴스 기사처럼 이어지는 하나의 문단으로 쓴다. `1장 |`, `2장:`, `다음 장` 같은 카드 번호·순서 안내는 넣지 않는다. 첫 문장에서 사건을 요약하고, 이후 핵심 수치·피해나 영향·남은 위험 또는 행동 정보를 자연스럽게 연결한다. 본문 뒤에 기준시각, 원문 URL, 이미지 출처와 정정 제보 경로를 별도 블록으로 둔다. `AI로 재구성한 인포그래픽`과 그 변형 문구는 넣지 않는다. AI 공개 표시는 게시 단계의 Instagram `AI 콘텐츠` 라벨로 처리한다.

## 6. QA하고 출력한다

[references/copy-qa.md](references/copy-qa.md)의 hard fail을 모두 통과하고 편집 품질 13/16 이상이어야 한다.

```powershell
python scripts/validate_plan.py --story <selected-story.json> --storyboard <storyboard.json>
```

출력:

```text
02-plan/editorial-plan.json
02-plan/storyboard.json
```

검증 실패 시 3단계로 넘기지 않는다.
