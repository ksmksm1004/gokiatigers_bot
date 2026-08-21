import unittest
from datetime import date
from unittest.mock import Mock

from kbo_api import (
    KBOGameResult,
    KBOPlayerClient,
    KBOPlayerRecord,
    format_head_to_head_results,
    format_player_record,
    parse_schedule_results,
    parse_pitcher_season_hbp,
    parse_player_basic_page,
    parse_player_candidates,
)


HITTER_HTML = """
<div class="player_info">
  <h4 id="h4Team"><span class="emb"><img src="emblem.png"></span>KIA 타이거즈</h4>
  <div class="player_basic">
    <div class="photo"><img id="ctl_playerProfile_imgProgile" src="//images.example/52605.jpg"></div>
    <ul>
      <li><span id="ctl_playerProfile_lblName">김도영</span></li>
      <li><span id="ctl_playerProfile_lblBackNo">5</span></li>
      <li><span id="ctl_playerProfile_lblBirthday">2003년 10월 02일</span></li>
      <li><span id="ctl_playerProfile_lblPosition">내야수(우투우타)</span></li>
      <li><span id="ctl_playerProfile_lblHeightWeight">183cm/85kg</span></li>
      <li><span id="ctl_playerProfile_lblSalary">25000만원</span></li>
    </ul>
  </div>
</div>
<h6>2026 성적</h6>
<table>
  <thead><tr><th>팀명</th><th>AVG</th><th>AB</th><th>R</th><th>H</th><th>2B</th><th>3B</th><th>HR</th><th>RBI</th><th>SB</th></tr></thead>
  <tbody><tr><td>KIA</td><td>0.298</td><td>400</td><td>89</td><td>119</td><td>21</td><td>1</td><td>37</td><td>93</td><td>8</td></tr></tbody>
</table>
<table>
  <thead><tr><th>BB</th><th>IBB</th><th>HBP</th><th>SO</th><th>SLG</th><th>OBP</th><th>OPS</th></tr></thead>
  <tbody><tr><td>62</td><td>7</td><td>5</td><td>81</td><td>0.633</td><td>0.395</td><td>1.028</td></tr></tbody>
</table>
"""


PITCHER_HTML = """
<div class="player_info">
  <h4 id="h4Team">KIA 타이거즈</h4>
  <div class="photo"><img id="ctl_playerProfile_imgProgile" src="//images.example/77637.jpg"></div>
  <span id="ctl_playerProfile_lblName">양현종</span>
  <span id="ctl_playerProfile_lblBackNo">54</span>
  <span id="ctl_playerProfile_lblBirthday">1988년 03월 01일</span>
  <span id="ctl_playerProfile_lblPosition">투수(좌투좌타)</span>
  <span id="ctl_playerProfile_lblHeightWeight">183cm/91kg</span>
  <span id="ctl_playerProfile_lblSalary">80000만원</span>
</div>
<h6>2026 성적</h6>
<table>
  <thead><tr><th>팀명</th><th>ERA</th><th>W</th><th>L</th><th>SV</th><th>HLD</th><th>IP</th><th>H</th><th>HR</th></tr></thead>
  <tbody><tr><td>KIA</td><td>4.33</td><td>8</td><td>6</td><td>0</td><td>0</td><td>95 2/3</td><td>91</td><td>12</td></tr></tbody>
</table>
<table>
  <thead><tr><th>BB</th><th>SO</th><th>R</th><th>ER</th><th>WHIP</th></tr></thead>
  <tbody><tr><td>50</td><td>63</td><td>52</td><td>46</td><td>1.47</td></tr></tbody>
</table>
"""


PITCHER_TOTAL_HTML = """
<table>
  <thead><tr><th>연도</th><th>팀명</th><th>ERA</th><th>BB</th><th>HBP</th><th>SO</th></tr></thead>
  <tbody>
    <tr><td>2025</td><td>KIA</td><td>5.06</td><td>57</td><td>4</td><td>109</td></tr>
    <tr><td>2026</td><td>KIA</td><td>4.33</td><td>50</td><td>2</td><td>63</td></tr>
  </tbody>
</table>
"""


def schedule_row(game_date, play_html, completed=True):
    review = (
        f"<a href='/Schedule/GameCenter/Main.aspx?gameDate={game_date}"
        f"&gameId={game_date}WOHT0&section=REVIEW'>리뷰</a>"
        if completed
        else ""
    )
    return {
        "row": [
            {"Text": f"{game_date[4:6]}.{game_date[6:]}(화)", "Class": "day"},
            {"Text": "<b>18:30</b>", "Class": "time"},
            {"Text": play_html, "Class": "play"},
            {"Text": review, "Class": "relay"},
        ]
    }


