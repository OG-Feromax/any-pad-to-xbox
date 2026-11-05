"""A hand-edited profiles.json must not be able to kill a pad in silence.

`resolve_code` raises KeyError on an unknown name, and the old Bridge.__init__ let it
escape mid-hotplug: the pad simply stopped becoming an Xbox controller, with a traceback
that named nothing. These tests pin the replacement — refuse the profile, name every bad
entry, and do it before any device is opened or grabbed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_FILE = REPO_ROOT / "packaging" / "xpad_bridge.py"
RUNNER_FILE = REPO_ROOT / "packaging" / "xboxdrv_runner.py"

VALID = {
    "name": "DragonRise",
    "evdev_keymap": {"BTN_THUMB": "a", "BTN_TOP2": "rt"},
    "evdev_absmap": {"ABS_X": "dpad_x"},
}


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bridge():
    return load(BRIDGE_FILE, "xpad_bridge_validation_test")


def profile_with(**changes) -> dict:
    profile = json.loads(json.dumps(VALID))
    profile.update(changes)
    return dict(profile)


class TestBuildMaps:
    def test_valid_profile_resolves_both_sides(self, bridge):
        keys, axes = bridge.build_maps(VALID)
        assert keys[bridge.resolve_code("BTN_THUMB")] == "a"
        assert axes[bridge.resolve_code("ABS_X")] == "dpad_x"

    def test_button_mapped_to_an_axis_is_valid(self, bridge):
        """rt is an EV_ABS target; rejecting it would break real profiles."""
        keys, _axes = bridge.build_maps(VALID)
        assert keys[bridge.resolve_code("BTN_TOP2")] == "rt"

    def test_empty_maps_are_not_an_error(self, bridge):
        assert bridge.build_maps({"name": "bare"}) == ({}, {})

    def test_unknown_button_name_is_named_in_the_error(self, bridge):
        with pytest.raises(ValueError) as exc:
            bridge.build_maps(profile_with(evdev_keymap={"BTN_NOTAREALKEY": "a"}))
        assert "BTN_NOTAREALKEY" in str(exc.value)
        assert "DragonRise" in str(exc.value)

    def test_unknown_target_is_rejected_too(self, bridge):
        """The emit path looks targets up in tables and would drop these presses quietly."""
        with pytest.raises(ValueError) as exc:
            bridge.build_maps(profile_with(evdev_keymap={"BTN_THUMB": "btn10"}))
        assert "btn10" in str(exc.value)

    def test_every_bad_entry_is_reported_at_once(self, bridge):
        """One typo should not hide the next: fixing a profile should take one pass."""
        with pytest.raises(ValueError) as exc:
            bridge.build_maps(
                profile_with(
                    evdev_keymap={"BTN_FAKE_ONE": "a", "BTN_THUMB": "nope"},
                    evdev_absmap={"ABS_FAKE_TWO": "dpad_x"},
                )
            )
        message = str(exc.value)
        for name in ("BTN_FAKE_ONE", "nope", "ABS_FAKE_TWO"):
            assert name in message

    def test_the_shipped_profiles_all_validate(self, bridge):
        """The guard must not reject any mapping this repo ships as an example."""
        example = json.loads((REPO_ROOT / "data" / "profiles.example.json").read_text())
        for key, profile in example["profiles"].items():
            bridge.build_maps(profile)

    def test_the_defaults_the_app_seeds_with_validate(self, bridge):
        """A fresh install seeds these; if one were unbridgeable the pad would look dead."""
        from any_pad_to_xbox.core.profiles import DEFAULT_PROFILES

        for profile in DEFAULT_PROFILES.values():
            bridge.build_maps(profile)


class TestRefusalHappensBeforeGrab:
    def test_missing_device_is_reported_as_missing(self, bridge, tmp_path):
        assert bridge.run_bridge(str(tmp_path / "absent"), VALID) == 1

    def test_bad_profile_exits_before_touching_the_device(self, bridge, tmp_path):
        """A regular file stands in for an event node: opening it would otherwise reach
        the 15x0.1 s grab retry, so a fast return proves validation ran first."""
        stand_in = tmp_path / "event99"
        stand_in.write_bytes(b"")
        broken = profile_with(evdev_keymap={"BTN_NOTAREALKEY": "a"})
        assert bridge.run_bridge(str(stand_in), broken) == 2
