# livekit_architectur_ec2.md — end-to-end architecture of the EC2 deployment

How the Sophia voice agent actually works on the shared EC2 (3.227.63.49). Covers both clients (browser + XREAL glasses) end-to-end. Read this when you need to explain the system, debug an unexpected behavior, or onboard someone.

Audience: anyone who needs to understand HOW the deployment works, not just operate it. For "how to RUN it", see `mvp_deployment_shared_ec2.md`. For "how to TAKE IT TO PRODUCTION", see `HANDOFF.md` + `production_deployment.md`.

---

## TL;DR

A voice agent (Sophia) lives in 3 docker containers + a Next.js process on a shared g5.2xlarge EC2 in us-east-1. Two clients — a browser at `http://3.227.63.49:3000` and an Android APK on XREAL Beam Pro — both talk to the same SFU on the EC2 over WebRTC. The agent worker on EC2 reaches inference services (Whisper, Qwen3-VL, Kokoro TTS, sophia-spatial-ai RAG) on an EKS cluster in us-west-2 via kubectl port-forwards. The whole loop (mic → STT → RAG → LLM → TTS → speaker) takes ~2-3 seconds round trip.

The architecture is a vanilla LiveKit Agents deployment with one wrinkle: cross-region access to inference services. Everything else is by-the-book.

---

## 30-second elevator pitch

The user speaks. Their device captures the mic and sends it via WebRTC (UDP) to a SelectiveForwarding Unit (SFU) called `livekit-server`. The SFU forwards the audio to a Python worker called `agent-worker` that subscribed to the user's audio track. The worker passes the audio to Whisper for STT, retrieves relevant manual chunks from sophia-spatial-ai (RAG), sends `[chunks + question]` to Qwen3-VL for an answer, sends the answer text to Kokoro for TTS, publishes the resulting audio back through the SFU, the user's device subscribes to it and plays it through speakers.

The browser and glasses paths look identical except for: (1) which token-mint endpoint they hit to get a LiveKit JWT, (2) how they render UI updates (browser = React DOM, glasses = world-space AR canvas).

---

## Bird's-eye view

```
                     INTERNET (public)
                          │
       ┌──────────────────┼────────────────────────┐
       │                  │                        │
  ┌────┴─────┐      ┌─────┴─────┐           ┌─────┴──────┐
  │ Browser  │      │  XREAL    │           │   Future   │
  │ (Chrome) │      │  Beam Pro │           │  clients   │
  │          │      │  + glasses│           │            │
  └────┬─────┘      └─────┬─────┘           └────────────┘
       │ HTTP             │ HTTP
       │ WS/UDP           │ WS/UDP
       │                  │
       └────────┬─────────┘
                │
                ▼
     ┌──────────────────────────────────────────────────────┐
     │  EC2: 3.227.63.49 (g5.2xlarge, us-east-1)           │
     │  /workspace/avinash/sophia/                          │
     │                                                       │
     │  ┌─────────────────┐      ┌──────────────────┐      │
     │  │ Next.js         │      │ token-mint       │      │
     │  │ frontend        │      │ (FastAPI)        │      │
     │  │ :3000           │      │ :8001            │      │
     │  │ (npm start)     │      │ (X-API-Key auth) │      │
     │  └─────────────────┘      └──────────────────┘      │
     │                                                       │
     │  ┌─────────────────┐      ┌──────────────────┐      │
     │  │ livekit-server  │      │ agent-worker     │      │
     │  │ (SFU)           │◄────►│ (Python)         │      │
     │  │ :7880 WS        │      │ host network     │      │
     │  │ :7881 TCP       │      │ registers w/ SFU │      │
     │  │ :50000-60000 UDP│      │ at localhost:7880│      │
     │  │ host network    │      │                  │      │
     │  └─────────────────┘      └────────┬─────────┘      │
     │                                    │                 │
     │                          kubectl port-forward        │
     │                          (cross-region, via EKS API) │
     └────────────────────────────────────┼─────────────────┘
                                          │
                                          ▼ (us-west-2)
     ┌────────────────────────────────────────────────────┐
     │  EKS cluster spatial-ai-staging (us-west-2)        │
     │  namespace: multi-agent                            │
     │                                                     │
     │  ┌──────────────┐  ┌──────────────┐               │
     │  │ whisper      │  │ qwen3-vl     │               │
     │  │ -inference   │  │ -inference   │               │
     │  │ :8080        │  │ :8080        │               │
     │  │ (STT)        │  │ (LLM, vision)│               │
     │  └──────────────┘  └──────────────┘               │
     │                                                     │
     │  ┌──────────────┐  ┌──────────────┐               │
     │  │ kokoro-tts   │  │ sophia       │               │
     │  │ :8122        │  │ -spatial-ai  │               │
     │  │ (TTS, voice  │  │ :8106        │               │
     │  │  'serena')   │  │ (RAG, vector)│               │
     │  └──────────────┘  └──────────────┘               │
     └────────────────────────────────────────────────────┘
```

---

## Where each component runs

| Component | Where | How started | Why |
|---|---|---|---|
| `livekit-server` (SFU) | EC2, docker, host network | `docker compose up -d livekit-server` | WebRTC media needs full UDP port range exposed |
| `token-mint` (FastAPI) | EC2, docker, port mapping | `docker compose up -d token-mint` | Plain HTTP, no UDP — standard port mapping |
| `agent-worker` (Python) | EC2, docker, host network | `docker compose up -d agent-worker` | Connects to SFU as LiveKit participant; needs same-host loopback to SFU |
| Next.js frontend | EC2, `npm start` directly (not docker) | `nohup npm start -- --port 3000 ...` | MVP shortcut; would be containerized for real production |
| Whisper STT, Qwen3-VL LLM, Kokoro TTS, sophia-spatial-ai RAG | EKS in us-west-2 | (already deployed by infra team — not our concern) | Already-existing infra; cross-region access via port-forward for MVP |
| Browser client | User's laptop, Chrome with `chrome://flags` workaround | User opens URL | Plain HTTP from public IP → Chrome requires the secure-origin flag |
| Glasses client | XREAL Beam Pro Android phone + XREAL One Pro glasses via USB-C | `adb shell am start ...` | Native Android APK built from Unity |

