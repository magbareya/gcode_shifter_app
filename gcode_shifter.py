"""G-code Shifter - desktop app to position and resize GRBL jobs (CNC or laser).

Run:  python gcode_shifter.py [file.nc]
"""

import math
import os
import sys

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils import MACHINE_TRAVEL_MM, alignment_box, get_gcode_info, get_toolpath, scale_gcode, shift_gcode

APP_NAME = "G-code Shifter"
FILE_FILTER = "G-code files (*.nc *.gcode *.ngc *.tap *.gc *.txt);;All files (*)"
H_NAMES = {"min": "left", "mid": "center", "max": "right"}
V_NAMES = {"min": "bottom", "mid": "middle", "max": "top"}


# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #
def is_dark():
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def make_theme(dark):
    if dark:
        return dict(
            bg="#1e1f22", grid="#2a2c30", grid_major="#34373c", grid_text="#80858d", panel="#232428",
            cut="#60a5fa", travel="#6b7280", original="#f59e0b", origin="#f87171", bed="#8b9099",
            target="#34d399", card="#2b2d31", border="#3a3d42", muted="#9aa0a6", accent="#3b82f6",
            warn_bg="#3a2f12", warn_fg="#fbd38d", info_bg="#15283f", info_fg="#93c5fd", text="#e6e6e6",
        )
    return dict(
        bg="#ffffff", grid="#f0f2f5", grid_major="#e2e5ea", grid_text="#8a9099", panel="#f7f8fa",
        cut="#2563eb", travel="#a3a9b3", original="#f59e0b", origin="#dc2626", bed="#6b7280",
        target="#059669", card="#ffffff", border="#e1e4e8", muted="#6b7280", accent="#2563eb",
        warn_bg="#fff4d6", warn_fg="#7a4f00", info_bg="#e8f1fd", info_fg="#1e4e8c", text="#1f2328",
    )


def make_palette(t, dark):
    """Window palette that always matches the theme colours (text never dark-on-dark)."""
    pal = QPalette()
    window = QColor("#1b1c1f" if dark else "#f0f1f3")
    text = QColor(t["text"])
    for role, color in (
        (QPalette.Window, window),
        (QPalette.WindowText, text),
        (QPalette.Base, QColor(t["card"])),
        (QPalette.AlternateBase, QColor(t["panel"])),
        (QPalette.Text, text),
        (QPalette.Button, QColor(t["card"])),
        (QPalette.ButtonText, text),
        (QPalette.ToolTipBase, QColor(t["card"])),
        (QPalette.ToolTipText, text),
        (QPalette.Highlight, QColor(t["accent"])),
        (QPalette.HighlightedText, QColor("#ffffff")),
        (QPalette.PlaceholderText, QColor(t["muted"])),
    ):
        pal.setColor(role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(t["muted"]))
    return pal


def make_stylesheet(t):
    return f"""
    QWidget#sidePanel {{ background: {t['panel']}; }}
    QFrame#card {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 8px; }}
    QLabel[role="muted"] {{ color: {t['muted']}; }}
    QLabel[role="h1"] {{ font-size: 13pt; font-weight: 600; }}
    QLabel[role="section"] {{ color: {t['muted']}; font-weight: 600; letter-spacing: 0.5px; }}
    QLabel[role="metricValue"] {{ font-size: 13pt; font-weight: 600; }}
    QLabel[role="delta"] {{ color: {t['accent']}; font-size: 8.5pt; }}
    QLabel[role="banner-warning"] {{ background: {t['warn_bg']}; color: {t['warn_fg']};
                                     border-radius: 6px; padding: 6px 10px; }}
    QLabel[role="banner-info"] {{ background: {t['info_bg']}; color: {t['info_fg']};
                                  border-radius: 6px; padding: 6px 10px; }}
    QPushButton {{ padding: 6px 12px; border-radius: 6px; border: 1px solid {t['border']};
                   background: {t['card']}; color: {t['text']}; }}
    QPushButton:hover {{ border-color: {t['accent']}; }}
    QPushButton:pressed {{ background: {t['border']}; }}
    QPushButton:disabled {{ color: {t['muted']}; background: transparent; }}
    QPushButton[primary="true"] {{ background: {t['accent']}; color: white; border: none; font-weight: 600; padding: 8px 14px; }}
    QPushButton[primary="true"]:hover {{ background: {QColor(t['accent']).lighter(115).name()}; }}
    QPushButton[primary="true"]:disabled {{ background: {t['border']}; color: {t['muted']}; }}
    QToolButton[anchor="true"] {{ border: 1px solid {t['border']}; border-radius: 4px; background: {t['card']}; }}
    QToolButton[anchor="true"]:checked {{ background: {t['accent']}; color: white; border-color: {t['accent']}; }}
    QListWidget {{ border: 1px solid {t['border']}; border-radius: 6px; background: {t['card']}; }}
    QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 6px; top: -1px; background: {t['card']}; }}
    """


def primary_button(text):
    b = QPushButton(text)
    b.setProperty("primary", True)
    b.setCursor(Qt.PointingHandCursor)
    return b


def label(text="", role=None, wrap=False):
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


def fmt(v, digits=2):
    if v is None:
        return "—"
    if abs(v) < 0.5 * 10 ** -digits:
        v = 0.0  # avoid "-0.00"
    return f"{v:,.{digits}f}"


EPS = 5e-4  # below G-code output precision (4 decimals) - treat as "no change"


def sfmt(v, digits=3):
    """Signed number without "-0.000"."""
    if abs(v) < 0.5 * 10 ** -digits:
        v = 0.0
    return f"{v:+,.{digits}f}"


def nice_step(raw):
    """Smallest 1/2/5 x 10^n >= raw."""
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * 10 ** exp >= raw:
            return m * 10 ** exp
    return 10 ** (exp + 1)


