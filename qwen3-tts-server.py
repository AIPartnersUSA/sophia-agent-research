#!/usr/bin/env python3
"""
Qwen3-TTS Inference Server

FastAPI server providing an OpenAI-compatible API for Qwen3-TTS
(Qwen/Qwen3-TTS-Flash). Drop-in replacement for the Orpheus TTS server in
the Sophia speech pipeline — same external contract:

Endpoints:
    GET  /health                 Liveness probe
    GET  /v1/models              List available models
    POST /v1/audio/speech        Generate speech (returns WAV)
    POST /v1/audio/speech/stream Stream speech (returns raw PCM chunks)
    GET  /metrics                Prometheus metrics

Environment:
    MODEL_PATH             Path to model weights (default: /models/qwen3-tts-12hz-1.7b-customvoice)
    PORT                   Server port (default: 8121)
    DEVICE                 Device map for Qwen3TTSModel (default: cuda:0)
    DTYPE                  Torch dtype: bfloat16, float16, float32 (default: bfloat16)
    SAMPLE_RATE            Fallback output sample rate hint (default: 24000)
    DEFAULT_LANGUAGE       Default language tag (default: English)
    DEFAULT_VOICE          Default speaker if request omits one (default: Aiden)
    DEFAULT_INSTRUCT       Optional style instruction prepended to every gen
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
from typing import List, Optional

import numpy as np
import torch
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
MODEL_PATH = os.environ.get("MODEL_PATH", "/models/qwen3-tts-12hz-1.7b-customvoice")
PORT = int(os.environ.get("PORT", "8121"))
DEVICE = os.environ.get("DEVICE", "cuda:0")
DTYPE = os.environ.get("DTYPE", "bfloat16")
SAMPLE_RATE = int(os.environ.get("SAMPLE_RATE", "24000"))
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE", "Aiden")
DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "English")
DEFAULT_INSTRUCT = os.environ.get("DEFAULT_INSTRUCT", "")
MODEL_NAME = "qwen3-tts-12hz-1.7b-customvoice"

# Qwen3-TTS CustomVoice 1.7B ships with 9 built-in speakers spanning EN/ZH/JA/KO.
# The exact list is queried from the model after load (see startup) but we keep
# this default for the /v1/models response when the model hasn't loaded yet.
VALID_VOICES = set(
    os.environ.get(
        "VOICES",
        "Aiden,Vivian,Ryan,Serena,Olivia,Noah,Mia,Ethan,Cherry",
    ).split(",")
)

# Streaming chunk sizes (samples). Tuned for ~80 ms initial chunk so the
# voice-relay can start playing before the full clip is generated.
FIRST_CHUNK_SAMPLES = int(SAMPLE_RATE * 0.08)
CHUNK_SAMPLES = int(SAMPLE_RATE * 0.20)

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
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
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
    """Log inference metrics to MLflow (best-effort)."""
    try:
        client = get_mlflow_client()
        if client is None:
            return
        with client.start_run(run_name=f"qwen3-tts-{int(time.time())}"):
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
tts_model = None
sample_rate_runtime = SAMPLE_RATE

# Single-flight gate around generate_speech. The model has a single GPU context
# and is autoregressive — running two synth jobs in parallel via to_thread
# either OOMs or thrashes through context-switch (RTF goes from 1.9 → 4+ with
# 5 concurrent calls, observed end-to-end via voice-relay's word-flush firing
# 4-5 concurrent TTS dispatches per assistant turn). Serializing here lets
# them queue cleanly: first call starts immediately, the rest stream in FIFO
# order, total wall time = N × single-call RTF instead of all-stalled.
# Lazily constructed inside lifespan so it binds to the running event loop.
_synth_lock: Optional[asyncio.Lock] = None
_synth_queue_depth = 0  # number of waiters + active call (advisory, for logs)


def _get_synth_lock() -> asyncio.Lock:
    global _synth_lock
    if _synth_lock is None:
        _synth_lock = asyncio.Lock()
    return _synth_lock


async def _synth_serialized(text: str, voice: str, language: str, instruct: str) -> np.ndarray:
    """Acquire the single-flight lock, then run generate_speech in a thread.

    Logs queue depth on entry so we can see contention in qwen3-tts logs
    (`queue_depth=N waited=X.XXs`). Lock is released as soon as the GPU work
    finishes — we explicitly do NOT hold it across PCM yield to the client,
    so the next phrase can start synthesising while bytes are still flowing
    to the previous caller.
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
                    "qwen3-tts synth gate: queue_depth=%d waited=%.2fs chars=%d voice=%s",
                    depth, waited, len(text), voice,
                )
            return await asyncio.to_thread(
                generate_speech, text, voice, language, instruct,
            )
    finally:
        _synth_queue_depth -= 1


