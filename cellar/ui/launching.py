"""MainWindow part: Launching, stopping and joining: launch sequences, Bring-here, website Play links, the command line.

A mixin of ui.main_window.MainWindow - `self` is the main window."""

import threading
import time
from typing import List, Optional


from .. import api, playlink, sober, specs, store, usage, util, webhook
from ..models import Account, GameEntry, Instance, JoinRecord, LaunchSpec
from .common import ask, bg, ui, warn
from .dialogs import PlayLinkDialog
from .widgets import _size


class LaunchMixin:
    def run_command(self, args: List[str]) -> str:
        """A command from the command line (cli.py), on the UI thread. Returns the text the terminal shows;
        'ERR ...' makes the command fail."""
        from .. import cli
        if not args:
            return cli.usage()
        cmd, rest = args[0], args[1:]
        if cmd == "show":
            self.showNormal()
            self.raise_()
            self.activateWindow()
            return ""
        if cmd == "list":
            alive = {i.account.id for i in self.launcher.alive_instances()}
            rows = [f"{a.name:<24} {self.model.status(a)[0] or ('running' if a.id in alive else '-'):<40} {a.group}"
                    for a in store.accounts]
            return "\n".join(rows) or "No accounts."
        if cmd == "preset":
            p = self.presets_page.find(" ".join(rest))
            if not p:
                return "ERR no preset called '" + " ".join(rest) + "'"
            self.presets_page.run(p)
            return f"Running preset '{p.name}'."
        if cmd == "stop":
            if rest == ["all"]:
                return f"Closed {self.launcher.stop_all(self.log)} window(s)."
            accs, err = cli.pick_accounts(rest)
            if err:
                return "ERR " + err
            for a in accs:
                self.launcher.stop_account(a, self.log)
            self.update_running()
            return f"Stopped {len(accs)} account(s)."
        if cmd == "launch":
            names, spec, err = cli.parse_launch(rest)
            if err:
                return "ERR " + err
            accs, err = cli.pick_accounts(names)
            if err:
                return "ERR " + err
            if self.launching:
                return "ERR a launch is already running in Cellar"
            if isinstance(spec, tuple):         # needs the network: resolve on a worker, then launch
                kind, val = spec
                form = specs.LaunchForm(mode="Private" if kind == "private" else "Follow",
                                        private=val if kind == "private" else "", follow=val if kind == "follow" else "")
                bg(specs.resolve_form, form, accs[0], self.log,
                   done=lambda sp: sp and self.start_launch(accs, fixed=sp, allow_saved=False))
            else:
                self.start_launch(accs, fixed=spec, allow_saved=spec is None)
            return f"Launching {len(accs)} account(s)."
        return "ERR unknown command - try: cellar help"

    def joined(self, inst: Instance, place_id: int, job_id: str):
        """An account entered a server (its Roblox log said so): Continue playing + join history."""
        s = store.settings
        if not s.recent or s.recent[0].place_id != place_id:
            self.add_recent(place_id)
        s.history.insert(0, JoinRecord(time.time(), inst.account.id, inst.account.name, place_id, job_id))
        del s.history[300:]
        store.save_settings()

    def open_servers(self, place_id: int):
        self.servers_page.place.setText(str(place_id))
        self.show_page(self.servers_page)
        self.servers_page.load(False)

    def bring_here(self, leader: Account, accs: List[Account]):
        """'Bring my alts here': accounts join the exact server another account is in. Its server comes from its
        Roblox log when Cellar runs it, otherwise from Roblox's presence (its own login can always see it)."""
        def find():
            for i in self.launcher.instances_of(leader):
                if i.job_id and i.place_id and self.launcher.is_alive(i):
                    return LaunchSpec(kind="Job", place_id=i.place_id, job_id=i.job_id)
            if leader.user_id and leader.cookie:
                pr = api.presence(leader.cookie, [leader.user_id]).get(leader.user_id)
                if pr and pr.type == 2:
                    if pr.place_id and util.looks_like_guid(pr.game_id):
                        return LaunchSpec(kind="Job", place_id=pr.place_id, job_id=pr.game_id)
                    return LaunchSpec(kind="Follow", follow_user_id=leader.user_id, follow_name=leader.name)
            return None

        def done(spec):
            if spec is None:
                return warn(self, "Bring accounts", f"{leader.name} is not in a game right now.")
            same = {i.account.id for i in self.launcher.alive_instances()
                    if spec.kind == "Job" and i.job_id == spec.job_id}
            go = [a for a in accs if a.id not in same]
            if not go:
                return self.log(f"Everyone is already in {leader.name}'s server.")
            self.log(f"Bringing {len(go)} account(s) to {leader.name}'s server...")
            self.start_launch(go, fixed=spec, allow_saved=False)
        bg(find, done=done)

    def add_recent(self, place_id: int, name: str = ""):
        s = store.settings
        e = next((x for x in s.recent if x.place_id == place_id), None)
        if e is None:
            e = GameEntry(place_id=place_id)
            s.recent.insert(0, e)
        e.ts = time.time()
        if name:
            e.name = name
        s.recent = sorted(s.recent, key=lambda x: -x.ts)[:25]
        store.save_settings()
        self.launch_page.refresh_recent()
        if not e.name:
            def done(n):
                if n:
                    e.name = n
                    store.save_settings()
                    self.launch_page.refresh_recent()
                    self.model.refresh_status()
            bg(api.place_name, place_id, done=done)

    def set_launching(self, on: bool, cancel: Optional[threading.Event] = None):
        self.launching = on
        self.cancel = cancel if on else None
        self.launch_page.set_launching(on)

    def launch_selected(self):
        sel = self.selected_accounts()
        if not sel:
            self.log("Select one or more accounts in the list first.")
            self.show_page(self.launch_page)
            return
        self.start_launch(sel)

    def launch_all_listed(self):
        accs = self.filtered_accounts()
        if not accs:
            self.log("There are no accounts in the list.")
            return
        if len(accs) > 3 and not ask(self, "Launch all", f"Launch all {len(accs)} listed accounts?"):
            return
        self.start_launch(accs)

    def stop_launch(self):
        if self.cancel:
            self.cancel.set()
            self.log("Stopping after the current account...")

    def join_server(self, place_id: int, job: str):
        sel = self.selected_accounts()
        if not sel:
            self.log("Select one or more accounts in the list first.")
            return
        self.start_launch(sel, LaunchSpec(kind="Job", place_id=place_id, job_id=job), allow_saved=False)

    def start_launch(self, accs: List[Account], fixed: Optional[LaunchSpec] = None, allow_saved: bool = True):
        if self.launching:
            self.log("A launch is already running. Press Stop to cancel it.")
            return
        form = self.launch_page.read_form()
        cancel = threading.Event()
        self.set_launching(True, cancel)
        s = store.settings

        def work():
            if fixed is not None:
                spec = fixed
            elif s.use_saved_per_account and all(specs.saved_spec(a) for a in accs):
                spec = specs.saved_spec(accs[0])
            else:
                spec = specs.resolve_form(form, accs[0], self.log)
            if spec is None:
                return
            self.run_sequence(accs, spec, allow_saved, cancel)

        bg(work, done=lambda _: self.set_launching(False), err=lambda _: self.set_launching(False))

    def run_sequence(self, accs: List[Account], spec: LaunchSpec, allow_saved: bool, cancel: threading.Event):
        """Worker thread."""
        s = store.settings
        self.log(f"Launching {len(accs)} account(s): {spec.describe()}")
        if spec.place_id:
            pid = spec.place_id
            ui(lambda: self.add_recent(pid))
        for i, a in enumerate(accs):
            if cancel.is_set():
                break
            self.launcher.breaker_clear(a)
            own = specs.saved_spec(a) if allow_saved and s.use_saved_per_account else None
            per = (own or spec).copy()
            if per.kind == "Private" and per.share_code and not per.link_code:
                if not specs.resolve_saved_share(a, per, self.log, save=own is not None):
                    continue
            if s.min_free_ram_mb > 0 and not self._wait_for_ram(a, s.min_free_ram_mb, cancel):
                break
            self.launcher.launch(a, per, self.log)
            ui(self.update_running)
            if i < len(accs) - 1 and not cancel.is_set():
                cancel.wait(max(0, s.launch_delay_sec))
        self.log("Launch cancelled." if cancel.is_set() else "Launch sequence finished.")
        if not cancel.is_set():
            ui(lambda: self.desktop_notify("done", f"Launched {len(accs)} account(s): {spec.describe()}."))
        if not cancel.is_set() and s.webhook_batch:
            webhook.send("Launch finished", f"Started {len(accs)} account(s): {spec.describe()}", webhook.GREEN)

    def _wait_for_ram(self, a: Account, need_mb: int, cancel: threading.Event) -> bool:
        """Worker thread. False = cancelled. Gives up waiting after 3 minutes and launches anyway."""
        end, told = time.time() + 180, False
        while usage.mem_available() < need_mb * 2**20 and time.time() < end:
            if not told:
                self.log(f"[{a.name}] waiting for free memory ({_size(usage.mem_available())} free, the setting "
                         f"wants {need_mb} MB)...")
                told = True
            if cancel.wait(3):
                return False
        if told and usage.mem_available() < need_mb * 2**20:
            self.log(f"[{a.name}] still not enough free memory after 3 minutes - launching anyway.")
        return True

    def stop_selected(self):
        sel = self.selected_accounts()
        if sel:
            bg(lambda: [self.launcher.stop_account(a, self.log) for a in sel], done=lambda _: self.update_running())

    def stop_instances(self, insts: List[Instance]):
        bg(lambda: [self.launcher.stop_instance(i, self.log) for i in insts], done=lambda _: self.update_running())

    def stop_all(self):
        self.stop_launch()
        bg(self.launcher.stop_all, self.log, done=lambda _: self.update_running())

    def focus_account(self, a: Account):
        if not self.kwin or not a.tracker_id:
            return
        for w in self.kwin.windows():
            if sober.tracker_of_pid(w.pid) == a.tracker_id:
                self.kwin.activate(w.id)
                return
        self.log(f"[{a.name}] has no open window.")

    def open_play_link(self, uri: str):
        """A roblox-player: / roblox: link the browser gave Cellar (Settings > Open the website's Play button)."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        spec = playlink.parse(uri)
        d = PlayLinkDialog(self, spec, {a.id for a in self.selected_accounts()})
        if not d.exec():
            return
        accs = d.chosen()
        if d.use_sober.isChecked() or not accs:
            playlink.forward_to_sober(uri)
            self.log("Opened the website's link in your normal Sober.")
        else:
            self.log(f"Website link: {spec.describe()} with {len(accs)} account(s).")
            self.start_launch(accs, fixed=spec, allow_saved=False)
