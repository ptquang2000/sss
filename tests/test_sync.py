"""SyncEngine is the priority for tests: it holds the real logic.

We feed it a mapping + a temp filesystem + a FakeConnection and assert which
files upload vs skip (mtime/size), that excludes are honored, and that {var}
substitution expands correctly.
"""

import os

from sss.config import Profile
from sss.sync import SyncEngine

from .fakes import FakeConnection, RemoteStat


def _write(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def test_uploads_new_files(tmp_path):
    src = tmp_path / "src"
    _write(str(src / "a.txt"), "hello")
    _write(str(src / "sub" / "b.txt"), "world")

    profile = Profile("p", source_dirs={"src": ["/remote/dest"]})
    conn = FakeConnection()  # remote empty -> everything is new
    result = SyncEngine(base_dir=str(tmp_path)).run(profile, conn)

    uploaded = {r for _, r in conn.uploaded}
    assert "/remote/dest/a.txt" in uploaded
    assert "/remote/dest/sub/b.txt" in uploaded
    assert result.uploaded and not result.skipped


def test_skips_unchanged_by_size_and_mtime(tmp_path):
    src = tmp_path / "src"
    local = str(src / "a.txt")
    _write(local, "hello")
    size = os.path.getsize(local)
    mtime = int(os.path.getmtime(local))

    # Remote is same size and newer -> should skip.
    conn = FakeConnection(remote={"/remote/dest/a.txt": RemoteStat(size, mtime + 100)})
    profile = Profile("p", source_dirs={"src": ["/remote/dest"]})
    result = SyncEngine(base_dir=str(tmp_path)).run(profile, conn)

    assert conn.uploaded == []
    assert "/remote/dest/a.txt" in result.skipped


def test_reuploads_when_local_newer(tmp_path):
    src = tmp_path / "src"
    local = str(src / "a.txt")
    _write(local, "hello")
    size = os.path.getsize(local)
    mtime = int(os.path.getmtime(local))

    # Remote same size but older -> re-upload.
    conn = FakeConnection(remote={"/remote/dest/a.txt": RemoteStat(size, mtime - 100)})
    profile = Profile("p", source_dirs={"src": ["/remote/dest"]})
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn)

    assert ("/remote/dest/a.txt") in {r for _, r in conn.uploaded}


def test_reuploads_when_size_differs(tmp_path):
    src = tmp_path / "src"
    local = str(src / "a.txt")
    _write(local, "hello")
    mtime = int(os.path.getmtime(local))

    conn = FakeConnection(remote={"/remote/dest/a.txt": RemoteStat(99999, mtime + 100)})
    profile = Profile("p", source_dirs={"src": ["/remote/dest"]})
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn)

    assert conn.uploaded  # size mismatch forces upload despite newer mtime


def test_exclude_glob_honored(tmp_path):
    src = tmp_path / "src"
    _write(str(src / "keep.txt"))
    _write(str(src / "drop.pdb"))

    profile = Profile("p", source_dirs={"src": ["/remote/dest"]}, exclude=["*.pdb"])
    conn = FakeConnection()
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn)

    uploaded = {r for _, r in conn.uploaded}
    assert "/remote/dest/keep.txt" in uploaded
    assert all("drop.pdb" not in r for r in uploaded)


def test_variable_substitution(tmp_path):
    src = tmp_path / "src"
    _write(str(src / "a.txt"))

    profile = Profile(
        "p",
        source_dirs={"src": ["/remote/{build_cfg}/{arch}"]},
        variables={"build_cfg": "Release", "arch": "x64"},
    )
    conn = FakeConnection()
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn)

    assert ("/remote/Release/x64/a.txt") in {r for _, r in conn.uploaded}


def test_multiple_destinations(tmp_path):
    src = tmp_path / "src"
    _write(str(src / "a.txt"))

    profile = Profile("p", source_dirs={"src": ["/dest1", "/dest2"]})
    conn = FakeConnection()
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn)

    uploaded = {r for _, r in conn.uploaded}
    assert "/dest1/a.txt" in uploaded
    assert "/dest2/a.txt" in uploaded


