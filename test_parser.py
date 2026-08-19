import unittest
from datetime import date

from parser import (
    RelayEvent,
    changed_pitcher_lines,
    current_player_record,
    expected_batters_message,
    format_batter_summary_stats,
    format_kia_news_articles,
    format_monthly_team_records,
    format_player_record_stats,
    format_relay_event,
    format_relay_event_with_context,
    format_team_record_stats,
    half_out_results,
    has_starting_lineups,
    kia_half_summary_message,
    kia_news_articles,
    lineup_media_items,
    parse_relay_events,
    plate_result_history,
    player_image_url,
    previous_half_out_labels,
    previous_half_pitcher_lines,
    record_options_message,
    resolve_record_option,
    should_send_relay_event,
)
from parser import format_preview


class StartingLineupTest(unittest.TestCase):
    @staticmethod
    def lineup(prefix):
        return [
            {
                "playerCode": f"{prefix}-pitcher",
                "playerName": f"{prefix} 선발",
                "batorder": None,
                "positionName": "선발투수",
            },
            *[
                {
                    "playerCode": f"{prefix}-{order}",
                    "playerName": f"{prefix} 타자 {order}",
                    "batorder": order,
                    "positionName": "타자",
                }
                for order in range(1, 10)
            ],
        ]

    def test_pitchers_only_are_not_treated_as_complete_lineups(self):
        preview = {
            "awayTeamLineUp": {"fullLineUp": [self.lineup("away")[0]]},
            "homeTeamLineUp": {"fullLineUp": [self.lineup("home")[0]]},
        }

        self.assertFalse(has_starting_lineups(preview))

    def test_both_pitchers_and_batting_orders_one_through_nine_are_complete(self):
        preview = {
            "awayTeamLineUp": {"fullLineUp": self.lineup("away")},
            "homeTeamLineUp": {"fullLineUp": self.lineup("home")},
        }

        self.assertTrue(has_starting_lineups(preview))

    def test_one_incomplete_team_keeps_lineup_pending(self):
        preview = {
            "awayTeamLineUp": {"fullLineUp": self.lineup("away")},
            "homeTeamLineUp": {"fullLineUp": self.lineup("home")[:-1]},
        }

        self.assertFalse(has_starting_lineups(preview))

    def test_lineup_photos_use_game_date_to_refresh_telegram_cache(self):
        preview = {
            "gameInfo": {"aName": "KIA", "gdate": 20260812},
            "awayTeamLineUp": {"fullLineUp": self.lineup("away")},
        }

        items = lineup_media_items(preview, "away")

        self.assertTrue(items[0][0].endswith("?type=w150&v=20260812"))
        self.assertEqual(
            player_image_url("52605", "2026-08-12"),
            "https://sports-phinf.pstatic.net/player/kbo/default/52605.png?type=w150&v=20260812",
        )
        self.assertEqual(
            player_image_url("62700", "2026-08-13"),
            "https://tigers.co.kr/files/playerImg/tigersImg2/2026_30_C_new.png?v=20260813",
        )


class RelayParsingTest(unittest.TestCase):
    def test_null_relay_payload_is_treated_as_no_events(self):
        self.assertEqual(parse_relay_events(None), [])
        self.assertEqual(parse_relay_events({"textRelays": None}), [])


class CurrentPlayerRecordTest(unittest.TestCase):
    def test_lineup_record_is_not_overwritten_by_stale_current_player_info(self):
        relay = {
            "homeLineup": {
                "batter": [
                    {
                        "pcode": "52605",
                        "name": "김도영",
                        "batOrder": 3,
                        "ab": 2,
                        "hit": 0,
                        "rbi": 0,
                        "bb": 1,
                    }
                ]
            }
        }
        event = RelayEvent(
            event_id=261,
            inning=5,
            half="말",
            text="김도영 : 볼넷",
            home_score=5,
            away_score=3,
            batter_code="52605",
            home_or_away="1",
            player_info={"batOrder": 4, "ab": 2, "hit": 1, "rbi": 3, "bb": 0},
        )

        player = current_player_record(relay, event)

        self.assertEqual(player["batOrder"], 3)
        self.assertEqual(player["hit"], 0)
        self.assertEqual(player["rbi"], 0)
        self.assertEqual(player["bb"], 1)


