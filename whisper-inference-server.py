#!/usr/bin/env python3
"""
Whisper Large v3 Inference Server

FastAPI server providing an OpenAI-compatible API for Whisper speech-to-text.
Supports audio file uploads with automatic language detection.

Endpoints:
    GET  /health                    Liveness probe
    GET  /v1/models                 List available models
    POST /v1/audio/transcriptions   Transcribe audio (OpenAI-compatible)
    GET  /metrics                   Prometheus metrics

Environment:
    MODEL_PATH             Path to model weights (default: /models/whisper-large-v3)
    PORT                   Server port (default: 8080)
    DEVICE                 Device to use: cuda, cpu, or auto (default: auto)
    MLFLOW_TRACKING_URI    MLflow server (default: http://mlflow:5000)
    LOG_LEVEL              Logging level (default: INFO)
"""

import asyncio
import logging
import os
import signal
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from starlette.responses import JSONResponse, PlainTextResponse, Response

# --- Configuration ---
MODEL_PATH = os.environ.get("MODEL_PATH", "/models/whisper-large-v3")
PORT = int(os.environ.get("PORT", "8080"))
DEVICE = os.environ.get("DEVICE", "auto")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MODEL_NAME = "whisper-large-v3"

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
AUDIO_DURATION_PROCESSED = Counter(
    "inference_audio_duration_seconds_total", "Total audio duration processed"
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


def log_to_mlflow(latency: float, audio_duration: float, status: str):
    """Log inference metrics to MLflow (best-effort)."""
    try:
        client = get_mlflow_client()
        if client is None:
            return
        with client.start_run(run_name=f"whisper-inference-{int(time.time())}"):
            client.log_metrics({
                "latency_seconds": latency,
                "audio_duration_seconds": audio_duration,
            })
            client.log_param("status", status)
            client.log_param("model", MODEL_NAME)
    except Exception as e:
        logger.debug("MLflow log failed: %s", e)


# --- Global pipeline ---
pipe = None
resolved_device = None


def resolve_device() -> str:
    if DEVICE == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return DEVICE


def load_model():
    """Load Whisper model and build the ASR pipeline."""
    global pipe, resolved_device
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

    resolved_device = resolve_device()
    torch_dtype = torch.float16 if resolved_device == "cuda" else torch.float32

    logger.info("Loading processor from %s", MODEL_PATH)
    processor = AutoProcessor.from_pretrained(MODEL_PATH)

    logger.info("Loading model on %s (dtype=%s)...", resolved_device, torch_dtype)
    load_start = time.time()

    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch_dtype,
        low_cpu_mem_usage=True,
    )
    model.to(resolved_device)
    model.eval()

    pipe = pipeline(
        "automatic-speech-recognition",
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        torch_dtype=torch_dtype,
        device=resolved_device,
    )

    elapsed = time.time() - load_start
    logger.info("Model loaded in %.1fs on %s", elapsed, resolved_device)

    if torch.cuda.is_available():
        mem = torch.cuda.memory_allocated()
        GPU_MEMORY_USED.set(mem)
        logger.info("GPU memory used: %.1f GB", mem / 1e9)


# --- Pydantic Models ---
class TranscriptionResponse(BaseModel):
    text: str


class VerboseTranscriptionResponse(BaseModel):
    task: str = "transcribe"
    language: str
    duration: float
    text: str


# --- App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield
    logger.info("Shutting down whisper inference server")


app = FastAPI(title="Whisper Large v3 Inference Server", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model": MODEL_NAME,
        "device": resolved_device,
        "gpu_available": torch.cuda.is_available(),
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "openai",
            }
        ],
    }


@app.get("/metrics")
async def metrics():
    if torch.cuda.is_available():
        GPU_MEMORY_USED.set(torch.cuda.memory_allocated())
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def transcribe_audio(file_path: str, language: Optional[str]) -> dict:
    """Run Whisper pipeline on an audio file."""
    generate_kwargs = {}
    if language:
        generate_kwargs["language"] = language

    result = pipe(
        file_path,
        return_timestamps=True,
        generate_kwargs=generate_kwargs,
    )
    return result


@app.post("/v1/audio/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    response_format: Optional[str] = Form("json"),
):
    ACTIVE_REQUESTS.inc()
    start = time.time()
    status = "success"
    tmp_path = None

    try:
        suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            tmp.write(content)

        result = await asyncio.to_thread(transcribe_audio, tmp_path, language)
        text = result.get("text", "").strip()

        latency = time.time() - start

        chunks = result.get("chunks", [])
        audio_duration = 0.0
        if chunks:
            last_chunk = chunks[-1]
            if last_chunk.get("timestamp") and last_chunk["timestamp"][1] is not None:
                audio_duration = last_chunk["timestamp"][1]

        AUDIO_DURATION_PROCESSED.inc(audio_duration)
        REQUEST_COUNT.labels(status="success").inc()
        REQUEST_LATENCY.observe(latency)

        log_to_mlflow(latency, audio_duration, "success")

        if response_format == "text":
            return PlainTextResponse(content=text)
        elif response_format == "verbose_json":
            detected_language = result.get("language", language or "en")
            return JSONResponse(content={
                "task": "transcribe",
                "language": detected_language,
                "duration": audio_duration,
                "text": text,
            })
        else:
            return JSONResponse(content={"text": text})

    except Exception as e:
        status = "error"
        REQUEST_COUNT.labels(status="error").inc()
        latency = time.time() - start
        REQUEST_LATENCY.observe(latency)
        log_to_mlflow(latency, 0.0, "error")
        logger.exception("Transcription error")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.dec()
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def handle_sigterm(*_):
    logger.info("SIGTERM received, initiating graceful shutdown")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    logger.info("Starting whisper inference server on port %d", PORT)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        timeout_keep_alive=300,
    )
    