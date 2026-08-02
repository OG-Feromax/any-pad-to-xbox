"""Evdev device discovery and live monitoring."""

from __future__ import annotations

import os
import select
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal

try:
    import evdev
    from evdev import ecodes
except ImportError:  # pragma: no cover
    evdev = None
    ecodes = None

BUS_VIRTUAL = 0x06


@dataclass
class JoystickInfo:
    path: str
    name: str
    vendor: str | None
    product: str | None
    phys: str | None = None
    uniq: str | None = None
    event_name: str = ""
    bustype: int = 0
    is_virtual: bool = False
    buttons: list[str] = field(default_factory=list)
    axes: list[str] = field(default_factory=list)

    @property
    def id_key(self) -> str | None:
        if self.vendor and self.product:
            return f"{self.vendor}:{self.product}"
        return None

    @property
    def short_event(self) -> str:
        return os.path.basename(self.path)


# When linux-event-codes lists several aliases, prefer the name profiles/UI use.
# (e.g. BTN_TRIGGER not BTN_JOYSTICK — same code 0x120; BTN_X not BTN_NORTH.)
_BTN_ALIAS_RANK: dict[str, int] = {
    "BTN_TRIGGER": 0,
    "BTN_JOYSTICK": 20,
    "BTN_A": 0,
    "BTN_SOUTH": 5,
    "BTN_GAMEPAD": 15,
    "BTN_B": 0,
    "BTN_EAST": 5,
    "BTN_X": 0,
    "BTN_NORTH": 5,
    "BTN_Y": 0,
    "BTN_WEST": 5,
}


def _pick_alias(names: str | list | tuple) -> str:
    if isinstance(names, str):
        return names
    return min(names, key=lambda n: (_BTN_ALIAS_RANK.get(n, 50), n))


def _code_name(kind: str, code: int) -> str:
    if ecodes is None:
        return f"{kind}_{code}"
    if kind == "KEY":
        names = ecodes.KEY.get(code) or ecodes.BTN.get(code)
    else:
        names = ecodes.ABS.get(code)
    if names:
        return _pick_alias(names)
    return f"{kind}_#{code}"


def button_name_aliases(name: str) -> tuple[str, ...]:
    """All linux aliases for a BTN_*/KEY_* name (includes the name itself)."""
    if ecodes is None:
        return (name,)
    code = getattr(ecodes, name, None)
    if code is None:
        code = ecodes.ecodes.get(name) if hasattr(ecodes, "ecodes") else None
    if code is None:
        return (name,)
    names = ecodes.BTN.get(code) or ecodes.KEY.get(code)
    if not names:
        return (name,)
    if isinstance(names, str):
        return (names,)
    return tuple(names)


def phys_button_down(phys_buttons: dict[str, bool], mapped_name: str) -> bool:
    """True if mapped_name (or any alias of the same code) is pressed."""
    if phys_buttons.get(mapped_name):
        return True
    return any(phys_buttons.get(alias) for alias in button_name_aliases(mapped_name))


def _sysfs_is_virtual(event_name: str) -> bool:
    try:
        link = Path(f"/sys/class/input/{event_name}/device")
        resolved = os.path.realpath(link)
        return "/devices/virtual/" in resolved
    except OSError:
        return False


def _build_info(path: str) -> JoystickInfo | None:
    if evdev is None:
        return None
    try:
        dev = evdev.InputDevice(path)
    except (OSError, PermissionError):
        return None

    event_name = os.path.basename(path)
    caps = dev.capabilities()
    btn_codes = caps.get(ecodes.EV_KEY, [])
    abs_codes = [c if not isinstance(c, tuple) else c[0] for c in caps.get(ecodes.EV_ABS, [])]
    interesting_btns = any(
        (ecodes.BTN_JOYSTICK <= c <= ecodes.BTN_THUMBR + 20)
        or (ecodes.BTN_GAMEPAD <= c <= ecodes.BTN_THUMBR)
        or (ecodes.BTN_TRIGGER <= c <= ecodes.BTN_BASE6)
        for c in btn_codes
    )
    interesting_abs = any(c <= ecodes.ABS_HAT3Y for c in abs_codes)
    lname = (dev.name or "").lower()
    if not (interesting_btns or (interesting_abs and btn_codes)):
        if not any(k in lname for k in ("joystick", "gamepad", "controller", "xbox", "pad")):
            return None

    vendor = f"{dev.info.vendor:04x}" if dev.info.vendor else None
    product = f"{dev.info.product:04x}" if dev.info.product else None
    is_virtual = (
        _sysfs_is_virtual(event_name)
        or dev.info.bustype == BUS_VIRTUAL
        or "userspace driver" in lname
    )

    return JoystickInfo(
        path=path,
        name=dev.name or path,
        vendor=vendor,
        product=product,
        phys=dev.phys,
        uniq=dev.uniq,
        event_name=event_name,
        bustype=dev.info.bustype,
        is_virtual=is_virtual,
        buttons=[_code_name("KEY", c) for c in btn_codes],
        axes=[_code_name("ABS", c) for c in abs_codes],
    )