def test_optional_dirs_skipped_unless_requested(tmp_path):
    _write(str(tmp_path / "src" / "a.txt"))
    _write(str(tmp_path / "opt" / "b.txt"))
    profile = Profile(
        "p",
        source_dirs={"src": ["/dest"]},
        optional_dirs={"opt": ["/dest/opt"]},
    )

    conn = FakeConnection()
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn, sync_optional=False)
    assert all("b.txt" not in r for _, r in conn.uploaded)

    conn2 = FakeConnection()
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn2, sync_optional=True)
    assert any("b.txt" in r for _, r in conn2.uploaded)


def test_source_files_mapping(tmp_path):
    _write(str(tmp_path / "tools" / "helper.dll"))
    profile = Profile("p", source_files={"tools/helper.dll": "/remote/bin"})
    conn = FakeConnection()
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn)
    assert ("/remote/bin/helper.dll") in {r for _, r in conn.uploaded}


def test_missing_source_recorded(tmp_path):
    profile = Profile("p", source_dirs={"nope": ["/dest"]})
    conn = FakeConnection()
    result = SyncEngine(base_dir=str(tmp_path)).run(profile, conn)
    assert result.missing and not conn.uploaded


def test_remote_dirs_created(tmp_path):
    _write(str(tmp_path / "src" / "a.txt"))
    profile = Profile("p", source_dirs={"src": ["/remote/dest"]})
    conn = FakeConnection()
    SyncEngine(base_dir=str(tmp_path)).run(profile, conn)
    assert "/remote/dest" in conn.mkdirs


# -- push: ad-hoc single source -> dest transfer (sync_path) ----------------

def test_push_file_lands_at_dest_basename(tmp_path):
    local = str(tmp_path / "artifact.dll")
    _write(local, "bytes")

    conn = FakeConnection()
    result = SyncEngine().sync_path(conn, local, "/remote/bin")

    uploaded = {r for _, r in conn.uploaded}
    assert "/remote/bin/artifact.dll" in uploaded
    assert "/remote/bin/artifact.dll" in result.uploaded


def test_push_directory_contents_merged_not_nested(tmp_path):
    src = tmp_path / "build"
    _write(str(src / "a.txt"))
    _write(str(src / "sub" / "b.txt"))

    conn = FakeConnection()
    SyncEngine().sync_path(conn, str(src), "/remote/dest")

    uploaded = {r for _, r in conn.uploaded}
    # contents merged into dest, NOT nested under dest/build
    assert "/remote/dest/a.txt" in uploaded
    assert "/remote/dest/sub/b.txt" in uploaded
    assert all("/remote/dest/build/" not in r for r in uploaded)


def test_push_skips_unchanged(tmp_path):
    local = str(tmp_path / "a.txt")
    _write(local, "hello")
    size = os.path.getsize(local)
    mtime = int(os.path.getmtime(local))

    conn = FakeConnection(remote={"/remote/dest/a.txt": RemoteStat(size, mtime + 100)})
    result = SyncEngine().sync_path(conn, local, "/remote/dest")

    assert conn.uploaded == []
    assert "/remote/dest/a.txt" in result.skipped


def test_push_resolves_source_against_cwd_not_base_dir(tmp_path, monkeypatch):
    # base_dir points elsewhere; a cwd-relative source must resolve against cwd.
    work = tmp_path / "work"
    _write(str(work / "note.txt"), "hi")
    monkeypatch.chdir(work)

    conn = FakeConnection()
    SyncEngine(base_dir=str(tmp_path / "somewhere_else")).sync_path(conn, "note.txt", "/remote/dest")

    assert "/remote/dest/note.txt" in {r for _, r in conn.uploaded}


def test_push_missing_source_recorded(tmp_path):
    conn = FakeConnection()
    result = SyncEngine().sync_path(conn, str(tmp_path / "nope.txt"), "/remote/dest")
    assert result.missing and not conn.uploaded
