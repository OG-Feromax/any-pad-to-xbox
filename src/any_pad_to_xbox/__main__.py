"""Entry point: the UI by default, install/apply helpers on the command line.

The CLI helpers exist so the system state can be synced without opening Qt. They only
*render* what `core.installer` decides — same script the GUI's Enable runs — and they
never edit the pad config: an existing `/etc/any-pad-to-xbox/profiles.json` is left
alone, because the GUI is the thing that edits it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _example_profiles_file() -> Path | None:
    from any_pad_to_xbox import REPO_ROOT

    for candidate in (
        REPO_ROOT / "data" / "profiles.example.json",
        Path("data/profiles.example.json"),
    ):
        if candidate.exists():
            return candidate
    return None


def _cli_profiles() -> dict:
    """Pads the script should describe: whatever is installed, else the bundled example."""
    from any_pad_to_xbox import SYSTEM_PROFILES
    from any_pad_to_xbox.core.profiles import _load_file

    if SYSTEM_PROFILES.exists():
        return _load_file(SYSTEM_PROFILES)
    example = _example_profiles_file()
    return _load_file(example) if example else {}


def _render_script() -> str:
    from any_pad_to_xbox.core.installer import (
        InstallSources,
        generate_artifacts,
        render_install_script,
    )

    return render_install_script(
        generate_artifacts(_cli_profiles()),
        sources=InstallSources.resolve(),
        restart_connected=True,
        preserve_existing_profiles=True,
    )


def _stale_paths() -> list[Path]:
    """Installed files that differ from what this build would write."""
    from any_pad_to_xbox.core.installer import InstallSources, drift

    return drift(_cli_profiles(), sources=InstallSources.resolve())


def _cli_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="any-pad-to-xbox",
        description="Map generic joysticks to virtual Xbox 360 pads.",
    )
    parser.add_argument(
        "--print-script",
        action="store_true",
        help="Write the privileged install script to stdout and exit (run as root).",
    )
    parser.add_argument(
        "--reapply",
        action="store_true",
        help="Run the privileged install script through pkexec (asks for password).",
    )
    args = parser.parse_args(argv)

    if args.print_script and args.reapply:
        parser.error("--print-script and --reapply are mutually exclusive")
    if not (args.print_script or args.reapply):
        parser.error("nothing to do — see --help")

    script = _render_script()
    if args.print_script:
        sys.stdout.write(script)
        return 0

    from any_pad_to_xbox.core.installer import failure_message, run_privileged

    stale = _stale_paths()
    if not stale:
        # Applying would ask for a password and restart the bridge, blinking the
        # virtual pad out of any running game, to write bytes that are already there.
        print("System already matches this build — nothing to apply.")
        return 0
    from any_pad_to_xbox import DIAG_NO_GRAB_FLAG

    print(
        f"Updating {len(stale)} file(s):\n  "
        + "\n  ".join(
            f"{p}  (diagnostics no-grab flag)" if p == DIAG_NO_GRAB_FLAG else str(p)
            for p in stale
        )
    )

    result = run_privileged(script)
    if result.returncode != 0:
        print(failure_message(result), file=sys.stderr)
        return result.returncode
    print("System integration reapplied.")
    return 0


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1].startswith("-"):
        sys.exit(_cli_main(sys.argv[1:]))

    from PySide6.QtWidgets import QApplication

    from any_pad_to_xbox.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Any Pad to Xbox")
    app.setOrganizationName("any-pad-to-xbox")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
