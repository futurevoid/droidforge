"""P1.8 - invariants for EVERY plan builder (P1, P2, P5, P7, P10), on the simulated phone.

For each registered builder:
  * every write step passes the guard, declares touches and has undo (proc:-only steps excepted: nothing persists);
  * executing it finishes "done" with no undeclared change and no health regression;
  * undoing it (through the same executor) restores a snapshot identical to the one taken before.

A function anywhere in `droidforge` annotated `-> Plan` that is not registered in SCENARIOS fails the suite.
Register new builders here, with a scenario that makes them produce at least one write step.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Callable, Dict, List, Set

import pytest

import droidforge
from droidforge.adb.device import Device
from droidforge.adb.sim import IME_BAIDU, FakePhone
from droidforge.engine import executor, guard, snapshot, undo
from droidforge.engine.history import History
from droidforge.engine.plan import Plan
from droidforge.engine.profile import Profile, import_plan, legacy_import_plan
from droidforge.engine.snapshot import Change
from tests.helpers import TELEMETRY, disable_plan, yes

PKG_ROOT = Path(droidforge.__file__).parent

Scenario = Callable[[FakePhone, Device, Path], Plan]


# ---------------------------------------------------------------------- discovery
def _returns_plan(fn: ast.AST) -> bool:
    r = getattr(fn, "returns", None)
    if r is None:
        return False
    if isinstance(r, ast.Name):
        return r.id == "Plan"
    if isinstance(r, ast.Constant):
        return r.value == "Plan"
    if isinstance(r, ast.Attribute):
        return r.attr == "Plan"
    return False


def discover_builders() -> Set[str]:
    found = set()
    for path in PKG_ROOT.rglob("*.py"):
        mod = "droidforge." + ".".join(path.relative_to(PKG_ROOT).with_suffix("").parts)
        mod = mod.replace(".__init__", "")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _returns_plan(node) \
                    and not node.name.startswith("_"):
                found.add(f"{mod}.{node.name}")
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and _returns_plan(sub) \
                            and not sub.name.startswith("_"):
                        found.add(f"{mod}.{node.name}.{sub.name}")
    return found


# ---------------------------------------------------------------------- scenarios
def _history_with_three(phone: FakePhone, dev: Device) -> History:
    h = History(phone.serial)
    rep = executor.run(disable_plan(TELEMETRY[:3]), dev, yes, history=h)
    assert rep.status == "done"
    return h


def sc_profile_reapply(phone: FakePhone, dev: Device, tmp: Path) -> Plan:
    prof = Profile(disabled=TELEMETRY[:2], removed=["com.opos.cs"], suspended=["com.oplus.sauhelper"],
                   neutered={"com.heytap.market": ["android.permission.POST_NOTIFICATIONS"]},
                   ime_disabled=[IME_BAIDU], app_locales={"com.whatsapp": "en-US,ar-EG"})
    return prof.reapply(dev)


def sc_import_plan(phone: FakePhone, dev: Device, tmp: Path) -> Plan:
    return import_plan({"disabled": TELEMETRY[3:5], "serial": "IGNORED"}, dev)


def sc_legacy_import(phone: FakePhone, dev: Device, tmp: Path) -> Plan:
    f = tmp / "cnrom_state.json"
    f.write_text(json.dumps({"disabled": [TELEMETRY[5]], "removed": ["com.heytap.quicksearchbox"],
                             "english": ["com.tencent.mm"], "device_locale_prev": "zh-Hans-CN"}))
    return legacy_import_plan(f, dev)


def sc_history_undo(phone: FakePhone, dev: Device, tmp: Path) -> Plan:
    h = _history_with_three(phone, dev)
    return h.undo([h.entries()[1].id])


def sc_history_rollback(phone: FakePhone, dev: Device, tmp: Path) -> Plan:
    h = _history_with_three(phone, dev)
    return h.rollback_to(h.entries()[0].id)


def sc_undo_plan(phone: FakePhone, dev: Device, tmp: Path) -> Plan:
    rep = executor.run(disable_plan(TELEMETRY[6:8]), dev, yes)
    return undo.undo_plan(rep.results, "Undo")


def sc_repair_plan(phone: FakePhone, dev: Device, tmp: Path) -> Plan:
    phone.side_effects[rf"disable-user --user 0 {TELEMETRY[8]}$"] = \
        lambda ph: ph.settings["global"].__setitem__("private_dns_mode", "opportunistic")
    rep = executor.run(disable_plan(TELEMETRY[8:9]), dev, yes)
    phone.side_effects.clear()
    assert rep.status == "stopped"
    return undo.repair_plan(rep.results, rep.undeclared, dev, "Repair")


SCENARIOS: Dict[str, Scenario] = {
    "droidforge.engine.profile.Profile.reapply": sc_profile_reapply,
    "droidforge.engine.profile.import_plan": sc_import_plan,
    "droidforge.engine.profile.legacy_import_plan": sc_legacy_import,
    "droidforge.engine.history.History.undo": sc_history_undo,
    "droidforge.engine.history.History.rollback_to": sc_history_rollback,
    "droidforge.engine.undo.undo_plan": sc_undo_plan,
    "droidforge.engine.undo.repair_plan": sc_repair_plan,
}


# ---------------------------------------------------------------------- tests
def test_every_plan_builder_is_registered() -> None:
    found = discover_builders()
    missing = found - set(SCENARIOS)
    assert not missing, f"plan builders not registered in tests/test_invariants.py: {sorted(missing)}"
    stale = set(SCENARIOS) - found
    assert not stale, f"registered builders that no longer exist: {sorted(stale)}"


def _writes(plan: Plan) -> List:
    return [s for s in plan.steps if s.risk != "read"]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_invariants(name: str, sim: Device, phone: FakePhone, tmp_path: Path) -> None:
    plan = SCENARIOS[name](phone, sim, tmp_path)
    writes = _writes(plan)
    assert writes, f"{name}: scenario produced no write step"

    # static: guard, touches, undo (P2, P8, P10)
    for s in plan.steps:
        guard.check(s, sim)
        for st in [s] + list(s.fallbacks):
            if st.risk == "read":
                continue
            assert st.touches, f"{name}: {st.cmd} declares no touches"
            if not all(t.startswith("proc:") for t in st.touches):
                assert st.undo, f"{name}: {st.cmd} has no undo"

    # execute: only declared keys change (P5, P10), no health regression (P11)
    scope = plan.packages()
    before = snapshot.take(sim, scope=scope)
    rep = executor.run(plan, sim, yes)
    assert rep.status == "done", (name, rep.error, [str(r) for r in rep.regressions], [str(c) for c in rep.undeclared])
    assert rep.undeclared == [] and rep.regressions == []
    after = snapshot.take(sim, scope=scope)
    declared = [t for r in rep.results for st in r.applied for t in st.touches]
    assert snapshot.undeclared(snapshot.diff(before, after), declared) == []
    assert any(r.effect == "changed" for r in rep.results), f"{name}: nothing observable changed"

    # undo restores the original snapshot exactly (P2)
    back = executor.run(undo.undo_plan(rep.results, f"Undo {plan.title}"), sim, yes)
    assert back.status == "done", (name, back.error, [str(r) for r in back.regressions])
    restored = snapshot.take(sim, scope=scope)
    remaining: List[Change] = snapshot.diff(before, restored)
    assert remaining == [], f"{name}: undo left differences: {[str(c) for c in remaining]}"
