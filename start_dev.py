"""Start both backend (uvicorn) and frontend (vite) dev servers concurrently."""

import subprocess
import signal
import sys
import os
import time
import threading
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
    """Start a subprocess with stderr piped, streamed to terminal via a reader thread."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # merge stderr into stdout so nothing is lost
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
        # Give reader threads a moment to drain remaining output
        for t in threads:
            t.join(timeout=1.0)
        # Show prominent error output for any failed process
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

    print("Starting backend (uvicorn) on http://localhost:8000 ...")
    _start_process(
        "backend",
        [sys.executable, "-m", "uvicorn", "thumbelina.api.app:create_app",
         "--factory", "--reload", "--host", "0.0.0.0", "--port", "8000"],
        str(root), procs, output_buffers, threads,
    )

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
