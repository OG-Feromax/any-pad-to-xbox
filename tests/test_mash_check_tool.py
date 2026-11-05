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


class TestPollIntervalEstimate:
    """The number that dominates latency, and the A/B for the jspoll experiment."""

    def test_same_report_bursts_are_not_gaps(self, tool):
        # down and up of one tap share a report (microseconds apart); only the real
        # inter-report distances count, and they must not be dragged toward 0.
        stamps = [0.0, 0.00001, 0.008, 0.00802, 0.016]
        gaps = tool.report_gaps(stamps)
        assert len(gaps) == 2
        assert [round(g) for g in gaps] == [8, 8]

    def test_a_1ms_poll_keeps_its_1ms_gaps(self, tool):
        stamps = [i * 0.001 for i in range(10)]
        assert len(tool.report_gaps(stamps)) == 9

    def test_an_idle_pad_is_not_cadence(self, tool):
        """A 28-minute gap between two mash sessions measures the human, not the device."""
        stamps = [0.0, 0.008, 1727.058, 1727.066, 1727.074]
        gaps = tool.report_gaps(stamps)
        assert len(gaps) == 3
        assert all(round(g) == 8 for g in gaps)

    def test_picks_the_largest_fitting_interval_not_the_smallest(self, tool):
        """Every multiple of 8 is also a multiple of 4, 2 and 1 — smallest-fits always
        answers 1 and means nothing."""
        gaps = [16.0, 24.0, 40.0, 48.0, 64.0, 8.0, 8.0, 16.0] * 4
        assert tool.estimate_poll_interval(gaps)[0] == 8

    def test_a_genuine_1ms_lattice_reads_as_1(self, tool):
        gaps = [1.0, 2.0, 1.0, 3.0, 1.0, 2.0] * 6
        assert tool.estimate_poll_interval(gaps)[0] == 1

    def test_jitter_within_tolerance_still_fits(self, tool):
        gaps = [8.0, 8.2, 7.9, 16.1, 24.0, 48.2] * 8
        interval, fit = tool.estimate_poll_interval(gaps)
        assert interval == 8 and fit > 0.9

    def test_a_non_lattice_is_reported_as_none(self, tool):
        gaps = [7.213, 11.618, 23.417, 41.623, 61.281, 97.442, 5.317, 13.684] * 3
        assert tool.estimate_poll_interval(gaps)[0] is None

    def test_no_gaps_is_not_an_interval(self, tool):
        assert tool.estimate_poll_interval([]) == (None, 0.0)

    def test_report_prints_the_interval_and_the_sample_size(self, tool, tmp_path, capsys):
        log = tmp_path / "any-pad-bridge.event20.diag"
        log.write_text(
            "1.0 BRIDGE start pid=1\n"
            + "".join(f"{1 + i * 0.008:.6f} PHYS KEY BTN_THUMB down\n" for i in range(60)),
            encoding="utf-8",
        )
        tool.poll_report(log, None, 0)
        out = capsys.readouterr().out
        assert "poll interval: 8 ms (125 Hz)" in out
        assert "60 events" in out

    def test_thin_data_says_so_instead_of_guessing(self, tool, tmp_path, capsys):
        log = tmp_path / "x.diag"
        log.write_text(
            "1.0 BRIDGE start pid=1\n1.008 PHYS KEY BTN_THUMB down\n", encoding="utf-8"
        )
        assert tool.poll_report(log, None, 0) == 1
        assert "press the pad and try again" in capsys.readouterr().out

    def test_presses_outside_the_window_are_named_not_hidden(self, tool, tmp_path, capsys):
        """What actually happened to him: he pressed, the window missed it, output said 0."""
        body = "".join(f"{1 + i * 0.008:.6f} PHYS KEY BTN_THUMB down\n" for i in range(40))
        log = tmp_path / "any-pad-bridge.event20.diag"
        log.write_text("1.0 BRIDGE start pid=1\n" + body, encoding="utf-8")
        offset = len("1.0 BRIDGE start pid=1\n") + len(body)

        assert tool.poll_report(log, offset, 10) == 1
        out = capsys.readouterr().out
        assert "40 event(s) from *before* the window" in out
        assert "you pressed, just not while it counted" in out

    def test_an_old_log_is_called_stale_not_reported_as_a_result(self, tool, tmp_path, capsys):
        """The trap --now creates: a log from before the change reads like a measurement."""
        now = tool.time.time()
        log = tmp_path / "any-pad-bridge.event20.diag"
        log.write_text(
            "1.0 BRIDGE start pid=1\n"
            + "".join(
                f"{now - 3600 + i * 0.008:.6f} PHYS KEY BTN_THUMB down\n" for i in range(60)
            ),
            encoding="utf-8",
        )
        assert tool.poll_report(log, None, 0) == 1
        out = capsys.readouterr().out
        assert "STALE" in out and "60 min ago" in out

    def test_poll_refuses_when_diag_mode_is_off(self, tool, tmp_path, monkeypatch, capsys):
        """A countdown over a log nothing can write would only re-read an old session."""
        log = tmp_path / "any-pad-bridge.event20.diag"
        log.write_text("1.0 BRIDGE start pid=1\n", encoding="utf-8")
        monkeypatch.setattr(tool, "DIAG_DIR", tmp_path)
        monkeypatch.setattr(tool, "DIAG_LEGACY", tmp_path / "absent.diag")
        monkeypatch.setattr(tool, "DIAG_FLAG", tmp_path / "nope")
        assert tool.poll_run(10, wait=True) == 2
        err = capsys.readouterr().err
        assert "no exclusive grab" in err and "ANY_PAD_DIAG_NO_GRAB=1" in err

    def test_an_armed_but_idle_logger_waits_instead_of_refusing(self, tool, tmp_path, monkeypatch, capsys):
        """Idle is not the same as dead: the logger writes the moment he presses."""
        log = tmp_path / "any-pad-bridge.event20.diag"
        log.write_text("1.0 BRIDGE start pid=1\n", encoding="utf-8")
        old = os.stat(log).st_mtime - 3600
        os.utime(log, (old, old))
        flag = tmp_path / "diag_flag"
        flag.write_text("", encoding="utf-8")
        monkeypatch.setattr(tool, "DIAG_DIR", tmp_path)
        monkeypatch.setattr(tool, "DIAG_LEGACY", tmp_path / "absent.diag")
        monkeypatch.setattr(tool, "DIAG_FLAG", flag)
        monkeypatch.setattr(tool, "_countdown", lambda *a, **k: None)
        monkeypatch.setattr(tool, "poll_report", lambda path, offset, window: 0)
        assert tool.poll_run(10, wait=True) == 0
        assert "armed but idle" in capsys.readouterr().out

    def test_poll_waits_when_a_logger_is_live(self, tool, tmp_path, monkeypatch, capsys):
        """Delegates the wait to _countdown (whose ticks are tested separately). The marks
        must be taken *before* the wait — that is what scopes the report to the window."""
        live = tmp_path / "any-pad-bridge.event20.diag"
        header = "1.0 BRIDGE start pid=1\n"
        live.write_text(header, encoding="utf-8")
        flag = tmp_path / "diag_flag"
        flag.write_text("", encoding="utf-8")
        monkeypatch.setattr(tool, "DIAG_DIR", tmp_path)
        monkeypatch.setattr(tool, "DIAG_LEGACY", tmp_path / "absent.diag")
        monkeypatch.setattr(tool, "DIAG_FLAG", flag)
        seen = {}

        def fake_countdown(seconds, logs, marks, **kwargs):
            seen["seconds"] = seconds
            seen["marks"] = dict(marks)

        def fake_report(path, offset, window):
            seen["offset"] = offset
            return 0

        monkeypatch.setattr(tool, "_countdown", fake_countdown)
        monkeypatch.setattr(tool, "poll_report", fake_report)
        assert tool.poll_run(5, wait=True) == 0
        assert seen["seconds"] == 5
        assert seen["marks"] == {"event20": len(header)}  # marked before any pressing
        assert seen["offset"] == len(header)
        assert "press the pad continuously for 5s" in capsys.readouterr().out


