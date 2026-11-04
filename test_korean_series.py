import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from config import Settings
from korean_series import is_korean_series_game, is_score_only_series_game, poll_korean_series


class KoreanSeriesTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings('', 'a', telegram_chat_ids=('b',))
        self.now = datetime(2026, 11, 4, 20, tzinfo=self.settings.timezone)
        self.gid = '77771104SSKT02026'
        self.state = {'seasonWatch': {'mode': 'offseason'}}
        self.game = {'gameId': self.gid, 'roundCode': 'kbo_ps_ks', 'seriesGameNo': 2,
                     'statusCode': 'STARTED', 'gameDateTime': '2026-11-04T18:30:00',
                     'homeTeamName': 'KT', 'awayTeamName': '삼성',
                     'homeTeamScore': 1, 'awayTeamScore': 2, 'currentInning': '7회초'}
        self.client = Mock()
        self.client.games_on.return_value = [{'gameId': self.gid}]
        self.client.game_detail.side_effect = lambda gid: {'result': {'game': dict(self.game)}}
        self.client.game_news.return_value = {'result': {'newsList': []}}
        self.telegram = Mock()
        self.chats = {c: Mock() for c in self.settings.all_telegram_chat_ids}
        self.telegram.for_chat.side_effect = self.chats.__getitem__
        self.persist = Mock()

    def poll(self, seconds=0):
        poll_korean_series(self.client, self.telegram, self.settings, self.state,
                          self.now + timedelta(seconds=seconds), self.persist)

    def messages(self, chat='a'):
        return [c.args[0] for c in self.chats[chat].send_message.call_args_list]

    def test_detection_does_not_include_playoffs(self):
        self.assertTrue(is_korean_series_game({'gameId': self.gid}))
        self.assertTrue(is_korean_series_game({'roundCode': 'kbo_ps_ks'}))
        self.assertFalse(is_korean_series_game({'gameId': '55551101HTSS02026', 'roundCode': 'kbo_ps_po'}))

    def test_score_only_routing_excludes_kia_by_code_or_encoded_id(self):
        self.assertTrue(is_score_only_series_game({'gameId': self.gid}))
        for game in (
            {'gameId': '77771104HTLG02026'},
            {'gameId': '77771104LGHT02026'},
            {'roundCode': 'kbo_ps_ks', 'awayTeamCode': 'HT', 'homeTeamCode': 'LG'},
            {'gameFlag': '7', 'hCode': 'HT', 'aCode': 'LG'},
        ):
            self.assertFalse(is_score_only_series_game(game))

    def test_kia_is_not_discovered_by_score_only_monitor(self):
        self.client.games_on.return_value = [{'gameId': '77771104HTLG02026'}]
        self.poll()
        self.client.game_detail.assert_not_called()
        self.assertEqual(self.state['koreanSeriesWatch']['games'], {})
        self.assertEqual(self.messages(), [])

    def test_old_kia_pending_score_alerts_are_removed_before_sending(self):
        gid = '77771104HTLG02026'
        self.state['koreanSeriesWatch'] = {'games': {gid: {
            'gameId': gid, 'events': {'result': {'message': 'old compact result', 'deliveredChats': []}},
        }}}
        self.poll()
        self.assertNotIn(gid, self.state['koreanSeriesWatch']['games'])
        self.assertEqual(self.messages(), [])

    def test_live_baseline_and_scoreless_play_are_silent_in_offseason(self):
        self.poll()
        self.poll(5)
        self.game['currentInning'] = '7회말'
        self.poll(10)
        self.assertEqual(self.messages(), [])
        self.assertEqual(self.state['seasonWatch']['mode'], 'offseason')
        self.assertEqual(self.state['koreanSeriesWatch']['games'][self.gid]['score'], [2, 1])

    def test_only_score_increase_sends_and_restart_does_not_repeat(self):
        self.poll()
        self.game['awayTeamScore'] = 3
        self.poll(5)
        self.state = json.loads(json.dumps(self.state))
        self.poll(10)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn('한국시리즈 2차전 득점', self.messages()[0])
        self.assertIn('삼성 3 : 1 KT', self.messages()[0])
        self.assertEqual(self.messages('a'), self.messages('b'))

    def test_score_correction_is_not_announced_as_scoring(self):
        self.poll()
        self.game['awayTeamScore'] = 1
        self.poll(5)
        self.assertEqual(self.messages(), [])

    def test_final_result_once_and_three_game_articles_after_ten_minutes(self):
        self.poll()
        self.game.update(statusCode='RESULT', awayTeamScore=3,
                         latestSeriesOutcome={'away': 1, 'home': 1})
        self.poll(5)
        self.assertEqual(len(self.messages()), 2)
        self.assertIn('경기 종료', self.messages()[1])
        self.assertIn('삼성 승리', self.messages()[1])
        self.assertIn('시리즈 전적', self.messages()[1])
        self.client.game_news.return_value = {'result': {'newsList': [
            {'oid': '109', 'aid': str(i), 'title': f'삼성 KT 한국시리즈 결과 기사 {i}',
             'dateTime': '2026-11-04T20:05:00'} for i in range(5)
        ]}}
        self.poll(604)
        self.client.game_news.assert_not_called()
        self.poll(605)
        self.assertEqual(len(self.messages()), 3)
        self.assertEqual(self.messages()[-1].count('https://'), 3)
        calls = self.client.game_detail.call_count
        self.state = json.loads(json.dumps(self.state))
        self.poll(1205)
        self.assertEqual(len(self.messages()), 3)
        self.assertEqual(self.client.game_detail.call_count, calls)

    def test_already_ended_game_sends_result_without_old_scoring_messages(self):
        self.game['statusCode'] = 'RESULT'
        self.poll()
        self.assertEqual(len(self.messages()), 1)
        self.assertIn('경기 종료', self.messages()[0])
        self.assertNotIn('득점', self.messages()[0])

    def test_failed_chat_retries_without_duplicating_successful_chat(self):
        self.poll()
        self.chats['b'].send_message.side_effect = RuntimeError('network')
        self.game['homeTeamScore'] = 2
        with self.assertLogs(level='ERROR'):
            self.poll(5)
        self.state = json.loads(json.dumps(self.state))
        self.chats['b'].send_message.side_effect = None
        self.poll(10)
        self.assertEqual(len(self.messages('a')), 1)
        self.assertEqual(len(self.messages('b')), 2)

    def test_night_scoring_and_result_are_not_suppressed_by_stove_news_hours(self):
        self.now = self.now.replace(hour=23)
        self.poll()
        self.game.update(statusCode='RESULT', homeTeamScore=3)
        self.poll(5)
        self.assertEqual(len(self.messages()), 2)

    def test_unavailable_scores_do_not_create_false_zero_score(self):
        self.poll()
        self.game['homeTeamScore'] = None
        self.poll(5)
        self.assertEqual(self.state['koreanSeriesWatch']['games'][self.gid]['score'], [2, 1])
        self.assertEqual(self.messages(), [])

    def test_schedule_discovery_is_not_done_every_live_poll(self):
        self.poll()
        self.poll(5)
        self.client.games_on.assert_called_once()
        self.assertEqual(self.client.game_detail.call_count, 2)

    def test_no_winter_schedule_queries_when_there_are_no_tracked_games(self):
        self.now = datetime(2027, 1, 4, 12, tzinfo=self.settings.timezone)
        self.poll()
        self.client.games_on.assert_not_called()
        self.client.game_detail.assert_not_called()

    def test_series_win_stops_further_schedule_discovery(self):
        self.game.update(statusCode='RESULT', latestSeriesOutcome={'away': 4, 'home': 2})
        self.poll()
        self.poll(86400)
        self.assertEqual(self.state['koreanSeriesWatch']['completedSeason'], 2026)
        self.client.games_on.assert_called_once()

    def test_no_news_does_not_retry_forever(self):
        self.game['statusCode'] = 'RESULT'
        self.poll()
        for seconds in (600, 1200, 1800, 2400):
            self.poll(seconds)
        self.assertEqual(self.client.game_news.call_count, 3)
        self.assertTrue(self.state['koreanSeriesWatch']['games'][self.gid]['newsDone'])


if __name__ == '__main__':
    unittest.main()
