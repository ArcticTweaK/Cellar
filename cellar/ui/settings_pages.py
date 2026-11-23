"""Performance, Settings and Help pages."""

import os
import shutil
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from .. import APP_ID, APP_NAME, AUTHOR, __version__, antiafk, crypto, gfx, paths, sober, store, webhook
from .common import bg, btn, chk, combo, group, hint, info, row, spin, warn
from .dialogs import PasswordDialog, TextDialog


def scrolled(w: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setWidget(w)
    return s


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
        v.addWidget(hint("Everything here is written into each account's own Sober profile right before it "
                         "launches, so already running windows keep their settings until relaunched "
                         "(CPU priority / RAM cap can be applied to running windows)."))

        v.addWidget(hint("<b>The FPS cap and graphics preset below are for your alts.</b> Accounts marked "
                         "<i>Full quality - this is my main</i> (Edit account) skip both. Measured on this kind of "
                         "PC: an alt in a game takes 0.82 CPU cores at 240 FPS with Roblox's default graphics, and "
                         "0.17 at 30 FPS with the Lowest preset. About 1 GB of RAM each either way, so RAM sets "
                         "how many alts fit. OpenGL used about 35% less graphics memory per alt than Vulkan."))
        g, f = group("Frame rate (alts)")
        f.addRow("FPS cap", self.bind(spin(0, 1000, S().fps_cap, special="same as my normal Sober",
                                           tip="Roblox's own 'Maximum frame rate' (FramerateCap), per profile. "
                                               "Accounts can have their own cap (Edit account)."), S, "fps_cap"))
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
        f.addRow(btn("Preview what will be written", self.preview_flags))
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
        f.addRow("CPU priority", self.bind(combo([("Normal", "Normal"), ("BelowNormal", "Below normal"),
                                                  ("Idle", "Idle (only spare CPU)")], S().priority), S, "priority"))
        f.addRow("RAM limit per window", self.bind(spin(0, 65536, S().ram_cap_mb, suffix=" MB", special="off",
                                                        tip="Soft memory limit (systemd MemoryHigh) of each Sober window. "
                                                            "Above it the kernel reclaims that window's memory first."),
                                                   S, "ram_cap_mb"))
        f.addRow(btn("Apply to running windows", lambda: bg(self.mw.launcher.apply_limits_all, self.mw.log)))
        v.addWidget(g)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scrolled(inner))

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


