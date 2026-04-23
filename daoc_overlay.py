#!/usr/bin/env python3
"""
Region Mirror — spiegelt einen frei konfigurierbaren Bildschirmbereich
als bewegliches, immer-oben-Overlay. Alles steuerbar ohne den Bereich zu überlagern.

Abhängigkeiten: pip install PySide6 mss numpy
"""
import sys
import ctypes
import mss
import numpy as np

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QSpinBox, QHBoxLayout,
    QVBoxLayout, QPushButton, QFrame, QSizeGrip, QSlider
)
from PySide6.QtCore import Qt, QTimer, QPoint, QThread, Signal, QSize
from PySide6.QtGui import QImage, QPixmap, QRegion, QPainter, QColor, QKeySequence, QShortcut

# ── Windows: DPI-Awareness sicherstellen ──────────────────────────────────────
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

BORDER_PX  = 3    # Rahmenbreite des Capture-Indikators
TARGET_FPS = 30   # Capture-Framerate


# ── Capture-Indikator ─────────────────────────────────────────────────────────
class CaptureIndicator(QWidget):
    """
    Zeigt den aufzunehmenden Bereich als leuchtendes Rechteck.
    Nur der Rahmen ist sichtbar; die Mitte ist transparent & klickdurchlässig.
    """
    def __init__(self):
        super().__init__()
        flags = (
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._color = QColor(255, 70, 0, 230)

    def update_region(self, x: int, y: int, w: int, h: int):
        b = BORDER_PX
        self.setGeometry(x - b, y - b, w + 2 * b, h + 2 * b)
        outer = QRegion(0, 0, w + 2 * b, h + 2 * b)
        inner = QRegion(b, b, w, h)
        self.setMask(outer.subtracted(inner))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), self._color)


# ── Mirror-Overlay ────────────────────────────────────────────────────────────
class MirrorWindow(QWidget):
    """
    Zeigt das Live-Bild des erfassten Bereichs.
    Frei verschiebbar per Drag, skaliert den Inhalt auf die Fenstergröße.
    """
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos: QPoint | None = None
        self._opacity: float = 1.0

        # Inhalt-Label
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            "background: #0a0a0a; border: 1px solid rgba(255,255,255,60);"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._label)

        self.resize(400, 300)
        self.move(200, 600)

    def set_frame(self, img: QImage):
        size = self._label.size()
        px = QPixmap.fromImage(img).scaled(
            size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._label.setPixmap(px)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._label.resize(self.size())

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, ev):
        if self._drag_pos and ev.buttons() == Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _ev):
        self._drag_pos = None


# ── Control Panel ─────────────────────────────────────────────────────────────
PANEL_STYLE = """
QWidget#panel_frame {
    background: rgba(18, 18, 18, 225);
    border: 1px solid rgba(255,255,255,45);
    border-radius: 10px;
}
QLabel {
    color: rgba(255,255,255,175);
    font-size: 11px;
    background: transparent;
    border: none;
    min-width: 12px;
}
QLabel#title_lbl {
    color: rgba(255,255,255,230);
    font-size: 12px;
    font-weight: 600;
}
QSpinBox {
    background: rgba(255,255,255,12);
    color: rgba(255,255,255,220);
    border: 1px solid rgba(255,255,255,35);
    border-radius: 5px;
    padding: 2px 4px;
    font-size: 11px;
    min-width: 62px;
    max-width: 70px;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 16px;
    background: rgba(255,255,255,15);
    border: none;
}
QSpinBox::up-arrow   { image: none; border: 3px solid transparent; border-bottom: 5px solid rgba(255,255,255,160); width:0; }
QSpinBox::down-arrow { image: none; border: 3px solid transparent; border-top:    5px solid rgba(255,255,255,160); width:0; }
QPushButton#close_btn {
    background: rgba(255,255,255,18);
    color: rgba(255,255,255,200);
    border: none;
    border-radius: 4px;
    font-size: 11px;
    padding: 0;
}
QPushButton#close_btn:hover { background: rgba(220,60,40,200); }
QPushButton#indicator_btn {
    background: rgba(255,70,0,170);
    color: white;
    border: none;
    border-radius: 5px;
    padding: 4px 0;
    font-size: 11px;
}
QPushButton#indicator_btn:checked {
    background: rgba(255,70,0,60);
    color: rgba(255,200,180,200);
}
QPushButton#indicator_btn:hover { background: rgba(255,90,20,220); }
QSlider::groove:horizontal {
    background: rgba(255,255,255,25);
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: rgba(255,150,80,230);
    width: 12px; height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: rgba(255,100,30,180);
    border-radius: 2px;
}
"""

