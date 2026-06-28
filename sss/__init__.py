"""sss -- SSH file-sync + remote primitives.

Two entry points:

* CLI -- ``sss sync``, ``sss exec``, ``sss service stop`` ... (see ``cli.py``).
* Library -- subsystem accessors on a connected ``Sss`` session::

      s = connect(host="10.0.0.5", user="test", password="test", profile=profile)
      # host is required; user/password are optional (publickey/agent works too)
      s.service.stop("FooSvc")
      s.sync.run()
      s.exec("hostname")

An MCP server can import and call these directly.
"""

from typing import Callable, Optional

from .config import Profile, load_config, select_profile
from .connection import Connection
from .exceptions import SssError
from .modules.files import WindowsFilesModule
from .modules.process import WindowsProcessModule
from .modules.service import WindowsServiceModule
from .scripts import ScriptRunner
from .sync import SyncEngine
from .target import Target

__all__ = ["Sss", "connect", "Profile", "SssError"]


class _SyncSubsystem:
    """Exposes ``s.sync.run()`` while owning the engine + bound profile."""

    def __init__(self, connection: Connection, profile: Optional[Profile],
                 project_dir: str = None, log: Callable[[str], None] = None):
        self._conn = connection
        self._profile = profile
        self._engine = SyncEngine(project_dir=project_dir, log=log)

    def run(self, profile: Profile = None, sync_optional: bool = False) -> dict:
        profile = profile or self._profile
        if profile is None:
            raise SssError("No sync profile is configured for this session")
        return self._engine.run(profile, self._conn, sync_optional=sync_optional).as_dict()

    def path(self, source: str, dest: str) -> dict:
        """Ad-hoc transfer of ``source`` to remote directory ``dest``.

        Profile-less and hook-less (see ``push``): ``source`` is resolved
        as-typed (cwd-relative or absolute, not ``project_dir``), ``dest`` is a
        remote directory. Reuses the engine's skip-unchanged + remote-mkdir.
        """
        return self._engine.sync_path(self._conn, source, dest).as_dict()


class Sss:
    """A connected session: subsystem accessors over one target Connection."""

    def __init__(self, connection: Connection, profile: Profile = None,
                 project_dir: str = None, meta: dict = None,
                 log: Callable[[str], None] = None):
        self._conn = connection
        self.profile = profile
        self.meta = meta or {}
        self.service = WindowsServiceModule(connection)
        self.process = WindowsProcessModule(connection)
        self.files = WindowsFilesModule(connection)
        self.sync = _SyncSubsystem(connection, profile, project_dir=project_dir, log=log)
        self.scripts = ScriptRunner(self)

    def exec(self, cmd: str) -> dict:
        """Run an ad-hoc command on the target."""
        result = self._conn.exec(cmd)
        return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}

    def run_lifecycle(self, sync_optional: bool = False) -> dict:
        """Full profile lifecycle: pre_sync -> sync -> post_sync."""
        if self.profile is None:
            raise SssError("No sync profile is configured for this session")
        pre = self.scripts.run(self.profile.pre_sync)
        synced = self.sync.run(sync_optional=sync_optional)
        post = self.scripts.run(self.profile.post_sync)
        return {"pre_sync": pre, "sync": synced, "post_sync": post}

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Sss":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def connect(
    host: str = None,
    user: str = None,
    password: str = None,
    port: int = 22,
    profile: Profile = None,
    project_dir: str = None,
    extra_vars: dict = None,
    log: Callable[[str], None] = None,
) -> Sss:
    """Resolve a target, open the connection, and return a ready ``Sss`` session.

    ``host`` is required -- the machine to reach over SSH; a missing host fails
    fast. ``user`` / ``password`` are optional (publickey/agent auth works
    without them). The profile is taken as given, else auto-selected from the
    project's git remote for sync/lifecycle.

    ``project_dir`` does double duty (ADR-0005): it selects the profile by git
    remote *and* is the root that the profile's relative source paths resolve
    against. It defaults to cwd in both roles.
    """
    if profile is None:
        config = load_config()
        try:
            profile = select_profile(config, project_dir=project_dir, extra_vars=extra_vars)
        except SssError:
            profile = None  # exec/service/etc. don't need a profile

    connection, meta = Target.resolve(
        host=host, user=user, password=password, port=port
    )
    return Sss(connection, profile=profile, project_dir=project_dir, meta=meta, log=log)
