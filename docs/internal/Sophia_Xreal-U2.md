# Sophia_Xreal-U2.md — architecture deep dive of the XR engineer's Unity client

How the existing production Unity wearable client at `Sophia_Xreal-U2/` is structured, what each module does, how voice/audio flows today, and where LiveKit integration plugs in. This doc is the canonical reference for understanding the codebase before we write a single line of integration code.

Audience: anyone working on Phase 1 (LiveKit provider integration into Sophia_Xreal-U2 against our EC2 backend), or returning months later to understand what's there.

Sibling docs:
- `livekit_architectur_ec2.md` — how OUR backend (EC2 services) works end-to-end. Read in tandem.
- `xr_build_voice_integration.md` — generic integration guide for any XR build.
- `project_complete_doubts.md` Q13–Q15 — the integration strategy + phase plan.

---

## What we have locally (LFS status clarification)

You asked: "we cloned the repo but left lfs pull — is that the only thing missing for the complete clone?"

Yes, that's right. The clone command we ran was:

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone git@github.com:AIPartnersUSA/Sophia_Xreal-U2.git
```

What we HAVE (real files):
- All `.cs` source code (this is the interesting stuff for our integration).
- All `.md` documentation (extensive — see `docs/`).
- All `.json` / `.asset` / `.txt` config files.
- All `.meta` files (Unity GUID tracking, needed for the project to load correctly in Editor).
- The `.git/` directory and full git history.

What we have as POINTER FILES (3-line text blobs that look like `version https://git-lfs.github.com/spec/v1\noid sha256:...\nsize ...`):
- All binary assets the engineer tagged with LFS in `.gitattributes`: textures, audio assets, prefabs that contain binary data, models, animation clips, etc.
- These live primarily under `Assets/_Audio/`, `Assets/_Visuals/`, `Assets/_Art/`, `Assets/Samples/`, scene prefabs in `Assets/_Scenes/Misc/`.

**For our research goal** (understanding the architecture + writing the LiveKit provider integration), we DO NOT need the LFS binaries. Source code + docs + config is enough.

**If the XR engineer needs to actually OPEN the project in Unity Editor** to run/test it, he'd need `git lfs pull` to materialize the binaries. The Unity project will fail to load several scenes/prefabs without them. But that's HIS workflow, not ours — we're reading code.

If we ever want to build the Unity project ourselves (test our LiveKit provider end-to-end in his app), we'd run `git lfs pull` then. Today, skipped.

---

## Top-level repo structure

```
Sophia_Xreal-U2/
├── README.md                      ← API handoff index for AWS team
├── .gitattributes                 ← LFS patterns for binary assets
├── .gitignore                     ← Unity-specific excludes
├── .cursor/                       ← Cursor IDE rules + skills (he uses Cursor for AI-augmented dev)
├── Sophia_Wearable/               ← THE PRODUCTION UNITY CLIENT (focus of this doc)
├── Sophia_UnityServer/            ← Optional local test server for AWS parity
├── AWS_References/                ← API contracts + handoff docs to AWS team
├── Planning_References/           ← Planning + architecture notes
├── Test_Data/                     ← Latency benchmarks, recordings (May 2026 trials)
├── docs/                          ← Comprehensive documentation tree
│   ├── architecture/              ← Architecture overview docs
│   ├── docs_client/               ← Wearable client API docs (5 handoffs to AWS)
│   ├── docs_unityserver/          ← Unity test server docs
│   ├── guides/, reference/, overview/, contributing/, support/
│   ├── AI_Agent_Handoffs/         ← Inter-session handoff docs
│   ├── AI_Context/                ← Context for AI dev sessions
│   ├── ProductManuals/            ← Product domain documentation
│   ├── GitHubReferenceDocs/       ← CHANGELOG.md lives here
│   └── archive/, AI_Docs_Archive/
├── tools/                         ← PDF processor, integration automation
└── Packages/                      ← Local UPM packages (com.sophia.productserver)
```

The doc tree is heavy because they're maintaining tight API contracts with AWS team for the gateway routes. README.md at the root indexes 5 distinct integration docs:

1. Conversational AI (OpenAI Realtime gateway, tools, session JSON)
2. Product database (catalog, metadata, packages)
3. Google Vision via gateway
4. Whisper / transcription
5. Self-hosted voice relay (STT → LLM → TTS WebSocket)

Most relevant to our integration is #5, since their VoiceRelay path is the closest architectural cousin to what we're adding via LiveKit.

---

## The Unity project — Sophia_Wearable/

