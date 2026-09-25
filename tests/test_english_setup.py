"""P2.5: guided English setup - three separately confirmed, health-gated steps."""

from __future__ import annotations

from droidforge.adb.sim import IME_BAIDU, IME_GBOARD, IME_SOGOU, FakePhone
from droidforge.engine import executor
from droidforge.features.english_setup import EnglishSetup, Watcher, focused_package
from tests.helpers import yes


def test_full_walkthrough(sim, phone: FakePhone) -> None:
    setup = EnglishSetup(sim)

    # step 1: droidforge only opens Settings; the user changes the language there
    rep1 = executor.run(setup.language_plan(), sim, yes)
    assert rep1.status == "done" and rep1.results[0].step.cmd == "am start -a android.settings.LOCALE_SETTINGS"
    assert phone.props["persist.sys.locale"] == "zh-Hans-CN"           # untouched by droidforge
    phone.set_device_locales(["en-US", "ar-EG", "zh-Hans-CN"])          # the user, in Settings
    assert "is now en-US" in setup.language_result()

    # step 2: Gboard, then the Chinese keyboards (each its own plan)
    assert executor.run(setup.keyboard_plan(), sim, yes).status == "done"
    assert phone.settings["secure"]["default_input_method"] == IME_GBOARD
    rep2 = executor.run(setup.chinese_keyboards_plan(), sim, yes)
    assert rep2.status == "done" and not phone.imes[IME_SOGOU] and not phone.imes[IME_BAIDU]

    # step 3: watch the screens that still show Chinese
    w = setup.start_watch()
    for p in ("com.tencent.mm", "com.tencent.mm", "com.android.settings", "com.heytap.market"):
        phone.focused = p
        w.poll()
    assert w.caught == ["com.tencent.mm", "com.android.settings", "com.heytap.market"]
    summary = setup.caught_summary()
    assert summary["com.tencent.mm"] == "" and "Settings > Language" in summary["com.heytap.market"]
    plan = setup.apps_plan("en-US,ar-EG")
    assert [s.cmd for s in plan.steps] == ["cmd locale set-app-locales com.tencent.mm --user 0 --locales en-US,ar-EG"]
    assert any(n.startswith("Refused com.android.settings") for n in plan.notes)
    assert executor.run(plan, sim, yes).status == "done"
    assert phone.packages["com.tencent.mm"].locales == "en-US,ar-EG"


def test_chinese_keyboards_wait_for_gboard(sim) -> None:
    plan = EnglishSetup(sim).chinese_keyboards_plan()
    assert plan.steps == [] and "Gboard the default keyboard first" in plan.notes[0]


def test_apps_plan_without_watch(sim) -> None:
    plan = EnglishSetup(sim).apps_plan()
    assert plan.steps == [] and any("No apps caught" in n for n in plan.notes)


def test_focused_package_and_watcher(sim, phone: FakePhone) -> None:
    assert focused_package(sim) == "com.android.launcher"
    w = Watcher(sim)
    assert w.poll() == "com.android.launcher" and w.poll() is None
    phone.focused = "com.whatsapp"
    assert w.poll() == "com.whatsapp" and w.caught == ["com.android.launcher", "com.whatsapp"]
