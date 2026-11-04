r"""验证原项目 HTTP(OTA) 与 WebSocket 服务是否可连接。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "stage2" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OTA_URL = "http://127.0.0.1:8003/xiaozhi/ota/"
WS_URL = "ws://127.0.0.1:8000/xiaozhi/v1/?device-id=stage2-test&client-id=stage2-test"

result = {"ota": None, "websocket": None}

ota = requests.post(
    OTA_URL,
    headers={
        "device-id": "aa:bb:cc:dd:ee:ff",
        "client-id": "stage2-test",
        "Content-Type": "application/json",
    },
    json={"application": {"version": "1.0.0"}, "board": {"type": "stage2-test"}},
    timeout=15,
)
result["ota"] = {"status": ota.status_code, "body": ota.json()}

hello = {
    "type": "hello",
    "version": 1,
    "transport": "websocket",
    "audio_params": {
        "format": "opus",
        "sample_rate": 24000,
        "channels": 1,
        "frame_duration": 60,
    },
    "features": {},
}
with connect(WS_URL, open_timeout=10, close_timeout=5) as ws:
    ws.send(json.dumps(hello, ensure_ascii=False))
    welcome = ws.recv(timeout=10)
    result["websocket"] = {
        "status": "connected",
        "welcome": json.loads(welcome) if isinstance(welcome, str) else str(welcome),
    }

(OUTPUT_DIR / "verify_service.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))