def _resolve_dtype():
    return {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "fp16": torch.float16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }.get(DTYPE.lower(), torch.bfloat16)


def load_model():
    """Load the Qwen3-TTS CustomVoice model via the qwen-tts package.

    The qwen-tts package wraps Qwen3-TTS-Tokenizer-12Hz + the autoregressive
    transformer behind a single `Qwen3TTSModel`. `from_pretrained` accepts
    either an HF repo id or a local snapshot directory.
    """
    global tts_model, sample_rate_runtime, VALID_VOICES
    from qwen_tts import Qwen3TTSModel

    torch_dtype = _resolve_dtype()
    use_flash_attn = "flash_attention_2" if torch.cuda.is_available() else None

    logger.info(
        "Loading Qwen3-TTS from %s on %s (dtype=%s, attn=%s)...",
        MODEL_PATH, DEVICE, DTYPE, use_flash_attn or "default",
    )
    load_start = time.time()

    kwargs = {"device_map": DEVICE, "dtype": torch_dtype}
    if use_flash_attn:
        kwargs["attn_implementation"] = use_flash_attn
    try:
        tts_model = Qwen3TTSModel.from_pretrained(MODEL_PATH, **kwargs)
    except Exception as e:
        # flash-attn may be missing on the image — retry without it.
        logger.warning("Falling back without flash_attention_2: %s", e)
        kwargs.pop("attn_implementation", None)
        tts_model = Qwen3TTSModel.from_pretrained(MODEL_PATH, **kwargs)

    logger.info("Qwen3-TTS loaded in %.1fs", time.time() - load_start)

    # Auto-discover speakers exposed by this checkpoint, fall back to defaults.
    try:
        speakers = tts_model.get_supported_speakers()
        if speakers:
            VALID_VOICES = set(speakers)
            logger.info("Supported speakers: %s", sorted(VALID_VOICES))
    except Exception as e:
        logger.warning("Could not query supported speakers: %s", e)

    if torch.cuda.is_available():
        mem = torch.cuda.memory_allocated()
        GPU_MEMORY_USED.set(mem)
        logger.info("GPU memory used: %.1f GB", mem / 1e9)


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
    """Convert a float waveform in [-1, 1] to int16 PCM."""
    return np.clip(audio_float * 32767.0, -32768, 32767).astype(np.int16)


def apply_fade(pcm: np.ndarray, fade_samples: int = 96) -> np.ndarray:
    """Soft fade-in/out to mask SNAC/Qwen chunk boundary clicks."""
    if pcm.size < 2 * fade_samples:
        return pcm
    fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    pcm = pcm.astype(np.float32)
    pcm[:fade_samples] *= fade_in
    pcm[-fade_samples:] *= fade_out
    return pcm.astype(np.int16)


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="Qwen3-TTS Server", version="1.0.0", lifespan=lifespan)


# --- Schemas ---
class SpeechRequest(BaseModel):
    model: Optional[str] = Field(default=MODEL_NAME)
    input: str = Field(..., description="Text to synthesize")
    voice: str = Field(default=DEFAULT_VOICE, description="Speaker name")
    language: Optional[str] = Field(default=DEFAULT_LANGUAGE,
                                    description="Auto, English, Chinese, …")
    instruct: Optional[str] = Field(default=DEFAULT_INSTRUCT,
                                    description="Free-form style/emotion direction")
    response_format: Optional[str] = Field(default="wav")
    speed: Optional[float] = Field(default=1.0, ge=0.5, le=2.0)


