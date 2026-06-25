"""Process primitive: kill/start a process on the target.

Abstract ``ProcessModule`` defines the verb set; ``WindowsProcessModule`` is
the only implementation today (PowerShell discovery + ``taskkill`` to kill, a
one-shot interactive scheduled task to launch -- see docs/adr/0002).
"""

import json
import uuid
from abc import ABC, abstractmethod

from ..connection import Connection

# Never killed by name matching (would break the SSH session or host tooling).
_PROTECTED = {
    "powershell.exe", "cmd.exe", "conhost.exe", "wsmprovhost.exe",
    "winrm.exe", "vmtoolsd.exe", "vmware-authd.exe",
    "vmware-usbarbitrator64.exe",
}


class ProcessModule(ABC):
    def __init__(self, connection: Connection):
        self._conn = connection

    @abstractmethod
    def kill(self, name: str) -> dict:
        ...

    @abstractmethod
    def start(self, exe_path: str, *args: str) -> dict:
        ...

    # Alias so callers / scripts can say stop_process.
    def stop(self, name: str) -> dict:
        return self.kill(name)


class WindowsProcessModule(ProcessModule):
    def kill(self, name: str) -> dict:
        """Find processes whose name/command line matches ``name`` and kill each."""
        ps = (
            'powershell "Get-CimInstance Win32_Process | '
            f"Where-Object {{ $_.Name -like '*{name}*' -or $_.CommandLine -like '*{name}*' }} | "
            'Select-Object Name, ProcessId | ConvertTo-Json"'
        )
        result = self._conn.exec(ps)
        out = result.stdout.strip()
        if not out:
            return {"success": True, "match": name, "killed": []}

        try:
            info = json.loads(out)
        except json.JSONDecodeError:
            return {"success": True, "match": name, "killed": []}
        if isinstance(info, dict):
            info = [info]

        killed = []
        for proc in info:
            pname = proc.get("Name")
            pid = proc.get("ProcessId")
            if pname and pname.lower() in _PROTECTED:
                continue
            if pname and pid and str(pid).isdigit():
                self._conn.exec(f"taskkill /PID {pid} /F /T")
                killed.append({"name": pname, "pid": pid})
        return {"success": True, "match": name, "killed": killed}

    def start(self, exe_path: str, *args: str) -> dict:
        """Launch an executable on the target's interactive desktop.

        Uses a one-shot interactive scheduled task instead of ``Start-Process``
        (see docs/adr/0002): a process spawned over SSH dies with the session's
        job object, and a service-session launch is invisible. ``schtasks /it``
        runs on the logged-on console session with the interactive token (no
        password on the command line), and ``/ru`` reuses the SSH username.

        Task Scheduler launches the exe directly (no ``cmd /c`` wrapper), so the
        child's ``Win32_Process.CommandLine`` equals the ``/tr`` content -- this
        keeps ``kill``'s name/CommandLine token matching working. The task is
        deleted right after ``/run``; the child is independent of it by then.

        Fire-and-forget: ``success`` means the launch was triggered, not that
        the child stayed alive.
        """
        win_path = exe_path.replace("/", "\\")
        user = self._conn.username
        task = "sss_start_" + uuid.uuid4().hex

        # /tr value: "\"<exe>\" <args>" -- inner-quote the exe (escaped for the
        # SSH->shell layer), append args verbatim. The child sees this as its
        # command line, which is what process.kill greps.
        action = f'\\"{win_path}\\"'
        if args:
            action += " " + " ".join(args)
        tr = f'"{action}"'

        self._conn.exec(
            f"schtasks /create /tn {task} /sc once /st 00:00 /it "
            f"/ru {user} /tr {tr} /f"
        )
        run = self._conn.exec(f"schtasks /run /tn {task}")
        self._conn.exec(f"schtasks /delete /tn {task} /f")
        return {
            "success": run.ok,
            "exe": win_path,
            "args": list(args),
            "task_name": task,
        }
