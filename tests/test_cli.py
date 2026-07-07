"""CLI wiring: the shared ``--config`` option reaches ``connect(config_path=…)``.

Mock-light: patch ``connect`` in ``sss.cli`` with a stub returning a
context-manager session, then assert the kwarg it received. The full connect /
profile behaviour is covered in ``test_config.py``.
"""

from unittest.mock import MagicMock

from click.testing import CliRunner

from sss import cli


def _fake_session():
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.profile = object()  # so need_profile=True passes for `sync`
    session.exec.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
    return session


def test_config_option_reaches_connect(monkeypatch):
    connect = MagicMock(return_value=_fake_session())
    monkeypatch.setattr(cli, "connect", connect)
    result = CliRunner().invoke(
        cli.cli,
        ["exec", "--host", "10.0.0.5", "--config", "/tmp/custom.json", "hostname"],
    )
    assert result.exit_code == 0, result.output
    _, kwargs = connect.call_args
    assert kwargs["config_path"] == "/tmp/custom.json"


def test_config_option_defaults_to_none(monkeypatch):
    connect = MagicMock(return_value=_fake_session())
    monkeypatch.setattr(cli, "connect", connect)
    result = CliRunner().invoke(cli.cli, ["exec", "--host", "10.0.0.5", "hostname"])
    assert result.exit_code == 0, result.output
    _, kwargs = connect.call_args
    assert kwargs["config_path"] is None
