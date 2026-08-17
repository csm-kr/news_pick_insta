# 검색과 본문 복구 경로

1. 상태가 검증된 언론 RSS·공식 목록을 직접 조회한다.
2. 후보가 부족할 때 Google News RSS·네이버 검색/섹션으로 넓힌다.
3. 제목·매체명으로 canonical 원문을 찾아 복귀한다.
4. 직접 GET에서 meta/JSON-LD와 출처별 본문 selector를 우선한다.
5. 본문 또는 locator가 부족하면 Jina Reader를 쓴다.
6. 실제 403/challenge가 반복되고 preflight가 통과한 경우에만 insane-search를 검토한다.
7. JS 렌더링이 필수이면 Browser Harness background target을 사용한다.
8. 여전히 실패하면 후보를 제외하거나 `developing`으로 둔다.

실측에서는 직접 RSS/GET이 대체로 0.1~1.8초로 가장 단순했고, Jina와 브라우저는 지연 편차가 컸다. agent-reach/Exa와 insane-search 의존성은 현재 기본 설치가 아니므로 필수 경로에 넣지 않는다.

