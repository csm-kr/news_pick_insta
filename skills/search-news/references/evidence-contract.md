# Evidence 계약

각 claim은 하나의 검증 가능한 문장이다.

```yaml
id: claim-1
text: 검증된 사실
evidence_ids: [press-1, press-2, official-1]
status: verified
```

각 evidence:

```yaml
id: press-1
relation: supports | contradicts | context
source_type: press_article | official_release
publisher: 발행처
canonical_url: https://...
published_at: ISO-8601
updated_at: ISO-8601 또는 null
observed_at: ISO-8601
locator: heading + 문단 순번, JSON-LD 필드, 또는 첨부파일 쪽/표
content_sha256: 원문 snapshot hash
```

같은 통신사 전재, 번역, 포털 재게시, 자매 매체는 독립 근거로 중복 계산하지 않는다. 숫자는 모수·기간·지역·단위까지 locator로 확인한다. 충돌하는 evidence를 숨기지 말고 `contradicts`로 남긴다.

