#!/usr/bin/env python3
"""Edge-preserving physical→Xbox 360 uinput bridge (stdlib only).

Replaces xboxdrv for fighting-game mash: every physical edge is emitted,
and a down while already down forces an up+down pulse so presses are never
swallowed by sticky virtual state.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import select
import struct
import sys
import time
from pathlib import Path
from typing import Any

# --- linux input / uinput constants -------------------------------------------------

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0

BTN_A = 0x130
BTN_B = 0x131
BTN_X = 0x133
BTN_Y = 0x134
BTN_TL = 0x136
BTN_TR = 0x137
BTN_TL2 = 0x138
BTN_TR2 = 0x139
BTN_SELECT = 0x13A
BTN_START = 0x13B
BTN_MODE = 0x13C
BTN_THUMBL = 0x13D
BTN_THUMBR = 0x13E

ABS_X = 0x00
ABS_Y = 0x01
ABS_Z = 0x02
ABS_RX = 0x03
ABS_RY = 0x04
ABS_RZ = 0x05
ABS_HAT0X = 0x10
ABS_HAT0Y = 0x11
ABS_CNT = 0x40

BUS_USB = 0x03
XPAD_VENDOR = 0x045E
XPAD_PRODUCT = 0x028E
XPAD_VERSION = 0x0114
XPAD_NAME = b"Microsoft X-Box 360 pad"

UINPUT_MAX_NAME_SIZE = 80

# ioctl helpers (linux _IOC)
_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2


def _IOC(dir_: int, type_: str, nr: int, size: int) -> int:
    return (dir_ << 30) | (ord(type_) << 8) | nr | (size << 16)


def _IO(type_: str, nr: int) -> int:
    return _IOC(_IOC_NONE, type_, nr, 0)


def _IOW(type_: str, nr: int, size: int) -> int:
    return _IOC(_IOC_WRITE, type_, nr, size)


def _IOR(type_: str, nr: int, size: int) -> int:
    return _IOC(_IOC_READ, type_, nr, size)


UI_DEV_CREATE = _IO("U", 1)
UI_DEV_DESTROY = _IO("U", 2)
UI_DEV_SETUP = _IOW("U", 3, 92)  # sizeof(struct uinput_setup)
UI_ABS_SETUP = _IOW("U", 4, 28)  # sizeof(struct uinput_abs_setup)
UI_SET_EVBIT = _IOW("U", 100, 4)
UI_SET_KEYBIT = _IOW("U", 101, 4)
UI_SET_ABSBIT = _IOW("U", 103, 4)
EVIOCGRAB = _IOW("E", 0x90, 4)
_ABSINFO_SIZE = 24  # 6 * s32


def EVIOCGABS(code: int) -> int:
    return _IOR("E", 0x40 + code, _ABSINFO_SIZE)


EVENT_FMT = "llHHi"  # timeval + type + code + value (64-bit)
EVENT_SIZE = struct.calcsize(EVENT_FMT)

# Names used in profiles → linux codes
CODE_BY_NAME: dict[str, int] = {
    "BTN_TRIGGER": 0x120,
    "BTN_THUMB": 0x121,
    "BTN_THUMB2": 0x122,
    "BTN_TOP": 0x123,
    "BTN_TOP2": 0x124,
    "BTN_PINKIE": 0x125,
    "BTN_BASE": 0x126,
    "BTN_BASE2": 0x127,
    "BTN_BASE3": 0x128,
    "BTN_BASE4": 0x129,
    "BTN_BASE5": 0x12A,
    "BTN_BASE6": 0x12B,
    "BTN_DEAD": 0x12F,
    "BTN_A": BTN_A,
    "BTN_B": BTN_B,
    "BTN_C": 0x132,
    "BTN_X": BTN_X,
    "BTN_Y": BTN_Y,
    "BTN_Z": 0x135,
    "BTN_TL": BTN_TL,
    "BTN_TR": BTN_TR,
    "BTN_TL2": BTN_TL2,
    "BTN_TR2": BTN_TR2,
    "BTN_SELECT": BTN_SELECT,
    "BTN_START": BTN_START,
    "BTN_MODE": BTN_MODE,
    "BTN_THUMBL": BTN_THUMBL,
    "BTN_THUMBR": BTN_THUMBR,
    "BTN_JOYSTICK": 0x120,
    **{f"BTN_{i}": 0x100 + i for i in range(10)},
    "ABS_X": ABS_X,
    "ABS_Y": ABS_Y,
    "ABS_Z": ABS_Z,
    "ABS_RX": ABS_RX,
    "ABS_RY": ABS_RY,
    "ABS_RZ": ABS_RZ,
    "ABS_HAT0X": ABS_HAT0X,
    "ABS_HAT0Y": ABS_HAT0Y,
    "ABS_HAT1X": 0x12,
    "ABS_HAT1Y": 0x13,
}

BTN_DPAD_UP = 0x220
BTN_DPAD_DOWN = 0x221
BTN_DPAD_LEFT = 0x222
BTN_DPAD_RIGHT = 0x223

# Xbox short names → virtual outputs
XBOX_BTN_CODES: dict[str, int] = {
    "a": BTN_A,
    "b": BTN_B,
    "x": BTN_X,
    "y": BTN_Y,
    "lb": BTN_TL,
    "rb": BTN_TR,
    "back": BTN_SELECT,
    "start": BTN_START,
    "guide": BTN_MODE,
    "tl": BTN_THUMBL,
    "tr": BTN_THUMBR,
    "du": BTN_DPAD_UP,
    "dd": BTN_DPAD_DOWN,
    "dl": BTN_DPAD_LEFT,
    "dr": BTN_DPAD_RIGHT,
}

XBOX_ABS_CODES: dict[str, int] = {
    "x1": ABS_X,
    "y1": ABS_Y,
    "x2": ABS_RX,
    "y2": ABS_RY,
    "lt": ABS_Z,
    "rt": ABS_RZ,
    "dpad_x": ABS_HAT0X,
    "dpad_y": ABS_HAT0Y,
}

TRIGGER_XBOX = {"lt", "rt"}
HAT_XBOX = {"dpad_x", "dpad_y"}
STICK_XBOX = {"x1", "y1", "x2", "y2"}
DPAD_DIR = {"du", "dd", "dl", "dr"}


def resolve_code(name: str) -> int:
    if name in CODE_BY_NAME:
        return CODE_BY_NAME[name]
    if name.startswith("KEY_") or name.startswith("BTN_") or name.startswith("ABS_"):
        # Numeric fallback: ABS_#12 / KEY_#123
        if "#" in name:
            return int(name.split("#", 1)[1])
    raise KeyError(f"unknown code name: {name}")


def parse_axismap(entries: list[str]) -> dict[str, bool]:
    """Return xbox-axis → invert flag from xboxdrv-style axismap (-Y1=Y1)."""
    invert: dict[str, bool] = {}
    for raw in entries:
        raw = raw.strip()
        if not raw or "=" not in raw:
            continue
        src, _dst = raw.split("=", 1)
        neg = src.startswith("-")
        token = src[1:] if neg else src
        # Y1 / y1 / LT → lowercase xbox id
        key = token.lower()
        if key in XBOX_ABS_CODES:
            invert[key] = invert.get(key, False) ^ neg
    return invert


def profile_flags(extra_opts: list[str]) -> tuple[bool, bool]:
    trigger_as_button = "--trigger-as-button" in extra_opts
    dpad_as_button = "--dpad-as-button" in extra_opts
    return trigger_as_button, dpad_as_button


def normalize_axis(value: int, minimum: int, maximum: int) -> float:
    if maximum == minimum:
        return 0.0
    # Map to [-1, 1] with center at midpoint
    mid = (maximum + minimum) / 2.0
    half = (maximum - minimum) / 2.0
    if half == 0:
        return 0.0
    return max(-1.0, min(1.0, (value - mid) / half))


def stick_to_xpad(norm: float) -> int:
    if norm >= 0:
        return int(round(norm * 32767))
    return int(round(norm * 32768))


def hat_from_norm(norm: float, dead: float = 0.45) -> int:
    if norm <= -dead:
        return -1
    if norm >= dead:
        return 1
    return 0


class UInputXbox:
    """Virtual Microsoft X-Box 360 pad via /dev/uinput."""

    def __init__(self, *, trigger_as_button: bool, dpad_as_button: bool) -> None:
        self.trigger_as_button = trigger_as_button
        self.dpad_as_button = dpad_as_button
        self.fd = os.open("/dev/uinput", os.O_RDWR | os.O_NONBLOCK)
        self._keys: dict[int, int] = {}
        self._abs: dict[int, int] = {}
        self._last_down_mono: dict[int, float] = {}
        self._dirty = False
        self._setup()

    def _setup(self) -> None:
        # NOTE: UI_SET_*BIT must pass a bare int — struct.pack('i', n) returns EINVAL here.
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)

        key_bits = [
            BTN_A, BTN_B, BTN_X, BTN_Y,
            BTN_TL, BTN_TR, BTN_SELECT, BTN_START, BTN_MODE,
            BTN_THUMBL, BTN_THUMBR,
        ]
        if self.trigger_as_button:
            key_bits.extend([BTN_TL2, BTN_TR2])
        if self.dpad_as_button:
            key_bits.extend([BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT])
        for code in key_bits:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)

        axes: dict[int, tuple[int, int]] = {
            ABS_X: (-32768, 32767),
            ABS_Y: (-32768, 32767),
            ABS_RX: (-32768, 32767),
            ABS_RY: (-32768, 32767),
            ABS_Z: (0, 255),
            ABS_RZ: (0, 255),
        }
        if not self.dpad_as_button:
            axes[ABS_HAT0X] = (-1, 1)
            axes[ABS_HAT0Y] = (-1, 1)

        for code, (minimum, maximum) in axes.items():
            fcntl.ioctl(self.fd, UI_SET_ABSBIT, code)
            # struct uinput_abs_setup { __u16 code; __u16 pad; struct input_absinfo; } = 28
            # input_absinfo: value, min, max, fuzz, flat, resolution
            buf = struct.pack("Hxxiiiiii", code, 0, minimum, maximum, 0, 0, 0)
            fcntl.ioctl(self.fd, UI_ABS_SETUP, buf)

        name = XPAD_NAME[: UINPUT_MAX_NAME_SIZE - 1].ljust(UINPUT_MAX_NAME_SIZE, b"\0")
        # struct uinput_setup { input_id id; char name[80]; __u32 ff_effects_max; }
        setup = struct.pack(
            "4H80sI",
            BUS_USB,
            XPAD_VENDOR,
            XPAD_PRODUCT,
            XPAD_VERSION,
            name,
            0,
        )
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.05)

    def _write_event(self, etype: int, code: int, value: int) -> None:
        os.write(self.fd, struct.pack(EVENT_FMT, 0, 0, etype, code, value))

    def syn(self) -> None:
        self._write_event(EV_SYN, SYN_REPORT, 0)
        self._dirty = False

    def flush(self) -> None:
        """Emit SYN_REPORT if any events were queued since the last syn."""
        if self._dirty:
            self.syn()

    def set_key(self, code: int, pressed: bool, *, flush: bool = True) -> bool:
        """Return True if any uinput event was written."""
        want = 1 if pressed else 0
        prev = self._keys.get(code, 0)
        now = time.monotonic()
        if want == 1 and prev == 1:
            # Duplicate down while held (USB bounce) → ignore.
            # Spaced downs without an up → mash recovery (lost up): pulse up+down.
            last = self._last_down_mono.get(code, 0.0)
            if now - last < 0.012:
                return False
            # SYN between up and down is mandatory: same-SYN 0→1 is invisible to
            # state pollers and many FG engines (still "held" after the report).
            self._write_event(EV_KEY, code, 0)
            self.syn()
            self._write_event(EV_KEY, code, 1)
            self._keys[code] = 1
            self._last_down_mono[code] = now
            self._dirty = True
            if flush:
                self.syn()
            return True
        if want == prev:
            return False
        self._write_event(EV_KEY, code, want)
        self._keys[code] = want
        if want == 1:
            self._last_down_mono[code] = now
        self._dirty = True
        if flush:
            self.syn()
        return True

    def set_abs(
        self, code: int, value: int, *, force_edge: bool = False, flush: bool = True
    ) -> bool:
        """Return True if any uinput event was written."""
        prev = self._abs.get(code)
        now = time.monotonic()
        if force_edge and prev is not None and prev == value and value != 0:
            last = self._last_down_mono.get(code, 0.0)
            if now - last < 0.012:
                return False
            # Same as keys: release must be its own SYN report or pollers miss it.
            self._write_event(EV_ABS, code, 0)
            self.syn()
            self._write_event(EV_ABS, code, value)
            self._abs[code] = value
            self._last_down_mono[code] = now
            self._dirty = True
            if flush:
                self.syn()
            return True
        if prev == value:
            return False
        self._write_event(EV_ABS, code, value)
        self._abs[code] = value
        if value:
            self._last_down_mono[code] = now
        self._dirty = True
        if flush:
            self.syn()
        return True

    def close(self) -> None:
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


class PhysicalDevice:
    def __init__(self, path: str, *, grab: bool = True) -> None:
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.grabbed = False
        self.absinfo: dict[int, tuple[int, int]] = {}
        self._load_absinfo()
        if grab:
            last_err: OSError | None = None
            for attempt in range(15):
                try:
                    fcntl.ioctl(self.fd, EVIOCGRAB, 1)
                    self.grabbed = True
                    last_err = None
                    break
                except OSError as exc:
                    last_err = exc
                    time.sleep(0.1)
            if last_err is not None and not self.grabbed:
                raise last_err

    def _load_absinfo(self) -> None:
        for code in range(ABS_CNT):
            buf = bytearray(_ABSINFO_SIZE)
            try:
                fcntl.ioctl(self.fd, EVIOCGABS(code), buf)
            except OSError:
                continue
            _value, minimum, maximum, _fuzz, _flat, _res = struct.unpack("iiiiii", buf)
            if minimum != maximum:
                self.absinfo[code] = (minimum, maximum)

    def axis_range(self, code: int) -> tuple[int, int]:
        return self.absinfo.get(code, (0, 255))

    def read_events(self) -> list[tuple[int, int, int]]:
        out: list[tuple[int, int, int]] = []
        # Large reads drain the kernel client queue faster under mash.
        chunk_bytes = EVENT_SIZE * 512
        while True:
            try:
                data = os.read(self.fd, chunk_bytes)
            except BlockingIOError:
                break
            if not data:
                break
            for off in range(0, len(data), EVENT_SIZE):
                piece = data[off : off + EVENT_SIZE]
                if len(piece) < EVENT_SIZE:
                    break
                _s, _us, etype, code, value = struct.unpack(EVENT_FMT, piece)
                if etype in (EV_KEY, EV_ABS):
                    out.append((etype, code, value))
        return out

    def close(self) -> None:
        if self.grabbed:
            try:
                fcntl.ioctl(self.fd, EVIOCGRAB, 0)
            except OSError:
                pass
            self.grabbed = False
        try:
            os.close(self.fd)
        except OSError:
            pass


# Reverse lookup for diag lines (code → name); built lazily from CODE_BY_NAME.
_NAME_BY_CODE: dict[int, str] | None = None


def _code_name(code: int) -> str:
    global _NAME_BY_CODE
    if _NAME_BY_CODE is None:
        _NAME_BY_CODE = {}
        for name, c in CODE_BY_NAME.items():
            # Prefer BTN_* / ABS_* canonical names over BTN_0.. duplicates
            if c not in _NAME_BY_CODE or name.startswith(("BTN_", "ABS_", "KEY_")):
                if name.startswith("BTN_") and name[4:].isdigit():
                    continue
                _NAME_BY_CODE[c] = name
        for name, c in [
            ("BTN_A", BTN_A), ("BTN_B", BTN_B), ("BTN_X", BTN_X), ("BTN_Y", BTN_Y),
            ("BTN_TL", BTN_TL), ("BTN_TR", BTN_TR), ("BTN_SELECT", BTN_SELECT),
            ("BTN_START", BTN_START), ("BTN_MODE", BTN_MODE),
            ("ABS_Z", ABS_Z), ("ABS_RZ", ABS_RZ), ("ABS_HAT0X", ABS_HAT0X),
            ("ABS_HAT0Y", ABS_HAT0Y),
        ]:
            _NAME_BY_CODE[c] = name
    return _NAME_BY_CODE.get(code, f"CODE_{code}")


class BridgeDiag:
    """Single-process ground-truth log (PHYS in + EMIT out). Survives UI dropouts."""

    def __init__(self, path: str) -> None:
        self.path = path
        # Truncate each bridge start so a remash session is easy to read.
        self._fh = open(path, "w", buffering=1, encoding="utf-8")  # noqa: SIM115
        try:
            os.chmod(path, 0o666)
        except OSError:
            pass
        self._fh.write(f"{time.time():.6f} BRIDGE start pid={os.getpid()}\n")

    def phys(self, etype: int, code: int, value: int) -> None:
        if etype == EV_KEY:
            if value == 2:
                return
            edge = "down" if value else "up"
            self._fh.write(f"{time.time():.6f} PHYS KEY {_code_name(code)} {edge}\n")
        elif etype == EV_ABS:
            self._fh.write(
                f"{time.time():.6f} PHYS ABS {_code_name(code)} value={value}\n"
            )

    def emit_key(self, code: int, pressed: bool, *, pulse: bool = False) -> None:
        tag = "PULSE" if pulse else "EMIT"
        edge = "down" if pressed else "up"
        self._fh.write(f"{time.time():.6f} {tag} KEY {_code_name(code)} {edge}\n")

    def emit_abs(self, code: int, value: int, *, pulse: bool = False) -> None:
        tag = "PULSE" if pulse else "EMIT"
        self._fh.write(
            f"{time.time():.6f} {tag} ABS {_code_name(code)} value={value}\n"
        )

    def close(self) -> None:
        try:
            self._fh.write(f"{time.time():.6f} BRIDGE stop\n")
            self._fh.close()
        except OSError:
            pass


class Bridge:
    def __init__(
        self,
        phys: PhysicalDevice,
        ui: UInputXbox,
        profile: dict[str, Any],
        diag: BridgeDiag | None = None,
    ) -> None:
        self.phys = phys
        self.ui = ui
        self.diag = diag
        self.trigger_as_button, self.dpad_as_button = profile_flags(list(profile.get("extra_opts") or []))
        self.invert = parse_axismap(list(profile.get("axismap") or []))
        self.key_map: dict[int, str] = {}
        for name, xbox in (profile.get("evdev_keymap") or {}).items():
            self.key_map[resolve_code(name)] = xbox
        self.abs_map: dict[int, str] = {}
        for name, xbox in (profile.get("evdev_absmap") or {}).items():
            self.abs_map[resolve_code(name)] = xbox
        # Cached hat / dpad button state for composite updates
        self._hat_x = 0
        self._hat_y = 0

    def _apply_invert(self, xbox: str, norm: float) -> float:
        if self.invert.get(xbox):
            return -norm
        return norm

    def _emit_xbox_button(self, xbox: str, pressed: bool) -> None:
        if xbox in TRIGGER_XBOX:
            if self.trigger_as_button:
                code = BTN_TL2 if xbox == "lt" else BTN_TR2
                prev = self.ui._keys.get(code, 0)
                wrote = self.ui.set_key(code, pressed, flush=False)
                if wrote and self.diag:
                    if pressed and prev == 1:
                        self.diag.emit_key(code, False, pulse=True)
                        self.diag.emit_key(code, True, pulse=True)
                    else:
                        self.diag.emit_key(code, pressed)
            else:
                abs_code = ABS_Z if xbox == "lt" else ABS_RZ
                prev = self.ui._abs.get(abs_code)
                want = 255 if pressed else 0
                wrote = self.ui.set_abs(
                    abs_code, want, force_edge=pressed, flush=False
                )
                if wrote and self.diag:
                    if pressed and prev == want and want != 0:
                        self.diag.emit_abs(abs_code, 0, pulse=True)
                        self.diag.emit_abs(abs_code, want, pulse=True)
                    else:
                        self.diag.emit_abs(abs_code, want)
            return
        if xbox in DPAD_DIR:
            if self.dpad_as_button:
                code = XBOX_BTN_CODES[xbox]
                prev = self.ui._keys.get(code, 0)
                wrote = self.ui.set_key(code, pressed, flush=False)
                if wrote and self.diag:
                    if pressed and prev == 1:
                        self.diag.emit_key(code, False, pulse=True)
                        self.diag.emit_key(code, True, pulse=True)
                    else:
                        self.diag.emit_key(code, pressed)
                return
            # Map directional buttons onto hat axes
            if xbox == "du":
                self._hat_y = -1 if pressed else (0 if self._hat_y < 0 else self._hat_y)
            elif xbox == "dd":
                self._hat_y = 1 if pressed else (0 if self._hat_y > 0 else self._hat_y)
            elif xbox == "dl":
                self._hat_x = -1 if pressed else (0 if self._hat_x < 0 else self._hat_x)
            elif xbox == "dr":
                self._hat_x = 1 if pressed else (0 if self._hat_x > 0 else self._hat_x)
            wx = self.ui.set_abs(ABS_HAT0X, self._hat_x, flush=False)
            wy = self.ui.set_abs(ABS_HAT0Y, self._hat_y, flush=False)
            if self.diag:
                if wx:
                    self.diag.emit_abs(ABS_HAT0X, self._hat_x)
                if wy:
                    self.diag.emit_abs(ABS_HAT0Y, self._hat_y)
            return
        code = XBOX_BTN_CODES.get(xbox)
        if code is not None:
            prev = self.ui._keys.get(code, 0)
            wrote = self.ui.set_key(code, pressed, flush=False)
            if wrote and self.diag:
                if pressed and prev == 1:
                    self.diag.emit_key(code, False, pulse=True)
                    self.diag.emit_key(code, True, pulse=True)
                else:
                    self.diag.emit_key(code, pressed)

    def _emit_xbox_axis(self, xbox: str, norm: float) -> None:
        norm = self._apply_invert(xbox, norm)
        if xbox in TRIGGER_XBOX:
            if self.trigger_as_button:
                code = BTN_TL2 if xbox == "lt" else BTN_TR2
                pressed = norm > 0.5
                wrote = self.ui.set_key(code, pressed, flush=False)
                if wrote and self.diag:
                    self.diag.emit_key(code, pressed)
            else:
                # Physical abs mapped as trigger: treat |norm| as pull depth (0..1)
                uni = max(0.0, min(1.0, abs(norm)))
                abs_code = ABS_Z if xbox == "lt" else ABS_RZ
                want = int(round(uni * 255))
                wrote = self.ui.set_abs(abs_code, want, flush=False)
                if wrote and self.diag:
                    self.diag.emit_abs(abs_code, want)
            return
        if xbox in HAT_XBOX:
            if self.dpad_as_button:
                hat = hat_from_norm(norm)
                if xbox == "dpad_x":
                    for code, on in ((BTN_DPAD_LEFT, hat < 0), (BTN_DPAD_RIGHT, hat > 0)):
                        wrote = self.ui.set_key(code, on, flush=False)
                        if wrote and self.diag:
                            self.diag.emit_key(code, on)
                else:
                    for code, on in ((BTN_DPAD_UP, hat < 0), (BTN_DPAD_DOWN, hat > 0)):
                        wrote = self.ui.set_key(code, on, flush=False)
                        if wrote and self.diag:
                            self.diag.emit_key(code, on)
                return
            hat = hat_from_norm(norm)
            if xbox == "dpad_x":
                self._hat_x = hat
                wrote = self.ui.set_abs(ABS_HAT0X, hat, flush=False)
                if wrote and self.diag:
                    self.diag.emit_abs(ABS_HAT0X, hat)
            else:
                self._hat_y = hat
                wrote = self.ui.set_abs(ABS_HAT0Y, hat, flush=False)
                if wrote and self.diag:
                    self.diag.emit_abs(ABS_HAT0Y, hat)
            return
        if xbox in STICK_XBOX:
            # Small deadzone for sticks
            if abs(norm) < 0.02:
                norm = 0.0
            abs_code = XBOX_ABS_CODES[xbox]
            want = stick_to_xpad(norm)
            wrote = self.ui.set_abs(abs_code, want, flush=False)
            if wrote and self.diag:
                self.diag.emit_abs(abs_code, want)

    def handle(self, etype: int, code: int, value: int) -> None:
        if etype == EV_KEY:
            if value == 2:
                return  # ignore kernel key-repeat
            if self.diag and code in self.key_map:
                self.diag.phys(etype, code, value)
            xbox = self.key_map.get(code)
            if xbox:
                self._emit_xbox_button(xbox, value != 0)
            return
        if etype == EV_ABS:
            xbox = self.abs_map.get(code)
            if not xbox:
                return
            if self.diag:
                self.diag.phys(etype, code, value)
            minimum, maximum = self.phys.axis_range(code)
            # Hats on physical device are often already -1..1
            if minimum == -1 and maximum == 1:
                norm = float(value)
            else:
                norm = normalize_axis(value, minimum, maximum)
            self._emit_xbox_axis(xbox, norm)

    def loop(self) -> None:
        # Drain all pending phys events, then one SYN — keeps the evdev client
        # queue from overflowing under fighting-game mash.
        while True:
            r, _w, _x = select.select([self.phys.fd], [], [], 1.0)
            if not r:
                continue
            batch = self.phys.read_events()
            for etype, code, value in batch:
                self.handle(etype, code, value)
            self.ui.flush()


def run_bridge(
    event_node: str,
    profile: dict[str, Any],
    *,
    grab: bool = True,
    diag_log: str | None = None,
) -> int:
    path = event_node if event_node.startswith("/") else f"/dev/input/{event_node}"
    if not os.path.exists(path):
        print(f"missing device {path}", file=sys.stderr)
        return 1
    trigger_as_button, dpad_as_button = profile_flags(list(profile.get("extra_opts") or []))
    phys = PhysicalDevice(path, grab=grab)
    ui = UInputXbox(trigger_as_button=trigger_as_button, dpad_as_button=dpad_as_button)
    diag = BridgeDiag(diag_log) if diag_log else None
    bridge = Bridge(phys, ui, profile, diag=diag)
    try:
        bridge.loop()
    except KeyboardInterrupt:
        return 0
    finally:
        if diag:
            diag.close()
        ui.close()
        phys.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Any Pad → Xbox 360 uinput bridge")
    parser.add_argument("event", help="eventN or /dev/input/eventN")
    parser.add_argument(
        "--profile-json",
        help="Inline profile JSON (otherwise read from /etc/any-pad-to-xbox/profiles.json)",
    )
    parser.add_argument("--no-grab", action="store_true", help="Do not EVIOCGRAB the physical pad")
    parser.add_argument(
        "--diag-log",
        help="Append PHYS/EMIT ground-truth lines (bridge-side; survives UI dropouts)",
    )
    parser.add_argument(
        "--profiles-path",
        default="/etc/any-pad-to-xbox/profiles.json",
        help="System profiles path",
    )
    parser.add_argument("--vendor", help="Force vendor id (hex)")
    parser.add_argument("--product", help="Force product id (hex)")
    args = parser.parse_args(argv)

    if args.profile_json:
        profile = json.loads(args.profile_json)
    else:
        # Resolve via udev ids unless forced
        event = args.event.removeprefix("/dev/input/")
        vendor, product = args.vendor, args.product
        if not vendor or not product:
            import subprocess

            out = subprocess.check_output(
                ["udevadm", "info", "--query=property", f"--name=/dev/input/{event}"],
                text=True,
            )
            for line in out.splitlines():
                if line.startswith("ID_VENDOR_ID="):
                    vendor = line.split("=", 1)[1].lower()
                elif line.startswith("ID_MODEL_ID="):
                    product = line.split("=", 1)[1].lower()
        if not vendor or not product:
            print("could not resolve vendor/product", file=sys.stderr)
            return 1
        data = json.loads(Path(args.profiles_path).read_text(encoding="utf-8"))
        key = f"{vendor}:{product}"
        profile = (data.get("profiles") or {}).get(key) or (data.get("profiles") or {}).get(key.lower())
        if not profile:
            print(f"no profile for {key}", file=sys.stderr)
            return 1
        if not profile.get("enabled", True):
            print(f"profile {key} disabled", file=sys.stderr)
            return 1

    return run_bridge(
        args.event,
        profile,
        grab=not args.no_grab,
        diag_log=args.diag_log,
    )


if __name__ == "__main__":
    sys.exit(main())
