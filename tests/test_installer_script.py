"""The one rendered root script — what replaced three hand-written installers.

Before this, `install-system.sh`, `install_integration()` and `apply_profiles()` each
carried their own copy of "what gets installed", and they disagreed: the shell installer
never wrote the udev rules, so a pull that changed rule generation left `/etc` on the
old rules silently. These tests pin the artifact set, the shell safety, and the fact that
the script is self-contained enough to be captured and run later.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import make_profile, root_imports

from any_pad_to_xbox import (
    BRIDGE_PATH,
    DIAG_NO_GRAB_FLAG,
    RUNNER_PATH,
    SERVICE_PATH,
    SYSTEM_CONFIG_DIR,
    SYSTEM_PROFILES,
    UDEV_HIDE_RULES_PATH,
    UDEV_RULES_PATH,
)
from any_pad_to_xbox.core.installer import (
    TMP_VAR,
    GeneratedArtifacts,
    InstallSources,
    _event_node,
    generate_artifacts,
    install_possible,
    render_install_script,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
PACKAGING = REPO_ROOT / "packaging"

PROFILES = {
    "0079:0006": make_profile("0079:0006", "DragonRise Fliperama"),
    "1b4f:9206": make_profile("1b4f:9206", "SparkFun Pro Micro"),
}

# Every file the running system is made of. An installer that skips one leaves a
# half-updated machine that still looks healthy.
GENERATED_ARTIFACTS = (SYSTEM_PROFILES, UDEV_RULES_PATH, UDEV_HIDE_RULES_PATH)
SOURCE_ARTIFACTS = (RUNNER_PATH, BRIDGE_PATH, SERVICE_PATH)


@pytest.fixture
def artifacts() -> GeneratedArtifacts:
    return generate_artifacts(PROFILES)


@pytest.fixture
def sources() -> InstallSources:
    """The checkout's own packaging files, as a source install would see them."""
    return InstallSources(
        runner=PACKAGING / "xboxdrv_runner.py",
        bridge=PACKAGING / "xpad_bridge.py",
        unit=PACKAGING / "xboxdrv@.service",
    )


def render(artifacts, *, sources=None, **kwargs) -> str:
    return render_install_script(
        artifacts, sources=sources if sources is not None else InstallSources(), **kwargs
    )


