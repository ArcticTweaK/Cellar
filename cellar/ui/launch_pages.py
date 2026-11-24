"""Launch and Servers pages."""

import random

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QLabel, QLineEdit, QRadioButton, QVBoxLayout,
                               QWidget, QCheckBox)

from .. import api, store, theme, util
from ..models import LaunchSpec
from ..specs import LaunchForm
from .common import bg, btn, chk, group, hint, row, spin
from .dialogs import GamePicker, ServerPicker, ServerTable


class LaunchPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        s = store.settings
        v = QVBoxLayout(self)

        self.sel = QLabel()
        self.sel.setObjectName("selection")
        self.sel.setWordWrap(True)
        v.addWidget(self.sel)

        g, f = group("Where should they go?")
        self.modes = QButtonGroup(self)
        self.rb_game = QRadioButton("Join a game  -  Roblox picks any public server")
        self.rb_job = QRadioButton("Join a specific server  -  put accounts into one exact server")
        self.rb_private = QRadioButton("Join a private server")
        self.rb_follow = QRadioButton("Follow a player")
        for i, rb in enumerate((self.rb_game, self.rb_job, self.rb_private, self.rb_follow)):
            self.modes.addButton(rb, i)
            rb.toggled.connect(lambda *_: self._mode_ui())

        self.place = QComboBox()
        self.place.setEditable(True)
        self.place.setMinimumWidth(260)
        self.place.lineEdit().setPlaceholderText("Place ID or roblox.com/games/... link")
        self.place.setToolTip("Paste a number such as 920587237 or a full roblox.com/games/... link. "
                              "Games you launched before are in the drop-down list.")
        self.job = QLineEdit(s.last_job_id)
        self.job.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        self.job.setMinimumWidth(300)
        self.private = QLineEdit(s.last_private)
        self.private.setPlaceholderText("...?privateServerLinkCode=...  or  roblox.com/share?code=...&type=Server")
        self.follow = QLineEdit(s.last_follow)
        self.follow.setPlaceholderText("Roblox username")
        self.b_random = btn("Random", self.pick_random, "Pick any open public server of the game above")
        self.b_pick = btn("Pick server...", self.pick_server, "Browse the running servers of the game above")

        f.addRow(self.rb_game)
        f.addRow("Game", row(self.place, btn("Search game...", self.search_game, icon="edit-find")))
        f.addRow(self.rb_job)
        f.addRow("Job ID", row(self.job, self.b_random, self.b_pick))
        f.addRow(self.rb_private)
        f.addRow("Link", self.private)
        f.addRow(self.rb_follow)
        f.addRow("Player", self.follow)
        v.addWidget(g)

        g, f = group("Launch options")
        self.delay = spin(0, 600, s.launch_delay_sec, self._delay, " s",
                          "Starting many clients at the same instant often makes some fail to load. 6-10 s is a good default.")
        f.addRow("Pause between accounts", self.delay)
        self.use_saved = chk("Use each account's own game when it has one", s.use_saved_per_account, self._use_saved,
                             "Accounts with their own game (Edit account) join it; the others use the choice above.")
        f.addRow(self.use_saved)
        f.addRow(btn("Save this game to the selected accounts", self.save_to_selected,
                     "Copies the Place ID (and Job ID for 'specific server') into every selected account."))
        v.addWidget(g)

        g, f = group("Go")
        self.b_launch = btn("Launch selected", self.mw.launch_selected, icon="play", primary=True)
        self.b_all = btn("Launch all listed", self.mw.launch_all_listed)
        self.b_stop = btn("Cancel", self.mw.stop_launch, tip="Stop a launch sequence that is still going")
        self.b_stop.setEnabled(False)
        f.addRow(row(self.b_launch, self.b_all, self.b_stop))
        self.queue = LaunchQueue(self.mw)
        f.addRow(self.queue)
        f.addRow(hint("Each account runs in its own isolated Sober profile (see Settings). "
                      "Windows are only moved by the Windows page."))
        v.addWidget(g)
        v.addStretch(1)

        {"Job": self.rb_job, "Private": self.rb_private, "Follow": self.rb_follow}.get(s.last_mode, self.rb_game).setChecked(True)
        self.refresh_recent()
        self.place.setCurrentText(s.last_place_id)
        self._mode_ui()
        self.update_selection([])

    # ------------------------------------------------------------
    def _delay(self, v):
        store.settings.launch_delay_sec = v
        store.save_settings()

    def _use_saved(self, v):
        store.settings.use_saved_per_account = v
        store.save_settings()

    def _mode_ui(self):
        self.place.setEnabled(self.rb_game.isChecked() or self.rb_job.isChecked())
        for w in (self.job, self.b_random, self.b_pick):
            w.setEnabled(self.rb_job.isChecked())
        self.private.setEnabled(self.rb_private.isChecked())
        self.follow.setEnabled(self.rb_follow.isChecked())

    def set_launching(self, on: bool):
        self.b_launch.setEnabled(not on)
        self.b_all.setEnabled(not on)
        self.b_stop.setEnabled(on)

    def update_selection(self, sel):
        if not sel:
            self.sel.setText(theme.span("warn", "●") + "&nbsp; No accounts selected - click accounts in the list "
                             + theme.span("muted", "(Ctrl / Shift for several)"))
        else:
            names = ", ".join(a.name for a in sel[:4]) + (f" ... (+{len(sel) - 4})" if len(sel) > 4 else "")
            self.sel.setText(theme.span("good", "●") + f"&nbsp; <b>{len(sel)} selected</b>"
                             + theme.span("muted", f"&nbsp; {names}"))

    def refresh_recent(self):
        keep = self.place.currentText()
        self.place.blockSignals(True)
        self.place.clear()
        for g in store.settings.recent:
            self.place.addItem(f"{g.place_id}  -  {g.name or '(unknown name)'}")
        self.place.setCurrentText(keep)
        self.place.blockSignals(False)

    def mode(self) -> str:
        return ("Job" if self.rb_job.isChecked() else "Private" if self.rb_private.isChecked()
                else "Follow" if self.rb_follow.isChecked() else "Game")

    def read_form(self) -> LaunchForm:
        """Snapshot of the form; also remembers it in the settings."""
        f = LaunchForm(self.mode(), self.place.currentText().strip(), self.job.text().strip(),
                       self.private.text().strip(), self.follow.text().strip())
        s = store.settings
        s.last_mode, s.last_place_id, s.last_job_id, s.last_private, s.last_follow = f.mode, f.place, f.job, f.private, f.follow
        store.save_settings()
        return f

    def load(self):
        s = store.settings
        {"Job": self.rb_job, "Private": self.rb_private, "Follow": self.rb_follow}.get(s.last_mode, self.rb_game).setChecked(True)
        self.place.setCurrentText(s.last_place_id)
        self.job.setText(s.last_job_id)
        self.private.setText(s.last_private)
        self.follow.setText(s.last_follow)
        for w, val in ((self.delay, s.launch_delay_sec),):
            w.blockSignals(True)
            w.setValue(val)
            w.blockSignals(False)
        self.use_saved.blockSignals(True)
        self.use_saved.setChecked(s.use_saved_per_account)
        self.use_saved.blockSignals(False)

    # ------------------------------------------------------------ actions
    def search_game(self):
        d = GamePicker(self, self.mw.any_cookie())
        if d.exec() and d.result:
            self.place.setCurrentText(str(d.result.place_id))
            if self.rb_private.isChecked() or self.rb_follow.isChecked():
                self.rb_game.setChecked(True)
            self.mw.log(f"Game selected: {d.result.name} ({d.result.place_id}).")
            self.mw.add_recent(d.result.place_id, d.result.name)

    def pick_server(self):
        pid = util.parse_place_id(self.place.currentText())
        if pid <= 0:
            self.mw.log("Choose a game first: type its Place ID or press 'Search game...'.")
            return
        d = ServerPicker(self, pid, self.mw.any_cookie())
        if d.exec() and d.result:
            self.job.setText(d.result)
            self.rb_job.setChecked(True)
            self.mw.log("Server selected: " + d.result)

    def pick_random(self):
        pid = util.parse_place_id(self.place.currentText())
        if pid <= 0:
            self.mw.log("Enter a Place ID first.")
            return
        self.mw.log(f"Looking up servers of place {pid}...")

        def done(sp):
            if sp.error:
                self.mw.log("Could not load servers: " + sp.error)
                return
            open_ = [x for x in sp.servers if x.playing < x.max]
            if not open_:
                self.mw.log("No joinable servers found for that place.")
                return
            pick = random.choice(open_)
            self.job.setText(pick.id)
            self.mw.log(f"Picked server {pick.id} ({pick.playing}/{pick.max} players).")
        bg(api.servers, pid, False, "", self.mw.any_cookie(), done=done)

    def save_to_selected(self):
        sel = self.mw.selected_accounts()
        if not sel:
            self.mw.log("Select one or more accounts first.")
            return
        pid = util.parse_place_id(self.place.currentText())
        for a in sel:
            a.saved_place_id = str(pid) if pid else ""
            a.game_link = f"https://www.roblox.com/games/{pid}" if pid else ""
            a.saved_job_id = self.job.text().strip() if self.rb_job.isChecked() else ""
        store.save_accounts()
        self.mw.refresh_accounts()
        self.mw.log(f"Saved Place {pid or '(none)'} to {len(sel)} account(s).")


class ServersPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.cursor = ""
        self.all = []
        v = QVBoxLayout(self)
        v.addWidget(hint("Browse the public servers of a game and put the selected accounts into the <b>same</b> server."))
        self.place = QLineEdit(store.settings.last_place_id)
        self.place.setPlaceholderText("Place ID or game link")
        self.place.setMinimumWidth(320)
        self.place.returnPressed.connect(lambda: self.load(False))
        self.order = QComboBox()
        self.order.addItem("Most players first", False)
        self.order.addItem("Fewest players first", True)
        self.hide_full = QCheckBox("Hide full servers")
        self.hide_full.setChecked(True)
        self.hide_full.toggled.connect(lambda *_: self._show())
        v.addWidget(row(QLabel("Game"), self.place, btn("Search game...", self.search_game, icon="search")))
        self.game_name = QLabel("")
        self.game_name.setObjectName("page_sub")
        v.addWidget(self.game_name)
        self.auto = QCheckBox("Refresh every 30 s")
        self.auto.toggled.connect(lambda on: self.timer.start(30000) if on else self.timer.stop())
        self.timer = QTimer(self, timeout=lambda: self.isVisible() and self.load(False, quiet=True))
        v.addWidget(row(self.order, btn("Load servers", lambda: self.load(False), icon="refresh-cw"),
                        btn("Load more", lambda: self.load(True)), self.hide_full, self.auto))
        v.addWidget(row(QLabel("Quick join:"),
                        btn("Emptiest server", lambda: self.quick("empty"),
                            tip="The server with the fewest players that still has room for everyone you send"),
                        btn("Busy server with room for everyone", lambda: self.quick("busy"),
                            tip="The fullest server that still has a free slot for each account you send")))
        self.table = ServerTable()
        self.table.doubleClicked.connect(lambda *_: self.join())
        v.addWidget(self.table, 1)
        self.status = QLabel("")
        v.addWidget(self.status)
        v.addWidget(row(btn("Join", self.join, icon="play", primary=True,
                            tip="The selected accounts join this server (or pick who, when none is selected)"),
                        btn("Use on Accounts page", self.use_on_launch),
                        btn("Copy Job ID", self.copy_job),
                        btn("History...", lambda: HistoryDialog(self.mw).exec(),
                            tip="Servers your accounts joined - rejoin one")))

    def search_game(self):
        d = GamePicker(self, self.mw.any_cookie())
        if d.exec() and d.result:
            self.place.setText(str(d.result.place_id))
            self.load(False)

    def load(self, more: bool, quiet: bool = False, then=None):
        pid = util.parse_place_id(self.place.text())
        if pid <= 0:
            self.status.setText("Enter a Place ID or game link.")
            return
        if more and not self.cursor:
            self.status.setText("No more servers.")
            return
        if not quiet:
            self.status.setText("Loading...")
        if pid != getattr(self, "_named", 0):
            self._named = pid
            self.game_name.setText("")
            bg(api.place_name, pid, done=lambda n: self.game_name.setText(n or ""))

        def done(sp):
            if sp.error:
                self.status.setText(sp.error)
                return
            self.cursor = sp.next
            self.all = (self.all if more else []) + sp.servers
            self._show()
            if then:
                then()
        bg(api.servers, pid, bool(self.order.currentData()), self.cursor if more else "", self.mw.any_cookie(), done=done)

    def quick(self, mode: str):
        """Picks a server for the accounts you send and joins it (loads the right list first)."""
        want_asc = mode == "empty"
        if bool(self.order.currentData()) != want_asc or not self.all:
            self.order.setCurrentIndex(self.order.findData(want_asc))
            return self.load(False, then=lambda: self.quick(mode))
        n = max(1, len(self.mw.selected_accounts()))
        fits = [x for x in self.all if x.max - x.playing >= n]
        if not fits:
            self.status.setText(f"No loaded server has {n} free slot(s) - press Load more.")
            return
        pick = min(fits, key=lambda x: x.playing) if mode == "empty" else max(fits, key=lambda x: x.playing)
        self.status.setText(f"Picked a server with {pick.playing}/{pick.max} players.")
        self._join_job(pick.id)

    def _show(self):
        shown = [s for s in self.all if not (self.hide_full.isChecked() and s.playing >= s.max)]
        self.table.fill(shown)
        if self.all and not shown:
            self.status.setText(f"All {len(self.all)} loaded servers are full - press Load more, choose Fewest "
                                "players first, or untick Hide full servers.")
        else:
            self.status.setText(f"{len(shown)} of {len(self.all)} server(s) shown"
                                + ("  ·  more available" if self.cursor else ""))

    def join(self):
        job = self.table.selected_job()
        if not job:
            self.status.setText("Load the servers and pick one first.")
            return
        self._join_job(job)

    def _join_job(self, job: str):
        from .home_page import play_menu
        pid = util.parse_place_id(self.place.text())
        if pid <= 0:
            return
        spec = LaunchSpec(kind="Job", place_id=pid, job_id=job)
        if self.mw.selected_accounts():
            self.mw.join_server(pid, job)
        else:                                   # nobody selected: ask who should go
            play_menu(self.mw, self, spec, "that server").exec(QCursor.pos())

    def use_on_launch(self):
        job = self.table.selected_job()
        if not job:
            return
        lp = self.mw.launch_page
        lp.place.setCurrentText(self.place.text().strip())
        lp.job.setText(job)
        lp.rb_job.setChecked(True)
        self.mw.show_page(lp)

    def copy_job(self):
        job = self.table.selected_job()
        if job:
            QGuiApplication.clipboard().setText(job)
            self.mw.log("Job ID copied.")


