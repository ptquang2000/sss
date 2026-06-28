# sss — Context

`sss` refactors the legacy `legacy-sync/sync.py` monolith into a clean Python **package** usable two ways: a **CLI tool** (thin entrypoint) and an embeddable **library** (consumed by vmctl, an eventual MCP server). Primary purpose: **sync files to a machine over SSH**, plus run a fixed set of high-level **primitives** on it.

`sss` is **standalone and target-agnostic** — it knows only how to reach a machine over SSH, contains **no VMware/VM/vmctl code, and takes no such dependency** (see ADR-0004, which supersedes ADR-0001). Tools that know about VMs (vmctl) **depend on sss** and feed it a resolved `host`/credentials; sss never reaches back. This inverts the original design.

## Glossary

- **Target** — the machine sss acts on over **SSH**. Supplied **explicitly** by the caller (host + credentials); sss does not discover or classify it. Bare-metal vs VM is opaque to sss. _Avoid_: treating "VM" as a kind of target inside sss — that lives in the *caller*.
- **Transport** — how sss moves bytes / runs commands. **SSH is the only transport** (Paramiko SFTP for files, SSH exec for commands).
- **Primitive** — a high-level operation exposed as both library API and script step. Fixed vocabulary: `stop_service`/`start_service`, `stop_process`/`start_process`, `remove_files`/`delete_files`, plus `sync` and `exec`. (`push` is a CLI/library verb, **not** a primitive — not a scriptable step.) Windows-only impls now (`sc.exe`, `taskkill`, `del`) behind an **OS-agnostic interface** so Linux/mac can be added without API changes.
- **start_process** — the launch primitive. Contract is **launch on the target's interactive desktop, surviving SSH-session close** — not merely "run a process." Canonical use: `post_sync: start_process FooCorpClientUI.exe` (relaunch the GUI after sync), and the developer must *see* the window. Because an SSH-spawned process dies with the session's job object and a service-session launch is invisible, it launches via a one-shot **interactive scheduled task** (`schtasks /it /ru <ssh-user>`). **Fire-and-forget** — success means the launch was triggered, not that the child lives. A property of Windows-over-SSH, **not** of VMs. _Avoid_: "Start-Process" (rejected mechanism), "spawn". See ADR-0002.
- **sync** — the **profile-driven** transfer. Expands the resolved profile's `source_dirs`/`source_files` (sources relative to `project_dir`, the repo root, default cwd — see ADR-0005), honors `exclude` globs and `{var}` substitution; the middle step of the `sss sync` lifecycle (`pre_sync` → sync → `post_sync`). Upload-only (local → target over SFTP), mtime/size skip-unchanged. _Avoid_ using "sync" for an ad-hoc copy — that's **push**.
- **push** — an **on-demand, ad-hoc** transfer of one `source` to one `dest` (`sss push <source> <dest>`; library `s.sync.path(source, dest)`). Distinct from sync: **no profile, no `pre_sync`/`post_sync`, no excludes, no `{var}`**. `source` resolved **as-typed** (absolute, else relative to **cwd** — *not* `project_dir`); `dest` is always a remote **directory**. Reuses the sync engine: upload-only, mtime/size skip, recursive remote mkdir, same path-mapping — a file source lands at `dest/<basename>`, a directory source has its **contents merged into `dest`** (rsync trailing-slash semantics; no nesting as `dest/<dirname>`, no rename). _Avoid_: "copy", "scp", "send".
- **Script** — a **declarative** (YAML/JSON) list of primitive invocations attached to exactly **two lifecycle hooks: `pre_sync` and `post_sync`**. sss owns the lifecycle and runs steps in list order at each hook. No arbitrary code — only the fixed primitive vocabulary. Replaces the hardcoded BarApp orchestration in legacy `main()`. The legacy BarApp flow maps to:
  - `pre_sync`: `stop_service FooSvc` → `stop_process BarApp.exe` → `remove_files <driver paths>`
  - *(sync runs)*
  - `post_sync`: `delete_files <log dirs>` → `start_service FooSvc` → `start_process FooCorpClientUI.exe`

