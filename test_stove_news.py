import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from config import Settings, get_settings
from stove_news import roster_news_kind, poll_roster_news, fetch_roster_news
from bot import send_due_kia_roster_news


class RosterHeadlineTests(unittest.TestCase):
    def test_announcements(self):
        for title, kind in [
            ('[공식] KIA-삼성, 김가나·이나다 1대1 트레이드 단행', '트레이드'),
            ('기아 타이거즈, 투수 김가나 트레이드 영입 발표', '트레이드'),
            ('KIA, 2027 신인 드래프트 1라운드 김가나 지명', '신인 드래프트'),
            ('KIA 신인드래프트 지명 결과, 11명 명단 공개', '신인 드래프트'),
        ]:
            with self.subTest(title=title):
                self.assertEqual(roster_news_kind({'title': title}), kind)

    def test_speculation_history_and_unrelated_articles_are_excluded(self):
        for title in [
            'KIA 트레이드 가능성, 김가나 영입할까?',
            'KIA 트레이드설 부인…공식 발표 없다',
            'KIA 1대1 트레이드 불발',
            'KIA, 트레이드 영입 효과! 김가나 맹활약',
            '지난해 KIA 트레이드 단행, 그 비화',
            '삼성-롯데 1대1 트레이드 공식 발표',
            'KIA 신인 드래프트 예상 지명 순위',
            'KIA 신인지명 앞두고 관심 집중',
            'KIA 2차 드래프트 결과 발표',
            'KIA 오늘 경기 승리',
        ]:
            with self.subTest(title=title):
                self.assertIsNone(roster_news_kind({'title': title}))

    def test_league_draft_results_must_mention_kia(self):
        article = {'title': '2027 신인 드래프트 지명 결과 전체 명단'}
        self.assertIsNone(roster_news_kind(article))
        article['subContent'] = 'KIA는 김가나를 지명했다.'
        self.assertEqual(roster_news_kind(article), '신인 드래프트')


class RosterMonitorTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings('', 'chat-a', telegram_chat_ids=('chat-b',))
        self.now = datetime(2026, 10, 30, 12, tzinfo=self.settings.timezone)
        self.state = {}
        self.client = Mock()
        self.client.section_news.return_value = {'result': {'newsList': []}}
        self.telegram = Mock()
        self.chats = {chat: Mock() for chat in self.settings.all_telegram_chat_ids}
        self.telegram.for_chat.side_effect = self.chats.__getitem__
        self.persist = Mock()

    def article(self, aid='1', title='[공식] KIA 1대1 트레이드 단행', minutes=1):
        return {'oid': '109', 'aid': aid, 'title': title, 'sourceName': '테스트신문',
                'dateTime': (self.now + timedelta(minutes=minutes)).isoformat()}

    def poll(self, minutes=0):
        return poll_roster_news(self.client, self.telegram, self.settings, self.state,
                                self.now + timedelta(minutes=minutes), self.persist)

    def feed(self, articles):
        self.client.section_news.return_value = {'result': {'newsList': articles}}

    def test_first_poll_baselines_without_sending_old_news(self):
        self.feed([self.article(minutes=-1)])
        self.assertFalse(self.poll())
        self.assertIn('109/1', self.state['stoveNews']['seen'])
        self.telegram.for_chat.assert_not_called()
        self.assertFalse(self.poll(11))

    def test_new_news_sends_once_across_restart(self):
        self.poll()
        self.feed([self.article()])
        self.assertTrue(self.poll(11))
        self.state = json.loads(json.dumps(self.state))
        self.assertFalse(self.poll(22))
        for chat in self.chats.values():
            chat.send_message.assert_called_once()
            message = chat.send_message.call_args.args[0]
            self.assertIn('트레이드', message)
            self.assertIn('https://m.sports.naver.com/kbaseball/article/109/1', message)

    def test_same_headline_under_another_article_id_is_not_resent(self):
        self.poll()
        self.feed([self.article('1'), self.article('2')])
        self.poll(11)
        for chat in self.chats.values():
            chat.send_message.assert_called_once()

    def test_partial_delivery_retries_only_failed_chat_even_if_article_leaves_feed(self):
        self.poll()
        self.chats['chat-b'].send_message.side_effect = RuntimeError('temporary failure')
        self.feed([self.article()])
        with self.assertLogs(level='ERROR'):
            self.poll(11)
        self.assertEqual(len(self.state['stoveNews']['pending']), 1)
        self.state = json.loads(json.dumps(self.state))
        self.feed([])
        self.chats['chat-b'].send_message.side_effect = None
        self.poll(22)
        self.chats['chat-a'].send_message.assert_called_once()
        self.assertEqual(self.chats['chat-b'].send_message.call_count, 2)
        self.assertEqual(self.state['stoveNews']['pending'], [])

    def test_old_missing_date_and_future_articles_do_not_send(self):
        self.poll()
        missing = self.article('3')
        missing.pop('dateTime')
        self.feed([self.article('1', minutes=-60), missing, self.article('4', minutes=100)])
        self.assertFalse(self.poll(11))
        self.telegram.for_chat.assert_not_called()

    def test_interval_does_not_fetch_on_every_game_poll(self):
        self.poll()
        self.poll(1)
        self.client.section_news.assert_called_once()

    def test_failed_initial_fetch_does_not_baseline_and_is_rate_limited(self):
        self.client.section_news.side_effect = RuntimeError('API unavailable')
        with self.assertRaises(RuntimeError):
            self.poll()
        self.assertNotIn('initializedAt', self.state['stoveNews'])
        self.assertFalse(self.poll(1))
        self.assertEqual(self.client.section_news.call_count, 1)

    def test_disabled_monitor_does_not_fetch_or_mutate(self):
        self.settings = Settings('', 'chat-a', stove_news_enabled=False)
        self.assertFalse(self.poll())
        self.assertEqual(self.state, {})
        self.client.section_news.assert_not_called()

    def test_fetch_reads_later_pages(self):
        first = [self.article(str(i)) for i in range(100)]
        self.client.section_news.side_effect = [
            {'result': {'newsList': first}},
            {'result': {'newsList': [self.article('200')]}}
        ]
        self.assertEqual(len(fetch_roster_news(self.client, self.now)), 101)
        self.assertEqual(self.client.section_news.call_args.kwargs['page'], 2)

    @patch('bot.poll_roster_news', side_effect=RuntimeError('API down'))
    def test_monitor_failure_does_not_escape_into_game_loop(self, poll):
        with self.assertLogs(level='ERROR'):
            self.assertFalse(send_due_kia_roster_news(self.client, self.telegram, self.settings, {}, self.now))

    @patch('config.load_dotenv')
    def test_config_switch_and_minimum_interval(self, dotenv):
        with patch.dict('os.environ', {'DRY_RUN': 'true', 'STOVE_NEWS_ENABLED': 'false',
                                      'STOVE_NEWS_POLL_SECONDS': '1'}, clear=True):
            settings = get_settings()
        self.assertFalse(settings.stove_news_enabled)
        self.assertEqual(settings.stove_news_poll_seconds, 60)


if __name__ == '__main__':
    unittest.main()
