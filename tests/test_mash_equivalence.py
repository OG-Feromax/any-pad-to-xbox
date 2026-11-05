"""Mash equivalence: what the bridge promises when a human presses faster than USB polls.

The reason this bridge exists instead of plain forwarding: under mash a cheap encoder
loses the "up" edge, and a game that polls state then sees one held button instead of two
presses. `UInputXbox.set_key` recovers that edge by pulsing up+down with a SYN between
(`xpad_bridge.py:325`). These tests pin that contract and its deliberate limit.

Expectations below were taken by driving the real module with a fake clock and recording
what it emits — not by guessing the Linux button codes.

No uinput, no root, no pad required: runs in CI.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_FILE = REPO_ROOT / "packaging" / "xpad_bridge.py"

# The DragonRise profile as stored in /etc, minus nothing: real mapping names.
PROFILE = {
    "name": "DragonRise Fliperama",
    "enabled": True,
    "slot": 1,
    "evdev_keymap": {
        "BTN_THUMB": "a",
        "BTN_TOP": "x",
        "BTN_PINKIE": "lt",
        "BTN_TOP2": "rt",
    },
    "evdev_absmap": {"ABS_X": "dpad_x", "ABS_Y": "dpad_y"},
    "axismap": ["-Y1=Y1", "-Y2=Y2"],
    "extra_opts": [],
}

SPARKFUN_BUTTON_DPAS = {
    "name": "SparkFun Pro Micro",
    "evdev_keymap": {"BTN_2": "dl", "BTN_3": "dd"},
    "evdev_absmap": {},
    "axismap": [],
    "extra_opts": ["--dpad-as-button"],
}


def load_bridge_module():
    spec = importlib.util.spec_from_file_location("xpad_bridge_under_test", BRIDGE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClock:
    """Hand-driven monotonic time: the debounce window must not race the wall clock."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def ms(self, milliseconds: float) -> None:
        self.now += milliseconds / 1000.0


@pytest.fixture
def mod():
    return load_bridge_module()


@pytest.fixture
def harness(monkeypatch, mod):
    """The bridge writing into a list instead of /dev/uinput."""
    clock = FakeClock()
    monkeypatch.setattr(mod, "time", clock)

    ui = object.__new__(mod.UInputXbox)
    ui.fd = -1
    ui._keys = {}
    ui._abs = {}
    ui._last_down_mono = {}
    ui._dirty = False
    written: list[tuple[int, int, int]] = []
    ui._write_event = lambda etype, code, value: written.append((etype, code, value))

    class FakePhys:
        def axis_range(self, _code):
            return (0, 255)

    bridge = mod.Bridge(FakePhys(), ui, PROFILE)

    def feed(etype: int, code: int, value: int) -> None:
        """One physical event, then the flush Bridge.loop() would do after its batch."""
        bridge.handle(etype, code, value)
        ui.flush()

    def reset() -> None:
        ui._keys.clear()
        ui._abs.clear()
        ui._last_down_mono.clear()
        ui._dirty = False
        written.clear()

    return SimpleNamespace(
        bridge=bridge, ui=ui, written=written, clock=clock, mod=mod,
        feed=feed, reset=reset,
        # Physical codes (what the encoder sends) and virtual codes (what the game
        # sees) are different numbers: BTN_THUMB=289 arrives, BTN_A=304 goes out.
        press=mod.resolve_code("BTN_THUMB"),
        top=mod.resolve_code("BTN_TOP"),
        pinkie=mod.resolve_code("BTN_PINKIE"),
        va=mod.XBOX_BTN_CODES["a"],
        vx=mod.XBOX_BTN_CODES["x"],
        code=mod.resolve_code,
    )


def transitions(written, mod, code):
    """The EV_KEY values the virtual pad saw for one button, in order."""
    return [value for etype, c, value in written if etype == mod.EV_KEY and c == code]


def batches(written, mod):
    """SYN-delimited groups, the unit a game actually polls."""
    out, current = [], []
    for etype, code, value in written:
        if etype == mod.EV_SYN:
            out.append(current)
            current = []
        else:
            current.append((etype, code, value))
    if current:
        out.append(current)
    return [b for b in out if b]


