# Conversational AI Architecture — XR Engineer's Wearable Product

Everything you need to understand the conversational AI subsystem of the XR engineer's production Unity wearable client (`Sophia_Wearable/`). Written so a future engineer (you in 3 months, a new hire, or the XR engineer himself if he forgets a corner) can modify or extend the conversation layer without spelunking the whole codebase.

**Scope**: only the conversational AI subsystem — voice agent orchestration, providers, transcripts, audio I/O routing, tool/RAG integration, HUD wiring. AR foundation, scene management, virtual product manipulation, hand tracking, etc. are out of scope.

**Audience**: anyone who wants to modify the voice agent, add a new provider, change audio routing, add a new tool, tweak transcripts/HUD behavior, or add chat history.

---

## 1. What this module is responsible for

Take a user's voice (mic input) → run it through STT + LLM + TTS (via a configurable backend) → produce voice output + transcripts + tool calls + UI events. Hide the backend choice behind a clean abstraction so the rest of his app doesn't care which provider is active.

**The module owns**:
- Voice loop orchestration (start session, run turns, handle interrupts/barge-in, reconnect, stop session).
- Provider abstraction (the `ILLMProvider` interface — see §3).
- Provider implementations (OpenAI Realtime, VoiceRelay, Gemini, GoogleVision, LiveKit — see §5).
- Mic capture (via the separate `Audio/` module) and audio playback (via `PcmAudioPlayer`).
- Event surface: state changes, transcripts, function calls, errors → consumed by HUD + PhoneUI.
- Configuration system (Provider Configuration Manager Editor window + ScriptableObject assets).

**What it does NOT own** (kept in other modules):
- AR Foundation + XR rig setup (`Modules/CameraOperations`, BuildSettings, ProjectSettings).
- Hand tracking + gesture input (`Modules/HandControls`).
- Virtual product manipulation (`Modules/VirtualProduct`, `Modules/VisualWorkspace`).
- Spatial AI tool implementations (`Modules/SpatialAI` — registers tools WITH the conversation layer via `LLMSpatialAPIGateway`).
- Scene management (`Modules/Scenarios`, `Modules/ProductPreparation`).
- User session lifecycle (`Modules/UserSessions`).

---

## 2. Top-level folder map

```
Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/
├── Sophia.ConversationalAI.asmdef       ← assembly definition (we added "LiveKit" to references)
│
├── Abstractions/
│   ├── ILLMProvider.cs                  ← THE main interface — 6 events + 6 methods
│   ├── ILLMProvider.cs.meta
│   ├── IAudioProvider.cs                ← lighter audio-only interface (some providers split this off)
│   ├── IVisionProvider.cs               ← image input + bounding box / segmentation contracts
│   └── IToolRegistry.cs                 ← tool registration + dispatch contract
│
├── Core/
│   ├── ConversationalAIController.cs    ← MAIN ORCHESTRATOR (1635 lines)
│   ├── ConversationProviderController.cs ← Provider selection + lifecycle wrapper
│   ├── ConversationToolService.cs        ← Tool registry implementation
│   ├── ProviderFactory.cs                ← Enum → Provider MonoBehaviour factory
│   ├── ClientSideVadService.cs           ← Client-side RMS VAD (for barge-in heuristic)
│   ├── STSLatencyDiagnostics.cs          ← Per-leg timing telemetry
│   ├── ConversationExitParticipant.cs    ← Clean-shutdown hook into app lifecycle
│   └── (a few support classes for state machines, log prefixes, etc.)
│
├── Providers/
│   ├── OpenAI/
│   │   ├── OpenAIProvider.cs            ← OpenAI Realtime over WebSocket (2753 lines)
│   │   ├── OpenAIAudioHandler.cs
│   │   ├── OpenAITranscriptHandler.cs
│   │   ├── OpenAIToolCallHandler.cs
│   │   ├── OpenAIVisionHandler.cs
│   │   ├── OpenAIErrorHandler.cs
│   │   └── OpenAISessionConfigBuilder.cs
│   ├── VoiceRelay/
│   │   └── VoiceRelayLlmProvider.cs     ← Custom WSS voice relay (879 lines)
│   ├── Gemini/
│   │   └── GeminiProvider.cs            ← Gemini Live API
│   ├── GoogleVision/
│   │   └── GoogleVisionProvider.cs      ← Vision-only HTTP fallback
│   └── LiveKit/                         ← WE ADDED THIS
│       ├── LiveKitLlmProvider.cs        ← LiveKit Unity SDK provider (~570 lines)
│       └── MicrophoneStreamerAudioSource.cs ← Mic adapter (RtcAudioSource subclass)
│
├── UI/
│   └── ProviderStatusUI.cs              ← Runtime status overlay (provider name, state)
│
└── Hud/
    └── ConversationalAiHudService.cs    ← Bridge to world-space HUD (subtitles, RAG chips, state pill)
```

**Related modules that touch the conversation system** (live alongside but in their own folders):

