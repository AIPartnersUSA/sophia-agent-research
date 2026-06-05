# Sophia Voice Agent — End-to-End Architectural Flow

How a voice conversation actually flows through the system from "user hits Play" / "user speaks into XREAL" all the way through inference and back to audio out. Covers the Unity Editor Play Mode path (dev/test on Mac), the XREAL + Beam Pro production wearable path (Android), and what changes after infra team deploys to production AWS.

This is the runtime / data-flow view. For the code-change view of how the integration was built, see `livekit_integration_sophia_wearable.md`.

---

## Two paths × three backend phases

**Two client paths** (same Unity code, different deployment targets):
- **Path A — Unity Editor Play Mode** on Mac (dev / smoke test loop).
- **Path B — XREAL One Pro + Beam Pro** (Android APK; production hardware).

**Three backend phases** (the same client code points at different backends as the project matures):
- **Phase 1 (today)** — MVP backend on EC2 (`3.227.63.49`), HTTP + WS (no TLS), cross-region EKS port-forward for inference.
- **Phase 2 (after smoke test)** — Phase 1 + port-forward running, full voice loop verified.
- **Phase 3 (future)** — Infra team deploys production AWS per `HANDOFF.md`: HTTPS + WSS, real DNS, autoscaled SFU + workers, Secrets Manager, external load balancers.

This doc walks all three phases for both paths.

---

## Path A: Unity Editor Play Mode (Mac)

### A.1 What the user does

Pre-conditions (one-time):
1. Work clone at `/Users/avinashbolleddula/Documents/repos/Sophia_Xreal-U2-main/` on branch `avinash/livekit-provider`.
2. Unity Editor `6000.3.12f1` installed.
3. Project opened in Unity Editor with a clean compile state.
4. `Sophia_Wearables.unity` scene loaded.
5. `LiveKitLlmProvider` GameObject exists in Hierarchy under `Logic/Modules/ConversationalAI` with Inspector fields wired (URLs + tokenApiKey + MicrophoneStreamer reference).
6. Provider Configuration Manager: `Active Conversation Provider = LiveKit (WebRTC + LiveKit Agents)`, `customizedEndpointsBundle = None`, `endpointConfigurationMode = Customized`.
7. Player Settings: `Allow downloads over HTTP = Always allowed`.

Per-session actions:
1. **Hit Play** (triangle button at top center of Unity Editor).
2. Speak into Mac microphone when ready.
3. Listen for Sophia's response through Mac speakers.
4. **Hit Stop** when done.

That's it. No port-forward / docker / kubectl needed on the Mac side — all backend reachability is via the public EC2 IP.

### A.2 End-to-end flow on Mac Editor (today's Phase 1 MVP)

