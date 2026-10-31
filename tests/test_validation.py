from pathlib import Path
import pytest

from klepto_dl.core.validation import InputError, validate_destination, validate_url, display_name


@pytest.mark.parametrize("url", [
    "https://example.org/file.zip",
    "http://127.0.0.1:8765/archive.bin",
    "https://files.example.com/download?file=1",
])
def test_accepted_urls(url):
    assert validate_url(url) == url


@pytest.mark.parametrize("url", [
    "", "example.org/file.zip", "file:///C:/Users/test/file.zip",
    "ftp://example.org/file.zip", "javascript:alert(1)",
    "https://", "https://example.org/file\nhttps://other.org/file",
    "https://bad host.com/f", "http://example.com:bad/file",
    "http://[broken-ipv6/path",
])
def test_rejected_urls(url):
    with pytest.raises(InputError):
        validate_url(url)


def test_trimming_and_display():
    assert validate_url(" https://example.org/a.zip ") == "https://example.org/a.zip"
    assert display_name("https://example.org/path/My%20File.zip?token=123") == "My File.zip"
    assert display_name("https://example.org/") == "example.org"


def test_valid_destination(tmp_path):
    assert validate_destination(str(tmp_path)) == tmp_path.resolve()


def test_missing_destination(tmp_path):
    with pytest.raises(InputError):
        validate_destination(str(tmp_path / "not-created"))
    with pytest.raises(InputError):
        validate_destination("  ")