```
Sophia_Wearable/Assets/_Scripts/Modules/

├── ProviderConfiguration/
│   ├── ProviderConfig.cs                ← THE config ScriptableObject + 12 enums + converter extensions
│   └── EndpointConfigurationBundles.cs  ← CustomizedEndpointsBundle ScriptableObject + its mapper
│
├── Audio/
│   ├── Common/
│   │   ├── MicrophoneStreamer.cs        ← Mic capture (757 lines, XREAL device-selection heuristic)
│   │   └── PcmAudioPlayer.cs            ← TTS audio playback with dual-output routing
│   └── Core/
│       ├── AudioController.cs           ← Hosts mic + playback singletons
│       └── AudioModel.cs                ← Runtime audio state
│
├── Networking/
│   ├── NetworkingController.cs          ← Singleton factory for WS + HTTP
│   ├── RealtimeWebSocketPump.cs         ← NativeWebSocket pump driving WS protocol
│   ├── HttpGateway.cs                   ← UnityWebRequest wrapper
│   ├── GatewayRuntimeBootstrapService.cs ← Bootstrap GET /gateway/sophia-speech/client-config
│   ├── IRealtimeWebSocketSession.cs     ← WS lifecycle abstraction
│   ├── RealtimeGateway.cs               ← HTTP gateway client for single-endpoint AWS mode
│   └── VoiceRelayObservabilityState.cs  ← Per-leg timing for VoiceRelay traceparent
│
├── SpatialAI/
│   ├── LLMSpatialAPIGateway.cs          ← Auto-discovers spatial tool handlers, registers with active provider
│   └── VisualFidelityRealtimeToolHandlers.cs ← Tools the LLM can call: spawn product, pin image, etc.
│
└── CameraOperations/                    ← Camera image capture for vision input
    ├── PhoneCameraManager.cs
    └── (other camera scripts)
```

