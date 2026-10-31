# Klepto Local Downloader — V1, Milestone 1

A free, local-first desktop downloader using **Python 3.12+**, **PySide6**, and **aria2c**. This repository covers the *first usable V1 milestone*: direct HTTP/HTTPS downloads, folder selection, and live progress. It also has basic pause/resume/cancel/retry and an aria2 session file for graceful restart. It does **not** scan webpages, scrape video, or integrate a browser yet.

## Folder layout

```text
local-download-manager-v1/
├── pyproject.toml                 # Python dependencies and entry point
├── src/klepto_dl/
│   ├── app.py                     # QApplication entry
│   ├── core/validation.py         # URL and download-folder checks
│   ├── core/formatting.py         # Size, transfer speed and ETA
│   ├── engine/aria2_rpc.py        # aria2 process lifecycle + JSON-RPC
│   └── ui/
│       ├── download_worker.py    # Background thread worker + polling
│       └── main_window.py        # PySide6 widgets and download table
├── tests/                         # Tests for parsing, RPC, and UI smoke
└── tools/                         # Optional aria2c.exe location
```

## Windows + VS Code: exact setup

1. Install Python **3.12 or newer** with `py` launcher, and VS Code with the Python extension.
2. Download and extract this source ZIP into an ordinary user-owned folder, for example `E:\Projects\local-download-manager-v1` (or `C:\Projects\...`). Open that **folder** in VS Code (File > Open Folder).
3. Open VS Code's PowerShell terminal in the project root and run:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
   ```

   If you have only Python 3.13 or later, use `py -3.13` (or your installed version) instead of `py -3.12`.

4. **Install aria2c**, the free external download engine. Either:
   - Download the Windows 64-bit ZIP from the [official aria2 releases](https://github.com/aria2/aria2/releases); extract `aria2c.exe` into this project's `tools` folder, **or**
   - install aria2 separately and add the directory containing `aria2c.exe` to your Windows `PATH`.

   To verify a portable binary:

   ```powershell
   .\tools\aria2c.exe --version
   ```

   You can also set `ARIA2C_PATH` to the absolute path of an installed `aria2c.exe` before starting the application.

5. Launch:

   ```powershell
   .\.venv\Scripts\python.exe -m klepto_dl
   ```

6. In VS Code choose **Python: Select Interpreter**, then select `.venv\Scripts\python.exe` for IntelliSense and testing.

### Choosing an E: drive

In the app, click **Browse…** and select an existing directory such as `E:\Downloads`. It does not assume that an `E:` drive exists. The last chosen folder is remembered locally using Qt settings.

## Test the downloader using a local test file

This avoids relying on a random external website or a server's download restrictions.

1. In the project root, open a *second* PowerShell terminal and create a 20 MiB file:

   ```powershell
   New-Item -ItemType Directory -Force -Path .\sample_files
   .\.venv\Scripts\python.exe -c "from pathlib import Path; Path('sample_files/sample.bin').write_bytes(b'A' * (20 * 1024 * 1024))"
   .\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory sample_files
   ```

2. Open the application and paste: `http://127.0.0.1:8765/sample.bin`.
3. Set the destination to a **different** folder from `sample_files`, for example `E:\Downloads`, then click **Download**.
4. Verify the download list changes from Queued/Downloading to Complete, and compare the downloaded file size (20 MiB) and optionally the SHA-256 hash with `Get-FileHash`.
5. Try a larger file or a throttled test HTTP server to see several progress updates. A 20 MiB loopback download may finish too quickly to observe much progress.
6. Test pause/resume on a slower network download. Range-based continuation depends on server support. Test cancel and retry using a failed URL.
7. Stop the HTTP test server with `Ctrl+C`.

**Safety:** Never run a downloaded installer automatically. Choose only files and websites you have permission to access. Do not paste DRM-protected media links or bypass access controls.

## Automated tests

Run in VS Code's terminal:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite covers input validation, transfer formatting, aria2 RPC requests/auth/error parsing, status conversion, and a Qt window smoke test. The RPC tests use a fake HTTP transport, not a live aria2 download; **the manual Windows download test is still required**.

## How it works

The GUI never downloads files itself. It emits Qt signals to a worker `QObject` living in a `QThread`. The worker starts a private `aria2c` process using a random localhost port, a random JSON-RPC secret, and no user-supplied aria2 configuration. It polls `aria2.tellStatus` every 500 ms and sends snapshots back to the GUI over Qt signals. aria2 handles transfers, concurrency and partial-file control data. (See [aria2's official manual](https://aria2.github.io/manual/en/html/aria2c.html).)

On graceful shutdown, aria2 saves unfinished transfers to `%LOCALAPPDATA%\KleptoLocalDownloader\aria2-session.txt`. On reopening, aria2 reads that file and the GUI restores any still-known jobs. This is *session recovery*, not yet full SQLite download history. If the system crashes, the latest session/checkpoint might not be saved; server range support is also required for efficient byte-range resume.

## Scope and known limitations

- **Included:** direct HTTP/HTTPS, chooser for existing download directories, actual speed/bytes/ETA, basic pause/resume/cancel/retry, concurrent jobs via aria2, graceful stop and local aria2 session recovery.
- **Not included yet:** HTML scans, video discovery, yt-dlp, FFmpeg, Playwright, browser integration, scheduling, file-type filters, full SQLite history, installer, or automatic updates.
- **Known limitations:** Headless server responses may not disclose final size, so the progress bar becomes indeterminate while byte counts update. Some links require authentication/cookies/headers and are not yet supported. The current GUI does not provide file size preflight. Retrying a file when a server does not support resume might fail safely if the target already exists. Very large download lists should use batched RPC polling in a later milestone.

Do not start V2 until you run the Windows acceptance test and confirm the V1 direct-download workflow.
