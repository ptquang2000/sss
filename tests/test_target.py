"""Target resolution: an explicit host builds an SSH connection; no host fails."""

import pytest

from sss.exceptions import SssError
from sss.target import Target


def test_host_builds_ssh_connection():
    conn, meta = Target.resolve(host="10.0.0.5", user="me", password="pw", connect=False)
    assert meta == {"host": "10.0.0.5", "user": "me"}
    assert conn.host == "10.0.0.5" and conn.username == "me"


def test_host_without_credentials_is_allowed():
    # publickey/agent auth: user/password may be omitted.
    conn, meta = Target.resolve(host="10.0.0.5", connect=False)
    assert meta == {"host": "10.0.0.5", "user": None}
    assert conn.host == "10.0.0.5" and conn.username is None


def test_missing_host_raises():
    with pytest.raises(SssError, match="host is required"):
        Target.resolve(connect=False)
