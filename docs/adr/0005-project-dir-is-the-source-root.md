# 5. project_dir is the single source-resolution root; base_dir is removed

Date: 2026-06-28

## Status

Accepted.

## Context

sss had **two** directory inputs that callers routinely confused:

- **`project_dir`** — a per-invocation path (CLI `--project-dir`, default cwd) read
  only to pick the sync profile: `git config --get remote.origin.url` in that dir is
  matched against the `profiles` map in `~/.sss/config.json`.
- **`base_dir`** — a global key in `~/.sss/config.json` (default `%USERPROFILE%`) that
  a profile's relative `source_dirs` / `source_files` / `optional_dirs` keys resolve
  against (`base_dir + rel = abs source`).

They anchored at *different* directories on purpose: `base_dir` was the **parent** of
the repo, so every profile key carried a repo-name prefix (`barapp/bin/{build_cfg}`),
and `project_dir` pointed at the repo itself (`…/barapp`) for git-remote detection.

In practice, every profile's source paths live **inside the project repo**. Sources
outside the repo never occur. That makes the separate `base_dir` anchor pure
ceremony: the repo root could serve as the resolution root, and then `project_dir`
and `base_dir` are the same directory.

## Decision

**`project_dir` is the one directory input.** It does double duty: git-remote profile
selection *and* the root that a profile's relative source paths resolve against.
`base_dir` is **removed** — from `~/.sss/config.json`, from `connect()`, from `Sss` /
`_SyncSubsystem`, and from `SyncEngine` (whose constructor takes `project_dir`).

- **Resolution root = `project_dir`, defaulting to cwd** (was `%USERPROFILE%`). Run
  sss from inside the repo, or pass `--project-dir <repo>`.
- **Profile source keys become repo-relative.** Drop the repo-name prefix:
  `barapp/bin/{build_cfg}` → `bin/{build_cfg}`. This is a **breaking config-format
  change** to existing `~/.sss/config.json` profiles.
- **The injectable-root test seam survives, renamed.** Tests that injected
  `SyncEngine(base_dir=…)` / `Sss(base_dir=…)` now inject `project_dir=…`. "Remove
  `base_dir`" renames the concept end-to-end; it does not delete the ability to point
  the root at a throwaway dir.
- **`push` is unchanged.** Its `source` is resolved as-typed (absolute, else
  cwd-relative) and never used `base_dir` ([ADR-0003](0003-push-adhoc-transfer-distinct-from-sync.md)).
- **vmctl** drops the `base_dir` passthrough on `vm.sync.run`/`push`; `--project-dir`
  stays its only sync path knob.

## Consequences

**Positive**

- One directory concept instead of two; `--project-dir` is the single knob, and the
  common case needs no config-level path tuning.
- Source paths read naturally as repo-relative, matching how developers think about
  the tree they're syncing.

**Negative / risks**

- **Breaking**: existing configs must drop the repo prefix from every profile key and
  delete the `base_dir` key. No automatic migration.
- Sources that live *outside* the repo can no longer be expressed by a profile (they
  never occurred in practice; `push` still handles one-off out-of-tree files).
- Default root changes from `%USERPROFILE%` to cwd — running sync from outside the
  repo without `--project-dir` now resolves against the wrong root instead of a
  stable home dir.

## Alternatives considered

- **Keep `base_dir` as an optional override defaulting to `project_dir`** — non-breaking
  escape hatch for out-of-repo sources. Rejected: those sources never occur, and a
  second seldom-used knob is exactly the confusion this ADR removes.