## Target addressing

- **Caller always supplies the target explicitly.** CLI: `--host <ip/name>` (required) plus `--user`/`--password`/`--port` (`--user`/`--password` optional when SSH keys/agent suffice). Library: `connect(host=..., user=..., password=..., port=...)`.
- **No auto-detection, no stored default target.** sss never scans for a "running" anything and stores **no host or credentials**. Missing `host` ⇒ clear error, not a guess.
- A VM-aware caller (vmctl) resolves the guest IP + creds itself and passes them in — that's how vmctl inherits sss's sync features without sss knowing what a VM is.

## Sync config

- Single **central config** at `~/.sss/config.json`. (Resemblance to `~/.vmctl/config.json` is convention, **not** a dependency or shared file.)
- Holds **only profiles** — the sync mapping (`source_dirs` → dest, `optional_dirs`, `exclude`, `source_files`) and lifecycle **scripts/hooks**. Holds **no target/host/credentials** (those are strictly CLI/library args).
- The applicable profile is **auto-selected by the project's git-remote URL** (legacy UX): run sss inside the repo and it picks the match. Falls back to the sole profile when exactly one is configured.

## Execution & API shape

- **All commands run over SSH** — a single execution path; no alternate (e.g. hypervisor guest-run) channel.
- **Library**: subsystem accessors — `s.service.stop(name)`, `s.process.kill(name)`, `s.files.remove([...])`, `s.sync.run()`, `s.sync.path(src, dest)`, `s.exec(cmd)`. `connect(host=..., user=..., password=...)` builds a ready session — the seam vmctl/MCP calls directly.
- **CLI**: Click command groups — `sss sync`, `sss push <source> <dest>`, `sss exec <cmd>`, `sss service stop <name>`, `sss process kill <name>`. Every command takes shared `--host/--user/--password/--port`. `push` needs no resolved profile.
- Package layout: `cli.py`, `config.py`, `connection.py` (SSH transport), `target.py` (builds `SSHConnection` from explicit host/creds), `sync.py`, `scripts.py` (runner), and `modules/` per primitive group.

## Out of scope / dropped from legacy

- Transports `scp`, `unc` (net use + PowerShell remoting), and `local` are **dropped** (only `ssh` survives).
- **All VMware/VM detection is out of scope** — `find_vmrun`/`vmcli`/DHCP-lease/`auto_detect_vm_ip`/guest-run never belonged in a sync tool; vmctl owns that and feeds sss a host.
- All baked-in BarApp specifics (FooSvc, BarApp.exe, drv1–drv4 drivers, log cleanup, FooCorpClientUI relaunch) become **user-authored declarative scripts**, not sss code.

## Testing

- **Unit tests only.** sss's suite runs with no network/target and **never imports vmctl**. No host gate, no `SSS_HOST`, no live SSH dependency.
- **Live coverage lives in vmctl.** Integration tests exercising sss's real primitives over SSH (SFTP, `sc.exe`, `del`/`rmdir`, `taskkill`, session-survival) were moved into vmctl's `tests/test_integration.py`. vmctl boots the VM, resolves IP + guest creds, and hands sss a plain host via `connect(...)` — the production handoff path. Keeps the dependency one-way (vmctl → sss) per ADR-0004.

## Side utilities (not part of sss)

- `remote_workspace.py` (VS Code `.code-workspace` generator) — standalone helper, out of scope.
- `copy_sdk.bat` (FooSdk DLL copy) — BarApp/FooSdk-specific; stays a separate batch file or becomes a user script. Out of scope.

## Related repos

- `../vmctl` — VMware Workstation wrapper. **Consumer of sss**, not a dependency: embeds sss (git submodule) and calls `sss.connect(host=<guest_ip>, …)` to sync into a VM. Dependency points vmctl → sss, never reverse.
- `../legacy-sync` — the legacy monolith being replaced.

> Status: re-grilled 2026-06-24 — VM/vmctl coupling removed; sss is standalone and target-agnostic.
