"""Wireless pairing (R-2.2): QR code (`WIFI:T:ADB;S:<name>;P:<password>;;`) drawn in the TUI, discovery with
`adb mdns services` (`_adb-tls-pairing._tcp`, then `_adb-tls-connect._tcp`), `adb pair`, `adb connect`; fallback:
type ip:port + the 6-digit code shown on the phone. Paired phones are remembered in config.json.

The pairing and connect commands only touch the PC's adb (host:adb-pairing); they are still previewed and
confirmed. Naming Wireless debugging is the owner's P0 exception (SPEC); no other developer option is named.
"""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from droidforge.engine.plan import Plan, Step

# SPEC P0 owner exception: USB debugging / Wireless debugging may be named (they are how adb connects at all).
PAIRING_HINT = ("On the phone: Developer options > Wireless debugging > 'Pair device with QR code', then scan this "
                "code. Phone and PC must be on the same Wi-Fi.")
CODE_HINT = ("Or: Wireless debugging > 'Pair device with pairing code', and type the ip:port and 6-digit code "
             "here.")
ADDR_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$")

Row = Tuple[str, str, str]   # (service name, type, ip:port)


@dataclass(frozen=True)
class Pairing:
    name: str
    password: str

    @property
    def payload(self) -> str:
        return f"WIFI:T:ADB;S:{self.name};P:{self.password};;"


def new_pairing() -> Pairing:
    alphabet = string.ascii_letters + string.digits
    return Pairing("droidforge-" + "".join(secrets.choice(alphabet) for _ in range(6)),
                   "".join(secrets.choice(alphabet) for _ in range(10)))


def qr_matrix(payload: str) -> List[List[bool]]:
    import qrcode
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(payload)
    qr.make(fit=True)
    return [list(row) for row in qr.get_matrix()]


def render_halfblocks(m: List[List[bool]]) -> str:
    """Two QR rows per text line (TUI), drawn light-on-dark so phones read it on a dark terminal."""
    rows = m + ([[False] * len(m[0])] if len(m) % 2 else [])
    chars = {(False, False): "█", (True, True): " ", (True, False): "▄", (False, True): "▀"}
    return "\n".join("".join(chars[(rows[y][x], rows[y + 1][x])] for x in range(len(rows[0])))
                     for y in range(0, len(rows), 2))


def render_ascii(m: List[List[bool]]) -> str:
    """CLI output stays ASCII: two characters per module."""
    return "\n".join("".join("  " if v else "##" for v in row) for row in m)


def parse_services(out: str) -> List[Row]:
    rows = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) >= 3 and "_adb-tls" in parts[1] and ADDR_RE.match(parts[2]):
            rows.append((parts[0], parts[1].rstrip("."), parts[2]))
    return rows


def find_pairing(rows: List[Row], name: str) -> Optional[str]:
    return next((a for n, t, a in rows if n == name and t.startswith("_adb-tls-pairing")), None)


def find_connect(rows: List[Row], ip: str) -> Optional[str]:
    return next((a for n, t, a in rows if t.startswith("_adb-tls-connect") and a.split(":")[0] == ip), None)


def valid_addr(addr: str) -> bool:
    m = ADDR_RE.match(addr)
    return bool(m) and all(int(x) < 256 for x in m.group(1).split(".")) and 0 < int(m.group(2)) < 65536


def pair_plan(pair_addr: str, password: str, connect_addr: Optional[str] = None) -> Plan:
    if not valid_addr(pair_addr) or (connect_addr and not valid_addr(connect_addr)):
        raise ValueError("expected ip:port, e.g. 192.168.1.20:37123")
    plan = Plan(title=f"Pair with {pair_addr}", steps=[Step(f"Pair with {pair_addr}",
                                                            f"adb pair {pair_addr} {password}", [], "wireless",
                                                            host=True, touches=["host:adb-pairing"])])
    if connect_addr:
        plan.steps.append(connect_step(connect_addr))
    plan.notes.append("This only changes the PC's adb: the phone remembers this PC in its paired-devices list.")
    return plan


def connect_step(addr: str) -> Step:
    return Step(f"Connect to {addr}", f"adb connect {addr}", [], "wireless", host=True, touches=["host:adb-pairing"])


def connect_plan(addr: str) -> Plan:
    if not valid_addr(addr):
        raise ValueError("expected ip:port")
    return Plan(title=f"Connect to {addr}", steps=[connect_step(addr)])


def remember(addr: str, name: str = "") -> None:
    from droidforge import config
    cfg = config.Config()
    known = [d for d in cfg.get("paired", []) if d.get("addr") != addr]
    known.append({"addr": addr, "name": name, "last": datetime.now().isoformat(timespec="seconds")})
    cfg.set("paired", known[-10:])


def remembered() -> List[dict]:
    from droidforge import config
    return list(config.Config().get("paired", []))
