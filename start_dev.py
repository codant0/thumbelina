"""Start backend (uvicorn) then frontend (vite) dev servers.

Backend is started first and health-checked before the frontend is launched.
"""

import gzip
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import IO


class RotatingLogWriter:
    """带大小滚动和压缩的日志写入器。

    Parameters
    ----------
    log_path : Path
        日志文件路径
    max_size : int
        文件最大大小（字节），超过后滚动，默认 50MB
    backup_count : int
        保留的备份文件数量，默认 10
    """

    def __init__(
        self,
        log_path: Path,
        max_size: int = 50 * 1024 * 1024,
        backup_count: int = 10,
    ) -> None:
        self.log_path = log_path
        self.max_size = max_size
        self.backup_count = backup_count
        self._file: IO[str] | None = None
        self._current_size: int = 0
        self._lock = threading.Lock()
        self._open_file()

    def _open_file(self) -> None:
        """打开日志文件，获取当前文件大小。"""
        self._file = open(self.log_path, "a", encoding="utf-8")
        self._current_size = self.log_path.stat().st_size if self.log_path.exists() else 0

    def _rotate(self) -> None:
        """滚动日志文件并压缩旧文件。"""
        if self._file:
            self._file.close()

        # 删除最旧的备份（如果超过备份数量）
        for i in range(self.backup_count, 0, -1):
            src = self.log_path.with_suffix(f".{i}.log.gz")
            if src.exists():
                if i == self.backup_count:
                    src.unlink()
                else:
                    dst = self.log_path.with_suffix(f".{i + 1}.log.gz")
                    src.rename(dst)

        # 压缩当前日志
        compressed_path = self.log_path.with_suffix(".1.log.gz")
        with open(self.log_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # 清空当前日志文件
        self._file = open(self.log_path, "w", encoding="utf-8")
        self._current_size = 0

    def write(self, data: str) -> None:
        """写入日志，必要时滚动。"""
        with self._lock:
            if self._file is None:
                return
            self._file.write(data)
            self._file.flush()
            self._current_size += len(data.encode("utf-8"))

            if self._current_size >= self.max_size:
                self._rotate()

    def close(self) -> None:
        """关闭日志文件。"""
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None


def _stream_to_log(
    pipe: IO[bytes],
    label: str,
    log_writer: RotatingLogWriter,
    buffer: list[str],
) -> None:
    """从管道读取输出，写入日志文件和终端。"""
    try:
        for raw_line in iter(pipe.readline, b""):
            line = raw_line.decode(errors="replace")
            buffer.append(line)
            # 每行写入时生成时间戳
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_line = f"[{timestamp}] [{label}] {line}"
            log_writer.write(log_line)
            # 同时输出到终端
            sys.stderr.write(line)
            sys.stderr.flush()
    except (ValueError, OSError):
        pass  # pipe closed


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


def _start_process(
    name: str,
    cmd: list[str],
    cwd: str,
    procs: dict[str, subprocess.Popen],
    buffers: dict[str, list[str]],
    threads: list[threading.Thread],
    log_writer: RotatingLogWriter | None = None,
) -> None:
    """Start a subprocess with output piped, streamed to terminal via a reader thread.

    Parameters
    ----------
    name : str
        进程名称
    cmd : list[str]
        命令行参数
    cwd : str
        工作目录
    procs : dict
        进程字典
    buffers : dict
        输出缓冲区字典
    threads : list
        线程列表
    log_writer : RotatingLogWriter | None
        日志写入器，如果提供则将输出写入日志文件
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    procs[name] = proc
    buffers[name] = []

    if log_writer:
        t = threading.Thread(
            target=_stream_to_log,
            args=(proc.stdout, name, log_writer, buffers[name]),
            daemon=True,
        )
    else:
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

    # 确保 logs 目录存在
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)

    # 创建前端日志写入器
    frontend_log_writer = RotatingLogWriter(log_dir / "frontend.log")

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

        # 关闭日志写入器
        frontend_log_writer.close()

        failed = False
        for name, p in procs.items():
            if p.returncode and p.returncode != 0:
                failed = True
                output = "".join(output_buffers.get(name, []))
                print(f"\n{'=' * 60}", file=sys.stderr)
                print(f"  [{name}] exited with code {p.returncode}", file=sys.stderr)
                print(f"{'=' * 60}", file=sys.stderr)
                if output.strip():
                    print(output.strip(), file=sys.stderr)
                else:
                    print("  (no output captured)", file=sys.stderr)
                print(f"{'=' * 60}\n", file=sys.stderr)
        sys.exit(1 if failed else 0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 1. Start backend（不重定向，由 loguru 管理）
    print("Starting backend (uvicorn) on http://localhost:8000 ...")
    _start_process(
        "backend",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "thumbelina.api.app:create_app",
            "--factory",
            "--reload",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--log-level",
            "info",
        ],
        str(root),
        procs,
        output_buffers,
        threads,
        log_writer=None,  # 后端日志由 loguru 管理
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
            print(" timed out after 30s. Starting frontend anyway ...")

    # 3. Start frontend（带日志重定向）
    print("Starting frontend (vite) on http://localhost:5173 ...")
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    _start_process(
        "frontend",
        [npm_cmd, "run", "dev"],
        str(frontend),
        procs,
        output_buffers,
        threads,
        log_writer=frontend_log_writer,  # 前端日志写入文件
    )

    print("\n  Backend:  http://localhost:8000")
    print("  Frontend: http://localhost:5173")
    print(f"  Logs:     {log_dir.absolute()}")
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
