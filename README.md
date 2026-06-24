# sss

SSH file-sync + a fixed vocabulary of remote primitives. A clean rewrite of the
legacy `legacy-sync/sync.py` monolith as a proper Python **package**, usable two
ways:

* **CLI** — `sss sync`, `sss exec`, `sss service stop`, … (Click groups
  mirroring [vmctl](../vmctl)).
* **Library** — subsystem-accessor API (`s.service.stop(...)`, `s.sync.run()`)
  that an MCP server can call directly.

sss does one thing well: **sync files over SSH** and run **high-level
primitives** on the target. All VM concerns are delegated to `vmctl`. All BarApp
specifics live in declarative `pre_sync`/`post_sync` scripts, not in code. SSH is
the only transport.

## Install

```bash
pip install -e .
# For VM (auto-detect) targets, also install the sibling vmctl:
pip install -e ../vmctl
```

## Configuration

Central config at `~/.sss/config.json`. The profile is auto-selected by the
project's git-remote URL — run sss from inside the repo and the matching profile
applies. See [`config.example.json`](config.example.json).

```jsonc
{
  "base_dir": "C:\\Users\\you",
  "profiles": {
    "git@github.com:foocorp/barapp.git": {
      "variables": { "build_cfg": "Release", "arch": "x86", "vm_dest_dir": "C:/Progra~2/FooCorp/BarApp Client" },
      "source_dirs": { "barapp/bin/{build_cfg}": ["{vm_dest_dir}"] },
      "exclude": ["*.pdb"],
      "pre_sync":  [{ "op": "stop_service",  "args": { "name": "FooSvc" } }],
      "post_sync": [{ "op": "start_service", "args": { "name": "FooSvc" } }]
    }
  }
}
```

A profile defines the sync mapping (`source_dirs` → dest, `optional_dirs`,
`source_files`, `exclude`) plus the lifecycle scripts. `{var}` placeholders are
substituted from `variables` (and CLI selectors like `--debug`/`--arch`).

## CLI

```bash
sss sync                          # auto-detect VM, run pre_sync → sync → post_sync
sss sync --release --arch x64     # feed {build_cfg}/{arch} substitution
sss sync --host 10.0.0.5 --user test --password test   # remote machine
sss sync --optional               # include optional_dirs

sss exec "hostname"
sss service stop FooSvc
sss service start FooSvc
sss process kill BarApp.exe
sss process start "C:/Progra~2/FooCorp/.../FooCorpClientUI.exe" showUI
sss files remove "C:/.../libfoodrv.sys"
sss files delete "C:/.../logs"
```

Every command auto-detects the running VM by default; pass `--host`/`--user` to
target a remote machine over SSH instead. If no VM is running and no `--host` is
given, sss exits clearly rather than prompting.

## Library

```python
from sss import connect

s = connect(host="10.0.0.5", user="test", password="test")   # or omit host -> VM
s.service.stop("FooSvc")
s.process.kill("BarApp.exe")
s.files.remove(["C:/.../libfoodrv.sys"])
s.sync.run()                  # mapping diff + upload
s.exec("hostname")
s.run_lifecycle()             # pre_sync → sync → post_sync
s.close()
```

## Architecture

| Module | Responsibility |
| --- | --- |
| `connection.py` | `Connection` interface + `SSHConnection` (Paramiko SFTP/exec). |
| `sync.py` | `SyncEngine` — mapping expansion, `{var}` substitution, exclude globs, mtime/size skip-unchanged diff, recursive remote mkdir. |
| `target.py` | `Target` resolution: VM (via `VmctlProvider`) vs `--host`. vmctl imported only on the VM path. |
| `modules/` | Primitive subsystems: `service` (`sc.exe`), `process` (`taskkill`/PowerShell), `files` (`del`/`rmdir`). Windows now, OS-agnostic interface. |
| `scripts.py` | `ScriptRunner` — interprets declarative `pre_sync`/`post_sync` steps against a fixed vocabulary (no arbitrary code). |
| `config.py` | `~/.sss/config.json` + git-remote profile selection + variable substitution. |
| `cli.py` | Click groups. |

The primitive vocabulary: `stop_service` / `start_service`, `stop_process` /
`start_process`, `remove_files` / `delete_files`, plus `sync` and `exec`.

See [`CONTEXT.md`](CONTEXT.md) and [`docs/adr/0001-depend-on-vmctl.md`](docs/adr/0001-depend-on-vmctl.md).

## Tests

```bash
pytest tests -k "not integration"   # unit tests, no network/VM
pytest tests                        # + live suite: provisions a VM and fails loud if unset
```

The live suite always runs under plain `pytest` (no opt-in gate) and **fails**
rather than skips when no VM/vmctl/SSH target is available. See
[tests/INTEGRATION.md](tests/INTEGRATION.md) for the one-time VM setup.
