"""P1.4: executor - guard -> confirm -> baseline -> recovery -> batches with diff + health gate."""

from __future__ import annotations

from pathlib import Path
from typing import List

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.plan import Plan, Step
from tests.helpers import (
    TELEMETRY,
    disable_plan,
    disable_step,
    force_step,
    no,
    replay_recovery,
    typed,
    yes,
)


def writes_in(phone: FakePhone, start: int = 0) -> List[str]:
    from tests.helpers import WRITE_PREFIXES
    return [c for c in phone.log[start:] if c.startswith(WRITE_PREFIXES)]


# ---------------------------------------------------------------- (a) dry-run
def test_dry_run_touches_nothing(sim, phone: FakePhone) -> None:
    before = phone.state()
    rep = executor.run(disable_plan(TELEMETRY[:3]), sim, yes, dry_run=True)
    assert rep.status == "dry-run" and len(rep.results) == 3 and all(r.dry_run for r in rep.results)
    assert phone.state() == before and writes_in(phone) == []


# ---------------------------------------------------------------- (b) escalation
def test_fallback_escalation(sim, phone: FakePhone) -> None:
    p = "com.oplus.sauhelper"  # the ROM refuses disable-user, suspend works
    rep = executor.run(Plan("Force-disable", [force_step(p)]), sim, yes)
    assert rep.status == "done", rep.regressions or rep.undeclared
    r = rep.results[0]
    assert r.ok and r.step.cmd == f"pm suspend --user 0 {p}"
    assert r.attempts == [f"pm disable-user --user 0 {p}", f"pm suspend --user 0 {p}"]
    assert [s.cmd for s in r.applied] == [f"pm suspend --user 0 {p}"]
    assert phone.packages[p].suspended and phone.packages[p].enabled
    assert r.effect == "changed"


def test_escalation_exhausted(sim, phone: FakePhone) -> None:
    p = "com.coloros.prome.service"  # disable and suspend both refused
    rep = executor.run(Plan("Force-disable", [force_step(p)]), sim, yes)
    assert not rep.results[0].ok and rep.results[0].applied == []
    assert rep.status == "done" and not rep.ok


# (c) and (d) - undeclared side effects and break_ui() mid-plan - live in tests/test_blast_radius.py


# ---------------------------------------------------------------- (e) recovery script
def test_recovery_script_written_first_and_restores(sim, phone: FakePhone, df_home: Path) -> None:
    initial = phone.clone().state()
    pkgs = TELEMETRY[:7]
    seen = {}

    def check_script(ph: FakePhone) -> None:
        seen["exists"] = any((df_home / "data" / "recovery").glob("*.sh"))
    phone.side_effects[rf"disable-user --user 0 {pkgs[0]}$"] = check_script
    plan = disable_plan(pkgs)
    rep = executor.run(plan, sim, yes)
    assert seen["exists"] is True
    assert rep.status == "done" and plan.recovery == rep.recovery
    text = Path(rep.recovery).read_text()
    assert text.startswith("#!/bin/sh") and "Reset all settings" in text
    assert text.index(pkgs[-1]) < text.index(pkgs[0])  # newest first
    assert phone.state() != initial
    replay_recovery(rep.recovery, sim.backend)
    assert phone.state() == initial


def test_recovery_covers_escalation_stages(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    rep = executor.run(Plan("Force", [force_step("com.oplus.sauhelper")]), sim, yes)
    assert "pm unsuspend --user 0 com.oplus.sauhelper" in Path(rep.recovery).read_text()
    replay_recovery(rep.recovery, sim.backend)
    assert phone.state() == initial


# ---------------------------------------------------------------- guard / confirm
def test_refused_plan_is_never_confirmed_or_sent(sim, phone: FakePhone) -> None:
    asked = []
    bad = Plan("Bad", [disable_step(TELEMETRY[0]),
                       Step("Font", "settings put system font_scale 1.3", ["settings put system font_scale 1.0"],
                            touches=["setting:system:font_scale"])])
    n0 = len(phone.log)
    rep = executor.run(bad, sim, lambda p: asked.append(p) or True)
    assert rep.status == "refused" and "forbidden" in rep.error and asked == []
    assert writes_in(phone, n0) == []


def test_cancel_sends_nothing(sim, phone: FakePhone) -> None:
    before = phone.state()
    rep = executor.run(disable_plan(TELEMETRY[:2]), sim, no)
    assert rep.status == "cancelled" and phone.state() == before


def test_typed_confirmation_rechecked(sim, phone: FakePhone) -> None:
    plan = disable_plan(TELEMETRY[:1])
    plan.typed = ["I UNDERSTAND"]
    assert executor.run(plan, sim, yes).status == "refused"
    assert executor.run(plan, sim, typed("i understand")).status == "refused"
    assert executor.run(plan, sim, typed("I UNDERSTAND")).status == "done"


def test_locked_step_needs_expert(sim) -> None:
    s = disable_step("com.android.systemui")
    s.risk = "locked"
    rep = executor.run(Plan("x", [s]), sim, yes)
    assert rep.status == "refused" and "expert" in rep.error


def test_pre_failing_probe_is_reported_but_not_a_new_regression(sim, phone: FakePhone) -> None:
    phone.permission_monitoring_disabled = True
    rep = executor.run(disable_plan(TELEMETRY[:1]), sim, yes)
    assert [p.name for p in rep.pre_failing] == ["permission_monitoring"]
    assert rep.status == "done" and rep.regressions == []


def test_history_hook_and_effects(sim, phone: FakePhone) -> None:
    recorded = []

    class H:
        def record(self, plan, result, device) -> str:
            recorded.append(result.requested.cmd)
            return f"h{len(recorded)}"
    rep = executor.run(disable_plan(TELEMETRY[:2]), sim, yes, history=H())
    assert recorded == [f"pm disable-user --user 0 {p}" for p in TELEMETRY[:2]]
    assert [r.history_id for r in rep.results] == ["h1", "h2"]
    assert all(r.effect == "changed" for r in rep.results)


def test_no_op_step_is_unchanged(sim, phone: FakePhone) -> None:
    p = TELEMETRY[0]
    rep = executor.run(Plan("Enable", [Step(f"Enable {p}", f"pm enable --user 0 {p}", [f"pm enable --user 0 {p}"],
                                            pkg=p, touches=[f"pkg:{p}:enabled"])]), sim, yes)
    assert rep.results[0].effect == "unchanged"


def test_batches_of_five_packages() -> None:
    pkgs = [f"com.p{i}" for i in range(11)]
    plan = disable_plan(pkgs)
    plan.steps.insert(1, disable_step("com.p0"))  # second step for the same package stays in its batch
    sizes = [len({s.pkg for s in b}) for b in plan.batches()]
    assert sizes == [5, 5, 1]
    plan.expert = True
    assert all(len({s.pkg for s in b}) == 1 for b in plan.batches())


def test_undo_plan_restores(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    pkgs = TELEMETRY[:3]
    phone.side_effects[rf"disable-user --user 0 {pkgs[2]}$"] = \
        lambda ph: ph.settings["global"].__setitem__("private_dns_mode", "opportunistic")
    rep = executor.run(disable_plan(pkgs), sim, yes)
    assert rep.status == "stopped"
    phone.side_effects.clear()
    rep2 = executor.run(rep.undo_plan, sim, yes)
    assert rep2.status == "done", (rep2.error, rep2.regressions, rep2.undeclared)
    assert phone.state() == initial
