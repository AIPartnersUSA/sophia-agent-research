# LiveKit — Doubts & Answers

Q&A log for LiveKit-specific questions while learning the framework, debugging, and building Sophia's voice agent on it. Latest at the bottom.

Related artifacts:
- `my-agent/` — the LiveKit Agents starter project for Sophia (bootstrapped via `lk agent init`)
- `livekit-agents/` — clone of `livekit/agents` for reading the framework source
- `COMPARISON.md` Q3–Q7 — earlier LiveKit how-to entries logged before this file existed

---

## Q1 (2026-05-12): Is LiveKit open source? Can I use it in my project with no problem? What's the difference between using the open-source path vs paying for LiveKit Cloud? What do I get extra, and what do I lose if I stay on open source?

**Yes, LiveKit is genuinely open source.** Both core components are **Apache 2.0**, which is a permissive license — commercial use, modification, redistribution, no royalties, no copyleft contamination. Specifically:

- `livekit/livekit` — the SFU server (Go) — **Apache 2.0**
- `livekit/agents` — the Python agent framework — **Apache 2.0**
- `livekit/livekit-plugins` — the 69 provider plugins — **Apache 2.0** (mostly; a couple have provider-specific terms that pass through)

You can run all of this on your own hardware, fork it, modify it, and ship it in a commercial product with no obligation back to LiveKit beyond the Apache 2.0 attribution clause.

### LiveKit Cloud — what the paid layer actually is

LiveKit Cloud is a **managed-infrastructure offering** layered on top of the OSS code. It's not "the full version" vs "the free version" — the OSS code is the full framework. Cloud is operations-as-a-service:

| LiveKit Cloud feature | What it gives you | OSS substitute |
|---|---|---|
| **Global SFU** | Geographically distributed media servers; auto-scaling; built-in TURN/STUN; low-latency edge routing | Run `livekit-server` yourself; manage scaling, TURN, TLS, geo-distribution |
| **LiveKit Inference** | Proxied access to OpenAI/Cartesia/Deepgram/etc. via LiveKit's API key — you only manage one credential | Use plugins directly with your own provider API keys |
| **LiveKit Cloud noise cancellation** | High-quality noise suppression plugin — **only works with Cloud** | Use Silero / RNNoise / browser-side noise suppression instead |
| **Agent observability** | Web dashboards: call recordings, latency tracing, eval result tracking, usage analytics | Wire OpenTelemetry → Grafana / Tempo / Loki yourself |
| **Cloud Agents** | Deploy your Python agent to LiveKit's infra — no Docker/K8s management | Build/deploy your own Docker image; the starter ships one |
| **SIP/Telephony** | Managed SIP trunks, phone-number provisioning, easier inbound/outbound calling setup | Self-host a SIP gateway (Twilio/Telnyx + livekit-server SIP support) |
| **Sandbox tokens** | One-click dev auth for the Playground | Generate JWTs yourself using `livekit-server` keys |

### What you LOSE if you stay fully open source

Honestly small for a research / benchmarking project:

- **The Cloud noise cancellation plugin.** Genuinely closed; replace with Silero/RNNoise.
- **LiveKit Inference convenience.** But you're going *away* from this anyway since you want self-hosted GPU models — so this isn't a loss for Sophia.
- **The observability dashboards.** You'd replace with your own OTel + Grafana if you need them at scale.
- **The "deploy with one command" UX.** You write your own Dockerfile (one is already in `my-agent/`).

**What you DON'T lose:**
- The whole voice agent framework
- VAD, turn detection, barge-in, full-duplex, interruption logic
- All 69 plugins (STT/LLM/TTS providers)
- Custom plugin authoring
- Test framework, observability hooks, all the SDK features
- The Playground UI (open-source, fork it: `livekit/agents-playground`)

### Practical answer for Sophia

**Open source is sufficient.** The `my-agent/` starter project has only three Cloud-specific dependencies, all easily removed:

1. **`LIVEKIT_URL`** points at Cloud (`wss://…livekit.cloud`) — change to `ws://localhost:7880` after `livekit-server --dev`.
2. **LiveKit Inference calls** — switch to direct plugins (`livekit-plugins-openai`, etc.) as per Q6 in COMPARISON.
3. **Cloud noise-cancellation plugin** — remove or replace with Silero.

The starter's own README acknowledges this:
> "You can also self-host LiveKit instead of using LiveKit Cloud. … If you choose to self-host, you'll need to also use model plugins instead of LiveKit Inference and will need to remove the LiveKit Cloud noise cancellation plugin."

### When you'd switch to Cloud later

- You ship to actual users and need global low-latency without operating WebRTC infrastructure yourself
- You want their observability dashboards rather than wiring OpenTelemetry
- You want managed SIP/telephony
- You want to deploy agents without managing Docker/K8s

None of these are Phase 1/2 concerns for Sophia. Stay OSS for the research and benchmarking work; reassess if you ship a production product.

### Bottom line

- ✅ **Use LiveKit OSS commercially with no licensing problem.** Apache 2.0.
- ✅ **You get the entire framework**, not a stripped-down version.
- ⚠️ **You lose only three Cloud-managed conveniences** (noise cancellation, Inference proxy, observability dashboards), each with reasonable OSS substitutes.
- 💡 **LiveKit Cloud's free tier exists** for prototyping if you want zero-setup; you can always self-host later without rewriting code.

---

## Q2 (2026-05-13): If we go OSS for production (self-hosted, our own cloud, our own dashboards, our own noise cancellation), can we actually get the same performance and full features as managed LiveKit Cloud?

**Short answer: Yes — with one real-but-closeable quality gap and a 2–4 person-week DevOps investment.**

### What's 100% identical (no parity work needed)
- Entire `livekit/agents` framework (VAD, turn detection, barge-in, full-duplex, interruption, audio recognition, generation streaming)
- All 69 STT/LLM/TTS plugins + custom plugin authoring
- Playground UI (also OSS — `livekit/agents-playground`)
- Voice agent SDK latency, streaming behavior, full-duplex models
- **Conversational quality is determined by your model choices, NOT by Cloud vs OSS** — same code path either way

### What you must build for operational parity

| Cloud feature | OSS substitute | Effort |
|---|---|---|
| Global SFU edge network | Deploy `livekit-server` in 2–4 regions + GeoDNS | 3–5 days |
| TURN/STUN | `coturn` alongside livekit-server + TLS | 1–2 days |
| Autoscaling | K8s HPA (or ECS/Cloud Run) | 3–5 days |
| Observability dashboards | OpenTelemetry → Grafana/Tempo/Loki + custom per-session views | 1–3 weeks (longer if you want call playback) |
| **Noise cancellation (Krisp in Cloud)** | **DeepFilterNet 3** (Apache 2.0, ~50 ms, ~90 % of Krisp quality) | 1–2 days |
| Agent worker fleet | Same K8s pattern for Python workers | 2–3 days |
| SIP/telephony (if needed) | Self-host LiveKit SIP gateway + Twilio/Telnyx trunk | 1 week |
| TLS, secrets, auth | Standard cloud-ops | 1–2 days |

**Total ~2–4 person-weeks** for a competent platform engineer.

### The one real quality gap: noise cancellation
LiveKit Cloud uses **Krisp** (commercial-licensed, closed). OSS options:

| Option | Quality vs Krisp | Notes |
|---|---|---|
| **DeepFilterNet 3** | ~90 % | Apache 2.0, CPU-friendly. **Best OSS option.** |
| RNNoise (Mozilla) | ~70 % | Apache 2.0, lightweight, older |
| Browser `noiseSuppression` constraint | Decent for mild noise | Free, runs in user's browser |

For Sophia's likely domain (office/home users) DeepFilterNet 3 is production-viable. The gap only really shows in extreme call-center-style overlapping speech.

### Operational comparison

| Dimension | Cloud | OSS (properly built) |
|---|---|---|
| SDK / voice latency | Same | Same |
| RTT to local user | ~30 ms | ~30 ms |
| RTT to distant user, single region | ~250 ms | ~250 ms — fix by deploying that region |
| Clean-input audio quality | Same | Same |
| Noisy-input audio quality | Better (Krisp) | ~90 % as good (DeepFilterNet) |
| Reliability | LiveKit SLA ~99.9 % | Your ops team's delivery |
| **Cost at scale (thousands+ min/mo)** | Per-minute pricing | Fixed cloud bill + eng time — **cheaper** |
| Cost at very small scale | Free/cheap tier wins | OSS fixed cost > tiny Cloud bill |

### Recommended migration path
1. **Benchmarking phase (now):** Use LiveKit Cloud free tier with self-hosted models behind plugins — zero infra effort, same code.
2. **Pre-production:** Stand up self-hosted `livekit-server` in one region, validate everything works against the same agent code.
3. **Production:** Add regions, swap in DeepFilterNet 3, wire OTel → Grafana, build your dashboards.

Agent code never has to change across these phases.

### Bottom line
- ✅ Equivalent code/feature parity: **yes**.
- ✅ Equivalent voice quality and latency with proper regional deployment: **yes**.
- ⚠️ ~2–4 person-weeks of DevOps to reach equivalence (one-time).
- ⚠️ One gap — Krisp-grade noise cancellation — closeable to ~90 % via DeepFilterNet 3, not eliminatable.
- ✅ At meaningful scale, OSS is cheaper than Cloud's per-minute pricing.

For Sophia: **OSS production path is viable**, framework is fully identical, gap is operational and engineering-tractable.

---

## Q3 (2026-05-13): What are agents / egress / ingress / client-SDK / server-SDK / CLI / Docker image / Helm charts in the LiveKit ecosystem, and which docs section should I focus on?

### Ecosystem (what runs where)

| Piece | What it does | Need it for Sophia? |
|---|---|---|
| **Agents** | AI participants that join a room and have a voice conversation (STT→LLM→TTS) | ✅ Yes — core |
| **Egress** | Pulls media OUT of a room: record MP4/MP3, push RTMP/HLS | ⚠️ Later — useful for recording calls for QA/eval |
| **Ingress** | Pushes external media INTO a room (RTMP/WHIP, phone) | ❌ Probably not |

Mental model: `ingress → ROOM (users + agents) → egress`. The **Room** is the central concept — a temporary multi-party container for audio/video tracks.

### SDKs (who's calling whom)

| Type | Runs on | Purpose | Languages |
|---|---|---|---|
| **Client SDKs** | User's browser/phone/device | Join room, publish mic, subscribe to agent audio | JS/TS, React, Swift, Kotlin, Flutter, React Native, Unity, Rust |
| **Server SDKs** | Your backend | Create rooms, mint JWT tokens, manage participants | Python, Node, Go, Java, Ruby, PHP |

The Agents framework bundles both — your agent process is both a server-side manager and a media client.

```
[ Browser frontend ]              [ Your backend ]            [ Agent process ]
   Client SDK (React)        ───► Server SDK (mint token)     Python agents framework
        ▲                                                            │
        └──── joins room with token ────────────────────────────────┘
```

### Tools

| Tool | What | When to use |
|---|---|---|
| `lk` CLI | Room mgmt, token gen, `lk agent init`, `lk docs search`, `lk cloud auth` | Daily |
| Docker image (`livekit/livekit-server`) | Pre-built SFU container | When self-hosting OSS |
| Helm charts | K8s manifests for `livekit-server` | At production scale on K8s |

Progression: now → CLI only · pre-prod → CLI + Docker · prod scale → CLI + Docker + Helm.

### Documentation — focus order

| Section | URL | Sophia priority |
|---|---|---|
| Agents | https://docs.livekit.io/agents/ | ⭐ Primary, daily |
| Realtime / Home (rooms/tracks/participants) | https://docs.livekit.io/home/ | 🔵 Secondary — enough to understand the SFU concepts |
| Reference (API docs) | https://docs.livekit.io/reference/ | 🔵 Look up as needed |
| Deploy | https://docs.livekit.io/deploy/ | 🟡 Only when production-bound |
| Telephony / SIP | https://docs.livekit.io/telephony/ | ❌ Skip unless adding phone |
| Egress | https://docs.livekit.io/egress/ | 🟡 When recording calls for eval |
| Ingress | https://docs.livekit.io/ingress/ | ❌ Skip |

**Next-session reading order:**
1. `/home/get-started/intro-to-livekit/` — 10-min overview of rooms/participants/tracks
2. `/agents/start/voice-ai/` — voice AI quickstart (matches `my-agent`)
3. `/agents/build/` — voice agent architecture
4. `/agents/build/turns/` — VAD + turn detection knobs

### Unifying mental model

The Agent is just another participant in a LiveKit Room — but instead of a human with a microphone, it's your Python process running STT/LLM/TTS plugins. Everything else (ingress, egress, client SDKs, server SDKs, CLI) is plumbing around getting people, bots, and media into and out of that Room.

---

## Q4 (2026-05-13): For XREAL glasses + Android phone end-users, what's the actual procedure? Is the glasses the client? Do we build a client SDK or use an existing one? Server side is OSS self-hosted with the Python server SDK?

### The client is the Android phone, not the glasses
XREAL Air/Light glasses tether to an Android phone over USB-C. The glasses are a display + (sometimes) mic/speaker peripheral; the **phone runs your app and handles all networking, audio I/O, and LiveKit connections.** XREAL provides **NRSDK** to render AR overlays on the glasses' display from your Android app.

LiveKit roles:
- **Client** = Android phone (your app)
- **Glasses** = I/O peripheral driven by NRSDK
- **Server** = self-hosted `livekit-server` in your cloud
- **Agent** = your Python process running the `livekit-agents` framework

### You don't build a client SDK — you use the existing one
LiveKit ships a production Android client SDK; you import it:
```kotlin
implementation("io.livekit:livekit-android:2.x.x")
implementation("io.livekit:livekit-android-compose-components:1.x.x")
implementation(files("libs/NRSDK_Android.aar")) // XREAL
```
Your code work is application-layer glue between LiveKit SDK + NRSDK in the Android app.

### Full architecture
```
[Android phone + XREAL glasses (USB-C)]
   Your app: LiveKit Android Client SDK (audio I/O + data channel)
              + XREAL NRSDK (AR overlays on glasses)
                            │ WebRTC (audio + data over UDP/TCP)
                            ▼
[Your cloud — self-hosted OSS]
   livekit-server (Docker, ports 7880/81/82)
   Token-mint backend (FastAPI + livekit-server-sdk Python)
   Sophia Agent Worker (Python + livekit-agents framework)
   Model servers (vLLM, Faster-Whisper-Server, …)
```

### What you build vs use

| Component | Build/Use | Language |
|---|---|---|
| Android app | Build | Kotlin (or Flutter) |
| LiveKit Android Client SDK | Use | Kotlin lib import |
| XREAL NRSDK | Use | Provided by XREAL |
| `livekit-server` | Self-host OSS | Go binary in Docker |
| Token-mint backend | Build (~50 lines FastAPI) | Python + `livekit-server-sdk` |
| Sophia Agent Worker | Build (evolved `my-agent`) | Python + `livekit-agents` |
| Model servers | Build/run | vLLM etc. |

### End-to-end flow
1. User opens app → glasses display the phone's screen as a virtual monitor.
2. App calls your backend `POST /token` with user identity.
3. Backend mints JWT using Python server SDK with API key/secret (never embed secret in app).
4. App calls `room.connect(wss://your-livekit, token)`.
5. App publishes mic track (phone mic or XREAL glasses mic).
6. Agent Worker already running, auto-joins room when user enters.
7. User speaks → mic → LiveKit → Agent STT → LLM (RAG) → TTS → audio back to room → phone plays via speaker or XREAL speakers.
8. Agent sends data-channel messages (`{event: transcript, text: ...}`, `{event: rag_source, url: ...}`).
9. App receives data messages → renders AR overlays via NRSDK on glasses.

### XREAL-specific gotchas
- **Glasses mic vs phone mic:** XREAL Air 2 Pro has dual mics; Air 1 doesn't. Android picks audio source per routing rules — LiveKit defaults usually work.
- **Glasses speakers vs phone speakers:** XREAL Air has built-in speakers; auto-routed by Android.
- **Battery / thermal:** LiveKit + NRSDK both heavy. Voice-only mode during low-attention helps.
- **NAT/firewall on cellular:** Carrier-grade NAT → need TURN. Run `coturn` next to `livekit-server`.
- **Distance latency:** Single-region server hurts distant users — deploy regional instances per Q2.

### Concrete first steps (post-benchmarking)
1. Keep benchmarking on Playground + laptop — don't fight Android/XREAL until models are picked.
2. Clone `livekit-examples/agent-starter-android` (Kotlin) — Android equivalent of `my-agent`. Get phone-talks-to-agent without XREAL first.
3. Add NRSDK for AR overlays — pure rendering driven by LiveKit data channel.
4. Self-host `livekit-server` in one region as launch approaches.

### Bookmarks
- LiveKit Android SDK: https://github.com/livekit/client-sdk-android
- Android agent starter: https://github.com/livekit-examples/agent-starter-android
- Python server SDK: https://github.com/livekit/server-sdk-python
- `livekit-server` OSS: https://github.com/livekit/livekit (Docker `livekit/livekit-server:latest`)
- XREAL NRSDK: https://docs.xreal.com/category/nrsdk-overview

---

## Q5 (2026-05-13): Recap — my Sophia app code is on Android, uses the LiveKit Android SDK, connects to self-hosted `livekit-server`, and XREAL glasses provide audio + camera. Right?

**Mostly correct — two precisions.**

**Right:**
- Sophia client code is an **Android app** using the **LiveKit Android SDK**
- Connects to your **self-hosted `livekit-server`**
- XREAL glasses provide some audio I/O (mic/speakers on Air 2 / Pro / Ultra)

**Precision 1 — XREAL camera availability varies:**

| Model | Camera | Mics | Speakers |
|---|---|---|---|
| Air 1 | ❌ | ❌ | ✅ |
| Air 2 / Air 2 Pro | ❌ | Dual | ✅ |
| Air 2 Ultra | ✅ | ✅ | ✅ |
| Light | ✅ (depth + RGB) | ✅ | ✅ |

For most XREAL models, **the camera is the phone's camera**, not the glasses'. Only Air 2 Ultra and Light have glasses-mounted cameras.

**Precision 2 — server side is four processes, not one:**

| Process | Purpose | Where |
|---|---|---|
| `livekit-server` | SFU — routes WebRTC media | Your cloud (Docker) |
| Token-mint backend | Mints JWTs for clients (keeps API secret server-side) | Your cloud (small Python service) |
| Sophia Agent Worker | The AI brain — Python + `livekit-agents` framework, joins rooms as an AI participant | Your cloud (CPU instance) |
| Model servers | STT/LLM/TTS (vLLM, Faster-Whisper-Server, Orpheus server, etc.) | Your cloud (GPU instances) |

**Corrected one-liner:** "Sophia Android app uses the LiveKit Android SDK to connect to self-hosted `livekit-server`, which routes audio between the user and the Sophia Agent Worker (a separate Python process that calls out to model servers for STT/LLM/TTS). A small token-mint backend issues JWTs to the app. XREAL glasses provide the AR display, audio I/O on supported models, and (on Air 2 Ultra/Light) a camera."

---

## Q6 (2026-05-13): I ran the `my-agent` starter, opened the URL, had a working STT/LLM/TTS session. How is this actually working — I don't think I installed `livekit-server`?

**Confirmed: you did NOT install `livekit-server`. Almost nothing is actually running on your laptop.** Inspecting `my-agent/.env.local` and `src/agent.py`:

**What's local:**
- `lk` CLI (binary)
- Python `agent.py` process
- Silero VAD (small CPU model, downloaded by `agent.py download-files`)
- Turn detector (`MultilingualModel`, needs PyTorch)

**What's remote (LiveKit Cloud + Inference partners):**
- The SFU — `LIVEKIT_URL` is `wss://…livekit.cloud` (LiveKit Cloud, multi-tenant)
- STT — `inference.STT(model="deepgram/nova-3")` → Deepgram via LiveKit Inference
- LLM — `inference.LLM(model="openai/gpt-5.2-chat-latest")` → OpenAI via LiveKit Inference
- TTS — `inference.TTS(model="cartesia/sonic-3")` → Cartesia via LiveKit Inference
- Noise cancellation — `ai_coustics.audio_enhancement(QUAIL_VF_S)` — LiveKit Cloud partner

**Data flow per utterance:** browser mic → LiveKit Cloud SFU → your agent.py (Silero VAD locally) → HTTPS to LiveKit Inference (STT) → HTTPS to LiveKit Inference (LLM) → HTTPS to LiveKit Inference (TTS) → audio frames published back through LiveKit Cloud SFU → browser speaker.

Your laptop is doing inbound/outbound audio framing + tiny VAD/turn-detector models. **All GPU work is remote.** That's why it "just works."

**Implication for Sophia benchmarking:** the current setup is NOT exercising your open-source shortlist — it's running Deepgram + OpenAI + Cartesia through LiveKit Inference. Latency you observe is `network + Inference provider latency`, not your own model latency.

**To actually benchmark Sophia's shortlist, change two things:**
1. Replace `inference.STT/LLM/TTS` with direct plugin calls to your own model servers (Route A from COMPARISON Q6) — e.g. `openai_plugin.STT(base_url="http://localhost:8000/v1", model="parakeet-tdt-0.6b-v2")`.
2. Keep `LIVEKIT_URL` pointed at Cloud for now — switching to self-hosted `livekit-server` is a later phase per Q2.

**Install inventory:**

| Component | Installed where |
|---|---|
| `lk` CLI | ✅ Laptop (`brew install livekit-cli`) |
| `livekit-server` (SFU) | ❌ NOT installed — using LiveKit Cloud |
| `livekit-agents` Python framework | ✅ In `my-agent/.venv` via `uv sync` |
| Silero VAD weights | ✅ Local (downloaded by `download-files`) |
| Turn-detector weights | ✅ Local |
| STT/LLM/TTS models | ❌ Remote (LiveKit Inference proxies to Deepgram/OpenAI/Cartesia) |
| Browser Playground | ❌ Hosted web page |

---

## Q7 (2026-05-13): Where is the code for Silero VAD and the turn-detector that actually run on my machine?

### Silero VAD plugin
Source: `livekit-agents/livekit-plugins/livekit-plugins-silero/livekit/plugins/silero/`
- `vad.py` ⭐ — main `VAD` class returned by `VAD.load()`; streaming inference loop
- `onnx_model.py` — thin ONNX-runtime wrapper
- `resources/silero_vad.onnx` — model weights (in installed pkg; cloned-repo copy is a Git LFS pointer)
- Uses **onnxruntime**, not PyTorch.

Real `.onnx` weights live in your installed venv:
`my-agent/.venv/lib/python*/site-packages/livekit/plugins/silero/resources/silero_vad.onnx`

### Turn-detector plugin
Source: `livekit-agents/livekit-plugins/livekit-plugins-turn-detector/livekit/plugins/turn_detector/`
- `multilingual.py` ⭐ — `MultilingualModel` class used by `agent.py`
- `english.py` — English-only variant
- `base.py` ⭐ — abstract base, HF download logic, end-of-utterance scoring
- `models.py` — `HG_MODEL = "livekit/turn-detector"`, `ONNX_FILENAME = "model_q8.onnx"`
- Uses **onnxruntime** for inference; `transformers` only for the tokenizer.

Weights downloaded to:
`~/.cache/huggingface/hub/models--livekit--turn-detector/snapshots/<sha>/onnx/model_q8.onnx`

### The PyTorch warning is benign
`[transformers] PyTorch was not found ...` is `transformers` library being defensive — turn-detector only needs the tokenizer subset (works without PyTorch). Inference runs on ONNX. **You can ignore the warning; do NOT need to `uv add torch` unless something else requires it.**

### Reading order to internalize VAD + turn detection
1. `silero/vad.py` — `VADStream._main_task` loop (per-30ms ONNX inference, speech/silence decision)
2. `silero/onnx_model.py` — the actual ONNX call (tiny)
3. `turn_detector/base.py` — `_predict_eou` and scoring (end-of-utterance based on recent transcript)
4. `turn_detector/multilingual.py` — thin subclass wiring base.py to the multilingual model

### What truly runs on your CPU per utterance
- Silero VAD: ONNX forward pass per ~30 ms audio frame → speech/silence
- Turn detector: tokenize recent transcript + small ONNX forward pass → end-of-utterance probability
- That's it. STT/LLM/TTS/noise-cancellation are all remote API calls.

---

## Q8 (2026-05-13): What are `livekit-agents[silero,turn-detector]~=1.5` and `livekit-plugins-ai-coustics~=0.2` in my `pyproject.toml`? What are they giving us from the `livekit-agents` repo?

### `livekit-agents[silero,turn-detector]~=1.5`

The bracket part is **PEP 508 "extras"** syntax — it installs the core `livekit-agents` framework **plus** two optional plugin sub-packages. From the repo's `livekit-agents/pyproject.toml`:

```
silero        = ["livekit-plugins-silero>=1.5.8"]
turn-detector = ["livekit-plugins-turn-detector>=1.5.8"]
```

Both plugin packages live in the cloned repo under `livekit-plugins/`:

| Plugin | What it gives you | Source in repo |
|---|---|---|
| `livekit-plugins-silero` | **Silero VAD** — local ONNX voice activity detector. Decides per ~30 ms audio frame whether the user is speaking. Used as `vad=silero.VAD.load(...)` in `AgentSession`. Apache 2.0, runs on CPU via onnxruntime. | `livekit-plugins/livekit-plugins-silero/livekit/plugins/silero/` — `vad.py`, `onnx_model.py`, `resources/silero_vad.onnx` |
| `livekit-plugins-turn-detector` | **LiveKit's end-of-utterance detector** — small ONNX model that reads the recent transcript and predicts whether the user is done speaking (smarter than pure silence timeout). Used as `turn_detection=turn_detector.MultilingualModel()`. Apache 2.0, onnxruntime. | `livekit-plugins/livekit-plugins-turn-detector/livekit/plugins/turn_detector/` — `base.py`, `multilingual.py`, `english.py`. Weights downloaded from HF: `livekit/turn-detector` → `model_q8.onnx` |

These are the **two pieces that actually run on the laptop** in the current setup. Everything else (STT/LLM/TTS) is currently hitting LiveKit Inference over HTTPS.

### `livekit-plugins-ai-coustics~=0.2`

This one is **different — it is NOT in the cloned `livekit/agents` repo.** Inspecting the installed package in the venv:

```
/my-agent/.venv/.../livekit/plugins/ai_coustics/__init__.py
# Copyright © 2025 LiveKit, Inc. All rights reserved.
# Proprietary and confidential.
```

Files include a precompiled `libplugins_ai_coustics_uniffi.dylib` binary, and the default auth is `Auth.livekit_cloud()` — so it **requires LiveKit Cloud credentials to work**.

In `agent.py` it's the `ai_coustics.audio_enhancement(QUAIL_VF_S)` line. The plugin exposes:
- `audio_enhancement(...)` — enhancer object you drop into `AgentSession`
- `VAD` — ai-coustics' own VAD (alternative to Silero)
- Models: `EnhancerModel.QUAIL_L`, `QUAIL_VF_S`, `ROOK_S` (and deprecated `SPARROW_S`)

**This is the Cloud-locked piece** flagged in Q1–Q2 above. When going OSS self-hosted in production, this plugin must be removed (auth fails without LiveKit Cloud) and replaced with **DeepFilterNet 3** (~90% of Krisp/ai-coustics quality, Apache 2.0) or Silero noise suppression. The starter's own README confirms: *"If you choose to self-host, you'll need to also use model plugins instead of LiveKit Inference and will need to remove the LiveKit Cloud noise cancellation plugin."*

### Summary table

| Dep in `pyproject.toml` | OSS or proprietary | Runs locally | Used as | Removable for OSS prod? |
|---|---|---|---|---|
| `livekit-agents` (core) | Apache 2.0 | Yes | Framework + `AgentSession` | Keep |
| `[silero]` extra → `livekit-plugins-silero` | Apache 2.0 | Yes (ONNX on CPU) | `vad=silero.VAD.load()` | Keep |
| `[turn-detector]` extra → `livekit-plugins-turn-detector` | Apache 2.0 | Yes (ONNX on CPU) | `turn_detection=turn_detector.MultilingualModel()` | Keep |
| `livekit-plugins-ai-coustics` | **Proprietary, Cloud-locked** (bundled `.dylib`, but auth required) | Local binary call, but auth gated by LiveKit Cloud | `ai_coustics.audio_enhancement(...)` | **Remove + replace with DeepFilterNet 3 or Silero noise suppression** |

### Takeaway
The three deps split cleanly: **two OSS local-CPU helpers** (Silero VAD + turn detector) that you keep forever, and **one Cloud-locked enhancer** (ai-coustics) that has to go when self-hosting. The `[extras]` syntax is just a uv/pip convention for pulling sibling plugin packages alongside the core framework.

---

## Q9 (2026-05-13): I installed `livekit-plugins-silero`, but in `my-agent/.venv` it shows up as `livekit/plugins/silero/` with a `resources/` folder. Why the rename? Are these two different things or the same?

**Same thing, two naming systems.** Standard Python packaging confusion.

### The two names

| Name type | Example | Where you see it |
|---|---|---|
| **Distribution name** (PyPI / pip / `pyproject.toml`) | `livekit-plugins-silero` (hyphens) | `pyproject.toml`, `pip install …`, PyPI page, `.dist-info` folder name |
| **Import name** (what Python actually loads) | `livekit.plugins.silero` → folder `livekit/plugins/silero/` | `import` statements, on-disk site-packages layout |

### Evidence from the venv

```
.venv/lib/python3.12/site-packages/
├── livekit/                                  ← import-path folder (shared namespace)
│   ├── agents/
│   ├── api/
│   ├── plugins/                              ← Python namespace package
│   │   ├── silero/        ← installed by livekit-plugins-silero
│   │   ├── turn_detector/ ← installed by livekit-plugins-turn-detector
│   │   └── ai_coustics/   ← installed by livekit-plugins-ai-coustics
│   ├── protocol/
│   └── rtc/
├── livekit_plugins_silero-1.5.8.dist-info/         ← pip metadata "receipt"
├── livekit_plugins_turn_detector-1.5.8.dist-info/
└── livekit_plugins_ai_coustics-0.2.13.dist-info/
```

### Why it works this way

`livekit.plugins` is a Python **namespace package**. Multiple separate PyPI distributions (silero, turn_detector, ai_coustics, openai, deepgram, cartesia, …) each unpack their contents into the shared `livekit/plugins/<name>/` tree on disk, even though they came from different pip packages.

Pip uses the **distribution name** to download and track installs (each gets its own `*.dist-info` folder). Python's importer doesn't know or care about distribution names — it only resolves dotted import paths against folders on `sys.path`. So `from livekit.plugins import silero` only needs `livekit/plugins/silero/__init__.py` to exist; the PyPI source is irrelevant at import time.

### What happened when `uv sync` ran `livekit-agents[silero,turn-detector]`

1. uv pulled three distributions from PyPI: `livekit-agents`, `livekit-plugins-silero`, `livekit-plugins-turn-detector` (plus `ai-coustics` from its own line).
2. Each one unpacked its files into the shared `livekit/...` tree on disk.
3. The `.dist-info` directories record "which distribution installed which files" so uv/pip can uninstall cleanly later.

### Are the cloned repo's silero files the same as the venv's?

Yes — same content, different role:
- **Cloned repo** (`livekit-agents/livekit-plugins/livekit-plugins-silero/livekit/plugins/silero/`) — the **source** you can read and modify. `silero_vad.onnx` in `resources/` is a **Git LFS pointer** until `git lfs pull` fetches the real bytes.
- **Venv copy** (`.venv/.../livekit/plugins/silero/`) — the **installed copy** uv pulled from PyPI. The `.onnx` is the real binary file, already usable.

Both came from the same upstream release; the cloned repo is the source-of-truth for reading code, the venv copy is what actually runs.

### General rule for any LiveKit plugin

PyPI name `livekit-plugins-<x>` → import path `livekit.plugins.<x>` → on-disk folder `livekit/plugins/<x>/`. Hyphens become dots become slashes. The pattern repeats for all 69 plugins in the repo.

---

## Q10 (2026-05-13): Before testing STT/TTS swaps, can I swap the LLM in `my-agent` with my own RAG endpoint and run the agent?

