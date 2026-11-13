from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PATH = Path(__file__).with_name("daily_report.py")
SPEC = importlib.util.spec_from_file_location("daily_report", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)

KST = ZoneInfo("Asia/Seoul")
DAY = date(2026, 11, 12)


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def make_run(root: Path, name: str, edition_at: str, status: str, headline: str | None = None, result: dict | None = None,
             lane: str | None = None) -> None:
    run = root / "runs" / name
    write(run / "run.json", {"status": status, "edition_at": edition_at})
    if headline:
        write(run / "01-search" / "selected-story.json", {"verified_headline": headline, "target_editorial_lane": lane})
    if result:
        write(run / "04-publish" / "result.json", result)


class ProfileParseTests(unittest.TestCase):
    # API 호출은 429가 나서(11-12) 프로필 페이지의 og:description만 읽는다.
    def test_parses_korean_og_description(self):
        meta = "팔로워 1,194명, 팔로잉 1,468명, 게시물 210개 - 뉴스픽(@newspick_studio)님의 Instagram 사진 및 동영상 보기"
        self.assertEqual(MOD.parse_profile_meta(meta), {"followers": 1194, "following": 1468, "posts": 210})

    def test_parses_english_og_description_with_k_suffix(self):
        meta = "1.2K Followers, 1,468 Following, 210 Posts - See Instagram photos and videos from 뉴스픽 (@newspick_studio)"
        self.assertEqual(MOD.parse_profile_meta(meta), {"followers": 1200, "following": 1468, "posts": 210})

    def test_unreadable_meta_fails_clearly(self):
        with self.assertRaises(ValueError):
            MOD.parse_profile_meta("Instagram")


class ShareTimeTests(unittest.TestCase):
    def test_maps_shortcode_to_recorded_share_time_from_publish_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp)
            write(jobs / "a" / "job.json", {"account": "newspick_studio", "submission_result": {"recorded_at": "2026-11-11T22:09:36.3Z"},
                                            "public_result": {"shortcode": "AAA"}})
            write(jobs / "b" / "job.json", {"submission_result": None, "public_result": None})
            self.assertEqual(MOD.share_times(jobs), {"AAA": {"at": "2026-11-11T22:09:36.3Z", "account": "newspick_studio"}})


class GrowthTests(unittest.TestCase):
    def test_upsert_keeps_one_snapshot_per_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "followers.jsonl"
            MOD.upsert_snapshot(path, {"date": "2026-11-12", "followers": 1190, "following": 1400})
            MOD.upsert_snapshot(path, {"date": "2026-11-12", "followers": 1194, "following": 1468})
            rows = MOD.load_snapshots(path)
            self.assertEqual(rows, [{"date": "2026-11-12", "followers": 1194, "following": 1468}])

    def test_growth_against_previous_day_and_seven_days(self):
        rows = [
            {"date": "2026-11-05", "followers": 1100, "following": 1300},
            {"date": "2026-11-11", "followers": 1180, "following": 1450},
            {"date": "2026-11-12", "followers": 1194, "following": 1468},
        ]
        g = MOD.growth(rows, DAY)
        self.assertEqual(g["followers"]["day"], {"base": 1180, "delta": 14, "rate": 1.19})
        self.assertEqual(g["followers"]["week"], {"base": 1100, "delta": 94, "rate": 8.55})
        self.assertEqual(g["following"]["day"]["delta"], 18)

    def test_growth_without_history_is_none_not_zero(self):
        g = MOD.growth([{"date": "2026-11-12", "followers": 1194, "following": 1468}], DAY)
        self.assertIsNone(g["followers"]["day"])
        self.assertIsNone(g["followers"]["week"])


