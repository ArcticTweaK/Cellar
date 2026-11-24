"""Dialogs: add / edit accounts, pickers, text views."""

from typing import List, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QTextBrowser,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout, QCheckBox)

from .. import api, store, theme
from ..models import Account
from .common import bg, hint, spin


class TextDialog(QDialog):
    def __init__(self, parent, title: str, text: str, mono: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 480)
        v = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setReadOnly(True)
        if mono:
            self.edit.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        v.addWidget(self.edit)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        copy = bb.addButton("Copy", QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.edit.toPlainText()))
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def set_text(self, t: str) -> None:
        self.edit.setPlainText(t)


class ReleaseNotesDialog(QDialog):
    """Release notes (GitHub Markdown) for "New version" and "What's new"."""

    def __init__(self, parent, title: str, notes: str, url: str, how: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 520)
        v = QVBoxLayout(self)
        head = QLabel(f"<h2>{title}</h2>")
        v.addWidget(head)
        if how:
            v.addWidget(hint(how))
        b = QTextBrowser()
        b.setOpenExternalLinks(True)
        b.setMarkdown(notes or "_No notes for this release._")
        v.addWidget(b, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        page = bb.addButton("Open release page", QDialogButtonBox.ActionRole)
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class PasteDialog(QDialog):
    """Multi-line input (cookies, username:password lines)."""

    def __init__(self, parent, title: str, explain: str, placeholder: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 380)
        v = QVBoxLayout(self)
        v.addWidget(hint(explain))
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(placeholder)
        v.addWidget(self.edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def text(self) -> str:
        return self.edit.toPlainText()


class PasswordDialog(QDialog):
    def __init__(self, parent, title: str, prompt: str, confirm: bool):
        super().__init__(parent)
        self.setWindowTitle(title)
        f = QFormLayout(self)
        f.addRow(QLabel(prompt))
        self.p1 = QLineEdit()
        self.p1.setEchoMode(QLineEdit.Password)
        f.addRow("Password", self.p1)
        self.p2 = None
        if confirm:
            self.p2 = QLineEdit()
            self.p2.setEchoMode(QLineEdit.Password)
            f.addRow("Repeat", self.p2)
        self.err = QLabel("")
        self.err.setStyleSheet(f"color: {theme.c('bad')}")
        f.addRow(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def _ok(self):
        if not self.p1.text():
            self.err.setText("Type a password.")
            return
        if self.p2 is not None and self.p1.text() != self.p2.text():
            self.err.setText("The two passwords are different.")
            return
        self.accept()

    @staticmethod
    def ask(parent, title: str, prompt: str, confirm: bool = False) -> Optional[str]:
        d = PasswordDialog(parent, title, prompt, confirm)
        return d.p1.text() if d.exec() == QDialog.Accepted else None


class EditAccountDialog(QDialog):
    def __init__(self, parent, a: Account):
        super().__init__(parent)
        self.a = a
        self.setWindowTitle(f"Edit account - {a.username or a.name}")
        self.resize(520, 0)
        f = QFormLayout(self)
        f.addRow(QLabel(f"<b>{a.username}</b>  (ID {a.user_id})" + (f"  ·  {a.display_name}" if a.display_name else "")))
        self.alias = QLineEdit(a.alias)
        self.alias.setPlaceholderText("shown instead of the username")
        f.addRow("Alias", self.alias)
        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.addItem("")
        self.group.addItems(store.all_groups())
        self.group.setCurrentText(a.group)
        f.addRow("Group", self.group)
        self.game = QLineEdit(a.game_link or a.saved_place_id)
        self.game.setPlaceholderText("Place ID, game link or private server link (optional)")
        f.addRow("Own game", self.game)
        self.job = QLineEdit(a.saved_job_id)
        self.job.setPlaceholderText("Job ID of a server (optional)")
        f.addRow("Own server", self.job)
        self.fps = spin(0, 1000, a.fps_cap, special="use the global FPS cap")
        f.addRow("FPS cap", self.fps)
        self.full = QCheckBox("Full quality - this is my main")
        self.full.setChecked(a.full_quality)
        self.full.setToolTip("Skips the alt settings (global FPS cap and graphics preset in Settings > Performance):\n"
                             "this account runs with Roblox's own graphics and your normal Sober's FPS cap,\n"
                             "unless you give it its own FPS cap above.")
        f.addRow("", self.full)
        from .. import gfx
        self.gfx = QComboBox()
        self.gfx.addItem("Default (Performance page, or full quality for your main)", "")
        for k in gfx.PRESETS:
            if k != "Custom":
                self.gfx.addItem(gfx.PRESET_LABELS[k], k)
        self.gfx.setCurrentIndex(max(0, self.gfx.findData(a.gfx_preset)))
        f.addRow("Graphics", self.gfx)
        self.volume = spin(-1, 100, a.volume, suffix=" %", special="default (Settings > Mute alts)",
                           tip="This account's sound. 0 = muted. Default follows Settings > Mute alts.")
        f.addRow("Volume", self.volume)
        self.bgmode = QCheckBox("Run in the background (its own invisible screen)")
        self.bgmode.setChecked(a.background)
        self.bgmode.setToolTip("Nothing shows on your desktop; see and control it with right-click > View screen.\n"
                               "Macros and anti-AFK then reach it without touching your mouse, keyboard or focus.\n"
                               "Costs ~0.1 CPU core and ~190 MB RAM extra. Takes effect at the next launch.")
        f.addRow("", self.bgmode)
        self.automacro = QComboBox()
        self.automacro.addItem("(none)", "")
        for m in store.settings.macros:
            self.automacro.addItem(m.name, m.name)
        i = self.automacro.findData(a.auto_macro)
        self.automacro.setCurrentIndex(i if i >= 0 else 0)
        f.addRow("Macro at launch", self.automacro)
        self.desc = QPlainTextEdit(a.description)
        self.desc.setMaximumHeight(80)
        f.addRow("Notes", self.desc)
        self.pw = QLineEdit(a.password)
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("optional - only used to fill the browser login form")
        f.addRow("Password", self.pw)
        self.cookie = QLineEdit(a.cookie)
        self.cookie.setEchoMode(QLineEdit.Password)
        f.addRow("Cookie", self.cookie)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def apply(self) -> bool:
        """Copies the fields into the account. Returns True if the cookie changed."""
        a = self.a
        from ..util import parse_place_id
        a.alias = self.alias.text().strip()
        a.group = self.group.currentText().strip()
        link = self.game.text().strip()
        a.game_link = link
        pid = parse_place_id(link)
        a.saved_place_id = str(pid) if pid else ""
        a.saved_job_id = self.job.text().strip()
        a.fps_cap = self.fps.value()
        a.full_quality = self.full.isChecked()
        a.volume = self.volume.value()
        a.gfx_preset = self.gfx.currentData() or ""
        a.background = self.bgmode.isChecked()
        a.auto_macro = self.automacro.currentData() or ""
        a.description = self.desc.toPlainText().strip()
        a.password = self.pw.text()
        new_cookie = self.cookie.text().strip()
        changed = new_cookie != a.cookie and bool(new_cookie)
        if changed:
            a.cookie = new_cookie
        return changed


class BulkEditDialog(QDialog):
    def __init__(self, parent, accs: List[Account]):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {len(accs)} accounts")
        f = QFormLayout(self)
        f.addRow(hint("Only the ticked fields are changed."))
        self.c_group, self.group = QCheckBox("Group"), QComboBox()
        self.group.setEditable(True)
        self.group.addItem("")
        self.group.addItems(store.all_groups())
        f.addRow(self.c_group, self.group)
        self.c_game, self.game = QCheckBox("Own game"), QLineEdit()
        self.game.setPlaceholderText("Place ID / link, empty = none")
        f.addRow(self.c_game, self.game)
        self.c_fps, self.fps = QCheckBox("FPS cap"), spin(0, 1000, 0, special="use the global FPS cap")
        f.addRow(self.c_fps, self.fps)
        self.c_bg, self.bg = QCheckBox("Background"), QComboBox()
        self.bg.addItem("Run on an invisible screen", True)
        self.bg.addItem("Normal window", False)
        f.addRow(self.c_bg, self.bg)
        self.c_full, self.full = QCheckBox("Quality"), QComboBox()
        self.full.addItem("Alt settings (FPS cap + graphics preset)", False)
        self.full.addItem("Full quality (like my main)", True)
        f.addRow(self.c_full, self.full)
        self.c_macro, self.macro = QCheckBox("Macro at launch"), QComboBox()
        self.macro.addItem("(none)", "")
        for m in store.settings.macros:
            self.macro.addItem(m.name, m.name)
        f.addRow(self.c_macro, self.macro)
        # ticking happens by itself when a field is changed
        self.group.currentTextChanged.connect(lambda *_: self.c_group.setChecked(True))
        self.game.textChanged.connect(lambda *_: self.c_game.setChecked(True))
        self.fps.valueChanged.connect(lambda *_: self.c_fps.setChecked(True))
        for c, w in ((self.c_bg, self.bg), (self.c_full, self.full), (self.c_macro, self.macro)):
            w.currentIndexChanged.connect(lambda *_, c=c: c.setChecked(True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def apply(self, accs: List[Account]) -> None:
        from ..util import parse_place_id
        for a in accs:
            if self.c_group.isChecked():
                a.group = self.group.currentText().strip()
            if self.c_game.isChecked():
                a.game_link = self.game.text().strip()
                pid = parse_place_id(a.game_link)
                a.saved_place_id = str(pid) if pid else ""
                a.saved_job_id = ""
            if self.c_fps.isChecked():
                a.fps_cap = self.fps.value()
            if self.c_bg.isChecked():
                a.background = bool(self.bg.currentData())
            if self.c_full.isChecked():
                a.full_quality = bool(self.full.currentData())
            if self.c_macro.isChecked():
                a.auto_macro = self.macro.currentData() or ""


class GamePicker(QDialog):
    """Search a game by name."""

    def __init__(self, parent, cookie: Optional[str]):
        super().__init__(parent)
        self.cookie = cookie
        self.result: Optional[api.GameInfo] = None
        self.setWindowTitle("Search game")
        self.resize(520, 420)
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Game name, e.g. Adopt Me")
        self.q.returnPressed.connect(self.search)
        go = QPushButton("Search")
        go.clicked.connect(self.search)
        h.addWidget(self.q)
        h.addWidget(go)
        v.addLayout(h)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._pick())
        v.addWidget(self.list)
        self.status = QLabel("")
        v.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._pick)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def search(self):
        q = self.q.text().strip()
        if not q:
            return
        self.status.setText("Searching...")
        self.list.clear()

        def done(games):
            self.list.clear()
            for g in games:
                it = QListWidgetItem(f"{g.name}    ({g.players:,} playing · place {g.place_id})")
                it.setData(Qt.UserRole, g)
                self.list.addItem(it)
            self.status.setText(f"{len(games)} result(s)" if games else "Nothing found.")
            if games:
                self.list.setCurrentRow(0)
        bg(api.search_games, q, self.cookie, done=done)

    def _pick(self):
        it = self.list.currentItem()
        if it is None:
            return
        self.result = it.data(Qt.UserRole)
        self.accept()


class _SortItem(QTableWidgetItem):
    def __lt__(self, other):
        a, b = self.data(Qt.UserRole), other.data(Qt.UserRole)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class ServerTable(QTableWidget):
    COLS = ["Players", "Ping", "FPS", "Job ID"]

    def __init__(self):
        super().__init__(0, len(self.COLS))
        self.setHorizontalHeaderLabels(self.COLS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.setSortingEnabled(True)

    def fill(self, servers: List[api.ServerInfo], append: bool = False) -> None:
        self.setSortingEnabled(False)
        if not append:
            self.setRowCount(0)
        for s in servers:
            r = self.rowCount()
            self.insertRow(r)
            for c, (text, key) in enumerate(((f"{s.playing}/{s.max}", s.playing), (str(s.ping), s.ping),
                                             (f"{s.fps:.0f}", s.fps), (s.id, s.id))):
                it = _SortItem(text)
                it.setData(Qt.UserRole, key)
                self.setItem(r, c, it)
        self.setSortingEnabled(True)

    def selected_job(self) -> Optional[str]:
        r = self.currentRow()
        if r < 0 or self.item(r, 3) is None:
            return None
        return self.item(r, 3).text()


class ServerPicker(QDialog):
    def __init__(self, parent, place_id: int, cookie: Optional[str]):
        super().__init__(parent)
        self.place_id, self.cookie, self.cursor = place_id, cookie, ""
        self.result: Optional[str] = None
        self.setWindowTitle(f"Servers of place {place_id}")
        self.resize(640, 480)
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        self.order = QComboBox()
        self.order.addItem("Most players first", False)
        self.order.addItem("Fewest players first", True)
        self.order.currentIndexChanged.connect(lambda *_: self.load(False))
        more = QPushButton("Load more")
        more.clicked.connect(lambda: self.load(True))
        h.addWidget(self.order)
        h.addStretch(1)
        h.addWidget(more)
        v.addLayout(h)
        self.table = ServerTable()
        self.table.doubleClicked.connect(lambda *_: self._pick())
        v.addWidget(self.table)
        self.status = QLabel("")
        v.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._pick)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.load(False)

    def load(self, more: bool):
        if more and not self.cursor:
            self.status.setText("No more servers.")
            return
        self.status.setText("Loading...")

        def done(sp: api.ServerPage):
            if sp.error:
                self.status.setText(sp.error)
                return
            self.cursor = sp.next
            self.table.fill(sp.servers, append=more)
            self.status.setText(f"{self.table.rowCount()} server(s)" + ("  ·  more available" if sp.next else ""))
        bg(api.servers, self.place_id, bool(self.order.currentData()), self.cursor if more else "", self.cookie, done=done)

    def _pick(self):
        j = self.table.selected_job()
        if j:
            self.result = j
            self.accept()


class PlayLinkDialog(QDialog):
    """A "Play" link from the website: join with Cellar accounts, or hand it to your normal Sober."""

    def __init__(self, parent, spec, selected_ids):
        super().__init__(parent)
        self.setWindowTitle("Join from the website")
        self.resize(480, 520)
        v = QVBoxLayout(self)
        self.title = QLabel("<h3>Roblox wants to start a game</h3>")
        v.addWidget(self.title)
        what = {"Game": "Any public server", "Job": "A specific server", "Private": "A private server",
                "Follow": "Follow a player into their game", "Reserved": "A reserved server"}
        v.addWidget(hint(what.get(spec.kind, "Roblox's home screen") if spec else "Roblox's home screen (no game in "
                         "the link)"))
        own = spec is not None and spec.kind != "Reserved"
        self.use_sober = QCheckBox("Play in my normal Sober (as the account logged in on the website)")
        self.use_sober.setChecked(not own)
        v.addWidget(self.use_sober)
        v.addWidget(QLabel("Or join with these Cellar accounts:"))
        self.list = QListWidget()
        for a in store.accounts:
            it = QListWidgetItem(a.name)
            it.setData(Qt.UserRole, a.id)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if own and a.id in selected_ids else Qt.Unchecked)
            self.list.addItem(it)
        self.list.setEnabled(own)
        v.addWidget(self.list, 1)
        if not own:
            v.addWidget(hint("Only the website's own account can open this link, so it goes to your normal Sober."))
        self.use_sober.toggled.connect(lambda on: self.list.setEnabled(own and not on))
        self.list.itemChanged.connect(lambda *_: self.use_sober.setChecked(False) if self.chosen() else None)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        go = bb.addButton("Join", QDialogButtonBox.AcceptRole)
        go.setProperty("primary", True)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if spec and spec.place_id:
            bg(api.place_name, spec.place_id,
               done=lambda n: n and self.title.setText(f"<h3>Roblox wants to start {n}</h3>"))

    def chosen(self) -> List[Account]:
        ids = {self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
               if self.list.item(i).checkState() == Qt.Checked}
        return [a for a in store.accounts if a.id in ids]


class RestoreBackupDialog(QDialog):
    """Pick one of the automatic backups of the accounts file (last 10) and see what is in it first."""

    def __init__(self, parent):
        super().__init__(parent)
        import time as _t
        self.setWindowTitle("Restore accounts from a backup")
        self.resize(560, 460)
        self.chosen: Optional[List[Account]] = None
        v = QVBoxLayout(self)
        v.addWidget(hint("Cellar keeps the last 10 versions of your accounts file. Pick one to see what is in it. "
                         "Restoring replaces your account list; the current list is kept as a backup."))
        self.files = QListWidget()
        for f in store.backups():
            it = QListWidgetItem(_t.strftime("%Y-%m-%d  %H:%M:%S", _t.localtime(f.stat().st_mtime)))
            it.setData(Qt.UserRole, str(f))
            self.files.addItem(it)
        self.files.currentItemChanged.connect(self._show)
        v.addWidget(self.files, 1)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        v.addWidget(self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.go = bb.addButton("Restore this backup", QDialogButtonBox.AcceptRole)
        self.go.setEnabled(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if not self.files.count():
            self.preview.setText("No backups yet - Cellar makes one every time it opens your accounts.")

    def _show(self, it, _prev=None):
        from pathlib import Path
        self.chosen = None
        self.go.setEnabled(False)
        if it is None:
            return
        accs, err = store.read_backup(Path(it.data(Qt.UserRole)))
        if accs is None:
            self.preview.setText(theme.span("bad", "Can't open this one: " + err))
            return
        self.chosen = accs
        names = ", ".join(a.name for a in sorted(accs, key=lambda a: a.order)[:12])
        more = f" and {len(accs) - 12} more" if len(accs) > 12 else ""
        self.preview.setText(f"<b>{len(accs)} account(s):</b> {names}{more}")
        self.go.setEnabled(True)