**Yes — completely doable, and a smart first swap.** It isolates one change at a time and proves the plumbing before touching STT/TTS. To LiveKit, the RAG endpoint is just "an LLM that happens to know things" — the framework doesn't care whether retrieval happens inside it.

### Two ways to wire it in

**A. RAG endpoint is OpenAI-compatible (`POST /v1/chat/completions`, streaming) → zero custom code:**

```python
from livekit.plugins import openai

session = AgentSession(
    vad=silero.VAD.load(),
    stt=...,                      # leave as-is (Deepgram via Inference for now)
    llm=openai.LLM(
        base_url="https://your-rag-endpoint/v1",
        api_key="...",
        model="your-rag-model-name",
    ),
    tts=...,                      # leave as-is (Cartesia via Inference for now)
)
```

STT pipes the user transcript in as `messages`; the endpoint retrieves + answers internally; the streamed response goes to TTS.

**B. RAG endpoint speaks a custom protocol → subclass `livekit.agents.llm.LLM`:**

Implement a small class that takes the message history, hits the endpoint, yields chunks. Reference impls: `livekit-agents/livekit-agents/livekit/agents/llm/llm.py` (base class) + `livekit-plugins/livekit-plugins-openai/.../llm.py` (real implementation to copy from).

### Two design choices to make

**1. "RAG-inside-LLM" vs "RAG as a tool."**

| Choice | What | Trade-off |
|---|---|---|
| **Inside** (Approach A) | Every user turn hits the endpoint; it always retrieves | Simplest. LiveKit sees a normal LLM. Wastes retrieval on small talk. |
| **As a tool** | Use any generic LLM + give it a `@function_tool` `search_docs(query)`; LLM decides when to retrieve | More flexible (handles greetings without hitting KB). Needs an LLM that supports function calling. |

**For Phase 2 benchmarking, start with "inside"** — fewer moving parts. Move to "as a tool" later if you want the LLM to skip retrieval on greetings/chitchat.

**2. Streaming.** Voice agents are extremely latency-sensitive. If the RAG endpoint returns only after full retrieval+generation (single JSON response), TTFB will be ~1–3 s and TTS will feel sluggish. If it streams tokens (SSE / chunked), LiveKit can start TTS on the first sentence and the user perceives ~300–600 ms. **Confirm the endpoint streams** before plugging it in — it's the difference between "fine" and "unusable."

### What to check before wiring

| Question | Why it matters |
|---|---|
| Is the endpoint OpenAI-compatible? | Decides Approach A (zero code) vs B (custom plugin). |
| Does it stream tokens (SSE / chunked)? | Without streaming, TTFB is bad and TTS is choppy. |
| Does it support `messages[]` (chat) or only `prompt` (completion)? | LiveKit speaks chat-format. Completion-only needs a small adapter. |
| First-token + total latency over your network? | Sets the floor for the whole pipeline. |
| Does it support function calling? | Only needed if going Approach B (RAG-as-tool) later. |

### Recommended first concrete step

1. Identify the shape of the RAG endpoint (OpenAI-compatible? streaming? URL pattern?).
2. Swap `inference.LLM(...)` → `openai.LLM(base_url=...)` in `src/agent.py` (one-line change if Approach A applies).
3. Run `uv run python src/agent.py dev`, talk to it in the Playground, confirm: STT still works, RAG answers come back, TTS plays them. No STT/TTS changes yet.
4. Add timing logs (`before_llm_cb` / `before_tts_cb`) to measure per-stage latency before swapping STT/TTS.

### Why this is the right first swap for Sophia
- Isolates one change — if it breaks, the cause is unambiguous.
- Validates that custom plugins work inside `AgentSession` at all.
- Lets the rest of Phase 2 (STT/TTS swaps) run against the *real* RAG brain, not a stand-in LLM, so latency/quality numbers are meaningful.

---

## Q11 (2026-05-13): If I connect my RAG deployed on AWS + AWS-hosted STT + AWS-hosted TTS as the three plugins in `my-agent`, do I still need LiveKit Cloud?

**Short answer: Yes — you still need an SFU somewhere, either LiveKit Cloud (free tier is fine) or self-hosted `livekit-server`. Plugins don't replace the SFU; they're a separate layer.**

### Why — decompose what LiveKit Cloud actually does

Cloud bundles several services. Plugins only replace ONE of them:

| Layer | What it does | What replaces it when bringing AWS STT/LLM/TTS? |
|---|---|---|
| **SFU (media routing)** | Routes audio WebRTC packets between browser/phone and the agent process. `LIVEKIT_URL=wss://…` points here. | **Nothing in plugins replaces this.** Still required — either Cloud or self-hosted `livekit-server`. |
| **LiveKit Inference** (STT/LLM/TTS proxy) | Hosted Deepgram/OpenAI/Cartesia behind LiveKit auth | ✅ Not needed — custom AWS plugins handle STT/LLM/TTS directly. |
| **Noise cancellation (ai-coustics)** | Cloud-locked enhancer | ⚠️ Plugin still needs Cloud auth — remove it (or replace with DeepFilterNet 3 / Silero noise suppression). |
| **Observability dashboards** | Web UI for sessions/latency/eval | Optional. Wire OTel → Grafana yourself if needed. |
| **Auth/token issuance** | API key+secret used by your token-mint to issue JWTs to clients | Same secrets work whether against Cloud SFU or self-hosted SFU — just point `LIVEKIT_URL` at the right place. |
| **Cloud Agents (hosted worker)** | Runs `agent.py` on their infra | Optional. You can run `agent.py` on your laptop or any VPS. |

### The mental model — three orthogonal layers

- **Network layer (must exist somewhere):** SFU = LiveKit Cloud **OR** self-hosted `livekit-server`.
- **Audio enhancement layer (optional):** noise cancellation = ai-coustics (Cloud-only) **OR** DeepFilterNet 3 **OR** Silero **OR** nothing.
- **Model layer (you bring):** STT + LLM + TTS = any plugin pointing anywhere (your AWS endpoints, localhost, Replicate, etc.).

Plugins live in the model layer. Swapping them doesn't free you from needing the SFU.

### Two options for the specific AWS-everywhere case

**Option 1 — Keep LiveKit Cloud SFU (recommended during benchmarking):**
- `LIVEKIT_URL=wss://…livekit.cloud` stays as-is.
- Swap `inference.STT` / `inference.LLM` / `inference.TTS` → three custom plugins (or `livekit-plugins-aws` if it covers AWS Transcribe/Polly — check `ls livekit-agents/livekit-plugins/ | grep aws`).
- **Remove the `ai_coustics.audio_enhancement(...)` line** — that's the only remaining Cloud-locked piece. Replace with nothing for now, or DeepFilterNet 3 later.
- Result: Cloud is network-layer only. All inference is AWS. No LiveKit per-minute Inference cost. Free tier handles benchmarking traffic.

**Option 2 — Fully self-hosted:**
- Run `docker run livekit/livekit-server` in your AWS VPC (or locally for dev).
- Set `LIVEKIT_URL=ws://your-server:7880`.
- Generate your own API key/secret in the server config.
- Same plugins, same agent code. Zero Cloud dependency.
- Worth it for production; overkill for benchmarking.

### Recommendation
- Phase 2 benchmarking: **Option 1.** SFU free, zero setup, identical code path. Just remove the ai-coustics line.
- Production launch on XREAL+Android: **Option 2,** alongside everything in Q2 (regional servers, TURN, DeepFilterNet 3, observability stack).

### Architecture visual

```
With AWS RAG + AWS STT + AWS TTS:

[Browser / Android client]
       │ WebRTC
       ▼
[ SFU ]   ← still LiveKit — Cloud OR self-hosted livekit-server
       │
       ▼
[ Your agent.py worker ]
       │ HTTPS
       ├──► AWS STT       (you bring)
       ├──► AWS RAG/LLM   (you bring)
       └──► AWS TTS       (you bring)
```

The SFU is the unchanged middle box. Plugins only change the right column.

---

## Q12 (2026-05-13): My RAG app is deployed on AWS. From local I can hit it like this — can I use this in place of the LLM in `my-agent`?

```bash
curl -s -X POST localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What is the revenue breakdown?", "ground_truth": "..."}' | jq
```

**Yes — but not with the zero-code path. You need to write a small custom LLM plugin (Approach B from Q10), and there are three real concerns to address first.**

### Why not Approach A

The endpoint is **not OpenAI-compatible**. OpenAI-shape expects:
```
POST /v1/chat/completions
{"model": "...", "messages": [{"role": "user", "content": "..."}], "stream": true}
```
This one is:
```
POST /query
{"query": "...", "ground_truth": "..."}
```
Different URL, different field names, different request body. `openai.LLM(base_url=...)` won't speak this. → subclass `livekit.agents.llm.LLM`.

### Three concerns to flag before wiring

**1. Streaming — almost certainly missing.** `curl … | jq` suggests one JSON blob returned after full retrieval+generation. For voice agents this is the latency killer: TTS can't start until the whole answer is back. Expect TTFB ~1–3 s vs ~300–600 ms with streaming.

