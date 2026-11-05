"""Profile model + serialization: the file the bridge reads at hotplug time."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_profile

from any_pad_to_xbox.core.profiles import (
    Profile,
    _load_file,
    get_profile,
    normalize_id,
    profiles_to_system_json,
)


class TestProfileModel:
    def test_from_dict_lowercases_the_key(self):
        p = Profile.from_dict("0079:0006", {"name": "X"})
        assert p.key == "0079:0006"
        p = Profile.from_dict("1B4F:9206", {"name": "X"})
        assert p.key == "1b4f:9206"

    def test_missing_name_falls_back_to_the_id(self):
        assert Profile.from_dict("0079:0006", {}).name == "0079:0006"

    def test_profiles_are_enabled_by_default(self):
        """An entry without `enabled` must still work — absent means wanted."""
        assert Profile.from_dict("0079:0006", {"name": "X"}).enabled is True

    def test_dict_round_trip_is_lossless(self):
        original = make_profile(
            "1b4f:9206",
            "SparkFun",
            buttons={"BTN_1": "a", "BTN_9": "start"},
            axes={"ABS_X": "x1"},
        )
        original.slot = 3
        original.axismap = ["-Y1=Y1"]
        original.extra_opts = ["--dpad-as-button"]
        restored = Profile.from_dict(original.key, original.to_dict())
        assert restored == original

    def test_has_mapping(self):
        assert make_profile("0079:0006").has_mapping() is True
        assert make_profile("0079:0006", buttons={}, axes={}).has_mapping() is False
        assert make_profile("0079:0006", buttons={}, axes={"ABS_X": "dpad_x"}).has_mapping() is True

    def test_button_maps_are_invertible(self):
        p = make_profile("0079:0006", buttons={"BTN_THUMB": "a", "BTN_TOP": "x"}, axes={})
        assert p.xbox_to_evdev_buttons() == {"a": "BTN_THUMB", "x": "BTN_TOP"}


class TestNormalizeId:
    @pytest.mark.parametrize(
        "vendor,product,expected",
        [
            ("0079", "0006", "0079:0006"),
            ("1B4F", "9206", "1b4f:9206"),
            ("0x0079", "0x0006", "0079:0006"),
            ("0X1B4F", "0X9206", "1b4f:9206"),
        ],
    )
    def test_accepts_udev_and_sysfs_shapes(self, vendor, product, expected):
        assert normalize_id(vendor, product) == expected

    def test_missing_half_returns_none(self):
        assert normalize_id("0079", None) is None
        assert normalize_id(None, "0006") is None
        assert normalize_id("", "") is None

    def test_lookup_is_case_insensitive(self):
        pads = {"0079:0006": make_profile("0079:0006")}
        assert get_profile(pads, "0079", "0006") is not None
        assert get_profile(pads, "1234", "5678") is None


class TestSystemProfilesFile:
    """/etc/any-pad-to-xbox/profiles.json is read by the runner as root at hotplug."""

    def test_payload_shape_the_runner_expects(self, two_pads):
        payload = json.loads(profiles_to_system_json(two_pads))
        assert payload["version"] == 1
        assert payload["require_remote_access"] is False
        assert set(payload["profiles"]) == {"0079:0006", "1b4f:9206"}

    def test_keys_are_sorted_so_the_file_is_diffable(self, two_pads):
        text = profiles_to_system_json(two_pads)
        shuffled = {k: two_pads[k] for k in reversed(list(two_pads))}
        assert text == profiles_to_system_json(shuffled)
        assert text.index("0079:0006") < text.index("1b4f:9206")

    def test_ends_with_a_newline(self, two_pads):
        assert profiles_to_system_json(two_pads).endswith("\n")

    def test_round_trip_through_disk_is_idempotent(self, tmp_path: Path, two_pads):
        """Write → read → write must be byte-identical: re-Enable cannot drift."""
        first = profiles_to_system_json(two_pads)
        target = tmp_path / "profiles.json"
        target.write_text(first, encoding="utf-8")
        second = profiles_to_system_json(_load_file(target))
        assert second == first
        assert _load_file(target) == two_pads

    def test_empty_profiles_yields_empty_object(self):
        payload = json.loads(profiles_to_system_json({}))
        assert payload["profiles"] == {}

    def test_missing_file_loads_as_empty(self, tmp_path: Path):
        assert _load_file(tmp_path / "nope.json") == {}

    def test_legacy_file_without_profiles_wrapper_still_loads(self, tmp_path: Path):
        """_load_file accepts `raw.get("profiles", raw)` — older dumps lack the key."""
        legacy = tmp_path / "old.json"
        legacy.write_text(
            json.dumps({"0079:0006": {"name": "Fliperama", "evdev_keymap": {"BTN_THUMB": "a"}}}),
            encoding="utf-8",
        )
        loaded = _load_file(legacy)
        assert loaded["0079:0006"].name == "Fliperama"
        assert loaded["0079:0006"].has_mapping() is True
