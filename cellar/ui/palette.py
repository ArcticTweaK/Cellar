"""Command palette (Ctrl+K): type a few letters of anything Cellar can do and press Enter.

    "lau alt2"  -> Launch alt2         "stop all" -> Stop all          "mint" -> Theme: Mint
    "mac"       -> Go to Macros        "adopt"    -> Play Adopt Me!    (anything else -> search a game to launch)
"""

from typing import Callable, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QStyledItemDelegate, QVBoxLayout

from .. import store, theme
from ..models import LaunchSpec
from .common import Dialog

Command = Tuple[str, str, Callable[[], None]]       # title, hint (right side), action


def commands(mw) -> List[Command]:
    out: List[Command] = []
    for name, page in mw.goto_items:
        out.append((f"Go to {name}", "page", lambda page=page: mw.show_page(page)))
    sel = mw.selected_accounts()
    if sel:
        out.append((f"Launch the {len(sel)} selected account(s)", "launch", mw.launch_selected))
        out.append(("Stop the selected accounts", "stop", mw.stop_selected))
    out.append(("Stop all accounts", "stop", mw.stop_all))
    for a in store.accounts:
        out.append((f"Launch {a.name}", "account", lambda a=a: mw.start_launch([a])))
        if mw.launcher.running(a):
            out.append((f"Stop {a.name}", "account", lambda a=a: mw.launcher.stop_account(a, mw.log)))
    for g in sorted({a.group for a in store.accounts if a.group}):
        accs = [a for a in store.accounts if a.group == g]
        out.append((f"Launch group {g} ({len(accs)})", "group", lambda accs=accs: mw.start_launch(accs)))
    for p in store.settings.presets:
        out.append((f"Run preset {p.name}", "preset", lambda p=p: mw.presets_page.run(p)))
    main = mw.main_account()
    for e in store.settings.recent[:15]:
        if e.name:
            who = sel or ([main] if main else [])
            out.append((f"Play {e.name}", "with " + (who[0].name if len(who) == 1 else f"{len(who)} accounts")
                        if who else "game",
                        lambda e=e, who=who: who and mw.start_launch(
                            who, fixed=LaunchSpec(kind="Game", place_id=e.place_id), allow_saved=False)))
    for t in theme.THEMES:
        out.append((f"Theme: {t.name}", "theme", lambda k=t.key: mw.apply_theme(k)))
    out += [("Add account (browser login)", "accounts", mw.add_browser),
            ("Screen wall", "background", mw.open_screen_wall),
            ("Anti-AFK now", "accounts", mw.anti_afk_now),
            ("Lock Cellar now (password)", "app", mw.lock),
            ("History: sessions and time played", "app", lambda: mw.open_history(
                (mw.selected_accounts() or [None])[0])),
            ("Roblox logs (what happened, errors)", "app", lambda: mw.open_roblox_log(
                (mw.selected_accounts() or [None])[0])),
            ("Check for updates", "app", lambda: mw.check_updates(manual=True)),
            ("System check", "app", mw.settings_page.system_check),
            ("Run setup again", "app", mw.run_setup),
            ("Refresh status", "accounts", mw.presence_tick)]
    return out


def score(title: str, query: str) -> int:
    """0 = no match. Every word of the query must start a word in the title (or be inside it); earlier and
    tighter matches score higher."""
    t = title.lower()
    words = t.split()
    total = 0
    for q in query.lower().split():
        if any(w.startswith(q) for w in words):
            total += 3
        elif q in t:
            total += 1
        else:
            return 0
    return total * 100 - len(t)


class _Row(QStyledItemDelegate):
    """Draws the item and its small grey category on the right."""

    def paint(self, p, opt, index):
        super().paint(p, opt, index)
        hint = index.data(Qt.UserRole + 1)
        if hint:
            p.save()
            p.setPen(theme.qc("muted"))
            p.drawText(opt.rect.adjusted(0, 0, -12, 0), Qt.AlignRight | Qt.AlignVCenter, hint)
            p.restore()

    def sizeHint(self, opt, index):
        sz = super().sizeHint(opt, index)
        sz.setHeight(max(sz.height(), 30))
        return sz


class Palette(Dialog):
    def __init__(self, mw):
        super().__init__(mw, Qt.Popup | Qt.FramelessWindowHint)
        self.mw = mw
        self.setObjectName("palette")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.cmds = commands(mw)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Type a command, an account, a game or a theme...")
        self.edit.textChanged.connect(self.fill)
        self.edit.returnPressed.connect(self.run)
        v.addWidget(self.edit)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _: self.run())
        self.list.setItemDelegate(_Row(self.list))
        v.addWidget(self.list)
        self.resize(620, 420)
        r = mw.geometry()
        self.move(r.x() + (r.width() - self.width()) // 2, r.y() + 90)
        self.fill("")
        self.edit.setFocus()

    def fill(self, text: str):
        self.list.clear()
        q = text.strip()
        hits = [(score(t, q) if q else 1, t, h, fn) for t, h, fn in self.cmds]
        hits = sorted((x for x in hits if x[0] > 0), key=lambda x: -x[0])[:40]
        if q and len(q) > 1:
            hits.append((0, f"Search games for “{q}”", "launch", lambda q=q: self._search(q)))
        for _, t, h, fn in hits:
            it = QListWidgetItem(f"{t}")
            it.setData(Qt.UserRole, fn)
            it.setData(Qt.UserRole + 1, h)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Down, Qt.Key_Up):
            r = self.list.currentRow() + (1 if ev.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, r)))
            return
        super().keyPressEvent(ev)

    def _search(self, q: str):
        self.mw.show_page(self.mw.launch_page)
        self.mw.launch_page.search_game(q)

    def run(self):
        it = self.list.currentItem()
        if not it:
            return
        fn = it.data(Qt.UserRole)
        self.accept()
        if fn:
            fn()
