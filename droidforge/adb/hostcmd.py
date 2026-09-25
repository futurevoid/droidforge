"""Host-side commands (adb install/pair, pacman, scrcpy, notify-send). Always previewed and guard-checked by the
executor before they get here. Run without a shell (argument list), so nothing is interpreted by /bin/sh.

With the simulator (`--simulate`, tests) the backend's `run_host` records the command instead of running it:
nothing ever executes on the development machine.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from typing import TYPE_CHECKING, Iterator, List, Optional

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


def _check_tool(cmd: str) -> None:
    """spawn()/stream() only run allowlisted host commands that change nothing (scrcpy, logcat, mdns)."""
    from droidforge.engine import guard  # lazy: adb must not depend on engine at import time
    if guard.check_command(cmd, host=True).write:
        raise guard.GuardError(cmd, "state-changing host command - it must go through the executor")


def spawn(cmd: str, device: "Device") -> Optional["subprocess.Popen[bytes]"]:
    """Start a host tool in the background (scrcpy). The simulator records it instead."""
    _check_tool(cmd)
    device.log.command(cmd)
    sim_runner = getattr(device.backend, "run_host", None)
    if sim_runner is not None:
        sim_runner(split(cmd))
        return None
    return subprocess.Popen(split(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Stream:
    """Line stream from a host tool (adb logcat). stop() ends it."""

    def __init__(self, lines: Iterator[str], proc: Optional["subprocess.Popen[str]"] = None) -> None:
        self._lines, self.proc, self.stopped = lines, proc, False

    def __iter__(self) -> Iterator[str]:
        for line in self._lines:
            if self.stopped:
                break
            yield line.rstrip("\n")

    def stop(self) -> None:
        self.stopped = True
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()


def stream(cmd: str, device: "Device") -> Stream:
    _check_tool(cmd)
    device.log.command(cmd)
    sim_stream = getattr(device.backend, "stream_host", None)
    if sim_stream is not None:
        return Stream(iter(sim_stream(split(cmd))))
    proc = subprocess.Popen(split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    assert proc.stdout is not None
    return Stream(iter(proc.stdout), proc)