class KBOPlayerSearchTest(unittest.TestCase):
    def test_filters_exact_active_player_name_and_requested_record_type(self):
        payload = {
            "code": "100",
            "now": [
                {
                    "P_ID": 77637,
                    "P_NM": "양현종",
                    "BACK_NO": "54",
                    "POS_NO": "투수",
                    "T_NM": "KIA",
                    "P_TYPE": "좌투좌타",
                    "P_LINK": "/Record/Player/PitcherDetail/Basic.aspx?playerId=77637",
                },
                {
                    "P_ID": 55370,
                    "P_NM": "양현종",
                    "BACK_NO": "60",
                    "POS_NO": "내야수",
                    "T_NM": "키움",
                    "P_TYPE": "우투우타",
                    "P_LINK": "/Record/Player/HitterDetail/Basic.aspx?playerId=55370",
                },
                {
                    "P_ID": 99999,
                    "P_NM": "양현종대",
                    "P_LINK": "/Record/Player/PitcherDetail/Basic.aspx?playerId=99999",
                },
            ],
            "retire": [
                {
                    "P_ID": 10000,
                    "P_NM": "양현종",
                    "P_LINK": "/Record/Retire/Pitcher.aspx?playerId=10000",
                }
            ],
        }

        pitchers = parse_player_candidates(payload, "양현종", "pitcher")
        hitters = parse_player_candidates(payload, "양현종", "hitter")

        self.assertEqual([player.player_id for player in pitchers], ["77637"])
        self.assertEqual([player.player_id for player in hitters], ["55370"])


class KBOPlayerPageTest(unittest.TestCase):
    def test_parses_and_formats_hitter_basic_record(self):
        malformed_comment = "<!\u2014[if lt IE 9]><script src='legacy.js'></script><![endif]\u2014>"
        record = parse_player_basic_page(malformed_comment + HITTER_HTML, "52605", "hitter")
        message = format_player_record(record)

        self.assertEqual(record.photo_url, "https://images.example/52605.jpg")
        self.assertEqual(record.stats["AVG"], "0.298")
        self.assertIn("김도영 (KIA)", message)
        self.assertIn("생년월일: 2003년 10월 02일", message)
        self.assertIn("타율 .298 | 타수 400 | 안타 119", message)
        self.assertIn("사사구 67 | 삼진 81", message)
        self.assertIn("출루율 .395 | 장타율 .633 | OPS 1.028", message)

    def test_parses_pitcher_record_and_supplements_hit_batters(self):
        record = parse_player_basic_page(PITCHER_HTML, "77637", "pitcher")
        hbp = parse_pitcher_season_hbp(PITCHER_TOTAL_HTML, record.season)
        record.stats["HBP"] = str(hbp)
        message = format_player_record(record)

        self.assertEqual(hbp, 2)
        self.assertIn("양현종 (KIA)", message)
        self.assertIn("평균자책 4.33 | 이닝 95 2/3", message)
        self.assertIn("승 8 | 패 6 | 세이브 0 | 홀드 0", message)
        self.assertIn("사사구 52 | 실점 52 | 자책점 46", message)
        self.assertIn("WHIP 1.47", message)

    def test_formats_profile_when_current_season_record_is_empty(self):
        record = KBOPlayerRecord(
            player_id="12345",
            record_type="hitter",
            season="2026",
            name="신인선수",
            position="내야수",
        )

        message = format_player_record(record)

        self.assertIn("신인선수", message)
        self.assertTrue(message.endswith("정규시즌 기록이 없습니다."))


class KBOScheduleResultTest(unittest.TestCase):
    def test_parses_only_completed_review_rows(self):
        payload = {
            "rows": [
                schedule_row(
                    "20260414",
                    '<span>키움</span><em><span class="lose">2</span><span>vs</span>'
                    '<span class="win">6</span></em><span>KIA</span>',
                ),
                schedule_row(
                    "20260724",
                    '<span>키움</span><em><span class="win">8</span><span>vs</span>'
                    '<span class="lose">5</span></em><span>KIA</span>',
                ),
                schedule_row(
                    "20260821",
                    '<span>KIA</span><em><span class="same">0</span><span>vs</span>'
                    '<span class="same">0</span></em><span>키움</span>',
                    completed=False,
                ),
            ]
        }

        games = parse_schedule_results(payload, 2026)

        self.assertEqual(len(games), 2)
        self.assertEqual(games[0].game_date, date(2026, 4, 14))
        self.assertEqual(games[0].away_team, "키움")
        self.assertEqual((games[0].away_score, games[0].home_score), (2, 6))

    def test_client_requests_the_whole_regular_season_once(self):
        response = Mock()
        response.json.return_value = {"rows": []}
        client = KBOPlayerClient()
        client._request = Mock(return_value=response)

        self.assertEqual(client.team_schedule_results(2026, "HT"), [])
        self.assertEqual(client._request.call_count, 1)
        self.assertEqual(
            client._request.call_args.kwargs["data"],
            {
                "leId": 1,
                "srIdList": "0,9,6",
                "seasonId": 2026,
                "gameMonth": "",
                "teamId": "HT",
            },
        )

    def test_formats_scores_in_away_home_order_and_results_from_kia_view(self):
        games = [
            KBOGameResult(date(2026, 4, 14), "키움", 2, 6, "KIA"),
            KBOGameResult(date(2026, 6, 1), "KIA", 3, 3, "키움"),
            KBOGameResult(date(2026, 7, 24), "키움", 8, 5, "KIA"),
            KBOGameResult(date(2026, 8, 1), "KIA", 4, 1, "한화"),
        ]

        self.assertEqual(
            format_head_to_head_results(games, "키움"),
            "\n".join(
                [
                    "KIA vs 키움 상대 전적",
                    "",
                    "KIA 1승 1무 1패",
                    "4/14 2:6 승",
                    "6/1 3:3 무",
                    "7/24 8:5 패",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
