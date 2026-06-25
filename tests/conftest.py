"""Shared fixtures for the live integration suite.

Host-only and target-agnostic: the suite connects to a plain SSH machine given
by ``SSS_HOST`` (with optional ``SSS_USER`` / ``SSS_PASSWORD``). There is no
vmctl import and no VM provisioning -- running sss's own tests needs only an
SSH-reachable host.

Fail-loud convention (no silent skips): a missing ``SSS_HOST`` or an unreachable
sshd is surfaced as a *failure* (``pytest.fail``), so a misconfigured
environment can never masquerade as passing tests. Plain ``pytest`` always
collects and runs the integration suite; unit-only runs use
``pytest -k "not integration"`` (the integration modules carry no in-code gate).
"""

import os
import socket
import uuid

import pytest

from sss import connect


def _tcp_open(host: str, port: int = 22, timeout: float = 5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def session():
    """A connected ``Sss`` session against the SSH host given by ``SSS_HOST``.

    Fails loudly if ``SSS_HOST`` is unset or its sshd is unreachable, rather than
    skipping -- a misconfigured environment must not look like a pass.
    """
    host = os.environ.get("SSS_HOST")
    if not host:
        pytest.fail("SSS_HOST is not set; the integration suite needs an SSH-reachable host.")
    if not _tcp_open(host):
        pytest.fail(f"SSS_HOST {host!r} is not accepting TCP/22.")

    s = connect(
        host=host,
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
