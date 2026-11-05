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


class TestDiagDiff:
    """The strict PHYS-vs-virtual equivalence, joined on code numbers."""

    PROFILE = {"0079:0006": {"evdev_keymap": {"BTN_THUMB": "a"}, "evdev_absmap": {"ABS_Y": "dpad_y"}}}

    @pytest.fixture
    def bridge(self, tool):
        return tool.load_bridge_module()

    def names(self, bridge):
        phys = bridge.resolve_code("BTN_THUMB")
        virt = bridge.XBOX_BTN_CODES["a"]
        return bridge._code_name(phys), bridge._code_name(virt)

    def write_case(self, tool, monkeypatch, tmp_path, bridge, presses, emitted, pulse=0):
        profiles = tmp_path / "profiles.json"
        profiles.write_text(
            json.dumps({"version": 1, "profiles": self.PROFILE}), encoding="utf-8"
        )
        monkeypatch.setattr(tool, "SYSTEM_PROFILES", profiles)
        monkeypatch.setattr(tool, "USER_PROFILES", tmp_path / "absent.json")
        phys, virt = self.names(bridge)
        lines = ["1.0 BRIDGE start pid=1"]
        lines += [f"1.{i:03d} PHYS KEY {phys} down" for i in range(presses)]
        lines += [f"1.{i:03d} EMIT KEY {virt} down" for i in range(emitted)]
        lines += [f"1.{i:03d} PULSE KEY {virt} down" for i in range(pulse)]
        log = tmp_path / "bridge.diag"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        monkeypatch.setattr(tool, "DIAG_LOG", log)
        return log

    def test_matching_counts_are_lossless(self, tool, monkeypatch, tmp_path, bridge, capsys):
        self.write_case(tool, monkeypatch, tmp_path, bridge, presses=3, emitted=2, pulse=1)
        assert tool.diag_report(10) == 0
        out = capsys.readouterr().out
        assert "lossless" in out and "EVERY press accounted for." in out

    def test_pulse_lines_count_as_recognized_presses(self, tool, monkeypatch, tmp_path, bridge, capsys):
        """Recovery is not a bug: down-while-held emits PULSE up+down and is still one press."""
        self.write_case(tool, monkeypatch, tmp_path, bridge, presses=4, emitted=1, pulse=3)
        tool.diag_report(10)
        assert "EVERY press accounted for." in capsys.readouterr().out

    def test_a_missing_emit_is_reported_as_lost(self, tool, monkeypatch, tmp_path, bridge, capsys):
        self.write_case(tool, monkeypatch, tmp_path, bridge, presses=3, emitted=1)
        tool.diag_report(10)
        out = capsys.readouterr().out
        assert "2 lost" in out and "2 press(es) unaccounted for" in out

    def test_axis_mapped_controls_are_declared_out_of_scope(
        self, tool, monkeypatch, tmp_path, bridge, capsys
    ):
        self.write_case(tool, monkeypatch, tmp_path, bridge, presses=1, emitted=1)
        tool.diag_report(10)
        assert "ABS_Y→dpad_y" in capsys.readouterr().out

    def test_stale_log_is_warned_about(self, tool, monkeypatch, tmp_path, bridge, capsys):
        log = self.write_case(tool, monkeypatch, tmp_path, bridge, presses=1, emitted=1)
        old = log.stat().st_mtime - 3600
        os.utime(log, (old, old))
        tool.diag_report(10)
        assert "WARNING" in capsys.readouterr().out

    def test_empty_log_explains_next_step(self, tool, monkeypatch, tmp_path, bridge, capsys):
        log = self.write_case(tool, monkeypatch, tmp_path, bridge, presses=0, emitted=0)
        log.write_text("1.0 BRIDGE start pid=1\n", encoding="utf-8")
        assert tool.diag_report(10) == 1
        assert "no PHYS KEY lines" in capsys.readouterr().err

    def test_missing_diag_log_tells_how_to_enable_it(self, tool, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(tool, "DIAG_LOG", tmp_path / "absent.diag")
        assert tool.diag_report(10) == 2
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
