# sophia-glasses reading guide

Stepped path for understanding the Unity client end-to-end: mic, speaker, UI, connections, configs, builds. Read top to bottom; each step builds on the previous one. Total time to internalize all of it: about an hour if you're new to Unity, 20-30 min if you've shipped a Unity project before.

## Folder map (what lives where)

```
sophia-glasses/
├── README.md                      <- one-page elevator pitch (read first)
├── AGENTS.md                      <- conventions: uv, ruff, lk docs, code rules
├── HUD_direction_a.md             <- current AR HUD design spec (subtitle-minimal)
├── READING_GUIDE.md               <- this file
├── client-sdk-unity/              <- LiveKit Unity SDK source (READ-ONLY reference,
│                                     installed from local disk per Packages/manifest.json)
└── unity/                         <- the Unity project itself
    ├── Assets/
    │   ├── Scripts/               <- ★ THE FIVE SCRIPTS — everything we wrote
    │   │   ├── SophiaConfig.cs            <- ScriptableObject schema for settings
    │   │   ├── SophiaConfig.cs.meta
    │   │   ├── SophiaSessionContext.cs    <- static runtime state across picker + connection
    │   │   ├── SessionPicker.cs           <- launch UI: Private / Team session selection
    │   │   ├── SophiaConnection.cs        <- voice loop: connect, mic publish, audio play
    │   │   └── SophiaOverlayUI.cs         <- world-space AR HUD (Direction A layout)
    │   ├── Settings/
    │   │   └── SophiaConfig.asset         <- instance of SophiaConfig (Tailscale URL etc.)
    │   ├── XR/Settings/XREALSettings.asset <- XREAL SDK config (auto-logcat, stereo mode)
    │   ├── Plugins/
    │   │   ├── Google.Protobuf.dll        <- LiveKit FFI dep, manually dropped
    │   │   └── Android/AndroidManifest.xml <- Custom Main Manifest (Q55 + Q54)
    │   ├── TextMesh Pro/                  <- TMP Essentials, auto-imported
    │   └── Scenes/sophia-scene.unity      <- the scene loaded at app launch
    ├── ProjectSettings/
    │   ├── AudioManager.asset             <- m_SampleRate 48000, Stereo
    │   ├── ProjectSettings.asset          <- bundle id, orientation, min SDK, etc.
    │   ├── EditorBuildSettings.asset      <- scene list for the APK
    │   └── ...
    ├── Packages/
    │   └── manifest.json                  <- UPM deps incl. XREAL + LiveKit SDK
    └── sophia-glasses.apk                 <- the latest build output
```

## Recommended reading order

### Step 1 — The 30-second elevator pitch

Read: `sophia-glasses/README.md`

What you'll learn: why this client exists (XREAL One Pro + Beam Pro Android, paired with the backend in `sophia-agent/`), how it connects to the rest of the project, and the two phases (Phase 1 = voice loop, Phase 2 = AR HUD).

### Step 2 — Conventions and rules

Read: `sophia-glasses/AGENTS.md`

What you'll learn: house rules for this subproject. uv-managed Python where relevant, LiveKit doc lookup via `lk docs search`, custom plugin pattern, file layout.

### Step 3 — The big narrative (skim, then deep-dive selectively)

Read: `unity_approach.md` at the project root (NOT inside sophia-glasses).

What you'll learn: the full ~2500-line story of how this client was built. 21 parts plus 3 appendices. Skim once for the table of contents, then read selectively:

- Parts 0-2 (strategic decisions, pre-flight): why Unity + XREAL SDK over native Kotlin
- Parts 3-7 (scaffolding, packages, token_mint tweak, SophiaConfig, SophiaConnection): the meat of the voice loop
- Parts 8-12 (SDK API quirks, scene, smoke test, working state): the gotchas that surfaced while making Editor Play mode work
- Parts 13-16 (Beam Pro migration, APK build, install, mic permission race, sample-rate trap): everything that broke when moving from Mac Editor to actual Android
- Part 17 (Phase 2 HUD first cut): how the AR overlay got built (note: this is the OLD 3-panel layout; the new Direction A layout supersedes it but the runtime-construction pattern is unchanged)
- Part 19 (Problems index, 18 distinct issues with symptom -> cause -> fix): scan this when something breaks; it probably already happened once
- **Appendix B (operational runbook): the actual 9-step sequence from "APK built" to "talking through glasses". Bookmark this.**
- Appendix C (multi-user discussion): Scenario A vs B reasoning

