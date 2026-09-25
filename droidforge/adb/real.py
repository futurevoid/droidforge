"""Real adb over subprocess. Missing adb -> exit 127 with the pacman hint; timeout -> exit 124."""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import List, Optional

from droidforge.adb.backend import EXIT_NOT_FOUND, EXIT_TIMEOUT, RunResult

ADB_HINT = "adb not found. Install it with: sudo pacman -S android-tools"


def find_adb() -> Optional[str]:
    return shutil.which("adb")


class RealBackend:
    def __init__(self, adb_path: Optional[str] = None) -> None:
        self.adb = adb_path or find_adb()

    def run(self, args: List[str], timeout: float = 30) -> RunResult:
        if not self.adb:
            return RunResult(EXIT_NOT_FOUND, "", ADB_HINT, 0)
        t0 = time.monotonic()
        try:
            p = subprocess.run([self.adb] + [str(a) for a in args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
            code, out, err = p.returncode, p.stdout.strip(), p.stderr.strip()
        except subprocess.TimeoutExpired:
            code, out, err = EXIT_TIMEOUT, "", f"timeout after {timeout:g}s"
        except OSError as ex:
            code, out, err = EXIT_NOT_FOUND, "", f"could not start adb: {ex}. {ADB_HINT}"
        return RunResult(code, out, err, int((time.monotonic() - t0) * 1000))
