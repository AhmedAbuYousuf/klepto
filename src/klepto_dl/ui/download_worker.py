"""All aria2 operations and polling are performed off the GUI thread."""
from __future__ import annotations

import httpx
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from klepto_dl.engine.aria2_rpc import Aria2RPC, DownloadSnapshot, EngineError


class DownloadWorker(QObject):
    ready = Signal()
    fatal_error = Signal(str)
    operation_error = Signal(str)
    added = Signal(str, str, str)  # gid, original URL, chosen destination
    updated = Signal(object)  # DownloadSnapshot
    stopped = Signal()

    def __init__(self, engine: Aria2RPC | None = None):
        super().__init__()
        self._engine = engine or Aria2RPC()
        self._timer: QTimer | None = None
        self._gids: set[str] = set()
        self._online = False

    @Slot()
    def start(self) -> None:
        try:
            self._engine.start()
            self._online = True
            for snapshot in self._engine.list_existing():
                self._gids.add(snapshot.gid)
                self.updated.emit(snapshot)
            self._timer = QTimer(self)
            self._timer.setInterval(500)
            self._timer.timeout.connect(self.poll)
            self._timer.start()
            self.ready.emit()
        except (EngineError, OSError, httpx.HTTPError) as exc:
            self._online = False
            self.fatal_error.emit(str(exc))

    @Slot(str, str)
    def add(self, url: str, directory: str) -> None:
        if not self._online:
            self.operation_error.emit("Download engine is not ready.")
            return
        try:
            gid = self._engine.add(url, directory)
            self._gids.add(gid)
            self.added.emit(gid, url, directory)
            self.poll()
        except (EngineError, OSError, httpx.HTTPError) as exc:
            self.operation_error.emit(f"Could not add download: {exc}")

    @Slot(str, str)
    def control(self, gid: str, action: str) -> None:
        try:
            self._engine.control(gid, action)
            self.poll()
        except (EngineError, OSError, httpx.HTTPError) as exc:
            self.operation_error.emit(f"{action.capitalize()} failed: {exc}")

    @Slot()
    def poll(self) -> None:
        if not self._online:
            return
        try:
            for gid in list(self._gids):
                self.updated.emit(self._engine.tell_status(gid))
        except (EngineError, httpx.HTTPError, OSError) as exc:
            # The RPC may have stopped. Prevent repeat modal dialogs.
            self._online = False
            if self._timer is not None:
                self._timer.stop()
            self.fatal_error.emit(f"Lost contact with aria2c: {exc}")

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._online = False
        try:
            self._engine.stop()
        finally:
            self.stopped.emit()
