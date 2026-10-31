"""Human readable transfer measurements."""


def byte_size(n: int) -> str:
    number = max(0, int(n))
    if number < 1024:
        return f"{number} B"
    value = float(number)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
    raise AssertionError("unreachable")


def speed_text(n: int) -> str:
    return f"{byte_size(n)}/s" if n > 0 else "0 B/s"


def eta_text(total: int, completed: int, speed: int) -> str:
    if total <= 0 or speed <= 0 or completed >= total:
        return "--"
    seconds = (total - completed + speed - 1) // speed
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"
