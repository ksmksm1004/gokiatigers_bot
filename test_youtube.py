import unittest
from datetime import date
from unittest.mock import Mock

from youtube import find_tving_kia_highlight


class TvingHighlightTest(unittest.TestCase):
    def test_finds_kia_highlight_for_requested_game_date(self):
        feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>[KIA vs \xec\x82\xbc\xec\x84\xb1] 7/29 \xea\xb2\xbd\xea\xb8\xb0 I 2026 KBO I \xed\x95\x98\xec\x9d\xb4\xeb\x9d\xbc\xec\x9d\xb4\xed\x8a\xb8 I TVING</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=kia-video"/>
  </entry>
  <entry>
    <title>[\xed\x82\xa4\xec\x9b\x80 vs LG] 7/29 \xea\xb2\xbd\xea\xb8\xb0 I \xed\x95\x98\xec\x9d\xb4\xeb\x9d\xbc\xec\x9d\xb4\xed\x8a\xb8 I TVING</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=other-video"/>
  </entry>
</feed>"""
        response = Mock(content=feed)
        session = Mock()
        session.get.return_value = response

        result = find_tving_kia_highlight(date(2026, 7, 29), session=session)

        self.assertEqual(result["url"], "https://www.youtube.com/watch?v=kia-video")
        self.assertIn("[KIA vs 삼성]", result["title"])
        response.raise_for_status.assert_called_once()

    def test_ignores_kia_highlight_from_another_date(self):
        feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>[KIA vs \xec\x82\xbc\xec\x84\xb1] 7/28 \xea\xb2\xbd\xea\xb8\xb0 I \xed\x95\x98\xec\x9d\xb4\xeb\x9d\xbc\xec\x9d\xb4\xed\x8a\xb8 I TVING</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=old-video"/>
  </entry>
</feed>"""
        response = Mock(content=feed)
        session = Mock()
        session.get.return_value = response

        self.assertIsNone(find_tving_kia_highlight(date(2026, 7, 29), session=session))


if __name__ == "__main__":
    unittest.main()
