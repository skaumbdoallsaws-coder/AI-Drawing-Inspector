# Local STT: faster-whisper Implementation Plan
**Status: IMPLEMENTED — local STT on CPU (int8), API fallback active**
**Date: 2026-03-27 (implemented 2026-03-28)**

## Blocker
- Current server runtime is Python 3.14
- ctranslate2 wheels currently go through 3.13 only
- Therefore local faster-whisper is blocked on this interpreter choice
- The existing Python 3.13 on this machine is a Windows Store install (Access Denied from WindowsApps path) — NOT usable for venv creation

**Resolution: Install a standard (non-Store) Python 3.13 interpreter from python.org, then create a fresh server venv on 3.13 and reinstall all server dependencies there.**

Do NOT wait for wheels. Do NOT build ctranslate2 from source.

## Changes (when unblocked)

### requirements.txt
```
faster-whisper>=1.1.0     # Local STT via CTranslate2
openai                    # Required for API fallback (if not already listed)
```
Note: `openai` may already be in requirements.txt — verify before adding a duplicate. The fallback path depends on it.

### server.py

**Add imports at top of server.py (these are NOT currently imported):**
```python
import threading
import io
import asyncio
import openai  # for API fallback
# torch: use lazy import inside _get_whisper_model() to avoid hard dependency

_whisper_model = None
_whisper_lock = threading.Lock()

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model
        from faster_whisper import WhisperModel
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        model_size = os.getenv("WHISPER_MODEL_SIZE", "base.en")
        compute_type = "float16" if device == "cuda" else "int8"
        logger.info(f"Loading faster-whisper model '{model_size}' on {device} ({compute_type})...")
        _whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("faster-whisper model loaded successfully")
        return _whisper_model
```

**Replace voice_transcribe endpoint (line 3908):**
```python
@app.post("/api/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=422, detail="Audio file is empty")
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds 25MB limit")

    # Force API mode if configured
    if os.getenv("STT_BACKEND") == "api":
        return await _fallback_openai_transcribe(audio_bytes, audio.filename)

    try:
        model = _get_whisper_model()
        audio_file = io.BytesIO(audio_bytes)

        def _transcribe():
            segments, info = model.transcribe(
                audio_file,
                beam_size=1,       # Low beam for latency-first barge-in
                language="en",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            text = " ".join(segment.text.strip() for segment in segments)
            # Retry without VAD if empty
            if not text.strip():
                audio_file.seek(0)
                segments2, _ = model.transcribe(audio_file, beam_size=1, language="en", vad_filter=False)
                text = " ".join(s.text.strip() for s in segments2)
            return text

        text = await asyncio.to_thread(_transcribe)
        text = text.strip()

        if not text:
            raise HTTPException(status_code=422, detail="No speech detected in audio")

        logger.info(f"Whisper transcription (local): {len(audio_bytes)} bytes -> {len(text)} chars")
        return {"text": text}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Local transcription error: {e}")
        return await _fallback_openai_transcribe(audio_bytes, audio.filename)
```

**Add fallback function:**
```python
_whisper_fallback_count = 0

async def _fallback_openai_transcribe(audio_bytes, filename=None):
    global _whisper_fallback_count
    _whisper_fallback_count += 1
    if _whisper_fallback_count == 1:
        logger.warning("Local STT failed — falling back to OpenAI Whisper API")
    elif _whisper_fallback_count == 5:
        logger.error("Local STT has failed 5 times — check faster-whisper installation")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Local STT failed and no OPENAI_API_KEY for fallback")

    try:
        client = openai.OpenAI(api_key=api_key)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename or "recording.webm"
        transcript = await asyncio.to_thread(
            client.audio.transcriptions.create,
            model="whisper-1", file=audio_file, response_format="text",
        )
        return {"text": transcript.strip()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {str(e)}")
```

## Codex Review Findings (all addressed in plan above)

1. **Python 3.14 blocker** — ctranslate2 wheels not available yet
2. **beam_size=1** — lowered from 5 for latency-first barge-in
3. **Fallback with circuit breaker** — counts failures, escalates logging at 5 failures
4. **No-VAD retry** — if VAD returns empty, retry with vad_filter=False before 422
5. **base.en configurable** — via WHISPER_MODEL_SIZE env var, ready for small.en upgrade
6. **Single worker assumption** — documented, acceptable for base.en (150MB)

## GPU Memory Budget
- SolidWorks: 1-3 GB
- YOLO: ~300 MB
- faster-whisper base.en: ~150 MB
- Total baseline: ~4.5 GB / 12 GB available

## Frontend Changes
None. Same endpoint, same request format, same response format.
