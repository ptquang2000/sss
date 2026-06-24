"""Target resolution: turn "auto-detect VM | --host" into a Connection.

VM targets delegate to vmctl for identity, IP, and guest credentials (reused as
the SSH login -- single source of truth). ``--host`` builds a direct SSH
connection and never imports vmctl, so pure remote-host usage works without it
(per ADR-0001).
"""

from abc import ABC, abstractmethod
from typing import Optional

from .connection import SSHConnection
from .exceptions import SssError


class VmProvider(ABC):
    """Resolves the running VM into SSH connection parameters."""

    @abstractmethod
    def running_target(self) -> Optional[dict]:
        """Return ``{name, host, user, password}`` for the running VM, or None."""


class VmctlProvider(VmProvider):
    """Adapter over vmctl. The single place that reaches into vmctl internals."""

    def __init__(self):
        try:
            import vmctl
        except ImportError as e:
            raise SssError(
                "vmctl is required for VM targets but is not installed. "
                "Install it (pip install -e ../vmctl) or use --host for a remote machine."
            ) from e
        self._vmctl = vmctl.VMCtl()

    def running_target(self) -> Optional[dict]:
        info = self._vmctl.list_vms()
        running = info.get("running", [])
        if not running:
            return None

        vmx_path = running[0]
        name = self._name_for(vmx_path)
        ip = self._guest_ip(vmx_path)
        creds = self._vmctl._config.get("credentials", {}).get((name or "").lower(), {})
        if not ip:
            raise SssError(f"VM '{name or vmx_path}' is running but has no reachable IP")
        return {
            "name": name,
            "host": ip,
            "user": creds.get("user"),
            "password": creds.get("password"),
        }

    def _name_for(self, vmx_path: str) -> Optional[str]:
        norm = vmx_path.replace("\\", "/").lower()
        for name, path in self._vmctl._registry.list_all().items():
            if path.replace("\\", "/").lower() == norm:
                return name
        return None

    def _guest_ip(self, vmx_path: str) -> Optional[str]:
        ip = self._vmctl._runner.run_vmrun("getGuestIPAddress", vmx_path, "-wait").strip()
        return ip or None


class Target:
    @staticmethod
    def resolve(
        host: str = None,
        user: str = None,
        password: str = None,
        port: int = 22,
        vm_provider: VmProvider = None,
        connect: bool = True,
    ) -> tuple:
        """Resolve a target into a ``(SSHConnection, meta)`` pair.

        ``host`` given -> direct SSH to a remote machine. Otherwise auto-detect
        the running VM via ``vm_provider`` (defaults to vmctl); if none is
        running, exit clearly rather than prompting.
        """
        if host:
            conn = SSHConnection(host, user, password, port=port)
            meta = {"kind": "host", "host": host, "user": user}
        else:
            provider = vm_provider or VmctlProvider()
            target = provider.running_target()
            if not target:
                raise SssError("No VM is running. Start one, or target a remote machine with --host.")
            conn = SSHConnection(target["host"], target["user"], target["password"], port=port)
            meta = {"kind": "vm", "name": target.get("name"), "host": target["host"], "user": target["user"]}

        if connect:
            conn.connect()
        return conn, meta
