"""Guided mapping checklist (Steam Input–style essentials)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from any_pad_to_xbox.core.profiles import Profile
from any_pad_to_xbox.ui import copy as C


class MapChecklist(QWidget):
    """Checklist of essential Xbox controls; click item to learn that control."""

    item_activated = Signal(str)  # xbox id
    cancel_clicked = Signal()
    skip_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(C.MAP_TITLE)
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(title)

        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.prompt.setStyleSheet("color:#f0c040; font-weight:600;")
        layout.addWidget(self.prompt)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_click)
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.skip_btn = QPushButton(C.SKIP)
        self.skip_btn.clicked.connect(self.skip_clicked.emit)
        row.addWidget(self.skip_btn)
        self.cancel_btn = QPushButton(C.CANCEL)
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)

        self._current: str | None = None
        self._order = [k for k, _ in C.ESSENTIALS]

    def mapped_set(self, profile: Profile | None) -> set[str]:
        if not profile:
            return set()
        return set(profile.evdev_keymap.values()) | set(profile.evdev_absmap.values())

    def rebuild(self, profile: Profile | None, current: str | None = None) -> None:
        mapped = self.mapped_set(profile)
        self.list.clear()
        self._current = current
        for key, label in C.ESSENTIALS:
            done = key in mapped
            mark = "✓" if done else ("●" if key == current else "○")
            text = f"{mark}  {label}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, key)
            if done:
                item.setForeground(QColor("#6a7080"))
            elif key == current:
                item.setForeground(QColor("#f0c040"))
            self.list.addItem(item)
            if key == current:
                self.list.setCurrentItem(item)

        if current:
            label = C.xbox_label(current)
            if current in C.AXIS_TARGETS:
                self.prompt.setText(C.PRESS_AXIS.format(label=label))
            else:
                self.prompt.setText(C.PRESS_FOR.format(label=label))
        else:
            self.prompt.setText("Pick a control below, or wait for auto-advance.")

    def next_unmapped(self, profile: Profile | None, after: str | None = None) -> str | None:
        mapped = self.mapped_set(profile)
        start = 0
        if after and after in self._order:
            start = self._order.index(after) + 1
        for key in self._order[start:] + self._order[:start]:
            if key not in mapped:
                return key
        return None

    def essentials_done(self, profile: Profile | None) -> bool:
        """Minimum: all face buttons + at least one shoulder or d-pad direction."""
        mapped = self.mapped_set(profile)
        faces = {"a", "b", "x", "y"}
        if not faces.issubset(mapped):
            return False
        shoulders = {"lb", "rb", "lt", "rt", "du", "dd", "dl", "dr"}
        return bool(mapped & shoulders)

    def _on_click(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole)
        if key:
            self.item_activated.emit(key)
