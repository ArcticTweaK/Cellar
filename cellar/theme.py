"""Colour themes (Settings > Appearance).

A theme is a handful of colour tokens. From them Cellar builds a QPalette (for the Fusion style, so check
boxes, scroll bars and dialogs follow it too) and one style sheet for the cards, buttons, tabs and tables.
"System" keeps your desktop's own style and colours and only styles Cellar's own labels (header, pills).
"""

from dataclasses import dataclass
from string import Template
from typing import Dict, List, Optional

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QAbstractSpinBox, QApplication

from . import paths


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    blurb: str
    dark: bool
    bg: str          # window background
    surface: str     # cards, tables, menus
    raised: str      # buttons
    border: str
    text: str
    muted: str       # captions, hints, placeholders
    accent: str
    on_accent: str   # text on an accent-coloured button
    good: str
    warn: str
    bad: str


THEMES: List[Theme] = [
    Theme("blossom", "Blossom", "Dark, with a pink accent", True,
          "#1b1a1f", "#222127", "#2b2a31", "#35333c", "#eceaf0", "#9b98a5", "#f0679a", "#1b1a1f",
          "#5fca8e", "#e8b45a", "#f2606b"),
    Theme("midnight", "Midnight", "Deep blue, periwinkle accent", True,
          "#13151c", "#1a1d26", "#222633", "#2c3142", "#e4e7f0", "#8a90a2", "#8b9cff", "#11131a",
          "#5fd08f", "#e8b55a", "#f2646e"),
    Theme("mint", "Mint", "Dark green, fresh mint accent", True,
          "#141a18", "#1a221f", "#222c28", "#2c3833", "#e3ece8", "#8ca39a", "#5fd6a8", "#0f1513",
          "#7bd88f", "#e6c15a", "#f0696f"),
    Theme("ember", "Ember", "Warm brown, orange accent", True,
          "#1c1816", "#241f1c", "#2e2824", "#3a322d", "#f0e9e4", "#a89a91", "#f59a4f", "#1c1816",
          "#7fcb85", "#f2c55c", "#f06a5f"),
    Theme("graphite", "Graphite", "Plain greys, no colour", True,
          "#18181a", "#1f1f22", "#29292d", "#34343a", "#e8e8ea", "#95959c", "#e8e8ea", "#18181a",
          "#6fcf8e", "#e3b65b", "#ef6461"),
    Theme("daylight", "Daylight", "Light, with a pink accent", False,
          "#f6f4f7", "#ffffff", "#efecf1", "#dedae3", "#1e1c22", "#6c6875", "#d6457a", "#ffffff",
          "#1e8e50", "#a86b12", "#cf3a45"),
    Theme("system", "System", "Your desktop's own colours", True,
          "", "", "", "", "", "", "", "", "", "", ""),       # filled from the desktop palette at runtime
]
DEFAULT = "blossom"

_current: Optional[Theme] = None
_orig_style: Optional[str] = None
_orig_palette: Optional[QPalette] = None


def get(key: str) -> Theme:
    t = next((t for t in THEMES if t.key == key), None) or next(t for t in THEMES if t.key == DEFAULT)
    return _from_desktop() if t.key == "system" else t


def current() -> Theme:
    return _current or get(DEFAULT)


def c(token: str) -> str:
    """A colour of the active theme as '#rrggbb' (token: good, warn, bad, accent, muted, text, ...)."""
    return getattr(current(), token)


def qc(token: str) -> QColor:
    return QColor(c(token))


def span(token: str, text: str) -> str:
    """Rich text in one of the theme's colours."""
    return f"<span style='color:{c(token)}'>{text}</span>"


