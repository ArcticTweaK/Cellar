"""Launching Sober clients and keeping them alive (port of Launcher.cs).

All methods here block - call them from a worker thread, never from the UI thread.
"""

import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import api, background, gfx, log, macros, paths, robloxlog, sober, store, util, webhook
from .models import Account, Instance, LaunchSpec

LogF = Callable[[str], None]


@dataclass
class _Breaker:
    count: int = 0
    window_start: float = 0.0
    gave_up: bool = False
    gave_up_at: float = 0.0


def _running_screen(a: Account):
    """The invisible screen of a background client still running from before (re)start - under
    Cellar's name or, for clients started before the rename, Roblox MultiHub's."""
    for prefix in (sober.PREFIX, sober.OLD_PREFIX):
        s = background.find_running(sober.runtime_dir_path(a, prefix))
        if s:
            return s
    return None


class Launcher:
    def __init__(self):
        self.instances: List[Instance] = []
        self.lock = threading.RLock()
        self._breaker: Dict[str, _Breaker] = {}
        self._account_locks: Dict[str, threading.Lock] = {}
        self.logs = robloxlog.Watcher()
        self._pulse: Optional[threading.Thread] = None
        # the UI sets this: notify(kind, instance, text) for desktop notifications (called on worker threads)
        self.notify: Callable[[str, Instance, str], None] = lambda kind, inst, text: None
        self.on_join: Callable[[Instance, int, str], None] = lambda inst, place_id, job: None   # UI: recent/history

    # ------------------------------------------------------------ bookkeeping
    def snapshot(self) -> List[Instance]:
        with self.lock:
            return list(self.instances)

    def instances_of(self, a: Account) -> List[Instance]:
        with self.lock:
            return [i for i in self.instances if i.account is a or i.account.id == a.id]

    def find_by_pid(self, pid: int) -> Optional[Instance]:
        with self.lock:
            return next((i for i in self.instances if i.pid == pid and pid), None)

    def find_by_tracker(self, tracker: int) -> Optional[Instance]:
        with self.lock:
            return next((i for i in self.instances if i.tracker == tracker and tracker), None)

    def is_alive(self, inst: Instance, procs=None) -> bool:
        if inst.pid and sober.alive(inst.pid, inst.tracker):
            return True
        wp = sober.window_pid(inst.tracker, procs)
        if wp:
            inst.pid = wp
            return True
        if time.time() - inst.started < 120 and sober.client_starting(inst.tracker, procs):
            return True
        # still starting up?
        if inst.launch_pid and time.time() - inst.started < 90:
            try:
                with open(f"/proc/{inst.launch_pid}/stat") as f:
                    return ") Z" not in f.read()
            except OSError:
                return False
        return False

    def alive_instances(self) -> List[Instance]:
        procs = sober.scan()
        return [i for i in self.snapshot() if self.is_alive(i, procs)]

    def running(self, a: Account) -> bool:
        return any(self.is_alive(i) for i in self.instances_of(a))

    def _remove(self, inst: Instance) -> None:
        with self.lock:
            if inst in self.instances:
                self.instances.remove(inst)
        self._release(inst)

    @staticmethod
    def _release(inst: Instance) -> None:
        """A client is gone: stop its macro and its invisible screen."""
        if inst.macro:
            inst.macro.stop()
            inst.macro = None
        if inst.screen:
            background.stop(inst.screen)
            inst.screen = None

    # ------------------------------------------------------------ macros (background clients)
    def start_macro(self, inst: Instance, name: str, logf: LogF) -> bool:
        m = next((m for m in store.settings.macros if m.name == name), None)
        if m is None:
            logf(f"[{inst.account.name}] no macro called '{name}'.")
            return False
        return self.start_macro_text(inst, m.name, m.text, m.loop, logf)

    def start_macro_text(self, inst: Instance, name: str, text: str, loop: bool, logf: LogF) -> bool:
        """Also used by the Macros page's Run once (the text as typed, saved or not)."""
        who = inst.account.name
        if not inst.screen:
            logf(f"[{who}] macros need background mode (Edit account > Run in the background), then relaunch it.")
            return False
        self.stop_macro(inst)
        try:
            inst.macro = macros.Runner(inst.screen, name, text, loop, logf, who).start()
        except ValueError as ex:
            logf(f"[{who}] macro '{name}' has mistakes: {ex}")
            return False
        logf(f"[{who}] running macro '{name}'" + (" (loops until you stop it)." if loop else " (once)."))
        return True

    @staticmethod
    def stop_macro(inst: Instance) -> bool:
        if inst.macro and inst.macro.running:
            inst.macro.stop()
            inst.macro = None
            return True
        inst.macro = None
        return False

    # ------------------------------------------------------------ crash breaker
    def _b(self, a: Account) -> _Breaker:
        b = self._breaker.get(a.id)
        if b is None:
            b = self._breaker[a.id] = _Breaker(window_start=time.time())
        return b

    def breaker_allows(self, a: Account) -> bool:
        s = store.settings
        if not s.crash_breaker:
            return True
        b = self._b(a)
        if b.gave_up:
            if time.time() - b.gave_up_at >= max(1, s.crash_breaker_cooldown_min) * 60:
                b.gave_up, b.count, b.window_start = False, 0, time.time()
                return True
            return False
        return True

    def breaker_record(self, a: Account) -> bool:
        s = store.settings
        if not s.crash_breaker:
            return False
        b = self._b(a)
        if time.time() - b.window_start > max(1, s.crash_breaker_window_min) * 60:
            b.window_start, b.count = time.time(), 0
        b.count += 1
        if b.count >= max(1, s.crash_breaker_max):
            b.gave_up, b.gave_up_at = True, time.time()
            return True
        return False

    def breaker_clear(self, a: Account) -> None:
        self._breaker.pop(a.id, None)

    # ------------------------------------------------------------ stopping
    def stop_instance(self, inst: Instance, logf: Optional[LogF] = None) -> None:
        inst.user_closed = True
        if inst.frozen and inst.pid:            # a frozen process cannot react to a polite "please quit"
            inst.frozen = False
            sober.freeze(inst.pid, False)
        n = sober.stop(inst.launch_pid, inst.tracker, unit=inst.unit)
        self._remove(inst)
        if logf and n:
            logf(f"[{inst.account.name}] closed its Sober window.")

    def stop_account(self, a: Account, logf: Optional[LogF] = None) -> None:
        for i in self.instances_of(a):
            self.stop_instance(i, logf)
        # a client of this account that survived an app restart
        if a.tracker_id and sober.window_pid(a.tracker_id):
            sober.stop(0, a.tracker_id)
        if a.background:
            background.stop(_running_screen(a))

    def stop_all(self, logf: Optional[LogF] = None) -> int:
        insts = self.snapshot()
        for i in insts:
            self.stop_instance(i, None)
        if logf:
            logf(f"Stopped {len(insts)} Sober window(s) started by this app." if insts
                 else "No Sober windows started by this app are running.")
        return len(insts)

    def adopt_running(self, logf: Optional[LogF] = None) -> int:
        """Re-attaches clients this app started before it was restarted (found by tracker id)."""
        n = 0
        for tracker, pid in sober.all_sober_trackers().items():
            a = store.find_by_tracker(tracker)
            if a is None or self.find_by_tracker(tracker):
                continue
            inst = Instance(account=a, tracker=tracker, launch_pid=0, pid=pid, started=time.time() - 300,
                            spec=LaunchSpec(), isolated=True)
            if a.background:
                inst.screen = _running_screen(a)
            with self.lock:
                self.instances.append(inst)
            n += 1
        if n and logf:
            logf(f"Found {n} Sober window(s) from an earlier session and took them over.")
        return n

    # ------------------------------------------------------------ launching
    @staticmethod
    def _random_tracker() -> int:
        # same shape as Roblox Account Manager: 6 digits (100000-174999) + 6 digits (100000-899999)
        return int(f"{random.randint(100000, 174999)}{random.randint(100000, 899999)}")

    def launch(self, a: Account, spec: LaunchSpec, logf: LogF) -> bool:
        lock = self._account_locks.setdefault(a.id, threading.Lock())
        if not lock.acquire(blocking=False):
            logf(f"[{a.name}] is already being launched.")
            return False
        try:
            return self._launch(a, spec, logf)
        except Exception as ex:
            log.error("launch", ex)
            logf(f"[{a.name}] unexpected error: {ex}")
            return False
        finally:
            lock.release()

    def _launch(self, a: Account, spec: LaunchSpec, logf: LogF) -> bool:
        s = store.settings
        who = f"[{a.name}] "
        if not a.cookie:
            logf(who + "has no cookie saved.")
            return False
        if not sober.sober_installed():
            logf("Sober is not installed. Install it with:  flatpak install flathub org.vinegarhq.Sober")
            return False

        isolated = s.multi_instance
        if isolated:
            ok, why = sober.multi_instance_support()
            if not ok:
                logf(who + f"multi-instance is not available ({why}) - using your normal Sober (one window at a time).")
                isolated = False

        alive = self.alive_instances()
        if s.max_instances > 0 and len([i for i in alive if i.account.id != a.id]) >= s.max_instances:
            logf(who + f"not launched: Max instances ({s.max_instances}) reached. Close one or raise the limit in Settings.")
            return False

        if s.refresh_cookie_on_launch:
            nc = api.rotate_cookie(a.cookie, lambda m: logf(who + m))
            if nc:
                a.cookie = nc
                store.save_accounts()
                logf(who + "cookie refreshed.")

        logf(who + "requesting login ticket...")
        t = api.get_ticket(a.cookie)
        li = store.live(a)
        if not t.ticket:
            logf(who + "failed: " + t.error)
            if t.unauthorized:
                li.cookie_bad = True
            if t.locked:
                if not li.locked_alerted and s.webhook_locked:
                    webhook.send("Account locked", f"{a.name} — Roblox returned HTTP 403 (locked / blocked). Unlock it on roblox.com.", webhook.RED)
                    li.locked_alerted = True
                li.locked = True
                logf(who + "this account looks LOCKED / blocked by Roblox (HTTP 403). Unlock it on roblox.com.")
            return False
        li.cookie_bad = li.locked = li.locked_alerted = False

        # One client per account: its profile cannot run twice.
        mine = [i for i in alive if i.account.id == a.id]
        if mine:
            if isolated or s.auto_close_last:
                for i in mine:
                    self.stop_instance(i, None)
                    logf(who + "closed its previous Sober window.")
            else:
                logf(who + "is already running (turn on 'close previous window' in Settings to replace it).")
                return False
        if not isolated:
            # Sober allows exactly one copy without the multi-instance isolation.
            for i in [i for i in alive if i.account.id != a.id]:
                self.stop_instance(i, None)
                logf(f"[{i.account.name}] closed (without multi-instance only one Sober can run).")
            known = [i.tracker for i in self.snapshot()]
            if sober.sober_running_unmanaged(known):
                logf(who + "your normal Sober window is open. Close it first - without multi-instance only one Sober can run.")
                return False
        elif a.tracker_id and sober.window_pid(a.tracker_id):
            sober.stop(0, a.tracker_id)            # leftover from an earlier session

        if not a.tracker_id:
            a.tracker_id = self._random_tracker()
            store.save_accounts()

        if isolated:
            sober.ensure_profile(a, s, logf)
            flags, ignored = gfx.final(s, a.full_quality, a.gfx_preset)
            sober.write_profile_settings(a, s, flags, logf)

        screen = None
        if a.background and not isolated:
            logf(who + "background mode needs multi-instance (Settings) - it opens as a normal window.")
        elif a.background:
            try:
                screen = background.start(sober.runtime_dir_for(a), lambda m: logf(who + m))
            except Exception as ex:
                logf(who + f"could not start its invisible screen ({ex}) - it opens as a normal window.")

        url = sober.place_launcher_url(s, spec, a.tracker_id)
        uri = sober.build_uri(t.ticket, util.now_ms(), url, a.tracker_id)
        argv, env, unit = sober.build_command(uri, a, isolated, background.LINK if screen else None)
        log_file = (sober.profile_home(a) if isolated else paths.DATA_DIR) / "sober-output.log"
        try:
            proc = sober.spawn(argv, env, log_file)
        except Exception as ex:
            background.stop(screen)
            logf(who + f"could not start Sober: {ex}")
            return False

        inst = Instance(account=a, tracker=a.tracker_id, launch_pid=proc.pid, started=time.time(),
                        spec=spec.copy(), isolated=isolated, unit=unit, screen=screen)
        with self.lock:
            self.instances.append(inst)
        logf(who + f"Sober is starting ({spec.describe()})" + (" in its own isolated profile..." if isolated else "..."))

        for _ in range(180):                        # up to 90 s
            time.sleep(0.5)
            wp = sober.window_pid(a.tracker_id)
            if wp:
                inst.pid = wp
                break
            if proc.poll() is not None:
                tail = _tail(log_file)
                self._remove(inst)
                if "already running" in tail.lower():
                    logf(who + "Sober refused: another Sober is already running." +
                         ("" if isolated else " Turn on multi-instance (Settings) or close the other Sober."))
                else:
                    logf(who + f"Sober exited right away (code {proc.returncode}). Last output: {util.trunc(tail, 300)}")
                return False

        threading.Thread(target=proc.wait, daemon=True).start()     # reap later, no zombie
        a.last_used = time.time()
        store.save_accounts()
        if not inst.pid:
            logf(who + f"Sober did not show up within 90 s. Details: {log_file}")
            self._release(inst)
            return False
        if screen and a.auto_macro:
            # give the game time to load in before the first input
            def later():
                time.sleep(25)
                if inst in self.snapshot() and not inst.macro:
                    self.start_macro(inst, a.auto_macro, logf)
            threading.Thread(target=later, daemon=True).start()
        if s.priority != "Normal" or s.ram_cap_mb > 0:
            err = sober.apply_limits(inst.pid, s.priority, s.ram_cap_mb)
            if err:
                logf(who + f"could not apply CPU priority / RAM cap: {err}")
        logf(who + f"started (PID {inst.pid})" +
             (" on its invisible screen - right-click it > View screen." if screen else "."))
        return True

    def freeze(self, inst: Instance, on: bool, logf: LogF) -> bool:
        who = f"[{inst.account.name}]"
        if not inst.pid:
            logf(f"{who} its window is not up yet - try again in a moment.")
            return False
        if on and inst.macro:
            self.stop_macro(inst)
        err = sober.freeze(inst.pid, on)
        if err:
            logf(f"{who} could not {'freeze' if on else 'resume'} it: {err}")
            return False
        inst.frozen = on
        inst.strikes = 0
        if not on:
            logf(f"{who} resumed.")
        elif store.settings.freeze_keep_connected:
            logf(f"{who} frozen - it wakes for a moment every {store.settings.freeze_wake_every_sec} s to stay "
                 "connected, and uses almost no CPU otherwise.")
            self._start_pulse()
        else:
            logf(f"{who} frozen solid - no CPU at all, but Roblox drops it from the server after a while.")
        return True

    def _start_pulse(self) -> None:
        if self._pulse is None or not self._pulse.is_alive():
            self._pulse = threading.Thread(target=self._pulse_loop, daemon=True, name="freeze pulse")
            self._pulse.start()

    def _pulse_loop(self) -> None:
        """While any client is frozen with 'stay connected': thaw it briefly every few seconds. Awake, it sends the
        game server its heartbeat and acks and works through what queued up; frozen again it takes no CPU. All
        frozen clients wake together, so this costs one short burst per cycle."""
        while True:
            s = store.settings
            time.sleep(max(3, s.freeze_wake_every_sec))
            insts = [i for i in self.snapshot() if i.frozen and i.pid and not i.user_closed]
            if not insts:
                return
            if not s.freeze_keep_connected:
                continue
            woke = [i for i in insts if not sober.freeze(i.pid, False)]
            time.sleep(max(200, s.freeze_wake_ms) / 1000)
            for i in woke:
                if i.frozen:                    # still meant to be frozen (not resumed / stopped meanwhile)
                    sober.freeze(i.pid, True)

    # ------------------------------------------------------------ Roblox log (joins, kicks)
    def log_tick(self, logf: LogF) -> None:
        """Every few seconds on a worker: reads each client's Roblox log. Kicks and lost connections are
        noticed within seconds (the presence watcher needs minutes) and can rejoin right away."""
        alive = [i for i in self.alive_instances() if not i.user_closed]
        items = {}
        for i in alive:
            app = sober.profile_app(i.account) if i.isolated else sober.main_app()
            items[i.tracker] = (robloxlog.logs_folder(app), i.started)
        events = self.logs.poll(items)
        s = store.settings
        for i in alive:
            for ev in events.get(i.tracker, []):
                who = f"[{i.account.name}]"
                if ev.kind == "joined":
                    first = not i.place_id
                    if ev.job_id != i.job_id:
                        self.on_join(i, ev.place_id, ev.job_id)
                    i.place_id, i.job_id = ev.place_id, ev.job_id
                    if not first:
                        logf(f"{who} joined another server (place {ev.place_id}).")
                elif ev.kind == "disconnected":
                    text = f"{who} {ev.describe()}."
                    self.notify("kick", i, f"{i.account.name}: {ev.describe()}")
                    if s.webhook_crash:
                        webhook.send("Disconnected", f"{i.account.name} — {ev.describe()}.", webhook.RED)
                    if not s.rejoin_on_kick:
                        logf(text + " (Turn on 'Rejoin when kicked' in Settings to bring it back by itself.)")
                        continue
                    if not self.breaker_allows(i.account):
                        logf(text + " The crash breaker paused rejoining it - launch it yourself to try again.")
                        continue
                    # lost connection: the same server; kicked: the server may refuse it, so the original target
                    same = ev.reason in (0, 277, 279) and ev.job_id and ev.place_id
                    spec = (LaunchSpec(kind="Job", place_id=ev.place_id, job_id=ev.job_id) if same
                            else (i.spec if i.spec and (i.spec.place_id or i.spec.follow_user_id) else LaunchSpec()))
                    logf(text + (" Rejoining the same server..." if same else " Rejoining..."))
                    self.breaker_record(i.account)
                    self.stop_instance(i)           # user_closed: the watcher must not relaunch it a second time
                    time.sleep(2)
                    self.launch(i.account, spec, logf)
                    if s.webhook_relaunch:
                        webhook.send("Client rejoined", f"{i.account.name} rejoined after: {ev.describe()}.",
                                     webhook.YELLOW)

    def apply_limits_all(self, logf: LogF) -> int:
        s = store.settings
        n = 0
        for i in self.alive_instances():
            if i.pid and not sober.apply_limits(i.pid, s.priority, s.ram_cap_mb):
                n += 1
        logf(f"CPU priority '{s.priority}'" + (f" and RAM cap {s.ram_cap_mb} MB" if s.ram_cap_mb > 0 else "")
             + f" applied to {n} window(s).")
        return n

    # ------------------------------------------------------------ watcher
    def low_ram_tick(self, logf: LogF) -> None:
        """Setting low_ram_close_mb: when free RAM falls below it, the most recently started alt is closed (never
        an account marked Full quality, i.e. your main) - before the kernel's OOM killer picks something itself."""
        from .usage import mem_available
        need = store.settings.low_ram_close_mb
        free = mem_available()
        if need <= 0 or not free or free >= need * 2**20:
            return
        alts = sorted((i for i in self.alive_instances() if not i.account.full_quality), key=lambda i: i.started)
        if not alts:
            return
        i = alts[-1]
        logf(f"[{i.account.name}] closed to free memory: only {free // 2**20} MB was free (the setting keeps "
             f"{need} MB free).")
        self.notify("crash", i, f"{i.account.name} was closed because memory ran low.")
        self.stop_instance(i)

    def watcher_tick(self, logf: LogF, cookie_for_presence: Callable[[], Optional[str]]) -> None:
        s = store.settings
        self.low_ram_tick(logf)
        procs = sober.scan()
        dead = [i for i in self.snapshot() if not i.user_closed and not self.is_alive(i, procs)]
        for d in dead:
            # A dead client stays in the list while the internet is down (relaunching needs it), so the watcher sees
            # it again every tick: report it once.
            if not d.reported:
                d.reported = True
                self.notify("crash", d, f"{d.account.name}'s Roblox window closed unexpectedly.")
                if s.webhook_crash:
                    webhook.send("Client closed", f"{d.account.name} — its Sober window disappeared unexpectedly.",
                                 webhook.RED)
        if not s.auto_relaunch:
            for d in dead:
                self._remove(d)
            return

        if s.watcher_use_presence:
            for i in self.snapshot():
                if (i.user_closed or i in dead or i.frozen or i.account.user_id <= 0
                        or time.time() - i.started < 150):
                    continue
                pr = api.presence(i.account.cookie, [i.account.user_id]).get(i.account.user_id)
                if pr is None:
                    continue
                if pr.type == 2:
                    i.strikes = 0
                    continue
                i.strikes += 1
                if i.strikes >= 2:
                    logf(f"Watcher: {i.account.name} is not in a game anymore - closing and relaunching.")
                    sober.stop(i.launch_pid, i.tracker, unit=i.unit)
                    dead.append(i)

        if not dead:
            return
        if not api.internet_ok():
            if not all(d.offline_logged for d in dead):
                logf("Watcher: no internet connection - closed clients are relaunched once it is back.")
                for d in dead:
                    d.offline_logged = True
            return
        for d in dead:
            self._remove(d)
            if not self.breaker_allows(d.account):
                logf(f"Watcher: {d.account.name} keeps crashing - the crash breaker stopped relaunching it. Launch it yourself to try again.")
                continue
            logf(f"Watcher: relaunching {d.account.name}...")
            self.launch(d.account, d.spec if d.spec and (d.spec.place_id or d.spec.follow_user_id) else LaunchSpec(), logf)
            gave_up = self.breaker_record(d.account)
            if s.webhook_relaunch:
                webhook.send("Client relaunched", f"{d.account.name} was brought back by the watcher.", webhook.YELLOW)
            if gave_up:
                mins = max(1, s.crash_breaker_cooldown_min)
                logf(f"Watcher: {d.account.name} has crashed too often - the crash breaker pauses relaunching for {mins} min.")
                if s.webhook_crash:
                    webhook.send("Crash breaker", f"{d.account.name} crashed too many times - auto-relaunch paused for {mins} min.", webhook.RED)
            time.sleep(max(1, s.launch_delay_sec))


def _tail(path, n: int = 4000) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n))
            lines = [l for l in f.read().decode(errors="replace").splitlines() if l.strip()]
            return " | ".join(lines[-6:])
    except OSError:
        return ""
