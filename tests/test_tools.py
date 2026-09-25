"""P5.3 scrcpy (R-9.1) + P5.4 logcat (R-9.2)."""

from __future__ import annotations

import pytest

from droidforge.adb import hostcmd
from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.guard import GuardError
from droidforge.features.tools import logcat, scrcpy
from tests.helpers import yes


def test_scrcpy_command_and_launch(sim, phone: FakePhone) -> None:
    assert scrcpy.command("SER", True, True, "/tmp/a b.mp4") == \
        "scrcpy -s SER --turn-screen-off --stay-awake --record '/tmp/a b.mp4'"
    cmd = scrcpy.launch(sim, screen_off=True)
    assert phone.host_log[-1] == f"scrcpy -s {phone.serial} --turn-screen-off" and cmd.startswith("scrcpy")


def test_scrcpy_install_plan_is_previewed_host_step(sim, phone: FakePhone) -> None:
    plan = scrcpy.install_plan(sim)
    assert plan.steps[0].host and plan.steps[0].cmd == "sudo pacman -S scrcpy"
    assert executor.run(plan, sim, yes).status == "done"
    assert phone.host_log[-1] == "sudo pacman -S scrcpy"          # recorded by the simulator, never run here


def test_spawn_refuses_writes(sim) -> None:
    with pytest.raises(GuardError):
        hostcmd.spawn("sudo pacman -S scrcpy", sim)
    with pytest.raises(GuardError):
        hostcmd.stream("rm -rf /", sim)


def test_logcat_stream_and_filters(sim, phone: FakePhone) -> None:
    lines = list(logcat.open_stream(sim))
    assert len(lines) == 5 and phone.host_log[-1] == f"adb -s {phone.serial} logcat -v threadtime"
    errs = [ln for ln in lines if logcat.Filter(level="W").matches(ln)]
    assert len(errs) == 2
    assert [ln for ln in lines if logcat.Filter(tag="oplushans").matches(ln)][0].endswith("freeze com.whatsapp")
    assert len([ln for ln in lines if logcat.Filter(regex=r"kill(ed)?").matches(ln)]) == 1
    assert logcat.Filter(regex="[unclosed").matches("x [unclosed y")
    assert logcat.command("S", 4321, True) == "adb -s S logcat -v threadtime --pid=4321 '*:E'"
    assert len(list(logcat.open_stream(sim, pid=4321))) == 3


def test_pid_of(sim, phone: FakePhone) -> None:
    assert logcat.pid_of(sim, "com.android.systemui") is not None
    assert logcat.pid_of(sim, "com.whatsapp") is None


def test_stream_stop() -> None:
    st = hostcmd.Stream(iter(["a\n", "b\n", "c\n"]))
    out = []
    for ln in st:
        out.append(ln)
        st.stop()
    assert out == ["a"]


async def test_tui_tools_scrcpy_and_logcat(df_home) -> None:
    from droidforge.adb.sim import neo8_cn
    from droidforge.tui.app import DroidforgeApp
    phone = neo8_cn()
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        app.show_section("tools")
        await pilot.pause(0.2)
        app.query_one("#scrcpy-awake").value = True
        app.query_one("#scrcpy").press()
        await pilot.pause()
        assert phone.host_log[-1] == f"scrcpy -s {phone.serial} --stay-awake"
        app.query_one("#lc-level").value = "W"
        app.query_one("#lc-start").press()
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        shown = [str(x) for x in app.query_one("#logcat").lines]
        assert len(shown) == 2 and "killed by OplusAthenaAmManager" in shown[1]
        app.query_one("#lc-save").press()
        await pilot.pause()
        saved = list((df_home / "data" / "logs").glob("logcat-*.txt"))
        assert saved and len(saved[0].read_text().splitlines()) == 5
