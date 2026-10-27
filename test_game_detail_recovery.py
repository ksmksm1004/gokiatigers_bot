import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from requests import ReadTimeout

from bot import get_detailed_game, main
from config import Settings


class GameDetailRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings('', '', state_path=Path(self.tmp.name) / 'state.json')
        self.game = {'gameId': 'today'}
        self.detail = {'gameId': 'today', 'gdate': 20261027, 'gtime': '18:30'}
        self.state = {'detailedGameId': 'today', 'detailedGame': self.detail}
        self.client = Mock()

    def test_preview_timeout_preserves_details_and_relay_progress(self):
        self.state['lastRelaySeq'] = 42
        self.client.preview.side_effect = ReadTimeout()
        result = get_detailed_game(self.client, self.settings, self.state, self.game, force=True)
        self.assertEqual(result, self.detail)
        self.assertEqual(self.state['lastRelaySeq'], 42)
        self.assertIn('nextGameDetailRetryAt', self.state)
        self.client.game_detail.assert_not_called()

    def test_cooldown_allows_forced_check_without_blocking_request(self):
        self.state['nextGameDetailRetryAt'] = (datetime.now(self.settings.timezone) + timedelta(seconds=60)).isoformat()
        self.assertEqual(get_detailed_game(self.client, self.settings, self.state, self.game, force=True), self.detail)
        self.client.preview.assert_not_called()

    def test_success_after_cooldown_refreshes_status(self):
        self.state['nextGameDetailRetryAt'] = (datetime.now(self.settings.timezone) - timedelta(seconds=1)).isoformat()
        self.client.preview.return_value = {'result': {'previewData': {'gameInfo': {'statusCode': 'END'}}}}
        result = get_detailed_game(self.client, self.settings, self.state, self.game, force=True)
        self.assertEqual(result['statusCode'], 'END')
        self.assertNotIn('nextGameDetailRetryAt', self.state)

    def test_previous_game_cache_is_not_used_on_failure(self):
        self.state['detailedGameId'] = 'yesterday'
        self.client.preview.side_effect = ReadTimeout()
        self.client.game_detail.return_value = {'result': {'game': self.detail}}
        result = get_detailed_game(self.client, self.settings, self.state, self.game, force=True)
        self.assertEqual(result, self.detail)
        self.client.game_detail.assert_called_once_with('today')
        self.assertEqual(self.state['detailedGameId'], 'today')

    def test_no_details_and_both_endpoints_down_propagates_error(self):
        self.client.preview.side_effect = ReadTimeout()
        self.client.game_detail.side_effect = ReadTimeout()
        with self.assertRaises(ReadTimeout):
            get_detailed_game(self.client, self.settings, {}, self.game)

    def test_main_reaches_relay_when_preview_is_down(self):
        self.state.update(gameId='today', lineupSentGameId='today')
        self.client.preview.side_effect = ReadTimeout()
        with ExitStack() as stack:
            stack.enter_context(patch('bot.get_settings', return_value=self.settings))
            stack.enter_context(patch('bot.NaverSportsClient', return_value=self.client))
            stack.enter_context(patch('bot.load_state', return_value=self.state))
            stack.enter_context(patch('bot.get_cached_today_game', return_value=self.game))
            for name in ('setup_logging', 'KBOPlayerClient', 'NaverWeatherClient', 'TelegramBot',
                         'handle_telegram_commands', 'send_due_kia_news', 'send_due_next_kia_game',
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


if __name__ == '__main__':
    unittest.main()