class FormatPreviewTest(unittest.TestCase):
    def test_away_kia_recent_and_vs_records_use_away_data(self):
        preview = {
            "gameInfo": {
                "aCode": "HT",
                "hCode": "LT",
                "aName": "KIA",
                "hName": "롯데",
                "gdate": 20260707,
                "gtime": "18:30",
                "stadium": "사직",
            },
            "awayTeamPreviousGames": [{"result": result} for result in ["승", "무", "승", "패", "패"]],
            "homeTeamPreviousGames": [{"result": result} for result in ["패", "승", "승", "패", "승"]],
            "seasonVsResult": {"aw": 6, "ad": 1, "al": 2, "hw": 2, "hd": 1, "hl": 6},
        }

        message = format_preview(preview, "20260707HTLT02026", "HT")

        self.assertIn("KIA: 승 무 승 패 패", message)
        self.assertIn("상대: 패 승 승 패 승", message)
        self.assertIn("KIA 6승 1무 2패", message)

    def test_home_kia_recent_and_vs_records_use_home_data(self):
        preview = {
            "gameInfo": {
                "aCode": "LT",
                "hCode": "HT",
                "aName": "롯데",
                "hName": "KIA",
                "gdate": 20260708,
                "gtime": "18:30",
                "stadium": "광주",
            },
            "awayTeamPreviousGames": [{"result": result} for result in ["패", "승", "승", "패", "승"]],
            "homeTeamPreviousGames": [{"result": result} for result in ["승", "무", "승", "패", "패"]],
            "seasonVsResult": {"aw": 2, "ad": 1, "al": 6, "hw": 6, "hd": 1, "hl": 2},
        }

        message = format_preview(preview, "20260708LTHT02026", "HT")

        self.assertIn("KIA: 승 무 승 패 패", message)
        self.assertIn("상대: 패 승 승 패 승", message)
        self.assertIn("KIA 6승 1무 2패", message)


class RecordStatsFormatTest(unittest.TestCase):
    def test_team_record_stats_sort_by_selected_metric(self):
        rows = [
            {"teamName": "KIA", "offenseHra": 0.26844, "offenseHit": 848},
            {"teamName": "KT", "offenseHra": 0.28132, "offenseHit": 860},
            {"teamName": "삼성", "offenseHra": 0.27713, "offenseHit": 858},
        ]

        message = format_team_record_stats(rows, "타율")

        self.assertIn("KBO 팀 기록 | 타율", message)
        self.assertLess(message.index("1. KT"), message.index("2. 삼성"))
        self.assertLess(message.index("2. 삼성"), message.index("3. KIA"))
        self.assertIn("0.281", message)

    def test_player_record_stats_recomputes_tied_ranks(self):
        rows = [
            {"playerName": "오스틴", "teamName": "LG", "hitterHr": 28},
            {"playerName": "김도영", "teamName": "KIA", "hitterHr": 27},
            {"playerName": "강백호", "teamName": "KT", "hitterHr": 23},
            {"playerName": "힐리어드", "teamName": "한화", "hitterHr": 23},
            {"playerName": "최정", "teamName": "SSG", "hitterHr": 20},
        ]

        message = format_player_record_stats(rows, "hitter", "홈런")

        self.assertIn("1. 오스틴 (LG) | 28개", message)
        self.assertIn("3. 강백호 (KT) | 23개", message)
        self.assertIn("3. 힐리어드 (한화) | 23개", message)
        self.assertIn("5. 최정 (SSG) | 20개", message)

    def test_rate_stats_exclude_unqualified_players_before_sorting(self):
        rows = [
            {"playerName": "최원준", "teamName": "KT", "hitterHra": 0.3577, "isQualified": True},
            {"playerName": "레이예스", "teamName": "롯데", "hitterHra": 0.3474, "isQualified": True},
            {"playerName": "전다민", "teamName": "두산", "hitterHra": 1.0, "isQualified": False},
        ]

        message = format_player_record_stats(rows, "hitter", "타율")

        self.assertIn("1. 최원준 (KT) | 0.358", message)
        self.assertIn("2. 레이예스 (롯데) | 0.347", message)
        self.assertNotIn("전다민", message)

    def test_pitcher_rate_stats_exclude_unqualified_players_before_sorting(self):
        rows = [
            {"playerName": "올러", "teamName": "KIA", "pitcherWhip": 1.06, "isQualified": True},
            {"playerName": "알칸타라", "teamName": "키움", "pitcherWhip": 1.08, "isQualified": True},
            {"playerName": "김한종", "teamName": "두산", "pitcherWhip": 0.0, "isQualified": False},
        ]

        message = format_player_record_stats(rows, "pitcher", "WHIP")

        self.assertIn("1. 올러 (KIA) | 1.06", message)
        self.assertIn("2. 알칸타라 (키움) | 1.08", message)
        self.assertNotIn("김한종", message)

    def test_record_option_prompt_and_resolution(self):
        self.assertIn("1. 타율", record_options_message("team"))
        self.assertEqual(resolve_record_option("team", "타율 알려줘"), "타율")
        self.assertEqual(resolve_record_option("hitter", "ops"), "OPS")