class PostsTests(unittest.TestCase):
    def test_lists_three_slots_and_manual_runs_with_instagram_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_run(root, "20261112-063035-a", "2026-11-12T07:00:00+09:00", "completed", "리센느 초동",
                     {"status": "published", "url": "https://www.instagram.com/p/AAA/", "shortcode": "AAA", "verified_at": "2026-11-11T22:20:00Z"})
            # 실제 12시 회차처럼 예약 기록에는 문장만, run 결과 파일에는 사유 코드가 남은 경우
            make_run(root, "20261112-113026-b", "2026-11-12T12:00:00+09:00", "cancelled", "국고채 담합",
                     {"status": "needs_review", "reason": "image_generation_incomplete_and_visual_qa_failed: 결과 없이 종료"})
            write(root / "scheduler" / "editions" / "2026-11-12-1200.json", {
                "status": "needs_review", "started_at": "2026-11-12T11:30:02+09:00", "completed_at": "2026-11-12T12:41:10+09:00",
                "final_result": {"reason": "복구 생성에서도 이미지 결과가 누락됐습니다."}})
            make_run(root, "20261112-225827-c", "2026-11-12T22:58:00+09:00", "completed", "젠슨 황 사임",
                     {"status": "published", "url": "https://www.instagram.com/p/CCC/", "shortcode": "CCC", "verified_at": "2026-11-12T14:35:55Z"})
            make_run(root, "20261111-163023-d", "2026-11-11T17:00:00+09:00", "completed", "어제 것",
                     {"status": "published", "url": "https://www.instagram.com/p/DDD/", "shortcode": "DDD"})
            posts = MOD.todays_posts(root, DAY, {"AAA": {"at": "2026-11-11T22:09:36Z", "account": "newspick_studio"}})
            self.assertEqual([p["slot"] for p in posts], ["07:00", "12:00", "17:00", "수동 22:58"])
            self.assertEqual(posts[0]["status"], "published")
            self.assertEqual(posts[0]["posted_at"], "07:09")
            self.assertEqual(posts[0]["account"], "newspick_studio")
            self.assertEqual(posts[0]["shared_at"], "2026-11-11T22:09:36Z")
            self.assertEqual(posts[1]["status"], "needs_review")
            self.assertEqual(MOD.short_reason(posts[1]["note"]), "이미지 생성 결과 누락")
            self.assertEqual(posts[2]["status"], "없음")
            # 공유 기록이 없으면 공개 검증 시각으로 대신하고 그렇다고 표시한다
            self.assertEqual(posts[3]["posted_at"], "23:35*")
            # 시작은 예약 기록, 없으면 run 폴더 이름의 시각. 종료는 예약 기록의 완료 시각
            self.assertEqual((posts[0]["started_at"], posts[1]["started_at"], posts[3]["started_at"]), ("06:30", "11:30", "22:58"))
            self.assertEqual(posts[1]["ended_at"], "12:41")
            self.assertIsNone(posts[2]["started_at"])


class EgoUsedTests(unittest.TestCase):
    SESSIONS = [
        {"at": "2026-11-12T21:30:00+00:00", "space": "newspick-instagram", "profile_id": "Profile 1", "profile_name": "성민"},
        {"at": "2026-11-12T21:50:00+00:00", "space": "newspick-growth", "profile_id": "Profile 2", "profile_name": "뉴스픽"},
        {"at": "2026-11-12T22:05:00+00:00", "space": "newspick-instagram", "profile_id": "Profile 2", "profile_name": "뉴스픽"},
        {"at": "2026-11-13T01:00:00+00:00", "space": "newspick-growth", "profile_id": "Profile 2", "profile_name": "뉴스픽"},
    ]

    def test_latest_connection_of_the_space_before_the_share(self):
        shared = datetime(2026, 11, 13, 7, 9, 36, tzinfo=KST)  # 2026-11-12T22:09:36Z
        self.assertEqual(MOD.ego_used(self.SESSIONS, "newspick-instagram", shared), "뉴스픽 (Profile 2)")

    def test_no_connection_within_window_is_none(self):
        late = datetime(2026, 11, 13, 12, 0, tzinfo=KST)
        self.assertIsNone(MOD.ego_used(self.SESSIONS, "newspick-instagram", late))

    def test_last_connection_of_a_space(self):
        self.assertEqual(MOD.last_ego(self.SESSIONS, "newspick-instagram"), {"label": "뉴스픽 (Profile 2)", "at": "07:05"})
        self.assertIsNone(MOD.last_ego(self.SESSIONS, "nope"))

    def test_profiles_used_by_a_space_on_a_day(self):
        self.assertEqual(MOD.ego_used_on(self.SESSIONS, "newspick-growth", date(2026, 11, 13)), "뉴스픽 (Profile 2)")
        self.assertIsNone(MOD.ego_used_on(self.SESSIONS, "newspick-growth", date(2026, 11, 14)))


