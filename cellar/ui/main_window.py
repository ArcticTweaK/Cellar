"""Main window: account list on the left, pages on the right, log at the bottom."""

import os
import threading
from typing import Optional

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMenu, QPlainTextEdit, QPushButton, QSplitter,
                               QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, AUTHOR, __version__, log, paths, sober, store, theme, usage
from .. import wm
from ..models import Account
from ..launcher import Launcher
from .accounts_model import ACCOUNT_ROLE, AccountFilter, AccountModel
from .common import app_icon, ask, btn, refresh_icons, row, ui
from .friends_page import FriendsPage
from .launch_pages import LaunchPage, ServersPage
from .home_page import HomePage
from .library_page import LibraryPage
from .profile_page import ProfilePage
from .macros_page import MacrosPage
from .my_sober_page import MySoberPage
from .presets_page import PresetsPage
from .settings_pages import HelpPage, PerfPage, SettingsPage
from .windows_page import WindowsPage
from .accounts import AccountsMixin
from .launching import LaunchMixin
from .live import LiveMixin
from .widgets import AccountCards, AccountChip, AccountTable, MiniStat, PlayingAs, page_frame


class MainWindow(AccountsMixin, LaunchMixin, LiveMixin, QMainWindow):
    def __init__(self, start_hidden: bool = False):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(store.settings.win_w, store.settings.win_h)
        self.launcher = Launcher()
        # window control: KWin on KDE Plasma, or Hyprland / Sway (wm.py) - None elsewhere
        self.kwin = wm.pick()
        self.launching = False
        self.cancel: Optional[threading.Event] = None
        self._watcher_busy = False
        self._presence_busy = False
        self._quitting = False

        # ---------------- left: accounts
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 6, 0)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search accounts...")
        self.search.setClearButtonEnabled(True)
        self.group_filter = QComboBox()
        self.group_filter.setMinimumWidth(130)
        self.sort = QComboBox()
        for k, label in (("Manual", "Your order"), ("Name", "Name"), ("Status", "Status"), ("Last", "Last used"), ("Group", "Group"),
                         ("Usage", "Memory use")):
            self.sort.addItem(label, k)
        top.addWidget(self.search, 1)
        top.addWidget(self.group_filter)
        top.addWidget(self.sort)
        self.view_btns = QButtonGroup(self)
        for i, (name, tip) in enumerate((("Cards", "Accounts as cards"), ("Table", "Accounts as a table"))):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("seg")
            b.setToolTip(tip)
            self.view_btns.addButton(b, i)
            top.addWidget(b)
        lv.addLayout(top)

        self.model = AccountModel()
        self.proxy = AccountFilter()
        self.proxy.setSourceModel(self.model)
        self.table = AccountTable()
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
        h.resizeSection(3, 104)                         # Usage
        h.resizeSection(4, 130)                         # Game
        h.setSectionResizeMode(5, QHeaderView.ResizeToContents)     # Last used: never cut off
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.doubleClicked.connect(lambda *_: self.launch_selected())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.on_selection())
        self.cards = AccountCards()
        self.cards.setModel(self.proxy)
        self.cards.setSelectionModel(self.table.selectionModel())      # one selection for both views
        self.cards.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cards.customContextMenuRequested.connect(lambda pos: self.context_menu(pos, self.cards))
        # cards are the "people" view: double-click opens the account's profile (the table keeps launch; Enter
        # launches in both)
        self.cards.doubleClicked.connect(lambda idx: idx.data(ACCOUNT_ROLE) and self.show_profile(idx.data(ACCOUNT_ROLE)))
        self.cards.setToolTip("Double-click an account for its profile · Enter launches the selected accounts")
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.cards)
        self.list_stack.addWidget(self.table)
        self.view_btns.idClicked.connect(self.set_list_view)
        lv.addWidget(self.list_stack, 1)

        add = QToolButton()
        add.setText("Add account")
        add.setObjectName("add_account")
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
        m.addAction("Import accounts file (Cellar export or Windows accounts.dat)...", self.add_windows_file)
        m.addAction("Export all accounts...", lambda: self.export_accounts(list(store.accounts)))
        m.addSeparator()
        m.addAction("Restore from a backup...", self.restore_backup)
        add.setMenu(m)
        self.add_menu = m
        bar = QHBoxLayout()
        bar.addWidget(add)
        bar.addWidget(btn("Edit", self.edit_selected))
        bar.addWidget(btn("Remove", self.remove_selected))
        bar.addWidget(btn("Profile", lambda: self.selected_accounts() and self.show_profile(self.selected_accounts()[0]),
                          tip="The selected account's profile page"))
        bar.addStretch(1)
        bar.addWidget(btn("Stop", self.stop_selected, tip="Close the selected accounts' Roblox windows"))
        bar.addWidget(btn("Stop all", self.stop_all, tip="Close every Roblox window Cellar started (Ctrl+Shift+S)"))
        lv.addLayout(bar)

        # ---------------- pages
        self.home_page = HomePage(self)
        self.library_page = LibraryPage(self)
        self.profile_page = ProfilePage(self)
        self.launch_page = LaunchPage(self)
        self.servers_page = ServersPage(self)
        self.windows_page = WindowsPage(self)
        self.perf_page = PerfPage(self)
        self.presets_page = PresetsPage(self)
        self.macros_page = MacrosPage(self)
        self.friends_page = FriendsPage(self)
        self.settings_page = SettingsPage(self)
        self.my_sober_page = MySoberPage(self)
        self.help_page = HelpPage(self)
        self.viewers = {}

        # Accounts = the account list and the launch panel side by side (the power-user screen)
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.addWidget(left)
        self.hsplit.addWidget(self.launch_page)
        self.hsplit.setStretchFactor(0, 1)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setSizes(store.settings.split[:2] if len(store.settings.split) >= 2 else [620, 620])
        self.accounts_page = page_frame("Accounts", "Select accounts (Ctrl / Shift for several), choose where they "
                                        "go, and launch.", self.hsplit)

        # Activity = the log (the status line at the bottom shows its newest line)
        self.logview = QPlainTextEdit()
        self.logview.setObjectName("log")
        self.logview.setFont(theme.mono_font(max(7.5, self.font().pointSizeF() - 1)))
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(3000)
        act = QWidget()
        av = QVBoxLayout(act)
        av.setContentsMargins(0, 0, 0, 0)
        av.addWidget(self.logview, 1)
        av.addWidget(row(btn("Copy", lambda: QGuiApplication.clipboard().setText(self.logview.toPlainText())),
                         btn("Open log file", lambda: sober.open_folder(paths.LOG_FILE.parent)),
                         btn("Clear", self.logview.clear)))
        self.activity_page = page_frame("Activity", "Everything Cellar did, newest at the bottom.", act)

        # name, icon, page, where it lives: "main" = a big tab in the top bar, "tools" = the TOOLS menu,
        # "corner" = an icon at the top right
        self.nav_items = [
            ("Home", "house", self.home_page, "main"),
            ("Library", "square-stack", self.library_page, "main"),
            ("Accounts", "user-round", self.accounts_page, "main"),
            ("Friends", "users", page_frame("Friends", "", self.friends_page), "main"),
            ("Servers", "server", page_frame("Servers", "", self.servers_page), "tools"),
            ("Presets", "bookmark", page_frame("Presets", "", self.presets_page), "tools"),
            ("Macros", "keyboard", page_frame("Macros", "", self.macros_page), "tools"),
            ("Windows", "layout-grid", page_frame("Windows", "", self.windows_page), "tools"),
            ("Performance", "gauge", page_frame("Performance", "", self.perf_page), "tools"),
            ("My Sober", "gamepad-2", page_frame("My Sober", "", self.my_sober_page), "tools"),
            ("Settings", "settings", page_frame("Settings", "", self.settings_page), "corner"),
            ("Help", "circle-help", page_frame("Help", "", self.help_page), "corner"),
            ("Activity", "activity", self.activity_page, "corner"),
            ("Profile", "user-round", self.profile_page, "hidden"),         # opened from an account / the chip
        ]
        self.tabs = QStackedWidget()            # named tabs: the rest of the code switches pages through it
        for _, _, page, _ in self.nav_items:
            self.tabs.addWidget(page)
        self.tabs.currentChanged.connect(self._tab_changed)
        self._history, self._hpos, self._hjump = [0], 0, False

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(24, 16, 24, 8)
        bv.addWidget(self.tabs, 1)
        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_topbar())
        cv.addWidget(body, 1)
        cv.addWidget(self._build_bottombar())
        self.setCentralWidget(central)
        self.me.set_account(self.home_page.home_account())
        self.sampler = usage.Sampler()

        self.addAction(QAction(self, shortcut=QKeySequence.Find, triggered=lambda: self.search.setFocus()))
        self.addAction(QAction(self, shortcut=QKeySequence.Delete, triggered=self.remove_selected))
        # Enter launches only from the account list (it confirms dialogs / fields everywhere else)
        for view in (self.table, self.cards):
            for key in ("Return", "Enter"):
                a = QAction(view, shortcut=QKeySequence(key), triggered=self.launch_selected)
                a.setShortcutContext(Qt.WidgetShortcut)
                view.addAction(a)
        for key, fn in (("F2", self.edit_selected), ("Ctrl+Shift+S", self.stop_all), ("Ctrl+N", self.add_browser),
                        ("Ctrl+A", lambda: self.table.selectAll()), ("Ctrl+Shift+W", self.open_screen_wall),
                        ("F5", self.presence_tick), ("Ctrl+K", self.open_palette), ("Ctrl+P", self.open_palette),
                        ("Alt+Left", self.go_back), ("Alt+Right", self.go_forward)):
            self.addAction(QAction(self, shortcut=QKeySequence(key), triggered=fn))
        for n in range(1, 11):          # Ctrl+1 ... Ctrl+0 = the first ten pages (sidebar order)
            self.addAction(QAction(self, shortcut=QKeySequence(f"Ctrl+{n % 10}"),
                                   triggered=lambda _=False, i=n - 1: self.tabs.setCurrentIndex(i)))

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
            tm.addAction("Screen wall", self.open_screen_wall)
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
        self.t_friends = QTimer(self, timeout=self.friends_tick)
        self.t_friends.start(60000)
        self.t_logs = QTimer(self, timeout=self.log_tick)     # Roblox logs: joins and kicks within seconds
        self.t_logs.start(4000)
        self._logs_busy = False
        self.launcher.notify = lambda kind, inst, text: ui(lambda: self.desktop_notify(kind, text))
        self.launcher.on_join = lambda inst, place, job: ui(lambda: self.joined(inst, place, job))
        self.t_updates = QTimer(self, timeout=lambda: (self.check_updates(), self.refresh_versions()))  # runs for days
        self.t_updates.start(6 * 3600 * 1000)
        self.restart_timers()

        self.refresh_groups()
        self.restore_ui_state()
        self.refresh_accounts()
        self.update_header()
        QTimer.singleShot(300, self.startup)

    def log(self, msg: str) -> None:
        """Thread-safe."""
        log.write(msg)

    def _append_log(self, line: str, replace: bool) -> None:
        fm = self.status_line.fontMetrics()
        self.status_line.setText(fm.elidedText(line, Qt.ElideRight, max(200, self.status_line.width() - 24)))
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
        if self._hjump:
            self._hjump = False
        elif self._history[self._hpos] != i:
            del self._history[self._hpos + 1:]
            self._history.append(i)
            self._history = self._history[-50:]
            self._hpos = len(self._history) - 1
        self._nav_icons()
        if self.tabs.widget(i) is self.windows_page:
            self.windows_page.refresh()
        elif self.tabs.widget(i) is self.settings_page:
            self.settings_page.update_status()
        elif self.tabs.widget(i) is self.my_sober_page and not self.my_sober_page.dirty:
            self.my_sober_page.load()           # Sober's own settings menu may have changed the file

    def reload_pages(self):
        for p in (self.launch_page, self.windows_page, self.perf_page, self.settings_page):
            p.load()
        self.restart_timers()

    def apply_theme(self, key: str):
        """Switches the theme right away (Settings > Appearance)."""
        store.settings.theme = key
        store.save_settings()
        theme.apply(key)
        self.update_header()
        self.model.refresh_status()
        self.table.viewport().update()
        self.on_selection()
        self.settings_page.update_status()
        self.windows_page.preview.update()
        self._nav_icons()
        refresh_icons()
        self.playing_as.update()
        self.log(f"Theme: {theme.current().name}.")

    def restart_timers(self):
        s = store.settings
        self.t_presence.start(max(15, s.presence_sec) * 1000) if s.show_presence else self.t_presence.stop()
        self.t_watcher.start(max(15, s.watcher_sec) * 1000)
        self.t_afk.start(max(1, s.anti_afk_min) * 60000) if s.anti_afk else self.t_afk.stop()


    # ---------------------------------------------------------------- header
    def _build_topbar(self) -> QWidget:
        """Back / forward, the big section tabs (TOOLS = a menu of the power-user pages), and at the right the
        update button, Activity / Settings / Help and the Home account."""
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 8, 14, 0)
        h.setSpacing(4)
        self.back_btn = QPushButton()
        self.fwd_btn = QPushButton()
        for b, ic, fn, tip in ((self.back_btn, "chevron-left", self.go_back, "Back (Alt+Left)"),
                               (self.fwd_btn, "chevron-right", self.go_forward, "Forward (Alt+Right)")):
            b.setObjectName("navarrow")
            b.setToolTip(tip)
            b.setIconSize(QSize(20, 20))
            b.clicked.connect(fn)
            h.addWidget(b, 0, Qt.AlignVCenter)
        h.addSpacing(8)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(30, 30))
        h.addWidget(logo, 0, Qt.AlignVCenter)
        name = QLabel(APP_NAME)
        name.setObjectName("brand")
        h.addWidget(name, 0, Qt.AlignVCenter)
        h.addSpacing(22)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(False)
        self.nav_buttons = []                   # (button, icon name, page index) - corner ones have icons
        tools = QMenu(self)
        self.tools_btn = QPushButton("TOOLS")
        for i, (text, icon_name, page, where) in enumerate(self.nav_items):
            if where == "main":
                b = QPushButton(text.upper())
                b.setObjectName("topnav")
                b.setCheckable(True)
                b.clicked.connect(lambda _=False, page=page: self.show_page(page))
                self.nav_buttons.append((b, "", i))
                h.addWidget(b)
            elif where == "tools":
                a = tools.addAction(text, lambda page=page: self.show_page(page))
                a.setData(icon_name)
        tools.addSeparator()
        tools.addAction("Screen wall", self.open_screen_wall)
        self.tools_menu = tools
        self.tools_btn.setObjectName("topnav")
        self.tools_btn.setCheckable(True)
        self.tools_btn.clicked.connect(lambda: (self.tools_btn.setChecked(self._on_tool_page()),
                                                tools.exec(self.tools_btn.mapToGlobal(
                                                    self.tools_btn.rect().bottomLeft()))))
        h.addWidget(self.tools_btn)
        h.addStretch(1)

        self.versions = ""          # "Sober 1.x · Roblox 2.x", filled in by startup()
        self.update_btn = btn("", self.show_update, primary=True)
        self.update_btn.setVisible(False)
        self.new_release = None
        h.addWidget(self.update_btn, 0, Qt.AlignVCenter)
        for i, (text, icon_name, page, where) in enumerate(self.nav_items):
            if where == "corner":
                b = QPushButton()
                b.setObjectName("corner")
                b.setCheckable(True)
                b.setToolTip(text)
                b.setIconSize(QSize(20, 20))
                b.clicked.connect(lambda _=False, page=page: self.show_page(page))
                self.nav_buttons.append((b, icon_name, i))
                h.addWidget(b, 0, Qt.AlignVCenter)
        h.addSpacing(8)
        self.me = AccountChip()
        self.me.clicked.connect(self._me_menu)
        h.addWidget(self.me, 0, Qt.AlignVCenter)
        self._nav_icons()
        return bar

    def _build_bottombar(self) -> QWidget:
        """+ Add account, the newest message, the live numbers, who plays and friends online."""
        bar = QWidget()
        bar.setObjectName("bottombar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 3, 12, 3)
        h.setSpacing(14)
        add = QPushButton("  Add account")
        add.setObjectName("barbtn")
        add.setIcon(theme.icon("plus", "muted"))
        add.clicked.connect(lambda: self.add_menu.exec(add.mapToGlobal(add.rect().topLeft())
                                                        - QPoint(0, self.add_menu.sizeHint().height())))
        self._bar_add = add
        h.addWidget(add)
        self.status_line = QPushButton("")
        self.status_line.setObjectName("statusline")
        self.status_line.setCursor(Qt.PointingHandCursor)
        self.status_line.setToolTip("The newest message - click for all of them (Activity)")
        self.status_line.clicked.connect(lambda: self.show_page(self.activity_page))
        h.addWidget(self.status_line, 1)
        self.stat_run = MiniStat("Running", "Accounts running now / all your accounts.")
        self.stat_cpu = MiniStat("CPU", "CPU used by everything Cellar runs for your accounts: their Sober clients,\n"
                                        "network helpers and invisible screens. 100% = every core of this PC busy.")
        self.stat_mem = MiniStat("Memory", "Memory used by the same, from the kernel's own accounting\n"
                                           "(file cache the kernel can drop at once is not counted).")
        for st in (self.stat_run, self.stat_cpu, self.stat_mem):
            h.addWidget(st)
        self.st_multi = QLabel()
        self.st_multi.setObjectName("pill")
        self.st_multi.setToolTip("Multi-instance gives every account its own isolated Sober, so many can run at "
                                 "once (Settings).")
        h.addWidget(self.st_multi)
        self.st_multi_sub = QLabel()            # its text goes into the pill's tooltip (no room in the bar)
        self.st_multi_sub.setVisible(False)
        self.playing_as = PlayingAs(compact=True)
        self.playing_as.clicked.connect(lambda: self.show_page(self.accounts_page))
        h.addWidget(self.playing_as)
        self.friends_btn = QPushButton("Friends")
        self.friends_btn.setObjectName("barbtn")
        self.friends_btn.setIcon(theme.icon("users", "muted"))
        self.friends_btn.clicked.connect(lambda: self.show_page(self.nav_items[3][2]))
        h.addWidget(self.friends_btn)
        return bar

    def _on_tool_page(self) -> bool:
        i = self.tabs.currentIndex()
        return self.nav_items[i][3] == "tools"

    def _nav_icons(self):
        i = self.tabs.currentIndex()
        for b, name, idx in self.nav_buttons:
            b.setChecked(idx == i)
            if name:
                b.setIcon(theme.icon(name, "accent" if idx == i else "muted"))
        self.tools_btn.setChecked(self._on_tool_page())
        for a in self.tools_menu.actions():
            if a.data():
                a.setIcon(theme.icon(a.data(), "text"))
        self.back_btn.setIcon(theme.icon("chevron-left", "text" if self._hpos > 0 else "muted"))
        self.fwd_btn.setIcon(theme.icon("chevron-right", "text" if self._hpos < len(self._history) - 1 else "muted"))
        self.back_btn.setEnabled(self._hpos > 0)
        self.fwd_btn.setEnabled(self._hpos < len(self._history) - 1)
        if hasattr(self, "_bar_add"):
            self._bar_add.setIcon(theme.icon("plus", "muted"))
            self.friends_btn.setIcon(theme.icon("users", "muted"))

    def go_back(self):
        if self._hpos > 0:
            self._hpos -= 1
            self._hjump = True
            self.tabs.setCurrentIndex(self._history[self._hpos])

    def go_forward(self):
        if self._hpos < len(self._history) - 1:
            self._hpos += 1
            self._hjump = True
            self.tabs.setCurrentIndex(self._history[self._hpos])

    def _me_menu(self):
        m = QMenu(self)
        a = self.home_page.home_account()
        if a:
            m.addAction(f"View {a.name}'s profile", lambda: self.show_profile(a))
            m.addSeparator()
        sub = m.addMenu("Home account (friends, favourites)")
        for acc in [x for x in store.accounts if x.user_id and x.cookie]:
            act = sub.addAction(acc.name, lambda acc=acc: self.set_home_account(acc))
            act.setCheckable(True)
            act.setChecked(a is not None and acc.id == a.id)
        m.addAction("Add account...", self.add_browser)
        m.addSeparator()
        m.addAction("Settings", lambda: self.show_page(self.settings_page.parentWidget()))
        m.exec(self.me.mapToGlobal(self.me.rect().bottomLeft()))

    def set_home_account(self, a: Account):
        i = self.home_page.acc.findData(a.id)
        if i >= 0:
            self.home_page.acc.setCurrentIndex(i)
        self.me.set_account(a)

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
            self.log("No window control found: the Windows page (layouts) and anti-AFK for normal windows need KDE "
                     "Plasma, Hyprland or Sway.")
        self.launcher.adopt_running(self.log)
        if not store.accounts:
            self.log("No accounts yet - use 'Add account' (browser login, cookies, or import from your Sober).")
        if not s.first_run_done:
            if store.accounts:          # an install from before the setup existed: nothing to set up
                s.first_run_done = True
                store.save_settings()
            else:
                QTimer.singleShot(300, self.run_setup)
        if s.check_logins_at_startup and store.accounts:
            self.check_logins()
        self.fetch_avatars()
        self.presence_tick()
        self.whats_new()
        self.check_updates()
        self.refresh_versions()
        if s.startup_preset:
            p = self.presets_page.find(s.startup_preset)
            if p:
                self.log(f"Running startup preset '{p.name}' in 4 seconds...")
                QTimer.singleShot(4000, lambda: self.presets_page.run(p))

    # ------------------------------------------------------------ updates

    def run_setup(self):
        from .setup_wizard import SetupWizard
        if not self.isVisible():
            self.show()
        SetupWizard(self).exec()
        self.settings_page.update_status()

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
        s.split = self.hsplit.sizes()
        s.ui_tab = self.tabs.currentIndex()
        s.ui_sort = self.sort.currentData() or "Manual"
        s.ui_header = bytes(self.table.horizontalHeader().saveState().toBase64()).decode()
        store.save_settings()

    def restore_ui_state(self):
        s = store.settings
        self.set_list_view(1 if s.accounts_view == "table" else 0)
        i = self.sort.findData(s.ui_sort)
        if i >= 0:
            self.sort.setCurrentIndex(i)
        if 0 <= s.ui_tab < self.tabs.count():
            self.tabs.setCurrentIndex(s.ui_tab)
        if s.ui_header:
            from PySide6.QtCore import QByteArray
            self.table.horizontalHeader().restoreState(QByteArray.fromBase64(s.ui_header.encode()))

    def set_list_view(self, i: int):
        """0 = cards, 1 = table (remembered)."""
        self.list_stack.setCurrentIndex(i)
        self.view_btns.button(i).setChecked(True)
        store.settings.accounts_view = "table" if i else "cards"
        store.save_settings()

    def restart_app(self):
        """Starts a fresh Cellar a moment after this one quits (running accounts keep running and are picked up
        again). The new process inherits this one's environment, so it runs the same way (Nix wrapper, dev shell...)."""
        import shlex
        import subprocess
        import sys
        a0 = sys.argv[0]
        argv = ([sys.executable, "-m", "cellar"] if a0.endswith("__main__.py") or not os.path.isfile(a0)
                else [sys.executable, a0])
        argv += [x for x in sys.argv[1:] if x == "--minimized"]
        subprocess.Popen(["sh", "-c", "sleep 1.5; exec " + shlex.join(argv)], cwd=os.getcwd(),
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.hide()                     # hidden: quitting does not ask about the running accounts (they stay)
        self.quit_app()

    def open_palette(self):
        from .palette import Palette
        Palette(self).exec()

    def mousePressEvent(self, e):           # the mouse's own back / forward buttons
        if e.button() == Qt.BackButton:
            self.go_back()
        elif e.button() == Qt.ForwardButton:
            self.go_forward()
        else:
            super().mousePressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_toasts()

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
        for i in self.launcher.snapshot():      # nobody wakes them up once Cellar is gone
            if i.frozen and i.pid:
                i.frozen = False
                sober.freeze(i.pid, False)
        n = len(self.launcher.alive_instances())
        if n and self.isVisible() and ask(self, "Quit", f"{n} Sober window(s) started by this app are running.\n\n"
                                          "Close them too? (No = keep them running; they are picked up again next start.)"):
            self.launcher.stop_all(self.log)
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()
