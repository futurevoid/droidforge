"""P4.1: telemetry preset (R-5.1) + ads/promos (R-5.4)."""

from __future__ import annotations

from droidforge.adb.sim import FakePhone
from droidforge.data.packages import TELEMETRY
from droidforge.engine import executor
from droidforge.features import ads, privacy
from tests.helpers import UAD_SAMPLE, yes


def test_telemetry_preset_filtered_to_installed(sim, phone: FakePhone) -> None:
    pkgs = privacy.telemetry_packages(sim)
    assert pkgs and all(p in TELEMETRY for p in pkgs)
    assert "com.nearme.statistics.rom" not in pkgs          # not on this phone
    assert "com.oplus.cosa" not in pkgs and "com.oplus.cosa" in privacy.telemetry_packages(sim, include_opt_in=True)
    plan = privacy.telemetry_plan(sim, UAD_SAMPLE)
    assert plan.title == "Kill telemetry" and {s.pkg for s in plan.steps} == set(pkgs)
    assert any("opt-in" in n for n in plan.notes)


def test_telemetry_runs_and_escalates(sim, phone: FakePhone) -> None:
    rep = executor.run(privacy.telemetry_plan(sim, UAD_SAMPLE, escalate=True), sim, yes)
    assert rep.status == "done", (rep.error, [str(c) for c in rep.undeclared])
    assert phone.packages["com.oplus.sauhelper"].suspended            # disable refused -> suspend
    assert not phone.packages["com.coloros.prome.service"].user0      # disable + suspend refused -> removed
    assert not phone.packages["com.oplus.statistics.rom"].enabled


def test_ads_all_four(sim, phone: FakePhone) -> None:
    plan = ads.ads_plan(sim, ["magazine", "push", "launcher", "feed"], UAD_SAMPLE)
    cmds = [s.cmd for s in plan.steps]
    for p in ("com.heytap.pictorial", "com.heytap.mcs", "com.opos.cs", "com.heytap.quicksearchbox",
              "com.nearme.instant.platform", "com.coloros.assistantscreen"):
        assert f"pm disable-user --user 0 {p}" in cmds
    assert "pm revoke com.heytap.themestore android.permission.POST_NOTIFICATIONS" in cmds
    assert "cmd appops set com.heytap.themestore POST_NOTIFICATION ignore" in cmds
    assert not any("disable-user --user 0 com.heytap.themestore" in c for c in cmds)   # theme stores never disabled
    assert not any("com.coloros.pictorial" in c for c in cmds)
    rep = executor.run(plan, sim, yes)
    assert rep.status == "done"
    assert phone.packages["com.heytap.market"].enabled and phone.packages["com.heytap.market"].appops == {
        "POST_NOTIFICATION": "ignore"}


def test_ads_only_chosen_categories(sim) -> None:
    plan = ads.ads_plan(sim, ["feed"], UAD_SAMPLE)
    assert [s.pkg for s in plan.steps] == ["com.coloros.assistantscreen"]
    assert "-1 screen feed" in plan.title


def test_notifications_already_off(sim, phone: FakePhone) -> None:
    phone.packages["com.heytap.browser"].perms["android.permission.POST_NOTIFICATIONS"] = False
    phone.packages["com.heytap.browser"].appops["POST_NOTIFICATION"] = "ignore"
    assert ads.notifications_off_steps(sim, "com.heytap.browser") == []