Options:
- Accept for first wiring (working but laggy).
- Add SSE / chunked streaming on the AWS side (real fix).
- Fake-stream client-side: plugin receives full string, emits sentence-by-sentence (smoother TTS, doesn't fix TTFB).

**2. Conversation context — single-turn endpoint.** `{"query": "..."}` takes only the latest user utterance. Voice conversations are multi-turn — by turn 3 the agent should remember turns 1 and 2. This endpoint as shown forgets every prior turn.

Options:
- Plugin flattens chat history into the `query` string (`"User: hi\nAssistant: hello\nUser: …"`). Hacky but works.
- Add a `messages[]` or `history[]` field to the AWS endpoint (cleaner).
- Decide it doesn't matter (each RAG query is genuinely independent).

**3. `ground_truth` looks like an eval field, not a production one.** A `ground_truth` parameter in the request body strongly suggests this endpoint is **built for benchmarking** — pass the expected answer alongside the query so the server scores itself. That's not the shape of a production query endpoint.

Worth confirming:
- Is there a separate production endpoint (e.g. `/answer` or `/chat` without `ground_truth`)?
- Or is `/query` doing double duty and `ground_truth` is optional?
- Does wiring `/query` with `ground_truth=""` give correct answers, or does it degrade quality?

### Plugin sketch (~40 lines)

```python
# src/plugins/aws_rag.py
from livekit.agents import llm
import aiohttp

class AwsRagLLM(llm.LLM):
    def __init__(self, url: str):
        super().__init__()
        self._url = url

    def chat(self, *, chat_ctx, fnc_ctx=None, **kwargs):
        return AwsRagStream(self, chat_ctx, self._url)

class AwsRagStream(llm.LLMStream):
    def __init__(self, llm, chat_ctx, url):
        super().__init__(llm, chat_ctx=chat_ctx, fnc_ctx=None)
        self._url = url

    async def _run(self):
        latest = self._chat_ctx.messages[-1].content   # or flatten history
        async with aiohttp.ClientSession() as s:
            async with s.post(self._url, json={"query": latest, "ground_truth": ""}) as r:
                data = await r.json()
        # emit as a single chunk; replace with streaming if endpoint supports it
        self._event_ch.send_nowait(llm.ChatChunk(
            choices=[llm.Choice(delta=llm.ChoiceDelta(role="assistant", content=data["answer"]))]
        ))
```

(Exact signatures shift between `livekit-agents` versions — verify against `livekit-agents/livekit-agents/livekit/agents/llm/llm.py` and `livekit-plugins/livekit-plugins-openai/.../llm.py` before pasting.)

Wire it in `src/agent.py`:
```python
from plugins.aws_rag import AwsRagLLM
session = AgentSession(
    ...,
    llm=AwsRagLLM(url="http://localhost:8000/query"),
    ...,
)
```

### Open questions before building the real plugin

1. **Is `localhost:8000` an SSH tunnel / port-forward to AWS, or is the RAG app also running locally?** The agent worker must actually be able to reach it — `localhost` only works if the worker runs on the same machine.
2. **What is the response JSON shape?** Sketch assumes `{"answer": "..."}` — need the real field name (and whether sources/citations come alongside).
3. **Is `ground_truth` required or optional? Is the endpoint production-serving or eval-only?**

Answers to these unlock the actual plugin implementation.

---

## Q13 (2026-05-13): In the current pipeline (LiveKit + OpenAI LLM), who maintains the chat history — the OpenAI model or LiveKit?

**LiveKit maintains the chat history client-side. The OpenAI model is completely stateless — zero memory between calls. Every turn, LiveKit re-sends the entire conversation.**

### Why — chat-completions APIs are stateless HTTP

Standard LLM chat-completions endpoints (OpenAI, Anthropic, Mistral, vLLM, anything `/v1/chat/completions`-shaped) are stateless. Every request must include the full `messages` array:

```
POST /v1/chat/completions
{
  "model": "gpt-5.2-chat-latest",
  "messages": [
    {"role": "system",    "content": "You are a helpful voice assistant. Be brief."},
    {"role": "user",      "content": "what's the weather?"},
    {"role": "assistant", "content": "I don't have weather data."},
    {"role": "user",      "content": "what about news?"}     ← latest turn
  ],
  "stream": true
}
```

The server-side model does NOT remember prior turns. Continuity exists only because the **client re-sends the full history every turn**.

### LiveKit is that client — owns `ChatContext`

Inside `AgentSession`, LiveKit owns a `ChatContext` object that holds the running history. Per user utterance:

```
1. User speaks
2. STT plugin streams transcript chunks → final transcript
3. Turn detector fires (end of user turn)
4. LiveKit appends {role: "user", content: <transcript>} to ChatContext
5. LiveKit calls llm.chat(chat_ctx=<entire history>)
6. Plugin POSTs the full messages[] to OpenAI
7. OpenAI streams tokens back
8. LiveKit appends the full assistant response to ChatContext
9. Tokens stream to TTS → audio out
10. Wait for next user turn → back to step 1
```

`ChatContext` lives in `livekit-agents/livekit-agents/livekit/agents/llm/chat_context.py`; owned by `AgentSession` (`voice/agent_session.py`). The `Agent(instructions="…")` becomes the first `system` message.

### Exception — Realtime / audio-LLM APIs

OpenAI Realtime, Gemini Live, and similar audio-in-audio-out APIs DO keep session state server-side over a persistent WebSocket. The model server tracks the conversation across audio chunks within one session. LiveKit treats those via a separate code path (`livekit-plugins-openai/.../realtime/`), not the chat-completions LLM. The current `my-agent` (`inference.LLM(model="openai/gpt-5.2-chat-latest")`) does NOT use the realtime path — it uses standard chat-completions, so history is LiveKit-owned.

### Why this matters for the AWS RAG endpoint (links to Q12)

Precise reason a `/query`-shaped endpoint loses context:
- LiveKit IS tracking the full conversation in `chat_ctx`.
- When it calls the custom plugin, it hands over the entire history.
- But an endpoint signature like `{"query": "..."}` only accepts the latest turn.
- So the plugin either:
  - Plucks just the last user message → loses context.
  - Flattens entire history into the `query` string → keeps context but eats tokens server-side.
  - Or the AWS endpoint is upgraded to accept `messages[]` / `history[]`.

The information is available — LiveKit hands it to the plugin. The question is whether the plugin and the AWS endpoint preserve it.

### Quick mental test

```python
def chat(self, *, chat_ctx, ...):
    print(chat_ctx.messages)
    # Turn 1: [{system}, {user: "hi"}]
    # Turn 2: [{system}, {user: "hi"}, {assistant: "hello"}, {user: "what's the weather?"}]
    # Turn 3: full history again, growing each turn
```

That's the proof — LiveKit re-presents the whole conversation on every call.

### Implications
1. **Context-window cost grows per turn.** Long conversations send more tokens per request. Larger pipelines use `Agent.truncate_history()` or summarization to cap it.
2. **History is programmatically editable.** `chat_ctx.append(role=…, text=…)` or splicing messages — useful for injecting tool results, system reminders, or trimming.
3. **Voice agents don't naturally use the Realtime API path** unless explicitly chosen (`openai.realtime.RealtimeModel(...)` instead of `openai.LLM(...)`). The starter is chat-completions-style → LiveKit-owned history.

---

## Q14 (2026-05-13): So with Realtime models the model maintains history, but with others LiveKit sends history. In my case, even if LiveKit sends history, I still need to check whether my RAG model can actually USE it. Right?

**Exactly right on both counts.** Two separable questions, most people only think about the first:

| Layer | Question | Decided by |
|---|---|---|
| **Transport / API shape** | Will LiveKit's payload reach the model? | The AWS endpoint's request schema |
| **Model behavior** | Once the model sees the history, does it actually *use* it? | The internals of the RAG pipeline |

### Layer 1 — the API contract

The endpoint signature `{"query": "...", "ground_truth": "..."}` accepts ONE string. Even if LiveKit hands the plugin a 20-message `chat_ctx`, only what gets crammed into `query` reaches the AWS side. Two bridges:

| Bridge | What | Cost |
|---|---|---|
| **Flatten history into `query`** | Plugin joins turns into one string: `"User: hi\nAssistant: hello\nUser: what's the revenue breakdown?"` | Pollutes the input. Retrieval embedding gets mixed with greeting tokens. Generation may or may not parse the format. |
| **Upgrade the endpoint** | Add `messages[]` / `history[]` field server-side; pipeline routes them | Cleanest. Requires touching the AWS app. |

### Layer 2 — RAG internals (the part people miss)

A typical RAG pipeline has two stages:
1. **Retrieval:** embed the input → search vector DB → return top-k chunks
2. **Generation:** stuff chunks + input into an LLM prompt → generate answer

If history is flattened into the `query` field:

- **Retrieval stage:** the embedder sees the whole flattened conversation. The embedding vector is dominated by greeting + prior-assistant token mass. The actual question intent gets diluted → **retrieval quality drops**, possibly returning wrong chunks.
- **Generation stage:** if the LLM is chat-tuned, it may recover and answer correctly. If completion-only, probably not.

The properly designed pattern — **"Conversational RAG"** — separates the two:
- A query-rewrite step turns the follow-up into a standalone query (e.g. *"what about Q3?"* + prior context → *"what is Anthropic's revenue in Q3?"*), then retrieves on the rewritten query.
- History feeds the generation step only, not retrieval.

### Three possible truths for the endpoint

| Truth | Symptom | Action |
|---|---|---|
| **A. Endpoint actually accepts `messages[]`** | The curl is a minimal example; full schema has more fields | Confirm by checking the AWS app's source or OpenAPI spec |
| **B. Single-turn endpoint, use case is fine with that** | Each query is independent — "what is X?" doesn't need prior context | Just plug latest user turn as `query`. No history needed. |
| **C. Truly single-turn AND follow-ups need context** | "What about for Q3?" can't be answered without knowing topic was revenue | Either flatten (cheap, lossy) or upgrade the AWS app (clean) |

### Empirical test (before any LiveKit wiring)

Three curl calls in sequence:

```bash
# Test 1: standalone — baseline
curl -X POST localhost:8000/query \
  -d '{"query": "what is Anthropic'\''s revenue?", "ground_truth": ""}'

# Test 2: follow-up that NEEDS context, with no context provided
curl -X POST localhost:8000/query \
  -d '{"query": "what about for last quarter?", "ground_truth": ""}'
# answers correctly → server keeps session somehow (unlikely)
# answers nonsensically or asks "for what?" → confirms single-turn

# Test 3: flatten history manually
curl -X POST localhost:8000/query \
  -d '{"query": "Earlier you said Anthropic'\''s revenue was $X. Now: what about for last quarter?", "ground_truth": ""}'
# works → client-side flattening is viable
# retrieval still off → need server-side history support
```

Result tells which truth applies and which bridge to build.

### Also check the RAG app itself

Before any LiveKit work, open the AWS RAG codebase and answer:
1. Is there a separate `/chat` or `/answer` endpoint with a richer schema? (`/query` may be eval-only.)
2. Does the pipeline have a query-rewrite step?
3. Is retrieval done on raw input or a processed query?
4. What model does generation? Chat-tuned or completion?

These dictate whether the plugin can solve this alone or whether the AWS app needs work first.

### Bottom line

> Layer 1: LiveKit hands you full history — you can always *send* it.
> Layer 2: Whether the RAG model *uses* it correctly is a property of the pipeline, not LiveKit's.

For the Phase 2 test matrix to be meaningful, the RAG model must handle multi-turn — otherwise voice conversations feel broken even with perfect STT/TTS. Confirming this upfront is the right instinct.

---

## Q15 (2026-05-14): Reverse-engineering `my-agent` — `Assistant` inherits from `Agent`; `Agent.__init__` takes `instructions/id/chat_ctx/…` and calls `_migrate_turn_handling()` from `turn.py`. So `Assistant()` gets all of those properties.

**All three claims confirmed against source.**

| Claim | Source location |
|---|---|
| `Assistant` inherits from `Agent` | `my-agent/src/agent.py:23` — `class Assistant(Agent):` |
| `Agent.__init__` takes `instructions`, `id`, `chat_ctx`, plus STT/LLM/TTS/VAD/turn-handling | `livekit-agents/.../voice/agent.py:36–57` |
| `_migrate_turn_handling` is from `turn.py` | Defined at `voice/turn.py:212`; imported at `voice/agent.py:19` |

### What actually gets set on `Assistant` after `super().__init__()`

`Assistant.__init__` passes ONLY `llm=` + `instructions=`. So:

```python
self._id                     = "assistant"                # camel_to_snake("Assistant"), since type(self) is not Agent
self._instructions           = "<textwrap.dedent block>"
self._tools                  = []                         # no tools passed + no @function_tool methods yet
self._chat_ctx               = ChatContext.empty()        # none passed
self._turn_detection         = NOT_GIVEN
self._stt                    = NOT_GIVEN                  # not at Agent level
self._llm                    = inference.LLM(model="openai/gpt-5.2-chat-latest")
self._tts                    = NOT_GIVEN
self._vad                    = NOT_GIVEN
self._allow_interruptions    = NOT_GIVEN
self._interruption_detection = NOT_GIVEN
self._min_endpointing_delay  = NOT_GIVEN
self._max_endpointing_delay  = NOT_GIVEN
self._turn_handling          = {}
self._mcp_servers            = NOT_GIVEN
self._activity               = None                       # set later by AgentSession activation
```

### Conceptual key — Agent vs AgentSession ownership

**Both `Agent` AND `AgentSession` can hold STT / LLM / TTS / VAD / turn-handling.** They're not duplicates — it's a per-agent override layered on a session default.

| Lives on | Role |
|---|---|
| `AgentSession(stt=…, llm=…, tts=…, vad=…)` | **Defaults** for the whole session. Used when an agent doesn't specify its own. |
| `Agent(stt=…, llm=…, tts=…, vad=…)` | **Per-agent override.** Lets workflows hand off between agents that use different models. |

In current `my-agent`:
- `Assistant(Agent)` sets `llm=` only.
- `entrypoint()` creates `AgentSession(stt=…, tts=…, vad=…, …)` with the rest.
- Runtime resolution: "for this active agent, do they have STT? No → use session's. LLM? Yes (gpt-5.2) → use theirs. TTS? No → use session's. VAD? No → use session's."

This is why the Assistant works end-to-end despite only setting `llm`.

### What `_migrate_turn_handling` is doing

Backwards-compat shim. Old API had four flat kwargs (`turn_detection`, `min_endpointing_delay`, `max_endpointing_delay`, `allow_interruptions`); new API has one structured `turn_handling` dict. `_migrate_turn_handling` reads the old args and packages them into the new shape so deprecated calls keep working. If nothing is passed, it returns an empty dict and the defaults from `AgentSession` win.

### Auto-tool-pickup (preview of Q16/17/18)

`self._tools = [*tools, *find_function_tools(self)]` (line 76) — why `@function_tool`-decorated methods on `Assistant` get auto-registered. Base class introspects the instance at construction time and pulls in decorated methods. See Q16–Q18 for the internals.

---

## Q16 (2026-05-14): In `Agent.__init__`, why `type(self) is not Agent` rather than `isinstance(self, Agent)`?

```python
if type(self) is Agent:
    self._id = "default_agent"
else:
    self._id = id or misc.camel_to_snake_case(type(self).__name__)
```

**Strict identity check, not subtype check.**

- `type(self) is Agent` — True **only** when someone instantiates the bare `Agent` class directly: `Agent(instructions="…")`.
- For `class Assistant(Agent)` + `Assistant()`, `type(self)` returns `Assistant`, not `Agent`. The check evaluates **False** → falls to the `else` branch.

**Why not `isinstance(self, Agent)`?** Because `isinstance` returns True for the bare class AND every subclass — it can't distinguish "is this raw Agent?" from "is this a subclass of Agent?" `type(x) is X` is strict — only matches the exact class.

### Effect

| Construction | id becomes |
|---|---|
| `Agent(instructions="…")` (rare direct use) | `"default_agent"` (constant) |
| `Assistant()` subclass, no explicit id | `"assistant"` (camel→snake of class name) |
| `Foo(id="my-agent-1")` subclass with explicit id | `"my-agent-1"` |

**Reason:** workflows/handoffs let one session host multiple agents — each needs a unique ID to route turns and log telemetry. Auto-naming from the subclass name covers the common case. The `"default_agent"` fallback handles the trivial single-Agent use where naming doesn't matter.

---

## Q17 (2026-05-14): What does an Agent instance get — full inventory of methods, properties, and variables?

### Instance variables (private state, set in `__init__`)

```
_id  _instructions  _tools  _chat_ctx  _turn_detection
_stt  _llm  _tts  _vad
_allow_interruptions  _interruption_detection
_min_consecutive_speech_delay  _use_tts_aligned_transcript
_min_endpointing_delay  _max_endpointing_delay
_turn_handling  _mcp_servers
_activity         ← set by AgentSession activation, NOT in __init__
```

### Public properties (read access)

| Property | Returns |
|---|---|
| `id` | str — the agent's identifier |
| `label` | str — alias for `id` (used in logs/telemetry) |
| `instructions` | str — system prompt |
| `tools` | list — copy of registered tools |
| `chat_ctx` | read-only `ChatContext` view of conversation history |
| `interruption_detection` | "adaptive" / "vad" / NOT_GIVEN |
| `realtime_llm_session` | active realtime session (when using Realtime API) |
| `turn_detection` | turn detector mode (also has a setter) |
| `stt` / `llm` / `tts` / `vad` | the model components (NOT_GIVEN if defaulting to session's) |
| `mcp_servers` | MCP tool servers |
| `allow_interruptions` | bool |
| `min_endpointing_delay` / `max_endpointing_delay` / `min_consecutive_speech_delay` | float — VAD/turn timing knobs |
| `use_tts_aligned_transcript` | bool |
| `session` | the parent `AgentSession` |

### Async public methods (call to mutate state)

| Method | What it does |
|---|---|
| `update_instructions(instructions)` | Swap the system prompt mid-session |
| `update_tools(tools)` | Replace the tool list |
| `update_chat_ctx(...)` | Edit conversation history (splice/insert/trim) |

### Override hooks (subclass these for custom behavior)

| Hook | Fired when |
|---|---|
| `on_enter()` | This agent becomes the active agent in the session |
| `on_exit()` | Session leaves this agent (handoff away) |
| `on_user_turn_completed(turn_ctx, new_message)` | After a user turn ends, before LLM call — last chance to mutate the message or chat_ctx |

### Pipeline node methods (override to customize each stage)

| Node | What flows through |
|---|---|
| `stt_node(audio, model_settings)` | Audio frames → text transcript |
| `llm_node(chat_ctx, tools, model_settings)` | Chat context + tools → response stream |
| `transcription_node(text, model_settings)` | Post-process generated text before TTS |
| `tts_node(text, model_settings)` | Text → audio frames |
| `realtime_audio_output_node(audio, model_settings)` | Realtime API audio pass-through |

The default implementations in `voice/agent.py:257–512` just call the configured `stt/llm/tts` plugins. Override them to inject logic per stage (e.g. log timing, strip text, rewrite queries).

### Internal

- `_get_activity_or_raise()` — accessor for the active `AgentActivity` (runtime state machine attached when the session is live). Used by methods that need to talk to the currently-running session.

---

## Q18 (2026-05-14): How does `@function_tool` actually add a tool? `find_function_tools` is in `tool_context.py` — what's happening internally so the agent picks it up automatically?

**The decorator does NOT just set a flag. It REPLACES the method with a `FunctionTool` instance — and that instance is a Python descriptor.**

### Step 1 — at class-definition time, the decorator runs

`function_tool` at `tool_context.py:274` resolves to `deco_func`:

```python
def deco_func(func):
    from docstring_parser import parse_from_object
    docstring = parse_from_object(func)
    info = FunctionToolInfo(
        name=name or func.__name__,
        description=description or docstring.description,
        flags=flags,
    )
    return FunctionTool(func, info)        # returns a CLASS INSTANCE, not a function
```

So for:
```python
class Assistant(Agent):
    @function_tool
    async def lookup_weather(self, context, location):
        """Use this tool to look up current weather information…"""
```

At class-body evaluation, the name `lookup_weather` in the `Assistant` class dict is bound to a `FunctionTool` **instance** — not a function. The docstring is parsed at decoration time and stored in `info.description`.

### Step 2 — `FunctionTool` is a descriptor + callable

```python
def __get__(self, obj, objtype):           # descriptor protocol
    if obj is None:
        return self
    bound_tool = self.__class__(self._func, self._info, instance=obj)
    sig = inspect.signature(self._func)
    params = list(sig.parameters.values())[1:]   # drop `self`
    bound_tool.__signature__ = sig.replace(parameters=params)
    return bound_tool

def __call__(self, *args, **kwargs):       # makes it invokable
    if self._instance is not None:
        return self._func(self._instance, *args, **kwargs)   # `self` injected
    return self._func(*args, **kwargs)
```

The magic:
- `__get__` makes it a **descriptor** — when you access `assistant.lookup_weather`, Python invokes `FunctionTool.__get__(self, assistant, Assistant)` and gets a **new bound FunctionTool** with `instance=assistant`. The externally-visible signature has `self` removed.
- `__call__` makes the bound tool **invokable** — the LLM later passes argument values, and the bound tool calls the original method with `assistant` injected as `self`.

Same mechanism Python uses for regular methods (plain `function` objects are also descriptors). `@function_tool` swaps the method-descriptor for a tool-descriptor that **also carries metadata** (`__livekit_tool_info` attribute set in `FunctionTool.__init__:223`).

### Step 3 — `Agent.__init__` discovers the tool via `find_function_tools`

```python
# voice/agent.py:76
self._tools = [*tools, *find_function_tools(self)]
```

```python
# llm/tool_context.py:379
def find_function_tools(cls_or_obj):
    methods = []
    for _, member in inspect.getmembers(cls_or_obj):       # walks MRO
        if isinstance(member, (FunctionTool, RawFunctionTool)):
            methods.append(member)
        elif normalized_tool := _resolve_wrapped_tool(member):
            methods.append(normalized_tool)
    return methods
```

- `inspect.getmembers(self)` iterates every attribute reachable on the instance, walking the class hierarchy (MRO: `Assistant` → `Agent` → `object`).
- Accessing each attribute triggers the descriptor's `__get__`, which returns a **bound** `FunctionTool` (instance=assistant).
- The `isinstance(member, FunctionTool)` filter keeps only the decorated ones.
- They all land in `self._tools`.

### Step 4 — at LLM call time, tools become a JSON schema

When `llm_node` runs, the framework serializes each `FunctionTool` in `self._tools` into a schema for the LLM:
- `info.name` → schema `name`
- `info.description` (parsed from docstring) → schema `description`
- The function's signature + type hints → JSON schema `parameters` (`location: str` → `{"type": "string"}` etc.)

LLM sees the tool, decides to call it, returns a tool_call with arguments. LiveKit looks up the `FunctionTool` by name in `self._tools`, invokes `__call__` with the arguments — original method runs with `self` already bound to the Assistant instance.

### Why the descriptor pattern matters

If `@function_tool` just flagged a function with an attribute and left it as a plain function, two things would break:
1. `find_function_tools` would need to special-case detecting flagged functions vs other attributes.
2. `self` binding wouldn't work cleanly — accessing instance state from inside the tool would require manual passing.

The descriptor pattern lets the tool act exactly like a regular method (instance-bound when accessed) **and** carry metadata on the same object. Python's existing method-resolution machinery does all the heavy lifting.

### One-paragraph summary

`@function_tool` replaces the method with a `FunctionTool` instance that is both a descriptor (binds `self` on attribute access via `__get__`) and callable (invokes the original method with `self` injected via `__call__`). It parses the docstring at decoration time and stores `FunctionToolInfo(name, description, flags)`. `Agent.__init__` then uses `find_function_tools(self)` — which is `inspect.getmembers` filtered for `FunctionTool` instances — to discover and register every decorated method into `self._tools`. The framework later turns each `FunctionTool` into a JSON schema for the LLM, and on a tool call, invokes the bound instance to run the user's code.

---

## Q19 (2026-05-14): Why is there a separate nested `class default:` inside `Agent` in `voice/agent.py` (line 386)?

### The pattern

Each pipeline node on `Agent` is split into two parallel structures:

```python
class Agent:
    # Instance method — PUBLIC INTERFACE (overridable)
    def stt_node(self, audio, model_settings):
        return Agent.default.stt_node(self, audio, model_settings)   # delegates

    class default:                                                    # nested namespace
        @staticmethod                                                 # `agent` passed explicitly
        async def stt_node(agent: Agent, audio, model_settings) -> AsyncGenerator[...]:
            activity = agent._get_activity_or_raise()
            ...                                                        # actual implementation
```

Same pattern for `llm_node`, `tts_node`, `transcription_node`, `realtime_audio_output_node`. Every pipeline node has this two-layer split.

### Why split — five real reasons (weight-ordered)

**1. Subclasses can call the default cleanly from inside an override.** Strongest reason. Without `Agent.default`, the only way to call parent behavior is `super().stt_node(...)` — which has the loose union return type (async-generator OR coroutine returning generator OR coroutine returning None) and walks the MRO in confusing ways through deep inheritance. With `Agent.default`:

```python
class MyAgent(Agent):
    async def stt_node(self, audio, model_settings):
        # custom prep
        async for event in Agent.default.stt_node(self, audio, model_settings):
            yield event   # post-process
```

Returns a concrete `AsyncGenerator` — known shape. Always resolves to "the framework default" regardless of inheritance depth.

**2. Decouples interface contract from default implementation.**

| `Agent.stt_node` (instance method) | `Agent.default.stt_node` (static) |
|---|---|
| Public contract | One implementation of that contract |
| Return type: union (any override shape valid) | Return type: concrete `AsyncGenerator[...]` |
| Has "you can override this" docstring | Has `"""Default implementation for…"""` docstring |
| Overrideable | Static; not part of the polymorphism |

**3. Concrete typing for the default, broad typing for the public.**

```python
# Public (instance method) — must accept any override style
def stt_node(...) -> (
    AsyncIterable[stt.SpeechEvent | str]
    | Coroutine[Any, Any, AsyncIterable[stt.SpeechEvent | str]]
    | Coroutine[Any, Any, None]
): ...

# Default (static) — single concrete shape
async def stt_node(agent, ...) -> AsyncGenerator[stt.SpeechEvent, None]: ...
```

If the default lived directly on the instance method, the type would be either the loose union (bad for type checkers reasoning about the default path) or the strict concrete type (bad — would reject valid overrides). Splitting lets each layer have the right type.

**4. Single self-documenting source of truth.** "What does the framework do for STT by default?" → read `Agent.default.stt_node`. Alternatives like `_default_stt_node` / `_stt_node_default` bury the relationship; the nested class is an explicit "namespace of all the default implementations."

**5. Testability.** `Agent.default.stt_node(mock_agent, mock_audio, mock_settings)` works without instantiating a real Agent or wiring up an `AgentSession`. Static + explicit `agent` parameter = trivially mockable.

### Why static + explicit `agent` parameter

`@staticmethod` + `agent: Agent` as first arg (not `self`) signals:
- This isn't bound to a specific instance — it's a free function in the Agent namespace.
- Pass any agent in and it does the default behavior on it — works for tests (mock), overrides (`self`), or framework internal calls (whichever agent is active).

### One-paragraph summary

`Agent.default` is a namespace of static default implementations of the pipeline nodes; the instance methods are thin overridable wrappers that delegate to it. The split exists so subclasses can call the framework's default explicitly from inside their overrides, the type system can give the default a precise shape while the public method accepts the broader override contract, and the framework has a single self-documenting source for "what does Agent do by default."

### Distinct from "default_agent" (different concept)

Note: this is unrelated to the `"default_agent"` id constant set at `voice/agent.py:60` when `type(self) is Agent`. That's a label for the bare-Agent case in logs/telemetry. This Q19 is about the `class default:` nested namespace holding default pipeline implementations — different mechanism entirely.

---

## Q20 (2026-05-14): In `my-agent` I have `server = AgentServer()` (from `worker.py`). What happens when I instantiate it? Is it connecting to LiveKit Cloud at that point?

**No — `AgentServer()` does NO network activity. It's pure in-memory config construction.** The actual connection happens much later at `cli.run_app(server)`.

### Phase 1 — `server = AgentServer()`: pure config

`AgentServer.__init__` (`worker.py:301–382`) does only in-memory setup:

```python
self._ws_url        = ws_url or os.environ.get("LIVEKIT_URL") or ""        # just reads env
self._api_key       = api_key or os.environ.get("LIVEKIT_API_KEY") or ""
self._api_secret    = api_secret or os.environ.get("LIVEKIT_API_SECRET") or ""
self._worker_token  = os.environ.get("LIVEKIT_WORKER_TOKEN") or ""         # Cloud Agents path

self._host, self._port = host, port
self._job_executor_type = ...
self._mp_ctx = mp.get_context("spawn")    # multiprocessing context
self._entrypoint_fnc = None               # not registered yet
self._setup_fnc = setup_fnc               # prewarm callback (None at this point)

self._closed       = True                 # ← server starts CLOSED
self._draining     = False
self._connecting   = False
self._id           = "unregistered"       # ← explicitly unregistered
self._http_server  = None
self._lock         = asyncio.Lock()
```

Two giveaways that nothing has happened externally: `_closed = True` and `_id = "unregistered"`. `AgentServer` extends `utils.EventEmitter`, but no events fire at construction.

### Phase 2 — `server.setup_fnc = prewarm`

Stores the prewarm callback in `self._setup_fnc`. Will be invoked **per subprocess** later when the process pool spawns workers — that's where `silero.VAD.load()` runs (once per worker, not per call).

### Phase 3 — `@server.rtc_session(agent_name="my-agent")`

Stores `my_agent` function in `self._entrypoint_fnc` and sets `self._agent_name = "my-agent"`. Still no network. Comment at line 365 confirms only one entrypoint per AgentServer.

### Phase 4 — `cli.run_app(server)`: THIS is where everything happens

1. **CLI argv parse** — looks at `sys.argv` for `console`/`dev`/`start`/`connect` and configures accordingly.
2. **Logging + signal handlers** set up.
3. **Asyncio event loop** started.
4. **Process pool spawned** via `multiprocessing` (`spawn` on macOS, `forkserver` on Linux). Each subprocess is a worker that will run one job at a time.
5. **`prewarm` (`setup_fnc`) runs in each subprocess** — `silero.VAD.load()` loads ONNX once per worker.
6. **WebSocket opened to `LIVEKIT_URL`** — first network operation. Connects to LiveKit Cloud (`wss://…livekit.cloud`) or self-hosted (`ws://localhost:7880`).
7. **Worker registration message sent** — authenticates with `LIVEKIT_API_KEY`+`SECRET`, declares `agent_name="my-agent"`, registers as available. `_id` assigned by the server. `_closed = False`.
8. **Listens for job dispatches.** SFU dispatches a job when a participant joins a room and the metadata wants `agent_name=my-agent`.
9. **Job dispatched to a subprocess.** The pool picks an idle worker; inside that subprocess, `my_agent(ctx)` runs — `AgentSession(...)`, `session.start(agent=Assistant(), ...)`, `ctx.connect()`.

### Critical clarification — "instantiating LiveKit Cloud"

You never "instantiate LiveKit Cloud." LiveKit Cloud is a hosted SFU that already exists 24/7 (or, if self-hosted, you've spawned `livekit-server` as a separate Docker container). Your `AgentServer` **registers AS A WORKER to that already-running SFU**:

```
                  [ LiveKit SFU ]                                  ← already running
                  Cloud or self-hosted                              (you don't create it)
                        ▲
                        │ WebSocket (opened at cli.run_app)
                        │ Registers: "I'm a worker for agent_name=my-agent"
                        │
                  [ Your AgentServer ]                              ← AgentServer() makes it
                  (process pool + worker registration)               but only ACTIVE after cli.run_app
                        │
                        │ on job dispatch, spawns subprocess
                        ▼
                  [ Your entrypoint fn my_agent(ctx) ]              ← runs per user-session
                  AgentSession + session.start + connect
```

### Two connection modes in the constructor

| Path | Triggered by | Use case |
|---|---|---|
| **Standard worker** | `LIVEKIT_URL` + `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` in env | Worker runs on your machine/VPS/AWS; registers via API credentials. **What `my-agent` is doing.** |
| **Cloud-hosted agent** | `LIVEKIT_WORKER_TOKEN` env var | LiveKit Cloud hosts the worker itself (`lk agent deploy`). Separate code path. |

Sophia uses path 1.

---

## Q21 (2026-05-14): Where can the worker process live? Local laptop or fully on the cloud?

**Anywhere with outbound network access to the SFU.** The SFU doesn't care where the worker is — only that it's reachable over WebSocket.

### Four placements (all run the same `agent.py` code)

| Where | How to deploy | When to use |
|---|---|---|
| **Your laptop** | `uv run python src/agent.py dev` | Development, benchmarking, demos. What `my-agent` is doing now. |
| **Your own cloud (VPS / EC2 / GCE / Fly / Railway / Render)** | Build the Docker image (`my-agent/` ships a Dockerfile), push, deploy. `start` mode instead of `dev`. | Production where you control infra. |
| **Kubernetes / ECS on your AWS** | Same Docker image, horizontal autoscaling | Production at scale (thousands of concurrent sessions). |
| **LiveKit Cloud Agents (managed worker)** | `lk agent deploy` — LiveKit hosts the worker for you | Production hands-off; no infra management. |

The only env-var differences:

| Setting | Local laptop | Your cloud | Cloud Agents (managed) |
|---|---|---|---|
| `LIVEKIT_URL` | `wss://…livekit.cloud` (Cloud SFU) or `ws://localhost:7880` (self-hosted) | same | injected by LiveKit |
| `LIVEKIT_API_KEY/SECRET` | your keys | your keys | not used |
| `LIVEKIT_WORKER_TOKEN` | not set | not set | injected by LiveKit |
| `AgentServer` connection mode | Standard worker | Standard worker | Cloud Agents |

### Two independent placement decisions (often conflated, keep separate)

| Question | Options | Constraint |
|---|---|---|
| Where does the **SFU** live? | LiveKit Cloud OR self-hosted `livekit-server` | Must exist somewhere. |
| Where does the **worker** live? | Your laptop / your cloud / LiveKit Cloud Agents | Just needs WS reach to the SFU. |

Any combination works:

| SFU | Worker | Example |
|---|---|---|
| LiveKit Cloud | Your laptop | Current `my-agent` dev setup |
| LiveKit Cloud | Your EC2 | Production self-managed, hands-off SFU |
| LiveKit Cloud | LiveKit Cloud Agents | Fully managed (everything Cloud) |
| Self-hosted | Your EC2 | Full OSS production (Sophia's eventual target) |
| Self-hosted | Your laptop | Dev against your own SFU |

### Practical implications for Sophia

The worker is mostly **network-bound + lightweight**. It manages WebSocket connections, runs Silero VAD + turn-detector (tiny ONNX on CPU), and forwards STT/LLM/TTS calls to model servers. **It does NOT need a GPU** — the GPU work lives in the model servers it calls out to.

- **Benchmarking now:** worker = laptop. Cheap, immediate.
- **Production with XREAL/Android:** worker = a small CPU instance in your AWS VPC (next to the RAG + STT + TTS), or LiveKit Cloud Agents if hands-off. Both work functionally identically.
- **No reason to put worker on a GPU box.** GPUs go where the inference is, not where the orchestration is.

### Cloud Agents trade-offs

| Pro | Con |
|---|---|
| Zero infra to manage | Container size / memory / CPU limits set by LiveKit |
| Auto-scaling | Some plugins may be restricted |
| Built-in observability dashboards | Per-minute pricing |
| One-command deploy | Less control over network egress, VPC peering |

For Sophia's OSS-everything production goal, likely **not** Cloud Agents — but useful to know it exists for prototyping.

---

## Q22 (2026-05-14): Recap — `AgentServer()` creates a worker process that sets config for the Agent and registers to SFU; if not set, AgentSession defaults are used; VAD + turn detection live inside the worker; model inference is remote (AWS); SFU is OSS livekit-server. Right?

**Mostly right, but three pieces need tightening.**

### What's correct ✅
1. The worker is a process that registers to the SFU.
2. VAD + turn detection run **inside** the worker process — wherever that process lives, they live.
3. STT/LLM/TTS inference is remote (AWS in Sophia's case); the worker calls them over HTTPS.
4. SFU and worker placement are independent.

### Precision 1 — `AgentServer` doesn't "set config for the Agent"

`AgentServer` does **process and connection management**, not Agent configuration:

| What `AgentServer` owns | What it does NOT own |
|---|---|
| WebSocket to the SFU | The Agent's instructions |
| API key + secret + URL | The Agent's LLM/STT/TTS plugins |
| The process pool (multiprocessing) | The AgentSession's defaults |
| The registered entrypoint function | The Agent's chat context |
| `agent_name` for SFU routing | The Agent's tools |
| `setup_fnc` (prewarm callback) | |

Agent configuration comes from three other places:
1. The `Agent` subclass (your `Assistant(Agent)`) — `super().__init__(...)` sets per-agent overrides.
2. The `AgentSession(...)` constructor — session-level defaults.
3. Runtime resolution — for each pipeline node, Agent's value wins if set; otherwise Session's value is used.

```python
class Assistant(Agent):
    def __init__(self):
        super().__init__(llm=..., instructions=...)     # ← Agent config (LLM + system prompt)

session = AgentSession(stt=..., tts=..., vad=..., ...)   # ← Session defaults (STT/TTS/VAD)

server = AgentServer()                                   # ← Has nothing to do with Agent config.
                                                         #   Manages processes + WS to SFU.
```

### Precision 2 — there are TWO process layers, not one

`AgentServer` doesn't run the agent in its own process. It spawns **subprocesses** to run jobs:

```
[ AgentServer main process ]                    ← `cli.run_app(server)` runs here
  - Opens WS to SFU                              - Manages process pool
  - Registers as worker                          - Runs setup_fnc per subprocess
  - Listens for job dispatches                   - Dispatches jobs into pool
       │
       │ on job dispatch, spawn / pick from pool
       ▼
[ Worker subprocess #1 ]   [ Worker subprocess #2 ]   …
  - Runs the entrypoint      - Same code, different room/user
  - AgentSession lives here  - AgentSession lives here
  - Assistant() lives here   - Assistant() lives here
  - Silero VAD loaded here   - Silero VAD loaded here
  - Turn detector here       - Turn detector here
  - HTTPS calls to AWS       - HTTPS calls to AWS
```

`prewarm` is a callback for a reason — it runs once **per subprocess** as the subprocess spawns, so each worker has its own VAD loaded in its own memory. The main process never loads the VAD.

So:
- **One** AgentServer main process (the "router")
- **N** worker subprocesses (one per active user session, up to pool limit)
- Both live in the same machine/container, but distinct OS processes with their own memory.

### Precision 3 — the SFU does NOT run the model inference

The SFU only routes audio packets. The worker process makes HTTPS calls to AWS directly — the SFU never sees inference traffic:

```
[Browser/Android] ─audio─► [SFU (livekit-server OSS)] ─audio─► [Worker subprocess]
                                                                       │
                                                                       │ HTTPS (independent of SFU)
                                                                       ├──► AWS STT
                                                                       ├──► AWS RAG/LLM
                                                                       └──► AWS TTS
                                                                       │
[Browser/Android] ◄audio─ [SFU                ]  ◄audio─ [Worker subprocess]
```

SFU sees audio frames in and out; never sees transcripts, LLM tokens, or any AWS traffic. Inference happens entirely worker-side.

### Corrected one-paragraph summary

`AgentServer` is a **process manager** that opens a WS to the SFU, registers as a worker for `agent_name=my-agent`, and dispatches incoming job requests to a pool of subprocesses. **Each subprocess** is where the actual agent lives: it runs the `Assistant(Agent)` instance plus `AgentSession`, loads Silero VAD + turn-detector ONNX into its own memory (via `prewarm`), and calls STT/LLM/TTS endpoints over HTTPS (in Sophia's case, to AWS). The SFU only routes audio between the client and the worker subprocess — it never touches inference traffic. SFU placement (Cloud or self-hosted `livekit-server`) and worker placement (laptop / your cloud / Cloud Agents) are independent; mix freely.

**Correction:** Q22's claim that "Silero VAD + turn-detector both load in the worker subprocess via prewarm" is wrong for the turn detector — see Q23.

---

## Q23 (2026-05-14): For VAD I set `setup_fnc = prewarm` (so it loads per subprocess), but for `turn_detection=MultilingualModel()` I didn't. Why the asymmetry?

**They use completely different process models.** Spotting this asymmetry was a real catch — Q22's claim that both load in the worker subprocess was wrong for the turn detector.

### The asymmetry

| Component | Where it's loaded | How |
|---|---|---|
| **Silero VAD** | Inside the **worker subprocess** (the one running `agent.py`) | Via `prewarm` → `silero.VAD.load()` → stored in `proc.userdata["vad"]` |
| **Turn detector** (`MultilingualModel`) | Inside a **separate "inference runner" subprocess** | Auto-loaded via `_InferenceRunner.register_runner(...)` at import time |

`MultilingualModel()` is **not the model** — it's a small client/handle object. The actual ONNX + tokenizer live in a different subprocess; the handle sends IPC requests to it.

### Evidence in source

`turn_detector/multilingual.py:116`:
```python
if not _remote_inference_url():
    _InferenceRunner.register_runner(_EUORunnerMultilingual)
```

That registers a runner with the framework's inference subsystem. The AgentServer spawns an **inference subprocess** alongside the worker subprocesses, and `_EUORunnerBase.initialize()` runs there:

```python
def initialize(self) -> None:                              # base.py:95
    import onnxruntime as ort
    from transformers import AutoTokenizer
    local_path_onnx = _download_from_hf_hub(HG_MODEL, ONNX_FILENAME, ...)
    self._session = ort.InferenceSession(local_path_onnx, ...)
    self._tokenizer = AutoTokenizer.from_pretrained(HG_MODEL, ...)
```

When `MultilingualModel.predict_end_of_turn(...)` is called from the worker, it serializes the chat history and dispatches it over IPC to the inference runner, which calls `run(data)` and returns probability bytes. The worker subprocess never touches the ONNX.

### Connects to Q5 log line

The log line from your first run:
```
initializing process {"pid": …, "inference": true}
```
**That `"inference": true` process was this inference runner subprocess starting up.** It exists alongside worker subprocesses and serves their turn-detector requests over IPC. The PyTorch warning came from this subprocess loading `transformers`.

### Why the asymmetric design

| Reason | VAD | Turn detector |
|---|---|---|
| **Model size** | ~few hundred KB | ~100 MB ONNX + tokenizer |
| **Call frequency** | Every ~30 ms audio frame | Once per user-turn |
| **Latency sensitivity** | Must be inline — IPC overhead would hurt | One call per turn — IPC overhead negligible |
| **Sharing across workers** | Not worth — each worker owns its audio | Worth it — one inference process serves many workers |
| **Replaceable with remote service** | No | Yes — `LIVEKIT_REMOTE_EOT_URL` swaps local runner for HTTP |

### Three subprocess types running locally (corrected loading inventory)

```
[ AgentServer main process ]           ← cli.run_app
  - WS to SFU
  - Process pool manager
  (no ML models loaded here)

[ Inference runner subprocess ]        ← spawned by framework, NOT your code
  - onnxruntime + transformers
  - turn-detector ONNX + tokenizer loaded ONCE
  - shared by all worker subprocesses via IPC

[ Worker subprocess #N ]               ← spawned per user session
  - prewarm runs once: silero.VAD.load()
  - VAD ONNX loaded here, per subprocess
  - AgentSession + Assistant live here
  - HTTPS to remote STT/LLM/TTS
  - IPC to inference runner for turn detection
```

### Why no `prewarm` for turn detector

`prewarm` (`setup_fnc`) only initializes things in **worker subprocesses**. The turn detector isn't loaded there — it has its own initialization lifecycle (`initialize()` method called automatically by the framework when the inference subprocess spawns). Nothing for `prewarm` to do.

If LiveKit had made `MultilingualModel` an inline class (like Silero VAD), you'd see:
```python
def prewarm(proc):
    proc.userdata["vad"] = silero.VAD.load()
    proc.userdata["turn_detector"] = MultilingualModel.load()    # hypothetical
```
But they chose the inference-subprocess design instead — better latency isolation, model sharing across workers, and remote-swap option.

### Remote-swap option

```python
def _remote_inference_url():                                   # multilingual.py:108
    url_base = os.getenv("LIVEKIT_REMOTE_EOT_URL")
    if not url_base:
        return None
    return f"{url_base}/eot/multi"
```

If `LIVEKIT_REMOTE_EOT_URL` is set: no local inference subprocess, no ONNX loaded, no transformers needed — `predict_end_of_turn` just POSTs to your URL. Useful for constrained-container deployments (e.g. LiveKit Cloud Agents).

---

## Q24 (2026-05-14): When models live on AWS, VAD + turn detection create the local "environment" they need. Without it, even SOTA models are inefficient. So I can benchmark in `my-agent`, but when I ship in my own project, I either provide the same environment myself OR keep using LiveKit (plugins + OSS SFU) and just swap the model values. Right?

**Core understanding is correct. Three precisions to make the model hold up under harder cases.**

### What's correct ✅
1. Remote models need a local orchestration "environment" — VAD + turn detection are part of it.
2. Poor environment settings → even SOTA models feel sluggish, talk over the user, or cut you off mid-sentence.
3. `my-agent` benchmarking is valid for comparing models head-to-head if the environment stays consistent across runs.
4. Shipping on LiveKit in production = swapping the chosen model is a 1-2 line plugin change.
5. Abandoning LiveKit in production = rebuilding the entire environment from scratch.

### Precision 1 — "environment" is much bigger than VAD + turn detection

The orchestration layer is more than two ONNX models. What LiveKit handles for you:

| Component | What it does | What happens if tuned wrong |
|---|---|---|
| **VAD** (Silero) | Per-frame speech/silence | Cuts off mid-sentence (threshold low) or never realizes you started (high) |
| **Turn detection** | Decides when user is done speaking | Long awkward pauses (too patient) or interrupts your sentence (too eager) |
| **Endpointing** (min/max delays) | How long silence before turn ends | Jumpy or sluggish |
| **Interruption controller (barge-in)** | User speaks while TTS plays → cancel TTS, cancel LLM stream, start new STT | Without this, TTS plays over interruption — terrible UX |
| **State machine** | listening → thinking → speaking → interrupted | Race conditions cause weird behavior |
| **Audio resampling / codec** | Browser sends Opus 48 kHz, model wants 16 kHz PCM | Silent failures or distorted audio |
| **Streaming glue / backpressure** | Async queues between STT/LLM/TTS stages | Buffer overruns, dropped chunks, lagging streams |
| **Reconnection / timeouts / error recovery** | WS drops, model server fails, network glitches | Sessions break instead of recovering |
| **Latency tracking + metrics** | Per-stage timing | Can't tell what's slow without it |

VAD + turn detection are the tunable pieces typically thought about, but the framework owns ~8 other things that also matter. Q2 listed this as "what a homemade LiveKit must implement" — 2–4 person-months of work for production quality with lots of subtle-timing iteration.

### Precision 2 — benchmark validity has TWO halves

| What you're measuring | Validity outside LiveKit |
|---|---|
| **Raw model quality** — WER, MOS, voice quality, hallucination rate, RAG accuracy | ✅ Portable. A model that scores well on WER scores well anywhere. |
| **End-to-end UX latency + interruption feel** | ❌ Depends on orchestration. Different framework = different feel for the same model. |

If Orpheus benchmarks at TTFB = 180 ms with great barge-in in `my-agent`, that's the **LiveKit-orchestrated** number. Ship on a different framework with different VAD/buffer tuning → Orpheus's raw audio quality is the same but TTFB and barge-in could be very different.

**Implication:** safest path is *benchmark on LiveKit → ship on LiveKit*. Same orchestration code = same UX. Different framework = re-validate the timing.

### Precision 3 — cascaded vs STS have different environment needs

| Path | What the environment needs |
|---|---|
| **Cascaded** (STT → LLM → TTS) | VAD + turn detection + interruption controller + state machine — everything above |
| **End-to-end STS** (Moshi, Step-Audio, Qwen-Omni, Hertz-dev) | **Different.** Full-duplex STS models do their own turn-taking internally. Bypasses most of the VAD/turn-detection/barge-in layer. Simpler plumbing but more locked-in to the model. |

The "environment cost" of switching frameworks is mostly a **cascaded-pipeline concern**. If Sophia eventually picks Moshi or Step-Audio 2 mini, much less of this matters.

### Strategic recommendation (locked in)

**Stay on LiveKit for production.** Benchmark in `my-agent` → ship the same code path with model plugins swapped to the winning OSS picks. OSS production migration is mostly DevOps (self-hosted `livekit-server`, DeepFilterNet for noise, OTel for observability — Q2), not re-architecture.

The alternative — "use LiveKit for benchmarking, then rebuild for production" — wastes benchmark validity, adds 2–4 person-months of orchestration work, and ships a less-polished UX. No upside.

Only reasons to leave LiveKit in production:
1. Can't get LiveKit Cloud / self-hosted to fit VPC / compliance constraints (unlikely — Apache 2.0, self-hostable).
2. Need a transport LiveKit doesn't support (e.g., embedded device with no WebRTC stack). For XREAL + Android, doesn't apply.
3. Using an end-to-end STS model exclusively and want the simplest plumbing. Even then, LiveKit supports realtime/audio-LLM models via `RealtimeModel`.

### One-line summary

The environment matters as much as the models, and LiveKit gives you that environment for free. **Stay on LiveKit through benchmarking AND production** — same code, different model plugins, OSS-self-hostable when ready. Cost of leaving the framework is much higher than the cost of staying.

---

## Q25 (2026-05-14): Is `silero_vad.onnx` in `silero/resources/` the actual model weights? If so, where's the turn-detector model — I only see `models.py` with `ONNX_FILENAME = "model_q8.onnx"` as a constant?

**Yes for Silero (bundled in package). Turn detector is downloaded from HuggingFace Hub at setup time, NOT bundled.**

### Where each one actually lives on disk

**Silero VAD:** bundled inside the pip package.
```
.venv/.../livekit/plugins/silero/resources/silero_vad.onnx     ← 2.3 MB, ships with the wheel
```

**Turn detector:** the package only ships pointers (`models.py`):
```python
HG_MODEL = "livekit/turn-detector"       # HuggingFace repo
ONNX_FILENAME = "model_q8.onnx"          # filename within that repo
MODEL_REVISIONS = {
    "en":           "v1.2.2-en",
    "multilingual": "v0.4.1-intl",
}
```

Actual file lives in the HuggingFace cache:
```
~/.cache/huggingface/hub/models--livekit--turn-detector/
├── snapshots/
│   └── 87e35fcb…/onnx/model_q8.onnx     ← symlink → ../../../blobs/bd2c…
├── blobs/
│   ├── bd2c3077…   ← actual ONNX binary (content-addressable)
│   ├── c2b2f5d8…   ← tokenizer
│   ├── ac23c0aa…   ← config
│   └── … (8 more)
└── refs/
    └── v0.4.1-intl   ← maps version tag → snapshot SHA
```

So `silero_vad.onnx` is a real file in the package; `model_q8.onnx` is a symlink in the HF cache → content-addressable blob.

### HF Hub cache layout (you'll see this pattern again)

| Directory | What's in it |
|---|---|
| `snapshots/<sha>/` | Logical view — expected filenames as symlinks |
| `blobs/<hash>` | Actual binary content, named by SHA. Content-addressable, deduplicated across revisions. |
| `refs/<tag>` | Maps human revision tag → snapshot SHA |
| `.no_exist/` | Markers for files known not to exist |

Standard HuggingFace layout. Every model downloaded via `huggingface_hub` ends up here; shared across all projects on the machine.

### How it got there

You triggered the download with:
```bash
uv run python src/agent.py download-files
```

The framework walks all registered inference runners and pre-fetches their models. For turn-detector this calls `_download_from_hf_hub("livekit/turn-detector", "model_q8.onnx", revision="v0.4.1-intl", …)`.

At runtime, `base.py:117` uses `local_files_only=True`:
```python
local_path_onnx = _download_from_hf_hub(
    HG_MODEL, ONNX_FILENAME,
    subfolder="onnx", revision=revision,
    local_files_only=True,          # MUST be pre-downloaded; won't fetch on demand
)
```

If you skip `download-files` and start the agent, it crashes with: *"Could not find model livekit/turn-detector with revision v0.4.1-intl. Use `python3 your_agent.py download-files`…"*

### Why two different distribution strategies

| Factor | Silero VAD (bundled) | Turn detector (HF Hub) |
|---|---|---|
| Model size | 2.3 MB | ~50–100 MB (q8 quantization keeps it smaller than fp16) |
| Versioning | Single static file, ships with package version | Multiple revisions, updated independently of plugin releases |
| Format | Single standalone ONNX | ONNX + tokenizer + config (multiple artifacts) |
| Update cadence | Years (Silero VAD changes rarely) | Months (LiveKit ships new detector models faster than plugin releases) |
| Ecosystem fit | Could go either way at this size | HF Hub is the natural distribution for transformer-based models |

Bundling the turn-detector would (a) bloat every install by ~100 MB for people who don't use it, (b) couple weight updates to plugin code releases, (c) require shipping tokenizer files too.

### Three places models can live (general LiveKit plugin pattern)

| Strategy | Example | When to use |
|---|---|---|
| **Bundled in pip package** | Silero VAD | Small (<10 MB), stable, single-file |
| **HF Hub cache** | Turn detector | Medium-large, versioned, multiple artifacts |
| **Remote API call** | LiveKit Inference, OpenAI plugin, your AWS plugin | Heavy enough you don't want it on the worker at all |

Same plugin can fall back across these — turn detector tries HF cache first; if `LIVEKIT_REMOTE_EOT_URL` is set, skips local entirely (Q23).

---

## Q26 (2026-05-14): What code runs when I do `uv run python src/agent.py download-files`? I only see `agent.py`. And confirm: Silero is in worker memory, turn detector is in the HF cache locally?

### Part A — where `download-files` comes from

`agent.py` itself has no `download-files` function. The subcommand is **added by the framework** at the moment `cli.run_app(server)` (last line of `agent.py`) runs.

**Trace:**

`agent.py:158`:
```python
cli.run_app(server)
```

`cli/cli.py:1977`:
```python
def run_app(server: AgentServer | WorkerOptions) -> None:
    if isinstance(server, WorkerOptions):
        server = AgentServer.from_server_options(server)
    _build_cli(server)()
```

`_build_cli(server)` builds a [typer](https://typer.tiangolo.com/) app with multiple subcommands registered as decorated functions: `dev`, `start`, `console`, `connect`, `download_files`. Typer auto-converts the Python function name `download_files` → CLI subcommand `download-files`.

When you run `python src/agent.py download-files`, typer dispatches to `download_files()` at `cli/cli.py:1952`:

```python
@app.command()
def download_files() -> None:
    for plugin in Plugin.registered_plugins:
        logger.info(f"Downloading files for {plugin.package}")
        plugin.download_files()
        logger.info(f"Finished downloading files for {plugin.package}")
```

It iterates `Plugin.registered_plugins` — a global list every plugin appended itself to at import time via `Plugin.register_plugin(...)` — and calls `.download_files()` on each.

Base `Plugin.download_files()` is a no-op (`plugin.py:39`, empty method). Plugins override if they need to fetch anything.

**For `my-agent` specifically:**

| Plugin | `download_files()` behavior |
|---|---|
| `silero` (SileroPlugin) | No override → no-op. ONNX already in the wheel. |
| `turn_detector` (EOUPlugin, `base.py:196`) | `self._runner_class._download_files()` → HF Hub fetch of `model_q8.onnx` + tokenizer + config |
| `ai_coustics` (AICousticsPlugin) | Likely a no-op — proprietary `.dylib` ships in the wheel |

### How plugins ended up in `Plugin.registered_plugins`

`agent.py` imports trigger module-level `Plugin.register_plugin(...)` side effects:
```python
from livekit.plugins import ai_coustics, silero          # each registers itself on import
from livekit.plugins.turn_detector.multilingual import MultilingualModel
```

By the time `cli.run_app(server)` runs, the registry already contains all three.

### Full path of `download-files`

```
You run:  uv run python src/agent.py download-files
              │
              ▼
agent.py executes top-to-bottom:
  - imports trigger Plugin.register_plugin(...) for silero, turn_detector, ai_coustics
  - reaches cli.run_app(server) at the bottom
              │
              ▼
cli.run_app(server) → _build_cli(server)() → typer parses argv "download-files"
              │
              ▼
typer dispatches to download_files() function in cli/cli.py:1952
              │
              ▼
Loops Plugin.registered_plugins, calls .download_files() on each
              │
              ▼
turn_detector's EOUPlugin.download_files() → _runner_class._download_files()
              │
              ▼
HF Hub download → ~/.cache/huggingface/hub/models--livekit--turn-detector/
```

Same `agent.py`, different `sys.argv`. `python src/agent.py dev` dispatches to `dev()` instead — which actually starts the AgentServer and connects to the SFU.

### Part B — disk-vs-RAM distinction for Silero / turn-detector

Your statement was half-right. Two clarifications: disk-vs-RAM, and which subprocess owns what.

| Component | On disk (storage) | In RAM (active runtime) |
|---|---|---|
| **Silero VAD** | `silero/resources/silero_vad.onnx` (bundled in pip package on local FS) | **Worker subprocess RAM** — loaded by `silero.VAD.load()` in `prewarm` |
| **Turn detector** | `~/.cache/huggingface/.../model_q8.onnx` (HF cache on local FS) | **Inference runner subprocess RAM** — loaded by `EOUModelBase.initialize()` when the inference subprocess spawns |

At runtime, on your laptop:

```
[ AgentServer main process ]          ← no ML in RAM
                                       (just process pool + WS state)

[ Inference runner subprocess ]        ← turn-detector ONNX in RAM
   loaded FROM: ~/.cache/.../model_q8.onnx
   serves: ALL worker subprocesses via IPC

[ Worker subprocess #N ]               ← Silero VAD ONNX in RAM, per subprocess
   loaded FROM: silero/resources/silero_vad.onnx
   each worker has its own copy in its own RAM
```

Three things to keep straight:

1. **Disk file ≠ RAM session.** The HF cache holds the file on disk. The ONNX model is **also** loaded into RAM by `onnxruntime.InferenceSession(...)` — that's the runtime that actually does inference. The disk file is the source; the RAM session is what's running.

2. **Different subprocesses own different models.** The worker subprocess does NOT have the turn-detector in its memory. When it needs a turn-end prediction, it serializes the chat context and sends it via IPC to the inference runner subprocess — which has the turn-detector loaded and returns the probability bytes.

3. **Per-subprocess copies of Silero.** 3 concurrent sessions = 3 worker subprocesses = 3 separate Silero VAD copies in RAM (one per subprocess). Turn detector is loaded **once total** in the inference runner, regardless of how many workers exist.

### Corrected one-liner

> Silero VAD: bundled file on disk → loaded into **every worker subprocess's RAM** by prewarm. Turn detector: HF-cache file on disk → loaded into **one inference runner subprocess's RAM** at framework startup; all workers share it via IPC.

---

## Q27 (2026-05-14): If I don't use LiveKit, what concrete pieces do I need to build in my own orchestration layer to match LiveKit's voice agent performance?

**Long answer because the list is long — but that's the point.** This is exactly why Q24 concluded "stay on LiveKit." Concrete checklist of what you'd own without it.

### Layer 1 — Transport (biggest piece)

Real-time audio over the internet is hard. WebRTC is the standard.

| Component | Why it matters | OSS substitutes | Build cost |
|---|---|---|---|
| **SFU / media server** | Routes audio between client(s) and worker; many concurrent sessions | mediasoup, Janus, Jitsi Videobridge, OWT, **livekit-server** (OSS LiveKit SFU itself) | Reuse `livekit-server` (Apache 2.0) = free. Write your own = person-years. |
| **WebRTC stack (client + server)** | Negotiation, ICE/STUN/TURN, DTLS/SRTP, codecs, jitter buffer | aiortc, Pion, libwebrtc, Janus | aiortc gets 80%; edge cases = weeks–months. |
| **TURN server** | NAT traversal for cellular/restricted networks | coturn (Apache 2.0, industry standard) | Configure: 1–2 days. Scale: ongoing. |
| **Codec handling** | Browser sends Opus 48 kHz | libopus, ffmpeg | Days. |
| **AEC / AGC / noise suppression** | Otherwise: feedback, clipping, hum | Browser `getUserMedia` constraints + WebRTC audio_processing, RNNoise, DeepFilterNet | 1–3 days; quality tuning ongoing. |

If you skip LiveKit but reuse `livekit-server` as your OSS SFU, you save most of this. Skip the SFU entirely: easily person-quarters, likely years to match LiveKit's polish.

### Layer 2 — Audio I/O in the worker

| Component | OSS substitutes |
|---|---|
| PCM frame buffering | numpy ring buffers, asyncio queues |
| Resampling (48 kHz Opus → 16 kHz PCM) | `scipy.signal.resample`, `soxr`, `librosa`, `audioop` |
| Format conversion (s16le ↔ float32) | numpy, soundfile |
| Track routing | Custom plumbing |
| AEC (if not browser-side) | WebRTC audio_processing, speexdsp |

Effort: ~1–2 weeks.

### Layer 3 — Conversation orchestration (THE part where models go bad without it)

| Component | Why | OSS substitutes | Tuning effort |
|---|---|---|---|
| **VAD** | Per-frame speech/silence | Silero VAD (same one LiveKit uses), webrtcvad | Iterative tuning of `threshold`, `min_speech_duration_ms`, `min_silence_duration_ms`, `speech_pad_ms` |
| **Turn detection** | When user's TURN is over | Silence timeout, or lift LiveKit's `turn-detector` model | Weeks of tuning per language/style |
| **Interruption / barge-in controller** | User speaks while agent talks → cancel TTS + LLM, flush partial, return to listening | Build from scratch | **Hardest one.** 2–4 weeks. Subtle race conditions. |
| **State machine** | listening / thinking / speaking / interrupted | aiosm, transitions, hand-rolled | Days–weeks. |
| **Hysteresis / debouncing** | Don't barge in on a cough; don't end turn on "uh…" | Custom heuristics | User-testing iteration |

**Realistic: 4–8 weeks for production-quality conversational orchestration.** This is the work LiveKit has been polishing for ~2 years. Most homemade voice agents feel sluggish or talk-over-you because this layer is hard.

### Layer 4 — Pipeline glue (STT / LLM / TTS streaming)

| Component | What you build |
|---|---|
| STT stream adapter | Async generator wrapping STT client; VAD-chunk audio for non-streaming STT |
| LLM stream consumer | Async iteration; tool-call detection; multi-turn context management |
| TTS stream adapter | Sentence tokenizer (blingfire — what LiveKit uses); audio chunk pacing; cancellable mid-utterance |
| Async queues + backpressure | asyncio.Queue with max size; per-stage backpressure |
| Cancellation propagation | asyncio cancellation + cleanup hooks |
| Per-stage timing | OpenTelemetry spans; custom timers |

Effort: ~2–3 weeks. Most weekend agents handle happy path but break on cancellation.

### Layer 5 — Conversation management

| Component | What you build |
|---|---|
| Chat context | List of message dicts; truncation; system prompt injection |
| Tool / function calling | Schema gen from signatures (or pydantic); tool result injection back into context |
| Multi-agent handoffs / workflows | State management; per-agent prompt overrides |
| Memory beyond context window | Summarization, RAG over past turns |

Effort: 1–2 weeks tool calling; more for LiveKit-style workflows.

### Layer 6 — Worker / scale

| Component | OSS substitutes |
|---|---|
| Worker process model | multiprocessing, ProcessPoolExecutor; Celery/Redis queue |
| Job dispatch | Custom routing via SFU webhooks or job queue |
| Graceful shutdown / draining | Signal handling; drain mode |
| Process supervision | systemd, supervisord, k8s |
| Concurrent session capacity tuning | Pool sizing, horizontal autoscaling |

Effort: 1–2 weeks simple; weeks–months production reliability.

### Layer 7 — Production concerns

| Component | OSS substitutes |
|---|---|
| Observability | OpenTelemetry → Grafana + Tempo + Loki; Prometheus |
| Session recording | Server-side audio recording; egress to S3 |
| Auth / token issuance | python-jose, PyJWT; ~50-line FastAPI |
| Reconnection handling | WebRTC ICE restart; session state persistence |
| Health checks | FastAPI /healthz |
| Metrics export | prometheus_client |

Effort: 2–4 weeks production-grade.

### Layer 8 — Edge / device-specific (XREAL + Android)

| Component | OSS substitutes |
|---|---|
| Android client SDK | `livekit-android` (Apache 2.0). Or libwebrtc directly — order of magnitude harder. |
| Audio routing on phone | Android AudioManager |
| Background audio | Foreground service |
| Bluetooth / USB-C audio routing | Test per XREAL model |

Effort: with SDK = days. Without = weeks–months.

### Total cost summary

| Layer | Person-weeks (production quality) |
|---|---|
| 1. Transport (livekit-server reuse) | 1–2 |
| 1. Transport (full DIY, no LiveKit SFU) | 20+ |
| 2. Audio I/O | 1–2 |
| 3. Conversation orchestration | **4–8** |
| 4. Pipeline glue | 2–3 |
| 5. Conversation management | 1–2 |
| 6. Worker / scale | 1–2 simple, 4–8 production |
| 7. Production concerns | 2–4 |
| 8. Android client | 1 with SDK, 8+ without |
| **Total (SDK + SFU reuse)** | **~13–25 person-weeks** |
| **Total (full DIY)** | **~50+ person-weeks** |

For a one-engineer team: 3–6 months JUST for parity, plus months of subtle tuning for natural feel.

### What you CAN reasonably DIY (keep LiveKit but own these)

- **Audio enhancement** — DeepFilterNet 3 instead of ai-coustics. Days.
- **Observability** — own Prometheus/Grafana. Weeks.
- **Auth / token-mint backend** — ~50 lines FastAPI. Hours.
- **Custom STT/LLM/TTS plugins** — the whole point. Days each.

Right ownership: keep what's hard (orchestration, transport, SDKs); build what's specific to you (models, business logic).

### Strategic reaffirmation

Going LiveKit-free = 3–6 person-months of orchestration work to MAYBE match what LiveKit gives free + ongoing maintenance. Math only works:
1. Extreme transport constraint (no WebRTC on device) — N/A for XREAL+Android.
2. Regulatory: on-device-only no SFU. Niche.
3. End-to-end STS exclusively — LiveKit's `RealtimeModel` handles those too with less work.

None apply to Sophia.

---

## Q28 (2026-05-14): If I use livekit OSS SFU (not Cloud) + my AWS models, do I still get the full orchestration environment?

**Yes — fully. With one small footnote about noise cancellation.**

The orchestration environment (Q27 Layers 3–8) lives in the **`livekit-agents` Python framework**, which is Apache 2.0 and runs in your worker subprocess. Cloud vs OSS-self-hosted SFU only affects **Layer 1 (network/transport)** — not orchestration.

### What you get with OSS SFU + your AWS models

| Layer | What you get | Source |
|---|---|---|
| 1. Transport (WebRTC, ICE, jitter buffer, codecs, encryption) | ✅ Same | `livekit-server` (Apache 2.0) |
| 2. Audio I/O (resampling, format conversion, buffering) | ✅ Same | `livekit-agents` framework |
| 3. **VAD + turn detection + barge-in + state machine** | ✅ **Identical** | `livekit-agents` framework |
| 4. Pipeline glue (STT/LLM/TTS streaming, cancellation, backpressure) | ✅ Identical | `livekit-agents` framework |
| 5. Conversation management (chat context, tool calling, workflows) | ✅ Identical | `livekit-agents` framework |
| 6. Worker/scale (process pool, job dispatch) | ✅ Identical | `livekit-agents` framework |
| 7. Observability hooks | ✅ Hooks; you wire your own Grafana/Prometheus | `livekit-agents` framework |
| 8. Android client | ✅ Same SDK | `livekit-android` (Apache 2.0) |

So the entire "environment" from Q24/Q27 — all of it — is yours with the OSS path. None of it is gated behind Cloud.

### What changes vs Cloud

| Cloud feature | OSS substitute when self-hosting | Effort |
|---|---|---|
| Cloud SFU (managed, geo-distributed) | `docker run livekit/livekit-server` in your VPC | 3–5 days |
| TURN/STUN | `coturn` next to livekit-server | 1–2 days |
| **Krisp noise cancellation** (via `ai_coustics` plugin) | DeepFilterNet 3 (~90% quality, Apache 2.0) or Silero noise suppression | 1–2 days |
| LiveKit Inference (Deepgram/OpenAI/Cartesia proxy) | **Skipping anyway** — AWS endpoints replace it | 0 (won) |
| Cloud Agents (managed worker hosting) | Worker on your EC2 / k8s | Days of DevOps |
| Cloud observability dashboards | OpenTelemetry → Grafana/Tempo/Loki | 1–3 weeks |
| Auto-scaling SFU edge | Deploy SFU in 2–4 regions + GeoDNS | 3–5 days |

Total **~2–4 person-weeks of DevOps** (per Q2) for SFU + ancillary services. Zero change to agent code.

### The one real footnote — noise cancellation

The `ai_coustics.audio_enhancement(...)` line in `agent.py` requires `Auth.livekit_cloud()` — without Cloud creds it fails to authenticate. From `my-agent/README.md`:

> "If you choose to self-host, you'll need to also use model plugins instead of LiveKit Inference and will need to remove the LiveKit Cloud noise cancellation plugin."

Fix: remove the line (works, no enhancement), or replace with DeepFilterNet 3 / Silero noise suppression. One-line edit and you're free of Cloud entirely.

### What stays IDENTICAL between Cloud and OSS

- The `agent.py` code (modulo the one `ai_coustics` line)
- The `Assistant(Agent)` class
- The `AgentSession(...)` construction with VAD, turn-detection, STT, LLM, TTS
- All plugin behavior
- Silero VAD in worker subprocess
- Turn detector in inference runner subprocess
- Latency feel, barge-in feel, conversation flow
- Tool calling, workflows, handoffs
- Android client experience

This is why Q24 said "benchmark on LiveKit Cloud → ship on OSS = same code path." Literally the same Python framework in both cases.

### Concrete production stack for Sophia

```
[ Android phone + XREAL glasses ]
   livekit-android SDK (Apache 2.0)
        │ WebRTC over UDP/TCP
        ▼
[ Your AWS VPC ]
   livekit-server (Docker) ←─── OSS SFU
   coturn (Docker) ←─── NAT traversal
   ┌──────────────────────────────────────────────┐
   │ Token-mint backend (~50 lines FastAPI)       │
   │   • mints JWTs for Android clients           │
   ├──────────────────────────────────────────────┤
   │ Sophia Agent Worker (Python + livekit-agents)│  ←─── Layers 2-7 here
   │   • Silero VAD (per worker subprocess RAM)   │      THIS is where the
   │   • Turn detector (inference runner RAM)     │      "environment" lives
   │   • DeepFilterNet 3 (noise cancellation)     │
   │   • Plugins → AWS STT / RAG / TTS via HTTPS  │
   ├──────────────────────────────────────────────┤
   │ AWS STT endpoint                             │  ←─── your inference
   │ AWS RAG/LLM endpoint                         │      (Layer outside LiveKit)
   │ AWS TTS endpoint                             │
   └──────────────────────────────────────────────┘
   
   OpenTelemetry → Grafana stack (separate; observability)
```

Everything inside the agent worker process is **identical** to what `my-agent` runs now with Cloud. The orchestration is yours; you just operate the SFU yourself.

### One-line answer

> The entire orchestration "environment" is in `livekit-agents` (Apache 2.0, framework-side), not in Cloud. Self-hosting the SFU + bringing your own AWS models gives you exactly the same conversation behavior. The only loss is the proprietary noise-cancellation plugin, substituted with DeepFilterNet 3.

---

## Q29 (2026-05-14): Concrete install/deploy checklist for OSS LiveKit production (XREAL+Android, AWS models, no noise cancellation for now) — what packages, services, and tooling do I need?

Three deployment environments. Shopping list below.

### 1. On the Android device

| Package | Notes |
|---|---|
| `io.livekit:livekit-android` | LiveKit Android Client SDK (Apache 2.0). Gradle dep. Room connection, mic publish, audio subscribe, data channel. |
| `io.livekit:livekit-android-compose-components` | Optional Jetpack Compose UI helpers. |
| `NRSDK_Android.aar` (XREAL) | XREAL's SDK for AR overlay rendering. Local AAR drop-in. |
| Your Kotlin/Flutter app code | Wires LiveKit SDK + NRSDK. Reference: `livekit-examples/agent-starter-android`. |

```gradle
dependencies {
    implementation "io.livekit:livekit-android:2.x.x"
    implementation "io.livekit:livekit-android-compose-components:1.x.x"
    implementation files("libs/NRSDK_Android.aar")
}
```

### 2. On AWS VPC — four server processes

**2a. SFU**

| Component | Install | Purpose |
|---|---|---|
| `livekit/livekit-server` Docker image | `docker pull livekit/livekit-server:latest` | OSS SFU (Go, Apache 2.0) |
| TLS cert | Let's Encrypt via Caddy/Traefik, or AWS ACM + ALB | WSS requires TLS |
| `coturn` Docker image | `docker pull coturn/coturn:latest` | NAT traversal for cellular/restricted-network clients |

```yaml
services:
  livekit-server:
    image: livekit/livekit-server:latest
    ports: ["7880:7880", "7881:7881", "7882:7882/udp"]
    environment:
      - LIVEKIT_KEYS=mykey: mysecret
  coturn:
    image: coturn/coturn:latest
    network_mode: host
    volumes: ["./turnserver.conf:/etc/turnserver.conf"]
```

**2b. Token-mint backend (~50 lines)**

Never embed `API_SECRET` in the Android app — keep it server-side.

| Package | Purpose |
|---|---|
| Python 3.10+ | Runtime |
| `livekit-api` | Server SDK — `pip install livekit-api`. Mints JWTs via `AccessToken`. |
| `fastapi` + `uvicorn` | HTTP framework |

```python
from fastapi import FastAPI
from livekit.api import AccessToken, VideoGrants
import os

app = FastAPI()

@app.post("/token")
def mint_token(user_id: str, room: str):
    token = AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]) \
        .with_identity(user_id) \
        .with_grants(VideoGrants(room_join=True, room=room))
    return {"token": token.to_jwt()}
```

**2c. Sophia Agent Worker** (the modified `my-agent`)

| Package | Purpose |
|---|---|
| Python 3.10+ | Runtime |
| `uv` | Package manager |
| `livekit-agents[silero,turn-detector]~=1.5` | Framework + Silero VAD + turn detector |
| Custom `AwsRagLLM`, `AwsSttPlugin`, `AwsTtsPlugin` | In `src/plugins/`, subclass `livekit.agents.{stt,tts,llm}` base classes |
| `aiohttp` | HTTP client (usually transitive) |
| `python-dotenv` | `.env` loading |

What changes from current `my-agent`:
- Remove `livekit-plugins-ai-coustics` from `pyproject.toml`
- Remove `noise_cancellation=ai_coustics.audio_enhancement(...)` from `agent.py`
- Env vars repoint at self-hosted SFU:
```bash
LIVEKIT_URL=wss://livekit.yourdomain.com
LIVEKIT_API_KEY=mykey
LIVEKIT_API_SECRET=mysecret
```

Deploy via `my-agent/Dockerfile` already present.

**2d. AWS model endpoints (already exist)**

Already deployed. Agent worker calls them over HTTPS through the custom plugins. No new install.

### 3. On the developer laptop

| Tool | Install | Purpose |
|---|---|---|
| `lk` CLI ≥ v2.15.0 | `brew install livekit-cli` | Room/agent/docs management |
| Docker Desktop | https://docker.com | Local SFU testing; build agent image |
| Python 3.10+ | `brew install python@3.12` | Runtime |
| `uv` | `brew install uv` | Python pkg manager |
| Android Studio | Standard | Build Android app |
| AWS CLI / Terraform | Per preference | Deploy to AWS |

### 4. Optional but production-recommended

| Component | Purpose | Install |
|---|---|---|
| DeepFilterNet 3 | Noise cancellation (later) | `pip install deepfilternet`, wire as plugin |
| OpenTelemetry collector | Traces/metrics export | Docker container |
| Prometheus + Grafana | Metrics dashboards | Docker; LiveKit dashboards on Grafana Hub |
| Loki + Tempo | Logs + traces | Docker |
| Sentry | Error tracking | SaaS or self-host |

### What NOT to install (clarify)

- ❌ LiveKit Cloud account
- ❌ `livekit-plugins-ai-coustics` (Cloud-locked)
- ❌ `livekit-plugins-deepgram` / `livekit-plugins-openai` / `livekit-plugins-cartesia` (custom AWS plugins replace these)
- ❌ LiveKit Inference (`inference.STT/LLM/TTS`)
- ❌ Krisp
- ❌ Frontend web hosting (native Android app)

### Deployment shape

```
[ Android phone + XREAL glasses (USB-C) ]
  Kotlin app + livekit-android SDK + NRSDK
       │ WSS / WebRTC
       ▼
[ Your AWS VPC ]
  livekit-server (Docker, OSS SFU)
  coturn (Docker, TURN)
  Token-mint FastAPI (Docker)
  ┌────────────────────────────────────────────┐
  │ Sophia Agent Worker (Docker)               │
  │  livekit-agents + Silero + turn-detector   │
  │  Custom plugins:                            │
  │    • AwsSTT  ───────► AWS STT  endpoint    │
  │    • AwsLLM  ───────► AWS RAG  endpoint    │
  │    • AwsTTS  ───────► AWS TTS  endpoint    │
  └────────────────────────────────────────────┘
  (optional: OTel collector + Grafana stack)
```

### Minimum end-to-end checklist

1. ✅ Already have: `my-agent` codebase, AWS STT/RAG/TTS endpoints.
2. **Modify** `my-agent`:
   - Remove `livekit-plugins-ai-coustics` dep
   - Remove `noise_cancellation=ai_coustics...` line
   - Add `src/plugins/aws_{rag,stt,tts}.py`, wire into `AgentSession(...)`
3. **Stand up** AWS infra:
   - `livekit-server` container
   - `coturn` container
   - TLS cert for `livekit.yourdomain.com`
4. **Generate** API key/secret, set in `livekit-server` config
5. **Deploy** token-mint FastAPI service
6. **Build + push** `my-agent` Docker image; run on EC2/ECS/Fargate
7. **Build** Android app (livekit-android SDK + NRSDK)
8. **Test** end-to-end (token → room → agent conversation)

Steps 1–7 are MVP. Observability + DeepFilterNet 3 can come later.

### One-line answer

**`livekit-server` + `coturn` (Docker) on AWS; `livekit-agents[silero,turn-detector]` in the worker; `livekit-api` in the token-mint backend; `livekit-android` + NRSDK in the Android app. Plus a ~50-line FastAPI token-mint service. That's the entire OSS LiveKit production stack — no Cloud anywhere.**

---

## Q30 (2026-05-14): Recap — Android Kotlin app uses livekit-android SDK + XREAL SDK to capture audio; OSS livekit-server runs on AWS; Sophia Agent runs on AWS using livekit-agents, takes inputs from Android, orchestrates, sends results back to Android → XREAL. Plus coturn and FastAPI token-mint deployed separately on AWS.

**Essentially correct. One precision: the SFU sits BETWEEN Android and Agent — they don't talk directly.**

### The SFU is the post office

Android and Agent are **two separate participants in the same Room**, mediated by the SFU:

```
[Android] ──audio track──► [livekit-server SFU] ──same track──► [Sophia Agent Worker]
[Android] ◄──audio track── [livekit-server SFU] ◄──TTS track── [Sophia Agent Worker]
```

Both publish audio tracks to the SFU; both subscribe to each other's. Neither has a direct connection — that's exactly what an SFU exists to do (selective forwarding without peer-to-peer mesh).

This matters because:
- The Agent never sees Android's IP address; it just receives audio frames from a participant in its Room.
- Adding a third participant (another user, debug listener) is trivial — they join the same Room.
- Audio path is always: client → SFU → agent → SFU → client. Never bypasses the SFU.

### Four flows in the stack (one per arrow type)

| Flow | From → To | Transport | When |
|---|---|---|---|
| **Auth** | Android app → FastAPI token-mint | HTTPS REST | Once per session, BEFORE connecting to SFU |
| **WebRTC media** | Android ↔ SFU ↔ Agent | WebRTC (UDP/TCP, DTLS/SRTP) | Continuously during conversation |
| **Worker control** | Agent worker ↔ SFU | WebSocket | Continuously — worker registration + job dispatch |
| **Inference** | Agent worker → AWS STT/RAG/TTS endpoints | HTTPS REST | Per user turn |

Each flow uses a different protocol and serves a different purpose.

### Sequence of what actually happens (first conversation)

```
1. User opens Android app
2. Android app → POST /token → FastAPI                        [Auth flow]
3. FastAPI mints JWT, returns to app
4. Android app uses JWT to connect to livekit-server          [WebRTC media flow opens]
5. Android joins Room X as participant "user_123"

   (Meanwhile, agent worker is already registered, idle)

6. SFU sees participant joined → dispatches job to agent worker [Worker control flow]
7. Agent worker spawns subprocess running my_agent(ctx)
8. Subprocess joins Room X as participant "agent"             [second WebRTC connection]

   (Conversation begins)

9. User speaks → Android mic → SFU → Agent subprocess         [WebRTC media flow]
10. Agent VAD detects speech, accumulates audio
11. Turn detector says "user done"
12. Agent calls AWS STT → AWS RAG → AWS TTS                   [Inference flow]
13. Agent publishes TTS audio back to SFU
14. SFU routes TTS audio to Android
15. Android plays audio (phone speaker or XREAL speakers via Android audio routing)
16. → back to step 9 for next turn
```

### Corrected inventory of "where what lives"

| Component | Where | Package / install |
|---|---|---|
| Android app (UI + mic capture + audio playback + AR overlays) | Phone | `livekit-android` SDK + XREAL NRSDK |
| **SFU (the audio post office)** | **AWS, always-on** | `livekit-server` Docker image |
| TURN (NAT helper) | AWS, always-on | `coturn` Docker image |
| Token-mint API (issues JWTs to clients) | AWS, always-on | FastAPI + `livekit-api` (Python server SDK) |
| Sophia Agent Worker (orchestration + plugin calls to AWS) | AWS, always-on (worker pool) | `livekit-agents[silero,turn-detector]` + custom plugins |
| AWS STT / RAG / TTS endpoints | AWS | Already deployed |

All AWS-side services are independent Docker containers; they don't communicate with each other except through documented protocols (WebRTC for media, WebSocket for worker control, HTTPS for everything else).

### One-line corrected mental model

> Android publishes audio to the SFU; Sophia Agent subscribes to that audio from the SFU; Agent calls AWS for STT/LLM/TTS over HTTPS; Agent publishes synthesized audio back to the SFU; SFU forwards to Android; Android plays it through XREAL or phone speakers. The SFU is always in the middle — never bypassed.

---

## Q31 (2026-05-14): Full catalog of LiveKit open-source components and their purposes — what does Sophia need vs not?

All Apache 2.0. Grouped by tier.

### Tier 1 — Core infrastructure (the SFU and adjacent media servers)

| Repo / package | Language | Purpose | Sophia uses? |
|---|---|---|---|
| **livekit-server** | Go | The SFU. WebRTC media routing, room mgmt, participant tracking, JWT auth. Runs at `wss://livekit.yourdomain.com`. | ✅ Required |
| livekit-egress | Go | Pulls media OUT of rooms — MP4/MP3 recording, RTMP/HLS push. | 🟡 Maybe for QA recording |
| livekit-ingress | Go | Pushes external media INTO rooms (RTMP, WHIP, MP4 file). | ❌ |
| livekit-sip | Go | Telephony bridge — connect phone calls (Twilio etc.) to rooms. | ❌ |

### Tier 2 — Agent framework

| Repo / package | Language | Purpose | Sophia uses? |
|---|---|---|---|
| **livekit-agents** | Python | The voice/multimodal agent framework. Agent, AgentSession, AgentServer; all orchestration (VAD, turn detection, barge-in, state machine, streaming glue, tool calling, workflows). | ✅ Required |
| **livekit-plugins-\*** | Python | 60+ provider plugins (STT/LLM/TTS for OpenAI/Anthropic/Deepgram/etc.) plus utilities (silero, turn-detector). | ✅ silero + turn-detector. Custom plugins to AWS. |

### Tier 3 — Client SDKs (publish + subscribe inside a Room from a device/app)

For the end-user device. One SDK per language/platform; pick by where the client app runs.

| Repo / package | Platform | Sophia uses? |
|---|---|---|
| **livekit-android** | Kotlin/Java (Android) | ✅ Required |
| client-sdk-swift | Swift (iOS / macOS / visionOS) | ❌ (possible future iOS port) |
| client-sdk-js | TS (web) | 🟡 Dev/debug (browser Playground) |
| components-react | React UI helpers on client-sdk-js | 🟡 Dev/debug |
| client-sdk-flutter | Dart | ❌ |
| client-sdk-react-native | TS | ❌ |
| client-sdk-unity | C# (Unity) | ❌ |
| client-sdk-rust | Rust (underlying lib) | ❌ |
| client-sdk-cpp | C++ | ❌ |
| node-sdks (client) | Node.js | ❌ |
| python-sdks (client) | Python | ✅ Transitively (via livekit-agents) |

### Tier 4 — Server SDKs (mint tokens, manage rooms FROM your backend)

NOT for joining rooms — for your backend service to call the SFU's HTTP API.

| Repo / package | Language | Sophia uses? |
|---|---|---|
| **server-sdk-python** (`livekit-api` on PyPI) | Python | ✅ Required — token-mint FastAPI |
| server-sdk-go | Go | ❌ |
| server-sdk-node | Node.js | ❌ |
| server-sdk-ruby | Ruby | ❌ |
| server-sdk-java | Java | ❌ |
| server-sdk-php | PHP | ❌ |

### Tier 5 — Tooling

| Repo / package | Purpose | Sophia uses? |
|---|---|---|
| **livekit-cli (`lk`)** | CLI: `lk docs search`, `lk agent init`, token gen, room mgmt. | ✅ Dev tool |
| **agents-playground** | Web app at agents-playground.livekit.io — quick test UI; OSS source, fork for self-hosted. | ✅ Dev/test |
| livekit-helm | Kubernetes Helm charts for `livekit-server` + deps. | 🟡 If k8s in production |
| protocol | Protobuf definitions shared across server + SDKs. | ❌ Indirect dependency |

### Tier 6 — Examples / starter repos (templates, not libraries)

| Repo | Use case |
|---|---|
| `livekit-examples/agent-starter-python` | Template `my-agent` was generated from |
| `livekit-examples/agent-starter-android` | Android client template ⭐ |
| `livekit-examples/agent-starter-react` | Web client template |
| `livekit-examples/agent-starter-swift` | iOS/macOS template |
| `livekit-examples/agent-starter-flutter` | Flutter template |
| `livekit-examples/voice-assistant-react-native` | React Native template |
| `livekit-examples/agent-starter-embed` | Embeddable web widget |

### Sophia's stack (the minimal map)

| LiveKit component | Where | Role |
|---|---|---|
| **livekit-server** | AWS Docker | SFU |
| **livekit-agents** | Sophia worker (AWS) | Agent framework + orchestration |
| **livekit-plugins-silero, livekit-plugins-turn-detector** | Sophia worker (AWS) | VAD + turn detection |
| **livekit-api (Python server SDK)** | Token-mint FastAPI (AWS) | JWT issuance |
| **livekit-android** | Android phone | Client SDK |
| **lk CLI** | Developer laptop | Dev tool |
| **agents-playground** (or its source) | Web | Test UI during dev |

Six packages + a couple of dev tools. Whole LiveKit footprint for Sophia.

### Quick mental model — three categories

| Category | Components | Role |
|---|---|---|
| **Media routing** (the "wire") | livekit-server, livekit-egress, livekit-ingress, livekit-sip | Move audio/video bits across the internet |
| **Application logic** (the "brain") | livekit-agents, livekit-plugins-* | Orchestrate conversation + call models |
| **Connectivity** (the "doors") | Client SDKs + Server SDKs | Let devices and backends talk to media routing |

Sophia needs one from each category. Everything else is optional or different use case.

---

## Q32 (2026-05-14): Comprehensive playground reference — every tunable arg for Agent, AgentSession, Silero VAD, MultilingualModel, turn_handling, ai-coustics + how to observe live changes

### 1. `Assistant(Agent)` — constructor args (per-agent overrides)

| Arg | Type | Default | What it does | Tweak observation |
|---|---|---|---|---|
| `instructions` | str | — | System prompt | Personality, style, brevity, refusal behavior |
| `id` | str | snake-cased class name (`"assistant"`) | Identifier in logs/telemetry | Logs show this; multi-agent routing |
| `chat_ctx` | `ChatContext` | empty | Initial conversation history | Inject prior turns or custom system message |
| `tools` | list[Tool] | `[]` + `@function_tool` methods | Function tools the LLM can call | LLM may call them mid-conversation |
| `stt` / `vad` / `llm` / `tts` | model objects | NOT_GIVEN (session wins) | Per-agent overrides | Different agent → different model |
| `turn_handling` | `TurnHandlingOptions` dict | NOT_GIVEN | Override session's turn-handling | See section 4 |
| `mcp_servers` | list[MCPServer] | NOT_GIVEN | External MCP tool servers | Adds remote tool calls |
| `min_consecutive_speech_delay` | float | NOT_GIVEN | Min delay between consecutive agent utterances | Pause between sentences |
| `use_tts_aligned_transcript` | bool | NOT_GIVEN | Use TTS-aligned text for transcription_node | Subtle interim transcript change |

Deprecated args migrated through `_migrate_turn_handling`: `turn_detection`, `min_endpointing_delay`, `max_endpointing_delay`, `allow_interruptions`. Use `turn_handling` instead.

### 2. `AgentSession` — constructor args (session-level defaults)

| Arg | Type | Default | Effect |
|---|---|---|---|
| `stt` / `vad` / `llm` / `tts` | model objects | NOT_GIVEN | Session model defaults |
| `turn_handling` | dict | sensible defaults | Turn/interruption/endpointing config |
| `tools` | list[Tool] | NOT_GIVEN | Tools shared by all agents |
| `mcp_servers` | list[MCPServer] | NOT_GIVEN | Shared MCP tool servers |
| `max_tool_steps` | int | **3** | Max consecutive tool calls per LLM turn |
| `use_tts_aligned_transcript` | bool | NOT_GIVEN | TTS-aligned transcript |
| `tts_text_transforms` | Sequence | NOT_GIVEN | Text transforms before TTS |
| `min_consecutive_speech_delay` | float | **0.0** | Min delay between agent utterances |
| `userdata` | T | NOT_GIVEN | Arbitrary per-session data |
| `video_sampler` | _VideoSampler | None | Video capture sampler |
| `aec_warmup_duration` | float | **3.0** | AEC warmup |
| `ivr_detection` | bool | **False** | Detect IVR menus |
| `user_away_timeout` | float | **15.0** | After this much user silence, mark away |
| `session_close_transcript_timeout` | float | **2.0** | Wait for final transcripts on close |
| `conn_options` | SessionConnectOptions | NOT_GIVEN | Per-stage timeouts/retries |
| `loop` | asyncio.AbstractEventLoop | None | Custom event loop |

### 3. `silero.VAD.load()` — the VAD itself

```python
silero.VAD.load(
    min_speech_duration=0.05,
    min_silence_duration=0.55,
    prefix_padding_duration=0.5,
    max_buffered_speech=60.0,
    activation_threshold=0.5,
    sample_rate=16000,
    force_cpu=True,
    deactivation_threshold=NOT_GIVEN,    # auto = max(activation_threshold - 0.15, 0.01)
)
```

| Arg | Default | Tune up → | Tune down → |
|---|---|---|---|
| `min_speech_duration` | **0.05 s** | Misses short utterances ("yes") | Triggers on coughs |
| `min_silence_duration` | **0.55 s** | Slow turn-end | Cuts off on mid-sentence pause |
| `prefix_padding_duration` | **0.5 s** | More lead-in for STT | Clipped word starts |
| `max_buffered_speech` | **60.0 s** | Long utterances OK | Splits long speeches |
| `activation_threshold` | **0.5** | Only loud speech triggers | Triggers on background noise |
| `deactivation_threshold` | **≈0.35** auto | Stays in speech mode longer | Drops out easily |
| `sample_rate` | **16000** | 16k better accuracy | 8k = phone quality |

Typical tunes — noisy env: `activation_threshold=0.6, min_speech_duration=0.1`. Short utterances: `min_speech_duration=0.03, min_silence_duration=0.4`.

### 4. `turn_handling` (nested dict)

```python
turn_handling = {
    "turn_detection": "vad" | "stt" | "realtime_llm" | "manual" | MultilingualModel(),
    "endpointing":            { ... },
    "interruption":           { ... },
    "preemptive_generation":  { ... },
}
```

**`turn_detection`**: signal for "user done":
| Value | Effect |
|---|---|
| `"vad"` | Pure VAD silence-based |
| `"stt"` | STT final-transcript timing |
| `"realtime_llm"` | Realtime LLM server-side turn-end |
| `"manual"` | You drive turns |
| `MultilingualModel()` instance | Semantic ML detector (current setup) |

**`endpointing`**:
| Key | Default | Effect |
|---|---|---|
| `mode` | `"fixed"` | `"fixed"` constant or `"dynamic"` adaptive |
| `min_delay` | **0.5 s** | Min silence before turn complete |
| `max_delay` | **3.0 s** | Max wait before forcing turn end |
| `alpha` | **0.9** | EMA coefficient for dynamic mode |

**`interruption`**:
| Key | Default | Effect |
|---|---|---|
| `enabled` | **True** | False disables barge-in |
| `mode` | auto | `"adaptive"` ML or `"vad"` simple |
| `discard_audio_if_uninterruptible` | **True** | Drop buffered audio when uninterruptible |
| `min_duration` | **0.5 s** | Min speech to register as interruption |
| `min_words` | **0** | Min word count (STT only) |
| `resume_false_interruption` | **True** | Resume after false interrupt |
| `false_interruption_timeout` | **2.0 s** | Silence after "interrupt" → reclassify false |
| `backchannel_boundary` | **(1.0, 3.5)** | Suppress interruption at turn (start, end) |

**`preemptive_generation`**:
| Key | Default | Effect |
|---|---|---|
| `enabled` | **True** | Start LLM before turn confirmed |
| `preemptive_tts` | **False** | Start TTS preemptively too (riskier) |
| `max_speech_duration` | **10.0 s** | Skip preemption for longer utterances |
| `max_retries` | **3** | Max preemption attempts per turn |

### 5. `MultilingualModel()` — turn detector

```python
MultilingualModel(unlikely_threshold=None)
```

| Arg | Default | Effect |
|---|---|---|
| `unlikely_threshold` | None | Override per-language "unlikely end-of-turn" threshold. Lower = more eager to end. None = use language-tuned defaults. |

Internal constant `MAX_HISTORY_TURNS = 6` (`base.py:26`) — can't tune without forking.

### 6. `ai_coustics.audio_enhancement()` — noise cancellation (Cloud-locked)

```python
ai_coustics.audio_enhancement(
    model=ai_coustics.EnhancerModel.QUAIL_VF_S,
    vad_settings=ai_coustics.VadSettings(...),
    model_parameters=None,
    auth=ai_coustics.Auth.livekit_cloud(),
)
```

Models: `QUAIL_L` (largest, best), `QUAIL_VF_S` (small voice-focused), `ROOK_S` (smallest fast), deprecated `SPARROW_S`. Swap and listen for noise floor.

### 7. Inference STT / LLM / TTS args (obvious tweaks)

```python
stt = inference.STT(model="deepgram/nova-3", language="multi", interim_results=True, ...)
llm = inference.LLM(model="openai/gpt-5.2-chat-latest", temperature=0.7, max_tokens=200, ...)
tts = inference.TTS(model="cartesia/sonic-3", voice="...", speed=1.0, ...)
```

Common args: `model`, `language`, `temperature`, `voice`, `speed`. Per-provider knobs (emotion, style, etc.) vary.

### How to observe changes live — playground methodology

**A. Dev mode = hot reload:** `uv run python src/agent.py dev` — edit & save → worker restarts.

**B. Crank logging:** `logging.basicConfig(level=logging.DEBUG)` — see VAD frames, STT chunks, LLM tokens, TTS chunks, turn events.

**C. Add per-stage timing:**
```python
@session.on("user_input_transcribed")
def on_transcribed(ev):
    logger.info(f"[STT done] {ev.transcript!r} @ {time.time()}")

@session.on("agent_state_changed")
def on_state(ev):
    logger.info(f"[state] {ev.old_state} → {ev.new_state} @ {time.time()}")
```
Gap from user-stop-speaking to TTS-first-byte = end-to-end latency.

**D. Test specific behaviors:**

| Want to observe | Set |
|---|---|
| Barge-in default | Default; talk over agent |
| No interruption | `turn_handling={"interruption": {"enabled": False}}` |
| VAD eager | `silero.VAD.load(activation_threshold=0.2)` |
| VAD lazy | `activation_threshold=0.8` |
| Endpoint slow | `endpointing: {"min_delay": 2.0}` |
| Endpoint fast | `endpointing: {"min_delay": 0.1}` |
| No preemption | `preemptive_generation: {"enabled": False}` (slower) |
| Tool chain limit | `max_tool_steps=1` |

**E. Side-by-side compare:** two terminals, different `agent_name`. Talk to each via Playground separately.

**F. Record for A/B:** macOS QuickTime > New Audio Recording, or ffmpeg. Listen without live-interaction bias.

### Suggested tweak sequence (start here)

1. Logging → DEBUG, talk one turn, read log
2. VAD `activation_threshold` at 0.3, 0.5, 0.7
3. Endpointing `min_delay` at 0.2, 0.5, 1.0 — pause mid-sentence
4. Preemption off → feel latency baseline; turn back on; confirm gain
5. Interruption off → barge in fails
6. Instructions: "be brief" → "verbose with examples"
7. TTS voice — different Cartesia voice ID
8. LLM temperature: 0.0 vs 1.2

~couple hours of tweaking = full intuition for the pipeline.

---

## Q33 (2026-05-14): Why exactly is VAD needed, and why is turn handling needed? Main purpose of each and how each argument contributes to that purpose.

**Two different questions, two different time scales — often conflated but solve completely different problems.**

### Core distinction

| Question | Asked by | Time scale |
|---|---|---|
| **"Is the user PHYSICALLY making sound RIGHT NOW?"** | VAD | Per audio frame (~30 ms) |
| **"Is the user DONE EXPRESSING their thought?"** | Turn detector | Per utterance (~seconds) |

VAD is **mechanical** — does this frame contain speech energy? Turn detection is **semantic** — does this utterance feel complete?

### Why VAD is needed — purpose: detect speech presence per frame

VAD is the per-frame primitive everything else builds on. Without it:
- STT receives constant silence/noise — wasted compute, bad transcripts.
- No barge-in (can't detect user speaking while agent talks).
- No "user started speaking" event.
- Agent either listens to everything or to nothing.

VAD output is NOT raw per-frame decisions — it's a clean stream of `SpeechStarted` / `SpeechEnded` events with timestamps, computed by aggregating frame-level probabilities through hysteresis and duration filters.

### Silero VAD args — each serves "detect speech per frame, robustly"

| Arg | What it controls | Contribution |
|---|---|---|
| `activation_threshold=0.5` | ENTER threshold: probability ≥ this → "speech" | Direct main-classifier knob. Higher = stricter. |
| `deactivation_threshold` (auto ≈ 0.35) | EXIT threshold: probability < this → "not speech" | Hysteresis — once in speech mode, lower bar to stay. Prevents flickering when intra-word energy briefly dips. |
| `min_speech_duration=0.05 s` | Reject chunks shorter than this | Filters single-frame false positives (clicks, pops). Speech must be ≥50 ms. |
| `min_silence_duration=0.55 s` | Required silence to declare speech ENDED | Smooths over normal between-word gaps. Without this, every micro-pause would fire SpeechEnded. |
| `prefix_padding_duration=0.5 s` | Audio kept BEFORE detected speech start | Captures word onset that the model itself might miss. STT gets the lead-in syllable. |
| `max_buffered_speech=60.0 s` | Cap on single chunk length | Memory cap. Forces chunk boundary after 60 s for very long utterances. |
| `sample_rate=16000` | Audio rate for inference | Required by Silero model (trained on 16 kHz) |
| `force_cpu=True` | Where to run inference | Perf knob, no behavioral change |

**None of these args know about conversation, turns, or LLMs.** They're all about making frame-level "is there speech?" decisions robust. VAD doesn't decide when a turn is over, doesn't know what the user said, doesn't know if a thought is complete.

### Why turn handling is needed — purpose: decide when USER'S UTTERANCE is complete enough to send to the LLM

VAD can tell you "silence detected for 550 ms" — but silence ≠ turn end:

| User says | Silence after | Turn complete? |
|---|---|---|
| "what's the weather today" | 600 ms | ✅ Yes — clear question |
| "I want to know about… uh…" | 800 ms | ❌ No — mid-thought hesitation |
| "Let me think…" | 1500 ms | ❌ No — thinking pause |
| "ok" | 400 ms | ✅ Yes — short but complete |

A pure silence-timeout can't distinguish these. Set timeout low → cut off mid-sentence. Set high → painful waits after short complete questions.

That's why semantic turn detection (`MultilingualModel`) exists. Reads recent transcript, predicts probability user is done. "I want to know about" with a pause → P(done) low. "what's the weather today" with a pause → P(done) high.

Plus turn handling owns more than just end-of-turn detection — it handles **barge-in** (user speaks while agent talks), **endpointing** (timing rule), and **preemptive generation** (speculative LLM call).

### turn_handling args — each serves a sub-purpose

**`turn_detection` — WHICH signal decides "user done"**

| Value | Contribution |
|---|---|
| `"vad"` | Use only silence timeout. Cheap, dumb. Cuts off pauses. |
| `"stt"` | Use STT's own endpointing. Variable quality. |
| `MultilingualModel()` | Semantic — reads transcript history, predicts P(end). Smartest. Sophia's current setting. |
| `"realtime_llm"` | Realtime API emits server-side turn events |
| `"manual"` | You drive turns programmatically |

**`endpointing` sub-dict — WHEN to declare turn over** (timing rules even with a semantic detector)

| Arg | Default | Contribution |
|---|---|---|
| `mode: "fixed"`/`"dynamic"` | "fixed" | Constant timeout vs adaptive |
| `min_delay=0.5 s` | 0.5 | Floor — even if detector is sure, wait at least this long. Prevents over-eagerness. |
| `max_delay=3.0 s` | 3.0 | Ceiling — force turn-end after this long. Prevents infinite waits. |
| `alpha=0.9` | 0.9 | EMA history weight for dynamic mode |

**`interruption` sub-dict — barge-in (different from turn-end)**

Turn-end = user finished, now agent talks. Barge-in = agent is talking, user speaks anyway.

| Arg | Default | Contribution |
|---|---|---|
| `enabled=True` | True | Master switch — set False = agent always finishes |
| `mode: "adaptive"`/`"vad"` | auto | ML-based vs raw VAD trigger |
| `min_duration=0.5 s` | 0.5 | Filters coughs/clicks — must speak ≥500 ms |
| `min_words=0` | 0 | Min word count (STT mode only) |
| `discard_audio_if_uninterruptible=True` | True | When uninterruptible, drop buffered audio (don't queue interruption for later) |
| `resume_false_interruption=True` | True | Brief interrupt → agent resumes original utterance |
| `false_interruption_timeout=2.0 s` | 2.0 | After this silence post-interrupt → reclassify as false |
| `backchannel_boundary=(1.0, 3.5)` | (1.0, 3.5) | Suppress interruption at (start, end) of agent's turn. Handles "mm-hmm" backchannels and STT timestamp drift. |

**`preemptive_generation` sub-dict — speculative LLM call**

While turn detector is computing, start LLM in parallel. Save latency.

| Arg | Default | Contribution |
|---|---|---|
| `enabled=True` | True | Start LLM speculatively when detector leans toward end |
| `preemptive_tts=False` | False | Also start TTS speculatively (riskier) |
| `max_speech_duration=10.0 s` | 10.0 | Skip preemption for utterances longer than this |
| `max_retries=3` | 3 | Cap on speculative-call retries per turn |

**`MultilingualModel()` args**

| Arg | Default | Contribution |
|---|---|---|
| `unlikely_threshold` | `None` (per-language defaults) | Override "unlikely end-of-turn" threshold. Lower = more eager to end. |

Internal `MAX_HISTORY_TURNS=6` — only last 6 turns sent for prediction. Not user-tunable.

### Lifecycle — VAD and turn handling in cooperation

```
User starts speaking
  ↓
[VAD] activation_threshold crossed for >min_speech_duration → SpeechStarted
  ↓
[STT] streams audio, emits interim transcripts
[Turn detector] reads interims, computes P(end) continuously
  ↓
User pauses
  ↓
[VAD] silence >min_silence_duration → SpeechEnded (just means "no more sound")
  ↓
[Endpointing] starts countdown (must wait min_delay before turn ends)
[Turn detector] given final transcript, predicts P(end)
  ↓
Decision branch:
  IF turn detector P > threshold AND endpointing min_delay elapsed:
    → Turn confirmed, send to LLM (or use preemptive result)
    → TTS speaks response
  IF P low AND max_delay not elapsed:
    → Wait. User probably paused mid-thought.
  IF max_delay elapsed regardless:
    → Force turn end

While agent speaking:
  [VAD] runs continuously
  IF user speech duration > min_interruption_duration AND not in backchannel_boundary:
    → Barge-in! Cancel TTS, cancel LLM, return to listening
  IF brief speech then silence > false_interruption_timeout AND resume_false_interruption:
    → Resume agent's original utterance from where it stopped
```

### Why we need BOTH together

| Approach | Pros | Cons |
|---|---|---|
| VAD alone (`turn_detection="vad"`) | Cheap, no extra model | Cuts off mid-sentence pauses, can't distinguish hesitation |
| Turn detector alone | Semantic, accurate | Needs VAD silence events as trigger |
| STT-based (`turn_detection="stt"`) | Free (STT engine usually has endpointing) | Variable quality; not as smart as semantic |
| **VAD + MultilingualModel (Sophia's current)** | Best — VAD handles fast per-frame events, turn detector handles slow semantic completeness | More compute (extra ONNX); more args to tune |

### One-line summaries

> **VAD**: "Per frame, is there speech right now?" — answers cheaply at millisecond scale. Args tune how robustly frame probabilities collapse into clean `SpeechStarted` / `SpeechEnded` events.
>
> **Turn handling**: "Now that speech ended, is the user actually DONE with their thought, and what should happen next?" — answers semantically at second scale. Args tune end-of-turn detection, endpointing timing, interruption behavior, and preemptive generation.

VAD gives temporal scaffolding (when sound starts/stops); turn detection gives semantic scaffolding (when a thought is complete). Complementary, not redundant.

---

## Q34 (2026-05-14): VAD and turn handling are tunable args for the STT side of the pipeline. What are the analogous tunable args for LLM and TTS — both at the framework (Agent / AgentSession) level and at the plugin level?

Verified by reading `voice/agent_session.py` (lines 217–322), `voice/agent.py` (lines 36–113, 283–367), `voice/turn.py` (lines 47–185), `llm/llm.py` (lines 134–144), `tts/tts.py` (lines 66–127), and `types.py` (lines 74–112).

**Key reframe:** the STT side is unusual — VAD/turn-handling args live almost entirely at the framework level because they're orchestration-of-time concerns. For LLM and TTS, the symmetry is split into **three concentric rings**:

```
[ Plugin constructor ]      ← model quality knobs (temperature, voice, speed)         ← per-provider
[ Agent / Session args ]    ← orchestration (when to call, how many retries, what to filter)
[ turn_handling block ]     ← timing/UX (when to interrupt, when to preempt, endpointing windows)
```

Quality-of-output knobs (temperature, voice, speed, sample_rate, emotion) sit in the **plugin constructor**, NOT on `Agent` — because they're inherently provider-specific and the framework stays provider-agnostic.

### Three-column symmetry

| Pipeline stage | Framework knobs (Agent / AgentSession) | Plugin-constructor knobs (provider-specific) |
|---|---|---|
| **STT input** | `vad`, `turn_handling.{turn_detection, endpointing, interruption}` | model name, language, beam_size, punctuation, etc. (set in `deepgram.STT(...)`, `openai.STT(...)`) |
| **LLM** | `instructions`, `tools`, `mcp_servers`, `chat_ctx`, `max_tool_steps`, `turn_handling.preemptive_generation`, `conn_options.llm_conn_options`, `max_unrecoverable_errors` | `model`, `temperature`, `top_p`, `max_completion_tokens`, `parallel_tool_calls`, `response_format` (set in `openai.LLM(...)`) |
| **TTS output** | `tts_text_transforms`, `use_tts_aligned_transcript`, `aec_warmup_duration`, `min_consecutive_speech_delay`, `turn_handling.interruption.*`, `turn_handling.preemptive_generation.preemptive_tts`, `conn_options.tts_conn_options`, `session_close_transcript_timeout` | `voice`, `speed`, `language`, `emotion`, `sample_rate`, SSML support (set in `cartesia.TTS(...)`, `openai.TTS(...)`) |

### LLM-stage Agent/Session args (one-liners)

| Arg | Where | Default | What it tunes |
|---|---|---|---|
| `instructions` | Agent | required | System prompt — biggest behavior lever |
| `tools` | Agent + Session | `[]` | `FunctionTool` list the LLM can call |
| `mcp_servers` | Agent + Session | `None` | External MCP-served tools |
| `chat_ctx` | Agent | empty | Pre-seeded conversation history |
| `max_tool_steps` | Session | `3` | Caps consecutive tool-call loops per user turn |
| `turn_handling.preemptive_generation.enabled` | Session | `True` | Run LLM speculatively before user finishes speaking |
| `…preemptive_generation.preemptive_tts` | Session | `False` | Also run TTS speculatively (latency↓, cost↑) |
| `…preemptive_generation.max_speech_duration` | Session | `10.0` s | Skip preemption for utterances longer than this |
| `…preemptive_generation.max_retries` | Session | `3` | How many speculative attempts per turn |
| `conn_options.llm_conn_options` | Session | `APIConnectOptions(max_retry=3, retry_interval=2.0, timeout=10.0)` | LLM HTTP resilience |
| `max_unrecoverable_errors` | Session (in `SessionConnectOptions`) | `3` | Session-kill threshold for repeat LLM/TTS failures |
| `tool_choice` | per-call (`session.generate_reply(...)`) | NOT_GIVEN | Force/forbid a tool for one turn |

**Plugin-call args** (in `LLM.chat(...)` signature): `parallel_tool_calls`, `tool_choice`, plus a generic `extra_kwargs: dict[str, Any]` escape hatch for everything else (temperature, top_p, max_tokens, response_format, …) — provider plugins typically expose these as constructor args and forward them through `extra_kwargs`.

**Override hook:** `Agent.llm_node(chat_ctx, tools, model_settings)` — async generator wrapping the entire LLM call. This is where a custom `AwsRagLLM` plugin hooks in (or where you intercept `chat_ctx` to inject retrieved docs, log per-turn timing, swap models mid-conversation, etc.).

### TTS-stage Agent/Session args (one-liners)

| Arg | Where | Default | What it tunes |
|---|---|---|---|
| `tts_text_transforms` | Session + Agent | `["filter_markdown", "filter_emoji"]` | Strips markdown/emoji before TTS sees it (so the agent doesn't say "asterisk asterisk hello") |
| `use_tts_aligned_transcript` | Session + Agent | disabled | Use TTS's word-level timing for the transcript stream — better caption sync (only if `TTS.capabilities.aligned_transcript=True` or non-streaming) |
| `aec_warmup_duration` | Session | `3.0` s | Ignore user audio for first N seconds of agent speech — prevents echo before AEC stabilizes from being mistaken for barge-in |
| `min_consecutive_speech_delay` | Session + Agent | `0.0` s | Minimum gap between back-to-back agent utterances |
| `session_close_transcript_timeout` | Session | `2.0` s | Wait for final TTS-aligned transcript when closing |
| `turn_handling.interruption.enabled` | Session | `True` | Whether the user can barge in at all |
| `…interruption.mode` | Session | auto | `"adaptive"` (ML) vs `"vad"` (pure VAD) |
| `…interruption.discard_audio_if_uninterruptible` | Session | `True` | Drop user audio buffered during non-interruptible TTS |
| `…interruption.min_duration` | Session | `0.5` s | Min user-speech length to count as a real interrupt |
| `…interruption.min_words` | Session | `0` | Min word count to count as interrupt (STT-driven) |
| `…interruption.resume_false_interruption` | Session | `True` | Resume TTS if interrupt turns out to be false |
| `…interruption.false_interruption_timeout` | Session | `2.0` s | How long of silence reclassifies an interrupt as false |
| `…interruption.backchannel_boundary` | Session | `(1.0, 3.5)` | Suppress interruption sensitivity at TTS start/end (lets user say "uh-huh" without cutting agent off) |
| `conn_options.tts_conn_options` | Session | `APIConnectOptions(max_retry=3, retry_interval=2.0, timeout=10.0)` | TTS HTTP resilience |

**Override hooks (run in this order):**
1. `Agent.transcription_node(text)` — runs **between** LLM and TTS. Post-process LLM text before synthesis (expand abbreviations, fix pronunciation, inject SSML, replace "$5" with "five dollars", etc.).
2. `Agent.tts_node(text)` — wraps the entire TTS synthesis. Replace tokenization, swap engine mid-conversation, etc.

### Key insight: most "interruption" args are TTS-side, not STT-side

Re-reading Q33's mental model with this lens: the `turn_handling.interruption.*` block is **mostly about TTS playback control** — when to cut TTS off (`enabled`, `mode`, `min_duration`, `min_words`), what to do with buffered user audio while TTS speaks (`discard_audio_if_uninterruptible`), how to recover from false barge-ins (`resume_false_interruption`, `false_interruption_timeout`), and when to be lenient (`backchannel_boundary`). VAD/turn-detection produce the *signal*; interruption args decide *how TTS reacts* to that signal.

### Why temperature isn't on `Agent` (and voice/speed aren't either)

These would force the framework to know about every provider's parameter set. Instead:
- `openai.LLM(model="gpt-4o", temperature=0.7, top_p=0.9, max_completion_tokens=512, parallel_tool_calls=True, ...)` — set when you construct the plugin
- `cartesia.TTS(voice="...", speed="normal", language="en", emotion=[...], sample_rate=24000, ...)` — same pattern

Same as Silero VAD: `silero.VAD.load(activation_threshold=0.5, min_silence_duration=0.55, ...)` — the args live on the plugin's constructor; the framework only sees the resulting `VAD` object.

For Sophia's `AwsRagLLM` plugin, this means we get to define our own constructor knobs (`endpoint_url`, `top_k`, `rerank=True`, `flatten_history=True`, `streaming=False`, `request_timeout=…`) without touching the framework signature. The framework sees just an `LLM` object and asks it to `.chat(chat_ctx=..., tools=..., conn_options=...)`.

---

## Q35 (2026-05-14): For each model used in `my-agent` (STT, LLM, TTS), what is the actual code flow at runtime, and what arguments can be tweaked at construction vs per-call?

Verified against `my-agent/src/agent.py` and the inference plugin sources (`inference/stt.py:341/482`, `inference/llm.py:189/262`, `inference/tts.py:314/550`), plus runtime callers in `voice/audio_recognition.py:107`, `voice/agent.py` default nodes, and `voice/generation.py`.

### Important upfront note: `inference.X` is NOT `livekit.plugins.<provider>.X`

`my-agent` uses `livekit.agents.inference.{STT, LLM, TTS}` — these are **proxy plugins**: they talk to LiveKit Cloud's Inference endpoint, which then forwards to Deepgram/OpenAI/Cartesia. Same provider behind the scenes, but the wire path is:

```
worker → wss://<LIVEKIT_URL>/inference → LiveKit Inference → provider → response
```

Auth: an **ephemeral access token** built from `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` (via `create_access_token(...)` — see `inference/llm.py:234`). No provider API key needed; LiveKit Cloud holds those.

When Sophia self-hosts or swaps to its own GPU models, this layer goes away — replaced with `livekit.plugins.deepgram.STT(...)` (direct, you supply DEEPGRAM_API_KEY) or a custom plugin like `AwsRagLLM`. Constructor shapes are similar but the `extra_kwargs` indirection becomes direct first-class kwargs in the provider plugin.

### 1. STT — `inference.STT(model="deepgram/nova-3", language="multi")`

**Constructor signature** (`inference/stt.py:341`):

```python
inference.STT(
    model: str,                          # "provider/model[:language]"
    *,
    language: str = NOT_GIVEN,
    encoding: "pcm_s16le" = "pcm_s16le",
    sample_rate: int = 16000,
    base_url: str = LIVEKIT_URL,         # auto from env
    api_key: str = LIVEKIT_API_KEY,
    api_secret: str = LIVEKIT_API_SECRET,
    http_session: aiohttp.ClientSession | None = None,
    extra_kwargs: DeepgramOptions | dict = {},   # ← provider-specific knobs
    fallback: list[FallbackModel] = NOT_GIVEN,   # auto-failover (Inference-only)
    conn_options: APIConnectOptions = APIConnectOptions(max_retry=3, retry_interval=2.0, timeout=10.0),
)
```

**Deepgram-specific `extra_kwargs`** (`inference/stt.py:62`):

| Key | Default | Purpose |
|---|---|---|
| `filler_words` | True | Keep "um", "uh" |
| `interim_results` | True | Emit partial transcripts |
| `endpointing` | 25 ms | Silence ms before utterance-final |
| `punctuate` | True | Add punctuation |
| `smart_format` | — | Auto-format phone numbers, dates |
| `keywords` | — | `[("XREAL", 2.0), ("Sophia", 1.5)]` boost |
| `keyterm` | — | Key-term bias (string or list) |
| `numerals` | — | "five" → "5" |
| `diarize` | False | Speaker labels (auto-enables capability) |
| `detect_language` | — | Auto language detection |
| `no_delay` | True | Lower latency, less stable |
| `vad_events` | False | Emit VAD start/stop in stream |
| `profanity_filter`, `dictation`, `redact`, `replace`, `search`, `tag`, `channels`, `version` | — | misc |

Other providers exposed by `inference.STT`: Cartesia, Deepgram Flux, AssemblyAI, ElevenLabs, xAI — each with its own TypedDict for `extra_kwargs` (see `inference/stt.py:57–127`).

**Runtime call chain:**

```
[mic audio → SFU → Worker subprocess → AgentSession audio input forwarder]
   │
   ▼
Agent.stt_node(audio_stream, model_settings)             ← override hook
   │ Default impl wraps STT in StreamAdapter if non-streaming
   ▼
inference.STT.stream(language=..., conn_options=...)     (inference/stt.py:482)
   │ Returns a SpeechStream
   ▼
SpeechStream.push_frame(rtc.AudioFrame) ← driven by _forward_input task
   │ Frames sent over WebSocket to LIVEKIT_URL/inference
   │ LiveKit Inference forwards to Deepgram nova-3
   ▼
Events stream back: stt.SpeechEventType.{INTERIM_TRANSCRIPT, FINAL_TRANSCRIPT}
   │
   ▼
_RecognitionPump pumps events into event_ch              (audio_recognition.py:107)
   │
   ▼
AudioRecognition.on_event():
   - accumulates final transcripts
   - notifies VAD + MultilingualModel turn detector (in inference runner subprocess)
   │
   ▼
Turn detector returns "done" → hooks.commit_user_turn(transcript) → LLM stage starts
```

**Tunable per-call vs constructor:**

| Constructor (set once) | Per `.stream()` call |
|---|---|
| `model`, `extra_kwargs`, `fallback`, `sample_rate`, `encoding`, language defaults | `language` (override), `conn_options` |

### 2. LLM — `inference.LLM(model="openai/gpt-5.2-chat-latest")`

**Constructor signature** (`inference/llm.py:189`):

```python
inference.LLM(
    model: str,                                   # "provider/model"
    *,
    provider: str | None = None,
    base_url: str = LIVEKIT_URL,
    api_key: str = LIVEKIT_API_KEY,
    api_secret: str = LIVEKIT_API_SECRET,
    inference_class: "priority" | "standard" | None = None,
    extra_kwargs: ChatCompletionOptions | dict = None,    # session-wide defaults
)
```

**Full `ChatCompletionOptions` knobs** (`inference/llm.py:144`):

| Key | Type | Purpose |
|---|---|---|
| `temperature` | float | Sampling temperature (0–2) |
| `top_p` | float | Nucleus sampling |
| `max_completion_tokens` | int | Cap on output length (preferred) |
| `max_tokens` | int | Legacy cap |
| `frequency_penalty`, `presence_penalty` | float | Repetition penalties |
| `stop` | str / list | Stop sequences |
| `seed` | int | Reproducibility |
| `n` | int | Number of completion choices |
| `logprobs`, `top_logprobs` | bool / int | Log-probability output |
| `parallel_tool_calls` | bool | Multiple tool calls per turn |
| `reasoning_effort` | "low"/"medium"/"high" | For reasoning models |
| `verbosity` | "low"/"medium"/"high" | Response length hint |
| `service_tier` | enum | "auto"/"default"/"flex"/"scale"/"priority" |
| `prompt_cache_key` + `prompt_cache_retention` | str + "in_memory"/"24h" | Prompt caching |
| `safety_identifier`, `metadata`, `user` | misc | Tracking / safety attribution |
| `web_search_options` | dict | OpenAI web search |
| `tool_choice` | "auto"/"required"/"none"/specific | Force tool behavior |
| `modalities` | list | text vs audio output |
| `prediction` | dict | Predicted-output speedup |

Tweak example:
```python
llm=inference.LLM(
    model="openai/gpt-5.2-chat-latest",
    extra_kwargs={
        "temperature": 0.4,
        "max_completion_tokens": 200,
        "reasoning_effort": "low",
        "prompt_cache_key": "sophia-system-v1",
    },
)
```

**Runtime call chain:**

```
[final user transcript, turn confirmed]
   │
   ▼
AgentActivity._on_user_turn_completed()                 (voice/agent_activity.py)
   │ Updates session.history with user message
   ▼
generate_reply() builds ChatContext + tools list        (voice/generation.py)
   │
   ▼
Agent.llm_node(chat_ctx, tools, model_settings)         ← override hook
   │ Default: calls activity.llm.chat(...)
   ▼
inference.LLM.chat(                                     (inference/llm.py:262)
    chat_ctx=ChatContext(items=[...full history...]),
    tools=[FunctionTool, ...],
    conn_options=APIConnectOptions(...),
    parallel_tool_calls=NOT_GIVEN,
    tool_choice=NOT_GIVEN,
    response_format=NOT_GIVEN,
    inference_class=NOT_GIVEN,
    extra_kwargs=NOT_GIVEN,
)
   │ Uses openai.AsyncClient pointed at LIVEKIT_URL/inference
   │ with ephemeral access_token built from LiveKit API_KEY+SECRET
   │ Streams chat-completion chunks over HTTPS
   ▼
LLMStream yields llm.ChatChunk objects (text deltas + tool-call deltas)
   │
   ▼
generate_reply consumes chunks:
   - text deltas      → forwarded into TTS pipeline (transcription_node, tts_node)
   - tool_call deltas → executes @function_tool, may loop up to max_tool_steps (default 3)
   - usage stats      → recorded into ChatMessage.metrics
   │
   ▼
ChatContext updated with assistant message; turn ends
```

**Tunable per-call vs constructor:**

| Constructor (defaults for every call) | Per `.chat()` call (override) |
|---|---|
| `extra_kwargs` (all ChatCompletionOptions), `inference_class` | `parallel_tool_calls`, `tool_choice`, `response_format`, `inference_class`, `extra_kwargs` |

### 3. TTS — `inference.TTS(model="cartesia/sonic-3", voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc")`

**Constructor signature** (`inference/tts.py:314`):

```python
inference.TTS(
    model: str,                                # "provider/model[:voice]"
    *,
    voice: str = NOT_GIVEN,
    language: str = NOT_GIVEN,
    encoding: "pcm_s16le" = "pcm_s16le",
    sample_rate: int = 24000,
    base_url: str = LIVEKIT_URL,
    api_key: str = LIVEKIT_API_KEY,
    api_secret: str = LIVEKIT_API_SECRET,
    http_session: aiohttp.ClientSession | None = None,
    extra_kwargs: CartesiaOptions | dict = {},
    fallback: list[FallbackModel] = NOT_GIVEN,
    conn_options: APIConnectOptions = ...,
)
```

**Cartesia-specific `extra_kwargs`** (`inference/tts.py:127`):

| Key | Type | Purpose |
|---|---|---|
| `emotion` | str | "happy", "sad", "neutral", … |
| `speed` | "slow"/"normal"/"fast" or float | Playback speed |
| `volume` | float | Output volume |
| `duration` | float | Target duration (s) |
| `max_buffer_delay_ms` | int | Buffering tolerance |
| `add_timestamps` | bool | Word-level timing (enables `aligned_transcript=True`) |
| `add_phoneme_timestamps` | bool | Phoneme-level timing |
| `use_normalized_timestamps` | bool | Normalize timing values |

Other providers' `extra_kwargs`:
- **ElevenLabs** (`inference/tts.py:142`): `stability` (0–1), `similarity_boost` (0–1), `style` (0–1), `speed` (0.25–4), `apply_text_normalization`, `auto_mode`, `enable_ssml_parsing`, `sync_alignment`, `language_code`, `chunk_length_schedule`, `use_speaker_boost`, `inactivity_timeout` (5–180s), `enable_logging`, `preferred_alignment`
- **Deepgram TTS**: `mip_opt_out`
- **Rime** (`inference/tts.py:159`): `speed_alpha` (default 1.0, <1 faster), `pause_between_brackets`, `phonemize_between_brackets`, `inline_speed_alpha`, `no_text_normalization`
- **Inworld** (`inference/tts.py:171`): `speaking_rate` (0.5–1.5), `temperature` (0–2), `timestamp_type`, `apply_text_normalization`

**Runtime call chain:**

```
[LLM streams text chunks from llm_node]
   │
   ▼
Agent.transcription_node(text_stream, model_settings)   ← override hook (post-LLM, pre-TTS)
   │ Default applies tts_text_transforms (filter_markdown, filter_emoji)
   ▼
Agent.tts_node(text_stream, model_settings)             ← override hook
   │ Default wraps TTS in StreamAdapter if non-streaming
   ▼
inference.TTS.stream(conn_options=...)                  (inference/tts.py:550)
   │ Returns SynthesizeStream
   ▼
SynthesizeStream.push_text(chunk) ← driven by _forward_input task
   │ Text sent over WebSocket to LIVEKIT_URL/inference
   │ LiveKit Inference forwards to Cartesia sonic-3
   ▼
SynthesizedAudio events stream back, each carrying rtc.AudioFrame
   │
   ▼
tts_node yields frames
   │
   ▼
SpeechHandle scheduler:
   - applies turn_handling.interruption.* rules (when to cut off)
   - applies aec_warmup_duration (ignore user audio for first 3s of speech)
   - applies min_consecutive_speech_delay
   │
   ▼
Frames published to SFU output track → routed to client → played in user's ear
```

Note: `synthesize(text)` is one-shot; `stream()` is the streaming path. Cartesia/Deepgram/ElevenLabs all support streaming, so `stream()` runs in `my-agent`.

**Tunable per-call vs constructor:**

| Constructor (set once) | Per `.stream()` / `.synthesize()` call |
|---|---|
| `voice`, `language`, `extra_kwargs`, `fallback`, `sample_rate`, `encoding` | `conn_options` |

### Three-ring summary applied to `my-agent`

| Stage | Plugin object in agent.py | Provider knobs (extra_kwargs) | Framework knobs (Agent/Session) | turn_handling block |
|---|---|---|---|---|
| **STT** | `inference.STT("deepgram/nova-3", language="multi")` | endpointing, keywords, smart_format, diarize, … | `vad`, `stt`, `Agent.stt_node` override | `turn_detection`, `endpointing.{min_delay, max_delay}` |
| **LLM** | `inference.LLM("openai/gpt-5.2-chat-latest")` | temperature, max_completion_tokens, reasoning_effort, parallel_tool_calls, … | `instructions`, `tools`, `mcp_servers`, `chat_ctx`, `max_tool_steps`, `Agent.llm_node` override | `preemptive_generation.{enabled, max_speech_duration}` |
| **TTS** | `inference.TTS("cartesia/sonic-3", voice="…")` | emotion, speed, volume, add_timestamps, … | `tts_text_transforms`, `use_tts_aligned_transcript`, `aec_warmup_duration`, `Agent.transcription_node`, `Agent.tts_node` overrides | `interruption.*` (mostly TTS-reaction), `preemptive_generation.preemptive_tts` |

**Key Inference-only feature: `fallback=`** — list backup models and LiveKit Inference will fail over server-side without your code reconnecting. Lost when swapping to direct `livekit.plugins.<provider>.X` or to a custom plugin like Sophia's `AwsRagLLM`.

---

## Q36 (2026-05-15): `my-agent` currently uses `silero.VAD.load(...)`. Can I write my own VAD plugin for my own VAD model, in a `vad.py` inside `my-agent/src/plugins/`, with my own `load()` args (similar to how Silero exposes `min_speech_duration`, `activation_threshold`, etc.)?

**Yes, exactly that pattern.** The framework is fully designed for it. Verified against `livekit-agents/livekit/agents/vad.py` (lines 19–115).

### What the framework requires (the contract)

The framework defines a base `VAD` class and an event contract. Anything that implements both can be passed as `vad=` to `AgentSession`. The framework does NOT care:
- Whether your model is ONNX, PyTorch, MLX, a remote HTTP API, or a C++ extension
- What args your `load()` factory takes
- How you compute "is this speech" internally

It only cares that your `.stream()` returns a `VADStream` that emits properly-shaped `VADEvent`s with types `START_OF_SPEECH`, `INFERENCE_DONE`, `END_OF_SPEECH`.

### Why Silero's load() args look the way they do

Silero's args (`min_speech_duration=0.05`, `min_silence_duration=0.55`, `prefix_padding_duration=0.5`, `max_buffered_speech=60.0`, `activation_threshold=0.5`, `deactivation_threshold` (auto), `sample_rate`, `force_cpu`, `onnx_file_path`) are **Silero-specific**. They exist because Silero is a per-frame binary classifier whose raw frame probabilities need hysteresis + duration filters in post-processing to produce clean `START_OF_SPEECH` / `END_OF_SPEECH` events.

Your custom VAD might need totally different args:
- Another ONNX classifier → probably similar (threshold + smoothing)
- A streaming VAD with built-in event detection → maybe just `model_url`, `chunk_ms`
- A remote API VAD (Picovoice Cobra, custom AWS endpoint) → `endpoint`, `api_key`, `language`
- A diarization-aware VAD → speaker thresholds, max speakers

You decide your own `load()` signature based on your model. The framework imposes nothing.

### File layout (per `my-agent/AGENTS.md` convention)

```
my-agent/
  src/
    agent.py
    plugins/
      __init__.py
      yourvad.py    <-- new file
```

### Required class skeleton

```python
# my-agent/src/plugins/yourvad.py
from __future__ import annotations
from typing import Literal
from livekit.agents import vad
from livekit import rtc


class YourVAD(vad.VAD):
    """Your custom VAD plugin."""

    @classmethod
    def load(
        cls,
        *,
        # YOU define these args -- whatever your model needs.
        model_path: str | None = None,
        threshold: float = 0.5,
        sample_rate: Literal[8000, 16000, 24000] = 16000,
        chunk_size_ms: int = 30,
        smoothing_window_ms: int = 200,
        force_cpu: bool = True,
        # ...whatever else
    ) -> "YourVAD":
        instance = cls(
            capabilities=vad.VADCapabilities(update_interval=chunk_size_ms / 1000.0),
        )
        instance._model = ...  # your loaded model
        instance._threshold = threshold
        instance._sample_rate = sample_rate
        return instance

    @property
    def model(self) -> str:
        return "your-model-name-v1"

    @property
    def provider(self) -> str:
        return "your-org"

    def stream(self) -> "YourVADStream":
        return YourVADStream(self)


class YourVADStream(vad.VADStream):
    async def _main_task(self) -> None:
        speech_started_ts = None
        accumulated_silence = 0.0
        accumulated_speech = 0.0

        async for input in self._input_ch:
            if isinstance(input, self._FlushSentinel):
                continue

            frame: rtc.AudioFrame = input

            # 1. Run YOUR model on this frame
            prob = self._vad._model.run(frame)

            # 2. Emit INFERENCE_DONE every frame (optional but enables metrics)
            self._event_ch.send_nowait(vad.VADEvent(
                type=vad.VADEventType.INFERENCE_DONE,
                samples_index=...,
                timestamp=...,
                speech_duration=accumulated_speech,
                silence_duration=accumulated_silence,
                probability=prob,
                speaking=prob > self._vad._threshold,
            ))

            # 3. Cross threshold -> START_OF_SPEECH or END_OF_SPEECH
            if prob > self._vad._threshold and speech_started_ts is None:
                speech_started_ts = ...
                self._event_ch.send_nowait(vad.VADEvent(
                    type=vad.VADEventType.START_OF_SPEECH,
                    ...
                ))
            elif prob < self._vad._threshold and speech_started_ts is not None:
                self._event_ch.send_nowait(vad.VADEvent(
                    type=vad.VADEventType.END_OF_SPEECH,
                    ...
                ))
                speech_started_ts = None
```

The two methods you MUST implement:
- `VAD.stream()` — return a `VADStream` instance
- `VADStream._main_task()` — async loop that consumes audio frames from `self._input_ch` and emits `VADEvent`s into `self._event_ch`

Everything else (constructor, `model` / `provider` properties, `update_options`) is optional / has defaults.

### Wire it into `agent.py`

```python
# OLD
from livekit.plugins import silero
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

# NEW
from plugins.yourvad import YourVAD
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = YourVAD.load(
        model_path="/path/to/your/model.onnx",
        threshold=0.6,
        chunk_size_ms=20,
    )
```

The rest of the pipeline — AgentSession, turn detector, barge-in logic, AEC warmup — doesn't care that you swapped Silero for your own VAD. They just consume `VADEvent`s through the same channel.

### Required event payloads (downstream consumers depend on these)

| Event | When to emit | Required fields |
|---|---|---|
| `START_OF_SPEECH` | Your threshold crossed (your smoothing) | `samples_index`, `timestamp`, `frames` (chunks that triggered) |
| `INFERENCE_DONE` | Per-frame after running your model (optional) | `probability`, `speaking`, `inference_duration` |
| `END_OF_SPEECH` | Your silence-duration condition met | `samples_index`, `timestamp`, `speech_duration`, `frames` (full segment) |

If your VAD model is a remote API, batch frames and send them in chunks — the framework only sees the events you emit, not how you compute them.

### When it makes sense (vs sticking with Silero)

Reasons to write your own VAD plugin:
- Your model is genuinely better on your domain audio (XREAL glasses mic profile, noisy outdoor, Indian English accents)
- You need diarization-aware VAD (separates speakers)
- You have a remote API VAD (Picovoice Cobra, custom AWS endpoint)
- You want to tightly couple VAD with your STT (combined endpointing model trained on your data)

Otherwise Silero is a strong default — it's what most LiveKit users keep.

### Two distribution paths

1. **Local-only plugin in `my-agent/src/plugins/`** — what's described above. Simplest for one project, no packaging.
2. **Publish as `livekit-plugins-yourvad`** — only needed if you want to share across projects or contribute upstream. Same code, just packaged with `pyproject.toml`.

For Sophia's case, path 1 is what we want.

---

## Q37 (2026-05-15): For VAD we just load Silero and tweak its args. Is the LiveKit framework actually doing anything for VAD? And for turn handling — turn detection is just a model (MultilingualModel), but the rest (endpointing, interruption, preemptive generation) is framework code I wouldn't get if I used the turn-detection model standalone. Right?

Mostly right. The framework's value is HIGHER for turn handling than for VAD, but it is NOT zero for VAD either.

### For VAD

Silero is just a frame-level binary classifier. Input: a 30 ms audio chunk. Output: a probability that this frame contains speech. That is all it does. To use it in a real voice agent, you need plumbing around it that the framework provides:

1. **Audio frame routing** — Get raw audio frames out of WebRTC (mic at 48 kHz on the wire), resample to 16 kHz (Silero's required input), chunk into 30 ms frames (Silero's frame size). The framework's audio I/O layer (`livekit-rtc` + `voice/io.py`) handles this.

2. **Probability-to-event conversion** — Silero gives raw per-frame probabilities. The framework runs the hysteresis (`activation_threshold` / `deactivation_threshold`) and the duration filters (`min_speech_duration` / `min_silence_duration`) to convert that into a clean stream of `START_OF_SPEECH` / `END_OF_SPEECH` events that downstream consumers can act on. Without this, you have raw probabilities flickering frame-by-frame, useless for triggering anything.

3. **Event channel routing to consumers** — Once you have clean VAD events, the framework routes them to:
   - Turn detector — uses `END_OF_SPEECH` to trigger a P(end) prediction
   - Barge-in handler — uses `START_OF_SPEECH` during agent speech to decide whether to interrupt TTS
   - AEC warmup logic — suppresses VAD-triggered interruptions during the first `aec_warmup_duration` seconds of agent speech
   - Endpointing countdown — starts the `min_delay`/`max_delay` timer on `END_OF_SPEECH`
   - User state tracker — sets `user_state` to `"speaking"` vs `"listening"`
   - `@session.on("user_started_speaking")` / `("user_stopped_speaking")` event listeners that you can subscribe to from your own code

4. **Lifecycle management** — Loading Silero in the worker subprocess via prewarm (one model instance per worker, shared across the session); cleanup on session end; integration with the JobProcess lifecycle.

If you ran Silero standalone in a script, you would get a stream of probabilities and nothing else would care about them. The framework saves you roughly 100–200 lines of plumbing per VAD integration.

### For turn handling

Your reading is exact. `MultilingualModel` is just the "is the user done with their thought" prediction model. It takes recent transcript history (up to `MAX_HISTORY_TURNS=6`) and returns a probability of end-of-turn. That is all the model does. The framework owns everything else:

| Capability | Where it lives | What you'd build without LiveKit |
|---|---|---|
| Endpointing timing | `voice/turn.py` (EndpointingOptions + countdown) | min_delay floor + max_delay ceiling timer per turn, integrated with VAD events |
| Interruption / barge-in detection | `voice/agent_activity.py` + interruption resolver in `voice/turn.py` | Compare VAD events to agent speaking state, fire interrupt cancellation on TTS task |
| Interruption mode adaptive vs vad | `inference.AdaptiveInterruptionDetector` | ML classifier or VAD-only threshold logic |
| min_duration / min_words filters | turn.py | Suppress micro-coughs (<500 ms) or word-count gates from triggering interrupts |
| backchannel_boundary suppression | turn.py | Per-turn time windows at start (1.0 s) and end (3.5 s) where interrupts are suppressed — handles "mm-hmm" backchannels |
| Preemptive generation | `voice/generation.py` + `_resolve_preemptive_generation` | Run LLM speculatively before turn is confirmed; cancel on user-still-talking; dedupe on confirmation |
| preemptive_tts (also TTS speculative) | generation.py | Same idea but cancel TTS audio mid-stream when speculation was wrong |
| max_speech_duration / max_retries gates | turn.py | Skip preemption for long utterances; cap retries per turn |
| False-interruption recovery | SpeechHandle scheduler | Detect that brief barge-in turned out to be silence; resume TTS from where it stopped |
| false_interruption_timeout | turn.py | Silence countdown to reclassify a brief interrupt as false |
| User state machine | `voice/agent_session.py` | Track listening/speaking/away states; emit `user_state_changed` events |
| Agent state machine | `voice/agent_activity.py` | Track listening/thinking/speaking/interrupted; emit `agent_state_changed` events |

If you took just the turn detection model into your own project, you would get P(end) values and have to build every row in that table yourself. Conservative estimate: 4–8 person-weeks of careful engineering, with a long tail of edge cases (false interrupts, race conditions between TTS cancellation and user resumption, preemptive generation that cancels gracefully when the user keeps talking, etc.).

### Sharper framing

For both VAD and turn detection, the model is small relative to the orchestration around it. The model is the easy part. What separates a usable voice agent from a frustrating one is the integration — how cleanly the events from VAD trigger turn detection, how cleanly turn detection drives endpointing, how cleanly endpointing decides when to call the LLM, how cleanly interruptions cancel TTS without race conditions, how cleanly false interruptions recover. None of that lives in the model. All of it lives in the framework.

This is a concrete instance of the broader Q24 / Q33 insight: "environment matters as much as raw model quality." For VAD, environment is ~70% of the value (Silero is great, but Silero alone gets you 30% of the way). For turn handling, environment is ~85% of the value (MultilingualModel is great, but the model alone is the smaller half of the work).

---

## Q38 (2026-05-15): To restate Q37 -- the smooth real-time flow I see in the LiveKit Playground (clean turn-taking, no cut-offs, smooth interruptions, no echo loops, preemptive responses) all comes from the framework. If I just took Silero and MultilingualModel into a standalone project, I would not get any of that. Right?

Yes, exactly right. If you took Silero and MultilingualModel into a standalone project, you would have two ONNX inference calls returning probabilities and nothing more. You would not have a conversation. The smooth real-time flow you see in the Playground is the framework's orchestration code wrapping those model outputs. The models alone give you the building blocks; the framework gives you the agent.

### Concrete behaviours you see in Playground -- and where each one comes from

| Behaviour you observe | Comes from |
|---|---|
| Agent starts speaking ~300 ms after you finish your sentence | Framework: `preemptive_generation` (LLM runs speculatively before turn confirmed) |
| Agent doesn't get interrupted when you say "uh-huh" while it talks | Framework: `interruption.backchannel_boundary=(1.0, 3.5)` suppression at agent turn start/end |
| Agent stops mid-sentence when you actually do interrupt with a real question | Framework: interruption detection (`interruption.min_duration=0.5`) + TTS cancellation in SpeechHandle scheduler |
| Agent resumes its sentence when your "interrupt" turned out to be a cough | Framework: `interruption.resume_false_interruption=True` + `false_interruption_timeout=2.0` |
| Agent doesn't transcribe its own voice and loop forever | WebRTC: client-side AEC. Plus framework: `aec_warmup_duration=3.0 s` ignores user audio for first 3 s of agent speech while AEC converges |
| Agent waits when you pause mid-thought instead of cutting you off | Model + framework: MultilingualModel returns low P(end) when transcript looks incomplete, framework's `endpointing.{min_delay, max_delay}` countdown holds turn-end accordingly |
| Agent transcribes correctly even when you mumble or whisper | Mostly model: STT (Deepgram nova-3) does this. Framework just routes audio at the right sample rate. |
| Agent's voice sounds natural and prosodic | Mostly model: TTS (Cartesia sonic-3) does this. Framework just streams the synthesized frames. |

The pattern: anything about TIMING, INTERRUPTION, RECOVERY, COORDINATION between stages is framework. Anything about ACOUSTIC QUALITY, TRANSCRIPT ACCURACY, GENERATION QUALITY is the model. The framework wraps the models with a state machine that turns "ML inference results" into "a conversation that feels human."

### Where this code actually lives

- `voice/agent_activity.py` -- per-turn state machine (listening / thinking / speaking / interrupted)
- `voice/turn.py` -- TurnHandlingOptions, EndpointingOptions, InterruptionOptions, PreemptiveGenerationOptions resolvers
- `voice/generation.py` -- generate_reply() loop, speculative LLM scheduling, ChatChunk stream consumption
- `voice/speech_handle.py` -- per-utterance scheduler with interruption + AEC warmup enforcement
- `voice/audio_recognition.py` -- pumps STT events to turn detector, fires endpointing countdown
- `voice/agent_session.py` -- session-level state, AEC warmup timer, user_state / agent_state machines

### Why this matters for Sophia's strategy

This is exactly why we decided in Q24 to stay on LiveKit through both benchmarking AND production. The framework gives us the conversation. The models give us the components. We can swap models freely (Sophia's whole Phase 2 plan rests on this), but we cannot easily replace the orchestration without rebuilding 4-8 person-weeks of careful state-machine and timing logic, plus the audio I/O plumbing on top of that. Sticking with the framework lets us spend our engineering time on model quality and RAG quality, not on rebuilding what already works.

## Q39 (2026-05-19): When wiring an OpenAI-compatible TTS server (like Sophia's Kokoro) into LiveKit, why does `openai.TTS(model="kokoro-82m")` fail with "no audio frames were pushed" but `openai.TTS(model="tts-1")` works?

Real bug we hit while wiring sophia-agent. The fix is to lie to the plugin about the model name (use `"tts-1"`) so it picks the correct decoder path. The server doesn't care what string we pass.

**Symptom:** Plugin call goes through (HTTP 200 from Kokoro, valid WAV bytes returned), but framework logs:
```
WARNING failed to synthesize speech: no audio frames were pushed for text: ..., retrying in 0.1s
ERROR livekit.agents._exceptions.APIError: no audio frames were pushed for text: ...
```

**Root cause (from reading the plugin source at `livekit/plugins/openai/tts.py`):**
```python
AUDIO_STREAM_MODELS = {"tts-1", "tts-1-hd"}

def synthesize(self, text, *, conn_options=...):
    if self._opts.model in AUDIO_STREAM_MODELS:
        return AudioChunkedStream(...)   # iter_bytes() — raw audio
    return SSEChunkedStream(...)         # iter_lines() — parses "data: ..." SSE prefixes
```

The plugin routes by MODEL NAME, not by `response_format`. Two completely different decoder paths:

| Model name | Stream class | Expects |
|---|---|---|
| `tts-1`, `tts-1-hd` | `AudioChunkedStream` | Raw audio bytes (mp3/wav/pcm/etc per response_format) -- consumed via `iter_bytes()` |
| Anything else (incl. `gpt-4o-mini-tts`, `kokoro-82m`, ...) | `SSEChunkedStream` | OpenAI's newer SSE-wrapped audio format -- consumes `iter_lines()` looking for `data: ` prefixes carrying base64-encoded audio deltas |

OpenAI's `gpt-4o-mini-tts` (their newer token-billed TTS) returns `text/event-stream` with `speech.audio.delta` JSON events. The plugin's SSEChunkedStream path is built for that format specifically.

When we passed `model="kokoro-82m"`, the plugin took the SSE path, iterated Kokoro's response line by line looking for `data: ` prefixes. Kokoro returns binary WAV bytes with no SSE structure -> zero events parsed -> `output_emitter.push()` never called -> framework's TTFB watchdog raises "no audio frames were pushed" after 3 retries.

**Fix:** Use `model="tts-1"` to force AudioChunkedStream. Then also pass `response_format="wav"` so the mime_type passed to the decoder (`audio/wav`) matches what Kokoro returns. Kokoro server does NOT validate the model field (source-confirmed -- its SpeechRequest schema has model as Optional, server ignores it for generation), so this is purely a routing hint to the LiveKit plugin.

**Sophia's working config in sophia-agent/src/agent.py:**
```python
tts=openai.TTS(
    base_url="http://localhost:8122/v1",
    model="tts-1",          # NOT "kokoro-82m" -- forces AudioChunkedStream
    voice="aiden",          # one of kokoro's 9 wire-level voices
    api_key="not-needed",
    response_format="wav",  # Kokoro hardcodes audio/wav on /v1/audio/speech
),
```

**Generalisation:** This affects ANY OpenAI-compatible TTS server that returns raw audio (most do, since gpt-4o-mini-tts's SSE format is OpenAI-specific and recent). Always pass `model="tts-1"` (or `"tts-1-hd"`) for non-OpenAI servers like Kokoro, Orpheus, qwen3-tts, faster-whisper-tts wrappers, etc. The OpenAI-side `model` validation does not happen because the request goes to your server, not openai.com. The `model` field is just a routing hint to the LiveKit plugin.

**Generalisation extension:** The openai LLM plugin does NOT have an analogous model-name whitelist that affects decoding -- streaming chat completions are universally SSE format `data: {...}\n\n`, so any model name works for `openai.LLM(...)`. Same for `openai.STT(...)` (the /v1/audio/transcriptions endpoint is multipart in / JSON out, no streaming variant). The plugin-side model-name routing trap is unique to the TTS plugin.

**Side observation -- two other Kokoro gotchas flagged but NOT bugs in practice:**
- `response_format` field: server schema accepts it but server-code ignores it and always returns WAV. So we MUST pass `"wav"` plugin-side to match.
- WAV-header glitch on non-streaming endpoint: theoretical click at start of first phrase. Not observed in practice.
- Real-streaming endpoint `/v1/audio/speech/stream` (raw int16 PCM at 24kHz, 80ms first chunk): not used by the openai plugin, only by a custom Route B plugin per Q36 pattern. Parked optimisation for ~500ms TTFB improvement.

## Q40 (2026-05-19): When wiring a `@function_tool` against an OpenAI-compatible LLM server, the LLM is hallucinating answers instead of calling the tool. Is this a LiveKit bug?

No. The LiveKit framework wiring is correct -- the `openai.LLM` plugin DOES include `tools=[...]` in the POST body to `/v1/chat/completions` when the Agent has `@function_tool` methods. Confirmed via plugin source: `livekit/plugins/openai/llm.py` populates the `tools` argument from `find_function_tools(agent)` and passes it through to `openai.AsyncClient.chat.completions.create(..., tools=...)`.

**Where the tool-call actually dies: the server-side wrapper.** For Sophia's case the server is a custom FastAPI app (`inference-server.py` serving Qwen3-VL-8B-Instruct via Transformers). Its `ChatCompletionRequest` Pydantic schema (line 203) defines only:
```python
class ChatCompletionRequest(BaseModel):
    model: str = MODEL_NAME
    messages: list[ChatMessage]
    temperature: float = ...
    top_p: float = ...
    max_tokens: int = ...
    stream: bool = False
    stop: Optional[list[str]] = None
```
No `tools`, no `tool_choice`. Pydantic v2 default is `extra='ignore'` -- it silently drops unknown fields. So the request body that hits Python's handler has `tools` already gone, and `generate_completion` calls `processor.apply_chat_template(messages, ...)` with no `tools=` kwarg. The Qwen chat template renders with no tool definitions in the prompt, the model has no idea function-calling exists, and proceeds to hallucinate plausible-sounding tool-results in plain text.

**How to diagnose this when it happens:**
- Symptom 1: agent gives confident detailed answers about your knowledge base without any worker-log line saying `function_call_started`.
- Symptom 2: if you ask the agent directly "are you calling the X function?", it correctly answers "no" -- it genuinely is not, the plugin sent the tool but the server stripped it.
- Symptom 3: agent hallucinates SPECIFICS that should not be possible without retrieval (Sophia's case: invented "Siemens 3VA1, ABB ACS150, Cutler-Hammer H-100" when actual KB only had GV70 + x250).

**How to verify the server-side strip:** read the server's request schema. If `tools` / `tool_choice` are not declared as Pydantic fields, they're being silently dropped. Alternative test: POST `/v1/chat/completions` directly with `tools=[...]` and see if the response includes any tool-call output or if it's pure text content.

**Fix paths:**
1. **Best (server-side):** add `tools: Optional[list[dict]] = None` and `tool_choice: Optional[Union[str, dict]] = None` to the request schema, pass `tools=` into `apply_chat_template(...)`, parse Qwen's `<tool_call>{json}</tool_call>` output tokens from the decoded text, return as OpenAI-style `tool_calls` in the response. Then LiveKit's `@function_tool` works unchanged.
2. **Workaround (client-side):** drop `@function_tool` and use the `Agent.on_user_turn_completed(turn_ctx, new_message)` hook to do retrieval/routing yourself. Inject results as a `system` message at the end of `turn_ctx` before the LLM call. Loses the LLM-decides-when-to-call benefit but works against ANY OpenAI-compatible server regardless of its tool support.
3. **vLLM-based servers:** vLLM's OpenAI-compatible server has built-in `--enable-auto-tool-choice` (and `--guided-decoding-backend`) flags. If the model is served by vLLM with that flag, tool-calling works without server-side schema changes.

**Generalisation:** this trap is invisible from the LiveKit side -- the plugin reports no error, sends the tools as documented, gets a normal-looking response back, and the LLM speaks as expected (just without ever using the tool). The only way to detect it is from the BEHAVIOUR (hallucination + no function_call_started logs) or by reading the server source. Worth checking explicitly when bringing up any custom OpenAI-compatible LLM server.

**Side note on the `openai.LLM` plugin:** unlike the `openai.TTS` plugin which routes by model name (see Q39), the LLM plugin has no model-name routing trap. Any model id works. The only failure mode here is server-side schema stripping.

---

## Q41 (2026-05-21): Why does the webapp not need mic gating to prevent echo, but the Unity client does?

Because browsers do Acoustic Echo Cancellation (AEC) for free as part of `getUserMedia`; Unity does not.

### Webapp path (Chrome / Safari / Firefox + livekit-client JS)

`navigator.mediaDevices.getUserMedia({ audio: true })` returns a mic stream where the browser has already applied WebRTC's audio pipeline. By default these three constraints are ON:

- `echoCancellation: true` — subtracts what speakers are playing from the mic input
- `noiseSuppression: true`
- `autoGainControl: true`

The browser knows what samples it just sent to the speakers (it owns the output mixer), so it can subtract that "reference signal" from the mic input in real time. Sophia's TTS coming out of the speakers gets cancelled before it ever reaches the mic stream the LiveKit JS SDK sees. The STT plugin therefore never gets the echo, and there's no feedback loop.

This is why our agent-starter-react frontend has never needed mic gating, even with the laptop's built-in speakers and mic. The same conversation that loops in Unity is clean in the browser.

### Unity path (this app, `sophia-glasses/unity/`)

`UnityEngine.Microphone.Start(...)` returns raw PCM. Unity has never shipped AEC, NS, or AGC for its `Microphone` API.

LiveKit's Unity `MicrophoneSource` then pipes that raw mic through an AudioSource → `OnAudioFilterRead` → FFI → WebRTC native encoder. The native WebRTC library DOES include an Audio Processing Module (APM) with AEC — but the Unity SDK does not wire the playback reference signal into APM. APM has no "what to subtract" data, so it can't cancel.

Result on a laptop with co-located speakers and mic: Sophia's TTS plays out of the speakers → mic captures it raw → STT transcribes "Voices", "I'm here to help with", "I'm here to help with industrial" → LLM treats each as a new user question → Sophia answers → feedback loop. Observed user_transcript entries from a real session at our project's Editor Play test:

```
user_transcript: "Hello, who are you?"   ← actual user speech, OK
user_transcript: "Voices"                ← Sophia's TTS picked up
user_transcript: "How can you help me? I'm so..."  ← Sophia
user_transcript: "I'm here to help with."          ← Sophia
user_transcript: "I'm here to help with in-"       ← Sophia (looping)
```

The "breaking" voice is the agent's TTS being cut by interruption detection every time the mic detects "user speaking" — which is really just Sophia echoing back.

### On Android / Beam Pro (relevant for our Phase 1 ship)

Android exposes a system-level `android.media.audiofx.AcousticEchoCanceler` API. It's tied to the audio source the recorder uses. `AudioRecord` with source `MediaRecorder.AudioSource.VOICE_COMMUNICATION` engages AEC automatically on most Android builds. The official `livekit-android` SDK uses VOICE_COMMUNICATION + AcousticEchoCanceler.

BUT — Unity's `UnityEngine.Microphone` API on Android uses `VOICE_RECOGNITION` by default, which on most builds does NOT engage AEC. So our out-of-the-box Unity APK on Beam Pro will NOT have system AEC.

### Mitigations (in cost order)

1. **Headphones.** Eliminates the acoustic loop physically. Zero code. (Caveat: pick output device that natively supports 48 kHz, or Unity falls back to 44100 — see Q42.)
2. **Mic gating in code.** Subscribe to `sophia.agent_events` text-stream, watch for `agent_state: speaking`, call `_micTrack.SetMuted(true)`; flip back on `listening`. The cheap portable substitute for AEC that voice assistants ship anyway. ~20 lines.
3. **Custom Android plugin** — replace `UnityEngine.Microphone` with a tiny JNI wrapper that uses `AudioRecord` + VOICE_COMMUNICATION + `AcousticEchoCanceler.create(...)`. Then keep mic gating off. Highest effort, best quality.
4. **Patch the LiveKit Unity SDK** — feed playback samples into the FFI's APM as the reference signal. The proper fix at the SDK layer. Out of scope for our project today.

For Sophia Phase 1: ship plain (no gating) and test on glasses. XREAL One Pro speakers fire into the temples right at your ears, Beam Pro mic is on your hand/pocket — geometry alone should attenuate the loop heavily compared to laptop. If audible, add gating (Option 2). Only escalate to Option 3 if Option 2 isn't enough.

---

## Q42 (2026-05-21): When using the LiveKit Unity SDK on macOS Editor, why do I get `InvalidState - sample_rate and num_channels don't match` even after setting `AudioManager.asset: m_SampleRate: 48000`?

Because `m_SampleRate` is a REQUEST and the active macOS output device wins. Unity's runtime audio rate follows the output device, not the project setting.

### What's actually happening

LiveKit's `RtcAudioSource` is constructed expecting 48000 Hz (the WebRTC / Opus standard rate). On its constructor log line you see:

```
NewAudioSource: 2 48000
```

— meaning channels=2, rate=48000.

LiveKit's `MicrophoneSource` captures the mic via `UnityEngine.Microphone` but plays it back through an `AudioSource` so Unity's audio thread can deliver samples via `OnAudioFilterRead`. That callback is the path into LiveKit's FFI.

**The trap:** `OnAudioFilterRead` delivers samples at the OUTPUT MIXER rate (Unity's `AudioSettings.outputSampleRate`), not the mic rate. On macOS this rate is decided at runtime by the active OUTPUT device (the thing playing audio out of your laptop), not by `ProjectSettings/AudioManager.asset`.

`m_SampleRate: 48000` is a request. If the output device can't honor it, Unity silently falls back to the device rate. EarPods Headphones are locked to 44100 Hz at the CoreAudio layer. MacBook Pro Speakers run at 48000 Hz natively.

### The symptom and trace

When you run with EarPods plugged in:

```
NewAudioSource: 2 48000     ← RtcAudioSource expects 48000
LiveKit: RtcAudioSource#1 audio frame #1 metadata mismatch
  actualRate=44100 actualChannels=2
  expectedRate=48000 expectedChannels=2
  sourceType=AudioSourceMicrophone
LiveKit: RtcAudioSource#1 capture callback failed asyncId=3 frame=1
  error=an RtcError occurred: InvalidState - sample_rate and num_channels don't match
```

The mic itself is fine — it's the OnAudioFilterRead invocation rate that doesn't match RtcAudioSource's expectation.

### Fixes (in order of effort)

1. **Use an output device that natively runs at 48 kHz.** MacBook Pro Speakers, USB headset rated for 48k, AirPods (negotiate 48000). Unplug EarPods, Unity restarts the audio system on Play, picks up 48000 from the new output device, errors disappear.
2. **Force the device to 48 kHz via Audio MIDI Setup.** Open `/System/Applications/Utilities/Audio MIDI Setup.app`, select the output device, change Format to `2 ch 16-bit Integer 48,000 Hz`. Restart Unity to be safe.
3. **Set `AudioManager.asset: m_SampleRate: 48000`** — necessary but not sufficient. Unity will request 48000, but only fulfills it if the device supports it. Keep this set anyway as the floor.
4. **Resample inside MicrophoneSource** — long-term SDK fix. Out of scope for our project.

### On Android / Beam Pro

Not affected the same way. Android audio for VOICE_COMMUNICATION-class apps is always 48000 Hz on modern devices. The mismatch only bites on macOS Editor when the user happens to have a 44100-only output device active. APK builds on Beam Pro should not hit this.

### File touched in our project

`sophia-glasses/unity/ProjectSettings/AudioManager.asset` — `m_SampleRate: 48000` (was 0 = follow OS default). Force-edited via sed because Unity must not be running when you edit ProjectSettings files (it'll overwrite on next save).

---

## Q43 (2026-05-21): Will the acoustic echo loop seen on the laptop with built-in speakers reproduce on XREAL One Pro + Beam Pro?

Probably MUCH weaker, but not zero. Test before deciding to ship mic gating.

### Three reasons it should be weaker on glasses than on a laptop

1. **Geometry.** XREAL One Pro speakers fire into the temples right above your ears — near-field, near-ear, designed for personal listening with low sound leakage. The Beam Pro mic is on the device in your hand or pocket, typically >1 meter away. Acoustic loop gain drops sharply with distance. Compare to a laptop where built-in speakers and mic are both in the same chassis, ~20 cm apart.
2. **Directionality.** XREAL One Pro speakers are designed to NOT leak audibly to people next to you. The acoustic signal reaching the Beam Pro mic is much quieter than the actual speech reaching your ears.
3. **Android system AEC (caveated).** Android's `android.media.audiofx.AcousticEchoCanceler` engages automatically when `AudioRecord` uses `MediaRecorder.AudioSource.VOICE_COMMUNICATION`. The native `livekit-android` SDK does this. **BUT** `UnityEngine.Microphone` on Android uses `VOICE_RECOGNITION` by default, which does NOT engage AEC on most builds. So our Unity APK does not get free AEC.

So we get factors 1 + 2 for free (physics), but lose factor 3 by going through Unity's mic API.

### Decision tree

1. **Build APK, install on Beam Pro, wear glasses, talk.** No mic gating, no Android plugin.
2. **If echo loop not audible:** done, ship as-is. Geometry alone was enough.
3. **If echo loop audible but mild:** implement mic gating (cheap fix, ~20 lines in SophiaConnection.cs). Subscribe to `sophia.agent_events` text-stream, watch `agent_state` transitions, call `_micTrack.SetMuted(true)` when "speaking", flip back on "listening".
4. **If echo loop bad:** write a tiny Android JNI plugin that exposes a `VoiceCommAudioRecord` class to C#. It uses `AudioRecord` with `MediaRecorder.AudioSource.VOICE_COMMUNICATION`, then `AcousticEchoCanceler.create(audioSession)` + `NoiseSuppressor.create(audioSession)` + `AutomaticGainControl.create(audioSession)`. SophiaConnection.cs uses this in place of `UnityEngine.Microphone`. Then turn mic gating off. Highest effort, best quality.

### Why this is non-deterministic

The user's specific Beam Pro hardware (mic placement, OS build's default audio processing, speaker volume, room acoustics) all affect loop gain. The only honest answer is empirical: install and try.

### What the agent reports already help

Our backend publishes `agent_state` events via `sophia.agent_events`. Frontends including the Unity client can subscribe and gate the mic with no backend change. This is the cheapest path-to-ship and works on any client (browser, Unity, native Android) regardless of platform AEC quality.

---

## Q44 (2026-05-21): What are the install-time gotchas for the LiveKit Unity SDK on a fresh project, beyond what the SDK README mentions?

Three categories. The first two are install-time blockers; the third is API drift between docs and current SDK source.

### Trap 1: Git LFS not configured before clone (FFI binaries are LFS pointer files)

The SDK's FFI binaries (the Rust LiveKit client compiled to per-platform `.dylib` / `.so` / `.dll`, ~17 MB each) live in Git LFS. The Google.Protobuf.dll bundled inside the SDK is ALSO behind LFS.

**Without `git-lfs` installed**, when you clone the SDK (or Unity's Package Manager pulls from a git URL), you get 133-byte text files containing:

```
version https://git-lfs.github.com/spec/v1
oid sha256:...
size 17473584
```

instead of the real binary. Unity tries to load these as Mach-O / ELF / PE and crashes with:

```
liblivekit_ffi.dylib: slice is not valid mach-o file
```

The Unity Package Manager's git-URL import path does NOT run git-lfs even if it's installed on your system. So even after `brew install git-lfs && git lfs install`, a fresh Package Manager git-URL install still pulls pointer files.

**Fix:**

```bash
brew install git-lfs
git lfs install   # one-time per machine
git clone https://github.com/livekit/client-sdk-unity.git sophia-glasses/client-sdk-unity
# ~1 GB clone, ~50 MB of binaries unpacked
# verify: file sophia-glasses/client-sdk-unity/Runtime/Plugins/.../liblivekit_ffi.dylib
#         should report Mach-O 64-bit dynamically linked shared library arm64
```

Then in Unity: Window > Package Manager > "+" > **Install package from disk** > pick the local clone's `package.json`. NOT the git URL.

### Trap 2: Google.Protobuf C# runtime not bundled

The SDK's auto-generated proto code references `Google.Protobuf` types but the SDK doesn't ship the protobuf runtime DLL. Standard fix is NuGetForUnity → install Google.Protobuf.

**Chicken-and-egg:** the missing protobuf causes ~3000 compile errors, which puts Unity into Safe Mode, which HIDES custom menus including NuGet's. You can't install Google.Protobuf via NuGet because the NuGet menu doesn't exist while errors are present.

**Manual workaround (the only thing that works in Safe Mode):**

```bash
mkdir -p /tmp/protobuf && cd /tmp/protobuf
curl -L https://www.nuget.org/api/v2/package/Google.Protobuf/3.27.4 -o protobuf.nupkg
unzip -p protobuf.nupkg lib/netstandard2.0/Google.Protobuf.dll > Google.Protobuf.dll
cp Google.Protobuf.dll '/path/to/unity/Assets/Plugins/Google.Protobuf.dll'
```

Unity auto-detects (or `Cmd-R` to force refresh), recompiles, exits Safe Mode. NuGetForUnity menu reappears.

After the local-disk SDK swap (Trap 1 fix), the SDK comes with its own bundled Google.Protobuf.dll. You'll then have TWO copies — Unity may warn about a duplicate assembly. Delete `Assets/Plugins/Google.Protobuf.dll`, keep the one inside the SDK package.

### Trap 3: SDK README quickstart is out of date vs current SDK source

The README example uses APIs that no longer exist or are ambiguous in SDK 1.3.7. Six concrete quirks discovered as of 2026-05-21:

| README says | Actually | Fix |
|---|---|---|
| `_room.Connect(serverUrl, token)` | Requires 3 args | `_room.Connect(serverUrl, token, new LiveKit.RoomOptions())` |
| `using LiveKit; new RoomOptions()` | `RoomOptions` is ambiguous between `LiveKit.RoomOptions` and `LiveKit.Proto.RoomOptions` | Use FQN: `new LiveKit.RoomOptions()` |
| `connectOp.Error` (string) | Only `IsError` (bool); error details only in SDK log | `if (connectOp.IsError) Debug.LogError("see SDK log above");` |
| `pubOp.Error` (string) | Same as above for PublishTrackInstruction | `if (pubOp.IsError) Debug.LogError("see SDK log above");` |
| `reader.ReadAll().ReadAllText` | Property is `.Text` | `readAll.Text` |
| `_micTrack.Stop()` | LocalAudioTrack has no `Stop()` method | Skip it. GC handles cleanup after `_micSource.Stop()` + `_room.Disconnect()` |
| `new TrackPublishOptions { Source = TrackSource.SourceMicrophone }` with `using LiveKit;` | Both types live in `LiveKit.Proto`, not `LiveKit` | Add `using LiveKit.Proto;` at top of file |

**Recovery procedure when you hit these:** read the installed SDK source under
`<unity-project>/Library/PackageCache/io.livekit.livekit-sdk@<hash>/Runtime/Scripts/`
or `<unity-project>/Packages/io.livekit.livekit-sdk/Runtime/Scripts/` if installed from disk. The actual API is always there even when docs lag. Specifically check `Runtime/Scripts/Room.cs`, `Runtime/Scripts/Internal/FFIClient.cs`, `Runtime/Scripts/AudioStream.cs`, `Runtime/Scripts/MicrophoneSource.cs`.

### Order of operations for a fresh install (no traps)

1. `brew install git-lfs && git lfs install` (host-level prep)
2. `git clone https://github.com/livekit/client-sdk-unity.git <project>/client-sdk-unity`
3. Verify a sample binary with `file Runtime/Plugins/.../liblivekit_ffi.dylib` — must be Mach-O / ELF / PE, not text.
4. Unity Editor > Package Manager > "+" > Install package from disk > select the clone's `package.json`
5. If you hit Google.Protobuf errors immediately, do the manual nupkg-drop above. After Unity exits Safe Mode you can use NuGetForUnity normally.
6. Write your scripts against the installed SDK source, not the README.
7. Allow HTTP in Player Settings (only if your backend uses `ws://` not `wss://`): `Edit > Project Settings > Player > Other Settings > Configuration > Allow downloads over HTTP > Always allowed`. If the UI toggle doesn't stick, force-edit `ProjectSettings/ProjectSettings.asset: insecureHttpOption: 2` directly with Unity closed.
8. Set audio sample rate: `ProjectSettings/AudioManager.asset: m_SampleRate: 48000` (close Unity before editing). See Q42 for the device-rate caveat.

### Files touched in our project for these fixes

- `sophia-glasses/client-sdk-unity/` — fresh git clone with LFS
- `sophia-glasses/unity/Assets/Plugins/Google.Protobuf.dll` — manual NuGet drop (kept; SDK's bundled copy not yet causing conflicts)
- `sophia-glasses/unity/ProjectSettings/ProjectSettings.asset` — `insecureHttpOption: 2`, `microphoneUsageDescription` set
- `sophia-glasses/unity/ProjectSettings/AudioManager.asset` — `m_SampleRate: 48000`

---

## Q45 (2026-05-21): What gotchas appear when first building + installing the LiveKit Unity + XREAL SDK Android APK on the Beam Pro?

Five gotchas hit in succession during the first end-to-end attempt. None blocking once known.

### Gotcha 1: `minSdkVersion` mismatch from XREAL auto-log library

Symptom (Gradle error):
```
uses-sdk:minSdkVersion 25 cannot be smaller than version 29 declared in library
  [:xreal-auto-log-1.2:] ... AndroidManifest.xml
  as the library might be using APIs not available in 25
```

Cause: XREAL SDK 3.1.0 bundles `xreal-auto-log-1.2.aar` which targets `minSdkVersion 29` (Android 10). Unity defaults projects to API 25.

Fix: `Edit > Project Settings > Player > Android > Other Settings > Minimum API Level → Android 10.0 'Q' (API level 29)`.

Pick exactly 29 not higher — wider device-compat window. Beam Pro runs Android 14 (API 34) per runtime log `Device Model 'XREAL X4000', OS 'Android OS 14 (API 34)'`.

### Gotcha 2: Default URP template bundle identifier is committed

The blank URP template ships with:
```
ProjectSettings.asset: applicationIdentifier: (empty)  but baked at build time to
  com.UnityTechnologies.com.unity.template.urpblank
```

The first APK installs under that auto-generated package name, not anything Sophia-branded. `adb shell pm list packages` shows it, and the path-to-launch and any future signing tools key off it.

Cleanup (Phase 2): Edit > Project Settings > Player > Other Settings > Identification > Override Default Package Name → `com.sophia.glasses` (or similar). Re-install will need an `adb uninstall com.UnityTechnologies.com.unity.template.urpblank` first because the old install will collide.

### Gotcha 3: Unity 6 default Android activity is `UnityPlayerGameActivity`, not `UnityPlayerActivity`

`adb shell am start -n <pkg>/com.unity3d.player.UnityPlayerActivity` returns:
```
Error type 3
Error: Activity class {<pkg>/com.unity3d.player.UnityPlayerActivity} does not exist.
```

Unity 6 uses Android `GameActivity` (Google's modern native-activity replacement) by default. The launchable main activity is `com.unity3d.player.UnityPlayerGameActivity`.

Discover the right one programmatically:
```bash
adb shell cmd package resolve-activity --brief <pkg> | tail -1
```

### Gotcha 4: `EditorBuildSettings.asset` defaults to only `SampleScene.unity`

After creating a Unity project from the URP template, the only scene in the build list is `Assets/Scenes/SampleScene.unity` — the empty default template scene. If you make a new scene (e.g. `Assets/sophia-scene.unity` with your `SophiaConnection` GameObject) but never add it to the Build Settings, the APK builds with only the empty template. Your GameObject never instantiates → no logs from your scripts → app appears to do nothing.

Diagnosis: `grep enabled <project>/ProjectSettings/EditorBuildSettings.asset` shows the active list.

Fix in Unity: `File > Build Profiles > Scenes In Build` → add your scene, drag to position 0 (= startup), untick or remove `SampleScene`.

Alternative: edit `ProjectSettings/EditorBuildSettings.asset` directly (Unity closed):
```yaml
m_Scenes:
  - enabled: 1
    path: Assets/sophia-scene.unity
    guid: <copy from the .meta sidecar>
```

### Gotcha 5: XREAL SDK ClassNotFoundExceptions at startup (harmless)

When the XREAL SDK initializes on a Beam Pro that doesn't have the full XREAL system service installed, you'll see:
```
AndroidJavaException: java.lang.ClassNotFoundException:
  ai.nreal.activitylife.FloatingManager
  at Unity.XR.XREAL.XREALMultiResumeMediator.OnLoad()
```
Plus optional warnings:
```
The referenced script on this Behaviour (Game Object 'XREALVirtualController') is missing!
Plugin libXREALXRPlugin.so is not 16KB-aligned. May cause issues on ARM64 devices running Android 15+.
```

All non-blocking. `FloatingManager` is part of XREAL's optional activity-life-cycle handoff (used when an XREAL launcher is installed on the device). `XREALVirtualController` is a Unity sample-scene leftover. The 16KB-alignment warning is an Android 15+ concern; Beam Pro is Android 14.

### Workflow that worked end-to-end

```bash
# After Build → APK at sophia-glasses/unity/sophia-glasses.apk
adb devices                                          # confirm Beam Pro online
adb install -r '<path>/sophia-glasses.apk'           # streamed install
adb shell cmd package resolve-activity --brief <pkg> # find main activity
adb logcat -c                                        # clear log buffer
adb shell am start -n <pkg>/<MainActivity>
sleep 10
adb logcat -d | grep -E 'Sophia|LiveKit|Microphone|FATAL'
```

---

## Q46 (2026-05-21): When deploying a non-web LiveKit client (Unity on Beam Pro), why does `Room.Connect` fail with the server URL the token endpoint returns?

Because `sophia-agent/src/token_mint.py` returns the SFU URL it reads from its own `.env.local` (`LIVEKIT_URL=ws://localhost:7880`), but that URL is the **server's** view of localhost, not the client's. On a Beam Pro reaching the Mac over Tailscale, `localhost:7880` points at the Beam Pro itself (no SFU there).

### Symptom

```
[Sophia] Got token (len=457) for url=ws://localhost:7880    ← override happened
[Sophia] Room.Connect failed                                ← Beam Pro can't reach its own localhost:7880
```

### Root cause

`token_mint.py` builds the JSON response as:
```python
return {
    "token": jwt,
    "url": LIVEKIT_URL,         # ← from os.environ
    "identity": req.identity,
    "room": req.room,
}
```

And our `SophiaConnection.cs` (pre-fix) preferred the response URL over the local config:
```csharp
if (!string.IsNullOrWhiteSpace(resp.url)) serverUrl = resp.url;
```

The web frontend gets away with this because its token-handler is the Next.js app whose own `LIVEKIT_URL` is set to whatever browser-facing URL is correct (`ws://localhost:7880` for local dev because the browser is on the same Mac). For a separate device, that doesn't generalize.

### Fix (chosen: client-side)

Removed the override in `SophiaConnection.cs`. Always use `config.liveKitUrl` from the `SophiaConfig.asset` ScriptableObject, which contains the Tailscale URL `ws://100.69.34.194:7880` reachable from anywhere on the Tailnet:

```csharp
var resp = JsonUtility.FromJson<TokenResponse>(www.downloadHandler.text);
token = resp.token;
// NOTE: do NOT override serverUrl with resp.url. The token_mint
// reports the SFU URL from sophia-agent's own .env.local (typically
// ws://localhost:7880 = the Mac's perspective). External clients
// need their own route to the SFU, which lives in
// SophiaConfig.liveKitUrl.
```

### Alternative fix (server-side, considered but rejected)

Change `sophia-agent/.env.local LIVEKIT_URL` to the Tailscale URL. The agent worker on the same Mac would still reach the SFU via Tailscale loopback. Rejected because:
- Token URL is fundamentally a server-perspective field; encoding "where the client should connect" in server config breaks every time you add another client (different deployment, different network).
- Per-machine config — would have to change for every dev who clones the project.
- The right architectural answer is: each client knows its own connection path. Server can advise via the field, but the client should treat it as advisory only.

### Generalization

Any LiveKit client that's not the web frontend running on the same host as `livekit-server` needs to:
1. Have its own `LIVEKIT_URL` configuration (in our case, `SophiaConfig.liveKitUrl`).
2. **Ignore** the `url` field in the token response unless it's known to be public/canonical.

For production cloud deployment this stops being an issue because `LIVEKIT_URL` would be set to the public wss:// URL on every host. For local-dev / Tailscale setups, the client must own its URL.

---

## Q47 (2026-05-21): On Android, why does `[Sophia] No microphone devices found` appear even though `RECORD_AUDIO` is in the manifest and the permission dialog DID pop up?

Race condition between Unity's `Application.RequestUserAuthorization(UserAuthorization.Microphone)` and Android's actual permission grant.

### Timeline observed

```
46.543  [Android] START GrantPermissionsActivity (mic permission dialog opens)
46.544  [Sophia] No microphone devices found    ← our script bailed
46.659  [Android] dialog displayed to user
50.805  [Android] user clicks button, RECORD_AUDIO granted=true
```

Our script's mic check ran BEFORE the user had a chance to grant. `Microphone.devices` returned empty array, our `yield break` fired, voice loop never started.

### What Unity actually does

`Application.RequestUserAuthorization(UserAuthorization.Microphone)` on Android:
- Triggers the Android system permission dialog as a side effect (if RECORD_AUDIO is in the manifest).
- Returns control to the coroutine after dispatching the request, NOT after the user has answered.
- `Application.HasUserAuthorization(Microphone)` then returns true based on Unity's internal flag, which doesn't reflect the actual Android `PackageManager.checkPermission` state until the dialog closes.

Documented Unity 6 behaviour. On iOS the same API blocks correctly; on Android it doesn't.

### Workaround used today (manual restart)

1. First launch → script bails, permission dialog appears.
2. User taps "While using the app" → Android grants `RECORD_AUDIO`.
3. `adb shell am force-stop <pkg>` + `am start ...` → relaunch.
4. Second launch: `Microphone.devices` populates immediately, voice loop runs.

Once the permission is granted system-wide, all future launches work without prompts.

### Proper fix (TODO in Phase 2 hardening)

Re-architect `SophiaConnection.ConnectFlow` to RETRY the mic check after the permission grant. Two paths:

Path A (Unity-native, simplest): after the auth coroutine yields, poll `Microphone.devices` for up to 5s with 200ms intervals before bailing.

Path B (Android-native, robust): write a small JNI helper that calls `ActivityCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO)` (returns PackageManager.PERMISSION_GRANTED only after actual grant) and wraps `ActivityCompat.requestPermissions(activity, new String[]{RECORD_AUDIO}, REQ_CODE)` with a callback so the coroutine truly blocks on the grant. Bonus: lets us swap the audio source from VOICE_RECOGNITION to VOICE_COMMUNICATION at the same time (Q41 / Q43 — enables Android system AEC).

Either path means: cold-launch UX works without the user having to know about force-stop+relaunch.

### Confirmed grant via dumpsys

After granting once, you can verify the persistent state:
```bash
adb shell dumpsys package <pkg> | grep RECORD_AUDIO
# → android.permission.RECORD_AUDIO: granted=true, flags=[ USER_SET|USER_SENSITIVE_WHEN_GRANTED|USER_SENSITIVE_WHEN_DENIED]
```

`granted=true` here means the OS has it on file; subsequent app launches see `Microphone.devices` populated synchronously without re-prompting.

### Side note: confirmation of Q43's prediction

Following this fix, the full voice loop ran end-to-end on Beam Pro through the mic — and once the user put on the XREAL One Pro glasses with the same Beam Pro, **no acoustic echo was audible**. The geometry argument from Q43 was validated empirically: XREAL One Pro near-ear speakers + Beam Pro mic in hand/pocket = loop gain too low for echo to manifest, despite the Unity Microphone API NOT engaging Android's AcousticEchoCanceler. Mic gating was NOT needed for Phase 1 ship. We can ship as-is and only add gating if a future deployment scenario surfaces echo.

---

## Q48 (2026-05-21): How do you build a runtime AR HUD overlay in Unity for the XREAL One Pro, without needing the user to wire UI components in the Editor?

Programmatic world-space Canvas as a child of `Camera.main`, with TMP text panels. Three things to know.

### Pattern

```csharp
private void BuildCanvas(Camera cam)
{
    var canvasGO = new GameObject("SophiaCanvas");
    canvasGO.transform.SetParent(cam.transform, false);
    canvasGO.transform.localPosition = new Vector3(0f, 0f, 2.0f);  // 2 metres in front
    canvasGO.transform.localRotation = Quaternion.identity;
    canvasGO.transform.localScale = Vector3.one * 0.0012f;          // see below

    var canvas = canvasGO.AddComponent<Canvas>();
    canvas.renderMode = RenderMode.WorldSpace;
    canvas.worldCamera = cam;

    canvasGO.AddComponent<CanvasScaler>();
    canvasGO.AddComponent<GraphicRaycaster>();

    var rect = canvasGO.GetComponent<RectTransform>();
    rect.sizeDelta = new Vector2(1920, 1080);  // virtual pixels
}
```

Then child panels via `new GameObject(...)` + `AddComponent<RectTransform>()` + `AddComponent<Image>()` and TMP text via `AddComponent<TextMeshProUGUI>()`.

### Sizing math

Canvas size 1920×1080 virtual pixels × 0.0012 scale = 2.30m × 1.30m physical at the camera-local origin. At 2.0m focal distance, that fills most of the XREAL One Pro's field of view comfortably (~45° H × 26° V → 90% horizontal fill).

Tune `distanceFromCamera` (1.5–3.0m comfortable focal range) and `canvasScale` (~0.001 baseline) per preference. Closer = bigger apparent panels but more eye strain; farther = smaller but easier on the eyes.

### Head-locked vs world-anchored

Parenting the Canvas to `Camera.main` = head-locked HUD (panels move with your head). Best for status pills, transcripts, things that should always be visible.

To world-anchor instead (panels stay in the room when you turn your head — best for AR labels pinned to objects), drop the `SetParent(cam.transform)` call and just set world position. Trade-off: user might lose the UI by looking away.

For Phase 1/2 we chose head-locked because the UI IS the application — there's nothing else to look at.

### TMP Essentials Resources MUST be imported for runtime TMP_Text creation

Symptom without import:
```
NullReferenceException: Object reference not set to an instance of an object.
  at TMPro.TMP_Settings.get_autoSizeTextContainer
  at TMPro.TMP_Text.LoadDefaultSettings
  at TMPro.TextMeshProUGUI.Awake
```

Every call to `AddComponent<TextMeshProUGUI>()` will throw at Awake. The component object gets created (`GameObject.AddComponent` returns) but its internal state is invalid; you'll see panel backgrounds with no text.

Cause: TMP needs `Assets/TextMesh Pro/Resources/TMP Settings.asset` to exist at build time. The URP / blank Unity templates DO include the TextMeshPro PACKAGE but DO NOT include the resources. Unity normally prompts to import on first TMP component creation in the Editor — if you create components purely at runtime (as in our `SophiaOverlayUI`), you never trigger that prompt during edit-time.

Fix: `Window > TextMeshPro > Import TMP Essential Resources` → ~10s import → rebuild. Creates `Assets/TextMesh Pro/` with the default font (LiberationSans SDF), shaders, sprite asset, and `TMP Settings.asset`.

Once imported, `TextMeshProUGUI.Awake` finds `TMP_Settings.instance` and runtime instantiation works cleanly.

### Camera.main caveat for XREAL stereo rendering

For Phase 1/2 we render the Main Camera's view as a flat 2D image to the glasses display (no stereo rendering — XR Plugin Management not configured). The log warning is visible at startup:
```
No XR Manager settings found, manifest entries will not be updated.
```

That means the HUD appears on both eyes of the glasses but without depth-correct stereo presentation — it's a flat overlay. Fine for status displays, less ideal for true AR labels pinned to depth.

To enable proper stereo: Phase 3 should configure `Edit > Project Settings > XR Plug-in Management > Android > XREAL Loader (check)`, then the XREAL camera rig handles per-eye rendering and Canvas world-space positioning becomes properly depth-aware.

### File reference

`sophia-glasses/unity/Assets/Scripts/SophiaOverlayUI.cs` — full working example. Combines this pattern with subscription to `SophiaConnection.OnTextStreamMessage` to update three panels (state pill / transcript / RAG sources) from agent text-stream events.

---

## Q49 (2026-05-22): For the XREAL One Pro + Beam Pro build, what Unity settings + UI code changes are needed so screens render landscape instead of clipped/cramped portrait?

XREAL One Pro displays are 1920×1080 LANDSCAPE per eye. Three places need to agree — Player orientation, Game-view aspect (Editor preview), and every runtime `CanvasScaler.referenceResolution`.

### Symptom

In Editor Play mode the picker looks taller than wide. After APK install on Beam Pro the picker / HUD shows clipped at top or bottom in glasses, or the card looks misproportioned even though the canvas was "set up correctly" for screen-space overlay.

### The three places to align

**1. Edit → Project Settings → Player → Resolution and Presentation**
- Default Orientation: `Landscape Left`
- Allowed Orientations: only Landscape Left + Landscape Right checked; Portrait + Portrait Upside Down unchecked

Pins the Android manifest's `screenOrientation` to landscape regardless of how the user holds the Beam Pro handset.

**2. Game view aspect (Editor only — for Play-mode preview)**
Game tab → aspect dropdown → `1920×1080 Landscape`. Without this the editor preview is portrait, and the picker appears cramped even though it'll render fine on Beam Pro after orientation is locked.

**3. `CanvasScaler.referenceResolution` in every runtime-built canvas**
If your `CanvasScaler` init uses `new Vector2(1080, 1920)` (portrait reference) with `MatchWidthOrHeight = 0.5f` on an actual 1920×1080 screen, the scaling math becomes `sqrt(1920/1080) * sqrt(1080/1920) = 1.0` — the card renders at its native pixel size. If your card sizeDelta is 800×1100 (taller than 1080), it clips top/bottom of the screen.

Wrong:
```csharp
scaler.referenceResolution = new Vector2(1080, 1920);  // portrait
var card = CreateChild(panel, "Card", ..., new Vector2(800f, 1100f));  // taller than screen
```

Right:
```csharp
scaler.referenceResolution = new Vector2(1920, 1080);  // landscape
var card = CreateChild(panel, "Card", ..., new Vector2(1500f, 900f));  // fits with margin
```

Then rebuild the card body as a horizontal two-column layout (left half + vertical divider + right half) so the card actually uses the wide aspect.

### World-space canvases (HUD) — already landscape

`SophiaOverlayUI.cs` uses `canvasSize = new Vector2(1920, 1080)` (line 34). World-space canvases use this as the rect dimensions, NOT screen resolution. With `canvasScale=0.0012` at 2 m focal distance the HUD is ~2.3 m × 1.3 m — already landscape, no change needed. Only the screen-space picker canvas had to be flipped.

### Files touched

- `sophia-glasses/unity/Assets/Scripts/SessionPicker.cs:225` — `referenceResolution = new Vector2(1920, 1080)` (was 1080×1920).
- `sophia-glasses/unity/Assets/Scripts/SessionPicker.cs:244-310` — card rewritten as landscape 1500×900 with two-column body (Private on left, Team on right, vertical divider between, title spans top, Quit at bottom-center).

---

## Q50 (2026-05-22): The Unity HUD's agent transcript text appears AFTER Sophia finishes speaking, but in the browser the text and TTS audio are in sync. Why?

`TextStreamReader.ReadAll()` buffers the entire stream until the sender closes it — you get one emit at end-of-stream. The browser uses incremental reads, so it gets each token as the agent generates it. Switch to `TextStreamReader.ReadIncremental()` in the Unity client.

### Two reader APIs in the Unity SDK

| API | Behavior |
|---|---|
| `reader.ReadAll()` | Returns one `ReadAllInstruction` that completes when the sender CLOSES the stream. `instruction.Text` holds the concatenated payload. ONE emit total. |
| `reader.ReadIncremental()` | Returns a `ReadIncrementalInstruction` whose `Text` property exposes the latest chunk. You yield-loop while `!IsEos`. Multiple emits, one per chunk. |

If the Unity client handler calls `ReadAll()` against `lk.transcription`, the agent's transcript doesn't reach the UI until TTS finishes — exactly what makes the HUD look like a post-hoc subtitle.

### Why the browser already gets it right

The React frontend uses `useTextStream(topic)` from `@livekit/components-react`, which subscribes incrementally under the hood. That's why text appears in sync with TTS in the browser but lagged in Unity.

### The Unity fix (pattern from the SDK docstring)

```csharp
private IEnumerator LogTextStream(string topicTag, TextStreamReader reader, string identity)
{
    var inc = reader.ReadIncremental();
    var accumulated = new StringBuilder();
    while (!inc.IsEos)
    {
        inc.Reset();
        yield return inc;
        if (inc.IsError) break;
        var chunk = inc.Text;        // latest chunk only — NOT cumulative
        if (string.IsNullOrEmpty(chunk)) continue;
        accumulated.Append(chunk);
        OnTextStreamMessage?.Invoke(topicTag, identity, accumulated.ToString());
    }
}
```

Two non-obvious details:

1. **`ReadIncrementalInstruction.Text` returns LATEST CHUNK (one delta), not the accumulated text.** You have to append yourself with a `StringBuilder`. If you forget, the panel will flicker through individual chunks instead of growing.
2. **`StreamYieldInstruction.keepWaiting => !IsCurrentReadDone && !IsEos`** — the yield naturally unblocks at end-of-stream too, you don't need a separate `IsEos` poll inside the yield. The `while (!inc.IsEos)` outer check is enough.

### Side effect on small JSON-payload topics

`sophia.rag_result` and `sophia.agent_events` typically arrive as a SINGLE chunk (small enough to fit in one FFI frame). Switching to incremental doesn't regress them — you still get one emit with the full payload. If a payload IS large enough to chunk, intermediate `accumulated` snapshots are partial JSON, but the tiny key-by-key parsers in `SophiaOverlayUI.ExtractJsonString` return null on missing markers — so partial parses are silent no-ops until the final chunk completes the JSON.

### File touched

`sophia-glasses/unity/Assets/Scripts/SophiaConnection.cs:315-352` — `LogTextStream` rewritten to use `ReadIncremental` + `StringBuilder` accumulation.

---

## Q51 (2026-05-22): The Unity HUD never shows agent state (LISTENING/THINKING/SPEAKING) or RAG sources, even though the browser frontend renders them and the agent's logs confirm both topics are published. Why?

Python's `json.dumps()` defaults to `": "` (colon + space) as the key/value separator. The Unity HUD's tiny JSON extractor was hard-coded to match `"key":"value"` (no space) so `IndexOf` returned -1 for every payload — silent drop, no error, panel stays on its default.

### The trap

The agent emits payloads like:

```json
{"ts": 1748907000.12, "kind": "agent_state", "old": "listening", "new": "thinking"}
```

— space after every colon. That's Python's `json.dumps(payload)` default (`separators=(", ", ": ")` when no `separators` kwarg is passed).

The Unity helper `ExtractJsonString` did:

```csharp
var marker = "\"" + key + "\":\"";        // looking for: "kind":"
var i = json.IndexOf(marker, StringComparison.Ordinal);
if (i < 0) return null;
```

For input `"kind": "agent_state"` (real payload), the marker `"kind":"` (no space) never appears in the string. `IndexOf` returns -1, function returns null, `SetAgentState` is never called, state pill stays "CONNECTING" forever. Same bug killed `"new"`, `"question"`, and `"source"` lookups — so the entire HUD was dark for state + RAG even though events were flowing.

### Why the browser doesn't see this

`@livekit/components-react`'s `useTextStream` passes chunks straight to `JSON.parse(text)`, which is whitespace-tolerant per RFC 8259 — it accepts any amount of whitespace between tokens.

### Two possible fixes — picked the client side

1. **Agent side:** call `json.dumps(payload, separators=(",", ":"))` for compact JSON with no spaces. Saves a few bytes per message. Requires editing the Python agent.
2. **Client side:** make the extractor whitespace-tolerant. Self-contained Unity fix, doesn't depend on the agent's serialization choices.

We did (2):

```csharp
// Old: marker = "\"" + key + "\":\"";   // strict — no whitespace allowed
// New: match "key": then skip whitespace, then expect '"'
var keyMarker = "\"" + key + "\":";
var i = json.IndexOf(keyMarker, StringComparison.Ordinal);
if (i < 0) return null;
i += keyMarker.Length;
while (i < json.Length && (json[i] == ' ' || json[i] == '\t' ||
                           json[i] == '\n' || json[i] == '\r')) i++;
if (i >= json.Length || json[i] != '"') return null;
i++;
// ... existing close-quote scan unchanged ...
```

Same change in `ExtractSourceFilenames` for the `"source":` key inside RAG hit objects.

### Symptom checklist for "browser-works-Unity-doesn't" parser bugs

When the React side renders something the Unity HUD doesn't:
1. Add `Debug.Log` of the raw `payload` string in `OnTextStreamMessage` — confirm it's arriving over the wire.
2. If arriving but not rendering, the bug is in the Unity-side parser, not in transmission.
3. Common pitfalls in homemade JSON parsers: whitespace after colons (this one), escaped quotes inside string values, unicode escape sequences (`\uXXXX`), nested objects/arrays. Once payloads grow beyond flat string maps, switch to `Newtonsoft.Json` or `System.Text.Json` instead of regex/IndexOf scans.

### File touched

`sophia-glasses/unity/Assets/Scripts/SophiaOverlayUI.cs:382-432` — `ExtractJsonString` and `ExtractSourceFilenames` now match `"key":` and skip whitespace before the opening `"` of the value.

## Q52 (2026-05-25): In Unity Editor Play mode the LiveKit RtcAudioSource fails on the very first audio frame with `InvalidState - sample_rate and num_channels don't match`. Sample rate was already set to 48000 in Project Settings > Audio. Why?

`MicrophoneSource` registers its native audio source with `_expectedSampleRate = DefaultMicrophoneSampleRate` which is 48000 on macOS (`RtcAudioSource.cs:55`). The actual frames come out of `AudioProbe.OnAudioFilterRead`, which delivers data at `AudioSettings.outputSampleRate` and the channel count of the active mixer. The Rust FFI side rejects the frame if either differs from what was registered at construction.

On macOS, `AudioSettings.outputSampleRate` is NOT the value you set in Project Settings > Audio > System Sample Rate. Unity's audio engine inherits the rate of the active OUTPUT device from Core Audio, regardless of the project setting. Many output devices (EarPods, some Bluetooth headsets, even MacBook speakers if not manually forced) default to 44100 Hz. Result: actual 44100, expected 48000, native rejects.

Confirmation pattern: look for two log lines in the Unity Console.
```
NewAudioSource: 2 48000                                           // what the SDK registered
RtcAudioSource#1 audio frame #1 metadata mismatch actualRate=44100 actualChannels=2 expectedRate=48000 expectedChannels=2
```

### Fix (no code change)

macOS Audio MIDI Setup (`/Applications/Utilities/Audio MIDI Setup.app`):
1. Select the currently active output device in the left list.
2. In the right panel's Format dropdown, pick `2 ch 16-bit Integer 48,000 Hz` (or 32-bit float at 48 kHz).
3. Quit Unity Editor fully (Cmd+Q) and reopen. Audio engine initializes at editor startup; just changing m_SampleRate in a running editor does not propagate to `AudioSettings.outputSampleRate`.

### Not affected

Beam Pro and Android phones are not affected because Android USB Audio Class always negotiates 48000 Hz. The mismatch is macOS Editor only. Q42 covers the broader sample-rate trap; Q52 is the concrete fix path when the symptom hits.

## Q53 (2026-05-25): The Phase 2 HUD is functional but visually cluttered for AR (three big rectangular panels occluding the field of view). Redesigned to "Direction A: subtitle-minimal". What's the contract?

Three new principles for the AR HUD:
1. Center of vision stays clear (industrial users need to look at equipment, not chrome).
2. Information is ephemeral — appears when relevant, fades when not.
3. Translucent panels with hairline borders so the real world bleeds through.

Layout:
- Top-right corner: small filled colored dot (24 px). Grey connecting, green listening, amber thinking, blue speaking. Pulses while thinking/speaking, solid while listening. No text.
- Bottom-center: one-line subtitle showing the latest spoken line (user OR Sophia). Speaker tag colored, body white. Fades in instantly on new line, fades out 2 seconds after Sophia stops.
- Above the subtitle: vertical stack of RAG source chips (one per unique source-page pair from hits[]). Capped at 6. Fades in when retrieve_injected lands, fades out 0.5 seconds after Sophia stops.
- End Session control: shrunk to a tiny 120x80 corner chip on the Beam Pro screen-space overlay (bottom-right). In glasses FOV it's at the extreme edge and effectively invisible; on the phone touchscreen it's still tappable.

### Implementation details

- World-space Canvas parented to Camera.main at 2 m focal distance. Same head-locked pattern as before.
- Procedural circle sprite generated at runtime (`MakeCircleSprite()`) so the state dot is a clean disc, not a square.
- All fades via CanvasGroup alpha with a smoothstep ease (`FadeTo()` coroutine), 200 ms duration.
- Vertical chip layout via `VerticalLayoutGroup` + `ContentSizeFitter` so the container resizes to fit any number of chips.
- RAG hit parsing walks the JSON `"hits": [...]` array, brace-balancing each object, extracting `source` + `page` per hit. Page may be int OR string ("?"); both supported.
- All SerializeField tunables stay on the script for live Inspector adjustment without recompile: `subtitleFontSize`, `subtitleWidth`, `subtitleBottomMargin`, `subtitleHoldAfterSpeak`, `chipFontSize`, `chipsGap`, `maxChips`, `chipsFadeAfterSpeak`, `fadeDuration`, `dotPulseHz`, `dotSize`, `dotEdgeMargin`.

### Full spec

`sophia-glasses/HUD_direction_a.md` has the design rationale, ASCII layout sketch, per-element behaviour table, and a turn-by-turn timeline showing what's visible at each phase of a conversation.

### Files touched

- `sophia-glasses/unity/Assets/Scripts/SophiaOverlayUI.cs` — full rewrite end-to-end. ~450 lines.
- `sophia-glasses/unity/Assets/Scripts/SessionPicker.cs` — `BuildInSessionPanel` shrunk to corner End chip.

## Q54 (2026-05-25): A red panel of log lines appears in the bottom-left of the glasses display showing error-level logs. It's not Unity's dev overlay and not our HUD. Where does it come from and how do we suppress it?

It's the XREAL Auto Logcat overlay, shipped inside `xreal-auto-log-1.2.aar` (a hidden dependency bundled by the XREAL SDK). Inspect the AAR:

```bash
unzip -l <project>/Library/Bee/Android/Prj/IL2CPP/Gradle/unityLibrary/libs/xreal-auto-log-1.2.aar
unzip -p <same path> AndroidManifest.xml
```

The AAR declares a ContentProvider:
```xml
<provider
    android:name="com.xreal.evapro.autologcat.AutoLogProvider"
    android:authorities="${applicationId}.auto_log"
    android:exported="false" />
```

ContentProviders auto-initialize before any of our app's code runs, so the overlay registers no matter what. `XREALSettings.asset` has an `EnableAutoLogcat: 0` toggle, but that only controls the SDK's runtime logging behaviour — it does NOT prevent the AAR's ContentProvider from registering. The overlay then activates whenever any ERROR-level logcat line is produced.

Why it only became visible THIS session: earlier sessions only produced WARN-level logs (multiple AudioSources, 16KB alignment, MissingReferenceException on shutdown). This session's new SophiaOverlayUI code path produces at least one ERROR-level log (still being investigated), which wakes the overlay.

### Fix attempt — AndroidManifest provider removal

Custom Main Manifest at `Assets/Plugins/Android/AndroidManifest.xml`:
```xml
<provider android:name="com.xreal.evapro.autologcat.AutoLogProvider"
          android:authorities="${applicationId}.auto_log"
          tools:node="remove" />
```

This SHOULD make the Android manifest merger drop the provider from the final merged manifest. Confirmation step: grep `AutoLogProvider` in `Library/Bee/Android/Prj/IL2CPP/Gradle/launcher/build/intermediates/packaged_manifests/debug/processDebugManifestForPackage/AndroidManifest.xml`. If the provider still appears there, the override didn't take effect.

### Status

Tried on 2026-05-25. The provider DOES get removed from the merged manifest (confirmed via grep), but a red panel still appears in the glasses display with what appears to be log content. The user reported "i see the red still now, but clear button beside removed it". Hypothesis: the AAR has a secondary code path (maybe a static initializer or a JNI hook) that draws the overlay independent of the registered ContentProvider, OR a separate XREAL SDK component (e.g. `FloatingManager`) draws it. The clear button suggests this is a runtime UI element with its own controls, not a passive log drain — implying SDK-level rendering, not Android-system level.

### Followups (deferred per user)

- Read AutoLogcatHelper.class via decompiler (`jd-gui` or `cfr`) to find the activation path that doesn't go through the ContentProvider.
- Check XREALSettings.asset's other flags for an overlay-specific toggle.
- Find the underlying ERROR log that's triggering the overlay; if we fix the root error, the overlay stays silent regardless of whether it loaded.
- Worst case: delete the AAR from the SDK package on disk (would require finding where Unity caches the XREAL UPM tarball).

## Q55 (2026-05-25): Why did writing a Custom Main Manifest break the Unity 6 build with `Theme.AppCompat` crash and `Activity not exported` error?

Unity 6's behaviour for `Assets/Plugins/Android/AndroidManifest.xml` is to use it AS the unityLibrary base manifest, NOT as an additive overlay. Any element absent from your custom file gets dropped from the final merged manifest.

Two crashes encountered in sequence while iterating on the manifest:

### Crash 1: `Theme.AppCompat` required

Unity 6 launches via `UnityPlayerGameActivity` which extends Google's `androidgamesdk.GameActivity`. GameActivity uses AndroidX AppCompat and REQUIRES a theme that descends from `Theme.AppCompat`. Unity's correct theme is `@style/BaseUnityGameActivityTheme`, NOT the legacy `@style/UnityThemeSelector` (which was for the older UnityPlayerActivity).

Symptom in logcat:
```
java.lang.IllegalStateException: You need to use a Theme.AppCompat theme (or descendant) with this activity.
   at androidx.appcompat.app.AppCompatDelegateImpl.createSubDecor
```

### Crash 2: Activity not exported

Symptom on `adb shell am start ...`:
```
SecurityException: Permission Denial: starting Intent { ... } not exported from uid ...
```

Because our minimal manifest declared no activity, the merger emitted a stub `<activity android:name="..." />` with no attributes. `android:exported` defaulted to false on Android 12+ (mandatory explicit declaration). `adb shell am start` cannot launch a non-exported activity.

### Working manifest pattern

Don't go minimal. Mirror what Unity normally generates, layer the provider remove on top:

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
          xmlns:tools="http://schemas.android.com/tools">
    <application>
        <activity android:name="com.unity3d.player.UnityPlayerGameActivity"
                  android:theme="@style/BaseUnityGameActivityTheme"
                  android:configChanges="..."
                  android:enabled="true"
                  android:exported="true"
                  android:hardwareAccelerated="false"
                  android:launchMode="singleTask"
                  android:resizeableActivity="true"
                  android:screenOrientation="landscape">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <meta-data android:name="unityplayer.UnityActivity" android:value="true" />
            <meta-data android:name="android.app.lib_name" android:value="game" />
            ...
        </activity>

        <provider android:name="com.xreal.evapro.autologcat.AutoLogProvider"
                  android:authorities="${applicationId}.auto_log"
                  tools:node="remove" />
    </application>
</manifest>
```

The `android.app.lib_name = "game"` meta-data is critical for IL2CPP to find the right native library. The `BaseUnityGameActivityTheme` is what unblocks the AppCompat crash. The `android:exported="true"` is what unblocks adb-launched starts on Android 12+.

### Diagnostic recipe — read the actually-installed manifest

```bash
grep -B1 -A12 "UnityPlayerGameActivity" \
  "<project>/Library/Bee/Android/Prj/IL2CPP/Gradle/launcher/build/intermediates/packaged_manifests/debug/processDebugManifestForPackage/AndroidManifest.xml"
```

If the activity block is a bare `<activity android:name="..." />` with no attributes, your custom manifest is missing pieces.

### Also: XML comment rule

The Android manifest XML parser rejects `--` inside comments (XML spec). An em-dash style comment like `--for this reason--` causes a parse failure at build time. Use single dashes or rewrite without dashes.

### Files touched

- `sophia-glasses/unity/Assets/Plugins/Android/AndroidManifest.xml` (new, ~40 lines)
- Also required: Edit menu > Project Settings > Player > Publishing Settings > Custom Main Manifest checkbox enabled (Unity auto-detects the file, but the checkbox makes the dependency explicit).

## Q56 (2026-05-25): For the multi-room shared-session demo we need both the browser client and the glasses client to join the same LiveKit room. The browser auto-generates a random room name on every page load. What's the smallest patch?

Two coordinated changes in `agent-starter-react`. The server-side token route reads a `?room=<name>` query parameter from the request URL; the client extracts the same parameter from `window.location.search` and forwards it onto the token endpoint URL it builds. Result: opening `http://localhost:3000?room=demo-team` joins the room `demo-team`. Opening plain `http://localhost:3000` auto-generates as before.

### Server side — `app/api/token/route.ts`

```ts
const roomOverride = new URL(req.url).searchParams.get('room')?.trim();
const roomName = roomOverride
  ? roomOverride
  : `voice_assistant_room_${Math.floor(Math.random() * 10_000)}`;
```

Placed where the random room name was generated. No other change.

### Client side — `components/app/app.tsx`

The starter uses `TokenSource.endpoint('/api/token')`. We append the query param to that URL when the browser's page URL has a `room` param:

```ts
let endpoint = '/api/token';
if (typeof window !== 'undefined') {
  const roomParam = new URLSearchParams(window.location.search).get('room');
  if (roomParam && roomParam.trim().length > 0) {
    endpoint += `?room=${encodeURIComponent(roomParam.trim())}`;
  }
}
return TokenSource.endpoint(endpoint);
```

`window` guard is required because `useMemo` runs during SSR where `window` is undefined.

### How the glasses side handles the same case

Already supported via SessionPicker's Team Session UI (livekit_doubts.md Q49 / unity_approach.md Appendix C). The user types the room code into the TMP_InputField and SophiaSessionContext.RoomOverride routes it into SophiaConnection's `_resolvedRoom`.

So for the demo: type `demo-team` in the glasses picker AND open `http://localhost:3000?room=demo-team` in the browser. Both clients land in room `demo-team`. The agent worker spawns one subprocess for that room, both clients share one Sophia, one conversation history, one chat_ctx.

### Files touched

- `agent-starter-react/app/api/token/route.ts` (3 line diff)
- `agent-starter-react/components/app/app.tsx` (10 line diff)

## Q57 (2026-05-25): With both browser and glasses in the same room (Q56), audio from glasses works (Sophia answers, both clients see/hear it). Audio from browser doesn't (Sophia never responds to browser-side speech). Why and what to debug?

This is the rare audio asymmetry case in a shared LiveKit room. Both clients publish audio tracks; the agent's STT receives all subscribed user tracks. So in theory both should reach the agent equally. In practice, several browser-side things can drop the publish path silently.

### Triage order (most to least likely)

1. **Browser UI mic toggle.** agent-starter-react's UI has a mic button on the call bar. If muted, the published audio track contains silence. Click to unmute. Browser-side LiveKit also auto-mutes if mic permission is denied; the toggle will be in a fail state.

2. **Browser mic permission + device selection.** Chrome URL bar's mic icon (left of URL). Click it, check which input device is selected. With earphones plugged in, macOS often auto-routes to "EarPods Microphone" or "AirPods Microphone" which may be a different device than what's plugged in. Force-pick "MacBook Pro Microphone" or whichever you're speaking near.

3. **macOS system input.** Apple menu > System Settings > Sound > Input. Confirm the active device, watch the level meter while speaking. If the meter doesn't move there, no app gets audio from that input.

4. **Agent worker log.** Watch the agent worker terminal during browser-side speech. You should see lines like:
   ```
   user_input_transcribed speaker_id=voice_assistant_user_XXXX text="..."
   ```
   If you see these, audio reached the agent and the issue is downstream (turn detector didn't fire end-of-utterance, etc.). If you DON'T see these, browser audio is not reaching the SFU — fix is browser-side.

### Diagnostic snippet (Chrome DevTools console)

```js
navigator.mediaDevices.enumerateDevices().then(d =>
  d.filter(x => x.kind === 'audioinput').forEach(x => console.log(x.label)))
```

Lists every audio input device Chrome can see. Then check via LiveKit's debug overlay (or DevTools Network -> WS) which device the published track is using.

### Status

Open as of 2026-05-25 session end. User reported "when i speak from browser via earphones, the agent doesnt use the microphone i guess, is it true and i dont see agent giving answers". Triage steps queued above; needs the user to run them next session.

**Update later same session**: while debugging the inverse symptom (browser hears Sophia but glasses don't, "speaker used is earphones only, i dont hear from beampro"), traced the root cause to a Unity-side AudioSource conflict that ALSO explains Q57. With two clients in the same room, the Beam Pro client subscribes to TWO remote audio tracks: Sophia's TTS + the browser user's mic. The pre-fix `OnTrackSubscribed` handler created a new AudioSource on the SAME GameObject (`speakerHost`) for every audio track, leaving the GameObject with 3+ AudioSources stacked (mic capture, agent TTS, peer mic, etc.). Unity's audio mixer + `AudioProbe.OnAudioFilterRead` cannot handle multiple AudioSources on one GameObject cleanly; one wins the slot and the others silently drop. On Beam Pro the browser-mic AudioSource ended up winning, so Sophia's TTS was dropped. The browser doesn't see this because livekit-client JS uses one HTMLAudioElement per track which the browser mixes natively. See Q58 for the production fix that closes both this symptom and Q57.

## Q58 (2026-05-25): What's the production-correct contract for audio playback when multiple participants share a LiveKit room? How do we make sure each device plays only what it should, with no echo / no cross-mic playback?

The production contract: each user owns their OWN mic AND their OWN speaker. The agent (Sophia) is the only voice that is shared across devices. Other human participants' raw mic tracks are subscribed by the SFU (so the agent's STT receives all of them and Sophia can answer about anything anyone says), but those raw mic tracks must NOT be played back through other users' local speakers. If you do play them, you get acoustic chaos: users hear themselves echoed back through each other's speakers, mixed with Sophia's TTS, with timing skew.

Two technical changes are required in the Unity client to implement this correctly.

### 1. Filter playback to agent tracks only

In `OnTrackSubscribed`, gate the AudioSource creation on participant identity:

```csharp
bool isAgent = !string.IsNullOrEmpty(participant?.Identity)
               && participant.Identity.StartsWith("agent-");
if (!isAgent)
{
    Debug.Log($"[Sophia] Skipping playback for non-agent audio track from " +
              $"'{participant?.Identity}' (room mate's mic; intentional).");
    return;
}
```

LiveKit's default `AutoSubscribe = true` still pulls the bytes over the wire (small bandwidth cost), but we never wire them to a playing AudioSource. For larger rooms with many concurrent users, an optimization is `AutoSubscribe = false` + selective subscription to agent tracks only -- but the simple filter handles 2-3 participant rooms with negligible cost.

### 2. One child GameObject per remote audio track

Stacking multiple AudioSources on a single GameObject is unsafe in Unity Android: `AudioProbe.OnAudioFilterRead` can only bind to one AudioSource at a time, and Unity's mixer doesn't always pick the right one. The fix: every subscribed remote audio track gets its OWN child GameObject under `speakerHost`, named by its publication SID for traceability.

```csharp
private readonly Dictionary<string, GameObject> _remoteSpeakers = new();

private void OnTrackSubscribed(IRemoteTrack track, RemoteTrackPublication publication,
                               RemoteParticipant participant)
{
    if (track is not RemoteAudioTrack audioTrack) return;
    if (!IsAgent(participant)) return;          // see filter above

    var sid = publication?.Sid ?? Guid.NewGuid().ToString("N").Substring(0, 8);
    var speakerName = $"SophiaSpeaker_{sid}";
    var speakerGO = new GameObject(speakerName);
    speakerGO.transform.SetParent(speakerHost.transform, false);

    var src = speakerGO.AddComponent<AudioSource>();
    src.loop = true;
    src.spatialBlend = 0f;
    new AudioStream(audioTrack, src);

    _remoteSpeakers[sid] = speakerGO;
}
```

`OnTrackUnsubscribed` finds the speaker by SID and destroys it; `Cleanup()` destroys all remaining speakers on disconnect / pause / quit. This prevents leaked AudioSources when the next session starts.

### Why this also fixes the "Sophia heard only on earphones, not on Beam Pro" symptom

Before the fix, Beam Pro had three AudioSources on the SophiaConnection GameObject: its own mic capture, Sophia's TTS, and the browser user's mic. The browser-mic AudioSource won Unity's playback slot (despite being near-silent) and Sophia's TTS got dropped. After the fix:
- Beam Pro filters out the browser-mic subscription entirely (no AudioSource for it).
- Beam Pro creates one child GameObject for Sophia's TTS with its own AudioSource.
- Mic capture stays on the parent GameObject with `AudioProbe` bound to that ONE AudioSource as the SDK expects.

Result: Sophia plays on the glasses speakers as in Scenario B, while the browser user separately hears Sophia through Mac earphones. No bleed.

### Why this is the right model long-term

- Each participant device has full control over its own speaker (volume, route, mute).
- No participant ever has to deal with another user's microphone artifacts (cough, background noise, breath).
- Shared experience emerges only through Sophia's voice, which is intentional content (synthesized from the shared chat_ctx).
- Per-participant speaker AudioSources can later carry their own AudioMixer group / spatial position / volume curve if the UX needs them.
- Matches how Zoom, Discord, etc. handle multi-party audio: server-side mixing for the conversation feed, client-side single output stream.

### What this CLOSES

- Q57 browser-mic-asymmetry: the underlying issue was the inverse — Beam Pro wasn't playing Sophia, not browser wasn't capturing. The Q57 triage list is still useful for genuine browser mic problems, but the specific Scenario-A symptom Q57 was opened for is resolved here.
- Phase 2 hardening item "separate child SophiaSpeaker GameObject for remote audio (eliminates multiple AudioSources warning)" — done.
- Phase 2 hardening item "unregister text-stream handlers in OnDisable" — still pending; that's a separate concern.

### Files touched

- `sophia-glasses/unity/Assets/Scripts/SophiaConnection.cs` — added `using System.Collections.Generic`, added `_remoteSpeakers` dictionary field, rewrote `OnTrackSubscribed` with agent filter + child GameObject creation, extended `OnTrackUnsubscribed` to destroy the matching child, extended `Cleanup()` to destroy all child speakers on disconnect.

### Pending validation

User to rebuild APK + reinstall + re-run Scenario A demo (`?room=demo-team` in browser + glasses' Team Session with code `demo-team`) and confirm Sophia plays on BOTH the glasses speakers and the Mac earphones simultaneously when either user speaks.
