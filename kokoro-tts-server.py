#!/usr/bin/env python3
"""
Kokoro-TTS Inference Server

FastAPI server providing an OpenAI-compatible API for Kokoro-82M
(hexgrad/Kokoro-82M). Drop-in replacement for the qwen3-tts / orpheus-tts
servers in the Sophia speech pipeline — same external contract:

Endpoints:
    GET  /health                 Liveness probe
    GET  /v1/models              List available models
    POST /v1/audio/speech        Generate speech (returns WAV)
    POST /v1/audio/speech/stream Stream speech (returns raw PCM chunks)
    GET  /metrics                Prometheus metrics

Why Kokoro vs qwen3-tts:
    qwen3-tts (autoregressive 1.7B) RTF on a sole-tenant L40S is ~1.9, which
    means a 6 s utterance takes ~12 s to synthesise — first-word latency
    11-13 s in the WS pipeline. Kokoro is an 82M-param StyleTTS2-style model
    (text → mel via flow matching, mel → audio via vocoder) with RTF
    0.05-0.1 on the same hardware. ~10-20× faster, fits in <500 MB GPU RAM.
    Apache-2.0 licensed.

Voice catalogue:
    Sophia / voice-relay advertises a hardcoded brand catalogue
    (aiden, dylan, eric, ono_anna, ryan, serena, sohee, uncle_fu, vivian)
    built around the qwen3-tts CustomVoice speaker set. Kokoro ships its
    own `am_*` / `af_*` / `bm_*` / `bf_*` voices that don't share names, so
    we keep voice-relay's wire-level catalogue and translate at this server
    via VOICE_MAP. Voice-relay does not need to change.

Environment:
    PORT                   Server port (default: 8122)
    DEVICE                 'cuda' or 'cpu' (default: cuda if available)
    MODEL_REPO             HF repo id (default: hexgrad/Kokoro-82M)
    MODEL_PATH             Local snapshot dir; overrides MODEL_REPO if set
    SAMPLE_RATE            Output sample rate (default: 24000 — Kokoro native)
    DEFAULT_VOICE          Default speaker if request omits one (default: aiden)
    DEFAULT_LANGUAGE       Default lang code: 'a'=US English, 'b'=UK English,
                           'j'=Japanese, 'z'=Mandarin (default: 'a')
    VOICE_MAP              JSON dict mapping wire-level voice → Kokoro voice
                           (default: built-in aiden→am_michael etc.)
    MLFLOW_TRACKING_URI    MLflow server (default: http://mlflow:5000)
    LOG_LEVEL              Logging level (default: INFO)
"""

import asyncio
import io
import json
import logging
import os
import signal
import sys
import time
import wave
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from starlette.responses import Response

# --- Configuration ---
PORT = int(os.environ.get("PORT", "8122"))
DEVICE = os.environ.get("DEVICE", "cuda")
MODEL_REPO = os.environ.get("MODEL_REPO", "hexgrad/Kokoro-82M")
MODEL_PATH = os.environ.get("MODEL_PATH", "")  # local snapshot; empty = use HF cache
SAMPLE_RATE = int(os.environ.get("SAMPLE_RATE", "24000"))
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE", "aiden")
DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "a")  # 'a' = American English
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MODEL_NAME = "kokoro-82m"

# Wire-level voice → Kokoro voice mapping. Keeps Sophia's hardcoded brand
# names (aiden / dylan / etc.) working without any voice-relay change. Driven
# by env so we can rebrand or swap voices without rebuilding the image.
# Kokoro v1.0 voice list (curated):
#   American Female: af_alloy, af_aoede, af_bella, af_heart, af_jessica,
#                    af_kore, af_nicole, af_nova, af_river, af_sarah, af_sky
#   American Male:   am_adam, am_echo, am_eric, am_fenrir, am_liam,
#                    am_michael, am_onyx, am_puck, am_santa
#   British Female:  bf_alice, bf_emma, bf_isabella, bf_lily
#   British Male:    bm_daniel, bm_fable, bm_george, bm_lewis
DEFAULT_VOICE_MAP = {
    "aiden": "am_michael",      # default — calm American male
    "dylan": "am_adam",
    "eric": "am_eric",
    "ono_anna": "af_nicole",
    "ryan": "am_puck",
    "serena": "af_heart",
    "sohee": "af_sarah",
    "uncle_fu": "bm_george",
    "vivian": "bf_emma",
}
try:
    VOICE_MAP = json.loads(os.environ.get("VOICE_MAP") or "")
    if not isinstance(VOICE_MAP, dict) or not VOICE_MAP:
        raise ValueError("empty/invalid")
except Exception:
    VOICE_MAP = DEFAULT_VOICE_MAP

