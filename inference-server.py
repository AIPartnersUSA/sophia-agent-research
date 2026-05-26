#!/usr/bin/env python3
"""
Qwen3-VL-8B Inference Server

FastAPI server providing an OpenAI-compatible API for Qwen3-VL-8B-Instruct.
Supports text, image, and video inputs with INT8 quantization on A10G (24GB).

Endpoints:
    GET  /health                  Liveness probe
    GET  /v1/models               List available models
    POST /v1/chat/completions     Chat completions (streaming + non-streaming)
    GET  /metrics                 Prometheus metrics

Environment:
    MODEL_PATH             Path to model weights (default: /models/Qwen3-VL-8B-Instruct)
    PORT                   Server port (default: 8080)
    QUANTIZATION           Quantization method: int8, fp16 (default: int8)
    MLFLOW_TRACKING_URI    MLflow server (default: http://mlflow:5000)
    LOG_LEVEL              Logging level (default: INFO)
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional, Union

import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Request
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
from transformers import AutoProcessor, BitsAndBytesConfig, TextIteratorStreamer
from threading import Thread

# --- Configuration ---
MODEL_PATH = os.environ.get("MODEL_PATH", "/models/Qwen3-VL-8B-Instruct")
PORT = int(os.environ.get("PORT", "8080"))
QUANTIZATION = os.environ.get("QUANTIZATION", "int8")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MODEL_NAME = "qwen3-vl-8b-instruct"

# --- Micro-batching configuration ---
# When BATCH_ENABLED=1, non-streaming requests with matching generation params
# are coalesced into a single model.generate() call. This dramatically improves
# throughput for ingestion workloads (e.g. visual descriptions) where many
# pages are processed back-to-back with identical params.
BATCH_ENABLED = os.environ.get("BATCH_ENABLED", "1") == "1"
BATCH_MAX_SIZE = int(os.environ.get("BATCH_MAX_SIZE", "8"))
BATCH_WAIT_MS = int(os.environ.get("BATCH_WAIT_MS", "50"))

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
TOKENS_GENERATED = Counter("inference_tokens_generated_total", "Total tokens generated")
TOKENS_PROMPT = Counter("inference_tokens_prompt_total", "Total prompt tokens processed")
GPU_MEMORY_USED = Gauge("inference_gpu_memory_used_bytes", "GPU memory used")
BATCH_SIZE_HIST = Histogram(
    "inference_batch_size",
    "Server-side micro-batch size at generate() time",
    buckets=[1, 2, 3, 4, 6, 8, 12, 16, 24, 32],
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


def log_to_mlflow(latency: float, prompt_tokens: int, completion_tokens: int, status: str):
    """Log inference metrics to MLflow (best-effort)."""
    try:
        client = get_mlflow_client()
        if client is None:
            return
        with client.start_run(run_name=f"inference-{int(time.time())}"):
            client.log_metrics({
                "latency_seconds": latency,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            })
            client.log_param("status", status)
            client.log_param("model", MODEL_NAME)
    except Exception as e:
        logger.debug("MLflow log failed: %s", e)


# --- Global model/processor ---
model = None
processor = None


def load_model():
    """Load model with quantization."""
    global model, processor

    logger.info("Loading processor from %s", MODEL_PATH)
    processor = AutoProcessor.from_pretrained(MODEL_PATH, trust_remote_code=True)
    # Left padding is required for batched causal generation: every row's
    # last token must be aligned at the right edge so model.generate()
    # treats them as the "next" token to predict.
    if hasattr(processor, "tokenizer"):
        processor.tokenizer.padding_side = "left"
        if processor.tokenizer.pad_token_id is None:
            processor.tokenizer.pad_token_id = processor.tokenizer.eos_token_id

    logger.info("Loading model with %s quantization...", QUANTIZATION)
    load_start = time.time()

    logger.info("Importing Qwen3VLForConditionalGeneration...")
    from transformers import Qwen3VLForConditionalGeneration
    logger.info("Import complete, starting from_pretrained (this may take several minutes from PVC)...")

    if QUANTIZATION == "int4":
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
        )
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            MODEL_PATH,
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.float16,
            quantization_config=bnb_config,
        )
    elif QUANTIZATION == "int8":
        bnb_config = BitsAndBytesConfig(load_in_8bit=True)
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            MODEL_PATH,
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.float16,
            quantization_config=bnb_config,
        )
    elif QUANTIZATION == "fp16":
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            MODEL_PATH,
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.float16,
        )
    else:
        raise ValueError(f"Unknown quantization: {QUANTIZATION}")

    model.eval()
    elapsed = time.time() - load_start
    logger.info("Model loaded in %.1fs", elapsed)

    if torch.cuda.is_available():
        mem = torch.cuda.memory_allocated()
        GPU_MEMORY_USED.set(mem)
        logger.info("GPU memory used: %.1f GB", mem / 1e9)


# --- Pydantic Models ---
class ChatMessage(BaseModel):
    role: str
    content: Union[str, list]


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_NAME
    messages: list[ChatMessage]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.8, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2048, ge=1, le=131072)
    stream: bool = False
    stop: Optional[list[str]] = None


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class UsageInfo(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: UsageInfo


def _build_messages(messages: list[ChatMessage]) -> list[dict]:
    """Convert API messages to Qwen3-VL format."""
    result = []
    for m in messages:
        if isinstance(m.content, str):
            result.append({"role": m.role, "content": [{"type": "text", "text": m.content}]})
        else:
            result.append({"role": m.role, "content": m.content})
    return result


# --- App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    global _batch_queue, _batcher_task
    if BATCH_ENABLED:
        _batch_queue = asyncio.Queue()
        _batcher_task = asyncio.create_task(_batcher_loop())
        logger.info(
            "Server-side micro-batcher enabled: max_size=%d wait_ms=%d",
            BATCH_MAX_SIZE, BATCH_WAIT_MS,
        )
    yield
    if _batcher_task is not None:
        # Send shutdown sentinel
        await _batch_queue.put(None)
        try:
            await asyncio.wait_for(_batcher_task, timeout=10.0)
        except asyncio.TimeoutError:
            _batcher_task.cancel()
    logger.info("Shutting down inference server")


app = FastAPI(title="Qwen3-VL-8B Inference Server", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model": MODEL_NAME,
        "quantization": QUANTIZATION,
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
                "owned_by": "local",
            }
        ],
    }


@app.get("/metrics")
async def metrics():
    if torch.cuda.is_available():
        GPU_MEMORY_USED.set(torch.cuda.memory_allocated())
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def generate_completion(messages: list[ChatMessage], params: ChatCompletionRequest) -> tuple[str, int, int]:
    """Generate a non-streaming completion."""
    qwen_messages = _build_messages(messages)

    inputs = processor.apply_chat_template(
        qwen_messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = inputs.to(model.device)
    prompt_tokens = inputs["input_ids"].shape[1]

    with torch.no_grad():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=params.max_tokens,
            temperature=params.temperature if params.temperature > 0 else None,
            top_p=params.top_p,
            do_sample=params.temperature > 0,
            pad_token_id=processor.tokenizer.pad_token_id,
        )

    generated_ids_trimmed = [
        out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs["input_ids"], generated_ids)
    ]
    completion_tokens = len(generated_ids_trimmed[0])
    content = processor.batch_decode(generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]

    return content, prompt_tokens, completion_tokens


def generate_completion_batch(
    items: list["BatchItem"],
) -> list[tuple[str, int, int]]:
    """Generate completions for N requests in a single model.generate() call.

    All items in `items` MUST share the same generation params (max_tokens,
    temperature, top_p) — that's the batcher's job to ensure.

    Returns a list of (content, prompt_tokens, completion_tokens) per item.
    """
    assert len(items) > 0
    params = items[0].params
    conversations = [_build_messages(it.messages) for it in items]

    # Native batched processing: pass a list of conversations.
    inputs = processor.apply_chat_template(
        conversations,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        padding=True,
    )
    inputs = inputs.to(model.device)
    input_ids = inputs["input_ids"]
    batch_size, prompt_len = input_ids.shape
    # Per-row prompt length (excludes left-padding)
    attention_mask = inputs["attention_mask"]
    per_row_prompt_tokens = attention_mask.sum(dim=1).tolist()

    BATCH_SIZE_HIST.observe(batch_size)

    with torch.no_grad():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=params.max_tokens,
            temperature=params.temperature if params.temperature > 0 else None,
            top_p=params.top_p,
            do_sample=params.temperature > 0,
            pad_token_id=processor.tokenizer.pad_token_id,
        )

    # Slice each row by the *padded* prompt_len (left-padded so all prompts
    # end at column prompt_len-1; new tokens start at prompt_len).
    new_tokens = generated_ids[:, prompt_len:]
    decoded = processor.batch_decode(
        new_tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )

    results: list[tuple[str, int, int]] = []
    for i, text in enumerate(decoded):
        # Count completion tokens by stripping trailing pad tokens
        row_new = new_tokens[i]
        pad_id = processor.tokenizer.pad_token_id
        if pad_id is not None:
            non_pad = (row_new != pad_id).sum().item()
        else:
            non_pad = row_new.shape[0]
        results.append((text.strip(), int(per_row_prompt_tokens[i]), int(non_pad)))
    return results


# ---- Micro-batcher infrastructure ----
@dataclass
class BatchItem:
    messages: list[ChatMessage]
    params: ChatCompletionRequest
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())

    def signature(self) -> tuple:
        """Bucket key — items in the same bucket can be batched together.

        Different generation params can't share a single model.generate()
        call, so we group by (max_tokens, temperature, top_p, stop).
        """
        p = self.params
        stop = tuple(p.stop) if p.stop else ()
        return (p.max_tokens, round(p.temperature, 3), round(p.top_p, 3), stop)


_batch_queue: Optional[asyncio.Queue] = None
_batcher_task: Optional[asyncio.Task] = None


async def _batcher_loop():
    """Coalesce queued requests into batches and run them through the model."""
    assert _batch_queue is not None
    while True:
        first: BatchItem = await _batch_queue.get()
        if first is None:  # shutdown sentinel
            return

        batch: list[BatchItem] = [first]
        sig = first.signature()
        deadline = asyncio.get_event_loop().time() + (BATCH_WAIT_MS / 1000.0)

        # Drain compatible items until window closes or batch is full.
        while len(batch) < BATCH_MAX_SIZE:
            timeout = deadline - asyncio.get_event_loop().time()
            if timeout <= 0:
                break
            try:
                nxt: BatchItem = await asyncio.wait_for(_batch_queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                break
            if nxt is None:
                # Shutdown sentinel — finish current batch, then return.
                await _execute_batch(batch)
                return
            if nxt.signature() == sig:
                batch.append(nxt)
            else:
                # Incompatible params — execute current batch first, then
                # restart the window with the new item.
                await _execute_batch(batch)
                batch = [nxt]
                sig = nxt.signature()
                deadline = asyncio.get_event_loop().time() + (BATCH_WAIT_MS / 1000.0)

        await _execute_batch(batch)


async def _execute_batch(batch: list[BatchItem]) -> None:
    try:
        results = await asyncio.to_thread(generate_completion_batch, batch)
        for item, result in zip(batch, results):
            if not item.future.done():
                item.future.set_result(result)
    except Exception as exc:
        logger.exception("Batched generate failed (size=%d): %s", len(batch), exc)
        for item in batch:
            if not item.future.done():
                item.future.set_exception(exc)


async def submit_batched(messages: list[ChatMessage], params: ChatCompletionRequest) -> tuple[str, int, int]:
    assert _batch_queue is not None
    item = BatchItem(messages=messages, params=params)
    await _batch_queue.put(item)
    return await item.future


async def generate_stream(messages: list[ChatMessage], params: ChatCompletionRequest) -> AsyncGenerator[str, None]:
    """Generate a streaming completion."""
    qwen_messages = _build_messages(messages)

    inputs = processor.apply_chat_template(
        qwen_messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = inputs.to(model.device)
    prompt_tokens = inputs["input_ids"].shape[1]

    streamer = TextIteratorStreamer(processor.tokenizer, skip_prompt=True, skip_special_tokens=True)

    generation_kwargs = {
        **inputs,
        "max_new_tokens": params.max_tokens,
        "temperature": params.temperature if params.temperature > 0 else None,
        "top_p": params.top_p,
        "do_sample": params.temperature > 0,
        "streamer": streamer,
        "pad_token_id": processor.tokenizer.pad_token_id,
    }

    thread = Thread(target=model.generate, kwargs=generation_kwargs)
    thread.start()

    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    completion_tokens = 0

    for token_text in streamer:
        completion_tokens += 1
        chunk = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": token_text},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

    final_chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n"
    yield "data: [DONE]\n\n"

    thread.join()

    TOKENS_PROMPT.inc(prompt_tokens)
    TOKENS_GENERATED.inc(completion_tokens)


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    ACTIVE_REQUESTS.inc()
    start = time.time()
    status = "success"

    try:
        if request.stream:
            async def event_stream():
                async for chunk in generate_stream(request.messages, request):
                    yield chunk
            return StreamingResponse(event_stream(), media_type="text/event-stream")

        if BATCH_ENABLED and _batch_queue is not None:
            content, prompt_tokens, completion_tokens = await submit_batched(
                request.messages, request
            )
        else:
            content, prompt_tokens, completion_tokens = await asyncio.to_thread(
                generate_completion, request.messages, request
            )

        latency = time.time() - start

        TOKENS_PROMPT.inc(prompt_tokens)
        TOKENS_GENERATED.inc(completion_tokens)
        REQUEST_COUNT.labels(status="success").inc()
        REQUEST_LATENCY.observe(latency)

        log_to_mlflow(latency, prompt_tokens, completion_tokens, "success")

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model=MODEL_NAME,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
    except Exception as e:
        status = "error"
        REQUEST_COUNT.labels(status="error").inc()
        latency = time.time() - start
        REQUEST_LATENCY.observe(latency)
        log_to_mlflow(latency, 0, 0, "error")
        logger.exception("Inference error")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        ACTIVE_REQUESTS.dec()


def handle_sigterm(*_):
    logger.info("SIGTERM received, initiating graceful shutdown")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    logger.info("Starting inference server on port %d", PORT)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        timeout_keep_alive=300,
    )