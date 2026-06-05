# LiveKit Integration into Sophia_Wearable (XR engineer's repo) — Complete Reference

How we integrated LiveKit (WebRTC + LiveKit Agents) as a new conversation provider in the XR engineer's production Unity wearable client (`AIPartnersUSA/Sophia_Xreal-U2`), working on a branch off his `development`. Read this end-to-end when picking the work back up, redoing on a fresh clone, or onboarding a new engineer to the integration. Captures the WHY behind every change, not just the WHAT.

---

## 1. Background + goal

**What we integrated**: LiveKit Unity SDK v1.3.7 as a new `ILLMProvider` implementation in the XR engineer's existing provider-abstraction architecture, pointed at our self-hosted LiveKit SFU + LiveKit Agents framework backend on EC2 (`3.227.63.49`). Sophia voice agent now reachable via WebRTC + sophia-agent (Python, LiveKit Agents) alongside his existing OpenAI Realtime / Gemini / VoiceRelay providers.

**Why**: his app shipping to XREAL wearables needs (a) better network resilience than raw WSS (WebRTC + Opus + jitter buffer), (b) future multi-participant collaborative XR sessions (SFU pattern), (c) parity with `sophia-glasses/` reference client so both share the same backend orchestration. See `Q12` + `Q16` + `Q26` in `project_complete_doubts.md` for the value analysis and comparison framing.

**Phase plan** (from `Q15`):
- **Phase 1** = integrate LiveKitProvider against EC2 MVP backend (THIS DOC). 1-1.5 days of work; ended up taking ~3 days of session time after surfacing the SDK API mismatches + architecture gotchas.
- **Phase 1.5** = measurement spike comparing LiveKit vs AWS Voice step path inside his same client.
- **Phase 2** = infra team migrates backend to standard AWS production using `HANDOFF.md`. URLs swap in config, code unchanged.
- **Phase 3** = latency optimization.

**Backend target for Phase 1 (where our new provider connects)**:
- LiveKit SFU: `ws://3.227.63.49:7880`
- Token-mint: `http://3.227.63.49:8001/token` with header `X-API-Key: 9a11fdf5ce05e3cecad28f933d778971`
- Agent worker registered as: `agentName = "sophia-agent"` (matches `@server.rtc_session(agent_name="sophia-agent")` in `sophia-agent/src/agent.py`)
- Three Docker containers Up 6+ days on EC2: `sophia-livekit-server-1`, `sophia-token-mint-1`, `sophia-agent-worker-1`.
- Cross-region kubectl port-forward from EC2 to EKS inference cluster (`spatial-ai-staging` in us-west-2) gives the agent worker access to Whisper STT (8080), Qwen3 LLM (18080), Kokoro TTS (8122).

---

## 2. Prerequisites

**Access**:
- GitHub Collaborator (Write) on `AIPartnersUSA/Sophia_Xreal-U2`. Granted via the `AIP_All` team. Verify with `gh api repos/AIPartnersUSA/Sophia_Xreal-U2 --jq .permissions` — should show `push: true`.
- GitHub Collaborator on `AIPartnersUSA/sophia-agent-research` (our research repo, for doc updates).
- SSH key for EC2 (`~/.ssh/config` alias `ssh sophia-gpu`).