**Configuration assets in Resources/**:

```
Sophia_Wearable/Assets/Resources/ProviderConfigurations/
├── ProviderConfig.asset                  ← THE main config ScriptableObject instance (the one his app loads at runtime via Resources.Load)
├── OpenAIConfig.asset                    ← OpenAI key + model name
├── OpenAISettings.asset
├── GoogleVisionSettings.asset
├── EndpointBundles/
│   ├── CustomizedEndpoints_Template.asset
│   ├── SingleEndpoint_Aws_Default.asset
│   └── SingleEndpoint_LocalUnity_Default.asset
└── ProviderConfigFiles/
    ├── OpenAIProviderConfig.asset
    ├── GeminiProviderConfig.asset
    ├── WhisperProviderConfig.asset
    ├── GoogleVisionProviderConfig.asset
    ├── AzureVisionProviderConfig.asset
    ├── SophiaCloudDatabaseProviderConfig.asset
    ├── SophiaSingleEndpointProviderConfig.asset
    ├── SophiaTranscriptionProviderConfig.asset
    ├── LocalProductDataProviderConfig.asset
    ├── MockProductDataProviderConfig.asset
    └── UnityLocalServerProductDataProviderConfig.asset
```

**Editor windows** (custom Unity Editor UI for managing the configuration):

```
Sophia_Wearable/Assets/_Scripts/Editor/SophiaClient/
├── ProviderConfigurationEditorWindow.cs ← THE Provider Configuration Manager window (menu: SophiaClient/Tools/Provider Configuration Manager)
├── ProviderConfigSerializedUi.cs        ← Helper that draws the mode-aware fields
└── ProviderConfigSyncUtility.cs         ← Sync/link default provider config assets
```

---

## 3. The architecture — five layers from interface to UI

```
                       ┌─────────────────────────────────────────┐
                       │  Layer 5: HUD + Phone UI                │
                       │  (subscribes to controller events,      │
                       │   renders captions, state pill, chips)  │
                       └────────────────┬────────────────────────┘
                                        │ signal/event subscription
                       ┌────────────────┴────────────────────────┐
                       │  Layer 4: Orchestrator                  │
                       │  ConversationalAIController             │
                       │   - StartConversation / StopConversation│
                       │   - Provider type-sniff branches         │
                       │   - Reconnect coordinator (every Update)│
                       │   - Audio-first caption gating          │
                       │   - Routes provider events to UI signals│
                       └────────────────┬────────────────────────┘
                                        │ uses ILLMProvider interface
                       ┌────────────────┴────────────────────────┐
                       │  Layer 3: Provider abstraction          │
                       │  ILLMProvider + IVisionProvider +       │
                       │  IAudioProvider + IToolRegistry         │
                       │   - 6 events (OnAudio, OnTranscript,    │
                       │     OnFunctionCall, OnError,            │
                       │     OnUserSpeaking, OnAgentSpeaking)    │
                       │   - 6 methods (ProviderName,            │
                       │     IsConnected, ConnectAsync,          │
                       │     DisconnectAsync, SendAudioChunkAsync,│
                       │     SendImageAsync, SendTextAsync)      │
                       └────────────────┬────────────────────────┘
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
   ┌──────────┴───────┐    ┌────────────┴────────┐    ┌───────────┴───────┐
   │ Layer 2: Provider impls (5 concrete LLM)    │    │   Adjacent:        │
   │                                              │    │   IToolRegistry   │
   │ OpenAIProvider     LiveKitLlmProvider       │    │   IVisionProvider │
   │ VoiceRelayLlm...   GeminiProvider           │    │                    │
   │ GoogleVision (vision-only)                   │    │   Tools registered │
   │                                              │    │   via SpatialAI    │
   └──────────┬───────────────────────────────────┘    │   gateway          │
              │                                         └────────────────────┘
              │ each provider talks to its own backend  
              │                                                                
   ┌──────────┴───────────────────────────────────────────────────────────┐
   │  Layer 1: Backends                                                    │
   │                                                                       │
   │  OpenAI Realtime  │  LiveKit SFU + Agents  │  AWS gateway / VoiceRelay│
   │  Gemini Live      │   (our EC2 today)      │  Google Vision API       │
   └───────────────────────────────────────────────────────────────────────┘
```

### Layer purposes — what each layer does and where

**Layer 1: Backends** (external services, NOT in his repo). Each provider talks to a different backend. LiveKit talks to our `sophia-agent` on EC2 → routes to EKS inference (Whisper / Qwen3 / Kokoro). OpenAI talks to `api.openai.com` directly. VoiceRelay talks to his AWS gateway (`staging.docu-mind.com`).

**Layer 2: Provider implementations** (one MonoBehaviour per backend). Each implements `ILLMProvider`. Provides a uniform event surface regardless of which backend it's wrapping.

**Layer 3: Provider abstraction** (4 interfaces). Defines the contract for what a provider must support. `ILLMProvider` is the main one — 6 events + 6 methods. `IToolRegistry` for tool registration. `IVisionProvider` for vision-only providers (e.g., GoogleVision). `IAudioProvider` for providers that split audio off from LLM.

**Layer 4: Orchestrator** (`ConversationalAIController` + a few helpers). Initializes the chosen provider via `ProviderFactory`, subscribes to its events, manages reconnect, audio-first caption gating, routes events to UI/HUD. One instance lives in the scene.

**Layer 5: UI** (HUD canvas + PhoneUI canvas). Subscribes to controller-fired signals (e.g., `AddUserMessageSignal`, `AddAIMessageSignal`, `HUDConnectionBannerSignal`). Renders captions, state pill, RAG source chips. Lives in `Modules/HUD` and `Modules/PhoneUI`.

---

## 4. The `ILLMProvider` contract — the central abstraction

Anyone implementing a new provider implements this interface (file: `Abstractions/ILLMProvider.cs`):

```csharp
public interface ILLMProvider
{
    string ProviderName { get; }                                    // for display + logging
    bool IsConnected { get; }                                       // for controller's reconnect logic

    Task ConnectAsync();                                            // open backend connection
    Task DisconnectAsync();                                         // clean shutdown
    Task SendAudioChunkAsync(byte[] audioData);                     // PCM mic frames (some providers no-op this if audio flows out-of-band)
    Task SendImageAsync(string imageDataUrl, string overlayImageDataUrl = null); // for vision-capable providers
    Task SendTextAsync(string text);                                // text-mode messages (chat history, retries, etc.)

    event EventHandler<AudioReceivedEventArgs> OnAudioReceived;     // TTS audio from backend
    event EventHandler<TranscriptReceivedEventArgs> OnTranscriptReceived; // user + agent transcripts
    event EventHandler<FunctionCallEventArgs> OnFunctionCall;       // backend wants to call a tool
    event EventHandler<ErrorEventArgs> OnError;                     // any error (with optional ErrorStage = "stt"/"llm"/"transport"/etc.)
    event EventHandler<bool> OnUserSpeaking;                        // VAD detected user start/stop
    event EventHandler<bool> OnAgentSpeaking;                       // backend agent start/stop talking
}
```

**Event args** (also in `Abstractions/ILLMProvider.cs`):

- `AudioReceivedEventArgs`: `{ AudioData (byte[]), Format ("pcm16" / "opus"), SampleRate (int) }`.
- `TranscriptReceivedEventArgs`: `{ Text, Type (User/Agent), IsComplete, RelayPhase (delta/final), RelayCommit }`. The last two are voice-relay v1.1 observability extensions; LiveKit ignores them.
- `FunctionCallEventArgs`: `{ CallId, FunctionName, Arguments (JObject) }`.
- `ErrorEventArgs`: `{ ErrorCode, ErrorMessage, Exception, ErrorStage (v1.1), ErrorSubcode (v1.1), ErrorDetail (v1.1) }`.

**When you implement a new provider, you must**:
1. Implement the interface (sealed `MonoBehaviour` + `ILLMProvider`).
2. Provide an `Initialize(ProviderConfig)` method (the factory calls this — not on the interface, but every provider has one).
3. Be discoverable by `FindFirstObjectByType<YourProvider>()` (factory pattern).
4. Fire events on the Unity main thread (controller is not thread-safety-aware for these).
5. Make `ConnectAsync` honor cancellation and not throw on already-connected.
6. Make `DisconnectAsync` swallow errors on already-disconnected.

---

## 5. The five providers — what each one does

### OpenAIProvider (2753 lines)
- Backend: `wss://api.openai.com/v1/realtime?model=...` (or his AWS gateway proxy).
- Implements `ILLMProvider` + `IVisionProvider` + `IAudioProvider`.
- 5 sub-handlers: `OpenAIAudioHandler`, `OpenAITranscriptHandler`, `OpenAIToolCallHandler`, `OpenAIVisionHandler`, `OpenAIErrorHandler` (split for readability of a once-monolithic class).
- Specialized fast-path: `SendAudioChunkBase64Async(string)` to avoid the controller's decode-re-encode round trip.
- VAD config + turn detection sent in `session.update` JSON; LLM + STT + TTS all happen server-side in OpenAI's realtime model.
- Function calls supported natively via `tools` field in session.update.
- Vision: `SendImageAsync` can route through `GoogleVisionProvider` as fallback (composite pattern) to convert images to Qwen3 text descriptions when OpenAI Realtime doesn't have native vision.

### VoiceRelayLlmProvider (879 lines)
- Backend: his AWS gateway voice relay endpoint over WSS (`wss://<host>/ws`).
- Implements `ILLMProvider` (audio + transcript only — no vision).
- Wire protocol: JSON messages with `type` field: `config`, `audio` (base64 PCM), `interrupt`, `transcript`, `audio_start`, `audio` (PCM down), `audio_end`, `session.updated`, `error`.
- 16 kHz PCM16 up, 24 kHz PCM16 down.
- `SendInterruptAsync` for barge-in (throttled 350 ms).
- Full v1.1 observability: traceparent header, correlation IDs, per-leg latency milestones (`[DEBUG_0605_VoiceRelayLegs]`).
- `SendImageAsync` is a no-op (matches what we did for LiveKit per Q23).
- Custom extension event `AssistantAudioPlaybackStarting` (not on interface) used by controller for caption gating.

### GeminiProvider
- Backend: Google's Gemini Live API.
- Implements `ILLMProvider` + `IVisionProvider`. WebSocket-based, multimodal.

### GoogleVisionProvider
- Backend: Google Vision API (HTTP, not WebSocket).
- Implements `IVisionProvider` only.
- Used as a fallback / composite — e.g., OpenAI Realtime's vision path can defer to this provider to extract image descriptions.

### LiveKitLlmProvider (~570 lines) — OUR ADDITION
- Backend: our self-hosted LiveKit SFU (`ws://3.227.63.49:7880`) + LiveKit Agents (`sophia-agent` worker on EC2) → EKS inference (Whisper/Qwen3/Kokoro).
- Implements `ILLMProvider`. Audio flows out-of-band via `MicrophoneStreamerAudioSource` (custom `RtcAudioSource` subclass).
- `SendAudioChunkAsync` is a no-op (audio doesn't go through this method).
- `SendImageAsync` is a no-op (matches VoiceRelay; can add composite-defer-to-GoogleVision later).
- Subscribes to three LiveKit text-stream topics: `sophia.agent_events`, `sophia.rag_result`, `lk.transcription`.
- Filters audio playback to agent participants only (Q58 fix).
- See `livekit_integration_sophia_wearable.md` for full integration details + design decisions.

---

## 6. Orchestrator — `ConversationalAIController.cs` (1635 lines)

The brain of the conversation system. One MonoBehaviour in the scene that:

### What it owns

- `_currentProvider` (the active `ILLMProvider` instance).
- `_currentToolRegistry` (the `ConversationToolService` instance).
- Connection lifecycle state (`_connected`, `_connecting`, `_lastReconnectAttempt`).
- Caption gating state (`_agentSpeakingFromProvider`, `_pendingCaptionBuffer`).
- Queued-user-message UX state (for barge-in).

### What it does on `Start()`

1. Resolve dependencies via `FindFirstObjectByType`: `ProviderFactory`, `ProviderConfig`, `ConversationToolService`, `MicrophoneStreamer`, `PcmAudioPlayer`.
2. Pick provider type via `_config.GetActiveConversationProvider()` (THE three-enum chain — see §8).
3. Call `_providerFactory.CreateLLMProvider(providerType)` → returns a MonoBehaviour implementing `ILLMProvider`.
4. Call `provider.Initialize(_config)`.
5. Subscribe to the provider's 6 events.
6. Type-sniff branches: `if (provider is VoiceRelayLlmProvider vr) { ... }` (hooks `AssistantAudioPlaybackStarting`), `if (provider is OpenAIProvider openAi) { ... }` (sets tool registry), etc. Our LiveKit doesn't need a type-sniff for any extra hookup beyond the standard interface.
7. Call `_currentProvider.ConnectAsync()`.
8. Subscribe `_micStreamer.OnAudioChunk` → `OnMicrophoneAudioChunk` callback.

### What it does in `Update()` (every frame)

- `TrackAudioPlaybackState` — monitors `audioPlayer.IsPlaying()` for caption gating.
- `UpdateLlmConnectionResilience` — checks `_currentProvider.IsConnected` every frame. After a 1.5s grace timer, fires reconnect coroutine if connection drops. Exponential backoff capped at 32s.

### What it does on `OnMicrophoneAudioChunk(base64Audio)`

This is the mic forwarding path (line ~907 onwards). Branches by provider type:

```csharp
// Branch 1: VoiceRelay interrupt-on-barge-in (when agent is speaking + first mic chunk arrives)
if (_currentProvider is VoiceRelayLlmProvider voiceRelay && _agentSpeakingFromProvider && ...)
    await voiceRelay.SendInterruptAsync();

// Branch 2: OpenAI fast-path (skips base64 decode)
if (_currentProvider is OpenAIProvider openAi)
    await openAi.SendAudioChunkBase64Async(base64Audio);
else if (_currentProvider is LiveKitLlmProvider)
    /* no-op — LiveKit owns mic uplink via MicrophoneStreamerAudioSource */
