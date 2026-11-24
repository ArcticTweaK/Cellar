"""LIBRARY: your games, laid out like a game launcher's library - a list on the left (search, favourites, recent,
games with saved private servers) and on the right either the overview (a big "jump back in" tile plus rows) or
the page of the game you clicked.
"""

import time
from typing import Dict, List, Optional

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QScrollArea,
                               QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import games, store, theme, util
from ..games import Game
from ..models import LaunchSpec
from .common import bg, btn, hint
from .home_page import GameCard, GameView, Shelf, _pixmap, _rounded, play_menu


class HeroTile(QWidget):
    """The game you played last, big: picture, name, when and who, and a Play button."""

    def __init__(self, page: "LibraryPage"):
        super().__init__()
        self.page = page
        self.g: Optional[Game] = None
        self.when = ""
        self.setFixedHeight(220)
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(220, 0, 24, 24)
        h.addStretch(1)
        self.play = btn("Play", self._play, icon="play", primary=True)
        self.play.setMinimumSize(140, 42)
        h.addWidget(self.play, 0, Qt.AlignBottom)

    def set_game(self, g: Optional[Game], when: str):
        self.g, self.when = g, when
        self.setVisible(g is not None)
        self.update()

    def _play(self):
        if self.g:
            play_menu(self.page.mw, self, LaunchSpec(kind="Game", place_id=self.g.place_id), self.g.name).exec(
                self.play.mapToGlobal(self.play.rect().bottomLeft()))

    def mouseReleaseEvent(self, ev):
        if self.g and ev.button() == Qt.LeftButton:
            self.page.open_game(self.g)

    def paintEvent(self, _):
        if not self.g:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(theme.qc("border"))
        p.setBrush(theme.qc("surface"))
        p.drawRoundedRect(r, 12, 12)
        pm = _pixmap(f"g{self.g.universe_id}", games.icon_path(self.g.universe_id))
        _rounded(p, QRect(16, 16, 188, 188), 10, pm, theme.qc("raised"))
        x = 228
        cap = theme.mono_font(8, 1.4)
        p.setFont(cap)
        p.setPen(theme.qc("accent"))
        p.drawText(QRect(x, 24, 400, 18), Qt.AlignLeft, "JUMP BACK IN")
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 1.9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.qc("text"))
        fm = QFontMetrics(f)
        p.drawText(QRect(x, 46, self.width() - x - 24, fm.height()), Qt.AlignLeft,
                   fm.elidedText(self.g.name, Qt.ElideRight, self.width() - x - 24))
        f2 = QFont(self.font())
        p.setFont(f2)
        p.setPen(theme.qc("muted"))
        bits = [self.when]
        if self.g.players:
            bits.append(f"{games.short(self.g.players)} playing now")
        if self.g.rating is not None:
            bits.append(f"{self.g.rating}% like it")
        p.drawText(QRect(x, 52 + fm.height(), self.width() - x - 24, 22), Qt.AlignLeft, "  ·  ".join(b for b in bits if b))