---

## What's deployed ON EC2 — per-component deep dive

### 1. `livekit-server` (the SFU)

The Selective Forwarding Unit. It receives WebRTC media tracks from participants and forwards each track to every OTHER participant in the same room. No transcoding, no recording — just packet routing.

**Image**: `livekit/livekit-server:latest` from Docker Hub.

**Network**: `network_mode: host` in docker-compose. This means the container shares the EC2's network namespace directly — port 7880, 7881, and the 50000-60000 UDP range are bound on the host's public interface (3.227.63.49). Without host networking, Docker would NAT each port through its bridge and break WebRTC candidate negotiation.

**Ports**:
- `7880` TCP — WebSocket signaling (clients connect here to negotiate the WebRTC peer connection)
- `7881` TCP — TURN/TCP fallback (used when UDP is blocked, e.g. corporate networks)
- `50000-60000` UDP — media transport (the actual audio/video packets flow over these)

**Config**: bind-mounted from `./sophia-agent/infra/livekit.prod.yaml` (gitignored on EC2 only). The key contents:
- `keys:` block has one API key + secret pair. The SFU verifies all incoming JWTs against this pair. The same key+secret must be loaded by token-mint (for signing) — mismatch means the SFU rejects every token.
- `rtc.use_external_ip: false` because we override the advertised IP via the CLI flag `--node-ip 3.227.63.49`.
- `rtc.port_range_start/end: 50000-60000` — must match the AWS Security Group ingress rule.

**Identity**: when the SFU starts, it advertises itself at `3.227.63.49:7880`. Clients reaching this address get back a list of "ice candidates" (host candidates, srflx candidates, relay candidates) and pick one to establish the WebRTC peer connection.

**State**: lives in memory. Restart loses all current rooms + participants. Persistent state would require Redis-backed clustering (not enabled for MVP).

### 2. `token-mint` (FastAPI JWT minter)

A small FastAPI service that mints LiveKit JWTs on demand for clients that can't (or shouldn't) hold the LiveKit API secret themselves.

**Image**: built from `sophia-agent/Dockerfile.token-mint` (slimmer than the agent worker — skips Silero VAD + turn-detector model download).

**Network**: standard Docker port mapping (`ports: ["8001:8001"]`). Container's port 8001 is reachable as `3.227.63.49:8001` from the outside, with the AWS SG passing TCP 8001.

**Endpoint**: `POST /token` accepts a JSON body, returns a JWT.

**Auth**: opt-in. If `SOPHIA_TOKEN_API_KEY` env var is set (and it is, value `9a11fdf5...` on the EC2), the FastAPI middleware checks for an `X-API-Key` header on every `POST /token` request. No header or wrong header → HTTP 401 with body `Missing or invalid X-API-Key header`. If the env var is unset, the auth check is bypassed and any caller can mint tokens (this was the MVP-early state).

**JWT contents**: the token signs three things into the payload:
- `sub` (subject) = participant identity (e.g. `glasses-1A2B3C4D`)
- `iss` (issuer) = the LiveKit API key from `LIVEKIT_API_KEY` env var
- `video` claim = room name + permissions (canPublish, canSubscribe, canPublishData)
- `roomConfig.agents` = list of agents to dispatch into the room. We set this to `[{"agentName": "sophia-agent"}]` so the SFU dispatches our worker.

JWT is signed using HS256 with `LIVEKIT_API_SECRET` as the signing key. The SFU verifies the signature on every connection attempt — wrong secret = SFU rejects.

**Who calls it**: ONLY the glasses (and any non-browser client). The browser uses a DIFFERENT token endpoint — see "The two auth paths" below.

### 3. `agent-worker` (the Python LiveKit Agents worker)

The actual voice agent. A Python process that registers with the SFU as a worker, listens for room dispatch events, and orchestrates the STT → RAG → LLM → TTS pipeline.

**Image**: built from `sophia-agent/Dockerfile`. Multi-stage build: stage 1 uses uv to resolve deps + downloads Silero VAD + turn-detector ONNX models (cache placed under `/app/.cache/huggingface` via `HF_HOME` env), stage 2 is the runtime image with everything copied over.

**Network**: `network_mode: host` like the SFU. The worker connects to the SFU as a participant; with host networking it can use `ws://localhost:7880` as the SFU URL, looping back through the host's network stack without going out the public interface.

**Environment override (CRITICAL)**: docker-compose explicitly sets `LIVEKIT_URL=ws://localhost:7880` for the worker container. This overrides whatever's in `.env.production` (which has the public IP). Why: if the worker tried `ws://3.227.63.49:7880`, the packet would go OUT the public interface, hit the AWS Security Group (inbound rule), and either succeed (slow round-trip through AWS) or fail (if SG closed). Loopback is instant + never depends on SG.

**Registration**: on startup, the worker:
1. Opens WebSocket to `ws://localhost:7880/worker` with credentials.
2. Sends a `RegisterWorkerRequest` with `agent_name: "sophia-agent"`, version, capabilities.
3. SFU replies with a worker ID (e.g. `AW_3svWCxz4GdXF`) and confirms registration.
4. Worker is now in "available" state. SFU will dispatch any incoming room with `roomConfig.agents` matching `agent_name: "sophia-agent"`.