class KiaNewsFormatTest(unittest.TestCase):
    def test_kia_news_articles_filter_title_and_deduplicate(self):
        game_news = [
            {"oid": "001", "aid": "1", "title": "KIA 타선 폭발", "sourceName": "A", "sportsSection": "kbaseball"},
            {"oid": "001", "aid": "2", "title": "한화 선발 호투", "sourceName": "B", "sportsSection": "kbaseball"},
        ]
        section_news = [
            {"oid": "001", "aid": "1", "title": "KIA 타선 폭발", "sourceName": "A", "sportsSection": "kbaseball"},
            {"oid": "002", "aid": "3", "title": "기아 불펜 점검", "sourceName": "C", "sportsSection": "kbaseball"},
        ]

        articles = kia_news_articles(game_news, section_news, limit=5)
        message = format_kia_news_articles(articles)

        self.assertEqual([article["aid"] for article in articles], ["1", "3"])
        self.assertIn("KIA 주요 기사", message)
        self.assertIn("1. KIA 타선 폭발 (A)", message)
        self.assertIn("https://m.sports.naver.com/kbaseball/article/001/1", message)
        self.assertIn("2. 기아 불펜 점검 (C)", message)


class MonthlyTeamRecordTest(unittest.TestCase):
    def test_monthly_records_count_results_and_use_shared_ranks(self):
        games = [
            {"awayTeamCode": "OB", "homeTeamCode": "HT", "statusCode": "RESULT", "winner": "HOME"},
            {"awayTeamCode": "LT", "homeTeamCode": "HT", "statusCode": "RESULT", "winner": "HOME"},
            {"awayTeamCode": "HT", "homeTeamCode": "SK", "statusCode": "RESULT", "winner": "HOME"},
            {"awayTeamCode": "OB", "homeTeamCode": "SK", "statusCode": "RESULT", "winner": "HOME"},
            {"awayTeamCode": "SK", "homeTeamCode": "LT", "statusCode": "RESULT", "winner": "HOME"},
            {"awayTeamCode": "LT", "homeTeamCode": "OB", "statusCode": "RESULT", "winner": "HOME"},
            {"awayTeamCode": "LT", "homeTeamCode": "OB", "statusCode": "RESULT", "winner": "DRAW"},
            {"awayTeamCode": "SK", "homeTeamCode": "HT", "statusCode": "STARTED", "winner": "HOME"},
            {"awayTeamCode": "SK", "homeTeamCode": "HT", "statusCode": "CANCEL", "winner": "DRAW"},
        ]
        team_names = {"HT": "KIA", "SK": "SSG", "OB": "두산", "LT": "롯데"}

        message = format_monthly_team_records(games, team_names, date(2026, 8, 18))

        self.assertTrue(message.startswith("2026 KBO 8월 월간 성적\n8월 18일 종료 경기 기준"))
        self.assertIn("1. KIA | 2승 1패 0무 | 승률 0.667", message)
        self.assertIn("1. SSG | 2승 1패 0무 | 승률 0.667", message)
        self.assertIn("3. 두산 | 1승 2패 1무 | 승률 0.333", message)
        self.assertIn("3. 롯데 | 1승 2패 1무 | 승률 0.333", message)

    def test_monthly_records_reports_when_no_game_has_ended(self):
        games = [
            {"awayTeamCode": "SK", "homeTeamCode": "HT", "statusCode": "BEFORE", "winner": "DRAW"}
        ]

        message = format_monthly_team_records(games, {"HT": "KIA", "SK": "SSG"}, date(2026, 3, 1))

        self.assertIn("이번 달 종료된 KBO 경기가 없습니다.", message)