# --------------------------------------------------------------------------- #
# Preview canvas
# --------------------------------------------------------------------------- #
class PreviewView(QGraphicsView):
    """Zoom/pan toolpath view with Y pointing up, adaptive grid and rulers."""

    cursorMoved = Signal(object)  # QPointF in job coordinates, or None

    def __init__(self, theme):
        super().__init__()
        self.t = theme
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(QRectF(-1e5, -1e5, 2e5, 2e5))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self._content_items = []
        self._overlay_items = []
        self._fit_rect = QRectF(-10, -10, 20, 20)
        self.setTransform(QTransform.fromScale(1, -1))

    # ---- content ---------------------------------------------------------- #
    def _pen(self, color, width=1.0, dash=None, alpha=255):
        c = QColor(color)
        c.setAlpha(alpha)
        p = QPen(c, width)
        p.setCosmetic(True)
        p.setCapStyle(Qt.RoundCap)
        p.setJoinStyle(Qt.RoundJoin)
        if dash:
            p.setDashPattern(dash)
        return p

    def _add(self, item, bucket):
        bucket.append(item)
        return item

    def _clear(self, bucket):
        for it in bucket:
            self.scene().removeItem(it)
        bucket.clear()

    def set_content(self, paths, job_rect, show_bed, unit_scale=1.0):
        """paths: list of (QPainterPath, pen-spec dict). job_rect: QRectF or None."""
        self._clear(self._content_items)
        sc = self.scene()
        t = self.t

        # Origin cross + label
        span = 1e5
        for line in ((-span, 0, span, 0), (0, -span, 0, span)):
            self._add(sc.addLine(*line, self._pen(t["origin"], 1, alpha=150)), self._content_items).setZValue(1)
        txt = self._add(sc.addSimpleText("0,0"), self._content_items)
        txt.setBrush(QColor(t["origin"]))
        f = QFont()
        f.setBold(True)
        txt.setFont(f)
        txt.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        txt.setPos(0, 0)
        txt.setZValue(1)

        if show_bed:
            bed = QRectF(0, 0, MACHINE_TRAVEL_MM["X"] / unit_scale, MACHINE_TRAVEL_MM["Y"] / unit_scale)
            self._add(sc.addRect(bed, self._pen(t["bed"], 1.2, dash=[6, 4])), self._content_items).setZValue(0)
            bl = self._add(sc.addSimpleText(f"TTC450 bed {MACHINE_TRAVEL_MM['X']:.0f}×{MACHINE_TRAVEL_MM['Y']:.0f}"), self._content_items)
            bl.setBrush(QColor(t["bed"]))
            bl.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            bl.setPos(bed.left(), bed.bottom())
            bl.setTransform(QTransform.fromTranslate(2, -18))  # screen px: sit just above the outline
            bl.setZValue(0)

        for path, spec in paths:
            item = self._add(sc.addPath(path, self._pen(**spec["pen"])), self._content_items)
            item.setZValue(spec["z"])

        if job_rect is not None:
            self._add(sc.addRect(job_rect, self._pen(t["cut"], 1, dash=[3, 3], alpha=140)), self._content_items).setZValue(2)

        fit = QRectF(job_rect) if job_rect is not None else QRectF()
        for path, _ in paths:
            fit = fit.united(path.boundingRect())
        fit = fit.united(QRectF(-1, -1, 2, 2))  # always include work zero
        if show_bed:
            fit = fit.united(bed)
        self._fit_rect = fit

    def set_overlay(self, marker=None, target=None):
        """marker: (x, y, tooltip) diamond; target: QRectF ghost of the result."""
        self._clear(self._overlay_items)
        sc = self.scene()
        if target is not None:
            r = self._add(sc.addRect(target, self._pen(self.t["target"], 1.6, dash=[5, 3])), self._overlay_items)
            r.setZValue(5)
        if marker is not None and None not in marker[:2]:
            d = 7
            poly = QPolygonF([QPointF(0, -d), QPointF(d, 0), QPointF(0, d), QPointF(-d, 0)])
            item = self._add(sc.addPolygon(poly, self._pen(self.t["bg"], 1.5), QColor(self.t["target"])), self._overlay_items)
            item.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            item.setPos(marker[0], marker[1])
            item.setToolTip(marker[2])
            item.setZValue(6)

    # ---- view ------------------------------------------------------------- #
    def fit(self):
        r = self._fit_rect
        vw, vh = max(self.viewport().width(), 50), max(self.viewport().height(), 50)
        w, h = max(r.width(), 1e-3), max(r.height(), 1e-3)
        s = 0.9 * min(vw / w, vh / h)
        self.setTransform(QTransform.fromScale(s, -s))
        self.centerOn(r.center())

    def visible_rect(self):
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def ensure_visible_content(self):
        if not self.visible_rect().intersects(self._fit_rect):
            self.fit()

    def wheelEvent(self, event):
        factor = 1.0015 ** event.angleDelta().y()
        s = abs(self.transform().m11()) * factor
        if 1e-3 < s < 1e4:
            self.scale(factor, factor)

    def mouseDoubleClickEvent(self, event):
        self.fit()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self.cursorMoved.emit(self.mapToScene(event.position().toPoint()))

    def leaveEvent(self, event):
        self.cursorMoved.emit(None)
        super().leaveEvent(event)

    def _grid_step(self):
        px = abs(self.transform().m11()) or 1.0
        return nice_step(70 / px)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor(self.t["bg"]))
        step = self._grid_step()
        vis = self.visible_rect()
        minor = self._pen(self.t["grid"], 1)
        major = self._pen(self.t["grid_major"], 1)
        x = math.floor(vis.left() / step) * step
        i = 0
        while x <= vis.right() and i < 400:
            painter.setPen(major if round(x / step) % 5 == 0 else minor)
            painter.drawLine(QPointF(x, vis.top()), QPointF(x, vis.bottom()))
            x += step
            i += 1
        y = math.floor(vis.top() / step) * step
        i = 0
        while y <= vis.bottom() and i < 400:
            painter.setPen(major if round(y / step) % 5 == 0 else minor)
            painter.drawLine(QPointF(vis.left(), y), QPointF(vis.right(), y))
            y += step
            i += 1

    def drawForeground(self, painter, rect):
        # Ruler labels in screen space along the bottom and left edges.
        step = self._grid_step()
        vis = self.visible_rect()
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(self.t["grid_text"]))
        f = painter.font()
        f.setPointSizeF(8)
        painter.setFont(f)
        digits = 0 if step >= 1 else min(4, -math.floor(math.log10(step)))
        vh = self.viewport().height()
        x = math.floor(vis.left() / step) * step
        while x <= vis.right():
            vx = self.mapFromScene(QPointF(x, 0)).x()
            if 30 < vx:
                painter.drawText(vx + 3, vh - 5, f"{x:.{digits}f}")
            x += step
        y = math.floor(vis.top() / step) * step
        while y <= vis.bottom():
            vy = self.mapFromScene(QPointF(0, y)).y()
            if vy < vh - 20:
                painter.drawText(4, vy - 3, f"{y:.{digits}f}")
            y += step
        painter.restore()


