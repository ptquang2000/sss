"""Shared fixtures for the live integration suite.

Follows vmctl's fail-loud convention: these fixtures **never skip** on missing
setup. A missing vmctl, an unknown VM, a failed revert/boot, or an unreachable
sshd is surfaced as a *failure* (``pytest.fail``), so a misconfigured
environment can never masquerade as passing tests. Plain ``pytest`` always
collects and runs the integration suite; unit-only runs use
``pytest -k "not integration"`` (the integration modules carry no in-code gate).

Targeting:

* ``SSS_HOST`` set -> remote-host mode. No VM is provisioned; the session
  connects directly over SSH (``SSS_USER`` / ``SSS_PASSWORD``).
* ``SSS_HOST`` unset -> VM mode. A dedicated test VM (``SSS_VM``, default
  ``vmctl-unittest``) is reverted to a known snapshot (``SSS_SNAPSHOT``, default
  ``init``), booted once per session, and auto-detected through vmctl.
"""

import os
import socket
import time
import uuid

import pytest

from sss import connect
from sss.target import VmctlProvider

VM_NAME = os.environ.get("SSS_VM", "vmctl-unittest")
SNAPSHOT = os.environ.get("SSS_SNAPSHOT", "init")
SSH_TIMEOUT_S = 180
SSH_POLL_S = 5


def _host_mode() -> bool:
    return bool(os.environ.get("SSS_HOST"))


def _tcp_open(host: str, port: int = 22, timeout: float = 5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_ssh(provider: VmctlProvider) -> dict:
    """Block until vmctl resolves a guest IP *and* TCP/22 answers, or fail loud.

    Boot alone isn't enough: the VM reports running while sshd is still coming
    up. Gate on both signals -- a resolved guest IP and a successful connect to
    port 22 -- before declaring the target ready.
    """
    deadline = time.time() + SSH_TIMEOUT_S
    last = "no guest IP resolved"
    while time.time() < deadline:
        try:
            target = provider.running_target()
        except Exception as e:  # running-but-no-IP, transient vmrun errors
            last, target = str(e), None
        else:
            if target and target.get("host"):
                if _tcp_open(target["host"]):
                    return target
                last = f"guest IP {target['host']} not yet accepting TCP/22"
        time.sleep(SSH_POLL_S)
    pytest.fail(
        f"VM {VM_NAME!r} booted but sshd never became reachable within "
        f"{SSH_TIMEOUT_S}s ({last})"
    )


@pytest.fixture(scope="session")
def provisioned_vm():
    """Revert the dedicated test VM to a clean snapshot, boot it, wait for sshd.

    Host mode (``SSS_HOST`` set): nothing to provision -> yield None. One boot
    per session; per-test isolation is the sandbox's job, not a per-test revert.
    """
    if _host_mode():
        yield None
        return

    try:
        import vmctl
    except ImportError as e:
        pytest.fail(
            f"vmctl is required to provision the test VM but is not installed "
            f"({e}). Install it (pip install -e ../vmctl) or set SSS_HOST."
        )

    try:
        vm = vmctl.VMCtl().get(VM_NAME)
    except Exception as e:
        pytest.fail(f"could not resolve test VM {VM_NAME!r} via vmctl: {e}")

    # Hard-stop before reverting (revert requires the VM off); ignore if already off.
    try:
        vm.power.stop(hard=True)
    except Exception:
        pass

    try:
        vm.snapshot.revert(SNAPSHOT)
        vm.power.start()
    except Exception as e:
        pytest.fail(f"failed to revert {VM_NAME!r} to {SNAPSHOT!r} and boot it: {e}")

    target = _wait_for_ssh(VmctlProvider())
    try:
        yield target
    finally:
        try:
            vm.power.stop(hard=True)
        except Exception:
            pass


@pytest.fixture(scope="session")
def session(provisioned_vm):
    """A connected ``Sss`` session against the host (SSS_HOST) or provisioned VM.

    In VM mode ``host`` is left unset so ``connect`` auto-detects the running VM
    through vmctl and reuses its guest credentials as the SSH login.
    """
    s = connect(
        host=os.environ.get("SSS_HOST"),
        user=os.environ.get("SSS_USER"),
        password=os.environ.get("SSS_PASSWORD"),
    )
    yield s
    s.close()


@pytest.fixture
def sandbox(session):
    """A unique scratch dir under the target's TEMP, removed on teardown.

    Every destructive op operates inside here, so no real service, process, or
    install path is ever touched. Cleanup runs even when the test fails.
    """
    out = session.exec("echo %TEMP%")["stdout"].strip()
    if not out or "%" in out:  # non-cmd shell left it unexpanded
        out = r"C:\Windows\Temp"
    temp = out.replace("\\", "/").rstrip("/")
    token = uuid.uuid4().hex[:12]
    scratch = f"{temp}/sss-it-{token}"
    session._conn.mkdir_p(scratch)
    try:
        yield {"dir": scratch, "token": token}
    finally:
        session.files.delete([scratch])
