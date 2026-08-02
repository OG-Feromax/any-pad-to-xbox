"""Persistent system traffic-light bar (install / ready / attention)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from any_pad_to_xbox.core.system import SystemStatus, check_system, install_integration
from any_pad_to_xbox.ui import copy as C


def _level(status: SystemStatus) -> str:
    """Return 'green' | 'yellow' | 'red'."""
    if not status.integration_installed:
        return "red"
    if not status.uinput_ok:
        return "yellow"
    if not status.in_input_group:
        return "yellow"
    return "green"


_STYLES = {
    "green": {
        "bar": "background:#13251a; border:1px solid #2a6b45; border-radius:8px;",
        "dot": "background:#3dd68c; border-radius:7px;",
        "title": "color:#b8f0d0; font-weight:700;",
        "body": "color:#9ab8a8;",
    },
    "yellow": {
        "bar": "background:#2a2410; border:1px solid #8a7020; border-radius:8px;",
        "dot": "background:#f0c040; border-radius:7px;",
        "title": "color:#ffe08a; font-weight:700;",
        "body": "color:#d0c090;",
    },
    "red": {
        "bar": "background:#2a1414; border:1px solid #8a3030; border-radius:8px;",
        "dot": "background:#f06060; border-radius:7px;",
        "title": "color:#ffb0b0; font-weight:700;",
        "body": "color:#d09090;",
    },
}


class SystemStatusBar(QWidget):
    """Always-visible green/yellow/red indicator for system prep."""

    changed = Signal()
    readiness_changed = Signal(bool)  # True when Map/Enable allowed (not red)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("systemStatusBar")
        self._expanded = True
        self._level = "red"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.frame = QFrame()
        self.frame.setObjectName("sysFrame")
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(10, 8, 10, 8)

        # Compact header row (always visible)
        head = QHBoxLayout()
        self.dot = QLabel()
        self.dot.setFixedSize(14, 14)
        head.addWidget(self.dot)

        self.title = QLabel()
        head.addWidget(self.title)

        head.addStretch()

        self.toggle_btn = QToolButton()
        self.toggle_btn.setText("▾")
        self.toggle_btn.setAutoRaise(True)
        self.toggle_btn.clicked.connect(self._toggle_expand)
        head.addWidget(self.toggle_btn)

        self.recheck_btn = QPushButton(C.RECHECK)
        self.recheck_btn.setFlat(True)
        self.recheck_btn.clicked.connect(self.refresh)
        head.addWidget(self.recheck_btn)

        self.install_btn = QPushButton(C.INSTALL)
        self.install_btn.setStyleSheet("font-weight: 600; padding: 4px 12px;")
        self.install_btn.clicked.connect(self._install)
        head.addWidget(self.install_btn)

        frame_layout.addLayout(head)

        # Expandable details
        self.detail = QWidget()
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(22, 6, 4, 2)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        detail_layout.addWidget(self.summary)

        self.check_component = QLabel()
        self.check_uinput = QLabel()
        self.check_input = QLabel()
        for lab in (self.check_component, self.check_uinput, self.check_input):
            detail_layout.addWidget(lab)

        why_row = QHBoxLayout()
        self.why_btn = QToolButton()
        self.why_btn.setText(C.WHY_PASSWORD)
        self.why_btn.setAutoRaise(True)
        self.why_btn.setCheckable(True)
        self.why_btn.toggled.connect(self._toggle_why)
        why_row.addWidget(self.why_btn)
        why_row.addStretch()
        detail_layout.addLayout(why_row)

        self.why_body = QLabel(C.WHY_PASSWORD_BODY)
        self.why_body.setWordWrap(True)
        self.why_body.setVisible(False)
        self.why_body.setStyleSheet("color:#9aa0aa; font-size:11px; padding-left:4px;")
        detail_layout.addWidget(self.why_body)

        frame_layout.addWidget(self.detail)
        root.addWidget(self.frame)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.refresh()

    def is_ready(self) -> bool:
        """True when not blocking (green or yellow). Red blocks Map/Enable."""
        return self._level != "red"

    def status(self) -> SystemStatus:
        return check_system()

    def refresh(self) -> None:
        status = check_system()
        level = _level(status)
        self._level = level
        style = _STYLES[level]
        self.frame.setStyleSheet(f"#sysFrame {{ {style['bar']} }}")
        self.dot.setStyleSheet(style["dot"])
        self.title.setStyleSheet(style["title"])
        self.summary.setStyleSheet(style["body"])

        if level == "green":
            self.title.setText(C.SYSTEM_READY)
            self.summary.setText("Your system can create virtual Xbox controllers.")
            self.install_btn.setVisible(False)
            self._expanded = False
        elif level == "yellow":
            bits = []
            if not status.uinput_ok:
                bits.append("Virtual controller support is missing (uinput).")
            if not status.in_input_group:
                bits.append("Your user is not in the input group (optional, recommended).")
            self.title.setText(C.SYSTEM_ATTENTION)
            self.summary.setText(" ".join(bits) or "Something needs attention.")
            self.install_btn.setVisible(not status.integration_installed)
            self._expanded = True
        else:
            self.title.setText(C.SYSTEM_REQUIRED)
            self.summary.setText(
                "We need to install a system component (asks for your password once)."
            )
            self.install_btn.setVisible(True)
            self.install_btn.setEnabled(True)
            self._expanded = True

        def tick(ok: bool, label: str) -> str:
            mark = "●" if ok else "○"
            color = "#3dd68c" if ok else ("#f0c040" if level == "yellow" else "#f06060")
            return f'<span style="color:{color}">{mark}</span>  {label}'

        self.check_component.setText(
            tick(status.integration_installed, C.CHECK_COMPONENT)
        )
        self.check_uinput.setText(tick(status.uinput_ok, C.CHECK_UINPUT))
        self.check_input.setText(tick(status.in_input_group, C.CHECK_INPUT_GROUP))

        self.detail.setVisible(self._expanded)
        self.toggle_btn.setText("▴" if self._expanded else "▾")
        self.changed.emit()
        self.readiness_changed.emit(self.is_ready())

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self.detail.setVisible(self._expanded)
        self.toggle_btn.setText("▴" if self._expanded else "▾")

    def _toggle_why(self, on: bool) -> None:
        self.why_body.setVisible(on)

    def _install(self) -> None:
        self.install_btn.setEnabled(False)
        self.summary.setText(C.INSTALLING)
        ok, msg = install_integration()
        if ok:
            self.refresh()
        else:
            self.summary.setText(C.INSTALL_CANCELLED if "cancel" in msg.lower() or not msg else msg)
            self.install_btn.setEnabled(True)
            self.refresh()
