"""NVIDIA GPU detection and on-demand installation of the CUDA paddle build.

Kept independent of ocr/paddle.py: this must work even before paddleocr or
any GPU package is installed, since it is what decides whether to offer
installing them in the first place. The CUDA runtime libraries this pulls
in are large (multiple gigabytes), so installation is always an explicit,
separate step -- never automatic, and never part of the base install.
"""
from collections.abc import Iterator
from importlib.metadata import PackageNotFoundError, version
import subprocess
import sys

DEFAULT_GPU_VERSION = "3.3.1"
DEFAULT_INDEX_URL = "https://www.paddlepaddle.org.cn/packages/stable/cu126/"

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def detect_nvidia_gpu() -> str | None:
    """The first NVIDIA GPU's name, or None if none is found (or nvidia-smi is absent)."""
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return names[0] if names else None


def gpu_utilization() -> dict | None:
    """Current GPU utilization percent and VRAM used/total in MB, or None if
    nvidia-smi is unavailable or its output doesn't parse. Cheap and has no
    package dependency (unlike gpu_paddle_installed()), so this can be polled
    repeatedly to drive a live display."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    parts = [part.strip() for part in lines[0].split(",")]
    if len(parts) != 3:
        return None
    try:
        return {"utilization_percent": int(parts[0]), "memory_used_mb": int(parts[1]),
                "memory_total_mb": int(parts[2])}
    except ValueError:
        return None


def gpu_paddle_installed() -> bool:
    """Whether the CUDA build (as opposed to the CPU-only build) is installed."""
    try:
        version("paddlepaddle-gpu")
        return True
    except PackageNotFoundError:
        return False


def paddle_version() -> str:
    """The installed paddlepaddle version, whichever of the two distributions provides it."""
    try:
        return version("paddlepaddle")
    except PackageNotFoundError:
        return version("paddlepaddle-gpu")


def install_gpu_support(version_pin: str = DEFAULT_GPU_VERSION,
                         index_url: str = DEFAULT_INDEX_URL) -> Iterator[str]:
    """Replace the CPU paddlepaddle install with the matching CUDA build.

    Runs against sys.executable, i.e. whichever Python is currently running
    -- the caller is expected to already be running inside the target
    runtime (the dev paddle-env, or the packaged app's bundled runtime).
    Yields output lines as they arrive; raises RuntimeError if either step
    exits non-zero, after yielding everything produced up to that point.
    """
    steps = [
        [sys.executable, "-m", "pip", "uninstall", "-y", "paddlepaddle"],
        [sys.executable, "-m", "pip", "install", f"paddlepaddle-gpu=={version_pin}", "-i", index_url],
    ]
    for command in steps:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        for line in process.stdout:
            yield line
        code = process.wait()
        if code != 0:
            raise RuntimeError(f"Command failed with exit code {code}: {' '.join(command)}")
