## Documind RAG Agent — Per-Company Document Q&A (Direct Access + WebSocket)

Documind is the dedicated multimodal RAG agent that replaces the old Sophia
document pipeline. It runs on its own dedicated GPU node (`g6.12xlarge`, 4× L4)
and serves answers grounded in a customer's own uploaded technical PDFs, with
page renders, annotated figures, evidence citations, and optional voice in/out.

XR/Unity clients can talk to Documind two ways, both bypassing
Supervisor/Kafka for low latency:

- **REST** at `/documind-api/` (request/response — simplest to integrate)
- **WebSocket** at `/documind-api/api/v1/ws` (bidirectional, for streaming voice
  + camera-frame turns without re-paying TLS/HTTP per question)

In-cluster the service is `documind:8502` (FastAPI/REST + WS) and
`documind:8501` (Streamlit query UI under `/documind`).

### Key features

| Feature | Detail |
|---------|--------|
| **Per-company (multi-tenant) RAG isolation** | Each customer (`company_slug`) has its own corpus, vector index, and namespace. A query NEVER spans tenants — answers come only from that company's ingested documents. |
| **Manual ingest** | An admin (or the company's own `users`) triggers ingest of that company's uploaded PDFs from S3 into an isolated index. Ingest is manual for now (run after new uploads). |
| **Cognito JWT auth** | Same identity as the dashboard. Pass a Cognito `id_token` (or the `DOCUMIND_API_KEY` super-user key). `admins`/service key may target any company; `users` are forced to their own `custom:company_slug`; upload-only accounts are rejected for query/ingest. |
| **Text Q&A** (`/ask`) | History-aware retrieval + chain-of-thought answering, with evidence citations (source PDF + page + score). |
| **Look-and-ask** (`/look-and-ask`) | Voice in (base64 audio → self-hosted Whisper) + optional camera frame, voice out (TTS) by default. |
| **Image grounding** | Send a base64 camera frame; answers can reference what's in view, with an annotated bounding-box image returned. |
| **OCR + vision** | DeepSeek-OCR + Qwen3-VL-8B for figures/diagrams in manuals. |
| **Visual evidence** | Returns `visual_url` (page render) and `annotated_url` (cropped/annotated figure), fetched via `/api/v1/asset/{filename}`. |
| **Feedback loop** | Thumbs up/down on any answer via `interaction_id`. |

### Authentication

```http
Authorization: Bearer <cognito_id_token | DOCUMIND_API_KEY>
```

For the WebSocket, pass the token either as the `Authorization` upgrade header
**or** as a `?token=<…>` query parameter (easier for Unity/Xreal clients that
can't set custom upgrade headers).

### POST /documind-api/api/v1/ask

Ask a text question against a company's isolated index. Optionally attach a
camera frame and prior conversation turns.

```http
POST /documind-api/api/v1/ask
Content-Type: application/json
Authorization: Bearer <id_token>

{
  "question": "What is the torque spec for the main bearing bolts?",
  "company_slug": "acme",
  "image_b64": "<optional base64 JPG/PNG of the user's view>",
  "max_results": 4,
  "history": [
    {"role": "user", "content": "Which manual covers the S7-1500?"},
    {"role": "assistant", "content": "The Siemens S7-1500 system manual."}
  ],
  "show_thinking": false,
  "tts": false
}
```

> `company_slug` is optional for `admins`/service (omit = legacy shared corpus).
> For `users` it is forced to their own company; a mismatching slug is rejected
> (no cross-tenant access).

**Response (`AskResponse`):**
```json
{
  "interaction_id": "a1b2c3…",
  "transcribed_question": null,
  "answer": "The torque specification for the main bearing bolts is 85 Nm ± 5 Nm…",
  "evidence": [
    {"source": "maintenance_manual.pdf", "page": 45, "score": 0.91,
     "preview": "Tighten the main bearing bolts to 85 Nm…", "shard": "manuals"}
  ],
  "visual_url": "https://staging.docu-mind.com/documind-api/api/v1/asset/page_45.png",
  "annotated_url": "https://staging.docu-mind.com/documind-api/api/v1/asset/bbox_45_2.jpg",
  "box_normalized": [120, 340, 540, 600],
  "image_grounded": false,
  "route": "manual_qa",
  "latency_ms": 1840,
  "thinking": null,
  "chat_rewrite": "torque spec main bearing bolts",
  "answer_audio_b64": null,
  "answer_audio_format": null
}
```

### POST /documind-api/api/v1/look-and-ask

Voice + optional camera frame. The server transcribes the audio (self-hosted
Whisper), runs the same RAG pipeline, and (by default) returns the answer as
synthesized speech.

```http
POST /documind-api/api/v1/look-and-ask
Content-Type: application/json
Authorization: Bearer <id_token>

{
  "audio_b64": "<base64 wav/mp3/m4a/webm/ogg/flac>",
  "audio_format": "wav",
  "company_slug": "acme",
  "image_b64": "<optional base64 camera frame>",
  "max_results": 4,
  "tts": true
}
```

Response is the same `AskResponse`, with `transcribed_question` set and
`answer_audio_b64` populated when `tts:true`.

### GET /documind-api/api/v1/asset/{filename}

Fetch a referenced page render or annotated figure (`visual_url` /
`annotated_url`). Returns `image/png` or `image/jpeg`. Requires auth.

### POST /documind-api/api/v1/feedback

Attach a thumbs up/down rating to a previous answer.

```http
POST /documind-api/api/v1/feedback
Content-Type: application/json
Authorization: Bearer <id_token>

{"interaction_id": "a1b2c3…", "rating": "up", "note": "spot on"}
```

### POST /documind-api/api/v1/admin/ingest

Manual per-company ingest: sync a company's uploaded PDFs from S3, (re)build its
**isolated** index, and hot-load it. Run after new uploads. `admins`/service may
ingest any company; `users` only their own; upload-only accounts are rejected.

```http
POST /documind-api/api/v1/admin/ingest
Content-Type: application/json
Authorization: Bearer <id_token>

{"company_slug": "acme"}
```

```json
{"status": "ok", "company_slug": "acme", "chunks": 8421,
 "pages": 612, "images": 233, "elapsed_sec": 74.2}
```

### GET /documind-api/health

Liveness + index stats, including which per-company tenants are currently hot in
memory.

```json
{
  "status": "ok",
  "index_chunks": 0, "index_pages": 0, "index_images": 0, "ready": false,
  "tenants": ["acme", "globex"]
}
```

### Documind WebSocket API (Real-Time XR)

**External:** `wss://staging.docu-mind.com/documind-api/api/v1/ws?token=<id_token>`
**In-cluster:** `ws://documind:8502/api/v1/ws`

Each message is JSON with a `type` and a client `id` that is echoed back on the
response for request correlation. Auth + per-company isolation are enforced
exactly as on REST.

```javascript
const token = localStorage.getItem("cognitoIdToken");      // dashboard user
const ws = new WebSocket(
  `wss://staging.docu-mind.com/documind-api/api/v1/ws?token=${token}`);
ws.onopen = () => ws.send(JSON.stringify({type: "ping", id: "1"}));
```

#### Ping / Pong

```json
// → {"type": "ping", "id": "1"}
// ← {"type": "pong", "id": "1"}
```

#### Ask (text Q&A, optional camera frame)

```json
// → Send
{
  "type": "ask",
  "id": "a1",
  "question": "What is the torque spec for the main bearing?",
  "company_slug": "acme",
  "image_b64": "<optional base64 camera frame>",
  "max_results": 4,
  "show_thinking": false,
  "tts": false
}

// ← Receive (full AskResponse fields, plus type/id)
{
  "type": "ask_result",
  "id": "a1",
  "interaction_id": "…",
  "answer": "The torque specification is 85 Nm ± 5 Nm…",
  "evidence": [{"source": "manual.pdf", "page": 45, "score": 0.91, "preview": "…"}],
  "visual_url": "…/api/v1/asset/page_45.png",
  "route": "manual_qa",
  "latency_ms": 1720
}
```

#### Look-and-ask (voice + optional camera frame)

```json
// → Send
{
  "type": "look-and-ask",
  "id": "v1",
  "audio_b64": "<base64 audio>",
  "audio_format": "wav",
  "company_slug": "acme",
  "image_b64": "<optional camera frame>",
  "tts": true
}

// ← Receive
{
  "type": "look_and_ask_result",
  "id": "v1",
  "transcribed_question": "what is the operating pressure",
  "answer": "The operating pressure is 6 bar…",
  "answer_audio_b64": "<base64 mp3>",
  "answer_audio_format": "mp3",
  "evidence": [ … ]
}
```

#### Error handling

Errors come back on the same socket, correlated by `id`:

```json
{"type": "error", "id": "a1", "error": "company 'acme' has not been ingested yet; run POST /api/v1/admin/ingest first"}
{"type": "error", "id": "v1", "error": "transcription empty"}
{"type": "error", "id": "a1", "error": "not allowed to access another company's data"}
```

A failed auth closes the socket with code `4401` before `accept`.

---
