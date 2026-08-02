"""Main application window — consumer-friendly Map → Test → Enable flow."""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from any_pad_to_xbox import DIAG_NO_GRAB, USER_CONFIG_DIR
from any_pad_to_xbox.core.evdev_monitor import (
    EvdevMonitor,
    JoystickInfo,
    axis_is_active,
    list_joysticks,
    list_virtual_xbox_pads,
)
from any_pad_to_xbox.core.profiles import (
    Profile,
    empty_profile_for_device,
    ensure_user_profiles,
    save_user_profiles,
)
from any_pad_to_xbox.core.reverse_map import (
    physical_mapped_from_direct,
    xbox_controls_from_virtual,
)
from any_pad_to_xbox.core.system import (
    apply_profiles,
    is_instance_active,
    start_instance,
    stop_instance,
)
from any_pad_to_xbox.ui import copy as C
from any_pad_to_xbox.ui.controller_view import ControllerView
from any_pad_to_xbox.ui.device_list import DeviceList
from any_pad_to_xbox.ui.map_checklist import MapChecklist
from any_pad_to_xbox.ui.system_status import SystemStatusBar


class UiMode(Enum):
    OVERVIEW = auto()
    MAP = auto()
    TEST = auto()
    ADVANCED = auto()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Any Pad to Xbox")
        self.resize(1180, 760)
        self.setStyleSheet(
            "QMainWindow { background: #12141a; }"
            "QLabel { color: #e8eaed; }"
            "QPushButton { padding: 6px 14px; border-radius: 6px; "
            "background:#1e2430; color:#e8eaed; border:1px solid #2a3344; }"
            "QPushButton:hover { background:#2a3344; }"
            "QPushButton:disabled { color:#6a7080; background:#161a22; }"
            "QPushButton#primaryCta { background:#1a5c3a; border-color:#2a8a55; "
            "font-weight:700; padding:8px 18px; }"
            "QPushButton#primaryCta:hover { background:#227a4a; }"
            "QListWidget { background:#161a22; border:1px solid #2a3344; "
            "border-radius:6px; color:#e8eaed; padding:4px; }"
            "QListWidget::item { padding:8px; border-radius:4px; }"
            "QListWidget::item:selected { background:#243044; }"
            "QSpinBox, QTextEdit, QPlainTextEdit { background:#161a22; color:#e8eaed; "
            "border:1px solid #2a3344; border-radius:6px; }"
            "QGroupBox { color:#9aa0aa; font-weight:600; margin-top:8px; }"
        )

        self.profiles: dict[str, Profile] = ensure_user_profiles()
        self.current: JoystickInfo | None = None
        self.monitor = EvdevMonitor(self, coalesce_ms=2, label="PHYS")
        self.virtual_monitor = EvdevMonitor(self, coalesce_ms=2, label="VIRT")
        self._learn_xbox: str | None = None
        self._virtual_path: str | None = None
        self._learn_paused: bool = False
        self._using_reverse: bool = False
        self._mode = UiMode.OVERVIEW
        self._guided_map = False
        self._diag_path = USER_CONFIG_DIR / "diag.log"
        self._bridge_active_cached = False
        self._last_live = ""
        self._last_test_lit = None
        self._overlay_pending = False
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(10)

        self.system_bar = SystemStatusBar()
        self.system_bar.readiness_changed.connect(self._on_system_readiness)
        outer.addWidget(self.system_bar)

        tagline = QLabel(C.TAGLINE)
        tagline.setStyleSheet("color:#9aa0aa; font-size:13px;")
        outer.addWidget(tagline)

        if DIAG_NO_GRAB:
            diag_banner = QLabel(
                "DEV: no-grab diagnostics on. Prefer /tmp/any-pad-bridge.diag for truth."
            )
            diag_banner.setWordWrap(True)
            diag_banner.setStyleSheet(
                "background:#3a2a10; color:#ffd080; border:1px solid #8a6020; "
                "border-radius:6px; padding:8px; font-weight:600;"
            )
            outer.addWidget(diag_banner)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.device_list = DeviceList()
        self.device_list.set_profiles(self.profiles)
        self.device_list.refresh_clicked.connect(self.refresh_devices)
        self.device_list.device_selected.connect(self.select_device)
        left_layout.addWidget(self.device_list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self.header = QLabel(C.SELECT_PAD)
        self.header.setStyleSheet("font-size: 18px; font-weight: 600;")
        right_layout.addWidget(self.header)

        status_row = QHBoxLayout()
        self.badge = QLabel("—")
        self.badge.setStyleSheet(
            "padding:3px 10px; border-radius:10px; background:#1e2430; color:#9aa0aa;"
        )
        status_row.addWidget(self.badge)
        self.virt_label = QLabel(C.VIRTUAL_OFF)
        self.virt_label.setStyleSheet("color:#8b909a;")
        status_row.addWidget(self.virt_label)
        status_row.addStretch()
        right_layout.addLayout(status_row)

        cta_row = QHBoxLayout()
        self.primary_btn = QPushButton(C.START_MAPPING)
        self.primary_btn.setObjectName("primaryCta")
        self.primary_btn.clicked.connect(self._on_primary)
        cta_row.addWidget(self.primary_btn)
        self.remap_btn = QPushButton(C.REMAP)
        self.remap_btn.clicked.connect(self._enter_map_mode)
        cta_row.addWidget(self.remap_btn)
        self.test_btn = QPushButton(C.TEST)
        self.test_btn.clicked.connect(self._enter_test_mode)
        cta_row.addWidget(self.test_btn)
        self.advanced_btn = QPushButton(C.ADVANCED + "…")
        self.advanced_btn.clicked.connect(self._toggle_advanced)
        cta_row.addWidget(self.advanced_btn)
        cta_row.addStretch()
        right_layout.addLayout(cta_row)

        mid = QHBoxLayout()
        self.controller = ControllerView()
        self.controller.learn_requested.connect(self._on_diagram_learn)
        mid.addWidget(self.controller, 3)

        self.checklist = MapChecklist()
        self.checklist.setMaximumWidth(240)
        self.checklist.item_activated.connect(self.start_learn)
        self.checklist.cancel_clicked.connect(self._cancel_map_mode)
        self.checklist.skip_clicked.connect(self._skip_current)
        self.checklist.setVisible(False)
        mid.addWidget(self.checklist, 1)
        right_layout.addLayout(mid, 3)

        # Always-visible live readout (old UI had PHYS/VIRT panels — removing them
        # made "Virtual off" look broken even when the pad was reading fine).
        self.live_input = QLabel("Live: —")
        self.live_input.setWordWrap(True)
        self.live_input.setMinimumHeight(36)
        self.live_input.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.live_input.setStyleSheet(
            "background:#0d1812; border:1px solid #1e5f3a; border-radius:6px; "
            "padding:8px; color:#d2ffe6; font-family: monospace; font-size: 12px;"
        )
        right_layout.addWidget(self.live_input)

        self.tip = QLabel(C.TIP_IDLE)
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("color:#9aa0aa; font-size:12px; padding:4px 0;")
        right_layout.addWidget(self.tip)

        # Advanced panel (hidden by default)
        self.advanced_panel = QFrame()
        self.advanced_panel.setVisible(False)
        self.advanced_panel.setStyleSheet(
            "QFrame { background:#161a22; border:1px solid #2a3344; border-radius:8px; }"
        )
        adv = QVBoxLayout(self.advanced_panel)
        adv.setContentsMargins(12, 10, 12, 10)

        slot_row = QHBoxLayout()
        slot_row.addWidget(QLabel(C.SLOT_LABEL))
        self.slot_spin = QSpinBox()
        self.slot_spin.setRange(1, 4)
        self.slot_spin.valueChanged.connect(self._on_slot_changed)
        slot_row.addWidget(self.slot_spin)
        slot_row.addStretch()
        self.clear_btn = QPushButton(C.CLEAR_MAPPING)
        self.clear_btn.clicked.connect(self.clear_mapping)
        slot_row.addWidget(self.clear_btn)
        adv.addLayout(slot_row)

        adv.addWidget(QLabel(C.READABLE_MAP))
        self.map_view = QTextEdit()
        self.map_view.setReadOnly(True)
        self.map_view.setMaximumHeight(100)
        adv.addWidget(self.map_view)

        what = QLabel(C.WHAT_INSTALLED + ": " + C.WHAT_INSTALLED_BODY)
        what.setWordWrap(True)
        what.setStyleSheet("color:#8b909a; font-size:11px;")
        adv.addWidget(what)

        self.diag_box = QGroupBox(C.DIAGNOSTICS)
        self.diag_box.setCheckable(True)
        self.diag_box.setChecked(False)
        self.diag_box.toggled.connect(self._on_diag_toggled)
        diag_layout = QVBoxLayout(self.diag_box)
        self.diag_log = QPlainTextEdit()
        self.diag_log.setReadOnly(True)
        self.diag_log.setMaximumBlockCount(2000)
        self.diag_log.setMaximumHeight(120)
        self.diag_log.setVisible(False)
        self.diag_log.setStyleSheet("font-family: monospace; font-size: 11px;")
        diag_layout.addWidget(self.diag_log)
        clear_log = QPushButton("Clear log")
        clear_log.clicked.connect(self._clear_diag_log)
        clear_log.setVisible(False)
        self._clear_log_btn = clear_log
        diag_layout.addWidget(clear_log)
        adv.addWidget(self.diag_box)

        right_layout.addWidget(self.advanced_panel)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self.monitor.button_down.connect(self._on_phys_button_down)
        self.monitor.axis_peak.connect(self._on_phys_axis_peak)
        self.monitor.diag_event.connect(self._on_diag_line)
        self.monitor.error.connect(lambda m: self.tip.setText(f"Input error: {m}"))
        self.monitor.disconnected.connect(self._on_disconnect)
        self.virtual_monitor.diag_event.connect(self._on_diag_line)
        # Event-driven paint (jstest-style): worker thread → queued slot on GUI.
        self.monitor.state_changed.connect(
            self._request_overlay_refresh, Qt.ConnectionType.QueuedConnection
        )
        self.virtual_monitor.state_changed.connect(
            self._request_overlay_refresh, Qt.ConnectionType.QueuedConnection
        )

        # Safety net only (sticks / missed edges). Hot path is state_changed above.
        self._ui_poll = QTimer(self)
        self._ui_poll.setTimerType(Qt.CoarseTimer)
        self._ui_poll.timeout.connect(self._request_overlay_refresh)
        self._ui_poll.start(33)
        self.controller.set_release_hold(0.0)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_devices)
        self._refresh_timer.start(5000)

        self._virt_attach_timer = QTimer(self)
        self._virt_attach_timer.timeout.connect(self._on_slow_tick)
        self._virt_attach_timer.start(1000)

        self.refresh_devices()
        self._set_detail_enabled(False)
        self._update_cta()

    def _on_slow_tick(self) -> None:
        """1 Hz: systemctl / virt attach — never do this in the 4 ms paint poll."""
        self._refresh_bridge_cache()
        self._try_attach_virtual()

    def _refresh_bridge_cache(self) -> None:
        if not self.current:
            self._bridge_active_cached = False
            return
        self._bridge_active_cached = is_instance_active(self.current.event_name)

    # --- system / enable gating -------------------------------------------------

    def _on_system_readiness(self, ready: bool) -> None:
        self._update_cta()
        if not ready:
            self.tip.setText(C.SETUP_FIRST)

    def _system_ok(self) -> bool:
        return self.system_bar.is_ready()

    # --- device list ------------------------------------------------------------

    def _set_detail_enabled(self, on: bool) -> None:
        for w in (
            self.primary_btn,
            self.remap_btn,
            self.test_btn,
            self.advanced_btn,
            self.controller,
            self.slot_spin,
            self.clear_btn,
        ):
            w.setEnabled(on and (self._system_ok() or w is self.advanced_btn))
        # Always allow viewing advanced when a device is selected
        self.advanced_btn.setEnabled(on)
        if on and not self._system_ok():
            self.primary_btn.setEnabled(False)
            self.remap_btn.setEnabled(False)
            self.test_btn.setEnabled(False)

    def refresh_devices(self) -> None:
        devices = list_joysticks(include_virtual=False)
        self.device_list.set_profiles(self.profiles)
        self.device_list.populate(devices)
        if not devices:
            self.tip.setText(C.NO_PADS)
        self._try_attach_virtual()
        self._update_cta()

    def select_device(self, device: JoystickInfo | None) -> None:
        if self._learn_paused:
            self._end_learn_session(restart=True)
        self.monitor.stop()
        self.controller.clear_activity()
        self._learn_xbox = None
        self.controller.set_learn_target(None)
        self.current = device
        if not device:
            self.header.setText(C.SELECT_PAD)
            self._set_detail_enabled(False)
            self._detach_virtual()
            self._mode = UiMode.OVERVIEW
            self.checklist.setVisible(False)
            self._update_cta()
            return
        self._set_detail_enabled(True)
        profile = self._ensure_profile(device)
        self.header.setText(device.name)
        self.slot_spin.blockSignals(True)
        self.slot_spin.setValue(profile.slot)
        self.slot_spin.blockSignals(False)
        self._update_map_view(profile)
        self.monitor.start(device.path)
        self._refresh_bridge_cache()
        self._try_attach_virtual()
        self._update_cta()

    def _pad_badge(self) -> str:
        profile = self._current_profile()
        if not self.current or not profile or not profile.has_mapping():
            return C.BADGE_UNMAPPED
        if profile.enabled and is_instance_active(self.current.event_name):
            return C.BADGE_ACTIVE
        return C.BADGE_READY

    def _update_cta(self) -> None:
        badge = self._pad_badge() if self.current else "—"
        self.badge.setText(badge)
        colors = {
            C.BADGE_UNMAPPED: ("#3a2a10", "#f0c040"),
            C.BADGE_READY: ("#1a3040", "#5ab0ff"),
            C.BADGE_ACTIVE: ("#13251a", "#3dd68c"),
        }
        bg, fg = colors.get(badge, ("#1e2430", "#9aa0aa"))
        self.badge.setStyleSheet(
            f"padding:3px 10px; border-radius:10px; background:{bg}; color:{fg}; font-weight:600;"
        )

        if not self.current:
            self.primary_btn.setText(C.START_MAPPING)
            self.primary_btn.setEnabled(False)
            self.tip.setText(C.TIP_IDLE if self._system_ok() else C.SETUP_FIRST)
            return

        if not self._system_ok():
            self.primary_btn.setText(C.START_MAPPING)
            self.primary_btn.setEnabled(False)
            self.tip.setText(C.SETUP_FIRST)
            return

        if self._mode == UiMode.MAP:
            self.primary_btn.setText(C.CANCEL)
            self.primary_btn.setEnabled(True)
            return

        if badge == C.BADGE_UNMAPPED:
            self.primary_btn.setText(C.START_MAPPING)
            self.tip.setText(C.TIP_UNMAPPED)
        elif badge == C.BADGE_READY:
            self.primary_btn.setText(C.ENABLE)
            self.tip.setText(C.TIP_READY)
        else:
            self.primary_btn.setText(C.DISABLE)
            self.tip.setText(C.TIP_ACTIVE if self._mode != UiMode.TEST else C.TIP_TEST)
        self.primary_btn.setEnabled(True)

    def _on_primary(self) -> None:
        if self._mode == UiMode.MAP:
            self._cancel_map_mode()
            return
        badge = self._pad_badge()
        if badge == C.BADGE_UNMAPPED:
            self._enter_map_mode()
        elif badge == C.BADGE_READY:
            self.enable_current()
        elif badge == C.BADGE_ACTIVE:
            self.disable_current()

    # --- modes ------------------------------------------------------------------

    def _sync_diagram_feel(self) -> None:
        # Test / overview live: instant off like jstest. Map: tiny hold so mash
        # recovery pulses don't flicker the amber learning UX.
        if self._mode == UiMode.MAP:
            self.controller.set_release_hold(0.04)
        else:
            self.controller.set_release_hold(0.0)

    def _enter_map_mode(self) -> None:
        if not self.current or not self._system_ok():
            return
        self._mode = UiMode.MAP
        self._sync_diagram_feel()
        self._guided_map = True
        self.checklist.setVisible(True)
        self.advanced_panel.setVisible(False)
        if not self._ensure_learn_access():
            self._mode = UiMode.OVERVIEW
            self._guided_map = False
            self.checklist.setVisible(False)
            self._update_cta()
            return
        profile = self._current_profile()
        nxt = self.checklist.next_unmapped(profile)
        self.checklist.rebuild(profile, nxt)
        self._update_cta()
        if nxt:
            self.start_learn(nxt)
        else:
            self.tip.setText(C.TIP_MAP_DONE)

    def _cancel_map_mode(self) -> None:
        self._guided_map = False
        self._mode = UiMode.OVERVIEW
        self._sync_diagram_feel()
        self.checklist.setVisible(False)
        self._learn_xbox = None
        self.controller.set_learn_target(None)
        # Leave virtual pad off — user clicks Enable (avoids pkexec per button).
        if self._learn_paused:
            self._learn_paused = False
        self._update_cta()

    def _skip_current(self) -> None:
        profile = self._current_profile()
        after = self._learn_xbox
        self._learn_xbox = None
        self.controller.set_learn_target(None)
        nxt = self.checklist.next_unmapped(profile, after=after)
        self.checklist.rebuild(profile, nxt)
        if nxt:
            self.start_learn(nxt)
        else:
            self.tip.setText(C.TIP_MAP_DONE)

    def _enter_test_mode(self) -> None:
        if not self.current or not self._system_ok():
            return
        if self._mode == UiMode.MAP:
            self._cancel_map_mode()
        # Never leave a stale learn-pause blocking virtual highlights
        self._learn_paused = False
        self._mode = UiMode.TEST
        self._sync_diagram_feel()
        self.checklist.setVisible(False)
        profile = self._current_profile()
        active = (
            profile
            and profile.enabled
            and self.current
            and is_instance_active(self.current.event_name)
        )
        if not active:
            self.tip.setText(C.TIP_TEST_OFF)
            reply = QMessageBox.question(
                self,
                C.ENABLE,
                C.TIP_TEST_OFF + "\n\nEnable now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.enable_current()
            else:
                self._mode = UiMode.OVERVIEW
                self._update_cta()
                return
        # Force a fresh attach so Test isn't staring at a dead virt fd
        self._detach_virtual()
        self._try_attach_virtual()
        if not self._virtual_path:
            self.tip.setText(
                "Enabled, but no virtual Xbox pad showed up yet — wait a second or click Enable again."
            )
        else:
            self.tip.setText(C.TIP_TEST)
        self._update_cta()
        QTimer.singleShot(800, self._try_attach_virtual)

    def _toggle_advanced(self) -> None:
        show = not self.advanced_panel.isVisible()
        self.advanced_panel.setVisible(show)
        if show:
            self._mode = UiMode.ADVANCED
            profile = self._current_profile()
            if profile:
                self._update_map_view(profile)
        elif self._mode == UiMode.ADVANCED:
            self._mode = UiMode.OVERVIEW
        self._update_cta()

    def _on_diagram_learn(self, xbox_name: str) -> None:
        if self._mode != UiMode.MAP:
            if not self.current or not self._system_ok():
                self.controller.set_learn_target(None)
                return
            self._mode = UiMode.MAP
            self._guided_map = True
            self.checklist.setVisible(True)
            if not self._ensure_learn_access():
                self._mode = UiMode.OVERVIEW
                self._guided_map = False
                self.checklist.setVisible(False)
                self.controller.set_learn_target(None)
                self._update_cta()
                return
        self.start_learn(xbox_name)

    # --- virtual attach ---------------------------------------------------------

    def _detach_virtual(self) -> None:
        self.virtual_monitor.stop()
        self._virtual_path = None
        self._using_reverse = False
        self.virt_label.setText(C.VIRTUAL_OFF)
        self.virt_label.setStyleSheet("color: #8b909a;")
        self.controller.set_virtual_active(set(), {})

    def _try_attach_virtual(self) -> None:
        if self._learn_paused:
            return
        virtuals = list_virtual_xbox_pads()
        if not virtuals:
            if self._virtual_path:
                self._detach_virtual()
            else:
                self.virt_label.setText(C.VIRTUAL_OFF)
                self.virt_label.setStyleSheet("color: #8b909a;")
            self._update_cta()
            return

        target = virtuals[-1]
        if self._virtual_path == target.path:
            self._update_cta()
            return
        self.virtual_monitor.stop()
        self._virtual_path = target.path
        self.virtual_monitor.start(target.path)
        self._using_reverse = False
        self.virt_label.setText(C.VIRTUAL_ON)
        self.virt_label.setStyleSheet("color: #3dd68c;")
        self._update_cta()

    # --- profiles ---------------------------------------------------------------

    def _ensure_profile(self, device: JoystickInfo) -> Profile:
        key = device.id_key or f"unknown:{device.event_name}"
        if key not in self.profiles:
            self.profiles[key] = empty_profile_for_device(
                device.vendor or "0000",
                device.product or "0000",
                device.name,
            )
            if not device.vendor:
                self.profiles[key].key = key
        return self.profiles[key]

    def _current_profile(self) -> Profile | None:
        if not self.current:
            return None
        if self.current.id_key:
            return self.profiles.get(self.current.id_key)
        return self.profiles.get(f"unknown:{self.current.event_name}")

    def _update_map_view(self, profile: Profile) -> None:
        lines: list[str] = []
        for code, xbox in sorted(profile.evdev_keymap.items(), key=lambda x: x[1]):
            lines.append(f"{C.xbox_label(xbox)}  ←  {C.friendly_code(code)}")
        for code, xbox in sorted(profile.evdev_absmap.items(), key=lambda x: x[1]):
            lines.append(f"{C.xbox_label(xbox)}  ←  {C.friendly_code(code)}")
        self.map_view.setPlainText("\n".join(lines) if lines else C.EMPTY_MAP)

    # --- learn ------------------------------------------------------------------

    def _ensure_learn_access(self) -> bool:
        """Pause Active virtual pad once for the whole remap session (one password)."""
        if not self.current:
            return False
        if DIAG_NO_GRAB or self._learn_paused:
            return True
        if not is_instance_active(self.current.event_name):
            return True
        reply = QMessageBox.question(
            self,
            C.PAUSE_TITLE,
            C.PAUSE_BODY,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return False
        self._detach_virtual()
        ok, msg = stop_instance(self.current.event_name)
        if not ok:
            QMessageBox.critical(self, C.PAUSE_FAIL, msg)
            return False
        self._learn_paused = True
        profile = self._current_profile()
        if profile:
            profile.enabled = False
            save_user_profiles(self.profiles)
        self.monitor.stop()
        QTimer.singleShot(
            300,
            lambda: self.monitor.start(self.current.path) if self.current else None,
        )
        return True

    def start_learn(self, xbox_name: str) -> None:
        if not self.current or not self._system_ok():
            return
        if not self._ensure_learn_access():
            self.controller.set_learn_target(None)
            return

        self._learn_xbox = xbox_name
        self.controller.set_learn_target(xbox_name)
        profile = self._current_profile()
        if self._mode == UiMode.MAP:
            self.checklist.rebuild(profile, xbox_name)
        label = C.xbox_label(xbox_name)
        if xbox_name in C.AXIS_TARGETS:
            self.tip.setText(C.PRESS_AXIS.format(label=label))
        else:
            self.tip.setText(C.PRESS_FOR.format(label=label))

    def _end_learn_session(self, *, restart: bool) -> None:
        """Clear learn target. Virtual pad stays off during Map (no pkexec per button)."""
        self._learn_xbox = None
        self.controller.set_learn_target(None)
        if not self._learn_paused:
            return
        if self._mode == UiMode.MAP or self._guided_map:
            return
        self._learn_paused = False
        if restart and self.current:
            ok, msg = start_instance(self.current.event_name)
            if ok:
                profile = self._current_profile()
                if profile:
                    profile.enabled = True
                    save_user_profiles(self.profiles)
                QTimer.singleShot(700, self._try_attach_virtual)
            else:
                self.tip.setText(msg)

    def _after_map_success(self, xbox: str) -> None:
        profile = self._current_profile()
        label = C.xbox_label(xbox)
        # Clear target only — keep pause for next button (no restart/pkexec).
        self._learn_xbox = None
        self.controller.set_learn_target(None)
        if profile:
            self._update_map_view(profile)
        self.device_list.set_profiles(self.profiles)
        self.refresh_devices()

        if self._guided_map and self._mode == UiMode.MAP:
            self.tip.setText(C.MAPPED_OK_MORE.format(label=label))
            nxt = self.checklist.next_unmapped(profile, after=xbox)
            self.checklist.rebuild(profile, nxt)
            if nxt:
                QTimer.singleShot(200, lambda: self.start_learn(nxt))
            elif self.checklist.essentials_done(profile):
                self._finish_remap_offer_enable(label)
            else:
                self._update_cta()
        else:
            # Single-button remap from diagram
            self._mode = UiMode.OVERVIEW
            self._guided_map = False
            self.checklist.setVisible(False)
            self._learn_paused = False
            self.tip.setText(C.MAPPED_OK.format(label=label))
            self._update_cta()
            self._offer_enable_after_remap(label)

    def _finish_remap_offer_enable(self, label: str) -> None:
        self._guided_map = False
        self.checklist.setVisible(False)
        self._mode = UiMode.OVERVIEW
        self._learn_paused = False
        self._update_cta()
        self._offer_enable_after_remap(label)

    def _offer_enable_after_remap(self, label: str) -> None:
        reply = QMessageBox.question(
            self,
            C.APPLY_REMAP_TITLE,
            C.APPLY_REMAP_BODY.format(label=label),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self.enable_current()
        else:
            self.tip.setText(C.TIP_READY)

    def _on_phys_button_down(self, code: str) -> None:
        if not self._learn_xbox:
            # Live feedback while mapping even before assignment lands
            if self._mode == UiMode.MAP:
                self.tip.setText(f"Heard: {C.friendly_code(code)}")
            return
        if self._using_reverse and not self._learn_paused:
            return
        profile = self._current_profile()
        if not profile:
            return
        xbox = self._learn_xbox
        if xbox in C.AXIS_TARGETS and xbox not in {"lt", "rt"}:
            self.tip.setText(C.MAP_AXIS_HINT + f" (heard {C.friendly_code(code)})")
            return
        # lt/rt can be buttons on cheap pads
        profile.evdev_keymap = {
            k: v for k, v in profile.evdev_keymap.items() if v != xbox and k != code
        }
        profile.evdev_keymap[code] = xbox
        if xbox in profile.evdev_absmap.values():
            profile.evdev_absmap = {k: v for k, v in profile.evdev_absmap.items() if v != xbox}
        save_user_profiles(self.profiles)
        self._after_map_success(xbox)

    def _on_phys_axis_peak(self, code: str, norm: float) -> None:
        if not self._learn_xbox:
            return
        if self._using_reverse and not self._learn_paused:
            return
        xbox = self._learn_xbox
        if xbox in C.BUTTON_TARGETS:
            return
        profile = self._current_profile()
        if not profile:
            return
        profile.evdev_absmap = {
            k: v for k, v in profile.evdev_absmap.items() if v != xbox and k != code
        }
        profile.evdev_absmap[code] = xbox
        if xbox in {"y1", "y2"} and norm < -0.85:
            inv = f"-{xbox.upper()}={xbox.upper()}"
            if inv not in profile.axismap:
                profile.axismap.append(inv)
        save_user_profiles(self.profiles)
        self._after_map_success(xbox)

    def _on_disconnect(self) -> None:
        if self._learn_paused:
            return
        self.tip.setText(C.DEVICE_GONE)
        self.refresh_devices()

    # --- overlays ---------------------------------------------------------------

    def _request_overlay_refresh(self) -> None:
        """Coalesce bursty state_changed + poll into one GUI-loop paint."""
        if self._overlay_pending:
            return
        self._overlay_pending = True
        QTimer.singleShot(0, self._flush_overlays)

    def _flush_overlays(self) -> None:
        self._overlay_pending = False
        self._refresh_overlays()

    def _fmt_live(
        self,
        *,
        virt_on: bool,
        v_active: set[str],
        p_active: set[str],
        phys_btns: dict[str, bool],
        phys_axes: dict[str, float],
        can_read_phys: bool,
    ) -> str:
        parts: list[str] = []
        if virt_on:
            parts.append(
                "VIRT " + (" · ".join(sorted(v_active)) if v_active else "—")
            )
        if can_read_phys:
            if p_active:
                parts.append("PAD " + " · ".join(sorted(p_active)))
            else:
                raw = [C.friendly_code(k) for k, v in phys_btns.items() if v]
                raw += [
                    f"{C.friendly_code(k)}:{val:+.2f}"
                    for k, val in phys_axes.items()
                    if axis_is_active(k, val)
                ]
                parts.append("PAD " + (" · ".join(raw) if raw else "—"))
        elif virt_on:
            parts.append("PAD (exclusive — only virtual is live)")
        else:
            parts.append("PAD —")
        return "Live:  " + "   |   ".join(parts)

    def _refresh_overlays(self) -> None:
        if not self.current and not self._virtual_path:
            return
        virt_btns, virt_axes = self.virtual_monitor.snapshot()
        phys_btns, phys_axes = self.monitor.snapshot()
        profile = self._current_profile()

        show_virt = bool(self._virtual_path and not self._learn_paused)
        v_active: set[str] = set()
        v_axes: dict[str, float] = {}
        if show_virt:
            v_active, v_axes = xbox_controls_from_virtual(virt_btns, virt_axes)

        # Cached flag only — never systemctl on this hot path (was ~250 calls/s).
        bridge_holds_pad = (
            not DIAG_NO_GRAB
            and not self._learn_paused
            and self._bridge_active_cached
        )
        can_read_phys = not bridge_holds_pad

        p_active: set[str] = set()
        p_axes: dict[str, float] = {}
        if can_read_phys and profile and profile.has_mapping():
            p_active, p_axes = physical_mapped_from_direct(profile, phys_btns, phys_axes)

        green = set(v_active)
        green_axes = dict(v_axes)
        if show_virt:
            # Green stays lit for the whole hold: virt state OR mapped pad (when we
            # can read it). Alias mismatches / missed virt edges used to blank the
            # diagram while the button was still down.
            if can_read_phys:
                green |= p_active
                for k, val in p_axes.items():
                    green_axes.setdefault(k, val)
            self.controller.apply_layers(
                physical=p_active if DIAG_NO_GRAB else set(),
                virtual=green,
                physical_axes=p_axes if DIAG_NO_GRAB else {},
                virtual_axes=green_axes,
            )
        else:
            # Virtual off: paint mapped presses on the GREEN layer (same as before
            # users expected the diagram to light). Blue-dashed-only felt "broken".
            green = set(p_active)
            green_axes = dict(p_axes)
            self.controller.apply_layers(
                physical=set(),
                virtual=green,
                physical_axes={},
                virtual_axes=green_axes,
            )

        live = self._fmt_live(
            virt_on=show_virt,
            v_active=green if show_virt else v_active,
            p_active=p_active,
            phys_btns=phys_btns,
            phys_axes=phys_axes,
            can_read_phys=can_read_phys,
        )
        if live != self._last_live:
            self._last_live = live
            self.live_input.setText(live)

        if self._mode == UiMode.TEST:
            lit = sorted(green)
            key = ",".join(lit)
            if key != getattr(self, "_last_test_lit", None):
                self._last_test_lit = key
                if key:
                    self.tip.setText(f"Pressed: {key}")
                elif self._virtual_path:
                    self.tip.setText(C.TIP_TEST)
                else:
                    self.tip.setText(
                        "Virtual off — diagram uses your mapping from the pad directly. "
                        "Watch Live: above."
                    )

    # --- enable / disable / clear -----------------------------------------------

    def _on_slot_changed(self, value: int) -> None:
        profile = self._current_profile()
        if profile:
            profile.slot = value
            save_user_profiles(self.profiles)

    def clear_mapping(self) -> None:
        profile = self._current_profile()
        if not profile:
            return
        reply = QMessageBox.question(
            self,
            C.CLEAR_CONFIRM_TITLE,
            C.CLEAR_CONFIRM,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        profile.evdev_keymap.clear()
        profile.evdev_absmap.clear()
        profile.axismap.clear()
        profile.extra_opts.clear()
        profile.enabled = False
        save_user_profiles(self.profiles)
        self._update_map_view(profile)
        self.tip.setText(C.CLEARED)
        self.refresh_devices()
        self._update_cta()

    def enable_current(self) -> None:
        if self._learn_paused:
            self._learn_paused = False
        profile = self._current_profile()
        if not profile or not self.current:
            return
        if not self.current.id_key:
            QMessageBox.warning(self, C.ENABLE, C.ENABLE_NO_ID)
            return
        if not profile.has_mapping():
            QMessageBox.warning(self, C.ENABLE, C.ENABLE_NO_MAP)
            return
        profile.enabled = True
        save_user_profiles(self.profiles)
        ok, msg = apply_profiles(self.profiles, start_event=self.current.event_name)
        if ok:
            self.tip.setText(C.ENABLE_OK)
            self._bridge_active_cached = True
            QTimer.singleShot(700, self._try_attach_virtual)
        else:
            QMessageBox.critical(self, C.ENABLE_FAIL, msg)
            self.tip.setText(msg)
        self.refresh_devices()
        self._update_cta()

    def disable_current(self) -> None:
        if not self.current:
            return
        if self._learn_paused:
            self._learn_paused = False
        profile = self._current_profile()
        if profile:
            profile.enabled = False
            save_user_profiles(self.profiles)
        # One pkexec: write disabled profile + stop the unit
        ok, msg = apply_profiles(
            self.profiles,
            start_event=None,
            stop_event=self.current.event_name,
        )
        self._bridge_active_cached = False
        self._detach_virtual()
        self.tip.setText(C.DISABLE_OK if ok else msg)
        self.refresh_devices()
        self._update_cta()

    # --- diagnostics ------------------------------------------------------------

    def _on_diag_toggled(self, on: bool) -> None:
        self.diag_log.setVisible(on)
        self._clear_log_btn.setVisible(on)

    def _on_diag_line(self, line: str) -> None:
        if not self.diag_box.isChecked():
            return
        self.diag_log.appendPlainText(line)
        try:
            with self._diag_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def _clear_diag_log(self) -> None:
        self.diag_log.clear()
        try:
            self._diag_path.write_text("", encoding="utf-8")
        except OSError:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._learn_paused and self.current:
            try:
                start_instance(self.current.event_name)
            except Exception:
                pass
        self.monitor.stop()
        self.virtual_monitor.stop()
        self._ui_poll.stop()
        self._refresh_timer.stop()
        self._virt_attach_timer.stop()
        super().closeEvent(event)