class HistoryDialog(QDialog):
    """Join history: every server an account entered (read from its Roblox log). Rejoin any of them."""

    def __init__(self, mw):
        super().__init__(mw)
        import time as _t
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem
        self.mw = mw
        self.setWindowTitle("Join history")
        self.resize(760, 520)
        v = QVBoxLayout(self)
        v.addWidget(hint("Every server your accounts joined while Cellar ran (newest first). Double-click or "
                         "<b>Rejoin</b> to put accounts back into that exact server."))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["When", "Account", "Game", "Server"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        names = {e.place_id: e.name for e in store.settings.recent if e.name}
        recs = store.settings.history
        self.table.setRowCount(len(recs))
        for r, h in enumerate(recs):
            when = _t.strftime("%a %d %b  %H:%M", _t.localtime(h.ts))
            for c, text in enumerate((when, h.account, names.get(h.place_id) or str(h.place_id), h.job_id[:8] + "…")):
                it = QTableWidgetItem(text)
                if c == 3:
                    it.setToolTip(h.job_id)
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda *_: self.rejoin())
        v.addWidget(self.table, 1)
        if not recs:
            v.addWidget(hint("Nothing yet - joins are recorded from now on."))
        self.rejoin_btn = btn("Rejoin...", self.rejoin, primary=True)
        v.addWidget(row(self.rejoin_btn, btn("Copy Job ID", self.copy), btn("Clear history", self.clear),
                        btn("Close", self.reject)))

    def _rec(self):
        r = self.table.currentRow()
        return store.settings.history[r] if 0 <= r < len(store.settings.history) else None

    def rejoin(self):
        from .home_page import play_menu
        h = self._rec()
        if h:
            spec = LaunchSpec(kind="Job", place_id=h.place_id, job_id=h.job_id)
            play_menu(self.mw, self, spec, "that server").exec(self.rejoin_btn.mapToGlobal(
                self.rejoin_btn.rect().bottomLeft()))

    def copy(self):
        h = self._rec()
        if h:
            QGuiApplication.clipboard().setText(h.job_id)

    def clear(self):
        store.settings.history.clear()
        store.save_settings()
        self.table.setRowCount(0)