```
┌─────────────────────────────┐
│  Unity Editor on Mac        │
│                             │
│  ConversationalAIController │   1. Start() called when Play hit
│         │                   │
│         ▼                   │
│  ProviderFactory            │   2. CreateLLMProvider(LiveKit)
│         │                   │      → CreateLiveKitProvider()
│         ▼                   │
│  LiveKitLlmProvider         │   3. .Initialize(config) — no-op, reads Inspector fields
│   .ConnectAsync()           │   4. .ConnectAsync() begins
└──────┬──────────────────────┘
       │
       │  5. POST http://3.227.63.49:8001/token
       │     Headers: X-API-Key: 9a11fdf5...
       │     Body: {"room": "<guid>", "identity": "xr-<guid>", "agent_name": "sophia-agent"}
       ▼
┌─────────────────────────────┐
│  EC2 sophia-token-mint-1    │
│  (FastAPI + livekit-api)    │   6. Validates X-API-Key
│                             │   7. Mints JWT signed with LIVEKIT_API_SECRET
│                             │      Token grants: roomJoin + canPublish + canSubscribe
│                             │      RoomConfiguration.agents = [{agentName: "sophia-agent"}]
│                             │   8. Returns 200 OK + {"token": "...", "serverUrl": "..."}
└──────┬──────────────────────┘
       │
       │  9. ws://3.227.63.49:7880 (signaling)
       │     + UDP 50000-60000 (media) / TCP 7881 (fallback)
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  EC2 sophia-livekit-server-1  (LiveKit SFU)                         │
│                                                                     │
│  10. Mac participant joins room=<guid> as "xr-<guid>"               │
│  11. ICE candidate gathering → DTLS handshake → UDP connection      │
│  12. SFU sees RoomConfig.agents → triggers job dispatch             │
│  13. Sends job to registered worker (sophia-agent, AW_souB3RfU3mXz) │
└────┬────────────────────────────────────────────────────────────────┘
     │
     │  14. Worker accepts job → opens its OWN Room.Connect to SFU
     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  EC2 sophia-agent-worker-1  (Python livekit-agents framework)       │
│                                                                     │
│  15. Joins same room as "agent-AJ_AEBd84m8of6k" (identity prefix    │
│      "agent-" matches Mac client's Q58 filter)                      │
│  16. Subscribes to xr-<guid>'s mic track                            │
│  17. Publishes its own audio track (TTS output channel)             │
└────┬────────────────────────────────────────────────────────────────┘
     │
     │  Two-way WebRTC audio + signaling now established
     │
     │  Mac publishes mic track:
     │   MicrophoneStreamer (16 kHz mono PCM via XREAL device heuristic)
     │   → OnAudioChunk(base64) event
     │   → MicrophoneStreamerAudioSource (RtcAudioSource custom subclass)
     │   → naive 3x upsample (16k → 48k) + base64 decode + int16 → float
     │   → AudioRead.Invoke(buffer, 1, 48000) → FFI CaptureAudioFrame
     │   → SDK packs into Opus → WebRTC PEER stream → SFU
     │   → SFU forwards to agent worker
     │
     │  Agent publishes TTS track:
     │   livekit.plugins.openai.tts (Kokoro adapter) streams PCM frames
     │   → SDK packs into Opus → WebRTC stream → SFU
     │   → SFU forwards to Mac
     │   → Mac's LiveKitLlmProvider.OnTrackSubscribed (filtered by "agent-" prefix)
     │   → New child GameObject "SophiaSpeaker_<sid>" with AudioSource + AudioStream
     │   → SDK plays audio via Unity AudioSource → AudioListener → Mac speakers
     │
     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Agent worker: per-turn pipeline                                    │
│                                                                     │
│  Turn boundary detection (Silero VAD + MultilingualModel)           │
│                                                                     │
│  STT: livekit.plugins.openai.STT(base_url=http://localhost:8080)    │
│   18. Mic audio buffered → POST /v1/audio/transcriptions            │
│       to Whisper Large v3 on EKS (via kubectl port-forward)         │
│   19. Returns transcript text                                       │
│                                                                     │
│  RAG hook (Assistant.on_user_turn_completed):                       │
│   20. POST http://localhost:8106/retrieve to sophia-spatial-ai      │
│   21. If max_score >= 0.30: injects chunks as system message        │
│   22. Publishes payload to text-stream topic "sophia.rag_result"    │
│                                                                     │
│  LLM: livekit.plugins.openai.LLM(base_url=http://localhost:18080)   │
│   23. Sends chat-completions request with full chat_ctx + tools     │
│       to Qwen3-VL-8B-Instruct on EKS                                │
│   24. Streams response tokens back                                  │
│                                                                     │
│  TTS: livekit.plugins.openai.TTS(base_url=http://localhost:8122)    │
│   25. Streams response sentences → POST /v1/audio/speech            │
│       to Kokoro-82M on EKS, voice="serena"                          │
│   26. Returns audio frames (raw WAV)                                │
│   27. Frames published to agent's audio track (see above)           │
│                                                                     │
│  Event publishes (throughout the turn):                             │
│   28. send_text to "sophia.agent_events" — kind=user_transcript,    │
│       kind=agent_state, kind=user_state, kind=metrics, etc.         │
│   29. send_text to "lk.transcription" (framework default) — deltas  │
│       and final agent transcribed text                              │
└────┬────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│  Mac client receives:       │
│                             │
│  - Audio plays through Mac speakers (LiveKit's auto AudioSource)
│  - "sophia.agent_events" → LiveKitLlmProvider.OnAgentEventsMessage
│      → fires OnTranscriptReceived(User), OnAgentSpeaking,
│        OnUserSpeaking, OnError events
│      → ConversationalAIController routes to HUD signals
│  - "sophia.rag_result" → LiveKitLlmProvider.OnRagResultMessage
│      → currently logs only (RAG chip rendering can be added later)
│  - "lk.transcription" → LiveKitLlmProvider.OnTranscriptionMessage
│      → fires OnTranscriptReceived(Agent) with segments
│  - HUD updates in real time via existing controller events            │
└─────────────────────────────┘
       │
       │  30. User stops Play (or hits Stop button)
       ▼
       OnDestroy → LiveKitLlmProvider.DisconnectAsync()
                  → Room.Disconnect()
                  → SFU sees LEAVE → closes session → "job ended"
```

