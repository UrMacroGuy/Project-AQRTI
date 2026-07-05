"""Standalone scheduler process — run separately from the API.

Usage:
    python -m aqrti.scheduler

The scheduler writes a PID file (backend/scheduler.pid) on startup and
removes it on clean exit. The API checks for this file to decide whether
to start an embedded scheduler or defer to this external process.
"""

from __future__ import annotations

import os
import signal
import sys


def _pid_file_path() -> str:
    """Return the absolute path to the scheduler PID file."""
    # backend/ is two levels up from aqrti/scheduler.py
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, "scheduler.pid")


def _write_pid() -> None:
    path = _pid_file_path()
    with open(path, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid() -> None:
    path = _pid_file_path()
    try:
        os.remove(path)
    except OSError:
        pass


def run() -> None:
    """Start the scheduler and block until SIGINT or SIGTERM."""
    from aqrti.config.settings import get_settings
    from aqrti.data.scheduler import start_scheduler, stop_scheduler
    from aqrti.utils.logger import scheduler_logger

    settings = get_settings()

    scheduler_logger.info(
        "Standalone scheduler starting (PID=%d, env=%s) …",
        os.getpid(),
        getattr(settings, "environment", "unknown"),
    )

    _write_pid()
    scheduler_logger.info("PID file written: %s", _pid_file_path())

    def _shutdown(signum, frame):  # noqa: ANN001
        scheduler_logger.info("Signal %d received — stopping scheduler …", signum)
        stop_scheduler()
        _remove_pid()
        scheduler_logger.info("Standalone scheduler stopped.")
        sys.exit(0)

    # Register handlers for both SIGINT (Ctrl-C) and SIGTERM (task-kill / service stop).
    # On Windows, SIGTERM is not natively supported for all processes, but Python's
    # signal module does handle it for Python processes started via the scheduler task.
    signal.signal(signal.SIGINT, _shutdown)
    try:
        signal.signal(signal.SIGTERM, _shutdown)
    except (OSError, ValueError):
        # SIGTERM may not be available on all Windows configurations — safe to ignore.
        pass

    start_scheduler()
    scheduler_logger.info("Standalone scheduler running. Press Ctrl-C to stop.")

    # Block the main thread so the daemon scheduler threads stay alive.
    try:
        signal.pause()
    except AttributeError:
        # signal.pause() is not available on Windows — fall back to a busy-wait.
        import time
        while True:
            time.sleep(60)


if __name__ == "__main__":
    run()