class SettingsPage(QWidget, _Bound):
    def __init__(self, mw):
        QWidget.__init__(self)
        _Bound.__init__(self)
        self.mw = mw
        inner = QWidget()
        v = QVBoxLayout(inner)

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
        f.addRow(self.bind(chk("Close an account's previous window when it is launched again", S().auto_close_last),
                           S, "auto_close_last"))
        f.addRow("Max windows", self.bind(spin(0, 200, S().max_instances, special="no limit"), S, "max_instances"))
        f.addRow(self.bind(chk("Get a fresh cookie before every launch (signs the account out elsewhere)",
                               S().refresh_cookie_on_launch), S, "refresh_cookie_on_launch"))
        self.plurl = self.bind(QLineEdit(S().place_launcher_url), S, "place_launcher_url")
        f.addRow("PlaceLauncher URL", self.plurl)
        v.addWidget(g)

        g, f = group("Watcher (auto-relaunch)")
        f.addRow(self.bind(chk("Relaunch accounts whose window closed or crashed", S().auto_relaunch), S, "auto_relaunch",
                           self.mw.restart_timers))
        f.addRow("Check every", self.bind(spin(15, 3600, S().watcher_sec, suffix=" s"), S, "watcher_sec", self.mw.restart_timers))
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

        g, f = group("Account list")
        f.addRow(self.bind(chk("Show live status (online / in game)", S().show_presence), S, "show_presence", self.mw.restart_timers))
        f.addRow("Refresh every", self.bind(spin(15, 600, S().presence_sec, suffix=" s"), S, "presence_sec", self.mw.restart_timers))
        f.addRow(self.bind(chk("Check every saved login when the app starts", S().check_logins_at_startup), S,
                           "check_logins_at_startup"))
        v.addWidget(g)

        g, f = group("Discord webhook alerts")
        f.addRow(self.bind(chk("Send alerts to a Discord channel", S().webhook), S, "webhook"))
        self.wh_url = self.bind(QLineEdit(S().webhook_url), S, "webhook_url")
        self.wh_url.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.wh_url.setPlaceholderText("https://discord.com/api/webhooks/...")
        f.addRow("Webhook URL", row(self.wh_url, btn("Test", self.test_webhook), stretch=False))
        for attr, text in (("webhook_crash", "A window closed unexpectedly"), ("webhook_relaunch", "The watcher relaunched a window"),
                           ("webhook_batch", "A launch sequence finished"), ("webhook_locked", "An account came back locked")):
            f.addRow(self.bind(chk(text, getattr(S(), attr)), S, attr))
        v.addWidget(g)

        g, f = group("Security")
        self.enc = QLabel()
        self.enc.setWordWrap(True)
        f.addRow(self.enc)
        f.addRow(row(btn("Set / change password...", self.set_password), btn("Use keyring (no password)", self.remove_password)))
        v.addWidget(g)

        g, f = group("App")
        self.autostart = chk("Start Cellar when I log in", paths.AUTOSTART_FILE.exists(), self.set_autostart)
        f.addRow(self.autostart)
        f.addRow(self.bind(chk("Start hidden in the tray", S().start_minimized_to_tray), S, "start_minimized_to_tray"))
        f.addRow(self.bind(chk("Closing the window keeps the app running in the tray", S().close_to_tray), S, "close_to_tray"))
        f.addRow(row(btn("Open data folder", lambda: sober.open_folder(paths.DATA_DIR), icon="folder-open"),
                     btn("System check", self.system_check, icon="dialog-information")))
        v.addWidget(g)
        v.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scrolled(inner))
        self.update_status()

    # ------------------------------------------------------------
    def update_status(self):
        ok, why = sober.multi_instance_support()
        if not sober.sober_installed():
            t = "<span style='color:#f85149'>Sober is not installed: <tt>flatpak install flathub org.vinegarhq.Sober</tt></span>"
        elif not S().multi_instance:
            t = "Off: one Sober window at a time."
        elif ok:
            t = "<span style='color:#3fb950'>Ready: pasta, unshare and Sober found.</span>"
        else:
            t = f"<span style='color:#d29922'>Not available - {why}. Until then one window at a time is used.</span>"
        self.mi_status.setText(t)
        a = antiafk.status()
        self.afk_status.setText("<span style='color:#3fb950'>ydotool is ready.</span>" if not a
                                else f"<span style='color:#d29922'>{a}</span>")
        self.enc.setText(f"Your accounts file is encrypted with <b>{store.key_location()}</b>."
                         + ("<br><span style='color:#d29922'>No keyring was found, so the key sits next to the file. "
                            "Set a password for real protection.</span>" if store.key_location().startswith("key file") else ""))

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
        lines.append(f"KWin window control:    {'yes' if kw and kw.available() else 'no (window layout disabled)'}")
        lines.append(f"Anti-AFK input:         {antiafk.status() or 'ready'}")
        lines.append(f"Accounts encrypted by:  {store.key_location()}")
        rings = ", ".join(p.label for p in crypto.PROVIDERS[:2] if p.available())
        lines.append(f"Keyrings available:     {rings or 'none'}")
        lines.append(f"Session:                {os.environ.get('XDG_SESSION_TYPE', '?')} / {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
        lines.append(f"Data folder:            {paths.DATA_DIR}")
        lines.append(f"Sober windows running:  {len(sober.all_sober_trackers())}")
        TextDialog(self, "System check", "\n".join(lines)).exec()


HELP = f"""
<h2>{APP_NAME} {__version__}</h2>
<p>Run many Roblox accounts at once on Linux through <b>Sober</b>. Made by <b>{AUTHOR}</b>.
Free and open source (GPL-3.0).</p>

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

<h3>Background mode and macros</h3>
<p>Tick <b>Run in the background</b> in an account's settings and it gets its own invisible screen with its own
mouse and keyboard: nothing shows on your desktop and nothing takes your focus. Right-click it &gt;
<b>View screen</b> to watch it, control it or record a macro. Macros are plain text (Macros tab) and run per
account, so one account can farm while another does something else. Needs <tt>sway</tt> and <tt>wayvnc</tt>.</p>

<h3>Windows page</h3>
<p>On Wayland only the compositor may move windows, so layouts are done through KWin scripts (KDE Plasma).
Pick a monitor, a grid mode and press <b>Arrange now</b>, or let new windows be arranged automatically.</p>

<h3>Performance</h3>
<p>FPS cap, graphics Fast Flags and Sober options are written into each account's profile before it launches.
CPU priority and the RAM limit use the systemd scope every Sober window runs in.</p>

<h3>Anti-AFK</h3>
<p>Background accounts get a key press on their own screen. Normal windows are focused briefly and get one key
press through <tt>ydotool</tt>; then your window gets the focus back.</p>

<h3>Not available on Linux</h3>
<p>RAM cleaner (Windows memory lists), renaming window titles, global hotkeys, Discord bot / screenshots.</p>

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
        t.setOpenExternalLinks(True)
        t.setHtml(HELP)
        v.addWidget(t)
