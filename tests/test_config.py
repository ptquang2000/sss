"""Config: load/save, git-remote profile selection, variable substitution.

Also covers the caller-supplied config path (ADR-0006): ``connect(config_path=…)``
loads profiles from the given file and the empty-profiles error names it.
"""

import json

import pytest

import sss
from sss import config
from sss.exceptions import SssError

from .fakes import FakeConnection


def _write_config(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return path


def test_load_missing_returns_defaults(tmp_path):
    cfg = config.load_config(tmp_path / "nope.json")
    assert cfg["profiles"] == {}


def test_load_fills_defaults(tmp_path):
    path = _write_config(tmp_path, {"profiles": {"r": {}}})
    cfg = config.load_config(path)
    assert "r" in cfg["profiles"]


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


# --------------------------------------------------------------------------- #
# caller-supplied config path (ADR-0006)                                      #
# --------------------------------------------------------------------------- #


def test_select_profile_empty_names_supplied_path(tmp_path):
    # The empty-profiles error must name the file actually consulted, not the
    # hardcoded sss default -- that is how vmctl's "~/.vmctl/sync.json" surfaces.
    supplied = tmp_path / "sync.json"
    with pytest.raises(SssError, match=str(supplied).replace("\\", "\\\\")):
        config.select_profile({"profiles": {}}, config_path=supplied)


def test_select_profile_empty_defaults_to_sss_path():
    with pytest.raises(SssError, match="No profiles configured") as exc:
        config.select_profile({"profiles": {}})
    assert str(config.CONFIG_PATH) in str(exc.value)


@pytest.fixture
def no_network(monkeypatch):
    """Stub Target.resolve so connect() opens no real SSH connection."""
    monkeypatch.setattr(
        sss.Target, "resolve",
        staticmethod(lambda **kw: (FakeConnection(), {})),
    )


def test_connect_loads_profiles_from_supplied_path(tmp_path, monkeypatch, no_network):
    path = _write_config(tmp_path, {"profiles": {"only": {"exclude": ["*.pdb"]}}})
    session = sss.connect(host="10.0.0.5", config_path=path)
    assert session.profile is not None
    assert session.profile.name == "only"
    assert session.profile.exclude == ["*.pdb"]


def test_connect_no_path_uses_sss_default(tmp_path, monkeypatch, no_network):
    # No config_path -> the sss default (~/.sss/config.json) is consulted; point
    # that default at a tmp file to prove the fallback path is what gets loaded.
    default = _write_config(tmp_path, {"profiles": {"dflt": {"exclude": ["*.o"]}}})
    monkeypatch.setattr(sss, "CONFIG_PATH", default)
    session = sss.connect(host="10.0.0.5")
    assert session.profile is not None
    assert session.profile.name == "dflt"