**Job loop**: when SFU dispatches a job:
1. SFU sends `JobOffer` over the worker socket.
2. Worker accepts (`JobAccept`).
3. SFU mints a special worker-side JWT and sends it back.
4. Worker uses that JWT to JOIN the room as a participant with identity `agent-<sid>` (the `agent-` prefix is what the glasses client filters on for audio playback per Q58).
5. Worker calls `entrypoint(JobContext)` — the function in `agent.py` that wires the STT/LLM/TTS pipeline.

**Pipeline wiring inside `entrypoint`**:
```python
session = AgentSession(
    stt=openai.STT(base_url="http://localhost:8080/v1", model="whisper-large-v3", api_key="not-needed"),
    llm=openai.LLM(base_url="http://localhost:18080/v1", model="qwen3-vl-8b-instruct", api_key="not-needed"),
    tts=openai.TTS(base_url="http://localhost:8122/v1", model="tts-1", voice="serena", api_key="not-needed", response_format="wav"),
    turn_detection=MultilingualModel(),
    vad=ctx.proc.userdata["vad"],
    preemptive_generation=True,
)
```

These URLs are all `localhost:<port>` because `pf-gpu.sh` runs kubectl port-forwards FROM the EC2 → EKS in us-west-2, exposing each inference service on a local port. The worker doesn't know (or care) that the actual service lives in a different region.

**Always-retrieve RAG hook**:
```python
class Assistant(Agent):
    async def on_user_turn_completed(self, turn_ctx, new_message):
        # Always calls POST /retrieve. If max_score >= 0.30, inject chunks.
        # Publishes result to frontend via sophia.rag_result topic.
```

Hook fires after each user turn completes. Always calls `localhost:8106/retrieve` (sophia-spatial-ai). If max score from the retrieval ≥ 0.30 (our threshold), the top chunks are injected into the LLM's `chat_ctx` as a system message — this is how grounding happens. Below threshold, skip injection → general conversation.

**Text-stream side channel**: the worker publishes three topics:
- `sophia.agent_events` — JSON events for state transitions (LISTENING, THINKING, SPEAKING) and metrics.
- `sophia.rag_result` — JSON with question, answer, hits, mode (retrieve_injected vs retrieve_skipped).
- `lk.transcription` — raw text per turn (built-in LiveKit topic; user vs agent disambiguated by participant identity prefix).

Both clients (browser + glasses) subscribe to these and render the HUD elements (state pill, transcript, RAG chips). The audio loop works without these — they're purely for UX.

### 4. Next.js frontend (`agent-starter-react`)

A vendored fork of the LiveKit Agents Starter React app. Runs as a plain `npm start` process on EC2 — not in docker (MVP shortcut). Lives at `/workspace/avinash/sophia/agent-starter-react/`.

**Process**: `nohup npm start -- --port 3000 --hostname 0.0.0.0 > frontend.log 2>&1 &` — binds to all interfaces, port 3000. Logs go to `/workspace/avinash/sophia/frontend.log`.

**Build artifacts**: the `.next/` directory (Next.js production build) is created by `npm run build` and served by `npm start`.

**Three key code modifications for production**:

1. `app/api/token/route.ts` — the original starter has a `throw new Error('THIS API ROUTE IS INSECURE...')` guard if `NODE_ENV !== 'development'`. Removed for MVP. The route is now open; anyone who can reach `:3000` can mint a JWT. Production must restore proper auth here.

2. `app-config.ts` — `agentName` is HARDCODED to `'sophia-agent'`. Was previously `process.env.AGENT_NAME ?? undefined`. Why hardcoded: Next.js strips non-`NEXT_PUBLIC_*` env vars from the CLIENT bundle at build time. The app-config.ts file is imported by client components; `process.env.AGENT_NAME` becomes `undefined` in the browser, the JWT gets `roomConfig.agents: []`, agent never dispatches, room session times out after 30s. Hardcoding eliminates the indirection.

3. `next.config.ts` — `eslint: { ignoreDuringBuilds: true }` to skip prettier rules in the starter template files (not our code).

**What the frontend's `/api/token` route does**: it's a Next.js server-side route handler. When the browser POSTs to `/api/token`, the Next.js process (server-side, in the same `npm start` process) signs a JWT using `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` from the frontend's own `.env.local` (different file from the backend's `.env.production`, but the values match). Returns the JWT to the browser.

This is NOT the same service as `token-mint` on port 8001. It's a separate JWT minter built into the Next.js app. Browser uses this, glasses do not.

---

## What's deployed on EKS (the inference services)

Pre-existing infra deployed by the team — not in this project's git repo. Lives in EKS cluster `spatial-ai-staging` in `us-west-2`, namespace `multi-agent`. The EC2 reaches them via kubectl port-forward FROM the EC2 (see "Cross-region access" below).

