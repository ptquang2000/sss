"""ScriptRunner: steps dispatch to the right primitive; unknown ops rejected."""

import pytest

from sss.exceptions import SssError
from sss.scripts import ScriptRunner


class _Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return {"ok": True}
        return method


class _FakeSession:
    def __init__(self):
        self.service = _Recorder()
        self.process = _Recorder()
        self.files = _Recorder()
        self.exec_calls = []

    def exec(self, cmd):
        self.exec_calls.append(cmd)
        return {"ok": True}


def test_dispatch_to_correct_primitive():
    session = _FakeSession()
    steps = [
        {"op": "stop_service", "args": {"name": "FooSvc"}},
        {"op": "stop_process", "args": {"name": "BarApp.exe"}},
        {"op": "remove_files", "args": {"paths": ["C:/x/libfoodrv.sys"]}},
    ]
    ScriptRunner(session).run(steps)

    assert ("stop", ("FooSvc",), {}) in session.service.calls or \
           ("stop", (), {"name": "FooSvc"}) in session.service.calls
    assert session.process.calls[0][0] == "stop"
    assert session.files.calls[0][0] == "remove"


def test_start_process_unpacks_args():
    session = _FakeSession()
    steps = [{"op": "start_process", "args": {"exe_path": "C:/app.exe", "args": ["showUI"]}}]
    ScriptRunner(session).run(steps)
    name, args, kwargs = session.process.calls[0]
    assert name == "start"
    assert "showUI" in args
    assert kwargs.get("exe_path") == "C:/app.exe"


def test_exec_op_dispatched():
    session = _FakeSession()
    ScriptRunner(session).run([{"op": "exec", "args": {"cmd": "hostname"}}])
    assert session.exec_calls == ["hostname"]


def test_unknown_op_rejected():
    session = _FakeSession()
    with pytest.raises(SssError, match="Unknown op"):
        ScriptRunner(session).run([{"op": "rm_rf_slash", "args": {}}])


def test_malformed_step_rejected():
    session = _FakeSession()
    with pytest.raises(SssError, match="malformed"):
        ScriptRunner(session).run([{"args": {}}])


def test_validate_does_not_dispatch():
    session = _FakeSession()
    ScriptRunner.validate([{"op": "stop_service", "args": {"name": "x"}}])
    assert session.service.calls == []


def test_empty_steps_ok():
    assert ScriptRunner(_FakeSession()).run([]) == []
    assert ScriptRunner(_FakeSession()).run(None) == []