# ---------------------------------------------------------------- colour tags (Account.color)
# key -> (label, on dark themes, on light themes). The same eight on every theme, so a tag means the same thing
# whichever theme you pick; the light-theme shades are deeper so they still stand out on white.
TAGS: Dict[str, tuple] = {
    "red": ("Red", "#f2626b", "#d93644"),
    "orange": ("Orange", "#f59a4a", "#d9741f"),
    "yellow": ("Yellow", "#f2cf4a", "#c79a00"),
    "green": ("Green", "#5fd38a", "#22a356"),
    "teal": ("Teal", "#4fd1c5", "#16998e"),
    "blue": ("Blue", "#5b9cf5", "#2f6fd6"),
    "purple": ("Purple", "#a98bf5", "#7a52db"),
    "pink": ("Pink", "#f07ac0", "#d1449b"),
}
_tag_icons: Dict[tuple, QIcon] = {}


def tag_qc(key: str) -> Optional[QColor]:
    """An account's colour tag in the active theme, None for no tag."""
    t = TAGS.get(key)
    if not t:
        return None
    return QColor(t[1] if qc("surface").lightness() < 128 else t[2])


def tag_icon(key: str) -> QIcon:
    """A round swatch of a colour tag (menus, combo boxes); an empty ring for 'no tag'."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPen, QPixmap
    col = tag_qc(key)
    ck = (key, col.name() if col else c("muted"))
    ic = _tag_icons.get(ck)
    if ic is None:
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        if col:
            p.setPen(Qt.NoPen)
            p.setBrush(col)
        else:
            p.setPen(QPen(qc("muted"), 2.5))
            p.setBrush(Qt.NoBrush)
        p.drawEllipse(5, 5, 22, 22)
        p.end()
        ic = _tag_icons[ck] = QIcon(pm)
    return ic


# ---------------------------------------------------------------- colour maths
def _mix(a: str, b: str, t: float) -> str:
    """a blended toward b by t (0..1)."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def _rgba(color: str, alpha: float) -> str:
    q = QColor(color)
    return f"rgba({q.red()}, {q.green()}, {q.blue()}, {alpha:.2f})"


def _from_desktop() -> Theme:
    """The System theme: tokens taken from the desktop palette Cellar started with."""
    pal = _orig_palette or QApplication.instance().palette()
    dark = pal.color(QPalette.Window).lightness() < 128
    good, warn, bad = ("#3fb950", "#d29922", "#f85149") if dark else ("#1a7f37", "#9a6700", "#cf222e")
    return Theme("system", "System", "Your desktop's own colours", dark,
                 pal.color(QPalette.Window).name(), pal.color(QPalette.Base).name(),
                 pal.color(QPalette.Button).name(), pal.color(QPalette.Mid).name(),
                 pal.color(QPalette.WindowText).name(), pal.color(QPalette.PlaceholderText).name(),
                 pal.color(QPalette.Highlight).name(), pal.color(QPalette.HighlightedText).name(), good, warn, bad)


# ---------------------------------------------------------------- fonts
_MONO = ("JetBrains Mono", "Fira Code", "FiraCode Nerd Font", "Cascadia Code", "IBM Plex Mono", "Source Code Pro",
         "Hack", "Noto Sans Mono", "DejaVu Sans Mono")


def mono_font(point_size: float = 0, spacing: float = 0) -> QFont:
    """A good-looking monospace font (for the log, macros and the small capital captions)."""
    have = set(QFontDatabase.families())
    fam = next((f for f in _MONO if f in have), None)
    f = QFont(fam) if fam else QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setStyleHint(QFont.Monospace)
    if point_size:
        f.setPointSizeF(point_size)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


# ---------------------------------------------------------------- icons (arrows, tick)
def _icons(t: Theme) -> Dict[str, str]:
    """Small SVGs in the theme's colours, for combo / spin box arrows and check boxes."""
    d = paths.CACHE_DIR / "theme" / t.key
    d.mkdir(parents=True, exist_ok=True)
    stroke = "fill='none' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'"
    svgs = {
        "down": f"<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'>"
                f"<path d='M3 4.5l3 3 3-3' stroke='{t.muted}' {stroke}/></svg>",
        "up": f"<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'>"
              f"<path d='M3 7.5l3-3 3 3' stroke='{t.muted}' {stroke}/></svg>",
        "check": f"<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'>"
                 f"<path d='M3.4 7.3l2.4 2.4 4.8-5' stroke='{t.on_accent}' fill='none' stroke-width='2' "
                 f"stroke-linecap='round' stroke-linejoin='round'/></svg>",
    }
    out = {}
    for name, svg in svgs.items():
        p = d / f"{name}.svg"
        try:
            if not p.exists() or p.read_text() != svg:
                p.write_text(svg)
        except OSError:
            pass
        out[name] = p.as_posix()
    return out


