#!/usr/bin/env python3
"""
Orpheus TTS Inference Server

FastAPI server providing an OpenAI-compatible API for Orpheus TTS
(canopylabs/orpheus-tts-0.1-finetune-prod). Generates speech from text using
a Llama-3B causal LM that produces SNAC audio tokens, then decodes them to
24 kHz 16-bit mono PCM via the SNAC codec.

Endpoints:
    GET  /health                 Liveness probe
    GET  /v1/models              List available models
    POST /v1/audio/speech        Generate speech (returns WAV)
    POST /v1/audio/speech/stream Stream speech (returns raw PCM chunks)
    GET  /metrics                Prometheus metrics

Environment:
    MODEL_PATH             Path to model weights (default: /models/orpheus-tts-0.1-finetune-prod)
    PORT                   Server port (default: 8120)
    DEVICE                 Device to use: cuda, cpu, or auto (default: auto)
    MLFLOW_TRACKING_URI    MLflow server (default: http://mlflow:5000)
    LOG_LEVEL              Logging level (default: INFO)
"""

import asyncio
import io
import json
import logging
import os
import signal
import struct
import sys
import time
import wave
from contextlib import asynccontextmanager
from threading import Thread
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
MODEL_PATH = os.environ.get("MODEL_PATH", "/models/orpheus-3b-0.1-ft")
PORT = int(os.environ.get("PORT", "8120"))
DEVICE = os.environ.get("DEVICE", "auto")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MODEL_NAME = "orpheus-tts-0.1-finetune-prod"

VALID_VOICES = {"tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"}

# Token layout
CODE_TOKEN_OFFSET = 128266
CODE_START_TOKEN = 128257
END_OF_AUDIO_TOKEN = 128258

# SNAC layer sizes per 7-token group
# Layer 0 (coarse):  indices 0
# Layer 1 (mid):     indices 1, 4
# Layer 2 (fine):    indices 2, 3, 5, 6
SNAC_LAYER_INDICES = {
    0: [0],
    1: [1, 4],
    2: [2, 3, 5, 6],
}

SAMPLE_RATE = 24000

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
        with client.start_run(run_name=f"orpheus-tts-{int(time.time())}"):
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
tokenizer = None
snac_model = None
resolved_device = None


def resolve_device() -> str:
    if DEVICE == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return DEVICE


def load_model():
    """Load the Orpheus TTS causal LM and SNAC decoder."""
    global tts_model, tokenizer, snac_model, resolved_device
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from snac import SNAC

    resolved_device = resolve_device()
    torch_dtype = torch.float16 if resolved_device == "cuda" else torch.float32

    logger.info("Loading tokenizer from %s", MODEL_PATH)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

    logger.info("Loading model on %s (dtype=%s)...", resolved_device, torch_dtype)
    load_start = time.time()

    tts_model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch_dtype,
        low_cpu_mem_usage=True,
    )
    tts_model.to(resolved_device)
    tts_model.eval()

    elapsed = time.time() - load_start
    logger.info("TTS model loaded in %.1fs on %s", elapsed, resolved_device)

    logger.info("Loading SNAC decoder (hubertsiuzdak/snac_24khz)...")
    snac_start = time.time()
    snac_model = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").to(resolved_device).eval()
    logger.info("SNAC loaded in %.1fs", time.time() - snac_start)

    if torch.cuda.is_available():
        mem = torch.cuda.memory_allocated()
        GPU_MEMORY_USED.set(mem)
        logger.info("GPU memory used: %.1f GB", mem / 1e9)


# --- Token processing ---

def build_prompt_tokens(text: str, voice: str) -> List[int]:
    """Build the token sequence: start token + prompt tokens + EOT."""
    prompt = f"{voice}: {text}"
    input_ids = tokenizer(prompt, return_tensors="pt").input_ids[0].tolist()
    # Prepend code-start marker, append EOS from tokenizer
    return [CODE_START_TOKEN] + input_ids + [tokenizer.eos_token_id]


