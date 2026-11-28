"""The Launch tab: where the selected accounts go, and the launch bar.

It also holds what Cellar keeps from the old Home tab - only what helps launching: your games (recent + the main
account's favourites), saved private servers, friends to follow, the server picker and the join history.
Browsing Roblox itself is roblox.com's job (with RoValra); its Play button comes back here (playlink.py).
"""

import random
import time
from typing import List, Optional

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSizePolicy, QStackedWidget, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from .. import api, games, paths, playlink, sessions, store, theme, util
from ..games import Game
from ..models import Account, LaunchSpec, PrivateServer
from ..specs import LaunchForm
from .common import Dialog, ask, bg, btn, chk, hint, popup, row, spin, warn
from .dialogs import GamePicker, ServerPicker
from .widgets import eyebrow


# ---------------------------------------------------------------- "Play with..." (game tiles, history, links)
def play_menu(mw, parent: QWidget, spec: LaunchSpec, title: str = "") -> QMenu:
    """Who plays: the selected accounts, the main account, anyone / a group, or your normal Sober.
    Show it with common.popup()."""
    m = QMenu(parent)
    sel = mw.selected_accounts()
    main = mw.main_account()

    def go(accs: List[Account]):
        if accs:
            mw.log(f"Playing {title or spec.describe()} with {', '.join(a.name for a in accs[:4])}"
                   + (f" and {len(accs) - 4} more" if len(accs) > 4 else "") + ".")
            mw.start_launch(accs, fixed=spec, allow_saved=False)

    if sel:
        m.addAction(f"Play with the {len(sel)} selected account(s)" if len(sel) > 1 else f"Play with {sel[0].name}",
                    lambda: go(sel))
    if main and main not in sel:
        m.addAction(f"Play with {main.name}", lambda: go([main]))
    sub = m.addMenu("Play with...")
    for a in store.accounts:
        sub.addAction(a.name, lambda a=a: go([a]))
    groups = sorted({a.group for a in store.accounts if a.group})
    if groups:
        sub.addSeparator()
        for g in groups:
            accs = [a for a in store.accounts if a.group == g]
            sub.addAction(f"Group '{g}' ({len(accs)})", lambda accs=accs: go(accs))
    if not store.accounts:
        sub.addAction("(add an account first)").setEnabled(False)

    def in_sober():
        bg(playlink.play_in_main_sober, spec,
           done=lambda err: warn(parent, "Play", err) if err else mw.log(f"Started {title or 'the game'} in your "
                                                                         "normal Sober."))
    m.addAction("Play in my normal Sober", in_sober)
    if spec.place_id:
        m.addSeparator()
        m.addAction("Servers...", lambda: mw.open_servers(spec.place_id))
        m.addAction("Open on roblox.com", lambda: open_url(f"https://www.roblox.com/games/{spec.place_id}"))
        m.addAction("Copy game link", lambda: QGuiApplication.clipboard().setText(
            f"https://www.roblox.com/games/{spec.place_id}"))
    return m


def open_url(url: str) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(url))


def private_spec(ps: PrivateServer) -> LaunchSpec:
    share = util.share_code_of(ps.link)
    if share:               # resolved per account when it launches (each account must be allowed in)
        return LaunchSpec(kind="Private", place_id=ps.place_id, share_code=share)
    return LaunchSpec(kind="Private", place_id=ps.place_id, link_code=util.private_link_code(ps.link))


# ---------------------------------------------------------------- your games
def _recent_games(place_ids: List[int]) -> List[Game]:
    """Worker: recent places -> games with names / players / icons, one per game (sub-places of the same game,
    e.g. a lobby and its match server, show once)."""
    gs = games.from_places(place_ids)
    games.fetch_icons([g.universe_id for g in gs])
    return gs


def _favourite_games(user_id: int, cookie: str) -> List[Game]:
    gs = games.favourites(user_id, cookie)
    games.fetch_icons([g.universe_id for g in gs])
    return gs


def _friend_avatars(user_ids: List[int]) -> int:
    """Worker: head shots of friends not cached yet (same cache as the accounts' own)."""
    need = [u for u in dict.fromkeys(user_ids) if u > 0 and not (paths.AVATAR_DIR / f"{u}.png").exists()]
    if not need:
        return 0
    paths.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for uid, url in api.avatar_urls(need).items():
        data = api.download(url)
        if data:
            tmp = paths.AVATAR_DIR / f".{uid}.png.part"
            try:
                tmp.write_bytes(data)
                tmp.replace(paths.AVATAR_DIR / f"{uid}.png")
                n += 1
            except OSError:
                pass
    return n


