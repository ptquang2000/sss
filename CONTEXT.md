# sss — Context

`sss` is a refactor of the legacy `legacy-sync/sync.py` monolith into a clean Python
**package** that is usable two ways:

1. **CLI tool** — a thin entrypoint over the library.
2. **Library** — embeddable, intended for an eventual (not-yet-existing) "vm mcp server".

Primary purpose: **sync files between machines over SSH**, plus run a fixed set of
**high-level operations** ("primitives") on the target.

## Glossary

- **Target** — the machine sss acts on. Two kinds:
  - **remote machine** — reachable over SSH only.
  - **VM** — a local VMware Workstation guest, addressed via [vmctl](#vmctl).
- **Transport** — how sss moves bytes / runs commands on a target. **SSH is the only
  sss transport.** File sync is *always* SSH (Paramiko SFTP), for both remote machines
  and VMs.
- **vmctl** — a separate, existing Python package + CLI (`../vmctl`) that wraps VMware
  `vmcli.exe`/`vmrun.exe` with JSON-native, name-based VM addressing. sss **imports
  vmctl as a library dependency**. For VM targets, sss delegates to vmctl for: VM
  identity (by name), IP resolution, **guest credentials** (reused as the VM's SSH
  login — single source of truth, no separate sss credential store), and guest command
  execution. sss contains **no VMware code of its own** (the legacy ~400 lines of
  `find_vmrun`/`vmcli`/DHCP-lease/`auto_detect_vm_ip`/guest-run are deleted). See
  [docs/adr/0001-depend-on-vmctl.md](docs/adr/0001-depend-on-vmctl.md).
- **Primitive** — a high-level operation sss exposes as both library API and script
  step. Fixed vocabulary: `stop_service` / `start_service`, `stop_process` /
  `start_process`, `remove_files` / `delete_files`, plus `sync` and `exec`.
  (`push` is a CLI/library verb, **not** a primitive — it is not a scriptable step;
  see below.)
  Windows-only implementations now (`sc.exe`, `taskkill`, `del`), but behind an
  **OS-agnostic interface** so Linux/mac can be added later without API changes.
- **start_process** — the launch primitive. Its contract is **launch on the
  target's interactive desktop, surviving SSH-session close** — not merely "run a
  process." The canonical use is `post_sync: start_process FooCorpClientUI.exe`
  (relaunch the BarApp GUI after a sync), and the developer must *see* the window.
  Because a process spawned over SSH dies with the session's job object and a
  service-session launch is invisible, `start_process` launches via a one-shot
  **interactive scheduled task** (`schtasks /it /ru <ssh-user>`). It is
  **fire-and-forget**: success means the launch was triggered, not that the child
  is still alive. _Avoid_: "Start-Process" (the rejected mechanism), "spawn".
  See [docs/adr/0002-start-process-interactive-launch.md](docs/adr/0002-start-process-interactive-launch.md).
- **sync** — the **profile-driven** transfer. Expands the resolved profile's
  `source_dirs`/`source_files` mapping (sources relative to `base_dir`), honors the
  profile's `exclude` globs and `{var}` substitution, and is the middle step of the
  `sss sync` lifecycle (`pre_sync` → sync → `post_sync`). Upload-only (local → target
  over SFTP), mtime/size skip-unchanged. _Avoid_ using "sync" for an ad-hoc one-off
  copy — that is **push**.
- **push** — an **on-demand, ad-hoc** transfer of one `source` to one `dest`,
  invoked as `sss push <source> <dest>` (library: `s.sync.path(source, dest)`).
  Deliberately distinct from **sync**: **no profile, no `pre_sync`/`post_sync` hooks,
  no excludes, no `{var}` substitution**. The `source` is resolved **as-typed**
  (absolute, else relative to **cwd** — *not* `base_dir`); `dest` is always a remote
  **directory**. Reuses the `sync` engine internals, so: upload-only, mtime/size
  skip-unchanged, recursive remote mkdir, and the same path-mapping rule — a file
  source lands at `dest/<basename>`, a directory source has its **contents merged
  into `dest`** (rsync trailing-slash semantics; it does *not* nest as
  `dest/<dirname>`, and there is **no rename**). _Avoid_: "copy", "scp", "send".
- **Script** — a **declarative** (YAML/JSON) list of primitive invocations, attached to
  one of exactly **two lifecycle hooks: `pre_sync` and `post_sync`**. sss owns the sync
  lifecycle and runs the user's steps in list order at each hook. No arbitrary code
  execution — steps may only call the fixed primitive vocabulary. This replaces the
  hardcoded BarApp orchestration in the legacy `main()`. The legacy BarApp flow maps to:
  - `pre_sync`: `stop_service FooSvc` → `stop_process BarApp.exe` →
    `remove_files <driver paths>`
  - *(sync runs)*
  - `post_sync`: `delete_files <log dirs>` → `start_service FooSvc` →
    `start_process FooCorpClientUI.exe`

## Target addressing

- **Default**: sss asks vmctl for the running VM and targets it. If **no VM is
  running, sss exits** (no manual-IP prompt, unlike legacy).
- **Override**: `--host IP --user ...` targets a **remote non-VM machine** over SSH
  instead. VM is the default path; remote host is the explicit path.

## Sync config

- Single **central config** at `~/.sss/config.json` (mirrors vmctl's
  `~/.vmctl/config.json` location/convention).
- The mapping that applies is **auto-selected by the project's git-remote URL** (legacy
  UX preserved): run sss from inside the repo, it picks the matching profile.
