"""Run on Windows after installing PySide6; skipped without Qt."""
import os
import time

import pytest

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from klepto_dl.ui.download_worker import DownloadWorker
from klepto_dl.ui.main_window import MainWindow


def test_gui_can_open_and_close_without_real_aria2(monkeypatch):
    # Keep Qt on the offscreen plugin during tests, including on Windows.
    # The actual app still uses the native Windows platform.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(DownloadWorker, "start", lambda self: self.ready.emit())
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    for _ in range(40):
        app.processEvents()
        if window.add_button.isEnabled():
            break
        time.sleep(0.02)
    assert window.add_button.isEnabled()
    assert window.table.rowCount() == 0
    window.close()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and window._thread.isRunning():
        app.processEvents()
        time.sleep(0.02)
    assert not window._thread.isRunning()
