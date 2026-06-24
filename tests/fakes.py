"""In-memory fakes so unit tests need no network or live host."""

from sss.connection import CommandResult, Connection, RemoteStat


class FakeConnection(Connection):
    """Records exec/put/mkdir calls; serves stat from an in-memory map.

    ``exec_results`` maps a command substring to a ``CommandResult``; the first
    match wins, otherwise a successful empty result is returned. A value may
    also be a *list* of ``CommandResult`` to model a command whose output
    changes across calls (e.g. a service that is RUNNING, then STOPPED): each
    call consumes the next entry, and the last entry sticks.
    """

    def __init__(self, exec_results=None, remote=None, username="testuser"):
        self.username = username  # mirrors SSHConnection.username (used by process.start)
        self.exec_results = exec_results or {}
        self.remote = {k.replace("\\", "/"): v for k, v in (remote or {}).items()}
        self.exec_calls = []
        self.uploaded = []
        self.mkdirs = []
        self.closed = False

    def exec(self, command: str) -> CommandResult:
        self.exec_calls.append(command)
        for key, result in self.exec_results.items():
            if key in command:
                if isinstance(result, list):
                    return result.pop(0) if len(result) > 1 else result[0]
                return result
        return CommandResult(0, "", "")

    def put(self, local_path: str, remote_path: str) -> None:
        self.uploaded.append((local_path, remote_path.replace("\\", "/")))

    def stat(self, remote_path: str):
        return self.remote.get(remote_path.replace("\\", "/"))

    def mkdir_p(self, remote_dir: str) -> None:
        self.mkdirs.append(remote_dir.replace("\\", "/"))

    def listdir(self, remote_path: str):
        return []

    def close(self) -> None:
        self.closed = True


__all__ = ["FakeConnection", "CommandResult", "RemoteStat"]