**Timing reference for Phase 1 MVP** (cross-region EKS adds ~70 ms per inference call):
- Token mint POST: ~50 ms
- Room.Connect handshake: ~200-500 ms (ICE + DTLS)
- Mic uplink first frame: < 100 ms after Connect
- First TTS audio byte after user finishes speaking: ~1.5-3 s
  - Mac → SFU → agent worker (WebRTC): ~50 ms
  - Whisper STT (cross-region EKS): ~500-800 ms
  - Qwen3 LLM time-to-first-token (cross-region): ~400-700 ms
  - Kokoro TTS time-to-first-byte: ~200-400 ms
  - Agent → SFU → Mac (WebRTC): ~50 ms

### A.3 Same flow Phase 3 (production AWS, after infra migration)

Code unchanged. Only Inspector fields change:

| Inspector field | Phase 1 (today) | Phase 3 (production) |
|---|---|---|
| `_liveKitUrl` | `ws://3.227.63.49:7880` | `wss://sfu.sophia.example.com` |
| `_tokenEndpoint` | `http://3.227.63.49:8001/token` | `https://api.sophia.example.com/token` |
| `_tokenApiKey` | `9a11fdf5...` (rotate before prod) | new key from AWS Secrets Manager (rotated regularly) |
| `_agentName` | `sophia-agent` | `sophia-agent` (unchanged) |
| Player Settings → HTTP allow | Always allowed | Not allowed (TLS in front, can revert) |

What infra team's production deployment changes on the backend (per `HANDOFF.md`):
- SFU: k8s `livekit-server` Deployment with Redis cluster for HA, exposed via LoadBalancer Service + TLS termination at ALB.
- Token-mint: k8s `sophia-token-mint` Deployment with HPA, exposed via Ingress + TLS.
- Agent workers: k8s `sophia-agent-worker` Deployment with HPA on concurrent-job count.
- Inference services (Whisper, Qwen3, Kokoro): same EKS pods, same region as the SFU + workers (no more cross-region port-forward — RPC over VPC-internal). Latency drops ~70 ms per call.
- Secrets: AWS Secrets Manager + External Secrets Operator → no more `.env.production` files.
- Monitoring: CloudWatch + Prometheus + Grafana, LiveKit's egress for session recording if needed.
- DNS: Route 53 with real hostnames.
- Auth: real authentication on token-mint replaces the X-API-Key shared secret (Cognito / Auth0 / Clerk depending on product decision).

The Mac client's voice flow is BIT-IDENTICAL to Phase 1 — just travels over TLS instead of plain TCP/UDP. The Inspector URL change is the only client-side delta.

---

## Path B: XREAL One Pro + Beam Pro (Android wearable, production hardware)

### B.1 What the user does

Pre-conditions (one-time):
1. Build APK from the same Unity project (Build Profiles → Android → Build).
2. Sign APK (development build OK for testing; release signature needed for production distribution).
3. Beam Pro device available, Android dev mode enabled.
4. XREAL One Pro glasses with USB-C tether cable.

Per-session actions:
1. **Connect XREAL One Pro to Beam Pro** via USB-C tether (USB Audio Class + DisplayLink modes auto-activate; AR display routes to glasses temples, audio I/O routes to glasses speakers + boom mic).
2. **Install APK** on Beam Pro:
   ```
   adb install -r '/path/to/sophia-wearable.apk'
   adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
   ```
3. **Grant microphone permission** on first launch (Android system prompt).
4. **App opens; voice loop starts automatically** (or via UI session start, depending on his entry-point implementation).
5. **Speak into the XREAL boom mic** (5 cm from mouth, NOT the phone mic in pocket).
6. **Listen via XREAL temple speakers** (audio routes there via USB Audio Class).
7. **Watch HUD on glasses temple displays** showing caption text + RAG source chips + state indicator.
8. **End session** via UI button or just close the app.

For dev/debug:
- `adb logcat -v time | grep -E '\[Sophia|LiveKit|Unity|0604'` to watch our `[DEBUG_0604_LiveKit]` tags in real time.
- Scrcpy mirror to see Beam Pro screen on Mac for screenshots.

