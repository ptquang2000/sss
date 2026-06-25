"""Live integration tests against a real SSH host (``SSS_HOST``).

Always run under plain ``pytest`` -- no opt-in env gate. The shared fixtures in
``conftest.py`` connect the target and **fail loudly** when setup is missing.
Unit-only runs: ``pytest -k "not integration"``. See tests/INTEGRATION.md for
setup.

These cross the seams unit tests can't reach: real Paramiko SFTP and real
Windows ``sc.exe`` / ``del`` / ``rmdir`` / ``taskkill`` semantics. Every
destructive operation is confined to a per-test ``sandbox`` scratch dir.
"""

import os
import time

from sss import Sss, connect
from sss.config import Profile
from sss.sync import SyncEngine


def _win(path: str) -> str:
    return path.replace("/", "\\")


def test_exec_roundtrip(session):
    result = session.exec("echo sss-live")
    assert result["exit_code"] == 0
    assert "sss-live" in result["stdout"]


def test_service_query_does_not_crash(session):
    # Query-only on the live target: a bogus service is reported not_found,
    # never raised. (The force-kill path is covered by unit tests.)
    result = session.service.stop("sss-nonexistent-service", timeout=0)
    assert result["success"] is False and result["reason"] == "not_found"


def test_sync_uploads_then_skips(session, sandbox, tmp_path):
    """SyncEngine over real SFTP: a fresh file uploads, an unchanged one skips."""
    src = tmp_path / "payload"
    src.mkdir()
    (src / "hello.txt").write_text("sss-live-sync")

    dest = sandbox["dir"] + "/synced"
    profile = Profile("it-sync", source_dirs={"payload": [dest]})
    engine = SyncEngine(base_dir=str(tmp_path))

    first = engine.run(profile, session._conn)
    assert any("hello.txt" in u for u in first.uploaded)
    assert not first.skipped

    second = engine.run(profile, session._conn)
    assert any("hello.txt" in s for s in second.skipped)
    assert not second.uploaded


def test_push_uploads_then_skips(session, sandbox, tmp_path):
    """``s.sync.path`` over real SFTP: ad-hoc push of a file and a directory.

    Exercises the profile-less ``push`` path end-to-end -- a file lands at
    ``dest/<basename>``, a directory has its contents merged into ``dest`` (not
    nested under ``dest/<dirname>``), and a second identical push skips.
    """
    payload = tmp_path / "build"
    payload.mkdir()
    (payload / "artifact.txt").write_text("sss-live-push")
    (payload / "sub").mkdir()
    (payload / "sub" / "nested.txt").write_text("sss-live-push-nested")

    # File push -> dest/<basename>.
    file_dest = sandbox["dir"] + "/file-push"
    first_file = session.sync.path(str(payload / "artifact.txt"), file_dest)
    uploaded = first_file["uploaded"]
    assert any(u.endswith("/file-push/artifact.txt") for u in uploaded)
    assert session._conn.stat(file_dest + "/artifact.txt") is not None

    # Second identical push skips (mtime/size unchanged).
    second_file = session.sync.path(str(payload / "artifact.txt"), file_dest)
    assert any("artifact.txt" in s for s in second_file["skipped"])
    assert not second_file["uploaded"]

    # Directory push -> contents merged into dest, NOT nested under dest/build.
    dir_dest = sandbox["dir"] + "/dir-push"
    dir_result = session.sync.path(str(payload), dir_dest)
    assert session._conn.stat(dir_dest + "/artifact.txt") is not None
    assert session._conn.stat(dir_dest + "/sub/nested.txt") is not None
    assert session._conn.stat(dir_dest + "/build") is None
    assert all("/build/" not in u for u in dir_result["uploaded"])


def test_files_remove_and_delete(session, sandbox, tmp_path):
    """files.remove (`del`) drops a file; files.delete (`rmdir`) drops a tree."""
    sub = sandbox["dir"] + "/files"
    session._conn.mkdir_p(sub)

    local = tmp_path / "junk.txt"
    local.write_text("data")
    target_file = sub + "/junk.txt"
    session._conn.put(str(local), target_file)
    assert session._conn.stat(target_file) is not None

    assert session.files.remove([target_file])["success"]
    assert session._conn.stat(target_file) is None

    session._conn.put(str(local), sub + "/again.txt")
    assert session.files.delete([sub])["success"]
    assert session._conn.stat(sub) is None


