"""remote_executor SSH 直连 backend 单测 (mock paramiko)."""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))
from tools import remote_executor as re  # noqa: E402


class FakeChannel:
    def recv_exit_status(self):
        return 0


class FakeStream:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data.encode()

    @property
    def channel(self):
        return FakeChannel()


def _fake_exec_command(cmd, timeout):
    return (None, FakeStream("hello from h20\n"), FakeStream(""))


def test_run_ssh_success():
    with mock.patch("paramiko.SSHClient") as m:
        client = m.return_value
        client.exec_command.side_effect = _fake_exec_command
        r = re._run_ssh("echo hello", timeout=30)
    assert r["exit_code"] == 0
    assert "hello from h20" in r["stdout"]
    client.connect.assert_called_once()
    client.close.assert_called_once()


def test_run_ssh_error_returns_exit1():
    with mock.patch("paramiko.SSHClient") as m:
        m.return_value.connect.side_effect = Exception("conn refused")
        r = re._run_ssh("echo x", timeout=30)
    assert r["exit_code"] == 1
    assert "conn refused" in r["stderr"]


def test_run_remote_ssh_dispatch():
    with mock.patch.object(re, "_run_ssh", return_value={"exit_code": 0, "stdout": "OK", "stderr": ""}) as m:
        r = re.run_remote("echo x", backend="ssh", timeout=30)
    assert r["stdout"] == "OK"
    m.assert_called_once()
