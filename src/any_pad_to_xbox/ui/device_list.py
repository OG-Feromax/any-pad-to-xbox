"""Device list widget — friendly names and status badges."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from any_pad_to_xbox.core.evdev_monitor import JoystickInfo
from any_pad_to_xbox.core.profiles import Profile
from any_pad_to_xbox.core.system import is_instance_active
from any_pad_to_xbox.ui import copy as C


class DeviceList(QWidget):
    device_selected = Signal(object)  # JoystickInfo | None
    refresh_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profiles: dict[str, Profile] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        title = QLabel(C.CONNECTED_PADS)
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        header.addWidget(title)
        header.addStretch()
        self.refresh_btn = QPushButton(C.REFRESH)
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_current)
        layout.addWidget(self.list)

        self.empty = QLabel(C.NO_PADS)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color:#8b909a; font-size:12px; padding:8px;")
        self.empty.setVisible(False)
        layout.addWidget(self.empty)

    def set_profiles(self, profiles: dict[str, Profile]) -> None:
        self._profiles = profiles

    def _badge(self, dev: JoystickInfo) -> str:
        profile = self._profiles.get(dev.id_key or "")
        if not profile or not profile.has_mapping():
            return C.BADGE_UNMAPPED
        if profile.enabled and is_instance_active(dev.event_name):
            return C.BADGE_ACTIVE
        return C.BADGE_READY

    def populate(self, devices: list[JoystickInfo]) -> None:
        current_path = None
        cur = self.list.currentItem()
        if cur:
            current_path = cur.data(Qt.UserRole)

        self.list.clear()
        self.empty.setVisible(not devices)
        self.list.setVisible(bool(devices))

        for dev in devices:
            badge = self._badge(dev)
            text = f"{dev.name}\n{badge}"
            item = QListWidgetItem(text)
            item.setToolTip(
                f"{dev.name}\n"
                f"ID: {dev.id_key or 'unknown'}\n"
                f"Device: {dev.event_name}\n"
                f"Path: {dev.path}"
            )
            item.setData(Qt.UserRole, dev.path)
            item.setData(Qt.UserRole + 1, dev)
            self.list.addItem(item)
            if current_path == dev.path:
                self.list.setCurrentItem(item)

        if self.list.count() and not self.list.currentItem():
            self.list.setCurrentRow(0)

    def _on_current(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            self.device_selected.emit(None)
            return
        self.device_selected.emit(current.data(Qt.UserRole + 1))

    def selected_device(self) -> JoystickInfo | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole + 1) if item else None
