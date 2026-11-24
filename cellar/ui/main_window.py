"""Main window, the Roblox MultiHub layout (DESIGN.md): live numbers at the top, the account list always on the
left, the tools as tabs on the right (Launch first), the log across the bottom."""

import os
import threading
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMenu, QPlainTextEdit, QPushButton, QSplitter,
                               QStackedWidget, QSystemTrayIcon, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, AUTHOR, __version__, log, paths, sober, store, theme, usage
from .. import wm
from ..launcher import Launcher
from .accounts_model import ACCOUNT_ROLE, AccountFilter, AccountModel
from .common import app_icon, ask, btn, refresh_icons, row, ui
from .launch_pages import LaunchPage
from .macros_page import MacrosPage
from .my_sober_page import MySoberPage
from .presets_page import PresetsPage
from .settings_pages import AutomationSettings, HelpPage, PerfPage, SettingsPage
from .windows_page import WindowsPage
from .accounts import AccountsMixin
from .launching import LaunchMixin
from .live import LiveMixin
from .widgets import AccountCards, AccountTable, StatBlock, eyebrow


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
        self.cards.doubleClicked.connect(lambda idx: idx.data(ACCOUNT_ROLE) and self.launch_selected())
        self.cards.setToolTip("Double-click or Enter launches the selected accounts · right-click for more · "
                              "drag accounts to rearrange them")
        for view in (self.table, self.cards):
            view.reorder = self.drop_reorder
            view.can_reorder = lambda: self.sort.currentData() == "Manual"
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
        bar.addWidget(btn("Details", self.details_selected,
                          tip="Robux, Premium, account age and login state of the selected account(s)"))
        bar.addStretch(1)
        bar.addWidget(btn("Launch", self.launch_selected, icon="play", primary=True,
                          tip="Launch the selected accounts where the Launch tab says (Enter)"))
        bar.addWidget(btn("Stop", self.stop_selected, tip="Close the selected accounts' Roblox windows"))
        bar.addWidget(btn("Stop all", self.stop_all, tip="Close every Roblox window Cellar started (Ctrl+Shift+S)"))
        lv.addLayout(bar)

        # ---------------- pages
        self.launch_page = LaunchPage(self)
        self.windows_page = WindowsPage(self)
        self.perf_page = PerfPage(self)
        self.presets_page = PresetsPage(self)
        self.macros_page = MacrosPage(self)
        self.auto_settings = AutomationSettings(self)
        self.settings_page = SettingsPage(self)
        self.my_sober_page = MySoberPage(self)
        self.help_page = HelpPage(self)
        self.viewers = {}

        # the log, across the bottom (filter / search / copy above it)
        self.logview = QPlainTextEdit()
        self.logview.setObjectName("log")
        self.logview.setFont(theme.mono_font(max(7.5, self.font().pointSizeF() - 1)))
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(3000)
        self.logbox = logbox = QWidget()
        av = QVBoxLayout(logbox)
        av.setContentsMargins(0, 4, 0, 0)
        av.setSpacing(4)
        self._log_lines: list = []              # everything this session (the view may show a filtered part)
        self.log_filter = QComboBox()
        self.log_filter.addItem("Everything", "")
        self.log_filter.addItem("Problems only", "!")
        self.log_filter.currentIndexChanged.connect(self._refilter_log)
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Search the log...")
        self.log_search.setClearButtonEnabled(True)
        self.log_search.textChanged.connect(self._refilter_log)
        av.addWidget(row(eyebrow("Log"), self.log_filter, self.log_search,
                         btn("Copy", lambda: QGuiApplication.clipboard().setText(self.logview.toPlainText())),
                         btn("Open log file", lambda: sober.open_folder(paths.LOG_FILE.parent)),
                         btn("Clear", lambda: (self._log_lines.clear(), self.logview.clear())), stretch=False))
        av.addWidget(self.logview, 1)

        # the tools, as tabs next to the account list
        self.tabs = QTabWidget()
        self.tabs.setObjectName("tools")
        self.tab_pages = [("Launch", self.launch_page), ("Presets", self.presets_page), ("Macros", self.macros_page),
                          ("Anti-AFK && rejoin", self.auto_settings), ("Windows", self.windows_page),
                          ("My Sober", self.my_sober_page), ("Performance", self.perf_page),
                          ("Settings", self.settings_page), ("Help", self.help_page)]
        for name, page in self.tab_pages:
            self.tabs.addTab(page, name)
        self.tabs.currentChanged.connect(self._page_shown)
        self.accounts_page = left               # show_page(accounts_page) = the list (always on screen)
        # every place the command palette (Ctrl+K) can go to
        self.goto_items = [(name.replace("&&", "and"), page) for name, page in self.tab_pages] + [("Log", logbox)]

        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.addWidget(left)
        self.hsplit.addWidget(self.tabs)
        self.hsplit.setStretchFactor(0, 2)
        self.hsplit.setStretchFactor(1, 3)
        self.hsplit.setSizes(store.settings.split[:2] if len(store.settings.split) >= 2 else [600, 900])
        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(logbox)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setStretchFactor(1, 0)
        self.vsplit.setSizes(store.settings.split_v[:2] if len(store.settings.split_v) >= 2 else [760, 170])

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(10, 8, 10, 8)
        bv.addWidget(self.vsplit, 1)
        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_header())
        cv.addWidget(body, 1)
        self.setCentralWidget(central)
        self.setAcceptDrops(True)
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
                        ("F5", self.presence_tick), ("Ctrl+K", self.open_palette), ("Ctrl+P", self.open_palette)):
            self.addAction(QAction(self, shortcut=QKeySequence(key), triggered=fn))
        for n in range(1, 10):          # Ctrl+1 ... Ctrl+9 = the tabs
            self.addAction(QAction(self, shortcut=QKeySequence(f"Ctrl+{n}"),
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
        self.t_audio = QTimer(self, timeout=self.audio_tick)
        self.t_audio.start(5000)
        self.t_schedule = QTimer(self, timeout=self.schedule_tick)
        self.t_schedule.start(30000)
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

    _PROBLEM = ("error", "failed", "could not", "kicked", "lost connection", "unexpectedly", "signed out",
                "not found", "crash", "warning", "missing", "refused", "disconnected", "skipped")

    def _log_matches(self, line: str) -> bool:
        f, q = self.log_filter.currentData() or "", self.log_search.text().strip().lower()
        low = line.lower()
        if f == "!" and not any(w in low for w in self._PROBLEM):
            return False
        if f.startswith("@") and f"[{f[1:].lower()}]" not in low:
            return False
        return not q or q in low

    def _refilter_log(self, *_):
        cur = self.log_filter.currentData()
        names = sorted({a.name for a in store.accounts})
        if self.log_filter.count() != 2 + len(names):           # one entry per account
            self.log_filter.blockSignals(True)
            while self.log_filter.count() > 2:
                self.log_filter.removeItem(2)
            for n in names:
                self.log_filter.addItem(f"Only {n}", "@" + n)
            i = self.log_filter.findData(cur)
            self.log_filter.setCurrentIndex(i if i >= 0 else 0)
            self.log_filter.blockSignals(False)
        self.logview.setPlainText("\n".join(x for x in self._log_lines if self._log_matches(x)))
        self.logview.moveCursor(QTextCursor.End)

    def _append_log(self, line: str, replace: bool) -> None:
        if replace and self._log_lines:
            self._log_lines[-1] = line
        else:
            self._log_lines.append(line)
            del self._log_lines[:-3000]
        if not self._log_matches(line):
            return
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
        """Opens the tab a page is on (also a page inside a page). The account list and the log are always on
        screen, so for them this only makes sure the window shows."""
        w = page
        while w is not None:
            parent = w.parentWidget()
            if isinstance(parent, QStackedWidget) and isinstance(parent.parentWidget(), QTabWidget):
                parent.parentWidget().setCurrentWidget(w)
            w = parent
        if page is self.logbox:
            self.log_search.setFocus()

    def _page_shown(self, *_):
        """A tab was opened: refresh what may be stale."""
        if self.windows_page.isVisible():
            self.windows_page.refresh()
        if self.settings_page.isVisible():
            self.settings_page.update_status()
        if self.my_sober_page.isVisible() and not self.my_sober_page.dirty:
            self.my_sober_page.load()           # Sober's own settings menu may have changed the file

    def reload_pages(self):
        for p in (self.launch_page, self.windows_page, self.perf_page, self.settings_page, self.auto_settings):
            p.load()
        self.restart_timers()

    def apply_theme(self, key: str):
        """Switches the theme right away (Settings > Appearance)."""
        store.settings.theme = key
        store.save_settings()
        theme.apply(key)
        self.update_header()
        self.model.refresh_status()
        self.refresh_groups()                   # colour-tag swatches in the filter follow the theme
        self.table.viewport().update()
        self.on_selection()
        self.settings_page.update_status()
        self.windows_page.preview.update()
        refresh_icons()
        self.log(f"Theme: {theme.current().name}.")

    def restart_timers(self):
        s = store.settings
        self.t_presence.start(max(15, s.presence_sec) * 1000) if s.show_presence else self.t_presence.stop()
        self.t_watcher.start(max(15, s.watcher_sec) * 1000)
        self.t_afk.start(max(1, s.anti_afk_min) * 60000) if s.anti_afk else self.t_afk.stop()


    # ---------------------------------------------------------------- header
    def _build_header(self) -> QWidget:
        """Cellar, the live numbers (running / CPU / memory), and at the right the update button and the
        multi-instance state."""
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(28)
        brand = QHBoxLayout()
        brand.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(34, 34))
        brand.addWidget(logo)
        name = QLabel(APP_NAME)
        name.setObjectName("brand")
        brand.addWidget(name)
        h.addLayout(brand)
        self.stat_run = StatBlock("Running", "Accounts running now / all your accounts.")
        self.stat_cpu = StatBlock("CPU", "CPU used by everything Cellar runs for your accounts: their Sober clients,\n"
                                         "network helpers and invisible screens. 100% = every core of this PC busy.")
        self.stat_mem = StatBlock("Memory", "Memory used by the same, from the kernel's own accounting\n"
                                            "(file cache the kernel can drop at once is not counted).")
        for st in (self.stat_run, self.stat_cpu, self.stat_mem):
            h.addWidget(st)
        h.addStretch(1)
        self.versions = ""          # "Sober 1.x · Roblox 2.x", filled in by startup()
        self.update_btn = btn("", self.show_update, primary=True)
        self.update_btn.setVisible(False)
        self.new_release = None
        h.addWidget(self.update_btn, 0, Qt.AlignVCenter)
        self.st_multi = QLabel()
        self.st_multi.setObjectName("pill")
        self.st_multi.setToolTip("Multi-instance gives every account its own isolated Sober, so many can run at "
                                 "once (Settings).")
        h.addWidget(self.st_multi, 0, Qt.AlignVCenter)
        return bar

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
        s.split_v = self.vsplit.sizes()
        s.ui_sort = self.sort.currentData() or "Manual"
        s.ui_header = bytes(self.table.horizontalHeader().saveState().toBase64()).decode()
        store.save_settings()

    def restore_ui_state(self):
        s = store.settings
        self.set_list_view(1 if s.accounts_view == "table" else 0)
        i = self.sort.findData(s.ui_sort)
        if i >= 0:
            self.sort.setCurrentIndex(i)
        self.tabs.setCurrentIndex(0)            # always start on Launch
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

    # ---------------------------------------------------------------- drop files onto the window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        """Cookie files / pasted cookie text add accounts; an accounts file (.dat) is imported."""
        from pathlib import Path
        from .. import util
        md = e.mimeData()
        texts, dats = [], []
        for u in md.urls() if md.hasUrls() else []:
            f = Path(u.toLocalFile())
            try:
                if f.suffix.lower() == ".dat":
                    dats.append(f)
                elif f.is_file() and f.stat().st_size < 2 * 2**20:
                    texts.append(f.read_text(errors="replace"))
            except OSError:
                pass
        if md.hasText() and not md.hasUrls():
            texts.append(md.text())
        for f in dats:
            self.add_windows_file(str(f))
        cookies = list(dict.fromkeys(c for t in texts for c in util.extract_cookies(t)))
        if cookies:
            self.add_cookies(cookies)
        elif texts and not dats:
            self.toast("No Roblox cookies in what you dropped.", "warn")

    def open_palette(self):
        from .palette import Palette
        Palette(self).exec()

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