def decode_snac_tokens(raw_tokens: List[int]) -> np.ndarray:
    """Decode a list of raw generated token IDs into a PCM waveform via SNAC.

    Filters to only audio code tokens (>= CODE_TOKEN_OFFSET), groups into 7,
    redistributes into 3 SNAC codebook layers, clamps to valid range, then decodes.
    """
    # Filter: keep only audio code tokens
    audio_tokens = [t for t in raw_tokens if t >= CODE_TOKEN_OFFSET]

    n_groups = len(audio_tokens) // 7
    if n_groups == 0:
        return np.array([], dtype=np.int16)

    tokens = audio_tokens[: n_groups * 7]

    codes_0, codes_1, codes_2 = [], [], []
    for g in range(n_groups):
        group = tokens[g * 7: (g + 1) * 7]
        adjusted = []
        for i, t in enumerate(group):
            val = t - CODE_TOKEN_OFFSET - (i * 4096)
            val = max(0, min(val, 4095))  # clamp to valid SNAC codebook range
            adjusted.append(val)
        codes_0.append(adjusted[0])
        codes_1.extend([adjusted[1], adjusted[4]])
        codes_2.extend([adjusted[2], adjusted[3], adjusted[5], adjusted[6]])

    try:
        with torch.no_grad():
            z = snac_model.decode([
                torch.tensor([codes_0], dtype=torch.long, device=resolved_device),
                torch.tensor([codes_1], dtype=torch.long, device=resolved_device),
                torch.tensor([codes_2], dtype=torch.long, device=resolved_device),
            ])
        audio_float = z.squeeze().cpu().numpy()
        audio_int16 = np.clip(audio_float * 32767, -32768, 32767).astype(np.int16)
        return audio_int16
    except RuntimeError as exc:
        logger.error("SNAC decode error (n_groups=%d): %s", n_groups, exc)
        return np.array([], dtype=np.int16)


def pcm_to_wav(pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw PCM int16 samples in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def apply_fade(pcm: np.ndarray, fade_samples: int = 120) -> np.ndarray:
    """Apply a short fade-in/fade-out to avoid clicks at chunk boundaries."""
    if len(pcm) < fade_samples * 2:
        return pcm
    pcm = pcm.astype(np.float32)
    fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    pcm[:fade_samples] *= fade_in
    pcm[-fade_samples:] *= fade_out
    return np.clip(pcm, -32768, 32767).astype(np.int16)


# --- Pydantic Models ---
class SpeechRequest(BaseModel):
    input: str
    voice: str = Field(default="tara")
    response_format: str = Field(default="wav")
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


# --- App ---
def warmup():
    """Run a short generation to pre-compile CUDA kernels."""
    logger.info("Running warmup inference...")
    try:
        t0 = time.time()
        _ = generate_speech("Hello.", "tara")
        logger.info("Warmup complete in %.1fs", time.time() - t0)
    except Exception as e:
        logger.warning("Warmup failed (non-fatal): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    await asyncio.to_thread(warmup)
    yield
    logger.info("Shutting down orpheus tts inference server")


app = FastAPI(title="Orpheus TTS Inference Server", lifespan=lifespan)


@app.get("/health")
async def health():
    gpu_healthy = True
    if resolved_device == "cuda":
        try:
            torch.tensor([1.0], device="cuda")
        except RuntimeError:
            gpu_healthy = False
    status = "healthy" if gpu_healthy else "unhealthy"
    code = 200 if gpu_healthy else 503
    return Response(
        content=json.dumps({
            "status": status,
            "model": MODEL_NAME,
            "device": resolved_device,
            "gpu_available": torch.cuda.is_available(),
            "gpu_healthy": gpu_healthy,
        }),
        status_code=code,
        media_type="application/json",
    )


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "canopylabs",
            }
        ],
    }