else
{
    var audioBytes = Convert.FromBase64String(base64Audio);
    await _currentProvider.SendAudioChunkAsync(audioBytes);
}
```

### What it does when provider fires events

- `OnAudioReceived(args)` → `audioPlayer.EnqueueBase64Audio(b64, sampleRate)`. Routes through `PcmAudioPlayer` for dual-output speaker routing.
- `OnTranscriptReceived(args)` → fires `AddUserMessageSignal` or `AddAIMessageSignal` for HUD/PhoneUI to render. Caption gating: agent transcripts buffered until audio actually starts playing (avoids "Sophia is responding..." text appearing before sound).
- `OnAgentSpeaking(true/false)` → fires `HUDConnectionBannerSignal` (pill animation) + drives caption gating.
- `OnUserSpeaking(true/false)` → fires user-state signals.
- `OnFunctionCall(args)` → forwards to `_toolRegistry.ExecuteToolAsync(name, args)` → result goes back to provider via `SendFunctionCallResultAsync` (provider-specific method).
- `OnError(args)` → logs with full diagnostic state, increments error counter for resilience logic, possibly triggers reconnect.

### What it does when stopping

- `StopConversation()` — unsubscribes events, calls `_currentProvider.DisconnectAsync()`, clears caption buffers.
- `ConversationExitParticipant` hooks into the app's `ApplicationExitCoordinator` so on app quit, the conversation cleans up before the app dies.

---

## 7. Audio pipeline (the most important non-provider code path)

### Mic capture (`Audio/Common/MicrophoneStreamer.cs`, 757 lines)

- Uses Unity's `Microphone.Start(device, true, 1, 16000)` API.
- 16 kHz output, 1024 samples per chunk (~64 ms).
- Downsamples if mic device runs at a higher native rate.
- Device-selection heuristic: `FindXREALMicrophoneDevice()` first (keyword match `xreal` / `nreal` / `usb`), falls back to `FindPhoneMicrophoneDevice()`.
- Android-only: `AndroidAudioSessionHelper.ConfigureForInputDevice(_micDevice)` sets VOICE_COMMUNICATION audio mode + hardware AEC.
- Encodes as 16-bit signed LE PCM, packs to `byte[]`, base64-encodes, then fires:
  - `Action<string> OnAudioChunk` (public field, NOT a multicast event) — base64 PCM
  - `event Action<float, float, float> OnMicChunkRmsForClientVad` — RMS probe (separate channel for VAD)
- Throttle: `MaxChunksPerFrame` (default 6, drops to 4 during video recording).

### Mic adapter to LiveKit (`Providers/LiveKit/MicrophoneStreamerAudioSource.cs`, 118 lines — OUR ADDITION)

- Subclasses `RtcAudioSource` (LiveKit Unity SDK base class).
- Subscribes to `MicrophoneStreamer.OnAudioChunk` using `-= then +=` pattern (to coexist alongside controller's existing subscription).
- Decodes base64 → int16 LE → upsamples 3x (16k → 48k) → converts to float [-1, 1] → invokes `AudioRead.Invoke(buffer, 1, 48000)` → LiveKit FFI captures the frame and publishes via the LocalAudioTrack.

### Audio playback (`Audio/Common/PcmAudioPlayer.cs`, ~250 lines)

- Maintains FIFO `Queue<AudioClip>` for incoming TTS PCM frames.
- Creates `AudioClip` instances at whatever sample rate the provider sends (16 kHz from VoiceRelay, 24 kHz from OpenAI, 48 kHz mixed).
- Drains one clip per Update() if not currently playing.
- **Dual-output**: a primary `AudioSource` (phone speaker route) + optional `xrealAudioSource` (glasses speaker via Audio Mixer group routing). Toggle controlled by `PhoneUIAudioOutputModeController`.
- Fires `OnClipStarted` event — used by AR session recording to capture device audio.
- API surface used by controller: `EnqueueBase64Audio(b64, sampleRate)`, `IsPlaying()`, `GetPlaybackRouteDescription()`, `Clear()`.

**LiveKit-specific note**: our `LiveKitLlmProvider` doesn't route audio through `PcmAudioPlayer` today (v1 limitation). LiveKit's SDK creates its own `AudioSource` on a child GameObject (`SophiaSpeaker_<sid>`) per agent track. This bypasses dual-output routing. To restore dual-output for LiveKit sessions, tap the LiveKit audio frames and call `PcmAudioPlayer.EnqueueBase64Audio` instead — see §10 "How to modify…" below.

---

## 8. Configuration system — the three-enum dispatch chain

This is the trickiest part of the architecture. See `Q30` in `project_complete_doubts.md` for the full deep dive. Here's the structural view:

### Three enums + one bundle override

```
                                    ┌──────────────────────────────────────────┐
                                    │  ProviderConfig.asset (ScriptableObject) │
                                    │                                          │
                                    │  Field 1: customizedEndpointsBundle      │
                                    │           (CustomizedEndpointsBundle SO  │
                                    │            reference — can be null)      │
                                    │                                          │
                                    │  Field 2: activeConversationProvider     │
                                    │           (CustomizedLooseConversation-  │
                                    │            Provider enum, values 0..5)   │
                                    └────────────────┬─────────────────────────┘
                                                     │
                                                     │ GetActiveConversationProvider()
                                                     │
                                ┌────────────────────┴────────────────────┐
                                │                                         │
                            UseCustomizedBundle() == true              == false
                            (bundle is assigned)                       (bundle is null)
                                │                                         │
                                ▼                                         ▼
                ┌──────────────────────────────────┐    ┌─────────────────────────────────┐
                │ CustomizedEndpointsBundle.       │    │ activeConversationProvider.     │
                │   ToConversationProviderType()   │    │   ToConversationProviderType()  │
                │                                  │    │                                 │
                │ Inside the bundle, the field     │    │ Extension method switch on the  │
                │ customizedAwsConversation        │    │ CustomizedLooseConversation-    │
                │ (CustomizedAwsConversationBackend│    │ Provider enum, returns          │
                │ enum, values 0..2) gets mapped:  │    │ ConversationProviderType.       │
                │  VoiceRelaySelfHosted →          │    │ Default arm: => OpenAI.         │
                │   ConversationProviderType.      │    │                                 │
                │   AwsVoiceRelaySelfHosted        │    │ (We added the LiveKit case here)│
                │  else → OpenAI                   │    │                                 │
                │                                  │    │                                 │
                │ (Does NOT know about LiveKit;    │    │                                 │
                │  needs extending if we want      │    │                                 │
                │  bundles to support LiveKit)     │    │                                 │
                └────────────┬─────────────────────┘    └───────────────┬─────────────────┘
                             │                                          │
                             └──────────────────┬───────────────────────┘
                                                ▼
                              ConversationProviderType (the RUNTIME enum)
                                                │
                                                │ ProviderFactory.CreateLLMProvider(type)
                                                │
                                                ▼
                                        ILLMProvider instance