# --- Routes ---

@app.get("/health")
async def health():
    ready = tts_model is not None
    return {
        "status": "healthy" if ready else "loading",
        "model": MODEL_NAME,
        "device": DEVICE,
        "sample_rate": sample_rate_runtime,
        "ready": ready,
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{
            "id": MODEL_NAME,
            "object": "model",
            "voices": sorted(VALID_VOICES),
            "sample_rate": sample_rate_runtime,
        }],
    }


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def generate_speech(text: str, voice: str, language: str, instruct: str) -> np.ndarray:
    """Synchronous full-clip synthesis. Returns int16 PCM at sample_rate_runtime."""
    global sample_rate_runtime
    with torch.no_grad():
        wavs, sr = tts_model.generate_custom_voice(
            text=text,
            language=language,
            speaker=voice,
            instruct=instruct or "",
        )
    sample_rate_runtime = int(sr)
    wav = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
    if hasattr(wav, "detach"):
        wav = wav.detach().cpu().float().numpy()
    wav = np.asarray(wav, dtype=np.float32).squeeze()
    return to_int16(wav)


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
            request.input, request.voice,
            request.language or DEFAULT_LANGUAGE,
            request.instruct or DEFAULT_INSTRUCT,
        )
        wav_bytes = pcm_to_wav(pcm, sample_rate_runtime)

        latency = time.time() - start
        audio_duration = len(pcm) / sample_rate_runtime
        characters = len(request.input)

        TTS_AUDIO_DURATION.inc(audio_duration)
        TTS_CHARACTERS_PROCESSED.inc(characters)
        REQUEST_COUNT.labels(status="success").inc()
        REQUEST_LATENCY.observe(latency)
        log_to_mlflow(latency, audio_duration, characters, "success")

        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
        REQUEST_COUNT.labels(status="error").inc()
        latency = time.time() - start
        REQUEST_LATENCY.observe(latency)
        log_to_mlflow(latency, 0.0, len(request.input), "error")
        logger.exception("TTS error")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.dec()


# Phrase splitter for sub-sentence chunking. Voice-relay already sentence-chunks
# its TTS calls upstream, but a single sentence on this model takes ~10s to
# synthesise on a co-tenant L40S slice (RTF ~1.7), which makes mouth-to-ear
# latency 25-30s end-to-end. Splitting on the cheapest natural boundaries
# (sentence ends, then commas / semicolons / colons) and yielding each phrase's
# audio as soon as it's ready collapses TTFB to first-phrase synth time
# (~1-2s) without waiting for the underlying model to expose token streaming.
# Only kicks in past PHRASE_SPLIT_MIN_CHARS so tiny inputs aren't fragmented.
import re as _re

PHRASE_SPLIT_MIN_CHARS = int(os.getenv("TTS_PHRASE_SPLIT_MIN_CHARS", "80"))
# Hard cap per phrase — past this length, fall back to word-boundary splitting
# even when there's no punctuation, otherwise a long sentence with no commas
# collapses to a single phrase and TTFB tracks full-synth time. Tuned at 120:
# small enough that first-phrase synth is ~1.5s on L40S, large enough that the
# per-call model setup overhead doesn't dominate when we'd rather amortise it.
# (Smaller values trade total wall time for lower TTFB; 55 was too aggressive
# and inflated total RTF from 1.7 → 1.95 on monolithic single-sentence inputs.)
PHRASE_SPLIT_MAX_CHARS = int(os.getenv("TTS_PHRASE_SPLIT_MAX_CHARS", "120"))
_PHRASE_SPLIT_RE = _re.compile(r"(?<=[\.\?!,;:])\s+")


def _word_split(text: str, max_chars: int) -> list[str]:
    """Greedy word-boundary split that respects max_chars per chunk.
    Used as a fallback when a phrase has no internal punctuation."""
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    buf: list[str] = []
    cur = 0
    for word in text.split():
        added = len(word) + (1 if buf else 0)
        if cur + added > max_chars and buf:
            out.append(" ".join(buf))
            buf = [word]
            cur = len(word)
        else:
            buf.append(word)
            cur += added
    if buf:
        out.append(" ".join(buf))
    return out