class HalfOutSummaryTest(unittest.TestCase):
    def test_out_results_follow_api_out_increases_and_include_runner_out(self):
        events = [
            RelayEvent(1, 7, "초", "박재현 : 우익수 뒤 2루타", 2, 3, batter_code="1", player_name="박재현", current_state={"out": "0"}),
            RelayEvent(2, 7, "초", "김선빈 : 유격수 땅볼 아웃", 2, 3, batter_code="2", player_name="김선빈", current_state={"out": "1"}),
            RelayEvent(3, 7, "초", "2루주자 박재현 : 태그아웃", 2, 3, batter_code="2", current_state={"out": "2"}),
            RelayEvent(4, 7, "초", "김도영 : 좌익수 뒤 홈런", 2, 4, batter_code="3", player_name="김도영", current_state={"out": "2"}),
            RelayEvent(5, 7, "초", "카스트로 : 중견수 플라이 아웃", 2, 4, batter_code="4", player_name="카스트로", current_state={"out": "3"}),
        ]

        results = half_out_results(events, 7, "초")

        self.assertEqual([result.tagged_label for result in results], ["땅볼1", "태그2", "플라이3"])
        self.assertEqual(results[0].player_code, "2")
        self.assertEqual(results[1].player_name, "박재현")

    def test_double_play_uses_both_out_numbers(self):
        events = [
            RelayEvent(1, 6, "말", "허인서 : 삼진 아웃", 2, 3, batter_code="7", current_state={"out": "1"}),
            RelayEvent(2, 6, "말", "이도윤 : 유격수 병살타 아웃", 2, 3, batter_code="8", current_state={"out": "3"}),
            RelayEvent(3, 6, "말", "1루주자 이원석 : 포스아웃", 2, 3, batter_code="8", current_state={"out": "3"}),
        ]
        attack_start = RelayEvent(4, 7, "초", "7회초 KIA 공격", 2, 3, home_or_away="0")

        labels = previous_half_out_labels([*events, attack_start], attack_start)

        self.assertEqual(labels, ["삼진1", "병살타23"])

    def test_previous_half_pitcher_lines_include_every_pitcher_with_team_label(self):
        events = [
            RelayEvent(
                0,
                7,
                "초",
                "7회초 KIA 공격",
                0,
                2,
                current_state={"pitcher": "stale", "out": "0"},
            ),
            RelayEvent(1, 7, "초", "김태군 : 볼넷", 0, 2, current_state={"pitcher": "1", "out": "0"}),
            RelayEvent(2, 7, "초", "투수 화이트 : 투수 김서현 (으)로 교체", 0, 2, current_state={"pitcher": "2", "out": "2"}),
            RelayEvent(3, 7, "초", "박정우 : 유격수 땅볼 아웃", 0, 2, current_state={"pitcher": "2", "out": "3"}),
        ]
        started_by = RelayEvent(4, 7, "말", "7회말 한화 공격", 0, 2, home_or_away="1")
        relay = {
            "homeLineup": {
                "pitcher": [
                    {
                        "pcode": "stale",
                        "name": "이민우",
                        "seqno": 0,
                        "ballCount": 8,
                        "inn": "0.1",
                        "hit": 2,
                        "run": 2,
                        "er": 2,
                        "bb": 0,
                        "hbp": 0,
                        "kk": 0,
                        "seasonEra": "4.53",
                    },
                    {
                        "pcode": "1",
                        "name": "화이트",
                        "seqno": 1,
                        "ballCount": 103,
                        "inn": "7.0",
                        "hit": 5,
                        "run": 2,
                        "er": 2,
                        "bb": 2,
                        "hbp": 0,
                        "kk": 6,
                        "seasonEra": "3.11",
                    },
                    {
                        "pcode": "2",
                        "name": "김서현",
                        "seqno": 2,
                        "ballCount": 4,
                        "inn": "0.1",
                        "hit": 0,
                        "run": 0,
                        "er": 0,
                        "bb": 0,
                        "hbp": 0,
                        "kk": 1,
                        "seasonEra": "2.45",
                    },
                ]
            }
        }

        lines = previous_half_pitcher_lines(events, relay, started_by, "home", "한")

        self.assertEqual(len(lines), 2)
        self.assertEqual(
            lines[0],
            "화이트(한) | 103개 | 7이닝 5피안타 2실점 2자책 2사사구 6삼진 ERA 3.11",
        )
        self.assertTrue(lines[1].startswith("김서현(한) | 4개 | 0 ⅓이닝"))

    def test_expected_batters_appends_previous_half_outs_to_score(self):
        event = RelayEvent(
            4,
            7,
            "초",
            "7회초 KIA 공격",
            2,
            3,
            batter_code="1",
            home_or_away="0",
        )
        relay = {
            "awayLineup": {
                "batter": [
                    {"pcode": "1", "name": "박재현", "batOrder": 1, "seasonHra": "0.284", "ab": 3, "hit": 1},
                    {"pcode": "2", "name": "김선빈", "batOrder": 2, "seasonHra": "0.272", "ab": 2, "hit": 0},
                    {"pcode": "3", "name": "김도영", "batOrder": 3, "seasonHra": "0.294", "ab": 2, "hit": 0},
                ]
            }
        }

        message = expected_batters_message(
            event,
            relay,
            "HH",
            "HT",
            "KIA",
            "한화",
            "HT",
            previous_out_labels=["삼진1", "병살타23"],
        )

        self.assertIn("KIA 3 : 2 한화 (삼진1 병살타23)", message)

    def test_kia_half_summary_appends_out_to_each_player(self):
        events = [
            RelayEvent(1, 7, "초", "박재현 : 우익수 뒤 2루타", 2, 3, batter_code="1", player_name="박재현", current_state={"out": "0"}),
            RelayEvent(2, 7, "초", "김선빈 : 유격수 땅볼 아웃", 2, 3, batter_code="2", player_name="김선빈", current_state={"out": "1"}),
            RelayEvent(3, 7, "초", "2루주자 박재현 : 태그아웃", 2, 3, batter_code="2", current_state={"out": "2"}),
            RelayEvent(4, 7, "초", "김도영 : 좌익수 뒤 홈런", 2, 4, batter_code="3", player_name="김도영", current_state={"out": "2"}),
            RelayEvent(5, 7, "초", "카스트로 : 중견수 플라이 아웃", 2, 4, batter_code="4", player_name="카스트로", current_state={"out": "3"}),
        ]
        finished_by = RelayEvent(6, 7, "말", "7회말 한화 공격", 2, 4, home_or_away="1")
        relay = {
            "awayLineup": {
                "batter": [
                    {"pcode": "1", "name": "박재현", "batOrder": 1, "seasonHra": "0.286", "ab": 4, "hit": 2, "rbi": 1},
                    {"pcode": "2", "name": "김선빈", "batOrder": 2, "seasonHra": "0.271", "ab": 3, "hit": 0, "bb": 1},
                    {"pcode": "3", "name": "김도영", "batOrder": 3, "seasonHra": "0.296", "ab": 3, "hit": 1, "hr": 1},
                    {"pcode": "4", "name": "카스트로", "batOrder": 4, "seasonHra": "0.350", "ab": 4, "hit": 2},
                ]
            }
        }

        message = kia_half_summary_message(
            events,
            relay,
            finished_by,
            "HH",
            "HT",
            "KIA",
            "한화",
            "HT",
            ["화이트(한) | 103개 | 7이닝 5피안타 2실점 2자책 2사사구 6삼진 ERA 3.11"],
        )

        self.assertIn("1 박재현 | .286 | 4타수 2안타 1타점 | 태그2", message)
        self.assertIn("2 김선빈 | .271 | 3타수 1볼넷 | 땅볼1", message)
        self.assertIn("4 카스트로 | .350 | 4타수 2안타 | 플라이3", message)
        self.assertTrue(message.endswith("\n\n화이트(한) | 103개 | 7이닝 5피안타 2실점 2자책 2사사구 6삼진 ERA 3.11"))


