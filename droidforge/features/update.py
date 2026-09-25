"""Self-update (R-12.4): check the latest GitHub release of futurevoid/droidforge, detect how droidforge was
installed (pipx / AUR / source / pip) and either build a previewed host plan or print the command to run.

Nothing here touches the phone: the upgrade is a host step (touches host:droidforge) run by the executor.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Optional, Tuple

from droidforge import __version__
from droidforge.engine.plan import Plan, Step

REPO = "futurevoid/droidforge"
RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"
TAGS = f"https://api.github.com/repos/{REPO}/tags"
COMMANDS = {"pipx": "pipx upgrade droidforge", "aur": "yay -S droidforge-git"}
PRINTED = {"source": "git pull && pip install -e .", "pip": "pip install --upgrade droidforge"}

Opener = Callable[..., object]


def _get(url: str, opener: Opener, timeout: float = 15) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "droidforge", "Accept": "application/vnd.github+json"})
    with opener(req, timeout=timeout) as r:  # type: ignore[attr-defined]
        return json.loads(r.read())


def parse_version(tag: str) -> Tuple[int, ...]:
    """'v1.2.3' / 'DroidForge-v1.2.3' -> (1, 2, 3), padded so 'v1' == '1.0.0'; no trailing dotted number -> ()."""
    m = re.search(r"(\d+(?:\.\d+)*)$", tag.strip())
    if not m:
        return ()
    nums = [int(x) for x in m.group(1).split(".")]
    return tuple(nums + [0] * (3 - len(nums)))


def latest(opener: Opener = urllib.request.urlopen) -> str:
    """Latest release tag; falls back to the newest version tag when no release is published yet.
    Raises OSError / ValueError when GitHub cannot be reached or answers nonsense."""
    try:
        rel = _get(RELEASES, opener)
        tag = str(rel.get("tag_name", "")) if isinstance(rel, dict) else ""
        if tag:
            return tag
    except OSError as e:
        if getattr(e, "code", None) != 404:
            raise
    tags = _get(TAGS, opener)
    names = [str(t.get("name", "")) for t in tags if isinstance(t, dict)] if isinstance(tags, list) else []
    names = [n for n in names if parse_version(n)]
    if not names:
        raise ValueError(f"no releases or version tags on {REPO} yet")
    return max(names, key=parse_version)


def is_newer(tag: str, current: str = __version__) -> bool:
    return parse_version(tag) > parse_version(current)


def install_method(pkg_dir: Optional[Path] = None, prefix: Optional[str] = None) -> str:
    """pipx | aur | source | pip, from where the droidforge package lives."""
    pkg_dir = (pkg_dir or Path(__file__).resolve().parent.parent)
    prefix = prefix if prefix is not None else sys.prefix
    if (pkg_dir.parent / ".git").exists() or (pkg_dir.parent / "pyproject.toml").exists():
        return "source"
    if "pipx" in Path(prefix).parts:
        return "pipx"
    if str(pkg_dir).startswith("/usr/lib/"):
        return "aur"
    return "pip"


def upgrade_plan(method: str, tag: str = "") -> Plan:
    """Host plan for pipx / AUR. Source and pip installs get a plan with no steps and the command as a note:
    droidforge does not run git or pip on the user's checkout."""
    title = f"Update droidforge {__version__} -> {tag}" if tag else "Update droidforge"
    if method in COMMANDS:
        return Plan(title=title, steps=[Step(f"Upgrade droidforge ({method})", COMMANDS[method], [], "host",
                                             host=True, touches=["host:droidforge"])])
    return Plan(title=title, notes=[f"Installed from {method}: run  {PRINTED.get(method, PRINTED['pip'])}"])
