"""P4.6: default-app swaps + roles (R-6.2)."""

from __future__ import annotations

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.plan import Confirmation
from droidforge.features import defaults
from tests.helpers import UAD_SAMPLE, yes

BROWSER = "android.app.role.BROWSER"


def test_browser_swap_and_undo(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    plan = defaults.swap_plan(sim, "browser", disable_coloros=True, uad=UAD_SAMPLE)
    cmds = [s.cmd for s in plan.steps]
    assert cmds[0] == f"cmd role add-role-holder --user 0 {BROWSER} org.mozilla.fenix"
    assert plan.steps[0].undo == [f"cmd role add-role-holder --user 0 {BROWSER} com.heytap.browser"]
    assert "pm disable-user --user 0 com.heytap.browser" in cmds
    rep = executor.run(plan, sim, yes)
    assert rep.status == "done" and rep.results[0].verified and phone.roles[BROWSER] == ["org.mozilla.fenix"]
    from droidforge.engine import undo
    executor.run(undo.undo_plan(rep.results, "u"), sim, yes)
    assert phone.state() == initial


def test_sms_swap_warns_about_calls(sim, phone: FakePhone) -> None:
    phone.add("com.google.android.apps.messaging", system=False)
    plan = defaults.swap_plan(sim, "sms")
    assert plan.reboot_check and defaults.TELEPHONY_CHECK in plan.notes
    assert executor.run(plan, sim, yes).status == "done"
    assert phone.packages["com.android.mms"].enabled          # never disabled


def test_missing_target_opens_play(sim) -> None:
    plan = defaults.swap_plan(sim, "dialer")
    assert plan.steps[0].risk == "read" and "market://details?id=com.google.android.dialer" in plan.steps[0].cmd


def test_no_previous_holder_is_not_swapped(sim, phone: FakePhone) -> None:
    phone.roles[BROWSER] = []
    plan = defaults.swap_plan(sim, "browser")
    assert [s.risk for s in plan.steps] == ["read"] and "cannot offer an undo" in plan.notes[0]


def test_gallery_disable_needs_expert_tier_confirmation(sim, phone: FakePhone) -> None:
    plan = defaults.swap_plan(sim, "gallery", disable_coloros=True, uad=UAD_SAMPLE)
    assert plan.notes[0].startswith("Disabling the ColorOS gallery") and plan.typed == ["YES"]
    assert executor.run(plan, sim, lambda p: Confirmation(True, ["YES"])).status == "done"


def test_role_change_is_observed(sim, phone: FakePhone) -> None:
    from tests.helpers import disable_plan
    phone.side_effects[r"disable-user --user 0 com\.opos\.cs$"] = lambda ph: ph.roles.__setitem__(BROWSER, ["x"])
    rep = executor.run(disable_plan(["com.opos.cs"]), sim, yes)
    assert rep.status == "stopped" and f"role:{BROWSER}" in {c.key for c in rep.undeclared}
