"""Main window: account list on the left, pages on the right, log at the bottom."""

import os
import threading
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QItemSelectionModel, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMenu, QPlainTextEdit, QSplitter, QSystemTrayIcon,
                               QTableView, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, AUTHOR, __version__, antiafk, api, background, log, paths, sober, specs, store, usage, util, webhook
from ..kwin import KWin
from ..launcher import Launcher
from ..models import Account, GameEntry, Instance, LaunchSpec
from .accounts_model import ACCOUNT_ROLE, AccountFilter, AccountModel
from .browser_login import HAVE_WEBENGINE, BrowserLogin
from .common import app_icon, ask, bg, btn, info, ui, warn
from .dialogs import BulkEditDialog, EditAccountDialog, PasswordDialog, PasteDialog, TextDialog
from .friends_page import FriendsPage
from .launch_pages import LaunchPage, ServersPage
from .macros_page import MacrosPage
from .presets_page import PresetsPage
from .screen_viewer import ScreenViewer
from .settings_pages import HelpPage, PerfPage, SettingsPage
from .windows_page import WindowsPage


def _size(n: float) -> str:
    return f"{n / 2**20:.0f} MB" if n < 2**30 else f"{n / 2**30:.1f} GB"


class StatBlock(QWidget):
    """A caption, a big number and a small line under it (the header's stats)."""

    def __init__(self, caption: str, tip: str = ""):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        cap = QLabel(caption.upper())
        cap.setStyleSheet("color: palette(placeholder-text); font-size: 8pt; font-weight: 600;")
        self.val = QLabel("-")
        self.val.setStyleSheet("font-size: 14pt; font-weight: 600;")
        self.val.setMinimumWidth(90)
        self.sub = QLabel("")
        self.sub.setStyleSheet("color: palette(placeholder-text); font-size: 8pt;")
        for w in (cap, self.val, self.sub):
            v.addWidget(w)
        self.setToolTip(tip)

    def set(self, value: str, sub: str = "") -> None:
        self.val.setText(value)
        self.sub.setText(sub)


