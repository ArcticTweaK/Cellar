"""Home tab: the part of Cellar that replaces the Roblox website - search, continue playing, friends online,
favourites and Roblox's own discover lists. Every game opens a game page; Play picks which account(s) play.

Cards are painted (no child widgets each), icons come from the disk cache in games.ICON_DIR and are loaded once.
"""

import time
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton,
                               QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from .. import api, games, paths, playlink, store, theme, util
from ..games import Game
from ..models import Account, LaunchSpec, PrivateServer
from .common import bg, btn, hint, warn

_pix: Dict[str, QPixmap] = {}           # "g<universe>" / "u<user>" -> pixmap (loaded once from the disk cache)


def _pixmap(key: str, path) -> Optional[QPixmap]:
    pm = _pix.get(key)
    if pm is None and path.exists():
        pm = QPixmap(str(path))
        if pm.isNull():
            return None
        _pix[key] = pm
    return pm


def forget_pixmaps(keys) -> None:
    for k in keys:
        _pix.pop(k, None)


def _rounded(p: QPainter, r: QRect, radius: float, pm: Optional[QPixmap], fallback) -> None:
    path = QPainterPath()
    path.addRoundedRect(QRectF(r), radius, radius)
    p.save()
    p.setClipPath(path)
    if pm is not None:
        p.drawPixmap(r, pm)
    else:
        p.fillRect(r, fallback)
    p.restore()


# ---------------------------------------------------------------- play menu (cards, game page, friends)
def play_menu(mw, parent: QWidget, spec: LaunchSpec, title: str = "") -> QMenu:
    m = QMenu(parent)
    sel = mw.selected_accounts()
    home = mw.home_page.home_account()

    def go(accs: List[Account]):
        if accs:
            mw.log(f"Playing {title or spec.describe()} with {', '.join(a.name for a in accs[:4])}"
                   + (f" and {len(accs) - 4} more" if len(accs) > 4 else "") + ".")
            mw.start_launch(accs, fixed=spec, allow_saved=False)

    if sel:
        m.addAction(f"Play with the {len(sel)} selected account(s)" if len(sel) > 1 else f"Play with {sel[0].name}",
                    lambda: go(sel))
    if home and home not in sel:
        m.addAction(f"Play with {home.name}", lambda: go([home]))
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
        m.addAction("Copy game link", lambda: QGuiApplication.clipboard().setText(
            f"https://www.roblox.com/games/{spec.place_id}"))
    return m


# ---------------------------------------------------------------- cards
class GameCard(QWidget):
    W, H, ICON = 150, 214, 134
    clicked = Signal(object)
    menu = Signal(object, object)       # game, global position

    def __init__(self, g: Game):
        super().__init__()
        self.g = g
        self.hover = False
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(g.name)

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self.g)
        elif ev.button() == Qt.RightButton:
            self.menu.emit(self.g, ev.globalPosition().toPoint())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(theme.qc("accent") if self.hover else theme.qc("border"))
        p.setBrush(theme.qc("raised") if self.hover else theme.qc("surface"))
        p.drawRoundedRect(r, 10, 10)
        icon = QRect(8, 8, self.ICON, self.ICON)
        _rounded(p, icon, 8, _pixmap(f"g{self.g.universe_id}", games.icon_path(self.g.universe_id)),
                 theme.qc("raised"))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.qc("text"))
        fm = QFontMetrics(f)
        name_r = QRect(9, icon.bottom() + 6, self.W - 18, fm.height() * 2)
        lines = _wrap2(self.g.name, fm, name_r.width())
        p.drawText(name_r, Qt.AlignLeft | Qt.AlignTop, "\n".join(lines))
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(f)
        y = self.H - QFontMetrics(f).height() - 7
        x = 9
        if self.g.players:
            p.setPen(theme.qc("good"))
            t = f"● {games.short(self.g.players)}"
            p.drawText(x, y, 200, 20, Qt.AlignLeft | Qt.AlignTop, t)
            x += QFontMetrics(f).horizontalAdvance(t) + 10
        if self.g.rating is not None:
            p.setPen(theme.qc("muted"))
            p.drawText(x, y, 200, 20, Qt.AlignLeft | Qt.AlignTop, f"👍 {self.g.rating}%")


