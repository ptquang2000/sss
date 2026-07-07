# sss is config-location-agnostic — the caller may supply the config path

## Status

accepted (enables vmctl [ADR-0013](../../../docs/adr/0013-vmctl-owns-sync-config.md))

## Context

sss reads its profiles from a single global file, `~/.sss/config.json`, loaded
implicitly inside `connect()`. `load_config(path)` / `save_config(path)` already
accepted a path argument, but `connect()` called `load_config()` with no
argument and `select_profile` baked `CONFIG_PATH` into its "No profiles
configured in …" error message — so the file location was effectively hardcoded
for every library consumer.

A consumer (vmctl) wants to own the sync-config **location** and point sss at its
own file (`~/.vmctl/sync.json`) while keeping sss standalone-clean. sss is already
target-agnostic (ADR-0004); making it **config-location-agnostic** is the same
move applied to config: the caller decides where the config lives, sss decides
what it means.

## Decision

**`connect(..., config_path=None)`** — a new optional kwarg. When given, it is
passed to `load_config(config_path)` and threaded into `select_profile` so error
messages name the **actual** file consulted, not the default. When omitted, sss
falls back to `~/.sss/config.json` exactly as before, so standalone sss and its
CLI are unchanged. The sss CLI gains a symmetric `--config` option in the shared
target-option set.

`~/.sss/config.json` is now merely **the default when no `config_path` is
supplied** — not a hardcoded location. sss still owns the profile **schema** and
all parsing/selection/error-reporting; the caller owns only the path.

## Consequences

- vmctl points sss at `~/.vmctl/sync.json` without sss knowing what vmctl is
  (dependency stays one-way, ADR-0004).
- A missing caller-supplied file behaves like a missing default: empty profiles →
  `SssError("No profiles configured in <that path>")`, now naming the real file.
- Additive and reversible — every existing caller and the CLI keep working with
  no change.