# Wire-level voices we accept; resolution to Kokoro happens via VOICE_MAP.
# Any voice not in this set returns a 400 — same contract as qwen3-tts.
VALID_VOICES = set(VOICE_MAP.keys())

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# --- Prometheus Metrics ---
REQUEST_COUNT = Counter(
    "inference_requests_total", "Total inference requests", ["status"]
)
REQUEST_LATENCY = Histogram(
    "inference_request_latency_seconds",
    "Request latency in seconds",
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
)
ACTIVE_REQUESTS = Gauge("inference_active_requests", "Currently processing requests")
GPU_MEMORY_USED = Gauge("inference_gpu_memory_used_bytes", "GPU memory used")
TTS_AUDIO_DURATION = Counter(
    "tts_audio_duration_seconds_total", "Total audio duration generated"
)
TTS_CHARACTERS_PROCESSED = Counter(
    "tts_characters_processed_total", "Total characters processed"
)

# --- MLflow Logger ---
_mlflow_client = None


def get_mlflow_client():
    global _mlflow_client
    if _mlflow_client is None:
        try:
            import mlflow
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment("inference-metrics")
            _mlflow_client = mlflow
            logger.info("MLflow connected: %s", MLFLOW_TRACKING_URI)
        except Exception as e:
            logger.warning("MLflow unavailable: %s", e)
    return _mlflow_client


def log_to_mlflow(latency: float, audio_duration: float, characters: int, status: str):
    try:
        client = get_mlflow_client()
        if client is None:
            return
        with client.start_run(run_name=f"kokoro-tts-{int(time.time())}"):
            client.log_metrics({
                "latency_seconds": latency,
                "audio_duration_seconds": audio_duration,
                "characters_processed": characters,
            })
            client.log_param("status", status)
            client.log_param("model", MODEL_NAME)
    except Exception as e:
        logger.debug("MLflow log failed: %s", e)


# --- Global model state ---
# Kokoro exposes a `KPipeline` per language code — they're cheap to construct
# but each loads its own G2P / lexicon, so we cache by lang_code.
_pipelines: dict[str, "object"] = {}

# Single-flight gate around inference. Kokoro is small + fast (RTF ~0.05) so
# concurrent calls actually parallelise reasonably well on a 48 GB L40S, but
# voice-relay's word-flush still fires N concurrent dispatches and we'd
# rather have predictable per-call latency than non-deterministic batching
# behaviour. Same pattern as qwen3-tts. Cheap to lift later if we want true
# concurrent inference (Kokoro is small enough that 4-8 parallel requests
# fit comfortably in VRAM).
_synth_lock: Optional[asyncio.Lock] = None
_synth_queue_depth = 0


def _get_synth_lock() -> asyncio.Lock:
    global _synth_lock
    if _synth_lock is None:
        _synth_lock = asyncio.Lock()
    return _synth_lock


def _resolve_device() -> str:
    if DEVICE.lower() == "cpu":
        return "cpu"
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _get_pipeline(lang_code: str):
    """Return a cached KPipeline for `lang_code`, constructing on first use."""
    if lang_code in _pipelines:
        return _pipelines[lang_code]
    from kokoro import KPipeline
    device = _resolve_device()
    logger.info("Building KPipeline lang=%s device=%s", lang_code, device)
    # KPipeline always calls `hf_hub_download(repo_id=...)` internally and
    # validates that repo_id matches the HF `namespace/name` shape — it
    # cannot take a local filesystem path. We therefore always pass the
    # HF repo id and rely on the HF hub cache (HF_HOME=/models in the
    # deployment) to keep weights local across restarts. MODEL_PATH is
    # accepted as a hint but only used to populate HF_HUB_CACHE below.
    if MODEL_PATH:
        # Point hf_hub at the staged snapshot dir so it can find files
        # without re-downloading. `huggingface_hub` looks up cache via
        # HF_HUB_CACHE; if /models/hub exists with the proper layout the
        # init container created it, otherwise this is a no-op and the
        # package downloads on first call (~10s for the 330 MB model).
        os.environ.setdefault("HF_HUB_CACHE", os.path.join(MODEL_PATH, "hub"))
    pipe = KPipeline(lang_code=lang_code, repo_id=MODEL_REPO, device=device)
    _pipelines[lang_code] = pipe
    if device == "cuda":
        try:
            import torch
            GPU_MEMORY_USED.set(torch.cuda.memory_allocated())
            logger.info(
                "Kokoro loaded; GPU memory used: %.1f MB",
                torch.cuda.memory_allocated() / 1e6,
            )
        except Exception:
            pass
    return pipe