class ReplacementTests(unittest.TestCase):
    def test_manual_run_recorded_as_replacement_fills_the_regular_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "scheduler" / "editions" / "2026-11-13-0700.json", {"status": "skipped", "started_at": "2026-11-13T06:30:01+09:00"})
            make_run(root, "20261113-072517-a", "2026-11-13T07:25:17+09:00", "completed", "코첼라",
                     {"status": "published", "url": "u", "shortcode": "K1"})
            write(root / "scheduler" / "editions" / "2026-11-13-0700.replacement.json", {"slot": "07:00", "run_id": "20261113-072517-a"})
            posts = MOD.todays_posts(root, date(2026, 11, 13), {"K1": {"at": "2026-11-12T22:47:00Z", "account": "newspick_studio"}})
            self.assertEqual([p["slot"] for p in posts], ["07:00", "12:00", "17:00"])
            self.assertEqual(posts[0]["status"], "published")
            self.assertTrue(posts[0]["replaced"])
            self.assertEqual((posts[0]["started_at"], posts[0]["posted_at"]), ("07:25", "07:47"))


class ScheduleListTests(unittest.TestCase):
    NOW = datetime(2026, 11, 13, 8, 45, tzinfo=KST)

    def test_upcoming_tasks_in_time_order_with_korean_labels(self):
        schedule = [
            {"name": "NewsPickUnfollow-Weekly", "state": "Ready", "next_run": "2026-11-16T00:30:00", "last_result": 0},
            {"name": "NewsPickInstagram-1200", "state": "Ready", "next_run": "2026-11-13T11:30:00", "last_result": 0},
            {"name": "NewsPickFollow-Morning", "state": "Ready", "next_run": "2026-11-13T09:48:00", "last_result": 0},
            {"name": "NewsPickInstagram-0700", "state": "Ready", "next_run": "2026-11-14T06:30:00", "last_result": 0},
            {"name": "NewsPickInstagram-DailyStory-1900", "state": "Ready", "next_run": "2026-11-13T19:00:00", "last_result": 0},
            {"name": "NewsPickDailyReport-1930", "state": "Disabled", "next_run": "2026-11-13T19:30:00", "last_result": 0},
        ]
        self.assertEqual(MOD.upcoming_lines(schedule, self.NOW), [
            "- 09:48 팔로우 (오전)",
            "- 11:30 12시 회차 준비 → 12:01~12:15 사이 게시",
            "- 19:00 스토리 (정규 3건 공개 검증 시)",
            "- 내일 06:30 07시 회차 준비 → 07:01~07:15 사이 게시",
            "- 11/16(월) 00:30 언팔 (맞팔 아닌 계정, 7일 유예)",
            "- (꺼짐) 일일 보고",
        ])

    def test_durations_of_published_posts(self):
        posts = [
            {"slot": "07:00", "status": "published", "started_at": "07:25", "posted_at": "07:47", "replaced": True},
            {"slot": "12:00", "status": "published", "started_at": "11:30", "posted_at": "12:09*"},
            {"slot": "17:00", "status": "없음", "started_at": None, "posted_at": None},
        ]
        self.assertEqual(MOD.duration_line(posts), "걸린 시간: 07:00 22분 (수동 대체) · 12:00 39분")
        self.assertIsNone(MOD.duration_line(posts[2:]))


class ShortReasonTests(unittest.TestCase):
    def test_known_codes_become_short_korean(self):
        self.assertEqual(MOD.short_reason("image_generation_incomplete_and_visual_qa_failed: 정상 복구 생성도 결과 없이 종료"), "이미지 생성 결과 누락")
        self.assertEqual(MOD.short_reason("no_publishable_story"), "올릴 만한 새 사건 없음")
        self.assertEqual(MOD.short_reason("composer_busy"), "다른 게시가 작성 중")

    def test_unknown_text_is_clipped(self):
        long = "복구 생성에서도 이미지 결과가 누락됐습니다. 후보 15장과 최종 QA 조건을 충족하지 못했으며, 성공 이미지와 실패 기록은 보존했습니다."
        clipped = MOD.short_reason(long)
        self.assertLessEqual(MOD.display_width(clipped), 40)
        self.assertTrue(clipped.endswith("…"))
        self.assertIsNone(MOD.short_reason(None))


