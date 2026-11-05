"""Tests for scripts/mash-check — the tool that answers "did every press survive?".

A measurement tool that is itself untested produces confident nonsense, so the event
parser and the PHYS-vs-EMIT differ are pinned here with synthetic data.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "scripts" / "mash-check"


def load_tool():
    loader = importlib.machinery.SourceFileLoader("mash_check", str(TOOL))
    spec = importlib.util.spec_from_loader("mash_check", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    return load_tool()


def pack(etype: int, code: int, value: int, tv_sec: int = 1, tv_usec: int = 0) -> bytes:
    return struct.pack("llHHi", tv_sec, tv_usec, etype, code, value)


class TestToolIsStdlibOnly:
    def test_runs_without_the_venv(self, tool):
        """Like the bridge, it has to work on any machine with just /usr/bin/python3."""
        import ast
        import sys as _sys

        names: set[str] = set()
        for node in ast.walk(ast.parse(TOOL.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names.add((node.module or "").split(".")[0])
        external = names - set(_sys.stdlib_module_names)
        assert not external, f"mash-check needs a pip package: {sorted(external)}"


class TestEventParsing:
    def test_unpacks_a_real_event_frame(self, tool):
        r, w = os.pipe()
        try:
            os.write(w, pack(tool.EV_KEY, 304, 1) + pack(tool.EV_KEY, 304, 0))
            events = list(tool._drain(r))
        finally:
            os.close(r)
            os.close(w)
        assert [(etype, code, value) for _ts, etype, code, value in events] == [
            (tool.EV_KEY, 304, 1),
            (tool.EV_KEY, 304, 0),
        ]

    def test_carries_a_wall_clock_timestamp(self, tool):
        r, w = os.pipe()
        try:
            os.write(w, pack(tool.EV_KEY, 304, 1, tv_sec=7, tv_usec=500_000))
            ts = next(iter(tool._drain(r)))[0]
        finally:
            os.close(r)
            os.close(w)
        assert ts == pytest.approx(7.5)

    def test_nonblocking_fd_yields_nothing(self, tool):
        r, w = os.pipe()
        os.set_blocking(r, False)
        try:
            assert list(tool._drain(r)) == []
        finally:
            os.close(r)
            os.close(w)

    def test_partial_frame_is_dropped_not_misread(self, tool):
        r, w = os.pipe()
        try:
            os.write(w, pack(tool.EV_KEY, 304, 1)[:10])
            events = list(tool._drain(r))
        finally:
            os.close(r)
            os.close(w)
        assert events == []


class TestVirtualNodeDiscovery:
    def test_returns_paths_or_nothing(self, tool):
        nodes = tool.find_virtual_nodes()
        assert isinstance(nodes, list)
        assert all(str(n).startswith("/dev/input/event") for n in nodes)


class TestPressTally:
    def test_counts_zero_to_one_transitions(self, tool):
        events = [
            (1.0, tool.EV_KEY, 304, 1),
            (1.1, tool.EV_KEY, 304, 0),
            (1.2, tool.EV_KEY, 304, 1),
            (1.3, tool.EV_KEY, 304, 0),
        ]
        downs, stuck = tool.tally(events)
        assert downs[304] == [1.0, 1.2]
        assert stuck == set()

    def test_timestamps_come_from_the_kernel_not_from_arrival(self, tool):
        """Gaps are measured between event stamps, so scheduling cannot skew them."""
        downs, _ = tool.tally([(5.5, tool.EV_KEY, 304, 1), (9.5, tool.EV_KEY, 304, 0)])
        assert downs[304] == [5.5]

    def test_a_repeated_down_without_up_is_not_a_second_press(self, tool):
        """The kernel may deliver value 1 twice; the game sees one held button."""
        downs, _stuck = tool.tally([(1.0, tool.EV_KEY, 304, 1), (1.1, tool.EV_KEY, 304, 1)])
        assert len(downs[304]) == 1

    def test_reports_buttons_left_down(self, tool):
        _downs, stuck = tool.tally([(1.0, tool.EV_KEY, 304, 1)])
        assert stuck == {304}

    def test_ignores_axis_and_sync_lines(self, tool):
        downs, _stuck = tool.tally(
            [(1.0, tool.EV_SYN, 0, 0), (1.0, 0x03, 17, 1), (1.1, tool.EV_KEY, 304, 1)]
        )
        assert list(downs) == [304]


def phys_downs(tool, bridge, lines) -> int:
    """Count physical presses in a set of log lines (the data layer, not the printout)."""
    return sum(tool.count_downs(bridge, lines)[0].values())


DIAG_PROFILES = {
    "0079:0006": {
        "name": "DragonRise",
        "evdev_keymap": {"BTN_THUMB": "a", "BTN_TOP": "x", "BTN_BASE2": "b"},
        "evdev_absmap": {"ABS_Y": "dpad_y"},
    },
    # A second pad whose BTN_0 lands on the same virtual code 305 as the first pad's
    # BTN_BASE2. Reports must not mix the two.
    "1b4f:9206": {"name": "SparkFun", "evdev_keymap": {"BTN_0": "b"}, "evdev_absmap": {}},
}


@pytest.fixture(scope="module")
def bridge(tool):
    return tool.load_bridge_module()


@pytest.fixture
def system(tool, monkeypatch, tmp_path):
    """A /tmp-like dir with one attributed diag log and the profiles behind it."""
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps({"version": 1, "profiles": DIAG_PROFILES}), encoding="utf-8"
    )
    monkeypatch.setattr(tool, "SYSTEM_PROFILES", profiles)
    monkeypatch.setattr(tool, "USER_PROFILES", tmp_path / "absent.json")
    monkeypatch.setattr(tool, "DIAG_DIR", tmp_path)
    monkeypatch.setattr(tool, "DIAG_LEGACY", tmp_path / "legacy.diag")
    monkeypatch.setattr(tool, "pad_id", lambda node: "0079:0006" if node == "event20" else None)
    return tmp_path


class TestWindowing:
    """--diag must measure the countdown, not everything the bridge already logged."""

    def test_offset_keeps_only_what_arrived_after_it(self, tool, tmp_path, bridge):
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("1.0 BRIDGE start pid=1\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            for i in range(4):
                handle.write(f"1.{i} PHYS KEY BTN_THUMB down\n")
        mark = path.stat().st_size
        with path.open("a", encoding="utf-8") as handle:
            for i in range(3):
                handle.write(f"2.{i} PHYS KEY BTN_THUMB down\n")

        before, _ = tool.read_since(path, mark, 10)
        whole, _ = tool.read_since(path, None, 10)
        assert phys_downs(tool, bridge, before) == 3
        assert phys_downs(tool, bridge, whole) == 7

    def test_scope_says_so(self, tool, tmp_path, bridge):
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("1.0 BRIDGE start pid=1\n1.0 PHYS KEY BTN_THUMB down\n", encoding="utf-8")
        assert tool.read_since(path, path.stat().st_size, 10)[1] == "the last 10s only"
        assert tool.read_since(path, None)[1] == "the whole session"

    def test_a_truncated_log_is_not_read_as_silence(self, tool, tmp_path, bridge):
        """The bridge reopens mode 'w' on start, so the old mark can be past EOF."""
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("1.0 BRIDGE start pid=1\n1.0 PHYS KEY BTN_THUMB down\n", encoding="utf-8")
        lines, scope = tool.read_since(path, 10_000)
        assert "restarted" in scope
        assert phys_downs(tool, bridge, lines) == 1


class TestDiagDiff:
    """Per-pad PHYS-vs-virtual equivalence, joined on code numbers, scoped to one profile."""

    def log_for(self, tool, tmp_path, bridge, presses, emitted, pulse=0, pad="0079:0006"):
        """Build a log using the bridge's own name tables — the point of these tests."""
        phys_names = {
            "0079:0006": bridge._code_name(bridge.resolve_code("BTN_THUMB")),
            "1b4f:9206": bridge._code_name(bridge.resolve_code("BTN_0")),
        }[pad]
        virt = bridge._code_name(bridge.XBOX_BTN_CODES["a"] if pad == "0079:0006" else bridge.XBOX_BTN_CODES["b"])
        lines = ["1.0 BRIDGE start pid=1"]
        lines += [f"1.{i:03d} PHYS KEY {phys_names} down" for i in range(presses)]
        lines += [f"1.{i:03d} EMIT KEY {virt} down" for i in range(emitted)]
        lines += [f"1.{i:03d} PULSE KEY {virt} down" for i in range(pulse)]
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_matching_counts_are_lossless(self, tool, system, tmp_path, bridge, capsys):
        path = self.log_for(tool, tmp_path, bridge, presses=3, emitted=2, pulse=1)
        assert tool.report_pad("event20", path, bridge) == 0
        out = capsys.readouterr().out
        assert "lossless" in out and "EVERY press accounted for." in out
        assert "/dev/input/event20 [0079:0006]" in out

    def test_other_pads_buttons_are_not_dragged_in(self, tool, system, tmp_path, bridge, capsys):
        """The bug this replaced printed BTN_0 (another pad) as '21 extra' presses."""
        path = self.log_for(tool, tmp_path, bridge, presses=2, emitted=2)
        assert tool.report_pad("event20", path, bridge) == 0
        out = capsys.readouterr().out
        assert "CODE_256" not in out and "SparkFun" not in out

    def test_shared_virtual_code_is_counted_once(self, tool, system, tmp_path, bridge, capsys):
        """Two physical buttons → one virtual target must be one row, sums added."""
        lines = ["1.0 BRIDGE start pid=1"]
        for name in ("BTN_THUMB", "BTN_TOP", "BTN_BASE2"):
            code = bridge._code_name(bridge.resolve_code(name))
            lines.append(f"1.001 PHYS KEY {code} down")
        for btn in ("BTN_A", "BTN_X", "BTN_B"):
            lines.append(f"1.002 EMIT KEY {btn} down")
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert tool.report_pad("event20", path, bridge) == 0

    def test_a_missing_emit_is_reported_as_lost(self, tool, system, tmp_path, bridge, capsys):
        path = self.log_for(tool, tmp_path, bridge, presses=3, emitted=1)
        assert tool.report_pad("event20", path, bridge) == 2
        out = capsys.readouterr().out
        assert "2 lost" in out and "2 press(es) unaccounted for." in out

    def test_axis_mapped_controls_are_declared_not_silently_dropped(
        self, tool, system, tmp_path, bridge, capsys
    ):
        path = self.log_for(tool, tmp_path, bridge, presses=1, emitted=1)
        tool.report_pad("event20", path, bridge)
        assert "ABS_Y→dpad_y" in capsys.readouterr().out

    def test_button_mapped_to_an_axis_counts_the_ramp(self, tool, system, tmp_path, bridge, capsys):
        """A button on `lt` leaves as EV_ABS: counting only KEY output would call it lost."""
        # `system` already points SYSTEM_PROFILES at this file; only the content changes.
        (tmp_path / "profiles.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": {
                        "0079:0006": {"name": "DR", "evdev_keymap": {"BTN_PINKIE": "lt"}}
                    },
                }
            ),
            encoding="utf-8",
        )
        phys = bridge._code_name(bridge.resolve_code("BTN_PINKIE"))
        lines = ["1.0 BRIDGE start pid=1"]
        for i in range(4):
            lines.append(f"1.{i:03d} PHYS KEY {phys} down")
            lines.append(f"1.{i:03d} EMIT ABS ABS_Z value=255")
            lines.append(f"1.{i + 10:03d} EMIT ABS ABS_Z value=0")
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert tool.report_pad("event20", path, bridge) == 0
        out = capsys.readouterr().out
        assert "lossless" in out and "ABS_Z (axis)" in out

    def test_legacy_log_is_attributed_when_only_one_profile_fits(
        self, tool, system, tmp_path, bridge, capsys
    ):
        """No node in the filename, but the codes present belong to exactly one pad."""
        (tmp_path / "legacy.diag").write_text(
            "1.0 BRIDGE start pid=1\n"
            "1.001 PHYS KEY BTN_THUMB down\n"
            "1.002 EMIT KEY BTN_A down\n",
            encoding="utf-8",
        )
        assert tool.diag_run(0, wait=False) == 0
        out = capsys.readouterr().out
        assert "inferred from the codes in the log" in out
        assert "EVERY press accounted for." in out

    def test_codes_no_profile_explains_refuse_to_guess(self, tool, system, tmp_path, capsys):
        """BTN_THUMB and BTN_0 belong to different pads: no single profile covers both."""
        (tmp_path / "legacy.diag").write_text(
            "1.0 BRIDGE start pid=1\n"
            "1.001 PHYS KEY BTN_THUMB down\n"
            "1.002 PHYS KEY BTN_0 down\n",
            encoding="utf-8",
        )
        assert tool.diag_run(0, wait=False) == 0
        assert "totals only" in capsys.readouterr().out

    def test_unresolvable_names_are_reported_not_dropped(self, tool, system, tmp_path, bridge, capsys):
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text(
            "1.0 BRIDGE start pid=1\n1.001 PHYS KEY NOT_A_CODE down\n", encoding="utf-8"
        )
        tool.report_pad("event20", path, bridge)
        assert "NOT_A_CODE" in capsys.readouterr().out

    def test_log_without_presses_says_so(self, tool, system, tmp_path, bridge, capsys):
        path = self.log_for(tool, tmp_path, bridge, presses=0, emitted=0)
        assert tool.report_pad("event20", path, bridge) == 0
        assert "no press arrived during" in capsys.readouterr().out

    def test_stale_log_is_warned_about(self, tool, system, tmp_path, bridge, capsys):
        path = self.log_for(tool, tmp_path, bridge, presses=1, emitted=1)
        old = path.stat().st_mtime - 3600
        os.utime(path, (old, old))
        tool.report_pad("event20", path, bridge)
        assert "WARNING" in capsys.readouterr().out

    def test_discovery_prefers_per_node_logs(self, tool, system, tmp_path, bridge):
        self.log_for(tool, tmp_path, bridge, presses=1, emitted=1)
        (tmp_path / "legacy.diag").write_text("1.0 BRIDGE start pid=1\n", encoding="utf-8")
        assert tool.diag_logs(tmp_path) == [("event20", tmp_path / "any-pad-bridge.event20.diag")]

    def test_diag_waits_by_default(self, tool, system, tmp_path, bridge, monkeypatch, capsys):
        """This is what the user tripped on: --diag has to give time to mash."""
        self.log_for(tool, tmp_path, bridge, presses=1, emitted=1)
        slept = []
        monkeypatch.setattr(tool.time, "sleep", lambda s: slept.append(s))
        assert tool.diag_run(7, wait=True) == 0
        assert slept == [7]
        assert "Mash now" in capsys.readouterr().out

    def test_now_skips_the_wait(self, tool, system, tmp_path, bridge, monkeypatch, capsys):
        self.log_for(tool, tmp_path, bridge, presses=1, emitted=1)
        slept = []
        monkeypatch.setattr(tool.time, "sleep", lambda s: slept.append(s))
        assert tool.diag_run(7, wait=False) == 0
        assert slept == []

    def test_no_log_at_all_explains_the_sequence(self, tool, system, tmp_path, capsys):
        assert tool.diag_run(1, wait=False) == 2
        err = capsys.readouterr().err
        assert "ANY_PAD_DIAG_NO_GRAB=1" in err and "click Enable" in err