```

**Three enums in `Modules/ProviderConfiguration/ProviderConfig.cs`**:

1. **`CustomizedLooseConversationProvider`** (lines 91-102, the UI dropdown enum):
   - `None = 0`
   - `AwsOpenAiRealtimeGateway = 1`
   - `AwsVoiceRelaySelfHosted = 2`
   - `SophiaLocalUnityServer = 3`
   - `OpenAiDirectVendor = 4`
   - `LiveKit = 5` (we added)

2. **`CustomizedAwsConversationBackend`** (lines 77-85, used by the bundle):
   - `OpenAiRealtimeGateway = 0`
   - `VoiceRelaySelfHosted = 1`
   - `OpenAiDirectVendor = 2`

3. **`ConversationProviderType`** (lines 119+, the runtime enum the factory switches on):
   - `None = 0`
   - `OpenAI = 1`
   - `Gemini = 2`
   - `Sophia = 3`
   - `SophiaLocalUnityServer = 4`
   - `AwsVoiceRelaySelfHosted = 5`
   - `LiveKit = 6` (we added)

**Converter extensions in `ProviderConfig.cs` (~line 1057)** — the mapping functions.

**Bundle ScriptableObject in `EndpointConfigurationBundles.cs`** — the override path. Has its own `ToConversationProviderType()` mapping.

### Provider Configuration Manager Editor window

Open via Unity menu: **SophiaClient → Tools → Provider Configuration Manager** (registered at `ProviderConfigurationEditorWindow.cs` line 14).

This window edits a `ProviderConfig.asset` instance using Unity's standard PropertyField — uses reflection on the enum types, so adding a new value to `CustomizedLooseConversationProvider` automatically makes it appear in the dropdown (no custom UI changes needed).

There's also a button on the main `ProviderConfig.asset` Inspector to open the manager window — `[CustomEditor(typeof(ProviderConfig))]` lives in `ProviderConfigEditor.cs`.

### The `ProviderConfig.asset` runtime load

At startup, his app loads the asset via:
```csharp
_config = Resources.Load<ProviderConfig>("ProviderConfigurations/ProviderConfig");
```

So the file must live at `Assets/Resources/ProviderConfigurations/ProviderConfig.asset`. Only ONE instance is used at runtime (the one at that exact path).

---

## 9. Tool system + RAG integration

### IToolRegistry contract

In `Abstractions/IToolRegistry.cs`:

```csharp
public interface IToolRegistry
{
    void RegisterTool(string name, Func<JObject, Task<JObject>> handler, JObject schema);
    void UnregisterTool(string name);
    Task<JObject> ExecuteToolAsync(string name, JObject args);
    JArray GetToolsSpec(string providerFormat = "openai");   // emits provider-format tool list
    bool IsToolRegistered(string name);
}
```

**Concrete implementation**: `Core/ConversationToolService.cs` (a MonoBehaviour in the scene).

### How tools get registered

`Modules/SpatialAI/LLMSpatialAPIGateway.cs` auto-discovers spatial tool handler classes via reflection at startup, calls `RegisterTool(name, handler, schema)` on the active provider's tool registry. Example tools:
- `pin_image_in_workspace`
- `focus_on_part`
- `spawn_product`
- `save_current_workspace`
- (etc. — see `VisualFidelityRealtimeToolHandlers.cs` for the canonical list)

### How tools get invoked at runtime

1. LLM (in agent worker on EC2 for LiveKit path, or OpenAI Realtime for OpenAI path) decides to call a tool based on user request.
2. Provider receives the tool call from backend, fires `OnFunctionCall(FunctionCallEventArgs)`.
3. Controller's `OnFunctionCall` handler routes to `_toolRegistry.ExecuteToolAsync(name, args)`.
4. Tool handler runs (in the SpatialAI module — spawn 3D model, pin image, etc.).
5. Handler returns `JObject` result.
6. Controller calls provider-specific `SendFunctionCallResultAsync(callId, result)` (OpenAI has this; LiveKit doesn't expose it yet — see §10 "How to add tool calling for LiveKit").

### RAG integration (for LiveKit path)

RAG is handled SERVER-SIDE in `sophia-agent/src/agent.py` via the `Assistant.on_user_turn_completed` always-retrieve hook. On every user turn:
1. Agent worker POSTs the user's transcript to `localhost:8106/retrieve` (sophia-spatial-ai on EKS via port-forward).
2. If `max_score >= 0.30`, the retrieved chunks get injected as a system message.
3. The agent ALSO publishes the raw RAG result to the `sophia.rag_result` text-stream topic.
4. Client (our `LiveKitLlmProvider.OnRagResultMessage`) receives the topic message and could render source chips on the HUD. Currently just logs.

For OpenAI Realtime path, the RAG hook lives in `OpenAIProvider` itself (different mechanism — embedded in the session tool config).

---

## 10. How to modify the conversation system (cheat sheet)

### Adding a new provider (e.g., "FooProvider" for some new backend)

1. **Create folder**: `Modules/ConversationalAI/Providers/Foo/`.
2. **Write `FooProvider.cs`**: implement `ILLMProvider` + an `Initialize(ProviderConfig)` method. Sealed `MonoBehaviour`. See LiveKitLlmProvider.cs as the v1.3.7 template; see `livekit_integration_sophia_wearable.md` § 5 for the design decisions to copy.
3. **Update `ConversationProviderType` enum** (`ProviderConfig.cs` line 119+) — add `Foo = N` with `[InspectorName("Foo (description)")]`.
4. **Update `CustomizedLooseConversationProvider` enum** (line 91+) — add same.
5. **Update converter** (line ~1057) — add the case mapping `CustomizedLooseConversationProvider.Foo => ConversationProviderType.Foo`.
6. **Update `ProviderFactory.cs`**: add `case ConversationProviderType.Foo: return CreateFooProvider();` plus the `CreateFooProvider()` method. Mirror `CreateVoiceRelayLlmProvider` pattern.
7. **Update asmdef**: if Foo uses a new SDK, add its assembly name to `Sophia.ConversationalAI.asmdef` references.
8. **Update `ConversationalAIController`**: if Foo needs special mic forwarding (e.g., bypass like LiveKit, or fast-path like OpenAI), add an `else if (_currentProvider is FooProvider foo)` branch in `OnMicrophoneAudioChunk`.
9. **Optional**: extend `CustomizedAwsConversationBackend` enum + bundle's `ToConversationProviderType()` if bundles should know about Foo.
10. **Scene wiring**: add a FooProvider GameObject under `Logic/Modules/ConversationalAI` and wire Inspector fields.
11. **Provider Configuration Manager**: select Foo in the dropdown; save asset.
12. **Smoke test**: hit Play, watch for your `[DEBUG_FOO]` log tags.

### Adding a new tool the LLM can call

1. **Decide where the tool lives**: usually `Modules/SpatialAI/` since most tools manipulate spatial things. Or add a new module if it's a different domain.
2. **Write handler class** with `[LLMTool(name, description, schema)]` attribute (his auto-discovery convention). Public method takes `JObject args` and returns `Task<JObject>`.
3. **Confirm `LLMSpatialAPIGateway`** picks it up (it auto-registers at session start).
4. **Verify the tool appears in `GetToolsSpec("openai")`** at runtime.
5. **Tool calling for LiveKit isn't wired today**: our `agent.py` doesn't expose tools. For LiveKit path, tools must be added in `sophia-agent/src/agent.py` via the LiveKit Agents framework's `@function_tool` decorator. Then the agent's tool-call decision flows back via the standard `OnFunctionCall` event.

### Modifying audio routing (e.g., enable dual-output for LiveKit)

Currently `LiveKitLlmProvider` lets the SDK play audio directly via its auto-attached `AudioSource` on a child GameObject. To route through `PcmAudioPlayer` instead (so dual-output works):

1. In `LiveKitLlmProvider.OnTrackSubscribed`, instead of letting SDK play directly, attach a custom `AudioFrameListener` to the `RemoteAudioTrack`.
2. In the listener callback, get the PCM bytes, base64-encode them, and call `_pcmAudioPlayer.EnqueueBase64Audio(b64, 48000)`.
3. Set the auto-attached AudioSource's volume to 0 (so audio doesn't double-play).
4. Re-add the `OnAudioReceived` event firing (currently a no-op for LiveKit) — emit with `AudioReceivedEventArgs { AudioData = bytes, Format = "pcm16", SampleRate = 48000 }`.
5. Controller's existing handler routes `OnAudioReceived` → `audioPlayer.EnqueueBase64Audio`.

### Modifying HUD behavior (e.g., change subtitle position)

HUD rendering lives in `Modules/HUD` and the `Modules/PhoneUI` canvases. They subscribe to signals fired by `ConversationalAIController`:
- `HUDConnectionBannerSignal` — state pill (connecting/connected/disconnected/speaking)
- `AddUserMessageSignal` — user transcript
- `AddAIMessageSignal` — agent transcript (gated by audio playback)
- Plus signals for RAG sources (look for `SignalSubscriber<RagResultSignal>` or similar)

To change subtitle position, change the world-space Canvas under `Sophia_Wearables.unity` → `Logic/Modules/HUD/`. The signal-handler scripts are usually `MonoBehaviour`s on those canvas children.

To add a new HUD element, write a new MonoBehaviour that subscribes to a signal (his pattern: `SignalSubscriber<SignalType>.Subscribe(this, OnSignalFired)`) and update its UI accordingly.

### Adding vision support to LiveKit (composite path)

Currently `LiveKitLlmProvider.SendImageAsync` is a no-op. To add vision:

1. **Option A — Backend-side**: extend `sophia-agent/src/agent.py` to handle image input via LiveKit's data channel. Add `@function_tool` or session-config piece. Client sends image as base64 via `PublishData(bytes, topic: "sophia.user_image")`. Agent receives, calls Qwen3-VL (it has vision capability!) for image understanding.

2. **Option B — Composite-defer-to-GoogleVision**: in `LiveKitLlmProvider.SendImageAsync`, do:
   ```csharp
   if (_googleVisionProvider != null)
   {
       var bytes = Convert.FromBase64String(imageDataUrl.Substring("data:image/png;base64,".Length));
       var analysis = await _googleVisionProvider.AnalyzeImageAsync(bytes);
       var description = string.Join(", ", analysis.Labels);
       await SendTextAsync($"[image context: {description}]");
   }
   ```
   Mirrors how `OpenAIProvider` degrades vision via composite.

Option A is more featureful (real multimodal) but requires backend changes. Option B is purely client-side.

### Adding chat history persistence

Currently chat history is held in `chat_ctx.messages[]` server-side (for LiveKit) or in the OpenAI Realtime session (for OpenAI). On disconnect, history is lost.

To persist chat history client-side:
1. Subscribe to `OnTranscriptReceived` events in the controller.
2. Append to a `List<ChatMessage>` field.
3. Serialize to PlayerPrefs or a JSON file on disk per `UserSessionController` (in `Modules/UserSessions`).
4. On reconnect, replay the last N turns to the provider via `SendTextAsync` (for text providers) or via the LiveKit agent worker's `chat_ctx` parameter (would require backend support).

### Modifying reconnect behavior

`ConversationalAIController.UpdateLlmConnectionResilience` (line ~635) controls reconnect. Knobs:
- Grace timer: 1.5s before triggering reconnect (line 659).
- Backoff: 1.5 × 2^n capped at 32s (in `ConversationProviderReconnectRoutine`, lines 674-800).

To change reconnect aggressiveness, edit those numeric constants. Don't change the IsConnected polling pattern — providers (LiveKit especially) rely on the grace-timer-absorbs-Reconnecting-state pattern (`Q6`).

### Debugging "voice agent doesn't respond"

1. **Console**: filter for `[DEBUG_*]` tags. Different providers use different prefixes:
   - LiveKit: `[DEBUG_0604_LiveKit]`
   - VoiceRelay: `[DEBUG_0605_VoiceRelay]`, `[DEBUG_0423_VoiceRelay]`, etc.
   - OpenAI: `[DEBUG_*_OpenAI]`
2. **Provider status**: look for `ConversationalAIController` "StartConversation failed" errors (line 412+). Has rich diagnostic context.
3. **Provider connect state**: log `_currentProvider.IsConnected` periodically.
4. **Backend reachability**: for LiveKit, SSH to EC2 and `docker compose logs livekit-server --tail 30 | grep $(date +%Y-%m-%d)`.

---

## 11. Cross-references — when to read what

- **Want to add a feature to conversation?** Start here, then read `livekit_integration_sophia_wearable.md` § 5 for new-provider patterns.
- **Want to understand voice data flow?** Read `livekit_voice_flow_end_to_end.md`.
- **Want to know how LiveKit specifically is integrated?** Read `livekit_integration_sophia_wearable.md`.
- **Want to understand the EC2 backend?** Read `livekit_architectur_ec2.md`.
- **Want to deploy to production?** Read `HANDOFF.md` (project root).
- **Want the full XR engineer repo architecture (not just conversation)?** Read `Sophia_Xreal-U2.md`.
- **Want LiveKit Unity SDK Q&A from earlier work?** Read `livekit_doubts.md`.
- **Want the full project history Q&A?** Read `project_complete_doubts.md`.

---

## 12. Quick file-paths reference

| Topic | File |
|---|---|
| Main interface | `Modules/ConversationalAI/Abstractions/ILLMProvider.cs` |
| Main orchestrator | `Modules/ConversationalAI/Core/ConversationalAIController.cs` |
| Factory | `Modules/ConversationalAI/Core/ProviderFactory.cs` |
| Tool registry | `Modules/ConversationalAI/Core/ConversationToolService.cs` |
| Client VAD | `Modules/ConversationalAI/Core/ClientSideVadService.cs` |
| Latency telemetry | `Modules/ConversationalAI/Core/STSLatencyDiagnostics.cs` |
| Exit cleanup | `Modules/ConversationalAI/Core/ConversationExitParticipant.cs` |
| OpenAI provider | `Modules/ConversationalAI/Providers/OpenAI/OpenAIProvider.cs` |
| VoiceRelay provider | `Modules/ConversationalAI/Providers/VoiceRelay/VoiceRelayLlmProvider.cs` |
| LiveKit provider | `Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs` |
| Mic adapter (LiveKit) | `Modules/ConversationalAI/Providers/LiveKit/MicrophoneStreamerAudioSource.cs` |
| HUD service | `Modules/ConversationalAI/Hud/ConversationalAiHudService.cs` |
| Provider status UI | `Modules/ConversationalAI/UI/ProviderStatusUI.cs` |
| asmdef | `Modules/ConversationalAI/Sophia.ConversationalAI.asmdef` |
| Config types + 3 enums + converters | `Modules/ProviderConfiguration/ProviderConfig.cs` |
| Config bundle ScriptableObject | `Modules/ProviderConfiguration/EndpointConfigurationBundles.cs` |
| Mic capture | `Modules/Audio/Common/MicrophoneStreamer.cs` |
| Audio playback | `Modules/Audio/Common/PcmAudioPlayer.cs` |
| Audio controller | `Modules/Audio/Core/AudioController.cs` |
| Networking factory | `Modules/Networking/NetworkingController.cs` |
| WS pump | `Modules/Networking/RealtimeWebSocketPump.cs` |
| Gateway bootstrap | `Modules/Networking/GatewayRuntimeBootstrapService.cs` |
| Tool auto-discovery | `Modules/SpatialAI/LLMSpatialAPIGateway.cs` |
| Editor: config manager | `_Scripts/Editor/SophiaClient/ProviderConfigurationEditorWindow.cs` |
| Runtime config asset | `Assets/Resources/ProviderConfigurations/ProviderConfig.asset` |
| Main scene | `Assets/_Scenes/Sophia_Wearables.unity` |

---

## 13. Glossary

- **Provider**: a `MonoBehaviour` implementing `ILLMProvider` that wraps a specific backend (OpenAI Realtime, LiveKit, VoiceRelay, etc.).
- **Bundle**: a `CustomizedEndpointsBundle` ScriptableObject that overrides the loose `activeConversationProvider` selection — currently knows only OpenAI / VoiceRelay (we cleared it to enable LiveKit; see Q30).
- **Tool**: a function the LLM can call (e.g., `pin_image_in_workspace`). Implemented in `Modules/SpatialAI`, auto-registered with the active provider.
- **Signal**: his app's pub/sub mechanism for UI events. Fired by controller, subscribed by HUD/PhoneUI canvases.
- **TTS audio**: text-to-speech audio bytes sent FROM the backend TO the client.
- **Mic uplink**: audio captured by the client mic going TO the backend for STT.
- **Audio-first caption gating**: showing agent caption text only AFTER the actual TTS audio starts playing (so user doesn't see "Sophia is responding..." before hearing it).
- **Barge-in**: user starts talking while agent is still talking — interrupt the agent.
- **Agent-only identity filter**: only play audio from participants whose `Identity.StartsWith("agent-")` to avoid hearing other users' raw mic in multi-user rooms (Q58 fix).
- **Three-enum chain**: `CustomizedLooseConversationProvider` (UI) → `ConversationProviderType` (runtime), with `CustomizedAwsConversationBackend` (bundle) as a third overlapping enum. See §8 + Q30.
- **Customized Endpoints vs Single Endpoint mode**: two `EndpointConfigurationMode` options. Customized = each provider has its own URL + creds. Single = one AWS gateway URL routes everything.

---

**End of document.**

If you spot a bug or learned something new about his conversation system that should be captured here, append it. This doc is meant to evolve as you (and the project) learn.