class TestCleanMashIsLossless:
    def test_every_press_with_its_up_comes_out(self, harness):
        for _ in range(10):
            harness.feed(harness.mod.EV_KEY, harness.press, 1)
            harness.clock.ms(8)
            harness.feed(harness.mod.EV_KEY, harness.press, 0)
            harness.clock.ms(8)
        assert transitions(harness.written, harness.mod, harness.va) == [1, 0] * 10

    def test_each_transition_is_polled_as_its_own_report(self, harness):
        """A down+up inside one SYN is invisible to state pollers and FG engines."""
        for _ in range(5):
            harness.feed(harness.mod.EV_KEY, harness.press, 1)
            harness.feed(harness.mod.EV_KEY, harness.press, 0)
        for batch in batches(harness.written, harness.mod):
            assert len(batch) == 1, f"two transitions in one report: {batch}"

    def test_mash_at_8ms_with_ups_present_is_still_lossless(self, harness):
        """The debounce window does not punish real, separated presses at 8 ms."""
        for _ in range(20):
            harness.feed(harness.mod.EV_KEY, harness.press, 1)
            harness.feed(harness.mod.EV_KEY, harness.press, 0)
        assert transitions(harness.written, harness.mod, harness.va) == [1, 0] * 20

    def test_two_buttons_alternating_fast_do_not_interfere(self, harness):
        for phys, virt in ((harness.press, harness.va), (harness.top, harness.vx)):
            for _ in range(6):
                harness.feed(harness.mod.EV_KEY, phys, 1)
                harness.feed(harness.mod.EV_KEY, phys, 0)
        assert transitions(harness.written, harness.mod, harness.va) == [1, 0] * 6
        assert transitions(harness.written, harness.mod, harness.vx) == [1, 0] * 6

    def test_nothing_is_left_held(self, harness):
        """A stuck-down virtual button is the worst failure mode for a fighter."""
        for phys, virt in ((harness.press, harness.va), (harness.top, harness.vx)):
            harness.feed(harness.mod.EV_KEY, phys, 1)
            harness.feed(harness.mod.EV_KEY, phys, 0)
            assert harness.ui._keys.get(virt, 0) == 0


class TestLostUpRecovery:
    """What actually happens under mash: the encoder's up disappears, downs arrive alone."""

    def test_down_while_held_becomes_a_pulse(self, harness):
        for _ in range(4):
            harness.feed(harness.mod.EV_KEY, harness.press, 1)
            harness.clock.ms(20)
        # 4 physical presses, zero ups in sight, still 4 edges a game can count
        assert transitions(harness.written, harness.mod, harness.va) == [1, 0, 1, 0, 1, 0, 1]

    def test_pulse_separates_release_from_press(self, harness):
        harness.feed(harness.mod.EV_KEY, harness.press, 1)
        harness.clock.ms(20)
        harness.feed(harness.mod.EV_KEY, harness.press, 1)
        assert [b[0] for b in batches(harness.written, harness.mod)] == [
            (harness.mod.EV_KEY, harness.va, 1),
            (harness.mod.EV_KEY, harness.va, 0),
            (harness.mod.EV_KEY, harness.va, 1),
        ]

    @pytest.mark.parametrize("presses", [50, 200])
    def test_recovery_count_matches_press_count(self, harness, presses):
        for _ in range(presses):
            harness.feed(harness.mod.EV_KEY, harness.press, 1)
            harness.clock.ms(16)
        downs = sum(1 for t, _c, v in harness.written if t == harness.mod.EV_KEY and v == 1)
        assert downs == presses


class TestDebounceBoundary:
    """The deliberate limit: a second down inside ~12 ms reads as USB bounce, not a press."""

    def test_repeats_inside_the_window_are_dropped(self, harness):
        for _ in range(4):
            harness.feed(harness.mod.EV_KEY, harness.press, 1)
            harness.clock.ms(6)
        assert transitions(harness.written, harness.mod, harness.va) == [1, 0, 1]

    def test_the_window_is_measured_from_the_last_accepted_press(self, harness):
        """Each dropped repeat does not push the deadline forward."""
        harness.feed(harness.mod.EV_KEY, harness.press, 1)
        harness.clock.ms(6)
        harness.feed(harness.mod.EV_KEY, harness.press, 1)  # dropped
        harness.clock.ms(8)
        harness.feed(harness.mod.EV_KEY, harness.press, 1)  # 14 ms after the first
        assert transitions(harness.written, harness.mod, harness.va) == [1, 0, 1]

    def test_just_outside_the_window_is_recovered(self, harness):
        harness.feed(harness.mod.EV_KEY, harness.press, 1)
        harness.clock.ms(13)
        harness.feed(harness.mod.EV_KEY, harness.press, 1)
        assert transitions(harness.written, harness.mod, harness.va) == [1, 0, 1]

    def test_exactly_12ms_falls_inside_due_to_float_arithmetic(self, harness):
        """The source says `< 0.012`, but 1000.012 - 1000.0 is 0.0119999... so it drops.

        Pinned so nobody "fixes" the boundary by accident and changes mash feel.
        """
        harness.feed(harness.mod.EV_KEY, harness.press, 1)
        harness.clock.ms(12)
        harness.feed(harness.mod.EV_KEY, harness.press, 1)
        assert transitions(harness.written, harness.mod, harness.va) == [1]

    def test_kernel_key_repeat_is_not_a_press(self, harness):
        harness.feed(harness.mod.EV_KEY, harness.press, 1)
        for _ in range(20):
            harness.feed(harness.mod.EV_KEY, harness.press, 2)
        assert transitions(harness.written, harness.mod, harness.va) == [1]