### Step 4 — Configuration layer (where deployment values live)

Open in this order:

1. `Assets/Scripts/SophiaConfig.cs` — the ScriptableObject schema. Read each `[SerializeField]` and the tooltip on it. EIGHT fields: liveKitUrl, tokenEndpoint, **tokenApiKey** (added 2026-05-29 for shared-EC2 X-API-Key auth — leave empty if your token-mint doesn't enforce it), agentName, roomName, participantIdentity, participantName, microphoneDeviceIndex.
2. `Assets/Settings/SophiaConfig.asset` — the actual instance. Inspect via Unity Inspector (drag the file in). Two reference configurations:
   - Local Tailscale dev: liveKitUrl `ws://100.69.34.194:7880`, tokenEndpoint `http://100.69.34.194:8001/token`, tokenApiKey empty, agentName `sophia-agent`, roomName empty (Scenario B default), microphoneDeviceIndex 0.
   - Shared EC2 demo: liveKitUrl `ws://3.227.63.49:7880`, tokenEndpoint `http://3.227.63.49:8001/token`, tokenApiKey set to the same value as `SOPHIA_TOKEN_API_KEY` on the EC2 `.env.production` file. See `mvp_deployment_shared_ec2.md` for the value-rotation procedure.

Mental model: `SophiaConfig` is the deployment-time settings; `SophiaSessionContext` (Step 5) is the runtime per-session overrides.

### Step 5 — Session state shared across UI and voice loop

Read: `Assets/Scripts/SophiaSessionContext.cs`

What you'll learn: how the picker UI tells the voice-loop layer which mode to start in (Private vs Team) without mutating the config asset at runtime. Two static fields: `CurrentMode` and `RoomOverride`. Reset on session end so the next picker shows fresh.

### Step 6 — The picker UI (launch + end-session flow)

Read: `Assets/Scripts/SessionPicker.cs`

What you'll learn: this is the FIRST thing the user sees when the app launches. Two panels both built at runtime in OnEnable (no Inspector wiring): the picker (landscape two-column card with Private + Team), and the in-session strip (now shrunk to a bottom-right End chip per Direction A). It also creates an EventSystem if missing (otherwise no button clicks register). The whole flow: launch -> picker shows -> user picks -> activates SophiaConnection GameObject -> SophiaConnection.OnEnable runs -> session live -> user taps End -> SetActive(false) on SophiaConnection -> Cleanup() fires -> picker shows again.

Pay attention to `EnsureEventSystem()` -- Unity 6 URP template defaults to the New Input System only, which silently swallows clicks if you don't use `InputSystemUIInputModule` instead of the legacy `StandaloneInputModule`. Reflection-loaded so the code compiles either way.

### Step 7 — The voice loop (the heart of the client)

Read: `Assets/Scripts/SophiaConnection.cs` — read it twice, top to bottom each time.

First read: get the lifecycle. OnEnable -> ConnectFlow coroutine -> token fetch -> Room.Connect -> mic permission -> mic publish -> wait for agent track -> OnTrackSubscribed wires playback. OnDisable -> Cleanup -> mic stop + room disconnect + destroy speaker child GameObjects.

Token fetch detail (added 2026-05-29 for shared-EC2 deploy): the UnityWebRequest POST to `/token` conditionally adds an `X-API-Key` header IF `SophiaConfig.tokenApiKey` is set. Logic in SophiaConnection.cs around the `www.SetRequestHeader("Content-Type", "application/json")` line. Server side enforces this only if env var `SOPHIA_TOKEN_API_KEY` is set on the token-mint container; left empty for local dev, populated for the shared EC2 demo. See livekit_deployment.md Q29 for the auth design + mvp_deployment_shared_ec2.md "Glasses repointing" section for the operational checklist.

Second read: focus on the audio side. The MIC path uses `MicrophoneSource` from the LiveKit Unity SDK (created in `Step 3` of ConnectFlow), wrapped in a `LocalAudioTrack`, published via `room.LocalParticipant.PublishTrack` with `TrackSource.SourceMicrophone`. The SPEAKER path is in `OnTrackSubscribed`: ONLY agent tracks (participant identity starts with `agent-`) get an AudioSource, and that AudioSource lives on a new CHILD GameObject `SophiaSpeaker_<sid>` under `speakerHost` — this is the production-correct multi-user contract from livekit_doubts.md Q58. Other users' raw mic tracks are subscribed-but-never-played-locally.

Three key things this file does NOT do (separation of concerns):
- It does NOT build UI. That's SophiaOverlayUI's job.
- It does NOT pick rooms. That's SessionPicker's job; SophiaConnection just reads `SophiaSessionContext.RoomOverride`.
- It does NOT speak directly to AWS. It only talks to the SFU; the agent worker on the Mac is what talks to the inference services.

Important static event: `OnTextStreamMessage` is fired whenever any subscribed text-stream topic emits a message. SophiaOverlayUI listens to this without holding any reference back to SophiaConnection. Decouples UI from connection lifecycle.

### Step 8 — The AR HUD (Direction A, current design)

Read in order:
1. `HUD_direction_a.md` — the design spec. Layout sketch, per-element behaviour, turn-by-turn timeline. Read this BEFORE the code so you know what the code is implementing.
2. `Assets/Scripts/SophiaOverlayUI.cs` — the actual MonoBehaviour. Walk through OnEnable (builds canvas + state dot + subtitle + chips container), then HandleTextStream (router for the three text-stream topics), then SetAgentState / ShowSubtitle / ShowRagChips (the rendering functions), then FadeTo (the 200ms smoothstep coroutine), then ExtractJsonString + ExtractHits (the homemade JSON parsers).

Three things to internalize about the HUD layer:
- World-space Canvas parented to Camera.main at 2 m focal distance. Head-locked: turn your head, the HUD follows.
- Procedural circle sprite generated at runtime for the dot (so we don't depend on a sprite asset).
- All animations via CanvasGroup.alpha + coroutine. No DOTween, no animation clips.

### Step 9 — Project settings that matter

Open these files (text editor or Unity Inspector):

1. `ProjectSettings/AudioManager.asset` — `m_SampleRate: 48000`, `Default Speaker Mode: 2` (Stereo). On macOS this is NOT enforced; must also set Audio MIDI Setup format on the active output device (Q52).
2. `ProjectSettings/ProjectSettings.asset` — bundle id (still `com.UnityTechnologies.com.unity.template.urpblank`; rename to `com.sophia.glasses` is Phase 2 hardening), AndroidMinSdkVersion 29, insecureHttpOption 2, microphoneUsageDescription, default orientation Landscape Left.
3. `ProjectSettings/EditorBuildSettings.asset` — which scenes are included in the build. Only `sophia-scene.unity` should be there (position 0). If you ever see two scenes here or the wrong one at position 0, the APK loads the wrong scene.
4. `Assets/XR/Settings/XREALSettings.asset` — XREAL SDK config. `EnableAutoLogcat: 0` (off, but the AAR's ContentProvider auto-runs anyway per Q54). `StereoRendering` mode. `SupportMultiResume`.
5. `Assets/Plugins/Android/AndroidManifest.xml` — Custom Main Manifest. Declares the full UnityPlayerGameActivity (BaseUnityGameActivityTheme, exported=true, etc.) plus the `<provider tools:node="remove"/>` directive for the XREAL Auto Logcat ContentProvider. Per Q55.

### Step 10 — The SDK reference (when you need to know what LiveKit actually does)

`sophia-glasses/client-sdk-unity/Runtime/Scripts/` — read these files when:

- You wonder how a specific method behaves. Read it. The SDK is plain C#.
- The compile errors after an SDK upgrade. Diff this folder against the install source.

Key files:
- `Room.cs` — connection, room state, participant/track events.
- `RtcAudioSource.cs` — the base class for audio sources, the one that registers `_expectedSampleRate` and `_expectedChannels`. This is where the Q52 sample-rate trap symptom comes from.
- `MicrophoneSource.cs` — subclass of RtcAudioSource that wraps Unity's `Microphone.Start`. Note the hardcoded `base(2, ...)` channel count.
- `AudioStream.cs` — bridges a `RemoteAudioTrack` into a Unity `AudioSource` for playback.
- `Internal/AudioProbe.cs` — the MonoBehaviour that uses `OnAudioFilterRead` to capture audio data from an AudioSource. ONE AudioSource per GameObject, hence Q58's child-GameObject pattern.

Do NOT modify anything in `client-sdk-unity/`. It's a vendored read-only reference.

### Step 11 — Build and run (operational)

Read: `unity_approach.md` Appendix B end-to-end.

This is the 9-step sequence from "I opened Unity, made a change" to "I'm wearing glasses and hearing Sophia". It covers backend bring-up, USB pairing, APK install, the first-launch permission grant dance, wireless adb setup, glasses plug-in, and the iterative 3-command rebuild loop. Bookmark it.

Also: `steps_to_run.md` at the project root gives the same operational sequence as a quick-reference cheat sheet.

## Quick-reference: where does X happen?

| You want to know about... | Read this |
|---|---|
| Where the room name is decided | `SophiaConnection.OnEnable` (lines around the `_resolvedRoom` assignment) |
| How tokens are obtained | `SophiaConnection.ConnectFlow` Step 1 + `sophia-agent/src/token_mint.py` on the backend |
| How the mic is captured and published | `SophiaConnection.ConnectFlow` Step 3 + `client-sdk-unity/.../MicrophoneSource.cs` |
| How Sophia's audio plays back | `SophiaConnection.OnTrackSubscribed` + `client-sdk-unity/.../AudioStream.cs` |
| Why multiple users don't echo each other's mic | `SophiaConnection.OnTrackSubscribed` agent-only filter + livekit_doubts.md Q58 |
| Why the picker UI is two columns landscape | `SessionPicker.BuildPickerPanel` + livekit_doubts.md Q49 |
| Why the HUD subtitle text matches Sophia's TTS word-by-word | `SophiaConnection.LogTextStream` (ReadIncremental) + livekit_doubts.md Q50 |
| Why the state pill / RAG chips actually populate from agent payloads | `SophiaOverlayUI.ExtractJsonString` whitespace tolerance + livekit_doubts.md Q51 |
| Why Editor Play mode crashes on sample rate | livekit_doubts.md Q42 + Q52 (macOS Audio MIDI Setup) |
| Why the AR HUD is head-locked | `SophiaOverlayUI.BuildCanvas` — world-space canvas parented to Camera.main |
| Why the APK installs as Unity template package name | bundle id rename is Phase 2 hardening; still `com.UnityTechnologies.com.unity.template.urpblank` |
| Why the red XREAL log overlay appears | livekit_doubts.md Q54 — open, deferred |
| Build APK and install | `unity_approach.md` Appendix B Step 1 + 2 + 9 |
| Wireless adb setup | `unity_approach.md` Appendix B Step 7 |

## Mental model summary

Two layers in this client:

1. **Connection layer** (`SophiaConnection.cs` + `SophiaConfig.cs/.asset` + `SophiaSessionContext.cs`)
   - Owns: room connection, mic capture, agent audio playback, text-stream subscriptions
   - Knows nothing about UI
   - Emits a static event `OnTextStreamMessage(topic, identity, payload)` for any UI to listen to

2. **UI layer** (`SessionPicker.cs` + `SophiaOverlayUI.cs`)
   - SessionPicker controls activation of the connection layer (SetActive on the SophiaConnection GameObject)
   - SophiaOverlayUI subscribes to the connection layer's static event and renders HUD elements
   - UI never reaches into the connection layer's internals

Three text-stream topics flowing from agent to client:
- `sophia.agent_events` — JSON events (agent_state, user_transcript, metrics, ...)
- `sophia.rag_result` — JSON with question/answer/hits/mode
- `lk.transcription` — raw text per turn (user vs agent distinguished by participant identity prefix)

Backend has zero knowledge of which client is connected (browser, glasses, both). The same agent serves all clients identically through the same SFU room model.
