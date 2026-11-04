r"""通过原项目 WebSocket 的文本模拟输入，验证 DeepSeek LLM + EdgeTTS 完整回复链路。

流程：
    hello -> listen(detect, text) -> 接收 stt/tts JSON + Opus 音频 -> 解码为 WAV

说明：这里用 listen.detect 的 text 字段模拟“ASR 后的用户文本”；
ASR 音频识别本身已由 8010 的 /asr 接口单独验证。
"""

from __future__ import annotations

import json
import time
import wave
from pathlib import Path

import opuslib_next
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "stage2" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WS_URL = "ws://127.0.0.1:8000/xiaozhi/v1/?device-id=dialogue-test&client-id=dialogue-test"
USER_TEXT = "请用一句话介绍你自己。"

hello = {
    "type": "hello",
    "version": 1,
    "transport": "websocket",
    "audio_params": {"format": "opus", "sample_rate": 24000, "channels": 1, "frame_duration": 60},
    "features": {},
}

messages: list[dict] = []
opus_packets: list[bytes] = []
reply_parts: list[str] = []
user_echo = ""
deadline = time.time() + 90

with connect(WS_URL, open_timeout=10, close_timeout=5) as ws:
    ws.send(json.dumps(hello, ensure_ascii=False))
    welcome = json.loads(ws.recv(timeout=10))
    print("welcome:", welcome.get("type"), welcome.get("session_id"))

    ws.send(json.dumps({"type": "listen", "state": "detect", "mode": "manual", "text": USER_TEXT}, ensure_ascii=False))

    while time.time() < deadline:
        try:
            item = ws.recv(timeout=15)
        except TimeoutError:
            break
        if isinstance(item, bytes):
            opus_packets.append(item)
            continue
        try:
            msg = json.loads(item)
        except Exception:
            continue
        messages.append(msg)
        if msg.get("type") == "stt":
            user_echo = msg.get("text", "")
        if msg.get("type") == "tts" and msg.get("text"):
            reply_parts.append(msg["text"])
        if msg.get("type") == "tts" and msg.get("state") == "stop":
            break

reply = "".join(reply_parts).strip()
result = {
    "user_text": USER_TEXT,
    "user_echo": user_echo,
    "reply": reply,
    "opus_packets": len(opus_packets),
    "messages": messages,
}

if opus_packets:
    decoder = opuslib_next.Decoder(24000, 1)
    pcm = bytearray()
    for packet in opus_packets:
        try:
            pcm.extend(decoder.decode(packet, 1440))
        except Exception:
            pass
    wav_path = OUTPUT_DIR / "dialogue_reply.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(bytes(pcm))
    result["audio_file"] = str(wav_path)
    result["audio_seconds"] = round(len(pcm) / 2 / 24000, 2)

(OUTPUT_DIR / "dialogue_result.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps({k: v for k, v in result.items() if k != "messages"}, ensure_ascii=False, indent=2))
print("message types:", [f"{m.get('type')}/{m.get('state', '')}" for m in messages])