class FakeClock:
    """Time that only moves when the code sleeps, and can do work as it does."""

    def __init__(self, on_first_sleep=None):
        self.now = 0.0
        self.slept = []
        self.on_first_sleep = on_first_sleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        first = not self.slept
        self.slept.append(seconds)
        self.now += seconds
        if first and self.on_first_sleep:
            self.on_first_sleep()


class TestCountdownFeedback:
    """A silent sleep is why his presses fell outside the window."""

    def test_it_reports_bytes_written_during_the_wait(self, tool, tmp_path, capsys):
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("x" * 10, encoding="utf-8")
        clock = FakeClock(on_first_sleep=lambda: path.write_text("x" * 500, encoding="utf-8"))

        tool._countdown(3, [("event20", path)], {"event20": 10}, clock=clock, tick=1.0)

        out = capsys.readouterr().out
        assert "2s left, 490 bytes logged" in out
        assert "0s left, 490 bytes logged" in out

    def test_it_counts_nothing_written_as_nothing_written(self, tool, tmp_path, capsys):
        """The useful signal he lacked: 0 bytes means he did not press in the window."""
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("x" * 10, encoding="utf-8")
        clock = FakeClock()

        tool._countdown(2, [("event20", path)], {"event20": 10}, clock=clock, tick=1.0)

        assert "0 bytes logged" in capsys.readouterr().out

    def test_it_never_prints_a_negative_countdown(self, tool, tmp_path, capsys):
        path = tmp_path / "any-pad-bridge.event20.diag"
        path.write_text("", encoding="utf-8")
        clock = FakeClock()

        tool._countdown(1.5, [("event20", path)], {"event20": 0}, clock=clock, tick=1.0)

        out = capsys.readouterr().out
        assert "0s left" in out and "-1s" not in out


