"""Session: device selection rules."""

from __future__ import annotations

import pytest

from droidforge.session import ConnectError, open_session, pick_serial


def test_pick_serial() -> None:
    assert pick_serial([("A", "device")], None) == "A"
    assert pick_serial([("A", "device"), ("B", "device")], "B") == "B"
    with pytest.raises(ConnectError, match="--serial"):
        pick_serial([("A", "device"), ("B", "device")], None)
    with pytest.raises(ConnectError, match="unauthorized"):
        pick_serial([("A", "unauthorized")], None)
    with pytest.raises(ConnectError, match="no device"):
        pick_serial([], None)
    with pytest.raises(ConnectError, match="not connected"):
        pick_serial([("A", "device")], "Z")


def test_pick_serial_explains_linux_usb_states() -> None:
    no_perm = "no permissions (user in plugdev group; are your udev rules wrong?)"
    with pytest.raises(ConnectError, match="udev"):
        pick_serial([("????????????", no_perm)], None)
    with pytest.raises(ConnectError, match="offline"):
        pick_serial([("A", "offline")], None)
    with pytest.raises(ConnectError, match="unauthorized"):
        pick_serial([("A", "authorizing")], None)
    with pytest.raises(ConnectError, match="not ready"):
        pick_serial([("A", "recovery")], None)
    with pytest.raises(ConnectError, match="File transfer"):
        pick_serial([], None)


def test_simulated_session_uses_guarded_device() -> None:
    s = open_session(simulate=True)
    assert s.simulate and s.phone is not None and s.device.serial == s.phone.serial
    assert s.device.read_guard is not None and s.device.write_guard is not None