# --------------------------------------------------------------------------- #
# Small widgets
# --------------------------------------------------------------------------- #
class MetricCard(QFrame):
    def __init__(self, title, tooltip=""):
        super().__init__()
        self.setObjectName("card")
        self.setToolTip(tooltip)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(1)
        lay.addWidget(label(title, "muted"))
        self.value = label("—", "metricValue")
        self.delta = label("", "delta")
        lay.addWidget(self.value)
        lay.addWidget(self.delta)

    def set(self, value, delta=""):
        self.value.setText(value)
        self.delta.setText(delta)


class AnchorPicker(QWidget):
    """3x3 grid to choose a reference point of the job (like an image-editor anchor)."""

    changed = Signal()
    ARROWS = (("↖", "↑", "↗"), ("←", "●", "→"), ("↙", "↓", "↘"))

    def __init__(self, h="min", v="min"):
        super().__init__()
        self._h, self._v = h, v
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        grid = QGridLayout(self)
        grid.setSpacing(3)
        grid.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for r, vk in enumerate(("max", "mid", "min")):
            for c, hk in enumerate(("min", "mid", "max")):
                b = QToolButton()
                b.setText(self.ARROWS[r][c])
                b.setProperty("anchor", True)
                b.setCheckable(True)
                b.setFixedSize(30, 30)
                name = "Center" if (hk, vk) == ("mid", "mid") else f"{V_NAMES[vk].title()} {H_NAMES[hk]}"
                b.setToolTip(name)
                b.setChecked((hk, vk) == (h, v))
                b.clicked.connect(lambda _=False, hk=hk, vk=vk: self._pick(hk, vk))
                self.group.addButton(b)
                grid.addWidget(b, r, c)

    def _pick(self, h, v):
        self._h, self._v = h, v
        self.changed.emit()

    def value(self):
        return self._h, self._v

    def describe(self):
        if (self._h, self._v) == ("mid", "mid"):
            return "center"
        return f"{V_NAMES[self._v]}-{H_NAMES[self._h]}"


def spin(minimum=-99999.0, maximum=99999.0, step=1.0, decimals=3, value=0.0):
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setAccelerated(True)
    s.setMinimumWidth(110)
    return s