def list_joysticks(*, include_virtual: bool = False) -> list[JoystickInfo]:
    if evdev is None:
        return []
    skip_ids = {"26ce:01a2"}
    skip_name_bits = ("led controller", "antimicro", "mouse emulation")
    devices: list[JoystickInfo] = []
    for path in evdev.list_devices():
        info = _build_info(path)
        if info is None:
            continue
        if info.id_key in skip_ids:
            continue
        if any(bit in (info.name or "").lower() for bit in skip_name_bits):
            continue
        if info.is_virtual and not include_virtual:
            continue
        devices.append(info)
    devices.sort(key=lambda d: d.path)
    return devices


def list_virtual_xbox_pads() -> list[JoystickInfo]:
    return [d for d in list_joysticks(include_virtual=True) if d.is_virtual]


XBOX_BTN_FROM_EVDEV = {
    "BTN_A": "a",
    "BTN_SOUTH": "a",
    "BTN_B": "b",
    "BTN_EAST": "b",
    "BTN_X": "x",
    "BTN_NORTH": "x",
    "BTN_Y": "y",
    "BTN_WEST": "y",
    "BTN_TL": "lb",
    "BTN_TR": "rb",
    "BTN_SELECT": "back",
    "BTN_START": "start",
    "BTN_MODE": "guide",
    "BTN_THUMBL": "tl",
    "BTN_THUMBR": "tr",
}

XBOX_ABS_FROM_EVDEV = {
    "ABS_X": "x1",
    "ABS_Y": "y1",
    "ABS_RX": "x2",
    "ABS_RY": "y2",
    "ABS_Z": "lt",
    "ABS_RZ": "rt",
    "ABS_HAT0X": "dpad_x",
    "ABS_HAT0Y": "dpad_y",
}

# Triggers on Xbox pads are unipolar 0..255 (released=0). Hats are -1/0/1.
TRIGGER_AXES = {"ABS_Z", "ABS_RZ", "lt", "rt"}
HAT_AXES = {"ABS_HAT0X", "ABS_HAT0Y", "ABS_HAT1X", "ABS_HAT1Y", "dpad_x", "dpad_y"}


def axis_kind(name: str) -> str:
    if name in TRIGGER_AXES or name.endswith("_Z") and "ABS" in name:
        return "trigger"
    if name in HAT_AXES or "HAT" in name:
        return "hat"
    return "stick"


def normalize_axis(name: str, value: int, amin: int, amax: int) -> float:
    """Normalize axis for UI.

    - stick: -1..+1 (center 0)
    - trigger: 0..1 (released 0, full 1)  — critical for ABS_Z/ABS_RZ
    - hat: -1..+1 typically already
    """
    if amax == amin:
        return 0.0
    kind = axis_kind(name)
    if kind == "trigger":
        return max(0.0, min(1.0, (value - amin) / (amax - amin)))
    if kind == "hat":
        # Usually min=-1 max=1 already
        if amin == -1 and amax == 1:
            return float(value)
        return (value - amin) / (amax - amin) * 2 - 1
    return (value - amin) / (amax - amin) * 2 - 1


def axis_is_active(name: str, norm: float, *, stick_threshold: float = 0.35) -> bool:
    kind = axis_kind(name)
    if kind == "trigger":
        return norm >= 0.12
    if kind == "hat":
        return abs(norm) >= 0.5
    return abs(norm) >= stick_threshold


