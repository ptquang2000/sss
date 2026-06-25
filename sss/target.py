"""Target resolution: turn an explicit ``--host`` into an SSH connection.

sss is target-agnostic -- it knows only how to reach a machine over SSH via an
explicitly supplied host plus optional credentials. There is no VM knowledge and
no auto-detection: a missing host fails fast (per ADR-0004). vmctl (or any other
caller) resolves its own target first and feeds the resulting host/credentials in.
"""

from .connection import SSHConnection
from .exceptions import SssError


class Target:
    @staticmethod
    def resolve(
        host: str = None,
        user: str = None,
        password: str = None,
        port: int = 22,
        connect: bool = True,
    ) -> tuple:
        """Resolve an explicit target into a ``(SSHConnection, meta)`` pair.

        ``host`` is required -- it is the machine to reach over SSH. ``user`` /
        ``password`` are optional (publickey/agent auth still works without
        them). Returns ``meta = {host, user}``; raises ``SssError`` if ``host``
        is missing.
        """
        if not host:
            raise SssError("A target host is required (pass --host / host=...).")

        conn = SSHConnection(host, user, password, port=port)
        meta = {"host": host, "user": user}

        if connect:
            conn.connect()
        return conn, meta
