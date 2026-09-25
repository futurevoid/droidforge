"""P1.10: expert mode (R-4.3) and the reboot check (R-11.9)."""

from __future__ import annotations

import pytest

from droidforge import cli
from droidforge.adb.sim import FakePhone
from droidforge.engine import executor, safety, steps
from droidforge.engine.plan import Confirmation, Plan
from droidforge.engine.reboot import reboot_check, reboot_plan
from droidforge.engine.safety import SafetyContext
from droidforge.session import open_session
from tests.helpers import TELEMETRY, disable_plan, yes

LOCKED = "com.android.ims.rcsservice"


def no_sleep(_: float) -> None:
    pass


def confirm_typed(plan: Plan) -> Confirmation:
    return Confirmation(True, list(plan.typed))


# ---------------------------------------------------------------- expert mode
def test_locked_package_cannot_enter_a_plan_without_expert(sim) -> None:
    ctx = SafetyContext.from_device(sim)
    sel = safety.select([TELEMETRY[0], LOCKED, "com.android.systemui"], ctx, expert_mode=False)
    assert sel.allowed == [TELEMETRY[0]]
    assert set(sel.rejected) == {LOCKED, "com.android.systemui"}
    assert "--expert" in sel.rejected[LOCKED]


def test_expert_selection_and_plan(sim, phone: FakePhone) -> None:
    ctx = SafetyContext.from_device(sim)
    sel = safety.select([TELEMETRY[0], LOCKED], ctx, expert_mode=True)
    assert sel.allowed == [TELEMETRY[0], LOCKED] and sel.locked == [LOCKED]
    plan = safety.make_expert(Plan("Expert debloat", [steps.disable(p) for p in sel.allowed]), sel.locked)
    assert plan.expert and plan.reboot_check and plan.typed == [LOCKED]
    assert [len({s.pkg for s in b}) for b in plan.batches()] == [1, 1]
    assert plan.steps[1].risk == "locked" and plan.steps[0].risk == "normal"
    # the same plan is refused unless expert mode is on AND the name is typed
    assert executor.run(plan, sim, yes, expert_mode=True).status == "refused"
    assert executor.run(plan, sim, confirm_typed, expert_mode=False).status == "refused"
    rep = executor.run(plan, sim, confirm_typed, expert_mode=True)
    assert rep.status == "done" and rep.batches_run == 2 and rep.offer_reboot
    assert not phone.packages[LOCKED].enabled


def test_cli_expert_flag(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return open_session(**kw)
    monkeypatch.setattr(cli, "SESSION_FACTORY", factory)
    assert cli.main(["-q", "--simulate", "--expert", "doctor"]) == 0
    assert seen["expert"] is True and "EXPERT MODE" in capsys.readouterr().err
    assert cli.main(["-q", "--simulate", "doctor"]) == 0
    assert seen["expert"] is False and "EXPERT MODE" not in capsys.readouterr().err


# ---------------------------------------------------------------- reboot check
def test_reboot_check_healthy(sim, phone: FakePhone) -> None:
    rep = executor.run(disable_plan(TELEMETRY[:2]), sim, yes)
    chk = reboot_check(sim, rep, yes, sleep=no_sleep)
    assert chk.status == "done", ([str(r) for r in chk.regressions], [str(c) for c in chk.undeclared])
    assert phone.boots == 1 and phone.boot_polls_left == 0            # it waited for sys.boot_completed
    assert any(c == f"adb -s {phone.serial} wait-for-device" for c in phone.host_log)


def test_reboot_check_catches_regression_injected_at_boot(sim, phone: FakePhone) -> None:
    rep = executor.run(disable_plan(TELEMETRY[:2]), sim, yes)
    phone.on_boot.append(lambda ph: ph.break_ui())
    chk = reboot_check(sim, rep, yes, sleep=no_sleep)
    assert chk.status == "stopped"
    assert {"settings_home", "permission_ui", "permission_monitoring"} <= {r.probe for r in chk.regressions}
    # the offered undo reverts the risky plan (not the reboot)
    assert [s.cmd for s in chk.undo_plan.steps] == [f"pm enable --user 0 {p}" for p in reversed(TELEMETRY[:2])]
    assert chk.advice[0].startswith("1) If the 'Disable permission monitoring'")


def test_reboot_check_catches_undeclared_change_at_boot(sim, phone: FakePhone) -> None:
    rep = executor.run(disable_plan(TELEMETRY[:1]), sim, yes)
    phone.on_boot.append(lambda ph: setattr(ph.packages[TELEMETRY[0]], "enabled", True))   # ROM re-enabled it
    phone.on_boot.append(lambda ph: ph.settings["global"].__setitem__("private_dns_mode", "opportunistic"))
    chk = reboot_check(sim, rep, yes, sleep=no_sleep)
    assert chk.status == "stopped"
    keys = {c.key for c in chk.undeclared}
    assert keys == {"setting:global:private_dns_mode"}  # the package change is declared by the earlier plan


def test_reboot_timeout_stops_without_checks(sim, phone: FakePhone) -> None:
    rep = executor.run(disable_plan(TELEMETRY[:1]), sim, yes)
    phone.on_boot.append(lambda ph: setattr(ph, "boot_polls_left", 10_000))
    chk = reboot_check(sim, rep, yes, sleep=no_sleep, boot_timeout=10)
    assert chk.status == "stopped" and "did not come back" in chk.error


def test_reboot_is_a_confirmed_plan(sim, phone: FakePhone) -> None:
    rep = executor.run(disable_plan(TELEMETRY[:1]), sim, yes)
    chk = reboot_check(sim, rep, lambda p: False, sleep=no_sleep)
    assert chk.status == "cancelled" and phone.boots == 0
    assert reboot_plan(phone.serial).steps[0].host


def test_reboot_check_needs_an_executed_plan(sim) -> None:
    with pytest.raises(ValueError):
        reboot_check(sim, executor.RunReport(plan=Plan("x")), yes)
