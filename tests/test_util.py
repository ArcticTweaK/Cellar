import unittest

from cellar import util
from cellar.updates import vtuple


class Util(unittest.TestCase):
    def test_place_id(self):
        self.assertEqual(util.parse_place_id("920587237"), 920587237)
        self.assertEqual(util.parse_place_id("https://www.roblox.com/games/920587237/Adopt-Me"), 920587237)
        self.assertEqual(util.parse_place_id("not a game"), 0)

    def test_guid(self):
        self.assertTrue(util.looks_like_guid("0e9b2c1a-1234-4abc-9def-0123456789ab"))
        self.assertFalse(util.looks_like_guid("0e9b2c1a"))

    def test_private_and_share_links(self):
        self.assertEqual(util.private_link_code(
            "https://www.roblox.com/games/123/x?privateServerLinkCode=abc123"), "abc123")
        self.assertEqual(util.share_code_of("https://www.roblox.com/share?code=dad67b2c&type=Server"), "dad67b2c")
        self.assertEqual(util.share_code_of("https://www.roblox.com/games/123"), "")

    def test_cookies(self):
        c = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you|_" + "A1b2" * 30
        self.assertEqual(util.extract_cookies(f"junk {c} more"), [c])

    def test_versions(self):
        self.assertLess(vtuple("1.0.0"), vtuple("1.0.1"))
        self.assertLess(vtuple("1.9"), vtuple("v1.10"))
        self.assertEqual(vtuple("v2.0.0"), (2, 0, 0))
