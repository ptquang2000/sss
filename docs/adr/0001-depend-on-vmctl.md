# 1. Depend on vmctl for all VM operations; delete sss's own VMware code

Date: 2026-06-22

## Status

Superseded by [0004-standalone-no-vm-coupling](0004-standalone-no-vm-coupling.md) (2026-06-24).

The dependency direction is now **inverted**: sss takes no VM dependency, and
vmctl (a VM-control tool) instead depends on sss and feeds it a resolved host.
The reasoning below is retained for history.

## Context

The legacy `legacy-sync/sync.py` carried ~400 lines of VMware Workstation logic:
`find_vmrun`/`find_vmcli` discovery, `get_running_vms`, DHCP-lease parsing,
`auto_detect_vm_ip`, `vmcli_run_process`, and VMware Tools state checks. It used these
only to (a) discover a running VM and its IP so it could SSH to it, and (b) run
processes inside the guest.

A sibling tool, `vmctl` (`../vmctl`), already exists and does all of this better: a
JSON-native Python package + Click CLI wrapping `vmcli`/`vmrun`, with name-based VM
lookup, IP/tools queries, guest run/copy, and per-VM credentials in
`~/.vmctl/config.json`. Both tools are Python.

`sss` is mainly an SSH file-sync tool. Its only need from the hypervisor is: resolve the
running VM's IP and credentials (to SSH in) and, optionally, run guest commands when no
network path exists.

## Decision

`sss` takes `vmctl` as a **library dependency** and **deletes all of its own VMware
code**. For VM targets, sss delegates to vmctl for VM identity, IP resolution, guest
credentials (reused as the SSH login), and guest command execution. File sync remains
SSH-only.

## Consequences

**Positive**

- Removes the single largest and most brittle chunk of the legacy code (DHCP parsing,
  vmrun timeouts, tool-path discovery).
- Single source of truth for VM identity and credentials (`~/.vmctl/config.json`).
- The two sibling tools stay consistent (same config convention, same VM names).

**Negative / risks**

- A "sync tool" now hard-depends on a VM-control tool — surprising, and couples their
  release cycles. Mitigated because both are ours and Python.
- vmctl must be installed for VM targets. Pure remote-host (`--host`) SSH usage does not
  need vmctl, so the import should fail gracefully / be required only on the VM path.
- Assumes a VM's SSH login equals its vmctl guest account (true for current test VMs).

## Alternatives considered

- **Keep a built-in VMware fallback in sss** — rejected: duplicates vmctl, keeps the
  bloat, two code paths to maintain.
- **Shell out to the vmctl CLI** instead of importing it — rejected for the tighter,
  type-safe library call since both are Python (revisit if version drift becomes a
  problem).
