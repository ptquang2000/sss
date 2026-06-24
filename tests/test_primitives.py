"""Primitive subsystems: assert command construction against a FakeConnection."""

from sss.modules.files import WindowsFilesModule
from sss.modules.process import WindowsProcessModule
from sss.modules.service import WindowsServiceModule

from .fakes import CommandResult, FakeConnection

RUNNING_SC = """
SERVICE_NAME: FooSvc
        STATE              : 4  RUNNING
        PID                : 4321
"""

STOPPED_SC = "SERVICE_NAME: FooSvc\n        STATE              : 1  STOPPED\n"

# sc qc output: the binary image lives in BINARY_PATH_NAME (note the drive-letter
# colon, so the parser must split on the *first* colon only).
QC_SC = (
    "[SC] QueryServiceConfig SUCCESS\n"
    "SERVICE_NAME: FooSvc\n"
    "        BINARY_PATH_NAME   : C:\\Program Files\\FooCorp\\BarApp\\BarApp.exe -service\n"
)


def test_service_stop_graceful_when_it_leaves_running():
    # RUNNING on the initial query, STOPPED once the polite `sc stop` lands.
    conn = FakeConnection(
        exec_results={"sc queryex": [CommandResult(0, RUNNING_SC, ""), CommandResult(0, STOPPED_SC, "")]}
    )
    result = WindowsServiceModule(conn).stop("FooSvc", timeout=0)
    assert result["method"] == "sc_stop"
    assert any('sc stop "FooSvc"' in c for c in conn.exec_calls)
    assert not any("taskkill" in c for c in conn.exec_calls)


def test_service_stop_force_kills_image_when_stubborn():
    # Stays RUNNING despite `sc stop` -> escalate to taskkill by binary image.
    conn = FakeConnection(
        exec_results={
            "sc queryex": CommandResult(0, RUNNING_SC, ""),
            "sc qc": CommandResult(0, QC_SC, ""),
        }
    )
    result = WindowsServiceModule(conn).stop("FooSvc", timeout=0)
    assert result["method"] == "taskkill_image" and result["image"] == "BarApp.exe"
    assert any("taskkill /F /T /IM BarApp.exe" in c for c in conn.exec_calls)


def test_service_stop_falls_back_to_pid_when_image_unresolved():
    # Stubborn, and `sc qc` yields no resolvable image -> kill by PID.
    conn = FakeConnection(exec_results={"sc queryex": CommandResult(0, RUNNING_SC, "")})
    result = WindowsServiceModule(conn).stop("FooSvc", timeout=0)
    assert result["method"] == "taskkill_pid" and result["pid"] == 4321
    assert any("taskkill /PID 4321 /T /F" in c for c in conn.exec_calls)


def test_service_stop_missing_service():
    conn = FakeConnection(exec_results={"sc queryex": CommandResult(1060, "The specified service does not exist", "")})
    result = WindowsServiceModule(conn).stop("Nope", timeout=0)
    assert result["success"] is False and result["reason"] == "not_found"


def test_service_stop_not_running():
    conn = FakeConnection(exec_results={"sc queryex": CommandResult(0, "STATE : 1  STOPPED", "")})
    result = WindowsServiceModule(conn).stop("FooSvc", timeout=0)
    assert result["state"] == "not_running"
    assert not any("taskkill" in c for c in conn.exec_calls)


def test_service_start_invokes_sc_start():
    conn = FakeConnection(exec_results={"sc start": CommandResult(0, "START_PENDING", "")})
    WindowsServiceModule(conn).start("FooSvc")
    assert any('sc start "FooSvc"' in c for c in conn.exec_calls)


def test_process_kill_targets_matching_pids():
    listing = '[{"Name":"BarApp.exe","ProcessId":111},{"Name":"powershell.exe","ProcessId":222}]'
    conn = FakeConnection(exec_results={"Get-CimInstance": CommandResult(0, listing, "")})
    result = WindowsProcessModule(conn).kill("BarApp")
    killed = {k["pid"] for k in result["killed"]}
    assert 111 in killed
    assert 222 not in killed  # powershell.exe is protected
    assert any("taskkill /PID 111 /F /T" in c for c in conn.exec_calls)


def test_process_kill_no_matches():
    conn = FakeConnection(exec_results={"Get-CimInstance": CommandResult(0, "", "")})
    result = WindowsProcessModule(conn).kill("Ghost")
    assert result["killed"] == []


def test_process_start_launches_via_interactive_scheduled_task():
    # start_process must create+run+delete a one-shot interactive task as the
    # SSH user, launching the exe directly so its command line stays greppable
    # by process.kill (docs/adr/0002).
    conn = FakeConnection(username="barappdev")
    result = WindowsProcessModule(conn).start("C:/Program Files/app.exe", "showUI")
    task = result["task_name"]

    create, run, delete = conn.exec_calls
    assert create.startswith(f"schtasks /create /tn {task} ")
    assert "/sc once" in create and "/it" in create and "/ru barappdev" in create
    # exe inner-quoted (escaped for the SSH->shell hop), args appended verbatim,
    # no cmd /c wrapper.
    assert r'/tr "\"C:\Program Files\app.exe\" showUI"' in create
    assert "cmd /c" not in create
    assert run == f"schtasks /run /tn {task}"
    assert delete == f"schtasks /delete /tn {task} /f"


def test_files_remove_uses_del():
    conn = FakeConnection()
    WindowsFilesModule(conn).remove(["C:/x/libfoodrv.sys", "C:/y/foo.dll"])
    assert any('del /F /Q "C:\\x\\libfoodrv.sys"' in c for c in conn.exec_calls)
    assert any('del /F /Q "C:\\y\\foo.dll"' in c for c in conn.exec_calls)


def test_files_delete_uses_rmdir():
    conn = FakeConnection()
    WindowsFilesModule(conn).delete("C:/logs")
    assert any('rmdir /S /Q "C:\\logs"' in c for c in conn.exec_calls)
