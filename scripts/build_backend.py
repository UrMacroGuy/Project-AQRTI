"""
AQRTI Backend Bundler
Uses PyInstaller to compile the FastAPI backend into a single Windows executable.
Output: dist/backend/aqrti_backend.exe

Run from project root:
    python scripts/build_backend.py
"""

import subprocess
import sys
import shutil
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
DIST_DIR = ROOT / "dist" / "backend"
BUILD_DIR = ROOT / "build" / "pyinstaller"
MAIN_PY = BACKEND_DIR / "main.py"

PYINSTALLER_ARGS = [
    sys.executable, "-m", "PyInstaller",
    "--name", "aqrti_backend",
    "--onefile",
    "--noconfirm",
    "--clean",
    "--distpath", str(DIST_DIR),
    "--workpath", str(BUILD_DIR),
    "--specpath", str(BUILD_DIR),
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols",
    "--hidden-import", "uvicorn.protocols.http",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.websockets",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan",
    "--hidden-import", "uvicorn.lifespan.on",
    "--hidden-import", "sqlalchemy.dialects.sqlite",
    "--hidden-import", "lightgbm",
    "--hidden-import", "xgboost",
    "--hidden-import", "catboost",
    "--hidden-import", "sklearn",
    "--hidden-import", "sklearn.ensemble",
    "--hidden-import", "scipy",
    "--hidden-import", "scipy.stats",
    "--hidden-import", "feedparser",
    "--hidden-import", "apscheduler.schedulers.background",
    "--hidden-import", "apscheduler.executors.pool",
    "--hidden-import", "apscheduler.jobstores.sqlalchemy",
    "--hidden-import", "pydantic_settings",
    "--collect-all", "uvicorn",
    "--collect-all", "fastapi",
    "--collect-all", "yfinance",
    "--collect-all", "pandas",
    "--collect-all", "numpy",
    "--collect-all", "catboost",
    "--add-data", f"{BACKEND_DIR / 'aqrti'}{os.pathsep}aqrti",
    "--add-data", f"{BACKEND_DIR / 'features'}{os.pathsep}features",
    "--add-data", f"{BACKEND_DIR / 'news'}{os.pathsep}news",
    "--add-data", f"{BACKEND_DIR / 'sentiment'}{os.pathsep}sentiment",
    "--add-data", f"{BACKEND_DIR / 'ml'}{os.pathsep}ml",
    str(MAIN_PY),
]


def ensure_pyinstaller():
    try:
        import PyInstaller
        print(f"[build] PyInstaller {PyInstaller.__version__} found.")
    except ImportError:
        print("[build] Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build():
    ensure_pyinstaller()

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[build] Building backend from {MAIN_PY}")
    print(f"[build] Output → {DIST_DIR}")

    result = subprocess.run(PYINSTALLER_ARGS, cwd=str(BACKEND_DIR))
    if result.returncode != 0:
        print("[build] ERROR: PyInstaller failed.")
        sys.exit(1)

    exe_name = "aqrti_backend.exe" if sys.platform == "win32" else "aqrti_backend"
    output_exe = DIST_DIR / exe_name
    if output_exe.exists():
        size_mb = output_exe.stat().st_size / (1024 * 1024)
        print(f"[build] SUCCESS: {output_exe} ({size_mb:.1f} MB)")
    else:
        print(f"[build] WARNING: Expected output not found at {output_exe}")

    # Clean up PyInstaller work dir
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    print("[build] Backend build complete.")


if __name__ == "__main__":
    build()