### B.2 End-to-end flow on XREAL + Beam Pro (today's Phase 1 MVP)

The data flow is **identical to Path A's section A.2 from steps 5 onward** (token POST, SFU connection, agent dispatch, mic/audio publishing, inference pipeline, audio playback). The differences are purely on the client side:

**B.2.1 Where audio comes IN (mic)**:

```
┌──────────────────────────────────────────┐
│  XREAL One Pro (boom mic, ~5cm from      │
│  user's mouth, near-field voice quality) │
└────┬─────────────────────────────────────┘
     │ USB-C tether (USB Audio Class)
     ▼
┌──────────────────────────────────────────┐
│  Beam Pro Android — Sophia APK            │
│                                          │
│  MicrophoneStreamer.cs                   │
│   - Microphone.Start(device=XREAL boom)  │
│     via FindXREALMicrophoneDevice()      │
│     heuristic (keyword match xreal/nreal)│
│   - AndroidAudioSessionHelper            │
│     .ConfigureForInputDevice() —         │
│     VOICE_COMMUNICATION audio mode +     │
│     hardware AEC enabled                 │
│   - 16 kHz mono PCM 16-bit capture       │
│   - 1024 samples per chunk (~64 ms)      │
│   - base64-encode → fires OnAudioChunk   │
│                                          │
│  MicrophoneStreamerAudioSource (our      │
│  adapter) subscribes to OnAudioChunk:    │
│   - decode base64 → int16                │
│   - upsample 3x (16k → 48k)              │
│   - convert to float [-1, 1]             │
│   - AudioRead.Invoke(buffer, 1, 48000)   │
│   → LiveKit FFI CaptureAudioFrame        │
└────┬─────────────────────────────────────┘
     │ WebRTC over UDP/cellular or Wi-Fi
     ▼
   (same as Path A from token POST onwards)
```

**B.2.2 Where audio comes OUT (speakers)**:

```
   (same as Path A — agent worker's TTS frames
    flow through SFU back to client)

     │
     ▼
┌──────────────────────────────────────────┐
│  Beam Pro Android — Sophia APK            │
│                                          │
│  LiveKitLlmProvider.OnTrackSubscribed:   │
│   - Filter participant.Identity          │
│     .StartsWith("agent-") — only agent's │
│     audio gets played (Q58 fix avoids    │
│     hearing other users' raw mic)        │
│   - Create child GameObject              │
│     SophiaSpeaker_<sid> under speakerHost│
│   - Add AudioSource + AudioStream        │
│   - SDK plays audio via Unity AudioSource│
└────┬─────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────┐
│  Android system audio routing            │
│   - System detects USB Audio Class       │
│     device (XREAL glasses) connected     │
│   - Routes Sophia's TTS audio to glasses │
│     temple speakers (NOT phone speaker)  │
│   - Phone speaker stays silent           │
└────┬─────────────────────────────────────┘
     │ USB-C tether
     ▼
┌──────────────────────────────────────────┐
│  XREAL One Pro temple speakers           │
│   - Audio plays at user's temples        │
│   - Geometry: speakers point INWARD      │
│     toward ears, NOT toward boom mic     │
│   - Boom mic → temple speaker leak is    │
│     minimal due to physical separation   │
│     → echo is geometrically suppressed   │
│     even without active AEC              │
└──────────────────────────────────────────┘
```

**B.2.3 Where the AR HUD displays**:

```
┌──────────────────────────────────────────┐
│  Sophia app's HUD rendering              │
│   - World-space Canvas (his app)         │
│   - Updates via signals fired from       │
│     ConversationalAIController on        │
│     OnTranscriptReceived events          │
│   - Rendering targets:                   │
│     * Beam Pro screen (phone UI mode)    │
│     * XREAL One Pro display via XR rig   │
│       (stereo rendering on temple LCDs)  │
└────┬─────────────────────────────────────┘
     │ USB-C DisplayLink mode
     ▼
┌──────────────────────────────────────────┐
│  XREAL One Pro temple displays (color    │
│  LCDs) — user sees:                      │
│   - State dot indicating speaking /       │
│     listening / thinking                 │
│   - Subtitle text (user's question +     │
│     Sophia's response captions)          │
│   - RAG source chips (e.g., "MANUAL-23   │
│     p.14" when retrieval returns hits)   │
└──────────────────────────────────────────┘
```

