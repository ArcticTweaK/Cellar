import time
import unittest
from pathlib import Path
import tempfile

from cellar import cli, playlink, robloxlog, sober, specs
from cellar.models import Account

JOB = "0e9b2c1a-1234-4abc-9def-0123456789ab"


def player_link(query: str) -> str:
    return ("roblox-player:1+launchmode:play+gameinfo:TICKET+launchtime:1+placelauncherurl:"
            + sober._urlencode("https://www.roblox.com/Game/PlaceLauncher.ashx?" + query) + "+browsertrackerid:1")


class PlayLinks(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(playlink.parse(player_link("request=RequestGame&placeId=5")).kind, "Game")
        s = playlink.parse(player_link(f"request=RequestGameJob&placeId=5&gameId={JOB}"))
        self.assertEqual((s.kind, s.job_id), ("Job", JOB))
        s = playlink.parse(player_link("request=RequestPrivateGame&placeId=5&linkCode=abc"))
        self.assertEqual((s.kind, s.link_code), ("Private", "abc"))
        s = playlink.parse(player_link("request=RequestFollowUser&userId=77"))
        self.assertEqual((s.kind, s.follow_user_id), ("Follow", 77))
        self.assertEqual(playlink.parse(player_link("request=RequestPrivateGame&placeId=5&accessCode=x")).kind,
                         "Reserved")
        self.assertIsNone(playlink.parse("roblox-player:1+launchmode:app"))

    def test_deeplinks(self):
        s = playlink.parse(f"roblox://experiences/start?placeId=9&gameInstanceId={JOB}")
        self.assertEqual((s.kind, s.place_id), ("Job", 9))
        self.assertEqual(playlink.parse("roblox://placeId=9").kind, "Game")
        self.assertIsNone(playlink.parse("roblox://navigation/home"))


class RobloxLog(unittest.TestCase):
    def test_events(self):
        d = Path(tempfile.mkdtemp())
        f = d / "x_Player_last.log"
        w = robloxlog.Watcher()

        def add(text):
            with open(f, "a") as fh:
                fh.write(text)
            return [(e.kind, e.reason) for e in w.poll({1: (d, time.time() - 5)}).get(1, [])]
        join = f"t [FLog::Output] ! Joining game '{JOB}' place 5 at 1.2.3.4\n"
        gone = "t [FLog::Network] Time to disconnect replication data: 0.1\n"
        self.assertEqual(add(join), [("joined", 0)])
        self.assertEqual(w.where(1), (5, JOB))
        self.assertEqual(add("t Sending disconnect with reason: 277\n" + gone), [("disconnected", 277)])
        add(join)
        self.assertEqual(add("t [FLog::SingleSurfaceApp] initiateTeleport\n" + gone), [("teleport", 0)])
        add(join)
        self.assertEqual(add("t [FLog::SingleSurfaceApp] leaveUGCGameInternal\n" + gone), [("left", 0)])


class Cli(unittest.TestCase):
    def test_parse_launch(self):
        names, spec, err = cli.parse_launch(["a", "b", "--place", "https://www.roblox.com/games/42/x"])
        self.assertEqual((names, spec.place_id, err), (["a", "b"], 42, ""))
        names, spec, err = cli.parse_launch(["a", "--job", "4242", JOB])
        self.assertEqual((spec.kind, spec.job_id), ("Job", JOB))
        self.assertTrue(cli.parse_launch(["a", "--place"])[2])
        self.assertTrue(cli.parse_launch(["a", "--nope"])[2])

    def test_pick_accounts(self):
        from cellar import store
        store.accounts = [Account(username="Main"), Account(username="alt1", group="Farm"),
                          Account(username="alt2", alias="Bob", group="Farm")]
        self.assertEqual(len(cli.pick_accounts(["group:farm"])[0]), 2)
        self.assertEqual(cli.pick_accounts(["bob"])[0][0].username, "alt2")
        self.assertEqual(len(cli.pick_accounts(["all"])[0]), 3)
        self.assertIn("nobody", cli.pick_accounts(["main", "nobody"])[1])


class Specs(unittest.TestCase):
    def test_saved_spec(self):
        a = Account(game_link="https://www.roblox.com/games/42/x?privateServerLinkCode=abc")
        s = specs.saved_spec(a)
        self.assertEqual((s.kind, s.place_id, s.link_code), ("Private", 42, "abc"))
        self.assertEqual(specs.saved_spec(Account(saved_place_id="4242", saved_job_id=JOB)).kind, "Job")
        self.assertIsNone(specs.saved_spec(Account()))


class Games(unittest.TestCase):
    def test_short_numbers(self):
        from cellar.games import short
        self.assertEqual([short(n) for n in (999, 1500, 242333, 45493296137)], ["999", "1.5K", "242K", "45.5B"])

    def test_rating(self):
        from cellar.games import Game
        self.assertEqual(Game(up=9, down=1).rating, 90)
        self.assertIsNone(Game().rating)


class ShareLinks(unittest.TestCase):
    def test_one_off_launch_keeps_the_saved_game(self):
        from unittest import mock
        from cellar.models import LaunchSpec
        a = Account(username="x", game_link="https://www.roblox.com/games/4242/mine")
        per = LaunchSpec(kind="Private", share_code="abc")
        with mock.patch("cellar.api.resolve_share",
                        return_value=LaunchSpec(kind="Private", place_id=99, link_code="L")):
            self.assertTrue(specs.resolve_saved_share(a, per, lambda m: None, save=False))
        self.assertEqual((per.place_id, per.link_code, a.game_link),
                         (99, "L", "https://www.roblox.com/games/4242/mine"))