# ---------------------------------------------------------------- app icons (Lucide, ISC - cellar/data/icons)
_ICON_SRC = __import__("pathlib").Path(__file__).resolve().parent / "data" / "icons"
_icon_cache: Dict[tuple, QIcon] = {}


def icon(name: str, token: str = "text") -> QIcon:
    """A bundled line icon in a theme colour (same look on every desktop, follows theme changes)."""
    t = current()
    key = (name, token, t.key, t.accent)
    ic = _icon_cache.get(key)
    if ic is None:
        try:
            svg = (_ICON_SRC / f"{name}.svg").read_text().replace("currentColor", c(token))
            d = paths.CACHE_DIR / "theme" / t.key / "icons"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{name}-{token}.svg"
            if not f.exists() or f.read_text() != svg:
                f.write_text(svg)
            ic = QIcon(str(f))
        except OSError:
            ic = QIcon()
        _icon_cache[key] = ic
    return ic


# ---------------------------------------------------------------- palette + style sheet
def _palette(t: Theme) -> QPalette:
    p = QPalette()
    disabled_text = _mix(t.muted, t.bg, 0.35)
    for role, col in ((QPalette.Window, t.bg), (QPalette.WindowText, t.text), (QPalette.Base, t.bg),
                      (QPalette.AlternateBase, t.surface), (QPalette.Text, t.text), (QPalette.Button, t.raised),
                      (QPalette.ButtonText, t.text), (QPalette.BrightText, t.bad), (QPalette.Highlight, t.accent),
                      (QPalette.HighlightedText, t.on_accent), (QPalette.ToolTipBase, t.raised),
                      (QPalette.ToolTipText, t.text), (QPalette.PlaceholderText, t.muted), (QPalette.Link, t.accent),
                      (QPalette.LinkVisited, t.accent), (QPalette.Light, _mix(t.raised, t.text, 0.12)),
                      (QPalette.Midlight, t.raised), (QPalette.Mid, t.border), (QPalette.Dark, _mix(t.bg, "#000000", 0.3)),
                      (QPalette.Shadow, "#000000")):
        p.setColor(role, QColor(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(disabled_text))
    p.setColor(QPalette.Disabled, QPalette.Highlight, QColor(t.border))
    return p


# Styles Cellar's own named widgets; used by every theme, System included.
_BASE = Template("""
QWidget#topbar { background: $side; border-bottom: 1px solid $border; }
QPushButton#topnav { background: transparent; border: none; border-bottom: 3px solid transparent; border-radius: 0;
                     color: $muted; font-size: 12pt; font-weight: 700; padding: 10px 14px 9px 14px; }
QPushButton#topnav:hover { color: $text; }
QPushButton#topnav:checked { color: $text; border-bottom: 3px solid $accent; }
QPushButton#corner { background: transparent; border: none; border-radius: 8px; padding: 6px; }
QPushButton#corner:hover { background: $nav_hover; }
QPushButton#corner:checked { background: $nav_on; }
QWidget#bottombar { background: $side; border-top: 1px solid $border; }
QPushButton#barbtn { background: transparent; border: none; color: $muted; padding: 5px 8px; font-weight: 600; }
QPushButton#barbtn:hover { color: $text; background: $nav_hover; border-radius: 6px; }
QLabel#mini_value { color: $text; font-weight: 600; }
QLabel#page_title { font-size: 19pt; font-weight: 700; color: $text; }
QLabel#page_sub { color: $muted; }
QPushButton#statusline { text-align: left; border: none; background: transparent; color: $muted; padding: 3px 2px; }
QPushButton#statusline:hover { color: $text; }
QLabel#brand { font-size: 15pt; font-weight: 700; color: $text; }
QPushButton#seg { padding: 4px 11px; }
QPushButton#seg:checked { background: $nav_on; color: $text; border-color: $accent; }
QPushButton#modetab { background: transparent; border: 1px solid transparent; border-radius: 8px; color: $muted;
                      font-weight: 600; padding: 5px 14px; }
QPushButton#modetab:hover { color: $text; background: $nav_hover; }
QPushButton#modetab:checked { color: $text; background: $nav_on; border-color: $accent; }
QWidget#launchbar { background: $surface; border: 1px solid $border; border-radius: 14px; }
QPushButton#launchbtn { font-size: 11pt; font-weight: 700; padding: 6px 18px; }
QListView#gametiles { background: transparent; border: none; }
QListView#gametiles::item, QListView#gametiles::item:selected, QListView#gametiles::item:hover { background: transparent; }
QListView#cards { background: transparent; border: none; }
QListView#cards::item, QListView#cards::item:selected, QListView#cards::item:hover { background: transparent; }
QDialog#palette { background: $raised; border: 1px solid $border; border-radius: 12px; }
QFrame#toast { background: $raised; border: 1px solid $border; border-radius: 12px; }
QFrame#toast QLabel { color: $text; background: transparent; }
QLabel#toast_dot { color: $accent; }
QLabel#toast_dot[kind="good"] { color: $good; }
QLabel#toast_dot[kind="warn"] { color: $warn; }
QLabel#toast_dot[kind="bad"] { color: $bad; }
QPushButton#toast_close { border: none; background: transparent; color: $muted; padding: 0; }
QPushButton#toast_close:hover { color: $text; }
QPushButton#toast_action { padding: 3px 10px; }
QLabel#brand_sub, QLabel#stat_sub, QLabel#pill_sub { color: $muted; }
QLabel#eyebrow { color: $muted; font-weight: 600; }
QLabel#stat_value { font-size: 15pt; font-weight: 600; color: $text; }
QLabel#pill { border-radius: 11px; padding: 3px 11px; font-weight: 600; }
QLabel#pill[state="good"] { color: $good; background: $good_soft; border: 1px solid $good_line; }
QLabel#pill[state="warn"] { color: $warn; background: $warn_soft; border: 1px solid $warn_line; }
QLabel#pill[state="bad"]  { color: $bad;  background: $bad_soft;  border: 1px solid $bad_line; }
QLabel#pill[state="off"]  { color: $muted; background: transparent; border: 1px solid $border; }
QLabel#selection { padding: 2px 0; }
""")

_FULL = Template("""
QToolTip { background: $raised; color: $text; border: 1px solid $border; border-radius: 6px; padding: 5px 8px; }

QTabWidget::pane { border: 1px solid $border; border-radius: 12px; top: -1px; background: $bg; }
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { background: transparent; color: $muted; padding: 8px 12px 7px 12px; margin-right: 2px;
               border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }

QGroupBox { background: $surface; border: 1px solid $border; border-radius: 12px; margin-top: 1.45em;
            padding: 8px 10px 8px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 4px;
                   color: $muted; }

QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QSpinBox, QComboBox {
    background: $field; color: $text; border: 1px solid $border; border-radius: 8px; padding: 4px 8px;
    selection-background-color: $accent; selection-color: $on_accent; }
QPlainTextEdit, QTextEdit, QTextBrowser { padding: 4px; }
QLineEdit:hover, QSpinBox:hover, QComboBox:hover, QPlainTextEdit:hover { border-color: $border_hi; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
    color: $disabled; background: $disabled_bg; border-color: $border; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url($i_down); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: $surface; color: $text; border: 1px solid $border; border-radius: 8px;
    padding: 4px; outline: 0; selection-background-color: $sel; selection-color: $text; }
QSpinBox { padding-right: 22px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 20px; border: none;
                                             background: transparent; }
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: $hover; border-radius: 6px; }
QSpinBox::up-arrow { image: url($i_up); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url($i_down); width: 10px; height: 10px; }

QPushButton, QToolButton { background: $raised; color: $text; border: 1px solid $border; border-radius: 8px;
                           padding: 5px 13px; }
QPushButton:hover, QToolButton:hover { background: $hover; border-color: $border_hi; }
QPushButton:pressed, QToolButton:pressed { background: $border; }
QPushButton:disabled, QToolButton:disabled { color: $disabled; background: $surface; border-color: $border; }
QPushButton:checked { background: $accent_soft; border-color: $accent; }
QPushButton[primary="true"] { background: $accent; color: $on_accent; border: 1px solid $accent; }
QPushButton[primary="true"]:hover { background: $accent_hi; border-color: $accent_hi; }
QPushButton#shelf_arrow { border-radius: 13px; padding: 0; font-size: 15pt; font-weight: 600; min-height: 0; }
QPushButton#shelf_arrow:hover { border-color: $accent; color: $accent; }
QPushButton#shelf_arrow:disabled { color: $border_hi; }
QPushButton[primary="true"]:pressed { background: $accent_lo; }
QPushButton[primary="true"]:disabled { background: $accent_soft; color: $disabled; border-color: transparent; }
QToolButton { padding-right: 24px; }
QToolButton::menu-indicator { image: url($i_down); subcontrol-origin: padding; subcontrol-position: center right;
                              right: 8px; width: 12px; height: 12px; }

QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QTreeView::indicator, QTableView::indicator, QListView::indicator {
    width: 15px; height: 15px; border: 1px solid $border_hi; border-radius: 5px; background: $field; }
QRadioButton::indicator { width: 15px; height: 15px; border: 1px solid $border_hi; border-radius: 8px;
                          background: $field; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover, QTreeView::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked,
QListView::indicator:checked { background: $accent; border-color: $accent; image: url($i_check); }
QRadioButton::indicator:checked { border-color: $accent; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
    fx:0.5, fy:0.5, stop:0 $accent, stop:0.42 $accent, stop:0.52 $field, stop:1 $field); }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { background: $disabled_bg; border-color: $border; }
QCheckBox:disabled, QRadioButton:disabled { color: $disabled; }

QTableView, QTreeView, QListView { background: $surface; alternate-background-color: $alt; color: $text;
    border: 1px solid $border; border-radius: 12px; gridline-color: $border; outline: 0;
    selection-background-color: $sel; selection-color: $text; }
QTableView::item, QTreeView::item, QListView::item { border: none; padding: 0 4px; }
QListView::item { padding: 5px 8px; border-radius: 6px; }
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover { background: $hover_row; }
/* the view's selection colour already fills the row; a second fill here would double it */
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected { background: transparent; color: $text; }
QHeaderView { background: transparent; border: none; }
QHeaderView::section { background: $surface; color: $muted; border: none; border-bottom: 1px solid $border;
                       padding: 7px 8px; font-weight: 600; }
QHeaderView::section:first { border-top-left-radius: 12px; }
QHeaderView::section:last { border-top-right-radius: 12px; }
QTableCornerButton::section { background: $surface; border: none; }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 11px; margin: 3px 2px; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px 3px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 3px; min-height: 30px; margin: 0 1px; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 3px; min-width: 30px; margin: 1px 0; }
QScrollBar::handle:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 8px; }
QSplitter::handle:vertical { height: 6px; }

QMenu { background: $surface; color: $text; border: 1px solid $border; border-radius: 10px; padding: 5px; }
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 6px; }
QMenu::item:selected { background: $sel; color: $text; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { height: 1px; background: $border; margin: 5px 8px; }
QMenu::icon { padding-left: 8px; }

QPlainTextEdit#log { background: $surface; color: $log_text; border: none; border-top: 1px solid $border;
                     border-radius: 0; padding: 6px 10px; }
QTextBrowser#help { background: $bg; border: none; }
QDialog { background: $bg; }
""")


def qss(t: Theme, full: bool) -> str:
    tok = {k: getattr(t, k) for k in ("bg", "surface", "raised", "border", "text", "muted", "accent", "on_accent",
                                      "good", "warn", "bad")}
    for k in ("good", "warn", "bad"):
        tok[k + "_soft"] = _rgba(getattr(t, k), 0.12)
        tok[k + "_line"] = _rgba(getattr(t, k), 0.35)
    tok.update(nav_hover=_rgba(t.text, 0.06), nav_on=_rgba(t.accent, 0.16 if t.dark else 0.12),
               side=_mix(t.bg, t.surface, 0.55))
    if full:
        to_text = 0.08 if t.dark else 0.05
        tok.update(
            field=t.bg,
            hover=_mix(t.raised, t.text, to_text),
            border_hi=_mix(t.border, t.text, 0.18),
            alt=_mix(t.surface, t.text, 0.022 if t.dark else 0.015),
            sel=_rgba(t.accent, 0.22 if t.dark else 0.16),
            hover_row=_rgba(t.text, 0.04),
            accent_hi=_mix(t.accent, "#ffffff" if t.dark else "#000000", 0.14),
            accent_lo=_mix(t.accent, "#000000", 0.12),
            accent_soft=_rgba(t.accent, 0.18),
            disabled=_mix(t.muted, t.bg, 0.35),
            disabled_bg=_mix(t.bg, t.surface, 0.5),
            scroll=_mix(t.border, t.text, 0.12),
            log_text=_mix(t.text, t.muted, 0.25),
        )
        tok.update({"i_" + k: v for k, v in _icons(t).items()})
    out = _BASE.substitute(tok)
    if full:
        out += _FULL.substitute(tok)
    return out


def pad_spin(sb: QAbstractSpinBox) -> None:
    """Style sheet padding does not reach the text field inside a spin box, so give it a margin here.
    Called by common.spin() for new spin boxes and by apply() for existing ones. (Not an app-wide event
    filter: a Python filter that sees every widget's Polish event crashed Qt WebEngine's own widgets,
    i.e. the browser login, with a segfault on NVIDIA + Wayland.)"""
    le = sb.lineEdit()
    if le is not None:
        le.setTextMargins(4 if _current is not None and _current.key != "system" else 0, 0, 0, 0)


_accent_override = ""


def set_accent(hex_colour: str) -> None:
    """Settings > Appearance > Accent: your own accent colour on any of Cellar's themes ('' = the theme's own).
    Takes effect with the next apply()."""
    global _accent_override
    _accent_override = hex_colour if QColor(hex_colour or "").isValid() else ""


def _on(colour: str) -> str:
    """Text colour that reads well on a coloured button."""
    c = QColor(colour)
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return "#151418" if lum > 0.5 else "#ffffff"


def apply(key: str) -> Theme:
    """Switches the whole app to a theme (any time, also while running)."""
    global _current, _orig_style, _orig_palette
    app = QApplication.instance()
    if _orig_style is None:
        _orig_style = app.style().name()
        _orig_palette = QPalette(app.palette())
    t = get(key)
    if _accent_override and t.key != "system":
        import dataclasses
        t = dataclasses.replace(t, accent=_accent_override, on_accent=_on(_accent_override))
    if t.key == "system":
        app.setStyleSheet("")
        QApplication.setStyle(_orig_style)
        app.setPalette(_orig_palette)
        t = _from_desktop()
    else:
        app.setStyleSheet("")
        QApplication.setStyle("Fusion")
        app.setPalette(_palette(t))
    _current = t
    app.setStyleSheet(qss(t, t.key != "system"))
    for w in app.topLevelWidgets():
        for sb in w.findChildren(QAbstractSpinBox):
            pad_spin(sb)
    return t


def preview_theme(key: str) -> Theme:
    """Colours to draw a theme's preview card with (System = the desktop's colours)."""
    t = next((t for t in THEMES if t.key == key), THEMES[0])
    return _from_desktop() if t.key == "system" else t


def repolish(w) -> None:
    """Re-applies the style sheet to a widget after one of its dynamic properties (pill state...) changed."""
    w.style().unpolish(w)
    w.style().polish(w)

