"""Shared fixtures. Every test runs with DROIDFORGE_HOME in a temp dir (never the real home)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def df_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "dfhome"
    monkeypatch.setenv("DROIDFORGE_HOME", str(home))
    return home


@pytest.fixture
def phone():
    from droidforge.adb.sim import neo8_cn
    return neo8_cn()


@pytest.fixture
def sim(phone):
    """Device(SimBackend(FakePhone)) - the only 'phone' any test talks to."""
    from droidforge.adb.sim import sim_device
    from droidforge.log import Logger
    return sim_device(phone, log=Logger(3), read_guard=None, write_guard=None)