class TestMashCeiling:
    """The number the user asked for: presses per second that survive, per button."""

    def test_untouched_ups_are_not_rate_limited(self, harness):
        """With real ups the window never applies: 200 cycles in 200 ms all come out."""
        for _ in range(200):
            harness.feed(harness.mod.EV_KEY, harness.press, 1)
            harness.feed(harness.mod.EV_KEY, harness.press, 0)
            harness.clock.ms(5)
        assert transitions(harness.written, harness.mod, harness.va).count(1) == 200

    def test_above_the_window_every_other_press_survives(self, harness):
        """Measured, not derived: 40 downs-only presses at each rate, how many come out.

        Up to ~83/s (the window) everything survives. Past it the recovery degrades by
        halving rather than dropping to nothing: 120/s in gives 60/s out, because a down
        2 steps later is always outside the window. Degraded, not lost.
        """
        accepted = []
        for hz in (40, 60, 80, 100, 120):
            harness.reset()
            step = 1000.0 / hz
            for _ in range(40):
                harness.feed(harness.mod.EV_KEY, harness.press, 1)
                harness.clock.ms(step)
            accepted.append(
                (hz, sum(1 for t, _c, v in harness.written if t == harness.mod.EV_KEY and v == 1))
            )
        assert accepted == [(40, 40), (60, 40), (80, 40), (100, 20), (120, 20)]


class TestLevelSemanticsAreDeliberate:
    """What is NOT pulsed, and why that is the right call."""

    def test_hat_direction_repeat_produces_no_edge(self, harness):
        """The dpad is level state: a held direction must stay held, not flicker.

        Many cheap encoders re-send the same axis value while a direction is held; if the
        hat pulsed on those, every hold would look like mash to the game. So tap-dpad
        recovery is traded for hold reliability here — use --dpad-as-button for taps.
        """
        harness.feed(harness.mod.EV_ABS, harness.code("ABS_Y"), 255)
        harness.clock.ms(20)
        harness.feed(harness.mod.EV_ABS, harness.code("ABS_Y"), 255)
        hat_y = harness.mod.ABS_HAT0Y
        values = [v for t, c, v in harness.written if t == harness.mod.EV_ABS and c == hat_y]
        assert values == [values[0]]

    def test_button_mapped_dpad_does_recover_edges(self, mod):
        """Same encoder, --dpad-as-button: directions become keys, so they get the pulse."""
        clock = FakeClock()
        ui = object.__new__(mod.UInputXbox)
        ui.fd, ui._keys, ui._abs, ui._last_down_mono, ui._dirty = -1, {}, {}, {}, False
        written = []
        ui._write_event = lambda *args: written.append(args)
        real_time = mod.time
        mod.time = clock
        try:
            class P:
                def axis_range(self, _code):
                    return (0, 255)

            bridge = mod.Bridge(P(), ui, SPARKFUN_BUTTON_DPAS)
            code = mod.resolve_code("BTN_2")
            for _ in range(3):
                bridge.handle(mod.EV_KEY, code, 1)
                ui.flush()
                clock.ms(20)
            assert [v for t, _c, v in written if t == mod.EV_KEY].count(1) == 3
        finally:
            mod.time = real_time

    def test_button_mapped_as_analog_trigger_pulses(self, harness):
        """BTN_PINKIE → lt as an axis: the value saturates, so a repeat needs a pulse."""
        abs_z = harness.mod.ABS_Z
        for _ in range(3):
            harness.feed(harness.mod.EV_KEY, harness.code("BTN_PINKIE"), 1)
            harness.clock.ms(20)
        values = [v for t, c, v in harness.written if t == harness.mod.EV_ABS and c == abs_z]
        assert values.count(255) == 3, values


class TestThroughput:
    """Performance in the sense that matters here: draining a burst faster than it arrives."""

    def test_translation_is_far_faster_than_a_usb_poll(self, harness):
        burst = [
            (harness.mod.EV_KEY, code, 1 if i % 4 < 2 else 0)
            for i, code in enumerate([harness.press, harness.code("BTN_TOP")] * 500)
        ]
        started = time.perf_counter()
        for etype, code, value in burst:
            harness.bridge.handle(etype, code, value)
        harness.ui.flush()
        elapsed = time.perf_counter() - started
        per_event_us = elapsed / len(burst) * 1e6
        # The loop reads up to 512 events at a time; per-event cost must stay tiny or the
        # kernel client queue (~64 events) overflows and presses are lost for real.
        assert per_event_us < 100, f"{per_event_us:.1f} µs/event"
        assert len(burst) / elapsed > 100_000
