# sss integration tests

The live suite (`test_integration.py`) drives a real SSH host. It **always
runs** under plain `pytest` — there is no opt-in env gate. Missing setup
(`SSS_HOST` unset, unreachable sshd) is surfaced as a **failure**, never a skip,
so a misconfigured environment can't masquerade as passing tests.

```bash
pytest tests                      # unit + live suite
pytest tests -k "not integration" # unit tests only, no network
```

## Run against an SSH host

Set `SSS_HOST` to the machine to reach over SSH. sss is target-agnostic — it
needs no vmctl and no VM; any SSH-reachable host works. `SSS_USER` /
`SSS_PASSWORD` are optional (publickey/agent auth works without them).

One-time setup on the target (a Windows host, since the primitives are
Windows-only today):

* **OpenSSH Server** installed, running, set to autostart, with password auth
  enabled for the login account (if using `SSS_PASSWORD`).

```bash
export SSS_HOST=10.0.0.5
export SSS_USER=test
export SSS_PASSWORD=test
pytest tests
```

## Isolation

Every destructive test operates inside a unique per-test scratch dir under the
target's TEMP, removed on teardown (even on failure). No real service, process,
or install path is ever touched. The `service.stop` force-kill path is covered
by unit tests (`test_primitives.py`), not against the live host.
