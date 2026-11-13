"""Offline preflight checks; never load recordings or start a search."""
import json
import os
import platform
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path


_RUNTIME_MODULES = (
    "numpy", "scipy", "numba", "pandas", "soundfile", "pyproj", "rasterio",
    "matplotlib", "requests", "pyarrow", "shapely", "portalocker",
)
_WEB_ASSETS = ("index.html", "app.js", "style.css", "leaflet.js", "leaflet.css", "leaflet-license.txt")


def diagnose(jobs="jobs"):
    """Return JSON-safe checks against the current interpreter and filesystem."""
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    add("python", "ok" if sys.version_info >= (3, 11) else "error",
        f"Python {platform.python_version()}; requires Python 3.11 or newer.")
    add("platform", "ok" if sys.platform in {"linux", "darwin"} else "error",
        f"{sys.platform}: full analysis requires Linux or macOS; use WSL on Windows.")
    for command in ("ffmpeg", "ffprobe"):
        executable = shutil.which(command)
        if not executable:
            add(command, "error", f"Install FFmpeg and put {command} on PATH.")
            continue
        try:
            result = subprocess.run([executable, "-version"], capture_output=True,
                                    text=True, timeout=10, check=False)
            lines = result.stdout.splitlines()
            add(command, "ok" if result.returncode == 0 else "error",
                lines[0] if lines else f"{command} exited with code {result.returncode}.")
        except (OSError, subprocess.TimeoutExpired) as exc:
            add(command, "error", f"Cannot run {command}: {exc}")

    # Isolate native-library import failures and avoid loading the numerical stack
    # into the CLI process. Installed metadata alone does not prove imports work.
    probe = """import importlib, json, sys
results = []
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
        results.append({'name': name, 'status': 'ok', 'detail': 'Import succeeded.'})
    except Exception as exc:
        results.append({'name': name, 'status': 'error', 'detail': str(exc)})
print(json.dumps(results))
"""
    try:
        result = subprocess.run([sys.executable, "-c", probe, json.dumps(_RUNTIME_MODULES)],
                                capture_output=True, text=True, timeout=45, check=False)
        if result.returncode:
            add("runtime_imports", "error", "Runtime import probe failed; reinstall the package in this Python environment.")
        else:
            checks.extend(json.loads(result.stdout))
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        add("runtime_imports", "error", f"Runtime import probe could not complete: {exc}")

    try:
        root = files("dopplergeist.web")
        missing = [name for name in _WEB_ASSETS if not root.joinpath(name).is_file()]
        add("web_assets", "error" if missing else "ok",
            "Missing: " + ", ".join(missing) if missing else "All local interface assets are available.")
    except (OSError, ModuleNotFoundError) as exc:
        add("web_assets", "error", f"Cannot read packaged interface assets: {exc}")

    target = Path(jobs).expanduser().absolute()
    try:
        existing = target
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
        if not existing.is_dir():
            add("job_storage", "error", f"{existing} is not a directory; choose another --jobs path.")
        elif not os.access(existing, os.W_OK | os.X_OK):
            add("job_storage", "error", f"No write/search permission for {existing}.")
        else:
            free = shutil.disk_usage(existing).free
            add("job_storage", "warning" if free < 20 * 1024**3 else "ok",
                f"{free / 1024**3:.1f} GiB free at {existing}. Online searches can use tens of GiB; "
                "this is a snapshot, not a capacity guarantee. Custom cache storage must be checked separately.")
    except OSError as exc:
        add("job_storage", "error", f"Cannot inspect {target}: {exc}")
    status = "error" if any(c["status"] == "error" for c in checks) else (
        "warning" if any(c["status"] == "warning" for c in checks) else "ok")
    return {"schema_version": 1, "status": status, "checks": checks,
            "scope": "Local prerequisites only; no network, audio, flight coverage or location-accuracy validation."}