@app.get("/metrics")
async def metrics():
    if torch.cuda.is_available():
        GPU_MEMORY_USED.set(torch.cuda.memory_allocated())
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def generate_speech(text: str, voice: str) -> np.ndarray:
    """Generate full speech audio (blocking)."""
    prompt_tokens = build_prompt_tokens(text, voice)
    input_ids = torch.tensor([prompt_tokens], dtype=torch.long, device=resolved_device)

    attention_mask = torch.ones_like(input_ids)
    with torch.no_grad():
        generated = tts_model.generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            max_new_tokens=8192,
            temperature=0.6,
            top_p=0.9,
            repetition_penalty=1.1,
            do_sample=True,
            eos_token_id=END_OF_AUDIO_TOKEN,
            pad_token_id=END_OF_AUDIO_TOKEN,
        )

    # Strip prompt tokens
    new_tokens = generated[0][len(prompt_tokens):].tolist()

    # Remove end-of-audio marker if present
    if new_tokens and new_tokens[-1] == END_OF_AUDIO_TOKEN:
        new_tokens = new_tokens[:-1]

    return decode_snac_tokens(new_tokens)


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
    status = "success"

    try:
        pcm = await asyncio.to_thread(generate_speech, request.input, request.voice)
        wav_bytes = pcm_to_wav(pcm)

        latency = time.time() - start
        audio_duration = len(pcm) / SAMPLE_RATE
        characters = len(request.input)

        TTS_AUDIO_DURATION.inc(audio_duration)
        TTS_CHARACTERS_PROCESSED.inc(characters)
        REQUEST_COUNT.labels(status="success").inc()
        REQUEST_LATENCY.observe(latency)

        log_to_mlflow(latency, audio_duration, characters, "success")

        return Response(content=wav_bytes, media_type="audio/wav")

    except Exception as e:
        status = "error"
        REQUEST_COUNT.labels(status="error").inc()
        latency = time.time() - start
        REQUEST_LATENCY.observe(latency)
        log_to_mlflow(latency, 0.0, len(request.input), "error")
        logger.exception("TTS error")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.dec()


