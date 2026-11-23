"""Launch and Servers pages."""

import random

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QVBoxLayout,
                               QWidget, QCheckBox)

from .. import api, store, util
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
        self.b_launch = btn("Launch selected", self.mw.launch_selected, icon="media-playback-start", primary=True)
        self.b_all = btn("Launch all listed", self.mw.launch_all_listed, icon="media-seek-forward")
        self.b_stop = btn("Stop", self.mw.stop_launch, icon="media-playback-stop")
        self.b_stop.setEnabled(False)
        f.addRow(row(self.b_launch, self.b_all, self.b_stop))
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
            self.sel.setText("<span style='color:#d29922'>Selected accounts: none - click accounts in the list "
                             "(Ctrl / Shift for several).</span>")
        else:
            names = ", ".join(a.name for a in sel[:4]) + (f" ... (+{len(sel) - 4})" if len(sel) > 4 else "")
            self.sel.setText(f"<span style='color:#3fb950'>Selected accounts ({len(sel)}): {names}</span>")

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
        self.place.returnPressed.connect(lambda: self.load(False))
        self.order = QComboBox()
        self.order.addItem("Most players first", False)
        self.order.addItem("Fewest players first", True)
        self.hide_full = QCheckBox("Hide full servers")
        self.hide_full.setChecked(True)
        self.hide_full.toggled.connect(lambda *_: self._show())
        v.addWidget(row(QLabel("Game"), self.place, btn("Search game...", self.search_game, icon="edit-find")))
        v.addWidget(row(self.order, btn("Load servers", lambda: self.load(False), icon="view-refresh"),
                        btn("Load more", lambda: self.load(True)), self.hide_full))
        self.table = ServerTable()
        self.table.doubleClicked.connect(lambda *_: self.join())
        v.addWidget(self.table, 1)
        self.status = QLabel("")
        v.addWidget(self.status)
        v.addWidget(row(btn("Join with selected accounts", self.join, icon="media-playback-start", primary=True),
                        btn("Use on Launch page", self.use_on_launch),
                        btn("Copy Job ID", self.copy_job, icon="edit-copy")))

    def search_game(self):
        d = GamePicker(self, self.mw.any_cookie())
        if d.exec() and d.result:
            self.place.setText(str(d.result.place_id))
            self.load(False)

    def load(self, more: bool):
        pid = util.parse_place_id(self.place.text())
        if pid <= 0:
            self.status.setText("Enter a Place ID or game link.")
            return
        if more and not self.cursor:
            self.status.setText("No more servers.")
            return
        self.status.setText("Loading...")

        def done(sp):
            if sp.error:
                self.status.setText(sp.error)
                return
            self.cursor = sp.next
            self.all = (self.all if more else []) + sp.servers
            self._show()
        bg(api.servers, pid, bool(self.order.currentData()), self.cursor if more else "", self.mw.any_cookie(), done=done)

    def _show(self):
        shown = [s for s in self.all if not (self.hide_full.isChecked() and s.playing >= s.max)]
        self.table.fill(shown)
        self.status.setText(f"{len(shown)} of {len(self.all)} server(s) shown" + ("  ·  more available" if self.cursor else ""))

    def join(self):
        job = self.table.selected_job()
        pid = util.parse_place_id(self.place.text())
        if not job or pid <= 0:
            self.mw.log("Load the servers and pick one first.")
            return
        self.mw.join_server(pid, job)

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
