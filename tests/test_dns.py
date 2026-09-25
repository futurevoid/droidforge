"""P4.2: Private DNS menu, AdGuard default, exact undo (R-5.2)."""

from __future__ import annotations

import pytest

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.history import History
from droidforge.engine.profile import Profile
from droidforge.features import dns
from tests.helpers import yes


def test_default_is_adguard(sim, phone: FakePhone) -> None:
    plan = dns.dns_plan(sim)
    assert [s.cmd for s in plan.steps] == ["settings put global private_dns_specifier dns.adguard-dns.com",
                                           "settings put global private_dns_mode hostname"]
    assert plan.steps[0].undo == ["settings delete global private_dns_specifier"]     # was unset
    assert plan.steps[1].undo == ["settings put global private_dns_mode off"]
    prof = Profile.for_device(phone.serial)
    rep = executor.run(plan, sim, yes, profile=prof)
    assert rep.status == "done" and all(r.verified for r in rep.results)
    assert phone.settings["global"]["private_dns_specifier"] == "dns.adguard-dns.com"
    assert prof.dns_prev == {"private_dns_specifier": "", "private_dns_mode": "off"}


def test_undo_restores_exactly(sim, phone: FakePhone) -> None:
    before = dict(phone.settings["global"])
    h = History(phone.serial)
    executor.run(dns.dns_plan(sim, "quad9"), sim, yes, history=h)
    executor.run(h.rollback_to(h.entries()[0].id), sim, yes, history=h)
    assert phone.settings["global"] == before and "private_dns_specifier" not in phone.settings["global"]


@pytest.mark.parametrize("provider,host", [("cloudflare", "one.one.one.one"), ("mullvad", "base.dns.mullvad.net"),
                                           ("adguard-family", "family.adguard-dns.com")])
def test_providers(sim, provider: str, host: str) -> None:
    assert dns.dns_plan(sim, provider).steps[0].cmd.endswith(host)


def test_nextdns_and_custom(sim) -> None:
    assert dns.dns_plan(sim, "nextdns", nextdns_id="abc123").steps[0].cmd.endswith("abc123.dns.nextdns.io")
    with pytest.raises(ValueError, match="configuration ID"):
        dns.dns_plan(sim, "nextdns")
    assert dns.dns_plan(sim, "custom", custom="dns.example.org").steps[0].cmd.endswith("dns.example.org")
    for bad in ("not a host", "x;reboot", "localhost"):
        with pytest.raises(ValueError):
            dns.dns_plan(sim, "custom", custom=bad)
    with pytest.raises(ValueError):
        dns.dns_plan(sim, "nope")


def test_off_and_already(sim, phone: FakePhone) -> None:
    assert dns.dns_plan(sim, "off").steps == []
    executor.run(dns.dns_plan(sim), sim, yes)
    assert dns.dns_plan(sim).steps == []
    off = dns.dns_plan(sim, "off")
    assert [s.cmd for s in off.steps] == ["settings put global private_dns_mode off"]
    assert off.steps[0].undo == ["settings put global private_dns_mode hostname"]


def test_menu_lists_everything() -> None:
    keys = [k for k, _ in dns.menu()]
    assert keys[0] == "adguard" and {"nextdns", "custom", "off"} <= set(keys)
