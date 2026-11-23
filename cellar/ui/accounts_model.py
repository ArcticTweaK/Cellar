"""Table model for the account list."""

from typing import Dict, List, Set

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap

from .. import paths, store, util
from ..models import Account

COLS = ["Account", "Group", "Status", "Game", "Last used"]
SORT_ROLE = Qt.UserRole + 1
ACCOUNT_ROLE = Qt.UserRole + 2

GOOD, WARN, BAD, DIM = QColor("#3fb950"), QColor("#d29922"), QColor("#f85149"), QColor("#8b949e")


class AccountModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.running: Set[str] = set()      # account ids with a live client
        self._icons: Dict[int, QIcon] = {}

    # ------------------------------------------------------------ helpers
    def accounts(self) -> List[Account]:
        return store.accounts

    def reload(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def refresh_status(self) -> None:
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 2), self.index(self.rowCount() - 1, 4))

    def icon_for(self, a: Account) -> QIcon:
        if not a.user_id:
            return QIcon.fromTheme("user-identity")
        ic = self._icons.get(a.user_id)
        if ic is None:
            p = paths.AVATAR_DIR / f"{a.user_id}.png"
            if p.exists():
                pm = QPixmap(str(p))
                if not pm.isNull():
                    ic = QIcon(pm)
                    self._icons[a.user_id] = ic
        return ic or QIcon.fromTheme("user-identity")

    def forget_icons(self) -> None:
        self._icons.clear()

    def status(self, a: Account):
        li = store.live(a)
        if li.locked:
            return "Locked (HTTP 403)", BAD
        if li.cookie_bad:
            return "Signed out - cookie expired", BAD
        run = a.id in self.running
        if li.presence_type == 2:
            where = li.where or "a game"
            return ("▶ In game: " if run else "In game: ") + where, GOOD
        if run:
            return "▶ Sober running", GOOD
        if li.presence_type == 1:
            return "Online", WARN
        if li.presence_type == 3:
            return "In Studio", WARN
        if li.presence_type == 0:
            return "Offline", DIM
        return "", DIM

    @staticmethod
    def game_text(a: Account) -> str:
        if util.share_code_of(a.game_link):
            return "private server (share link)"
        pid = util.parse_place_id(a.game_link) or util.parse_place_id(a.saved_place_id)
        if not pid:
            return ""
        name = next((g.name for g in store.settings.recent if g.place_id == pid and g.name), "")
        tag = " (private)" if util.private_link_code(a.game_link) else (" (server)" if util.looks_like_guid(a.saved_job_id) else "")
        return (name or str(pid)) + tag

    # ------------------------------------------------------------ Qt API
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(store.accounts)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(store.accounts):
            return None
        a = store.accounts[index.row()]
        c = index.column()
        if role == ACCOUNT_ROLE:
            return a
        if role == Qt.DisplayRole:
            if c == 0:
                return a.alias + f"  ({a.username})" if a.alias and a.username and a.alias != a.username else a.name
            if c == 1:
                return a.group
            if c == 2:
                return self.status(a)[0]
            if c == 3:
                return self.game_text(a)
            if c == 4:
                return util.ago(a.last_used)
        if role == Qt.DecorationRole and c == 0:
            return self.icon_for(a)
        if role == Qt.ForegroundRole and c == 2:
            return QBrush(self.status(a)[1])
        if role == Qt.ToolTipRole:
            lines = [f"{a.username} (ID {a.user_id})" if a.user_id else a.username]
            if a.display_name and a.display_name != a.username:
                lines.append("Display name: " + a.display_name)
            if a.description:
                lines.append(a.description)
            return "\n".join(x for x in lines if x)
        if role == SORT_ROLE:
            if c == 0:   # natural order as a plain string: digit runs zero-padded
                return "".join(f"{t:>012}" if t.isdigit() else t.lower()
                               for t in __import__("re").split(r"(\d+)", a.name))
            if c == 4:
                return -a.last_used
            return (self.data(index, Qt.DisplayRole) or "").lower()
        return None


class AccountFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.text = ""
        self.group = None           # None = all groups, "" = no group
        self.setSortRole(SORT_ROLE)

    def set_text(self, t: str) -> None:
        self.text = (t or "").strip().lower()
        self.invalidateFilter()

    def set_group(self, g) -> None:
        self.group = g
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        if source_row >= len(store.accounts):
            return False
        a = store.accounts[source_row]
        if self.group is not None and a.group != self.group:
            return False
        if self.text:
            hay = " ".join([a.username, a.alias, a.display_name, a.group, a.description, str(a.user_id)]).lower()
            return self.text in hay
        return True
