r"""一键启动阶段一前端 + 阶段二后端（Windows 本地部署）。

用法（在 F:\PBL\voice-assistant 下）：
    python start_all.py

它会：
1. 启动阶段二 8010 ASR/LLM/TTS + 8000/8003 小智服务（复用 backend/stage2/run_services.py）
2. 启动阶段一 7860 Gradio 前端
3. 健康检查并打印地址

停止：
    阶段二：F:\PBL\voice-assistant\.venv\Scripts\python.exe backend\stage2\stop_services.py
    阶段一：关闭其进程或按 README 的端口方式停止。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> int:
    if not PYTHON.exists():
        print(f"缺少共享虚拟环境：{PYTHON}", file=sys.stderr)
        return 1
    if not (FRONTEND / "app.py").exists():
        print(f"缺少阶段一目录：{FRONTEND}", file=sys.stderr)
        return 1
    if not (BACKEND / "stage2" / "run_services.py").exists():
        print(f"缺少阶段二目录：{BACKEND}", file=sys.stderr)
        return 1

    # 1) 阶段二后端（8010 + 8003 都在才算完整）
    if http_ok("http://127.0.0.1:8010/health") and http_ok("http://127.0.0.1:8003/xiaozhi/ota/"):
        print("[skip] 阶段二后端已在运行")
    else:
        print("[start] 阶段二后端 ...")
        completed = subprocess.run(
            [str(PYTHON), str(BACKEND / "stage2" / "run_services.py")],
            cwd=str(BACKEND),
            timeout=240,
        )
        if completed.returncode != 0:
            print("阶段二启动脚本返回非 0，请查看 backend/stage2/logs/", file=sys.stderr)

    # 2) 阶段一前端
    if http_ok("http://127.0.0.1:7860/"):
        print("[skip] 阶段一 7860 已在运行")
    else:
        print("[start] 阶段一 Gradio 前端 ...")
        out = (LOG_DIR / "frontend.out.log").open("ab")
        err = (LOG_DIR / "frontend.err.log").open("ab")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            [str(PYTHON), "app.py"],
            cwd=str(FRONTEND),
            stdout=out,
            stderr=err,
            creationflags=flags,
        )
        print(f"阶段一 PID={proc.pid}")

    # 3) 健康检查
    for _ in range(30):
        if http_ok("http://127.0.0.1:8010/health") and http_ok("http://127.0.0.1:7860/"):
            break
        time.sleep(1)

    print("\n服务状态：")
    print("  阶段二 ASR/LLM/TTS:", "OK" if http_ok("http://127.0.0.1:8010/health") else "FAILED")
    print("  阶段二 OTA/WS     :", "OK" if http_ok("http://127.0.0.1:8003/xiaozhi/ota/") else "FAILED")
    print("  阶段一 Gradio     :", "OK" if http_ok("http://127.0.0.1:7860/") else "FAILED")
    print("\n打开：")
    print("  http://127.0.0.1:7860          阶段一聊天界面")
    print("  http://127.0.0.1:8010/docs     阶段二 ASR/LLM/TTS 接口文档")
    print("  http://127.0.0.1:8003/xiaozhi/ota/   OTA 接口")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