**Local environment**:
- macOS (we worked on Mac Mac17,8 / Mac OS 26.4.1).
- Git + Git LFS installed.
- GitHub CLI (`gh`) authenticated as `AvinashSophia`.
- Unity Hub + Unity Editor `6000.3.12f1` (his project's required version per `Sophia_Wearable/ProjectSettings/ProjectVersion.txt`).
- Unity modules: Mac Build Support (Apple silicon), Android Build Support (with SDK & NDK + OpenJDK for APK builds).

**Reference clones we already have** in this research project (read-only, for code reading):
- `/Users/avinashbolleddula/Documents/sophia Agent Research/Sophia_Xreal-U2/` — XR engineer's repo cloned with `GIT_LFS_SKIP_SMUDGE=1` for source code reading only.
- `/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/client-sdk-unity/` — our vendored LiveKit Unity SDK (v1.3.7), useful as a reference for SDK APIs even though the integration uses UPM.

**Work clone** (where we actually edit + commit + push):
- `/Users/avinashbolleddula/Documents/repos/Sophia_Xreal-U2-main/` — separate from research project root. Avinash's pre-existing repos folder. This is the writable clone we push from.

---

## 3. Setup — clone + branch (one-time)

The work clone already existed in Avinash's repos folder from earlier work. Setup was:

```bash
cd /Users/avinashbolleddula/Documents/repos/Sophia_Xreal-U2-main
git fetch origin --prune                       # prune stale branches; bring development down
git checkout development                       # switch to development branch
git pull origin development                    # latest commits
git checkout -b avinash/livekit-provider       # our feature branch
```

**Why branch off `development`, not `main`**:
- His team's archive branches (`archive/agent-test`, `archive/fix-rgb-camera`, etc.) suggest a development-first workflow.
- `main` is the default branch but `development` is where active work lives.
- Branch name `avinash/livekit-provider` chosen because XR engineer said "feel free to add a branch with a clear name". The `avinash/` prefix attributes ownership.

**Confirm baseline before any edits**: open the project in Unity Editor at `Sophia_Wearable/`. With XR engineer's `customizedEndpointsBundle` assigned, OpenAI Realtime + AWS Voice Step (cascaded) baseline tests should both run cleanly. This was confirmed on 2026-06-04.

---

## 4. The integration plan — 10 changes in 4 categories

Yesterday's plan was 8 steps; today's discoveries (Q30-Q31) added 2 more. Final list of all 10 changes that make LiveKit fully functional in his client:

| # | Category | What changes | File |
|---|---|---|---|
| 1 | New code | Provider implementation | `LiveKitLlmProvider.cs` (new) |
| 2 | New code | Mic adapter | `MicrophoneStreamerAudioSource.cs` (new) |
| 3 | SDK install | LiveKit Unity SDK via UPM Git URL | `Packages/manifest.json` |
| 4 | Code modify | LiveKit added to runtime + UI enums + converter | `ProviderConfig.cs` |
| 5 | Code modify | Factory dispatch | `ProviderFactory.cs` |
| 6 | Code modify | Mic-forwarding bypass for LiveKit | `ConversationalAIController.cs` |
| 7 | Code modify | LiveKit asmdef reference | `Sophia.ConversationalAI.asmdef` |
| 8 | Config modify | HTTP allow for EC2 MVP | `ProjectSettings.asset` |
| 9 | Asset modify | LiveKit selected + bundle cleared | `ProviderConfig.asset` |
| 10 | Scene modify | LiveKitLlmProvider GameObject + Inspector wiring | `Sophia_Wearables.unity` |

Plus one important non-our-change in the same branch:
| - | Cleanup (XR engineer's call) | Remove ARCore Extensions package | `manifest.json` + delete `Assets/Samples/ARCore Extensions/` |

Detailed walkthrough of each below.

---

## 5. Step-by-step code changes (with WHY)

### Change 1 — Write `LiveKitLlmProvider.cs`

**File**: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs` (~570 lines after fixes).

**Why**: implements his existing `ILLMProvider` interface against LiveKit Unity SDK. Provider gets instantiated by `ProviderFactory` when the user picks LiveKit; controller dispatches all voice events through its public events.

**Key design decisions**:
1. `MonoBehaviour` + sealed (mirrors `VoiceRelayLlmProvider` pattern). Factory uses `FindFirstObjectByType` then `AddComponent` if absent.
2. Mic uplink via custom `RtcAudioSource` subclass (next file) — preserves XREAL boom mic device-selection + VOICE_COMMUNICATION audio mode that his `MicrophoneStreamer` already handles. Without this we'd lose audio quality on actual XREAL hardware (see `Q17` for the factory-floor scenario).
3. Audio downlink via SDK's auto-attached `AudioSource` on a per-track child GameObject (mirrors `sophia-glasses` Q58 fix — child GameObject per agent track keyed by publication SID).
4. Identity filter: `participant.Identity.StartsWith("agent-")` everywhere agent-vs-user matters. The LiveKit Agents framework auto-generates participant identity like `agent-AJ_AEBd84m8of6k`.
5. Three text-stream topics subscribed BEFORE `Room.Connect`: `sophia.agent_events`, `sophia.rag_result`, `lk.transcription`.
6. Reconnect coexistence (`Q6` in Q17): `IsConnected` returns true while SDK is in `Reconnecting` state so the controller's 1.5s grace timer absorbs SDK transient blips.
7. `SendImageAsync` is a deliberate no-op (matches VoiceRelay's behavior; vision can be added later via composite-defer-to-GoogleVision).
8. `SendAudioChunkAsync` is also a no-op — audio flows out-of-band via the mic adapter (next file).
9. `[DEBUG_0604_LiveKit]` log prefix for grep parity with VoiceRelay's `[DEBUG_*_VoiceRelay]` tags.
10. v1 configuration via `[SerializeField]` Inspector fields (`_liveKitUrl`, `_tokenEndpoint`, `_tokenApiKey`, `_agentName`, etc.). `Initialize(ProviderConfig _)` is a no-op for v1 — accepts the arg for ProviderFactory's call to compile, but reads nothing.

**Compile-clean against LiveKit SDK v1.3.7 required these specific patterns** (each was discovered as a compile error and documented in detail in `Q29`):
- `new global::LiveKit.RoomOptions()` (the `global::` prefix dodges the namespace shadow since our own namespace is `Sophia.ConversationalAI.Providers.LiveKit`).
- `await AwaitYield(connectOp)` instead of `await connectOp` — `ConnectInstruction`/`PublishTrackInstruction`/`ReadAllInstruction` all inherit `CustomYieldInstruction`, not awaitable as Task. Helper:
  ```csharp
  private static async Task AwaitYield(global::LiveKit.YieldInstruction instr)
  {
      while (!instr.IsDone)
          await Task.Yield();
  }
  ```
- No `_room.Dispose()` call (Room has no `Dispose` in v1.3.7; FfiHandle finalizer cleans up).
- `PublishData(bytes, topic: "sophia.user_text")` (void return, named topic param — no `DataPublishOptions`).
- `reader.ReadAll()` returning `ReadAllInstruction` with `.Text` after `.IsDone`, NOT `ReadAllAsync()`.

**Required usings at top**:
```csharp
using System;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using LiveKit;
using LiveKit.Proto;
using Newtonsoft.Json.Linq;
using Sophia.ConversationalAI.Abstractions;
using Sophia.ConversationalAI.Config;          // for ProviderConfig type — easy to miss!
using UnityEngine;
using UnityEngine.Networking;
```

### Change 2 — Write `MicrophoneStreamerAudioSource.cs`

**File**: same folder as Change 1 (118 lines).

**Why**: bridges his `MicrophoneStreamer.OnAudioChunk(string base64)` event into LiveKit's audio capture pipeline. Without this adapter we'd lose his XREAL device-selection heuristic and AndroidAudioSessionHelper VOICE_COMMUNICATION routing — meaning the wearable on actual hardware would use the phone's pocket mic instead of the XREAL boom mic.

**Key design decisions**:
1. Subclass `RtcAudioSource` with `RtcAudioSourceType.AudioSourceCustom`, `channels: 1` (mono).
2. Subscribe to `MicrophoneStreamer.OnAudioChunk` using `-=` then `+=` pattern (it's a public `Action<string>` field, not an event — risk of clobber if you use `=`).
3. Naive 3x upsampling (sample triplication) to bridge 16 kHz → 48 kHz. The base `RtcAudioSource` Custom-type locks to 48 kHz in the constructor (no per-instance override). Quality is acceptable for voice; STT (Whisper) resamples internally. Replace with linear interpolation if quality issues arise.
4. Single-pass: decode base64 → reinterpret bytes as int16 LE → upsample + convert to float [-1, 1] in one loop with one allocation per chunk.
5. Lifecycle parity: `Start` subscribes + invokes `base.Start()`, `Stop` unsubscribes + `base.Stop()`, `Dispose(bool)` chains, finalizer for safety.

### Change 3 — Add LiveKit Unity SDK via UPM Git URL

**File**: `Sophia_Wearable/Packages/manifest.json`.

**Why**: provides the `using LiveKit;` namespace, the native FFI binaries for all platforms, and the `Google.Protobuf.dll` precompiled reference.

**Edit** (one line added alphabetically between `com.xreal.xr` and `org.khronos.unitygltf`):
```json
"com.xreal.xr": "file:com.xreal.xr",
"io.livekit.livekit-sdk": "https://github.com/livekit/client-sdk-unity.git#v1.3.7",
"org.khronos.unitygltf": "https://github.com/KhronosGroup/UnityGLTF.git",
```

**Why UPM Git URL over vendor-copy**: his manifest already uses 5 UPM Git URLs (`com.convai.openai`, NativeWebSocket, ARCore extensions originally, ARKit, UnityGLTF) — so the pattern fits his ecosystem. One-line diff in PR vs ~150 MB of LFS binaries that would impact his org's LFS quota. v1.3.7 is the exact version we tested with in `sophia-glasses/client-sdk-unity/package.json`. Full rationale + tradeoffs in `Q27`.

**What happens at first Unity Editor open**: Unity reads the manifest, recognizes the URL-with-tag pattern, clones the upstream `livekit/client-sdk-unity` repo at tag `v1.3.7`, caches it locally at `<project>/Library/PackageCache/io.livekit.livekit-sdk@270adc1cbceb/` (the suffix is the commit hash that v1.3.7 points to). Subsequent opens use the cache, no network needed.

### Change 4 — Edit `ProviderConfig.cs` (THREE separate changes in one file)

**File**: `Sophia_Wearable/Assets/_Scripts/Modules/ProviderConfiguration/ProviderConfig.cs`.

**Why**: his Provider Configuration system has TWO enums + a converter — all three need LiveKit. Yesterday we added it only to one and silently fell back to OpenAI. See `Q30` for the full architecture analysis.

**Sub-change 4a — Add `LiveKit = 6` to `ConversationProviderType`** (lines ~119-135):
```csharp
public enum ConversationProviderType
{
    None = 0,
    [InspectorName("OpenAI Realtime")]
    OpenAI = 1,
    Gemini = 2,
    [InspectorName("Sophia AWS Server")]
    Sophia = 3,
    [InspectorName("Sophia Local Unity Server")]
    SophiaLocalUnityServer = 4,
    /// <summary>Self-hosted voice relay (Whisper → LLM → Kokoro) via <c>/gateway/sophia-speech/ws</c>.</summary>
    [InspectorName("AWS — Voice relay (Whisper → LLM → Kokoro TTS)")]
    AwsVoiceRelaySelfHosted = 5,
    /// <summary>Self-hosted LiveKit (WebRTC SFU + LiveKit Agents framework) — see sophia-agent/src/agent.py.</summary>
    [InspectorName("LiveKit (WebRTC + LiveKit Agents)")]
    LiveKit = 6
}
```
This is the RUNTIME enum the factory switches on.

**Sub-change 4b — Add `LiveKit = 5` to `CustomizedLooseConversationProvider`** (lines ~91-102):
```csharp
public enum CustomizedLooseConversationProvider
{
    None = 0,
    [InspectorName("AWS — OpenAI Realtime (gateway adapter)")]
    AwsOpenAiRealtimeGateway = 1,
    [InspectorName("AWS — Voice relay (Whisper → LLM → Kokoro TTS)")]
    AwsVoiceRelaySelfHosted = 2,
    [InspectorName("Sophia Local Unity Server")]
    SophiaLocalUnityServer = 3,
    [InspectorName("OpenAI — Direct API (api.openai.com)")]
    OpenAiDirectVendor = 4,
    [InspectorName("LiveKit (WebRTC + LiveKit Agents)")]
    LiveKit = 5
}
```
This is the UI-facing enum the dropdown in Provider Configuration Manager shows. Different numbering from runtime enum (5 here, 6 in runtime).

**Sub-change 4c — Add converter case** (~line 1057-1071):
```csharp
public static ConversationProviderType ToConversationProviderType(this CustomizedLooseConversationProvider p) =>
    p switch
    {
        CustomizedLooseConversationProvider.None => ConversationProviderType.None,
        CustomizedLooseConversationProvider.AwsOpenAiRealtimeGateway => ConversationProviderType.OpenAI,
        CustomizedLooseConversationProvider.AwsVoiceRelaySelfHosted => ConversationProviderType.AwsVoiceRelaySelfHosted,
        CustomizedLooseConversationProvider.SophiaLocalUnityServer => ConversationProviderType.SophiaLocalUnityServer,
        CustomizedLooseConversationProvider.OpenAiDirectVendor => ConversationProviderType.OpenAI,
        CustomizedLooseConversationProvider.LiveKit => ConversationProviderType.LiveKit,
        _ => ConversationProviderType.OpenAI
    };
```
Without this case, selecting LiveKit in the dropdown silently dispatches to OpenAI because the `_ => ConversationProviderType.OpenAI` default catches it.

**Lessons learned**: silent default fallback in a switch expression is the trap. The compiler doesn't warn you about missing enum cases when there's a `_ => ...` arm.

### Change 5 — Edit `ProviderFactory.cs`

**File**: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Core/ProviderFactory.cs`.

**Why**: the factory translates `ConversationProviderType.LiveKit` into our actual MonoBehaviour. Without this case, the runtime returns null and nothing happens.

**Two hunks**:

**Hunk 5a — new case arm** (around line 42 in `CreateLLMProvider(ConversationProviderType)`):
```csharp
case ConversationProviderType.AwsVoiceRelaySelfHosted:
    return CreateVoiceRelayLlmProvider();

case ConversationProviderType.LiveKit:                              // NEW
    return CreateLiveKitProvider();                                 // NEW

case ConversationProviderType.Gemini:
    return CreateGeminiProvider();
```

**Hunk 5b — new method** (around line 190, mirroring `CreateVoiceRelayLlmProvider` exactly):
```csharp
private ILLMProvider CreateLiveKitProvider()
{
    var p = FindFirstObjectByType<Sophia.ConversationalAI.Providers.LiveKit.LiveKitLlmProvider>();
    if (p == null)
    {
        var go = new GameObject("LiveKitLlmProvider");
        p = go.AddComponent<Sophia.ConversationalAI.Providers.LiveKit.LiveKitLlmProvider>();
        go.transform.SetParent(transform);
    }

    p.Initialize(config);
    return p;
}
```

**Why FindFirstObjectByType then AddComponent**: if a `LiveKitLlmProvider` GameObject already exists in the scene (which is what Change 10 sets up), reuse it (preserves Inspector field assignments). Otherwise create one on the fly.

### Change 6 — Edit `ConversationalAIController.cs`

**File**: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Core/ConversationalAIController.cs`.

**Why**: the controller forwards mic chunks (base64) to providers via `OnMicrophoneAudioChunk`. For OpenAI it's a fast-path that sends base64 directly. For everyone else it base64-decodes to byte[] then calls `provider.SendAudioChunkAsync(bytes)`. For LiveKit, our `SendAudioChunkAsync` is intentionally a no-op (because audio flows out-of-band via `MicrophoneStreamerAudioSource` subscribing to the same `OnAudioChunk` event independently). Adding an explicit skip saves a wasted base64 decode per chunk (~6/frame at 64 ms chunks).

**Edit** (around line 1005, between the OpenAI fast-path and the catch-all `else`):
```csharp
if (_currentProvider is OpenAIProvider openAi)
{
    // ... existing OpenAI fast-path with Stopwatch ...
}
else if (_currentProvider is Sophia.ConversationalAI.Providers.LiveKit.LiveKitLlmProvider)   // NEW
{                                                                                              // NEW
    // LiveKit owns the mic uplink out-of-band via MicrophoneStreamerAudioSource,              // NEW
    // which independently subscribes to MicrophoneStreamer.OnAudioChunk and pushes            // NEW
    // PCM into the LocalAudioTrack. Skip the byte[] forwarding here — the                     // NEW
    // provider's SendAudioChunkAsync is a deliberate no-op, and decoding base64               // NEW
    // just to discard it wastes CPU per chunk (~6 calls/frame at 64 ms chunks).               // NEW
}                                                                                              // NEW
else
{
    var audioBytes = Convert.FromBase64String(base64Audio);
    await _currentProvider.SendAudioChunkAsync(audioBytes);
}
```

**Other type-sniff branches in the same method correctly skip LiveKit as-is**, no edits needed:
- VoiceRelay interrupt-on-barge-in (lines 980-986): only fires when `_currentProvider is VoiceRelayLlmProvider`.
- VoiceRelay uplink chunk clock (lines 988-989): VoiceRelay-specific diagnostic.
- `_voiceRelayMicChunksForwarded++` counter (lines 1011-1013): only increments for VoiceRelay + OpenAI.

### Change 7 — Edit `Sophia.ConversationalAI.asmdef`

**File**: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Sophia.ConversationalAI.asmdef`.

**Why**: his asmdef has an explicit `references` array, which makes Unity STRICT — `autoReferenced: true` on the LiveKit asmdef doesn't help when an explicit references list exists. Without this, our `using LiveKit;` doesn't resolve and the whole module fails to compile.

**Edit** (add `"LiveKit"` to the references array):
```json
{
    "name": "Sophia.ConversationalAI",
    "rootNamespace": "Sophia",
    "references": [
        "Sophia.Audio",
        "Sophia.ProviderConfiguration",
        "Sophia.Networking",
        "Sophia.Core",
        "Sophia.Scenarios",
        "Sophia.CameraOperations",
        "Unity.TextMeshPro",
        "Unity.InputSystem",
        "Unity.XR.Interaction.Toolkit",
        "Unity.XR.CoreUtils",
        "Unity.RenderPipelines.Universal.Runtime",
        "Unity.XR.XREAL",
        "Newtonsoft.Json",
        "endel.nativewebsocket",
        "LiveKit"                                  // NEW (matches the LiveKit asmdef name)
    ],
    ...
}
```

The exact name `"LiveKit"` matches what the SDK's `livekit.unity.Runtime.asmdef` declares as `"name": "LiveKit"`.

### Change 8 — Edit `ProjectSettings.asset`

**File**: `Sophia_Wearable/ProjectSettings/ProjectSettings.asset`.

**Why**: Unity 6 changed the default for HTTP downloads from "Always allowed" to "Not allowed". Our EC2 MVP token-mint runs at `http://3.227.63.49:8001/token` (no TLS). Without this setting, UnityWebRequest refuses the POST client-side with `System.InvalidOperationException: Insecure connection not allowed`. See `Q31`.

**Edit** (via Unity Editor — change persists in ProjectSettings.asset):
1. Edit → Project Settings → Player.
2. Right panel → Other Settings → Configuration.
3. Allow downloads over HTTP → change to **"Always allowed"**.

**What it looks like in the file**:
```yaml
insecureHttpOption: 2          # was 0 (Not allowed) → now 2 (Always allowed)
```

**Phase 2 cleanup**: when production AWS puts TLS in front of token-mint and SFU, this can revert to `0`.

### Change 9 — Edit `ProviderConfig.asset`

**File**: `Sophia_Wearable/Assets/Resources/ProviderConfigurations/ProviderConfig.asset`.

**Why**: two things need to change in this ScriptableObject instance:
1. `activeConversationProvider: 5` — selecting LiveKit in the dropdown.
2. `customizedEndpointsBundle: {fileID: 0}` — clearing the assigned bundle. WITHOUT this, the runtime dispatch uses `customizedEndpointsBundle.ToConversationProviderType()` which only knows OpenAI / VoiceRelay (no awareness of LiveKit). With the bundle cleared, dispatch falls through to `activeConversationProvider.ToConversationProviderType()` which we just taught about LiveKit in Change 4c. See `Q30` for the architecture analysis.

**Edit via Unity Editor**:
1. Open `Sophia_Wearables.unity` scene if not already open.
2. In Project panel, click `Assets/Resources/ProviderConfigurations/ProviderConfig.asset`.
3. Inspector → Customized Endpoints Bundle field → click the small target icon → select None.
4. Either click the Provider Configuration Manager button + select LiveKit there, OR set `activeConversationProvider` to `LiveKit (WebRTC + LiveKit Agents)` directly.
5. Cmd+S to save.

**What it looks like in the file**:
```yaml
endpointConfigurationMode: 0           # Customized (unchanged)
activeConversationProvider: 5           # was 4 (OpenAiDirectVendor) → now 5 (LiveKit)
customizedEndpointsBundle: {fileID: 0}  # was a bundle reference → now null
```

**Long-term cleanup item**: extend `CustomizedAwsConversationBackend` enum + `CustomizedEndpointsBundle.ToConversationProviderType()` to also support LiveKit. Then bundles can be re-enabled. Out of scope for v1 PR.

### Change 10 — Scene wiring (`Sophia_Wearables.unity`)

**File**: `Sophia_Wearable/Assets/_Scenes/Sophia_Wearables.unity`.

**Why**: factory will create a LiveKitLlmProvider GameObject at runtime if none exists, but it'd have empty Inspector fields (no tokenApiKey, no MicrophoneStreamer ref). Pre-adding the GameObject in the scene with Inspector fields pre-assigned is the v1 config approach.

**Steps**:
1. In Hierarchy, navigate to `Logic/Modules/ConversationalAI`.
2. Right-click → Create Empty → name it `LiveKitLlmProvider`.
3. With the new GameObject selected, Inspector → Add Component → search "LiveKitLlmProvider" → click to add. (Or drag the .cs file from Project panel into the Hierarchy — same result.)
4. Fill Inspector fields:
   - Live Kit Url: `ws://3.227.63.49:7880`
   - Token Endpoint: `http://3.227.63.49:8001/token`
   - Token Api Key: `9a11fdf5ce05e3cecad28f933d778971`
   - Agent Name: `sophia-agent` (default; leave as-is)
   - Room Name: leave empty (random GUID per session)
   - Participant Identity: leave empty (random GUID per session prefixed with `xr-`)
   - Enable Debug Logging: ✓ (on)
   - Mic Streamer: drag the MicrophoneStreamer GameObject from Hierarchy (Cmd+F → search "MicrophoneStreamer" — under `Logic/Modules/Audio/` in his scene). Drop on this field.
   - Speaker Host: drag the LiveKitLlmProvider GameObject itself (it'll be the parent for `SophiaSpeaker_<sid>` child GameObjects). Optional — null falls back to its own transform.
5. Cmd+S to save scene.

**Verify**: scene file should contain exactly one `m_Name: LiveKitLlmProvider` line and exactly one component reference to the script GUID. Cross-check by grepping the scene file.

---

## 6. Environmental conflicts hit during integration

### Conflict A — ARCore Extensions vs LiveKit SDK Google.Protobuf duplication (RESOLVED by XR engineer)

**Symptom**: after adding LiveKit SDK to manifest, ARCore Extensions Editor scripts failed to compile with `error CS0234: The type or namespace name 'Protobuf' does not exist in the namespace 'Google'`. Unity blocked add-component operations because Editor scripts couldn't compile.

**Root cause**: BOTH ARCore Extensions and LiveKit SDK ship their own bundled `Google.Protobuf.dll`. ARCore's Editor asmdef relies on Unity's folder-local auto-detection (`precompiledReferences: []`) which fails when multiple Protobuf DLLs exist in the project, even with disjoint platforms.

**Resolution**: XR engineer directly removed the `com.google.ar.core.arfoundation.extensions` package + Samples folder from his manifest. His AR functionality lives in AR Foundation + `com.unity.xr.arcore` + ARKit + XR Hands + OpenXR — Extensions specifically adds Geospatial Creator + analytics, neither of which his app depends on.

**Repercussions**: ARCore Extensions Samples folder (50+ files) deleted from the work clone. Visible in our PR. Should be flagged in PR description as a separate concern, NOT part of our LiveKit changes.

**Full story**: `Q28` in `project_complete_doubts.md`.

### Conflict B — LiveKit SDK v1.3.7 API surface I initially guessed wrong (7 mismatches)

When I drafted `LiveKitLlmProvider.cs` against signatures inferred from our older `sophia-glasses/client-sdk-unity/` reference, 7 mismatches surfaced as compile errors against v1.3.7. Fixed via:

1. **Ambiguous `RoomOptions` / `YieldInstruction`** (both also in `LiveKit.Proto`) → qualify with `global::LiveKit.RoomOptions` etc.
2. **`ConnectInstruction` / `PublishTrackInstruction` / `ReadAllInstruction` not awaitable as Task** (they inherit `CustomYieldInstruction`) → added `AwaitYield` helper that polls `IsDone` via `Task.Yield()`.
3. **`Room.Dispose()` doesn't exist in v1.3.7** → only `Disconnect()`. Drop the Dispose call; FfiHandle finalizer handles cleanup.
4. **`DataPublishOptions` doesn't exist** → `LocalParticipant.PublishData(byte[], topic: string)` with named topic param, void return.
5. **`TextStreamReader.ReadAllAsync()` doesn't exist** → `reader.ReadAll()` returns `ReadAllInstruction` with `.Text` after `.IsDone`.
6. **`YieldInstruction` namespace shadow** because our namespace ends in `LiveKit` → `global::LiveKit.YieldInstruction`.
7. **Missing `using Sophia.ConversationalAI.Config;`** → `ProviderConfig` couldn't be found. The class is in `namespace Sophia.ConversationalAI.Config`, NOT `Sophia.ProviderConfiguration` (which is the ASSEMBLY name — different from the namespace).

Full diagnostic + correct patterns documented in `Q29`.

### Conflict C — Three-enum dispatch chain (the silent OpenAI fallback)

After fixing Conflict B, the integration code compiled clean, but when the user selected LiveKit in the Provider Configuration Manager dropdown, the runtime silently dispatched to OpenAI. `[DEBUG_0604_LiveKit]` tags didn't appear in console.

**Root cause**: his `ProviderConfig` architecture has FOUR places that need to know about a new provider, not one:
- Layer 1 (UI enum): `CustomizedLooseConversationProvider` — what the dropdown reads.
- Layer 2 (bundle): `customizedEndpointsBundle` ScriptableObject + its `CustomizedAwsConversationBackend` enum — OVERRIDES Layer 1 if assigned.
- Layer 3 (runtime enum): `ConversationProviderType` — what the factory switches on.
- Layer 4 (converter): `CustomizedLooseConversationProvider.ToConversationProviderType()` extension method — with `_ => ConversationProviderType.OpenAI` default that silently catches missing cases.

I'd only added LiveKit to Layer 3 yesterday. Today added Layer 1 + Layer 4 converter + cleared the Layer 2 bundle in `ProviderConfig.asset`. Full architecture analysis + lessons in `Q30`.

### Conflict D — Unity 6 HTTP block

After fixing Conflict C, our `LiveKitLlmProvider.Initialize()` started firing. Then `ConnectAsync` errored with `System.InvalidOperationException: Insecure connection not allowed`. Unity 6's new default blocks HTTP requests. Fix: Player Settings → Allow downloads over HTTP → "Always allowed" (`insecureHttpOption: 2`). Full story in `Q31`.

---

## 7. Smoke test — what proves end-to-end works

### Client-side verification (Unity console)

Filter the Console (top-right search box) for `[DEBUG_0604_LiveKit]`. Expected log sequence when Play starts with LiveKit selected:

```
[DEBUG_0604_LiveKit] Initialize: liveKitUrl='ws://3.227.63.49:7880' tokenEndpoint='http://3.227.63.49:8001/token' agentName='sophia-agent'
[DEBUG_0604_LiveKit] ConnectAsync completed.
[DEBUG_0604_LiveKit] mic uplink published.
[DEBUG_0604_LiveKit] ParticipantConnected: agent-AJ_AEBd84m8of6k
[DEBUG_0604_LiveKit] agent audio track subscribed sid=TR_AMuufZpCjXpDAv identity=agent-AJ_AEBd84m8of6k
```

Absence of any of these = something's broken at that step.

### EC2-side verification (SFU + agent-worker logs)

SSH to EC2 and check today's log activity:
```bash
ssh sophia-gpu "cd /workspace/avinash/sophia && docker compose logs --tail 100 livekit-server agent-worker | grep $(date +%Y-%m-%d)"
```

Expected log lines (proven during 2026-06-05T14:00 smoke test, see `Q32`):
- **token-mint**: `POST /token HTTP/1.1 200 OK` from your Mac's external IP.
- **livekit-server**: `starting RTC session, participant=xr-<guid>, client SDK=UNITY, version=1.3.7`.
- **livekit-server**: `assigned job to worker, jobID=AJ_..., agentName=sophia-agent`.
- **livekit-server**: `starting RTC session, participant=agent-AJ_..., client SDK=PYTHON`.
- **livekit-server**: `mediaTrack published, participant=xr-<guid>, source=MICROPHONE` AND `participant=agent-AJ_..., source=MICROPHONE`.
- **livekit-server**: `participant active, connectionType: udp, agent connectTime ~250ms, mac connectTime ~800ms`.
- **agent-worker**: `received job request, job_id=AJ_..., agent_name=sophia-agent`.

If the EKS port-forward is NOT running (as was the case during today's verification), expect agent-worker to ALSO show:
```
agent-worker: "failed to recognize speech: Connection error, retrying in 0.1s"
agent-worker: "AgentSession is closing due to unrecoverable error: Connection error"
```

This is expected and proves everything BEFORE the inference call is working.

### Full voice loop verification (after port-forward is started)

1. On EC2: `cd /workspace/avinash/sophia && ./infra/pf-gpu.sh start` (or his exact runbook command — see `mvp_deployment_shared_ec2.md` cold-start sequence). STS credentials may need re-export.
2. Verify Whisper / Qwen3 / Kokoro all reachable from localhost on EC2.
3. In Unity, hit Play with LiveKit selected.
4. Speak: "What manuals do you have?"
5. Expected: Sophia transcribes (Whisper STT), retrieves RAG context (sophia-spatial-ai /retrieve), generates response (Qwen3), TTS audio plays (Kokoro). Console shows `[DEBUG_0604_LiveKitLegs]` metrics events for each leg of latency. HUD updates if his app's HUD scene component is wired.

---

## 8. PR contents — what to commit, what to exclude

### Files to include in PR (14 total)

**Code added (4 files, including auto-generated meta files)**:
1. `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs`
2. `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs.meta`
3. `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/MicrophoneStreamerAudioSource.cs`
4. `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/MicrophoneStreamerAudioSource.cs.meta`

**Auto-generated folder meta (1 file)**:
5. `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit.meta`

**Code modifications (4 files)**:
6. `Sophia_Wearable/Assets/_Scripts/Modules/ProviderConfiguration/ProviderConfig.cs` (the 3 sub-changes from Change 4)
7. `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Core/ProviderFactory.cs`
8. `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Core/ConversationalAIController.cs`
9. `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Sophia.ConversationalAI.asmdef`

**Config + scene modifications (5 files)**:
10. `Sophia_Wearable/Packages/manifest.json` (UPM Git URL added; ARCore Extensions removed — separate concern, flag in PR)
11. `Sophia_Wearable/ProjectSettings/ProjectSettings.asset` (insecureHttpOption: 2)
12. `Sophia_Wearable/Assets/Resources/ProviderConfigurations/ProviderConfig.asset` (activeConversationProvider: 5 + customizedEndpointsBundle cleared)
13. `Sophia_Wearable/Assets/Resources/ProviderConfigurations/ProviderConfig.asset.meta` (Unity touches this on modify)
14. `Sophia_Wearable/Assets/_Scenes/Sophia_Wearables.unity` (LiveKitLlmProvider GameObject + Inspector wiring)

### Files to EXCLUDE from PR (Unity-incidental noise)

- `Sophia_Wearable/.vscode/` — IDE settings folder.
- `Sophia_Wearable/Sophia_Wearable.slnx` — auto-generated solution.
- Any `*.log` files (runtime log content).
- Any `*.log.meta` deletions.
- `Sophia_Wearable/Assets/_Scripts/Core/Logs/MiscLogs/*` runtime log files Unity touched.
- `Sophia_Wearable/Assets/_Visuals/Models/SantaFe/3DModelsOrg/Materials/redglass.mat` — Unity touched this during reimport, not our concern.
- Misc `.meta` deletions for files that no longer exist (Unity will regenerate as needed).

### Separate concern to FLAG in PR description (not lumped with our changes)

- **ARCore Extensions Samples folder deletion (~50 files)** — Avinash, working with XR engineer, removed the `com.google.ar.core.arfoundation.extensions` package from the manifest to resolve the Google.Protobuf conflict with LiveKit SDK. Unity then cleaned up the Samples folder for that package. This is HIS decision, included in our branch because we share the work-clone, but it should be flagged as a separate concern in the PR description so reviewers understand it's not part of the LiveKit integration code.

### Selective `git add` workflow (DO NOT `git add -A`)

```bash
cd /Users/avinashbolleddula/Documents/repos/Sophia_Xreal-U2-main

# Add new files
git add Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/

# Add code modifications
git add Sophia_Wearable/Assets/_Scripts/Modules/ProviderConfiguration/ProviderConfig.cs
git add Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Core/ProviderFactory.cs
git add Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Core/ConversationalAIController.cs
git add Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Sophia.ConversationalAI.asmdef

# Add config + scene
git add Sophia_Wearable/Packages/manifest.json
git add Sophia_Wearable/ProjectSettings/ProjectSettings.asset
git add Sophia_Wearable/Assets/Resources/ProviderConfigurations/ProviderConfig.asset
git add Sophia_Wearable/Assets/Resources/ProviderConfigurations/ProviderConfig.asset.meta
git add Sophia_Wearable/Assets/_Scenes/Sophia_Wearables.unity

# Add the ARCore Extensions Samples deletions (the XR engineer's separate change)
# These are deletions of files that no longer exist:
git add -u "Sophia_Wearable/Assets/Samples/ARCore Extensions/"

# Verify the staged set
git status

# Commit with the prepared message (see template below)
git commit -m "..."

# Push to our branch
git push origin avinash/livekit-provider
```

### Commit message template

```
feat(conversational-ai): add LiveKit provider for self-hosted WebRTC voice agent

Implements ILLMProvider against LiveKit Unity SDK v1.3.7. Adds a new
ConversationProviderType.LiveKit option that routes voice through a
LiveKit SFU + LiveKit Agents framework backend (currently MVP on EC2 at
3.227.63.49). Mic uplink uses a custom RtcAudioSource that wraps the
existing MicrophoneStreamer so device-selection + AEC tuning is
preserved. Audio downlink and text-stream subscriptions follow the
agent-only identity-prefix pattern.

New files:
- Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs
- Modules/ConversationalAI/Providers/LiveKit/MicrophoneStreamerAudioSource.cs

Modified:
- ProviderConfig.cs: LiveKit added to ConversationProviderType (runtime) +
  CustomizedLooseConversationProvider (UI dropdown) + converter mapping
- ProviderFactory.cs: CreateLiveKitProvider() + new switch case
- ConversationalAIController.cs: bypass byte[] mic forwarding for LiveKit
- Sophia.ConversationalAI.asmdef: LiveKit assembly reference
- Packages/manifest.json: UPM Git URL for LiveKit SDK v1.3.7
- Sophia_Wearables.unity: LiveKitLlmProvider GameObject in scene
- ProviderConfig.asset: LiveKit selected + customizedEndpointsBundle cleared
- ProjectSettings.asset: insecureHttpOption=2 for EC2 MVP HTTP

Smoke test verified via EC2 SFU logs 2026-06-05T14:00 UTC: token mint
200 OK, SFU connect, agent dispatch with agent- prefix identity, both
audio tracks published, ICE UDP negotiation succeeded. Full voice loop
pending EKS port-forward startup (infrastructure state, not code).

NOTE: ARCore Extensions package + its Samples folder removed in this
branch (decided by XR engineer) to resolve a Google.Protobuf.dll
conflict with LiveKit SDK's bundled DLL. His AR functionality lives in
AR Foundation + com.unity.xr.arcore + ARKit + XR Hands + OpenXR — none
of which are affected. ARCore Extensions specifically added Geospatial
Creator + SDK analytics, neither of which his app uses.

Long-term cleanup (not blocking this PR):
- Extend CustomizedAwsConversationBackend enum + CustomizedEndpointsBundle
  .ToConversationProviderType() to support LiveKit, so endpoint bundles
  can be re-enabled for LiveKit users.
- Revert insecureHttpOption to 0 (Not allowed) once Phase 2 production
  AWS deployment puts TLS in front of token-mint + SFU.

Refs: Q25, Q28, Q29, Q30, Q31, Q32 in research repo
docs/internal/project_complete_doubts.md.
```

---

## 9. Open items + future work

**Immediate (after EKS port-forward starts ~11 AM CST)**:
1. Re-run full voice loop test. Expected to work end-to-end.
2. Measurement spike (Q16 + Q26): same client, same scene, flip Active Conversation Provider between LiveKit and AWS Voice Step. Measure latency on each. Record numbers in `Q25` under a new "Smoke test + measurement results" subsection.
3. Commit + push to `avinash/livekit-provider`.
4. Open PR to `AIPartnersUSA/Sophia_Xreal-U2:development`.

**Long-term cleanups (separate PRs after merge)**:
- Extend `CustomizedAwsConversationBackend` enum + `CustomizedEndpointsBundle.ToConversationProviderType()` to know about LiveKit, so endpoint bundles can be re-enabled for LiveKit users (currently they're cleared).
- Phase 2 backend migration: when infra team deploys production AWS with TLS, swap URLs in Inspector (no code change) and revert `insecureHttpOption` to 0.
- Refactor LiveKitLlmProvider config from `[SerializeField]` Inspector fields to read from a new `LiveKitProviderSettings` ScriptableObject (mirrors `OpenAISettings.asset` pattern).
- Add vision support via composite-defer-to-GoogleVisionProvider (currently `SendImageAsync` is a no-op, matching VoiceRelay).
- Re-enable ARCore Extensions if Geospatial Creator becomes needed: embed the package locally + add `"Google.Protobuf.dll"` to its Editor asmdef precompiledReferences with `overrideReferences: true`.

**Tooling polish**:
- Add per-leg latency telemetry in `[DEBUG_0604_LiveKitLegs]` prefix lines, mirroring VoiceRelay's `[DEBUG_0605_VoiceRelayLegs]` shape. Hook into LiveKit Agents framework's `metrics` events.
- Optional: rich error events with `ErrorStage` set to `"stt"` / `"llm"` / `"tts"` based on which inference call failed.

---

## 10. Quick-reference appendices

### Appendix A — Key paths

- **Work clone**: `/Users/avinashbolleddula/Documents/repos/Sophia_Xreal-U2-main/`
- **Branch**: `avinash/livekit-provider` (off `development`)
- **Unity project**: `Sophia_Wearable/`
- **Main scene**: `Assets/_Scenes/Sophia_Wearables.unity`
- **Our code lives**: `Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/`
- **LiveKit SDK cache**: `Library/PackageCache/io.livekit.livekit-sdk@270adc1cbceb/` (commit hash = v1.3.7 tag target)
- **ProviderConfig asset**: `Assets/Resources/ProviderConfigurations/ProviderConfig.asset`
- **Reference clone (read-only)**: `/Users/avinashbolleddula/Documents/sophia Agent Research/Sophia_Xreal-U2/`
- **Our research repo**: `/Users/avinashbolleddula/Documents/sophia Agent Research/`
- **EC2 backend**: `ssh sophia-gpu`, workspace `/workspace/avinash/sophia/`

### Appendix B — Connection values

- **LiveKit SFU URL**: `ws://3.227.63.49:7880`
- **Token-mint URL**: `http://3.227.63.49:8001/token`
- **Token API key**: `9a11fdf5ce05e3cecad28f933d778971` (X-API-Key header)
- **Agent name**: `sophia-agent` (matches sophia-agent/src/agent.py `@server.rtc_session(agent_name="sophia-agent")`)
- **Agent identity prefix at runtime**: `agent-` (LiveKit Agents framework default, e.g., `agent-AJ_AEBd84m8of6k`)

### Appendix C — Text-stream topics

- `sophia.agent_events` — kind-tagged events: `user_transcript`, `agent_state`, `user_state`, `metrics`, `error`, `close`, `speech_created`, `tools_executed`, `false_interruption`. Defined in `sophia-agent/src/agent.py`.
- `sophia.rag_result` — RAG retrieval chunks (sources + scores).
- `lk.transcription` — LiveKit framework default; carries both user + agent transcribed text.

Our `LiveKitLlmProvider.ConnectAsync` registers handlers for all three before `Room.Connect`.

### Appendix D — Common troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No `[DEBUG_0604_LiveKit]` in console after Play | Bundle still assigned in ProviderConfig.asset | Clear `customizedEndpointsBundle` field in Inspector (set to None) |
| Dropdown doesn't show LiveKit | `CustomizedLooseConversationProvider` enum doesn't have LiveKit added (Change 4b) | Verify enum extension; Cmd+R to force recompile |
| Selecting LiveKit silently routes to OpenAI | Converter (Change 4c) missing the LiveKit case | Add `CustomizedLooseConversationProvider.LiveKit => ConversationProviderType.LiveKit` to switch |
| `Insecure connection not allowed` error | Unity 6 HTTP block | Player Settings → Allow downloads over HTTP → "Always allowed" |
| `RoomOptions ambiguous` compile error | Both `LiveKit.RoomOptions` and `LiveKit.Proto.RoomOptions` exist | Use `new global::LiveKit.RoomOptions()` |
| `YieldInstruction` ambiguous or "doesn't exist in namespace Sophia.ConversationalAI.Providers.LiveKit" | Namespace shadow (our namespace ends in LiveKit) | Use `global::LiveKit.YieldInstruction` |
| `Room does not contain Dispose` | v1.3.7 has no Dispose; older SDKs did | Drop `_room.Dispose()`, rely on FfiHandle finalizer + Disconnect |
| `failed to recognize speech: Connection error` in agent-worker logs | EKS port-forward not running on EC2 | SSH to EC2, start port-forward (`./infra/pf-gpu.sh start` or similar) |
| `Google.Protobuf` not found in ARCore Editor scripts | LiveKit + ARCore both ship Protobuf.dll | XR engineer's resolution: drop ARCore Extensions from manifest (his AR uses AR Foundation directly) |
| ProviderConfig.asset shows old enum value after enum addition | Unity dropdown UI cache | Right-click asset → Reimport, or Cmd+R |
| ConfigProvider can't find type | Missing `using Sophia.ConversationalAI.Config;` | Add the using directive at top of file |
| Compile errors after Library/PackageCache regenerates | SDK re-resolved with empty cache | Wait for Unity to download SDK + recompile (first open takes ~1 min for SDK fetch) |

### Appendix E — Cross-references

For deeper understanding of specific decisions:
- `Q12` — why LiveKit at all (over PTT/WSS alternatives)
- `Q15` — locked phase plan
- `Q16` — measurement-spike framing (LiveKit vs VoiceRelay)
- `Q17` — initial integration plan + 7 open questions for XR engineer
- `Q23` — vision behavior decision (no-op matching VoiceRelay)
- `Q25` — running integration journal (what's done, what's next)
- `Q26` — Phase 2 comparison framing
- `Q27` — UPM Git URL vs vendor-copy SDK install decision
- `Q28` — ARCore Extensions vs Google.Protobuf conflict + resolution
- `Q29` — 7 LiveKit SDK v1.3.7 API mismatches I got wrong + correct patterns
- `Q30` — three-enum dispatch chain discovery (THE one we missed yesterday)
- `Q31` — Unity 6 HTTP block + Player Settings fix
- `Q32` — smoke test SUCCESS proof via EC2 logs
- `Q33` — audible voice loop CONFIRMED + the in-app start button is required for ALL providers
- `Q34` — Sophia text streaming attempts (conversation_item_added / speech_created / llm_node) — current OPEN issue
- `Q35` — user-side real-time transcript blocked by Whisper batch STT (Phase 1.5 infra decision)
- `Q36` — EKS port-forward flakiness recovery procedure
- `Q37` — Mac screen recording system audio capture options
- `Q38` — backend agent.py 2026-06-05 changes recap (for tomorrow's context recovery)
- `Sophia_Xreal-U2.md` — architecture survey of his entire repo
- `livekit_doubts.md` — older LiveKit framework + debugging Q&A (Q1-Q62)
- `livekit_architectur_ec2.md` — end-to-end architecture of our EC2 backend

---

## Appendix F — 2026-06-05 backend transcript-streaming additions (WIP)

Three additions on top of the original 10 client-side integration changes. **These live on the BACKEND** (`sophia-agent/src/agent.py`), not in the XR engineer's repo.

### Backend change 1 — `conversation_item_added` event handler

Publishes Sophia's FINAL spoken text via `sophia.agent_events` topic with `kind="agent_transcript"` and `is_final=True`. Fires after TTS finishes. Final-only display (delayed captions).

### Backend change 2 — `speech_created` event handler (extended)

Existing handler extended to try extracting `ev.speech_handle.chat_items`. DEBUG log proves `chat_items` is empty at this event (`items=0`), so no interim publish actually fires. Dead code on disk; cleanup pending after Q34 resolves.

### Backend change 3 — `Assistant.llm_node` method override

Attempts to publish streaming text chunks AS Qwen3 emits them, with `is_final=False`, throttled to every ~8 chars. **NOT YET WORKING** as of 2026-06-05 session end — user tested, still sees text only after speech ends. Open hypotheses tracked in Q34.

### Client-side counterpart change

`LiveKitLlmProvider.OnAgentEventsMessage` got one new switch case (`case "agent_transcript":`) which fires `OnTranscriptReceived` with `Type=Agent` and `IsComplete=is_final`. This is THE ONLY client-side change needed for transcript rendering; backend changes do the heavy lifting.

### Tomorrow's pickup

Per Q34, walk these hypotheses in order: (1) confirm `llm_node` entry via top-of-function log, (2) inspect first chunk's repr to verify `delta.content` shape, (3) test with throttle threshold = 1 char, (4) compare against how his OpenAI Realtime provider renders interim agent transcripts (he has a working precedent — may use a different event API).