def _warmup():
    """Build the default-language pipeline + run one tiny synth so the first
    real request doesn't pay G2P/lexicon load latency on the hot path."""
    pipe = _get_pipeline(DEFAULT_LANGUAGE)
    voice = VOICE_MAP.get(DEFAULT_VOICE, "am_michael")
    t0 = time.time()
    try:
        for _ in pipe("Hello.", voice=voice, speed=1.0):
            pass
        logger.info("Kokoro warmup complete in %.2fs", time.time() - t0)
    except Exception as exc:
        logger.warning("Kokoro warmup failed (non-fatal): %s", exc)


# --- Audio helpers ---

def pcm_to_wav(pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw PCM int16 samples in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def to_int16(audio_float: np.ndarray) -> np.ndarray:
    return np.clip(audio_float * 32767.0, -32768, 32767).astype(np.int16)


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bind the lock to the running loop, then warm up the model.
    _get_synth_lock()
    _warmup()
    yield


app = FastAPI(title="Kokoro-TTS Server", version="1.0.0", lifespan=lifespan)


# --- Schemas ---
class SpeechRequest(BaseModel):
    model: Optional[str] = Field(default=MODEL_NAME)
    input: str = Field(..., description="Text to synthesize")
    voice: Optional[str] = Field(default=DEFAULT_VOICE)
    language: Optional[str] = Field(default=None, description="Kokoro lang code: a/b/j/z")
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0)
    instruct: Optional[str] = Field(default=None, description="Ignored; kept for parity with qwen3-tts contract")


# --- Routes ---
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model": MODEL_NAME,
        "device": _resolve_device(),
        "voices": sorted(VALID_VOICES),
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{
            "id": MODEL_NAME,
            "object": "model",
            "voices": sorted(VALID_VOICES),
            "sample_rate": SAMPLE_RATE,
        }],
    }


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def generate_speech(text: str, wire_voice: str, lang_code: str, speed: float) -> np.ndarray:
    """Synchronous full-clip synthesis. Returns int16 PCM at SAMPLE_RATE.

    KPipeline yields (graphemes, phonemes, audio) tuples per chunk — Kokoro
    chunks at ~510-token boundaries internally, so a long input may yield
    multiple segments. We concatenate them here for the non-streaming path.
    """
    kokoro_voice = VOICE_MAP.get(wire_voice, wire_voice)
    pipe = _get_pipeline(lang_code)
    chunks: list[np.ndarray] = []
    for _, _, audio in pipe(text, voice=kokoro_voice, speed=speed):
        if audio is None:
            continue
        # Kokoro returns either torch tensors or numpy float arrays in [-1, 1]
        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().float().numpy()
        chunks.append(np.asarray(audio, dtype=np.float32).squeeze())
    if not chunks:
        return np.zeros(0, dtype=np.int16)
    waveform = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    return to_int16(waveform)


async def _synth_serialized(text: str, wire_voice: str, lang_code: str, speed: float) -> np.ndarray:
    """Serialised synth — see qwen3-tts-server._synth_serialized for rationale.

    Kokoro is fast enough that contention is rarely visible (RTF ~0.05 → 6 s
    of audio synthesises in ~300 ms), but voice-relay still fires concurrent
    dispatches per assistant turn. Serialisation keeps p99 stable.
    """
    global _synth_queue_depth
    lock = _get_synth_lock()
    _synth_queue_depth += 1
    depth = _synth_queue_depth
    t_wait = time.time()
    try:
        async with lock:
            waited = time.time() - t_wait
            if depth > 1 or waited > 0.05:
                logger.info(
                    "kokoro synth gate: queue_depth=%d waited=%.2fs chars=%d voice=%s",
                    depth, waited, len(text), wire_voice,
                )
            return await asyncio.to_thread(
                generate_speech, text, wire_voice, lang_code, speed,
            )
    finally:
        _synth_queue_depth -= 1


