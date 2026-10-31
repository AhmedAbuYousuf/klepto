from klepto_dl.core.formatting import byte_size, eta_text, speed_text


def test_units():
    assert byte_size(0) == "0 B"
    assert byte_size(1024) == "1.0 KiB"
    assert byte_size(1024 * 1024) == "1.0 MiB"
    assert byte_size(-1) == "0 B"
    assert speed_text(2048) == "2.0 KiB/s"
    assert speed_text(0) == "0 B/s"


def test_eta():
    assert eta_text(100, 40, 10) == "6s"
    assert eta_text(2000, 0, 10) == "3m 20s"
    assert eta_text(100, 50, 0) == "--"
    assert eta_text(0, 0, 20) == "--"
