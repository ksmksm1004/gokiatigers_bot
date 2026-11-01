import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from config import Settings
from season_watch import start_offseason, automatic_games_paused, wait_for_new_season
from bot import main, send_next_kia_game_once


class SeasonWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings('', '', state_path=Path(self.tmp.name) / 'state.json')
        self.state = {'stoveNews': {'seen': {'109/1': 'saved'}},
                      'nextGamePendingDate': '2026-11-01', 'nextGameScheduleCheckAt': 'old'}
        self.persist = Mock()
        self.client = Mock()
        self.client.games_in_month.return_value = []
        start_offseason(self.state, 2026, self.settings.timezone, self.persist)

    def now(self, year, month, day, hour=9):
        return datetime(year, month, day, hour, tzinfo=self.settings.timezone)

    def check(self, now):
        return wait_for_new_season(self.client, self.settings, self.state, now, self.persist)

    def game(self, day, status='READY'):
        return {'gameId': '20270312SKHT02027', 'homeTeamCode': 'HT', 'awayTeamCode': 'SK',
                'gameDate': day, 'statusCode': status}

    def test_activation_clears_retry_and_preserves_roster_news(self):
        self.assertTrue(automatic_games_paused(self.state))
        self.assertNotIn('nextGamePendingDate', self.state)
        self.assertNotIn('nextGameScheduleCheckAt', self.state)
        self.assertEqual(self.state['stoveNews']['seen'], {'109/1': 'saved'})
        self.assertEqual(self.state['seasonWatch']['nextScheduleCheckAt'], '2027-03-01T09:00:00+09:00')

    def test_no_automatic_game_api_calls_until_march(self):
        for now in (self.now(2026, 11, 1), self.now(2027, 2, 28), self.now(2027, 3, 1, 8)):
            self.assertTrue(self.check(now))
        self.client.games_in_month.assert_not_called()

    def test_march_schedule_lookup_only_once_a_week(self):
        march1 = self.now(2027, 3, 1)
        self.assertTrue(self.check(march1))
        self.assertEqual(self.client.games_in_month.call_count, 2)  # March and April in one weekly check.
        self.assertTrue(self.check(march1 + timedelta(days=6)))
        self.assertEqual(self.client.games_in_month.call_count, 2)
        self.assertTrue(self.check(march1 + timedelta(days=7)))
        self.assertEqual(self.client.games_in_month.call_count, 4)

    def test_discovered_exhibition_waits_until_game_day_then_resumes(self):
        self.client.games_in_month.side_effect = [[self.game('2027-03-12')], []]
        self.assertTrue(self.check(self.now(2027, 3, 8)))
        self.assertEqual(self.state['seasonWatch']['firstGameDate'], '2027-03-12')
        self.assertTrue(self.check(self.now(2027, 3, 11)))
        self.assertEqual(self.client.games_in_month.call_count, 2)
        self.state.update(scheduledGame={'gameId': 'old'}, scheduleDate='2026-11-01')
        self.assertFalse(self.check(self.now(2027, 3, 12, 0)))
        self.assertFalse(automatic_games_paused(self.state))
        self.assertNotIn('scheduledGame', self.state)
        self.assertNotIn('scheduleDate', self.state)
        self.assertEqual(self.state['stoveNews']['seen'], {'109/1': 'saved'})

    def test_game_today_resumes_immediately(self):
        self.client.games_in_month.side_effect = [[self.game('2027-03-01')], []]
        self.assertFalse(self.check(self.now(2027, 3, 1)))

    def test_regular_season_opener_is_detected_if_no_exhibition(self):
        self.client.games_in_month.side_effect = [[], [self.game('2027-04-02')]]
        self.assertTrue(self.check(self.now(2027, 3, 1)))
        self.assertEqual(self.state['seasonWatch']['firstGameDate'], '2027-04-02')

    def test_past_cancelled_and_other_team_games_are_ignored(self):
        self.client.games_in_month.side_effect = [[
            self.game('2027-02-28'), self.game('2027-03-02', 'CANCELLED'),
            dict(self.game('2027-03-03'), homeTeamCode='SS'),
        ], []]
        self.assertTrue(self.check(self.now(2027, 3, 1)))
        self.assertNotIn('firstGameDate', self.state['seasonWatch'])

    def test_failed_lookup_remains_paused_and_does_not_retry_daily(self):
        self.client.games_in_month.side_effect = RuntimeError('API down')
        with self.assertLogs(level='ERROR'):
            self.assertTrue(self.check(self.now(2027, 3, 1)))
        self.assertTrue(self.check(self.now(2027, 3, 2)))
        self.assertEqual(self.client.games_in_month.call_count, 1)

    def test_missing_schedule_notification_is_suppressed(self):
        telegram = Mock()
        send_next_kia_game_once(self.client, telegram, self.settings, self.state, self.now(2026, 11, 1).date())
        telegram.send_message.assert_not_called()
        self.client.games_in_month.assert_not_called()

    def test_main_keeps_roster_news_polling_but_skips_games(self):
        with ExitStack() as stack:
            stack.enter_context(patch('bot.get_settings', return_value=self.settings))
            stack.enter_context(patch('bot.load_state', return_value=self.state))
            clock = stack.enter_context(patch('bot.datetime'))
            clock.now.return_value = self.now(2026, 11, 1)
            for name in ('setup_logging', 'NaverSportsClient', 'KBOPlayerClient', 'NaverWeatherClient',
                         'TelegramBot', 'handle_telegram_commands', 'send_due_kia_news',
                         'send_due_next_kia_game', 'send_due_kia_highlight', 'send_due_kia_shorts',
                         'process_due_asian_games_baseball_relay'):
                stack.enter_context(patch('bot.' + name))
            roster = stack.enter_context(patch('bot.send_due_kia_roster_news'))
            games = stack.enter_context(patch('bot.get_cached_today_game'))
            stack.enter_context(patch('bot.sleep_with_command_polling', side_effect=KeyboardInterrupt))
            with self.assertRaises(KeyboardInterrupt):
                main()
            roster.assert_called_once()
            games.assert_not_called()


if __name__ == '__main__':
    unittest.main()
