"""Focused tests for the reproducible local development launcher."""

import os
import sqlite3
import subprocess
import urllib.error

import pytest

from tazama import local_dev


class FakeProcess:
    def __init__(self, pid: int = 100, exit_code: int | None = None) -> None:
        self.pid = pid
        self.exit_code = exit_code

    def poll(self) -> int | None:
        return self.exit_code

    def wait(self, timeout: float | None = None) -> int:
        return self.exit_code or 0

    def terminate(self) -> None:
        self.exit_code = 0

    def kill(self) -> None:
        self.exit_code = -9


@pytest.fixture
def config(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    return local_dev.LocalDevConfig(
        repository_root=tmp_path,
        database_path=tmp_path / ".local" / "tazama.sqlite3",
        web_directory=web,
        startup_timeout=1,
    )


def test_fresh_database_initialization(config):
    local_dev.initialize_database(config)
    assert config.database_path.is_file()
    with sqlite3.connect(config.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"observations", "review_requests", "mcp_tool_calls"} <= tables


def test_repeated_initialization_preserves_existing_contents(config):
    local_dev.initialize_database(config)
    with sqlite3.connect(config.database_path) as connection:
        connection.execute("CREATE TABLE launcher_marker (value TEXT)")
        connection.execute("INSERT INTO launcher_marker VALUES ('preserved')")
    local_dev.initialize_database(config)
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute("SELECT value FROM launcher_marker").fetchone() == (
            "preserved",
        )


def test_missing_required_dependency_has_install_guidance(config, monkeypatch):
    monkeypatch.setattr(local_dev.importlib.util, "find_spec", lambda name: object())
    with pytest.raises(local_dev.LauncherError, match="Install Node.js"):
        local_dev.require_prerequisites(
            config,
            which=lambda command: None if command == "node" else f"/bin/{command}",
        )


def test_missing_frontend_packages_use_npm_ci(config, monkeypatch):
    monkeypatch.setattr(local_dev.importlib.util, "find_spec", lambda name: object())
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    local_dev.require_prerequisites(
        config,
        which=lambda command: f"/bin/{command}",
        run=run,
    )
    assert calls == [
        (["npm", "ci"], {"cwd": config.web_directory, "check": True})
    ]


def test_occupied_port_fails_without_starting_services():
    with pytest.raises(local_dev.LauncherError, match="Port 8000 is already in use"):
        local_dev.require_available_ports(checker=lambda port: port != 8000)


def launcher_mocks(monkeypatch):
    calls = []
    stopped = []

    def popen(command, **kwargs):
        process = FakeProcess(pid=100 + len(calls))
        calls.append((command, kwargs, process))
        return process

    monkeypatch.setattr(local_dev, "stop_process", stopped.append)
    monkeypatch.setattr(local_dev.signal, "signal", lambda *args: None)
    return calls, stopped, popen


def test_backend_startup_failure_cleans_up_backend(config, monkeypatch):
    calls, stopped, popen = launcher_mocks(monkeypatch)

    def readiness(name, url, process, timeout):
        raise local_dev.LauncherError("backend failed")

    with pytest.raises(local_dev.LauncherError, match="backend failed"):
        local_dev.run_local_dev(
            config,
            popen=popen,
            readiness=readiness,
            port_checker=lambda port: True,
        )
    assert len(calls) == 1
    assert stopped == [calls[0][2]]


def test_frontend_startup_failure_cleans_up_both_children(config, monkeypatch):
    calls, stopped, popen = launcher_mocks(monkeypatch)

    def readiness(name, url, process, timeout):
        if name == "Next.js frontend":
            raise local_dev.LauncherError("frontend failed")

    with pytest.raises(local_dev.LauncherError, match="frontend failed"):
        local_dev.run_local_dev(
            config,
            popen=popen,
            readiness=readiness,
            port_checker=lambda port: True,
        )
    assert stopped == [calls[1][2], calls[0][2]]


def test_readiness_timeout_is_clear():
    times = iter([0.0, 0.0, 1.1])

    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("not ready")

    with pytest.raises(local_dev.LauncherError, match="Timed out after 1s"):
        local_dev.wait_for_service(
            "service",
            "http://127.0.0.1",
            FakeProcess(),
            1,
            opener=unavailable,
            monotonic=lambda: next(times),
            sleep=lambda seconds: None,
        )


def test_ctrl_c_cleans_up_both_children(config, monkeypatch):
    calls, stopped, popen = launcher_mocks(monkeypatch)

    def interrupt(processes, stop):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        local_dev.run_local_dev(
            config,
            popen=popen,
            readiness=lambda *args: None,
            port_checker=lambda port: True,
            supervisor=interrupt,
        )
    assert stopped == [calls[1][2], calls[0][2]]


def test_child_environments_and_commands_are_propagated(config, monkeypatch):
    calls, stopped, popen = launcher_mocks(monkeypatch)
    monkeypatch.setenv("TAZAMA_OLLAMA_MODEL", "local-model")

    local_dev.run_local_dev(
        config,
        popen=popen,
        readiness=lambda *args: None,
        port_checker=lambda port: True,
        supervisor=lambda processes, stop: None,
    )

    backend_command, backend_options, _ = calls[0]
    frontend_command, frontend_options, _ = calls[1]
    assert backend_command[:3] == [os.sys.executable, "-m", "uvicorn"]
    assert backend_options["env"]["TAZAMA_DB_PATH"] == str(
        config.database_path.resolve()
    )
    assert frontend_command[:3] == ["npm", "run", "dev"]
    assert frontend_options["env"]["TAZAMA_API_URL"] == "http://127.0.0.1:8000"
    assert backend_options["env"]["TAZAMA_OLLAMA_MODEL"] == "local-model"
    assert stopped == [calls[1][2], calls[0][2]]
