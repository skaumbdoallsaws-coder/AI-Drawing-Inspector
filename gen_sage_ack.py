"""One-off generator for the Phase-2A barge-in instant-acknowledgement audio.

Pre-renders a short Sage line to static/audio/sage_ack.mp3 so the frontend can play
it the instant a barge-in question is submitted (masking the LLM + answer-TTS wait).
Re-run this whenever you want to change the line. The frontend degrades to a visual-
only status if this asset is absent, so generating it is optional.

Usage:  python gen_sage_ack.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "static" / "audio" / "sage_ack.mp3"
ACK_TEXT = "Got it. I'm checking that against this step."
SAGE_VOICE_ID = os.getenv("ELEVENLABS_VOICE_SAGE", "s3TPKV1kjDlVtZbl4Ksh")


def _load_env_key():
    key = os.getenv("ELEVENLABS_API_KEY")
    if key:
        return key
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main():
    key = _load_env_key()
    if not key:
        print("ELEVENLABS_API_KEY not found (env or .env) — skipping. "
              "Frontend will degrade to visual-only ack.")
        return 1
    try:
        from elevenlabs import ElevenLabs
    except Exception as e:
        print(f"elevenlabs package unavailable: {e} — skipping.")
        return 1

    client = ElevenLabs(api_key=key)
    chunks = []
    for chunk in client.text_to_speech.convert(
        voice_id=SAGE_VOICE_ID,
        text=ACK_TEXT,
        model_id="eleven_turbo_v2_5",
        output_format="mp3_44100_128",
    ):
        if chunk:
            chunks.append(chunk)
    audio = b"".join(chunks)
    if not audio:
        print("ElevenLabs returned no audio — skipping.")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(audio)
    print(f"Wrote {OUT} ({len(audio)} bytes) — '{ACK_TEXT}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