def test_process_spawn_and_kill(session, sandbox):
    """Spawn a throwaway waiter tagged with a unique token, then kill by token.

    ``waitfor.exe /t 60 <TOKEN>`` blocks on a never-signalled event (self-expires
    in 60s as a cleanup backstop) and is not in the process module's protected
    set. ``process.kill`` matches the token surgically against the command line,
    so only this waiter is affected.
    """
    token = "sssit" + sandbox["token"]
    session.process.start("waitfor.exe", "/t", "60", token)

    killed = []
    for _ in range(15):  # Start-Process returns before the child is visible
        result = session.process.kill(token)
        killed = result["killed"]
        if killed:
            break
        time.sleep(1)

    assert killed, f"throwaway waiter tagged {token!r} never appeared / wasn't killed"
    assert any("waitfor" in k["name"].lower() for k in killed)


def test_process_survives_session_close(session, sandbox):
    """A process started by sss must outlive the SSH session that launched it.

    This is the regression gate for docs/adr/0002. Start a token-tagged waiter
    on session A, then open an *independent* session B (a fresh ``connect``) and
    assert the waiter is still alive there -- the property the old
    ``Start-Process`` launch could never satisfy, since the child died with
    session A's job object. Only then kill it by token and confirm it's gone.

    ``waitfor.exe /t 60 <TOKEN>`` blocks (self-expiring in 60s as a cleanup
    backstop, comfortably past reconnect + poll time) and is not protected, so
    ``process.kill`` matches the token surgically.
    """
    token = "sssalive" + sandbox["token"]
    session.process.start("waitfor.exe", "/t", "60", token)

    other = connect(
        host=os.environ.get("SSS_HOST"),
        user=os.environ.get("SSS_USER"),
        password=os.environ.get("SSS_PASSWORD"),
    )
    try:
        alive = False
        for _ in range(15):  # the scheduled-task launch isn't instantaneous
            ps = (
                'powershell "Get-CimInstance Win32_Process | '
                f"Where-Object {{ $_.CommandLine -like '*{token}*' }} | "
                'Select-Object -First 1 ProcessId | ConvertTo-Json"'
            )
            if other.exec(ps)["stdout"].strip():
                alive = True
                break
            time.sleep(1)
        assert alive, (
            f"process tagged {token!r} did not survive into a fresh session "
            "(start_process launch did not outlive the launching session)"
        )

        result = other.process.kill(token)
        assert result["killed"], f"failed to kill surviving process tagged {token!r}"
        assert any("waitfor" in k["name"].lower() for k in result["killed"])
    finally:
        other.close()


def test_run_lifecycle_in_sandbox(session, sandbox, tmp_path):
    """Full pre_sync -> sync -> post_sync over a test-authored, sandboxed profile.

    The real BarApp profile never runs: this profile's every step stays inside
    the scratch dir. Built on the live connection via a fresh ``Sss`` so its
    sync base_dir points at the local payload.
    """
    src = tmp_path / "life"
    src.mkdir()
    (src / "app.txt").write_text("lifecycle")

    dest = sandbox["dir"] + "/install"
    pre_marker = sandbox["dir"] + "/pre.flag"
    post_marker = sandbox["dir"] + "/post.flag"
    profile = Profile(
        "it-lifecycle",
        source_dirs={"life": [dest]},
        pre_sync=[{"op": "exec", "args": {"cmd": f'echo pre> "{_win(pre_marker)}"'}}],
        post_sync=[{"op": "exec", "args": {"cmd": f'echo post> "{_win(post_marker)}"'}}],
    )

    lifecycle = Sss(session._conn, profile=profile, base_dir=str(tmp_path))
    result = lifecycle.run_lifecycle()

    assert result["pre_sync"][0]["result"]["exit_code"] == 0
    assert session._conn.stat(pre_marker) is not None
    assert any("app.txt" in u for u in result["sync"]["uploaded"])
    assert result["post_sync"][0]["result"]["exit_code"] == 0
    assert session._conn.stat(post_marker) is not None