def form_row(*widgets):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for x in widgets:
        if isinstance(x, str):
            lay.addWidget(label(x))
        else:
            lay.addWidget(x)
    lay.addStretch(1)
    return w


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self, theme):
        super().__init__()
        self.t = theme
        self.settings = QSettings("gcode_shifter", "GcodeShifter")

        # document state
        self.path = None
        self.save_path = None
        self.original = ""
        self.output = ""
        self.saved_text = ""
        self.undo_stack = []  # [(label, text_before)]
        self.redo_stack = []  # [(label, text_after)]
        self._info_cache = {}
        self._path_cache = {}

        self.setAcceptDrops(True)
        self.resize(1320, 860)
        self._build_actions()
        self._build_ui()
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self.refresh()

    # ---- building --------------------------------------------------------- #
    def _act(self, text, slot, shortcut=None, checkable=False, checked=False, tip=""):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        if checkable:
            a.setChecked(checked)
            a.toggled.connect(slot)
        else:
            a.triggered.connect(slot)
        a.setStatusTip(tip)
        return a

    def _build_actions(self):
        s = self.settings
        self.a_open = self._act("&Open…", self.open_dialog, QKeySequence.Open)
        self.a_save = self._act("&Save", self.save, QKeySequence.Save)
        self.a_save_as = self._act("Save &As…", self.save_as, QKeySequence.SaveAs)
        self.a_quit = self._act("E&xit", self.close, QKeySequence.Quit)
        self.a_undo = self._act("&Undo", self.undo, QKeySequence.Undo)
        self.a_redo = self._act("&Redo", self.redo, QKeySequence.Redo)
        self.a_reset = self._act("Reset to &original", self.reset)
        self.a_fit = self._act("&Fit to window", lambda: self.view.fit(), "F")
        self.a_travel = self._act("Show &travel moves", self._redraw, "T", True, s.value("show_travel", True, bool))
        self.a_orig = self._act("&Compare with original", self._redraw, "C", True, s.value("show_original", True, bool))
        self.a_bed = self._act("Show machine &bed", self._redraw, "B", True, s.value("show_bed", True, bool))

        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_open, None, self.a_save, self.a_save_as, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_reset):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&View")
        for a in (self.a_fit, None, self.a_travel, self.a_orig, self.a_bed):
            m.addSeparator() if a is None else m.addAction(a)

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ---------------- side panel ----------------
        side = QWidget()
        side.setObjectName("sidePanel")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 14, 14, 14)
        sl.setSpacing(10)

        self.file_title = label("No file loaded", "h1")
        self.file_meta = label("Open a file to start", "muted")
        open_btn = QPushButton("Open…")
        open_btn.clicked.connect(self.open_dialog)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.file_title)
        col.addWidget(self.file_meta)
        head.addLayout(col, 1)
        head.addWidget(open_btn, 0, Qt.AlignTop)
        sl.addLayout(head)

        mgrid = QGridLayout()
        mgrid.setSpacing(8)
        self.metrics = QWidget()
        mgrid.setContentsMargins(0, 0, 0, 0)
        self.m_w = MetricCard("Width (X)")
        self.m_h = MetricCard("Height (Y)")
        self.m_ll = MetricCard("Lower-left corner", "Where the cut/engraved area starts, relative to work zero (X0 Y0).")
        self.m_z = MetricCard("Deepest cut (Z)", "Lowest Z of the cutting moves. Laser files usually have no Z.")
        for i, c in enumerate((self.m_w, self.m_h, self.m_ll, self.m_z)):
            mgrid.addWidget(c, i // 2, i % 2)
        self.metrics.setLayout(mgrid)
        sl.addWidget(self.metrics)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_position_tab(), "Position")
        self.tabs.addTab(self._build_scale_tab(), "Scale")
        self.tabs.addTab(self._build_z_tab(), "Z · depth/focus")
        self.tabs.currentChanged.connect(self.update_overlay)
        sl.addWidget(self.tabs)

        self.history_title = label("HISTORY", "section")
        sl.addWidget(self.history_title)
        self.history = QListWidget()
        self.history.setMinimumHeight(80)
        self.history.setFocusPolicy(Qt.NoFocus)
        sl.addWidget(self.history, 10)
        sl.addStretch(0)  # keeps the header at the top when nothing is loaded

        footer = QWidget()
        footer.setObjectName("sidePanel")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(14, 8, 14, 12)
        fl.setSpacing(6)
        hrow = QHBoxLayout()
        self.b_undo = QPushButton("↶ Undo")
        self.b_redo = QPushButton("↷ Redo")
        self.b_reset = QPushButton("Reset")
        self.b_undo.clicked.connect(self.undo)
        self.b_redo.clicked.connect(self.redo)
        self.b_reset.clicked.connect(self.reset)
        for b in (self.b_undo, self.b_redo, self.b_reset):
            hrow.addWidget(b)
        fl.addLayout(hrow)
        self.b_save = primary_button("Save G-code…   (Ctrl+S)")
        self.b_save.clicked.connect(self.save)
        fl.addWidget(self.b_save)
        fl.addWidget(label("Always run a frame / dry run before cutting or burning.", "muted", wrap=True))
        self.footer = footer

        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_col = QWidget()
        lcl = QVBoxLayout(left_col)
        lcl.setContentsMargins(0, 0, 0, 0)
        lcl.setSpacing(0)
        lcl.addWidget(scroll, 1)
        lcl.addWidget(footer)
        left_col.setMinimumWidth(390)
        left_col.setMaximumWidth(540)
        splitter.addWidget(left_col)

        # ---------------- preview area ----------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 10, 10, 0)
        rl.setSpacing(6)

        self.banner_box = QVBoxLayout()
        self.banner_box.setSpacing(4)
        rl.addLayout(self.banner_box)

        self.view_bar = QWidget()
        bar = QHBoxLayout(self.view_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.legend = label("", "muted")
        self.legend.setTextFormat(Qt.RichText)
        bar.addWidget(self.legend, 1)
        for a in (self.a_travel, self.a_orig, self.a_bed):
            cb = QCheckBox(a.text().replace("&", ""))
            cb.setChecked(a.isChecked())
            cb.toggled.connect(a.setChecked)
            a.toggled.connect(cb.setChecked)
            bar.addWidget(cb)
        fit_btn = QPushButton("Fit (F)")
        fit_btn.clicked.connect(lambda: self.view.fit())
        bar.addWidget(fit_btn)
        rl.addWidget(self.view_bar)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty_state())
        self.view = PreviewView(self.t)
        self.view.cursorMoved.connect(self._on_cursor)
        self.stack.addWidget(self.view)
        rl.addWidget(self.stack, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 900])
        self.setCentralWidget(splitter)

        self.cursor_label = label("", "muted")
        self.statusBar().addPermanentWidget(self.cursor_label)

    def _build_empty_state(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        title = label("Drop a G-code file here", "h1")
        title.setAlignment(Qt.AlignCenter)
        sub = label(
            "or press Ctrl+O.  Works with router files (Fusion, Carbide, Easel…) and laser files (LightBurn, LaserGRBL, Inkscape…).",
            "muted",
            wrap=True,
        )
        sub.setAlignment(Qt.AlignCenter)
        btn = primary_button("Open G-code file…")
        btn.clicked.connect(self.open_dialog)
        steps = label("1 · Open    →    2 · Position / scale    →    3 · Save", "muted")
        steps.setAlignment(Qt.AlignCenter)
        for x in (title, sub):
            lay.addWidget(x)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        row.addStretch(1)
        lay.addSpacing(10)
        lay.addLayout(row)
        lay.addSpacing(18)
        lay.addWidget(steps)
        lay.addStretch(2)
        return w

    def _section(self, lay, text):
        lb = label(text.upper(), "section")
        lay.addWidget(lb)
        return lb

    def _build_position_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        quick = QHBoxLayout()
        self.b_ll0 = QPushButton("↙  Lower-left → 0,0")
        self.b_ll0.setToolTip("Most common: start the job at your work zero.")
        self.b_ll0.clicked.connect(lambda: self.place("min", "min", 0.0, 0.0))
        self.b_c0 = QPushButton("●  Center → 0,0")
        self.b_c0.setToolTip("When you zero the machine on the middle of the stock.")
        self.b_c0.clicked.connect(lambda: self.place("mid", "mid", 0.0, 0.0))
        quick.addWidget(self.b_ll0)
        quick.addWidget(self.b_c0)
        lay.addLayout(quick)

        self._section(lay, "Place a point of the job at")
        self.pos_anchor = AnchorPicker("min", "min")
        self.pos_x = spin()
        self.pos_y = spin()
        coords = QGridLayout()
        coords.addWidget(label("X"), 0, 0)
        coords.addWidget(self.pos_x, 0, 1)
        coords.addWidget(label("Y"), 1, 0)
        coords.addWidget(self.pos_y, 1, 1)
        row = QHBoxLayout()
        row.addWidget(self.pos_anchor)
        row.addSpacing(12)
        row.addLayout(coords)
        row.addStretch(1)
        lay.addLayout(row)
        self.pos_hint = label("", "muted", wrap=True)
        lay.addWidget(self.pos_hint)
        self.b_place = primary_button("Place job")
        self.b_place.clicked.connect(lambda: self.place(*self.pos_anchor.value(), self.pos_x.value(), self.pos_y.value()))
        lay.addWidget(self.b_place)

        self._section(lay, "Move by")
        self.mv_x = spin()
        self.mv_y = spin()
        self.b_move = QPushButton("Move job")
        self.b_move.clicked.connect(self.move_by)
        lay.addWidget(form_row("ΔX", self.mv_x, "ΔY", self.mv_y))
        lay.addWidget(self.b_move)
        lay.addStretch(1)

        for s in (self.pos_x, self.pos_y, self.mv_x, self.mv_y):
            s.valueChanged.connect(self.update_overlay)
        self.pos_anchor.changed.connect(self.update_overlay)
        self._pos_focus = "place"
        for s in (self.pos_x, self.pos_y):
            s.valueChanged.connect(lambda _=0: self._set_pos_focus("place"))
        self.pos_anchor.changed.connect(lambda: self._set_pos_focus("place"))
        for s in (self.mv_x, self.mv_y):
            s.valueChanged.connect(lambda _=0: self._set_pos_focus("move"))
        return w

    def _set_pos_focus(self, which):
        self._pos_focus = which
        self.update_overlay()

    def _build_scale_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        self.scale_disabled = label("This file has arcs in the XZ/YZ planes, which can't be scaled.", "banner-info", wrap=True)
        lay.addWidget(self.scale_disabled)

        self._section(lay, "Scale by")
        self.sc_pct = QRadioButton("Percent")
        self.sc_w = QRadioButton("Width")
        self.sc_h = QRadioButton("Height")
        self.sc_pct.setChecked(True)
        self.sc_group = QButtonGroup(self)
        for b in (self.sc_pct, self.sc_w, self.sc_h):
            self.sc_group.addButton(b)
        lay.addWidget(form_row(self.sc_pct, self.sc_w, self.sc_h))
        self.sc_value = spin(0.001, 100000, 5.0, 3, 100.0)
        lay.addWidget(self.sc_value)

        self._section(lay, "Fixed point")
        self.sc_anchor = AnchorPicker("mid", "mid")
        lay.addWidget(self.sc_anchor)

        self.sc_preview = label("", wrap=True)
        self.sc_preview.setObjectName("card")
        self.sc_preview.setTextFormat(Qt.RichText)
        self.sc_preview.setContentsMargins(10, 8, 10, 8)
        lay.addWidget(self.sc_preview)
        self.b_scale = primary_button("Scale job")
        self.b_scale.clicked.connect(self.scale)
        lay.addWidget(self.b_scale)
        note = label(
            "Scales X/Y and arcs. Z, feed rate and spindle speed / laser power stay the same.\n"
            "CNC: the bit doesn't scale, so offset paths come out slightly off size.\n"
            "Laser images: line spacing scales too (bigger = lighter, smaller = darker).",
            "muted",
            wrap=True,
        )
        lay.addWidget(note)
        lay.addStretch(1)

        self.sc_group.buttonToggled.connect(self._scale_mode_changed)
        self.sc_value.valueChanged.connect(self.update_overlay)
        self.sc_anchor.changed.connect(self.update_overlay)
        self._scale_widgets = [self.sc_pct, self.sc_w, self.sc_h, self.sc_value, self.sc_anchor, self.b_scale]
        return w

    def _build_z_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        self.z_none = label("This file has no Z moves (typical for laser files). Nothing to adjust here.", "banner-info", wrap=True)
        lay.addWidget(self.z_none)
        self.z_body = QWidget()
        zl = QVBoxLayout(self.z_body)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.setSpacing(8)
        self.z_range = label("", wrap=True)
        self.z_range.setTextFormat(Qt.RichText)
        zl.addWidget(self.z_range)
        self.z_set = QRadioButton("Set deepest cut to")
        self.z_move = QRadioButton("Move Z by")
        self.z_move.setChecked(True)
        zg = QButtonGroup(self)
        zg.addButton(self.z_set)
        zg.addButton(self.z_move)
        zl.addWidget(form_row(self.z_set, self.z_move))
        self.z_val = spin(step=0.1)
        zl.addWidget(self.z_val)
        self.z_effect = label("", "banner-warning", wrap=True)
        zl.addWidget(self.z_effect)
        self.z_confirm = QCheckBox("I understand this changes the cut depth / focus")
        zl.addWidget(self.z_confirm)
        self.b_z = primary_button("Apply Z change")
        self.b_z.clicked.connect(self.apply_z)
        zl.addWidget(self.b_z)
        lay.addWidget(self.z_body)
        lay.addStretch(1)
        for sig in (self.z_val.valueChanged, zg.buttonToggled, self.z_confirm.toggled):
            sig.connect(lambda *_: self._update_z())
        return w

    # ---- analysis ----------------------------------------------------------- #
    def info(self, text):
        key = hash(text)
        if key not in self._info_cache:
            if len(self._info_cache) > 12:
                self._info_cache.clear()
            self._info_cache[key] = get_gcode_info(text)
        return self._info_cache[key]

    def paths(self, text):
        key = hash(text)
        if key not in self._path_cache:
            if len(self._path_cache) > 12:
                self._path_cache.clear()
            cut, travel = QPainterPath(), QPainterPath()
            for kind, pts in get_toolpath(text):
                p = cut if kind == "cut" else travel
                p.moveTo(*pts[0])
                for xy in pts[1:]:
                    p.lineTo(*xy)
            self._path_cache[key] = (cut, travel)
        return self._path_cache[key]

    @property
    def loaded(self):
        return self.path is not None

    @property
    def modified(self):
        return self.loaded and self.output != self.original

    @property
    def dirty(self):
        return self.loaded and self.output != self.saved_text

    def box(self, text=None):
        return alignment_box(self.info(self.output if text is None else text))

    # ---- refresh ------------------------------------------------------------ #
    def refresh(self, refit=False):
        loaded = self.loaded
        self.stack.setCurrentIndex(1 if loaded else 0)
        for wdg in (self.metrics, self.tabs, self.history_title, self.history, self.footer, self.view_bar):
            wdg.setVisible(loaded)
        for a in (self.a_save, self.a_save_as, self.a_fit):
            a.setEnabled(loaded)
        can_undo, can_redo = bool(self.undo_stack), bool(self.redo_stack)
        self.a_undo.setEnabled(can_undo)
        self.b_undo.setEnabled(can_undo)
        self.a_redo.setEnabled(can_redo)
        self.b_redo.setEnabled(can_redo)
        self.a_reset.setEnabled(self.modified)
        self.b_reset.setEnabled(self.modified)

        name = os.path.basename(self.path) if loaded else ""
        self.setWindowTitle(f"{name}{' •' if self.dirty else ''} — {APP_NAME}" if loaded else APP_NAME)
        self._refresh_history()

        while self.banner_box.count():
            old = self.banner_box.takeAt(0).widget()
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()

        if not loaded:
            self.file_title.setText("No file loaded")
            self.file_meta.setText("Open a file to start")
            for c in (self.m_w, self.m_h, self.m_ll, self.m_z):
                c.set("—")
            self.legend.setText("")
            return

        info = self.info(self.output)
        u = info["units"]
        box, obox = self.box(), self.box(self.original)
        self.file_title.setText(name)
        self.file_title.setToolTip(self.path)
        n_lines = self.original.count("\n") + 1
        self.file_meta.setText(f"{n_lines:,} lines · {len(self.original) / 1024:,.1f} KB · {u}")

        def delta(axis, key):
            a, b = box[key][axis], obox[key][axis]
            if a is None or b is None or abs(a - b) < 1e-9:
                return ""
            return f"{a - b:+,.2f} vs original"

        self.m_w.set(f"{fmt(box['size']['X'])} {u}", delta("X", "size"))
        self.m_h.set(f"{fmt(box['size']['Y'])} {u}", delta("Y", "size"))
        self.m_ll.set(f"{fmt(box['min']['X'])}, {fmt(box['min']['Y'])}", "")
        has_z = box["min"]["Z"] is not None
        self.m_z.set(f"{fmt(box['min']['Z'])} {u}" if has_z else "No Z", delta("Z", "min"))

        for level, text in info["notices"]:
            b = label(("⚠  " if level == "warning" else "ℹ  ") + text, f"banner-{level}", wrap=True)
            self.banner_box.addWidget(b)

        suffix = f" {u}"
        for s in (self.pos_x, self.pos_y, self.mv_x, self.mv_y, self.z_val):
            s.setSuffix(suffix)
        self._scale_mode_changed(None, True, keep_value=True)

        can_scale = info["can_scale"]
        self.scale_disabled.setVisible(not can_scale)
        for wdg in self._scale_widgets:
            wdg.setEnabled(can_scale)

        self.z_none.setVisible(not has_z)
        self.z_body.setVisible(has_z)
        self._update_z()
        self._redraw(refit=refit)

    def _refresh_history(self):
        self.history.clear()
        if not self.loaded:
            return
        it = QListWidgetItem("Opened original file")
        it.setForeground(QColor(self.t["muted"]))
        self.history.addItem(it)
        for i, (lbl, _) in enumerate(self.undo_stack, 1):
            self.history.addItem(QListWidgetItem(f"{i}. {lbl}"))
        for lbl, _ in reversed(self.redo_stack):
            it = QListWidgetItem(f"↷ {lbl}  (undone)")
            f = it.font()
            f.setItalic(True)
            it.setFont(f)
            it.setForeground(QColor(self.t["muted"]))
            self.history.addItem(it)
        self.history.scrollToBottom()

    def _redraw(self, *_, refit=False):
        s = self.settings
        s.setValue("show_travel", self.a_travel.isChecked())
        s.setValue("show_original", self.a_orig.isChecked())
        s.setValue("show_bed", self.a_bed.isChecked())
        if not self.loaded:
            return
        t = self.t
        cut, travel = self.paths(self.output)
        items = []
        legend = [f"<span style='color:{t['cut']}'>━━</span> cut / burn"]
        if self.a_orig.isChecked() and self.modified:
            ocut, _ = self.paths(self.original)
            items.append((ocut, {"pen": {"color": t["original"], "width": 1.2, "dash": [3, 3], "alpha": 170}, "z": 3}))
            legend.append(f"<span style='color:{t['original']}'>┅┅</span> original")
        if self.a_travel.isChecked():
            items.append((travel, {"pen": {"color": t["travel"], "width": 0.9, "dash": [4, 4]}, "z": 3.5}))
            legend.append(f"<span style='color:{t['travel']}'>╌╌</span> travel")
        items.append((cut, {"pen": {"color": t["cut"], "width": 1.5}, "z": 4}))
        legend.append(f"<span style='color:{t['origin']}'>✚</span> work zero")
        legend.append(f"<span style='color:{t['target']}'>◆ ┅</span> result preview")
        self.legend.setText("&nbsp;&nbsp;&nbsp;".join(legend))

        box = self.box()
        job_rect = None
        if box["min"]["X"] is not None and box["min"]["Y"] is not None:
            job_rect = QRectF(QPointF(box["min"]["X"], box["min"]["Y"]), QPointF(box["max"]["X"], box["max"]["Y"]))
        self.view.set_content(items, job_rect, self.a_bed.isChecked(),
                              25.4 if self.info(self.output)["units"] == "inch" else 1.0)
        if refit:
            self.view.fit()
        else:
            self.view.ensure_visible_content()
        self.update_overlay()

    # ---- live previews (marker + ghost box) ------------------------------- #
    def _rect(self, box, dx=0.0, dy=0.0, factor=1.0, ref=(0.0, 0.0)):
        if box["min"]["X"] is None or box["min"]["Y"] is None:
            return None
        rx, ry = ref
        x0 = (box["min"]["X"] - rx) * factor + rx + dx
        x1 = (box["max"]["X"] - rx) * factor + rx + dx
        y0 = (box["min"]["Y"] - ry) * factor + ry + dy
        y1 = (box["max"]["Y"] - ry) * factor + ry + dy
        return QRectF(QPointF(x0, y0), QPointF(x1, y1))

    @staticmethod
    def _anchor_xy(box, h, v):
        return box[h]["X"], box[v]["Y"]

    def _scale_factor(self, box):
        if self.sc_pct.isChecked():
            return self.sc_value.value() / 100.0
        size = box["size"]["X" if self.sc_w.isChecked() else "Y"]
        return self.sc_value.value() / size if size else None

    def update_overlay(self, *_):
        if not self.loaded:
            return
        box = self.box()
        u = self.info(self.output)["units"]
        tab = self.tabs.currentIndex()
        marker = target = None

        # Position tab hint
        ax, ay = self._anchor_xy(box, *self.pos_anchor.value())
        if ax is not None and ay is not None:
            dx, dy = self.pos_x.value() - ax, self.pos_y.value() - ay
            self.pos_hint.setText(
                f"The ◆ {self.pos_anchor.describe()} point is at {fmt(ax, 3)}, {fmt(ay, 3)} — "
                + (f"it will move by X {sfmt(dx)}, Y {sfmt(dy)} {u}." if abs(dx) > EPS or abs(dy) > EPS else "already there.")
            )
            self.b_place.setEnabled(abs(dx) > EPS or abs(dy) > EPS)
        else:
            self.pos_hint.setText("No known XY position to place.")
            self.b_place.setEnabled(False)
        self.b_move.setEnabled(self.mv_x.value() != 0 or self.mv_y.value() != 0)

        if tab == 0:
            if self._pos_focus == "move":
                if self.b_move.isEnabled():
                    target = self._rect(box, self.mv_x.value(), self.mv_y.value())
            elif ax is not None and ay is not None:
                marker = (ax, ay, f"{self.pos_anchor.describe().title()} point")
                if self.b_place.isEnabled():
                    target = self._rect(box, self.pos_x.value() - ax, self.pos_y.value() - ay)
        elif tab == 1:
            factor = self._scale_factor(box)
            rx, ry = self._anchor_xy(box, *self.sc_anchor.value())
            sx, sy = box["size"]["X"], box["size"]["Y"]
            ok = bool(factor) and sx is not None and sy is not None and self.info(self.output)["can_scale"]
            if ok:
                self.sc_preview.setText(
                    f"<b>{fmt(sx)} × {fmt(sy)}</b> &nbsp;→&nbsp; <b>{fmt(sx * factor)} × {fmt(sy * factor)}</b> {u}"
                    f"<br><span style='color:{self.t['muted']}'>{factor * 100:,.2f}% · aspect ratio kept · "
                    f"{self.sc_anchor.describe()} stays in place</span>"
                )
                marker = (rx, ry, "Fixed point")
                if abs(factor - 1) > 1e-6:
                    target = self._rect(box, factor=factor, ref=(rx or 0.0, ry or 0.0))
            else:
                self.sc_preview.setText("")
            self.b_scale.setEnabled(ok and abs(factor - 1) > 1e-6)
        self.view.set_overlay(marker, target)

    def _scale_mode_changed(self, _button, checked, keep_value=False):
        if not checked or not self.loaded:
            return
        u = self.info(self.output)["units"]
        box = self.box()
        self.sc_value.blockSignals(True)
        if self.sc_pct.isChecked():
            self.sc_value.setSuffix(" %")
            self.sc_value.setSingleStep(5.0)
            if not keep_value:
                self.sc_value.setValue(100.0)
        else:
            self.sc_value.setSuffix(f" {u}")
            self.sc_value.setSingleStep(1.0)
            size = box["size"]["X" if self.sc_w.isChecked() else "Y"]
            if size and not keep_value:
                self.sc_value.setValue(round(size, 3))
        self.sc_value.blockSignals(False)
        self.update_overlay()

    def _update_z(self):
        if not self.loaded:
            return
        box = self.box()
        zmin, zmax = box["min"]["Z"], box["max"]["Z"]
        if zmin is None:
            return
        u = self.info(self.output)["units"]
        self.z_range.setText(
            f"Cutting Z range: <b>{fmt(zmax, 3)}</b> (top) to <b>{fmt(zmin, 3)}</b> (deepest) {u}.<br>"
            f"<span style='color:{self.t['muted']}'>Changing Z changes how deep the bit cuts (CNC) or the focus height (laser).</span>"
        )
        dz = (self.z_val.value() - zmin) if self.z_set.isChecked() else self.z_val.value()
        if abs(dz) > 1e-9:
            self.z_effect.setText(
                f"⚠  Every Z move (including safe height) goes {abs(dz):.3f} {u} {'deeper' if dz < 0 else 'higher'}."
            )
            self.z_effect.setVisible(True)
        else:
            self.z_effect.setVisible(False)
        self.b_z.setEnabled(self.z_confirm.isChecked() and abs(dz) > 1e-9)

    # ---- operations --------------------------------------------------------- #
    def apply(self, label_text, new_text):
        if new_text == self.output:
            self.statusBar().showMessage("Nothing changed.", 3000)
            return
        self.undo_stack.append((label_text, self.output))
        self.redo_stack.clear()
        self.output = new_text
        self.statusBar().showMessage(f"✓ {label_text}", 5000)
        self.refresh()

    def place(self, h, v, x, y):
        ax, ay = self._anchor_xy(self.box(), h, v)
        if ax is None or ay is None:
            return
        name = "center" if (h, v) == ("mid", "mid") else f"{V_NAMES[v]}-{H_NAMES[h]}"
        self.apply(f"Placed {name} at X{x:g} Y{y:g}", shift_gcode(self.output, x - ax, y - ay, 0.0))

    def move_by(self):
        dx, dy = self.mv_x.value(), self.mv_y.value()
        self.apply(f"Moved by X{dx:+g} Y{dy:+g}", shift_gcode(self.output, dx, dy, 0.0))

    def scale(self):
        box = self.box()
        factor = self._scale_factor(box)
        if not factor:
            return
        rx, ry = self._anchor_xy(box, *self.sc_anchor.value())
        try:
            new = scale_gcode(self.output, factor, rx or 0.0, ry or 0.0)
        except ValueError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self.apply(f"Scaled to {factor * 100:.2f}% ({self.sc_anchor.describe()} fixed)", new)
        if not self.sc_pct.isChecked():
            self._scale_mode_changed(None, True)

    def apply_z(self):
        zmin = self.box()["min"]["Z"]
        dz = (self.z_val.value() - zmin) if self.z_set.isChecked() else self.z_val.value()
        self.z_confirm.setChecked(False)  # fresh confirmation for every Z change
        self.apply(f"Z shifted by {dz:+g}", shift_gcode(self.output, 0.0, 0.0, dz))

    def undo(self):
        if self.undo_stack:
            lbl, before = self.undo_stack.pop()
            self.redo_stack.append((lbl, self.output))
            self.output = before
            self.statusBar().showMessage(f"Undid: {lbl}", 4000)
            self.refresh()

    def redo(self):
        if self.redo_stack:
            lbl, after = self.redo_stack.pop()
            self.undo_stack.append((lbl, self.output))
            self.output = after
            self.statusBar().showMessage(f"Redid: {lbl}", 4000)
            self.refresh()

    def reset(self):
        if self.modified:
            self.apply("Reset to original", self.original)

    # ---- files -------------------------------------------------------------- #
    def _confirm_discard(self):
        if not self.dirty:
            return True
        r = QMessageBox.question(
            self,
            APP_NAME,
            "You have unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def open_dialog(self):
        if not self._confirm_discard():
            return
        start = self.settings.value("last_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, "Open G-code", start, FILE_FILTER)
        if path:
            self.load(path)

    def load(self, path):
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't open the file:\n{e}")
            return
        text = raw.decode("utf-8-sig", errors="replace")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.path = path
            self.save_path = None
            self.original = self.output = self.saved_text = text
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.settings.setValue("last_dir", os.path.dirname(path))
            self.mv_x.setValue(0)
            self.mv_y.setValue(0)
            self.z_confirm.setChecked(False)
            self.sc_pct.setChecked(True)
            self.sc_value.setValue(100.0)
            self._pos_focus = "place"
            self.refresh(refit=True)
        finally:
            QApplication.restoreOverrideCursor()
        msg = f"Opened {os.path.basename(path)}"
        if "�" in text:
            msg += " — some characters weren't valid UTF-8 and were replaced"
        self.statusBar().showMessage(msg, 6000)

    def save(self):
        if not self.loaded:
            return False
        if self.save_path is None:
            return self.save_as()
        return self._write(self.save_path)

    def save_as(self):
        if not self.loaded:
            return False
        base, ext = os.path.splitext(self.path)
        suggested = self.save_path or f"{base}_edited{ext or '.nc'}"
        path, _ = QFileDialog.getSaveFileName(self, "Save G-code", suggested, FILE_FILTER)
        if not path:
            return False
        if (os.path.normcase(os.path.realpath(path)) ==
                os.path.normcase(os.path.realpath(self.path))):
            r = QMessageBox.warning(
                self, APP_NAME, "This overwrites the original file. Continue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return False
        return self._write(path)

    def _write(self, path):
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(self.output)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't save the file:\n{e}")
            return False
        self.save_path = path
        self.saved_text = self.output
        self.statusBar().showMessage(f"Saved {path}", 6000)
        self.refresh()
        return True

    # ---- events ------------------------------------------------------------- #
    def _on_cursor(self, p):
        if p is None or not self.loaded:
            self.cursor_label.setText("")
        else:
            u = self.info(self.output)["units"]
            self.cursor_label.setText(f"X {p.x():,.3f}   Y {p.y():,.3f} {u}  ")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files and self._confirm_discard():
            self.load(files[0])

    def showEvent(self, e):
        super().showEvent(e)
        if self.loaded:
            self.view.fit()

    def closeEvent(self, e):
        if self._confirm_discard():
            self.settings.setValue("geometry", self.saveGeometry())
            e.accept()
        else:
            e.ignore()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    dark = is_dark()
    theme = make_theme(dark)
    app.setPalette(make_palette(theme, dark))
    app.setStyleSheet(make_stylesheet(theme))
    win = MainWindow(theme)
    win.show()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        win.load(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