class LaunchQueue(QWidget):
    """The launch sequence as it happens: a progress bar, one line per account (waiting / starting / started /
    failed and why) and Retry failed. Hidden until something launches."""

    ICON = {"wait": "○", "go": "◐", "ok": "✓", "fail": "✗", "skip": "–"}
    TOKEN = {"wait": "muted", "go": "accent", "ok": "good", "fail": "bad", "skip": "muted"}

    def __init__(self, mw):
        super().__init__()
        from PySide6.QtWidgets import QHBoxLayout, QListWidget, QProgressBar
        self.mw = mw
        self.rows = {}              # account id -> (item, state, reason)
        self.accs = []
        self.spec, self.allow_saved = None, True
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        top = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.label = QLabel()
        top.addWidget(self.label)
        top.addWidget(self.bar, 1)
        self.retry = btn("Retry failed", self._retry)
        self.retry.setVisible(False)
        top.addWidget(self.retry)
        v.addLayout(top)
        self.list = QListWidget()
        self.list.setMaximumHeight(170)
        v.addWidget(self.list)
        self.setVisible(False)

    def start(self, accs, spec, allow_saved):
        from PySide6.QtWidgets import QListWidgetItem
        self.accs, self.spec, self.allow_saved = list(accs), spec, allow_saved
        self.list.clear()
        self.rows = {}
        for a in accs:
            it = QListWidgetItem()
            self.list.addItem(it)
            self.rows[a.id] = [it, "wait", ""]
            self._paint(a)
        self.bar.setRange(0, len(accs))
        self.bar.setValue(0)
        self.retry.setVisible(False)
        self.setVisible(True)
        self._summary(False)

    def set(self, a, state: str, reason: str = ""):
        r = self.rows.get(a.id)
        if r is None:
            return
        r[1], r[2] = state, reason
        self._paint(a)
        self.bar.setValue(sum(1 for _, st, _ in self.rows.values() if st in ("ok", "fail", "skip")))
        if state == "go":
            self.list.scrollToItem(r[0])
        self._summary(False)

    def _paint(self, a):
        from PySide6.QtGui import QBrush
        it, st, why = self.rows[a.id]
        it.setText(f"{self.ICON[st]}  {a.name}" + (f"  -  {why}" if why else ""))
        it.setForeground(QBrush(theme.qc(self.TOKEN[st])))
        it.setToolTip(why)

    def finish(self, cancelled: bool):
        for a in self.accs:
            if self.rows[a.id][1] in ("wait", "go"):
                self.set(a, "skip", "cancelled" if cancelled else "")
        self._summary(True, cancelled)

    def _summary(self, done: bool, cancelled: bool = False):
        states = [st for _, st, _ in self.rows.values()]
        ok, bad = states.count("ok"), states.count("fail")
        if done:
            self.label.setText(theme.span("bad" if bad else "good", ("Cancelled: " if cancelled else "Done: ")
                                          + f"{ok} started" + (f", {bad} failed" if bad else "")))
            self.retry.setVisible(bad > 0)
        else:
            self.label.setText(f"Launching {sum(1 for x in states if x != 'wait')} of {len(states)}")

    def _retry(self):
        failed = [a for a in self.accs if self.rows.get(a.id, [None, ""])[1] == "fail"]
        if failed and self.spec is not None:
            self.mw.start_launch(failed, fixed=self.spec, allow_saved=self.allow_saved)
