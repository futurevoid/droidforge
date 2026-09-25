"""P1.7: verdicts, typed requirements, locked packages refused by the executor, UI infra hidden."""

from __future__ import annotations

import pytest

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor, safety
from droidforge.engine.plan import Plan
from droidforge.engine.safety import SafetyContext, verdict
from tests.helpers import TELEMETRY, disable_step, typed, yes

UAD = {"com.heytap.market": {"removal": "Recommended"}, "com.coloros.assistantscreen": {"removal": "Advanced"},
       "com.coloros.gallery3d": {"removal": "Expert"}, "com.oplus.some.unsafe": {"removal": "Unsafe"},
       "com.coloros.gamespace": {"removal": "Recommended"},
       "com.heytap.pictorial": {"removal": "Recommended", "neededBy": []}}


@pytest.fixture
def ctx(sim) -> SafetyContext:
    return SafetyContext.from_device(sim, uad=UAD)


@pytest.mark.parametrize("pkg,level", [
    ("com.android.systemui", "locked"), ("com.android.settings", "locked"), ("com.google.android.gms", "locked"),
    ("com.android.vending", "locked"), ("com.android.webview", "locked"), ("com.android.contacts", "locked"),
    ("com.android.mms", "locked"), ("com.android.ims.rcsservice", "locked"), ("android", "locked"),
    ("com.android.systemui.auto_generated_characteristics_rro", "locked"), ("com.oplus.uxdesign", "locked"),
    ("com.coloros.pictorial", "locked"), ("com.oplus.safecenter", "locked"), ("com.oplus.some.unsafe", "locked"),
    ("com.sohu.inputmethod.sogouoem", "locked"),   # current keyboard
    ("com.android.launcher", "locked"),            # current launcher
    ("com.coloros.gamespace", "keep"), ("com.coloros.smartsidebar", "keep"), ("com.oplus.ota", "keep"),
    ("com.coloros.gallery3d", "expert"), ("com.heytap.market", "ok"), ("com.coloros.assistantscreen", "ok"),
    ("com.oplus.camera", "guarded"), ("com.whatsapp", "unknown"),
])
def test_verdicts(pkg: str, level: str, ctx: SafetyContext) -> None:
    assert verdict(pkg, ctx).level == level, verdict(pkg, ctx)


def test_requirements(ctx: SafetyContext) -> None:
    req = safety.requirements(["com.oplus.camera", "com.coloros.gallery3d", "com.android.systemui",
                               "com.coloros.gamespace"], ctx, needed_by={"com.oplus.camera": ["com.coloros.gallery3d",
                                                                                              "com.x.other"]})
    assert req.typed == ["com.android.systemui", safety.TYPED_GUARDED, safety.TYPED_EXPERT_TIER]
    assert req.locked == ["com.android.systemui"]
    assert any("needed by com.x.other" in n for n in req.notes)
    assert not any("needed by com.coloros.gallery3d" in n for n in req.notes)  # both selected
    assert any("keep-list" in n for n in req.notes)


def test_overlays_absent_from_default_lists(sim) -> None:
    default = safety.package_list(sim)
    assert not any("overlay" in p or ".rro" in p or p.endswith("_rro") for p in default)
    assert "android" not in default and "com.android.settings" not in default and "com.oplus.uxdesign" not in default
    assert "com.heytap.market" in default
    full = safety.package_list(sim, show_infra=True)
    assert "com.oplus.framework.overlay" in full and "com.android.systemui.auto_generated_characteristics_rro" in full


def test_bulk_select_excludes_locked_and_keep(ctx: SafetyContext) -> None:
    pkgs = ["com.heytap.market", "com.android.systemui", "com.coloros.gamespace", "com.oplus.camera"]
    assert safety.bulk_selectable(pkgs, ctx) == ["com.heytap.market", "com.oplus.camera"]
    assert "com.coloros.gamespace" in safety.bulk_selectable(pkgs, ctx, explicit=["com.coloros.gamespace"])


# ---------------------------------------------------------------- executor
def test_locked_without_typed_name_rejected(sim, phone: FakePhone) -> None:
    p = "com.android.systemui"
    before = phone.state()
    plan = Plan("Expert", [disable_step(p)], expert=True)            # risk not even marked "locked"
    assert executor.run(plan, sim, yes, expert_mode=True).status == "refused"
    plan.typed = [p]
    assert executor.run(plan, sim, typed(p), expert_mode=False).status == "refused"   # expert mode off
    plan.expert = False
    assert executor.run(plan, sim, typed(p), expert_mode=True).status == "refused"    # plan not an expert plan
    assert phone.state() == before


def test_locked_through_touches_of_any_kind(sim) -> None:
    from droidforge.engine import steps
    plan = Plan("Revoke Play notifications", [steps.revoke("com.android.vending",
                                                           "android.permission.POST_NOTIFICATIONS")])
    rep = executor.run(plan, sim, yes)
    assert rep.status == "refused" and "com.android.vending is locked" in rep.error


def test_locked_with_expert_mode_and_typed_name_runs(sim, phone: FakePhone) -> None:
    p = "com.android.ims.rcsservice"
    plan = Plan("Expert", [disable_step(p)], typed=[p], expert=True)
    rep = executor.run(plan, sim, typed(p), expert_mode=True)
    assert rep.status == "done", rep.error
    assert not phone.packages[p].enabled


def test_unlocked_plans_unaffected(sim) -> None:
    assert executor.run(Plan("x", [disable_step(TELEMETRY[0])]), sim, yes).status == "done"


def test_targets_from_touches() -> None:
    from droidforge.engine import steps
    s = steps.appop("com.x", "RUN_ANY_IN_BACKGROUND", "ignore", None)
    s.pkg = None
    assert safety.targets(s) == {"com.x"}