- A profile defines the sync mapping (`source_dirs` → dest, `exclude`, individual
  `source_files`) and the lifecycle **scripts/hooks** (declarative primitive steps).

## Command execution model

- **Remote machine**: simple commands run over **SSH**.
- **VM**: simple commands run over **SSH or vmctl** (vmctl guest-run when no network /
  SSH path is available).

## Public API & CLI shape (mirrors vmctl)

- **Library**: subsystem accessors, like vmctl's `vm.power.start()`. e.g.
  `s.service.stop(name)`, `s.process.kill(name)`, `s.files.remove([...])`,
  `s.sync.run()`, `s.exec(cmd)`. An MCP server calls these directly.
- **CLI**: Click command groups mirroring vmctl. e.g. `sss sync`, `sss exec <cmd>`,
  `sss service stop <name>`, `sss process kill <name>`. Plus `sss push <source>
  <dest>` for an ad-hoc, profile-less transfer (see **push** in the glossary).
  `push` does not require a profile to be resolved.
- Package layout follows vmctl: `cli.py`, `config.py`, a registry/session, a `runner`,
  and a `modules/` (or subsystems) dir per primitive group.

## Out of scope / dropped from legacy

- Transports `scp`, `unc` (net use + PowerShell remoting), and `local` are **dropped**
  (only `ssh` survives).
- All baked-in BarApp specifics (FooSvc, BarApp.exe, drv1/drv2/drv3/drv4 drivers, log
  cleanup, FooCorpClientUI relaunch) become **user-authored declarative scripts**, not
  sss code.

## Migration approach

**Clean package build**, not an in-place transform. Start fresh as a proper Python
package (`pyproject.toml`, modules mirroring vmctl). Port only the genuinely reusable
logic from `sync.py`:

- SSH/SFTP connection (`SSHConnection`) and the file-diff **sync engine** (mtime/size
  skip + `exclude` glob handling).
- The Windows **primitive implementations**: service control (`sc.exe`), process kill
  (`taskkill`/PowerShell), file remove/delete.

Dropped on the floor: all VMware detection (→ vmctl), `scp`/`unc`/`local` transports,
baked-in BarApp orchestration (→ user scripts), `remote_workspace.py`, `copy_sdk.bat`.

## Side utilities (not part of sss)

- `remote_workspace.py` (VS Code `.code-workspace` generator) — stays a standalone
  helper, out of sss scope.
- `copy_sdk.bat` (FooSdk SDK DLL copy) — BarApp/FooSdk-specific; stays a separate batch file
  or becomes a user script. Out of sss scope.

## Related repos

- `../vmctl` — VMware Workstation wrapper (hard dependency for VM targets).
- `../legacy-sync` — the legacy monolith being replaced.

> Status: design settled (grilling complete 2026-06-22). Ready to scaffold the package.