class ControlPanel(QWidget):
    region_changed = Signal(int, int, int, int)
    opacity_changed = Signal(float)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(PANEL_STYLE)
        self._drag_pos: QPoint | None = None
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        frame = QFrame(self)
        frame.setObjectName("panel_frame")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        inner = QVBoxLayout(frame)
        inner.setContentsMargins(12, 10, 12, 10)
        inner.setSpacing(7)

        # ── Titelzeile ───────────────────────────────────────────────────────
        row_title = QHBoxLayout()
        lbl_title = QLabel("Region Mirror")
        lbl_title.setObjectName("title_lbl")
        btn_close = QPushButton("✕")
        btn_close.setObjectName("close_btn")
        btn_close.setFixedSize(20, 20)
        btn_close.clicked.connect(QApplication.quit)
        row_title.addWidget(lbl_title)
        row_title.addStretch()
        row_title.addWidget(btn_close)
        inner.addLayout(row_title)

        inner.addWidget(self._separator())

        # ── X / Y ────────────────────────────────────────────────────────────
        row_xy = QHBoxLayout()
        row_xy.setSpacing(5)
        row_xy.addWidget(QLabel("X"))
        self._x = self._spin(0, 7680, 0)
        row_xy.addWidget(self._x)
        row_xy.addSpacing(6)
        row_xy.addWidget(QLabel("Y"))
        self._y = self._spin(0, 4320, 0)
        row_xy.addWidget(self._y)
        inner.addLayout(row_xy)

        # ── W / H ────────────────────────────────────────────────────────────
        row_wh = QHBoxLayout()
        row_wh.setSpacing(5)
        row_wh.addWidget(QLabel("B"))
        self._w = self._spin(10, 3840, 400)
        row_wh.addWidget(self._w)
        row_wh.addSpacing(6)
        row_wh.addWidget(QLabel("H"))
        self._h = self._spin(10, 2160, 300)
        row_wh.addWidget(self._h)
        inner.addLayout(row_wh)

        inner.addWidget(self._separator())

        # ── Rahmen ein/aus ────────────────────────────────────────────────────
        self._ind_btn = QPushButton("◉  Capture-Rahmen sichtbar")
        self._ind_btn.setObjectName("indicator_btn")
        self._ind_btn.setCheckable(True)
        self._ind_btn.setChecked(True)
        inner.addWidget(self._ind_btn)

        # ── Opazität Mirror ───────────────────────────────────────────────────
        row_op = QHBoxLayout()
        row_op.addWidget(QLabel("Opazität"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.valueChanged.connect(
            lambda v: self.opacity_changed.emit(v / 100.0)
        )
        self._opacity_lbl = QLabel("100%")
        self._opacity_lbl.setFixedWidth(34)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_lbl.setText(f"{v}%")
        )
        row_op.addWidget(self._opacity_slider)
        row_op.addWidget(self._opacity_lbl)
        inner.addLayout(row_op)

        frame.adjustSize()
        self.adjustSize()

    def _spin(self, lo: int, hi: int, val: int = 0) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setSingleStep(1)
        # Feinsteuerung: Shift+Pfeil = ±10, Ctrl+Pfeil = ±100
        s.valueChanged.connect(lambda *_: self._emit())
        return s

    @staticmethod
    def _separator() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(
            "background: rgba(255,255,255,25); max-height:1px; border:none;"
        )
        return f

    # ── API ──────────────────────────────────────────────────────────────────
    def _emit(self):
        self.region_changed.emit(
            self._x.value(), self._y.value(),
            self._w.value(), self._h.value(),
        )

    def get_region(self) -> tuple[int, int, int, int]:
        return self._x.value(), self._y.value(), self._w.value(), self._h.value()

    @property
    def indicator_visible(self) -> bool:
        return self._ind_btn.isChecked()

    # ── Drag ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, ev):
        if self._drag_pos and ev.buttons() == Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _ev):
        self._drag_pos = None