class TestGrabDetection:
    """--latency needs to read the physical node, which is impossible under the grab.

    It returned a bare "no samples" instead, indistinguishable from nobody pressing.
    """

    REAL = (
        "/usr/bin/python3\0/usr/local/lib/any-pad-to-xbox/xpad_bridge.py\0event20\0"
        "--profile-json\0{\"name\":\"DragonRise\"}\0"
    )
    DIAG = REAL + "--no-grab\0--diag-log\0/tmp/any-pad-bridge.event20.diag\0"

    def test_bridge_holding_the_grab_is_recognised(self, tool):
        assert tool.parse_bridge_cmdline(self.REAL) == ("event20", True)

    def test_diag_mode_bridge_is_not_holding_the_grab(self, tool):
        assert tool.parse_bridge_cmdline(self.DIAG) == ("event20", False)

    @pytest.mark.parametrize(
        "cmd",
        [
            "bash\0-c\0echo hi\0",
            "python3\0/usr/local/lib/any-pad-to-xbox/xpad_bridge.py\0--help\0",
            "",
        ],
    )
    def test_anything_else_is_not_a_bridge(self, tool, cmd):
        assert tool.parse_bridge_cmdline(cmd) is None

    def test_latency_refuses_with_the_reason_and_the_way_out(
        self, tool, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setattr(
            tool,
            "load_profiles",
            lambda: {"0079:0006": {"name": "DR", "enabled": True, "evdev_keymap": {}}},
        )
        monkeypatch.setattr(
            tool, "find_physical_nodes", lambda ids: [("0079:0006", Path("/dev/input/event20"))]
        )
        monkeypatch.setattr(tool, "grab_state_of", lambda name: True)
        assert tool.main(["--latency"]) == 2
        err = capsys.readouterr().err
        assert "grabbed by the bridge" in err
        assert "ANY_PAD_DIAG_NO_GRAB=1" in err


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


@pytest.fixture(scope="module")
def runner():
    path = REPO_ROOT / "packaging" / "xboxdrv_runner.py"
    loader = importlib.machinery.SourceFileLoader("xboxdrv_runner_under_test", str(path))
    spec = importlib.util.spec_from_loader("xboxdrv_runner_under_test", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestDiagLogNamingContract:
    """The runner writes the filename; this tool parses the node back out of it.

    Writer and reader live in different files, so a rename on one side silently breaks
    attribution on the other — exactly the kind of drift this repo had today.
    """

    @pytest.mark.parametrize("node", ["event20", "event0", "event128"])
    def test_written_name_is_discoverable(self, tool, runner, tmp_path, node):
        written = runner.diag_log_path(node)
        assert written.parent == runner.BRIDGE_DIAG_LOG.parent, "must stay in /tmp"
        target = tmp_path / written.name
        target.write_text("1.0 BRIDGE start pid=1\n", encoding="utf-8")
        assert tool.diag_logs(tmp_path) == [(node, target)]

    def test_two_pads_get_two_different_files(self, runner):
        """Same path with mode 'w' would make the second bridge truncate the first."""
        assert runner.diag_log_path("event20") != runner.diag_log_path("event21")

    def test_name_still_ends_in_diag(self, runner):
        assert runner.diag_log_path("event20").suffix == ".diag"


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
