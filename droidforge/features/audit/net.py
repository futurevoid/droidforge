"""Live connections (R-8.3): `cat /proc/net/tcp /proc/net/tcp6 /proc/net/udp /proc/net/udp6`, UID -> package via
`pm list packages -U`. Best effort without root (SELinux may block it - reported, not guessed); full with root
comes with root mode (v2). Read-only."""

from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

CMD = "cat /proc/net/tcp /proc/net/tcp6 /proc/net/udp /proc/net/udp6"
TCP_STATES = {"01": "ESTABLISHED", "02": "SYN_SENT", "03": "SYN_RECV", "04": "FIN_WAIT1", "05": "FIN_WAIT2",
              "06": "TIME_WAIT", "07": "CLOSE", "08": "CLOSE_WAIT", "09": "LAST_ACK", "0A": "LISTEN",
              "0B": "CLOSING"}
SPECIAL_UIDS = {0: "root", 1000: "android (system)", 1051: "netd / DNS", 1021: "GPS", 1002: "bluetooth"}


@dataclass
class Conn:
    proto: str          # tcp | tcp6 | udp | udp6
    local: str
    remote: str
    state: str
    uid: int
    apps: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NetReport:
    conns: List[Conn] = field(default_factory=list)
    blocked: bool = False
    note: str = ""


def _addr(hexaddr: str) -> str:
    host, port = hexaddr.split(":")
    raw = bytes.fromhex(host)
    if len(raw) == 4:
        ip = str(ipaddress.IPv4Address(raw[::-1]))
    else:
        words = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
        v6 = ipaddress.IPv6Address(words)
        ip = str(v6.ipv4_mapped) if v6.ipv4_mapped else str(v6)
    return f"{ip}:{int(port, 16)}"


def parse(text: str) -> List[Conn]:
    out: List[Conn] = []
    udp = False
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "sl":
            udp = "drops" in line
            continue
        if len(parts) < 8 or not parts[0].endswith(":"):
            continue
        try:
            local, remote = _addr(parts[1]), _addr(parts[2])
            uid = int(parts[7])
        except (ValueError, IndexError):
            continue
        v6 = len(parts[1].split(":")[0]) == 32
        proto = ("udp" if udp else "tcp") + ("6" if v6 else "")
        state = "" if udp else TCP_STATES.get(parts[3].upper(), parts[3])
        out.append(Conn(proto, local, remote, state, uid))
    return out


def uid_map(device: "Device") -> Dict[int, List[str]]:
    res: Dict[int, List[str]] = {}
    for pkg, uid in device.package_uids().items():
        res.setdefault(uid, []).append(pkg)
    return res


def scan(device: "Device", include_listen: bool = False, include_loopback: bool = False) -> NetReport:
    r = device.read(CMD)
    if not r.out.strip():
        return NetReport(blocked=True, note="Reading /proc/net is blocked on this phone (SELinux). Root mode (v2) "
                                            "can read it.")
    uids = uid_map(device)
    rep = NetReport()
    for c in parse(r.out):
        if not include_listen and c.state == "LISTEN":
            continue
        if not include_loopback and (c.remote.startswith(("127.", "::1", "0.0.0.0")) or c.remote.startswith("::")):
            continue
        c.apps = sorted(uids.get(c.uid, [])) or ([SPECIAL_UIDS[c.uid]] if c.uid in SPECIAL_UIDS else [])
        rep.conns.append(c)
    if r.err.strip():
        rep.note = "Some tables could not be read (SELinux): the list may be incomplete."
    return rep
