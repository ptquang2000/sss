# 2. Launch start_process via an interactive scheduled task, not Start-Process

Date: 2026-06-22

## Status

Accepted

## Context

`WindowsProcessModule.start` used `Start-Process` over SSH. Windows OpenSSH puts
every process spawned during a command into a job object tied to the SSH session;
when the launching `exec` returns and the channel closes, the "detached" child is
killed with it. A process launched by `start_process` therefore could never
outlive the call (proven live: a child PID launched in one `exec` was gone from a
separate `exec` 2s later).

This breaks the canonical real use case — `post_sync: start_process
FooCorpClientUI.exe`, relaunching the BarApp client **GUI** after a sync. The
requirement is not merely that the process survives the SSH session, but that the
GUI is **visible on the interactive logged-on desktop**. Two launch mechanisms
escape the SSH job object but land in the non-interactive service session
(session 0), where a GUI runs invisibly: WMI `Win32_Process.Create`, and a
`schtasks` task created the default way ("run whether user is logged on or not",
which uses a service logon). Neither satisfies the visibility requirement.

## Decision

`start_process` launches via a **one-shot interactive scheduled task**:

```
schtasks /create /tn <unique> /sc once /st 00:00 /it /ru <ssh-user> \
         /tr "\"<exe>\" <args>"
schtasks /run /tn <unique>
schtasks /delete /tn <unique> /f
```

- `/it` runs the task in the specified user's **interactive console session**, so
  the GUI appears on the desktop. It also uses the interactive token, so **no
  password (`/rp`) is needed on the command line**.
- `/ru <ssh-user>` reuses the connection's SSH username. We assume the VM's
  interactive console user equals the SSH/vmctl guest account and is
  auto-logged-in at the console (true for the test VMs and the BarApp dev VMs).
- The exe path is wrapped in escaped inner quotes inside `/tr`, with args
  appended directly. Task Scheduler launches the exe **directly** (no `cmd /c`
  wrapper), so the spawned `Win32_Process.CommandLine` equals the `/tr` content —
  this preserves `process.kill`'s token/CommandLine matching contract.
- The task is deleted immediately after `/run`; the launched process is already
  independent of the task by then.

## Consequences

**Positive**

- The launched process survives SSH-session close and appears on the interactive
  desktop — the actual BarApp relaunch requirement.
- `process.kill`'s name/CommandLine token matching is unchanged: direct `/tr`
  launch keeps the exe+args verbatim in the child's command line.
- `start` semantics stay fire-and-forget: success means the task created and
  triggered, not that the child stayed alive (same contract as before).

**Negative / risks**

- Depends on an interactive user being logged on at the VM console at run time
  (the auto-login assumption). If nobody is logged in, `/it` has no session to
  target and the GUI won't appear. Not currently detected; revisit with active-
  session discovery (`quser`/`query session`) if a non-auto-login VM appears.
- `WindowsProcessModule` now needs the SSH username (`self._conn.username`),
  which exists on `SSHConnection` but is not part of the abstract `Connection`
  interface — a small abstraction leak to formalize when a second transport/OS
  lands.
- Nested SSH → PowerShell → schtasks quoting is fragile; the exact child
  `CommandLine` must be verified live against `process.kill`.

## Alternatives considered

- **WMI `Win32_Process.Create`** — rejected: escapes the job object and returns a
  PID cleanly, but launches in session 0, so the GUI is invisible. Fails the
  visibility requirement.
- **Plain `schtasks` (run-whether-logged-on-or-not)** — rejected: uses a service
  logon → session 0 → invisible GUI, and requires the password on the command
  line.
- **Keep `Start-Process`** — rejected: child dies with the SSH session.

## Test coverage

The original `test_process_spawn_and_kill` spawned and killed within a single
session-scoped connection, so it never exercised the broken property. A new live
test must start the process, then open a **fresh independent SSH session**, assert
the process is still alive, and only then kill it — the assertion that actually
catches this regression.
