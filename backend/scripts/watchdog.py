"""
GO-2: AQRTI Watchdog + Auto-Restart

Pings /health every 3 minutes. Restarts the backend after 2 consecutive
failures, force-killing whatever holds port 8000 first (handles the
hung-but-alive case, not just a clean crash). Logs every restart with
timestamp. On restart, updates a restart-log file that the UI reads to
show "last restart: X min ago".

Run this as a Windows Scheduled Task on-boot:
  Action: python "C:\\...\\backend\\scripts\\watchdog.py"
  Trigger: At startup
  Run whether user is logged on or not
  (see setup_watchdog_task.ps1 for automated registration)

The watchdog keeps a PID file at backend/watchdog_state.json so it
can survive its own restart without losing the consecutive-failure count.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BACKEND_DIR   = Path(__file__).resolve().parent.parent
HEALTH_URL    = "http://localhost:8000/health"
PORT           = 8000
CHECK_INTERVAL = 180   # 3 minutes — the failure mode actually observed is a
                       # hung-but-alive process (high RAM, no /health reply),
                       # not a clean crash, so 15min/3-strikes was too slow
MAX_FAILURES   = 2
STATE_FILE     = BACKEND_DIR / "watchdog_state.json"
RESTART_LOG    = BACKEND_DIR / "watchdog_restart_log.json"


def _kill_listeners_on_port(port: int) -> list[int]:
    """Force-kill whatever is bound to `port`. A hung-but-alive backend
    won't free the port on its own — without this, a restart attempt just
    fails to bind or leaves a duplicate process fighting over it."""
    killed = []
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"], text=True, errors="ignore"
        )
    except Exception:
        return killed
    pattern = re.compile(r"^TCP\s+\S+:" + str(port) + r"\s+\S+\s+\S+\s+(\d+)", re.MULTILINE)
    for m in pattern.finditer(out):
        pid = int(m.group(1))
        if pid in seen:
            continue
        seen.add(pid)
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10,
            )
            killed.append(pid)
        except Exception:
            pass
    return killed


def _now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _check_health() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"consecutive_failures": 0, "last_check": None}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def _log_restart(reason: str) -> None:
    import msvcrt
    try:
        with open(RESTART_LOG, "a+") as f:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            f.seek(0)
            raw = f.read()
            try:
                log = json.loads(raw) if raw.strip() else []
            except (json.JSONDecodeError, Exception):
                log = []
            log.insert(0, {"ts": _now_str(), "reason": reason})
            f.seek(0)
            f.truncate()
            json.dump(log[:50], f)
            f.flush()
    except Exception:
        pass


def _start_backend() -> None:
    """Launch uvicorn in a new detached process."""
    python = sys.executable
    cmd = [
        str(python), "-m", "uvicorn",
        "aqrti.api.app:app",
        "--host", "0.0.0.0",
        "--port", "8000",
    ]
    log_file = open(BACKEND_DIR / "uvicorn.log", "a")
    try:
        subprocess.Popen(
            cmd,
            cwd=str(BACKEND_DIR),
            stdout=log_file,
            stderr=log_file,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        print(f"[{_now_str()}] Backend started")
    finally:
        log_file.close()


def main():
    print(f"[{_now_str()}] Watchdog started. Checking {HEALTH_URL} every {CHECK_INTERVAL}s")
    state = _load_state()

    while True:
        healthy = _check_health()
        if healthy:
            if state["consecutive_failures"] > 0:
                print(f"[{_now_str()}] Backend recovered after {state['consecutive_failures']} failure(s)")
            state["consecutive_failures"] = 0
        else:
            state["consecutive_failures"] += 1
            print(f"[{_now_str()}] Health check FAILED ({state['consecutive_failures']}/{MAX_FAILURES})")

            if state["consecutive_failures"] >= MAX_FAILURES:
                reason = f"{MAX_FAILURES} consecutive /health failures"
                print(f"[{_now_str()}] RESTARTING backend: {reason}")
                killed = _kill_listeners_on_port(PORT)
                if killed:
                    print(f"[{_now_str()}] Killed hung process(es) on port {PORT}: {killed}")
                    time.sleep(2)
                _log_restart(reason + (f" (killed pid(s) {killed})" if killed else ""))
                _start_backend()
                # Give the server time to boot before next check
                time.sleep(60)
                state["consecutive_failures"] = 0

        state["last_check"] = _now_str()
        _save_state(state)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