# ── Capture-Thread ────────────────────────────────────────────────────────────
class CaptureThread(QThread):
    frame_ready = Signal(QImage)
    error       = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._region = (0, 0, 400, 300)
        self._running = True
        # Retina/HiDPI: logische → physische Pixel
        screen = QApplication.primaryScreen()
        self._dpr = screen.devicePixelRatio() if screen else 1.0

    def set_region(self, x: int, y: int, w: int, h: int):
        d = self._dpr
        self._region = (
            max(0, int(x * d)),
            max(0, int(y * d)),
            max(1, int(w * d)),
            max(1, int(h * d)),
        )

    def stop(self):
        self._running = False
        self.wait()

    def run(self):
        with mss.mss() as sct:
            blank_count = 0
            while self._running:
                x, y, w, h = self._region
                mon = {"left": x, "top": y, "width": w, "height": h}
                try:
                    raw = sct.grab(mon)
                    arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(
                        raw.height, raw.width, 4
                    )
                    # Schwarzes Bild = Screen Recording Permission fehlt (macOS)
                    if arr[:, :, :3].max() == 0:
                        blank_count += 1
                        if blank_count == TARGET_FPS:
                            self.error.emit(
                                "Schwarzes Bild erkannt.\n\n"
                                "macOS: Systemeinstellungen → Datenschutz & Sicherheit\n"
                                "→ Bildschirmaufnahme → Terminal (oder Python) aktivieren,\n"
                                "dann das Tool neu starten."
                            )
                    else:
                        blank_count = 0

                    img = QImage(
                        arr.data, raw.width, raw.height, raw.width * 4,
                        QImage.Format.Format_BGRA8888,
                    )
                    self.frame_ready.emit(img.copy())
                except Exception as exc:
                    self.error.emit(str(exc))
                self.msleep(1000 // TARGET_FPS)


# ── App-Koordinator ───────────────────────────────────────────────────────────
class RegionMirrorApp:
    def __init__(self):
        self.indicator = CaptureIndicator()
        self.mirror    = MirrorWindow()
        self.panel     = ControlPanel()
        self.thread    = CaptureThread()

        # Signale verbinden
        self.thread.frame_ready.connect(self.mirror.set_frame)
        self.thread.error.connect(self._on_error)
        self.panel.region_changed.connect(self._on_region_changed)
        self.panel.opacity_changed.connect(self._on_opacity)
        self.panel._ind_btn.toggled.connect(self._on_indicator_toggle)

        # Initiale Region anwenden
        x, y, w, h = self.panel.get_region()
        self._on_region_changed(x, y, w, h)
        self.thread.start()

        # Panel oben rechts positionieren
        screen = QApplication.primaryScreen().availableGeometry()
        self.panel.adjustSize()
        self.panel.move(screen.right() - self.panel.width() - 24, screen.top() + 24)

        self.indicator.show()
        self.mirror.show()
        self.panel.show()

    def _on_error(self, msg: str):
        self.mirror._label.setText(msg)
        self.mirror._label.setStyleSheet(
            "background:#1a0a0a; color:rgba(255,120,80,220);"
            "font-size:11px; padding:12px; border:1px solid rgba(255,80,40,120);"
        )

    def _on_region_changed(self, x: int, y: int, w: int, h: int):
        self.thread.set_region(x, y, w, h)
        self.mirror.resize(w, h)
        if self.panel.indicator_visible:
            self.indicator.update_region(x, y, w, h)

    def _on_indicator_toggle(self, visible: bool):
        if visible:
            x, y, w, h = self.panel.get_region()
            self.indicator.update_region(x, y, w, h)
            self.indicator.show()
        else:
            self.indicator.hide()

    def _on_opacity(self, value: float):
        self.mirror.setWindowOpacity(value)

    def shutdown(self):
        self.thread.stop()


# ── Einstiegspunkt ────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RegionMirror")
    app.setQuitOnLastWindowClosed(False)

    mirror_app = RegionMirrorApp()

    ret = app.exec()
    mirror_app.shutdown()
    sys.exit(ret)


if __name__ == "__main__":
    main()