"""V1 interface: paste URL, choose a folder, monitor live aria2 progress."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from klepto_dl.core.formatting import byte_size, eta_text, speed_text
from klepto_dl.core.validation import (
    InputError,
    display_name,
    validate_destination,
    validate_url,
)
from klepto_dl.engine.aria2_rpc import DownloadSnapshot
from klepto_dl.ui.download_worker import DownloadWorker


STATUS_LABELS = {
    "active": "Downloading",
    "waiting": "Queued",
    "paused": "Paused",
    "complete": "Complete",
    "error": "Error",
    "removed": "Cancelled",
}


class MainWindow(QMainWindow):
    add_requested = Signal(str, str)
    control_requested = Signal(str, str)
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Klepto Local Downloader | V1")
        self.resize(990, 570)
        self._settings = QSettings("Klepto", "LocalDownloader")
        self._rows: dict[str, int] = {}
        self._sources: dict[str, tuple[str, str]] = {}
        self._states: dict[str, str] = {}
        self._shutdown_requested = False
        self._shutdown_complete = False
        self._build_ui()

        self._thread = QThread(self)
        self._worker = DownloadWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self.add_requested.connect(self._worker.add)
        self.control_requested.connect(self._worker.control)
        self.stop_requested.connect(self._worker.stop)
        self._worker.ready.connect(self._engine_ready)
        self._worker.added.connect(self._download_added)
        self._worker.updated.connect(self._download_updated)
        self._worker.operation_error.connect(self._operation_error)
        self._worker.fatal_error.connect(self._engine_error)
        self._worker.stopped.connect(self._thread.quit)
        self._thread.start()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)

        heading = QLabel("Local Download Manager")
        heading.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(heading)
        hint = QLabel("Direct HTTP/HTTPS downloads only in this milestone. No cloud account required.")
        layout.addWidget(hint)

        form = QGridLayout()
        form.setColumnStretch(1, 1)
        form.addWidget(QLabel("Direct URL"), 0, 0)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.org/files/archive.zip")
        self.url_input.returnPressed.connect(self._start_download)
        form.addWidget(self.url_input, 0, 1, 1, 2)

        form.addWidget(QLabel("Save into"), 1, 0)
        initial_dir = str(Path.home() / "Downloads")
        if not Path(initial_dir).is_dir():
            initial_dir = str(Path.home())
        self.folder_input = QLineEdit(str(self._settings.value("downloadFolder", initial_dir)))
        self.folder_input.setPlaceholderText(r"C:\Users\You\Downloads or E:\Downloads")
        form.addWidget(self.folder_input, 1, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        form.addWidget(browse, 1, 2)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Download")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._start_download)
        buttons.addWidget(self.add_button)
        buttons.addStretch(1)
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.cancel_button = QPushButton("Cancel")
        self.retry_button = QPushButton("Retry")
        for button in (self.pause_button, self.resume_button, self.cancel_button, self.retry_button):
            buttons.addWidget(button)
            button.setEnabled(False)
        self.pause_button.clicked.connect(lambda: self._control_selected("pause"))
        self.resume_button.clicked.connect(lambda: self._control_selected("resume"))
        self.cancel_button.clicked.connect(lambda: self._control_selected("cancel"))
        self.retry_button.clicked.connect(self._retry_selected)
        layout.addLayout(buttons)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["File", "Progress", "Status", "Downloaded", "Speed", "ETA"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table)

        self.status_label = QLabel("Starting local aria2 engine…")
        layout.addWidget(self.status_label)
        self.statusBar().showMessage("All downloads are stored on your computer.")

    @Slot()
    def _browse(self) -> None:
        start = self.folder_input.text() if Path(self.folder_input.text()).is_dir() else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Choose download folder", start)
        if selected:
            self.folder_input.setText(selected)

    @Slot()
    def _start_download(self) -> None:
        if not self.add_button.isEnabled():
            return
        try:
            url = validate_url(self.url_input.text())
            destination = str(validate_destination(self.folder_input.text()))
        except InputError as exc:
            QMessageBox.warning(self, "Check download details", str(exc))
            return
        self._settings.setValue("downloadFolder", destination)
        self.status_label.setText("Sending download to aria2…")
        self.add_requested.emit(url, destination)

    @Slot()
    def _engine_ready(self) -> None:
        self.add_button.setEnabled(True)
        self.status_label.setText("Ready. Paste a direct file URL to download.")

    @Slot(str, str, str)
    def _download_added(self, gid: str, url: str, destination: str) -> None:
        self._sources[gid] = (url, destination)
        self._ensure_row(gid, url)
        self.status_label.setText("Download added to the local queue.")
        self.url_input.clear()

    def _ensure_row(self, gid: str, source_url: str = "") -> int:
        if gid in self._rows:
            return self._rows[gid]
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[gid] = row
        self._set_cell(row, 0, display_name(source_url) if source_url else "Restored download")
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setMinimumWidth(155)
        self.table.setCellWidget(row, 1, progress)
        for column in (2, 3, 4, 5):
            self._set_cell(row, column, "--")
        return row

    def _set_cell(self, row: int, column: int, value: str) -> None:
        item = self.table.item(row, column)
        if item is None:
            item = QTableWidgetItem(value)
            self.table.setItem(row, column, item)
        else:
            item.setText(value)

    @Slot(object)
    def _download_updated(self, data: DownloadSnapshot) -> None:
        row = self._ensure_row(data.gid, data.source_uri)
        if data.source_uri and data.gid not in self._sources:
            self._sources[data.gid] = (data.source_uri, data.directory)
        if data.file_path:
            self._set_cell(row, 0, Path(data.file_path).name)
        self._states[data.gid] = data.status
        bar = self.table.cellWidget(row, 1)
        if isinstance(bar, QProgressBar):
            if data.total > 0:
                bar.setRange(0, 100)
                bar.setValue(min(100, int(100 * data.completed / data.total)))
            elif data.status == "active":
                bar.setRange(0, 0)  # size unknown, but bytes still update
            else:
                bar.setRange(0, 100)
                bar.setValue(100 if data.status == "complete" else 0)
        self._set_cell(row, 2, STATUS_LABELS.get(data.status, data.status))
        transferred = byte_size(data.completed)
        self._set_cell(row, 3, f"{transferred} / {byte_size(data.total)}" if data.total else transferred)
        self._set_cell(row, 4, speed_text(data.speed))
        self._set_cell(row, 5, eta_text(data.total, data.completed, data.speed))
        if data.status == "error" and data.error_message:
            self.table.item(row, 2).setToolTip(data.error_message)
            self.status_label.setText(f"Download failed: {data.error_message}")
        self._update_buttons()

    def _selected_gid(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return next((gid for gid, row_index in self._rows.items() if row_index == row), None)

    @Slot()
    def _update_buttons(self) -> None:
        gid = self._selected_gid()
        status = self._states.get(gid or "", "")
        self.pause_button.setEnabled(status in {"active", "waiting"})
        self.resume_button.setEnabled(status == "paused")
        self.cancel_button.setEnabled(status in {"active", "waiting", "paused"})
        self.retry_button.setEnabled(status == "error" and gid in self._sources)

    def _control_selected(self, action: str) -> None:
        gid = self._selected_gid()
        if gid:
            self.control_requested.emit(gid, action)

    @Slot()
    def _retry_selected(self) -> None:
        gid = self._selected_gid()
        if gid and gid in self._sources:
            url, directory = self._sources[gid]
            self.add_requested.emit(url, directory)

    @Slot(str)
    def _operation_error(self, message: str) -> None:
        self.status_label.setText(message)
        QMessageBox.warning(self, "Download operation failed", message)

    @Slot(str)
    def _engine_error(self, message: str) -> None:
        self.add_button.setEnabled(False)
        self.status_label.setText(message)
        QMessageBox.critical(self, "aria2 engine problem", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._shutdown_complete or not self._thread.isRunning():
            event.accept()
            return
        if not self._shutdown_requested:
            if any(s in {"active", "waiting"} for s in self._states.values()):
                choice = QMessageBox.question(
                    self,
                    "Leave downloads unfinished?",
                    "Running downloads will stop. aria2 saves unfinished transfers "
                    "so they can resume when you reopen the app. Close anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if choice != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            self._shutdown_requested = True
            self.add_button.setEnabled(False)
            self.status_label.setText("Saving download session and closing…")
            self.stop_requested.emit()
        event.ignore()

    @Slot()
    def _thread_finished(self) -> None:
        self._shutdown_complete = True
        self.close()