def _wrap2(text: str, fm: QFontMetrics, width: int) -> List[str]:
    """Two lines, the second elided."""
    words, line, out = text.split(), "", []
    for i, w in enumerate(words):
        test = (line + " " + w).strip()
        if fm.horizontalAdvance(test) <= width or not line:
            line = test
        else:
            out.append(line)
            out.append(fm.elidedText(" ".join(words[i:]), Qt.ElideRight, width))
            return out
    return [fm.elidedText(line, Qt.ElideRight, width)] if line else []


class FriendChip(QWidget):
    W, H = 92, 118
    clicked = Signal(object, object)

    def __init__(self, f):
        super().__init__()
        self.f = f
        self.hover = False
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        where = f.presence.location if f.presence and f.presence.type == 2 else ""
        self.setToolTip(f"{f.display_name or f.name} (@{f.name})" + (f"\nIn {where}" if where else "\nOnline"))

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, ev):
        self.clicked.emit(self.f, ev.globalPosition().toPoint())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        av = QRect((self.W - 64) // 2, 6, 64, 64)
        pm = _pixmap(f"u{self.f.user_id}", paths.AVATAR_DIR / f"{self.f.user_id}.png")
        _rounded(p, av, 32, pm, theme.qc("raised"))
        in_game = bool(self.f.presence and self.f.presence.type == 2)
        p.setPen(theme.qc("surface"))
        p.setBrush(theme.qc("good") if in_game else theme.qc("accent"))
        p.drawEllipse(av.right() - 15, av.bottom() - 15, 16, 16)
        if self.hover:
            p.setPen(theme.qc("accent"))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(av.adjusted(-2, -2, 2, 2))
        f = QFont(self.font())
        fm = QFontMetrics(f)
        p.setPen(theme.qc("text"))
        p.drawText(QRect(2, av.bottom() + 6, self.W - 4, fm.height()), Qt.AlignHCenter,
                   fm.elidedText(self.f.display_name or self.f.name, Qt.ElideRight, self.W - 4))
        f.setPointSizeF(f.pointSizeF() * 0.85)
        p.setFont(f)
        fm = QFontMetrics(f)
        p.setPen(theme.qc("good") if in_game else theme.qc("muted"))
        where = self.f.presence.location if in_game else "Online"
        p.drawText(QRect(2, av.bottom() + 8 + fm.height() + 4, self.W - 4, fm.height()), Qt.AlignHCenter,
                   fm.elidedText(where or "In a game", Qt.ElideRight, self.W - 4))


class _HScroll(QScrollArea):
    """A horizontal row. The normal mouse wheel is passed on, so it always scrolls the whole page (also with the
    pointer over a card); the row itself moves with its arrow buttons, a sideways touchpad swipe or Shift+wheel."""

    def wheelEvent(self, ev):
        d = ev.angleDelta()
        sideways = d.x() if d.x() else (d.y() if ev.modifiers() & Qt.ShiftModifier else 0)
        if not sideways:
            # hand it straight to the page's scroll area (more reliable than letting it bubble up)
            w = self.parentWidget()
            while w is not None and not isinstance(w, QScrollArea):
                w = w.parentWidget()
            if w is not None:
                QApplication.sendEvent(w.viewport(), ev.clone())
            ev.accept()
            return
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - sideways)
        ev.accept()


