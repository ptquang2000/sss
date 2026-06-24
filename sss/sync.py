"""SyncEngine: the deep, valuable core ported from legacy ``sync.py``.

Behind a tiny ``run(profile, connection)`` interface it encapsulates:
source -> dest mapping expansion, ``{var}`` substitution, exclude-glob
filtering, the mtime/size skip-unchanged diff, recursive remote mkdir, and
individual-file sync. Pure enough to test against a temp filesystem + a mock
Connection.
"""

import fnmatch
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from .config import Profile, apply_variables
from .connection import Connection


@dataclass
class SyncResult:
    uploaded: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "uploaded": self.uploaded,
            "skipped": self.skipped,
            "missing": self.missing,
            "uploaded_count": len(self.uploaded),
            "skipped_count": len(self.skipped),
        }


class SyncEngine:
    def __init__(self, base_dir: str = None, log: Callable[[str], None] = None):
        # Source paths are resolved against base_dir (legacy used %USERPROFILE%).
        self.base_dir = base_dir or os.environ.get("USERPROFILE") or os.path.expanduser("~")
        self._log = log or (lambda msg: None)

    # -- helpers -----------------------------------------------------------

    def _is_excluded(self, path: str, exclude: List[str]) -> bool:
        lower = os.path.normpath(path).lower()
        for pattern in exclude:
            pat = pattern.lower()
            if fnmatch.fnmatch(lower, pat) or pat in lower:
                return True
        return False

    def _should_upload(self, conn: Connection, local_path: str, remote_path: str) -> bool:
        """Upload when the remote file is missing, a different size, or older."""
        local_size = os.path.getsize(local_path)
        local_mtime = int(os.path.getmtime(local_path))
        attr = conn.stat(remote_path)
        if attr is None:
            return True
        if local_size != attr.st_size or local_mtime > attr.st_mtime:
            return True
        return False

    def _norm_dests(self, dests) -> List[str]:
        return dests if isinstance(dests, list) else [dests]

    # -- public ------------------------------------------------------------

    def run(self, profile: Profile, connection: Connection, sync_optional: bool = False) -> SyncResult:
        """Expand the profile's mapping and sync every source to the target."""
        variables = profile.variables
        exclude = apply_variables(profile.exclude, variables)

        dirs_to_sync = dict(apply_variables(profile.source_dirs, variables))
        optional = apply_variables(profile.optional_dirs, variables)
        if sync_optional:
            for src, dests in optional.items():
                dirs_to_sync.setdefault(src, dests)

        # Roots that are themselves sync targets must not be descended into as
        # part of another root; optional roots are skipped unless requested.
        abs_roots = {self._abs(src) for src in dirs_to_sync}
        abs_optional = {self._abs(src) for src in optional}

        result = SyncResult()
        for src, dests in dirs_to_sync.items():
            self._sync_one(connection, src, self._norm_dests(dests), exclude,
                           abs_roots, abs_optional, sync_optional, result)

        source_files = apply_variables(profile.source_files, variables)
        for src_file, dest_dir in source_files.items():
            self._sync_file(connection, src_file, dest_dir, exclude, result)

        return result

    def sync_path(self, connection: Connection, source: str, dest: str) -> SyncResult:
        """Ad-hoc single ``source`` -> ``dest`` transfer (no profile/excludes/vars).

        ``source`` is resolved **as-typed** -- absolute, else relative to the
        current directory (*not* ``base_dir``); it is normalized to absolute
        here so the configured ``base_dir`` is irrelevant. ``dest`` is always a
        remote directory: a file source lands at ``dest/<basename>``; a
        directory source has its **contents merged into ``dest``** (no
        ``dest/<dirname>`` nesting). Reuses the same skip-unchanged + recursive
        remote-mkdir core as ``run()``.
        """
        abs_src = os.path.abspath(source)
        result = SyncResult()
        self._sync_one(connection, abs_src, [dest], exclude=[],
                       abs_roots=set(), abs_optional=set(),
                       sync_optional=False, result=result)
        return result

    def _abs(self, rel: str) -> str:
        return os.path.normpath(os.path.join(self.base_dir, rel))

    def _sync_one(self, conn, src, dest_dirs, exclude, abs_roots, abs_optional,
                  sync_optional, result: SyncResult) -> None:
        abs_src = self._abs(src)
        if self._is_excluded(abs_src, exclude):
            self._log(f"skip (excluded): {abs_src}")
            return

        if os.path.isdir(abs_src):
            self._log(f"dir {abs_src} -> {dest_dirs}")
            for root, dirs, files in os.walk(abs_src):
                for d in list(dirs):
                    abs_d = os.path.normpath(os.path.join(root, d))
                    if self._is_excluded(abs_d, exclude):
                        dirs.remove(d)
                    elif abs_d in abs_roots and abs_d != abs_src:
                        dirs.remove(d)
                    elif not sync_optional and abs_d in abs_optional:
                        dirs.remove(d)
                for fname in files:
                    local_path = os.path.join(root, fname)
                    if self._is_excluded(local_path, exclude):
                        continue
                    rel_path = os.path.relpath(local_path, abs_src)
                    for dest_dir in dest_dirs:
                        remote_file = os.path.join(dest_dir, rel_path).replace("\\", "/")
                        self._transfer(conn, local_path, remote_file, result)
        elif os.path.isfile(abs_src):
            for dest_dir in dest_dirs:
                remote_file = os.path.join(dest_dir, os.path.basename(abs_src)).replace("\\", "/")
                self._transfer(conn, abs_src, remote_file, result)
        else:
            self._log(f"missing source: {abs_src}")
            result.missing.append(abs_src)

    def _sync_file(self, conn, src_file, dest_dir, exclude, result: SyncResult) -> None:
        abs_src = self._abs(src_file)
        if self._is_excluded(abs_src, exclude):
            return
        if not os.path.isfile(abs_src):
            result.missing.append(abs_src)
            return
        remote_file = os.path.join(dest_dir, os.path.basename(abs_src)).replace("\\", "/")
        self._transfer(conn, abs_src, remote_file, result)

    def _transfer(self, conn: Connection, local_path, remote_file, result: SyncResult) -> None:
        remote_dir = os.path.dirname(remote_file)
        conn.mkdir_p(remote_dir)
        if self._should_upload(conn, local_path, remote_file):
            conn.put(local_path, remote_file)
            self._log(f"uploaded: {local_path} -> {remote_file}")
            result.uploaded.append(remote_file)
        else:
            result.skipped.append(remote_file)
