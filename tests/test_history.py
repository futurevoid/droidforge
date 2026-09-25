"""P1.5: history timeline, undo(ids), rollback_to(id) - through the same executor."""

from __future__ import annotations

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.history import History
from droidforge.engine.plan import Plan
from tests.helpers import TELEMETRY, disable_plan, force_step, yes


def test_rollback_to_first_restores_initial_state(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    h = History(phone.serial)
    pkgs = TELEMETRY[:3]
    rep = executor.run(disable_plan(pkgs), sim, yes, history=h)
    assert rep.status == "done"
    entries = h.entries()
    assert [e.cmd for e in entries] == [f"pm disable-user --user 0 {p}" for p in pkgs]
    assert all(e.fingerprint.startswith("realme/") and e.plan_id == rep.plan.id for e in entries)

    plan = h.rollback_to(entries[0].id)
    assert [s.cmd for s in plan.steps] == [f"pm enable --user 0 {p}" for p in reversed(pkgs)]
    rep2 = executor.run(plan, sim, yes, history=h)
    assert rep2.status == "done"
    assert phone.state() == initial
    originals = [e for e in h.entries() if e.id in {x.id for x in entries}]
    assert all(e.undone for e in originals)
    assert h.rollback_to(entries[0].id).steps == []  # nothing left to undo


def test_undo_single_entry(sim, phone: FakePhone) -> None:
    h = History(phone.serial)
    executor.run(disable_plan(TELEMETRY[:3]), sim, yes, history=h)
    mid = h.entries()[1]
    rep = executor.run(h.undo([mid.id]), sim, yes, history=h)
    assert rep.status == "done"
    assert phone.packages[TELEMETRY[1]].enabled and not phone.packages[TELEMETRY[0]].enabled
    assert [e.undone for e in h.entries()[:3]] == [False, True, False]
    # the undo is itself in history and can be undone (redo)
    redo = h.entries()[-1]
    assert redo.undoes == mid.id and redo.undo == [mid.cmd]


def test_escalation_entry_undoes_the_applied_stage(sim, phone: FakePhone) -> None:
    h = History(phone.serial)
    initial = phone.clone().state()
    executor.run(Plan("Force", [force_step("com.oplus.sauhelper")]), sim, yes, history=h)
    e = h.entries()[0]
    assert e.cmd == "pm suspend --user 0 com.oplus.sauhelper" and e.undo == ["pm unsuspend --user 0 com.oplus.sauhelper"]
    executor.run(h.undo([e.id]), sim, yes, history=h)
    assert phone.state() == initial


def test_dry_run_and_failed_entries_not_undoable(sim, phone: FakePhone) -> None:
    h = History(phone.serial)
    executor.run(disable_plan(TELEMETRY[:1]), sim, yes, history=h, dry_run=True)
    executor.run(Plan("Force", [force_step("com.oplus.safecenter")]), sim, yes, history=h)
    es = h.entries()
    assert es[0].dry_run and not es[0].undoable
    assert not es[1].ok and not es[1].undoable
    assert h.undo([e.id for e in es]).steps == []


def test_torn_line_is_tolerated(sim, phone: FakePhone) -> None:
    h = History(phone.serial)
    executor.run(disable_plan(TELEMETRY[:1]), sim, yes, history=h)
    with h.path.open("a") as f:
        f.write('{"type": "step", "id": "x", "ts"')  # crash mid-write
    assert len(h.entries()) == 1


def test_wireless_serial_filename(tmp_path) -> None:
    h = History("192.168.1.5:40123", tmp_path)
    assert h.path.name == "192.168.1.5_40123.jsonl"


def test_rollback_over_an_undo_does_not_redo(sim, phone: FakePhone) -> None:
    initial = phone.clone().state()
    h = History(phone.serial)
    executor.run(disable_plan(TELEMETRY[:2]), sim, yes, history=h)
    first = h.entries()[0]
    executor.run(h.undo([h.entries()[1].id]), sim, yes, history=h)   # undo the second one
    plan = h.rollback_to(first.id)
    assert [s.cmd for s in plan.steps] == [f"pm enable --user 0 {TELEMETRY[0]}"]
    executor.run(plan, sim, yes, history=h)
    assert phone.state() == initial
