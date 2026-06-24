"""Transport abstraction. SSH is the only sss transport.

`Connection` is the OS-agnostic interface the primitives sit on: exec a
command, put a file, stat / mkdir / list remote paths. The single concrete
implementation (`SSHConnection`, Paramiko SFTP) backs both VM and remote-host
targets. The abstraction is what lets primitives stay portable later.
"""

import posixpath
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from .exceptions import SssError


@dataclass
class CommandResult:
    """Outcome of a remote command: exit code plus captured streams."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass
class RemoteStat:
    """Minimal remote-file metadata the sync diff needs."""

    st_size: int
    st_mtime: float


class Connection(ABC):
    @abstractmethod
    def exec(self, command: str) -> CommandResult:
        """Run a command on the target and return its result."""

    @abstractmethod
    def put(self, local_path: str, remote_path: str) -> None:
        """Upload a single local file to an absolute remote path."""

    @abstractmethod
    def stat(self, remote_path: str) -> Optional[RemoteStat]:
        """Return remote-file metadata, or None if the path does not exist."""

    @abstractmethod
    def mkdir_p(self, remote_dir: str) -> None:
        """Recursively create a remote directory (idempotent)."""

    @abstractmethod
    def listdir(self, remote_path: str) -> List[str]:
        """List the names of entries in a remote directory."""

    @abstractmethod
    def close(self) -> None:
        """Release the underlying transport."""

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class SSHConnection(Connection):
    """Paramiko-backed SSH/SFTP connection.

    Tries the supplied password first (kept for backward compatibility), then
    falls back to key/agent auth so publickey-only servers still work.
    """

    def __init__(self, host: str, username: str, password: str = None, port: int = 22):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self._client = None
        self._sftp = None

    def connect(self) -> "SSHConnection":
        import paramiko

        attempts = []
        if self.password:
            attempts.append({"password": self.password, "allow_agent": True, "look_for_keys": True})
        attempts.append({"password": None, "allow_agent": True, "look_for_keys": True})

        last_error = None
        for auth_kwargs in attempts:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    timeout=10,
                    auth_timeout=15,
                    banner_timeout=15,
                    **auth_kwargs,
                )
                self._client = client
                self._sftp = client.open_sftp()
                return self
            except Exception as e:  # paramiko auth/transport errors + OSError
                last_error = e
                client.close()

        raise SssError(f"SSH connection to {self.username}@{self.host} failed: {last_error}")

    def exec(self, command: str) -> CommandResult:
        if self._client is None:
            raise SssError("SSH connection is not open")
        _, stdout, stderr = self._client.exec_command(command)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return CommandResult(code, out, err)

    def put(self, local_path: str, remote_path: str) -> None:
        self._sftp.put(local_path, remote_path)

    def stat(self, remote_path: str) -> Optional[RemoteStat]:
        try:
            attr = self._sftp.stat(remote_path)
        except (FileNotFoundError, OSError):
            return None
        return RemoteStat(st_size=attr.st_size, st_mtime=attr.st_mtime)

    def mkdir_p(self, remote_dir: str) -> None:
        remote_dir = remote_dir.replace("\\", "/")
        parts = []
        cur = remote_dir
        while cur not in ("", "/"):
            parts.append(cur)
            cur = posixpath.dirname(cur)
        for d in reversed(parts):
            try:
                self._sftp.stat(d)
            except FileNotFoundError:
                self._sftp.mkdir(d)

    def listdir(self, remote_path: str) -> List[str]:
        return self._sftp.listdir(remote_path)

    def close(self) -> None:
        if self._sftp:
            self._sftp.close()
            self._sftp = None
        if self._client:
            self._client.close()
            self._client = None