**B.2.4 Network path differences from Mac Editor flow**:

- **Cellular link**: NAT traversal via ICE/STUN, sometimes TURN if behind restrictive carrier NAT. Total round-trip latency to EC2 typically 50-150 ms.
- **Wi-Fi link**: Similar to Mac dev path; ~30-80 ms RTT depending on AP.
- **WebRTC handles both transparently** — no app-side change needed for cellular vs Wi-Fi.
- **LiveKit's Opus codec at low bitrate (~32 kbps)** means a 4G link is more than sufficient for voice quality.

### B.3 Same flow Phase 3 (production AWS, after infra migration)

XREAL + Beam Pro path picks up the SAME Phase 3 Inspector changes as Path A (TLS URLs). The on-device experience is identical to Phase 1 — same XREAL hardware, same audio routing, same HUD — but with TLS + production-grade backend reliability.

Notable production benefits for the wearable specifically:
- Real autoscaling on the SFU — large-scale events / multi-user XR rooms supported without re-architecting.
- Production-grade observability for triaging field issues (CloudWatch + correlation IDs in spans).
- Possible LiveKit Egress for session recording (compliance / training data).
- Eventual real authentication (Cognito / Auth0 / Clerk) — replaces the shared X-API-Key, supports per-user permissions.

---

## Component reference (what each piece does in the voice flow)

### Client-side (Unity, runs in Editor or Android APK)

