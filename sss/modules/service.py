"""Service primitive: start/stop a service on the target.

Abstract ``ServiceModule`` defines the verb set; ``WindowsServiceModule`` is
the only implementation today (driving ``sc.exe`` / ``taskkill`` over the
Connection). A Linux impl can be added later without changing the interface.
"""

import os
import time
from abc import ABC, abstractmethod

from ..connection import Connection

# How long ``stop`` waits for a polite ``sc stop`` to take effect before it
# escalates to a force-kill. ``timeout=0`` collapses this to a single,
# non-sleeping check (keeps unit tests instant).
_STOP_TIMEOUT_DEFAULT = 5
_POLL_INTERVAL = 0.5


class ServiceModule(ABC):
    def __init__(self, connection: Connection):
        self._conn = connection

    @abstractmethod
    def stop(self, name: str, timeout: float = None) -> dict:
        ...

    @abstractmethod
    def start(self, name: str) -> dict:
        ...


class WindowsServiceModule(ServiceModule):
    def stop(self, name: str, timeout: float = None) -> dict:
        """Stop a service gracefully, force-killing its image if it won't budge.

        1. ``sc queryex`` -> early-return ``not_found`` / ``not_running``.
        2. ``sc stop``, then poll ``sc queryex`` up to ``timeout`` seconds
           (default 5) for the service to leave RUNNING.
        3. If still RUNNING, resolve the binary image from ``sc qc`` and
           ``taskkill /F /T /IM <image>``.
        4. Fall back to kill-by-PID if the image can't be resolved.

        ``timeout=0`` does a single non-sleeping check.
        """
        if timeout is None:
            timeout = _STOP_TIMEOUT_DEFAULT

        query = self._conn.exec(f'sc queryex "{name}"')
        out = query.stdout
        if "does not exist" in out.lower() or "1060" in out:
            return {"success": False, "reason": "not_found", "service": name}
        if "RUNNING" not in out.upper():
            return {"success": True, "service": name, "state": "not_running"}

        # Ask the SCM to stop it, then wait for it to actually leave RUNNING.
        self._conn.exec(f'sc stop "{name}"')
        last = self._poll_until_stopped(name, timeout)
        if "RUNNING" not in last.upper():
            return {"success": True, "service": name, "method": "sc_stop"}

        # Stubborn: the service ignored the polite stop. Force-kill its binary
        # image (covers child processes the SCM never tracked), else PID.
        image = self._binary_image(name)
        if image:
            self._conn.exec(f"taskkill /F /T /IM {image}")
            return {"success": True, "service": name, "image": image, "method": "taskkill_image"}

        pid = _extract_pid(last)
        if pid:
            self._conn.exec(f"taskkill /PID {pid} /T /F")
            return {"success": True, "service": name, "pid": pid, "method": "taskkill_pid"}

        return {"success": False, "service": name, "reason": "still_running"}

    def start(self, name: str) -> dict:
        """Ensure the service runs as LocalSystem, then start it."""
        cfg = self._conn.exec(f'sc qc "{name}"')
        if "SERVICE_START_NAME" in cfg.stdout and "LocalSystem" not in cfg.stdout:
            self._conn.exec(f'sc config "{name}" obj= LocalSystem')
        result = self._conn.exec(f'sc start "{name}"')
        return {"success": result.ok, "service": name, "output": result.stdout.strip()}

    # -- helpers -----------------------------------------------------------

    def _poll_until_stopped(self, name: str, timeout: float) -> str:
        """Poll ``sc queryex`` until the service leaves RUNNING or time runs out.

        Returns the last ``sc queryex`` stdout seen. ``timeout=0`` checks once
        without sleeping.
        """
        deadline = time.monotonic() + timeout
        while True:
            out = self._conn.exec(f'sc queryex "{name}"').stdout
            if "RUNNING" not in out.upper() or time.monotonic() >= deadline:
                return out
            time.sleep(min(_POLL_INTERVAL, timeout))

    def _binary_image(self, name: str):
        """Resolve the service binary's basename from ``sc qc``'s BINARY_PATH_NAME."""
        out = self._conn.exec(f'sc qc "{name}"').stdout
        for line in out.splitlines():
            if "BINARY_PATH_NAME" in line.upper():
                value = line.split(":", 1)[1] if ":" in line else line
                return _first_exe(value)
        return None


def _first_exe(text: str):
    """Basename of the first ``*.exe`` whitespace token in ``text``, or None."""
    for token in text.replace('"', " ").split():
        if token.lower().endswith(".exe"):
            return os.path.basename(token.replace("\\", "/"))
    return None


def _extract_pid(sc_output: str):
    for line in sc_output.splitlines():
        if "PID" in line:
            parts = line.split(":")
            if len(parts) == 2:
                try:
                    return int(parts[1].strip())
                except ValueError:
                    pass
    return None
