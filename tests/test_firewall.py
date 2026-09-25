"""P4.4: non-root per-app firewall via chain 3 (R-5.5)."""

from __future__ import annotations

from pathlib import Path

from droidforge.adb.sim import FakePhone, neo8_cn
from droidforge.engine import executor
from droidforge.engine.history import History
from droidforge.engine.plan import Confirmation, Plan
from droidforge.engine.profile import Profile
from droidforge.engine.reboot import reboot_check
from droidforge.features import debloat, firewall
from tests.helpers import UAD_SAMPLE, yes


def typed_all(plan: Plan) -> Confirmation:
    return Confirmation(True, list(plan.typed))


def test_block_verify_undo(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    prof, h = Profile.for_device(phone.serial), History(phone.serial)
    plan = firewall.block_plan(sim, ["com.heytap.browser", "com.whatsapp"])
    assert [s.cmd for s in plan.steps] == ["cmd connectivity set-package-networking-enabled false com.heytap.browser",
                                           "cmd connectivity set-package-networking-enabled false com.whatsapp",
                                           "cmd connectivity set-chain3-enabled true"]
    assert firewall.REBOOT_NOTE in plan.notes
    rep = executor.run(plan, sim, yes, profile=prof, history=h)
    assert rep.status == "done" and rep.results[0].verified and rep.results[0].effect == "changed"
    assert phone.firewall_chain3 and phone.firewall_blocked == {"com.heytap.browser", "com.whatsapp"}
    assert prof.firewall == ["com.heytap.browser", "com.whatsapp"]
    executor.run(h.rollback_to(h.entries()[0].id), sim, yes, profile=prof, history=h)
    assert phone.state() == initial and prof.firewall == []


def test_second_block_keeps_chain(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    executor.run(firewall.block_plan(sim, ["com.heytap.browser"], profile=prof), sim, yes, profile=prof)
    plan = firewall.block_plan(sim, ["com.whatsapp", "com.heytap.browser"], profile=prof)
    assert [s.cmd for s in plan.steps] == ["cmd connectivity set-package-networking-enabled false com.whatsapp"]
    assert "Already blocked: com.heytap.browser" in plan.notes


def test_locked_needs_expert(sim, phone: FakePhone) -> None:
    plan = firewall.block_plan(sim, ["com.google.android.gms"])
    assert plan.steps == [] and any("Locked, skipped" in n for n in plan.notes)
    plan = firewall.block_plan(sim, ["com.google.android.gms"], expert_mode=True)
    assert plan.expert and plan.typed == ["com.google.android.gms"]
    assert executor.run(plan, sim, typed_all, expert_mode=True).status == "done"


def test_unsupported_build(sim, phone: FakePhone) -> None:
    phone.firewall_supported = False
    assert firewall.block_plan(sim, ["com.whatsapp"]).notes == [firewall.UNSUPPORTED]
    assert firewall.missing_rules(sim, Profile(firewall=["com.whatsapp"])) == []


def test_rules_lost_at_reboot_are_detected_and_reapplied(sim, phone: FakePhone) -> None:
    prof = Profile.for_device(phone.serial)
    rep = executor.run(firewall.block_plan(sim, ["com.heytap.browser"]), sim, yes, profile=prof)
    rep.plan.reboot_check = True
    chk = reboot_check(sim, rep, yes, sleep=lambda _: None)
    assert chk.status == "done", [str(c) for c in chk.undeclared]    # the reset is declared platform behaviour
    assert firewall.missing_rules(sim, prof) == ["com.heytap.browser"]
    again = firewall.reapply_plan(sim, prof)
    assert [s.cmd for s in again.steps][-1] == "cmd connectivity set-chain3-enabled true"
    assert executor.run(again, sim, yes, profile=prof).status == "done"
    assert firewall.missing_rules(sim, prof) == []


def test_force_disable_last_stage_is_firewall_plus_neuter(sim, phone: FakePhone) -> None:
    p = "com.heytap.market"
    phone.packages[p].refuse = {"disable", "suspend", "uninstall"}
    plan = debloat.force_plan(sim, [p], UAD_SAMPLE)
    last = plan.steps[0].fallbacks[-1]
    assert last.cmd == f"cmd connectivity set-package-networking-enabled false {p}"
    extra = [e.cmd for e in last.extra]
    assert f"pm revoke {p} android.permission.POST_NOTIFICATIONS" in extra
    assert extra[-1] == "cmd connectivity set-chain3-enabled true"
    assert any("block its internet + neuter" in n for n in plan.notes)
    initial = phone.clone().state()
    h = History(phone.serial)
    rep = executor.run(plan, sim, yes, history=h)
    assert rep.status == "done" and rep.results[0].ok
    assert p in phone.firewall_blocked and phone.packages[p].appops["RUN_ANY_IN_BACKGROUND"] == "ignore"
    assert not phone.packages[p].perms["android.permission.POST_NOTIFICATIONS"]
    executor.run(h.undo([h.entries()[0].id]), sim, yes, history=h)
    assert phone.state() == initial


async def test_tui_asks_before_reapplying(df_home: Path) -> None:
    from droidforge.tui.app import DroidforgeApp
    from droidforge.tui.screens.modals import ConfirmBox
    phone = neo8_cn()
    Profile.for_device(phone.serial)
    prof = Profile.for_device(phone.serial)
    prof.firewall = ["com.heytap.browser"]
    prof.save()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=(140, 44)) as pilot:
        for _ in range(60):
            await pilot.pause(0.05)
            if isinstance(app.screen, ConfirmBox):
                break
        assert isinstance(app.screen, ConfirmBox)
        assert "com.heytap.browser" in str(app.screen.query_one("#confirm-body").render())
        app.screen.query_one("#no").press()
        await pilot.pause(0.2)
        await app.workers.wait_for_complete()
    assert phone.firewall_blocked == set()          # nothing re-applied without the user's yes
