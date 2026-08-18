# 워크플로 계약

## 단계와 소유권

| 순서 | 스킬 | 입력 | 출력 | hard stop |
|---|---|---|---|---|
| 1 | `search-news` | edition/checkpoint | verified story | 증거 부족·충돌 |
| 2 | `plan-news-pick` | verified story | editorial plan/storyboard | 선정성·근거 누락 |
| 3 | `create-news-cards` | locked storyboard | selected slides/QA | 12장 미완성·시각 QA 실패·이미지 중복 |
| 4 | `publish-news-pick` | locked slides/caption | public verified result | hash 불일치·계정 불일치 |

각 단계는 앞 단계 내용을 수정하지 않는다. 오류가 있으면 앞 단계로 반환하고 새 산출물 hash를 만든다.

## 재개

- `run.json`은 현재 단계와 단계별 출력 hash를 기록한다.
- 같은 hash의 완료 단계는 재사용한다.
- 완료된 단계의 파일이 바뀌면 그 단계와 모든 뒤 단계 상태를 `pending`으로 되돌린다.
- 외부 제출이 시작된 4단계는 자동 재실행하지 않는다.
- `needs_review`는 공개 프로필을 먼저 확인한 뒤 사람의 결정으로만 해제한다.
- 예약 모드는 날짜·회차별 state를 먼저 만들고 동일 회차 state가 있으면 다시 실행하지 않는다.
- 다른 회차가 실행 중이면 전역 lock으로 새 회차를 시작하지 않는다.
- 예약 시각에서 30분이 지난 missed run은 보충 게시하지 않는다.

## 폴더 계약

모든 산출물은 `NEWS_PICK_OUTPUT_ROOT` 아래에 있어야 한다. 사건별 산출물은 `runs/<run_id>`, 게시 queue와 선택적 backend는 `publish-news-pick`, 프로필 후보는 `profile-candidates`에 둔다. skill 폴더에는 실행물을 쓰지 않는다. 절대 경로나 `..`로 output root 밖의 파일을 출력 계약에 넣지 않는다. 각 JSON은 UTF-8, 정렬 가능한 키, 명시적 `schema_version`을 사용한다.
