# 3. `push` is an ad-hoc transfer verb, distinct from profile-driven `sync`

Date: 2026-06-23

## Status

Accepted

## Context

`sync` is profile-driven: it expands the resolved profile's
`source_dirs`/`source_files` mapping (sources relative to `base_dir`), honors the
profile's `exclude` globs and `{var}` substitution, and runs as the middle step of
the `sss sync` lifecycle (`pre_sync` → sync → `post_sync`). The profile itself is
auto-selected from the project's git remote.

A recurring need is the one-off case: "push *this* path to *that* place on the
target," with no project, no profile, and no lifecycle — e.g. shipping a single
freshly built artifact to a VM. Forcing that through `sync` would mean either
authoring a throwaway profile or overloading `sss sync` with positional args that
silently skip the hooks, making one command mean two incompatible things.

## Decision

Add a separate verb, `sss push <source> <dest>` (library: `s.sync.path(source,
dest)`), for ad-hoc transfers. It deliberately diverges from `sync` despite reusing
the same `SyncEngine` internals:

- **No profile, no `pre_sync`/`post_sync` hooks, no excludes, no `{var}`
  substitution.** A bare transfer of exactly what was pointed at.
- **`source` resolved as-typed** — absolute, else relative to **cwd**, *not*
  `base_dir`. This matches `cp`/`scp`/`rsync` ergonomics; the engine is invoked with
  `base_dir` set to cwd (or the source pre-normalized to absolute).
- **`dest` is always a remote directory.** Engine path-mapping is unchanged: a file
  source lands at `dest/<basename>`; a directory source has its **contents merged
  into `dest`** (rsync trailing-slash semantics — no `dest/<dirname>` nesting, no
  rename).
- **Upload-only**, single source → single dest, reusing the engine's mtime/size
  skip-unchanged and recursive remote mkdir.
- `push` does **not** require a resolved profile (unlike `sss sync`).

`push` is a CLI/library verb only — it is **not** a scriptable primitive and cannot
appear in `pre_sync`/`post_sync` step lists.

## Consequences

**Positive**

- One-off transfers need no config; the common "ship this artifact now" case is a
  single command.
- Reuses the proven sync engine (diff, mkdir, SFTP), so there is no second transfer
  implementation to maintain.
- Keeping it a separate verb leaves `sss sync`'s "full lifecycle" meaning intact.

**Negative / risks**

- Two transfer verbs with overlapping engines but different rules (base_dir vs cwd,
  excludes on vs off, hooks on vs off) — a future reader may expect `push` to behave
  like `sync`. Mitigated by the glossary entries in CONTEXT.md and this ADR.
- The directory-contents-merge behavior surprises users expecting `cp -r` nesting;
  must be called out in `push`'s `--help`.

## Alternatives considered

- **Overload `sss sync <source> <dest>`** (positional args bypass profile + hooks) —
  rejected: makes one command silently mean two things; the hook-skipping is
  invisible at the call site.
- **Require a throwaway profile for one-offs** — rejected: defeats the point of an
  on-demand transfer.
- **Resolve `source` against `base_dir` for consistency with `sync`** — rejected:
  surprising for a typed path argument; ergonomics beat engine-consistency here.
- **cp-style `dest` (nest dir as `dest/<dirname>`, support rename)** — rejected:
  needs a second resolution path and diverges from the engine's mapping.
- **Bidirectional / download** — out of scope: the engine is upload-only (no SFTP
  `get`, remote-side stat for the diff); adding it is a separate, larger feature.
