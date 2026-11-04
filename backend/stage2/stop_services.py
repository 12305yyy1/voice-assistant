r"""停止阶段二服务（只停止本项目共享 venv 启动的 app.py / asr_tts_api.py）。"""

from __future__ import annotations

import json
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]          # ...\voice-assistant\backend
STAGE2 = Path(__file__).resolve().parent
PIDS_FILE = STAGE2 / "logs" / "pids.json"
BACKEND_ROOT = str(ROOT.resolve()).lower()
VENV_ROOT = str(ROOT.parent.resolve()).lower()       # ...\voice-assistant\.venv

stopped: list[int] = []


def belongs_to_backend(proc: psutil.Process) -> bool:
    try:
        exe = str(Path(proc.exe()).resolve()).lower()
        if not exe.startswith(VENV_ROOT):
            return False
        try:
            cwd = str(Path(proc.cwd()).resolve()).lower()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            cwd = ""
        cmdline = " ".join(proc.cmdline()).lower()
        return (
            cwd.startswith(BACKEND_ROOT)
            or "asr_tts_api.py" in cmdline
            or ("app.py" in cmdline and "backend" in cmdline)
        )
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False


def stop_pid(pid: int) -> None:
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    if not belongs_to_backend(proc):
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (psutil.NoSuchProcess, psutil.TimeoutExpired):
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    stopped.append(pid)


if PIDS_FILE.exists():
    try:
        for item in json.loads(PIDS_FILE.read_text(encoding="utf-8")):
            stop_pid(int(item["pid"]))
    except Exception as exc:
        print(f"读取 pids.json 失败：{exc}")

for proc in psutil.process_iter(["pid", "exe"]):
    if belongs_to_backend(proc):
        stop_pid(proc.info["pid"])

stopped = sorted(set(stopped))
print(f"已停止 PID: {', '.join(map(str, stopped))}" if stopped else "没有找到本项目正在运行的服务进程")
