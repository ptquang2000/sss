"""Click CLI mirroring vmctl's command-group shape.

Target selection is shared across commands: pass ``--host/--user`` for a remote
machine, or omit them to auto-detect the running VM. Bare ``sss sync`` runs the
full profile lifecycle (pre_sync -> sync -> post_sync).
"""

import json
import sys

import click

from . import SssError, connect


def _out(data) -> None:
    click.echo(json.dumps(data, indent=2, default=str))


def _err(msg: str) -> None:
    click.echo(json.dumps({"error": msg}), err=True)
    sys.exit(1)


def target_options(f):
    """Shared target / connection options for every command."""
    f = click.option("--host", default=None, help="Remote machine IP/hostname (omit to auto-detect VM).")(f)
    f = click.option("--user", default=None, help="SSH username (remote host).")(f)
    f = click.option("--password", default=None, help="SSH password (remote host).")(f)
    f = click.option("--port", default=22, show_default=True, help="SSH port.")(f)
    f = click.option("--project-dir", default=None, help="Repo dir for git-remote profile selection.")(f)
    return f


def _session(host, user, password, port, project_dir, extra_vars=None, need_profile=False):
    session = connect(
        host=host, user=user, password=password, port=port,
        project_dir=project_dir, extra_vars=extra_vars, log=lambda m: click.echo(m, err=True),
    )
    if need_profile and session.profile is None:
        session.close()
        raise SssError("No sync profile resolved for this project (configure ~/.sss/config.json)")
    return session


@click.group()
def cli():
    pass


# ---------------------------------------------------------------------------
# sync -- full lifecycle: pre_sync -> sync -> post_sync
# ---------------------------------------------------------------------------
@cli.command("sync")
@target_options
@click.option("--optional", "sync_optional", is_flag=True, help="Also sync optional dirs/files.")
@click.option("--debug", "build_cfg", flag_value="Debug", help="Sync Debug binaries ({build_cfg}=Debug).")
@click.option("--release", "build_cfg", flag_value="Release", default=True, help="Sync Release binaries (default).")
@click.option("--arch", type=click.Choice(["x64", "x86", "ARM64", "win32"]), default=None,
              help="Architecture selector, fed to {arch} substitution.")
def cmd_sync(host, user, password, port, project_dir, sync_optional, build_cfg, arch):
    extra_vars = {"build_cfg": build_cfg}
    if arch:
        extra_vars["arch"] = arch
    try:
        with _session(host, user, password, port, project_dir, extra_vars, need_profile=True) as s:
            _out(s.run_lifecycle(sync_optional=sync_optional))
    except SssError as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# push -- ad-hoc, profile-less transfer (no pre_sync/post_sync hooks)
# ---------------------------------------------------------------------------
@cli.command("push")
@target_options
@click.argument("source")
@click.argument("dest")
def cmd_push(host, user, password, port, project_dir, source, dest):
    """Push SOURCE to remote directory DEST -- no profile, no hooks.

    SOURCE is resolved as-typed (absolute, else relative to the current
    directory -- not the profile's base_dir). DEST is always a remote
    directory: a file lands at DEST/<basename>; a directory has its CONTENTS
    merged into DEST (rsync trailing-slash semantics -- it is NOT nested as
    DEST/<dirname>, and there is no rename). Files already up to date on the
    target are skipped.
    """
    try:
        with _session(host, user, password, port, project_dir) as s:
            _out(s.sync.path(source, dest))
    except SssError as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------
@cli.command("exec")
@target_options
@click.argument("command")
def cmd_exec(host, user, password, port, project_dir, command):
    try:
        with _session(host, user, password, port, project_dir) as s:
            _out(s.exec(command))
    except SssError as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------
@cli.group()
def service():
    pass


@service.command("stop")
@target_options
@click.argument("name")
def service_stop(host, user, password, port, project_dir, name):
    try:
        with _session(host, user, password, port, project_dir) as s:
            _out(s.service.stop(name))
    except SssError as e:
        _err(str(e))


@service.command("start")
@target_options
@click.argument("name")
def service_start(host, user, password, port, project_dir, name):
    try:
        with _session(host, user, password, port, project_dir) as s:
            _out(s.service.start(name))
    except SssError as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------
@cli.group()
def process():
    pass


@process.command("kill")
@target_options
@click.argument("name")
def process_kill(host, user, password, port, project_dir, name):
    try:
        with _session(host, user, password, port, project_dir) as s:
            _out(s.process.kill(name))
    except SssError as e:
        _err(str(e))


@process.command("start")
@target_options
@click.argument("exe_path")
@click.argument("args", nargs=-1)
def process_start(host, user, password, port, project_dir, exe_path, args):
    try:
        with _session(host, user, password, port, project_dir) as s:
            _out(s.process.start(exe_path, *args))
    except SssError as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------
@cli.group()
def files():
    pass


@files.command("remove")
@target_options
@click.argument("paths", nargs=-1, required=True)
def files_remove(host, user, password, port, project_dir, paths):
    try:
        with _session(host, user, password, port, project_dir) as s:
            _out(s.files.remove(list(paths)))
    except SssError as e:
        _err(str(e))


@files.command("delete")
@target_options
@click.argument("paths", nargs=-1, required=True)
def files_delete(host, user, password, port, project_dir, paths):
    try:
        with _session(host, user, password, port, project_dir) as s:
            _out(s.files.delete(list(paths)))
    except SssError as e:
        _err(str(e))
