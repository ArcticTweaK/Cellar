"""Performance, Settings and Help pages."""

import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QGridLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from .. import (APP_ID, APP_NAME, AUTHOR, __version__, antiafk, crypto, gfx, paths, playlink, sober, store, theme,
               webhook)
from .common import bg, btn, chk, combo, group, hint, info, row, spin, warn
from .dialogs import PasswordDialog, TextDialog


class ThemeCard(QAbstractButton):
    """A small picture of a theme: its window, a card, text lines and its accent button."""

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(168, 128)
        t = theme.preview_theme(key)
        self.setToolTip(f"{t.name} - {t.blurb}")

    def enterEvent(self, ev):
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _):
        t = theme.preview_theme(self.key)
        cur = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        outer = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        # frame: accent of the active theme when chosen
        edge = QColor(cur.accent) if self.isChecked() else QColor(cur.border if not self.underMouse() else cur.muted)
        p.setPen(QPen(edge, 2.5 if self.isChecked() else 1))
        p.setBrush(QColor(cur.surface))
        p.drawRoundedRect(outer, 12, 12)
        # the mini window
        win = QRectF(outer.x() + 8, outer.y() + 8, outer.width() - 16, 76)
        p.setPen(QPen(QColor(t.border), 1))
        p.setBrush(QColor(t.bg))
        p.drawRoundedRect(win, 7, 7)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t.text))
        p.drawRoundedRect(QRectF(win.x() + 9, win.y() + 9, 46, 6), 3, 3)
        p.setBrush(QColor(t.accent))
        p.drawRoundedRect(QRectF(win.x() + 59, win.y() + 9, 24, 6), 3, 3)
        card = QRectF(win.x() + 9, win.y() + 22, win.width() - 18, win.height() - 31)
        p.setPen(QPen(QColor(t.border), 1))
        p.setBrush(QColor(t.surface))
        p.drawRoundedRect(card, 5, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t.muted))
        p.drawRoundedRect(QRectF(card.x() + 8, card.y() + 9, 58, 4), 2, 2)
        p.drawRoundedRect(QRectF(card.x() + 8, card.y() + 18, 40, 4), 2, 2)
        p.setBrush(QColor(t.good))
        p.drawEllipse(QRectF(card.x() + 8, card.y() + 29, 7, 7))
        p.setBrush(QColor(t.accent))
        p.drawRoundedRect(QRectF(card.right() - 44, card.bottom() - 17, 36, 11), 5, 5)
        # name
        p.setPen(QColor(cur.text))
        f = self.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(outer.x() + 12, win.bottom() + 6, outer.width() - 24, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   t.name)
        if self.isChecked():
            p.setPen(QColor(cur.accent))
            p.drawText(QRectF(outer.x() + 12, win.bottom() + 6, outer.width() - 24, 20),
                       Qt.AlignRight | Qt.AlignVCenter, "✓")
        p.setPen(QColor(cur.muted))
        f.setBold(False)
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(f)
        p.drawText(QRectF(outer.x() + 12, win.bottom() + 23, outer.width() - 24, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   t.blurb)
        p.end()


class ThemePicker(QWidget):
    """Grid of ThemeCards; calls on_pick(key) when another one is clicked."""

    def __init__(self, current_key: str, on_pick):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setSpacing(10)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.cards = []
        for i, t in enumerate(theme.THEMES):
            card = ThemeCard(t.key)
            card.setChecked(t.key == current_key)
            card.clicked.connect(lambda _=False, k=t.key: on_pick(k))
            self.group.addButton(card)
            self.cards.append(card)
            grid.addWidget(card, i // 4, i % 4)
        grid.setColumnStretch(4, 1)

    def refresh(self):
        for c in self.cards:
            c.setChecked(c.key == store.settings.theme)
            c.update()


def scrolled(w: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setWidget(w)
    return s


def _follows(master, widgets) -> None:
    """Options that only matter while `master` is ticked are greyed out otherwise."""
    for w in widgets:
        w.setEnabled(master.isChecked())
    master.toggled.connect(lambda on: [w.setEnabled(on) for w in widgets])


class _Bound:
    """Widgets bound to settings attributes, re-loadable after a preset changed the settings."""

    def __init__(self):
        self._binds = []
        self._loading = False

    def bind(self, widget, get_obj, attr, after=None):
        self._binds.append((widget, get_obj, attr))

        def setter(v):
            if self._loading:
                return
            setattr(get_obj(), attr, v)
            store.save_settings()
            if after:
                after()
        if hasattr(widget, "toggled") and hasattr(widget, "isChecked"):
            widget.toggled.connect(setter)
        elif hasattr(widget, "valueChanged"):
            widget.valueChanged.connect(setter)
        elif hasattr(widget, "currentIndexChanged"):
            widget.currentIndexChanged.connect(lambda *_: setter(widget.currentData()))
        elif hasattr(widget, "textChanged"):
            widget.textChanged.connect(setter)
        return widget

    def load(self):
        self._loading = True
        try:
            for w, get_obj, attr in self._binds:
                v = getattr(get_obj(), attr)
                if hasattr(w, "isChecked") and hasattr(w, "toggled"):
                    w.setChecked(bool(v))
                elif hasattr(w, "setValue"):
                    w.setValue(int(v))
                elif hasattr(w, "findData"):
                    i = w.findData(v)
                    if i >= 0:
                        w.setCurrentIndex(i)
                elif hasattr(w, "setText"):
                    w.setText(str(v))
        finally:
            self._loading = False


S = lambda: store.settings
G = lambda: store.settings.gfx
SO = lambda: store.settings.sober


class PerfPage(QWidget, _Bound):
    def __init__(self, mw):
        QWidget.__init__(self)
        _Bound.__init__(self)
        self.mw = mw
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.addWidget(hint("<b>How your alts run.</b> Accounts marked <i>Full quality - this is my main</i> (Edit "
                         "account) skip the FPS cap, graphics, CPU priority and RAM limit. Written into each "
                         "account's own Sober when it "
                         "launches - running windows keep theirs until relaunched."))
        g, f = group("Last hour - everything Cellar runs for your accounts")
        from .widgets import UsageGraph
        self.g_cpu = UsageGraph("CPU", lambda v: f"{v:.0f}%", floor=5)
        self.g_mem = UsageGraph("Memory", lambda v: f"{v / 2**30:.1f} GB" if v >= 2**30 else f"{v / 2**20:.0f} MB",
                                floor=2**29)
        f.addRow(row(self.g_cpu, self.g_mem, stretch=False))
        v.addWidget(g)

        g, f = group("Frame rate (alts)")
        f.addRow("FPS cap", self.bind(spin(0, 1000, S().fps_cap, special="same as my normal Sober",
                                           tip="Roblox's own 'Maximum frame rate' (FramerateCap), per profile. "
                                               "Accounts can have their own cap (Edit account).\n\nMeasured: an alt "
                                               "in a game takes 0.82 CPU cores at 240 FPS with Roblox's default "
                                               "graphics, and 0.17 at 30 FPS with the Lowest preset. About 1 GB of "
                                               "RAM each either way, so RAM sets how many alts fit. OpenGL used "
                                               "about 35% less graphics memory per alt than Vulkan."), S, "fps_cap"))
        v.addWidget(g)

        g, f = group("Roblox graphics for alts (Fast Flags)")
        self.preset = self.bind(combo([(k, gfx.PRESET_LABELS[k]) for k in gfx.PRESETS], G().preset), G, "preset",
                                self._preset_changed)
        f.addRow("Preset", self.preset)
        self.quality = self.bind(spin(0, 21, G().quality, special="Roblox default"), G, "quality", self._custom)
        f.addRow("Graphics quality", self.quality)
        self.texture = self.bind(combo([(-1, "Roblox default"), (0, "0 - lowest"), (1, "1"), (2, "2"), (3, "3 - highest")],
                                       G().texture), G, "texture", self._custom)
        f.addRow("Texture quality", self.texture)
        self.msaa = self.bind(combo([(0, "Roblox default"), (1, "Off"), (2, "2x"), (4, "4x"), (8, "8x")], G().msaa),
                              G, "msaa", self._custom)
        f.addRow("Anti-aliasing", self.msaa)
        for attr, text in (("no_grass", "No grass"), ("gray_sky", "Gray sky"), ("pause_voxelizer", "Pause voxelizer (lighting)"),
                           ("low_csg", "Low detail for unions (CSG)")):
            f.addRow(self.bind(chk(text, getattr(G(), attr)), G, attr, self._custom))
        self.custom = QPlainTextEdit(S().custom_flags)
        self.custom.setPlaceholderText('{"FlagName": "True"}  - only flags on Roblox\'s allowlist are written')
        self.custom.setMaximumHeight(90)
        self.custom.textChanged.connect(self._custom_text)
        f.addRow("Your own flags", self.custom)
        f.addRow(self.bind(chk("Also write flags that are not on Roblox's allowlist (Roblox ignores them)",
                               G().write_unlisted), G, "write_unlisted"))
        f.addRow(row(btn("Preview what will be written", self.preview_flags)))
        v.addWidget(g)

        g, f = group("Sober options")
        f.addRow("Renderer", self.bind(combo([(False, "Vulkan (Sober's default)"),
                                              (True, "OpenGL (less graphics memory per alt: 261 vs 400 MB measured)")],
                                             SO().use_opengl), SO, "use_opengl"))
        f.addRow("Optimization", self.bind(combo([("quality", "Quality"), ("balanced", "Balanced (default)"),
                                                  ("performance", "Performance")], SO().graphics_optimization_mode),
                                           SO, "graphics_optimization_mode"))
        f.addRow(self.bind(chk("Close Sober when leaving a game", SO().close_on_leave), SO, "close_on_leave"))
        f.addRow(self.bind(chk("HiDPI scaling", SO().enable_hidpi), SO, "enable_hidpi"))
        f.addRow(self.bind(chk("Show server location on join", SO().server_location_indicator_enabled), SO,
                           "server_location_indicator_enabled"))
        f.addRow(self.bind(chk("Discord Rich Presence", SO().discord_rpc_enabled), SO, "discord_rpc_enabled"))
        v.addWidget(g)

        g, f = group("CPU and memory")
        f.addRow("CPU priority of alts", self.bind(combo([("Normal", "Normal"), ("BelowNormal", "Below normal"),
                                                          ("Idle", "Idle (only spare CPU)")], S().priority,
                                                         tip="Accounts marked Full quality (your main) always run "
                                                             "at normal priority."), S, "priority"))
        f.addRow("RAM limit per alt", self.bind(spin(0, 65536, S().ram_cap_mb, suffix=" MB", special="off",
                                                     tip="Soft memory limit (systemd MemoryHigh) of each alt's Sober "
                                                         "window. Above it the kernel reclaims that window's memory "
                                                         "first. Accounts marked Full quality (your main) have none."),
                                                S, "ram_cap_mb"))
        f.addRow(row(btn("Apply to running alts",
                         lambda: bg(self.mw.launcher.apply_limits_all, self.mw.log))))
        f.addRow("Before each launch, wait until", self.bind(spin(0, 65536, S().min_free_ram_mb, suffix=" MB free",
                                                         special="off", tip="Before each account starts, wait (up to 3 "
                                                         "minutes) until at least this much memory is free."),
                                                    S, "min_free_ram_mb"))
        f.addRow("Close the newest alt below", self.bind(spin(0, 65536, S().low_ram_close_mb, suffix=" MB free", special="off",
                                                    tip="When free memory drops below this, the most recently "
                                                        "started alt is closed (never an account marked Full "
                                                        "quality) - before Linux's out-of-memory killer picks "
                                                        "something itself."), S, "low_ram_close_mb"))
        self.fit = QLabel()
        self.fit.setWordWrap(True)
        f.addRow(self.fit)
        v.addWidget(g)

        g, f = group("Freeze (right-click a running account)")
        f.addRow(self.bind(chk("Keep frozen accounts connected (wake them for a moment now and then)",
                               S().freeze_keep_connected,
                               tip="An account that stays frozen stops answering the game server, which drops it "
                                   "after a while. Waking it briefly keeps it in the server for a tiny bit of CPU."),
                           S, "freeze_keep_connected"))
        f.addRow("Wake every", row(self.bind(spin(3, 120, S().freeze_wake_every_sec, suffix=" s"), S,
                                             "freeze_wake_every_sec"),
                                   QLabel("for"),
                                   self.bind(spin(200, 10000, S().freeze_wake_ms, suffix=" ms"), S, "freeze_wake_ms")))
        f.addRow(hint("If frozen accounts still get kicked, wake them more often or for longer."))
        v.addWidget(g)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scrolled(inner))

    def update_fit(self, per_alt: int, measured: bool):
        """'How many more alts fit' from free memory and what an alt uses (measured on this PC when one runs)."""
        from .. import usage
        free = usage.mem_available()
        if not free:
            self.fit.setText("")
            return
        keep = max(S().min_free_ram_mb, S().low_ram_close_mb, 1024) * 2**20   # leave room for your desktop
        n = max(0, int((free - keep) // max(per_alt, 1)))
        self.fit.setText(f"<b>About {n} more alt{'s' if n != 1 else ''} fit</b> in the {free / 2**30:.1f} GB free now "
                         f"({per_alt / 2**30:.1f} GB per alt, {'measured on your alts' if measured else 'typical'}; "
                         "1 GB kept for your desktop).")

    def _preset_changed(self):
        if self._loading:
            return
        gfx.apply_preset(G(), G().preset)
        store.save_settings()
        self.load()

    def _custom(self):
        if not self._loading and G().preset != "Custom":
            G().preset = "Custom"
            store.save_settings()
            self._loading = True
            self.preset.setCurrentIndex(self.preset.findData("Custom"))
            self._loading = False

    def _custom_text(self):
        S().custom_flags = self.custom.toPlainText()
        store.save_settings()

    def load(self):
        _Bound.load(self)
        self.custom.blockSignals(True)
        self.custom.setPlainText(S().custom_flags)
        self.custom.blockSignals(False)

    def preview_flags(self):
        TextDialog(self, "Fast Flags", gfx.preview(S())).exec()


class AutomationSettings(QWidget, _Bound):
    """The Anti-AFK & rejoin tab: the watcher (auto-relaunch, rejoin after a kick) and anti-AFK."""

    def __init__(self, mw):
        QWidget.__init__(self)
        _Bound.__init__(self)
        self.mw = mw
        inner = QWidget()
        v = QVBoxLayout(inner)

        g, f = group("Watcher (auto-relaunch)")
        f.addRow(self.bind(chk("Relaunch accounts whose window closed or crashed", S().auto_relaunch), S, "auto_relaunch",
                           self.mw.restart_timers))
        f.addRow("Check every", self.bind(spin(15, 3600, S().watcher_sec, suffix=" s"), S, "watcher_sec", self.mw.restart_timers))
        f.addRow(self.bind(chk("Rejoin right away when an account is kicked or loses connection",
                               S().rejoin_on_kick, tip="Cellar reads each account's Roblox log, so it notices a "
                                                       "disconnect within seconds. A lost connection rejoins the same "
                                                       "server."), S, "rejoin_on_kick"))
        f.addRow(self.bind(chk("Also relaunch accounts that are no longer in a game (presence check)",
                               S().watcher_use_presence), S, "watcher_use_presence"))
        f.addRow(self.bind(chk("Crash breaker: stop relaunching an account that keeps crashing", S().crash_breaker),
                           S, "crash_breaker"))
        f.addRow("Give up after", row(self.bind(spin(1, 50, S().crash_breaker_max, suffix=" relaunches"), S, "crash_breaker_max"),
                                      QLabel("within"),
                                      self.bind(spin(1, 120, S().crash_breaker_window_min, suffix=" min"), S, "crash_breaker_window_min"),
                                      QLabel("retry after"),
                                      self.bind(spin(1, 600, S().crash_breaker_cooldown_min, suffix=" min"), S, "crash_breaker_cooldown_min")))
        v.addWidget(g)

        g, f = group("Anti-AFK")
        f.addRow(self.bind(chk("Keep accounts from being kicked for idling", S().anti_afk), S, "anti_afk", self.mw.restart_timers))
        f.addRow("Every", self.bind(spin(1, 19, S().anti_afk_min, suffix=" min",
                                         tip="Roblox kicks after about 20 minutes without input."), S, "anti_afk_min",
                                    self.mw.restart_timers))
        f.addRow("Action", self.bind(combo(antiafk.ACTIONS, S().anti_afk_action), S, "anti_afk_action"))
        self.afk_status = QLabel()
        self.afk_status.setWordWrap(True)
        f.addRow(self.afk_status)
        f.addRow(btn("Run once now", self.mw.anti_afk_now))
        v.addWidget(g)

        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scrolled(inner))
        self.update_status()

    def update_status(self):
        a = antiafk.status()
        self.afk_status.setText(theme.span("good", "✓ ydotool is ready.") if not a else theme.span("warn", a))

    def showEvent(self, ev):
        super().showEvent(ev)
        self.update_status()


class SettingsPage(QWidget, _Bound):
    def __init__(self, mw):
        QWidget.__init__(self)
        _Bound.__init__(self)
        self.mw = mw
        self._loading_links = False
        inner = QWidget()
        v = QVBoxLayout(inner)

        g, f = group("Appearance")
        self.themes = ThemePicker(S().theme, self._pick_theme)
        f.addRow(self.themes)
        f.addRow(hint("Changes the whole app right away. <i>System</i> uses your desktop's own style and colours."))
        self.accent_btn = btn("Pick a colour...", self._pick_accent)
        self.accent_reset = btn("Theme's own", self._reset_accent)
        self.accent_reset.setVisible(bool(S().accent))
        f.addRow("Accent", row(self.accent_btn, self.accent_reset))
        f.addRow(hint("Your own colour for buttons, tabs and highlights, on any theme except System."))
        auto = int(round(S().auto_scale * 100))
        self.size = combo([("auto", f"Auto ({auto}% on this screen)"), ("90", "90% - compact"), ("100", "100%"),
                           ("115", "115%"), ("130", "130% - large"), ("150", "150% - extra large")], S().ui_scale)
        self.size_restart = btn("Restart now", self.mw.restart_app, primary=True,
                                tip="Cellar restarts in a second; your running accounts keep running")
        self.size_restart.setVisible(False)
        self.size.currentIndexChanged.connect(self._size_changed)
        f.addRow("Size", row(self.size, self.size_restart))
        f.addRow(hint("Makes text, buttons and pictures bigger or smaller together. Applies after a restart."))
        v.addWidget(g)

        g, f = group("Multi-instance")
        f.addRow(self.bind(chk("Give every account its own isolated Sober (run many at once)", S().multi_instance),
                           S, "multi_instance", self.update_status))
        self.mi_status = QLabel()
        self.mi_status.setWordWrap(True)
        f.addRow(self.mi_status)
        f.addRow(hint("Each account gets a private copy of your Sober profile (a copy-on-write clone: no extra disk on "
                      "btrfs), its own network namespace (pasta) and time namespace. Off = one Sober window at a time, "
                      "using your normal Sober."))
        f.addRow(self.bind(chk("Keep the profiles' Roblox files updated from my normal Sober", S().keep_profiles_updated),
                           S, "keep_profiles_updated"))
        f.addRow(row(btn("Open profiles folder", lambda: sober.open_folder(paths.PROFILES_DIR), icon="folder-open"),
                     btn("Reset profile of selected accounts", self.mw.reset_selected_profiles)))
        v.addWidget(g)

        g, f = group("Launching")
        self.play_links = chk("Open the website's Play button with Cellar (choose which accounts join)", False,
                              tip="Roblox links from your browser come to Cellar instead of Sober. You pick accounts, "
                                  "or send the link on to your normal Sober.")
        self.play_links.toggled.connect(self._set_play_links)
        f.addRow(self.play_links)
        f.addRow(self.bind(chk("Close an account's previous window when it is launched again", S().auto_close_last),
                           S, "auto_close_last"))
        f.addRow("Max windows", self.bind(spin(0, 200, S().max_instances, special="no limit"), S, "max_instances"))
        f.addRow(self.bind(chk("Get a fresh cookie before every launch (signs the account out elsewhere)",
                               S().refresh_cookie_on_launch), S, "refresh_cookie_on_launch"))
        self.plurl = self.bind(QLineEdit(S().place_launcher_url), S, "place_launcher_url")
        self.plurl.setToolTip("The Roblox address accounts join games through (PlaceLauncher). Leave it as it is "
                              "unless Roblox changes it or a fix tells you to.")
        f.addRow("Join address (advanced)", self.plurl)
        v.addWidget(g)

        g, f = group("Sound")
        f.addRow(self.bind(chk("Mute alts (accounts not marked Full quality)", S().mute_alts,
                               tip="Only your main plays sound. Right-click an account > Mute / Unmute, or give it its "
                                   "own volume in Edit account. Needs PipeWire (pw-dump, wpctl)."),
                           S, "mute_alts", self.mw.audio_tick))
        v.addWidget(g)

        g, f = group("Account list")
        self.main_acc = QComboBox()
        self.main_acc.setToolTip("Its friends fill the Launch tab's Friend list, its favourites fill "
                                 "'Your games', and friend notifications are about its friends.")
        self.main_acc.currentIndexChanged.connect(self._main_account_changed)
        f.addRow("Main account", self.main_acc)
        f.addRow(self.bind(chk("Show live status (online / in game)", S().show_presence), S, "show_presence", self.mw.restart_timers))
        f.addRow("Refresh every", self.bind(spin(15, 600, S().presence_sec, suffix=" s"), S, "presence_sec", self.mw.restart_timers))
        f.addRow(self.bind(chk("Check every saved login when the app starts", S().check_logins_at_startup), S,
                           "check_logins_at_startup"))
        v.addWidget(g)

        g, f = group("Desktop notifications")
        master = self.bind(chk("Show desktop notifications", S().notify), S, "notify")
        f.addRow(master)
        kids = []
        for attr, text in (("notify_kick", "An account was kicked or lost its connection"),
                           ("notify_crash", "A Roblox window closed unexpectedly"),
                           ("notify_login_lost", "Roblox signed an account out"),
                           ("notify_launch_done", "A launch sequence finished"),
                           ("notify_friends", "A friend comes online or starts a game (friends of your main account)")):
            kids.append(self.bind(chk(text, getattr(S(), attr)), S, attr))
            f.addRow(kids[-1])
        _follows(master, kids)
        v.addWidget(g)

        g, f = group("Discord webhook alerts")
        master = self.bind(chk("Send alerts to a Discord channel", S().webhook), S, "webhook")
        f.addRow(master)
        kids = []
        self.wh_url = self.bind(QLineEdit(S().webhook_url), S, "webhook_url")
        self.wh_url.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.wh_url.setPlaceholderText("https://discord.com/api/webhooks/...")
        wh_row = row(self.wh_url, btn("Test", self.test_webhook), stretch=False)
        kids.append(wh_row)
        f.addRow("Webhook URL", wh_row)
        for attr, text in (("webhook_crash", "A window closed unexpectedly"), ("webhook_relaunch", "The watcher relaunched a window"),
                           ("webhook_batch", "A launch sequence finished"), ("webhook_locked", "An account came back locked")):
            kids.append(self.bind(chk(text, getattr(S(), attr)), S, attr))
            f.addRow(kids[-1])
        kids.append(self.bind(chk("Add a picture of the account's screen when it is disconnected (background accounts)",
                               S().webhook_screenshot, tip="Shows Roblox's own kick / disconnect message. Only background "
                               "accounts have a screen Cellar can see (Wayland lets no app capture other windows)."),
                              S, "webhook_screenshot"))
        f.addRow(kids[-1])
        _follows(master, kids)
        v.addWidget(g)

        g, f = group("Security")
        self.enc = QLabel()
        self.enc.setWordWrap(True)
        f.addRow(self.enc)
        f.addRow(row(btn("Set / change password...", self.set_password), btn("Use keyring (no password)", self.remove_password)))
        self.lock_min = self.bind(spin(0, 600, S().lock_after_min, suffix=" min", special="never",
                                       tip="With a password on your accounts file: after this long in the background "
                                           "Cellar hides your accounts until you type it again (your accounts keep "
                                           "running). Ctrl+L or the tray menu locks right away."),
                                  S, "lock_after_min")
        f.addRow("Lock after", row(self.lock_min, QLabel("in the background (password only)")))
        v.addWidget(g)

        g, f = group("App")
        self.autostart = chk("Start Cellar when I log in", paths.AUTOSTART_FILE.exists(), self.set_autostart)
        f.addRow(self.autostart)
        f.addRow(self.bind(chk("Start hidden in the tray", S().start_minimized_to_tray), S, "start_minimized_to_tray"))
        f.addRow(self.bind(chk("Closing the window keeps the app running in the tray", S().close_to_tray), S, "close_to_tray"))
        f.addRow(row(self.bind(chk("Tell me when a new version is out (asks GitHub once a day)", S().check_updates),
                               S, "check_updates"),
                     btn("Check now", lambda: self.mw.check_updates(manual=True))))
        f.addRow(row(btn("Open data folder", lambda: sober.open_folder(paths.DATA_DIR), icon="folder-open"),
                     btn("System check", self.system_check, icon="dialog-information"),
                     btn("Run setup again", self.mw.run_setup, icon="tools-wizard")))
        v.addWidget(g)
        v.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scrolled(inner))
        self.update_status()

    # ------------------------------------------------------------
    def _pick_accent(self):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(S().accent or theme.c("accent")), self, "Accent colour")
        if c.isValid():
            self._set_accent(c.name())

    def _reset_accent(self):
        self._set_accent("")

    def _set_accent(self, hex_colour: str):
        S().accent = hex_colour
        store.save_settings()
        theme.set_accent(hex_colour)
        self.mw.apply_theme(S().theme)
        self.accent_reset.setVisible(bool(hex_colour))

    def _size_changed(self, *_):
        S().ui_scale = self.size.currentData()
        store.save_settings()
        self.size_restart.setVisible(True)

    def _pick_theme(self, key: str):
        if key != S().theme or key == "system":
            self.mw.apply_theme(key)
        self.themes.refresh()

    def _fill_main_account(self):
        self.main_acc.blockSignals(True)
        self.main_acc.clear()
        self.main_acc.addItem("Automatic (the one marked Full quality, else the first)", "")
        for acc in sorted((x for x in store.accounts if x.user_id and x.cookie), key=lambda x: x.order):
            self.main_acc.addItem(acc.name, acc.id)
        self.main_acc.setCurrentIndex(max(0, self.main_acc.findData(S().home_account)))
        self.main_acc.blockSignals(False)

    def _main_account_changed(self, *_):
        S().home_account = self.main_acc.currentData() or ""
        store.save_settings()
        self.mw.launch_page.main_account_changed()

    def update_status(self):
        self._sync_play_links()
        ok, why = sober.multi_instance_support()
        if not sober.sober_installed():
            t = theme.span("bad", "Sober is not installed: <tt>flatpak install flathub org.vinegarhq.Sober</tt>")
        elif not S().multi_instance:
            t = "Off: one Sober window at a time."
        elif ok:
            t = theme.span("good", "✓ Ready: pasta, unshare and Sober found.")
        else:
            t = theme.span("warn", f"Not available - {why}. Until then one window at a time is used.")
        self.mi_status.setText(t)
        self._fill_main_account()
        self.enc.setText(f"Your accounts file is encrypted with <b>{store.key_location()}</b>."
                         + ("<br>" + theme.span("warn", "No keyring was found, so the key sits next to the file. "
                                                "Set a password for real protection.")
                            if store.key_location().startswith("key file") else ""))
        self.themes.refresh()

    def _set_play_links(self, on: bool):
        if self._loading_links:
            return
        try:
            playlink.set_handler(on)
            self.mw.log("Roblox's Play button now opens Cellar." if on else "Roblox's Play button opens Sober again.")
        except (OSError, subprocess.SubprocessError) as ex:
            warn(self, "Play button", f"Could not change the handler: {ex}")
        self._sync_play_links()

    def _sync_play_links(self):
        def done(is_cellar):
            self._loading_links = True
            self.play_links.setChecked(is_cellar)
            self._loading_links = False
        bg(playlink.handler_is_cellar, done=done)

    def test_webhook(self):
        url = self.wh_url.text().strip()
        if not webhook.looks_like_webhook(url):
            warn(self, "Webhook", "That is not a Discord webhook URL.")
            return
        bg(webhook.post, url, "Test", "Cellar can post here.", webhook.BLURPLE, True,
           done=lambda e: info(self, "Webhook", "Sent." if not e else "Failed: " + e))

    def set_password(self):
        pw = PasswordDialog.ask(self, "Accounts password", "New password for your accounts file:", confirm=True)
        if pw is None:
            return
        store.set_password(pw)
        self.update_status()
        info(self, "Password", "Your accounts file is now protected by this password. You will be asked for it at "
                               "every start. It is the same format as the Windows app.")

    def remove_password(self):
        store.set_password(None)
        self.update_status()
        info(self, "Encryption", f"Your accounts file is now encrypted with {store.key_location()} - no password needed.")

    def set_autostart(self, on: bool):
        try:
            if on:
                exe = shutil.which(APP_ID)
                cmd = f'"{exe}"' if exe else f'"{sys.executable}" -m cellar'
                paths.AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
                paths.AUTOSTART_FILE.write_text(
                    f"[Desktop Entry]\nType=Application\nName={APP_NAME}\nIcon={APP_ID}\n"
                    f"Exec={cmd} --minimized\nX-GNOME-Autostart-enabled=true\n")
            elif paths.AUTOSTART_FILE.exists():
                paths.AUTOSTART_FILE.unlink()
        except OSError as ex:
            warn(self, "Autostart", str(ex))

    def system_check(self):
        lines = [f"{APP_NAME} {__version__} by {AUTHOR}", ""]
        inst = sober.sober_installed()
        lines.append(f"Sober installed:        {'yes ' + sober.sober_version() if inst else 'NO - flatpak install flathub org.vinegarhq.Sober'}")
        mv = sober.app_version(sober.main_app())
        lines.append(f"Your Sober profile:     {sober.main_app()} " + (f"(Roblox {mv})" if mv else "(not found - start Sober once)"))
        for t in ("flatpak", "pasta", "unshare", "systemd-run", "sway", "wayvnc", "ydotool", "busctl", "xdg-open"):
            lines.append(f"{t + ':':23} {sober.which(t) or 'missing'}")
        ok, why = sober.multi_instance_support()
        lines.append(f"Multi-instance:         {'available' if ok else why}")
        kw = self.mw.kwin
        lines.append(f"Window control:         {getattr(kw, 'name', '?') if kw and kw.available() else 'no (window layout off)'}")
        lines.append(f"Anti-AFK input:         {antiafk.status() or 'ready'}")
        lines.append(f"Accounts encrypted by:  {store.key_location()}")
        rings = ", ".join(p.label for p in crypto.PROVIDERS[:2] if p.available())
        lines.append(f"Keyrings available:     {rings or 'none'}")
        lines.append(f"Session:                {os.environ.get('XDG_SESSION_TYPE', '?')} / {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
        lines.append(f"Data folder:            {paths.DATA_DIR}")
        lines.append(f"Sober windows running:  {len(sober.all_sober_trackers())}")
        from .setup_wizard import SystemCheckDialog
        SystemCheckDialog(self, self.mw, "\n".join(lines)).exec()


HELP = f"""
<h2>{APP_NAME} {__version__}</h2>
<p>Run many Roblox accounts at once on Linux through <b>Sober</b>. Made by <b>{AUTHOR}</b>.
Free and open source (GPL-3.0).</p>

<h3>Finding your way</h3>
<p>One window: the live numbers at the top, your accounts on the left, the tools as tabs on the right (Launch,
Presets, Macros, Anti-AFK &amp; rejoin, Windows, My Sober, Performance, Settings, Help) and the log at the bottom
(filter it to problems or one account, or search it). Ctrl+1 ... Ctrl+9 open the tabs, Ctrl+K anything. Too small
or too big? Settings &gt; Appearance &gt; <b>Size</b>.</p>
<p>Cellar sits next to roblox.com, it does not replace it: find games on the website (RoValra and other
extensions keep working there), press Play, and Cellar asks which accounts join (see <i>The website's Play
button</i>).</p>

<h3>Launching</h3>
<p>Select accounts in the list (Ctrl / Shift for several), choose where they go on the <b>Launch</b> tab (Game,
Server, Private server or Friend), and press the big launch button - it says what will happen ("Launch 3 accounts into ABOVE"). Enter or a
double-click on an account launches too.</p>
<ul>
<li><b>Game</b>: your games as tiles - <i>Recent</i> (what your accounts played) or <i>Favourites</i> (your main
account's Roblox favourites). Click one to choose it, double-click to launch the selected accounts there,
right-click for <i>Play with...</i>, your normal Sober or its servers. The search field finds any game by name,
or takes a pasted game link / Place ID.</li>
<li><b>Server</b>: one exact server of the chosen game. <i>Pick server...</i> lists its servers and has <b>Quick
join</b> (the emptiest server, or a busy one with room for everyone you send); <i>History...</i> lists every server
your accounts joined.</li>
<li><b>Private server</b>: paste a link; <i>Save...</i> keeps it in the list below for one click next time.</li>
<li><b>Friend</b>: your main account's friends who are online (in a game first) - click one, or type any
username. Your main account is set in Settings &gt; Account list &gt; <b>Main account</b>.</li>
</ul>
<p>Accounts that have their own game (Edit account) go there unless you untick <i>Accounts with their own game go
there</i>. <b>...</b> next to it saves the chosen game to the selected accounts.</p>

<h3>Adding accounts</h3>
<ul>
<li><b>Log in with browser</b> - a private login window; captcha, 2-step and passkeys work. It closes by itself.</li>
<li><b>Create a new Roblox account</b> - Roblox's own sign-up page in the same private window. You fill it in and
pass Roblox's checks yourself; once the account exists it is added here. Give it an email and 2-step verification.</li>
<li><b>username:password</b> - one per line; each opens the login window with the form filled in. You press Log In.</li>
<li><b>Paste / import cookies</b> - any text containing <tt>.ROBLOSECURITY</tt> cookies (bulk).</li>
<li><b>Import my Sober account</b> - takes the account your normal Sober is logged in with.</li>
<li><b>Import Windows accounts.dat</b> - from Roblox MultiHub on Windows, if it is password protected
    (Windows DPAPI files can only be opened on that Windows PC).</li>
</ul>

<h3>Many accounts at once</h3>
<p>Sober allows only one copy per machine. With multi-instance on, every account runs in its own isolated Sober:
its own profile (a copy-on-write clone of your Sober profile in <tt>~/.local/share/cellar/profiles</tt>),
its own network namespace (<tt>pasta</tt>) and its own time namespace. Your normal Sober is never touched and can
keep running next to them. The Sober developers do not support multi-instancing, so if Sober changes this may break.</p>

<h3>The website's Play button</h3>
<p>Settings &gt; Launching &gt; <b>Open the website's Play button with Cellar</b>. Then Play on roblox.com (a
game, a server, a private server, or joining a friend) asks which accounts should join - or sends the link on to
your normal Sober, which plays as the account you are logged in with on the website. Turn it off to give the
links back to Sober.</p>

<h3>My Sober</h3>
<p>Settings for your <b>normal</b> Sober (the one in your app menu), useful even with one account: renderer,
FPS cap and Sober's options in plain language, a Fast Flags editor (the last column shows which flags Roblox
really uses - it ignores flags that are not on its allowlist), repair tools that clear caches and crash dumps, and
<b>Roblox logs</b>: what happened in your last sessions (joined, left, disconnected and why, and the errors of
Roblox and Sober themselves - not the thousands of game-script lines) with <b>Copy for a bug report</b> (cookies
removed). Right-click an account &gt; <b>Roblox log</b> shows that account's own.
Your accounts' own profiles are set in the <b>Performance</b> tab.</p>

<h3>Account switcher</h3>
<p>Right-click an account &gt; <b>Use in my normal Sober</b> logs your normal Sober into that account. Close Sober
first. The account Sober was using is added to Cellar if it is not there yet, so you can switch back.</p>

<h3>Background mode and macros</h3>
<p>Tick <b>Run in the background</b> in an account's settings and it gets its own invisible screen with its own
mouse and keyboard: nothing shows on your desktop and nothing takes your focus. Right-click it &gt;
<b>View screen</b> to watch it, control it, record a macro or take a screenshot (saved in Pictures/Cellar). Macros are plain text
(Macros tab) and run per account, so one account can farm while another does something else; <b>Export</b> /
<b>Import</b> share them as .txt files. <b>Step by step</b> runs a macro one line at a time on the selected
account (the line is highlighted; <b>Next step</b> or F10 does it) - the way to find out why a macro misses. Needs <tt>sway</tt> and <tt>wayvnc</tt>.</p>

<h3>Screen wall and freezing</h3>
<p><b>Screen wall</b> (Windows, tray menu, Ctrl+Shift+W or right-click a background account) shows every background
account's screen in one window, about one picture a second; click one to open it. Right-click a running account
&gt; <b>Freeze</b> stops it from using CPU while it stays open. By default it wakes for a moment every 10 s so it
keeps answering the game server and stays in it (Performance &gt; Freeze); turned off it uses no CPU at all,
but Roblox drops it from the server after a while. The Usage column shows what each account uses (100% = the whole PC).</p>

<h3>Kicks and notifications</h3>
<p>Cellar reads each running account's own Roblox log, so a kick or lost connection is noticed within seconds.
It shows a desktop notification, and with Anti-AFK &amp; rejoin &gt; <b>Rejoin right away when an
account is kicked</b> it comes back by itself - into the same server after a lost connection. Which notifications you get
is set in Settings &gt; Desktop notifications. Discord alerts (Settings &gt; Discord webhook alerts) of a
background account come with a picture of its screen, so you see Roblox's own message.</p>

<h3>Windows</h3>
<p>On Wayland only the compositor may move windows, so layouts go through it: KWin scripts on KDE Plasma,
<tt>hyprctl</tt> on Hyprland and <tt>swaymsg</tt> on Sway (there the windows are made floating first).
Pick a monitor, a grid mode and press <b>Arrange now</b>, or let new windows be arranged automatically. With
more than one screen, <b>All monitors</b> shares the windows out by screen size, each screen with its own grid.
<b>Saved layouts</b> keeps a setup under a name (grid, monitor, borderless...) to switch back in one click.</p>

<h3>Alts and performance</h3>
<p>The <b>Performance</b> tab: FPS cap, graphics Fast Flags and Sober options are written into each
account's profile before it launches. CPU priority and the RAM limit use the systemd scope every Sober window runs
in; like the FPS cap they are for alts only, so an account marked Full quality (your main) keeps normal priority and
no RAM limit. The page also
estimates how many more alts fit in your free memory, can wait before each launch until enough memory is free,
and can close the newest alt when memory runs low (never one marked Full quality). <b>Last hour</b> graphs the CPU
and memory of everything Cellar runs (hover for exact values). Edit account &gt; <b>Graphics</b> gives one account
its own graphics preset.</p>

<h3>Themes</h3>
<p>Settings &gt; Appearance: Blossom (pink), Midnight, Mint, Ember, Graphite, Daylight (light), or System to use
your desktop's own look. The change shows right away.</p>

<h3>Anti-AFK</h3>
<p>The <b>Anti-AFK &amp; rejoin</b> tab. Background accounts get a key press on their own screen. Normal windows are focused briefly and get one key
press through <tt>ydotool</tt>; then your window gets the focus back.</p>

<h3>Handy extras</h3>
<ul>
<li>Right-click an account &gt; <b>Bring accounts to its server</b>: the selected accounts, a group or everyone
join the exact server that account is in.</li>
<li><b>History</b> (right-click an account, Ctrl+K, or Launch &gt; Server &gt; History): every session - which
account played what, when and for how long - and the time played in the last 7 days per account and game.
Kept on this PC only. Double-click a session to rejoin that server.</li>
<li>Settings &gt; Security &gt; <b>Lock after</b> (with a password on your accounts file): after that long in the
background Cellar hides your accounts until you type the password; your accounts keep running. Ctrl+L locks right
away.</li>
<li>Settings &gt; Desktop notifications &gt; <b>A friend comes online or starts a game</b>: a message with a
<b>Join</b> button (friends of your main account).</li>
<li>Right-click &gt; <b>Details</b> (or the Details button): Robux, Premium, account age and whether the login
still works. Right-click &gt; <b>Open profile on roblox.com</b> for the rest.</li>
<li>Right-click &gt; <b>Export to a file</b> (or Add account &gt; Export all) makes a password-protected copy of
your accounts for another PC; import it there with Add account &gt; <b>Import accounts file</b>.</li>
<li>Right-click &gt; <b>Colour tag</b> marks accounts with a colour (a bar on the card or table row); the group
list above the accounts can then show only one colour. Edit account and Bulk edit have it too.</li>
<li><b>Pin to top</b> keeps an account first in the list. <b>Log in again</b> appears on accounts Roblox signed
out. Add account &gt; <b>Restore from a backup</b> brings back an earlier account list (the last 10 are kept).</li>
<li><b>Ctrl+K</b> opens the command palette: type a few letters of anything (an account, a page, a preset,
a recent game, a theme) and press Enter. Text that matches nothing searches games to launch.</li>
<li>The account list: <b>Cards</b> or <b>Table</b> view (top right of the list). With the list set to <b>Your
order</b>, drag accounts to rearrange them (select several first to move them together).</li>
<li>Keys: Enter = launch selected, F2 = edit, Ctrl+N = add account, Ctrl+Shift+S = stop all, Ctrl+1...9 = tabs,
Ctrl+F = search, F5 = refresh status.</li>
<li>Command line: <tt>cellar list</tt>, <tt>cellar launch NAME... [--place ID]</tt>, <tt>cellar preset NAME</tt>,
<tt>cellar stop all</tt> (<tt>cellar help</tt> for all). <b>Add to app menu</b> (right-click an account, or
on the Presets tab) makes a launcher entry.</li>
</ul>

<h3>More</h3>
<ul>
<li>Launching shows a progress list on the Launch tab: ✓ started or ✗ failed with the reason, and
<b>Retry failed</b>.</li>
<li>Presets &gt; <b>Schedule</b>: run a preset at a time of day and stop it later (Cellar must be running).</li>
<li>Settings &gt; Sound &gt; <b>Mute alts</b>, right-click &gt; Mute / Unmute, or a volume per account (Edit
account). Needs PipeWire.</li>
<li>The log: show only problems or one account, or search it.</li>
<li>Drop cookie files (or copied cookie text) onto the window to add accounts; drop an accounts .dat file to
import it.</li>
<li>Settings &gt; Appearance &gt; <b>Accent</b>: your own colour on any theme.</li>
</ul>

<h3>Problems?</h3>
<p>Settings &gt; <b>System check</b> shows what is missing with the command to install it, and <b>Copy report</b>
copies a bug report (your cookies are removed). <b>Run setup again</b> repeats the first-start setup. If Cellar
ever closes by itself, the next start says so and keeps what it was doing in <tt>crash-last.txt</tt>.</p>

<h3>Warning</h3>
<p>Running several clients and automating input is against Roblox's rules and can get accounts moderated.
Use your own accounts at your own risk, and give every account a verified email + 2-step verification.</p>

<h3>Credits</h3>
<p>{APP_NAME} started as a Linux port of Roblox MultiHub (Windows, GPL-3.0) by the Roblox-MultiHub authors.
Not affiliated with Roblox Corporation or VinegarHQ (Sober).</p>
"""


class HelpPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        v = QVBoxLayout(self)
        t = QTextBrowser()
        t.setObjectName("help")
        t.setOpenExternalLinks(True)
        t.setHtml(HELP)
        v.addWidget(t)
