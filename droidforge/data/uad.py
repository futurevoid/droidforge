"""UAD-NG package list (R-4.1): Recommended / Advanced / Expert / Unsafe ratings, descriptions, neededBy.

Universal Android Debloater Next Generation, GPL-3.0:
https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation
The list is downloaded only when the user asks (`update()`), cached in the droidforge cache dir, and read from the
cache everywhere else (`load_cached()` never touches the network).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

UAD_URL = ("https://raw.githubusercontent.com/Universal-Debloater-Alliance/"
           "universal-android-debloater-next-generation/main/resources/assets/uad_lists.json")
TIERS = ("Recommended", "Advanced", "Expert", "Unsafe")
LISTS = ("Oem", "Google", "Carrier", "Misc", "Aosp")
MIN_ENTRIES = 1000

_CACHE: Dict[str, Tuple[float, Dict[str, dict]]] = {}


def cache_file() -> Path:
    from droidforge import config
    return config.paths().sub("cache") / "uad_lists.json"


def normalise(raw: Any) -> Dict[str, dict]:
    """Accept the dict-by-package format (and a list of {id: ...} objects)."""
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, dict)}
    if isinstance(raw, list):
        return {e["id"]: e for e in raw if isinstance(e, dict) and isinstance(e.get("id"), str)}
    raise ValueError("unexpected UAD list format")


def load_cached(path: Optional[Path] = None) -> Dict[str, dict]:
    """The cached list, or {} if it was never downloaded / is corrupt. Never downloads."""
    f = path or cache_file()
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return {}
    hit = _CACHE.get(str(f))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = normalise(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    _CACHE[str(f)] = (mtime, data)
    return data


def update(timeout: float = 60, path: Optional[Path] = None) -> Tuple[bool, str]:
    """Download the list (only when the user asked). On any failure the cached copy is kept."""
    f = path or cache_file()
    try:
        req = urllib.request.Request(UAD_URL, headers={"User-Agent": "droidforge"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        data = normalise(json.loads(raw))
        if len(data) < MIN_ENTRIES:
            raise ValueError(f"only {len(data)} entries")
    except Exception as e:  # network, TLS, JSON - all mean "keep the old copy"
        kept = " - keeping the cached copy" if f.exists() else ""
        return False, f"UAD-NG download failed: {e}{kept}"
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(f)
    return True, f"UAD-NG list updated: {len(data)} packages"


def status_line(path: Optional[Path] = None) -> str:
    f = path or cache_file()
    if not f.exists():
        return "UAD-NG: not downloaded"
    from datetime import datetime
    return f"UAD-NG: {len(load_cached(f))} pkgs, {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d}"


def entry(uad: Dict[str, dict], p: str) -> dict:
    return uad.get(p) or {}


def tier(uad: Dict[str, dict], p: str) -> str:
    return entry(uad, p).get("removal", "")


def description(uad: Dict[str, dict], p: str, width: int = 0) -> str:
    d = " ".join((entry(uad, p).get("description") or "").split())
    return d if not width or len(d) <= width else d[:width - 3] + "..."


def needed_by(uad: Dict[str, dict], p: str) -> List[str]:
    return list(entry(uad, p).get("neededBy") or [])


def depends_on(uad: Dict[str, dict], p: str) -> List[str]:
    return list(entry(uad, p).get("dependencies") or [])