This is the production app deployed to XREAL One Pro + Beam Pro Android.

### Unity version + key dependencies

- **Unity 6** (exact: `6000.3.12f1`). Same major as our `sophia-glasses/`.
- **URP (Universal Render Pipeline)** for rendering.
- **AR Foundation 6.3.3** + ARCore + ARKit + XR Hands + XRI 3.3.1 + OpenXR 1.14.0 — mature AR stack.
- **XREAL SDK** via UPM (`com.xreal.xr` as `file:com.xreal.xr` — vendored locally).
- **Netcode for GameObjects 2.11.0** — multiplayer infrastructure already in place.
- **Convai's OpenAI Unity package** (`com.convai.openai` from a GitHub URL).
- **NativeWebSocket** (`com.endel.nativewebsocket` from GitHub) — their WebSocket layer for non-WebRTC providers.
- **Newtonsoft.Json 3.2.2** — JSON serialization.
- **Sophia Product Server** — their custom local UPM package.

### Top-level Assets/ organization

```
Sophia_Wearable/Assets/
├── _Scripts/                    ← All their C# (focus of this doc)
│   ├── Modules/                 ← Module-per-concern (Audio, ConversationalAI, HUD, PhoneUI, ...)
│   ├── Core/                    ← Global app state, diagnostics, signals
│   ├── BuildSettings/           ← AR session bootstrap, platform-specific setup
│   ├── Editor/                  ← Editor windows (Provider Config Manager, etc.)
│   ├── Logs/                    ← Runtime logging (PlaySession.log capture)
│   └── Common/, Modules/        ← Shared utilities
├── _Scenes/
│   ├── Sophia_Wearables.unity   ← MAIN ENTRY POINT (the one scene at runtime)
│   └── Misc/                    ← Test scenes (PhoneWebCamTest, RGBTest, etc.)
├── _Audio/, _Visuals/, _Art/    ← Binary assets (LFS pointers in our clone)
├── ARFoundationPackage/, XR*, XRI/  ← AR + XR plugins
├── Scenes/, Settings/, Resources/, Plugins/  ← Standard Unity organization
├── XrealUltra2/                 ← XREAL-specific assets + configs
└── ProjectSettings/             ← Build target, audio, XR provider config
```

The `_Scripts/Modules/` directory is where everything important lives. It's organized as one folder per concern with its own assembly definition (`.asmdef`), which gives them clean module boundaries — module A can only depend on module B if its asmdef explicitly references it.

---

## The Modules/ map (what each module does)

| Module | Role | Key files (what to read first) |
|---|---|---|
| **`ConversationalAI/`** | Voice agent orchestration. Provider abstraction (LLM/Audio/Vision/Tools), 4 provider implementations, conversation lifecycle. | `Core/ConversationalAIController.cs`, `Abstractions/ILLMProvider.cs`, `Providers/{OpenAI,VoiceRelay,Gemini,GoogleVision}/`, `Core/ProviderFactory.cs` |
| **`Audio/`** | Mic capture + PCM playback. Resamples to 16 kHz mono for STT, plays back TTS audio at 16/24 kHz. | `Common/MicrophoneStreamer.cs`, `Common/PcmAudioPlayer.cs`, `Core/AudioController.cs` |
| **`Networking/`** | WebSocket + HTTP gateway. Abstracts NativeWebSocket as `IRealtimeWebSocketSession`. Bootstrap fetches gateway client-config at app launch. | `RealtimeWebSocketPump.cs`, `HttpGateway.cs`, `GatewayRuntimeBootstrapService.cs`, `NetworkingController.cs` |
| **`ProviderConfiguration/`** | Runtime config schema. Selects which provider via enum. Bundled vs customized endpoint modes. | `ProviderConfig.cs`, `SingleEndpointAwsBundle.cs`, `EndpointConfigurationBundles.cs` |
| **`PhoneUI/`** | UGUI control panel on the Beam Pro screen. Provider selector, transcripts, audio output mode toggle. | `PhoneUIAudioOutputModeController.cs` and many sibling controllers (30 subdirs) |
| **`HUD/`** | World-space AR HUD. Voice captions, agent state indicators, visual feedback. Consumes `ILLMProvider` events. | Speaker indicators + transcript display components |
| **`SpatialAI/`** | Tool registry orchestrator. Auto-discovers spatial tool handlers and registers with the active LLM provider. | `LLMSpatialAPIGateway.cs`, `VisualFidelityRealtimeToolHandlers.cs` |
| **`CameraOperations/`** | XREAL RGB camera + phone camera capture. Image-based vision provider input. | `PhoneCameraManager.cs`, AR camera management |
| **`Camereon/`** | XREAL eye camera (RGB module). Image capture pipeline. | Camera-specific to XREAL hardware |
| **`HandControls/`** | Hand-tracking input. XR Hands integration for gesture commands. | XRI hand-input bindings |
| **`HUD/` (capital)** | Distinct from world-space `Hud/` inside ConversationalAI. Top-level wearable HUD. | Visual feedback prefabs + controllers |
| **`VirtualProduct/`** | Spawned 3D product models, manipulation, animation. Driven by spatial AI tool calls. | Product manipulation + state management |
| **`VisualWorkspace/`** | Spatial product display, hand interaction, gesture recognition. Persists across sessions (per UserSessions). | Workspace persistence + interaction |
| **`UserSessions/`** | Per-user session DB. Tracks identity, conversation history, saved images. | `UserSessionController.cs`, `UserAndSessionsDatabase.cs` |
| **`ProductPreparation/`** | Product loading + preparation pipeline. Catalog → in-scene rendering. | Catalog → mesh import |
| **`Scenarios/`** | Application scenarios (warehouse, retail, training, etc.). | Scenario controllers |
| **`Debug/` + `DebugSystem/`** | In-app debug UI + runtime diagnostics. | Debug overlays + tooling |
| **`ImageMasking/`** | Image segmentation pipeline. Used in vision flows. | Bridge to image processing |
| **`PartAnimator/`** | Per-part product animation (explosion, assembly, etc.). | Animation state machine |
| **`ArMovementTuning/`** | AR session calibration tools. | Editor + runtime calibration |
| **`AndroidPurePhoneOverlay/`** | Phone-only overlay UI (when glasses not present). | Phone overlay pattern |

