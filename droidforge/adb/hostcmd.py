"""Host-side commands (adb install/pair, pacman, scrcpy, notify-send). Always previewed and guard-checked by the
executor before they get here. Run without a shell (argument list), so nothing is interpreted by /bin/sh.

With the simulator (`--simulate`, tests) the backend's `run_host` records the command instead of running it:
nothing ever executes on the development machine.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from typing import TYPE_CHECKING, List

from droidforge.adb.backend import EXIT_NOT_FOUND, EXIT_TIMEOUT, RunResult

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device


def split(cmd: str) -> List[str]:
    return shlex.split(cmd)


def run_host(cmd: str, device: "Device", timeout: float = 600) -> RunResult:
    args = split(cmd)
    device.log.command(cmd)
    t0 = time.monotonic()
    sim_runner = getattr(device.backend, "run_host", None)
    if sim_runner is not None:
        r = sim_runner(args, timeout)
    elif args[:1] == ["adb"]:
        r = device.backend.run(args[1:], timeout)
    else:
        try:
            p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)
            r = RunResult(p.returncode, p.stdout.strip(), p.stderr.strip())
        except subprocess.TimeoutExpired:
            r = RunResult(EXIT_TIMEOUT, "", f"timeout after {timeout:g}s")
        except OSError as ex:
            r = RunResult(EXIT_NOT_FOUND, "", f"could not start {args[0]}: {ex}")
    ms = r.ms or int((time.monotonic() - t0) * 1000)
    device.log.result(r.exit, ms, r.out, r.err)
    return r


def notify(cmd: str, device: "Device" = None) -> bool:  # type: ignore[assignment]
    """Run an (already guard-checked) notify-send command; simulated backends only record it."""
    sim_runner = getattr(getattr(device, "backend", None), "run_host", None)
    if sim_runner is not None:
        return sim_runner(split(cmd)).ok
    import shutil
    if not shutil.which("notify-send"):
        return False
    try:
        return subprocess.run(split(cmd), capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
