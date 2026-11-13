# 뉴스픽 작업 기본 설정

- **운영 위치(2026-11-13 사용자 지정): 뉴스픽은 이 폴더(`C:\Users\csm81\Desktop\sm\skills\newspick_studio`)에서 Claude Code로 운영한다. 정기 예약과 실행 기록(`output/`)도 이 폴더를 쓴다. 바탕화면 `뉴스픽` 폴더는 운영을 멈춘 이전 위치다.**
- Instagram 뉴스픽 게시·공개 검증·스토리 작업은 **ego-lite의 `뉴스픽` 프로필(`Profile 2`)에 로그인된 `newspick_studio` 세션**을 기본으로 사용한다.
- 기준 설정은 `output/workspace.json`의 `account`와 `browser` 블록이다. `성민`(`Profile 1`)이나 다른 계정으로 임의 전환하지 않는다.
- Instagram 작업은 `publish-news-pick/scripts/invoke_edge_browser_harness.py`를 통해 실행한다. 공개 뉴스 조사와 기사·공식 자료 수집은 Aside CLI를 사용한다.
- 재개 시 정기 게시 회차는 매일 07·12·17시 KST이며, 19시 스토리는 당일 정규 게시 3건의 공개 검증이 완료된 경우에만 실행한다. 지난 회차를 자동으로 몰아서 게시하지 않는다.
- 사용자가 열어 둔 탭은 이동하거나 닫지 않는다. Windows 명령은 `exec_command`의 `tty: true`를 사용하고, 백그라운드 자식 프로세스 창은 숨긴다.
