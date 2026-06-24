"""Target resolution: VM path (provider mocked) vs --host; no-VM exits clearly."""

import pytest

from sss.exceptions import SssError
from sss.target import Target, VmProvider


class _StubProvider(VmProvider):
    def __init__(self, target):
        self._target = target

    def running_target(self):
        return self._target


def test_host_path_builds_ssh_without_provider():
    conn, meta = Target.resolve(host="10.0.0.5", user="me", password="pw", connect=False)
    assert meta == {"kind": "host", "host": "10.0.0.5", "user": "me"}
    assert conn.host == "10.0.0.5" and conn.username == "me"


def test_vm_path_uses_provider():
    provider = _StubProvider({"name": "win11", "host": "192.168.1.2", "user": "test", "password": "test"})
    conn, meta = Target.resolve(vm_provider=provider, connect=False)
    assert meta["kind"] == "vm" and meta["name"] == "win11"
    assert conn.host == "192.168.1.2" and conn.username == "test"


def test_no_running_vm_exits():
    provider = _StubProvider(None)
    with pytest.raises(SssError, match="No VM is running"):
        Target.resolve(vm_provider=provider, connect=False)


def test_host_takes_precedence_over_vm():
    provider = _StubProvider({"name": "vm", "host": "1.1.1.1", "user": "u", "password": "p"})
    conn, meta = Target.resolve(host="9.9.9.9", user="x", vm_provider=provider, connect=False)
    assert meta["kind"] == "host" and conn.host == "9.9.9.9"
