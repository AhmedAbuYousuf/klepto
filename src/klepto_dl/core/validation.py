"""Input checks; never interpret a URL as a local file path."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit


class InputError(ValueError):
    """A user-fixable input error."""


def validate_url(value: str) -> str:
    url = value.strip()
    if not url or any(ord(ch) < 32 or ch.isspace() for ch in url):
        raise InputError("Enter one complete URL, without spaces or line breaks.")
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise InputError("V1 supports direct HTTP and HTTPS links only.")
        if not parsed.hostname or any(ch.isspace() for ch in parsed.netloc):
            raise InputError("Enter a URL with a valid host name.")
        # urlsplit validates a malformed IPv6 host; .port validates ports.
        _ = parsed.port
    except ValueError as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError(f"Invalid URL: {exc}") from exc
    return url


def validate_destination(value: str) -> Path:
    if not value.strip():
        raise InputError("Choose a download folder.")
    path = Path(value.strip()).expanduser()
    if not path.is_dir():
        raise InputError("Download folder does not exist. Browse to an existing folder.")
    if not os.access(path, os.W_OK):
        raise InputError("Download folder is not writable.")
    return path.resolve()


def display_name(url: str) -> str:
    """Only for display. aria2 determines the actual downloaded file name."""
    parsed = urlsplit(url)
    name = unquote(parsed.path.rsplit("/", 1)[-1]) or parsed.hostname or "Download"
    name = "".join(ch if ch.isprintable() else "_" for ch in name)
    return name[:120] or "Download"
