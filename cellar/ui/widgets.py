"""Small widgets of the main window: page titles, the sidebar's numbers and "Playing as", the account table."""

from typing import List, Optional

from PySide6.QtCore import QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QListView,
                               QPushButton, QStyle, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget)

from .. import paths, store, theme
from ..models import Account
def _size(n: float) -> str:
    return f"{n / 2**20:.0f} MB" if n < 2**30 else f"{n / 2**30:.1f} GB"

def eyebrow(text: str) -> QLabel:
    """A small spaced-out capital caption in the monospace font (RUNNING, CPU, ...)."""
    l = QLabel(text.upper())
    l.setObjectName("eyebrow")
    l.setFont(theme.mono_font(7.5, 1.4))
    return l

def page_frame(title: str, subtitle: str, body: QWidget) -> QWidget:
    """A page: a big title, an optional one-line explanation, then the page itself."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("page_title")
    v.addWidget(t)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("page_sub")
        sub.setWordWrap(True)
        v.addWidget(sub)
    v.addSpacing(8)
    v.addWidget(body, 1)
    return w

class MiniStat(QWidget):
    """One line of the sidebar's live numbers: caption left, value right (details in the tooltip)."""

    def __init__(self, caption: str, tip: str = ""):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(eyebrow(caption))
        h.addStretch(1)
        self.val = QLabel("-")
        self.val.setObjectName("mini_value")
        h.addWidget(self.val)
        self.tip = tip
        self.setToolTip(tip)

    def set(self, value: str, sub: str = "") -> None:
        self.val.setText(value)
        self.setToolTip(self.tip + (f"\n\nNow: {value}" + (f" ({sub})" if sub else "")))

class PlayingAs(QWidget):
    """Sidebar: the accounts selected right now (what Play / Join use). Click to open Accounts."""

    clicked = Signal()

    def __init__(self, compact: bool = False):
        super().__init__()
        self.accs: List[Account] = []
        self.compact = compact              # one line for the bottom bar: avatars + text, no caption
        self.setFixedHeight(28 if compact else 54)
        if compact:
            self.setMinimumWidth(170)
        self.setCursor(Qt.PointingHandCursor)

    def set_accounts(self, accs: List[Account]):
        self.accs = list(accs)
        names = ", ".join(a.name for a in self.accs[:6]) + (" ..." if len(self.accs) > 6 else "")
        self.setToolTip(("Selected: " + names) if self.accs else "No account selected - click to pick some")
        self.update()

    def mouseReleaseEvent(self, ev):
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.compact:
            y, x, size = 3, 2, 22
        else:
            cap = theme.mono_font(7.5, 1.4)
            p.setFont(cap)
            p.setPen(theme.qc("muted"))
            p.drawText(QRect(2, 0, self.width(), 14), Qt.AlignLeft | Qt.AlignVCenter, "PLAYING AS")
            y, x, size = 20, 2, 30
        if not self.accs:
            p.setFont(self.font())
            p.drawText(QRect(2, y, self.width() - 4, size), Qt.AlignLeft | Qt.AlignVCenter,
                       "Playing as: nobody selected" if self.compact else "No account selected")
            return
        for a in self.accs[:5]:
            r = QRect(x, y, size, size)
            path = paths.AVATAR_DIR / f"{a.user_id}.png"
            p.setPen(theme.qc("bg"))
            p.setBrush(theme.qc("raised"))
            p.drawEllipse(r)
            if path.exists():
                from PySide6.QtGui import QPixmap
                clip = QPainterPath()
                clip.addEllipse(r.adjusted(1, 1, -1, -1))
                p.save()
                p.setClipPath(clip)
                p.drawPixmap(r, QPixmap(str(path)))
                p.restore()
            x += size - (6 if self.compact else 8)
        x += 12 if self.compact else 14
        p.setFont(self.font())
        p.setPen(theme.qc("text"))
        more = len(self.accs) - 5
        text = self.accs[0].name if len(self.accs) == 1 else (f"+{more} more" if more > 0 else f"{len(self.accs)} accounts")
        fm = p.fontMetrics()
        p.drawText(QRect(x, y, self.width() - x, size), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(text, Qt.ElideRight, self.width() - x))

