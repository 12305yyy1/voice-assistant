r"""启动阶段二服务：8010 ASR/TTS 验证接口 + 8000/8003 原项目服务。

在普通 Windows 终端运行（不要在 DSH 文件沙箱中运行，loguru 需要命名管道）：
    cd F:\PBL\voice-assistant\backend
    ..\.venv\Scripts\python.exe .\stage2\run_services.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE2 = Path(__file__).resolve().parent
SERVER_DIR = ROOT / "main" / "xiaozhi-server"
PYTHON = ROOT.parent / ".venv" / "Scripts" / "python.exe"
LOG_DIR = STAGE2 / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

ENV = os.environ.copy()
ENV.update(
    {
        "PATH": str(STAGE2 / "bin") + os.pathsep + ENV.get("PATH", ""),
        "PYTHONPATH": str(SERVER_DIR),
        "MODELSCOPE_CACHE": r"F:\PBL\.cache\modelscope",
        "TMP": r"F:\PBL\.cache\tmp",
        "TEMP": r"F:\PBL\.cache\tmp",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
)


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def start(name: str, args: list[str], cwd: Path) -> subprocess.Popen | None:
    out = (LOG_DIR / f"{name}.out.log").open("ab")
    err = (LOG_DIR / f"{name}.err.log").open("ab")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [str(PYTHON), *args],
        cwd=str(cwd),
        env=ENV,
        stdout=out,
        stderr=err,
        creationflags=flags,
    )
    print(f"[start] {name} pid={proc.pid}")
    return proc


def main() -> int:
    if not PYTHON.exists():
        print(f"找不到虚拟环境 Python：{PYTHON}", file=sys.stderr)
        return 1
    if not (SERVER_DIR / "data" / ".config.yaml").exists():
        print(f"找不到配置：{SERVER_DIR / 'data' / '.config.yaml'}", file=sys.stderr)
        return 1
    if not (SERVER_DIR / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17" / "model.int8.onnx").exists():
        print("找不到 SherpaASR 模型，请先下载模型", file=sys.stderr)
        return 1

    started: list[dict] = []

    if http_ok("http://127.0.0.1:8010/health"):
        print("[skip] 8010 ASR/TTS API 已在运行")
    else:
        proc = start("api", [str(STAGE2 / "asr_tts_api.py")], STAGE2)
        if proc:
            started.append({"name": "asr_tts_api", "pid": proc.pid})

    if http_ok("http://127.0.0.1:8003/xiaozhi/ota/"):
        print("[skip] 8003 xiaozhi-server 已在运行")
    else:
        proc = start("server", ["app.py"], SERVER_DIR)
        if proc:
            started.append({"name": "xiaozhi_server", "pid": proc.pid})

    if started:
        (LOG_DIR / "pids.json").write_text(
            json.dumps(started, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    for _ in range(20):
        api_ok = http_ok("http://127.0.0.1:8010/health")
        srv_ok = http_ok("http://127.0.0.1:8003/xiaozhi/ota/")
        if api_ok and srv_ok:
            break
        time.sleep(1.5)

    print("\n服务状态：")
    print("  ASR/TTS API:", "OK" if http_ok("http://127.0.0.1:8010/health") else "FAILED（看 stage2/logs/api.err.log）")
    print("  OTA/WS     :", "OK" if http_ok("http://127.0.0.1:8003/xiaozhi/ota/") else "FAILED（看 stage2/logs/server.err.log）")
    print("\n本机地址：")
    print("  Swagger    http://127.0.0.1:8010/docs")
    print("  ASR/TTS    http://127.0.0.1:8010")
    print("  OTA        http://127.0.0.1:8003/xiaozhi/ota/")
    print("  WebSocket  ws://127.0.0.1:8000/xiaozhi/v1/")
    print("\n局域网地址见 stage2/阶段二-接口与部署文档.md（当前 192.168.0.110）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