Most of these modules are unaffected by our LiveKit integration — they consume `ILLMProvider` events through the provider abstraction. We touch only `ConversationalAI/`, optionally `Audio/`, and possibly add a new `LiveKitConfig` entry to `ProviderConfiguration/`.

---

## The provider abstraction — the architectural insight that matters most

This is what makes the LiveKit integration clean. Three sibling interfaces in `Modules/ConversationalAI/Abstractions/`:

- **`ILLMProvider`** — the conversational AI provider. WHAT we're implementing.
- **`IAudioProvider`** — separate audio provider abstraction (some providers split audio off).
- **`IVisionProvider`** — image-input provider.
- **`IToolRegistry`** — registry for function-call tools.

The KEY contract is `ILLMProvider`. Verbatim from `ILLMProvider.cs`:

```csharp
public interface ILLMProvider
{
    string ProviderName { get; }
    bool IsConnected { get; }

    Task ConnectAsync();
    Task DisconnectAsync();

    Task SendAudioChunkAsync(byte[] audioData);
    Task SendImageAsync(string imageDataUrl, string overlayImageDataUrl = null);
    Task SendTextAsync(string text);

    event EventHandler<AudioReceivedEventArgs> OnAudioReceived;
    event EventHandler<TranscriptReceivedEventArgs> OnTranscriptReceived;
    event EventHandler<FunctionCallEventArgs> OnFunctionCall;
    event EventHandler<ErrorEventArgs> OnError;
    event EventHandler<bool> OnUserSpeaking;
    event EventHandler<bool> OnAgentSpeaking;
}
```

The 6 events are the surface area his entire UI / HUD / orchestration layer consumes. Any provider (ours included) that fires these events correctly slots in transparently.

The event-arg shapes are also load-bearing:

```csharp
public class AudioReceivedEventArgs : EventArgs
{
    public byte[] AudioData { get; set; }
    public string Format { get; set; }       // e.g., "pcm16", "opus"
    public int SampleRate { get; set; }
}

public class TranscriptReceivedEventArgs : EventArgs
{
    public string Text { get; set; }
    public TranscriptType Type { get; set; } // User or Agent
    public bool IsComplete { get; set; }     // true = final, false = delta/partial
    public string RelayPhase { get; set; }   // v1.1: "delta" / "final" / null
    public bool RelayCommit { get; set; }    // v1.1: true on final assistant line
}

public class FunctionCallEventArgs : EventArgs
{
    public string CallId { get; set; }
    public string FunctionName { get; set; }
    public JObject Arguments { get; set; }
}

public class ErrorEventArgs : EventArgs
{
    public string ErrorCode { get; set; }
    public string ErrorMessage { get; set; }
    public Exception Exception { get; set; }
    public string ErrorStage { get; set; }   // v1.1: "stt" / "llm" / "transport"
    public string ErrorSubcode { get; set; } // v1.1: "timeout" / "refused"
    public string ErrorDetail { get; set; }  // v1.1: target_url + status combined
}
```