def bash_syntax_ok(script: str, tmp_path: Path) -> str:
    target = tmp_path / "rendered.sh"
    target.write_text(script, encoding="utf-8")
    result = subprocess.run(
        ["bash", "-n", str(target)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return str(target)


class TestArtifactSetIsFixed:
    @pytest.mark.parametrize("target", GENERATED_ARTIFACTS, ids=lambda p: p.name)
    def test_generated_files_are_always_installed(self, artifacts, target: Path):
        """No entry point may skip these — that is precisely how the rules went stale."""
        assert str(target) in render(artifacts)

    @pytest.mark.parametrize("target", SOURCE_ARTIFACTS, ids=lambda p: p.name)
    def test_sources_are_installed_when_present(self, artifacts, sources, target: Path):
        assert str(target) in render(artifacts, sources=sources)

    def test_missing_sources_are_skipped_not_fatal(self, artifacts):
        """An AUR install has no `packaging/` in the wheel; its files are already placed."""
        text = render(artifacts)
        for target in SOURCE_ARTIFACTS:
            assert str(target) not in text
        assert str(UDEV_HIDE_RULES_PATH) in text

    def test_config_dir_and_bin_dir_are_created(self, artifacts):
        text = render(artifacts)
        assert f"install -d -m 755 {SYSTEM_CONFIG_DIR}" in text
        assert f"install -d -m 755 {RUNNER_PATH.parent}" in text

    def test_checkout_carries_the_three_sources(self):
        """If these get renamed, InstallSources.resolve() silently installs nothing."""
        resolved = InstallSources.resolve()
        assert resolved.runner and resolved.bridge and resolved.unit
        assert resolved.runner.name == "xboxdrv_runner.py"


class TestSelfContained:
    """`install-system.sh` captures the script, then runs it — nothing may be left behind.

    A renderer that stages files in its own temp dir produces a script full of dangling
    references, which only fails once root executes it.
    """

    def test_generated_content_rides_inside_the_script(self, artifacts):
        text = render(artifacts)
        assert artifacts.udev_rules.strip() in text
        assert artifacts.hide_rules.strip() in text
        assert artifacts.profiles_json.strip() in text
        assert 'ENV{ID_INPUT_JOYSTICK}=""' in text

    def test_no_install_reads_a_path_that_does_not_exist_yet(self, artifacts, sources):
        text = render(artifacts, sources=sources)
        for source in re.findall(r'^install -m [0-6][0-9]{2} "([^"]+)"', text, re.M):
            if source.startswith(f"${{{TMP_VAR}}}"):
                continue
            assert Path(source).exists(), f"dangling reference: {source}"

    def test_scratch_dir_is_created_and_cleaned_up_by_the_script(self, artifacts):
        text = render(artifacts)
        assert f'{TMP_VAR}="$(mktemp -d)"' in text
        assert f"trap 'rm -rf \"${{{TMP_VAR}}}\"' EXIT" in text

    def test_bash_accepts_the_script(self, artifacts, sources, tmp_path: Path):
        bash_syntax_ok(render(artifacts, sources=sources, restart_connected=True), tmp_path)

    def test_preamble_materializes_the_generated_files(self, artifacts, tmp_path: Path):
        """Actually run the non-privileged part: heredoc → real files, byte for byte.

        String matching cannot prove bash heredoc semantics (trailing newlines, quoting),
        and this is the part that broke when the content lived in the renderer's temp dir.
        """
        lines = render(artifacts).splitlines(keepends=True)
        cut = next(i for i, ln in enumerate(lines) if ln.startswith("install -d"))
        # Keep the mktemp + heredocs, drop the cleanup trap so we can read the result.
        preamble = "".join(ln for ln in lines[:cut] if not ln.startswith("trap "))
        target = tmp_path / "preamble.sh"
        target.write_text(preamble, encoding="utf-8")

        result = subprocess.run(
            ["bash", str(target)],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "TMPDIR": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr

        written = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file()}
        written.pop("preamble.sh", None)
        assert written == {
            SYSTEM_PROFILES.name: artifacts.profiles_json,
            UDEV_RULES_PATH.name: artifacts.udev_rules,
            UDEV_HIDE_RULES_PATH.name: artifacts.hide_rules,
        }

    def test_bash_accepts_source_paths_needing_quotes(self, artifacts, tmp_path: Path):
        hostile = tmp_path / "we ird$dir/with'quote"
        sources = InstallSources(
            runner=hostile / "xboxdrv_runner.py",
            bridge=hostile / "xpad_bridge.py",
            unit=hostile / "xboxdrv@.service",
        )
        bash_syntax_ok(render(artifacts, sources=sources), tmp_path)

    def test_source_paths_are_single_arguments(self, artifacts, tmp_path: Path):
        spaced = tmp_path / "a b"
        sources = InstallSources(runner=spaced / "xboxdrv_runner.py")
        text = render(artifacts, sources=sources)
        for target in (spaced / "xboxdrv_runner.py", RUNNER_PATH):
            line = next((ln for ln in text.splitlines() if str(target) in ln), None)
            assert line is not None, f"nothing installs {target}"
            assert str(target) in shlex.split(line), f"not a single argument: {line}"


class TestShellSafety:
    def test_event_node_must_be_a_real_event_device(self):
        assert _event_node("/dev/input/event20") == "event20"
        assert _event_node("event3") == "event3"

    @pytest.mark.parametrize(
        "bad",
        ["event20; rm -rf /", 'event20"$(id)', "/dev/input/js0", "event", "event2o", ""],
    )
    def test_rejects_names_that_would_break_out_of_quotes(self, bad):
        with pytest.raises(ValueError):
            _event_node(bad)

    def test_renderer_refuses_a_poisoned_start_event(self, artifacts):
        with pytest.raises(ValueError):
            render(artifacts, start_event="/dev/input/event9$(whoami)")

    def test_legacy_purge_runs_on_every_path(self, artifacts, sources):
        """Enable used to purge xboxdrv too; a refactor must not quietly drop it."""
        assert "systemctl mask xboxdrv.service" in render(artifacts, sources=sources)
        assert (
            "systemctl mask xboxdrv.service"
            in render(artifacts, sources=sources, start_event="/dev/input/event20")
        )

    def test_heredocs_are_quoted_so_nothing_is_interpolated(self, artifacts):
        """Profiles can carry user-typed names; `$` there must stay literal."""
        text = render(artifacts)
        for marker in re.findall(r"<<'([A-Z_]+)'", text):
            assert re.search(rf"^{marker}$", text, re.M), f"unclosed heredoc: {marker}"


class TestPolicyKnobs:
    def test_preserving_profiles_wraps_the_write(self, artifacts):
        assert f"if [[ ! -f {SYSTEM_PROFILES} ]]" in render(
            artifacts, preserve_existing_profiles=True
        )

    def test_apply_writes_profiles_unconditionally(self, artifacts):
        assert f"if [[ ! -f {SYSTEM_PROFILES} ]]" not in render(
            artifacts, preserve_existing_profiles=False
        )

    def test_diag_flag_is_touched_or_removed(self, artifacts):
        assert f"touch {DIAG_NO_GRAB_FLAG}" in render(artifacts, diag_no_grab=True)
        assert f"rm -f {DIAG_NO_GRAB_FLAG}" in render(artifacts, diag_no_grab=False)

    def test_restart_connected_embeds_quoted_python(self, artifacts):
        text = render(artifacts, restart_connected=True)
        assert "python3 - <<'PY'" in text
        assert "xboxdrv@{ev.name}.service" in text
        assert "python3 - <<'PY'" not in render(artifacts)

    def test_stop_event_targets_that_unit_only(self, artifacts):
        text = render(artifacts, stop_event="/dev/input/event7")
        assert "systemctl stop 'xboxdrv@event7.service'" in text
        assert "systemctl start" not in text

    def test_start_event_waits_for_the_grab_to_be_released(self, artifacts):
        text = render(artifacts, start_event="/dev/input/event7")
        assert "systemctl start 'xboxdrv@event7.service'" in text
        assert "is-active --quiet" in text


class TestReloadOrdering:
    def test_rules_reload_before_trigger(self, artifacts):
        text = render(artifacts)
        assert text.index("udevadm control --reload") < text.index("udevadm trigger")

    def test_daemon_reload_after_unit_is_written(self, artifacts, sources):
        text = render(artifacts, sources=sources)
        assert text.index(str(SERVICE_PATH)) < text.index("systemctl daemon-reload")

    def test_strict_mode_is_the_first_thing_in_the_script(self, artifacts):
        lines = render(artifacts).splitlines()
        assert lines[0] == "#!/bin/bash"
        assert lines[1] == "set -euo pipefail"


class TestHeadlessPathNeedsNoVenv:
    """`install-system.sh` runs the renderer as root with the *system* python."""

    @pytest.mark.parametrize(
        "module",
        [
            "any_pad_to_xbox/__init__.py",
            "any_pad_to_xbox/core/installer.py",
            "any_pad_to_xbox/core/udev.py",
            "any_pad_to_xbox/core/profiles.py",
        ],
    )
    def test_imports_are_stdlib_or_intra_package(self, module: str):
        external = root_imports(SRC / module) - sys.stdlib_module_names - {"any_pad_to_xbox"}
        assert not external, f"{module} needs a pip package: {sorted(external)}"

    def test_qt_is_only_imported_by_the_ui_branch(self):
        """`--print-script` must work before `uv sync` has ever run."""
        tree = ast.parse((SRC / "any_pad_to_xbox/__main__.py").read_text(encoding="utf-8"))
        in_functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(child, (ast.Import, ast.ImportFrom)) and "PySide6" in ast.dump(child)
                for child in ast.walk(node)
            )
        }
        assert in_functions == {"main"}

    def test_print_script_runs_on_the_system_python(self):
        """End to end, the way root actually invokes it — no venv on the path."""
        system_python = Path("/usr/bin/python3")
        if not system_python.exists():
            pytest.skip("no /usr/bin/python3 on this box")
        version_ok = subprocess.run(
            [
                str(system_python),
                "-c",
                "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)",
            ],
            check=False,
        ).returncode == 0
        if not version_ok:
            pytest.skip("system python is older than the project's 3.11 minimum")

        result = subprocess.run(
            [str(system_python), "-m", "any_pad_to_xbox", "--print-script"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": str(SRC)},
        )
        assert result.returncode == 0, result.stderr
        assert str(UDEV_HIDE_RULES_PATH) in result.stdout
        assert str(SERVICE_PATH) in result.stdout

    def test_install_system_sh_delegates_instead_of_reimplementing(self):
        text = (PACKAGING / "install-system.sh").read_text(encoding="utf-8")
        assert "--print-script" in text
        # If someone re-adds hand-written install lines here, the drift can come back.
        assert "install -m" not in text
        assert "rules.d" not in text


class TestInstallDecision:
    """When is an install allowed to run at all?"""

    def test_source_checkout_can_install(self):
        assert install_possible(InstallSources.resolve(), package_managed=False) is True

    def test_missing_sources_with_files_in_place_can_still_apply(self):
        """The AUR case: no `packaging/` in the wheel, pacman already put the files down.

        Refusing here dead-ends the user — the UI routes them to Install whenever
        /etc/any-pad-to-xbox/profiles.json is missing, and that file is what the install
        creates.
        """
        assert install_possible(InstallSources(), package_managed=True) is True

    def test_nothing_to_write_fails_loudly(self):
        """Neither sources nor an existing install: there is no usable script here."""
        assert install_possible(InstallSources(), package_managed=False) is False


class TestDiagNoGrabEnvVar:
    """It used to be a source constant, so enabling it meant editing code then re-applying."""

    @pytest.fixture(autouse=True)
    def _restore_module_state(self):
        """`reload` mutates the live package; put it back however the test ends."""
        yield
        import importlib

        import any_pad_to_xbox

        importlib.reload(any_pad_to_xbox)

    def _reload(self):
        import importlib

        import any_pad_to_xbox

        return importlib.reload(any_pad_to_xbox).DIAG_NO_GRAB

    def test_enabled_by_env_var(self, monkeypatch):
        monkeypatch.setenv("ANY_PAD_DIAG_NO_GRAB", "1")
        assert self._reload() is True

    @pytest.mark.parametrize("value", ["true", "YES", "on", " 1 "])
    def test_accepts_common_truthy_spellings(self, monkeypatch, value):
        monkeypatch.setenv("ANY_PAD_DIAG_NO_GRAB", value)
        assert self._reload() is True

    @pytest.mark.parametrize("value", ["", "0", "off", "maybe"])
    def test_off_by_default_and_for_nonsense(self, monkeypatch, value):
        monkeypatch.setenv("ANY_PAD_DIAG_NO_GRAB", value)
        assert self._reload() is False