class Shelf(QWidget):
    """A titled row of cards."""

    def __init__(self, title: str, height: int):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 2)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.title = QLabel(title)
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.15)
        f.setBold(True)
        self.title.setFont(f)
        head.addWidget(self.title)
        self.note = QLabel()
        self.note.setObjectName("stat_sub")
        head.addWidget(self.note)
        head.addStretch(1)
        self.prev = QPushButton("‹")
        self.next = QPushButton("›")
        for b, step in ((self.prev, -1), (self.next, 1)):
            b.setObjectName("shelf_arrow")
            b.setFixedSize(30, 26)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, step=step: self.page(step))
            head.addWidget(b)
        v.addLayout(head)
        self.area = _HScroll()
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # the arrows do it, like Roblox
        self.area.setWidgetResizable(True)
        self.area.setFixedHeight(height + 4)
        bar = self.area.horizontalScrollBar()
        bar.valueChanged.connect(self._arrows)
        bar.rangeChanged.connect(self._arrows)
        self._anim = QPropertyAnimation(bar, b"value", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.inner = QWidget()
        self.row = QHBoxLayout(self.inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(10)
        self.row.addStretch(1)
        self.area.setWidget(self.inner)
        v.addWidget(self.area)
        self.empty = hint("")
        self.empty.hide()
        v.addWidget(self.empty)

    def page(self, step: int):
        """Slides one screenful of cards (keeps the first visible card whole)."""
        bar = self.area.horizontalScrollBar()
        card = (self.cards()[0].width() + self.row.spacing()) if self.cards() else 160
        span = max(card, (self.area.viewport().width() // card) * card)
        start = self._anim.endValue() if self._anim.state() == QPropertyAnimation.Running else bar.value()
        target = max(0, min(bar.maximum(), int(start) + step * span))
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()

    def _arrows(self, *_):
        bar = self.area.horizontalScrollBar()
        more = bar.maximum() > 0
        self.prev.setVisible(more)
        self.next.setVisible(more)
        self.prev.setEnabled(bar.value() > 0)
        self.next.setEnabled(bar.value() < bar.maximum())

    def set_widgets(self, widgets: List[QWidget], empty_text: str = ""):
        while self.row.count() > 1:
            it = self.row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for w in widgets:
            self.row.insertWidget(self.row.count() - 1, w)
        self.area.setVisible(bool(widgets))
        self.area.horizontalScrollBar().setValue(0)
        self._arrows()
        self.empty.setText(empty_text)
        self.empty.setVisible(not widgets and bool(empty_text))

    def cards(self) -> List[QWidget]:
        return [self.row.itemAt(i).widget() for i in range(self.row.count() - 1)]


# ---------------------------------------------------------------- game page
class GameView(QWidget):
    """A game's page: picture, stats, Play / Servers / Favourite, description, your private servers. Shown inside
    the Library, or in a window (GameDialog) from Home."""

    leave = Signal()            # it sent you somewhere else (Servers): a window closes itself

    def __init__(self, mw, g: Game):
        super().__init__()
        self.mw, self.g = mw, g
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(150, 150)
        top.addWidget(self.icon, 0, Qt.AlignTop)
        info = QVBoxLayout()
        self.name_label = name = QLabel(g.name)
        f = name.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setBold(True)
        name.setFont(f)
        name.setWordWrap(True)
        info.addWidget(name)
        self.by = QLabel()
        self.by.setObjectName("stat_sub")
        info.addWidget(self.by)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setTextFormat(Qt.RichText)
        info.addWidget(self.stats)
        info.addStretch(1)
        play = btn("Play", None, icon="play", primary=True)
        play.setMinimumHeight(36)
        play.clicked.connect(lambda: play_menu(mw, self, LaunchSpec(kind="Game", place_id=g.place_id), g.name)
                             .exec(play.mapToGlobal(play.rect().bottomLeft())))
        buttons = QHBoxLayout()
        buttons.addWidget(play)
        buttons.addWidget(btn("Servers", lambda: (mw.open_servers(g.place_id), self.leave.emit())))
        self.fav = btn("☆ Favourite", self._toggle_fav)
        self.fav.setEnabled(False)
        self.fav_state: Optional[bool] = None
        buttons.addWidget(self.fav)
        buttons.addWidget(btn("Open on roblox.com", lambda: _open_url(f"https://www.roblox.com/games/{g.place_id}")))
        buttons.addStretch(1)
        info.addLayout(buttons)
        top.addLayout(info, 1)
        v.addLayout(top)
        self.desc = QTextBrowser()
        self.desc.setOpenExternalLinks(True)
        v.addWidget(self.desc, 1)
        v.addWidget(self._private_servers())
        self._show()
        if not g.description or not g.visits:          # list entries come without the full details
            bg(_complete, g, done=lambda _: self._show())
        self.acc = mw.home_page.home_account()
        if self.acc and g.universe_id:
            self.fav.setToolTip(f"Favourite on {self.acc.name}'s Roblox account")
            bg(games.is_favourite, g.universe_id, self.acc.cookie, done=self._fav_state)

    # ---- your private servers for this game (saved links)
    def _private_servers(self) -> QWidget:
        box = QWidget()
        bv = QVBoxLayout(box)
        bv.setContentsMargins(0, 6, 0, 0)
        head = QHBoxLayout()
        t = QLabel("Your private servers")
        f = t.font()
        f.setBold(True)
        t.setFont(f)
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(btn("Add...", self._add_ps))
        bv.addLayout(head)
        self.ps_list = QListWidget()
        self.ps_list.setMaximumHeight(110)
        self.ps_list.itemDoubleClicked.connect(lambda it: self._play_ps(it))
        self.ps_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ps_list.customContextMenuRequested.connect(self._ps_menu)
        bv.addWidget(self.ps_list)
        self.ps_empty = hint("Save private server links here (Add...) and join them with one click.")
        bv.addWidget(self.ps_empty)
        self._fill_ps()
        return box

    def _mine(self) -> List[PrivateServer]:
        return [p for p in store.settings.private_servers if p.place_id == self.g.place_id]

    def _fill_ps(self):
        self.ps_list.clear()
        for ps in self._mine():
            it = QListWidgetItem(f"{ps.name}")
            it.setToolTip(ps.link)
            it.setData(Qt.UserRole, ps)
            self.ps_list.addItem(it)
        self.ps_list.setVisible(bool(self._mine()))
        self.ps_empty.setVisible(not self._mine())

    def _add_ps(self):
        from PySide6.QtWidgets import QInputDialog
        clip = QGuiApplication.clipboard().text().strip()
        guess = clip if ("privateServerLinkCode=" in clip or "share?code=" in clip) else ""
        link, ok = QInputDialog.getText(self, "Add a private server", "Private server link "
                                        "(roblox.com/share?code=... or ...?privateServerLinkCode=...):", text=guess)
        link = link.strip()
        if not ok or not link:
            return
        if not (util.share_code_of(link) or util.private_link_code(link)):
            return warn(self, "Private server", "That is not a private server link.")
        name, ok = QInputDialog.getText(self, "Add a private server", "A name for it:",
                                        text=f"Private server {len(self._mine()) + 1}")
        if not ok:
            return
        store.settings.private_servers.append(PrivateServer(self.g.place_id, name.strip() or "Private server", link))
        store.save_settings()
        self._fill_ps()

    def _spec(self, ps: PrivateServer) -> LaunchSpec:
        share = util.share_code_of(ps.link)
        if share:           # resolved per account when it launches (each account must be allowed in)
            return LaunchSpec(kind="Private", place_id=ps.place_id, share_code=share)
        return LaunchSpec(kind="Private", place_id=ps.place_id, link_code=util.private_link_code(ps.link))

    def _play_ps(self, it, pos=None):
        ps = it.data(Qt.UserRole)
        play_menu(self.mw, self, self._spec(ps), ps.name).exec(pos or QCursor.pos())

    def _ps_menu(self, pos):
        it = self.ps_list.itemAt(pos)
        if not it:
            return
        ps = it.data(Qt.UserRole)
        m = play_menu(self.mw, self, self._spec(ps), ps.name)
        m.addSeparator()
        m.addAction("Copy link", lambda: QGuiApplication.clipboard().setText(ps.link))
        m.addAction("Remove", lambda: (store.settings.private_servers.remove(ps), store.save_settings(),
                                       self._fill_ps()))
        m.exec(self.ps_list.viewport().mapToGlobal(pos))

    def _fav_state(self, on):
        self.fav_state = on
        self.fav.setEnabled(on is not None)
        self.fav.setText("★ Favourited" if on else "☆ Favourite")

    def _toggle_fav(self):
        want = not self.fav_state
        self.fav.setEnabled(False)

        def done(err):
            if err:
                self.fav.setEnabled(True)
                return warn(self, "Favourite", f"Roblox did not accept it: {err}")
            self._fav_state(want)
            self.mw.home_page.load_favourites()
        bg(games.set_favourite, self.g.universe_id, self.acc.cookie, want, done=done)

    def _show(self):
        g = self.g
        pm = _pixmap(f"g{g.universe_id}", games.icon_path(g.universe_id)) if g.universe_id else None
        if pm is not None:
            self.icon.setPixmap(pm.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.name_label.setText(g.name)
        self.by.setText(f"by {g.creator}" if g.creator else "")
        bits = []
        if g.players:
            bits.append(theme.span("good", f"● {games.short(g.players)} playing"))
        if g.rating is not None:
            bits.append(f"👍 {g.rating}%")
        if g.visits:
            bits.append(f"{games.short(g.visits)} visits")
        if g.max_players:
            bits.append(f"{g.max_players} per server")
        if g.genre:
            bits.append(g.genre)
        if g.updated:
            bits.append(f"updated {g.updated}")
        self.stats.setText(" &nbsp;·&nbsp; ".join(bits))
        self.desc.setPlainText(g.description or "")


def _complete(g: Game) -> None:
    """Worker thread: everything a game page shows, for a game that may only have its place id."""
    if not g.universe_id:
        g.universe_id = games.universes([g.place_id]).get(g.place_id, 0)
    if g.universe_id:
        games.fill([g])
        games.fetch_icons([g.universe_id])


class GameDialog(QDialog):
    """The game page in its own window (Home's cards)."""

    def __init__(self, mw, g: Game):
        super().__init__(mw)
        self.setWindowTitle(g.name or "Game")
        self.resize(760, 600)
        v = QVBoxLayout(self)
        self.view = GameView(mw, g)
        self.view.leave.connect(self.accept)
        v.addWidget(self.view)


def _open_url(url: str):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(url))


# ---------------------------------------------------------------- the page
class HomePage(QWidget):
    REFRESH_SEC = 300

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.loaded_at = 0.0
        self._busy = 0
        outer = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Roblox games...")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.do_search)
        self.search.textChanged.connect(lambda t: None if t.strip() else self.results.hide())
        bar.addWidget(self.search, 1)
        self.acc_label = QLabel("Home for")
        bar.addWidget(self.acc_label)
        self.acc = QComboBox()
        self.acc.setToolTip("Whose friends and favourites are shown")
        self.acc.currentIndexChanged.connect(self._account_changed)
        bar.addWidget(self.acc)
        self.refresh_btn = btn("Refresh", lambda: self.load(force=True), icon="refresh-cw")
        bar.addWidget(self.refresh_btn)
        outer.addLayout(bar)

        body = QWidget()
        self.v = QVBoxLayout(body)
        self.v.setContentsMargins(0, 0, 8, 0)
        self.v.setSpacing(4)
        self.results = Shelf("Search results", GameCard.H)
        self.results.hide()
        self.recent = Shelf("Continue playing", GameCard.H)
        self.friends = Shelf("Friends online", FriendChip.H)
        self.favs = Shelf("Favourites", GameCard.H)
        for s in (self.results, self.recent, self.friends, self.favs):
            self.v.addWidget(s)
        self.discover: List[Shelf] = []
        self.v.addStretch(1)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.fill_accounts()

    # ------------------------------------------------------------ accounts
    def fill_accounts(self):
        cur = store.settings.home_account
        self.acc.blockSignals(True)
        self.acc.clear()
        accs = sorted((a for a in store.accounts if a.user_id and a.cookie), key=lambda a: (not a.full_quality, a.order))
        for a in accs:
            self.acc.addItem(a.name, a.id)
        i = self.acc.findData(cur)
        self.acc.setCurrentIndex(i if i >= 0 else 0)
        self.acc.blockSignals(False)
        self.acc.setVisible(bool(accs))
        self.acc_label.setVisible(bool(accs))
        if hasattr(self.mw, "me"):
            self.mw.me.set_account(self.home_account())

    def home_account(self) -> Optional[Account]:
        return store.find_by_id(self.acc.currentData() or "") if self.acc.count() else None

    def _account_changed(self, _):
        store.settings.home_account = self.acc.currentData() or ""
        store.save_settings()
        if hasattr(self.mw, "me"):
            self.mw.me.set_account(self.home_account())
        self.load_friends()
        self.load_favourites()

    # ------------------------------------------------------------ loading
    def showEvent(self, ev):
        super().showEvent(ev)
        self.fill_accounts()
        if time.time() - self.loaded_at > self.REFRESH_SEC:
            self.load()

    def load(self, force: bool = False):
        self.loaded_at = time.time()
        self.load_recent()
        self.load_friends()
        self.load_favourites()
        self.load_discover()

    def _task(self, fn, *args, done: Callable):
        self._busy += 1
        self.refresh_btn.setEnabled(False)

        def fin(res):
            self._busy -= 1
            self.refresh_btn.setEnabled(self._busy == 0)
            done(res)
        bg(fn, *args, done=fin, err=lambda _: fin(None))

    def _game_cards(self, shelf: Shelf, gs: Optional[List[Game]], empty: str):
        cards = []
        for g in gs or []:
            c = GameCard(g)
            c.clicked.connect(self.open_game)
            c.menu.connect(self.game_menu)
            cards.append(c)
        shelf.set_widgets(cards, empty)
        ids = [g.universe_id for g in gs or [] if not games.icon_path(g.universe_id).exists()]
        if ids:
            bg(games.fetch_icons, ids, done=lambda _: [c.update() for c in shelf.cards()])

    def load_recent(self):
        ids = [e.place_id for e in store.settings.recent[:20]]
        if not ids:
            self.recent.set_widgets([], "Games you and your accounts play show up here.")
            return
        self._task(games.from_places, ids, done=lambda gs: self._game_cards(
            self.recent, gs, "Could not load your recent games."))

    def load_favourites(self):
        a = self.home_account()
        if not a:
            self.favs.set_widgets([], "Add an account to see its favourite games.")
            return
        self.favs.title.setText(f"{a.name}'s favourites")
        self._task(games.favourites, a.user_id, a.cookie, done=lambda gs: self._game_cards(
            self.favs, gs, "No favourite games yet - favourite games on Roblox and they show up here."))

    def load_friends(self):
        a = self.home_account()
        if not a:
            self.friends.set_widgets([], "Add an account to see its friends.")
            return

        def done(res):
            fr = (res or ([], ""))[0]
            on = [f for f in fr if f.presence and f.presence.type in (1, 2)]
            on.sort(key=lambda f: (f.presence.type != 2, (f.display_name or f.name).lower()))
            chips = []
            for f in on[:60]:
                c = FriendChip(f)
                c.clicked.connect(self.friend_menu)
                chips.append(c)
            self.friends.title.setText(f"{a.name}'s friends online")
            in_game = sum(1 for f in on if f.presence.type == 2)
            if hasattr(self.mw, "friends_btn"):
                self.mw.friends_btn.setText(f"Friends · {len(on)} online" if res else "Friends")
            self.friends.note.setText(f"{len(on)} online · {in_game} in a game" if on else "")
            self.friends.set_widgets(chips, "No friends online right now." if res else "Could not load friends.")
            ids = [f.user_id for f in on[:60]]
            bg(games.fetch_avatars, ids, done=lambda _: [c.update() for c in self.friends.cards()])
        self._task(api.friends, a.cookie, a.user_id, done=done)

    def load_discover(self):
        def done(rows):
            for s in self.discover:
                s.deleteLater()
            self.discover = []
            for title, gs in rows or []:
                shelf = Shelf(title, GameCard.H)
                self.v.insertWidget(self.v.count() - 1, shelf)
                self.discover.append(shelf)
                self._game_cards(shelf, gs, "")
        self._task(games.discover, done=done)

    def do_search(self):
        q = self.search.text().strip()
        if not q:
            return
        a = self.home_account()
        self.results.title.setText(f"Results for “{q}”")
        self.results.show()
        self.results.set_widgets([], "Searching...")
        self._task(games.search, q, a.cookie if a else None,
                   done=lambda gs: self._game_cards(self.results, gs, "Nothing found."))

    # ------------------------------------------------------------ actions
    def open_game(self, g: Game):
        GameDialog(self.mw, g).exec()

    def game_menu(self, g: Game, pos):
        play_menu(self.mw, self, LaunchSpec(kind="Game", place_id=g.place_id), g.name).exec(pos)

    def friend_menu(self, f, pos):
        name = f.display_name or f.name
        spec = LaunchSpec(kind="Follow", follow_user_id=f.user_id, follow_name=f.name)
        in_game = bool(f.presence and f.presence.type == 2)
        m = play_menu(self.mw, self, spec, f"{name}'s game") if in_game else QMenu(self)
        if not in_game:
            m.addAction(f"{name} is online, not in a game").setEnabled(False)
        m.addSeparator()
        m.addAction("Copy username", lambda: QGuiApplication.clipboard().setText(f.name))
        m.addAction("Open profile on roblox.com", lambda: _open_url(f"https://www.roblox.com/users/{f.user_id}/profile"))
        m.exec(pos)
