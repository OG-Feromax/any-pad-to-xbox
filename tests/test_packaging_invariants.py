"""Contracts between files that never fail loudly until a pad is plugged in.

The bridge runs under the *system* python outside the venv, the udev rules reference a
systemd unit by name, and the unit references the runner by path. Each of those links is
a plain string in a different file — nothing checks them at runtime, so they are checked
here.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from conftest import make_profile

from any_pad_to_xbox import BRIDGE_PATH, RUNNER_PATH, SERVICE_PATH, UDEV_RULES_PATH
from any_pad_to_xbox.core.system import generate_udev_rules

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGING = REPO_ROOT / "packaging"

BRIDGE = PACKAGING / "xpad_bridge.py"
RUNNER = PACKAGING / "xboxdrv_runner.py"
UNIT = PACKAGING / "xboxdrv@.service"


def root_imports(path: Path) -> set[str]:
    """Top-level module names imported by a file (relative imports ignored)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names.add((node.module or "").split(".")[0])
    return {n for n in names if n}


@pytest.mark.parametrize("script", [BRIDGE, RUNNER], ids=lambda p: p.name)
def test_runs_on_system_python_with_no_venv_deps(script: Path):
    """The runner execs `/usr/bin/python3 .../xpad_bridge.py` — outside the venv.

    Importing PySide6 or evdev here would install fine and then fail at hotplug with
    only a log line, so stdlib-only is a hard requirement, not a style choice.
    """
    third_party = root_imports(script) - sys.stdlib_module_names
    assert not third_party, f"{script.name} imports non-stdlib: {sorted(third_party)}"


class TestPathContracts:
    def test_unit_starts_the_installed_runner(self):
        """check_system() decides the install is done by grepping this string."""
        text = UNIT.read_text(encoding="utf-8")
        assert str(RUNNER_PATH) in text

    def test_runner_falls_back_to_the_installed_bridge(self):
        text = RUNNER.read_text(encoding="utf-8")
        assert str(BRIDGE_PATH) in text

    def test_unit_is_a_template_matching_the_rules(self):
        """`xboxdrv@%k.service` in the rules only resolves if the unit is a template."""
        assert SERVICE_PATH.name == UNIT.name
        assert UNIT.name.startswith("xboxdrv@") and UNIT.name.endswith(".service")
        assert "[Install]" in UNIT.read_text(encoding="utf-8")

    def test_generated_rules_want_the_unit_template_by_instance_name(self, two_pads):
        rules = generate_udev_rules(two_pads)
        assert "xboxdrv@%k.service" in rules
        # SERVICE_PATH is already the template name ("xboxdrv@.service"), so the stem
        # keeps the "@" and the rule's instance form is stem + "%k.service".
        assert SERVICE_PATH.name.removesuffix(".service") in rules
        assert f"{SERVICE_PATH.name.removesuffix('.service')}%k.service" in rules

    def test_runner_installs_the_unit_that_rules_reference(self):
        """install-system.sh and apply_profiles must agree on the unit's destination."""
        installer = (PACKAGING / "install-system.sh").read_text(encoding="utf-8")
        assert str(SERVICE_PATH) in installer


class TestBridgeRulesAreWellFormed:
    """udev parses these files; one bad quote disables every rule in it."""

    @pytest.fixture
    def rules_text(self, two_pads) -> str:
        return generate_udev_rules(two_pads)

    @staticmethod
    def rule_lines(text: str) -> list[str]:
        return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]

    def test_quotes_are_balanced(self, rules_text):
        for line in self.rule_lines(rules_text):
            assert line.count('"') % 2 == 0, f"unbalanced quotes: {line}"

    def test_braces_are_balanced(self, rules_text):
        """ATTRS{} / ENV{} need doubled braces — a lost one yields invalid syntax."""
        for line in self.rule_lines(rules_text):
            assert line.count("{") == line.count("}"), f"unbalanced braces: {line}"

    def test_every_rule_line_names_a_subsystem(self, rules_text):
        for line in self.rule_lines(rules_text):
            assert 'SUBSYSTEM=="input"' in line

    def test_vendor_and_product_are_hex_four_digits(self, rules_text):
        for key in ("0079:0006", "1b4f:9206"):
            vendor, product = key.split(":")
            assert f'ATTRS{{idVendor}}=="{vendor}"' in rules_text
            assert f'ATTRS{{idProduct}}=="{product}"' in rules_text