class CompactBatterFormatTest(unittest.TestCase):
    def test_relay_header_includes_current_out_count(self):
        event = RelayEvent(
            event_id=1,
            inning=7,
            half="말",
            text="김도영 : 좌익수 앞 1루타",
            home_score=4,
            away_score=3,
            current_state={"out": "2"},
        )

        message = format_relay_event(event, "삼성", "KIA")

        self.assertTrue(message.startswith("중계 | 7회말 (2 out)\n"))

    def test_attack_start_header_does_not_include_out_count(self):
        event = RelayEvent(
            event_id=1,
            inning=7,
            half="말",
            text="7회말 KIA 공격",
            home_score=4,
            away_score=3,
            current_state={"out": "0"},
        )

        message = format_relay_event(event, "삼성", "KIA")

        self.assertTrue(message.startswith("중계 | 7회말\n"))
        self.assertNotIn("out)", message)

    def test_relay_batter_snapshot_uses_short_result_format(self):
        event = RelayEvent(
            event_id=1,
            inning=1,
            half="초",
            text="나성범 : 좌익수 앞 1루타",
            home_score=0,
            away_score=0,
            player_name="나성범",
        )
        message = format_relay_event(
            event,
            "KIA",
            "롯데",
            {
                "name": "나성범",
                "batOrder": 4,
                "seasonHra": "0.296",
                "ab": 1,
                "hit": 1,
                "rbi": 1,
            },
        )

        self.assertIn("4 나성범 | .296 | 1-1 | 안타(타점1)", message)

    def test_relay_batter_snapshot_omits_empty_result(self):
        event = RelayEvent(
            event_id=1,
            inning=1,
            half="초",
            text="김호령 : 타석 준비",
            home_score=5,
            away_score=1,
            player_name="김호령",
        )
        message = format_relay_event(
            event,
            "KIA",
            "롯데",
            {
                "name": "김호령",
                "batOrder": 9,
                "seasonHra": "0.281",
                "ab": 0,
                "hit": 0,
            },
        )

        self.assertIn("9 김호령 | .281 | 0-0", message)
        self.assertNotIn(" | 타석 준비", message)

    def test_relay_batter_snapshot_uses_full_plate_history(self):
        events = [
            RelayEvent(
                event_id=1,
                inning=2,
                half="초",
                text="김선빈 : 삼진 아웃",
                home_score=0,
                away_score=0,
                batter_code="6",
                home_or_away="0",
                player_name="김선빈",
            ),
            RelayEvent(
                event_id=2,
                inning=5,
                half="초",
                text="김선빈 : 유격수 땅볼 아웃",
                home_score=3,
                away_score=1,
                batter_code="6",
                home_or_away="0",
                player_name="김선빈",
            ),
            RelayEvent(
                event_id=3,
                inning=8,
                half="초",
                text="김선빈 : 우익수 오른쪽 1루타",
                home_score=5,
                away_score=5,
                batter_code="6",
                home_or_away="0",
                player_name="김선빈",
            ),
        ]
        player = {"name": "김선빈", "batOrder": 6, "seasonHra": "0.251", "ab": 3, "hit": 1, "rbi": 1}

        history = plate_result_history(events, events[-1], player)
        message = format_relay_event_with_context(events[-1], "KIA", "SSG", player_record=player, plate_results=history)

        self.assertEqual(history, ["삼진", "땅볼", "안타(타점1)"])
        self.assertIn("6 김선빈 | .251 | 1-3 | 삼진 땅볼 안타(타점1)", message)

    def test_score_runner_event_omits_repeated_batter_snapshot(self):
        previous = RelayEvent(
            event_id=1,
            inning=8,
            half="초",
            text="김호령 : 중견수 앞 1루타",
            home_score=5,
            away_score=5,
            batter_code="1",
            home_or_away="0",
            player_name="김호령",
        )
        score = RelayEvent(
            event_id=2,
            inning=8,
            half="초",
            text="2루주자 김규성 : 홈인",
            home_score=5,
            away_score=6,
            batter_code="1",
            home_or_away="0",
        )
        player = {"name": "김호령", "batOrder": 1, "seasonHra": "0.283", "ab": 4, "hit": 1, "rbi": 2}

        message = format_relay_event_with_context(score, "KIA", "SSG", previous, player)

        self.assertIn("김호령 : 중견수 앞 1루타", message)
        self.assertNotIn("1 김호령 | .283 | 1-4", message)

    def test_score_homer_event_keeps_batter_snapshot(self):
        previous = RelayEvent(
            event_id=0,
            inning=8,
            half="초",
            text="김호령 : 중견수 앞 1루타",
            home_score=5,
            away_score=7,
            batter_code="1",
            home_or_away="0",
            player_name="김호령",
        )
        events = [
            RelayEvent(
                event_id=1,
                inning=1,
                half="초",
                text="카스트로 : 삼진 아웃",
                home_score=0,
                away_score=0,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
            RelayEvent(
                event_id=2,
                inning=3,
                half="초",
                text="카스트로 : 우익수 앞 1루타",
                home_score=0,
                away_score=1,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
            RelayEvent(
                event_id=3,
                inning=5,
                half="초",
                text="카스트로 : 2루수 땅볼 아웃",
                home_score=3,
                away_score=2,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
            RelayEvent(
                event_id=4,
                inning=7,
                half="초",
                text="카스트로 : 좌익수 앞 1루타",
                home_score=5,
                away_score=5,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
            RelayEvent(
                event_id=5,
                inning=8,
                half="초",
                text="카스트로 : 우익수 뒤 홈런 (홈런거리:125M)",
                home_score=5,
                away_score=8,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
        ]
        event = events[-1]
        player = {"name": "카스트로", "batOrder": 2, "seasonHra": "0.324", "ab": 5, "hit": 3, "rbi": 2}
        history = plate_result_history(events, event, player)

        message = format_relay_event_with_context(event, "KIA", "SSG", previous, player, history)

        self.assertIn("득점 | 8회초", message)
        self.assertIn("2 카스트로 | .324 | 3-5 | 삼진 안타 땅볼 안타 홈런(타점2)", message)
        self.assertNotIn("김호령 : 중견수 앞 1루타", message)

    def test_runner_steal_and_video_review_do_not_use_current_batter_stats(self):
        steal = RelayEvent(
            event_id=1,
            inning=8,
            half="초",
            text="1루주자 김호령 : 도루로 2루까지 진루",
            home_score=5,
            away_score=7,
            batter_code="2",
            home_or_away="0",
        )
        video = RelayEvent(
            event_id=2,
            inning=8,
            half="초",
            text="8회초 2번타순 2구 후 SSG요청 비디오 판독: 김호령 2루 도루 관련 세이프→세이프",
            home_score=5,
            away_score=7,
            batter_code="2",
            home_or_away="0",
        )
        player = {"name": "카스트로", "batOrder": 2, "seasonHra": "0.320", "ab": 4, "hit": 2, "sb": 1}

        self.assertTrue(should_send_relay_event(steal, "SK", "HT", "HT"))
        self.assertNotIn("카스트로", format_relay_event_with_context(steal, "KIA", "SSG", player_record=player))
        self.assertNotIn("카스트로", format_relay_event_with_context(video, "KIA", "SSG", player_record=player))

    def test_half_summary_omits_zero_stats(self):
        self.assertEqual(
            format_batter_summary_stats(
                {
                    "name": "박재현",
                    "batOrder": 1,
                    "seasonHra": "0.284",
                    "ab": 0,
                    "run": 1,
                    "hit": 0,
                    "rbi": 0,
                    "hr": 0,
                    "bb": 1,
                    "so": 0,
                    "sb": 0,
                }
            ),
            "1 박재현 | .284 | 1득점 1볼넷",
        )

    def test_expected_batters_use_short_snapshot_without_plate_result(self):
        event = RelayEvent(
            event_id=1,
            inning=2,
            half="초",
            text="2회초 KIA 공격",
            home_score=4,
            away_score=1,
            batter_code="6",
            home_or_away="0",
        )
        relay = {
            "awayLineup": {
                "batter": [
                    {"pcode": "6", "name": "박상준", "batOrder": 6, "seasonHra": "0.303", "ab": 0, "hit": 0},
                    {"pcode": "7", "name": "김선빈", "batOrder": 7, "seasonHra": "0.248", "ab": 0, "hit": 0},
                    {"pcode": "8", "name": "김규성", "batOrder": 8, "seasonHra": "0.245", "ab": 0, "hit": 0},
                ]
            }
        }

        message = expected_batters_message(event, relay, "LT", "HT", "KIA", "롯데", "HT")

        self.assertIn("6 박상준 | .303 | 0-0", message)
        self.assertIn("7 김선빈 | .248 | 0-0", message)
        self.assertIn("8 김규성 | .245 | 0-0", message)

    def test_expected_batters_can_include_previous_kia_pitcher_stats(self):
        event = RelayEvent(
            event_id=1,
            inning=3,
            half="초",
            text="3회초 KIA 공격",
            home_score=1,
            away_score=0,
            batter_code="9",
            home_or_away="0",
        )
        relay = {
            "awayLineup": {
                "batter": [
                    {"pcode": "9", "name": "김규성", "batOrder": 9, "seasonHra": "0.245", "ab": 0, "hit": 0},
                    {"pcode": "1", "name": "박재현", "batOrder": 1, "seasonHra": "0.280", "ab": 1, "hit": 0},
                    {"pcode": "2", "name": "김호령", "batOrder": 2, "seasonHra": "0.283", "ab": 1, "hit": 1},
                ],
                "pitcher": [
                    {
                        "pcode": "50054",
                        "name": "성영탁",
                        "seqno": 2,
                        "ballCount": 22,
                        "inn": "0.2",
                        "hit": 4,
                        "run": 4,
                        "er": 3,
                        "bb": 1,
                        "hbp": 0,
                        "kk": 2,
                        "seasonEra": "4.11",
                    }
                ],
            }
        }
        previous = {
            "50054": {
                "name": "성영탁",
                "seqno": 2,
                "ballCount": 0,
                "inn": "0",
                "hit": 0,
                "run": 0,
                "er": 0,
                "bb": 0,
                "hbp": 0,
                "kk": 0,
                "seasonEra": "4.11",
            }
        }

        pitcher_lines, snapshot = changed_pitcher_lines(relay, "away", previous)
        message = expected_batters_message(event, relay, "LT", "HT", "KIA", "롯데", "HT", pitcher_lines)

        self.assertEqual(
            pitcher_lines,
            ["성영탁 | 22개 | 0 ⅔이닝 4피안타 4실점 3자책 1사사구 2삼진 ERA 4.11"],
        )
        self.assertEqual(snapshot["50054"]["ballCount"], 22)
        self.assertIn("9 김규성 | .245 | 0-0", message)
        self.assertIn("\n\n성영탁 | 22개 | 0 ⅔이닝", message)

    def test_first_kia_attack_includes_pitcher_stats_after_defense(self):
        relay = {
            "awayLineup": {
                "pitcher": [
                    {
                        "pcode": "50054",
                        "name": "성영탁",
                        "seqno": 2,
                        "ballCount": 22,
                        "inn": "0.2",
                        "hit": 4,
                        "run": 4,
                        "er": 3,
                        "bb": 1,
                        "hbp": 0,
                        "kk": 2,
                        "seasonEra": "4.11",
                    }
                ]
            }
        }

        pitcher_lines, snapshot = changed_pitcher_lines(relay, "away", None)

        self.assertEqual(
            pitcher_lines,
            ["성영탁 | 22개 | 0 ⅔이닝 4피안타 4실점 3자책 1사사구 2삼진 ERA 4.11"],
        )
        self.assertEqual(snapshot["50054"]["inn"], "0.2")

    def test_first_kia_attack_omits_pitcher_before_any_pitch(self):
        relay = {
            "awayLineup": {
                "pitcher": [
                    {
                        "pcode": "50054",
                        "name": "성영탁",
                        "seqno": 1,
                        "ballCount": 0,
                        "inn": "0.0",
                        "hit": 0,
                        "run": 0,
                        "er": 0,
                        "bb": 0,
                        "hbp": 0,
                        "kk": 0,
                        "seasonEra": "4.11",
                    }
                ]
            }
        }

        pitcher_lines, snapshot = changed_pitcher_lines(relay, "away", None)

        self.assertEqual(pitcher_lines, [])
        self.assertIn("50054", snapshot)

    def test_first_snapshot_only_displays_current_pitcher(self):
        relay = {
            "homeLineup": {
                "pitcher": [
                    {
                        "pcode": "starter",
                        "name": "선발",
                        "seqno": 1,
                        "ballCount": 80,
                        "inn": "5.0",
                        "seasonEra": "3.00",
                    },
                    {
                        "pcode": "reliever",
                        "name": "불펜",
                        "seqno": 2,
                        "ballCount": 12,
                        "inn": "1.0",
                        "seasonEra": "2.00",
                    },
                ]
            }
        }

        pitcher_lines, _ = changed_pitcher_lines(relay, "home", None)

        self.assertEqual(len(pitcher_lines), 1)
        self.assertTrue(pitcher_lines[0].startswith("불펜 | 12개 |"))

    def test_video_review_is_sent_for_any_team(self):
        event = RelayEvent(
            event_id=1,
            inning=4,
            half="말",
            text="비디오 판독 : 세이프 여부",
            home_score=1,
            away_score=1,
            home_or_away="1",
        )

        self.assertTrue(should_send_relay_event(event, "LT", "HT", "HT"))


if __name__ == "__main__":
    unittest.main()
