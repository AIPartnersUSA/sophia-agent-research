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
| **Visual evidence** | Returns `visual_url` (page render) and `annotated_url` (cropped/annotated figure), fetched via `/api/v1/asset/{slug}/{filename}` (slug-scoped, auth required). |
| **Feedback loop** | Thumbs up/down on any answer via `interaction_id`. |

### Authentication

Auth is **enforced** (`AUTH_ENABLED=true`). Every endpoint below requires a
bearer token **except** `/health`, `/ready`, `/api/v1/index/status`, and
`/auth/callback`.

```http
Authorization: Bearer <cognito_id_token | DOCUMIND_API_KEY>
```

For the **WebSocket**, pass the token either as the `Authorization` upgrade
header **or** as a `?token=<…>` query parameter (easier for Unity/Xreal clients
that can't set custom upgrade headers).

#### Two kinds of token

| Token | How a request is scoped | When to use |
|-------|-------------------------|-------------|
| **Cognito `id_token`** (per-user JWT, RS256, verified against the pool JWKS) | Forced to the user's own `custom:company_slug`. `admins` may target any company. Upload-only (`uploaders`) accounts are rejected for query/ingest. | A real, attributable user is signed in on the headset. |
| **`DOCUMIND_API_KEY`** (static super-user key) | Admin — may target ANY company by passing `company_slug` in the body. | A shared device/kiosk with no per-user login, or backend/server-to-server. Avoids token-refresh logic. |

#### How to get a Cognito `id_token` (Unity / headless)

The same Cognito user pool as the dashboard:
- Region `us-west-2`, Pool `us-west-2_9uJRszagh`, App client `611t4ftmnppgubnfa5hq5i16b6` (public, no client secret).

**Option A — programmatic login (recommended for Unity, no browser).**
The app client has `USER_PASSWORD_AUTH` enabled, so you can call Cognito's
`InitiateAuth` directly and read `IdToken` from the response:

```http
POST https://cognito-idp.us-west-2.amazonaws.com/
Content-Type: application/x-amz-json-1.1
X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth

{
  "AuthFlow": "USER_PASSWORD_AUTH",
  "ClientId": "611t4ftmnppgubnfa5hq5i16b6",
  "AuthParameters": { "USERNAME": "user@company.com", "PASSWORD": "•••" }
}
```

```json
// Response
{
  "AuthenticationResult": {
    "IdToken": "eyJ…",        // ← send this as the bearer
    "AccessToken": "eyJ…",
    "RefreshToken": "eyJ…",   // ← keep to refresh without re-login
    "ExpiresIn": 3600,        // id_token valid ~1 hour
    "TokenType": "Bearer"
  }
}
```

> First login for a freshly-invited user returns
> `{"ChallengeName":"NEW_PASSWORD_REQUIRED", "Session":"…"}` instead. The user
> must set a permanent password once (do this in the dashboard login page, or
> via `RespondToAuthChallenge` with `ChallengeName=NEW_PASSWORD_REQUIRED`).
> After that, `USER_PASSWORD_AUTH` returns tokens directly.

**Refresh** (before the 1-hour expiry, without asking for the password again):

```http
POST https://cognito-idp.us-west-2.amazonaws.com/
X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth
Content-Type: application/x-amz-json-1.1

{ "AuthFlow": "REFRESH_TOKEN_AUTH", "ClientId": "611t4ftmnppgubnfa5hq5i16b6",
  "AuthParameters": { "REFRESH_TOKEN": "eyJ…" } }
```

**Option B — Hosted UI in a system/embedded browser** (if you prefer the
standard OAuth screen). Open the login URL, then extract `id_token` from the
redirect URL's **hash fragment** (`#id_token=…`):

```
https://documind-dashboard-staging.auth.us-west-2.amazoncognito.com/login?
  client_id=611t4ftmnppgubnfa5hq5i16b6&
  response_type=token&
  scope=openid+profile+email&
  redirect_uri=<your_registered_callback>
```

**Option C — static key.** Skip Cognito entirely: send
`Authorization: Bearer <DOCUMIND_API_KEY>` and include `company_slug` in each
request body. The key lives in the `documind-api-key` Kubernetes secret — ask
the platform team; never ship it inside a distributed app binary.

#### Minimal Unity C# (programmatic login + ask)

```csharp
using UnityEngine;
using UnityEngine.Networking;
using System.Text;
using System.Collections;

public class DocumindClient : MonoBehaviour {
  const string Idp    = "https://cognito-idp.us-west-2.amazonaws.com/";
  const string Client = "611t4ftmnppgubnfa5hq5i16b6";
  const string ApiBase = "https://staging.docu-mind.com/documind-api";
  string idToken;

  IEnumerator Login(string user, string pass) {
    string body = "{\"AuthFlow\":\"USER_PASSWORD_AUTH\",\"ClientId\":\"" + Client +
      "\",\"AuthParameters\":{\"USERNAME\":\"" + user + "\",\"PASSWORD\":\"" + pass + "\"}}";
    using var r = new UnityWebRequest(Idp, "POST");
    r.uploadHandler   = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));
    r.downloadHandler = new DownloadHandlerBuffer();
    r.SetRequestHeader("Content-Type", "application/x-amz-json-1.1");
    r.SetRequestHeader("X-Amz-Target",
      "AWSCognitoIdentityProviderService.InitiateAuth");
    yield return r.SendWebRequest();
    // parse JSON → AuthenticationResult.IdToken (use your JSON lib)
    idToken = ParseIdToken(r.downloadHandler.text);
  }

  IEnumerator Ask(string question, string slug) {
    string body = "{\"question\":" + JsonStr(question) +
      ",\"company_slug\":" + JsonStr(slug) + ",\"max_results\":4}";
    using var r = new UnityWebRequest(ApiBase + "/api/v1/ask", "POST");
    r.uploadHandler   = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));
    r.downloadHandler = new DownloadHandlerBuffer();
    r.SetRequestHeader("Content-Type", "application/json");
    r.SetRequestHeader("Authorization", "Bearer " + idToken);
    yield return r.SendWebRequest();
    Debug.Log(r.downloadHandler.text);   // AskResponse JSON
  }
}
```

> With a user `id_token`, omit `company_slug` (the server forces the caller's
> own). With the static key, include it. `max_results` must be **1–10**.

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
  "visual_url": "https://staging.docu-mind.com/documind-api/api/v1/asset/acme/page_45.png",
  "annotated_url": "https://staging.docu-mind.com/documind-api/api/v1/asset/acme/bbox_45_2.jpg",
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

### GET /documind-api/api/v1/asset/{slug}/{filename}

Fetch a referenced page render or annotated figure. Just GET the exact
`visual_url` / `annotated_url` returned in the answer — they are already
slug-scoped (`/asset/<company_slug>/<file>`). Returns `image/png` or
`image/jpeg`. **Requires auth** (same bearer as `/ask`), and the slug is
authorized against the caller (a user can only fetch their own company's
assets). `st.image`-style clients that can't send headers won't work — fetch
the bytes yourself with the `Authorization` header, then display.

### POST /documind-api/api/v1/feedback

Attach a thumbs up/down rating to a previous answer.

```http
POST /documind-api/api/v1/feedback
Content-Type: application/json
Authorization: Bearer <id_token>

{"interaction_id": "a1b2c3…", "rating": "up", "comment": "spot on"}
```

### POST /documind-api/api/v1/admin/ingest

Manual per-company ingest: sync a company's uploaded PDFs from S3, (re)build its
**isolated** index, and hot-load it. Run after new uploads. `admins`/service may
ingest any company; `users` only their own; upload-only accounts are rejected.

This is **asynchronous** — it returns `202 Accepted` immediately with status
`running` and builds in the background (can take minutes for a large corpus).
Poll the status endpoint until `done` (or `error`). Calling it again while a
build is already running is idempotent (returns the in-flight job).

```http
POST /documind-api/api/v1/admin/ingest
Content-Type: application/json
Authorization: Bearer <id_token>

{"company_slug": "acme"}
```

```json
// 202 Accepted
{"status": "running", "company_slug": "acme", "started_at": "2026-06-08T19:00:00Z",
 "chunks": null, "pages": null, "images": null, "files": [], "already_running": false}
```

### GET /documind-api/api/v1/admin/ingest/status?company_slug=acme

Poll the latest ingest job for a company. Same per-company auth as ingest.
`status` is `running` | `done` | `error` | `none`. While `running`, `files[]`
fills in with per-file `pending|processing|done` so you can show progress; when
`done`, `chunks`/`pages`/`images` are populated.

```http
GET /documind-api/api/v1/admin/ingest/status?company_slug=acme
Authorization: Bearer <id_token>
```

```json
{
  "status": "done", "company_slug": "acme",
  "chunks": 8421, "pages": 612, "images": 233, "elapsed_sec": 74.2,
  "files": [
    {"name": "maintenance_manual.pdf", "status": "done"},
    {"name": "install_guide.pdf", "status": "done"}
  ]
}
```

> After `status: done`, `POST /api/v1/ask {company_slug}` answers from the new
> index. Until a company has been ingested at least once, `/ask` returns
> `409` (`company '…' has not been ingested yet`).

### GET /documind-api/health

Liveness + index stats. `tenants` is a map of the per-company indexes currently
hot in memory; `active_ingests` is how many builds are in flight (the scale-down
job uses it to avoid killing the pod mid-ingest). Unauthenticated.

```json
{
  "status": "ok",
  "index_chunks": 0, "index_pages": 0, "index_images": 0, "ready": false,
  "active_ingests": 0,
  "build_status": "empty",
  "tenants": {
    "acme":   {"chunks": 8421, "pages": 612, "images": 233},
    "globex": {"chunks": 1290, "pages": 88,  "images": 41}
  }
}
```

> `index_chunks`/`ready` describe the legacy **shared** corpus (normally empty
> in the multi-tenant deployment — that's expected). Per-company readiness is
> reflected by an entry under `tenants` and by the ingest status endpoint.

### GET /documind-api/ready

Readiness probe. `200` once the background startup build has finished
(`build_status` is `ready` or `empty`), `503` while still building. Useful as a
health gate before sending traffic. Unauthenticated.

### Documind WebSocket API (Real-Time XR)

**External:** `wss://staging.docu-mind.com/documind-api/api/v1/ws?token=<id_token>`
**In-cluster:** `ws://documind:8502/api/v1/ws`

Each message is JSON with a `type` and a client `id` that is echoed back on the
response for request correlation. Auth + per-company isolation are enforced
exactly as on REST.

```javascript
// token = the id_token from Cognito InitiateAuth (Option A above), or the
// DOCUMIND_API_KEY for a shared device. Unity: build the same URL with the
// token in the query string since WebSocket upgrade headers aren't settable.
const ws = new WebSocket(
  `wss://staging.docu-mind.com/documind-api/api/v1/ws?token=${token}`);
ws.onopen = () => ws.send(JSON.stringify({type: "ping", id: "1"}));
// Auth failure closes the socket with code 4401 before any message.
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
  "visual_url": "…/api/v1/asset/acme/page_45.png",
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
