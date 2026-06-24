"""Files primitive: remove individual files / delete directory trees.

``remove`` deletes files; ``delete`` removes directories recursively. Abstract
``FilesModule`` defines the verb set; ``WindowsFilesModule`` drives ``del`` /
``rmdir`` over the Connection.
"""

from abc import ABC, abstractmethod
from typing import List

from ..connection import Connection


class FilesModule(ABC):
    def __init__(self, connection: Connection):
        self._conn = connection

    @abstractmethod
    def remove(self, paths: List[str]) -> dict:
        ...

    @abstractmethod
    def delete(self, paths: List[str]) -> dict:
        ...


class WindowsFilesModule(FilesModule):
    def remove(self, paths: List[str]) -> dict:
        """Force-delete each file (``del /F /Q``)."""
        results = []
        for path in _as_list(paths):
            win = path.replace("/", "\\")
            result = self._conn.exec(f'del /F /Q "{win}"')
            results.append({"path": win, "ok": result.ok})
        return {"success": all(r["ok"] for r in results), "removed": results}

    def delete(self, paths: List[str]) -> dict:
        """Recursively delete each directory (``rmdir /S /Q``)."""
        results = []
        for path in _as_list(paths):
            win = path.replace("/", "\\")
            result = self._conn.exec(f'rmdir /S /Q "{win}"')
            results.append({"path": win, "ok": result.ok})
        return {"success": all(r["ok"] for r in results), "deleted": results}


def _as_list(paths) -> List[str]:
    if isinstance(paths, str):
        return [paths]
    return list(paths)
