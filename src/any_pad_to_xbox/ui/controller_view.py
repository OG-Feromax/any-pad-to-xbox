"""Xbox 360 controller overlay with hit-areas and dual highlight layers."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from any_pad_to_xbox import asset_path
from any_pad_to_xbox.core.evdev_monitor import axis_is_active


class ControllerView(QWidget):
    """Clickable Xbox diagram.

    Layers:
      - virtual (green): live state of the real virtual Xbox pad only
      - learn (amber): control waiting to be assigned
      - physical (blue dashed): direct pad preview when readable
    """

    control_clicked = Signal(str)
    learn_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 340)
        self.setMouseTracking(True)
        self._regions: dict = {}
        self._labels: dict = {}
        self._image_size = (720, 480)
        self._physical: set[str] = set()
        self._virtual: set[str] = set()
        self._axis_physical: dict[str, float] = {}
        self._axis_virtual: dict[str, float] = {}
        # 0 = jstest-like (instant off). Small values only for mash-pulse masking.
        self.RELEASE_HOLD_S = 0.0
        self._hold_physical: dict[str, float] = {}
        self._hold_virtual: dict[str, float] = {}
        self._live_physical: set[str] = set()
        self._live_virtual: set[str] = set()
        self._hover: str | None = None
        self._learn_target: str | None = None
        self._svg = QSvgRenderer(str(asset_path("xbox360.svg")))
        self._svg_cache: QPixmap | None = None
        self._svg_cache_key: tuple | None = None
        self._load_regions()

    def _load_regions(self) -> None:
        path = asset_path("regions.json")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._image_size = tuple(data.get("image_size", [720, 480]))
        self._regions = data.get("regions", {})
        self._labels = data.get("labels", {})

    def set_release_hold(self, seconds: float) -> None:
        """0 = instant release (Test / live). Tiny >0 masks mash up→down pulses."""
        seconds = max(0.0, float(seconds))
        if seconds == self.RELEASE_HOLD_S:
            return
        self.RELEASE_HOLD_S = seconds
        if seconds <= 0:
            self._hold_physical.clear()
            self._hold_virtual.clear()
            self._physical = set(self._live_physical)
            self._virtual = set(self._live_virtual)
            self.update()

    def set_physical_active(self, controls: set[str], axes: dict[str, float] | None = None) -> None:
        self.apply_layers(physical=controls, physical_axes=axes)

    def set_virtual_active(self, controls: set[str], axes: dict[str, float] | None = None) -> None:
        self.apply_layers(virtual=controls, virtual_axes=axes)

    def apply_layers(
        self,
        *,
        physical: set[str] | None = None,
        virtual: set[str] | None = None,
        physical_axes: dict[str, float] | None = None,
        virtual_axes: dict[str, float] | None = None,
    ) -> None:
        """Update highlight layers. Hold is optional (see set_release_hold)."""
        now = time.monotonic()
        changed = False

        def merge(incoming: set[str], live: set[str], hold: dict[str, float]) -> set[str]:
            if self.RELEASE_HOLD_S <= 0:
                hold.clear()
                if incoming != live:
                    live.clear()
                    live |= incoming
                return set(incoming)
            for name in incoming:
                hold.pop(name, None)
            for name in live - incoming:
                hold.setdefault(name, now + self.RELEASE_HOLD_S)
            for name in [n for n, until in hold.items() if until <= now]:
                del hold[name]
            live.clear()
            live |= incoming
            return set(incoming) | set(hold)

        if physical is not None:
            merged = merge(set(physical), self._live_physical, self._hold_physical)
            if merged != self._physical:
                self._physical = merged
                changed = True
        if virtual is not None:
            merged = merge(set(virtual), self._live_virtual, self._hold_virtual)
            if merged != self._virtual:
                self._virtual = merged
                changed = True
        if physical_axes is not None:
            cleaned = {k: max(-1.0, min(1.0, v)) for k, v in physical_axes.items()}
            if cleaned != self._axis_physical:
                self._axis_physical = cleaned
                changed = True
        if virtual_axes is not None:
            cleaned = {k: max(-1.0, min(1.0, v)) for k, v in virtual_axes.items()}
            if cleaned != self._axis_virtual:
                self._axis_virtual = cleaned
                changed = True
        if changed:
            self.update()
        if self.RELEASE_HOLD_S > 0 and (self._hold_physical or self._hold_virtual):
            QTimer.singleShot(int(self.RELEASE_HOLD_S * 1000) + 5, self._decay_hold)

    def _decay_hold(self) -> None:
        if self.RELEASE_HOLD_S <= 0:
            return
        now = time.monotonic()
        changed = False
        for hold, live, attr in (
            (self._hold_physical, self._live_physical, "_physical"),
            (self._hold_virtual, self._live_virtual, "_virtual"),
        ):
            for name in [n for n, until in hold.items() if until <= now]:
                del hold[name]
            new = set(live) | set(hold)
            if new != getattr(self, attr):
                setattr(self, attr, new)
                changed = True
        if changed:
            self.update()
        if self._hold_physical or self._hold_virtual:
            QTimer.singleShot(16, self._decay_hold)

    def set_physical_axis(self, name: str, norm: float) -> None:
        self._axis_physical[name] = max(-1.0, min(1.0, norm))

    def set_virtual_axis(self, name: str, norm: float) -> None:
        self._axis_virtual[name] = max(-1.0, min(1.0, norm))

    def clear_activity(self) -> None:
        self._physical.clear()
        self._virtual.clear()
        self._axis_physical.clear()
        self._axis_virtual.clear()
        self._live_physical.clear()
        self._live_virtual.clear()
        self._hold_physical.clear()
        self._hold_virtual.clear()
        self.update()

    def set_learn_target(self, name: str | None) -> None:
        self._learn_target = name
        self.update()

    def set_active_controls(self, controls: set[str]) -> None:
        self.set_physical_active(controls)

    def set_axis_value(self, name: str, norm: float) -> None:
        self.set_physical_axis(name, norm)

    def _content_rect(self) -> QRectF:
        iw, ih = self._image_size
        aspect = iw / ih
        w, h = self.width(), self.height()
        if w / h > aspect:
            cw = h * aspect
            ch = float(h)
            x = (w - cw) / 2
            y = 0.0
        else:
            cw = float(w)
            ch = w / aspect
            x = 0.0
            y = (h - ch) / 2
        return QRectF(x, y, cw, ch)

    def _ensure_svg_cache(self, rect: QRectF) -> QPixmap:
        dpr = self.devicePixelRatioF()
        w = max(1, int(rect.width()))
        h = max(1, int(rect.height()))
        key = (w, h, round(dpr, 3))
        if self._svg_cache is not None and self._svg_cache_key == key:
            return self._svg_cache
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        self._svg.render(painter, QRectF(0, 0, w, h))
        painter.end()
        self._svg_cache = pm
        self._svg_cache_key = key
        return pm

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._svg_cache = None
        self._svg_cache_key = None
        super().resizeEvent(event)

    def _region_path(self, spec: dict, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        shape = spec.get("shape", "ellipse")
        if shape == "ellipse":
            cx = rect.left() + spec["cx"] * rect.width()
            cy = rect.top() + spec["cy"] * rect.height()
            rx = spec["rx"] * rect.width()
            ry = spec["ry"] * rect.height()
            path.addEllipse(QPointF(cx, cy), rx, ry)
        else:
            x = rect.left() + spec["x"] * rect.width()
            y = rect.top() + spec["y"] * rect.height()
            w = spec["w"] * rect.width()
            h = spec["h"] * rect.height()
            path.addRoundedRect(QRectF(x, y, w, h), 6, 6)
        return path

    def _hit_test(self, pos: QPointF) -> str | None:
        rect = self._content_rect()
        order = sorted(
            self._regions.items(),
            key=lambda kv: (
                0 if kv[1].get("type") == "button" else 1,
                -(kv[1].get("rx", kv[1].get("w", 0.1)) * kv[1].get("ry", kv[1].get("h", 0.1))),
            ),
        )
        for name, spec in order:
            if self._region_path(spec, rect).contains(pos):
                return name
        return None

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#12141a"))
        rect = self._content_rect()
        painter.drawPixmap(rect.topLeft(), self._ensure_svg_cache(rect))

        for name, spec in self._regions.items():
            path = self._region_path(spec, rect)
            phys = name in self._physical or axis_is_active(
                name, self._axis_physical.get(name, 0.0)
            )
            virt = name in self._virtual or axis_is_active(
                name, self._axis_virtual.get(name, 0.0)
            )
            learn = name == self._learn_target
            hover = name == self._hover

            if learn:
                painter.setBrush(QBrush(QColor(255, 190, 40, 150)))
                painter.setPen(QPen(QColor(255, 170, 0), 3))
                painter.drawPath(path)
            elif virt and phys:
                painter.setBrush(QBrush(QColor(60, 230, 120, 170)))
                painter.setPen(QPen(QColor(30, 200, 90), 3))
                painter.drawPath(path)
            elif virt:
                painter.setBrush(QBrush(QColor(50, 210, 110, 150)))
                painter.setPen(QPen(QColor(20, 180, 80), 3))
                painter.drawPath(path)
            elif phys:
                painter.setBrush(QBrush(QColor(56, 160, 255, 120)))
                painter.setPen(QPen(QColor(40, 140, 255), 2, Qt.DashLine))
                painter.drawPath(path)
            elif hover:
                painter.setBrush(QBrush(QColor(255, 255, 255, 35)))
                painter.setPen(QPen(QColor(220, 220, 230), 2))
                painter.drawPath(path)

            for axis_x, axis_map, color in (
                (
                    "x1",
                    self._axis_virtual
                    if abs(self._axis_virtual.get("x1", 0)) > 0.05
                    else self._axis_physical,
                    QColor(255, 255, 255),
                ),
                (
                    "x2",
                    self._axis_virtual
                    if abs(self._axis_virtual.get("x2", 0)) > 0.05
                    else self._axis_physical,
                    QColor(255, 255, 255),
                ),
            ):
                if name != axis_x:
                    continue
                pair = spec.get("pair")
                xv = axis_map.get(axis_x, 0.0)
                yv = axis_map.get(pair or "", 0.0)
                if abs(xv) > 0.05 or abs(yv) > 0.05:
                    br = path.boundingRect()
                    cx, cy = br.center().x(), br.center().y()
                    painter.setPen(QPen(color, 3))
                    painter.setBrush(QBrush(color))
                    painter.drawEllipse(
                        QPointF(cx + xv * br.width() * 0.28, cy + yv * br.height() * 0.28),
                        6,
                        6,
                    )

        legend_y = rect.bottom() - 8
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        items = [
            (QColor(56, 160, 255), "Pad (direct)"),
            (QColor(50, 210, 110), "Virtual Xbox"),
            (QColor(255, 190, 40), "Learning"),
        ]
        x = rect.left() + 8
        for color, text in items:
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(x, legend_y - 12, 12, 12), 3, 3)
            painter.setPen(QColor("#9aa0aa"))
            painter.drawText(int(x + 16), int(legend_y - 1), text)
            x += 18 + painter.fontMetrics().horizontalAdvance(text) + 14

        if self._learn_target:
            painter.setPen(QColor("#f0c040"))
            font = QFont("Segoe UI", 11, QFont.Bold)
            painter.setFont(font)
            label = self._labels.get(self._learn_target, self._learn_target)
            painter.drawText(
                self.rect().adjusted(12, 10, -12, -8),
                Qt.AlignTop | Qt.AlignHCenter,
                f"Press on your pad: {label}",
            )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        hit = self._hit_test(event.position())
        if hit != self._hover:
            self._hover = hit
            self.update()
        if hit:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(self._labels.get(hit, hit))
        else:
            self.setCursor(Qt.ArrowCursor)
            self.setToolTip("")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        hit = self._hit_test(event.position())
        if hit:
            self.control_clicked.emit(hit)
            self.learn_requested.emit(hit)
            self.set_learn_target(hit)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = None
        self.update()
