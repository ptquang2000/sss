"""Live integration tests for the vmctl identity/credential seam (VM-only).

This is the seam a host-based test can never reach: ADR-0001's claim that sss
resolves a running VM's identity, IP, and guest credentials through vmctl and
*reuses the guest creds as the SSH login*. Black-box only -- the proof is that
``session.meta`` reports a fully-resolved VM identity and an ``exec`` built
solely from vmctl-supplied creds round-trips. We deliberately do not re-reach
into vmctl's private ``_config`` / ``_registry``; ``VmctlProvider`` owns those.

Skipped only in host mode (``SSS_HOST`` set) as not-applicable -- a deliberate
not-applicable skip, distinct from the fail-loud missing-setup contract.
"""

import os
import re

import pytest

pytestmark = pytest.mark.skipif(
    bool(os.environ.get("SSS_HOST")),
    reason="vmctl seam is not applicable in host mode (SSS_HOST set)",
)

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def test_meta_reports_resolved_vm_identity(session):
    meta = session.meta
    assert meta.get("kind") == "vm"
    assert meta.get("name"), "vmctl did not resolve a VM name"
    assert _IP_RE.match(meta.get("host") or ""), f"host is not IP-shaped: {meta.get('host')!r}"
    assert meta.get("user"), "vmctl did not supply a guest user"


def test_authenticated_exec_roundtrips(session):
    # A working command over a session authenticated solely from vmctl-supplied
    # guest credentials IS the end-to-end proof of credential reuse.
    result = session.exec("echo sss-vm-seam")
    assert result["exit_code"] == 0
    assert "sss-vm-seam" in result["stdout"]
