from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


PATH = Path(__file__).with_name("scheduled_runner.py")
SPEC = importlib.util.spec_from_file_location("scheduled_runner", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def fake_stream(events):
    """subprocess.run 대체: stream-json 이벤트를 stdout 파일에 쓰고 성공 종료를 흉내 낸다."""

    def run(command, **kwargs):
        stdout = kwargs["stdout"]
        for event in events:
            stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        return CompletedProcess(command, 0)

    return run


class ScheduledRunnerTests(unittest.TestCase):
    def settings(self, output_root):
        return {
            "output_root": Path(output_root),
            "account": "newspick_studio",
            "browser": {
                "engine": "edge",
                "connection_name": "edge9333",
                "cdp_url": "http://127.0.0.1:9333",
                "user_data_dir": "C:/Users/test/AppData/Local/NewsPick/EdgeProfile",
                "profile_directory": "Default",
            },
            "imagegen": {},
        }

    def make_root(self, tmp):
        root = Path(tmp)
        references = root / "skills" / "upload-news-pick" / "references"
        references.mkdir(parents=True)
        (references / "scheduled-result.schema.json").write_text(
            json.dumps({"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}),
            encoding="utf-8",
        )
        return root

    def test_edition_uses_korean_time(self):
        value = MOD.edition_at("17:00", date(2026, 8, 18))
        self.assertEqual(value.isoformat(), "2026-08-18T17:00:00+09:00")

    def test_edge_browser_settings_are_gone(self):
        # 2026-11-06부터 Edge를 쓰지 않는다. workspace.json의 옛 browser 블록은 무시한다.
        for name in ("validate_edge_browser", "EDGE_CONNECTION_NAME", "EDGE_CDP_URL"):
            self.assertFalse(hasattr(MOD, name), name)

    def test_start_window_rejects_catch_up_posts(self):
        scheduled = MOD.edition_at("07:00", date(2026, 8, 18))
        self.assertTrue(MOD.within_start_window(scheduled, scheduled - timedelta(minutes=30)))
        self.assertFalse(MOD.within_start_window(scheduled, scheduled - timedelta(minutes=31)))
        self.assertTrue(MOD.within_start_window(scheduled, scheduled + timedelta(minutes=30)))
        self.assertFalse(MOD.within_start_window(scheduled, scheduled + timedelta(minutes=31)))

    def test_prompt_contains_standing_approval_and_fail_closed_rules(self):
        settings = self.settings("C:/work/output")
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("12:00", date(2026, 8, 18)), settings)
        self.assertIn("예약 정책 범위의 실게시를 사전 승인", prompt)
        self.assertIn("자동 재시도하지 않고", prompt)
        self.assertIn("자연스러운 뉴스 문단 하나", prompt)
        self.assertIn("공개 페이지에서 확인", prompt)
        self.assertIn("30분 전에 시작", prompt)
        self.assertIn("wait_for_publish_time.py", prompt)
        self.assertIn("edition_at 이전에 절대 누르지 않는다", prompt)
        self.assertIn("Get-Content -Raw -Encoding UTF8", prompt)
        self.assertIn("Tibo/GPT Image 백엔드로 전송", prompt)
        self.assertIn("references/content", prompt)
        self.assertIn("references/style", prompt)
        self.assertIn("--approve-public-reference-egress", prompt)
        self.assertIn("이 플래그가 빠진 생성 명령은 한 번도 시도하지 말고", prompt)
        self.assertIn("target editorial lane: hot_news_week", prompt)
        self.assertIn("12:00 `hot_news_week`", prompt)
        self.assertIn("공개 반응", prompt)
        self.assertIn("직전 48시간", prompt)
        self.assertIn("1080×1350 세로형 5장", prompt)
        self.assertIn("15장 후보", prompt)
        self.assertIn("360px 폭", prompt)
        self.assertIn("정치·부동산", prompt)
        self.assertIn("하루 1건", prompt)
        self.assertIn("연속 편성하지 않는다", prompt)
        self.assertIn("Instagram browser: ego lite", prompt)
        self.assertIn("NEWS_PICK_BROWSER=ego", prompt)
        self.assertIn("newspick-instagram", prompt)
        self.assertIn("invoke_edge_browser_harness.py", prompt)
        self.assertNotIn("launch_edge_profile.py", prompt)
        self.assertNotIn("Microsoft Edge only", prompt)
        self.assertIn("기존 사용자 탭은 닫거나 탐색하지 않는다", prompt)
        self.assertIn("ego-browser 직접 스크립트·Chrome·다른 CDP URL로 우회하지 않는다", prompt)
        self.assertIn("composer_busy", prompt)
        self.assertIn("기존 draft를 폐기하지 말고", prompt)
        self.assertIn("IG_DUPLICATE_TOKENS", prompt)
        self.assertIn("browser_web_upload_prepare.py", prompt)
        self.assertIn("existing_confirmed_crop_session", prompt)
        self.assertIn("새 run-local helper를 만들거나", prompt)

    def test_prompt_allows_one_recovery_share_only_after_confirmed_no_post(self):
        settings = self.settings("C:/work/output")
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("07:00", date(2026, 10, 21)), settings)
        self.assertIn("미게시 복구", prompt)
        self.assertIn("NEWS_PICK_SHARE_RECOVERY=1", prompt)
        self.assertIn("NEWS_PICK_SHARE_FAILED_AT", prompt)
        self.assertIn("NEWS_PICK_RUN_DIR", prompt)
        self.assertIn("작성기 dialog가 사라졌고", prompt)
        self.assertIn("게시물 수", prompt)
        self.assertIn("duplicate_match=false", prompt)
        self.assertIn("payload hash가 첫 job과 같을 때만", prompt)
        self.assertIn("회차당 한 번", prompt)
        self.assertIn("복구 공유도 실패하면", prompt)

    def test_prompt_declares_unattended_claude_code_run(self):
        settings = self.settings("C:/work/output")
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("12:00", date(2026, 8, 18)), settings)
        self.assertNotIn("$upload-news-pick", prompt)
        self.assertIn("Claude Code 비대화형", prompt)
        self.assertNotIn("tty: true", prompt)
        self.assertNotIn("CodexSandboxOffline", prompt)
        self.assertNotIn("codex", prompt.replace("CODEX_IMAGEGEN", "").replace(".codex", "").lower())
        self.assertIn("질문하거나 확인을 기다리지 말고", prompt)
        self.assertIn("skipped 또는 needs_review", prompt)
        self.assertIn("게시물을 삭제하시겠어요", prompt)
        self.assertIn("취소", prompt)

    def test_prompt_mentions_configured_imagegen_credentials(self):
        settings = {**self.settings("C:/work/output"), "imagegen": {"auth_file": "C:/Users/test/.codex/auth.json", "model": "gpt-6-astra"}}
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("07:00", date(2026, 8, 18)), settings)
        self.assertIn("--imagegen-auth-file", prompt)
        self.assertIn("C:/Users/test/.codex/auth.json", prompt)
        self.assertIn("--imagegen-model gpt-6-astra", prompt)

    def test_entertainment_prompt_expands_history_and_prioritizes_impact(self):
        settings = self.settings("C:/work/output")
        prompt = MOD.build_prompt(
            Path("C:/work"), MOD.edition_at("07:00", date(2026, 10, 15)), settings
        )
        self.assertIn("target editorial lane: entertainment", prompt)
        self.assertIn("최대 30일을 역추적", prompt)
        self.assertIn("검증 사건 3건", prompt)
        self.assertIn("가장 임팩트가 큰 사건", prompt)
        self.assertIn("공개 반응", prompt)
        self.assertIn("최신성은 임팩트가 비슷할 때만", prompt)

    def test_editorial_lane_uses_requested_topic_by_slot(self):
        # 2026-10-14 사용자 지시: 07시 연예, 12시 핫뉴스(7일 내), 17시 핫뉴스(3일 내)
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("07:00", date(2026, 10, 15))), "entertainment")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("12:00", date(2026, 10, 14))), "hot_news_week")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("17:00", date(2026, 10, 14))), "hot_news_3day")

    def test_07_00_lane_is_asian_games_until_closing_day(self):
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("07:00", date(2026, 9, 26))), "entertainment")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("07:00", date(2026, 9, 27))), "asian_games")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("07:00", date(2026, 10, 2))), "asian_games")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("07:00", date(2026, 10, 3))), "entertainment")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("12:00", date(2026, 9, 27))), "hot_news_week")
        self.assertEqual(MOD.editorial_lane_for(MOD.edition_at("17:00", date(2026, 9, 27))), "hot_news_3day")

    def test_asian_games_prompt_only_during_games(self):
        settings = self.settings("C:/work/output")
        games = MOD.build_prompt(Path("C:/work"), MOD.edition_at("07:00", date(2026, 9, 27)), settings)
        self.assertIn("target editorial lane: asian_games", games)
        self.assertIn("07:00 `asian_games`", games)
        self.assertIn("아이치·나고야 아시안게임", games)
        self.assertIn("단순 경기 결과", games)
        after = MOD.build_prompt(Path("C:/work"), MOD.edition_at("07:00", date(2026, 10, 5)), settings)
        self.assertIn("target editorial lane: entertainment", after)
        self.assertNotIn("07:00 `asian_games`", after)

    def test_hot_news_lanes_use_week_and_three_day_windows(self):
        settings = self.settings("C:/work/output")
        noon = MOD.build_prompt(Path("C:/work"), MOD.edition_at("12:00", date(2026, 10, 14)), settings)
        evening = MOD.build_prompt(Path("C:/work"), MOD.edition_at("17:00", date(2026, 10, 14)), settings)
        self.assertIn("target editorial lane: hot_news_week", noon)
        self.assertIn("target editorial lane: hot_news_3day", evening)
        self.assertIn("12:00 `hot_news_week`는 분야 제한 없이 edition_at 직전 7일", noon)
        self.assertIn("17:00 `hot_news_3day`는 분야 제한 없이 edition_at 직전 3일", noon)
        self.assertIn("오늘 07:00·12:00 회차와 같은 사건은 제외", evening)

    def test_publish_offset_is_random_within_one_to_fifteen_minutes(self):
        offsets = {MOD.choose_publish_offset() for _ in range(200)}
        self.assertTrue(all(60 <= value <= 900 for value in offsets))
        self.assertGreater(len(offsets), 50)

    def test_child_environment_passes_publish_offset(self):
        environment = MOD.child_environment(
            self.settings("C:/work/output"), MOD.edition_at("07:00", date(2026, 8, 18)), base={}, publish_offset=437
        )
        self.assertEqual(environment["NEWS_PICK_PUBLISH_OFFSET_SECONDS"], "437")
        self.assertEqual(environment["NEWS_PICK_EDITION_AT"], "2026-08-18T07:00:00+09:00")

    def test_prompt_tells_gate_may_wait_past_tool_timeout(self):
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("12:00", date(2026, 8, 18)), self.settings("C:/work/output"))
        self.assertIn("NEWS_PICK_PUBLISH_OFFSET_SECONDS", prompt)
        self.assertIn("같은 게이트 명령을 다시 실행", prompt)

    def test_every_lane_prefers_hookable_news(self):
        settings = self.settings("C:/work/output")
        for slot in ("07:00", "12:00", "17:00"):
            prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at(slot, date(2026, 10, 15)), settings)
            self.assertIn("후킹 잠재력", prompt)
            self.assertIn("반전·격차·손실·최초·역대 기록", prompt)
            self.assertIn("검증된 사실만으로 첫 장 제목이 성립", prompt)
            self.assertIn("낚시성", prompt)

    def test_trot_and_idol_lanes_are_retired(self):
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("07:00", date(2026, 10, 15)), self.settings("C:/work/output"))
        self.assertNotIn("`trot`", prompt)
        self.assertNotIn("`idol`", prompt)

    def test_violent_crime_allowed_only_in_hot_news_lanes(self):
        prompt = MOD.build_prompt(Path("C:/work"), MOD.edition_at("17:00", date(2026, 10, 14)), self.settings("C:/work/output"))
        self.assertIn("핫뉴스 lane(`hot_news_week`·`hot_news_3day`)은 경찰·검찰·법원 발표 또는 독립 언론 두 곳으로 확인된 강력범죄 사건도 후보로 비교한다", prompt)
        self.assertIn("피해자 신상", prompt)
        self.assertIn("07:00 `entertainment`에서는 자극적 범죄 소비도 제외한다", prompt)

    def test_entertainment_prompt_has_watchlist(self):
        settings = self.settings("C:/work/output")
        morning = MOD.build_prompt(Path("C:/work"), MOD.edition_at("07:00", date(2026, 10, 15)), settings)
        self.assertIn("target editorial lane: entertainment", morning)
        self.assertIn("리센느", morning)
        self.assertIn("watchlist", morning)
        self.assertIn("최대 30일을 역추적", morning)
        self.assertIn("12:00 `hot_news_week`는 오늘 07:00 회차와 같은 사건을 제외", morning)
        self.assertIn("리센느", MOD.ENTERTAINMENT_WATCHLIST)

    def test_recent_history_contains_only_public_verified_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "output"
            for run_id, topic, published in (
                ("20260818-070000-new", "science_technology", True),
                ("20260817-170000-old", "politics", True),
                ("20260817-120000-draft", "real_estate", False),
            ):
                run = output_root / "runs" / run_id
                (run / "01-search").mkdir(parents=True)
                (run / "04-publish").mkdir(parents=True)
                MOD.atomic_json(run / "01-search" / "selected-story.json", {"edition_at": run_id, "topic": topic, "verified_headline": topic})
                MOD.atomic_json(run / "04-publish" / "result.json", {"status": "published" if published else "submitted", "public_verified": published, "portrait_4x5": published, "card_count": 5 if published else None})
            history = MOD.recent_published_stories(output_root)
            self.assertEqual([item["topic"] for item in history], ["science_technology", "politics"])

    def test_workspace_settings_read_optional_imagegen_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "output").mkdir()
            MOD.atomic_json(
                root / "output" / "workspace.json",
                {
                    "output_root": str(root / "output"),
                    "account": "newspick_studio",
                    "browser": self.settings(root / "output")["browser"],
                    "imagegen": {"auth_file": str(root / "auth.json"), "model": "gpt-6-astra"},
                },
            )
            settings = MOD.workspace_settings(root)
            self.assertNotIn("browser", settings)
            self.assertEqual(settings["imagegen"]["model"], "gpt-6-astra")
            self.assertEqual(settings["imagegen"]["auth_file"], str((root / "auth.json").resolve()))
            environment = MOD.child_environment(settings, MOD.edition_at("07:00", date(2026, 8, 18)), base={})
            self.assertEqual(environment["CODEX_IMAGEGEN_MODEL"], "gpt-6-astra")
            self.assertEqual(environment["CODEX_IMAGEGEN_AUTH_FILE"], str((root / "auth.json").resolve()))
            self.assertEqual(environment["NEWS_PICK_SCHEDULED_MODE"], "1")
            self.assertEqual(environment["NEWS_PICK_BROWSER"], "ego")
            for edge_key in ("BU_NAME", "BU_CDP_URL", "NEWS_PICK_BROWSER_HARNESS_NAME", "NEWS_PICK_EDGE_CDP_URL", "NEWS_PICK_EDGE_USER_DATA_DIR"):
                self.assertNotIn(edge_key, environment)

    def test_prompt_excludes_verified_stories_of_earlier_editions_in_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            settings = self.settings(root / "output")
            target = MOD.edition_at("17:00", date(2026, 11, 7))
            for name, edition, status, verified in (
                ("earlier", "2026-11-07T12:00:00+09:00", "in_progress", "verified"),
                ("cancelled", "2026-11-07T07:00:00+09:00", "cancelled", "verified"),
                ("unverified", "2026-11-07T07:00:00+09:00", "in_progress", "developing"),
                ("same-slot", "2026-11-07T17:00:00+09:00", "in_progress", "verified"),
                ("previous-day", "2026-11-06T12:00:00+09:00", "in_progress", "verified"),
            ):
                run = settings["output_root"] / "runs" / name
                MOD.atomic_json(run / "run.json", {"status": status, "edition_at": edition})
                MOD.atomic_json(run / "01-search/selected-story.json", {"verification_status": verified, "story_id": name, "verified_headline": "reserved-" + name})
            prompt = MOD.build_prompt(root, target, settings)
            self.assertIn("reserved-earlier", prompt)
            for name in ("cancelled", "unverified", "same-slot", "previous-day"):
                self.assertNotIn("reserved-" + name, prompt)
            self.assertIn("공개 게시가 아직 끝나지 않았어도", prompt)

    def test_child_environment_without_imagegen_block_leaves_backend_defaults(self):
        environment = MOD.child_environment(self.settings("C:/work/output"), MOD.edition_at("07:00", date(2026, 8, 18)), base={})
        self.assertNotIn("CODEX_IMAGEGEN_MODEL", environment)
        self.assertNotIn("CODEX_IMAGEGEN_AUTH_FILE", environment)

    def test_find_claude_skips_binary_without_print_schema_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old-claude.exe"
            current = Path(tmp) / "current-claude.exe"
            old.touch()
            current.touch()
            with patch.object(MOD, "claude_candidates", return_value=[old, current]), patch.object(
                MOD, "supports_print_schema", side_effect=lambda path: path == current.resolve()
            ):
                self.assertEqual(MOD.find_claude(), current.resolve())

    def test_claude_candidates_prefer_explicit_executable(self):
        with patch.dict(MOD.os.environ, {"CLAUDE_EXECUTABLE": "C:/tools/claude.exe"}):
            self.assertEqual(MOD.claude_candidates()[0], Path("C:/tools/claude.exe"))

    def test_existing_edition_state_suppresses_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            settings = self.settings(root / "output")
            scheduled = MOD.edition_at("12:00", date(2026, 8, 18))
            state = settings["output_root"] / "scheduler" / "editions" / "2026-08-18-1200.json"
            MOD.atomic_json(state, {"status": "published"})
            with patch.object(MOD, "find_claude") as find:
                code, result = MOD.run_job(root, scheduled, settings, scheduled)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "duplicate_suppressed")
            find.assert_not_called()

    def test_dry_run_command_uses_claude_print_mode_with_schema_and_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            settings = self.settings(root / "output")
            scheduled = MOD.edition_at("17:00", date(2026, 8, 18))
            environ = {k: v for k, v in MOD.os.environ.items() if k not in {"NEWS_PICK_CLAUDE_MODEL", "NEWS_PICK_CLAUDE_EFFORT"}}
            with patch.object(MOD, "find_claude", return_value=Path(__file__)), patch.dict(MOD.os.environ, environ, clear=True):
                code, result = MOD.run_job(root, scheduled, settings, scheduled - timedelta(minutes=30), dry_run=True)
            self.assertEqual(code, 0)
            command = result["command"]
            self.assertEqual(result["executor"], "claude-code")
            self.assertIn("-p", command)
            self.assertIn("--dangerously-skip-permissions", command)
            self.assertEqual(command[command.index("--output-format") + 1], "stream-json")
            self.assertIn("--verbose", command)
            self.assertNotIn("--model", command)
            self.assertEqual(command[command.index("--effort") + 1], MOD.DEFAULT_CLAUDE_EFFORT)
            schema = json.loads(command[command.index("--json-schema") + 1])
            self.assertEqual(schema["required"], ["status"])
            self.assertNotIn("--approve-for-me", command)
            self.assertNotIn("--add-dir", command)

    def test_dry_run_adds_output_root_outside_project_as_allowed_dir(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = self.make_root(tmp)
            settings = self.settings(Path(other) / "output")
            scheduled = MOD.edition_at("17:00", date(2026, 8, 18))
            with patch.object(MOD, "find_claude", return_value=Path(__file__)):
                _code, result = MOD.run_job(root, scheduled, settings, scheduled - timedelta(minutes=30), dry_run=True)
            command = result["command"]
            self.assertEqual(command[command.index("--add-dir") + 1], str(settings["output_root"]))

    def test_build_command_strips_schema_dialect_keys_rejected_by_cli(self):
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "x", "type": "object", "required": ["status"]}
        command = MOD.build_command(Path("C:/tools/claude.exe"), Path("C:/work"), schema, Path("C:/work/output"))
        passed = json.loads(command[command.index("--json-schema") + 1])
        self.assertNotIn("$schema", passed)
        self.assertNotIn("$id", passed)
        self.assertEqual(passed["required"], ["status"])
        self.assertIn("$schema", schema)

    def test_model_and_effort_can_be_overridden_by_environment(self):
        with patch.dict(MOD.os.environ, {"NEWS_PICK_CLAUDE_MODEL": "claude-opus-5", "NEWS_PICK_CLAUDE_EFFORT": "xhigh"}):
            command = MOD.build_command(Path("C:/tools/claude.exe"), Path("C:/work"), {"type": "object"}, Path("C:/work/output"))
            self.assertEqual(command[command.index("--model") + 1], "claude-opus-5")
            self.assertEqual(command[command.index("--effort") + 1], "xhigh")

    def test_run_job_records_structured_output_from_stream_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            settings = self.settings(root / "output")
            scheduled = MOD.edition_at("07:00", date(2026, 8, 18))
            final = {
                "status": "published",
                "summary": "ok",
                "story_headline": "headline",
                "run_directory": str(root / "output" / "runs" / "x"),
                "instagram_url": "https://www.instagram.com/p/abc/",
                "reason": None,
            }
            events = [
                {"type": "system", "subtype": "init", "session_id": "sess-1", "model": "claude-test"},
                {"type": "assistant", "message": {"content": []}, "session_id": "sess-1"},
                {"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-1", "total_cost_usd": 1.25, "num_turns": 9, "result": json.dumps(final), "structured_output": final},
            ]
            with patch.object(MOD, "find_claude", return_value=Path(__file__)), patch.object(MOD.subprocess, "run", side_effect=fake_stream(events)):
                code, result = MOD.run_job(root, scheduled, settings, scheduled - timedelta(minutes=30))
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["executor"], "claude-code")
            self.assertEqual(result["claude_exit_code"], 0)
            self.assertEqual(result["claude_session_id"], "sess-1")
            self.assertEqual(result["final_result"], final)
            result_path = settings["output_root"] / "scheduler" / "results" / "2026-08-18-0700.json"
            self.assertEqual(json.loads(result_path.read_text(encoding="utf-8")), final)
            state = settings["output_root"] / "scheduler" / "editions" / "2026-08-18-0700.json"
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["status"], "published")

    def test_run_job_starts_claude_without_console_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            settings = self.settings(root / "output")
            scheduled = MOD.edition_at("07:00", date(2026, 8, 18))
            final = {"status": "skipped", "summary": "x", "story_headline": None, "run_directory": None, "instagram_url": None, "reason": "no_publishable_story"}
            events = [{"type": "result", "subtype": "success", "is_error": False, "session_id": "s", "result": json.dumps(final), "structured_output": final}]
            calls = []
            stream = fake_stream(events)

            def run(command, **kwargs):
                calls.append(kwargs)
                return stream(command, **kwargs)

            with patch.object(MOD, "find_claude", return_value=Path(__file__)), patch.object(MOD.subprocess, "run", side_effect=run):
                MOD.run_job(root, scheduled, settings, scheduled - timedelta(minutes=30))
            self.assertEqual(calls[-1].get("creationflags", 0), MOD.NO_WINDOW_FLAGS)
            if MOD.sys.platform == "win32":
                self.assertEqual(MOD.NO_WINDOW_FLAGS, MOD.subprocess.CREATE_NO_WINDOW)

    def test_windows_task_uses_pythonw_so_no_console_opens(self):
        script = PATH.with_name("manage_windows_schedule.ps1").read_text(encoding="utf-8")
        self.assertIn("pythonw.exe", script)

    def test_schedule_installer_registers_claude_code_executor(self):
        script = PATH.with_name("manage_windows_schedule.ps1").read_text(encoding="utf-8")
        self.assertIn("auth status --json", script)
        self.assertIn("executor = 'claude-code'", script)
        self.assertIn("News Pick Claude Code print-mode executor", script)
        self.assertNotIn("find_codex", script)
        self.assertNotIn("codex", script.lower())

    def test_run_job_parses_fenced_json_when_structured_output_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            settings = self.settings(root / "output")
            scheduled = MOD.edition_at("12:00", date(2026, 8, 18))
            final = {"status": "skipped", "summary": "no story", "story_headline": None, "run_directory": None, "instagram_url": None, "reason": "no_publishable_story"}
            events = [
                {"type": "system", "subtype": "init", "session_id": "sess-2"},
                {"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-2", "result": "결과:\n```json\n" + json.dumps(final, ensure_ascii=False) + "\n```"},
            ]
            with patch.object(MOD, "find_claude", return_value=Path(__file__)), patch.object(MOD.subprocess, "run", side_effect=fake_stream(events)):
                code, result = MOD.run_job(root, scheduled, settings, scheduled - timedelta(minutes=30))
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["final_result"], final)

    def test_run_job_fails_closed_on_error_result_or_missing_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            settings = self.settings(root / "output")
            scheduled = MOD.edition_at("17:00", date(2026, 8, 18))
            events = [
                {"type": "system", "subtype": "init", "session_id": "sess-3"},
                {"type": "result", "subtype": "error_max_turns", "is_error": True, "session_id": "sess-3", "result": "stopped"},
            ]
            with patch.object(MOD, "find_claude", return_value=Path(__file__)), patch.object(MOD.subprocess, "run", side_effect=fake_stream(events)):
                code, result = MOD.run_job(root, scheduled, settings, scheduled - timedelta(minutes=30))
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(result["final_result"])

            settings2 = self.settings(root / "output2")
            published_without_url = {"status": "published", "summary": "x", "story_headline": "h", "run_directory": None, "instagram_url": None, "reason": None}
            events2 = [{"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-4", "structured_output": published_without_url, "result": json.dumps(published_without_url)}]
            with patch.object(MOD, "find_claude", return_value=Path(__file__)), patch.object(MOD.subprocess, "run", side_effect=fake_stream(events2)):
                code2, result2 = MOD.run_job(root, scheduled, settings2, scheduled - timedelta(minutes=30))
            self.assertEqual(code2, 2)
            self.assertEqual(result2["status"], "failed")

    def test_outside_window_records_skip_without_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            settings = self.settings(root / "output")
            scheduled = MOD.edition_at("07:00", date(2026, 8, 18))
            with patch.object(MOD, "find_claude") as find, patch.object(MOD.subprocess, "run") as run:
                code, result = MOD.run_job(root, scheduled, settings, scheduled + timedelta(hours=2))
            self.assertEqual(code, 0)
            self.assertEqual(result["reason"], "outside_start_window")
            run.assert_not_called()
            find.assert_not_called()
            state = settings["output_root"] / "scheduler" / "editions" / "2026-08-18-0700.json"
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
