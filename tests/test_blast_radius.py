"""P10 / P11 / P13 - blast radius: a command that also flips something undeclared is caught, the plan stops
after that batch (later batches are never sent) and an undo/revert plan is offered (R-11.8)."""

from __future__ import annotations

from typing import List

import pytest

from droidforge.adb.sim import IME_GBOARD, FakePhone
from droidforge.engine import executor
from tests.helpers import TELEMETRY, disable_plan, yes


def writes_in(phone: FakePhone, start: int = 0) -> List[str]:
    reads = ("getprop", "pm list", "settings get", "settings list", "dumpsys", "cmd package resolve", "ime list",
             "cmd locale get", "cmd appops get", "cmd uimode night", "logcat", "pidof", "for p in")
    return [c for c in phone.log[start:] if not c.startswith(reads)]


# ---------------------------------------------------------------- (c) undeclared side effect
def test_side_effect_caught_and_plan_stops_after_that_batch(sim, phone: FakePhone) -> None:
    pkgs = TELEMETRY[:10]
    phone.side_effects[rf"disable-user --user 0 {pkgs[1]}$"] = \
        lambda ph: ph.settings["global"].__setitem__("private_dns_mode", "hostname")
    rep = executor.run(disable_plan(pkgs), sim, yes)
    assert rep.status == "stopped" and rep.batches_run == 1 and rep.batches_total == 2
    assert [str(c) for c in rep.undeclared] == ["setting:global:private_dns_mode: off -> hostname"]
    assert len(rep.results) == 5
    for p in pkgs[5:]:
        assert phone.packages[p].enabled, "batch 2 must not be sent"
    # the undo offer reverts the plan and the (allowlisted) undeclared change
    cmds = [s.cmd for s in rep.undo_plan.steps]
    assert cmds[:5] == [f"pm enable --user 0 {p}" for p in reversed(pkgs[:5])]
    assert "settings put global private_dns_mode off" in cmds


def test_undeclared_display_change_cannot_be_auto_reverted(sim, phone: FakePhone) -> None:
    p = TELEMETRY[0]
    phone.side_effects[rf"disable-user --user 0 {p}$"] = \
        lambda ph: ph.settings["system"].__setitem__("font_scale", "1.3")
    rep = executor.run(disable_plan([p]), sim, yes)
    assert rep.status == "stopped"
    assert all("font_scale" not in s.cmd for s in rep.undo_plan.steps)  # P9b: never written, not even to repair
    assert any("Reset all settings" in n for n in rep.undo_plan.notes)
    assert any(r.probe == "font_scale" for r in rep.regressions)


# ---------------------------------------------------------------- (d) break_ui mid-plan
def test_break_ui_at_step_3_of_12_stops_before_batch_2(sim, phone: FakePhone) -> None:
    pkgs = TELEMETRY[:12]
    phone.side_effects[rf"disable-user --user 0 {pkgs[2]}$"] = lambda ph: ph.break_ui()
    n0 = len(phone.log)
    rep = executor.run(disable_plan(pkgs), sim, yes)
    assert rep.status == "stopped" and rep.batches_run == 1 and rep.batches_total == 3
    names = {r.probe for r in rep.regressions}
    assert {"settings_home", "permission_ui", "permission_monitoring"} <= names
    sent = writes_in(phone, n0)
    assert sent == [f"pm disable-user --user 0 {p}" for p in pkgs[:5]]
    assert rep.advice[0].startswith("1) If the 'Disable permission monitoring'")


SIDE_EFFECTS = {
    "another package disabled": (lambda ph: setattr(ph.packages["com.whatsapp"], "enabled", False),
                                 "pkg:com.whatsapp:enabled"),
    "app locale changed": (lambda ph: setattr(ph.packages["com.whatsapp"], "locales", "en-US"),
                           "applocale:com.whatsapp"),
    "IME enabled": (lambda ph: ph.imes.__setitem__(IME_GBOARD, True), f"ime:enabled:{IME_GBOARD}"),
    "system package removed": (lambda ph: setattr(ph.packages["com.coloros.weather.service"], "user0", False),
                               "pkg:com.coloros.weather.service:installed"),
    "secure setting added": (lambda ph: ph.settings["secure"].__setitem__("some_rom_key", "1"),
                             "setting:secure:some_rom_key"),
    "density changed": (lambda ph: setattr(ph.config, "density", 400), "config:density"),
}


@pytest.mark.parametrize("name", sorted(SIDE_EFFECTS))
def test_every_kind_of_side_effect_is_caught(name: str, sim, phone: FakePhone) -> None:
    mutate, key = SIDE_EFFECTS[name]
    phone.side_effects[rf"disable-user --user 0 {TELEMETRY[0]}$"] = mutate
    rep = executor.run(disable_plan(TELEMETRY[:6]), sim, yes)
    assert rep.status == "stopped" and rep.batches_run == 1
    assert key in {c.key for c in rep.undeclared}
    assert phone.packages[TELEMETRY[5]].enabled  # batch 2 never sent


def test_declared_changes_do_not_stop(sim, phone: FakePhone) -> None:
    rep = executor.run(disable_plan(TELEMETRY[:6]), sim, yes)
    assert rep.status == "done" and rep.batches_run == 2 and rep.undeclared == [] and rep.regressions == []


def test_side_effect_in_last_batch_still_offers_full_undo(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    def hook(ph: FakePhone) -> None:
        ph.settings["global"]["package_verifier_enable"] = "0"
    phone.side_effects[rf"disable-user --user 0 {TELEMETRY[6]}$"] = hook
    rep = executor.run(disable_plan(TELEMETRY[:7]), sim, yes)
    assert rep.status == "stopped" and rep.batches_run == 2
    phone.side_effects.clear()
    assert executor.run(rep.undo_plan, sim, yes).status == "done"
    assert phone.state() == initial
