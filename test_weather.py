import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from naver_weather import format_stadium_weather, parse_weather_page, resolve_stadium_weather_region


class NaverWeatherTest(unittest.TestCase):
    def test_resolve_stadium_weather_region(self):
        self.assertEqual(resolve_stadium_weather_region("광주").code, "18300105")
        self.assertEqual(resolve_stadium_weather_region("사직").code, "08260109")
        self.assertEqual(resolve_stadium_weather_region("잠실").code, "09710101")

    def test_parse_weather_page_and_format(self):
        sample = (
            '<script>var blockApiResult = {"results":{"choiceResult":{'
            '"talkHeader~~1":{"nowFcastInfo":{"wetrTxt":"구름많음","tmpr":26.0,'
            '"windSpd":5.0,"oneHourRainAmt":"0.0"},"airNowInfo":'
            '{"stationPm10Legend":"좋음","stationPm25Legend":"보통"}},'
            '"visualMap~~2":{"domesticWetrList":[{"wetrTxt":"맑음","tmpr":25.0,'
            '"rainProb":"-","rainAmt":"0","windSpd":3.2,"aplYmd":"20260708",'
            '"aplTm":"01"},{"wetrTxt":"구름많음","tmpr":24.0,"rainProb":"60",'
            '"rainAmt":"2","windSpd":4.1,"aplYmd":"20260708","aplTm":"02"}]}}}};'
            "</script>"
        )
        data = parse_weather_page(sample)
        message = format_stadium_weather(
            "광주",
            resolve_stadium_weather_region("광주"),
            data,
            datetime(2026, 7, 8, 1, tzinfo=ZoneInfo("Asia/Seoul")),
            hours=2,
        )

        self.assertIn("구장 날씨 | 광주", message)
        self.assertIn("현재 흐림 26.0° | 바람 5.0m/s | 1시간 강수 0.0mm", message)
        self.assertIn("미세먼지 좋음 | 초미세먼지 보통", message)
        self.assertIn("01시 맑음 25.0° | 강수 - (0mm) | 바람 3.2m/s", message)
        self.assertIn("02시 흐림 24.0° | 강수 60% (2mm) | 바람 4.1m/s", message)


if __name__ == "__main__":
    unittest.main()
