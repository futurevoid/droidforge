"""XDG paths and the user config file.

~/.config/droidforge/config.json
~/.local/share/droidforge/{profiles,history,backups,reports,logs,cache,modules,recovery}

`DROIDFORGE_HOME=<dir>` puts everything under <dir>/config and <dir>/data (tests, portable use).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import platformdirs

APP = "droidforge"
DATA_SUBDIRS = ("profiles", "history", "backups", "reports", "logs", "cache", "modules", "recovery")

DEFAULTS: Dict[str, Any] = {
    "theme": "textual-dark",
    "verbosity": 3,           # P3: ULTRA is the default
    "last_device": None,
    "limits_shown": False,    # P16: the "honest limits" note is shown once, on first run
}


@dataclass(frozen=True)
class Paths:
    config_dir: Path
    data_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    def sub(self, name: str) -> Path:
        """A data subdirectory (created on first use)."""
        if name not in DATA_SUBDIRS:
            raise ValueError(f"unknown data dir {name!r}")
        d = self.data_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def debug_log(self) -> Path:
        return self.sub("logs") / "debug.log"


def paths(home: Optional[Path] = None) -> Paths:
    """Resolve the directories. `home` (or $DROIDFORGE_HOME) overrides XDG."""
    base = home or (Path(os.environ["DROIDFORGE_HOME"]) if os.environ.get("DROIDFORGE_HOME") else None)
    if base is not None:
        return Paths(config_dir=Path(base) / "config", data_dir=Path(base) / "data")
    return Paths(config_dir=Path(platformdirs.user_config_dir(APP)),
                 data_dir=Path(platformdirs.user_data_dir(APP)))


class Config:
    """config.json: theme, verbosity, last device, first-run flags. Unknown keys are preserved."""

    def __init__(self, p: Optional[Paths] = None) -> None:
        self.paths = p or paths()
        self.data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        f = self.paths.config_file
        if not f.exists():
            return
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return  # unreadable config -> defaults; the file is rewritten on the next save
        if isinstance(raw, dict):
            self.data.update(raw)
        v = self.data.get("verbosity")
        self.data["verbosity"] = min(3, max(1, v)) if isinstance(v, int) else DEFAULTS["verbosity"]

    def save(self) -> None:
        f = self.paths.config_file
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(f)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()
