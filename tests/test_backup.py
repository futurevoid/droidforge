"""P2.4: session backups (R-11.3) - evidence + baseline; restore only droidforge's own changes."""

from __future__ import annotations

from pathlib import Path

from droidforge.adb.sim import FakePhone
from droidforge.engine import executor
from droidforge.engine.history import History
from droidforge.engine.snapshot import Snapshot
from droidforge.features import backup
from droidforge.session import open_session
from tests.helpers import TELEMETRY, disable_plan, yes


def test_session_backup_is_full_and_read_only(sim, phone: FakePhone, tmp_path: Path) -> None:
    before = phone.state()
    path = backup.session_backup(sim, tmp_path)
    assert phone.state() == before and path.parent == tmp_path / phone.serial
    snap = Snapshot.load(path)
    assert "font_scale" in snap.settings["system"] and "private_dns_mode" in snap.settings["global"]
    assert "com.android.settings" in snap.app_locales            # every package, not just user apps
    assert snap.config["mMaterialColor"] and snap.packages["com.heytap.market"]["enabled"]
    assert backup.list_backups(phone.serial, tmp_path) == [path]


def test_session_start_writes_backup(df_home: Path) -> None:
    s = open_session(simulate=True)
    path = s.start()
    assert path.exists() and "backups" in str(path)


def test_changes_since(sim, phone: FakePhone, tmp_path: Path) -> None:
    path = backup.session_backup(sim, tmp_path)
    phone.settings["system"]["font_scale"] = "1.3"
    assert [str(c) for c in backup.changes_since(sim, path)] == ["setting:system:font_scale: 1.0 -> 1.3"]


def test_restore_reverts_only_droidforge_changes(sim, phone: FakePhone, tmp_path: Path) -> None:
    h = History(phone.serial)
    executor.run(disable_plan(TELEMETRY[:1]), sim, yes, history=h)          # before the backup: not included
    path = backup.session_backup(sim, tmp_path)
    executor.run(disable_plan(TELEMETRY[1:3]), sim, yes, history=h)
    phone.settings["system"]["font_scale"] = "1.3"                           # foreign change (not droidforge)
    phone.packages["com.whatsapp"].enabled = False                            # foreign package change
    plan = backup.restore_plan(sim, h, path)
    assert sorted(s.cmd for s in plan.steps) == sorted(f"pm enable --user 0 {p}" for p in TELEMETRY[1:3])
    notes = "\n".join(plan.notes)
    assert "not by droidforge" in notes and "font_scale" in notes and "com.whatsapp" in notes
    assert "Reset all settings" in notes
    assert not any("settings put" in s.cmd for s in plan.steps)                # no blanket restore
    phone.settings["system"]["font_scale"] = "1.0"   # so the health gate does not stop the restore itself
    phone.packages["com.whatsapp"].enabled = True
    assert executor.run(plan, sim, yes, history=h).status == "done"
    assert all(phone.packages[p].enabled for p in TELEMETRY[1:3])
    assert not phone.packages[TELEMETRY[0]].enabled                             # older change untouched


def test_restore_when_nothing_changed(sim, phone: FakePhone, tmp_path: Path) -> None:
    path = backup.session_backup(sim, tmp_path)
    plan = backup.restore_plan(sim, History(phone.serial), path)
    assert plan.steps == [] and "Nothing changed since this backup." in plan.notes
