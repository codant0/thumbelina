"""Start both backend (uvicorn) and frontend (vite) dev servers concurrently."""

import subprocess
import signal
import sys
import os
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    frontend = root / "frontend"

    procs: list[subprocess.Popen] = []

    def shutdown(*_):
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            p.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("Starting backend (uvicorn) on http://localhost:8000 ...")
    procs.append(
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "thumbelina.api.app:create_app",
             "--factory", "--reload", "--host", "0.0.0.0", "--port", "8000"],
            cwd=root,
        )
    )

    print("Starting frontend (vite) on http://localhost:5173 ...")
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    procs.append(
        subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=frontend,
        )
    )

    print("\n  Backend:  http://localhost:8000")
    print("  Frontend: http://localhost:5173")
    print("\nPress Ctrl+C to stop both servers.\n")

    # Wait for any child to exit
    try:
        while True:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    print(f"\nA server exited (code {ret}). Shutting down...")
                    shutdown()
            import time
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