class TestRiseTally:
    """Classifying frames into presses on each side.

    This path is what crashed on real hardware: the tool used EV_ABS without ever defining
    it, so the first dpad or trigger event raised NameError. Nothing else exercised it --
    the live run had no events at all, which is why "no samples" looked like a pass.
    """

    def test_ev_abs_is_a_real_constant(self, tool):
        assert (tool.EV_SYN, tool.EV_KEY, tool.EV_ABS) == (0x00, 0x01, 0x03)

    def test_physical_key_rise_goes_to_the_physical_side(self, tool):
        phys, virt = tool.tally_rises([("phys", 1.0, tool.EV_KEY, 304, 1)], set())
        assert phys == [(1.0, 304)] and virt == []

    def test_axis_ramp_counts_as_one_press_not_one_per_value(self, tool):
        frames = [
            ("virt", 1.0, tool.EV_ABS, 0x02, 90),
            ("virt", 1.1, tool.EV_ABS, 0x02, 200),
            ("virt", 1.2, tool.EV_ABS, 0x02, 255),
            ("virt", 1.3, tool.EV_ABS, 0x02, 0),
            ("virt", 1.4, tool.EV_ABS, 0x02, 255),
        ]
        _phys, virt = tool.tally_rises(frames, {0x02})
        assert [ts for ts, _code in virt] == [1.0, 1.4]

    def test_axis_values_outside_the_map_are_ignored(self, tool):
        _phys, virt = tool.tally_rises([("virt", 1.0, tool.EV_ABS, 0x00, 255)], {0x02})
        assert virt == []

    def test_releases_and_autorepeat_are_not_presses(self, tool):
        frames = [
            ("phys", 1.0, tool.EV_KEY, 304, 0),
            ("phys", 1.1, tool.EV_KEY, 304, 2),
            ("phys", 1.2, tool.EV_SYN, 0, 0),
        ]
        phys, _virt = tool.tally_rises(frames, set())
        assert phys == []

    def test_end_to_end_pairing_from_frames(self, tool):
        """Frames in, latency out — the shape --latency actually reports."""
        frames = [
            ("phys", 1.000, tool.EV_KEY, 289, 1),
            ("virt", 1.006, tool.EV_KEY, 304, 1),
            ("phys", 2.000, tool.EV_KEY, 293, 1),
            ("virt", 2.010, tool.EV_ABS, 0x02, 255),
        ]
        phys, virt = tool.tally_rises(frames, {0x02})
        deltas, lost = tool.pair_latencies(phys, virt, {289: 304, 293: 0x02})
        assert deltas == [pytest.approx(6.0), pytest.approx(10.0)]
        assert lost == 0


