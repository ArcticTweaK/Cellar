"""Launcher bookkeeping: one record per account (the "8 / 6 running" bug)."""

import tempfile
import types
import unittest
from pathlib import Path
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
        rt = tempfile.TemporaryDirectory()                # launch.json: never the real runtime dir
        self.addCleanup(rt.cleanup)
        self.rt = Path(rt.name)
        patches.append(mock.patch.object(launcher.sober, "runtime_dir_path", lambda a, prefix="": self.rt / a.id[:12]))
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

    def test_after_a_cellar_restart_a_crash_goes_back_to_the_same_game(self):
        spec = LaunchSpec(kind="Private", place_id=42, link_code="abc")
        self.L.launch(self.a, spec, lambda m: None)
        restarted = launcher.Launcher()                  # Cellar restarted; the client kept running
        with mock.patch.object(launcher.sober, "all_sober_trackers",
                               lambda *a: {self.a.tracker_id: self.world.clients[self.a.tracker_id]}), \
                mock.patch.object(launcher.store, "find_by_tracker", lambda t: self.a), \
                mock.patch.object(launcher, "_running_screen", lambda a: None):
            restarted.adopt_running()
        inst = restarted.instances_of(self.a)[0]
        self.assertEqual((inst.spec.kind, inst.spec.place_id, inst.spec.link_code), ("Private", 42, "abc"))
        self.assertEqual(launcher.again_spec(inst).link_code, "abc")

    def test_stop_while_starting_is_not_reported_as_a_crash(self):
        log = []
        self.world.spawn = lambda *a: types.SimpleNamespace(pid=1, poll=lambda: None, wait=lambda *x, **k: 0)
        with mock.patch.object(launcher.sober, "spawn", self.world.spawn):
            def stop_soon(_s, L=self.L):
                for i in L.snapshot():
                    i.user_closed = True
            with mock.patch.object(launcher.time, "sleep", stop_soon):
                self.assertFalse(self.L.launch(self.a, LaunchSpec(), log.append))
        self.assertFalse(any("exited right away" in m or "did not show up" in m for m in log))
        self.assertTrue(any("stopped while it was starting" in m for m in log))


class LimitsAreForAlts(unittest.TestCase):
    """CPU priority / RAM limit: alts only; a Full quality window (your main) is set back to normal."""

    def test_apply_to_running_skips_the_main(self):
        main = Account(username="main", full_quality=True)
        alt = Account(username="alt")
        L = launcher.Launcher()
        running = [launcher.Instance(account=main, pid=101), launcher.Instance(account=alt, pid=202)]
        calls = []
        with mock.patch.object(launcher.sober, "apply_limits", lambda pid, *a: calls.append((pid, *a)) or ""), \
                mock.patch.object(L, "alive_instances", lambda: running), \
                mock.patch.object(store.settings, "priority", "Idle"), \
                mock.patch.object(store.settings, "ram_cap_mb", 900):
            n = L.apply_limits_all(lambda m: None)
        self.assertEqual(n, 1)
        self.assertIn((202, "Idle", 900), calls)
        self.assertIn((101, "Normal", 0), calls)


class AgainSpec(unittest.TestCase):
    def inst(self, spec, place=0):
        from cellar.models import Instance
        return Instance(account=Account(username="x"), spec=spec, place_id=place)

    def test_kicked_from_one_server_goes_to_the_game_not_that_server(self):
        sp = launcher.again_spec(self.inst(LaunchSpec(kind="Job", place_id=7, job_id="j")), kicked=True)
        self.assertEqual((sp.kind, sp.place_id, sp.job_id), ("Game", 7, ""))

    def test_a_crash_goes_back_to_the_same_server(self):
        sp = launcher.again_spec(self.inst(LaunchSpec(kind="Job", place_id=7, job_id="j")))
        self.assertEqual((sp.kind, sp.job_id), ("Job", "j"))

    def test_nothing_known_uses_the_place_from_its_log(self):
        sp = launcher.again_spec(self.inst(LaunchSpec(), place=99))
        self.assertEqual((sp.kind, sp.place_id), ("Game", 99))

if __name__ == "__main__":
    unittest.main()


class WatcherRecovery(unittest.TestCase):
    def setUp(self):
        self.L = launcher.Launcher()
        self.inst = launcher.Instance(account=Account(username='test'), spec=LaunchSpec(place_id=123))
        self.L.instances.append(self.inst)
        for patch in (mock.patch.object(self.L, 'is_alive', return_value=False),
                      mock.patch.object(self.L, '_remove', side_effect=lambda i: self.L.instances.remove(i)),
                      mock.patch.object(launcher.sober, 'scan', return_value=[]),
                      mock.patch.object(launcher.time, 'sleep'),
                      mock.patch.object(store.settings, 'auto_relaunch', True),
                      mock.patch.object(store.settings, 'watcher_use_presence', False),
                      mock.patch.object(store.settings, 'low_ram_close_mb', 0),
                      mock.patch.object(store.settings, 'webhook_crash', False),
                      mock.patch.object(store.settings, 'webhook_relaunch', True)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_failed_relaunch_does_not_announce_success(self):
        with mock.patch.object(launcher.api, 'internet_ok', return_value=True), \
                mock.patch.object(self.L, 'launch', return_value=False), \
                mock.patch.object(launcher.webhook, 'send') as send:
            self.L.watcher_tick(lambda _: None, lambda: None)
        self.assertFalse(any(c.args[0] == 'Client relaunched' for c in send.call_args_list))

    def test_stop_during_connectivity_check_prevents_relaunch(self):
        def connected():
            self.inst.user_closed = True
            return True
        with mock.patch.object(launcher.api, 'internet_ok', side_effect=connected), \
                mock.patch.object(self.L, 'launch') as launch:
            self.L.watcher_tick(lambda _: None, lambda: None)
        launch.assert_not_called()
