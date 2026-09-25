"""Private DNS (R-5.2): AdGuard by default; Cloudflare, Quad9, Mullvad, NextDNS (asks for an ID), a custom hostname,
or off. The previous mode and specifier are recorded for undo (put back, or deleted if they were unset)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from droidforge.engine.guard import HOSTNAME
from droidforge.engine.plan import Plan, Step

if TYPE_CHECKING:  # pragma: no cover
    from droidforge.adb.device import Device

PROVIDERS: Dict[str, Tuple[str, str]] = {
    "adguard": ("AdGuard - blocks ads and trackers (default)", "dns.adguard-dns.com"),
    "adguard-family": ("AdGuard Family - also adult content", "family.adguard-dns.com"),
    "cloudflare": ("Cloudflare - fast, no filtering", "one.one.one.one"),
    "quad9": ("Quad9 - blocks malware domains", "dns.quad9.net"),
    "mullvad": ("Mullvad - blocks ads and trackers", "base.dns.mullvad.net"),
}
DEFAULT = "adguard"
CHOICES = list(PROVIDERS) + ["nextdns", "custom", "off"]
NEXTDNS_ID_RE = re.compile(r"^[a-z0-9]{4,16}$")


def current(device: "Device") -> Tuple[Optional[str], Optional[str]]:
    """(private_dns_mode, private_dns_specifier) - None when unset."""
    def get(k: str) -> Optional[str]:
        v = device.out(f"settings get global {k}")
        return None if v in ("", "null") else v
    return get("private_dns_mode"), get("private_dns_specifier")


def _put(key: str, value: str, prev: Optional[str], label: str) -> Step:
    undo = f"settings put global {key} {prev}" if prev is not None else f"settings delete global {key}"
    return Step(label, f"settings put global {key} {value}", [undo], "dns",
                verify=f"settings get global {key}", expect=rf"^{re.escape(value)}$",
                touches=[f"setting:global:{key}"])


def resolve_host(provider: str, nextdns_id: Optional[str] = None, custom: Optional[str] = None) -> str:
    if provider in PROVIDERS:
        return PROVIDERS[provider][1]
    if provider == "nextdns":
        if not nextdns_id or not NEXTDNS_ID_RE.match(nextdns_id):
            raise ValueError("NextDNS needs your configuration ID (e.g. abc123) from my.nextdns.io")
        return f"{nextdns_id}.dns.nextdns.io"
    if provider == "custom":
        if not custom or not re.fullmatch(HOSTNAME, custom):
            raise ValueError(f"not a valid DNS-over-TLS hostname: {custom!r}")
        return custom
    raise ValueError(f"unknown provider {provider!r} (choose from {', '.join(CHOICES)})")


def dns_plan(device: "Device", provider: str = DEFAULT, nextdns_id: Optional[str] = None,
             custom: Optional[str] = None) -> Plan:
    mode, spec = current(device)
    plan = Plan(title="Private DNS: " + ("off" if provider == "off" else provider))
    plan.notes.append(f"Now: mode={mode or '(unset)'}, host={spec or '(unset)'}. Undo puts both back.")
    if provider == "off":
        if mode != "off":
            plan.steps.append(_put("private_dns_mode", "off", mode, "Private DNS off"))
        else:
            plan.notes.append("Private DNS is already off.")
        return plan
    host = resolve_host(provider, nextdns_id, custom)
    if spec != host:
        plan.steps.append(_put("private_dns_specifier", host, spec, f"Private DNS host -> {host}"))
    if mode != "hostname":
        plan.steps.append(_put("private_dns_mode", "hostname", mode, "Private DNS mode -> hostname (DNS-over-TLS)"))
    if not plan.steps:
        plan.notes.append(f"Already using {host}.")
    else:
        plan.notes.append("If websites stop loading afterwards, the host is unreachable from your network: undo it.")
    return plan


def menu() -> List[Tuple[str, str]]:
    return [(k, v[0]) for k, v in PROVIDERS.items()] + [
        ("nextdns", "NextDNS - asks for your configuration ID"), ("custom", "Custom DNS-over-TLS hostname"),
        ("off", "Off")]