@app.post("/v1/audio/speech/stream")
async def create_speech_stream(request: SpeechRequest):
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
        from transformers import TextIteratorStreamer

        # ──────────────────────────────────────────────────────────────────
        # TTFB instrumentation (added 2026-05-06).
        #
        # We've measured 3–5 s TTFB on direct in-cluster calls and the gap
        # from first byte to last byte is only ~100 ms for ~3 s of audio,
        # which means the entire response is being produced in one burst —
        # no real streaming. Before swapping models or tweaking generation
        # kwargs, we want a hard breakdown of where those 5 s actually go:
        #
        #   t_prompt           build_prompt_tokens + tensor construction
        #   t_thread           spawning the generate() worker thread
        #   t_first_token      first text_piece arriving from the streamer
        #                      (= prefill + first decode step end-to-end)
        #   t_first_21_tokens  accumulating 21 audio tokens (= FIRST_CHUNK_
        #                      GROUPS × 7), the minimum needed for SNAC
        #   snac_decode_ms     SNAC decoder cost on the first chunk
        #
        # Logged once per request right before the first PCM chunk is yielded
        # so we can correlate against the client-observed TTFB.
        # ──────────────────────────────────────────────────────────────────
        t0 = time.time()

        prompt_tokens = build_prompt_tokens(request.input, request.voice)
        input_ids = torch.tensor([prompt_tokens], dtype=torch.long, device=resolved_device)
        attention_mask = torch.ones_like(input_ids)

        t_prompt = time.time()

        # We use a raw token streamer; TextIteratorStreamer works at the token level
        streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=False)

        generation_kwargs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "max_new_tokens": 8192,
            "temperature": 0.6,
            "top_p": 0.9,
            "repetition_penalty": 1.1,
            "do_sample": True,
            "eos_token_id": END_OF_AUDIO_TOKEN,
            "pad_token_id": END_OF_AUDIO_TOKEN,
            "streamer": streamer,
        }

        thread = Thread(target=tts_model.generate, kwargs=generation_kwargs)
        thread.start()

        t_thread = time.time()

        audio_token_buffer: List[int] = []
        first_chunk = True
        # First chunk: 3 groups (21 tokens) for lowest latency
        # Subsequent chunks: 30 groups (210 tokens)
        FIRST_CHUNK_GROUPS = 3
        CHUNK_GROUPS = 30
        total_pcm_samples = 0
        finished = False

        # TTFB instrumentation timestamps (set as we hit each phase).
        t_first_token: Optional[float] = None
        t_first_21_tokens: Optional[float] = None

        for text_piece in streamer:
            if t_first_token is None:
                t_first_token = time.time()
            if finished:
                break

            # Convert streamed text back to token IDs
            piece_ids = tokenizer.encode(text_piece, add_special_tokens=False)

            for tid in piece_ids:
                if tid == END_OF_AUDIO_TOKEN:
                    finished = True
                    break
                if tid >= CODE_TOKEN_OFFSET:
                    audio_token_buffer.append(tid)

            required_groups = FIRST_CHUNK_GROUPS if first_chunk else CHUNK_GROUPS
            required_tokens = required_groups * 7

            while len(audio_token_buffer) >= required_tokens:
                if first_chunk and t_first_21_tokens is None:
                    t_first_21_tokens = time.time()

                chunk_tokens = audio_token_buffer[:required_tokens]
                audio_token_buffer = audio_token_buffer[required_tokens:]

                snac_t0 = time.time()
                pcm_chunk = decode_snac_tokens(chunk_tokens)
                snac_ms = (time.time() - snac_t0) * 1000.0
                pcm_chunk = apply_fade(pcm_chunk)
                total_pcm_samples += len(pcm_chunk)

                if first_chunk:
                    # Single-line breakdown of where TTFB went. Use 0.0 fallbacks
                    # if a phase somehow never fired (shouldn't happen, but keeps
                    # the log line shape stable for downstream parsers).
                    _t_first_token = t_first_token if t_first_token is not None else t_thread
                    _t_first_21 = t_first_21_tokens if t_first_21_tokens is not None else _t_first_token
                    logger.info(
                        "orpheus timings: prompt=%.2fs thread_start=%.2fs "
                        "first_token=%.2fs first_21_tokens=%.2fs "
                        "snac_decode_ms=%.0f total_ttfb=%.2fs chars=%d voice=%s",
                        t_prompt - t0,
                        t_thread - t_prompt,
                        _t_first_token - t_thread,
                        _t_first_21 - _t_first_token,
                        snac_ms,
                        time.time() - t0,
                        len(request.input),
                        request.voice,
                    )

                yield pcm_chunk.tobytes()
                first_chunk = False
                required_groups = CHUNK_GROUPS
                required_tokens = required_groups * 7

        # Flush remaining tokens (must be a full group of 7)
        remainder = (len(audio_token_buffer) // 7) * 7
        if remainder > 0:
            pcm_chunk = decode_snac_tokens(audio_token_buffer[:remainder])
            pcm_chunk = apply_fade(pcm_chunk)
            total_pcm_samples += len(pcm_chunk)
            yield pcm_chunk.tobytes()

        thread.join()

        latency = time.time() - start
        audio_duration = total_pcm_samples / SAMPLE_RATE

        TTS_AUDIO_DURATION.inc(audio_duration)
        TTS_CHARACTERS_PROCESSED.inc(len(request.input))
        REQUEST_COUNT.labels(status="success").inc()
        REQUEST_LATENCY.observe(latency)
        log_to_mlflow(latency, audio_duration, len(request.input), "success")
        ACTIVE_REQUESTS.dec()

    try:
        return StreamingResponse(audio_stream(), media_type="audio/pcm")
    except Exception as e:
        REQUEST_COUNT.labels(status="error").inc()
        latency = time.time() - start
        REQUEST_LATENCY.observe(latency)
        log_to_mlflow(latency, 0.0, len(request.input), "error")
        logger.exception("TTS streaming error")
        ACTIVE_REQUESTS.dec()
        raise HTTPException(status_code=500, detail=str(e))


def handle_sigterm(*_):
    logger.info("SIGTERM received, initiating graceful shutdown")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    logger.info("Starting orpheus tts inference server on port %d", PORT)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        timeout_keep_alive=300,
    )