def _two_lines(text: str, fm: QFontMetrics, width: int) -> List[str]:
    """A name on at most two lines (the second one elided)."""
    words, line = text.split(), ""
    for i, w in enumerate(words):
        test = (line + " " + w).strip()
        if fm.horizontalAdvance(test) <= width:
            line = test
            continue
        if not line:                    # one very long word
            return [fm.elidedText(text, Qt.ElideRight, width)]
        return [line, fm.elidedText(" ".join(words[i:]), Qt.ElideRight, width)]
    return [line]


class _TileDelegate(QStyledItemDelegate):
    """A game tile: its picture, the name on up to two lines and how many play it now. Painted, so a full grid
    of games is one widget (no child widgets per tile)."""

    W, H, ART = 132, 190, 112

    def sizeHint(self, opt, index):
        return QSize(self.W, self.H)

    def paint(self, p: QPainter, opt, index):
        g: Game = index.data(Qt.UserRole)
        if g is None:
            return
        pm: Optional[QPixmap] = index.data(Qt.UserRole + 1)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = opt.rect.adjusted(3, 3, -3, -3)
        selected = bool(opt.state & QStyle.State_Selected)
        if selected or opt.state & QStyle.State_MouseOver:
            fill = QColor(theme.c("accent"))
            fill.setAlphaF(0.16 if selected else 0.07)
            p.setPen(theme.qc("accent") if selected else Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(r), 12, 12)
        art = QRect(r.x() + (r.width() - self.ART) // 2, r.y() + 8, self.ART, self.ART)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(art), 10, 10)
        p.save()
        p.setClipPath(clip)
        if pm is not None and not pm.isNull():
            p.drawPixmap(art, pm)
        else:
            p.fillRect(art, theme.qc("raised"))
            theme.icon("gamepad-2", "muted").paint(p, art.adjusted(36, 36, -36, -36))
        p.restore()
        f = QFont(opt.font)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        p.setPen(theme.qc("text"))
        y = art.bottom() + 7
        for line in _two_lines(g.name or f"Place {g.place_id}", fm, r.width() - 12):
            p.drawText(QRect(r.x() + 6, y, r.width() - 12, fm.height()), Qt.AlignHCenter, line)
            y += fm.height()
        if g.players:
            f.setBold(False)
            f.setPointSizeF(f.pointSizeF() * 0.9)
            p.setFont(f)
            text = f"●  {games.short(g.players)} playing"
            p.setPen(theme.qc("good"))
            p.drawText(QRect(r.x() + 6, y + 2, r.width() - 12, QFontMetrics(f).height()), Qt.AlignHCenter, text)
        p.restore()


class GameStrip(QWidget):
    """Game tab: your games as big tiles - Recent (what your accounts played) or Favourites (the main account's,
    from Roblox) - and a search field that also takes a pasted link or Place ID.
    Click = this game, double-click = launch the selected accounts there, right-click = Play with..."""

    picked = Signal(object)         # Game
    launch = Signal(object)         # Game
    search = Signal(str)            # text typed + Enter (a link / Place ID or words to search)
    FAV_TTL = 600

    def __init__(self, mw, names: dict):
        super().__init__()
        self.mw = mw
        self.names = names              # the launch panel's place id -> name (filled from what is shown here)
        self._favs: Optional[List[Game]] = None
        self._favs_at = 0.0
        self._favs_of = ""
        self.selected_place = 0
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        top = QHBoxLayout()
        self.kind = QButtonGroup(self)
        for i, text in enumerate(("Recent", "Favourites")):
            b = QPushButton(text)
            b.setObjectName("seg")
            b.setCheckable(True)
            self.kind.addButton(b, i)
            top.addWidget(b)
        self.kind.button(0).setChecked(True)
        self.kind.idClicked.connect(lambda *_: self.refresh())
        top.addSpacing(10)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search Roblox games, or paste a game link / Place ID  (Enter)")
        self.find.setClearButtonEnabled(True)
        self.find.returnPressed.connect(lambda: self.find.text().strip() and self.search.emit(self.find.text().strip()))
        top.addWidget(self.find, 1)
        v.addLayout(top)
        self.note = QLabel("")
        self.note.setObjectName("stat_sub")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        self.list = QListWidget()
        self.list.setObjectName("gametiles")
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setFlow(QListWidget.LeftToRight)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setUniformItemSizes(True)
        self.list.setGridSize(QSize(_TileDelegate.W, _TileDelegate.H))
        self.list.setItemDelegate(_TileDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda it: self.picked.emit(it.data(Qt.UserRole)))
        self.list.itemDoubleClicked.connect(lambda it: self.launch.emit(it.data(Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.list, 1)
        self.refresh()

    def favourites_mode(self) -> bool:
        return self.kind.checkedId() == 1

    def refresh(self, force: bool = False):
        if self.favourites_mode():
            self._load_favourites(force)
            return
        ids = [e.place_id for e in store.settings.recent[:24]]
        if not ids:
            self._fill([], "Games your accounts play show up here. Search above, or press Play on roblox.com.")
            return
        # names are known already: show them at once, then pictures / player counts from the worker
        self._fill([Game(place_id=e.place_id, universe_id=games.cached_universe(e.place_id), name=e.name)
                    for e in store.settings.recent[:24]], "", dedupe=True)
        bg(_recent_games, ids, done=lambda gs: not self.favourites_mode() and self._fill(gs, "", dedupe=True))

    def _load_favourites(self, force: bool):
        a = self.mw.main_account()
        if not a:
            self._fill([], "Add an account to see its favourite games.")
            return
        fresh = self._favs is not None and self._favs_of == a.id and time.time() - self._favs_at < self.FAV_TTL
        if fresh and not force:
            self._fill(self._favs, "")
            return
        self._fill([], f"Loading {a.name}'s favourites...")

        def done(gs):
            self._favs, self._favs_at, self._favs_of = gs, time.time(), a.id
            if self.favourites_mode():
                self._fill(gs, "" if gs else f"{a.name} has no favourite games yet - favourite games on roblox.com "
                                             "(or pick another main account in Settings).")
        bg(_favourite_games, a.user_id, a.cookie, done=done, err=lambda _: self._fill([], "Could not load favourites."))

    def _fill(self, gs: List[Game], note: str, dedupe: bool = False):
        self.list.clear()
        seen = set()
        for g in gs:
            key = g.universe_id or -g.place_id
            if dedupe and key in seen:
                continue
            seen.add(key)
            path = games.icon_path(g.universe_id) if g.universe_id else None
            pm = QPixmap(str(path)) if path is not None and path.exists() else None
            it = QListWidgetItem()
            it.setData(Qt.UserRole, g)
            it.setData(Qt.UserRole + 1, pm)
            it.setToolTip(g.name + (f"\n{games.short(g.players)} playing now" if g.players else "")
                          + "\nClick: choose it · double-click: launch the selected accounts · right-click: more")
            self.list.addItem(it)
            self.names[g.place_id] = g.name or self.names.get(g.place_id, "")
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.select_place(self.selected_place)

    def select_place(self, place_id: int):
        """Highlights the tile of the game that is chosen (if it is in the list)."""
        self.selected_place = place_id
        uni = games.cached_universe(place_id)
        self.list.clearSelection()
        for i in range(self.list.count()):
            g = self.list.item(i).data(Qt.UserRole)
            if g.place_id == place_id or (uni and g.universe_id == uni):
                self.list.setCurrentRow(i)
                return

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it:
            g = it.data(Qt.UserRole)
            popup(play_menu(self.mw, self, LaunchSpec(kind="Game", place_id=g.place_id), g.name),
                  self.list.viewport().mapToGlobal(pos))


class LaunchPage(QWidget):
    """Where the selected accounts go (Game / Server / Private server / Friend tabs) and the launch bar."""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.names = {e.place_id: e.name for e in store.settings.recent if e.name}     # place id -> game name
        s = store.settings
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 0, 0, 0)
        v.setSpacing(10)
        self._place = ""                # the chosen game: a Place ID or a link (set_place / place_text)

        self.sel = QLabel()
        self.sel.setObjectName("selection")
        self.sel.setWordWrap(True)
        v.addWidget(self.sel)

        # ---- where: one tab per kind of target
        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self.modes = QButtonGroup(self)
        self.rb_game = QPushButton("Game")
        self.rb_job = QPushButton("Server")
        self.rb_private = QPushButton("Private server")
        self.rb_follow = QPushButton("Friend")
        tips = ("Join a game - Roblox picks any public server", "Put the accounts into one exact server",
                "Join a private server (each account must be allowed in)", "Join the server a player is in")
        for i, (b, tip) in enumerate(zip((self.rb_game, self.rb_job, self.rb_private, self.rb_follow), tips)):
            b.setObjectName("modetab")
            b.setCheckable(True)
            b.setToolTip(tip)
            self.modes.addButton(b, i)
            tabs.addWidget(b)
        tabs.addStretch(1)
        v.addLayout(tabs)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        # Game
        self.strip = GameStrip(mw, self.names)
        self.strip.picked.connect(self.use_game)
        self.strip.launch.connect(lambda g: (self.use_game(g), self.mw.launch_selected()))
        self.strip.search.connect(self._search_or_link)
        self.stack.addWidget(self.strip)

        # Server
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        self.server_game = QLabel()
        self.server_game.setWordWrap(True)
        pv.addWidget(self.server_game)
        self.job = QLineEdit(s.last_job_id)
        self.job.setPlaceholderText("Job ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        self.job.textChanged.connect(lambda *_: self.update_launch_text())
        self.b_pick = btn("Pick server...", self.pick_server, "The game's servers, with Quick join: the emptiest "
                                                               "one, or a busy one with room for everyone", primary=True)
        pv.addWidget(row(self.job, stretch=False))
        pv.addWidget(row(self.b_pick, btn("Random", self.pick_random, "Any open public server of the game"),
                         btn("History...", lambda: HistoryDialog(self.mw).exec(),
                             tip="Servers your accounts joined - rejoin one")))
        pv.addWidget(hint("Tip: right-click a running account > <b>Bring accounts to its server</b> sends the others "
                          "into the server it is in."))
        pv.addStretch(1)
        self.stack.addWidget(page)

        # Private server
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        self.private = QLineEdit(s.last_private)
        self.private.setPlaceholderText("Private server link: roblox.com/share?code=...  or  ...?privateServerLinkCode=...")
        self.private.setClearButtonEnabled(True)
        self.private.textChanged.connect(lambda *_: self.update_launch_text())
        self.b_ps = btn("Save...", self._save_current_private, "Keep this link in the list below, with a name")
        pv.addWidget(row(self.private, self.b_ps, stretch=False))
        pv.addWidget(eyebrow("Saved private servers"))
        self.ps_list = QListWidget()
        self.ps_list.setObjectName("plainlist")
        self.ps_list.itemClicked.connect(lambda it: self.private.setText(it.data(Qt.UserRole).link))
        self.ps_list.itemDoubleClicked.connect(lambda it: (self.private.setText(it.data(Qt.UserRole).link),
                                                           self.mw.launch_selected()))
        self.ps_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ps_list.customContextMenuRequested.connect(self._private_menu)
        pv.addWidget(self.ps_list, 1)
        self.ps_empty = hint("Paste a private server link above and press <b>Save...</b> - it stays here for one "
                             "click next time.")
        pv.addWidget(self.ps_empty)
        self.stack.addWidget(page)

        # Friend
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        self.follow = QLineEdit(s.last_follow)
        self.follow.setPlaceholderText("Roblox username - or pick a friend below")
        self.follow.setClearButtonEnabled(True)
        self.follow.textChanged.connect(lambda *_: self.update_launch_text())
        self._friends_at, self._friends_of = 0.0, ""
        self.b_friends = btn("", lambda: self.load_friends(force=True), icon="refresh-cw",
                             tip="Reload the main account's friends (Settings > Main account)")
        pv.addWidget(row(self.follow, self.b_friends, stretch=False))
        self.friends_title = eyebrow("Friends online")
        pv.addWidget(self.friends_title)
        self.friend_list = QListWidget()
        self.friend_list.setObjectName("plainlist")
        self.friend_list.setIconSize(QSize(32, 32))
        self.friend_list.itemClicked.connect(lambda it: self.follow.setText(it.data(Qt.UserRole)))
        self.friend_list.itemDoubleClicked.connect(lambda it: (self.follow.setText(it.data(Qt.UserRole)),
                                                               self.mw.launch_selected()))
        pv.addWidget(self.friend_list, 1)
        self.stack.addWidget(page)

        # ---- options + the launch bar
        self.delay = spin(0, 600, s.launch_delay_sec, self._delay, " s",
                          "Starting many clients at the same instant often makes some fail to load. 6-10 s is a good default.")
        self.use_saved = chk("Accounts with their own game go there", s.use_saved_per_account, self._use_saved,
                             "Accounts with their own game (Edit account) join it; the others go where this panel says.")
        more = btn("...", self._more_menu, "More")
        self._more = more
        v.addWidget(row(QLabel("Pause between accounts"), self.delay, self.use_saved, None, more, stretch=False))
        bar = QWidget()
        bar.setObjectName("launchbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(10, 10, 10, 10)
        self.b_launch = btn("Launch selected", self.mw.launch_selected, icon="play", primary=True)
        self.b_launch.setObjectName("launchbtn")
        self.b_launch.setMinimumHeight(38)
        self.b_launch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.b_all = btn("Launch all listed", self.mw.launch_all_listed,
                         "Every account the list shows (search / group filter), not only the selected ones")
        self.b_stop = btn("Cancel", self.mw.stop_launch, tip="Stop a launch sequence that is still going")
        self.b_stop.setEnabled(False)
        for b in (self.b_all, self.b_stop):
            b.setMinimumHeight(38)
        bh.addWidget(self.b_launch, 1)
        bh.addWidget(self.b_all)
        bh.addWidget(self.b_stop)
        v.addWidget(bar)
        self.queue = LaunchQueue(self.mw)
        v.addWidget(self.queue)

        self.modes.idToggled.connect(self._mode_changed)
        {"Job": self.rb_job, "Private": self.rb_private, "Follow": self.rb_follow}.get(s.last_mode, self.rb_game).setChecked(True)
        self.set_place(s.last_place_id)
        self._fill_private()
        self.update_selection([])

    # ------------------------------------------------------------
    def _delay(self, v):
        store.settings.launch_delay_sec = v
        store.save_settings()

    def _use_saved(self, v):
        store.settings.use_saved_per_account = v
        store.save_settings()

    def _mode_changed(self, i: int, on: bool):
        if not on:
            return
        self.stack.setCurrentIndex(i)
        if self.rb_follow.isChecked():
            self.load_friends()
        self._server_game_text()
        self.update_launch_text()

    def place_text(self) -> str:
        return self._place

    def set_place(self, text) -> None:
        """The chosen game: a Place ID or a game link."""
        self._place = str(text or "").strip()
        pid = util.parse_place_id(self._place)
        self.strip.select_place(pid)
        if pid > 0 and not self.names.get(pid):
            def named(n, pid=pid):
                if n:
                    self.names[pid] = n
                    self._server_game_text()
                    self.update_launch_text()
            bg(api.place_name, pid, done=named)
        self._server_game_text()
        self.update_launch_text()

    def game_name(self) -> str:
        pid = util.parse_place_id(self._place)
        return self.names.get(pid) or (f"place {pid}" if pid > 0 else "")

    def _server_game_text(self):
        n = self.game_name()
        self.server_game.setText(f"Servers of <b>{n}</b> - pick another game on the Game tab." if n else
                                 theme.span("warn", "Pick a game on the Game tab first."))

    def use_game(self, g: Game):
        """A game from Your games / search / a link becomes the game; 'Server' keeps its tab (it picks a server
        of this game), the other tabs switch to Game."""
        if g.name:
            self.names[g.place_id] = g.name
        self.set_place(g.place_id)
        if not self.rb_job.isChecked():
            self.rb_game.setChecked(True)

    def _search_or_link(self, text: str):
        if util.parse_place_id(text) > 0:           # a pasted link or Place ID
            self.set_place(text)
            self.rb_game.setChecked(True)
            self.strip.find.clear()
        else:
            self.search_game(text)

    def update_launch_text(self):
        """The launch button says what will happen: how many accounts, and where."""
        selected = self.mw.selected_accounts() if hasattr(self.mw, "table") else []
        n = len(selected)
        action = util.launch_action((a.id for a in selected), self.mw.model.running)
        mode = self.mode()
        where = ""
        if mode == "Game":
            where = self.game_name()
        elif mode == "Job":
            name = self.game_name()
            where = f"one server of {name}" if name and self.job.text().strip() else ""
        elif mode == "Private":
            link = self.private.text().strip()
            ps = next((p for p in store.settings.private_servers if p.link == link), None)
            where = (ps.name if ps else "a private server") if link else ""
        else:
            name = self.follow.text().strip()
            where = f"{name}'s server" if name else ""
        who = "1 account" if n == 1 else f"{n} accounts"
        if not n:
            text = "Select accounts to launch"
        elif where:
            text = f"{action} {who} into {where}"
        else:
            text = f"{action} {who}"
        fm = self.b_launch.fontMetrics()
        self.b_launch.setText(fm.elidedText(text, Qt.ElideRight, max(200, self.b_launch.width() - 60)))
        self.b_launch.setToolTip(text + ("" if n else " - click accounts in the list (Ctrl / Shift for several)"))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.update_launch_text()

    def _more_menu(self):
        m = QMenu(self)
        m.addAction("Save this game to the selected accounts", self.save_to_selected)
        popup(m, self._more.mapToGlobal(self._more.rect().bottomLeft()))

    # ---- private servers (saved links)
    def _fill_private(self):
        self.ps_list.clear()
        for ps in store.settings.private_servers:
            game = self.names.get(ps.place_id, "") if ps.place_id else ""
            it = QListWidgetItem(ps.name + (f"   ·   {game}" if game else ""))
            it.setToolTip(ps.link + "\nClick: use it · double-click: launch the selected accounts · right-click: more")
            it.setData(Qt.UserRole, ps)
            self.ps_list.addItem(it)
        has = bool(store.settings.private_servers)
        self.ps_list.setVisible(has)
        self.ps_empty.setVisible(not has)

    def _save_current_private(self):
        link = self.private.text().strip()
        if not (util.share_code_of(link) or util.private_link_code(link)):
            return warn(self, "Private server", "Paste a private server link first (roblox.com/share?code=... or "
                                                "...?privateServerLinkCode=...).")
        self._save_private(link)

    def _save_private(self, link: str):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Save private server", "A name for it:",
                                        text=f"Private server {len(store.settings.private_servers) + 1}")
        if not ok:
            return
        pid = util.parse_place_id(self._place)
        store.settings.private_servers.append(PrivateServer(max(0, pid), name.strip() or "Private server", link))
        store.save_settings()
        self._fill_private()
        self.update_launch_text()
        self.mw.log(f"Saved private server '{name.strip() or 'Private server'}'.")

    def _private_menu(self, pos):
        it = self.ps_list.itemAt(pos)
        if not it:
            return
        ps = it.data(Qt.UserRole)
        m = play_menu(self.mw, self, private_spec(ps), ps.name)
        m.addSeparator()
        m.addAction("Copy link", lambda: QGuiApplication.clipboard().setText(ps.link))
        m.addAction("Remove", lambda: self._remove_private(ps))
        popup(m, self.ps_list.viewport().mapToGlobal(pos))

    def _remove_private(self, ps: PrivateServer):
        store.settings.private_servers.remove(ps)
        store.save_settings()
        self._fill_private()

    # ---- friends to follow (the main account's)
    def main_account_changed(self):
        self._friends_at = 0.0
        self.strip.refresh()
        if self.rb_follow.isChecked():
            self.load_friends()

    def load_friends(self, force: bool = False):
        a = self.mw.main_account()
        if not a:
            self.friends_title.setText("Add an account to see its friends here".upper())
            return
        if not force and self._friends_of == a.id and time.time() - self._friends_at < 60:
            return
        self._friends_at, self._friends_of = time.time(), a.id
        self.b_friends.setEnabled(False)
        self.friends_title.setText(f"Loading {a.name}'s friends...".upper())

        def done(res):
            self.b_friends.setEnabled(True)
            fr, err = res
            if err:
                self.friends_title.setText(f"Could not load {a.name}'s friends: {err}".upper())
                return
            order = {2: 0, 1: 1, 3: 2, 0: 3}             # in game, online, in Studio, offline
            fr = sorted((f for f in fr if f.presence and f.presence.type), key=lambda f: (
                order.get(f.presence.type, 3), (f.display_name or f.name).lower()))
            self._show_friends(fr)
            self.friends_title.setText((f"{a.name}'s friends online - {len(fr)}" if fr else
                                        f"None of {a.name}'s friends is online right now").upper())
            bg(_friend_avatars, [f.user_id for f in fr[:80]], done=lambda n: n and self._show_friends(fr))
        bg(api.friends, a.cookie, a.user_id, done=done, err=lambda _: self.b_friends.setEnabled(True))

    def _show_friends(self, fr):
        self.friend_list.clear()
        for f in fr:
            who = f.display_name if f.display_name and f.display_name != f.name else f.name
            t = f.presence.type
            where = (f"playing {f.presence.location}" if t == 2 and f.presence.location else
                     "in a game" if t == 2 else "in Studio" if t == 3 else "online")
            path = paths.AVATAR_DIR / f"{f.user_id}.png"
            it = QListWidgetItem(QIcon(str(path)) if path.exists() else QIcon(), f"{who}  (@{f.name})   ·   {where}")
            it.setForeground(theme.qc("text" if t == 2 else "muted"))
            it.setData(Qt.UserRole, f.name)
            it.setToolTip("Click: follow them · double-click: launch the selected accounts into their server")
            self.friend_list.addItem(it)

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
        self.update_launch_text()

    def refresh_recent(self):
        for e in store.settings.recent:
            if e.name:
                self.names[e.place_id] = e.name
        if not self.strip.favourites_mode():
            self.strip.refresh()
        self._server_game_text()
        self.update_launch_text()

    def mode(self) -> str:
        return ("Job" if self.rb_job.isChecked() else "Private" if self.rb_private.isChecked()
                else "Follow" if self.rb_follow.isChecked() else "Game")

    def read_form(self) -> LaunchForm:
        """Snapshot of the form; also remembers it in the settings."""
        f = LaunchForm(self.mode(), self._place, self.job.text().strip(), self.private.text().strip(),
                       self.follow.text().strip())
        s = store.settings
        s.last_mode, s.last_place_id, s.last_job_id, s.last_private, s.last_follow = f.mode, f.place, f.job, f.private, f.follow
        store.save_settings()
        return f

    def load(self):
        s = store.settings
        {"Job": self.rb_job, "Private": self.rb_private, "Follow": self.rb_follow}.get(s.last_mode, self.rb_game).setChecked(True)
        self.set_place(s.last_place_id)
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
    def search_game(self, query: str = ""):
        d = GamePicker(self, self.mw.any_cookie(), query)
        if d.exec() and d.result:
            self.names[d.result.place_id] = d.result.name
            self.set_place(d.result.place_id)
            if not self.rb_job.isChecked():
                self.rb_game.setChecked(True)
            self.strip.find.clear()
            self.mw.log(f"Game selected: {d.result.name} ({d.result.place_id}).")
            self.mw.add_recent(d.result.place_id, d.result.name)

    def pick_server(self):
        pid = util.parse_place_id(self._place)
        if pid <= 0:
            self.mw.log("Choose a game first (Game tab: Your games, or search).")
            return
        d = ServerPicker(self, pid, self.mw.any_cookie(), need=max(1, len(self.mw.selected_accounts())))
        if d.exec() and d.result:
            self.job.setText(d.result)
            self.rb_job.setChecked(True)
            self.mw.log("Server selected: " + d.result)

    def pick_random(self):
        pid = util.parse_place_id(self._place)
        if pid <= 0:
            self.mw.log("Choose a game first (Game tab: Your games, or search).")
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
        pid = util.parse_place_id(self._place)
        for a in sel:
            a.saved_place_id = str(pid) if pid else ""
            a.game_link = f"https://www.roblox.com/games/{pid}" if pid else ""
            a.saved_job_id = self.job.text().strip() if self.rb_job.isChecked() else ""
        store.save_accounts()
        self.mw.refresh_accounts()
        self.mw.log(f"Saved Place {pid or '(none)'} to {len(sel)} account(s).")


class HistoryDialog(Dialog):
    """History: every session (an account in one server, from its Roblox log) with how long it lasted, and the
    time played in the last 7 days per account and game. Rejoin any server. Local only (settings.history)."""

    def __init__(self, mw, account: Optional[Account] = None):
        super().__init__(mw)
        from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHeaderView, QTabWidget, QTableWidget
        self.mw = mw
        self.setWindowTitle("History")
        self.resize(820, 560)
        v = QVBoxLayout(self)
        v.addWidget(hint("What your accounts played while Cellar ran, newest first - kept on this PC only. "
                         "Double-click a session (or <b>Rejoin</b>) to put accounts back into that exact server."))
        self.who = QComboBox()
        self.who.addItem("All accounts", "")
        for a in store.accounts:
            self.who.addItem(a.name, a.id)
        if account is not None:
            self.who.setCurrentIndex(max(0, self.who.findData(account.id)))
        self.who.currentIndexChanged.connect(lambda *_: self.fill())
        v.addWidget(row(QLabel("Show"), self.who))
        self.tabs = QTabWidget()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["When", "Account", "Game", "How long", "Server"])
        self.totals = QTableWidget(0, 4)
        self.totals.setHorizontalHeaderLabels(["Account", "Game", "Sessions", "Time played"])
        for t in (self.table, self.totals):
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
            t.setSelectionMode(QAbstractItemView.SingleSelection)
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.verticalHeader().hide()
            t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.totals.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda *_: self.rejoin())
        self.tabs.addTab(self.table, "Sessions")
        self.tabs.addTab(self.totals, "Time played (last 7 days)")
        v.addWidget(self.tabs, 1)
        self.empty = hint("Nothing yet - sessions are recorded from the Roblox log while Cellar runs.")
        v.addWidget(self.empty)
        self.rejoin_btn = btn("Rejoin...", self.rejoin, primary=True)
        v.addWidget(row(self.rejoin_btn, btn("Copy Job ID", self.copy), btn("Clear history", self.clear),
                        None, btn("Close", self.reject), stretch=False))
        self.fill()

    def _recs(self):
        aid = self.who.currentData()
        return [h for h in store.settings.history if not aid or h.account_id == aid]

    def fill(self):
        from PySide6.QtWidgets import QTableWidgetItem
        names = {e.place_id: e.name for e in store.settings.recent if e.name}
        recs = self._recs()
        self._rows = recs
        self.table.setRowCount(len(recs))
        for r, h in enumerate(recs):
            secs = sessions.duration(h)
            took = "-" if secs < 0 else ("playing now · " if not h.end else "") + sessions.human(secs)
            when = time.strftime("%a %d %b  %H:%M", time.localtime(h.ts))
            for c, text in enumerate((when, h.account, names.get(h.place_id) or f"place {h.place_id}", took,
                                      h.job_id[:8] + "…")):
                it = QTableWidgetItem(text)
                if c == 4:
                    it.setToolTip(h.job_id)
                if c == 3 and not h.end:
                    it.setForeground(theme.qc("good"))
                self.table.setItem(r, c, it)
        aid = self.who.currentData()
        rows = sessions.totals(recs, since=time.time() - 7 * 86400)
        per_acc = {}
        for a, _, n, secs in rows:
            per_acc[a] = per_acc.get(a, 0.0) + secs
        lines = rows + ([] if aid or len(per_acc) < 2 else [(a, -1, 0, t) for a, t in
                                                           sorted(per_acc.items(), key=lambda x: -x[1])])
        self.totals.setRowCount(len(lines))
        for r, (a, place, n, secs) in enumerate(lines):
            total = place == -1                 # one line per account at the bottom: all its games together
            cells = (a, "all games" if total else names.get(place) or f"place {place}",
                     "" if total else str(n), sessions.human(secs))
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if total:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.totals.setItem(r, c, it)
        self.empty.setVisible(not recs)

    def _rec(self):
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def rejoin(self):
        h = self._rec()
        if h:
            spec = LaunchSpec(kind="Job", place_id=h.place_id, job_id=h.job_id)
            popup(play_menu(self.mw, self, spec, "that server"),
                  self.rejoin_btn.mapToGlobal(self.rejoin_btn.rect().bottomLeft()))

    def copy(self):
        h = self._rec()
        if h:
            QGuiApplication.clipboard().setText(h.job_id)

    def clear(self):
        if not ask(self, "Clear history", "Remove every recorded session (and the time played)?"):
            return
        store.settings.history.clear()
        store.save_settings()
        self.fill()


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
