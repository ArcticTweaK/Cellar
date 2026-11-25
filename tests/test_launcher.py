"""Launcher bookkeeping: one record per account (the "8 / 6 running" bug)."""

import types
import unittest
from unittest import mock

from cellar import launcher, store
from cellar.models import Account, LaunchSpec


class FakeWorld:
    """Sober clients by tracker id, standing in for /proc."""

    def __init__(self):
        self.clients = {}           # tracker -> window pid
        self.next_pid = 5000

    def window_pid(self, tracker, procs=None):
        return self.clients.get(tracker, 0)

    def spawn(self, argv, env, log_file):
        self.next_pid += 1
        self.clients[self.tracker] = self.next_pid          # the new client comes up right away
        return types.SimpleNamespace(pid=self.next_pid, poll=lambda: None, wait=lambda *a, **k: 0)


class OneRecordPerAccount(unittest.TestCase):
    def setUp(self):
        self.world = w = FakeWorld()
        self.a = Account(username="alt1", cookie="c" * 60, tracker_id=111222333444)
        w.tracker = self.a.tracker_id
        patches = [
            mock.patch.object(store, "save_accounts", lambda *x, **k: None),
            mock.patch.object(launcher.sober, "sober_installed", lambda: True),
            mock.patch.object(launcher.sober, "multi_instance_support", lambda: (True, "")),
            mock.patch.object(launcher.sober, "ensure_profile", lambda *a: None),
            mock.patch.object(launcher.sober, "write_profile_settings", lambda *a: None),
            mock.patch.object(launcher.sober, "place_launcher_url", lambda *a: "url"),
            mock.patch.object(launcher.sober, "build_uri", lambda *a: "uri"),
            mock.patch.object(launcher.sober, "build_command", lambda *a: ([], {}, "unit")),
            mock.patch.object(launcher.sober, "profile_home", lambda a: launcher.paths.DATA_DIR),
            mock.patch.object(launcher.sober, "spawn", w.spawn),
            mock.patch.object(launcher.sober, "window_pid", w.window_pid),
            mock.patch.object(launcher.sober, "alive", lambda pid, tracker: w.clients.get(tracker) == pid),
            mock.patch.object(launcher.sober, "client_starting", lambda *a: False),
            mock.patch.object(launcher.sober, "scan", lambda: []),
            mock.patch.object(launcher.sober, "stop", lambda *a, **k: 1),
            mock.patch.object(launcher.api, "get_ticket", lambda c: types.SimpleNamespace(ticket="t", error="")),
            mock.patch.object(launcher.gfx, "final", lambda *a: ({}, [])),
            mock.patch.object(launcher.time, "sleep", lambda s: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        store.settings.multi_instance = True
        store.settings.refresh_cookie_on_launch = False
        store.settings.max_instances = 0
        self.L = launcher.Launcher()

    def test_relaunch_after_the_client_died_keeps_one_record(self):
        log = []
        self.assertTrue(self.L.launch(self.a, LaunchSpec(), log.append))
        self.world.clients.clear()                       # its window closed; the watcher has not run yet
        self.assertEqual(self.L.alive_instances(), [])
        self.assertTrue(self.L.launch(self.a, LaunchSpec(), log.append))     # launched again right away
        self.assertEqual(len(self.L.instances_of(self.a)), 1)
        self.assertEqual(len(self.L.alive_instances()), 1)

    def test_a_later_crash_is_relaunched_once(self):
        log = []
        self.L.launch(self.a, LaunchSpec(), log.append)
        self.world.clients.clear()
        self.L.launch(self.a, LaunchSpec(), log.append)
        self.world.clients.clear()                       # now the new client crashes too
        store.settings.auto_relaunch = True
        with mock.patch.object(launcher.api, "internet_ok", lambda: True), \
                mock.patch.object(self.L, "launch") as relaunch:
            self.L.watcher_tick(log.append, lambda: None)
        self.assertEqual(relaunch.call_count, 1)         # the stale record made it 2 before

if __name__ == "__main__":
    unittest.main()
