"""P5.2: Shizuku install / start / status (R-2.3)."""

from __future__ import annotations

from pathlib import Path

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.features import shizuku
from tests.helpers import make_apk, yes


def test_status_and_start(sim, phone: FakePhone, tmp_path: Path) -> None:
    assert shizuku.status(sim) == "not installed"
    assert shizuku.start_plan(sim).steps == []
    make_apk(tmp_path / "s.apk", shizuku.PKG)
    assert executor.run(shizuku.install_plan(sim, tmp_path / "s.apk"), sim, yes).status == "done"
    assert shizuku.status(sim) == "stopped"
    plan = shizuku.start_plan(sim)
    assert plan.steps[0].cmd.endswith("/lib/arm64/libshizuku.so") and plan.steps[0].fallbacks[0].cmd == shizuku.FALLBACK
    rep = executor.run(plan, sim, yes)
    assert rep.status == "done" and rep.results[0].verified and shizuku.status(sim) == "running"
    phone.reboot()
    assert shizuku.status(sim) == "stopped"


async def test_tui_asks_to_start_shizuku(df_home) -> None:
    from droidforge.adb.sim import neo8_cn
    from droidforge.tui.app import DroidforgeApp
    from droidforge.tui.screens.modals import ConfirmBox
    from tests.test_tui import run_previewed
    phone = neo8_cn()
    phone.add(shizuku.PKG, system=False)
    app = DroidforgeApp(simulate=True, show_limits=False, phone=phone)
    async with app.run_test(size=(140, 44)) as pilot:
        for _ in range(80):
            await pilot.pause(0.05)
            if isinstance(app.screen, ConfirmBox) and app.screen.query("#yes"):
                break
        assert "Shizuku" in str(app.screen.query_one("#confirm-body").render())
        assert not phone.shizuku_running                   # nothing started before the user says yes
        app.screen.query_one("#yes").press()
        await run_previewed(app, pilot)
        assert phone.shizuku_running
