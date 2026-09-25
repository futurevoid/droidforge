"""P4.8: region only opens screens (R-3.3)."""

from __future__ import annotations

import ast
from pathlib import Path

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor, guard
from droidforge.features import region
from tests.helpers import yes


def test_module_can_only_emit_am_start_reads(sim, phone: FakePhone) -> None:
    for plan in (region.regional_plan(sim), region.datetime_plan(sim)):
        for s in plan.steps:
            v = guard.check_command(s.cmd, sim)
            assert not v.write and s.cmd.startswith("am start -a ") and s.undo == [] and s.risk == "read"
    text = Path(region.__file__).read_text()
    assert "settings put" not in text and "setprop" not in text
    calls = {n.func.attr for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)}
    assert calls <= {"open_screen", "append"}


def test_opens_and_changes_nothing(sim, phone: FakePhone) -> None:
    before = phone.state()
    assert executor.run(region.regional_plan(sim), sim, yes).status == "done"
    assert executor.run(region.datetime_plan(sim), sim, yes).status == "done"
    assert phone.state() == before and phone.started == [region.REGIONAL, region.DATE]


def test_old_android(sim, phone: FakePhone) -> None:
    phone.props["ro.build.version.sdk"] = "33"
    sim.forget_props()
    assert region.regional_plan(sim).steps == []
