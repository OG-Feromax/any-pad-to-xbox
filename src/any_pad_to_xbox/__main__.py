"""Entry point for any-pad-to-xbox UI."""

from __future__ import annotations

import sys


def main() -> None:
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
