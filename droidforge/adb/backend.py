"""Backend protocol: how adb arguments reach a phone (real subprocess or the simulator)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

try:  # Protocol is typing-only on 3.9 as well; keep the import cheap
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore[assignment,misc]

EXIT_TIMEOUT = 124
EXIT_NOT_FOUND = 127


@dataclass(frozen=True)
class RunResult:
    exit: int
    out: str
    err: str
    ms: int = 0

    @property
    def ok(self) -> bool:
        return self.exit == 0

    @property
    def text(self) -> str:
        return f"{self.out}\n{self.err}".strip()


class Backend(Protocol):
    """`args` are the adb arguments without the `adb` binary, e.g. ["-s", "SER", "shell", "pm list packages"]."""

    def run(self, args: List[str], timeout: float = 30) -> RunResult:
        ...