@app.post("/v1/audio/speech")
async def create_speech(request: SpeechRequest):
    if request.voice not in VALID_VOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid voice '{request.voice}'. Valid voices: {sorted(VALID_VOICES)}",
        )
    if not request.input.strip():
        raise HTTPException(status_code=400, detail="Input text must not be empty")

    ACTIVE_REQUESTS.inc()
    start = time.time()

    try:
        pcm = await _synth_serialized(
            request.input,
            request.voice,
            request.language or DEFAULT_LANGUAGE,
            request.speed or 1.0,
        )
        wav_bytes = pcm_to_wav(pcm, SAMPLE_RATE)

        latency = time.time() - start
        audio_duration = len(pcm) / SAMPLE_RATE
        characters = len(request.input)

        TTS_AUDIO_DURATION.inc(audio_duration)
        TTS_CHARACTERS_PROCESSED.inc(characters)
        REQUEST_COUNT.labels(status="success").inc()
        REQUEST_LATENCY.observe(latency)
        log_to_mlflow(latency, audio_duration, characters, "success")

        return Response(content=wav_bytes, media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(status="error").inc()
        REQUEST_LATENCY.observe(time.time() - start)
        log_to_mlflow(time.time() - start, 0.0, len(request.input), "error")
        logger.exception("TTS error")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.dec()


@app.post("/v1/audio/speech/stream")
async def create_speech_stream(request: SpeechRequest):
    """Stream raw int16 PCM at SAMPLE_RATE.

    Kokoro's KPipeline naturally yields per-segment audio as it's generated,
    so we can pipe each segment to the wire as soon as it's ready. For short
    inputs that fit in one segment, TTFB ≈ full-synth time (~300 ms for a
    typical 6 s utterance) — still ~30× faster than qwen3-tts. For longer
    multi-segment inputs the first segment lands in <300 ms.
    """
    if request.voice not in VALID_VOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid voice '{request.voice}'. Valid voices: {sorted(VALID_VOICES)}",
        )
    if not request.input.strip():
        raise HTTPException(status_code=400, detail="Input text must not be empty")

    ACTIVE_REQUESTS.inc()
    start = time.time()

    async def audio_stream():
        global _synth_queue_depth
        try:
            kokoro_voice = VOICE_MAP.get(request.voice, request.voice)
            lang_code = request.language or DEFAULT_LANGUAGE
            speed = request.speed or 1.0
            pipe = _get_pipeline(lang_code)

            yield_chunk_samples = int(SAMPLE_RATE * 0.20)
            ttfb_logged = False
            t0 = time.time()
            total_samples = 0

            # Acquire the synth lock for the full streaming generation. This
            # blocks any other request from starting on the GPU until we
            # finish, matching qwen3-tts behaviour. Kokoro is fast enough
            # this is barely visible.
            lock = _get_synth_lock()
            _synth_queue_depth += 1
            depth = _synth_queue_depth
            t_wait = time.time()
            async with lock:
                waited = time.time() - t_wait
                if depth > 1 or waited > 0.05:
                    logger.info(
                        "kokoro synth gate (stream): queue_depth=%d waited=%.2fs chars=%d voice=%s",
                        depth, waited, len(request.input), request.voice,
                    )

                # KPipeline is a sync generator. Iterate in a thread so we
                # don't block the event loop, but we still need to bridge
                # back to the async stream — easiest: collect each segment,
                # then yield + await sleep(0) to release. For Kokoro's chunk
                # cadence this is fine; if we ever needed true sample-level
                # streaming we'd switch to anyio.from_thread.
                def _generate():
                    return list(pipe(request.input, voice=kokoro_voice, speed=speed))

                segments = await asyncio.to_thread(_generate)

                for seg_idx, item in enumerate(segments):
                    # Each item is (graphemes, phonemes, audio)
                    audio = item[2] if len(item) >= 3 else None
                    if audio is None:
                        continue
                    if hasattr(audio, "detach"):
                        audio = audio.detach().cpu().float().numpy()
                    audio = np.asarray(audio, dtype=np.float32).squeeze()
                    pcm = to_int16(audio)

                    if not ttfb_logged:
                        logger.info(
                            "kokoro-tts timings: segments=%d first_synth=%.3fs "
                            "ttfb=%.3fs first_chars=%d total_chars=%d voice=%s lang=%s",
                            len(segments), time.time() - t0, time.time() - t0,
                            len(item[0]) if item[0] else 0, len(request.input),
                            request.voice, lang_code,
                        )
                        ttfb_logged = True

                    # Frame each segment in ~200 ms PCM chunks for smooth
                    # client buffering — same shape as qwen3-tts-server.
                    offset = 0
                    n = len(pcm)
                    while offset < n:
                        chunk = pcm[offset: offset + yield_chunk_samples]
                        offset += yield_chunk_samples
                        yield chunk.tobytes()
                    total_samples += n

            latency = time.time() - start
            audio_duration = total_samples / SAMPLE_RATE
            TTS_AUDIO_DURATION.inc(audio_duration)
            TTS_CHARACTERS_PROCESSED.inc(len(request.input))
            REQUEST_COUNT.labels(status="success").inc()
            REQUEST_LATENCY.observe(latency)
            log_to_mlflow(latency, audio_duration, len(request.input), "success")
        except Exception:
            REQUEST_COUNT.labels(status="error").inc()
            latency = time.time() - start
            REQUEST_LATENCY.observe(latency)
            log_to_mlflow(latency, 0.0, len(request.input), "error")
            logger.exception("TTS streaming error")
            raise
        finally:
            _synth_queue_depth -= 1
            ACTIVE_REQUESTS.dec()

    return StreamingResponse(audio_stream(), media_type="audio/pcm")


def handle_sigterm(*_):
    logger.info("SIGTERM received, initiating graceful shutdown")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    logger.info("Starting kokoro-tts inference server on port %d", PORT)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        timeout_keep_alive=300,
    )