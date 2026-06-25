# 4. sss is standalone and target-agnostic; the VM dependency is inverted

Date: 2026-06-24

## Status

Accepted. Supersedes [0001-depend-on-vmctl](0001-depend-on-vmctl.md).

## Context

ADR-0001 made sss **import vmctl** to auto-detect a running VM, resolve its guest
IP, and reuse its guest credentials as the SSH login. That coupled a generic
SSH file-sync tool to a VMware-control tool, conflated "target" with "VM", and
made sss's default code path depend on a sibling package.

The intent has since flipped. sss should be a clean, reusable **file-sync module
that knows nothing about VMs** — usable to sync to *any* SSH-reachable machine —
and the VM-control tool (vmctl) should be the one that *inherits* sss's sync
features by depending on sss, not the other way around.

In practice the seam was already small: vmctl was only ever an **optional** extra,
and `--host` already bypassed it entirely. The VM logic lived almost wholly in
`target.py`'s `VmctlProvider` plus the test harness.

## Decision

sss takes **no VM/vmctl dependency of any kind** and contains no code that knows
what a VM is. Concretely:

- **The target is always supplied explicitly by the caller.** CLI requires
  `--host` (plus optional `--user`/`--password`/`--port`); the library's
  `connect(host=..., user=..., password=..., port=...)` is the entry seam. There
  is **no auto-detection** and **no stored default target** — sss persists no host
  or credentials in its config (config holds only sync profiles + scripts).
- **`target.py` collapses to an SSH-connection builder.** The `VmProvider` /
  `VmctlProvider` abstraction and the "auto-detect running VM" branch are deleted.
- **The `vm` optional dependency / extra is removed** from packaging.
- **The dependency direction inverts.** vmctl embeds sss (git submodule) and calls
  `sss.connect(host=<guest_ip>, user=…, password=…)` after resolving the VM itself.
  vmctl → sss; never sss → vmctl.
- **Tests:** sss's integration suite is host-only (`SSS_HOST`/`SSS_USER`/
  `SSS_PASSWORD`). The vmctl seam test is deleted. Any VM-boot harness that drives
  sss against a reverted VM belongs to vmctl's test suite.

`start_process`'s interactive-scheduled-task mechanism ([ADR-0002](0002-start-process-interactive-launch.md))
is **unchanged** — it is a Windows-over-SSH property (escaping the SSH job object,
landing on the interactive desktop), not a VM property, and applies to any Windows
target with a logged-on console session.

## Consequences

**Positive**

- sss is a self-contained sync library with one job and one transport; no sibling
  package needed to use it.
- The dependency graph is sane: the VM tool depends on the sync tool, not vice
  versa. vmctl gains `sync`/`push`/`exec`/primitives by composition.
- Smaller, simpler `target.py`; no graceful-import dance, no `_config`/`_registry`
  reach-ins.

**Negative / risks**

- Convenience lost: a developer can no longer run `sss sync` with no arguments and
  have it find the running VM. They must pass `--host` (or use vmctl, which does the
  resolution). Accepted — that resolution is vmctl's responsibility.
- Credentials are no longer sourced from `~/.vmctl/config.json`; the caller provides
  them. For VM targets, vmctl supplies its guest creds when it calls `connect`.

## Alternatives considered

- **Keep a generic pluggable target-provider seam in sss** (rename off "VM") so an
  external tool injects a resolved host — rejected: still bakes an extension point
  whose only consumer is vmctl, when `connect(host=…)` already *is* that seam.
- **Store the target in the profile/config** so `sss sync` needs no `--host` —
  rejected: target is strictly an explicit per-call argument; config stays
  sync-mapping-only.
