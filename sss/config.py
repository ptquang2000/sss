"""Central config at ``~/.sss/config.json`` (a ``~/.<tool>/config.json`` path
convention; no dependency implied -- config holds only ``base_dir`` + profiles,
never any host or credentials).

A profiles map is selected by the project's git-remote URL: run sss from inside
a repo and it picks the matching profile. Each profile defines the sync mapping
(``source_dirs`` -> dest, ``optional_dirs``, ``source_files``, ``exclude``) plus
the declarative ``pre_sync`` / ``post_sync`` step lists.
"""

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .exceptions import SssError

CONFIG_PATH = Path.home() / ".sss" / "config.json"

_DEFAULTS = {
    # Root that source paths are resolved against (legacy used %USERPROFILE%).
    "base_dir": None,
    "profiles": {},
}


@dataclass
class Profile:
    """A resolved sync profile: a mapping + lifecycle scripts.

    ``source_dirs`` / ``optional_dirs`` map a source path (relative to
    ``base_dir``) to one or more destination directories on the target.
    ``source_files`` maps an individual source file to a destination directory.
    """

    name: str
    source_dirs: Dict[str, object] = field(default_factory=dict)
    optional_dirs: Dict[str, object] = field(default_factory=dict)
    source_files: Dict[str, str] = field(default_factory=dict)
    exclude: List[str] = field(default_factory=list)
    pre_sync: List[dict] = field(default_factory=list)
    post_sync: List[dict] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict, extra_vars: dict = None) -> "Profile":
        variables = dict(data.get("variables", {}))
        if extra_vars:
            variables.update({k: v for k, v in extra_vars.items() if v is not None})
        return cls(
            name=name,
            source_dirs=data.get("source_dirs", {}),
            optional_dirs=data.get("optional_dirs", {}),
            source_files=data.get("source_files", {}),
            exclude=data.get("exclude", []),
            pre_sync=data.get("pre_sync", []),
            post_sync=data.get("post_sync", []),
            variables=variables,
        )


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not Path(path).exists():
        return dict(_DEFAULTS)
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in _DEFAULTS.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(config: dict, path: Path = CONFIG_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_git_remote_url(project_path: str) -> Optional[str]:
    """Return the project's ``remote.origin.url``, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        return None
    return None


def select_profile(config: dict, project_dir: str = None, extra_vars: dict = None) -> Profile:
    """Pick the profile matching the project's git remote.

    Falls back to the sole profile when there is exactly one; raises otherwise.
    """
    profiles = config.get("profiles", {})
    if not profiles:
        raise SssError(f"No profiles configured in {CONFIG_PATH}")

    project_path = project_dir or os.getcwd()
    remote_url = get_git_remote_url(project_path)
    if remote_url and remote_url in profiles:
        return Profile.from_dict(remote_url, profiles[remote_url], extra_vars)

    if len(profiles) == 1:
        name, data = next(iter(profiles.items()))
        return Profile.from_dict(name, data, extra_vars)

    raise SssError(
        f"Could not auto-detect a profile for {project_path} "
        f"(git remote: {remote_url or 'none'}). Configured profiles: {list(profiles)}"
    )


def apply_variables(obj, variables: Dict[str, str]):
    """Recursively substitute ``{name}`` placeholders in keys and string values."""
    if isinstance(obj, dict):
        return {
            apply_variables(k, variables): apply_variables(v, variables)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [apply_variables(item, variables) for item in obj]
    if isinstance(obj, str):
        result = obj
        for name, value in variables.items():
            result = result.replace("{" + name + "}", str(value))
        return result
    return obj