class StoryTests(unittest.TestCase):
    def test_skipped_story_reports_how_many_posts_were_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "logs" / "scheduler" / "daily-story" / "2026-11-12-1900.stderr.log"
            log.parent.mkdir(parents=True)
            log.write_text('{"ok": false, "error": "21:00 batch requires exactly 3 publicly verified posts; found 2"}\n', encoding="utf-8")
            write(root / "scheduler" / "daily-story" / "editions" / "2026-11-12-1900.json",
                  {"status": "failed_pre_submit", "stderr_log": str(log), "started_at": "2026-11-12T19:00:02+09:00"})
            self.assertEqual(MOD.story_status(root, DAY), {"status": "not_posted", "reason": "정규 게시 2/3건", "at": "19:00"})

    def test_published_and_missing_story(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(MOD.story_status(root, DAY))
            write(root / "scheduler" / "daily-story" / "editions" / "2026-11-12-1900.json",
                  {"status": "published", "started_at": "2026-11-12T19:00:02+09:00", "completed_at": "2026-11-12T19:06:40+09:00"})
            self.assertEqual(MOD.story_status(root, DAY), {"status": "published", "reason": None, "at": "19:06"})

    def test_latest_run_wins_when_a_slot_was_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_run(root, "20261110-161941-a", "2026-11-10T17:00:00+09:00", "cancelled", "첫 시도")
            make_run(root, "20261110-164502-b", "2026-11-10T17:00:00+09:00", "completed", "재시도",
                     {"status": "published", "url": "u", "shortcode": "S"})
            posts = MOD.todays_posts(root, date(2026, 11, 10), {})
            self.assertEqual(posts[2]["headline"], "재시도")


class ActivityTests(unittest.TestCase):
    def test_counts_only_successful_follow_and_unfollow_of_the_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            follow = root / "follow" / "follow_log.jsonl"
            follow.parent.mkdir(parents=True)
            follow.write_text("\n".join(json.dumps(r) for r in [
                {"step": "follow", "status": 200, "at": "2026-11-12T10:00:00+09:00"},
                {"step": "follow", "status": 200, "at": "2026-11-12T15:00:00+09:00"},
                {"step": "follow", "status": 429, "at": "2026-11-12T15:01:00+09:00"},
                {"step": "follow", "status": 200, "at": "2026-11-11T15:00:00+09:00"},
            ]) + "\n", encoding="utf-8")
            unfollow = root / "unfollow" / "20261112-manual" / "unfollow_log.jsonl"
            unfollow.parent.mkdir(parents=True)
            unfollow.write_text("\n".join(json.dumps(r) for r in [
                {"step": "unfollow", "status": 200, "at": "2026-11-12T23:40:00+09:00"},
                {"step": "skip_mutual", "at": "2026-11-12T23:41:00+09:00"},
                {"step": "unfollow", "status": 200, "at": "2026-11-13T00:10:00+09:00"},
            ]) + "\n", encoding="utf-8")
            self.assertEqual(MOD.activity(root, DAY), {"follow": 2, "unfollow": 1})


class EgoProfileTests(unittest.TestCase):
    def test_reports_configured_and_actual_space_profile(self):
        spaces = [
            {"name": "newspick-instagram", "profileId": "Profile 2", "profileName": "뉴스픽"},
            {"name": "other", "profileId": "Profile 1", "profileName": "성민"},
        ]
        info = MOD.ego_profile({"browser": {"ego_profile_id": "Profile 2", "ego_profile_name": "뉴스픽"}}, spaces)
        self.assertEqual(info, {"configured": "뉴스픽 (Profile 2)", "space": "뉴스픽 (Profile 2)", "match": True})

    def test_mismatch_and_missing_space_are_visible(self):
        cfg = {"browser": {"ego_profile_id": "Profile 2", "ego_profile_name": "뉴스픽"}}
        wrong = MOD.ego_profile(cfg, [{"name": "newspick-instagram", "profileId": "Profile 1", "profileName": "성민"}])
        self.assertFalse(wrong["match"])
        missing = MOD.ego_profile(cfg, [])
        self.assertEqual(missing["space"], "공간 없음")
        self.assertIsNone(missing["match"])


class EgoSpacesParseTests(unittest.TestCase):
    def test_reads_space_list_even_when_cli_prints_it_to_stderr(self):
        listing = '[{"name":"newspick-instagram","profileId":"Profile 2","profileName":"뉴스픽"}]'
        self.assertEqual(MOD.parse_spaces("", listing)[0]["profileId"], "Profile 2")
        self.assertEqual(MOD.parse_spaces(listing + "\n", "")[0]["name"], "newspick-instagram")


class WarningTests(unittest.TestCase):
    def test_intentional_unfollow_pause_is_not_a_warning(self):
        schedule = [
            {"name": "NewsPickUnfollow-Weekly", "state": "Ready", "last_result": 4},
            {"name": "NewsPickInstagram-1200", "state": "Ready", "last_result": 2},
            {"name": "NewsPickFollow-Morning", "state": "Disabled", "last_result": 1},
        ]
        # 꺼진 작업은 그 회차가 아예 돌지 않는다는 뜻이라 결과 코드와 상관없이 알린다(11-13 실제로 4개가 꺼져 있었다)
        self.assertEqual(MOD.schedule_warnings(schedule),
                         ["NewsPickInstagram-1200 최근 결과 코드 2", "NewsPickFollow-Morning 꺼져 있음"])


class RenderTests(unittest.TestCase):
    def report(self, **over):
        base = {
            "date": "2026-11-12", "generated_at": "2026-11-12T19:30:00+09:00", "account": "newspick_studio",
            "ego": {"configured": "뉴스픽 (Profile 2)", "space": "뉴스픽 (Profile 2)", "match": True},
            "posts": [
                {"slot": "07:00", "status": "published", "started_at": "06:30", "ended_at": "07:14", "posted_at": "07:09",
                 "account": "newspick_studio", "headline": "리센느 PULSE 초동 60만 장 돌파", "url": "https://www.instagram.com/p/AAA/", "note": None,
                 "ego": "뉴스픽 (Profile 2)"},
                {"slot": "12:00", "status": "needs_review", "started_at": "11:30", "ended_at": "12:41", "posted_at": None,
                 "account": None, "headline": "국고채 담합", "url": None, "note": "image_generation_incomplete_and_visual_qa_failed: x"},
                {"slot": "17:00", "status": "없음", "started_at": None, "ended_at": None, "posted_at": None,
                 "account": None, "headline": None, "url": None, "note": None},
                {"slot": "수동 22:58", "status": "published", "started_at": "22:58", "ended_at": None, "posted_at": "23:35",
                 "account": "newspick_studio", "headline": "젠슨 황 사임", "url": "u", "note": None},
            ],
            "story": {"status": "not_posted", "reason": "정규 게시 2/3건", "at": "19:00"},
            "profile": {"followers": 1194, "following": 1468, "posts": 210},
            "growth": MOD.growth([{"date": "2026-11-11", "followers": 1180, "following": 1450},
                                  {"date": "2026-11-12", "followers": 1194, "following": 1468}], DAY),
            "activity": {"follow": 46, "unfollow": 20}, "growth_ego": "뉴스픽 (Profile 2)",
            "schedule": [{"name": "NewsPickInstagram-0700", "state": "Ready", "next_run": "2026-11-13T06:30:00", "last_result": 0}],
            "warnings": [],
        }
        base.update(over)
        return base

    def test_clip_respects_display_width(self):
        self.assertEqual(MOD.clip("가나다라마", 7), "가나다…")
        self.assertEqual(MOD.clip("abc", 7), "abc")
        self.assertIsNone(MOD.clip(None, 7))

    def test_brief_lines_per_slot(self):
        lines = MOD.render(self.report()).splitlines()
        self.assertEqual(lines[0], "뉴스픽 보고 (11/12) · 19:30 기준")
        self.assertIn("- 07:00 ✅ 게시 (06:30 시작 → 07:09 게시)", lines)
        self.assertIn("  - ego: 뉴스픽 (Profile 2) · 계정 @newspick_studio", lines)
        self.assertIn("  - 리센느 PULSE 초동 60만 장 돌파 · https://www.instagram.com/p/AAA/", lines)
        self.assertIn("- 12:00 ❌ 검토 필요 (11:30 시작 → 12:41 종료): 이미지 생성 결과 누락", lines)
        self.assertIn("- 수동 ✅ 게시 (22:58 시작 → 23:35 게시)", lines)
        self.assertIn("  - 국고채 담합", lines)
        self.assertIn("- 17:00 ⚠️ 실행 기록 없음", lines)
        self.assertIn("- 19:00 스토리 ⏭ 안 올림: 정규 게시 2/3건", lines)
        self.assertIn("- 팔로워 1,194 (전일 +14 · +1.19%) · 팔로잉 1,468 (전일 +18)", lines)
        self.assertIn("- 팔로우 46 · 언팔 20 (ego: 뉴스픽 (Profile 2))", lines)
        # 연결 기록이 없는 게시는 설정값으로 채우지 않고 기록 없음으로 둔다
        self.assertIn("  - ego: 기록 없음 · 계정 @newspick_studio", lines)
        self.assertIn("- ego 게시 공간: 뉴스픽 (Profile 2) ✓ 설정과 일치", lines)
        self.assertIn("- 예약 이상: 없음", lines)

    def test_status_mode_header_and_next_schedule_section(self):
        report = self.report(mode="status", generated_at="2026-11-12T08:45:00+09:00")
        report["schedule"] = [{"name": "NewsPickInstagram-1200", "state": "Ready", "next_run": "2026-11-12T11:30:00", "last_result": 0}]
        text = MOD.render(report)
        self.assertTrue(text.startswith("지금 보고 (11/12) · 08:45 기준"))
        self.assertIn("다음 일정 (예약 등록 완료)", text)
        self.assertIn("- 11:30 12시 회차 준비 → 12:01~12:15 사이 게시", text)
        self.assertIn("걸린 시간: 07:00 39분", text)

    def test_stale_follower_count_shows_its_date(self):
        report = self.report(profile={"followers": 1194, "following": 1468, "posts": None, "as_of": "2026-11-11"},
                             growth=MOD.growth([], DAY))
        self.assertIn("- 팔로워 1,194 (11/11 기준) · 팔로잉 1,468", MOD.render(report).splitlines())

    def test_no_open_space_shows_last_real_connection(self):
        report = self.report(ego={"configured": "뉴스픽 (Profile 2)", "space": "공간 없음", "match": None},
                             last_ego={"label": "뉴스픽 (Profile 2)", "at": "07:47"})
        self.assertIn("- ego 게시 공간: 지금 열린 공간 없음 · 마지막 연결 뉴스픽 (Profile 2) 07:47 (설정 뉴스픽 (Profile 2))",
                      MOD.render(report).splitlines())

    def test_replaced_slot_is_labelled(self):
        report = self.report()
        report["posts"][0] = {**report["posts"][0], "replaced": True}
        self.assertIn("- 07:00 ✅ 게시 · 수동 대체 (06:30 시작 → 07:09 게시)", MOD.render(report).splitlines())

    def test_future_slot_and_missing_history(self):
        report = self.report(generated_at="2026-11-12T05:00:00+09:00", story=None,
                             growth=MOD.growth([], DAY), profile={"followers": 1194, "following": 1468, "posts": None},
                             ego={"configured": "뉴스픽 (Profile 2)", "space": "확인 안 함", "match": None},
                             warnings=["NewsPickInstagram-1200 최근 결과 코드 2"])
        report["posts"][0] = {**report["posts"][0], "status": "없음", "started_at": None, "posted_at": None}
        lines = MOD.render(report).splitlines()
        self.assertIn("- 07:00 ⏰ 예정 (06:30 준비 시작)", lines)
        self.assertIn("- 19:00 스토리 ⏰ 예정", lines)
        self.assertIn("- 팔로워 1,194 (비교 기록 없음) · 팔로잉 1,468", lines)
        self.assertIn("- ego 게시 공간: 확인 안 함 (설정 뉴스픽 (Profile 2))", lines)
        self.assertIn("- 예약 이상: NewsPickInstagram-1200 최근 결과 코드 2", lines)


class ScheduleRegistrationTests(unittest.TestCase):
    def test_daily_report_task_runs_at_1930_every_day(self):
        script = (PATH.parents[2] / "follow-suggested" / "scripts" / "manage_windows_growth_schedule.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("name = 'NewsPickDailyReport-1930'", script)
        self.assertIn("daily_report.py", script)
        self.assertIn("New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(19).AddMinutes(30))", script)


if __name__ == "__main__":
    unittest.main()
