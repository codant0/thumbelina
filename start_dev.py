"""Start backend (uvicorn) then frontend (vite) dev servers.

Backend is started first and health-checked before the frontend is launched.
"""

import subprocess
import signal
import sys
import os
import time
import threading
import urllib.request
import urllib.error
from pathlib import Path


def _stream_and_capture(pipe, label: str, buffer: list[str]):
    """Read from a pipe line-by-line, printing to the terminal and storing in buffer."""
    try:
        for raw_line in iter(pipe.readline, b""):
            line = raw_line.decode(errors="replace")
            buffer.append(line)
            sys.stderr.write(line)
            sys.stderr.flush()
    except (ValueError, OSError):
        pass  # pipe closed


def _start_process(name: str, cmd: list[str], cwd: str, procs, buffers, threads):
    """Start a subprocess with output piped, streamed to terminal via a reader thread."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    procs[name] = proc
    buffers[name] = []
    t = threading.Thread(
        target=_stream_and_capture,
        args=(proc.stdout, name, buffers[name]),
        daemon=True,
    )
    t.start()
    threads.append(t)


def _wait_for_backend(procs, output_buffers, threads, host="127.0.0.1", port=8000, timeout=30):
    """Poll the /health endpoint until the backend is ready or times out."""
    url = f"http://{host}:{port}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # If backend already exited, bail out immediately
        if procs.get("backend") and procs["backend"].poll() is not None:
            return False
        try:
            resp = urllib.request.urlopen(url, timeout=2)
            if resp.status == 200:
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return False


def main():
    root = Path(__file__).resolve().parent
    frontend = root / "frontend"

    procs: dict[str, subprocess.Popen] = {}
    output_buffers: dict[str, list[str]] = {}
    threads: list[threading.Thread] = []

    def shutdown(*_):
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        for p in procs.values():
            p.wait()
        for t in threads:
            t.join(timeout=1.0)
        failed = False
        for name, p in procs.items():
            if p.returncode and p.returncode != 0:
                failed = True
                output = "".join(output_buffers.get(name, []))
                print(f"\n{'='*60}", file=sys.stderr)
                print(f"  [{name}] exited with code {p.returncode}", file=sys.stderr)
                print(f"{'='*60}", file=sys.stderr)
                if output.strip():
                    print(output.strip(), file=sys.stderr)
                else:
                    print("  (no output captured)", file=sys.stderr)
                print(f"{'='*60}\n", file=sys.stderr)
        sys.exit(1 if failed else 0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 1. Start backend
    print("Starting backend (uvicorn) on http://localhost:8000 ...")
    _start_process(
        "backend",
        [sys.executable, "-m", "uvicorn", "thumbelina.api.app:create_app",
         "--factory", "--reload", "--host", "0.0.0.0", "--port", "8000"],
        str(root), procs, output_buffers, threads,
    )

    # 2. Wait for backend to be healthy
    print("Waiting for backend to be ready ...", end="", flush=True)
    if _wait_for_backend(procs, output_buffers, threads):
        print(" ready!")
    else:
        # Check if backend process died
        if procs.get("backend") and procs["backend"].poll() is not None:
            shutdown()
        else:
            print(f" timed out after 30s. Starting frontend anyway ...")

    # 3. Start frontend
    print("Starting frontend (vite) on http://localhost:5173 ...")
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    _start_process(
        "frontend",
        [npm_cmd, "run", "dev"],
        str(frontend), procs, output_buffers, threads,
    )

    print("\n  Backend:  http://localhost:8000")
    print("  Frontend: http://localhost:5173")
    print("\nPress Ctrl+C to stop both servers.\n")

    # Monitor subprocesses: if either exits, shut down both
    try:
        while True:
            for name, p in procs.items():
                if p.poll() is not None:
                    shutdown()
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