def _split_phrases(text: str) -> list[str]:
    """Greedy phrase split for streaming. Falls back to single-shot if the
    input is shorter than PHRASE_SPLIT_MIN_CHARS so we don't over-chunk;
    word-splits any phrase exceeding PHRASE_SPLIT_MAX_CHARS so monolithic
    sentences without internal punctuation still stream."""
    text = text.strip()
    if len(text) <= PHRASE_SPLIT_MIN_CHARS:
        return [text]
    parts = [p.strip() for p in _PHRASE_SPLIT_RE.split(text) if p.strip()]
    # Re-coalesce parts shorter than 20 chars into the next one — TTS quality
    # degrades on tiny fragments and the per-call model overhead dominates.
    coalesced: list[str] = []
    for p in parts:
        if coalesced and len(coalesced[-1]) < 20:
            coalesced[-1] = (coalesced[-1] + " " + p).strip()
        else:
            coalesced.append(p)
    # Fallback: word-split any phrase that's still too long. This is what
    # rescues TTFB on single-sentence inputs with no internal commas.
    final: list[str] = []
    for p in (coalesced or [text]):
        final.extend(_word_split(p, PHRASE_SPLIT_MAX_CHARS))
    return final


@app.post("/v1/audio/speech/stream")
async def create_speech_stream(request: SpeechRequest):
    """Stream raw int16 PCM at SAMPLE_RATE.

    The voice-relay expects the same wire-format as Orpheus: raw little-endian
    PCM frames, no WAV header. We synthesize phrase-by-phrase and yield each
    phrase's audio as soon as it's produced, so TTFB tracks first-phrase synth
    time rather than full-input synth time. The previous implementation
    awaited the full clip before yielding anything (TTFB ≈ Total).
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
        try:
            phrases = _split_phrases(request.input)
            language = request.language or DEFAULT_LANGUAGE
            instruct = request.instruct or DEFAULT_INSTRUCT

            t0 = time.time()
            total_samples = 0
            ttfb_logged = False
            # Tail-chunk size for sub-yielding inside a phrase's PCM so the
            # client receives audio in steady ~200ms frames instead of one
            # giant blob per phrase.
            yield_chunk_samples = int(sample_rate_runtime * 0.20)

            for idx, phrase in enumerate(phrases):
                t_phrase = time.time()
                # Serialized via _synth_lock so concurrent streaming requests
                # (voice-relay's word-flush fires N TTS calls per assistant
                # turn) queue cleanly behind each other instead of all
                # stalling on a single GPU context.
                pcm = await _synth_serialized(
                    phrase, request.voice, language, instruct,
                )
                synth_dt = time.time() - t_phrase

                if not ttfb_logged:
                    logger.info(
                        "qwen3-tts timings: phrases=%d first_phrase_synth=%.2fs "
                        "ttfb=%.2fs first_phrase_chars=%d total_chars=%d "
                        "voice=%s lang=%s",
                        len(phrases), synth_dt, time.time() - t0,
                        len(phrase), len(request.input),
                        request.voice, language,
                    )
                    ttfb_logged = True
                else:
                    logger.debug(
                        "qwen3-tts phrase %d/%d synth=%.2fs chars=%d",
                        idx + 1, len(phrases), synth_dt, len(phrase),
                    )

                # Yield this phrase's PCM in ~200ms frames so the client
                # buffers smoothly instead of receiving one large jump.
                offset = 0
                n_phrase = len(pcm)
                while offset < n_phrase:
                    chunk = pcm[offset: offset + yield_chunk_samples]
                    offset += yield_chunk_samples
                    yield apply_fade(chunk).tobytes()
                total_samples += n_phrase

            latency = time.time() - start
            audio_duration = total_samples / sample_rate_runtime
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
            ACTIVE_REQUESTS.dec()

    return StreamingResponse(audio_stream(), media_type="audio/pcm")


def handle_sigterm(*_):
    logger.info("SIGTERM received, initiating graceful shutdown")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    logger.info("Starting qwen3-tts inference server on port %d", PORT)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        timeout_keep_alive=300,
    )