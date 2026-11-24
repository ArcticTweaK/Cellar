"""My Sober tab: settings, FPS cap, Fast Flags and repair tools for your *normal* Sober (the one in your app menu).

Useful with a single account too - this is the part of Cellar that has nothing to do with multi-instance.
Account profiles are not touched here (the Performance tab manages those).
"""

import json
from typing import Dict, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import gfx, sober, theme
from .common import ask, bg, btn, chk, combo, group, hint, info, row, spin, warn
from .dialogs import PasteDialog

# Sober's config.json keys in plain language; any other true/false key still gets a checkbox under its own name.
_LABELS = {
    "close_on_leave": "Close Sober when I leave a game",
    "discord_rpc_enabled": "Show the game I play on Discord",
    "discord_rpc_show_join_button": "Discord: let friends join me with a button",
    "server_location_indicator_enabled": "Show where the server is when I join",
    "enable_hidpi": "HiDPI scaling (sharper on high-resolution screens)",
    "enable_gamemode": "Use GameMode while playing (needs Feral GameMode installed)",
    "enable_mobile_home_screen": "Mobile-style home screen",
    "use_console_experience": "Console interface (for controllers / TV)",
    "allow_gamepad_permission": "Allow controllers",
    "use_libsecret": "Keep my login in the system keyring (the account switcher can't change it then)",
}
_SKIP = {"use_opengl", "graphics_optimization_mode", "fflags"}

# One-click Fast Flag sets. Only flags on Roblox's allowlist: Roblox ignores everything else since Sep 2025.
FLAG_PRESETS: List[Tuple[str, Dict[str, str]]] = [
    ("Lowest graphics quality (more FPS)", {"DFIntDebugFRMQualityLevelOverride": "1"}),
    ("Low-resolution textures", {"DFFlagTextureQualityOverrideEnabled": "True", "DFIntTextureQualityOverride": "0"}),
    ("No grass", {"FIntFRMMinGrassDistance": "0", "FIntFRMMaxGrassDistance": "0"}),
    ("Anti-aliasing off", {"FIntDebugForceMSAASamples": "1"}),
    ("Gray sky", {"FFlagDebugSkyGray": "True"}),
    ("Ignore screen scaling (DPI)", {"DFFlagDisableDPIScale": "True"}),
]


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


class FlagTable(QWidget):
    """Fast Flags as a table: name, value, and whether Roblox honours it (its allowlist)."""

    def __init__(self, on_change):
        super().__init__()
        self.on_change = on_change
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search flags...")
        self.search.textChanged.connect(self._filter)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Flag", "Value", "Roblox uses it"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(200)
        self.table.itemChanged.connect(self._edited)
        presets = QPushButton("Add preset")
        m = QMenu(presets)
        for name, flags in FLAG_PRESETS:
            m.addAction(name, lambda f=flags: self.merge(f))
        presets.setMenu(m)
        v.addWidget(row(self.search, btn("Add flag", self.add_row), btn("Remove", self.remove_selected), presets,
                        btn("Import JSON...", self.import_json), btn("Copy as JSON", self.copy_json), stretch=False))
        v.addWidget(self.table)
        self._loading = False
        self._typed: set = set()

    def set_flags(self, flags: Dict[str, object]):
        # Sober accepts real JSON values (true, 60) as well as strings ("True", "60"): keep each flag's own kind
        self._typed = {k for k, val in flags.items() if not isinstance(val, str)}
        self._loading = True
        self.table.setRowCount(0)
        for k, val in flags.items():
            self._append(k, val)
        self._loading = False
        self._filter()

    def flags(self) -> Dict[str, object]:
        out = {}
        for r in range(self.table.rowCount()):
            k = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            if k:
                val = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
                if k in self._typed:
                    try:
                        val = json.loads(val)
                    except ValueError:
                        pass
                out[k] = val
        return out

    def _append(self, k: str, val) -> int:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(k))
        self.table.setItem(r, 1, QTableWidgetItem(val if isinstance(val, str) else json.dumps(val)))
        st = QTableWidgetItem()
        st.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(r, 2, st)
        self._mark(r)
        return r

    def _mark(self, r: int):
        k = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else ""
        st = self.table.item(r, 2)
        if st is None:
            return
        ok = k in gfx.ALLOWLIST
        st.setText("✓ yes" if ok else ("" if not k else "✗ ignored"))
        st.setForeground(theme.qc("good" if ok else "warn"))
        st.setToolTip("" if ok else "Not on Roblox's allowlist - since Sep 2025 Roblox ignores flags that are not on it.")

    def _edited(self, item):
        if self._loading:
            return
        if item.column() == 0:
            self._loading = True
            self._mark(item.row())
            self._loading = False
        self.on_change()

    def _filter(self):
        q = self.search.text().strip().lower()
        for r in range(self.table.rowCount()):
            k = self.table.item(r, 0).text().lower() if self.table.item(r, 0) else ""
            self.table.setRowHidden(r, bool(q) and q not in k)

    def add_row(self):
        self._loading = True
        r = self._append("", "")
        self._loading = False
        self.table.setCurrentCell(r, 0)
        self.table.editItem(self.table.item(r, 0))

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        if rows:
            self.on_change()

    def merge(self, flags: Dict[str, object]):
        cur = self.flags()
        cur.update(flags)
        self.set_flags(cur)
        self.on_change()

    def import_json(self):
        d = PasteDialog(self, "Import Fast Flags", 'Paste a JSON object, e.g. {"FFlagDebugSkyGray": "True"}. '
                        "Flags you already have are overwritten.", '{\n  "FlagName": "True"\n}')
        if not d.exec():
            return
        try:
            j = json.loads(d.text())
            if not isinstance(j, dict):
                raise ValueError("not an object")
        except ValueError as ex:
            return warn(self, "Import Fast Flags", f"That is not a JSON object ({ex}).")
        self.merge(j)

    def copy_json(self):
        QGuiApplication.clipboard().setText(json.dumps(self.flags(), indent=2))


class MySoberPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.cfg: dict = {}
        self.dirty = False
        from .settings_pages import scrolled
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.addWidget(hint("Settings of your <b>normal Sober</b> - the one in your app menu. Your accounts' own "
                         "profiles are set in the Performance tab. Changes apply the next time Sober starts."))
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        v.addWidget(self.status)

        g, f = group("Sober options")
        self.renderer = combo([(False, "Vulkan (Sober's default)"), (True, "OpenGL (try this if games crash)")],
                              on_change=lambda *_: self.changed())
        f.addRow("Renderer", self.renderer)
        self.optim = combo([("quality", "Quality"), ("balanced", "Balanced (default)"), ("performance", "Performance")],
                           on_change=lambda *_: self.changed())
        f.addRow("Optimization", self.optim)
        self.fps = spin(1, 1000, 60, suffix=" FPS", on_change=lambda *_: self.changed(),
                        tip="Roblox's own 'Maximum frame rate'. Higher than your screen's refresh rate only "
                            "makes the PC work harder.")
        f.addRow("FPS cap", self.fps)
        self.checks_form = f
        self.checks: Dict[str, object] = {}
        v.addWidget(g)

        g, f = group("Fast Flags")
        f.addRow(hint("Engine switches for Roblox. Since September 2025 Roblox only honours flags on its "
                      "allowlist; the last column shows which ones it really uses."))
        self.flags = FlagTable(self.changed)
        f.addRow(self.flags)
        v.addWidget(g)

        self.save_btn = btn("Save to my Sober", self.save, primary=True)
        self.revert_btn = btn("Undo changes", self.load)
        v.addWidget(row(self.save_btn, self.revert_btn))

        g, f = group("Repair")
        f.addRow(hint("Close Sober first. Nothing here touches your login, settings or Roblox itself."))
        self.clean_btns = {}
        for key, (label, _) in sober.CLEANABLE.items():
            b = btn(f"Clear {label.lower()}", lambda k=key: self.clean(k))
            self.clean_btns[key] = b
            f.addRow(b)
        self.also_profiles = chk("Also in the accounts' own profiles (accounts that are not running)", False)
        f.addRow(self.also_profiles)
        f.addRow(row(btn("Reset Sober's settings...", self.reset_settings),
                     btn("Open Sober's logs", lambda: sober.open_folder(sober.main_app() / "data" / "sober" /
                                                                        "sober_logs"), icon="folder-open")))
        v.addWidget(g)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scrolled(inner))
        self._loading = False
        self.load()

    # ------------------------------------------------------------ load / save
    def load(self):
        self._loading = True
        try:
            self.cfg = sober.main_sober_settings()
            exists = (sober.main_app() / "config" / "sober" / "config.json").exists()
            self.renderer.setCurrentIndex(max(0, self.renderer.findData(bool(self.cfg.get("use_opengl", False)))))
            self.optim.setCurrentIndex(max(0, self.optim.findData(self.cfg.get("graphics_optimization_mode",
                                                                               "balanced"))))
            cap = sober.read_fps_cap(sober.main_app())
            self.fps.setEnabled(cap is not None)
            self.fps.setValue(cap if cap and cap > 0 else 60)
            self.fps.setToolTip(self.fps.toolTip() if cap is not None else "Start Sober once - Roblox creates this "
                                                                            "setting on its first start.")
            for w in self.checks.values():
                self.checks_form.removeRow(w)
            self.checks = {}
            keys = [k for k in _LABELS if k in self.cfg] + sorted(k for k, val in self.cfg.items()
                                                                  if isinstance(val, bool) and k not in _LABELS)
            for k in keys:
                if k in _SKIP or not isinstance(self.cfg.get(k), bool):
                    continue
                c = chk(_LABELS.get(k, k), self.cfg[k], lambda *_: self.changed())
                self.checks[k] = c
                self.checks_form.addRow(c)
            flags = self.cfg.get("fflags")
            self.flags.set_flags(flags if isinstance(flags, dict) else {})
            self.dirty = False
            self._status(None if exists else "Sober has no settings file yet - start Sober once.")
            self._sizes()
        finally:
            self._loading = False

    def changed(self):
        if self._loading:
            return
        self.dirty = True
        self._status()

    def _status(self, problem: str = None):
        if problem:
            t = theme.span("warn", problem)
        elif self.dirty:
            t = theme.span("warn", "● Not saved yet.")
        else:
            t = theme.span("muted", "Showing what your Sober uses now.")
        self.status.setText(t)
        self.save_btn.setEnabled(self.dirty)
        self.revert_btn.setEnabled(self.dirty)

    def save(self):
        cfg = dict(self.cfg)
        cfg["use_opengl"] = bool(self.renderer.currentData())
        cfg["graphics_optimization_mode"] = self.optim.currentData()
        for k, c in self.checks.items():
            cfg[k] = c.isChecked()
        cfg["fflags"] = self.flags.flags()
        try:
            sober.write_main_config(cfg)
        except OSError as ex:
            return warn(self, "My Sober", f"Could not save: {ex}")
        err = ""
        if self.fps.isEnabled() and self.fps.value() != sober.read_fps_cap(sober.main_app()):
            err = sober.write_fps_cap(sober.main_app(), self.fps.value())
        self.mw.log("Saved your Sober's settings." + (f" FPS cap not set: {err}" if err else "")
                    + (" Restart Sober to use them." if sober.main_sober_running() else ""))
        self.load()

    # ------------------------------------------------------------ repair
    def _apps(self) -> List:
        apps = [sober.main_app()]
        if self.also_profiles.isChecked():
            running = {sober.profile_app(i.account) for i in self.mw.launcher.alive_instances()}
            apps += [a for a in sober.account_apps() if a not in running]
        return apps

    def _sizes(self):
        app = sober.main_app()

        def done(sizes):
            for k, n in sizes.items():
                self.clean_btns[k].setText(f"Clear {sober.CLEANABLE[k][0].lower()}  ({_size(n)})")
        bg(lambda: {k: sober.clean_size(app, k) for k in sober.CLEANABLE}, done=done)

    def clean(self, key: str):
        if sober.main_sober_running():
            return warn(self, "Repair", "Close your normal Sober first.")
        label = sober.CLEANABLE[key][0]
        apps = self._apps()
        b = self.clean_btns[key]
        b.setEnabled(False)

        def done(freed):
            b.setEnabled(True)
            self.mw.log(f"Cleared {label.lower()}: {_size(freed)} freed"
                        + (f" in {len(apps)} Sober folders." if len(apps) > 1 else "."))
            self._sizes()
        bg(lambda: sum(sober.clean(a, key) for a in apps), done=done, err=lambda ex: b.setEnabled(True))

    def reset_settings(self):
        if sober.main_sober_running():
            return warn(self, "Repair", "Close your normal Sober first.")
        f = sober.main_app() / "config" / "sober" / "config.json"
        if not f.exists():
            return info(self, "Repair", "Sober has no settings file - nothing to reset.")
        if not ask(self, "Reset Sober's settings", "Delete your Sober's settings file? Sober creates a fresh one with "
                                                   "its defaults on the next start. (Your login is kept; a copy of "
                                                   "the old file is saved as config.json.old.)"):
            return
        f.replace(f.with_name("config.json.old"))
        self.mw.log("Reset your Sober's settings - Sober creates new ones on its next start.")
        self.load()
