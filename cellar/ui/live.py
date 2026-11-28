"""MainWindow part: What runs by itself: timers (status, usage, presence, watcher, Roblox logs), notifications, screens, updates.

A mixin of ui.main_window.MainWindow - `self` is the main window."""

import os
import subprocess
import time
from typing import List, Optional

import shiboken6
from PySide6.QtWidgets import QSystemTrayIcon

from .. import (APP_ID, APP_NAME, __version__, antiafk, api, background, log, sessions, sober, store, theme,
               updates, usage)
from ..models import Instance, LaunchSpec
from .common import bg, info, warn
from .dialogs import ReleaseNotesDialog
from .screen_viewer import ScreenViewer, ScreenWall
from .widgets import Toast, _size


class LiveMixin:
    def update_running(self) -> List[Instance]:
        alive = self.launcher.alive_instances()
        self.model.running = {i.account.id for i in alive}
        if sessions.close_missing(store.settings.history, self.model.running):     # its window is gone
            store.save_settings()
        self.model.frozen = {i.account.id for i in alive if i.frozen}
        self.model.macro = {i.account.id for i in alive if i.macro and i.macro.running}
        self.model.refresh_status()
        self.refresh_launch_action()
        self.autohide_columns()
        self.update_header(alive)
        return alive

    def update_header(self, alive: Optional[List[Instance]] = None):
        s = store.settings
        ok, why = sober.multi_instance_support()
        sub = []
        if not sober.sober_installed():
            state, text = "bad", "Sober is not installed"
        elif s.multi_instance and ok:
            state, text = "good", "●  Multi-instance on"
        elif s.multi_instance:
            state, text = "warn", "Multi-instance unavailable"
            sub.append(why)
        else:
            state, text = "off", "Multi-instance off"
            sub.append("one Sober at a time")
        if self.kwin is None or not self.kwin.available():
            sub.append("window layout off (needs KDE Plasma, Hyprland or Sway)")
        if self.st_multi.property("state") != state:
            self.st_multi.setProperty("state", state)
            theme.repolish(self.st_multi)
        self.st_multi.setText(text)
        if not sub and self.versions:
            sub.append(self.versions)
        self.st_multi.setToolTip("Multi-instance gives every account its own isolated Sober, so many can run at "
                                 "once (Settings)." + ("\n\n" + "\n".join(sub) if sub else ""))
        if alive is None:
            alive = self.launcher.alive_instances()
        n = len({i.account.id for i in alive})        # accounts, not records
        in_bg = len({i.account.id for i in alive if i.screen})
        self.stat_run.set(f"{n} / {len(store.accounts)}",
                          "nothing running" if not n else f"{in_bg} in the background" if in_bg else "in windows")
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME} - {n} running")

    def update_usage(self, alive: List[Instance]):
        if not usage.available():
            self.stat_cpu.set("-", "needs cgroup v2")
            self.stat_mem.set("-", "needs cgroup v2")
            return
        res = self.sampler.sample_each({i.account.id: usage.groups_for([i]) for i in alive})
        cores, mem = res.pop("")
        if cores is not None:                       # the Performance tab > Last hour
            now = time.time()
            self.perf_page.g_cpu.add(now, cores / (os.cpu_count() or 1) * 100)
            self.perf_page.g_mem.add(now, mem)
        self.model.usage = res
        alts = [m for i in alive if not i.account.full_quality and (m := res.get(i.account.id, (0, 0))[1]) > 2**28]
        if self.perf_page.isVisible():
            self.perf_page.update_fit(sum(alts) // len(alts) if alts else 2**30, bool(alts))
        ncpu = os.cpu_count() or 1
        if cores is None:
            self.stat_cpu.set("...", "measuring")
        else:
            self.stat_cpu.set(f"{cores / ncpu * 100:.0f}%", f"{cores:.1f} of {ncpu} cores")
        self.stat_mem.set(_size(mem), f"about {_size(mem / len(alive))} each" if alive else "")

    def tick(self):
        alive = self.update_running()
        if self.isVisible() or alive:       # keep the Last hour graphs going while Cellar sits in the tray
            self.update_usage(alive)
        try:
            self.windows_page.auto_tick()
            if self.windows_page.isVisible():
                self.windows_page.refresh()
        except Exception as ex:
            log.error("tick", ex)

    def presence_tick(self):
        if self._presence_busy or not store.settings.show_presence:
            return
        ids = [a.user_id for a in store.accounts if a.user_id]
        cookie = self.any_cookie()
        if not ids or not cookie:
            return
        self._presence_busy = True

        def done(res):
            self._presence_busy = False
            for a in store.accounts:
                p = res.get(a.user_id)
                if p:
                    li = store.live(a)
                    li.presence_type, li.where = p.type, p.location
            self.model.refresh_status()
        bg(api.presence, cookie, ids, done=done, err=lambda _: setattr(self, "_presence_busy", False))

    def watcher_tick(self):
        if self._watcher_busy or self.launching:
            return
        if not self.launcher.snapshot():
            return
        self._watcher_busy = True

        def fin(_=None):
            self._watcher_busy = False
            self.update_running()
        bg(self.launcher.watcher_tick, self.log, self.any_cookie, done=fin, err=fin)

    def view_screen(self, inst: Instance):
        v = self.viewers.get(inst.account.id)
        if v and shiboken6.isValid(v) and v.isVisible() and v.inst is inst:
            v.raise_()
            v.activateWindow()
            return
        v = ScreenViewer(self, inst, self.log, lambda: self.macros_page.load())
        v.setWindowIcon(self.model.icon_for(inst.account))     # its headshot in the title bar / task bar
        self.viewers[inst.account.id] = v
        v.show()

    def log_tick(self):
        if self._logs_busy or not self.model.running:
            return
        self._logs_busy = True

        def fin(_=None):
            self._logs_busy = False
            self.update_running()
        bg(self.launcher.log_tick, self.log, done=fin, err=fin)

    def desktop_notify(self, kind: str, text: str):
        """kind: kick | crash | login | done. While you are looking at Cellar it shows an in-app toast; otherwise a
        desktop notification (each kind can be turned off in Settings > Desktop notifications)."""
        if self.isVisible() and self.isActiveWindow():
            self.toast(text, {"done": "good", "login": "warn"}.get(kind, "bad"))
            return
        s = store.settings
        on = {"kick": s.notify_kick, "crash": s.notify_crash, "login": s.notify_login_lost,
              "done": s.notify_launch_done}.get(kind, True)
        if not (s.notify and on):
            return
        if self.tray is not None and self.tray.isVisible():
            icon = QSystemTrayIcon.Information if kind == "done" else QSystemTrayIcon.Warning
            self.tray.showMessage(APP_NAME, text, icon, 10000)
        else:
            exe = sober.which("notify-send")
            if exe:
                subprocess.Popen([exe, "-a", APP_NAME, "-i", APP_ID, APP_NAME, text], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)

    def friends_tick(self):
        """Every minute (setting notify_friends): friends of the main account who came online or started a game.
        The first check only remembers who is where, so turning it on does not announce everyone at once."""
        a = self.main_account()
        if not store.settings.notify_friends or not a or getattr(self, "_friends_busy", False):
            return
        self._friends_busy = True
        st = getattr(self, "_friends", None)
        if st is None or st.get("account") != a.id:
            st = self._friends = {"account": a.id, "names": {}, "listed": 0.0, "seen": None}

        def work():
            if time.time() - st["listed"] > 1800 or not st["names"]:        # the friend list itself: every 30 min
                fr, err = api.friends(a.cookie, a.user_id)
                if not err:
                    st["names"] = {f.user_id: f.display_name or f.name for f in fr}
                    st["listed"] = time.time()
            return api.presence(a.cookie, list(st["names"])) if st["names"] else {}

        def done(pres):
            self._friends_busy = False
            now = {uid: (p.type, p.place_id, p.location) for uid, p in (pres or {}).items()}
            before, st["seen"] = st["seen"], now
            if before is None or not now:
                return
            news = []
            for uid, (typ, place, where) in now.items():
                old = before.get(uid, (0, 0, ""))
                if typ == 2 and (old[0] != 2 or old[1] != place):
                    news.append((uid, f"{st['names'].get(uid, 'A friend')} started playing {where or 'a game'}.", True))
                elif typ == 1 and old[0] == 0:
                    news.append((uid, f"{st['names'].get(uid, 'A friend')} is online.", False))
            for uid, text, joinable in news[:3]:
                spec = LaunchSpec(kind="Follow", follow_user_id=uid, follow_name=st["names"].get(uid, ""))
                who = self.selected_accounts() or [a]
                act = ("Join", lambda spec=spec, who=who: self.start_launch(who, fixed=spec, allow_saved=False))
                if self.isVisible() and self.isActiveWindow():
                    self.toast(text, "info", act if joinable else None)
                elif store.settings.notify and self.tray is not None:
                    self.tray.showMessage(APP_NAME, text, QSystemTrayIcon.Information, 8000)
            if len(news) > 3:
                self.toast(f"...and {len(news) - 3} more friends came online or started a game.", "info")
        bg(work, done=done, err=lambda _: setattr(self, "_friends_busy", False))

    def audio_tick(self):
        """Every few seconds while clients run: each account's sound (Mute alts / its own volume)."""
        from .. import audio
        if getattr(self, "_audio_busy", False) or not self.model.running:
            return
        s = store.settings
        targets = {}
        for i in self.launcher.alive_instances():
            a = i.account
            vol = a.volume if a.volume >= 0 else (0 if s.mute_alts and not a.full_quality else 100)
            if i.pid and (vol != 100 or a.volume >= 0 or s.mute_alts):
                cg = usage.cgroup_of(i.pid)
                if cg:
                    targets[cg] = (vol == 0, vol / 100)
        if not targets:
            return
        self._audio_busy = True

        def fin(_=None):
            self._audio_busy = False
        bg(audio.apply, targets, done=fin, err=fin)

    def set_volume(self, accs, volume: int):
        for a in accs:
            a.volume = volume
        store.save_accounts()
        self.audio_tick()
        self.log(("Muted " if volume == 0 else "Unmuted " if volume == 100 else f"Volume {volume}% for ")
                 + ", ".join(a.name for a in accs[:4]) + (" ..." if len(accs) > 4 else "") + ".")

    def schedule_tick(self):
        """Every 30 s: scheduled presets that are due (schedule.py decides)."""
        from .. import schedule
        fired = schedule.due(store.settings.schedules)
        if not fired:
            return
        for sc, kind in fired:
            p = self.presets_page.find(sc.preset)
            if p is None:
                self.log(f"Schedule: there is no preset called '{sc.preset}' any more.")
                continue
            if kind == "start":
                if self.launching:              # try again on the next tick (still inside the grace time)
                    sc.last_start = ""
                    continue
                self.log(f"Schedule: running preset '{p.name}' ({sc.start}).")
                self.presets_page.run(p)
            else:
                ids = {e.account_id for e in p.entries}
                accs = [a for a in store.accounts if a.id in ids]

                def stop(accs=accs):            # on a worker: closing waits up to 3 s per client
                    run = [a for a in accs if self.launcher.running(a)]
                    for a in run:
                        self.launcher.stop_account(a, self.log)
                    return len(run)

                def done(n, p=p, sc=sc):
                    self.log(f"Schedule: stopped preset '{p.name}' ({sc.stop}) - {n} account(s) closed.")
                    self.desktop_notify("done", f"Schedule: stopped '{p.name}' ({n} account(s)).")
                    self.update_running()
                bg(stop, done=done)
        store.save_settings()

    def toast(self, text: str, kind: str = "info", action=None):
        """In-app message, bottom right. kind: info | good | warn | bad. action = (button text, function)."""
        self._toasts = [t for t in getattr(self, "_toasts", []) if shiboken6.isValid(t) and t.isVisible()]
        while len(self._toasts) >= 4:
            self._toasts.pop(0).close_now()
        self._toasts.append(Toast(self, text, kind, action))
        self._layout_toasts()

    def _layout_toasts(self):
        live = [t for t in getattr(self, "_toasts", []) if shiboken6.isValid(t) and t.isVisible()]
        self._toasts = live
        y = self.height() - 40                  # above the status line
        for t in reversed(live):
            t.adjustSize()
            y -= t.height()
            t.move(self.width() - t.width() - 22, y)
            t.raise_()
            y -= 8

    def open_screen_wall(self):
        w = getattr(self, "_wall", None)
        if w is not None and shiboken6.isValid(w) and w.isVisible():
            w.raise_()
            w.activateWindow()
            return
        self._wall = ScreenWall(self)
        self._wall.show()

    def anti_afk_now(self):
        # background accounts: straight over their own screen - no focus change, works without window control
        bg_insts = [i for i in self.launcher.alive_instances() if i.screen and not i.frozen]
        if bg_insts:
            act = store.settings.anti_afk_action
            bg(lambda: sum(background.poke(i.screen, act) for i in bg_insts if not i.macro),
               done=lambda n: n and self.log(f"Anti-AFK: poked {n} background account(s)."))
        if not self.kwin or not self.kwin.available():
            if bg_insts:
                return
            self.log("Anti-AFK for normal windows needs KDE Plasma, Hyprland or Sway to focus them.")
            return
        ours = {i.tracker for i in self.launcher.alive_instances() if not i.frozen}
        ids = [w.id for w in self.kwin.windows() if sober.tracker_of_pid(w.pid) in ours]
        if not ids:
            return
        n = antiafk.pulse(self.kwin, ids, self.log)
        if n:
            self.log(f"Anti-AFK: poked {n} window(s).")

    def check_updates(self, manual: bool = False):
        s = store.settings
        if not manual and (not s.check_updates or not updates.due(s.last_update_check)):
            return

        def done(rel):
            s.last_update_check = time.time()
            store.save_settings()
            self.new_release = rel
            if rel:
                self.update_btn.setText(f"New version {rel.version}")
                self.update_btn.setVisible(True)
                self.log(f"Cellar {rel.version} is out (you have {__version__}) - press 'New version' at the top.")
            elif manual:
                info(self, "Updates", f"You have the newest version ({__version__}).")
        bg(updates.newer, done=done, err=(lambda ex: warn(self, "Updates", f"Could not reach GitHub: {ex}"))
           if manual else None)

    def show_update(self):
        rel = self.new_release
        if rel:
            ReleaseNotesDialog(self, f"Cellar {rel.version} is out", rel.notes, rel.url,
                               f"You have {__version__}. " + updates.how_to_update()).exec()

    def whats_new(self):
        """Once after an update: the release notes of the version now running."""
        s = store.settings
        before, s.last_seen_version = s.last_seen_version, __version__
        store.save_settings()
        if not before or updates.vtuple(__version__) <= updates.vtuple(before):
            return
        bg(updates.notes_for, __version__,
           done=lambda rel: rel and rel.notes and ReleaseNotesDialog(
               self, f"What's new in Cellar {__version__}", rel.notes, rel.url).exec())

    def refresh_versions(self):
        def work():
            sv = sober.sober_version() if sober.sober_installed() else ""
            rv = sober.app_version(sober.main_app())
            upd = bool(sv) and sober.sober_update_available()
            return " · ".join(x for x in (f"Sober {sv}" if sv else "", f"Roblox {rv}" if rv else "") if x), upd

        def done(res):
            self.versions, upd = res
            if upd:
                self.versions += " · Sober update ready"
                self.log("A new Sober version is ready. Update it with:  flatpak update org.vinegarhq.Sober  "
                         "(or your software centre), then restart your accounts.")
            self.update_header()
        bg(work, done=done)
