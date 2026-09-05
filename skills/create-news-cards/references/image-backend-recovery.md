# 이미지 생성 인증·모델 오류 복구

이미지 backend의 HTTP 401/400은 Instagram DOM 오류와 별개다. Edge 연결이나 작성기를 바꾸지 않는다. `codex login status`의 로그인 표시는 저장된 자격 증명의 존재를 뜻하며, Tibo의 실제 요청 성공을 보장하지 않는다.

## 실행 전

`generate_candidates.py`는 인증 파일의 존재와 현재 모델 설정을 먼저 확인한다. 모델은 `--imagegen-model` → `CODEX_IMAGEGEN_MODEL` → `CODEX_MODEL` → 현재 `CODEX_HOME/config.toml`의 최상위 `model` 순서로 정한다. 프로필 안 모델이나 Tibo의 오래된 고정 기본값을 추측해서 쓰지 않는다. 로컬 `models_cache.json`이 있으면 선택 모델이 목록에 있는지 확인한다. 이 캐시는 실제 생성 권한의 증거가 아니므로 첫 미생성 후보 한 장이 성공한 뒤 나머지를 병렬 생성한다. 실패 시 남은 후보는 `skipped=true`이며 성공 이미지로 세지 않는다. dry-run에는 실제 인증 검증이 없다.

## 401: 실제 인증 경로 확인

1. `backend_runtime.auth_file`과 사용자가 로그인한 CLI의 `CODEX_HOME`을 비교한다. 앱 내 runtime home과 일반 PowerShell의 `$HOME/.codex`가 다를 수 있다. 인증 파일은 경로·존재·수정시각만 확인하고 내용을 출력·복사하지 않는다.
2. 사용자에게 같은 경로에서 `codex login`을 실행하게 한다. 로그인 주소는 Edge에서 열며, 비밀번호·MFA·인증 코드는 사용자가 직접 처리한다. 401만으로 토큰 만료라고 단정하지 않는다.
3. 사용자가 다른 경로에 재로그인했음을 확인한 경우에만 `--imagegen-auth-file <확인한 auth.json>`을 사용한다. 이 값은 생성 자식 프로세스에만 적용하며 앱의 `CODEX_HOME`, 전역 환경변수, 인증 파일을 덮어쓰지 않는다. 다른 홈·계정으로 자동 fallback하지 않는다.

## 400: 서버가 지적한 요청 항목 확인

`IMAGE_BACKEND_DIAGNOSTIC`의 HTTP 상태와 제한된 `type/code/param/message`를 먼저 읽는다. 원문 응답·요청 header·이미지 data URL·토큰은 기록하지 않는다. `model is not supported`이면 로그인이나 reference 크기를 반복해서 바꾸지 않는다. Codex의 현재 모델 목록과 설정을 확인하고 지원 모델을 명시한다. 캐시가 오래됐다면 Codex에서 목록을 갱신한 뒤 재확인한다. 다른 400을 모델 오류로 일반화하지 않는다.

2026-09-05 실측: 앱 runtime home의 자격 증명으로는 401, 사용자가 갱신한 일반 CLI 인증 경로로는 400이었다. 제한된 서버 오류는 기본 요청 모델 `gpt-5.4`의 계정 미지원을 지적했다. 당시 사용자 설정과 로컬 지원 목록에 있던 `gpt-6-astra`를 요청 모델로 지정하자 첫 이미지 생성이 성공했다. 이 모델명을 영구 기본값으로 고정하지 않는다.

## 재개와 검증

실패한 `visual-manifest.json`은 다른 이름으로 보존한다. 공개 reference 전송 승인이 유효한 같은 run에서 다음을 실행한다.

```powershell
python skills/create-news-cards/scripts/generate_candidates.py --work-dir <run>/03-create --imagegen-auth-file <확인한-auth.json> --imagegen-model <현재-지원-모델> --workers 15 --approve-public-reference-egress
```

기존 성공 후보는 보존하고 첫 미생성 후보 성공 후 나머지를 진행한다. HTTP 401/400을 동일 조건으로 일괄 재시도하지 않는다. 후보 수·raw/최종 이미지·한국어·수치·출처·360px 가독성을 다시 검수한다. 시간 의존 뉴스는 게시 전에 원문을 재확인한다. 이미지 생성 성공과 실제 게시 성공은 따로 보고한다.

소스 수정 후 해당 회귀 테스트와 전체 create-news-cards 테스트를 실행한다. 활성 생성·게시 프로세스가 끝난 뒤 `python scripts/bootstrap.py install --update-existing --skills-dir "$HOME/.codex/skills"`로 백업을 포함해 설치본을 갱신하고 변경 파일의 SHA-256을 비교한다. 기존 사용자 변경은 보존하고 이번 수정만 커밋·푸시한다.