class EvdevMonitor(QObject):
    """High-rate evdev reader; discrete controls flush immediately, sticks coalesce."""

    state_changed = Signal()
    button_down = Signal(str)
    axis_peak = Signal(str, float)
    # Precise wall-clock diagnostic line, e.g. "1712345678.123456 PHYS KEY BTN_A down"
    diag_event = Signal(str)
    error = Signal(str)
    disconnected = Signal()

    def __init__(self, parent=None, coalesce_ms: float = 8.0, label: str = "DEV"):
        super().__init__(parent)
        self._path: str | None = None
        self._label = label
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._dev = None
        self._coalesce_s = max(0.001, coalesce_ms / 1000.0)
        self._dirty = False
        self._urgent = False
        self._lock = threading.Lock()
        self.button_state: dict[str, bool] = {}
        self.axis_state: dict[str, float] = {}

    def start(self, path: str) -> None:
        self.stop()
        self._path = path
        self._stop.clear()
        with self._lock:
            self.button_state.clear()
            self.axis_state.clear()
            self._dirty = False
            self._urgent = False
        self._thread = threading.Thread(target=self._run, name="evdev-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.8)
        self._thread = None
        self._dev = None

    def snapshot(self) -> tuple[dict[str, bool], dict[str, float]]:
        with self._lock:
            return dict(self.button_state), dict(self.axis_state)

    def _run(self) -> None:
        if evdev is None or not self._path:
            self.error.emit("evdev not available")
            return
        try:
            self._dev = evdev.InputDevice(self._path)
        except Exception as exc:
            self.error.emit(str(exc))
            return

        absinfo: dict = {}
        key_codes: list[int] = []
        try:
            caps = self._dev.capabilities()
            for code, info in caps.get(ecodes.EV_ABS, []):
                absinfo[code] = info
            key_codes = list(caps.get(ecodes.EV_KEY, []))
        except Exception:
            pass

        # Seed from kernel so a button already held at attach lights immediately.
        try:
            held0 = set(self._dev.active_keys())
        except (OSError, AttributeError):
            held0 = set()
        with self._lock:
            for code in key_codes:
                self.button_state[_code_name("KEY", code)] = code in held0
            for code, info in absinfo.items():
                try:
                    cur = self._dev.absinfo(code).value
                except Exception:
                    continue
                name = _code_name("ABS", code)
                self.axis_state[name] = normalize_axis(name, cur, info.min, info.max)
            if held0 or self.axis_state:
                self._dirty = True
                self._urgent = True

        last_emit = 0.0
        last_sync = 0.0
        while not self._stop.is_set():
            try:
                r, _, _ = select.select([self._dev.fd], [], [], 0.001)
            except (OSError, ValueError):
                self.disconnected.emit()
                return

            now = time.monotonic()
            if r:
                try:
                    for event in self._dev.read():
                        wall = time.time()
                        if event.type == ecodes.EV_KEY:
                            name = _code_name("KEY", event.code)
                            # value 1=down, 2=repeat, 0=up — treat repeat as still down
                            pressed = event.value != 0
                            with self._lock:
                                self.button_state[name] = pressed
                                self._dirty = True
                                self._urgent = True
                            edge = "down" if pressed else "up"
                            self.diag_event.emit(
                                f"{wall:.6f} {self._label} KEY {name} {edge}"
                            )
                            if event.value == 1:
                                self.button_down.emit(name)
                        elif event.type == ecodes.EV_ABS:
                            name = _code_name("ABS", event.code)
                            info = absinfo.get(event.code)
                            amin = info.min if info else -32768
                            amax = info.max if info else 32767
                            norm = normalize_axis(name, event.value, amin, amax)
                            kind = axis_kind(name)
                            with self._lock:
                                prev = self.axis_state.get(name, 0.0)
                                self.axis_state[name] = norm
                                self._dirty = True
                                if kind in {"hat", "trigger"}:
                                    self._urgent = True
                            # Log discrete-ish axis edges only (avoid stick spam)
                            if kind == "trigger":
                                was = prev >= 0.12
                                now_on = norm >= 0.12
                                if was != now_on:
                                    self.diag_event.emit(
                                        f"{wall:.6f} {self._label} TRG {name} "
                                        f"{'on' if now_on else 'off'} raw={event.value} n={norm:.3f}"
                                    )
                                if norm >= 0.85 and prev < 0.85:
                                    self.axis_peak.emit(name, norm)
                            elif kind == "hat":
                                if abs(norm) >= 0.5 and abs(prev) < 0.5:
                                    self.diag_event.emit(
                                        f"{wall:.6f} {self._label} HAT {name} "
                                        f"deflect={norm:+.0f} raw={event.value}"
                                    )
                                    self.axis_peak.emit(name, norm)
                                elif abs(norm) < 0.5 and abs(prev) >= 0.5:
                                    self.diag_event.emit(
                                        f"{wall:.6f} {self._label} HAT {name} center raw={event.value}"
                                    )
                            else:
                                if abs(norm) > 0.85 and abs(prev) <= 0.85:
                                    self.axis_peak.emit(name, norm)
                except BlockingIOError:
                    pass
                except OSError:
                    self.disconnected.emit()
                    return

            # Resync held keys from kernel (~60 Hz backup). Event path is primary;
            # this catches missed downs / stuck "still held" without burning CPU.
            if key_codes and (now - last_sync) >= 0.016:
                last_sync = now
                try:
                    held = set(self._dev.active_keys())
                except (OSError, AttributeError):
                    held = None
                if held is not None:
                    changed = False
                    with self._lock:
                        for code in key_codes:
                            name = _code_name("KEY", code)
                            want = code in held
                            if self.button_state.get(name, False) != want:
                                self.button_state[name] = want
                                changed = True
                        if changed:
                            self._dirty = True
                            self._urgent = True
                    for code, info in absinfo.items():
                        try:
                            cur = self._dev.absinfo(code).value
                        except Exception:
                            continue
                        name = _code_name("ABS", code)
                        amin = info.min
                        amax = info.max
                        norm = normalize_axis(name, cur, amin, amax)
                        kind = axis_kind(name)
                        with self._lock:
                            if self.axis_state.get(name) != norm:
                                self.axis_state[name] = norm
                                self._dirty = True
                                if kind in {"hat", "trigger"}:
                                    self._urgent = True

            if self._dirty and (self._urgent or (now - last_emit) >= self._coalesce_s):
                self._dirty = False
                self._urgent = False
                last_emit = now
                self.state_changed.emit()

        if self._dirty:
            self.state_changed.emit()
