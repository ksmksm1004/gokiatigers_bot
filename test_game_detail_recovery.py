import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from requests import ReadTimeout

from bot import get_cached_today_game, get_detailed_game, main, should_poll_game
from config import Settings
from parser import parse_game_summary


class GameDetailRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings('', '', state_path=Path(self.tmp.name) / 'state.json')
        self.game = {'gameId': 'today'}
        self.detail = {'gameId': 'today', 'gdate': 20261027, 'gtime': '18:30'}
        self.state = {'detailedGameId': 'today', 'detailedGame': self.detail}
        self.client = Mock()

    def test_detail_timeout_preserves_details_and_relay_progress(self):
        self.state['lastRelaySeq'] = 42
        self.client.game_detail.side_effect = ReadTimeout()
        result = get_detailed_game(self.client, self.settings, self.state, self.game, force=True)
        self.assertEqual(result, self.detail)
        self.assertEqual(self.state['lastRelaySeq'], 42)
        self.assertIn('nextGameDetailRetryAt', self.state)
        self.client.preview.assert_not_called()

    def test_cooldown_allows_forced_check_without_blocking_request(self):
        self.state['nextGameDetailRetryAt'] = (datetime.now(self.settings.timezone) + timedelta(seconds=60)).isoformat()
        self.assertEqual(get_detailed_game(self.client, self.settings, self.state, self.game, force=True), self.detail)
        self.client.game_detail.assert_not_called()

    def test_success_after_cooldown_refreshes_status(self):
        self.state['nextGameDetailRetryAt'] = (datetime.now(self.settings.timezone) - timedelta(seconds=1)).isoformat()
        self.client.game_detail.return_value = {'result': {'game': {'statusCode': 'END'}}}
        result = get_detailed_game(self.client, self.settings, self.state, self.game, force=True)
        self.assertEqual(result['statusCode'], 'END')
        self.assertNotIn('nextGameDetailRetryAt', self.state)

    def test_previous_game_cache_is_not_used_on_failure(self):
        self.state['detailedGameId'] = 'yesterday'
        self.client.game_detail.side_effect = ReadTimeout()
        self.client.preview.return_value = {'result': {'previewData': {'gameInfo': self.detail}}}
        result = get_detailed_game(self.client, self.settings, self.state, self.game, force=True)
        self.assertEqual(result, self.detail)
        self.client.preview.assert_called_once_with('today')
        self.assertEqual(self.state['detailedGameId'], 'today')

    def test_no_details_and_both_endpoints_down_propagates_error(self):
        self.client.game_detail.side_effect = ReadTimeout()
        self.client.preview.side_effect = ReadTimeout()
        with self.assertRaises(ReadTimeout):
            get_detailed_game(self.client, self.settings, {}, self.game)

    def test_main_reaches_relay_when_detail_is_down(self):
        self.state.update(gameId='today', lineupSentGameId='today')
        self.client.game_detail.side_effect = ReadTimeout()
        with ExitStack() as stack:
            stack.enter_context(patch('bot.get_settings', return_value=self.settings))
            stack.enter_context(patch('bot.NaverSportsClient', return_value=self.client))
            stack.enter_context(patch('bot.load_state', return_value=self.state))
            stack.enter_context(patch('bot.get_cached_today_game', return_value=self.game))
            for name in ('setup_logging', 'KBOPlayerClient', 'NaverWeatherClient', 'TelegramBot',
                         'handle_telegram_commands', 'send_due_kia_news', 'send_due_kia_roster_news', 'send_due_next_kia_game',
                         'send_due_kia_highlight', 'send_due_kia_shorts', 'process_due_asian_games_baseball_relay'):
                stack.enter_context(patch('bot.' + name))
            for name in ('should_check_game_status', 'should_poll_game', 'is_after_game_start'):
                stack.enter_context(patch('bot.' + name, return_value=True))
            for name in ('should_check_preview', 'is_before_game_start'):
                stack.enter_context(patch('bot.' + name, return_value=False))
            relay = stack.enter_context(patch('bot.process_relay', side_effect=KeyboardInterrupt))
            with self.assertRaises(KeyboardInterrupt):
                main()
            relay.assert_called_once()

    def test_ended_game_uses_current_status_not_stale_preview(self):
        self.state['detailedGame'] = dict(self.detail, statusCode='1')
        self.client.preview.return_value = {'result': {'previewData': {'gameInfo': dict(self.detail, statusCode='1')}}}
        self.client.game_detail.return_value = {'result': {'game': {
            'gameId': 'today', 'statusCode': 'RESULT', 'gameDateTime': '2026-10-27T18:30:00',
        }}}
        detail = get_detailed_game(self.client, self.settings, self.state, self.game, force=True)
        summary = parse_game_summary(detail)
        self.assertTrue(should_poll_game(summary, self.settings, datetime(2026, 10, 28, 12, tzinfo=self.settings.timezone)))
        self.assertEqual(detail['statusCode'], 'RESULT')
        self.client.preview.assert_not_called()

    def test_new_game_keeps_roster_news_delivery_history(self):
        tracking = {'initializedAt': '2026-10-30T12:00:00+09:00', 'seen': {'109/1': '2026-10-30T12:00:00+09:00'}}
        self.state.update(gameId='yesterday', stoveNews=tracking)
        self.client.game_detail.return_value = {'result': {'game': self.detail}}
        with ExitStack() as stack:
            stack.enter_context(patch('bot.get_settings', return_value=self.settings))
            stack.enter_context(patch('bot.NaverSportsClient', return_value=self.client))
            stack.enter_context(patch('bot.load_state', return_value=self.state))
            stack.enter_context(patch('bot.get_cached_today_game', return_value=self.game))
            for name in ('setup_logging', 'KBOPlayerClient', 'NaverWeatherClient', 'TelegramBot',
                         'handle_telegram_commands', 'send_due_kia_news', 'send_due_kia_roster_news',
                         'send_due_next_kia_game', 'send_due_kia_highlight', 'send_due_kia_shorts',
                         'process_due_asian_games_baseball_relay', 'send_lineup_once'):
                stack.enter_context(patch('bot.' + name))
            for name in ('should_check_game_status', 'should_poll_game', 'is_after_game_start'):
                stack.enter_context(patch('bot.' + name, return_value=True))
            for name in ('should_check_preview', 'is_before_game_start'):
                stack.enter_context(patch('bot.' + name, return_value=False))
            relay = stack.enter_context(patch('bot.process_relay', side_effect=KeyboardInterrupt))
            with self.assertRaises(KeyboardInterrupt):
                main()
            self.assertEqual(relay.call_args.args[3]['stoveNews'], tracking)

    def test_empty_detail_uses_preview_without_losing_known_terminal_status(self):
        self.client.game_detail.return_value = {'result': {'game': None}}
        self.client.preview.return_value = {'result': {'previewData': {'gameInfo': dict(self.detail, statusCode='1')}}}
        detail = get_detailed_game(self.client, self.settings, {}, dict(self.game, statusCode='RESULT'))
        self.assertEqual(detail['statusCode'], 'RESULT')
        self.assertEqual(detail['gtime'], '18:30')


class PreviousGameRolloverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings('', '', state_path=Path(self.tmp.name) / 'state.json')
        self.previous = {'gameId': 'previous', 'homeTeamCode': 'HT', 'awayTeamCode': 'SS'}
        self.today = {'gameId': 'today', 'homeTeamCode': 'HT', 'awayTeamCode': 'SS', 'statusCode': 'READY'}
        self.state = {'gameId': 'previous', 'scheduleDate': '2026-10-29', 'scheduledGame': self.previous}
        self.now = datetime(2026, 10, 30, 17, 40, tzinfo=self.settings.timezone)
        self.client = Mock()

    def test_unsent_previous_final_does_not_block_today(self):
        self.client.game_detail.return_value = {'result': {'game': dict(self.previous, statusCode='RESULT')}}
        self.client.games_on.return_value = [self.today]
        game = get_cached_today_game(self.client, self.settings, self.state, self.now)
        self.assertEqual(game, self.today)
        self.assertEqual(self.state['scheduleDate'], '2026-10-30')
        self.assertEqual(self.state['scheduledGame'], self.today)
        self.assertNotIn('gameOverSentGameId', self.state)

    def test_previous_final_still_processed_when_today_has_no_game(self):
        self.client.game_detail.return_value = {'result': {'game': dict(self.previous, statusCode='RESULT')}}
        self.client.games_on.return_value = []
        game = get_cached_today_game(self.client, self.settings, self.state, self.now)
        self.assertEqual(game['gameId'], 'previous')
        self.assertEqual(game['statusCode'], 'RESULT')
        self.assertEqual(self.state['scheduleDate'], '2026-10-29')

    def test_live_previous_game_is_not_replaced(self):
        self.client.game_detail.return_value = {'result': {'game': dict(self.previous, statusCode='STARTED')}}
        game = get_cached_today_game(self.client, self.settings, self.state, self.now)
        self.assertEqual(game['gameId'], 'previous')
        self.client.games_on.assert_not_called()


if __name__ == '__main__':
    unittest.main()