The `RelayPhase` / `RelayCommit` / `ErrorStage` / `ErrorSubcode` / `ErrorDetail` fields are voice-relay v1.1 observability extensions. For our LiveKit provider we map:
- `RelayPhase` = "delta" while the LLM is streaming tokens, "final" on the last chunk.
- `RelayCommit` = true once the TTS audio for the turn completes.
- `ErrorStage` = "transport" for WS/WebRTC connection issues, "stt"/"llm"/"tts" if we can disambiguate.

---

## The four existing providers

Sibling implementations of `ILLMProvider` (and sometimes `IVisionProvider`, `IAudioProvider`) live under `Modules/ConversationalAI/Providers/`:

### 1. OpenAI (`Providers/OpenAI/OpenAIProvider.cs`, ~650 lines)

OpenAI's Realtime API over WebSocket. Implements `ILLMProvider` + `IVisionProvider` + `IAudioProvider`. Composes:

- `OpenAIAudioHandler` — wires PCM mic chunks ↔ Realtime audio events; wires response audio_delta → `PcmAudioPlayer`.
- `OpenAITranscriptHandler` — handles delta/final transcript events.
- `OpenAIToolCallHandler` — function-call dispatch.
- `OpenAIVisionHandler` — image submission.
- `IRealtimeWebSocketSession` (from Networking) — WS lifecycle.

Key state: `_ws`, `_sessionReady`, `_responseActive`, `_agentCurrentlySpeaking`. Has interrupt-grace-period logic so brief silences don't trigger cancellation.

This is the most feature-complete provider. Best canonical template for LiveKit if we want max fidelity.

### 2. VoiceRelay (`Providers/VoiceRelay/VoiceRelayLlmProvider.cs`, ~2000 lines)

Their custom self-hosted STT → LLM → TTS WebSocket protocol. Implements `ILLMProvider` (audio + transcript only — no vision). Architectural details from the docs:

- Connects to `wss://<host>/ws` (gateway-routed in production).
- Sends `{type: "config", voice, system_prompt, sophia_relevance_threshold, sophia_retrieve_timeout_sec}` once at session start.
- Streams 16 kHz PCM16 mono mic chunks as `{type: "audio", data: <base64>}`.
- Receives `{type: "transcript"}`, `{type: "audio"}` (24 kHz TTS PCM), `{type: "audio_end"}`, `{type: "error"}` from server.
- Sends `{type: "interrupt"}` on first mic chunk while agent is speaking (barge-in).
- Has full v1.1 observability: `_sessionTraceparent`, `_lastRxSessionCorrelationId`, `_lastRxTurnId`, `_wireV11Observability`.
- Diagnostic trace tags: `[DEBUG_0423_VoiceRelay]`, `[DEBUG_2904_VoiceRelay]`, `[DEBUG_0605_VoiceRelayLegs]`, `[DEBUG_0605_VoiceRelayXray]` — per-leg latency timings (stt_complete, rag_complete, llm_first_token, tts_first_byte, end_to_end_ms).

This provider is the SHAPE-WISE closest analog to a LiveKit provider — same lifecycle (connect, stream audio, receive audio, disconnect), same event surface, similar telemetry hooks. Most useful template.

### 3. Gemini (`Providers/Gemini/`)

Google's Gemini Live API. Implements `ILLMProvider` + `IVisionProvider`. WebSocket-based, similar lifecycle to OpenAI Realtime.

### 4. GoogleVision (`Providers/GoogleVision/`)

Vision-only provider for bounding boxes. Implements `IVisionProvider`. HTTP (not WebSocket) — annotate proxy through gateway.

Not relevant for our LiveKit work directly but explains why the abstraction is split into LLM/Audio/Vision (some providers are vision-only).

---

## Audio pipeline (the most important non-provider code path)

How audio flows in their app today, regardless of which provider is selected:

### Mic capture: `MicrophoneStreamer.cs` (~757 lines in `Modules/Audio/Common/`)