**`MicrophoneStreamer.cs`** (XR engineer's existing code, 757 lines) — owns the device microphone.
- Calls Unity's `Microphone.Start(device, true, 1, 16000)`.
- Picks device via heuristic: prefer XREAL/Nreal devices over phone mic.
- On Android: calls `AndroidAudioSessionHelper.ConfigureForInputDevice()` to set VOICE_COMMUNICATION mode + hardware AEC.
- Emits `OnAudioChunk(base64)` event every 64 ms (1024 samples at 16 kHz).
- Also emits `OnMicChunkRmsForClientVad(rms, ...)` for any client-side VAD service.

**`MicrophoneStreamerAudioSource.cs`** (our new adapter, 118 lines) — bridges his mic into LiveKit.
- Subclasses `RtcAudioSource` with `AudioSourceCustom` type.
- Subscribes to `MicrophoneStreamer.OnAudioChunk` (using `-= then +=` pattern to coexist with controller's existing subscription).
- Decodes base64 → int16 → upsamples 3x to 48 kHz → converts to float [-1, 1].
- Calls `AudioRead.Invoke(buffer, 1, 48000)` to push frames into LiveKit FFI.

**`LiveKitLlmProvider.cs`** (our new provider, ~570 lines) — implements his `ILLMProvider` against LiveKit SDK v1.3.7.
- `Initialize(ProviderConfig _)` — logs init values; v1 reads Inspector fields not the config arg.
- `ConnectAsync` — POSTs token-mint with X-API-Key, builds Room, hooks events, calls `Room.Connect`, publishes mic track via `MicrophoneStreamerAudioSource`, registers three text-stream handlers.
- `OnTrackSubscribed` — Q58 filter on `participant.Identity.StartsWith("agent-")`, creates child `SophiaSpeaker_<sid>` GameObject for each agent audio track.
- Three text-stream handlers map LiveKit events to `ILLMProvider` events (OnTranscriptReceived, OnAgentSpeaking, OnUserSpeaking, OnError).
- `IsConnected` returns true while SDK is in `Reconnecting` state to absorb transient blips (Q6 pattern).
- `DisconnectAsync` — fire-and-forget from OnDestroy; cleans up speakers + room.

**`ConversationalAIController.cs`** (XR engineer's existing code, 1635 lines) — voice loop orchestrator.
- On `Start`: calls `ProviderFactory.CreateLLMProvider(activeConversationProvider.ToConversationProviderType())` → our `CreateLiveKitProvider()` → constructs `LiveKitLlmProvider`.
- Subscribes to the provider's 6 events (OnAudioReceived, OnTranscriptReceived, OnFunctionCall, OnError, OnUserSpeaking, OnAgentSpeaking) and routes them to HUD signals / scene UI.
- `OnMicrophoneAudioChunk(base64)` — has type-sniff branches: OpenAI fast-path, OUR NEW LiveKit no-op bypass, default base64-decode + SendAudioChunkAsync (for VoiceRelay, etc.).
- `UpdateLlmConnectionResilience` (every frame) — checks `IsConnected`, fires reconnect coroutine after 1.5s grace. Our provider's IsConnected-stays-true-during-reconnect pattern absorbs SDK transient blips.

**`ProviderFactory.cs`** (XR engineer's existing code, 234 lines) — switches enum value to MonoBehaviour.
- `CreateLLMProvider(ConversationProviderType)` switch has a new case for LiveKit → `CreateLiveKitProvider()`.
- `CreateLiveKitProvider()` calls `FindFirstObjectByType<LiveKitLlmProvider>()`; if not found, creates GameObject + AddComponent.

### Backend on EC2 (today's Phase 1 MVP)

**`sophia-livekit-server-1` container** — LiveKit SFU (Go binary, Docker image `livekit/livekit-server`).
- Host networking mode (needed for WebRTC UDP candidate exposure).
- Configured via `infra/livekit.prod.yaml` (mounted from host) — keys, port range, node-ip.
- Bind: TCP 7880 (signaling), TCP 7881 (TURN fallback), UDP 50000-60000 (media).
- Internal agent dispatcher: receives jobs from rooms with `RoomConfig.agents = [{agentName: "..."}]`, assigns to registered workers.

**`sophia-token-mint-1` container** — FastAPI app (Python).
- Port-mapped 8001:8001.
- Routes: `POST /token` (mint JWT with optional RoomConfig.agents), `GET /health`.
- X-API-Key middleware checks the SOPHIA_TOKEN_API_KEY env var on every request.
- Uses `livekit-api` Python lib for AccessToken builder + signing.

**`sophia-agent-worker-1` container** — Python livekit-agents framework + sophia-agent custom code.
- Host networking mode (so `localhost:7880` reaches SFU loopback inside the container; SFU is also on host net).
- `LIVEKIT_URL=ws://localhost:7880` env override (forces worker to bypass public IP and use the SFU loopback).
- Worker registration: connects to SFU, advertises `agentName="sophia-agent"`, becomes eligible for job dispatch.
- Per-job: spins up a fresh `AgentSession` with STT + LLM + TTS plugins configured to talk to localhost ports (8080/18080/8122 — forwarded via kubectl port-forward to EKS).

### Inference services on EKS (cross-region us-west-2, accessed via kubectl port-forward FROM EC2)

- **whisper-inference** at `localhost:8080` (port-forwarded to `spatial-ai-staging` EKS service) — OpenAI-compatible Whisper Large v3 STT.
- **qwen3-inference** at `localhost:18080` — OpenAI-compatible Qwen3-VL-8B-Instruct LLM (text mode for voice; vision wired up but unused in voice path today).
- **kokoro-tts** at `localhost:8122` — OpenAI-compatible Kokoro-82M TTS, voice `serena` (af_heart, female warm tone).
- **sophia-spatial-ai** at `localhost:8106` — RAG retrieval (vector store of equipment manual chunks). Hit on every user turn via `Assistant.on_user_turn_completed` always-retrieve hook.

The `infra/pf-gpu.sh start` script (run on EC2) starts the port-forwards. STS credentials must be exported in EC2's shell first (~1 hour validity). Without these port-forwards running, the agent worker can't reach inference services and the voice loop fails at STT (this is what blocked the full smoke test on 2026-06-05 — the connection between client and SFU and agent worker all functioned, only STT to Whisper failed).

---

## Step-by-step reference: a single conversation turn (Phase 1 MVP)

Sequence diagram in text form. `[t]` is approximate ms elapsed since user started speaking.

```
[t=0]      User starts speaking into Mac mic / XREAL boom mic
[t=0-N]    Microphone capture in 64 ms chunks (1024 samples @ 16 kHz)
           Each chunk:
               16 kHz int16 → MicrophoneStreamer.OnAudioChunk(base64)
               → MicrophoneStreamerAudioSource (3x upsample + base64 decode + float)
               → RtcAudioSource → FFI CaptureAudioFrame
               → SDK encodes Opus → WebRTC SRTP packet → SFU
               → SFU forwards to agent worker
[t≈300ms]  Silero VAD on agent worker detects speech start
[t≈800ms]  User stops speaking
[t≈1200ms] MultilingualModel turn-detector decides end-of-utterance
[t≈1250ms] Agent worker forwards accumulated mic audio to Whisper STT
           via POST localhost:8080/v1/audio/transcriptions
[t≈1900ms] STT returns transcript text
[t≈1910ms] Assistant.on_user_turn_completed hook fires:
           - POST localhost:8106/retrieve with user query
           - sophia-spatial-ai returns chunks + max_score
           - If max_score >= 0.30: chunks injected as system message
           - publish RAG result to "sophia.rag_result" topic
[t≈2150ms] LLM call: POST localhost:18080/v1/chat/completions
           with chat_ctx.messages[] (system + retrieved chunks + history + user turn)
[t≈2550ms] Qwen3 returns first response token
[t≈2570ms] LiveKit framework starts TTS as LLM tokens arrive (streaming)
           - First sentence sent to Kokoro: POST localhost:8122/v1/audio/speech
[t≈2950ms] Kokoro returns first audio bytes (WAV)
[t≈2960ms] Agent worker publishes audio bytes onto its track
           → SDK encodes Opus → WebRTC → SFU → Mac/Beam Pro
[t≈3010ms] Mac/Beam Pro receives first audio frame via OnTrackSubscribed
           → child SophiaSpeaker_<sid> GameObject's AudioSource starts playing
           → user HEARS Sophia start responding
[t≈3010ms - ...] Audio continues streaming until Sophia finishes
[t≈3050ms] "sophia.agent_events" kind=user_transcript published → Mac fires
           OnTranscriptReceived(User) → HUD shows user caption
[t≈3100ms] "sophia.agent_events" kind=agent_state new=speaking published → 
           Mac fires OnAgentSpeaking(true) → HUD pill animates speaking
[t≈3050ms - end] "lk.transcription" streams Sophia's delta tokens → Mac fires
           OnTranscriptReceived(Agent, IsComplete=false) for each delta →
           HUD agent caption fades in token-by-token
[t=end]    Sophia finishes; "sophia.agent_events" kind=agent_state new=listening
           → OnAgentSpeaking(false) → HUD pill fades back to listening color
```

**Key user-perceived latency**: "press enter" → "first byte of Sophia's response audio plays in your ear" ≈ **3 seconds in Phase 1 MVP** (cross-region EKS adds ~70 ms per inference call; first-token-streaming TTS hides most of the LLM latency). Phase 3 production with same-region inference should drop this to ~2 seconds.

---

## How the user knows it's working (verification cheat-sheet)

### Unity Editor console — successful start

```
[DEBUG_0604_LiveKit] Initialize: liveKitUrl='ws://3.227.63.49:7880' tokenEndpoint='http://3.227.63.49:8001/token' agentName='sophia-agent'
[DEBUG_0604_LiveKit] ConnectAsync completed.
[DEBUG_0604_LiveKit] mic uplink published.
[DEBUG_0604_LiveKit] ParticipantConnected: agent-AJ_<...>
[DEBUG_0604_LiveKit] agent audio track subscribed sid=TR_<...> identity=agent-AJ_<...>
```

### Android adb logcat — successful start (filter: `adb logcat -v time | grep -E '\[Sophia|0604_LiveKit'`)

Same `[DEBUG_0604_LiveKit]` tags will appear, plus Android-specific Sophia tags from his other modules (MicrophoneStreamer, ConversationalAIController, etc.).

### EC2 SFU log — successful connection

```
livekit-server-1 | INFO starting RTC session, participant=xr-<guid>, room=<guid>,
                 |   client SDK=UNITY, version=1.3.7
livekit-server-1 | INFO agents: assigned job to worker, jobID=AJ_<...>, workerID=AW_<...>
livekit-server-1 | INFO starting RTC session, participant=agent-AJ_<...>, client SDK=PYTHON
livekit-server-1 | INFO mediaTrack published, participant=xr-<guid>, kind=audio, source=MICROPHONE
livekit-server-1 | INFO mediaTrack published, participant=agent-AJ_<...>, kind=audio, source=MICROPHONE
livekit-server-1 | INFO participant active, connectionType=udp
```

### EC2 agent-worker log — full voice loop (when port-forward running)

```
agent-worker-1 | INFO received job request, job_id=AJ_<...>, agent_name=sophia-agent
agent-worker-1 | INFO process initialized
agent-worker-1 | INFO injected N rag chunks (max_score=0.<...>) for "<user question>"
agent-worker-1 | (no "Connection error" warnings — STT succeeds)
```

### Failure modes

| Symptom | Likely cause | Look at |
|---|---|---|
| No `[DEBUG_0604_LiveKit]` in console | LiveKit not actually selected at runtime — bundle override or missing converter case | `ProviderConfig.asset` → check `customizedEndpointsBundle: {fileID: 0}` and `activeConversationProvider: 5` |
| `Insecure connection not allowed` | Unity 6 HTTP block | Player Settings → Allow downloads over HTTP → Always allowed |
| Token POST 401 | X-API-Key mismatch | Verify Inspector `_tokenApiKey` matches EC2's `SOPHIA_TOKEN_API_KEY` env var |
| SFU log shows no Mac participant | Network reachability blocked | curl `http://3.227.63.49:8001/health` from Mac — verify SG inbound rules |
| SFU log shows participant but no agent dispatch | Agent worker not registered, or wrong agent_name in RoomConfig | Check `docker compose ps` and SFU agents log |
| Agent registered but `Connection error` on STT | EKS port-forward not running | SSH EC2, start `./infra/pf-gpu.sh start` |
| Audio plays but garbled / robotic | Sample rate mismatch | Likely a regression on MicrophoneStreamerAudioSource upsample logic — verify 3x sample triplication still correct |
| Echo loop (Sophia hears herself) | Glasses not connected (audio falls back to Beam Pro speaker → mic) | Connect XREAL One Pro via USB-C tether so audio routes to temple speakers |
| HUD shows no captions | Text-stream handler registration failed, or controller didn't subscribe to OnTranscriptReceived | Check Unity console for `RegisterTextStreamHandler` errors |

---

## What changes Phase 1 → Phase 3 visually

### Sequence diagram diff

```
┌────────────────────────────────────────┐
│  PHASE 1 (today) — EC2 MVP             │
│                                        │
│  Client → http://3.227.63.49:8001      │  (insecure, public IP)
│  Client → ws://3.227.63.49:7880        │  (insecure, public IP)
│  Worker → http://localhost:8080        │  (kubectl port-forward to EKS, cross-region)
│  Worker → http://localhost:18080       │  (~70 ms RTT to us-west-2)
│  Worker → http://localhost:8122        │
│  Worker → http://localhost:8106        │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│  PHASE 3 (production) — AWS native     │
│                                        │
│  Client → https://api.sophia.ex.com    │  (TLS, real DNS)
│  Client → wss://sfu.sophia.ex.com      │  (TLS, real DNS)
│  Worker → http://whisper.svc.cluster.local:8080    │  (VPC-internal RPC)
│  Worker → http://qwen3.svc.cluster.local:18080     │  (~5 ms RTT, same region)
│  Worker → http://kokoro.svc.cluster.local:8122     │
│  Worker → http://spatial-ai.svc.cluster.local:8106 │
└────────────────────────────────────────┘
```

### Client-side delta to migrate from Phase 1 to Phase 3

1. Update Inspector fields on LiveKitLlmProvider GameObject (3 string changes).
2. Optional: revert Player Settings → Allow downloads over HTTP back to "Not allowed".
3. Rebuild APK if shipping to wearables.

That's it for the client side. **No code change** — the provider-abstraction pattern means infra migration is a config swap, not a refactor.

### Backend delta (infra team's work per HANDOFF.md)

1. Replace docker-compose on EC2 with k8s Deployments + Services + Ingresses.
2. Put TLS in front (ALB / Ingress + cert-manager + Let's Encrypt or ACM).
3. Replace shared X-API-Key with real authentication.
4. Co-locate inference pods with SFU/workers (same region) — eliminates port-forward + cross-region latency.
5. Add HPA on SFU + workers.
6. Wire observability + on-call runbooks.

---

## Cross-references

- `livekit_integration_sophia_wearable.md` — the build view (how the integration was coded, file by file).
- `livekit_architectur_ec2.md` — current EC2 backend architecture in detail.
- `HANDOFF.md` (root) — infra team's onboarding for Phase 3 production deployment.
- `Sophia_Xreal-U2.md` — architecture survey of his entire Unity client.
- `project_complete_doubts.md` — running Q&A log with Q1-Q32 covering the full project journey.
- `livekit_doubts.md` — older Q&A log specifically for LiveKit framework / debugging Q&A (Q1-Q62).
- `mvp_deployment_shared_ec2.md` — operational runbook for EC2 (cold-start, warm-start, runtime checks).
