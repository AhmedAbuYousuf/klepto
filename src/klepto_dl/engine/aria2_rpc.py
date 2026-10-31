"""Own a local aria2c subprocess and talk to its private JSON-RPC endpoint.

This object is created on a Qt worker thread, not the GUI thread.
Only HTTP(S) URLs are accepted by the UI in V1.
"""
from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class EngineError(RuntimeError):
    """An aria2 process or RPC error."""


@dataclass(frozen=True)
class DownloadSnapshot:
    gid: str
    status: str
    completed: int
    total: int
    speed: int
    file_path: str = ""
    source_uri: str = ""
    directory: str = ""
    error_message: str = ""

    @classmethod
    def from_rpc(cls, data: dict[str, Any]) -> "DownloadSnapshot":
        files = data.get("files") or []
        first = files[0] if files else {}
        uris = first.get("uris") or []
        return cls(
            gid=str(data["gid"]),
            status=str(data.get("status", "unknown")),
            completed=int(data.get("completedLength", 0)),
            total=int(data.get("totalLength", 0)),
            speed=int(data.get("downloadSpeed", 0)),
            file_path=str(first.get("path", "")),
            source_uri=str(uris[0].get("uri", "")) if uris else "",
            directory=str(data.get("dir", "")),
            error_message=str(data.get("errorMessage", "")),
        )


def find_aria2c() -> str:
    """Prefer explicit executable, then bundled tools, then PATH."""
    override = os.getenv("ARIA2C_PATH")
    project_root = Path(__file__).resolve().parents[3]
    candidates = [
        Path(override) if override else None,
        project_root / "tools" / "aria2c.exe",
        project_root / "tools" / "aria2c",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return str(candidate)
    on_path = shutil.which("aria2c")
    if on_path:
        return on_path
    raise EngineError(
        "aria2c was not found. Put aria2c.exe in the project's tools folder, "
        "add it to PATH, or set ARIA2C_PATH. See README.md."
    )


def _unused_local_port() -> int:
    # There is a narrow bind race between releasing this port and launching aria2.
    # If something else wins it, startup fails rather than connecting without auth.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    if not 1024 <= port <= 65535:
        raise EngineError("Could not allocate an RPC port.")
    return port


def _app_state_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        root = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return root / "KleptoLocalDownloader"


class Aria2RPC:
    def __init__(self, executable: str | None = None, state_dir: Path | None = None):
        self._executable = executable
        self._state_dir = state_dir
        self._process: subprocess.Popen | None = None
        self._client: httpx.Client | None = None
        self._token = ""
        self._endpoint = ""
        self._stderr_file = None
        self._session: Path | None = None

    def start(self) -> None:
        if self._process is not None:
            raise EngineError("aria2 is already running for this application.")
        exe = self._executable or find_aria2c()
        state = self._state_dir or _app_state_dir()
        state.mkdir(parents=True, exist_ok=True)
        session = state / "aria2-session.txt"
        self._session = session
        port = _unused_local_port()
        self._token = secrets.token_hex(32)
        self._endpoint = f"http://127.0.0.1:{port}/jsonrpc"
        args = [
            exe,
            "--no-conf=true",
            "--enable-rpc=true",
            "--rpc-listen-all=false",
            "--rpc-allow-origin-all=false",
            f"--rpc-listen-port={port}",
            f"--rpc-secret={self._token}",
            "--console-log-level=warn",
            "--summary-interval=0",
            "--continue=true",
            "--auto-file-renaming=false",
            "--allow-overwrite=false",
            "--max-concurrent-downloads=3",
            "--max-connection-per-server=4",
            "--split=4",
            "--min-split-size=1M",
            "--auto-save-interval=10",
            "--follow-torrent=false",
            "--follow-metalink=false",
            f"--save-session={session}",
            "--save-session-interval=30",
        ]
        if session.is_file():
            args.append(f"--input-file={session}")
        self._stderr_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr_file,
                creationflags=flags,
            )
            self._client = httpx.Client(timeout=1.5, trust_env=False)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    self._stderr_file.seek(0)
                    detail = self._stderr_file.read()[-900:].strip()
                    raise EngineError(f"aria2c could not start: {detail or 'process exited'}")
                try:
                    self.call("getVersion")
                    return
                except (httpx.HTTPError, EngineError):
                    time.sleep(0.12)
            raise EngineError("aria2c did not open its local RPC interface within 8 seconds.")
        except Exception:
            self.stop()
            raise

    def call(self, method: str, *args: Any) -> Any:
        if self._client is None:
            raise EngineError("Download engine is not connected.")
        request = {
            "jsonrpc": "2.0",
            "id": "klepto",
            "method": f"aria2.{method}",
            "params": [f"token:{self._token}", *args],
        }
        response = self._client.post(self._endpoint, json=request)
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise EngineError("Download engine returned invalid JSON.") from exc
        if "error" in body:
            problem = body["error"]
            raise EngineError(str(problem.get("message", problem)))
        if "result" not in body:
            raise EngineError("Download engine response was missing a result.")
        return body["result"]

    def add(self, url: str, directory: str) -> str:
        return str(self.call("addUri", [url], {"dir": directory}))

    def tell_status(self, gid: str) -> DownloadSnapshot:
        return DownloadSnapshot.from_rpc(self.call("tellStatus", gid))

    def list_existing(self) -> list[DownloadSnapshot]:
        rows: list[dict[str, Any]] = []
        rows.extend(self.call("tellActive"))
        rows.extend(self.call("tellWaiting", 0, 100))
        rows.extend(self.call("tellStopped", 0, 100))
        return [DownloadSnapshot.from_rpc(row) for row in rows]

    def control(self, gid: str, action: str) -> None:
        method = {"pause": "pause", "resume": "unpause", "cancel": "remove"}.get(action)
        if method is None:
            raise EngineError(f"Unsupported action: {action}")
        self.call(method, gid)

    def stop(self) -> None:
        """Gracefully exit so aria2 can save its session and .aria2 control files."""
        process = self._process
        if process is not None:
            if process.poll() is None:
                try:
                    self.call("shutdown")
                except (httpx.HTTPError, EngineError, ValueError):
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._stderr_file is not None:
            self._stderr_file.close()
            self._stderr_file = None
        self._process = None