class TestLatencyPairing:
    """The number he asked for: delay from the physical event to the virtual one."""

    PAIRS = {289: 304, 293: 0x02}  # BTN_THUMB→BTN_A, BTN_PINKIE→ABS_Z

    def test_delta_is_physical_to_virtual(self, tool):
        deltas, lost = tool.pair_latencies([(1.000, 289)], [(1.004, 304)], self.PAIRS)
        assert deltas == [pytest.approx(4.0)]
        assert lost == 0

    def test_earliest_pending_press_answers_first(self, tool):
        deltas, _lost = tool.pair_latencies(
            [(1.000, 289), (1.002, 289)], [(1.005, 304), (1.009, 304)], self.PAIRS
        )
        assert deltas == [pytest.approx(5.0), pytest.approx(7.0)]

    def test_a_swallowed_press_is_reported_not_folded_into_latency(self, tool):
        """One lost press must not make every later press on that button look slow."""
        deltas, lost = tool.pair_latencies(
            [(1.000, 289), (2.000, 289)], [(2.003, 304)], self.PAIRS
        )
        assert deltas == [pytest.approx(3.0)]
        assert lost == 1

    def test_presses_outside_the_map_are_ignored(self, tool):
        deltas, lost = tool.pair_latencies([(1.0, 999)], [(1.5, 304)], self.PAIRS)
        assert deltas == [] and lost == 0

    def test_axis_target_counts_as_a_press(self, tool):
        deltas, _lost = tool.pair_latencies([(1.000, 293)], [(1.012, 0x02)], self.PAIRS)
        assert deltas == [pytest.approx(12.0)]

    def test_stats_shape(self, tool):
        assert tool.stats([]) == "no samples"
        line = tool.stats([1.0, 2.0, 3.0, 4.0])
        assert "n=4" in line and "median 3.00" in line and "max 4.00 ms" in line

    def test_no_pad_gives_the_diag_mode_hint(self, tool, monkeypatch, capsys):
        monkeypatch.setattr(tool, "load_profiles", lambda: {})
        monkeypatch.setattr(tool, "find_physical_nodes", lambda ids: [])
        assert tool.main(["--latency"]) == 2
        assert "ANY_PAD_DIAG_NO_GRAB=1" in capsys.readouterr().err


class TestStuckDetection:
    def test_a_button_left_down_is_reported(self, tool, capsys):
        tool._report({304: [1.0, 2.0]}, {304}, 10.0)
        out = capsys.readouterr().out
        assert "STUCK DOWN at exit: a" in out
        assert "lossless" not in out

    def test_press_rate_and_fastest_gap_are_printed(self, tool, capsys):
        tool._report({304: [1.0, 1.05, 1.07]}, set(), 10.0)
        out = capsys.readouterr().out
        assert "0.3" in out, "expected 3 presses over 10 s to print as 0.3 press/s"
        assert "20.0 ms" in out, "expected the 1.07-1.05 gap as the fastest"
        assert "STUCK" not in out