class MainWindow(QMainWindow):
    def __init__(self, start_hidden: bool = False):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(store.settings.win_w, store.settings.win_h)
        self.launcher = Launcher()
        self.kwin: Optional[KWin] = None
        try:
            self.kwin = KWin()
        except Exception as ex:
            log.error("KWin bridge", ex)
        self.launching = False
        self.cancel: Optional[threading.Event] = None
        self._watcher_busy = False
        self._presence_busy = False
        self._quitting = False

        # ---------------- left: accounts
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 0, 0)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search accounts...")
        self.search.setClearButtonEnabled(True)
        self.group_filter = QComboBox()
        self.group_filter.setMinimumWidth(130)
        self.sort = QComboBox()
        for k, label in (("Manual", "Your order"), ("Name", "Name"), ("Status", "Status"), ("Last", "Last used"), ("Group", "Group")):
            self.sort.addItem(label, k)
        top.addWidget(self.search, 1)
        top.addWidget(self.group_filter)
        top.addWidget(self.sort)
        lv.addLayout(top)

        self.model = AccountModel()
        self.proxy = AccountFilter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setIconSize(QSize(28, 28))
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.resizeSection(0, 210)
        h.resizeSection(1, 80)
        h.resizeSection(3, 130)
        h.resizeSection(4, 80)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.doubleClicked.connect(lambda *_: self.launch_selected())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.on_selection())
        lv.addWidget(self.table, 1)

        add = QToolButton()
        add.setText("Add account")
        add.setIcon(app_icon().fromTheme("list-add"))
        add.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        add.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(add)
        m.addAction("Log in with browser...", self.add_browser)
        m.addAction("Create a new Roblox account...", self.add_signup)
        m.addAction("Log in with username:password...", self.add_userpass)
        m.addSeparator()
        m.addAction("Paste cookies...", self.add_paste)
        m.addAction("Import cookies from a file...", self.add_file)
        m.addAction("Import the account my Sober is logged in with", self.add_from_sober)
        m.addAction("Import Windows accounts.dat...", self.add_windows_file)
        add.setMenu(m)
        bar = QHBoxLayout()
        bar.addWidget(add)
        bar.addWidget(btn("Edit", self.edit_selected, icon="document-edit"))
        bar.addWidget(btn("Remove", self.remove_selected, icon="list-remove"))
        bar.addWidget(btn("Details", self.details_selected, icon="documentinfo"))
        bar.addStretch(1)
        bar.addWidget(btn("Launch", self.launch_selected, icon="media-playback-start", primary=True))
        bar.addWidget(btn("Stop", self.stop_selected, icon="media-playback-stop"))
        bar.addWidget(btn("Stop all", self.stop_all, icon="process-stop"))
        lv.addLayout(bar)

        # ---------------- right: pages
        self.tabs = QTabWidget()
        self.launch_page = LaunchPage(self)
        self.servers_page = ServersPage(self)
        self.windows_page = WindowsPage(self)
        self.perf_page = PerfPage(self)
        self.presets_page = PresetsPage(self)
        self.macros_page = MacrosPage(self)
        self.friends_page = FriendsPage(self)
        self.settings_page = SettingsPage(self)
        self.help_page = HelpPage(self)
        self.viewers = {}
        for page, name, icon in ((self.launch_page, "Launch", "media-playback-start"), (self.friends_page, "Friends", "system-users"),
                                 (self.servers_page, "Servers", "network-server"),
                                 (self.windows_page, "Windows", "view-grid"), (self.perf_page, "Performance", "speedometer"),
                                 (self.presets_page, "Presets", "bookmarks"), (self.macros_page, "Macros", "media-record"),
                                 (self.settings_page, "Settings", "configure"), (self.help_page, "Help", "help-contents")):
            self.tabs.addTab(page, app_icon().fromTheme(icon), name)
        self.tabs.currentChanged.connect(self._tab_changed)

        # ---------------- log
        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(3000)
        self.logview.setMinimumHeight(70)

        hsplit = QSplitter(Qt.Horizontal)
        hsplit.addWidget(left)
        hsplit.addWidget(self.tabs)
        hsplit.setStretchFactor(0, 1)
        hsplit.setStretchFactor(1, 1)
        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(hsplit)
        vsplit.addWidget(self.logview)
        vsplit.setStretchFactor(0, 5)
        vsplit.setStretchFactor(1, 1)
        if len(store.settings.split) == 4:
            hsplit.setSizes(store.settings.split[:2])
            vsplit.setSizes(store.settings.split[2:])
        else:
            hsplit.setSizes([560, 760])
            vsplit.setSizes([640, 150])
        self.hsplit, self.vsplit = hsplit, vsplit
        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_header())
        cv.addWidget(vsplit, 1)
        self.setCentralWidget(central)
        self.sampler = usage.Sampler()

        self.addAction(QAction(self, shortcut=QKeySequence.Find, triggered=lambda: self.search.setFocus()))
        self.addAction(QAction(self, shortcut=QKeySequence.Delete, triggered=self.remove_selected))

        self.search.textChanged.connect(self.proxy.set_text)
        self.group_filter.currentIndexChanged.connect(lambda *_: self.proxy.set_group(self.group_filter.currentData()))
        self.sort.currentIndexChanged.connect(lambda *_: self.apply_sort())

        log.add_listener(lambda line, replace: ui(lambda: self._append_log(line, replace)))

        # ---------------- tray
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon(), self)
            self.tray.setToolTip(APP_NAME)
            tm = QMenu()
            tm.addAction("Show / hide", self.toggle_visible)
            tm.addAction("Launch selected", self.launch_selected)
            tm.addAction("Arrange windows", lambda: self.windows_page.arrange())
            tm.addAction("Stop all", self.stop_all)
            tm.addSeparator()
            tm.addAction("Quit", self.quit_app)
            self.tray.setContextMenu(tm)
            self.tray.activated.connect(lambda r: self.toggle_visible() if r == QSystemTrayIcon.Trigger else None)
            self.tray.show()

        # ---------------- timers
        self.t_tick = QTimer(self, timeout=self.tick)
        self.t_tick.start(2000)
        self.t_presence = QTimer(self, timeout=self.presence_tick)
        self.t_watcher = QTimer(self, timeout=self.watcher_tick)
        self.t_afk = QTimer(self, timeout=self.anti_afk_now)
        self.restart_timers()

        self.refresh_groups()
        self.refresh_accounts()
        self.update_header()
        QTimer.singleShot(300, self.startup)

    # ================================================================ basics
    def log(self, msg: str) -> None:
        """Thread-safe."""
        log.write(msg)

    def _append_log(self, line: str, replace: bool) -> None:
        doc = self.logview.document()
        if replace and self.logview.toPlainText():
            c = QTextCursor(doc.lastBlock())
            c.movePosition(QTextCursor.StartOfBlock)
            c.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            c.insertText(line)
        else:
            self.logview.appendPlainText(line)
        self.logview.moveCursor(QTextCursor.End)

    def show_page(self, page):
        self.tabs.setCurrentWidget(page)

    def _tab_changed(self, i):
        if self.tabs.widget(i) is self.windows_page:
            self.windows_page.refresh()
        elif self.tabs.widget(i) is self.settings_page:
            self.settings_page.update_status()

    def reload_pages(self):
        for p in (self.launch_page, self.windows_page, self.perf_page, self.settings_page):
            p.load()
        self.restart_timers()

    def restart_timers(self):
        s = store.settings
        self.t_presence.start(max(15, s.presence_sec) * 1000) if s.show_presence else self.t_presence.stop()
        self.t_watcher.start(max(15, s.watcher_sec) * 1000)
        self.t_afk.start(max(1, s.anti_afk_min) * 60000) if s.anti_afk else self.t_afk.stop()

    # ================================================================ account list
    def refresh_accounts(self):
        sel = {a.id for a in self.selected_accounts()}
        self.model.reload()
        self.apply_sort()
        sm = self.table.selectionModel()
        for r in range(self.proxy.rowCount()):
            a = self.proxy.index(r, 0).data(ACCOUNT_ROLE)
            if a and a.id in sel:
                sm.select(self.proxy.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.refresh_groups()
        self.on_selection()

    def refresh_groups(self):
        keep = self.group_filter.currentData()
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem("All groups", None)
        for g in store.all_groups():
            self.group_filter.addItem(g, g)
        if any(not a.group for a in store.accounts) and store.all_groups():
            self.group_filter.addItem("(no group)", "")
        i = self.group_filter.findData(keep)
        self.group_filter.setCurrentIndex(i if i >= 0 else 0)
        self.group_filter.blockSignals(False)

    def apply_sort(self):
        k = self.sort.currentData()
        col = {"Name": 0, "Group": 1, "Status": 2, "Last": 4}.get(k, -1)
        self.proxy.sort(col, Qt.AscendingOrder)

    def selected_accounts(self) -> List[Account]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [a for a in (self.proxy.index(r, 0).data(ACCOUNT_ROLE) for r in rows) if a]

    def filtered_accounts(self) -> List[Account]:
        return [a for a in (self.proxy.index(r, 0).data(ACCOUNT_ROLE) for r in range(self.proxy.rowCount())) if a]

    def any_cookie(self) -> Optional[str]:
        sel = self.selected_accounts()
        a = sel[0] if sel else next((x for x in store.accounts if x.cookie and not store.live(x).cookie_bad), None)
        return a.cookie if a else None

    def on_selection(self):
        self.launch_page.update_selection(self.selected_accounts())

    def context_menu(self, pos):
        sel = self.selected_accounts()
        if not sel:
            return
        m = QMenu(self)
        m.addAction("Launch", self.launch_selected)
        m.addAction("Stop", self.stop_selected)
        bg_insts = [i for a in sel for i in self.launcher.instances_of(a) if i.screen]
        if len(sel) == 1 and not bg_insts:
            m.addAction("Focus its window", lambda: self.focus_account(sel[0]))
        if bg_insts:
            m.addSeparator()
            if len(bg_insts) == 1:
                m.addAction("View screen", lambda: self.view_screen(bg_insts[0]))
            mm = m.addMenu("Run macro")
            for mac in store.settings.macros:
                mm.addAction(mac.name, lambda n=mac.name: [self.launcher.start_macro(i, n, self.log) for i in bg_insts])
            if not store.settings.macros:
                mm.addAction("(none yet - see the Macros tab)").setEnabled(False)
            if any(i.macro for i in bg_insts):
                m.addAction("Stop macro", lambda: [self.launcher.stop_macro(i) for i in bg_insts])
        m.addSeparator()
        m.addAction("Edit...", self.edit_selected)
        m.addAction("Details", self.details_selected)
        m.addAction("Copy cookie", lambda: self.copy([a.cookie for a in sel]))
        m.addAction("Copy username", lambda: self.copy([a.username for a in sel]))
        m.addSeparator()
        if self.sort.currentData() == "Manual":
            m.addAction("Move up", lambda: self.move_selected(-1))
            m.addAction("Move down", lambda: self.move_selected(1))
            m.addSeparator()
        if len(sel) == 1:
            m.addAction("Open its Sober profile folder", lambda: sober.open_folder(sober.profile_app(sel[0])
                                                                                 if sober.profile_app(sel[0]).exists() else paths.PROFILES_DIR))
        m.addAction("Reset Sober profile", self.reset_selected_profiles)
        m.addSeparator()
        m.addAction("Remove", self.remove_selected)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def copy(self, items: List[str]):
        QGuiApplication.clipboard().setText("\n".join(items))
        self.log(f"Copied {len(items)} item(s) to the clipboard.")

    def move_selected(self, d: int):
        sel = self.selected_accounts()
        if not sel:
            return
        accs = store.accounts
        idx = sorted(accs.index(a) for a in sel)
        if d < 0 and idx[0] == 0 or d > 0 and idx[-1] == len(accs) - 1:
            return
        for i in (idx if d < 0 else reversed(idx)):
            accs[i], accs[i + d] = accs[i + d], accs[i]
        store.save_accounts()
        self.refresh_accounts()

    # ================================================================ adding accounts
    def _validate(self, cookie: str) -> bool:
        return api.authenticated(cookie).valid

    def add_cookies(self, cookies: List[str], password_for: dict = None):
        """Validates cookies on a worker thread and adds / updates the accounts."""
        if not cookies:
            self.log("No .ROBLOSECURITY cookies found in that text.")
            return
        self.log(f"Checking {len(cookies)} cookie(s)...")

        def work():
            out = []
            for c in cookies:
                u = api.authenticated(c)
                out.append((c, u))
                time.sleep(0.25)
            return out

        def done(results):
            added = updated = bad = 0
            for c, u in results:
                if not u.valid:
                    bad += 1
                    self.log(f"Cookie rejected: {u.error}")
                    continue
                a = store.find_by_user_id(u.id)
                if a:
                    a.cookie = c
                    updated += 1
                else:
                    a = Account(username=u.name, user_id=u.id, display_name=u.display, cookie=c, order=len(store.accounts))
                    store.accounts.append(a)
                    added += 1
                a.username, a.display_name, a.login_lost = u.name, u.display, False
                if password_for and u.name.lower() in password_for:
                    a.password = password_for[u.name.lower()]
                li = store.live(a)
                li.cookie_bad = li.locked = False
            store.save_accounts()
            self.refresh_accounts()
            self.log(f"Accounts: {added} added, {updated} updated" + (f", {bad} invalid." if bad else "."))
            self.fetch_avatars()
        bg(work, done=done)

    def add_browser(self, user: str = "", password: str = ""):
        if not HAVE_WEBENGINE:
            warn(self, "Browser login", "Qt WebEngine is not available. Paste the account's cookie instead.")
            return None
        d = BrowserLogin(self, self._validate, user, password)
        if d.exec() and d.cookie:
            self.add_cookies([d.cookie], {user.lower(): password} if user and password else None)
            return d.cookie
        return None

    def add_signup(self):
        """Roblox's real sign-up page in the built-in browser; you fill it in, the hub adds the login."""
        if not HAVE_WEBENGINE:
            warn(self, "Create account", "Qt WebEngine is not available. Sign up on roblox.com and paste the cookie.")
            return
        d = BrowserLogin(self, self._validate, signup=True)
        if d.exec() and d.cookie:
            self.add_cookies([d.cookie])

    def add_userpass(self):
        d = PasteDialog(self, "Add accounts with username:password",
                        "One account per line as <b>username:password</b>. For each one a login window opens with the "
                        "form filled in; you press Log In (and solve any captcha). The password is saved with the account.",
                        "user1:password1\nuser2:password2")
        if not d.exec():
            return
        pairs = []
        for line in d.text().splitlines():
            if ":" in line.strip():
                u, p = line.strip().split(":", 1)
                if u.strip():
                    pairs.append((u.strip(), p))
        for i, (u, p) in enumerate(pairs):
            self.log(f"Login {i + 1}/{len(pairs)}: {u}")
            if self.add_browser(u, p) is None and i < len(pairs) - 1:
                if not ask(self, "Browser login", f"The login for {u} was closed. Continue with the next account?"):
                    break

    def add_paste(self):
        d = PasteDialog(self, "Paste cookies", "Paste text containing one or more <tt>.ROBLOSECURITY</tt> cookies "
                        "(<tt>_|WARNING:-DO-NOT-SHARE-THIS...</tt>). Anything else in the text is ignored.")
        if d.exec():
            self.add_cookies(util.extract_cookies(d.text()))

    def add_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Import cookies", str(Path.home()), "Text files (*.txt *.json *.csv);;All files (*)")
        if fn:
            try:
                self.add_cookies(util.extract_cookies(Path(fn).read_text(errors="replace")))
            except OSError as ex:
                warn(self, "Import", str(ex))

    def add_from_sober(self):
        c = sober.main_cookie()
        if not c:
            warn(self, "Import from Sober", "No login was found in your Sober profile "
                 f"({sober.main_app() / 'data/sober/cookies'}). Log in inside Sober first "
                 "(and keep 'use_libsecret' off).")
            return
        self.add_cookies([c])

    def add_windows_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Windows accounts.dat", str(Path.home()), "accounts.dat (*.dat);;All files (*)")
        if not fn:
            return
        raw = Path(fn).read_bytes()
        if raw[:1] == b"D":
            warn(self, "Import", "This file is encrypted with Windows DPAPI and can only be opened on that Windows PC.\n\n"
                 "In the Windows app set a password (Settings > Encryption), then copy accounts.dat again.")
            return
        pw = None
        if raw[:1] == b"P":
            pw = PasswordDialog.ask(self, "Windows accounts.dat", "Password of that accounts file:")
            if pw is None:
                return
        try:
            accs = store.accounts_from_json(store.decrypt_file(raw, pw))
        except Exception as ex:
            warn(self, "Import", str(ex))
            return
        added = 0
        for a in accs:
            if not a.cookie or store.find_by_user_id(a.user_id) or store.find_by_cookie(a.cookie):
                continue
            a.order = len(store.accounts)
            store.accounts.append(a)
            added += 1
        store.save_accounts()
        self.refresh_accounts()
        self.log(f"Imported {added} of {len(accs)} account(s) from the Windows app (duplicates skipped).")
        self.fetch_avatars()

    # ================================================================ editing
    def edit_selected(self):
        sel = self.selected_accounts()
        if not sel:
            return
        if len(sel) == 1:
            d = EditAccountDialog(self, sel[0])
            if d.exec():
                changed = d.apply()
                store.save_accounts()
                self.refresh_accounts()
                if changed:
                    self.add_cookies([sel[0].cookie])
        else:
            d = BulkEditDialog(self, sel)
            if d.exec():
                d.apply(sel)
                store.save_accounts()
                self.refresh_accounts()

    def remove_selected(self):
        sel = self.selected_accounts()
        if not sel:
            return
        names = ", ".join(a.name for a in sel[:6]) + ("..." if len(sel) > 6 else "")
        if not ask(self, "Remove accounts", f"Remove {len(sel)} account(s)?\n\n{names}\n\n"
                   "Their isolated Sober profiles are deleted too."):
            return
        for a in sel:
            store.accounts.remove(a)
        store.save_accounts()
        self.refresh_accounts()
        self.log(f"Removed {len(sel)} account(s).")

        def cleanup():
            for a in sel:
                self.launcher.stop_account(a)
                sober.reset_profile(a)
        bg(cleanup, done=lambda _: self.update_running())

    def details_selected(self):
        sel = self.selected_accounts()
        if not sel:
            return
        d = TextDialog(self, "Account details", "Loading...")

        def work():
            return ("\n\n" + "-" * 40 + "\n\n").join(api.details(a) for a in sel)
        bg(work, done=d.set_text)
        d.exec()

    def reset_selected_profiles(self):
        sel = self.selected_accounts()
        if not sel:
            self.log("Select the accounts whose Sober profile should be reset.")
            return
        if not ask(self, "Reset Sober profile", f"Delete the isolated Sober profile of {len(sel)} account(s)? "
                   "It is created again (from your normal Sober) on the next launch."):
            return

        def work():
            for a in sel:
                self.launcher.stop_account(a)
                sober.reset_profile(a)
        bg(work, done=lambda _: (self.update_running(), self.log(f"Reset the Sober profile of {len(sel)} account(s).")))

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

    # ================================================================ launching
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
            per = ((specs.saved_spec(a) or spec) if allow_saved and s.use_saved_per_account else spec).copy()
            if per.kind == "Private" and per.share_code and not per.link_code:
                if not specs.resolve_saved_share(a, per, self.log):
                    continue
            self.launcher.launch(a, per, self.log)
            ui(self.update_running)
            if i < len(accs) - 1 and not cancel.is_set():
                cancel.wait(max(0, s.launch_delay_sec))
        self.log("Launch cancelled." if cancel.is_set() else "Launch sequence finished.")
        if not cancel.is_set() and s.webhook_batch:
            webhook.send("Launch finished", f"Started {len(accs)} account(s): {spec.describe()}", webhook.GREEN)

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

    # ================================================================ timers
    def update_running(self) -> List[Instance]:
        alive = self.launcher.alive_instances()
        self.model.running = {i.account.id for i in alive}
        self.model.refresh_status()
        self.update_header(alive)
        return alive

    # ---------------------------------------------------------------- header
    def _build_header(self) -> QWidget:
        h = QWidget()
        hl = QHBoxLayout(h)
        hl.setContentsMargins(10, 8, 12, 6)
        hl.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(40, 40))
        hl.addWidget(icon)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        name = QLabel(APP_NAME)
        name.setStyleSheet("font-size: 15pt; font-weight: 700;")
        by = QLabel(f"by {AUTHOR}")
        by.setStyleSheet("color: palette(placeholder-text);")
        brand.addWidget(name)
        brand.addWidget(by)
        hl.addLayout(brand)
        hl.addSpacing(24)
        self.stat_run = StatBlock("Running", "Accounts running now / all your accounts.")
        self.stat_cpu = StatBlock("CPU", "CPU used by everything Cellar runs for your accounts: their Sober clients,\n"
                                         "network helpers and invisible screens. 100% = every core of this PC busy.")
        self.stat_mem = StatBlock("Memory", "Memory used by the same, from the kernel's own accounting\n"
                                            "(file cache the kernel can drop at once is not counted).")
        for b in (self.stat_run, self.stat_cpu, self.stat_mem):
            hl.addWidget(b)
            hl.addSpacing(16)
        hl.addStretch(1)
        self.st_multi = QLabel()
        self.st_multi.setTextFormat(Qt.RichText)
        self.st_multi.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hl.addWidget(self.st_multi)
        return h

    def update_header(self, alive: Optional[List[Instance]] = None):
        s = store.settings
        ok, why = sober.multi_instance_support()
        if not sober.sober_installed():
            t = "<span style='color:#f85149'>Sober is not installed</span>"
        elif s.multi_instance and ok:
            t = "<span style='color:#3fb950'>Multi-instance: ON</span>"
        elif s.multi_instance:
            t = f"<span style='color:#d29922'>Multi-instance: unavailable</span><br><small>{why}</small>"
        else:
            t = "Multi-instance: off<br><small>one Sober at a time</small>"
        if self.kwin is None or not self.kwin.available():
            t += "<br><small>window layout off (needs KDE Plasma)</small>"
        self.st_multi.setText(t)
        if alive is None:
            alive = self.launcher.alive_instances()
        n = len(alive)
        in_bg = sum(1 for i in alive if i.screen)
        self.stat_run.set(f"{n} / {len(store.accounts)}",
                          "nothing running" if not n else f"{in_bg} in the background" if in_bg else "in windows")
        if self.tray:
            self.tray.setToolTip(f"{APP_NAME} - {n} running")

    def update_usage(self, alive: List[Instance]):
        if not usage.available():
            self.stat_cpu.set("-", "needs cgroup v2")
            self.stat_mem.set("-", "needs cgroup v2")
            return
        cores, mem = self.sampler.sample(usage.groups_for(alive))
        ncpu = os.cpu_count() or 1
        if cores is None:
            self.stat_cpu.set("...", "measuring")
        else:
            self.stat_cpu.set(f"{cores / ncpu * 100:.0f}%", f"{cores:.1f} of {ncpu} cores")
        self.stat_mem.set(_size(mem), f"about {_size(mem / len(alive))} each" if alive else "")

    def tick(self):
        alive = self.update_running()
        if self.isVisible():
            self.update_usage(alive)
        try:
            self.windows_page.auto_tick()
            if self.isVisible() and self.tabs.currentWidget() is self.windows_page:
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
        if v and v.isVisible() and v.inst is inst:
            v.raise_()
            v.activateWindow()
            return
        v = ScreenViewer(self, inst, self.log, lambda: self.macros_page.load())
        self.viewers[inst.account.id] = v
        v.show()

    def anti_afk_now(self):
        # background accounts: straight over their own screen - no focus change, works without KWin
        bg_insts = [i for i in self.launcher.alive_instances() if i.screen]
        if bg_insts:
            act = store.settings.anti_afk_action
            bg(lambda: sum(background.poke(i.screen, act) for i in bg_insts if not i.macro),
               done=lambda n: n and self.log(f"Anti-AFK: poked {n} background account(s)."))
        if not self.kwin or not self.kwin.available():
            if bg_insts:
                return
            self.log("Anti-AFK needs KWin (KDE Plasma) to focus the windows.")
            return
        ours = {i.tracker for i in self.launcher.alive_instances()}
        ids = [w.id for w in self.kwin.windows() if sober.tracker_of_pid(w.pid) in ours]
        if not ids:
            return
        n = antiafk.pulse(self.kwin, ids, self.log)
        if n:
            self.log(f"Anti-AFK: poked {n} window(s).")

    # ================================================================ startup
    def startup(self):
        s = store.settings
        self.log(f"{APP_NAME} {__version__} by {AUTHOR} - data in {paths.DATA_DIR}")
        store.apply_main_full_quality()
        for n in store.notices:
            self.log(n)
        store.notices.clear()
        if not s.sober.initialized:
            main = sober.main_sober_settings()
            for k in ("use_opengl", "graphics_optimization_mode", "enable_gamemode", "close_on_leave",
                      "discord_rpc_enabled", "server_location_indicator_enabled", "enable_hidpi"):
                if k in main:
                    setattr(s.sober, k, main[k])
            s.sober.initialized = True
            store.save_settings()
            self.perf_page.load()
        if not sober.sober_installed():
            self.log("Sober is not installed. Install it with:  flatpak install flathub org.vinegarhq.Sober")
        elif s.multi_instance and not sober.multi_instance_support()[0]:
            self.log("Multi-instance needs 'pasta' (package passt). Until it is installed only one window can run at a time.")
        if self.kwin is None or not self.kwin.available():
            self.log("KWin not found: the Windows page (layouts) and anti-AFK need KDE Plasma.")
        self.launcher.adopt_running(self.log)
        if not store.accounts:
            self.log("No accounts yet - use 'Add account' (browser login, cookies, or import from your Sober).")
        if s.check_logins_at_startup and store.accounts:
            self.check_logins()
        self.fetch_avatars()
        self.presence_tick()
        if s.startup_preset:
            p = self.presets_page.find(s.startup_preset)
            if p:
                self.log(f"Running startup preset '{p.name}' in 4 seconds...")
                QTimer.singleShot(4000, lambda: self.presets_page.run(p))

    def check_logins(self):
        accs = [a for a in store.accounts if a.cookie]

        def work():
            out = []
            for a in accs:
                out.append((a, api.authenticated(a.cookie)))
                time.sleep(0.3)
            return out

        def done(results):
            lost = []
            for a, u in results:
                li = store.live(a)
                if u.valid:
                    li.cookie_bad = False
                    a.login_lost = False
                    if u.name and u.name != a.username:
                        a.username = u.name
                    a.display_name = u.display or a.display_name
                    if not a.user_id:
                        a.user_id = u.id
                elif u.locked:
                    li.locked = True
                elif "expired" in u.error.lower():
                    li.cookie_bad = True
                    if not a.login_lost:
                        lost.append(a.name)
                        a.login_lost = True
            store.save_accounts()
            self.model.refresh_status()
            if lost:
                self.log("Signed out by Roblox (log in again): " + ", ".join(lost))
                if self.isVisible():
                    warn(self, "Logins", "These accounts were signed out by Roblox and need a new login:\n\n" + "\n".join(lost))
            else:
                self.log(f"Startup check: {sum(1 for _, u in results if u.valid)} of {len(results)} login(s) valid.")
        bg(work, done=done)

    def fetch_avatars(self):
        ids = [a.user_id for a in store.accounts if a.user_id and not (paths.AVATAR_DIR / f"{a.user_id}.png").exists()]
        if not ids:
            return

        def work():
            urls = api.avatar_urls(ids)
            n = 0
            for uid, url in urls.items():
                data = api.download(url)
                if data:
                    (paths.AVATAR_DIR / f"{uid}.png").write_bytes(data)
                    n += 1
            return n

        def done(n):
            if n:
                self.model.forget_icons()
                self.model.reload()
                self.apply_sort()
        bg(work, done=done)

    # ================================================================ window / tray
    def toggle_visible(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def save_geometry(self):
        s = store.settings
        s.win_w, s.win_h = self.width(), self.height()
        s.split = self.hsplit.sizes() + self.vsplit.sizes()
        store.save_settings()

    def closeEvent(self, e):
        self.save_geometry()
        if not self._quitting and store.settings.close_to_tray and self.tray is not None:
            e.ignore()
            self.hide()
            if not getattr(self, "_told_tray", False):
                self._told_tray = True
                self.tray.showMessage(APP_NAME, "Still running in the tray (watcher, anti-AFK). Right-click the icon to quit.")
            return
        self.quit_app()

    def quit_app(self):
        self._quitting = True
        self.save_geometry()
        n = len(self.launcher.alive_instances())
        if n and self.isVisible() and ask(self, "Quit", f"{n} Sober window(s) started by this app are running.\n\n"
                                          "Close them too? (No = keep them running; they are picked up again next start.)"):
            self.launcher.stop_all(self.log)
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()
