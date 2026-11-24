"""Friends tab: an account's friends, who is in which game, and join them with your selected accounts."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMenu,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import api, store
from ..models import LaunchSpec
from .common import bg, hint

_ORDER = {2: 0, 1: 1, 3: 2, 0: 3}           # in game, online, in Studio, offline
_TEXT = {0: "Offline", 1: "Online", 2: "In game", 3: "In Studio"}


class FriendsPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.friends = []
        v = QVBoxLayout(self)
        v.addWidget(hint("Pick an account to see its friends and where they are. <b>Join</b> sends the accounts "
                         "selected on the Accounts page into that friend's server (Roblox's own 'join friend' rules apply)."))
        top = QHBoxLayout()
        top.addWidget(QLabel("Friends of"))
        self.acc = QComboBox()
        top.addWidget(self.acc, 1)
        self.online = QCheckBox("Only online")
        self.online.setChecked(True)
        self.online.toggled.connect(self._fill)
        top.addWidget(self.online)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)
        v.addLayout(top)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Friend", "Status", "Where"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.doubleClicked.connect(lambda _: self.join())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.status = QLabel("")
        row.addWidget(self.status, 1)
        b = QPushButton("Join with selected accounts")
        b.clicked.connect(self.join)
        row.addWidget(b)
        v.addLayout(row)
        self.load_accounts()

    def load_accounts(self):
        cur = self.acc.currentData()
        self.acc.clear()
        accs = [a for a in store.accounts if a.user_id > 0 and a.cookie]
        accs.sort(key=lambda a: (not a.full_quality, a.order))      # your main first
        for a in accs:
            self.acc.addItem(a.name, a.id)
        i = self.acc.findData(cur)
        if i >= 0:
            self.acc.setCurrentIndex(i)

    def refresh(self):
        a = store.find_by_id(self.acc.currentData() or "")
        if not a:
            self.status.setText("Add an account first.")
            return
        self.refresh_btn.setEnabled(False)
        self.status.setText(f"Loading {a.name}'s friends...")

        def done(res):
            self.refresh_btn.setEnabled(True)
            fr, err = res
            if err:
                self.status.setText(f"Could not load friends: {err}")
                return
            self.friends = sorted(fr, key=lambda f: (_ORDER.get(f.presence.type if f.presence else 0, 3),
                                                     (f.display_name or f.name).lower()))
            self._fill()
        bg(api.friends, a.cookie, a.user_id, done=done, err=lambda ex: (self.refresh_btn.setEnabled(True),
                                                                        self.status.setText(f"Failed: {ex}")))

    def _fill(self):
        rows = [f for f in self.friends if not self.online.isChecked() or (f.presence and f.presence.type)]
        self.table.setRowCount(len(rows))
        for r, f in enumerate(rows):
            t = f.presence.type if f.presence else 0
            name = f"{f.display_name} (@{f.name})" if f.display_name and f.display_name != f.name else f.name
            it = QTableWidgetItem(name)
            it.setData(Qt.UserRole, f.user_id)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(_TEXT.get(t, "?")))
            self.table.setItem(r, 2, QTableWidgetItem(f.presence.location if f.presence and t else ""))
        online = sum(1 for f in self.friends if f.presence and f.presence.type)
        ingame = sum(1 for f in self.friends if f.presence and f.presence.type == 2)
        self.status.setText(f"{len(self.friends)} friends - {online} online, {ingame} in a game.")

    def _menu(self, pos):
        r = self.table.rowAt(pos.y())
        if r < 0:
            return
        self.table.selectRow(r)
        m = QMenu(self)
        sel = self.mw.selected_accounts()
        a = m.addAction(f"Join with the {len(sel)} selected account(s)" if sel else "Join with selected accounts",
                        self.join)
        a.setEnabled(bool(sel))
        jm = m.addMenu("Join with...")
        for acc in store.accounts:
            jm.addAction(acc.name, lambda acc=acc: self.join([acc]))
        for g in sorted({x.group for x in store.accounts if x.group}):
            accs = [x for x in store.accounts if x.group == g]
            jm.addAction(f"Group '{g}' ({len(accs)})", lambda accs=accs: self.join(accs))
        m.addSeparator()
        name = self.table.item(r, 0).text()
        m.addAction("Copy username", lambda: QGuiApplication.clipboard().setText(name.split("@")[-1].rstrip(")")))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def join(self, accs=None):
        r = self.table.currentRow()
        if r < 0:
            self.status.setText("Pick a friend first.")
            return
        it = self.table.item(r, 0)
        uid = it.data(Qt.UserRole)
        sel = accs or self.mw.selected_accounts()
        if not sel:
            self.mw.log("Select the accounts that should join (Accounts page) first.")
            return
        self.mw.start_launch(sel, LaunchSpec(kind="Follow", follow_user_id=int(uid), follow_name=it.text()),
                             allow_saved=False)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.load_accounts()
        if not self.friends and self.acc.count():
            self.refresh()
