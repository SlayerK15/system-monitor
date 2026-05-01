"""Cross-platform Performance Monitor."""

from .monitor import SystemMonitor


def main() -> None:
    """Console-script entrypoint (declared in pyproject.toml)."""
    from .server import main as _main
    _main()


__all__ = ["SystemMonitor", "main"]
