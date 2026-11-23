"""Presets: save what is running (accounts, games, window positions, settings) and bring it back."""

import threading
import time
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHeaderView, QInputDialog, QLineEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import sober, specs, store, util
from ..models import LaunchSpec, Preset, PresetEntry, PresetSettings
from .common import ask, bg, btn, chk, group, hint, row
from .dialogs import TextDialog


class PresetsPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self._loading = False
        v = QVBoxLayout(self)

        g, f = group("Save what is running now")
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Farm 6 accounts")
        f.addRow("Preset name", row(self.name, btn("Save as preset", self.save, icon="document-save", primary=True), stretch=False))
        f.addRow(hint("Saves every running account started by this app (in launch order), the game / server each one "
                      "joined, where every window is, and the Launch / Windows / Performance settings. If nothing is "
                      "running, the selected accounts are saved with their own game."))
        v.addWidget(g)

        g, f = group("Your presets")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Accounts", "Saved", "Accounts in launch order"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tree.itemDoubleClicked.connect(lambda *_: self.run_selected())
        self.tree.itemSelectionChanged.connect(self._sel)
        f.addRow(self.tree)
        f.addRow(row(btn("Run", self.run_selected, icon="media-playback-start", primary=True), btn("Update", self.update_selected),
                     btn("Rename...", self.rename), btn("Details", self.details), btn("Delete", self.delete, icon="edit-delete")))
        v.addWidget(g, 1)

        g, f = group("Options")
        self.exact = chk("Rejoin the exact same servers (Job ID)", store.settings.preset_exact_servers, self._exact,
                         "Off = any server of the same game (old servers usually no longer exist).")
        f.addRow(self.exact)
        self.startup = QComboBox()
        self.startup.currentIndexChanged.connect(self._startup)
        f.addRow("Run at startup", self.startup)
        v.addWidget(g)
        self.refresh()

    # ------------------------------------------------------------
    def _exact(self, v):
        store.settings.preset_exact_servers = v
        store.save_settings()

    def _startup(self, *_):
        if self._loading:
            return
        store.settings.startup_preset = self.startup.currentData() or ""
        store.save_settings()
        if store.settings.startup_preset:
            self.mw.log(f"Preset '{store.settings.startup_preset}' will run every time Cellar starts.")

    def _sel(self):
        p = self.selected()
        if p:
            self.name.setText(p.name)

    @staticmethod
    def entry_name(e: PresetEntry) -> str:
        a = store.find_by_id(e.account_id)
        return a.name if a else f"{e.username} (removed)"

    def refresh(self):
        keep = self.selected().name if self.selected() else None
        self.tree.clear()
        for p in store.settings.presets:
            it = QTreeWidgetItem([p.name, str(len(p.entries)), util.ago(p.saved), ", ".join(self.entry_name(e) for e in p.entries)])
            it.setData(0, Qt.UserRole, p.name)
            self.tree.addTopLevelItem(it)
            if p.name == keep:
                it.setSelected(True)
        self._loading = True
        self.startup.clear()
        self.startup.addItem("(none)", "")
        for p in store.settings.presets:
            self.startup.addItem(p.name, p.name)
        self.startup.setCurrentIndex(max(0, self.startup.findData(store.settings.startup_preset)))
        self._loading = False

    def find(self, name: str) -> Optional[Preset]:
        return next((p for p in store.settings.presets if p.name.lower() == (name or "").lower()), None)

    def selected(self) -> Optional[Preset]:
        its = self.tree.selectedItems()
        return self.find(its[0].data(0, Qt.UserRole)) if its else None

    # ------------------------------------------------------------ capture
    def capture(self, name: str) -> Optional[Preset]:
        p = Preset(name=name, saved=time.time(), settings=PresetSettings.capture(store.settings))
        insts = sorted(self.mw.launcher.alive_instances(), key=lambda i: i.started)
        wins = {}
        if self.mw.kwin and self.mw.kwin.available():
            for w in self.mw.kwin.windows():
                wins[sober.tracker_of_pid(w.pid)] = w
        grid = self.mw.windows_page
        if insts:
            for idx, i in enumerate(insts):
                e = PresetEntry(account_id=i.account.id, username=i.account.username,
                                spec=i.spec.copy() if i.spec and (i.spec.place_id or i.spec.follow_user_id) else None,
                                grid_index=idx, include=i.tracker not in grid.excluded)
                w = wins.get(i.tracker)
                if w:
                    e.has_rect, e.x, e.y, e.w, e.h = True, w.x, w.y, w.w, w.h
                    e.borderless, e.minimized = w.no_border, w.minimized
                p.entries.append(e)
        else:
            sel = self.mw.selected_accounts()
            if not sel:
                self.mw.log("Nothing launched by this app is running and no accounts are selected - nothing to save.")
                return None
            for idx, a in enumerate(sel):
                p.entries.append(PresetEntry(account_id=a.id, username=a.username, spec=None, grid_index=idx))
        return p

    def save(self):
        name = self.name.text().strip()
        if not name:
            self.mw.log("Type a name for the preset first.")
            return
        old = self.find(name)
        if old and not ask(self, "Save preset", f"Replace the preset '{old.name}' with what is running now?"):
            return
        p = self.capture(name)
        if p is None:
            return
        if old:
            store.settings.presets[store.settings.presets.index(old)] = p
        else:
            store.settings.presets.append(p)
        store.save_settings()
        self.refresh()
        self.mw.log(f"Preset '{name}' saved ({len(p.entries)} account(s)).")

    def update_selected(self):
        old = self.selected()
        if not old:
            return
        p = self.capture(old.name)
        if p:
            store.settings.presets[store.settings.presets.index(old)] = p
            store.save_settings()
            self.refresh()
            self.mw.log(f"Preset '{old.name}' updated.")

    def rename(self):
        p = self.selected()
        if not p:
            return
        new, ok = QInputDialog.getText(self, "Rename preset", "New name:", text=p.name)
        new = new.strip()
        if ok and new and not self.find(new):
            if store.settings.startup_preset == p.name:
                store.settings.startup_preset = new
            p.name = new
            store.save_settings()
            self.refresh()

    def delete(self):
        p = self.selected()
        if p and ask(self, "Delete preset", f"Delete the preset '{p.name}'?"):
            store.settings.presets.remove(p)
            if store.settings.startup_preset == p.name:
                store.settings.startup_preset = ""
            store.save_settings()
            self.refresh()

    def details(self):
        p = self.selected()
        if not p:
            return
        lines = [f"Preset: {p.name}", f"Saved: {util.ago(p.saved)}", ""]
        for e in p.entries:
            where = e.spec.describe() if e.spec else "own game / Launch page"
            rect = f"  window {e.x},{e.y} {e.w}x{e.h}" + (" borderless" if e.borderless else "") if e.has_rect else ""
            lines.append(f"{e.grid_index + 1}. {self.entry_name(e)}: {where}{rect}" + ("" if e.include else "  (not in grid)"))
        s = p.settings
        lines += ["", f"FPS cap {s.fps_cap or 'default'}, graphics {s.gfx.preset}, CPU {s.priority}, "
                  f"grid {s.layout.mode}, delay {s.launch_delay_sec}s, auto-relaunch {'on' if s.auto_relaunch else 'off'}, "
                  f"anti-AFK {'on' if s.anti_afk else 'off'}"]
        TextDialog(self, "Preset details", "\n".join(lines)).exec()

    # ------------------------------------------------------------ run
    def run_selected(self):
        p = self.selected()
        if p:
            self.run(p)

    def run(self, p: Preset):
        mw = self.mw
        if mw.launching:
            mw.log("A launch is already running. Press Stop to cancel it.")
            return
        p.settings.apply_to(store.settings)
        store.save_settings()
        mw.reload_pages()
        form = mw.launch_page.read_form()
        exact = store.settings.preset_exact_servers
        entries = [e for e in p.entries if store.find_by_id(e.account_id)]
        missing = len(p.entries) - len(entries)
        mw.log(f"Running preset '{p.name}' ({len(entries)} account(s)" + (f", {missing} removed" if missing else "") + ")...")
        cancel = threading.Event()
        mw.set_launching(True, cancel)

        def work():
            delay = max(0, store.settings.launch_delay_sec)
            first = True
            for e in entries:
                if cancel.is_set():
                    break
                a = store.find_by_id(e.account_id)
                if mw.launcher.running(a):
                    mw.log(f"[{a.name}] is already running - only its window is placed.")
                    continue
                if not first:
                    cancel.wait(delay)
                    if cancel.is_set():
                        break
                first = False
                spec = e.spec.copy() if e.spec else None
                if spec and spec.kind == "Job" and not exact:
                    spec = LaunchSpec(kind="Game", place_id=spec.place_id)
                if spec is None:
                    spec = specs.saved_spec(a) or specs.resolve_form(form, a, mw.log)
                if spec is None:
                    mw.log(f"[{a.name}] skipped - no game saved for it and none on the Launch page.")
                    continue
                if spec.kind == "Private" and spec.share_code and not spec.link_code:
                    if not specs.resolve_saved_share(a, spec, mw.log):
                        continue
                mw.launcher.breaker_clear(a)
                mw.launcher.launch(a, spec, mw.log)
            return not cancel.is_set()

        def done(ok):
            mw.set_launching(False)
            mw.log(f"Preset '{p.name}' launched." if ok else "Preset cancelled.")
            if ok:
                self._place_when_ready(p, time.time() + 60)
        bg(work, done=done)

    def _place_when_ready(self, p: Preset, deadline: float):
        """Waits for the windows, then puts each one where the preset saved it (or into the grid)."""
        mw = self.mw
        if not mw.kwin or not mw.kwin.available():
            return
        wins = {sober.tracker_of_pid(w.pid): w for w in mw.kwin.windows()}
        want = []
        for e in p.entries:
            a = store.find_by_id(e.account_id)
            if a and a.tracker_id:
                want.append((e, wins.get(a.tracker_id)))
        if any(w is None for _, w in want) and time.time() < deadline:
            QTimer.singleShot(2000, lambda: self._place_when_ready(p, deadline))
            return
        grid = mw.windows_page
        grid.excluded = {store.find_by_id(e.account_id).tracker_id for e, _ in want if not e.include}
        grid.order = [store.find_by_id(e.account_id).tracker_id for e, _ in sorted(want, key=lambda t: t[0].grid_index)]
        saved = {w.id: (e.x, e.y, e.w, e.h, e.borderless, e.minimized) for e, w in want if w and e.has_rect}
        if saved:
            grid.place_saved(saved)
            mw.log(f"Preset '{p.name}': {len(saved)} window(s) moved to their saved place.")
        else:
            grid.arrange()
