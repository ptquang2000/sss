# sss

SSH file-sync + a fixed vocabulary of remote primitives. A clean rewrite of the
legacy `legacy-sync/sync.py` monolith as a proper Python **package**, usable two
ways:

* **CLI** — `sss sync`, `sss exec`, `sss service stop`, … (Click groups).
* **Library** — subsystem-accessor API (`s.service.stop(...)`, `s.sync.run()`)
  that an MCP server can call directly.

sss does one thing well: **sync files over SSH** and run **high-level
primitives** on the target. It is **standalone and target-agnostic** — you give
it an explicit host plus optional credentials and it reaches that machine over
SSH; it knows nothing about VMs and never imports a VM tool (see
[ADR-0004](docs/adr/0004-standalone-no-vm-coupling.md)). App-specific steps live
in declarative `pre_sync`/`post_sync` scripts, not in code. SSH is the only
transport.

## Install

```bash
pip install -e .
```

## Configuration

Config defaults to `~/.sss/config.json`. The profile is auto-selected by the
project's git-remote URL — run sss from inside the repo and the matching profile
applies. See [`config.example.json`](config.example.json). A caller can point sss
at another file: `sss <cmd> --config <path> …` on the CLI, or
`connect(config_path=…)` in the library (the default file is merely the fallback
when no path is given).

```jsonc
{
  "profiles": {
    "git@github.com:foocorp/barapp.git": {
      "variables": { "build_cfg": "Release", "arch": "x86", "vm_dest_dir": "C:/Progra~2/FooCorp/BarApp Client" },
      "source_dirs": { "bin/{build_cfg}": ["{vm_dest_dir}"] },
      "exclude": ["*.pdb"],
      "pre_sync":  [{ "op": "stop_service",  "args": { "name": "FooSvc" } }],
      "post_sync": [{ "op": "start_service", "args": { "name": "FooSvc" } }]
    }
  }
}
```

A profile defines the sync mapping (`source_dirs` → dest, `optional_dirs`,
`source_files`, `exclude`) plus the lifecycle scripts. Source keys are
**repo-relative**: they resolve against `--project-dir` (the repo root, default
cwd), which is also what selects the profile by git remote (see ADR-0005).
`{var}` placeholders are substituted from `variables` (and CLI selectors like
`--debug`/`--arch`).

## CLI

```bash
sss sync --host 10.0.0.5 --user test --password test   # pre_sync → sync → post_sync
sss sync --host 10.0.0.5 --release --arch x64          # feed {build_cfg}/{arch} substitution
sss sync --host 10.0.0.5 --optional                    # include optional_dirs

sss exec --host 10.0.0.5 "hostname"
sss service stop --host 10.0.0.5 FooSvc
sss service start --host 10.0.0.5 FooSvc
sss process kill --host 10.0.0.5 BarApp.exe
sss process start --host 10.0.0.5 "C:/Progra~2/FooCorp/.../FooCorpClientUI.exe" showUI
sss files remove --host 10.0.0.5 "C:/.../libfoodrv.sys"
sss files delete --host 10.0.0.5 "C:/.../logs"
```

`--host` is **required** on every command — it names the machine to reach over
SSH. `--user`/`--password` are optional (publickey/agent auth works without
them).

## Library

```python
from sss import connect

s = connect(host="10.0.0.5", user="test", password="test")   # host required
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
| `target.py` | `Target` resolution: builds an `SSHConnection` from an explicit `--host` (+ optional creds). No VM knowledge. |
| `modules/` | Primitive subsystems: `service` (`sc.exe`), `process` (`taskkill`/PowerShell), `files` (`del`/`rmdir`). Windows now, OS-agnostic interface. |
| `scripts.py` | `ScriptRunner` — interprets declarative `pre_sync`/`post_sync` steps against a fixed vocabulary (no arbitrary code). |
| `config.py` | `~/.sss/config.json` + git-remote profile selection + variable substitution. |
| `cli.py` | Click groups. |

The primitive vocabulary: `stop_service` / `start_service`, `stop_process` /
`start_process`, `remove_files` / `delete_files`, plus `sync` and `exec`.

See [`CONTEXT.md`](CONTEXT.md) and
[`docs/adr/0004-standalone-no-vm-coupling.md`](docs/adr/0004-standalone-no-vm-coupling.md).

## Tests

```bash
pytest tests   # unit tests, no network or live target required
```

sss ships a **unit-only** suite — it needs no SSH host and never imports vmctl.
The live coverage of sss's own primitives (real SFTP, `sc.exe`, `del`/`rmdir`,
`taskkill`, session-survival) runs in **vmctl's** integration suite, which boots
a VM and drives sss against it over SSH. That keeps sss target-agnostic per
[`docs/adr/0004-standalone-no-vm-coupling.md`](docs/adr/0004-standalone-no-vm-coupling.md);
see the parent repo's `tests/INTEGRATION.md` for how to run it.
