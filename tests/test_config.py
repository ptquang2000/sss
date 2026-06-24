"""Config: load/save, git-remote profile selection, variable substitution."""

import json

import pytest

from sss import config
from sss.exceptions import SssError


def _write_config(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return path


def test_load_missing_returns_defaults(tmp_path):
    cfg = config.load_config(tmp_path / "nope.json")
    assert cfg["profiles"] == {} and cfg["base_dir"] is None


def test_load_fills_defaults(tmp_path):
    path = _write_config(tmp_path, {"profiles": {"r": {}}})
    cfg = config.load_config(path)
    assert cfg["base_dir"] is None and "r" in cfg["profiles"]


def test_select_profile_single_fallback(tmp_path):
    cfg = {"profiles": {"git@x:repo.git": {"source_dirs": {"a": "/b"}}}}
    profile = config.select_profile(cfg, project_dir=str(tmp_path))
    assert profile.name == "git@x:repo.git"
    assert profile.source_dirs == {"a": "/b"}


def test_select_profile_by_git_remote(tmp_path, monkeypatch):
    cfg = {"profiles": {"git@x:one.git": {"exclude": ["*.pdb"]}, "git@x:two.git": {}}}
    monkeypatch.setattr(config, "get_git_remote_url", lambda p: "git@x:one.git")
    profile = config.select_profile(cfg, project_dir=str(tmp_path))
    assert profile.name == "git@x:one.git"
    assert profile.exclude == ["*.pdb"]


def test_select_profile_ambiguous_raises(tmp_path, monkeypatch):
    cfg = {"profiles": {"a": {}, "b": {}}}
    monkeypatch.setattr(config, "get_git_remote_url", lambda p: "unmatched")
    with pytest.raises(SssError, match="Could not auto-detect"):
        config.select_profile(cfg, project_dir=str(tmp_path))


def test_select_profile_no_profiles_raises():
    with pytest.raises(SssError, match="No profiles"):
        config.select_profile({"profiles": {}})


def test_extra_vars_override():
    cfg = {"profiles": {"r": {"variables": {"build_cfg": "Release"}}}}
    profile = config.select_profile(cfg, extra_vars={"build_cfg": "Debug", "arch": None})
    assert profile.variables["build_cfg"] == "Debug"
    assert "arch" not in profile.variables  # None-valued extras are dropped


def test_apply_variables_recurses():
    out = config.apply_variables(
        {"{k}": ["/x/{v}", "plain"]}, {"k": "key", "v": "val"}
    )
    assert out == {"key": ["/x/val", "plain"]}


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "sub" / "config.json"
    config.save_config({"profiles": {"r": {"exclude": ["*.tmp"]}}}, path)
    cfg = config.load_config(path)
    assert cfg["profiles"]["r"]["exclude"] == ["*.tmp"]
