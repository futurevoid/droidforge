"""Batched READS over many packages in few adb calls (legacy `batch`, read-only here).

    for p in <p1> <p2> ...; do echo "@@$p"; <cmd with $p> 2>&1; done      (40 packages per call)

Writes are never batched this way: the executor sends each write step on its own (P13).
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from droidforge.adb.device import PKG_RE, Device

CHUNK = 40


def batch_script(pkgs: List[str], cmd_tmpl: str) -> str:
    return f'for p in {" ".join(pkgs)}; do echo "@@$p"; {cmd_tmpl} 2>&1; done'


def parse_batch(text: str) -> Dict[str, str]:
    res: Dict[str, str] = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("@@"):
            cur = line[2:].strip()
            res[cur] = ""
        elif cur:
            res[cur] += line + "\n"
    return res


def batch_read(device: Device, pkgs: Iterable[str], cmd_tmpl: str, chunk: int = CHUNK,
               label: str = "") -> Dict[str, str]:
    """Run the read-only `cmd_tmpl` (uses `$p`) for every package. Returns {pkg: output}."""
    pkgs = list(dict.fromkeys(pkgs))
    safe = [p for p in pkgs if PKG_RE.match(p)]
    bad = [p for p in pkgs if not PKG_RE.match(p)]
    if bad:
        device.log.warn(f"Skipped {len(bad)} invalid package name(s): {', '.join(bad[:5])}")
    if not safe:
        return {}
    chunks = (len(safe) + chunk - 1) // chunk
    device.log.trace(f"batch{f' [{label}]' if label else ''}: {len(safe)} package(s) in {chunks} adb call(s) of "
                     f"<= {chunk} - command per package: {cmd_tmpl.replace('$p', '<pkg>')}")
    res: Dict[str, str] = {}
    for n, i in enumerate(range(0, len(safe), chunk), 1):
        grp = safe[i:i + chunk]
        device.log.trace(f"chunk {n}/{chunks}: {grp[0]} ... {grp[-1]} ({len(grp)} pkgs)", 3)
        r = device.read(batch_script(grp, cmd_tmpl), timeout=180)
        res.update(parse_batch(f"{r.out}\n{r.err}"))
    missing = [p for p in safe if p not in res]
    if missing:
        device.log.warn(f"No response for {len(missing)} package(s) (shell cut off?): {', '.join(missing[:5])}")
    return res