def _paint_empty(view) -> None:
    """The account list says what to do when it is empty instead of showing a blank box."""
    if view.model() is None or view.model().rowCount():
        return
    if store.accounts:
        title, text = "No matches", "No account matches your search or group filter."
    else:
        title, text = "No accounts yet", "Press  Add account  below and log in with the browser,\n" \
                                         "paste cookies, or import the account your Sober uses."
    p = QPainter(view.viewport())
    r = view.viewport().rect().adjusted(20, 0, -20, 0)
    f = p.font()
    f.setPointSizeF(f.pointSizeF() + 2)
    f.setBold(True)
    p.setFont(f)
    p.setPen(theme.qc("text"))
    top = r.center().y() - 40
    p.drawText(QRect(r.x(), top, r.width(), 28), Qt.AlignCenter, title)
    p.setFont(view.font())
    p.setPen(theme.qc("muted"))
    p.drawText(QRect(r.x(), top + 32, r.width(), 60), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, text)
    p.end()


class AccountChip(QWidget):
    """Top bar, far right: the Home account's avatar and name (click for its menu) - like a launcher's user."""

    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.a: Optional[Account] = None
        self.setFixedHeight(36)
        self.setMinimumWidth(180)
        self.setCursor(Qt.PointingHandCursor)
        self.hover = False

    def set_account(self, a: Optional[Account]):
        self.a = a
        self.setToolTip(f"Home account: {a.name}" if a else "No account yet")
        self.update()

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, ev):
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qc("raised"))
            p.drawRoundedRect(self.rect(), 8, 8)
        av = QRect(6, 4, 28, 28)
        clip = QPainterPath()
        clip.addEllipse(av)
        p.save()
        p.setClipPath(clip)
        p.fillRect(av, theme.qc("raised"))
        if self.a and (paths.AVATAR_DIR / f"{self.a.user_id}.png").exists():
            from PySide6.QtGui import QPixmap
            p.drawPixmap(av, QPixmap(str(paths.AVATAR_DIR / f"{self.a.user_id}.png")))
        p.restore()
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.qc("text"))
        text = self.a.name if self.a else "Add an account"
        fm = QFontMetrics(f)
        p.drawText(QRect(42, 0, self.width() - 62, self.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(text, Qt.ElideRight, self.width() - 62))
        p.setPen(theme.qc("muted"))
        p.drawText(QRect(self.width() - 18, 0, 14, self.height()), Qt.AlignCenter, "▾")


class AccountTable(QTableView):
    def paintEvent(self, ev):
        super().paintEvent(ev)
        _paint_empty(self)


class AccountCards(QListView):
    """The account list as cards (Accounts page > Cards): same model and the same selection as the table."""

    W, H = 236, 88

    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(5)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMouseTracking(True)
        self.setObjectName("cards")
        self.setItemDelegate(_CardDelegate(self))

    def paintEvent(self, ev):
        super().paintEvent(ev)
        _paint_empty(self)


class _CardDelegate(QStyledItemDelegate):
    def sizeHint(self, opt, index):
        return QSize(AccountCards.W, AccountCards.H)

    def paint(self, p, opt, index):
        from .accounts_model import ACCOUNT_ROLE
        a = index.data(ACCOUNT_ROLE)
        if a is None:
            return
        model = index.model().sourceModel() if hasattr(index.model(), "sourceModel") else index.model()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = opt.rect.adjusted(1, 1, -1, -1)
        selected = bool(opt.state & QStyle.State_Selected)
        hover = bool(opt.state & QStyle.State_MouseOver)
        bg = QColor(theme.c("accent"))
        bg.setAlphaF(0.16)
        p.setPen(theme.qc("accent") if selected else theme.qc("border"))
        p.setBrush(bg if selected else (theme.qc("raised") if hover else theme.qc("surface")))
        p.drawRoundedRect(r, 10, 10)
        av = QRect(r.x() + 12, r.y() + (r.height() - 48) // 2, 48, 48)
        clip = QPainterPath()
        clip.addEllipse(av)
        p.save()
        p.setClipPath(clip)
        p.fillRect(av, theme.qc("raised"))
        p.drawPixmap(av, model.icon_for(a).pixmap(96, 96))
        p.restore()
        text, token = model.status(a)
        running = a.id in model.running
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qc(token if running or token in ("good", "warn", "bad") else "muted"))
        p.drawEllipse(av.right() - 11, av.bottom() - 11, 13, 13)
        x = av.right() + 12
        w = r.right() - x - 10
        f = QFont(opt.font)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        p.setPen(theme.qc("text"))
        name = ("★ " if a.pinned else "") + a.name
        p.drawText(QRect(x, r.y() + 12, w, fm.height()), Qt.AlignLeft, fm.elidedText(name, Qt.ElideRight, w))
        f.setBold(False)
        f.setPointSizeF(f.pointSizeF() * 0.92)
        p.setFont(f)
        fm = QFontMetrics(f)
        y = r.y() + 14 + fm.height() + 2
        p.setPen(theme.qc(token))
        p.drawText(QRect(x, y, w, fm.height()), Qt.AlignLeft,
                   fm.elidedText(text.replace("▶ ", "") or "-", Qt.ElideRight, w))
        bits = [b for b in (a.group, model.usage_text(a)) if b]
        if bits:
            p.setPen(theme.qc("muted"))
            p.drawText(QRect(x, y + fm.height() + 3, w, fm.height()), Qt.AlignLeft,
                       fm.elidedText("  ·  ".join(bits), Qt.ElideRight, w))
        p.restore()


class Toast(QFrame):
    """A small message in the window's bottom-right corner that fades out by itself (in-app notifications)."""

    LIFE_MS = 5500

    def __init__(self, host: QWidget, text: str, kind: str = "info", action=None):
        super().__init__(host)
        self.setObjectName("toast")
        self.setProperty("kind", kind)
        self.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(10)
        dot = QLabel("●")
        dot.setObjectName("toast_dot")
        dot.setProperty("kind", kind)
        h.addWidget(dot, 0, Qt.AlignTop)
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setMinimumWidth(240)
        msg.setMaximumWidth(360)
        h.addWidget(msg, 1)
        if action is not None:
            label, fn = action
            b = QPushButton(label)
            b.setObjectName("toast_action")
            b.clicked.connect(lambda: (fn(), self.close_now()))
            h.addWidget(b, 0, Qt.AlignVCenter)
        x = QPushButton("✕")
        x.setObjectName("toast_close")
        x.setFixedSize(22, 22)
        x.clicked.connect(self.close_now)
        h.addWidget(x, 0, Qt.AlignTop)
        self.fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.anim = QPropertyAnimation(self.fx, b"opacity", self)
        self.anim.setDuration(220)
        self.adjustSize()
        self.show()
        self._fade(0.0, 1.0)
        QTimer.singleShot(self.LIFE_MS, lambda: self._fade(1.0, 0.0, self.close_now))

    def _fade(self, a: float, b: float, then=None):
        try:
            self.anim.stop()
            self.anim.setStartValue(a)
            self.anim.setEndValue(b)
            if then:
                self.anim.finished.connect(then)
            self.anim.start()
        except RuntimeError:            # already closed
            pass

    def close_now(self):
        try:
            host = self.parentWidget()
            self.hide()
            self.deleteLater()
            if host is not None and hasattr(host, "_layout_toasts"):
                QTimer.singleShot(0, host._layout_toasts)
        except RuntimeError:
            pass

    def enterEvent(self, _):           # stays while the mouse is on it
        self.anim.stop()
        self.fx.setOpacity(1.0)


class UsageGraph(QWidget):
    """One measure over the last hour (Performance page): a thin line, a recessive grid, the latest value in the
    title, and a crosshair + exact value under the mouse. CPU and memory get one graph each (never two scales)."""

    WINDOW = 3600.0

    def __init__(self, title: str, fmt, floor: float = 1.0):
        super().__init__()
        self.title, self.fmt, self.floor = title, fmt, floor
        self.points: list = []          # (unix time, value)
        self.hover_x: Optional[int] = None
        self.setMinimumHeight(150)
        self.setMouseTracking(True)

    def add(self, t: float, v: float):
        self.points.append((t, v))
        cut = t - self.WINDOW
        while self.points and self.points[0][0] < cut:
            self.points.pop(0)
        self.update()

    def leaveEvent(self, _):
        self.hover_x = None
        self.update()

    def mouseMoveEvent(self, ev):
        self.hover_x = int(ev.position().x())
        self.update()

    def _plot(self) -> QRect:
        return self.rect().adjusted(8, 30, -8, -22)

    def paintEvent(self, _):
        import time as _t
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot()
        now = _t.time()
        top = max([v for _, v in self.points] + [self.floor]) * 1.15
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(theme.qc("text"))
        last = self.points[-1][1] if self.points else None
        p.drawText(QRect(8, 4, self.width() - 16, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   self.title + (f"   {self.fmt(last)}" if last is not None else ""))
        small = QFont(self.font())
        small.setPointSizeF(small.pointSizeF() * 0.85)
        p.setFont(small)
        grid = QColor(theme.c("border"))
        for i in range(4):                                  # recessive grid: 0, 1/3, 2/3, top
            y = r.bottom() - r.height() * i / 3
            p.setPen(QPen(grid, 1))
            p.drawLine(r.left(), int(y), r.right(), int(y))
        p.setPen(theme.qc("muted"))
        p.drawText(QRect(r.left(), r.bottom() + 4, 200, 16), Qt.AlignLeft, "60 min ago")
        p.drawText(QRect(r.right() - 200, r.bottom() + 4, 200, 16), Qt.AlignRight, "now")
        p.drawText(QRect(r.right() - 200, r.top() - 16, 200, 14), Qt.AlignRight, self.fmt(top))
        if len(self.points) < 2:
            p.drawText(r, Qt.AlignCenter, "Collecting... (one point every few seconds while accounts run)")
            return

        def xy(t, v):
            return QPointF(r.left() + r.width() * (1 - (now - t) / self.WINDOW), r.bottom() - r.height() * v / top)
        path = QPainterPath()
        path.moveTo(xy(*self.points[0]))
        for t, v in self.points[1:]:
            path.lineTo(xy(t, v))
        pen = QPen(theme.qc("accent"), 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)
        if self.hover_x is not None and r.left() <= self.hover_x <= r.right():
            t_at = now - self.WINDOW * (1 - (self.hover_x - r.left()) / r.width())
            t, v = min(self.points, key=lambda tv: abs(tv[0] - t_at))
            pt = xy(t, v)
            p.setPen(QPen(theme.qc("muted"), 1, Qt.DashLine))
            p.drawLine(int(pt.x()), r.top(), int(pt.x()), r.bottom())
            p.setPen(QPen(theme.qc("surface"), 2))           # a ring so the dot stands off the line
            p.setBrush(theme.qc("accent"))
            p.drawEllipse(pt, 5, 5)
            label = f"{_t.strftime('%H:%M:%S', _t.localtime(t))}  ·  {self.fmt(v)}"
            fm = QFontMetrics(small)
            w = fm.horizontalAdvance(label) + 16
            bx = min(max(int(pt.x()) - w // 2, r.left()), r.right() - w)
            box = QRect(bx, r.top() + 2, w, fm.height() + 8)
            p.setPen(QPen(theme.qc("border"), 1))
            p.setBrush(theme.qc("raised"))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(theme.qc("text"))
            p.drawText(box, Qt.AlignCenter, label)
