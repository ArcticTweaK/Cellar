"""Dialogs: add / edit accounts, pickers, text views."""

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout, QCheckBox)

from .. import api, store
from ..models import Account
from .common import bg, hint


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
        self.err.setStyleSheet("color: #f85149")
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
        self.fps = QSpinBox()
        self.fps.setRange(0, 1000)
        self.fps.setValue(a.fps_cap)
        self.fps.setSpecialValueText("use the global FPS cap")
        f.addRow("FPS cap", self.fps)
        self.full = QCheckBox("Full quality - this is my main")
        self.full.setChecked(a.full_quality)
        self.full.setToolTip("Skips the alt settings (global FPS cap and graphics preset in Settings > Performance):\n"
                             "this account runs with Roblox's own graphics and your normal Sober's FPS cap,\n"
                             "unless you give it its own FPS cap above.")
        f.addRow("", self.full)
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
        self.c_fps, self.fps = QCheckBox("FPS cap"), QSpinBox()
        self.fps.setRange(0, 1000)
        self.fps.setSpecialValueText("use the global FPS cap")
        f.addRow(self.c_fps, self.fps)
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
