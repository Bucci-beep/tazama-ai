"""Reproducible local FastAPI and Next.js development launcher."""

from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tazama.storage.database import Database
from tazama.storage.reviews import ReviewRepository

HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_PORT = 3000


class LauncherError(RuntimeError):
    """A clear, actionable local launcher failure."""


class Process(Protocol):
    pid: int

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


@dataclass(frozen=True)
class LocalDevConfig:
    """Resolved local paths, URLs, and timeouts."""

    repository_root: Path
    database_path: Path
    web_directory: Path
    startup_timeout: float = 60.0

    @classmethod
    def default(cls) -> LocalDevConfig:
        root = Path(__file__).resolve().parents[2]
        timeout = float(os.environ.get("TAZAMA_STARTUP_TIMEOUT", "60"))
        return cls(
            repository_root=root,
            database_path=root / ".local" / "tazama.sqlite3",
            web_directory=root / "web",
            startup_timeout=timeout,
        )


def require_prerequisites(
    config: LocalDevConfig,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Validate executables and install locked frontend packages when absent."""
    if importlib.util.find_spec("uvicorn") is None:
        raise LauncherError(
            "Python dependencies are missing. Install uv, then run: uv sync"
        )
    for command, guidance in (
        ("uv", "Install uv from https://docs.astral.sh/uv/ and run 'uv sync'."),
        ("node", "Install Node.js 20 or newer."),
        ("npm", "Install npm with Node.js, then retry."),
    ):
        if which(command) is None:
            raise LauncherError(f"Required command '{command}' was not found. {guidance}")

    next_package = config.web_directory / "node_modules" / "next" / "package.json"
    if not next_package.is_file():
        print("Frontend dependencies are missing; running npm ci...")
        try:
            run(["npm", "ci"], cwd=config.web_directory, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise LauncherError(
                "Frontend dependency installation failed. Run 'cd web && npm ci' "
                "and review npm's output."
            ) from exc


def initialize_database(config: LocalDevConfig) -> None:
    """Create missing schema without deleting or reseeding existing data."""
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(config.database_path)
    database.initialize()
    ReviewRepository(database).initialize()


def port_is_available(port: int, *, host: str = HOST) -> bool:
    """Return whether a localhost TCP port can be bound without interference."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
        except OSError:
            return False
    return True


def require_available_ports(
    *, checker: Callable[[int], bool] = port_is_available
) -> None:
    for port, service in ((BACKEND_PORT, "FastAPI"), (FRONTEND_PORT, "Next.js")):
        if not checker(port):
            raise LauncherError(
                f"Port {port} is already in use; {service} was not started. "
                "Stop the existing service or free the port, then retry."
            )


def wait_for_service(
    name: str,
    url: str,
    process: Process,
    timeout: float,
    *,
    opener: Callable[..., object] = urllib.request.urlopen,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait for HTTP readiness while detecting early process failure."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise LauncherError(f"{name} exited during startup with code {exit_code}.")
        try:
            with opener(url, timeout=1) as response:
                if getattr(response, "status", None) == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        sleep(0.2)
    raise LauncherError(
        f"Timed out after {timeout:g}s waiting for {name} readiness at {url}."
    )


def _popen_options() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_process(process: Process, *, timeout: float = 5.0) -> None:
    """Stop a child process group, escalating only after a bounded wait."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=timeout)
    except ProcessLookupError:
        return


def supervise(processes: Sequence[tuple[str, Process]], stop: threading.Event) -> None:
    """Block until termination is requested or a child exits unexpectedly."""
    while not stop.wait(0.25):
        for name, process in processes:
            exit_code = process.poll()
            if exit_code is not None:
                raise LauncherError(f"{name} stopped unexpectedly with code {exit_code}.")


def run_local_dev(
    config: LocalDevConfig,
    *,
    popen: Callable[..., Process] = subprocess.Popen,
    readiness: Callable[[str, str, Process, float], None] = wait_for_service,
    port_checker: Callable[[int], bool] = port_is_available,
    supervisor: Callable[[Sequence[tuple[str, Process]], threading.Event], None] = supervise,
) -> None:
    """Initialize, start, verify, and supervise both local services."""
    require_available_ports(checker=port_checker)
    initialize_database(config)

    backend_url = f"http://{HOST}:{BACKEND_PORT}"
    frontend_url = f"http://{HOST}:{FRONTEND_PORT}"
    backend_env = {**os.environ, "TAZAMA_DB_PATH": str(config.database_path.resolve())}
    frontend_env = {**os.environ, "TAZAMA_API_URL": backend_url}
    processes: list[tuple[str, Process]] = []
    stop = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    previous_handlers = {
        signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        for signum in previous_handlers:
            signal.signal(signum, request_stop)
        backend = popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tazama.api.app:app",
                "--host",
                HOST,
                "--port",
                str(BACKEND_PORT),
            ],
            cwd=config.repository_root,
            env=backend_env,
            **_popen_options(),
        )
        processes.append(("FastAPI backend", backend))
        readiness(
            "FastAPI backend",
            f"{backend_url}/api/v1/health",
            backend,
            config.startup_timeout,
        )

        frontend = popen(
            [
                "npm",
                "run",
                "dev",
                "--",
                "--hostname",
                HOST,
                "--port",
                str(FRONTEND_PORT),
            ],
            cwd=config.web_directory,
            env=frontend_env,
            **_popen_options(),
        )
        processes.append(("Next.js frontend", frontend))
        readiness(
            "Next.js frontend",
            frontend_url,
            frontend,
            config.startup_timeout,
        )

        print("\nTriageGuard AI local development is ready:")
        print(f"  Dashboard: {frontend_url}")
        print(f"  API:       {backend_url}")
        print(f"  Database:  {config.database_path}")
        if "TAZAMA_OLLAMA_MODEL" not in os.environ:
            print("  Ollama:    optional and not configured; explanations stay unavailable")
        print("Press Ctrl+C to stop both services. Synthetic data only; not for clinical use.\n")
        supervisor(processes, stop)
    finally:
        for _name, process in reversed(processes):
            stop_process(process)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main() -> int:
    config = LocalDevConfig.default()
    try:
        require_prerequisites(config)
        run_local_dev(config)
    except KeyboardInterrupt:
        print("\nStopping local development services...")
    except LauncherError as exc:
        print(f"Local development failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