| Service | EKS port | Local-on-EC2 port (post port-forward) | What it does |
|---|---|---|---|
| `whisper-inference` | 8080 | `localhost:8080` | Speech-to-text. Whisper-large-v3. OpenAI-compatible HTTP API at `/v1/audio/transcriptions`. |
| `qwen3-inference` | 8080 | `localhost:18080` (collision with whisper → re-prefixed by pf-gpu.sh) | LLM + vision. Qwen3-VL-8B-Instruct. Chat-completions API at `/v1/chat/completions`. |
| `kokoro-tts` | 8122 | `localhost:8122` | Text-to-speech. Kokoro-82M. OpenAI-compatible at `/v1/audio/speech`. Voice `serena` (mapped to `af_heart` in Kokoro's VOICE_MAP). |
| `sophia-spatial-ai` | 8106 | `localhost:8106` | RAG retrieval. Custom HTTP API at `/retrieve` returning `{question, answer, hits, mode, ...}`. |

(Plus a few we don't actively use: `orpheus-tts:8120` — alternative TTS, `voice-relay:8111`, `infra-prometheus-grafana:3030`.)

**Cross-region access pattern**:
- EC2 is in `us-east-1`. EKS is in `us-west-2`. Different regions = different VPCs = no same-VPC routing.
- The EKS API endpoint IS reachable cross-region (it's a public HTTPS endpoint).
- `kubectl port-forward` works through the EKS API: kubectl on EC2 → EKS API (cross-region HTTPS) → kube-apiserver → kubelet on the node → service Pod → response back the same way.
- Cost: ~$0.02/GB cross-region transfer. Negligible for demo loads.
- Latency: ~70ms extra round-trip per inference call. Noticeable but acceptable for MVP.
- For real production: move EC2 to us-west-2 (same region as EKS) to eliminate the penalty.

**Authentication for kubectl**:
- The EC2's IAM Instance Profile (`sophiaspatialai-ai-gpu-ec2`) does NOT have EKS permissions. `aws eks update-kubeconfig` fails with AccessDenied.
- Workaround: export YOUR (the user's) temporary STS credentials as env vars on the EC2 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`). Then kubectl uses YOUR identity (which IS in the cluster's aws-auth ConfigMap), bypassing the instance role.
- STS creds expire ~1 hour after issue. Re-export per session.
- This is fragile for production. Real production needs the EC2 instance role added to aws-auth OR a service-account-based access pattern.

**The port-forward script**: `sophia-agent/infra/pf-gpu.sh` (in the repo). It iterates over the four service names, runs `kubectl port-forward -n multi-agent svc/<service> <local>:<remote>` in the background for each, saves PIDs to `/tmp/pf-gpu.pids` for cleanup. `./pf-gpu.sh stop` reads the PID file and kills them.

---

## Networking topology + ports

```
EC2 host (3.227.63.49):
├── eth0 (public 3.227.63.49 + private 10.20.1.90)
│
├── 0.0.0.0:22       <- SSH (always)
├── 0.0.0.0:3000     <- frontend (npm start, npm process)
├── 0.0.0.0:7880     <- livekit-server signal (docker host-network)
├── 0.0.0.0:7881     <- livekit-server TCP/TURN (docker host-network)
├── 0.0.0.0:8001     <- token-mint (docker, port-mapped 8001:8001)
├── 0.0.0.0:50000-60000 UDP  <- livekit-server media (docker host-network)
│
├── 127.0.0.1:8080   <- kubectl port-forward → whisper-inference (us-west-2)
├── 127.0.0.1:18080  <- kubectl port-forward → qwen3-inference (us-west-2)
├── 127.0.0.1:8122   <- kubectl port-forward → kokoro-tts (us-west-2)
└── 127.0.0.1:8106   <- kubectl port-forward → sophia-spatial-ai (us-west-2)
```

AWS Security Group ingress rules (managed via the `AIPartnersUSA/aws-infra` Terraform repo):
- TCP 22 — SSH (always)
- TCP 3000 — frontend
- TCP 7880 — SFU signal
- TCP 7881 — SFU TCP/TURN
- TCP 8001 — token-mint
- UDP 50000-60000 — SFU media
- All from `0.0.0.0/0` per the JupyterLab pattern this SG follows.

---

## The two auth paths (browser vs glasses)

The two clients hit DIFFERENT endpoints to get their LiveKit JWTs:

**BROWSER path** — uses `http://3.227.63.49:3000/api/token` (Next.js built-in route).
- The Next.js process (running via `npm start`) handles this route server-side.
- Code: `agent-starter-react/app/api/token/route.ts`.
- Mints a JWT using `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` from the frontend's own `.env.local`.
- **No `X-API-Key` header required** — the route is open. Anyone who can load `:3000` can mint a token.
- Why this is "fine" for MVP: the route is same-origin from the page (browser already had to load the page to call this route).
- For real production: must add proper auth (replace open route with bearer JWT or OAuth from a real identity provider).

**GLASSES path** — uses `http://3.227.63.49:8001/token` (standalone FastAPI service).
- The token-mint container handles this.
- Code: `sophia-agent/src/token_mint.py`.
- Mints a JWT using `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` from the backend's `.env.production`. (Values match those in the frontend's `.env.local` — same keys, two files.)
- **Requires `X-API-Key` header** matching `SOPHIA_TOKEN_API_KEY` env var (currently `9a11fdf5...`). Missing or wrong header → HTTP 401.
- Unity code in `SophiaConnection.cs` conditionally sets the header based on `SophiaConfig.asset.tokenApiKey` value. If the field is empty, no header is sent (matches the opt-in behavior on the server).

**Why two paths**: the Next.js route was already in the starter template for browser-only use. The FastAPI token-mint was added for glasses (and any future non-browser client) because glasses can't run a Next.js server. We could collapse the two long-term (browser hits FastAPI too) but for MVP keeping both was less code change.

Both paths produce JWTs signed with the same `LIVEKIT_API_SECRET`, so the SFU accepts either equally.

---

## End-to-end flow — BROWSER application

User picks up laptop, opens Chrome, types `http://3.227.63.49:3000`. Sophia answers their question 4 seconds later. What actually happened:

### Setup (one-time per Chrome profile)

Chrome blocks `navigator.mediaDevices.getUserMedia()` on non-secure-context pages (HTTP from public IP qualifies as non-secure). The mic API is literally not exposed to page JavaScript. Workaround: enable `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, paste `http://3.227.63.49:3000` into the field, relaunch. After relaunch, that one origin is treated as secure and the API becomes available.

### Step 1 — Page load

Browser sends `GET /` to `http://3.227.63.49:3000`. The `npm start` Next.js process serves the production-built HTML + JavaScript bundles. The page is a React SPA — once the JS loads it takes over.

### Step 2 — User clicks "Start Call"

React calls a click handler that triggers the LiveKit React SDK's connection flow.

### Step 3 — Token request

The browser calls `fetch('/api/token', {method: 'POST', body: JSON.stringify({})})`. This is a relative-path request, so it goes to the same origin (`http://3.227.63.49:3000`).

Next.js routes this to `app/api/token/route.ts`, which runs server-side inside the `npm start` process. The route:
1. Reads `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` from `process.env` (loaded from `.env.local` at startup).
2. Generates a random room name (e.g. `sophia-2025-1234`).
3. Generates a random participant identity (e.g. `viewer-abc123`).
4. Builds a `livekit-server-sdk` AccessToken with permissions + room name + identity.
5. Adds `roomConfig.agents: [{agentName: 'sophia-agent'}]` to tell the SFU to dispatch our worker.
6. Signs the JWT using `LIVEKIT_API_SECRET`.
7. Returns `{ serverUrl: 'ws://3.227.63.49:7880', participantToken: '<jwt>', roomName, participantName }`.

### Step 4 — WebSocket connect to SFU

Browser opens a WebSocket to `ws://3.227.63.49:7880/rtc?access_token=<jwt>&...`. SFU verifies the JWT against its `keys:` block — same `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` pair as the frontend used to sign, so signature checks out.

SFU creates a room (if not exists), adds the browser as a participant. Sends back `JoinResponse` with the SFU's WebRTC connection parameters (ICE candidates, fingerprints, etc.).

### Step 5 — Agent dispatch (parallel with Step 4)

When the SFU processes the JoinRequest, it sees `roomConfig.agents: [{agentName: 'sophia-agent'}]` in the JWT. It looks up registered workers matching `agent_name = "sophia-agent"`, finds the agent-worker that registered at startup, sends a `JobOffer` over the worker's persistent WebSocket.

The agent-worker accepts (`JobAccept`), gets a JWT for itself, opens its OWN WebSocket to the SFU, joins the same room as a participant with identity `agent-<sid>`. The room now has 2 participants: the viewer (browser) and the agent.

### Step 6 — WebRTC negotiation

Browser and SFU exchange SDP offer/answer over the WebSocket. They agree on codecs (Opus for audio, VP8/H.264 for video — but we don't use video). They establish a WebRTC peer connection: ICE candidates traded, DTLS handshake completes, SRTP keys derived. Now UDP packets between browser and SFU can flow (over UDP 50000-60000 to the SFU side, ephemeral high port on the browser side).

The agent-worker similarly has its own WebRTC peer connection to the SFU.

### Step 7 — Browser publishes mic track

Browser calls `getUserMedia({audio: true})`. Chrome shows the mic permission dialog (if first time). User clicks Allow. Browser gets a MediaStreamTrack containing live mic audio.

Browser wraps the track in a LiveKit `LocalAudioTrack` and publishes via `room.localParticipant.publishTrack(track)`. The SFU now receives an audio stream from the browser participant.

### Step 8 — Agent subscribes to user's track

The agent-worker is subscribed to all tracks in the room by default (LiveKit Agents subscribes broadly). When the SFU notices the new track, it starts forwarding the audio packets to the agent. The agent's track-subscribed handler fires inside the Python process.

The `AgentSession` instance hands the incoming audio frames to the VAD (Silero) to detect voice activity, and accumulates audio frames in a buffer.

### Step 9 — User speaks

User says "What's the safety procedure for the X-200?". Audio flows browser → SFU → agent in real time (~50ms latency for that hop).

The VAD detects speech segments. The turn-detector (a separate ONNX model) watches for end-of-turn signals (silence, falling intonation, etc.).

### Step 10 — End of turn → STT call

The turn-detector decides the user is done. AgentSession finalizes the buffered audio and sends it to STT.

STT call: `openai.STT(base_url='http://localhost:8080/v1', model='whisper-large-v3')` posts the audio as multipart to `http://localhost:8080/v1/audio/transcriptions`. The request goes to `127.0.0.1:8080`, which is the kubectl port-forward, which tunnels cross-region to whisper-inference in EKS us-west-2.

Whisper returns text: `"What's the safety procedure for the X-200?"`.

### Step 11 — `on_user_turn_completed` hook fires (RAG)

Before the LLM is called, the `Assistant.on_user_turn_completed(turn_ctx, new_message)` hook runs.

Inside, the worker calls `localhost:8106/retrieve` with the user's question. sophia-spatial-ai does a vector search across indexed manual content, returns top-K chunks with scores.

If `max_score >= 0.30` (RAG_SCORE_THRESHOLD), the chunks are injected into `turn_ctx.chat_ctx` as a system message: "Here is relevant context from the maintenance manual: <chunk text> <chunk text> ...". The LLM will see this when it generates.

The hook also publishes a `sophia.rag_result` text-stream message with the question, answer (will be filled in later), hits, and mode (`retrieve_injected` or `retrieve_skipped`). Browser components subscribe to this and render the RAG side panel.

### Step 12 — LLM call

AgentSession sends the chat history (system prompts + RAG injection + user turn) to the LLM. `openai.LLM(base_url='http://localhost:18080/v1', model='qwen3-vl-8b-instruct')` POSTs to `http://localhost:18080/v1/chat/completions` with `stream: true`.

LLM streams back tokens. The agent worker buffers the tokens and starts feeding them to TTS as they arrive (streaming TTS).

### Step 13 — TTS

AgentSession sends each text chunk to TTS. `openai.TTS(base_url='http://localhost:8122/v1', model='tts-1', voice='serena')` POSTs to `http://localhost:8122/v1/audio/speech`. Kokoro returns WAV audio.

The agent worker wraps the TTS audio in a LiveKit `LocalAudioTrack` and publishes via its own `localParticipant.publishTrack(track)`. The SFU receives the agent's audio.

### Step 14 — Browser subscribes to agent's audio

When the agent published its track, the SFU notified all subscribers in the room — including the browser. The browser's LiveKit React SDK auto-subscribes, attaches the incoming RemoteAudioTrack to an `<audio>` element in the DOM, and the browser's audio output plays the sound.

User hears Sophia answer. Round trip from "stopped talking" to "Sophia starts talking" is ~2-3 seconds total: 0.5s STT + 0.2s RAG + 1-1.5s LLM (first token) + 0.3s TTS first chunk + 50ms network.

### Step 15 — Text-stream side channel for UI

Throughout the above, the agent worker also publishes:
- `sophia.agent_events` — state transitions (LISTENING when waiting for user, THINKING during STT/RAG/LLM, SPEAKING during TTS)
- `lk.transcription` — incremental transcription text (so the browser can show what was heard / what's being said)
- `sophia.rag_result` — RAG metadata (sources, scores)

Browser components subscribe to these topics via `room.localParticipant.on('dataReceived', ...)` or LiveKit's text-stream API. The state pill, scrolling transcript, and RAG sources side panel all update in real time.

### Step 16 — End session

When user clicks End Call (or closes the tab), the browser sends `LeaveRequest` to the SFU. SFU removes the participant from the room. Since the agent worker is also in the room and is the only other participant, the SFU sends the agent a `RoomDisconnected` event. The agent's `entrypoint()` returns, the worker goes back to "available" state ready for the next job.

---

## End-to-end flow — XREAL GLASSES application

User picks up Beam Pro, plugs in glasses, taps the Sophia app icon. The flow is structurally identical to the browser path but with different glue.

### Step 0 — APK is pre-installed

The Sophia Unity APK is already installed via `adb install -r <apk>`. The APK's bundled `SophiaConfig.asset` has:
- `liveKitUrl: ws://3.227.63.49:7880`
- `tokenEndpoint: http://3.227.63.49:8001/token`
- `tokenApiKey: 9a11fdf5ce05e3cecad28f933d778971` (matches EC2's `SOPHIA_TOKEN_API_KEY`)
- `agentName: sophia-agent`

### Step 1 — App launch

User taps app icon (or `adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity`). Unity initializes, loads `Assets/Scenes/sophia-scene.unity`.

The scene contains:
- `SessionPicker` GameObject (active by default) — builds the picker UI in `OnEnable`.
- `SophiaConnection` GameObject (DEACTIVATED by default) — will activate when picker chooses a session.
- `SophiaOverlayUI` MonoBehaviour — builds the world-space AR HUD canvas in `OnEnable`.

### Step 2 — User picks Private session

User sees the launch picker UI (landscape two-column card: Private session / Team session). Taps Private.

`SessionPicker.OnPrivateClicked()` fires. It:
1. Sets `SophiaSessionContext.CurrentMode = Mode.Private`.
2. Hides the picker panel.
3. Calls `connectionGameObject.SetActive(true)` — this activates SophiaConnection and triggers its `OnEnable`.

### Step 3 — ConnectFlow coroutine begins

`SophiaConnection.OnEnable` starts the `ConnectFlow` coroutine. The first thing it does is fetch a token.

```csharp
UnityWebRequest www = UnityWebRequest.Post(config.tokenEndpoint, body, "application/json");
www.SetRequestHeader("Content-Type", "application/json");
if (!string.IsNullOrEmpty(config.tokenApiKey))
{
    www.SetRequestHeader("X-API-Key", config.tokenApiKey);
}
yield return www.SendWebRequest();
```

This POSTs to `http://3.227.63.49:8001/token` with the X-API-Key header.

### Step 4 — Token-mint validates + signs JWT

The FastAPI token-mint container receives the POST. Middleware checks the `X-API-Key` header against `SOPHIA_TOKEN_API_KEY` env var. Match → proceed. The `/token` handler:
1. Generates a random room name and participant identity.
2. Builds a LiveKit JWT (same library as the Next.js route, just different language — Python `livekit.api.AccessToken`).
3. Sets `roomConfig.agents: [{agentName: 'sophia-agent'}]`.
4. Signs with `LIVEKIT_API_SECRET`.
5. Returns JSON: `{ "token": "<jwt>", "url": "ws://3.227.63.49:7880", "room": "<room>", "identity": "<identity>" }`.

### Step 5 — Unity opens WebSocket to SFU

LiveKit Unity SDK's `Room.Connect(serverUrl, token)` opens a WebSocket to `ws://3.227.63.49:7880`. SFU verifies the JWT (same `LIVEKIT_API_SECRET`), accepts the connection.

### Step 6 — Agent dispatch (parallel with Step 5)

SFU sees `roomConfig.agents` in the JWT, finds the registered agent-worker, dispatches a job. Agent worker accepts, joins the room as `agent-<sid>`. Identical to the browser path Step 5.

### Step 7 — Glasses-side mic publish

The LiveKit Unity SDK's `MicrophoneSource` opens the Android microphone via `Microphone.Start()`. Wraps the resulting `AudioClip` in a `LocalAudioTrack`. Calls `room.LocalParticipant.PublishTrack(track, new TrackPublishOptions { Source = TrackSource.SourceMicrophone })`.

Permission handling: if Android hasn't granted RECORD_AUDIO yet, Unity shows the permission dialog. The Path A poll-retry code in `SophiaConnection.cs` waits up to 20 seconds for the user to tap Allow. Once granted, mic capture starts, audio flows up to the SFU.

### Step 8-15 — Same as browser

The STT → RAG → LLM → TTS pipeline is identical from this point. The agent worker doesn't know or care which type of client subscribed — it's just "a remote participant publishing an audio track."

### Step 16 — Glasses-side audio playback (DIFFERENT from browser)

When the agent publishes its TTS audio track, the LiveKit Unity SDK fires `Room.TrackSubscribed` on the glasses client.

```csharp
private void OnTrackSubscribed(RemoteTrack track, RemoteTrackPublication publication, RemoteParticipant participant)
{
    // Q58: only play AGENT tracks. Filter on participant identity starting with "agent-"
    if (!participant.Identity.StartsWith("agent-")) return;

    // Q58: create a child GameObject per agent track so the AudioSource is isolated.
    var speakerGo = new GameObject($"SophiaSpeaker_{publication.Sid}");
    speakerGo.transform.SetParent(speakerHost.transform);
    var audioSource = speakerGo.AddComponent<AudioSource>();
    audioStream = new AudioStream(track as RemoteAudioTrack, audioSource);
}
```

Why the agent-only filter: in a multi-user room (Scenario A), the glasses would otherwise also subscribe to OTHER USERS' mic tracks and play them locally — creating echo and confusion. The filter ensures only Sophia's voice plays through the glasses speakers.

Why the child GameObject per track: Unity's AudioSource model is one-per-GameObject. If multiple agent tracks (rare, but possible) landed on the same GameObject, the mixer would drop one. The child GameObject pattern (per publication SID) isolates each track.

The AudioSource plays the agent's audio. On the Beam Pro the audio comes out the phone speaker. With XREAL glasses plugged in, USB audio routing sends it to the glasses' temple speakers instead.

### Step 17 — World-space AR HUD updates

Throughout the session, `SophiaOverlayUI` (a separate MonoBehaviour) listens to the static event `SophiaConnection.OnTextStreamMessage`. Whenever the agent publishes on `sophia.agent_events`, `sophia.rag_result`, or `lk.transcription`, the HUD updates:

- A pulsing colored dot top-right shows the agent state (LISTENING blue, THINKING amber, SPEAKING green).
- A bottom-center subtitle shows the latest transcript line, with speaker-colored prefix ("You: ..." vs "Sophia: ...").
- A vertical stack of chips above the subtitle shows the RAG source citations (each chip = one source/page).

All HUD elements are world-space (parented to Camera.main at 2m focal distance) so they're head-locked — turn your head, the HUD follows. All transitions are 200ms `CanvasGroup.alpha` smoothstep coroutines.

### Step 18 — End session

User taps the End chip in the bottom-right corner of the Beam Pro screen. `SessionPicker.OnEndSessionClicked()` fires. It:
1. Calls `connectionGameObject.SetActive(false)` — triggers `SophiaConnection.OnDisable`.
2. SophiaConnection's `OnDisable` → `Cleanup()` runs: stops the mic, disconnects from the room, destroys all `SophiaSpeaker_*` child GameObjects.
3. Picker UI re-shows for the next session.

The agent worker side: SFU sends `RoomDisconnected`, agent's `entrypoint()` returns, worker goes back to available.

---

## What's different between the two paths

| Aspect | Browser | Glasses |
|---|---|---|
| Token endpoint | `/api/token` (Next.js, open) | `/token` (FastAPI, X-API-Key required) |
| LiveKit client | livekit-client (JavaScript) | LiveKit Unity SDK (C#, wraps native FFI) |
| WebRTC implementation | browser's built-in (libwebrtc) | LiveKit Unity SDK's bundled libwebrtc via FFI |
| Mic API | `getUserMedia({audio: true})` | Unity `Microphone.Start()` via Android MIC permission |
| Audio output | DOM `<audio>` element | Unity AudioSource per agent track (Q58 pattern) |
| UI rendering | React DOM | Unity world-space Canvas (head-locked AR) |
| Text-stream consumption | React component subscribes to `room.on('dataReceived')` | Static C# event `SophiaConnection.OnTextStreamMessage` consumed by SophiaOverlayUI |
| State management | React useState/useReducer | C# MonoBehaviour fields + static `SophiaSessionContext` |
| TLS support | Chrome requires `chrome://flags` workaround over HTTP+public IP | Beam Pro Android tolerates plain HTTP without workaround |
| Audio echo behavior | None (browser handles AEC) | Echo on Beam Pro speakers alone (Q41/Q43); kills naturally with glasses temple speakers geometry |
| Multi-user filtering | LiveKit JS SDK plays all subscribed tracks | Unity-side filter to `participant.Identity.StartsWith("agent-")` (Q58 fix) |

Both paths produce JWTs signed with the same `LIVEKIT_API_SECRET`, hit the same SFU, get the same agent dispatched, run the same STT → RAG → LLM → TTS pipeline. The differences are all glue (token endpoint, UI framework, audio output mechanism).

---

## Data flowing through the system

### JWT shape

What the SFU validates on every connection:

```json
{
  "iss": "7baeb38a5bfadcfed6a713152b8d1c70",       // LIVEKIT_API_KEY (issuer)
  "sub": "glasses-1A2B3C4D",                         // participant identity
  "exp": 1748725800,                                  // expiry timestamp
  "nbf": 0,                                           // not-before
  "video": {
    "room": "sophia-glasses-xyz",                     // room name
    "roomJoin": true,
    "canPublish": true,
    "canSubscribe": true,
    "canPublishData": true
  },
  "roomConfig": {
    "agents": [
      { "agentName": "sophia-agent" }                 // tells SFU to dispatch our worker
    ]
  }
}
```

Signed with HS256 using `LIVEKIT_API_SECRET` (64 hex chars).

### WebRTC media

Opus-encoded audio frames, 20ms each, 48kHz sample rate, mono. Carried in SRTP packets over UDP 50000-60000 (one ephemeral port pair per peer connection).

### Text-stream topics (data channel, not media)

Three topics published by the agent worker:

**`sophia.agent_events`** — JSON-encoded events for UI state updates.
```json
{ "kind": "agent_state", "state": "thinking", "ts": 1748725432000 }
{ "kind": "user_transcript", "text": "What's the safety procedure?", "is_final": true, "ts": ... }
{ "kind": "metrics", "stt_ms": 480, "llm_first_token_ms": 1320, "tts_first_chunk_ms": 280, "ts": ... }
```

**`sophia.rag_result`** — JSON per RAG call.
```json
{
  "question": "What's the safety procedure for the X-200?",
  "answer": "...",
  "mode": "retrieve_injected",
  "hits": [
    { "source": "manual_x200.pdf", "page": 42, "score": 0.78, "text": "..." },
    { "source": "manual_x200.pdf", "page": 43, "score": 0.71, "text": "..." }
  ]
}
```

**`lk.transcription`** — built-in LiveKit topic with raw text per turn. The participant identity distinguishes user vs agent.

### Inference service request/response shapes

**Whisper STT** (`POST /v1/audio/transcriptions`):
- Request: multipart/form-data with `file` (audio bytes), `model: "whisper-large-v3"`.
- Response: `{ "text": "user's transcribed words" }`.

**Qwen3-VL LLM** (`POST /v1/chat/completions`):
- Request: `{ "model": "qwen3-vl-8b-instruct", "messages": [...], "stream": true, ... }`.
- Response: server-sent events with token chunks, terminated by `[DONE]`.

**Kokoro TTS** (`POST /v1/audio/speech`):
- Request: `{ "model": "tts-1", "voice": "serena", "input": "text to speak", "response_format": "wav" }`.
- Response: WAV audio bytes (binary).

**sophia-spatial-ai RAG** (`POST /retrieve`):
- Request: `{ "question": "user's question", "top_k": 5 }`.
- Response: `{ "question": ..., "answer": ..., "hits": [...], "mode": ..., "images": [...] }`.

---

## Where typical failures happen + how they look

| Symptom | Probable cause | Where to look |
|---|---|---|
| Browser: "session ended" after ~30s, no agent voice | JWT `roomConfig.agents` is empty → SFU didn't dispatch worker | Decode JWT at jwt.io. If `roomConfig.agents == []`, the `agentName` env var indirection broke. Check `app-config.ts` is hardcoded. (Problem 16) |
| Browser: 500 on `/api/token` | `NODE_ENV !== 'development'` throw guard | Check `app/api/token/route.ts` has the guard removed. (Problem 14) |
| Browser: `navigator.mediaDevices` undefined | Chrome blocking non-secure origin | Add `chrome://flags` exception. (Problem 15) |
| Glasses: 401 from token-mint | Missing or wrong `X-API-Key` header | Check `SophiaConfig.asset.tokenApiKey` matches `SOPHIA_TOKEN_API_KEY` on EC2. (Problem 17) |
| Glasses: "connection timeout to ws://3.227.63.49:7880" | EC2 stopped OR SG closed | From laptop: `curl -sI --max-time 5 http://3.227.63.49:7880/` should return 200 |
| Agent: subscribes to user but never speaks | Inference port-forwards died (STS expired) | On EC2: re-export AWS creds + restart pf-gpu.sh + `docker compose restart agent-worker` |
| Agent worker: "ConnectionTimeoutError ws://3.227.63.49:7880" | Worker used public IP instead of localhost | Check docker-compose has `LIVEKIT_URL=ws://localhost:7880` override on agent-worker service. (Problem 6) |
| Agent worker: "model not found" at startup | Turn-detector ONNX missing from final stage of multi-stage build | Check Dockerfile has `ENV HF_HOME=/app/.cache/huggingface` in BOTH build and final stages. (Problem 7) |
| Glasses: echo loop when speaking | Beam Pro speaker → Beam Pro mic without glasses geometry | Expected behavior per Q41/Q43. Plug in XREAL glasses, geometry kills the loop |
| Multi-user (Scenario A): glasses echoes browser user's mic | Q58 fix not applied or APK is pre-fix | Check `SophiaConnection.OnTrackSubscribed` filters on `participant.Identity.StartsWith("agent-")` and creates child GameObject per track |
| 401 on EVERY token-mint call after rotating key | `docker compose restart` doesn't reload env_file | Full `docker compose down && up -d`. (Problem 18) |
| Inference calls timing out | kubectl port-forwards died after STS expiry | Check `ps -ef \| grep '[k]ubectl port-forward'` — should show 4-7 processes. If gone, re-run `pf-gpu.sh` |

---

## Cross-references

- `mvp_deployment_shared_ec2.md` — operational runbook (cold/warm start, day-to-day, 19 documented problems).
- `livekit_doubts.md` — Q&A on LiveKit framework specifics. Q41+Q43 (echo geometry), Q49+Q50+Q51 (HUD updates), Q58 (multi-user audio fix), Q61 (two-auth-paths), Q62 (network_mode: host rationale).
- `livekit_deployment.md` — design rationale for component placement. Q28 (MVP walkthrough), Q29 (token-mint auth deep dive).
- `unity_approach.md` — 2500-line narrative for the glasses client. Part 17 covers HUD construction; Appendix B is the operational runbook.
- `sophia-glasses/READING_GUIDE.md` — Unity client codebase tour. Tour of SophiaConfig, SophiaConnection, SophiaOverlayUI, SessionPicker, SophiaSessionContext.
- `HANDOFF.md` — what to change about all this for real production deployment.
- `production_deployment.md` — Section 0 Keep/Replace/Defer between MVP and production.

---

## When to update this file

- Architectural changes (replacing a component, adding a new service, changing the auth model).
- New client types added (iOS, web with TLS, etc.) — add a parallel end-to-end flow section.
- Inference services moved (e.g. EC2 to same region as EKS) — update networking + port-forward section.
- TLS added — update the security context language for the browser path.
- Production migration — at that point most of this file's "MVP" content becomes historical and a fresh architecture doc takes its place.
