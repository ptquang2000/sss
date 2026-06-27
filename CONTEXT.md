# sss — Context

`sss` is a refactor of the legacy `legacy-sync/sync.py` monolith into a clean Python
**package** that is usable two ways:

1. **CLI tool** — a thin entrypoint over the library.
2. **Library** — embeddable; consumed directly by other tools (e.g. vmctl, an
   eventual MCP server).

Primary purpose: **sync files to a machine over SSH**, plus run a fixed set of
**high-level operations** ("primitives") on that machine.

`sss` is **standalone and target-agnostic**: it knows only how to reach a machine
over SSH. It contains **no VMware / VM / vmctl code and takes no such dependency**
— see [docs/adr/0004-standalone-no-vm-coupling.md](docs/adr/0004-standalone-no-vm-coupling.md),
which supersedes the original [0001](docs/adr/0001-depend-on-vmctl.md). Tools that
*do* know about VMs (such as vmctl) **depend on sss** and feed it a resolved
`host`/credentials; sss never reaches back. This is the inverse of the original
design.

## Glossary

- **Target** — the machine sss acts on, reachable over **SSH**. It is supplied
  **explicitly** by the caller (host + credentials); sss does not discover or
  classify it. Whether that host happens to be a bare-metal box or a VM is opaque
  to sss.
  _Avoid_: treating "VM" as a kind of target inside sss — that distinction lives in
  the *caller*, not here.
- **Transport** — how sss moves bytes / runs commands on a target. **SSH is the only
  transport** (Paramiko SFTP for files, SSH exec for commands).
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
  is still alive. This is a property of Windows-over-SSH, **not** of VMs — it
  applies to any Windows target with an interactive console session logged on.
  _Avoid_: "Start-Process" (the rejected mechanism), "spawn".
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

- **The caller always supplies the target explicitly.** CLI: `--host <ip/name>`
  (required) plus `--user` / `--password` / `--port` (`--user`/`--password` optional
  when SSH keys/agent suffice). Library: `connect(host=..., user=..., password=...,
  port=...)`.
- **No auto-detection, no stored default target.** sss never scans for a "running"
  anything and stores **no host or credentials** in its config. If `host` is missing,
  sss errors clearly rather than guessing.
- **A VM-aware caller (e.g. vmctl) resolves the guest IP + credentials itself and
  passes them in.** That is how vmctl "inherits" sss's sync features without sss
  knowing what a VM is.

## Sync config

- Single **central config** at `~/.sss/config.json`. (Path/style coincidentally
  resembles `~/.vmctl/config.json`; this is a convention, **not** a dependency or a
  shared file.)
- The config holds **only profiles** — the sync mapping (`source_dirs` → dest,
  `optional_dirs`, `exclude`, individual `source_files`) and the lifecycle
  **scripts/hooks** (declarative primitive steps). It holds **no target/host/
  credentials** (those are strictly CLI/library arguments).
- The profile that applies is **auto-selected by the project's git-remote URL**
  (legacy UX preserved): run sss from inside the repo and it picks the matching
  profile. Falls back to the sole profile when exactly one is configured.

## Command execution model

- **All commands run over SSH.** There is a single execution path; sss has no
  alternate (e.g. hypervisor guest-run) channel.

## Public API & CLI shape

- **Library**: subsystem accessors, e.g. `s.service.stop(name)`,
  `s.process.kill(name)`, `s.files.remove([...])`, `s.sync.run()`,
  `s.sync.path(src, dest)`, `s.exec(cmd)`. `connect(host=..., user=..., password=...)`
  builds a ready session — this is the seam an MCP server or vmctl calls directly.
- **CLI**: Click command groups. e.g. `sss sync`, `sss push <source> <dest>`,
  `sss exec <cmd>`, `sss service stop <name>`, `sss process kill <name>`. Every
  command takes the shared `--host/--user/--password/--port` target options.
  `push` does not require a profile to be resolved.
- Package layout: `cli.py`, `config.py`, `connection.py` (the SSH transport),
  `target.py` (builds an `SSHConnection` from explicit host/creds), `sync.py`, a
  `scripts.py` runner, and a `modules/` dir per primitive group.

## Out of scope / dropped from legacy

- Transports `scp`, `unc` (net use + PowerShell remoting), and `local` are **dropped**
  (only `ssh` survives).
- **All VMware/VM detection is out of scope** — `find_vmrun`/`vmcli`/DHCP-lease/
  `auto_detect_vm_ip`/guest-run never belonged in a sync tool. A VM-control tool
  (vmctl) owns that and feeds sss a host.
- All baked-in BarApp specifics (FooSvc, BarApp.exe, drv1/drv2/drv3/drv4 drivers, log
  cleanup, FooCorpClientUI relaunch) become **user-authored declarative scripts**, not
  sss code.

## Testing

- **Unit tests only.** sss's own suite runs with no network/target and **never
  imports vmctl**. There is no host gate, no `SSS_HOST`, no live SSH dependency.
- **Live coverage lives in vmctl.** The integration tests that exercise sss's
  real primitives over SSH (SFTP, `sc.exe`, `del`/`rmdir`, `taskkill`,
  session-survival) were moved into the **vmctl** repo's `tests/test_integration.py`.
  vmctl boots the VM, resolves its IP + guest creds, and hands sss a plain host
  via `connect(...)` — the production handoff path. This keeps the dependency
  direction one-way (vmctl → sss) per [ADR-0004](docs/adr/0004-standalone-no-vm-coupling.md).

## Side utilities (not part of sss)

- `remote_workspace.py` (VS Code `.code-workspace` generator) — stays a standalone
  helper, out of sss scope.
- `copy_sdk.bat` (FooSdk SDK DLL copy) — BarApp/FooSdk-specific; stays a separate batch file
  or becomes a user script. Out of sss scope.

## Related repos

- `../vmctl` — VMware Workstation wrapper. **Consumer of sss**, not a dependency:
  vmctl embeds sss (git submodule) and calls `sss.connect(host=<guest_ip>, …)` to
  sync into a VM. The dependency points vmctl → sss, never the reverse.
- `../legacy-sync` — the legacy monolith being replaced.

> Status: re-grilled 2026-06-24 — VM/vmctl coupling removed; sss is standalone and
> target-agnostic. vmctl inherits sss's sync features as a consumer.