class LibraryPage(QWidget):
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.games: Dict[int, Game] = {}            # place id -> game (with details)
        self.favs: List[int] = []
        self.loaded_at = 0.0
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        h.addWidget(split)

        left = QWidget()
        left.setObjectName("libside")
        left.setAttribute(Qt.WA_StyledBackground, True)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)
        home = btn("Library home", self.show_home, icon="house")
        home.setObjectName("libhome")
        lv.addWidget(home)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search your games...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_list)
        lv.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("liblist")
        self.list.setIconSize(QSize(28, 28))
        self.list.itemClicked.connect(self._picked)
        lv.addWidget(self.list, 1)
        split.addWidget(left)

        self.right = QStackedWidget()
        # overview
        over = QWidget()
        ov = QVBoxLayout(over)
        ov.setContentsMargins(8, 0, 8, 0)
        ov.setSpacing(6)
        self.hero = HeroTile(self)
        ov.addWidget(self.hero)
        self.recent = Shelf("Recent games", GameCard.H)
        self.favshelf = Shelf("Favourites", GameCard.H)
        self.private = Shelf("Games with your private servers", GameCard.H)
        for sh in (self.recent, self.favshelf, self.private):
            ov.addWidget(sh)
        self.empty = hint("Your library fills up as you and your accounts play: every game Cellar sees an account "
                          "join lands here, with your Roblox favourites and saved private servers.")
        ov.addWidget(self.empty)
        ov.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(over)
        self.right.addWidget(scroll)
        # a game's page
        self.game_box = QWidget()
        self.gv = QVBoxLayout(self.game_box)
        self.gv.setContentsMargins(8, 0, 8, 0)
        self.right.addWidget(self.game_box)
        split.addWidget(self.right)
        split.setSizes([280, 1000])
        split.setStretchFactor(1, 1)

    # ------------------------------------------------------------ data
    def showEvent(self, ev):
        super().showEvent(ev)
        if time.time() - self.loaded_at > 300:
            self.load()
        else:
            self._fill_list()

    def load(self):
        self.loaded_at = time.time()
        ids = list(dict.fromkeys([e.place_id for e in store.settings.recent]
                                 + [p.place_id for p in store.settings.private_servers]))
        a = self.mw.home_page.home_account()

        def work():
            gs = games.from_places(ids) if ids else []
            favs = games.favourites(a.user_id, a.cookie) if a else []
            games.fetch_icons([g.universe_id for g in gs + favs])
            return gs, favs

        def done(res):
            gs, favs = res or ([], [])
            for g in gs + favs:
                self.games[g.place_id] = g
            self.favs = [g.place_id for g in favs]
            self._fill_list()
            self._fill_home()
        bg(work, done=done)
        self._fill_list()
        self._fill_home()

    def _name(self, pid: int) -> str:
        g = self.games.get(pid)
        if g and g.name:
            return g.name
        return next((e.name for e in store.settings.recent if e.place_id == pid and e.name), str(pid))

    def _game(self, pid: int) -> Game:
        return self.games.get(pid) or Game(place_id=pid, name=self._name(pid))

    # ------------------------------------------------------------ list
    def _fill_list(self, *_):
        q = self.search.text().strip().lower()
        self.list.clear()
        recent = [e.place_id for e in store.settings.recent]
        private = list(dict.fromkeys(p.place_id for p in store.settings.private_servers))
        for title, ids in (("FAVOURITES", self.favs), ("RECENT", recent), ("PRIVATE SERVERS", private)):
            ids = [i for i in ids if not q or q in self._name(i).lower()]
            if not ids:
                continue
            head = QListWidgetItem(f"{title}  ({len(ids)})")
            head.setFlags(Qt.NoItemFlags)
            head.setFont(theme.mono_font(7.5, 1.4))
            self.list.addItem(head)
            for pid in ids:
                it = QListWidgetItem(self._name(pid))
                g = self.games.get(pid)
                pm = _pixmap(f"g{g.universe_id}", games.icon_path(g.universe_id)) if g else None
                it.setIcon(QIcon(pm) if pm is not None else QIcon(QPixmap()))
                it.setData(Qt.UserRole, pid)
                self.list.addItem(it)

    def _picked(self, it):
        pid = it.data(Qt.UserRole)
        if pid:
            self.open_game(self._game(pid))

    # ------------------------------------------------------------ right side
    def _cards(self, shelf: Shelf, pids: List[int], empty: str):
        cards = []
        for pid in pids:
            c = GameCard(self._game(pid))
            c.clicked.connect(self.open_game)
            c.menu.connect(lambda g, pos: play_menu(self.mw, self, LaunchSpec(kind="Game", place_id=g.place_id),
                                                    g.name).exec(pos))
            cards.append(c)
        shelf.set_widgets(cards, empty)
        shelf.setVisible(bool(cards))

    def _fill_home(self):
        recent = store.settings.recent
        if recent:
            e = recent[0]
            who = next((h.account for h in store.settings.history if h.place_id == e.place_id), "")
            self.hero.set_game(self._game(e.place_id), f"Last played {util.ago(e.ts)}" + (f" by {who}" if who else ""))
        else:
            self.hero.set_game(None, "")
        self._cards(self.recent, [e.place_id for e in recent[1:]], "")
        self._cards(self.favshelf, self.favs, "")
        self._cards(self.private, list(dict.fromkeys(p.place_id for p in store.settings.private_servers)), "")
        self.empty.setVisible(not recent and not self.favs and not store.settings.private_servers)

    def show_home(self):
        self.right.setCurrentIndex(0)
        self.list.clearSelection()

    def open_game(self, g: Game):
        while self.gv.count():
            w = self.gv.takeAt(0).widget()
            if w:
                w.deleteLater()
        back = btn("Library", self.show_home, icon="chevron-left")
        back.setObjectName("libback")
        self.gv.addWidget(back, 0, Qt.AlignLeft)
        view = GameView(self.mw, g)
        view.leave.connect(self.show_home)
        self.gv.addWidget(view, 1)
        self.right.setCurrentIndex(1)