- Uses Unity's `Microphone` API.
- Default 16 kHz output, 1024 samples per chunk (~64 ms).
- Downsamples (linear interpolation) from native mic rate to 16 kHz.
- Encodes as 16-bit signed little-endian PCM, packed to `byte[]`, then base64 for WSS transport.
- Device selection heuristic — picks XREAL glasses mic over phone mic if available (keyword match: "xreal" / "nreal" / "usb").
- Requests Android `RECORD_AUDIO` permission async via coroutine (non-blocking — start streaming once granted).
- Emits `OnMicChunkRmsForClientVad(rms, realtime, chunkDuration)` for any external VAD client (OpenAI server-side VAD, custom heuristic).
- Throttles `MaxChunksPerFrame` (default 6, drops to 4 during video recording) to avoid main-thread spikes.

### Audio playback: `PcmAudioPlayer.cs` (~250 lines)

- Maintains a FIFO `Queue<AudioClip>` for incoming TTS PCM.
- Creates `AudioClip` instances at 16 kHz (or whatever sample rate the provider sends).
- Drains one clip per Update() if not currently playing.
- **Dual-output**: primary `AudioSource` (phone speaker) + optional `xrealAudioSource` (glasses speaker via Audio Mixer group routing). The output mode is toggled at runtime via `PhoneUIAudioOutputModeController`.
- Fires `OnClipStarted` event — used by AR session recording to capture device audio.

### How VoiceRelay wires mic + playback (template for our LiveKit provider)

```
MicrophoneStreamer.OnAudioChunk(base64 PCM)
    → VoiceRelayLlmProvider.SendAudioChunkAsync()
    → _ws.SendMessageAsync({"type":"audio","data":"<base64>"})

_ws.OnMessage receives {"type":"audio","data":"<base64 TTS PCM>"}
    → decode base64 → byte[]
    → fire OnAudioReceived(AudioReceivedEventArgs{AudioData, Format="pcm16", SampleRate=24000})
    → Audio module's listener calls PcmAudioPlayer.QueueAudioClip()
    → AudioSource plays via the dual-output routing
```

For LiveKit, we replace the WS portion with LiveKit Unity SDK's `Room.LocalParticipant.PublishTrack` for uplink and `Room.OnTrackSubscribed` for downlink. The provider's `OnAudioReceived` event still fires the same `AudioReceivedEventArgs` shape so `PcmAudioPlayer` works unchanged.

Important detail: LiveKit's audio flows through its own `AudioSource` (created on the child GameObject per agent track per Q58). We may or may not want to route LiveKit's audio THROUGH `PcmAudioPlayer` to get the dual-output routing his app expects. Two options:

A. Let LiveKit's own AudioSource play the agent's TTS directly (skip `PcmAudioPlayer`). Lose dual-output routing.

B. Tap LiveKit's audio stream, decode the frames, push into `PcmAudioPlayer.QueueAudioClip()` to keep dual-output. More code, preserves UX consistency with other providers.

Option B is more correct for parity but Option A is simpler for v1. Plan to start with A, upgrade to B if dual-output is required for his demo flow.

---

## Networking layer

Modules/Networking/ abstracts WS + HTTP through clean interfaces:

- **`IRealtimeWebSocketSession`** — the WS contract: `OnOpen`, `OnMessage`, `OnError`, `OnClose`, `ConnectAsync`, `SendMessageAsync`, `IsConnected`.
- **`RealtimeWebSocketPump.cs`** — concrete WS implementation wrapping NativeWebSocket.
- **`HttpGateway.cs`** — `UnityWebRequest` wrapper for HTTPS (GET client-config, POST vision, etc.).
- **`GatewayRuntimeBootstrapService.cs`** — at app launch, hits the gateway's client-config endpoint to fetch runtime config (model name, protocol version, observability flags, voice WebSocket path, etc.).
- **`RealtimeGateway.cs`** — HTTP gateway client for single-endpoint AWS mode.
- **`NetworkingController.cs`** — MonoBehaviour that hosts both HTTP + WS factories as a singleton.

LiveKit doesn't go through this layer at the protocol level — the LiveKit Unity SDK has its own WS + WebRTC stack. But our provider might still use `HttpGateway` for the initial token-mint POST (to keep network code consistent with rest of the app) — or it can use a plain `UnityWebRequest`. Style decision; either works.

---

## Configuration system

Modules/ProviderConfiguration/ implements a layered config system:

