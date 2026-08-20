import unittest
from io import BytesIO

from PIL import Image

from lineup_image import IMAGE_SIZE, defensive_lineup_players, render_defensive_lineup_image


class DefensiveLineupImageTest(unittest.TestCase):
    @staticmethod
    def preview():
        positions = [
            (None, "1", "선발투수", "황동하"),
            (1, "7", "좌익수", "박재현"),
            (2, "4", "2루수", "김선빈"),
            (3, "0", "지명타자", "김도영"),
            (4, "3", "1루수", "카스트로"),
            (5, "9", "우익수", "나성범"),
            (6, "5", "3루수", "윤도현"),
            (7, "2", "포수", "한준수"),
            (8, "6", "유격수", "정현창"),
            (9, "8", "중견수", "김호령"),
        ]
        return {
            "gameInfo": {"aCode": "HT", "aName": "KIA", "gdate": 20260820},
            "awayTeamLineUp": {
                "fullLineUp": [
                    {
                        "playerCode": f"player-{position}",
                        "playerName": name,
                        "batorder": order,
                        "position": position,
                        "positionName": position_name,
                    }
                    for order, position, position_name, name in positions
                ]
            },
        }

    @staticmethod
    def photo_bytes():
        image = Image.new("RGBA", (80, 100), (200, 30, 40, 255))
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def test_defensive_players_exclude_designated_hitter_and_cover_all_positions(self):
        players = defensive_lineup_players(self.preview(), "away")

        self.assertEqual([player["positionCode"] for player in players], list("123456789"))
        self.assertNotIn("김도영", [player["playerName"] for player in players])

    def test_rendered_image_is_a_complete_png(self):
        requested_urls = []

        def load_photo(url):
            requested_urls.append(url)
            return self.photo_bytes()

        content = render_defensive_lineup_image(self.preview(), "away", load_photo)

        self.assertIsNotNone(content)
        rendered = Image.open(BytesIO(content))
        self.assertEqual(rendered.format, "PNG")
        self.assertEqual(rendered.size, IMAGE_SIZE)
        self.assertEqual(len(requested_urls), 9)
        self.assertEqual(rendered.getpixel((0, 0)), (47, 125, 69))

    def test_incomplete_defense_does_not_render(self):
        preview = self.preview()
        preview["awayTeamLineUp"]["fullLineUp"] = preview["awayTeamLineUp"]["fullLineUp"][:-1]

        self.assertIsNone(render_defensive_lineup_image(preview, "away", lambda _url: self.photo_bytes()))


if __name__ == "__main__":
    unittest.main()
