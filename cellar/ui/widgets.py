"""Small widgets of the main window: the header's live numbers, the account table and cards, toasts, graphs."""

from typing import Optional

from PySide6.QtCore import QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QListView,
                               QPushButton, QStyle, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget)

from .. import store, theme


def _size(n: float) -> str:
    return f"{n / 2**20:.0f} MB" if n < 2**30 else f"{n / 2**30:.1f} GB"


def eyebrow(text: str) -> QLabel:
    """A small spaced-out capital caption in the monospace font (RUNNING, CPU, ...)."""
    l = QLabel(text.upper())
    l.setObjectName("eyebrow")
    l.setFont(theme.mono_font(7.5, 1.4))
    return l

class StatBlock(QWidget):
    """The header's live numbers: a small caption, a big value and a line under it (RUNNING 3 / 5, in windows)."""

    def __init__(self, caption: str, tip: str = ""):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(eyebrow(caption))
        self.val = QLabel("-")
        self.val.setObjectName("stat_value")
        self.val.setMinimumWidth(90)
        v.addWidget(self.val)
        self.sub = QLabel("")
        self.sub.setObjectName("stat_sub")
        v.addWidget(self.sub)
        self.setToolTip(tip)

    def set(self, value: str, sub: str = "") -> None:
        self.val.setText(value)
        self.sub.setText(sub)


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


class _DragReorder:
    """Drag accounts onto another account to move them before / after it (both list views). The main window sets
    `reorder(target, after)` (moves the selected accounts) and `can_reorder()` (only in "Your order").
    Drags from outside (cookie files, text) are ignored here, so they reach the window's import."""

    VERTICAL = True             # table rows: before = upper half; cards: before = left half

    def _setup_drag(self):
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)       # our own line (the model takes no drops, Qt's would not show)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.reorder = None
        self.can_reorder = lambda: True
        self._drop: Optional[tuple] = None      # (target account, after)

    def _target(self, pos):
        from .accounts_model import ACCOUNT_ROLE
        idx = self.indexAt(pos)
        a = idx.data(ACCOUNT_ROLE) if idx.isValid() else None
        if a is None:
            return None
        r = self.visualRect(idx.siblingAtColumn(0)) if self.VERTICAL else self.visualRect(idx)
        return a, (pos.y() > r.center().y()) if self.VERTICAL else (pos.x() > r.center().x())

    def _line(self) -> Optional[QRect]:
        from .accounts_model import ACCOUNT_ROLE
        if not self._drop:
            return None
        m = self.model()
        for row in range(m.rowCount()):
            idx = m.index(row, 0)
            if idx.data(ACCOUNT_ROLE) is self._drop[0]:
                r = self.visualRect(idx)
                if self.VERTICAL:
                    y = r.bottom() if self._drop[1] else r.top()
                    return QRect(0, y - 1, self.viewport().width(), 3)
                x = r.right() + 2 if self._drop[1] else r.left() - 2
                return QRect(x - 1, r.top() + 4, 3, r.height() - 8)
        return None

    def dragEnterEvent(self, e):
        if e.source() is self:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.source() is not self:
            e.ignore()
            return
        super().dragMoveEvent(e)                # auto-scroll near the edges
        self._drop = self._target(e.position().toPoint()) if self.can_reorder() else None
        e.setDropAction(Qt.MoveAction)
        e.accept()
        self.viewport().update()

    def dragLeaveEvent(self, e):
        self._drop = None
        self.viewport().update()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        if e.source() is not self:
            e.ignore()
            return
        drop, self._drop = self._target(e.position().toPoint()), None
        e.setDropAction(Qt.CopyAction)          # not Move: Qt would then try to remove the dragged rows itself
        e.accept()
        self.viewport().update()
        if drop and self.reorder:
            self.reorder(*drop)

    def _paint_drop(self):
        r = self._line()
        if r is not None:
            p = QPainter(self.viewport())
            p.fillRect(r, theme.qc("accent"))
            p.end()


class AccountTable(_DragReorder, QTableView):
    def __init__(self):
        super().__init__()
        self.setItemDelegateForColumn(0, _TagBarDelegate(self))
        self._setup_drag()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        _paint_empty(self)
        self._paint_drop()


class _TagBarDelegate(QStyledItemDelegate):
    """Account column: the colour tag as a bar on the row's left edge, like on the cards. (A BackgroundRole
    brush does nothing here - the style sheet's item rules win.)"""

    def paint(self, p, opt, index):
        super().paint(p, opt, index)
        from .accounts_model import ACCOUNT_ROLE
        a = index.data(ACCOUNT_ROLE)
        tag = theme.tag_qc(a.color) if a is not None else None
        if tag:
            p.fillRect(QRect(opt.rect.x(), opt.rect.y() + 3, 4, opt.rect.height() - 6), tag)


class AccountCards(_DragReorder, QListView):
    """The account list as cards (Cards button above the list): same model and the same selection as the table."""

    W, H = 236, 88
    VERTICAL = False

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
        self._setup_drag()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        _paint_empty(self)
        self._paint_drop()


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
        tag = theme.tag_qc(a.color)
        if tag:                                 # colour tag: a bar down the card's left edge
            edge = QPainterPath()
            edge.addRoundedRect(QRectF(r), 10, 10)
            p.save()
            p.setClipPath(edge)
            p.fillRect(QRect(r.x(), r.y(), 5, r.height()), tag)
            p.restore()
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
