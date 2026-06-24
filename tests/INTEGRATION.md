# sss integration tests

The live suite (`test_integration.py`, `test_integration_vm.py`) drives a real
SSH target. It **always runs** under plain `pytest` — there is no opt-in env
gate. Following vmctl's convention, missing setup (no vmctl, unknown VM, failed
revert/boot, unreachable sshd) is surfaced as a **failure**, never a skip, so a
misconfigured environment can't masquerade as passing tests.

```bash
pytest tests                      # unit + live suite
pytest tests -k "not integration" # unit tests only, no network/VM
```

## Run against a VM (default — via vmctl auto-detect)

Leave `SSS_HOST` unset. The session-scoped fixture reverts a dedicated test VM
to a known snapshot, boots it once, and waits until vmctl resolves a guest IP
**and** TCP/22 answers. sss then auto-detects the VM through vmctl and reuses
its guest credentials as the SSH login.

One-time setup:

* VMware Workstation + a dedicated test VM (default `vmctl-unittest`) with a
  known snapshot (default `init`).
* **OpenSSH Server** installed, running, set to autostart, with password auth
  enabled for the `test` account.
* vmctl installed (`pip install -e ../vmctl`) and configured
  (`~/.vmctl/config.json` with the VM in `scan_roots` and credentials registered).

```bash
pytest tests
```

Env overrides: `SSS_VM` (VM name), `SSS_SNAPSHOT` (snapshot name).

## Run against a remote host

Set `SSS_HOST` to target a remote machine directly over SSH; no VM is
provisioned. The vmctl-seam tests (`test_integration_vm.py`) are skipped as
not-applicable in this mode.

```bash
export SSS_HOST=10.0.0.5
export SSS_USER=test
export SSS_PASSWORD=test
pytest tests/test_integration.py
```

## Isolation

Every destructive test operates inside a unique per-test scratch dir under the
target's TEMP, removed on teardown (even on failure). No real BarApp service,
process, or install path is ever touched. The `service.stop` force-kill path is
covered by unit tests (`test_primitives.py`), not against the live VM.