- **`ProviderConfig.cs`** — the master enum-driven config object. Top-level enums:
  - `EndpointConfigurationMode` — bundled vs customized endpoints.
  - `SingleEndpointBackendType` — Sophia, Local-Unity-Server, etc.
  - `AwsSingleEndpointConversationPipeline` — OpenAI Realtime, Voice Relay, etc. (this is the field we'd add `LiveKit` to).
  - Sub-configs for vision providers, TTS voice settings, etc.
- **`SophiaSingleEndpointProviderConfigFile.cs`** — origin URL + bearer token for AWS gateway bootstrap.
- **`SingleEndpointAwsBundle.cs`** + **`SingleEndpointLocalUnityBundle.cs`** — bundled configs for staging/prod environments.
- **`EndpointConfigurationBundles.cs`** — factory for selecting a bundle at runtime.

Editor UI for editing this is in `Assets/_Scripts/Modules/Editor/SophiaClient/ProviderConfigurationManagerWindow.cs`. Cmd-Shift-P-ish: opens a custom Unity Editor window for editing all config knobs.

For our LiveKit provider, we'd:
1. Add a new value to `AwsSingleEndpointConversationPipeline` enum: `LiveKitSelfHosted` (or similar).
2. Add a `LiveKitConfig` sub-object to `ProviderConfig` with `liveKitUrl`, `tokenEndpoint`, `tokenApiKey`, `agentName`.
3. Extend `ProviderFactory` to instantiate `LiveKitLlmProvider` when the enum is set to LiveKit.

---

## Bootstrap flow (how the app starts)

From the Explore agent's findings, traced through `Sophia_Wearables.unity` + `AndroidPureArSessionBootstrap` + `ConversationalAIController`:

```
1. Android process launches → Unity initializes
2. Sophia_Wearables.unity scene loads
3. AndroidPureArSessionBootstrap.OnAwake [DefaultExecutionOrder -200]
   - Request AR permissions (CAMERA, RECORD_AUDIO)
   - Init AR Foundation (ARSession, ARRaycastManager)
4. GatewayRuntimeBootstrapService.OnStart [static singleton]
   - HTTPS GET /gateway/sophia-speech/client-config
     (or fallback per ProviderConfig)
   - Parse JSON, cache GatewayClientConfig
   - Set IsReady=true (unlocks provider connect)
5. ConversationalAIController.OnStart
   - Resolve dependencies: ProviderFactory, ProviderConfig,
     ConversationToolService, MicrophoneStreamer, etc.
   - If startOnAwake=true: StartConversation()
6. StartConversation() → ProviderFactory.CreateLLMProvider(type)
   - Switch on ConversationProviderType enum
   - Instantiate provider MonoBehaviour (or find existing)
   - Call provider.Initialize(config)
   - Call provider.ConnectAsync()
7. Provider.ConnectAsync()
   - OpenAI: WS to OpenAI/gateway; session.created + system prompt
   - VoiceRelay: WS to voiceRelayWebSocketUrl; send config JSON
   - Gemini: WS to Gemini Live API
8. Provider connected:
   - LLMSpatialAPIGateway.RegisterToolsWithProvider() — auto-discover handlers
   - MicrophoneStreamer.StartStreaming()
   - PhoneUI + HUD ready to display
```

For LiveKit, step 7 becomes:

```
7'. LiveKitLlmProvider.ConnectAsync()
    - POST liveKitConfig.tokenEndpoint with X-API-Key header
    - Get back JWT + serverUrl
    - LiveKit Unity SDK Room.Connect(serverUrl, jwt)
    - Wait for OnConnected → IsConnected=true
    - Hook Room.OnTrackSubscribed (filter agent-* identity per Q58)
    - Hook Room.OnDataReceived (LiveKit text-stream topics)
    - Publish mic via Room.LocalParticipant.PublishTrack(micTrack)
```

Step 8 stays unchanged — the tool registration + mic streaming work the same way regardless of provider.

---

## Scene + entry point details

**`Assets/_Scenes/Sophia_Wearables.unity`** is the single runtime scene. Conceptual hierarchy (from the agent's reconstruction):

```
Sophia_Wearables.unity
├── [AndroidPureArSessionBootstrap]     ← AR + permission init
├── [NetworkingController]              ← HTTP + WS singleton
├── [AudioController]                   ← MicrophoneStreamer + PcmAudioPlayer host
├── [ConversationalAIController]        ← Master orchestrator
│   ├── [ProviderFactory]               ← Spawns ILLMProvider instances
│   ├── [ConversationProviderController]
│   ├── [ConversationToolService]
│   └── [MicrophoneStreamer (ref)]
├── [ProviderConfiguration UI]
├── [PhoneUI Canvas]                    ← UGUI control panel
├── [HUD Canvas]                        ← UGUI captions, feedback
├── [SpatialAI / LLMSpatialAPIGateway]  ← Tool handler discovery
├── [VirtualProductManager]
├── [UserSessionController]
├── [AR Camera Stack]                   ← Base + URP overlay cameras
└── [XR Origin (XREAL device tracking)]
```

Multiple Canvases (URP overlay camera stack). The HUD canvas + PhoneUI canvas are separate so the phone display + glasses display can render different content.

---

## ProjectSettings highlights

| Setting | Value | Why |
|---|---|---|
| Player → Resolution | Fullscreen, Portrait, XREAL-optimized | AR Foundation handles orientation; XR display routing handles glasses |
| Player → Android Target SDK | 34+ | Required for Beam Pro Android |
| Player → Android Min SDK | 24 | Broad device support |
| XR backend | OpenXR + XREAL plugin enabled | Standard XR rendering pipeline |
| Audio System Sample Rate | 48 kHz speaker, 16 kHz mic DSP | Matches OpenAI Realtime + downsampler in MicrophoneStreamer |
| Graphics | URP, Forward renderer, 2x MSAA | XREAL glasses performance target |

For LiveKit we may need to bump audio settings — LiveKit uses Opus at 48 kHz internally. Their app's 48 kHz output + 16 kHz DSP for mic should be compatible; verify during testing.

---

## Where LiveKit integration plugs in (recap from Q13–Q15)

1. **New file**: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs` — implements `ILLMProvider`, internally uses LiveKit Unity SDK.

2. **Add to `Packages/manifest.json`**: LiveKit Unity SDK reference (recommended: vendor our `client-sdk-unity/` via Git LFS at the same level we did for `sophia-glasses/`).

3. **Extend `ProviderConfig`**: new enum value + `LiveKitConfig` sub-block with `liveKitUrl`, `tokenEndpoint`, `tokenApiKey`, `agentName`.

4. **Extend `ProviderFactory`**: new switch arm returns `LiveKitLlmProvider` when the enum says LiveKit.

5. **Optional extend `EndpointConfigurationBundles`**: add a "Sophia LiveKit MVP (EC2)" bundle with our 3.227.63.49 values baked in for easy dev switching.

6. **No changes**: scene, mic capture (LiveKit's `MicrophoneSource` opens its own; we can route OUR `MicrophoneStreamer` into LiveKit later if we want shared mic state), HUD, PhoneUI, SpatialAI, ProjectSettings, AR setup, Netcode.

---

## Critical files to read directly before coding the provider

Ranked by the Explore agent for deepest architectural understanding:

1. **`Modules/ConversationalAI/Core/ConversationalAIController.cs`** (~370 lines) — master orchestrator; shows event flow provider → HUD → PhoneUI, reconnect logic, audio-first caption policy, VAD heuristics. Entry point for understanding cross-module wiring.

2. **`Modules/ConversationalAI/Providers/OpenAI/OpenAIProvider.cs`** (~650 lines) — canonical `ILLMProvider` implementation. Shows WS lifecycle, session setup, audio/transcript/tool event handling, queue mode for interrupted speech, interrupt grace period.

3. **`Modules/ConversationalAI/Providers/VoiceRelay/VoiceRelayLlmProvider.cs`** (~2000 lines) — closest analog to what we're writing. Mic uplink chunking, TTS PCM downlink, v1.1 observability, E2E latency tracking.

4. **`Modules/Audio/Common/MicrophoneStreamer.cs`** (~757 lines) — mic capture, downsampling, chunking, base64 encoding, device switching, VAD probe. Critical to know if we want to use LiveKit's `MicrophoneSource` OR feed his `MicrophoneStreamer` into LiveKit's track API.

5. **`Modules/ConversationalAI/Core/ProviderFactory.cs`** (~233 lines) — factory pattern, enum → provider class mapping. The exact code we extend to add LiveKit.

---

## Existing observability + telemetry patterns (we should mirror)

He has structured per-leg latency telemetry in VoiceRelay with debug trace tags:

- `[DEBUG_0605_VoiceRelayLegs]` emits per-leg timings: `stt_complete`, `rag_complete`, `llm_first_token`, `tts_first_byte`, summary `stt_latency_ms`, `llm_ttft_ms`, `tts_ttfb_ms`, `end_to_end_ms`, gaps between milestones.
- `[DEBUG_0423_VoiceRelay]` emits RX/TX events, correlation IDs, traceparent, errors.
- `[DEBUG_0605_VoiceRelayXray]` emits AWS X-Ray spans if AWS adds `xray`/`spans` on the wire.

For our LiveKit provider, mirror this with `[DEBUG_LiveKit]` and `[DEBUG_LiveKitLegs]` prefixes. Map LiveKit Agents framework's metrics (it emits `metrics` events on AgentSession) to the same `*_ms` fields. Makes A/B comparison with VoiceRelay trivially log-greppable.

---

## Open questions to clarify with the XR engineer before integration

These are technical decisions we need his input on:

1. **Mic ownership**: should LiveKit's `MicrophoneSource` open the mic directly (simpler), OR should his `MicrophoneStreamer` continue to own the mic and feed audio into a LiveKit `LocalAudioTrack` (preserves his device-selection heuristic for XREAL vs phone mic)?

2. **Audio playback**: should LiveKit's auto-attached `AudioSource` play TTS directly (simpler), OR route LiveKit audio frames through his `PcmAudioPlayer` (preserves his dual-output routing for phone+glasses)?

3. **Vision flow**: his existing providers support `SendImageAsync()` for AR vision. Our `sophia-agent` agent-worker doesn't have a vision path wired yet. Options: (a) implement vision in `LiveKitLlmProvider.SendImageAsync` by sending images via LiveKit's data channel to the agent, then wire vision-RAG via sophia-spatial-ai; (b) leave vision NOT supported in LiveKit provider for v1, fall back to GoogleVision provider for vision queries.

4. **Tool registry**: his SpatialAI module auto-registers tools with the connected provider. Does the LiveKit Agents framework on our backend support tool calling? (Yes — `livekit-agents` has function tool support, but our current `agent.py` doesn't wire any tools.) Plan for v1: don't expose tools through LiveKit provider; fall back to OpenAI/VoiceRelay if tool calls are needed.

5. **VAD coordination**: client-side VAD probe (`OnMicChunkRmsForClientVad`) is consumed by OpenAI's server-side VAD opt-out logic. LiveKit Agents framework runs Silero VAD server-side. Do we suppress client-side VAD for LiveKit provider, or keep it for telemetry?

6. **Reconnect policy**: VoiceRelay handles WS reconnects with exponential backoff. LiveKit Unity SDK has its own reconnect logic. Two reconnect layers — verify they don't conflict.

7. **Branch + PR strategy**: branch in HIS repo named `feat/livekit-provider` off `development`, PR back to `development` when stable? Or fork-then-PR? (His preference.)

---

## Cross-references

- `livekit_architectur_ec2.md` — backend architecture our LiveKit provider connects to. Read in tandem with this doc.
- `xr_build_voice_integration.md` — generic XR integration guide. Sections on Drop-in vs Custom path are superseded by Q13's "Provider-plugin path" for this specific codebase.
- `project_complete_doubts.md` Q13–Q15 — the strategy + phase plan + key technical decisions.
- `mvp_deployment_shared_ec2.md` — operational reference for the EC2 backend his provider will hit.
- His own docs (in his repo): `docs/architecture/overview.md`, `docs/docs_client/WEARABLE_VOICE_RELAY_CLIENT_API.md`, `docs/GitHubReferenceDocs/CHANGELOG.md`.

---

## When to update this doc

- After reading the 5 critical files end-to-end — replace any "from the agent's reconstruction" notes with verbatim observations.
- After kicking off Phase 1 — capture the actual `LiveKitLlmProvider.cs` path + interface conformance details.
- After his answers to the 7 open questions — pin down decisions.
- After any new module gets added to his codebase (rare but possible).
- When his Unity version bumps significantly (currently 6000.3.12f1; future LTS or Unity 7 would need re-verification).
- When the LiveKit Unity SDK gets a major version bump that changes our integration patterns.

---

## Short status summary

We have his codebase locally (text + source + docs + config; LFS binaries intentionally skipped). We understand:
- It's Unity 6 with mature AR Foundation + XR Foundation setup, XREAL SDK, Netcode for GameObjects.
- Sophia_Wearable is the production XR client; single scene `Sophia_Wearables.unity` boots everything.
- Module-per-concern under `Modules/` with asmdef boundaries.
- Voice agent orchestration via `ILLMProvider` interface; 4 existing providers (OpenAI Realtime, Gemini Live, custom VoiceRelay WSS, GoogleVision HTTP).
- Audio pipeline: `MicrophoneStreamer` → provider → `PcmAudioPlayer` (dual-output).
- Tool registry, networking, config, UI — all separated into their own modules.

We can write the `LiveKitLlmProvider.cs` cleanly as a new sibling in `Providers/LiveKit/`. Estimated 1-1.5 days for Phase 1 integration per Q15. The 5 ranked files above + the 7 open questions are the next research milestone before coding.
