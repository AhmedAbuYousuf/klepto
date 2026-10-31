"""Qt application entrypoint."""
from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication

from klepto_dl.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Klepto Local Downloader")
    window = MainWindow()
    window.show()
    return app.exec()
