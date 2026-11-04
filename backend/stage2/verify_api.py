r"""阶段二联调脚本：验证 /asr、/tts 以及 TTS->ASR 回环。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "stage2" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--wav",
        default=str(ROOT / "stage2" / "samples" / "asr_sample.wav"),
        help="用于 ASR 的 WAV/MP3 文件",
    )
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--text", default="今天天气不错，适合出门散步。")
    args = parser.parse_args()

    result = {}
    started = time.perf_counter()

    health = requests.get(f"{args.base}/health", timeout=10)
    health.raise_for_status()
    result["health"] = health.json()

    wav_path = Path(args.wav)
    with wav_path.open("rb") as f:
        asr = requests.post(
            f"{args.base}/asr",
            files={"file": (wav_path.name, f, "audio/wav")},
            timeout=120,
        )
    result["asr_status"] = asr.status_code
    result["asr"] = asr.json()
    asr.raise_for_status()

    tts = requests.post(
        f"{args.base}/tts",
        json={"text": args.text},
        timeout=120,
    )
    tts.raise_for_status()
    tts_file = OUTPUT_DIR / "roundtrip_tts.mp3"
    tts_file.write_bytes(tts.content)
    result["tts_status"] = tts.status_code
    result["tts_bytes"] = len(tts.content)
    result["tts_file"] = str(tts_file)
    result["tts_elapsed_ms"] = tts.headers.get("X-TTS-Elapsed-Ms")

    with tts_file.open("rb") as f:
        roundtrip = requests.post(
            f"{args.base}/asr",
            files={"file": (tts_file.name, f, "audio/mpeg")},
            timeout=120,
        )
    result["roundtrip_status"] = roundtrip.status_code
    result["roundtrip"] = roundtrip.json()
    roundtrip.raise_for_status()

    result["total_elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    (OUTPUT_DIR / "verify_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
