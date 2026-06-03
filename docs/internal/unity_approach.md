# Unity + XREAL Build Approach — End-to-End Narrative

How we got from "web voice agent works in Chrome" to "voice agent + AR HUD working through XREAL One Pro tethered to Beam Pro", step by step, with every decision explained and every problem traced to its root cause and fix.

This document is the narrative; the Q&A files (`livekit_doubts.md` Q26–Q48) and the chronological session log (`sophia-agent/CHAT.md` turns 48–65) are the technical depth. Read this first to understand the shape of the journey, then dive into the others for any specific gotcha.

---

## Part 0 — Where we started

Before any Unity work, sophia-agent's web stack was already fully working:

- `livekit-server` running natively on the Mac at port 7880 (Apache 2.0 OSS, installed via Homebrew)
- `sophia-agent/src/token_mint.py` minting JWTs at port 8001
- `sophia-agent/src/agent.py` running as the voice agent worker (Whisper-large-v3 STT + Qwen3-VL-8B LLM + Kokoro TTS + sophia-spatial-ai `/retrieve` RAG)
- `agent-starter-react` frontend at port 3000 showing the conversation in the browser, with overlay panels (state pill, scrolling event log with per-stage metrics, RAG sources side panel, transcript)

User would open Chrome at `localhost:3000`, click Start Call, talk, Sophia replied. Round-trip ~2-3s. RAG injected manual chunks when the question hit `max_score >= 0.30` against the indexed PDFs (GV70 owner's manual, x250 user guide).

**The end goal of the whole project** is industrial-equipment voice assistant on **XREAL One Pro glasses tethered to an XREAL Beam Pro Android device** — not the browser. The web stack was the validation that the backend works. Now we needed to build the glasses client.

---

## Part 1 — Strategic decisions made before any code was written

These were settled in turns 48-54 before scaffolding started.

### Decision 1: Unity, not native Kotlin

Two paths considered:

- **Native Kotlin app**: Uses the official `livekit-android` SDK + NRSDK directly. Simpler for pure 2D UI. Native Android dev tooling.
- **Unity + XREAL SDK 3.1.0**: Heavier framework. Cross-platform potential. Native 3D/AR support.

**Picked Unity** because the project's roadmap includes Phase 2 (head-locked AR UI panels) and Phase 3 (XREAL Eye camera + image-based vision RAG with 3D overlay). Native Kotlin would get us through Phase 1 faster but then we'd have to rebuild the rendering pipeline for AR. Unity bakes AR rendering in via XREAL's XR Plug-in Management. One platform, one codebase, scales to the full roadmap.

### Decision 2: Phased build, voice-only first

Alternative was "build Phase 1 + Phase 2 together so user sees overlays from day one". Rejected because:

- Audio working through the glasses is the high-risk milestone (echo, sample rate, mic permission, network reachability all unknown).
- AR UI is low-risk (Unity canvas + text components, well-trodden territory).
- De-risk audio first; then the UI is a known-effort add-on.

So Phase 1 = voice loop only, plain camera, no overlays. Phase 2 = add the overlays.

### Decision 3: Don't touch the backend from the glasses client

Hard rule baked into `sophia-glasses/AGENTS.md`: this project is a CLIENT only. Backend stays exactly as web-app uses it. If the backend needs a change, do it in `sophia-agent/` and update its CHAT.md.

Why: the web frontend and the glasses client must work simultaneously, possibly even in the same LiveKit room (Scenario A). Diverging the backend per client breaks that.

The one exception we had to make was adding optional `agent_name` field to token_mint, because non-web clients had no way to trigger agent dispatch on their own. That's documented in CHAT.md turn 58 and the token_mint comments.

### Decision 4: Modular MonoBehaviours

`sophia-glasses/AGENTS.md` convention: each MonoBehaviour subscribes to ONE data source (a text-stream topic, a LiveKit event, an NRSDK input) and renders to ONE UI panel or performs ONE side effect. No component knows about another component.

Why: Phase 2 adds UI panels one at a time; if they're decoupled, we add/remove without ripple. Also debugging-friendly — one symptom maps to one component.

In practice this meant the voice-loop component (`SophiaConnection.cs`) doesn't know about any UI, and the UI component (`SophiaOverlayUI.cs`) doesn't know about LiveKit internals — they communicate via a single C# static event.

### Decision 5: Scenario A and Scenario B both supported via config

Two production use cases identified in turn 56:
- **Scenario B**: Each user has their own isolated Sophia (different rooms per launch, agent forks per room). Default behavior — `SophiaConfig.roomName` empty = generate `sophia-glasses-<uuid>` per launch.
- **Scenario A**: Multiple users join the same shared room with one shared Sophia (browser + glasses, or two pairs of glasses watching the same conversation). Set `SophiaConfig.roomName` to a fixed value like `maintenance-bay-3`.

Both supported by the same SophiaConfig.cs without code changes. Just change the value of the `roomName` field in the asset.

---

## Part 2 — Pre-flight (everything before any Unity code)

Documented in `livekit_doubts.md` Q26 as the dev-environment writeup. Seven checks, all done before P1-1 scaffolding:

1. **Unity Hub installed** on the Mac. (User opened DMG, dragged to Applications.)
2. **Unity 6.3 LTS editor installed** (version `6000.3.16f1`), with these modules selected during install:
   - Android Build Support
   - OpenJDK (Unity's bundled Java)
   - Android SDK & NDK Tools
   - Reason: we need to build APKs for Android. Without these modules, "Switch Platform to Android" fails.
3. **XREAL SDK 3.1.0 downloaded** from XREAL's developer portal. Distributed as a **UPM tarball** (`com.xreal.xr-3.1.0.tgz`), NOT the older `.unitypackage` format. This was a surprise — older NRSDK 2.x docs reference `.unitypackage`. SDK 3.1.0 install path is Package Manager > Install package from disk > pick the package.json inside the unzipped tarball folder.
4. **Beam Pro adb-connected via USB.** Required: enable Developer Options (tap Build Number 7 times in Settings > About Phone), enable USB Debugging, change USB mode to File Transfer (default Charge Only blocks adb), accept "Allow USB debugging" prompt. Verified via `adb devices` showing `RHLM56L118630F device`.
5. **Network reachability** Mac ↔ Beam Pro. We had Tailscale already on both ends (Mac at `100.69.34.194`, Beam Pro at `100.69.32.120`), so no need to change livekit-server's `--node-ip` config. Verified via `adb shell curl http://100.69.34.194:7880` returning `HTTP 200 OK`.
6. **Wireless adb workaround documented** for when the glasses occupy the Beam Pro's USB-C port (you can't have glasses + adb cable at the same time, only one USB-C jack): `adb tcpip 5555` while still on USB → unplug → plug in glasses → `adb connect 100.69.32.120:5555`.
7. **Web voice loop sanity check**: opened the browser to localhost:3000, joined a room, confirmed voice loop still working end-to-end before disrupting anything.

---

## Part 3 — Scaffolding (P1-1)

Created `sophia-glasses/` directory at the project root, parallel to `sophia-agent/`:

```
sophia Agent Research/
├── sophia-agent/       ← backend (untouched except for token_mint tweak)
├── sophia-glasses/     ← NEW
│   ├── README.md       ← positioning, stack, phased plan
│   ├── AGENTS.md       ← modularity + topic-name + networking conventions
│   └── .gitignore      ← Unity-standard (Library/, Temp/, Logs/, etc.)
```

**Why a separate directory** (vs adding Unity files to sophia-agent): clean separation. sophia-glasses is the CLIENT, sophia-agent is the SERVER. Different language (C# vs Python), different runtime (Android device vs server worker), different deployment (APK vs container). Keeping them apart means each AGENTS.md is short and focused.

No Unity code yet at this stage — just the scaffolding directory + three convention files. AGENTS.md baked in the rules we'd follow: don't touch the backend, default Scenario B but allow Scenario A via config, text-stream topic names MUST match the backend publisher (otherwise the panels render nothing).

---

## Part 4 — Unity project creation (P1-2)

User action in Unity Hub:

1. Hub > Projects > New Project.
2. Editor version: `6000.3.16f1` (the LTS we'd installed).
3. Template: **3D (URP)** — Universal Render Pipeline. Standard modern Unity render path.
4. Project Name: `unity`. Location: `sophia-glasses/`. So the full path becomes `sophia-glasses/unity/`.
5. Click Create. Unity Hub generated the project, ~30s.

**Why URP and not Built-in or HDRP**: URP is the modern default, supports mobile rendering (which Android is), and works with XREAL SDK 3.1.0 out of the box. Built-in is legacy. HDRP is desktop-class, too heavy for Android mobile GPUs.

Initial scene from the template: `Assets/Scenes/SampleScene.unity` — an empty 3D scene with just a Main Camera + Directional Light. We later replaced this with our own `Assets/sophia-scene.unity` (more on that in Part 12).

---

## Part 5 — Package installation (P1-3)

### LiveKit Unity SDK

First attempt: Package Manager > Add package from git URL → `https://github.com/livekit/client-sdk-unity.git`. Imported in ~1 minute. Looked successful.

Hit a problem later (Part 11 detour 5): the SDK's FFI binaries (Rust client compiled to `.dylib`/`.so`/`.dll`, ~17 MB each) are stored in **Git LFS**. Unity Package Manager's git-URL importer does NOT fetch LFS objects. So we ended up with 133-byte text pointer files instead of the real binaries, and `liblivekit_ffi.dylib: slice is not valid mach-o file` at Play time.

Fixed by switching to a local-disk install:

```bash
brew install git-lfs
git lfs install                                   # one-time per machine
git clone https://github.com/livekit/client-sdk-unity.git \
  sophia-glasses/client-sdk-unity                 # ~1 GB clone, ~50 MB binaries
```

Then in Unity: Package Manager > Remove the broken git-URL package → "+" > Install package from disk → pick `sophia-glasses/client-sdk-unity/package.json`. Real binaries this time.

### XREAL SDK 3.1.0

Already downloaded as a UPM tarball during pre-flight. Install: Package Manager > "+" > Install package from disk → pick `~/Downloads/package/package.json` (the directory you get after unzipping the tarball).

### Google.Protobuf 3.27.4

The LiveKit SDK's auto-generated proto code references `Google.Protobuf` types but the SDK doesn't bundle the protobuf runtime DLL. Standard fix is NuGetForUnity — but the missing runtime caused 3000 compile errors, which put Unity into Safe Mode, which hides custom menus including NuGet's. Chicken-and-egg.

Manual workaround:

```bash
mkdir -p /tmp/protobuf && cd /tmp/protobuf
curl -L https://www.nuget.org/api/v2/package/Google.Protobuf/3.27.4 -o protobuf.nupkg
unzip -p protobuf.nupkg lib/netstandard2.0/Google.Protobuf.dll > Google.Protobuf.dll
cp Google.Protobuf.dll '/.../sophia-glasses/unity/Assets/Plugins/Google.Protobuf.dll'
```

Unity auto-detected the new DLL on next focus → 3000 errors cleared → Safe Mode exited.

After the local-disk SDK swap, the SDK's own bundled Google.Protobuf.dll became available too. The two copies didn't conflict (Unity warned but didn't fail). We kept both for safety.

### Why each package

- **LiveKit Unity SDK**: implements WebRTC client + Room/Track APIs + audio I/O bridging from Unity Microphone → LiveKit's Rust FFI → SFU.
- **XREAL SDK 3.1.0**: AR display, head pose, camera, eventually XREAL Eye. For Phase 1 mostly inert — but loading it early so the build chain is ready for Phase 2.
- **Google.Protobuf**: dependency of LiveKit's auto-generated protocol code. Without it, none of the Room/Track classes compile.

---

## Part 6 — Backend tweak: token_mint agent dispatch

This was the ONE backend change we made.

### Problem

In the web stack, the frontend's own token handler (a Next.js route in agent-starter-react) builds the JWT and attaches `RoomConfiguration(agents=[RoomAgentDispatch(agent_name="sophia-agent")])`. That instructs the LiveKit SFU: "when this token's owner joins, automatically dispatch a worker named sophia-agent into the room".

Without that, the agent worker registers as available but doesn't join rooms. The frontend triggers dispatch via the token.

For our Unity client, we use `sophia-agent/src/token_mint.py` directly (no Next.js route in the middle). That endpoint was a simple JWT minter — it didn't know about agent dispatch.

### Fix

Edited `sophia-agent/src/token_mint.py`:

1. Added `agent_name: Optional[str] = "sophia-agent"` to the `TokenRequest` Pydantic model.
2. After building the JWT, if `agent_name` is set, attach the RoomConfiguration:

```python
if req.agent_name:
    token = token.with_room_config(
        api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=req.agent_name)])
    )
```

Then any client (Unity included) that POSTs `{"identity":"...", "room":"...", "agent_name":"sophia-agent"}` gets a JWT that triggers dispatch.

We also fixed a latent bug discovered later: the file used `.with_ttl_seconds(N)` which doesn't exist on `api.AccessToken`. Changed to `.with_ttl(timedelta(seconds=N))`. The webapp never exercised this path so the bug had sat dormant.

### Verification

Smoke-tested with a Python one-liner that calls the same API directly before deploying. Then once the Unity client connected, the agent worker's logs showed `prewarm` + `entrypoint` for the new room — confirming dispatch via JWT was working.

### Example: what the dispatch model looks like in practice

The short version: a LiveKit agent worker only joins rooms it's been *dispatched* to. The JWT can carry the dispatch instruction. Our `token_mint` wasn't including it.

Walk-through.

**The dispatch model**

The agent worker (`sophia-agent/src/agent.py`) is running on the Mac. It registered with the SFU as "available" — but it doesn't join every room that exists. The SFU only tells it to join a room when something requests dispatch. Three ways to request dispatch:

1. Server-side API call (`livekit-server-sdk` → `dispatch_agent`)
2. Explicit agent-side config
3. **Embed the dispatch instruction directly in the JWT that a participant uses to join** — when a token with `roomConfig.agents=[...]` joins a room, the SFU sees that claim and dispatches the named agent

Path 3 is the lightweight one. No extra HTTP calls, no separate orchestration service. The token itself says "when I join, please also wake up this agent for the room".

**The webapp uses Path 3 — but via its OWN TypeScript token route**

When you click Start Call in the browser, agent-starter-react's Next.js route handler builds the JWT in TypeScript and adds the dispatch claim:

```typescript
// agent-starter-react/app/api/connection-details/route.ts
participantToken.attachWithRoomConfig({
  agents: [{ agentName: 'sophia-agent' }],
});
```

The browser gets that JWT, joins the room, the SFU sees the claim, dispatches sophia-agent. You hear Sophia within ~1s.

Our Unity client doesn't talk to that Next.js route — it talks to `sophia-agent/src/token_mint.py`, which is a separate Python equivalent. That Python file was a bare JWT minter — it didn't know about agent dispatch.

**What happened BEFORE the fix**

You'd see this exact sequence in the logs.

Unity client log:
```
[Sophia] Got token (len=457) for url=ws://100.69.34.194:7880
[Sophia] Connection state: ConnConnected
[Sophia] Connected to room 'sophia-glasses-abc123'.
[Sophia] Microphone publishing. You can speak now.
   ↓
(silence forever — no participant joins, no track subscribed, no agent events)
```

Agent worker terminal:
```
INFO  livekit.agents - registered worker {"id": "AW_xxx", "agent_name": "sophia-agent"}
   ↓
(no further logs — worker is idle, waiting for dispatch that never comes)
```

You'd talk → nothing happens. The Unity client connected to a room with nobody else in it.

**Decoded JWT — what was inside**

If you base64-decoded the JWT that token_mint returned (paste a JWT into jwt.io to see), the payload looked like this:

```json
{
  "iss": "devkey",
  "sub": "glasses-2647ecb8",
  "name": "Sophia Glasses User",
  "exp": 1779403600,
  "video": {
    "room": "sophia-glasses-abc123",
    "roomJoin": true,
    "canPublish": true,
    "canSubscribe": true
  }
}
```

Notice: no `roomConfig` claim. The SFU validates the token, lets the client join, but has no instruction to do anything else. The agent worker is never notified.

**What happens AFTER the fix**

Unity client log:
```
[Sophia] Got token (len=457) for url=ws://100.69.34.194:7880
[Sophia] Connection state: ConnConnected
[Sophia] Connected to room 'sophia-glasses-abc123'.
[Sophia] Microphone publishing. You can speak now.
[Sophia] Participant connected: agent-AJ_j77KMBxPRFyk          ← agent arrives ~1s later
[Sophia] Track subscribed: kind=KindAudio from agent-AJ_...
[Sophia] Remote audio wired to AudioSource on SophiaConnection.
[Sophia][agent_events] payload={"kind": "agent_state", "new": "listening"}
```

Agent worker terminal:
```
INFO  livekit.agents - registered worker {"id": "AW_xxx", "agent_name": "sophia-agent"}
INFO  livekit.agents - received dispatch {"room": "sophia-glasses-abc123", "agent_name": "sophia-agent"}
INFO  livekit.agents - starting entrypoint {"room": "sophia-glasses-abc123"}
INFO  sophia-agent - connected as participant agent-AJ_j77KMBxPRFyk
```

The JWT payload now contains the extra claim:

```json
{
  "iss": "devkey",
  "sub": "glasses-2647ecb8",
  "name": "Sophia Glasses User",
  "exp": 1779403600,
  "video": {
    "room": "sophia-glasses-abc123",
    "roomJoin": true,
    "canPublish": true,
    "canSubscribe": true
  },
  "roomConfig": {                                ← NEW
    "agents": [
      { "agentName": "sophia-agent" }
    ]
  }
}
```

The SFU sees `roomConfig.agents = [{agentName: "sophia-agent"}]` when the Unity client joins, looks up registered workers, finds one matching `agent_name="sophia-agent"`, sends it the dispatch message. Worker wakes up and joins the room. From the Unity client's perspective, the agent "appeared" as a second participant.

**The code change in token_mint.py**

The whole fix is about 8 lines. Before:

```python
@app.post("/token")
def mint_token(req: TokenRequest):
    grants = api.VideoGrants(
        room_join=True,
        room=req.room,
        can_publish=True,
        can_subscribe=True,
    )
    token = (api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(req.identity)
        .with_name(req.name or req.identity)
        .with_grants(grants)
        .with_ttl(timedelta(seconds=req.ttl_seconds)))
    return {"token": token.to_jwt(), "url": LIVEKIT_URL, ...}
```

After (added `agent_name` field to the request schema + the conditional block):

```python
DEFAULT_AGENT_NAME = "sophia-agent"

class TokenRequest(BaseModel):
    identity: str
    room: str
    name: Optional[str] = None
    ttl_seconds: int = 3600
    agent_name: Optional[str] = DEFAULT_AGENT_NAME     # NEW

@app.post("/token")
def mint_token(req: TokenRequest):
    grants = api.VideoGrants(
        room_join=True,
        room=req.room,
        can_publish=True,
        can_subscribe=True,
    )
    token = (api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(req.identity)
        .with_name(req.name or req.identity)
        .with_grants(grants)
        .with_ttl(timedelta(seconds=req.ttl_seconds)))

    if req.agent_name:                                                # NEW
        token = token.with_room_config(                               # NEW
            api.RoomConfiguration(                                    # NEW
                agents=[api.RoomAgentDispatch(agent_name=req.agent_name)]  # NEW
            )                                                         # NEW
        )                                                             # NEW

    return {"token": token.to_jwt(), "url": LIVEKIT_URL, ...}
```

The Unity client's POST body now includes `"agent_name": "sophia-agent"` (default value of `SophiaConfig.agentName`), token_mint embeds the RoomConfiguration claim, the JWT carries dispatch instructions to the SFU.

**Why we didn't notice the bug earlier with the webapp**

The webapp has its OWN token route (the TypeScript one above) that already does this. It was correct from day one. We never tested `sophia-agent/src/token_mint.py` against a real client until the Unity glasses client showed up — that's when the missing claim suddenly mattered.

A common pattern: a piece of code that was "fine because nobody used it" reveals its limitations the first time something actually exercises it.

---

## Part 7 — `SophiaConfig.cs`: runtime configuration via ScriptableObject

**File**: `sophia-glasses/unity/Assets/Scripts/SophiaConfig.cs`

A `ScriptableObject` subclass. One asset file (`Assets/Settings/SophiaConfig.asset`) holds all runtime configuration:

| Field | Purpose | Default |
|---|---|---|
| `liveKitUrl` | SFU WebSocket URL | `ws://100.69.34.194:7880` (Mac's Tailscale IP) |
| `tokenEndpoint` | URL of `/token` endpoint | `http://100.69.34.194:8001/token` |
| `agentName` | Worker name to dispatch | `sophia-agent` (matches `@server.rtc_session(agent_name=...)`) |
| `roomName` | Room to join | empty = unique per launch (Scenario B); fixed string = Scenario A |
| `participantIdentity` | This client's identity | empty = `glasses-<uuid>` |
| `participantName` | Display name shown to other participants | empty = "Sophia Glasses User" |
| `microphoneDeviceIndex` | Which mic to use (Android = 0 = built-in) | -1 = default |

**Why a ScriptableObject and not constants in code**:

- Edit in Unity Inspector. No recompile.
- Multiple instances possible — could swap a `SophiaConfig-dev.asset` for `SophiaConfig-prod.asset` later.
- ScriptableObjects serialize cleanly into scenes and prefabs.
- AGENTS.md convention: "all runtime config goes through a single SophiaConfig.asset ScriptableObject. Edit in the Inspector, no recompile needed."

The `[CreateAssetMenu(menuName = "Sophia/Config")]` attribute means right-click in the Project panel > Create > Sophia > Config creates a new instance.

---

## Part 8 — `SophiaConnection.cs`: the voice loop

**File**: `sophia-glasses/unity/Assets/Scripts/SophiaConnection.cs`

The main MonoBehaviour. Does CONNECTION + AUDIO. No UI — UI is a separate component (Part 17).

### Lifecycle

`OnEnable` runs when the GameObject becomes active in the scene. It:

1. Validates `SophiaConfig` is wired.
2. Defaults `micHost` and `speakerHost` GameObjects to `this.gameObject` if not assigned.
3. Resolves the room name: empty config = generate `sophia-glasses-<12-hex-uuid>`; non-empty = use as-is.
4. Resolves the participant identity: empty config = generate `glasses-<8-hex-uuid>`; non-empty = use as-is.
5. Logs the resolved settings.
6. Starts the `ConnectFlow` coroutine.

`OnDisable` does best-effort cleanup: `_micSource.Stop()` and `_room.Disconnect()` with a try/catch.

### ConnectFlow coroutine

Four phases:

**Phase 1 — Fetch JWT** from the token mint endpoint via `UnityWebRequest.POST`. Body is hand-built JSON matching `token_mint.py`'s `TokenRequest` Pydantic schema:

```csharp
{
  "identity": "glasses-12345678",
  "room": "sophia-glasses-abcdef123456",
  "name": "Sophia Glasses User",
  "agent_name": "sophia-agent"
}
```

Parse the response with `JsonUtility.FromJson<TokenResponse>`. Token comes back as a 457-char JWT.

**Phase 2 — Connect to the room.** Create a `Room`, wire up event handlers (`TrackSubscribed`, `ParticipantConnected`, `Disconnected`, `ConnectionStateChanged`), register text-stream handlers for the three topics (`sophia.rag_result`, `sophia.agent_events`, `lk.transcription`) that the backend publishes. Then `_room.Connect(serverUrl, token, new LiveKit.RoomOptions())`.

**Phase 3 — Request mic permission** via `Application.RequestUserAuthorization(UserAuthorization.Microphone)`. On macOS Editor this is a no-op (grant is in System Settings); on Android it should pop the runtime permission dialog (caveat in Part 15).

**Phase 4 — Publish microphone** via LiveKit's `MicrophoneSource` + `LocalAudioTrack.CreateAudioTrack` + `_room.LocalParticipant.PublishTrack(_micTrack, new TrackPublishOptions { Source = TrackSource.SourceMicrophone })`.

After all four phases succeed, the agent worker dispatches into the room (triggered by the JWT's RoomConfiguration), connects as participant `agent-AJ_...`, publishes its TTS audio track. Our `OnTrackSubscribed` handler creates an AudioSource on `speakerHost`, wires the remote track into it via `new AudioStream(audioTrack, src)`, and Sophia's voice plays through whatever audio output Unity is using.

### Text-stream subscriptions

The backend publishes to three topics:

- `sophia.rag_result` — per-turn RAG retrieve result with question + chunks + sources
- `sophia.agent_events` — AgentSession state changes + per-stage metrics (STT duration, LLM TTFT, TTS TTFB, VAD inference, etc.)
- `lk.transcription` — LiveKit-native transcription stream (raw text per participant)

For Phase 1, `LogTextStream` coroutine reads the full text from each `TextStreamReader` and logs it. Phase 2 added event broadcasting so UI panels can subscribe.

### Why this architecture

- One MonoBehaviour, one job. Matches the AGENTS.md modularity rule.
- Coroutine-based async because Unity's main thread can't block on network calls.
- Best-effort cleanup in OnDisable because LiveKit's disposal is async and we can't yield from non-coroutine methods.
- All UI references are nullable / separate — Phase 2's UI was added by writing a new MonoBehaviour that subscribes to a static C# event, NOT by modifying SophiaConnection's responsibility.

---

## Part 9 — 6 LiveKit Unity SDK API quirks discovered and fixed

The SDK README's quickstart example didn't compile against the actual installed SDK code. After 7 specific errors, the pattern became clear: README is out of date relative to current SDK source. Fixed by reading the installed SDK source under `Library/PackageCache/io.livekit.livekit-sdk@.../Runtime/Scripts/`.

The 7 quirks, with the fixes baked into our SophiaConnection.cs:

| README says | Reality | Our fix |
|---|---|---|
| `_room.Connect(serverUrl, token)` | Requires 3 args | `_room.Connect(serverUrl, token, new LiveKit.RoomOptions())` |
| `using LiveKit; new RoomOptions()` | `RoomOptions` is ambiguous between `LiveKit.RoomOptions` and `LiveKit.Proto.RoomOptions` | Use fully qualified `new LiveKit.RoomOptions()` |
| `connectOp.Error` (string property) | Only `IsError` (bool); details only via SDK log | `if (connectOp.IsError) Debug.LogError("see SDK log above")` |
| `pubOp.Error` (string property) | Same pattern as ConnectInstruction | `if (pubOp.IsError) Debug.LogError("see SDK log above")` |
| `reader.ReadAll().ReadAllText` | Property is `.Text`, not `.ReadAllText` | `readAll.Text` |
| `_micTrack.Stop()` | `LocalAudioTrack` has no `Stop()` method | Skip; rely on GC after `_micSource.Stop()` + `_room.Disconnect()` |
| `new TrackPublishOptions { Source = TrackSource.SourceMicrophone }` with only `using LiveKit;` | Both types live in `LiveKit.Proto` namespace | Add `using LiveKit.Proto;` at top of file |

These are documented exhaustively in `livekit_doubts.md` Q44 with the recovery procedure ("read the installed SDK source directly when docs lag").

---

## Part 10 — Scene creation

User created `Assets/sophia-scene.unity` as the new scene (replacing the URP template's `SampleScene.unity`). Steps in Unity Editor:

1. File > New Scene > Basic (URP).
2. Save As → `sophia-scene.unity` in `Assets/`.
3. Hierarchy > right-click > Create Empty → rename to `SophiaConnection`.
4. Inspector > Add Component → type `Sophia Connection` → Enter.
5. Drag `Assets/Settings/SophiaConfig.asset` (created via Project panel right-click > Create > Sophia > Config) onto the `Config` field in the Inspector.
6. Save scene (`Cmd+S`).

The scene now has one GameObject (`SophiaConnection`) with one MonoBehaviour (`SophiaConnection.cs`) wired to one ScriptableObject (`SophiaConfig.asset`). Minimum viable.

### Why the scene + GameObject step is mandatory (Unity's runtime model)

Common follow-up question: do we *have* to put SophiaConnection on a scene/GameObject before building? Yes — the scene + GameObject step is non-negotiable in Unity.

**Unity is event-driven.** A C# script by itself is just a class definition sitting in the compiled assembly. Nothing runs it. `MonoBehaviour` lifecycle methods (`OnEnable`, `Start`, `Update`, etc.) only fire when Unity's runtime sees a **component instance attached to a GameObject in a loaded scene**.

The chain is rigid:

```
sophia-scene.unity is in build list
        ↓ (APK launches, Unity loads first scene in the list)
sophia-scene.unity loaded into memory
        ↓ (scene contains a GameObject named "SophiaConnection")
GameObject becomes active
        ↓ (GameObject has SophiaConnection component attached)
SophiaConnection.OnEnable() fires
        ↓ (component has its Config field wired)
ConnectFlow coroutine reads from SophiaConfig.asset → connects to LiveKit
```

**Break any link in the chain → nothing happens at runtime.** Which is exactly what Detour 14 (Part 14) was: we had built the APK before adding `sophia-scene.unity` to the Build Settings list. The APK loaded `SampleScene` (the empty URP default) which had no SophiaConnection GameObject, so `OnEnable` never fired, and we got zero `[Sophia]` log lines despite the C# code being compiled into the APK.

**Why SophiaConfig (ScriptableObject) also needs the scene indirectly:** SophiaConfig is a data container, not a behaviour. It has no lifecycle methods that auto-fire. It sits on disk as `SophiaConfig.asset` doing nothing on its own. Something has to **reference** it for it to matter. That something is the `SophiaConnection` component:

```csharp
public class SophiaConnection : MonoBehaviour
{
    [SerializeField] private SophiaConfig config;   // ← this field needs the asset dragged in
    ...
}
```

When Unity loads the scene and instantiates the SophiaConnection component, it sees the serialized reference and loads the .asset into the `config` field. Without the GameObject existing, the .asset is just data nobody reads.

**Failure modes if each step is skipped:**

| What you skip | What happens at runtime |
|---|---|
| Don't create a scene with the SophiaConnection GameObject | APK launches, Unity loads whatever default scene is in the build list, no Sophia code runs, app appears frozen on an empty background. (= Detour 14) |
| Create scene with GameObject, but don't attach the SophiaConnection script | GameObject exists, but has no components. Nothing to fire `OnEnable`. Same blank result. |
| Attach script, but forget to drag SophiaConfig.asset into the `Config` field | `OnEnable` fires, hits the `if (config == null)` check at the top, logs `SophiaConfig is not assigned ... Assign Assets/Settings/SophiaConfig.asset in the Inspector.`, returns. No connection. |
| Don't add the scene to Build Settings | Unity builds the APK without your scene. Same as the first row — your code never runs because your scene doesn't exist in the APK. (= Detour 14) |

**Is there any way to bypass the scene step?**

Strictly speaking, Unity has an escape hatch: `[RuntimeInitializeOnLoadMethod]` lets you run code on app startup without a scene component:

```csharp
[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
static void Bootstrap() {
    var go = new GameObject("SophiaConnection");
    go.AddComponent<SophiaConnection>();
    // ...but config still has to come from somewhere — Resources.Load or hardcoded
}
```

This is unusual, harder to debug, and you still need *some* scene loaded (even if empty). For a normal Unity app the scene-with-GameObject-with-component pattern is the convention, and we follow it.

**Summary of the mandatory one-time wiring:**

1. **A scene file** (`Assets/sophia-scene.unity`) — created once via File > New Scene + Save As.
2. **A GameObject in that scene** (named "SophiaConnection") — created once via Hierarchy > Create Empty.
3. **The SophiaConnection script attached as a component** — Inspector > Add Component.
4. **The SophiaConfig asset wired into the Config field** — drag from Project panel onto the field.
5. **The scene added to Build Settings at position 0** — File > Build Profiles > Scene List.

All five steps are one-time setup. After that, you just edit C# files and rebuild — the wiring stays. Future Phase 2/3 components (SophiaOverlayUI, future EyeCameraCapture, etc.) each need step 3 (attach to a GameObject), but the existing scene + the existing SophiaConnection GameObject host them all — no new scenes needed.

---

## Part 11 — Mac Editor smoke test: first attempt (multiple blockers)

Hitting Play in the Unity Editor against the running backend (livekit-server + token_mint + agent worker on the Mac). Goal: hear Sophia respond through Mac speakers.

This is where most of the work happened. Eight problems, fixed in sequence.

### Detour 1: Burst compiler transient error

`Failed to resolve assembly: 'Editor'` from Unity's Burst compiler. Mysterious. **Fixed by quitting and reopening the Unity Editor.** Some kind of stale cache state. Never recurred.

### Detour 2: 3000 Google.Protobuf errors

Compile errors throughout the LiveKit SDK's auto-generated protocol files: `The type or namespace 'Google' could not be found`. Fixed via the manual nupkg drop described in Part 5.

### Detour 3: NuGet menu missing

The standard fix for Detour 2 would have been `Window > NuGet > Manage NuGet Packages`. But Unity was in **Safe Mode** (it goes into Safe Mode whenever there are compile errors), and Safe Mode hides custom menus, including NuGet's. Classic chicken-and-egg.

Worked around by manual DLL drop (Detour 2's fix). Once errors cleared and Safe Mode exited, the NuGet menu reappeared.

### Detour 4: 7 API mismatches

Documented in Part 9.

### Detour 5: `liblivekit_ffi.dylib: slice is not valid mach-o file`

When clicking Play, the LiveKit SDK tried to load its native FFI binary and crashed. Inspection showed the file was 133 bytes containing `version https://git-lfs.github.com/spec/v1` — a Git LFS pointer.

Cause: the SDK's binaries are stored in Git LFS. Unity Package Manager's git-URL importer doesn't run git-lfs. Fix described in Part 5: install git-lfs, clone the SDK manually, install via "Install package from disk".

### Detour 6: My ordering mistake re-deleting Google.Protobuf.dll

Mid-fix, I (Claude) deleted the manually-dropped `Google.Protobuf.dll` because the local SDK clone bundles its own copy. But user hadn't swapped Package Manager to the local clone yet at that moment. So we ended up with NO protobuf binary, errors flooded back. Apologized, re-copied the DLL.

Lesson: be careful about ordering when reorganizing dependencies across two parties' actions.

### Detour 7: HTTP allow toggle wouldn't stick

`Edit > Project Settings > Player > Other Settings > Configuration > Allow downloads over HTTP > Always allowed` kept reverting between sessions. Probably per-platform tab confusion in Unity 6's settings UI.

**Fixed by force-editing the underlying file with Unity closed:**

```bash
sed -i.bak 's/insecureHttpOption: 0/insecureHttpOption: 2/' \
  sophia-glasses/unity/ProjectSettings/ProjectSettings.asset
```

Verified `grep insecureHttpOption ProjectSettings.asset` → `insecureHttpOption: 2`. Persistent after that.

**Why HTTP needs to be allowed**: our local dev backend uses `ws://` and `http://` (not `wss://` and `https://`). Unity 6 blocks insecure HTTP by default for security. Production deploy on EC2 will use TLS; for local dev we allow insecure.

### Detour 8: `token_mint` 500 error

`AttributeError: 'AccessToken' object has no attribute 'with_ttl_seconds'`. Pre-existing latent bug in token_mint.py — the webapp's Next.js token route uses its own JS implementation, so it never exercised the Python `with_ttl_seconds` path. Our Unity client did.

**Fixed in `sophia-agent/src/token_mint.py`:**

```python
from datetime import timedelta
# in mint_token():
token = (...
    .with_ttl(timedelta(seconds=req.ttl_seconds))   # was: .with_ttl_seconds(req.ttl_seconds)
)
```

Restarted uvicorn to pick up the change.

### Detour 9: macOS Editor mic permission

`InvalidOperationException: Microphone access not authorized`. macOS Editor doesn't auto-prompt for mic. Two changes:

- Added permission request to SophiaConnection.cs ConnectFlow:
  ```csharp
  yield return Application.RequestUserAuthorization(UserAuthorization.Microphone);
  if (!Application.HasUserAuthorization(UserAuthorization.Microphone)) {
      Debug.LogError("[Sophia] Microphone permission not granted. On macOS Editor: ...");
      yield break;
  }
  ```
- Set `microphoneUsageDescription` in `ProjectSettings.asset`.

User then manually granted Unity mic access via macOS System Settings > Privacy & Security > Microphone. Persistent after that grant.

### Detour 10: Sample rate mismatch

Hundreds of `RtcAudioSource: sample_rate and num_channels don't match actualRate=44100 expectedRate=48000`. The mic was capturing at 44100 Hz; LiveKit RtcAudioSource expects 48000 Hz.

Root cause: `OnAudioFilterRead` (the Unity audio callback path that LiveKit's MicrophoneSource uses) is invoked at the OUTPUT MIXER rate (`AudioSettings.outputSampleRate`), which on macOS follows the active output device. The user's EarPods were locked to 44100. `ProjectSettings/AudioManager.asset: m_SampleRate` is only a REQUEST — Unity silently falls back to the device rate if it can't fulfill.

Two fixes applied in succession:
- Force-edited `AudioManager.asset: m_SampleRate: 0 → 48000` (necessary baseline).
- User unplugged EarPods, switched to MacBook Pro Speakers (native 48000).

Errors disappeared. Full mechanism documented in `livekit_doubts.md` Q42.

---

## Part 12 — Mac Editor working end-to-end

After all the detours, hit Play, said "Hello, who are you?", Sophia replied through Mac speakers in Kokoro aiden voice. Full pipeline verified:

- Token mint
- Room connect
- Agent dispatch
- Mic publish
- Sophia TTS subscribe + AudioSource wire-up
- `sophia.agent_events` streaming back (VAD metrics, state transitions)
- `sophia.rag_result` arriving per turn
- `lk.transcription` mirroring both sides

### One remaining Editor-only issue: echo loop

Mac speakers played Sophia's TTS → MacBook mic captured it raw → STT transcribed it as "user speech" → LLM treated it as a new question → Sophia answered → cut by her own next utterance → infinite loop.

User trail visible in the transcripts:
```
user_transcript: "Hello, who are you?"          ← real user
user_transcript: "Voices"                       ← Sophia echoing back
user_transcript: "How can you help me? I'm so..." ← Sophia
user_transcript: "I'm here to help with."       ← Sophia (looping)
```

**Why the webapp doesn't have this**: browsers' `getUserMedia` returns a mic stream already processed by WebRTC's audio pipeline — `echoCancellation: true`, `noiseSuppression: true`, `autoGainControl: true` are all on by default. The browser owns the output mixer and feeds the playback signal into WebRTC's APM, which cancels echo before STT ever sees it.

**Why Unity has this**: `UnityEngine.Microphone.Start(...)` returns raw PCM. No AEC. LiveKit's Unity MicrophoneSource pipes raw mic through Unity's AudioSource → OnAudioFilterRead → FFI → WebRTC encoder. The Rust WebRTC library DOES have APM, but the Unity SDK doesn't wire the playback reference signal into it. So APM has no "what to subtract" data and can't cancel.

Three mitigation options identified:
1. Headphones (passive, eliminates loop physically). Requires picking a 48kHz output.
2. Mic gating in code (mute the mic track while `agent_state=speaking`, unmute on `listening`).
3. Patch the SDK to feed playback into APM (proper fix, SDK-side).

**Decision LOCKED**: do not add mic gating speculatively. Test on glasses first — the geometry (near-ear speakers + far Beam Pro mic) should kill most of the loop. Mic gating is the fallback if it doesn't.

Full explanation saved as `livekit_doubts.md` Q41 (webapp AEC vs Unity), Q42 (sample rate trap), Q43 (echo on glasses prediction).

### The precise sequence when you hit Play (Mac Editor)

Once all the detours are fixed and you click Play, here's exactly what fires, in order. Useful both for understanding the working state and for diagnosing future failures by spotting which step stopped.

1. **Unity Editor enters Play Mode** → loads `sophia-scene.unity` (the only scene in the build list) → instantiates the `SophiaConnection` GameObject → Unity's runtime calls `SophiaConnection.OnEnable()`.

2. **OnEnable** validates config is wired, resolves the room name (`sophia-glasses-<uuid>` because `SophiaConfig.roomName` is empty = Scenario B), resolves the participant identity (`glasses-<uuid>`), logs the resolved values, then `StartCoroutine(ConnectFlow())`.

3. **ConnectFlow Phase 1 — get token.** Unity POSTs to `http://100.69.34.194:8001/token` with `{identity, room, name, agent_name: "sophia-agent"}`. `token_mint.py` builds the JWT, embeds `roomConfig.agents=[{agentName: "sophia-agent"}]` (the Part 6 fix), returns it. Unity log: `[Sophia] Got token (len=457) for url=ws://100.69.34.194:7880`.

4. **ConnectFlow Phase 2 — connect to room.** Unity calls `_room.Connect(serverUrl, token, ...)`. This is where the agent dispatch is triggered — but **Unity itself doesn't dispatch anything.** The SFU does. Precision worth highlighting:

   - Unity hands the JWT to the SFU as part of the connect handshake.
   - SFU validates the JWT signature, sees the `roomConfig.agents=[...]` claim, looks up registered workers matching `agent_name="sophia-agent"`, sends a dispatch message to the matching worker.
   - SFU admits Unity to the room. Unity log: `[Sophia] Connection state: ConnConnected`, then `[Sophia] Connected to room 'sophia-glasses-...'`.
   - These two side effects (Unity admitted + agent dispatched) happen in parallel from Unity's perspective. Unity just sees "connected" and a few hundred milliseconds later a new participant named `agent-AJ_...` joining.

   So saying "Unity dispatched the agent" is imprecise — Unity *handed the SFU a token that asked the SFU to dispatch*. The actual dispatch instruction goes SFU → worker, not Unity → worker.

5. **ConnectFlow Phase 3 — mic permission.** `Application.RequestUserAuthorization(UserAuthorization.Microphone)` + `HasUserAuthorization` check. On macOS Editor this is mostly a no-op:
   - **First Play ever**: returned false because Unity had never been granted mic access via macOS System Settings. We hit `InvalidOperationException: Microphone access not authorized`. That was Detour 9 in Part 11.
   - **After granting Unity mic access** in System Settings > Privacy & Security > Microphone (one-time, persistent): returns true immediately. No dialog. The permission check passes silently.

   So in a Play session after the initial grant, this step is invisible — no prompt, no delay.

6. **ConnectFlow Phase 4 — publish microphone.** Unity enumerates `Microphone.devices` (got `"EarPods Microphone"` or `"MacBook Pro Microphone"` depending on what was plugged in), constructs a `MicrophoneSource`, wraps it in a `LocalAudioTrack`, calls `_room.LocalParticipant.PublishTrack(_micTrack, ...)`. Mic audio now flowing Unity → SFU. Unity log: `[Sophia] Using microphone [0] '...'` then `[Sophia] Microphone publishing. You can speak now.`.

7. **Agent meanwhile** — running on the same Mac in a separate terminal — received the SFU's dispatch message, ran its `entrypoint(ctx)` function, prewarmed Silero VAD + turn detector, connected to the room as `agent-AJ_...`, published its own TTS audio track.

8. **Unity receives `ParticipantConnected` event** for the agent participant. Logs `[Sophia] Participant connected: agent-AJ_...`.

9. **Unity receives `TrackSubscribed` event** for the agent's audio track. Our `OnTrackSubscribed` handler creates an `AudioSource` on the SophiaConnection GameObject, wires the remote track to it via `new AudioStream(audioTrack, src)`. Sophia's audio is now playing through Mac speakers. Unity log: `[Sophia] Track subscribed: kind=KindAudio from participant='agent-AJ_...'` then `[Sophia] Remote audio wired to AudioSource on SophiaConnection.`.

10. **Conversation loop is now live.** User speaks → mic publishes audio → SFU forwards to agent → agent's STT transcribes → LLM generates reply (with RAG injection if `max_score >= 0.30`) → TTS synthesizes audio → published back through SFU → Unity's `AudioStream` plays it through the Mac's active output device.

#### Quick mental model

| What it looks like from outside | What's actually happening |
|---|---|
| "Unity client joined the room" | ✓ SophiaConnection.cs called `_room.Connect` after fetching the token. |
| "Unity dispatched sophia agent" | ⚠️ Imprecise. Unity handed the SFU a JWT containing the dispatch instruction. The SFU did the actual dispatch (sending a message to the registered worker). Unity itself made no separate dispatch call. |
| "Asked microphone access" | ✓ On Mac Editor after first session this is silent (no dialog); permission was already granted system-wide. On Beam Pro it's a real Android system dialog (Detour 16). |

#### Two halves that are easy to overlook

- **Unity PUBLISHED its mic to the room.** Symmetric half of the conversation — without publishing, the agent has nothing to listen to. Underlying mechanic: `_room.LocalParticipant.PublishTrack(_micTrack, ...)`.
- **Unity SUBSCRIBED to the agent's TTS audio track.** When the agent published its audio output, Unity got a `TrackSubscribed` event and wired the incoming audio to an `AudioSource` so the Mac speakers could play it. Without that wire-up, you'd hear silence even with everything else working.

So the full bidirectional flow is:

```
Unity → publishes mic to room → SFU → agent (STT → LLM → TTS) →
   publishes audio to room → SFU → Unity (subscribes track, wires to AudioSource) →
   Mac speakers
```

---

## Part 13 — APK build attempt (P1-8)

### Why we need to build an APK at all

The Unity Editor runs only on macOS (or Windows/Linux). It cannot run on Android. The Beam Pro is an Android device. So to get the Sophia client onto the Beam Pro, we have to produce a **native Android executable** — that's the APK (Android Package).

What's inside the APK that the Editor doesn't need to ship:

- **Your C# scripts cross-compiled to native ARM64.** Unity's Mono runtime works on desktop, but on Android it uses **IL2CPP**: your C# is first compiled to IL (Microsoft intermediate language) then transpiled into C++ then compiled by the NDK into `libil2cpp.so`. End result is a native ARM64 binary, not interpreted bytecode. Much faster than Mono on mobile, and required for some Android features.
- **The Unity Android Player** itself (`libunity.so` + `libmain.so`) — the engine runtime bundled into the APK.
- **The XREAL native plugins** (`libXREALXRPlugin.so`, `libVulkanSupport.so`, `libmedia_codec.so`) — the AR display, camera, video codecs.
- **The LiveKit FFI Rust client compiled for Android** (`liblivekit_ffi.so` for arm64-v8a, ~17 MB) — what handles the WebRTC/Opus/DTLS protocols.
- **Compiled scenes + assets** — your `sophia-scene.unity`, compressed textures, shader variants pre-cooked for the target GPU.
- **AndroidManifest.xml** — auto-generated by Unity from Player Settings, declares permissions (RECORD_AUDIO, INTERNET), the main activity (`UnityPlayerGameActivity`), the bundle ID, the supported screen densities, etc.
- **TextMeshPro font assets** — LiberationSans SDF + shaders + sprite asset, the things you imported via "Import TMP Essentials".

The APK is signed with a debug keystore (Unity generates a default for dev), zipped, and dropped at the path you choose. Once installed via `adb install -r`, Android treats it like any other app — appears in the launcher, lives in `/data/app/<pkg>/`, runs in its own sandbox.

### Pre-build checklist (what to verify before clicking Build)

Each item below maps to a problem we hit (or one we'd have hit). Tick each before pressing Build.

**1. Build target is Android (not Mac/Windows/iOS).**
`File > Build Profiles > Android > Switch Platform`. Triggers a one-time asset re-import (3-5 min: Unity recompresses textures for ETC2, recompiles shader variants for Vulkan/GLES, regenerates sprite atlases for mobile). If your active target is still Mac/PC, the Build button produces a desktop binary, not an APK — silent failure, no error message, you just get a `.app` you can't install on Beam Pro.

**2. Scenes In Build list includes sophia-scene at position 0.**
`File > Build Profiles > Scenes In Build`. Verify:
- Your `sophia-scene.unity` is present.
- It's at index 0 (= startup scene).
- The default `SampleScene` is removed or unchecked.

This was Detour 14 — we built once with only the empty SampleScene in the list, APK launched into an empty world, no Sophia code ever ran.

**3. Player Settings > Android tab — verify each:**

| Setting | Required value | Why |
|---|---|---|
| Scripting Backend | IL2CPP | Mono doesn't work on Android in modern Unity. IL2CPP cross-compiles C# → native ARM64. |
| Target Architectures | ARM64 only (uncheck ARMv7) | Beam Pro is 64-bit ARM. Including ARMv7 nearly doubles APK size for no benefit. |
| Minimum API Level | 29 (Android 10 'Q') | XREAL's `xreal-auto-log-1.2.aar` requires 29. Setting it lower fails Gradle (Detour 11). |
| Target API Level | Latest installed (36 in our build) | Required by Play Store; for sideload less strict. Leave at latest. |
| Package Name / Bundle Identifier | `com.sophia.glasses` (eventually) | Currently default `com.UnityTechnologies.com.unity.template.urpblank` — Phase 2 cleanup. Changing it requires `adb uninstall` of the old package before reinstall (signature mismatch). |
| Microphone Usage Description | "Sophia voice agent needs microphone access to hear you" (or similar) | Required for Android RECORD_AUDIO permission dialog to display your string. Empty string = Unity warning + manifest gets a placeholder. |
| Allow downloads over HTTP | Always Allowed (or Dev Only) | Our backend uses `ws://` and `http://`, not TLS. Unity 6 blocks insecure HTTP by default. Force-edit `insecureHttpOption: 2` if the UI toggle won't stick (Detour 7). |
| Internet Access | Require | Same reason — without it, manifest skips INTERNET permission. |

**4. AudioManager.asset — sample rate.**
`ProjectSettings/AudioManager.asset: m_SampleRate: 48000`. Less critical for Android (system audio is always 48 kHz for voice apps) but set as a floor anyway. Critical on Mac Editor (Detour 10 — `livekit_doubts.md` Q42).

**5. TMP Essentials imported (only if you have any TMP_Text in your scene).**
If you use TextMeshPro components — and we do, via SophiaOverlayUI — verify `Assets/TextMesh Pro/` directory exists. If not: `Window > TextMeshPro > Import TMP Essential Resources` (one click, ~10s).

Without this, runtime `AddComponent<TextMeshProUGUI>()` crashes with NullReferenceException at `TMP_Settings.get_autoSizeTextContainer` (Detour 18, `livekit_doubts.md` Q48).

**6. Native plugins are real binaries (not LFS pointer files).**
If you cloned the LiveKit Unity SDK manually (because the git-URL Package Manager install left LFS pointer files), verify:

```bash
file sophia-glasses/client-sdk-unity/Runtime/Plugins/Android/arm64-v8a/liblivekit_ffi.so
# expected: ELF 64-bit LSB shared object, ARM aarch64
# NOT: ASCII text (= LFS pointer)
```

Hit this on macOS as Detour 5; would happen on Android equally if the per-platform `.so` files were pointer files.

**7. Build flags.**
In the Build Profiles window:
- **Development Build**: ON for dev (includes debug symbols, allows `adb logcat` with full C# stack traces, allows the in-app Profiler connection, slightly larger APK ~+5 MB). OFF for production.
- **Autoconnect Profiler**: only if you're using Unity Profiler over the network. Off otherwise.
- **Script Debugging**: ON for dev (lets you attach a managed debugger from the IDE). Off for production.
- **Wait For Managed Debugger**: ON if you want the app to pause on startup until a debugger attaches. Almost always OFF.
- **Compression Method**: LZ4HC for release (smaller), LZ4 for dev (faster builds). Default is fine.

**8. Build output path.**
`File > Build Profiles > Build` opens a save dialog. Convention for this project: `sophia-glasses/unity/sophia-glasses.apk`. Pick a stable path so the `adb install` command stays the same — easier for automation later. **Don't put it inside `Assets/`** — Unity will reimport it as an asset and waste minutes on every focus.

**9. External prerequisites (not Unity settings, but required for the APK to do anything).**
The APK will install and launch even if these are wrong, but it'll connect to nothing. Verify:
- **Backend services running on Mac**: `livekit-server`, `pf-gpu.sh` (kubectl port-forwards), `token_mint`, `agent.py`. See `sophia-agent/RUNBOOK.md`.
- **Tailscale up on both Mac and Beam Pro.** Verify with `adb shell curl http://100.69.34.194:7880` returning HTTP 200 from the Beam Pro.
- **`SophiaConfig.asset` has the right Tailscale IP** in `liveKitUrl` and `tokenEndpoint`. If your Mac's Tailscale IP changed (rare but happens), update this field and rebuild.
- **Beam Pro adb-ready**: USB debugging enabled, "Allow USB debugging" accepted, USB mode = File Transfer (not Charge Only).
- **Free disk space**: APK build process needs ~2-5 GB working space in `sophia-glasses/unity/Library/Bee/`. First build is heaviest; subsequent builds are incremental.

**10. Sanity-check the APK before `adb install`.**

```bash
ls -lh sophia-glasses/unity/sophia-glasses.apk    # expected: ~50-100 MB
file sophia-glasses/unity/sophia-glasses.apk      # expected: Zip archive data
unzip -l sophia-glasses/unity/sophia-glasses.apk | grep -E 'liblivekit_ffi.so|libXREAL|libil2cpp.so'
# expected: each .so present at non-trivial size (megabytes)
```

If `liblivekit_ffi.so` is missing or tiny, you've shipped a broken APK — the LiveKit native client isn't bundled, the app will crash on Connect.

### The actual build we did

Switched Build Target to Android: `File > Build Profiles > Android > Switch Platform` (re-imported assets for Android, took ~3-5 min).

Clicked Build. Output destination: `sophia-glasses/unity/sophia-glasses.apk`.

### Detour 11: minSdkVersion conflict

Gradle error:
```
uses-sdk:minSdkVersion 25 cannot be smaller than version 29 declared in library
  [:xreal-auto-log-1.2:] ... AndroidManifest.xml
```

XREAL SDK 3.1.0 bundles `xreal-auto-log-1.2.aar` which targets `minSdkVersion 29` (Android 10). Unity defaults projects to API 25 (Android 7).

**Fix in Player Settings**: `Edit > Project Settings > Player > Android > Other Settings > Minimum API Level → Android 10.0 'Q' (API level 29)`.

Pick exactly 29, not higher — wider device compatibility. Beam Pro runs Android 14 (API 34) per the runtime log, so 29 is fine.

Rebuild → succeeded. APK file at `sophia-glasses/unity/sophia-glasses.apk`.

Saved as `livekit_doubts.md` Q45 (alongside the other APK build/install gotchas).

### Other non-blocking warnings observed during build

- `Plugin libXREALXRPlugin.so is not 16KB-aligned. May cause issues on ARM64 devices running Android 15+.` — Beam Pro is Android 14, doesn't bite. Will need XREAL SDK update before Android 15 ship.
- `nrsdk.pack namespace used in multiple modules` — XREAL SDK internal warning, not an error.
- `No XR Manager settings found, manifest entries will not be updated.` — XR Plugin Management not configured. Glasses will render as flat 2D (no stereoscopic AR). Fine for Phase 1/2; Phase 3 will configure XREAL XR Loader.

---

## Part 14 — APK install + first launch on Beam Pro

```bash
adb devices                                                           # confirm Beam Pro online
adb install -r '/path/to/sophia-glasses/unity/sophia-glasses.apk'     # streamed install: Success
adb shell pm list packages -3 | grep sophia                           # finds nothing — bundle ID didn't match
adb shell pm list packages -3 | grep -i unity                         # found: com.UnityTechnologies.com.unity.template.urpblank
```

**Detour 12**: Bundle ID is the URP template default, never customized. We hadn't set `applicationIdentifier` in Player Settings, so Unity baked it from the template metadata. The package shows up as `com.UnityTechnologies.com.unity.template.urpblank`. Future cleanup: rename to `com.sophia.glasses` (requires `adb uninstall` first because signature mismatch). Deferred to Phase 2 hardening.

### Detour 13: Wrong activity name

```bash
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerActivity
# → Error: Activity class ... UnityPlayerActivity does not exist.
```

Unity 6 uses Android `GameActivity` (Google's modern native-activity replacement) by default. The launchable main activity is `com.unity3d.player.UnityPlayerGameActivity`, not `UnityPlayerActivity`.

Discovered via:
```bash
adb shell cmd package resolve-activity --brief com.UnityTechnologies.com.unity.template.urpblank
# → com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
```

### Detour 14: App ran but no Sophia logs (wrong scene in build)

`adb logcat` showed Unity initializing fine — `Handle cmd APP_CMD_GAINED_FOCUS` etc. — but ZERO `[Sophia]` log lines. That meant SophiaConnection's `OnEnable` never ran. Which meant the GameObject wasn't in the scene that loaded.

Cause:

```bash
grep enabled sophia-glasses/unity/ProjectSettings/EditorBuildSettings.asset
# m_Scenes:
#   - enabled: 1
#     path: Assets/Scenes/SampleScene.unity   ← only the empty URP template scene
```

We never added `Assets/sophia-scene.unity` to the build list. The APK built the empty default template; our scene was excluded.

**Fix in Unity**: `File > Build Profiles > Scene List` → open sophia-scene → "Add Open Scenes" button → drag to position 0 → untick or delete SampleScene → save scene list → rebuild.

After fix, `EditorBuildSettings.asset` had only `Assets/sophia-scene.unity` at position 0.

---

## Part 15 — Beam Pro voice loop: connection then mic, two more fixes

Rebuilt + reinstalled. App now loaded the correct scene. Coroutine ran:

```
[Sophia] Starting. room='sophia-glasses-1fb66a606e01' identity='glasses-94d50575' server='ws://100.69.34.194:7880'
[Sophia] Got token (len=457) for url=ws://localhost:7880
[Sophia] Room.Connect failed (see SDK log above).
```

### Detour 15: `Room.Connect failed` — token server URL was Mac-perspective

The token mint endpoint returned `url=ws://localhost:7880` from its own `os.environ["LIVEKIT_URL"]` (set in `sophia-agent/.env.local`). That URL works from the Mac itself (where livekit-server runs on localhost:7880). On the Beam Pro, `localhost` is the Beam Pro itself — nothing listens on its port 7880.

Our `SophiaConnection.cs` had a line:
```csharp
if (!string.IsNullOrWhiteSpace(resp.url)) serverUrl = resp.url;
```
that preferred the response URL over `SophiaConfig.liveKitUrl`. That's wrong for multi-host setups: the server has no business telling the client where to connect; each client should own its own URL.

**Fix in `SophiaConnection.cs`**: removed that line. Always use `config.liveKitUrl` (which is set to the Tailscale URL `ws://100.69.34.194:7880`, reachable from any device on the Tailnet).

After rebuild + reinstall:
```
[Sophia] Got token (len=457) for url=ws://100.69.34.194:7880    ← Tailscale URL now used
[Sophia] Connection state: ConnConnected                         ← SFU reachable
[Sophia] Connected to room 'sophia-glasses-...'
[Sophia] No microphone devices found.                            ← next problem
```

Saved as `livekit_doubts.md` Q46.

### Detour 16: `No microphone devices found` (Android permission race)

Despite RECORD_AUDIO being declared in the manifest (auto-added by Unity because we used `Microphone` API + had `microphoneUsageDescription` set), the mic enumeration returned empty.

Looking at concurrent Android logs:
```
46.543  [Android]   START GrantPermissionsActivity (permission dialog opens)
46.544  [Sophia]    No microphone devices found      ← our script bailed
46.659  [Android]   dialog displayed to user
50.805  [Android]   user clicks Allow, RECORD_AUDIO granted=true
```

Race condition: Unity's `Application.RequestUserAuthorization(Microphone)` on Android triggers the system permission dialog as a side effect, but returns to the coroutine IMMEDIATELY — doesn't block on user response. `HasUserAuthorization` returns true based on Unity's internal flag, which is stale until the actual grant happens. Our script proceeded past the auth check before Android had granted, found `Microphone.devices` empty, hit `yield break`.

**Workaround used today**: user taps Allow on the dialog → permission is persisted → `adb shell am force-stop` + `am start` to relaunch the app → second launch sees `Microphone.devices` populated immediately (no re-prompt because grant is sticky).

Verified persistence:
```bash
adb shell dumpsys package com.UnityTechnologies.com.unity.template.urpblank | grep RECORD_AUDIO
# android.permission.RECORD_AUDIO: granted=true, flags=[ USER_SET|...]
```

**Proper fix (deferred to Phase 2 hardening)**: retry the mic check after the auth coroutine for up to 5 seconds (poll `Microphone.devices` every 200ms), OR write a small Android JNI helper that uses `ActivityCompat.requestPermissions` with a real callback that truly blocks. The JNI path has a bonus benefit: it can also switch the audio source from VOICE_RECOGNITION (Unity default) to VOICE_COMMUNICATION, which enables Android's system AcousticEchoCanceler.

Saved as `livekit_doubts.md` Q47.

### Detour 16 in detail: timeline, workaround, and the permanent fix (Path A now implemented, Path B deferred to Phase 2)

**The problem in one sentence.** On Android, our script asks for microphone permission and tries to use the mic in the next line, but Android's permission grant happens asynchronously (the user has to tap a dialog) — so by the time the user actually taps Allow, our script has already given up.

**Concrete timeline (real millisecond ticks from the actual first install on Beam Pro):**

```
T=0ms      App launched. SophiaConnection.OnEnable fires, kicks off ConnectFlow.
T=140ms    Coroutine fetched token from token_mint.
T=470ms    Room.Connect succeeded → joined LiveKit room.

T=545ms    Coroutine reaches:
              yield return Application.RequestUserAuthorization(UserAuthorization.Microphone);
           
           Behind the scenes, Unity SHOWS the Android system permission dialog:
              "Allow Sophia voice agent to record audio?  [Don't allow] [While using the app]"
           
           BUT: this `yield return` returns control IMMEDIATELY on Android.
           It does NOT actually wait for the user to tap a button.

T=546ms    Coroutine reaches the next check:
              if (!Application.HasUserAuthorization(UserAuthorization.Microphone))
                  yield break;
           
           HasUserAuthorization returns true (Unity's internal flag is optimistic).
           Check passes, coroutine continues.

T=547ms    Coroutine reaches:
              if (Microphone.devices == null || Microphone.devices.Length == 0)
                  yield break;
           
           Microphone.devices returns an empty array because Android has NOT
           actually granted RECORD_AUDIO yet (the dialog is still open).
           
           Coroutine logs: "[Sophia] No microphone devices found."
           yield break → coroutine exits. NO MIC PUBLISHED.

T=660ms    Android finally displays the dialog on screen.

T=4,200ms  User reads the dialog, taps "While using the app".
           Android RECORD_AUDIO is now granted at the OS level.

T=4,201ms  ...but our coroutine has been dead for 3.6 seconds. App is connected
           to the room with no mic. Sophia waits for audio that never comes.
```

The actual log lines we observed:
```
46.543  [Android]   START GrantPermissionsActivity (permission dialog opens)
46.544  [Sophia]    No microphone devices found      ← our script bailed
46.659  [Android]   dialog displayed to user
50.805  [Android]   user clicks Allow, RECORD_AUDIO granted=true
```

Between **46.544** (our bail-out) and **50.805** (actual grant) is **4.26 seconds**. Our code couldn't have known to wait — `yield return` on `RequestUserAuthorization` returns immediately on Android, and we treated it as "permission is decided, check the result". On Android that assumption is false.

**Why this only bites on Android.** `Application.RequestUserAuthorization` was originally a WebPlayer/iOS API. On those platforms it blocks correctly until the user responds. Unity bolted it onto Android years later but the implementation doesn't actually wait — it just fires the request and returns. The API has the *same signature* across platforms but *different blocking behaviour*. We assumed the iOS/WebPlayer semantics.

**The dev-time workaround (what we did Phase 1).** Once the user has tapped Allow once, Android remembers it forever (`granted=true` persists across launches). So:

1. First launch — script bails at "No microphone devices found", user taps Allow on the still-visible dialog, OS records the grant permanently.
2. Force-stop + relaunch:
   ```bash
   adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
   adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
   ```
3. Second launch — `Microphone.devices` returns the device immediately, coroutine proceeds normally, voice loop works.

This is fine for dev (we have adb) but unshippable for users (silent broken first launch, no in-app instruction).

**Path A (now implemented in SophiaConnection.cs).** Poll-retry with a 20-second window. Replaces the hard `yield break` with a loop that gives Android time to actually grant:

```csharp
// Android permission race: Application.RequestUserAuthorization above
// shows the system dialog but returns immediately on Android (doesn't
// block on user response). A naive zero-wait check on Microphone.devices
// returns empty because Android hasn't granted RECORD_AUDIO yet. Poll
// up to 20s, allowing the user time to tap Allow.
const float maxWaitSeconds = 20f;
const float pollInterval = 0.2f;
float elapsed = 0f;

if (Microphone.devices == null || Microphone.devices.Length == 0)
{
    Debug.Log($"[Sophia] No microphone devices yet. Waiting up to " +
        $"{maxWaitSeconds}s for Android to grant RECORD_AUDIO " +
        "(tap Allow on the permission dialog if visible).");
}

while (Microphone.devices == null || Microphone.devices.Length == 0)
{
    if (elapsed >= maxWaitSeconds)
    {
        Debug.LogError($"[Sophia] No microphone devices found after " +
            $"{maxWaitSeconds}s. User likely denied or ignored the " +
            "permission dialog. Re-grant via OS settings or reinstall.");
        yield break;
    }
    yield return new WaitForSeconds(pollInterval);
    elapsed += pollInterval;
}

if (elapsed > 0f)
{
    Debug.Log($"[Sophia] Microphone became available after {elapsed:F1}s.");
}
```

What this does:
- Fires the permission request (dialog appears).
- Doesn't bail. Sits in a loop checking `Microphone.devices` 5 times per second.
- Each iteration yields back to Unity's main loop so the rest of the engine keeps running (rendering, FFI events, agent track subscription).
- The moment Android grants RECORD_AUDIO and the mic enumerates, the loop exits and the coroutine continues normally.
- If user ignores or denies for 20 seconds, log a clean error message that points them to OS settings.

20 seconds is generous — covers the slowest realistic case (user reading the dialog, deciding, tapping). Most cases resolve in 2-5s. The polling itself is cheap (a property lookup every 200ms; no CPU cost).

After Path A, cold-launch UX is: install → tap icon → permission dialog appears → tap Allow → voice loop starts within a second. No force-stop+relaunch needed.

**Path B (Android JNI bridge, deferred to Phase 2 hardening).** The "real" fix uses Android's native `ActivityCompat.requestPermissions` with an `onRequestPermissionsResult` callback, exposed to C# via an `AndroidJavaProxy`. The C# side wraps this in a `Task<bool>` so the coroutine genuinely awaits the user's response — no polling, no timeout, just the right answer when it's ready.

Sketch (full code in the design discussion under Detour 16 example):

- **`Assets/Plugins/Android/SophiaMicPermission.java`** — wraps `ActivityCompat.requestPermissions` with a callback interface.
- **`Assets/Scripts/SophiaMicPermission.cs`** — exposes `Task<bool> RequestAsync()` via `AndroidJavaClass` + `AndroidJavaProxy`.
- **`SophiaConnection.cs`** — replaces the polling loop with `await SophiaMicPermission.RequestAsync()`.

Why Path B is worth doing in Phase 2 even though Path A solves the UX issue:
- **Bonus: can swap the audio source.** The same JNI plugin can replace Unity's `Microphone.Start` (which uses `MediaRecorder.AudioSource.VOICE_RECOGNITION`) with a direct `AudioRecord` using `MediaRecorder.AudioSource.VOICE_COMMUNICATION`. That source automatically engages Android's system `AcousticEchoCanceler` + `NoiseSuppressor` + `AutomaticGainControl`. Would solve Q41/Q43's "Unity Microphone API has no AEC on Android" gap, making the app resilient to deployments where glasses geometry doesn't kill echo on its own.
- **One plugin, two problems solved.** Permission flow + AEC enablement in the same Java file. Worth the ~2-4 hour native-Android setup time.

**Decision LOCKED**: Path A shipped now (in `SophiaConnection.cs` as of this commit). Path B is in Phase 2 hardening backlog. Defer until either (a) someone reports echo on glasses in a noisier environment than your test setup, or (b) we're already touching native Android code for another reason — at which point bundle the permission fix into the same plugin.

---

## Part 16 — Beam Pro voice loop CONFIRMED working

After permission grant + relaunch, full pipeline ran cleanly:

```
[Sophia] Connected to room
[Sophia] Using microphone [0] 'Android audio input'
[Sophia] Microphone publishing. You can speak now.
[Sophia] Participant connected: agent-AJ_j77KMBxPRFyk
[Sophia] Track subscribed: kind=KindAudio
[Sophia] Remote audio wired to AudioSource
agent_state: initializing → listening
```

VAD metrics streaming back from the agent every ~1s — mic frames reaching the agent, VAD processing.

**No sample-rate errors** at all (Android audio is 48 kHz natively, validating Q42's macOS-only nature).

### Wearing the glasses

Setup for the glasses test:
```bash
adb tcpip 5555                          # while still on USB
adb connect 100.69.32.120:5555          # Beam Pro Tailscale IP
adb devices                             # both USB + wireless listed
# then unplug USB, plug XREAL One Pro into Beam Pro USB-C, wear glasses
```

User wore the glasses, launched the app (still installed and ready), spoke. Reported: **"its working awesome, i can see the app wearing glasses, i ran end to end voice loop"** with **no echo**.

This empirically validated Q43's prediction: XREAL One Pro near-ear directional speakers + Beam Pro mic in hand/pocket = loop gain too low for echo to manifest, even though Unity's Microphone API doesn't engage Android's AcousticEchoCanceler. Mic gating NOT needed for Phase 1 ship.

**PHASE 1 COMPLETE.**

But at this point the glasses showed only the URP template's plain background — no overlays. The user immediately asked for the web frontend's UI to appear in the glasses too.

### Sidebar: which microphone is actually being used?

A natural follow-up: "we're using Beam Pro's mic and the glasses' speaker, right? Does Beam Pro have to stay near my face?"

Short answer: **probably no, because the glasses also have built-in mics, and Android's USB audio routing auto-switches to them when you plug the glasses in.** We've likely been using the glasses' mic since Step 8 of the operational sequence without realizing it.

**Why this isn't obvious from our logs**

When SophiaConnection enumerates `Microphone.devices` on Android, Unity always returns a single generic string:
```
[Sophia] Using microphone [0] 'Android audio input' (available: Android audio input)
```

`"Android audio input"` is whatever the OS has currently routed mic input to. Unity doesn't surface the underlying hardware. When glasses are unplugged, that's Beam Pro's built-in mic. When glasses are plugged in via USB-C, Android's audio policy auto-routes input to the USB audio device (the glasses), and "Android audio input" silently means the glasses' mic. Same Unity code, different actual hardware behind it.

**XREAL One Pro mic capability (per spec)**

The XREAL One Pro ships with dual-mic arrays on the temples, primarily for noise-cancelled voice pickup for the glasses' own assistant UI. They appear to the host Android device as a standard USB Audio Class input — no XREAL SDK required, the OS handles the routing.

**How to verify which mic is in use**

Three quick adb checks while glasses are plugged in:

```bash
# 1. Confirm adb is connected
adb devices

# 2. See what audio cards the OS sees (should show TWO when glasses plugged in:
#    Beam Pro's built-in audio + USB Audio for XREAL)
adb shell cat /proc/asound/cards

# 3. Get the actively routed input device
adb shell dumpsys audio | grep -iE "active.*input|input.*device|primary.*input" | head -10
```

If `/proc/asound/cards` shows a USB Audio entry while glasses are plugged in, the glasses' mic is available to the OS. The `dumpsys audio` output confirms which device Android is actively routing input from.

**Even simpler empirical test**: with glasses on, place the Beam Pro at arm's length (or on a desk) and talk normally. If Sophia hears you and replies, the glasses' mic is being used. If she stays silent in `agent_state: listening` forever, Beam Pro's built-in mic is being used and you need to be close to it. The fact that earlier voice-loop tests through the glasses worked with the Beam Pro NOT held to the face is strong indirect evidence that the glasses' mic was active.

**Practical implications for Beam Pro placement**

| Scenario | Beam Pro placement | Quality |
|---|---|---|
| Glasses' mic is the active input (auto-routed via USB) | Pocket, bag, belt clip — anywhere on your person within tether reach (~1.2m) | Good — XREAL mics are designed for voice assistant use |
| Beam Pro's built-in mic is the active input (somehow not auto-routed) | 30-50cm from your mouth — held like a phone or clipped to collar | Workable but awkward UX |

If the glasses' mic isn't auto-selected for some Android variant or USB negotiation quirk, the fix is in the Path B JNI plugin from Detour 16: Android's `AudioRecord` API lets you explicitly select an input device by AudioDeviceInfo, including the USB one. That's a single line of Java once the JNI plugin exists. So the same Phase 2 plugin we're already planning (Path B for the permission race + VOICE_COMMUNICATION for AEC) can also force-select the glasses' mic if Android's defaults misbehave. Three problems solved by one plugin.

**Summary**

- The XREAL One Pro has built-in mics (dual-mic array on the temples).
- Android's USB audio routing typically picks the USB input automatically when glasses are plugged in.
- Our existing Phase 1 setup is most likely already using the glasses' mic — the Beam Pro just needs to be on your person, not held to your face.
- Verify with `cat /proc/asound/cards` + the arm's-length-test. If both check out, the user-wearing-glasses ergonomics are exactly what they should be: glasses on face, Beam Pro in pocket.
- If routing misbehaves on some future device or Android version, Phase 2's JNI plugin can explicitly select the glasses' mic via `AudioRecord.setPreferredDevice(...)`.

---

## Part 17 — Phase 2 first cut: AR HUD overlay

**File**: `sophia-glasses/unity/Assets/Scripts/SophiaOverlayUI.cs` (NEW, ~270 lines)

Builds a world-space head-locked Canvas + 3 TMP panels at RUNTIME — no Unity Editor wiring required for the user. They just add the script as a component on the same GameObject as `SophiaConnection`.

### Architecture (per AGENTS.md modularity)

`SophiaConnection.cs` got a single addition:

```csharp
public static event Action<string, string, string> OnTextStreamMessage;
// topic, fromIdentity, jsonPayload
```

Raised inside the existing `LogTextStream` coroutine after the Debug.Log. Wrapped in try/catch so a misbehaving subscriber can't crash the connection layer.

`SophiaOverlayUI.cs` subscribes to that static event in `Start`, unsubscribes in `OnDestroy`. Filters by topic. Each topic routes to a small handler that updates one panel.

Static event because (a) subscribers can be created at any time without finding the connection object by reference, and (b) there's only ever one SophiaConnection in the scene so leaks aren't a concern.

### Canvas construction at runtime

```csharp
var canvasGO = new GameObject("SophiaCanvas");
canvasGO.transform.SetParent(Camera.main.transform, false);
canvasGO.transform.localPosition = new Vector3(0f, 0f, 2.0f);   // 2m in front of head
canvasGO.transform.localScale = Vector3.one * 0.0012f;          // 1920×1080 virtual px → ~2.3m physical at 2m distance

var canvas = canvasGO.AddComponent<Canvas>();
canvas.renderMode = RenderMode.WorldSpace;
canvas.worldCamera = Camera.main;
```

World-space Canvas parented to Camera.main = head-locked HUD (panels stay glued to your view as you turn your head). Standard pattern for AR status displays.

### Three panels

Each created via the same `CreatePanel(name, bg, anchor, pivot, offset, size)` helper:

1. **Top-left state pill** — anchor `(0,1)` pivot `(0,1)` offset `(40,-40)` size `(440,100)`. Single TMP_Text, big bold font, displays "LISTENING" / "THINKING" / "SPEAKING" with color-coded background (green/amber/blue).
2. **Bottom transcript** — anchor `(0.5,0)` pivot `(0.5,0)` offset `(0,40)` size `(1500,220)`. Two stacked TMP_Texts, top half = "You: ...", bottom half = "Sophia: ...".
3. **Right RAG panel** — anchor `(1,0.5)` pivot `(1,0.5)` offset `(-40,0)` size `(560,600)`. Two stacked TMP_Texts, top 30% = "Q: <question>", bottom 70% = "Sources: \n - x250_ug_en.pdf \n - GV70_Owners_Manual.pdf" (or "Sources: (general chat -- no manual lookup)" when retrieve was skipped).

### JSON parsing

Sophia-agent's payloads are predictable enough that small substring-scan helpers work:

- `ExtractJsonString(json, key)` finds `"key":"value"`, returns the value with backslash-escape handling.
- `ExtractSourceFilenames(json)` finds every `"source":"..."` occurrence in the hits array.

No Newtonsoft.Json dependency.

### TMP Essentials gotcha

First build of Phase 2 produced `NullReferenceException` at every `AddComponent<TextMeshProUGUI>()`. Cause: TMP Essentials Resources weren't imported. The URP template ships the TMP package but NOT the default font/sprite/shader assets. Runtime instantiation needs `TMP_Settings.instance` to load defaults from; without Essentials, that's null.

**Fix**: user ran `Window > TextMeshPro > Import TMP Essential Resources` (one click, ~10s). Created `Assets/TextMesh Pro/` directory with `TMP Settings.asset` + the default font (LiberationSans SDF) + shaders + sprite asset.

Rebuild → HUD bootstrapped cleanly, panels rendered.

Documented this pattern + the TMP requirement as `livekit_doubts.md` Q48.

### What the panels actually show + where you can see them

The three panels are **the same overlays as the web frontend**, rendered with Unity Canvas + TextMeshPro instead of React + HTML. Same data, same per-turn updates, just a different render target.

**Real-time data sources (identical to the React app):**

| Panel | Subscribes to | Same as browser's |
|---|---|---|
| Top-left state pill | `sophia.agent_events` filtered for `kind: "agent_state"` | AgentStatePill (top-left in the React app) |
| Bottom transcript | `lk.transcription` + `sophia.agent_events` filtered for `user_transcript` | The chat transcript at the bottom of the React app |
| Right RAG sources | `sophia.rag_result` | RagResultPanel (right side of the React app) |

So when you ask "what's the tire pressure for the GV70?", the right panel shows the same `GV70_Owners_Manual.pdf` source filenames the browser shows. When Sophia is thinking, the top-left flips to amber `THINKING`. Same backend events; the only difference is the render target.

**Where the HUD will appear:**

The Canvas is world-space, parented to `Camera.main`, 2 metres in front of the camera. `Camera.main` exists in BOTH the Mac Editor's Game view AND on the Beam Pro / glasses display. So the same code, the same scene, the same panels render in all three places.

| Setup | Before (Phase 1) | After (Phase 2) |
|---|---|---|
| **Mac Editor (Play button)** | Plain URP background, voice loop working, no UI | Same plain background + 3 floating HUD panels in the Game view updating in real time; voice loop working with echo (use headphones to suppress -- see Part 12) |
| **Beam Pro alone** (no glasses) | Plain URP background, voice loop through Beam Pro speaker, no UI | Plain URP background + 3 HUD panels on the Beam Pro screen; voice loop |
| **Glasses on Beam Pro** | Plain URP background through glasses, voice loop through glasses speakers, no UI | Plain URP background + 3 HUD panels floating ~2m in front of you in the glasses, updating live as you talk |

The "plain URP background" is the dark sky from the empty template scene — we haven't added any 3D content yet. Phase 3 will start changing that (XREAL Eye camera feed, AR overlays anchored to real-world objects). For Phase 2 the HUD just floats over the dark void, which is the right end-state for a voice-assistant UI.

**Editor-specific gotchas:**

- **Aspect ratio**: Unity's Game view defaults to "Free Aspect" which uses whatever shape your Editor window happens to be. The panels were positioned for 16:9 (1920×1080). At weird aspect ratios the top-left pill might be off-screen at the top, the bottom transcript might clip. Fix: in the Game view, click the aspect dropdown → pick **16:9**. Matches what the Beam Pro display shows and what the glasses present.
- **Camera position**: the URP template's Main Camera defaults to `(0, 1, -10)` looking at origin. World-space Canvas at z=+2 in camera-local coordinates = at world position roughly `(0, 1, -8)`. Game view centres on it cleanly. If you've moved Main Camera around for any reason, the Canvas follows (it's a child).
- **Sophia's voice plays through Mac speakers in the Editor** — which means the echo loop from Detour 17 in Part 12 returns. You'll see yourself echo back as user_transcript chatter in the bottom panel. We chose not to fix this in code for Phase 1 because glasses geometry kills it; in the Editor you'll see it again. Use headphones (48 kHz capable) to suppress.
- **Backend services still need to be running** — same 4 terminals on the Mac (livekit-server, pf-gpu.sh, token_mint, agent worker). The Editor is just another client.

**To actually see the new HUD on the glasses you need to rebuild + reinstall** (the APK currently on the device is the pre-HUD build). Sequence:

1. Open Unity Editor.
2. `File > Build Profiles > Build` → overwrite `sophia-glasses/unity/sophia-glasses.apk`.
3. From Mac terminal:
   ```bash
   adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
   adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
   adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
   ```
4. Wear glasses → you'll see:
   - Top-left: grey `CONNECTING` → green `LISTENING` (the state pill)
   - Bottom: `You: (say something)` + `Sophia: (waiting)` placeholders
   - Right: `Q: -` + `Sources: -` placeholders
5. Talk. All three panels update in real time as the conversation goes.

**Prerequisite**: `SophiaOverlayUI` must be attached as a component on the SophiaConnection GameObject in `sophia-scene.unity`. Done in turn 65/66 per `sophia-agent/CHAT.md`. Quick check: open the scene in Unity, click SophiaConnection in Hierarchy, look at Inspector — `SophiaOverlayUI` should be listed under `SophiaConnection` (the script). If missing, add it (Inspector > Add Component > type `SophiaOverlayUI`), save scene, rebuild.

---

## Part 18 — File inventory: what got created and what each does

### New files

| File | Type | Purpose |
|---|---|---|
| `sophia-glasses/README.md` | doc | Project positioning, stack, phased plan |
| `sophia-glasses/AGENTS.md` | doc | Conventions: client-only, modularity, topic names, networking |
| `sophia-glasses/.gitignore` | config | Unity-standard ignores (Library/, Temp/, Builds/, etc.) |
| `sophia-glasses/client-sdk-unity/` | dependency | Fresh git clone of LiveKit Unity SDK with LFS binaries resolved |
| `sophia-glasses/unity/` | Unity project | The actual app |
| `sophia-glasses/unity/Assets/Plugins/Google.Protobuf.dll` | binary | Protobuf C# runtime, 473KB, manually dropped (LiveKit SDK doesn't bundle it) |
| `sophia-glasses/unity/Assets/Scripts/SophiaConfig.cs` | C# script | ScriptableObject schema for runtime config |
| `sophia-glasses/unity/Assets/Scripts/SophiaConnection.cs` | C# script | Voice loop MonoBehaviour: token → connect → publish mic → subscribe Sophia |
| `sophia-glasses/unity/Assets/Scripts/SophiaOverlayUI.cs` | C# script | AR HUD: builds Canvas + 3 panels at runtime, subscribes to text streams |
| `sophia-glasses/unity/Assets/Settings/SophiaConfig.asset` | ScriptableObject instance | All runtime config: Tailscale URL, agent name, room mode, etc. |
| `sophia-glasses/unity/Assets/sophia-scene.unity` | Unity scene | The scene that builds into the APK: contains SophiaConnection GameObject |
| `sophia-glasses/unity/Assets/TextMesh Pro/` | UPM assets | TMP Essential Resources (font, shaders, sprite, settings) |
| `sophia-glasses/unity/sophia-glasses.apk` | binary | The built Android APK |

### Modified files

| File | Change |
|---|---|
| `sophia-agent/src/token_mint.py` | Added `agent_name` field + `RoomConfiguration(agents=[RoomAgentDispatch(...)])`; fixed `with_ttl_seconds` → `with_ttl(timedelta(...))` |
| `sophia-glasses/unity/ProjectSettings/ProjectSettings.asset` | `insecureHttpOption: 2`, `microphoneUsageDescription` set, `AndroidMinSdkVersion: 29` |
| `sophia-glasses/unity/ProjectSettings/AudioManager.asset` | `m_SampleRate: 48000` |
| `sophia-glasses/unity/ProjectSettings/EditorBuildSettings.asset` | Scene list: only `sophia-scene.unity` at position 0 (removed default SampleScene) |
| `sophia-glasses/unity/Packages/manifest.json` | LiveKit SDK source switched from git URL to local disk path |

---

## Part 19 — Problems index: every issue we hit and why

In the order they happened. Each one with: symptom → root cause → fix → reference for depth.

1. **Burst transient compile error** — stale cache → quit + reopen Editor → ✓
2. **3000 Google.Protobuf errors** — LiveKit SDK doesn't bundle protobuf runtime → manual nupkg drop at `Assets/Plugins/Google.Protobuf.dll` → ✓ — `livekit_doubts.md` Q44 trap 2
3. **NuGet menu hidden** — Unity Safe Mode (triggered by compile errors) hides custom menus → bypass via manual DLL drop → ✓
4. **7 SDK API mismatches** — README outdated vs current SDK → read installed source under `Library/PackageCache/...` → ✓ — `livekit_doubts.md` Q44 trap 3 (full table)
5. **`liblivekit_ffi.dylib: slice is not valid mach-o file`** — LFS pointer files, Unity Package Manager doesn't run git-lfs → manual git clone with LFS, install from local disk → ✓ — `livekit_doubts.md` Q44 trap 1
6. **Re-introduced Google.Protobuf errors mid-fix** — my (Claude) ordering mistake → re-copied DLL → ✓
7. **HTTP allow UI toggle wouldn't stick** — per-platform tab confusion in Unity 6 → force-edited `ProjectSettings.asset` directly with Unity closed → ✓
8. **`token_mint` 500 `with_ttl_seconds`** — pre-existing latent bug in `sophia-agent/src/token_mint.py` (webapp's Next.js route never exercised it) → fixed: `with_ttl(timedelta(seconds=...))` → ✓
9. **macOS Editor mic permission** — Editor doesn't auto-prompt → added `Application.RequestUserAuthorization` + `microphoneUsageDescription` + user grants via System Settings → ✓
10. **Sample rate mismatch 44100 vs 48000** — `OnAudioFilterRead` runs at OUTPUT MIXER rate (follows macOS output device); EarPods are 44100-locked → set `AudioManager.m_SampleRate: 48000` AND user switched to MacBook Pro Speakers (native 48000) → ✓ — `livekit_doubts.md` Q42
11. **APK build failed: minSdkVersion 25 vs 29** — XREAL `xreal-auto-log-1.2.aar` requires API 29 → bumped Player Settings Minimum API Level to Android 10 Q (API 29) → ✓ — `livekit_doubts.md` Q45 gotcha 1
12. **Default URP bundle ID `com.UnityTechnologies.com.unity.template.urpblank`** — never customized → noted, deferred rename to `com.sophia.glasses` to Phase 2 hardening (requires `adb uninstall` first) → 🟡 deferred — `livekit_doubts.md` Q45 gotcha 2
13. **`UnityPlayerActivity does not exist` on `adb start`** — Unity 6 uses `UnityPlayerGameActivity` by default → discovered via `adb shell cmd package resolve-activity --brief` → ✓ — `livekit_doubts.md` Q45 gotcha 3
14. **App ran but no `[Sophia]` logs** — `EditorBuildSettings.asset` had only the empty `SampleScene.unity` in the build list, our `sophia-scene.unity` was excluded → added our scene at position 0, removed SampleScene → ✓ — `livekit_doubts.md` Q45 gotcha 4
15. **`Room.Connect failed` after token fetched** — token_mint returned `ws://localhost:7880` (Mac's view of localhost, unreachable from Beam Pro) and our client overrode `config.liveKitUrl` with it → removed the override; always use `SophiaConfig.liveKitUrl` → ✓ — `livekit_doubts.md` Q46
16. **`No microphone devices found` despite RECORD_AUDIO in manifest** — Android permission grant happens AFTER Unity's `Application.RequestUserAuthorization` returns (race) → workaround: user grants, then force-stop + relaunch → ✓ — `livekit_doubts.md` Q47 (proper fix deferred to Phase 2 hardening)
17. **Acoustic echo loop in macOS Editor** — Mac speakers → mic feedback, Unity has no AEC, LiveKit Unity SDK doesn't wire playback into APM → decided NOT to fix in code; predicted glasses geometry would kill it → confirmed on glasses (no echo) → ✓ — `livekit_doubts.md` Q41, Q43
18. **Phase 2 build #1: TMP NullReferenceException** — TMP Essentials Resources not imported (URP template ships TMP package but not the default font/sprite assets) → user ran `Window > TextMeshPro > Import TMP Essential Resources` → ✓ — `livekit_doubts.md` Q48
19. **Picker UI cramped/portrait on landscape glasses** — `SessionPicker.cs` had `CanvasScaler.referenceResolution = Vector2(1080, 1920)` (portrait reference) with an 800×1100 card on a 1920×1080 landscape screen; with `MatchWidthOrHeight=0.5` the scaling collapses to ~1.0 so the card renders at native pixel size, exceeds screen height, clips top + bottom → flipped reference to `Vector2(1920, 1080)` AND rewrote the card as a 1500×900 two-column layout (Private left / vertical divider / Team right, title spans top, Quit bottom-center). Player Settings → Resolution and Presentation → Default Orientation = Landscape Left, Allowed Orientations = landscape only → ✓ — `livekit_doubts.md` Q49
20. **HUD transcript text lags TTS audio (in-sync in browser, lagged in Unity)** — `SophiaConnection.LogTextStream` used `TextStreamReader.ReadAll()` which buffers the entire stream until end-of-stream; the agent's per-token transcript chunks were held until TTS playback finished, making the HUD read like a post-hoc subtitle → switched to `TextStreamReader.ReadIncremental()` with a `StringBuilder` accumulator and per-chunk broadcast (`while (!inc.IsEos) { inc.Reset(); yield return inc; accumulated.Append(inc.Text); OnTextStreamMessage(snapshot); }`). Non-obvious gotcha: `inc.Text` returns the LATEST CHUNK (one delta), not cumulative → ✓ — `livekit_doubts.md` Q50
21. **Agent state pill stuck on CONNECTING + RAG sources never populating** — `SophiaOverlayUI.ExtractJsonString` and `ExtractSourceFilenames` matched `"key":"value"` (no space after colon); Python `json.dumps()` defaults to `": "` (colon + space) as the separator so the marker `"kind":"` never appeared in `{"kind": "agent_state", ...}` payloads; `IndexOf` returned -1, silent drop, no error logged. Browser frontend works because `JSON.parse` is whitespace-tolerant per RFC 8259 → made both extractors whitespace-tolerant: match `"key":` then skip whitespace, then expect the opening `"` → ✓ — `livekit_doubts.md` Q51

Plus 5 known cosmetic warnings, non-blocking, deferred to Phase 2 cleanup:
- Multiple AudioSources on SophiaConnection GameObject (Phase 2 fix: child "SophiaSpeaker" GameObject)
- XREAL `ClassNotFoundException: ai.nreal.activitylife.FloatingManager` at startup (optional XREAL launcher class)
- `Plugin *.so is not 16KB-aligned` (Android 15+ concern; Beam Pro is Android 14)
- `No XR Manager settings found` (XR Plugin Management not configured; Phase 3 will configure for stereo rendering)
- `MissingReferenceException` on shutdown (text-stream handlers fire after `OnDisable` destroys MonoBehaviour; Phase 2 fix: unregister handlers in OnDisable)

---

## Part 20 — Current state + what's next

**At the moment this document was written:**

- ✅ Phase 1 SHIPPED on XREAL One Pro + Beam Pro. Voice loop end-to-end working with NO echo (validates Q43 prediction empirically).
- ✅ Phase 2 first iteration deployed. World-space HUD with 3 panels (state pill, transcript, RAG sources) renders in the glasses via TMP.
- ✅ **2026-05-22 — Phase 2 HUD parity polish complete (in code, awaiting user verification in next APK).** Four UX-parity bugs diagnosed + fixed so the Unity client matches the browser frontend feature-for-feature: landscape picker (Q49), incremental text streams so transcript moves in sync with TTS (Q50), whitespace-tolerant JSON extractor so agent state pill + RAG sources actually populate (Q51), Project Settings → System Sample Rate = 48000 workaround for Editor mic capture (no new Q — covered by Q42). Full narrative in **Part 21**. Three files touched: `SessionPicker.cs:225 + 244-310`, `SophiaConnection.cs:315-352`, `SophiaOverlayUI.cs:382-432`.

**Decided next sequence:**

1. **P2-1 — Verify the four 2026-05-22 fixes in Beam Pro**: rebuild APK, install, confirm landscape picker, transcript-in-sync-with-TTS, state pill flipping LISTENING→THINKING→SPEAKING, RAG sources populating with filenames. If any regression, fall back to per-fix bisect.
2. **P2-2 — Iterate the HUD layout** based on what the user sees in the glasses. Tunables already exposed via `[SerializeField]` so no recompile needed: `distanceFromCamera` (default 2.0m), `canvasSize` (1920×1080), `canvasScale` (0.0012). Plus per-panel font sizes editable via code.
3. **P2-3 — Phase 2 hardening (in parallel)**:
   - Fix mic permission race in code (Q47 path A poll-retry or path B JNI bridge).
   - Multiple-AudioSources warning: child "SophiaSpeaker" GameObject for remote audio.
   - Unregister text-stream handlers in `OnDisable`.
   - Rename bundle ID to `com.sophia.glasses`.
4. **P2-4 — XR Plug-in Management for stereo rendering**: configure XREAL XR Loader so the glasses get proper stereo, not flat 2D.
5. **P2-5 — Write `sophia-glasses/RUNBOOK.md`** mirroring `sophia-agent/RUNBOOK.md`. Day-one startup sequence so future sessions don't reconstruct from this document.
6. **Phase 3** — XREAL Eye camera snapshot → sophia-spatial-ai `/image-question` for vision RAG (image-grounded answers).
7. **Phase 4** — Signing + internal distribution.

---

## Part 21 — Phase 2 HUD parity polish (2026-05-22)

Phase 2 first cut (Part 17) got the world-space HUD with three panels rendering on the glasses, but when the user actually ran it side-by-side against the browser frontend four UX gaps showed up. None of these involved the backend — agent.py was already publishing everything correctly — so all four fixes landed in the three `sophia-glasses/unity/Assets/Scripts/*.cs` files. After this session the Unity client matches the React app behaviour for behaviour.

### Bug 1: Picker UI clipped/portrait on landscape glasses (Q49)

**Symptom:** The SessionPicker (the "Start Private Session" / "Join Team Session" card from Phase 2's room-mode chooser) rendered taller than wide both in the Editor Game view and in the glasses. Top of the title and bottom of the Quit button were clipped off the screen.

**Diagnosis path:** XREAL One Pro displays are 1920×1080 LANDSCAPE per eye. The Beam Pro projects in landscape. Three places need to agree:

1. **Player Settings → Resolution and Presentation** — Default Orientation `Landscape Left`, Allowed Orientations: only Landscape Left + Landscape Right checked. Pins the Android manifest's `screenOrientation` to landscape regardless of how the user holds the Beam Pro.
2. **Game view aspect (Editor only)** — top-of-tab dropdown → `1920×1080 Landscape`. Without this, the Editor preview is portrait and the picker looks cramped even when the APK renders fine on Beam Pro.
3. **`CanvasScaler.referenceResolution` for every runtime-built canvas.** `SessionPicker.cs:225` had `Vector2(1080, 1920)` (portrait reference). With `MatchWidthOrHeight = 0.5f` on a 1920×1080 screen, the scaling math becomes `sqrt(1920/1080) * sqrt(1080/1920) = 1.0` — the card renders at its native pixel size. Card was sized 800×1100, taller than 1080 screen height, so top + bottom clipped.

**Fix:** Flipped `referenceResolution` to `Vector2(1920, 1080)` AND rewrote the card body as a horizontal two-column layout (1500×900):

- Title + subtitle span the top, full width
- Vertical divider down the centre
- Left column: "Just you and Sophia" + green `Start Private Session` button
- Right column: "Join an existing team room" + room code input + blue `Join Team Session` button
- `Quit App` centred at the bottom

`SophiaOverlayUI.cs` world-space canvas was already `Vector2(1920, 1080)` at line 34 — world-space canvases use this as the rect dimensions (not screen resolution), so the HUD was already landscape and needed no change.

### Bug 2: HUD transcript text lags TTS (Q50)

**Symptom:** "Sophia: ..." text in the bottom transcript panel appeared AFTER Sophia finished speaking. In the browser frontend, text and TTS audio are in lockstep — you can read along with what she's saying.

**Diagnosis path:** LiveKit agents publish the agent's transcript via the `lk.transcription` text-stream topic, writing chunks incrementally as the LLM streams tokens (~25-50 ms ahead of the TTS audio that voices them). Two reader APIs in the Unity SDK:

| API | Behavior |
|---|---|
| `reader.ReadAll()` | Returns one `ReadAllInstruction` that completes when the sender CLOSES the stream. One emit at end-of-stream. |
| `reader.ReadIncremental()` | Returns a `ReadIncrementalInstruction` whose `Text` exposes the latest chunk. Yield-loop while `!IsEos`. Multiple emits, one per chunk. |

`SophiaConnection.LogTextStream` was using `ReadAll()`. Result: the agent's transcript chunks accumulated in the FFI buffer until EOS (which happens when the agent's turn ends, roughly when TTS finishes playing), then one big payload arrived and overwrote the panel. The browser doesn't see this because `@livekit/components-react`'s `useTextStream(topic)` hook is incremental under the hood.

**Fix:** Switch to `ReadIncremental` with a `StringBuilder` accumulator. Pattern from the SDK docstring:

```csharp
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
```

Two non-obvious details:

1. **`ReadIncrementalInstruction.Text` returns the LATEST chunk (one delta), not the accumulated text.** Forgetting to append yourself produces a flickering panel that cycles through individual chunks instead of growing.
2. **`StreamYieldInstruction.keepWaiting => !IsCurrentReadDone && !IsEos`** — the yield naturally unblocks at end-of-stream, so the `while (!inc.IsEos)` outer check is enough; no extra polling needed.

Side effect on the small JSON-payload topics (`sophia.rag_result`, `sophia.agent_events`): they typically arrive as a SINGLE chunk anyway (small enough to fit in one FFI frame), so the incremental path still gives one emit with the full payload. If a payload IS large enough to chunk, intermediate `accumulated` snapshots are partial JSON, but the tolerant key-by-key parsers in `SophiaOverlayUI` return null on missing markers — silent no-ops until the final chunk completes the JSON.

### Bug 3: Agent state pill + RAG sources never populating (Q51)

**Symptom:** Top-left state pill stuck on grey `CONNECTING` forever. Right-side RAG sources panel always showed `Q: -` / `Sources: -`, even though the agent's worker logs confirmed `sophia.agent_events` with `kind: agent_state` payloads were firing on every state transition and `sophia.rag_result` payloads on every turn.

This was the embarrassing one. The events were arriving over the wire — `Debug.Log` in `OnTextStreamMessage` confirmed the raw payload string contained the full JSON. But the panels weren't updating.

**Diagnosis path:** `SophiaOverlayUI.ExtractJsonString` had:

```csharp
var marker = "\"" + key + "\":\"";        // looking for: "kind":"
var i = json.IndexOf(marker, StringComparison.Ordinal);
if (i < 0) return null;
```

Python's `json.dumps()` defaults to `separators=(", ", ": ")` — space after every colon. So the agent's payload is:

```json
{"ts": 1748907000.12, "kind": "agent_state", "old": "listening", "new": "thinking"}
```

The marker `"kind":"` (no space) is nowhere in that string. `IndexOf` returns -1, `ExtractJsonString` returns null, `SetAgentState` is never called. Same blocker hit `"new"`, `"question"`, and `"source"` lookups — so the entire HUD was dark for state + RAG even though events were flowing freely.

The browser doesn't see this because `useTextStream` passes chunks straight to `JSON.parse(text)`, which is whitespace-tolerant per RFC 8259.

**Two possible fixes:**

1. **Agent side:** call `json.dumps(payload, separators=(",", ":"))` to emit compact JSON with no spaces. Saves a few bytes per message.
2. **Client side:** make the Unity extractor whitespace-tolerant.

We picked option 2 because it's self-contained — doesn't depend on the agent's serialization choices, which could change later for other reasons. Now both `ExtractJsonString` and `ExtractSourceFilenames` match `"key":` then skip whitespace before expecting the opening `"`:

```csharp
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

**Diagnostic checklist saved for future "browser-works-Unity-doesn't" parser bugs** (full version in Q51): (1) `Debug.Log` the raw payload string in `OnTextStreamMessage` to confirm it's arriving over the wire; (2) if arriving but not rendering, the bug is in the Unity-side parser, not in transmission; (3) common pitfalls in homemade JSON parsers — whitespace after colons (this one), escaped quotes inside string values, unicode escape sequences (`\uXXXX`), nested objects/arrays. Once payloads grow past flat string maps, swap to `Newtonsoft.Json` or `System.Text.Json` instead of `IndexOf` scans.

### Bug 4: Editor mic sample-rate mismatch recurring (Q42 follow-up)

**Symptom:** Even with EarPods unplugged, `RtcAudioSource#1 audio frame #N metadata mismatch actualRate=44100 actualChannels=2 expectedRate=48000 expectedChannels=2` errors spammed the Editor Console on every captured frame. No new agent dispatch ever recognized the user's speech because every frame was being dropped at the FFI layer.

Q42 already explains the root cause: `OnAudioFilterRead` runs at Unity's OUTPUT MIXER rate, which follows the active macOS output device, and 44.1kHz-only devices break LiveKit's 48kHz `RtcAudioSource` constructor expectation.

What was new this session: even with EarPods unplugged, the user's iPhone showing up as a Continuity Camera microphone got picked as `Microphone.devices[0]` and also runs at 44.1kHz — same symptom, different specific device.

**Workarounds applied (not logged as a new Q since Q42 covers it):**

1. **Edit → Project Settings → Audio → System Sample Rate = 48000** — forces Unity's audio system to resample to 48k regardless of device. Strictly better than relying on the OS-active device being 48k.
2. (Recommended, not yet code-fixed) Change `SophiaConnection.cs` to prefer `MacBook Pro Microphone` by name lookup instead of `Microphone.devices[0]`. Built-in MacBook mics are mono 48 kHz native — no resample drama.

Beam Pro APK is unaffected (Android USB Audio Class is 48kHz native), so this is purely an Editor-time annoyance — but blocking enough to halt voice-loop validation in Editor until fixed.

### Cumulative file state after Part 21

| File | Lines touched today | What changed |
|---|---|---|
| `SessionPicker.cs` | 225, 244-310 | Landscape `CanvasScaler` reference + two-column 1500×900 card layout |
| `SophiaConnection.cs` | 315-352 | `LogTextStream` rewritten to use `ReadIncremental` + `StringBuilder` |
| `SophiaOverlayUI.cs` | 382-432 | Both JSON extractors made whitespace-tolerant |

After the user (a) rebuilds the APK, (b) sets Player Settings to landscape, (c) sets Project Settings → Audio System Sample Rate = 48000, the Unity client should render and behave indistinguishably from the browser frontend for the voice loop + 3-panel HUD. Q&A entries for all three new bugs live at `livekit_doubts.md` Q49–Q51.

---

## Appendix A — Reference reading order

For someone new picking this up:

1. **This document** (`unity_approach.md`) — the narrative. Start here.
2. **`sophia-glasses/AGENTS.md`** — current conventions (modularity, topic names, networking, what NOT to do).
3. **`sophia-glasses/README.md`** — high-level project positioning.
4. **`sophia-agent/CHAT.md` turns 48–65** — the chronological session log. Use as a search index when the narrative skips a detail.
5. **`livekit_doubts.md` Q26, Q27, Q41–Q51** — technical depth on each gotcha (Q49–Q51 are the 2026-05-22 HUD parity fixes covered narratively in Part 21).
6. **`livekit_deployment.md` Q25, Q26, Q27** — XREAL architecture, Beam Pro dev environment, Phase 1 walkthrough.
7. **The C# source files** under `sophia-glasses/unity/Assets/Scripts/`. All three are small (<300 lines each) and heavily commented.
8. **Appendix C of this document** — multi-user discussion (Scenario A shared room vs Scenario B isolated rooms), real-world use cases, how to enable Scenario A from current state, and the rolling Q&A log for future multi-user questions.

---

## Appendix B — Full operational sequence: from "APK built" to "talking through glasses"

Every command runnable as-is on the Mac. Walk through these in order the first time; subsequent dev sessions skip to Step 9 (the iterative loop).

### Step 0 — Backend services must be running on the Mac

The APK is just the client. Without the server-side stack alive, it'll install fine and connect to nothing. Open four terminals on the Mac and start each:

```bash
# Terminal 1 — LiveKit SFU (the room server)
cd '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-agent'
livekit-server --config infra/livekit.yaml --dev

# Terminal 2 — Kubernetes port-forwards (whisper/qwen/kokoro/sophia-spatial-ai on AWS)
cd '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-agent'
./infra/pf-gpu.sh

# Terminal 3 — Token mint (issues JWTs with agent dispatch)
cd '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-agent'
uv run uvicorn src.token_mint:app --port 8001 --reload

# Terminal 4 — Sophia agent worker (the actual voice agent)
cd '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-agent'
uv run python src/agent.py dev
```

Leave all four running for the entire dev session.

Sanity check from a 5th terminal:
```bash
curl -sI http://localhost:7880 | head -1       # → HTTP/1.1 200 OK   (SFU)
curl -sI http://localhost:8001/docs | head -1  # → HTTP/1.1 200 OK   (token mint)
```

### Step 1 — Beam Pro USB-connected (with Beam Pro's own speaker, glasses NOT yet plugged in)

Plug the Beam Pro into the Mac via USB-C. Make sure USB mode = File Transfer (not Charge Only) — check by swiping down on the Beam Pro's notification shade.

```bash
adb devices -l
```

Expected output:
```
List of devices attached
RHLM56L118630F   device usb:1-2 product:X4000 model:X4000 device:X4000
```

If you see `unauthorized`, accept the "Allow USB debugging" prompt on the Beam Pro screen. If you see nothing, USB Debugging is off in Developer Options.

### Step 2 — Install the APK

```bash
adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
```

Expected output:
```
Performing Streamed Install
Success
```

The `-r` flag means "reinstall, preserving the app's data". For a clean wipe (rare, only if data is corrupt), use `adb uninstall com.UnityTechnologies.com.unity.template.urpblank` first.

### Step 3 — Find the launchable activity (only the first time)

Unity 6 uses a non-default activity name. Discover it:

```bash
adb shell cmd package resolve-activity --brief com.UnityTechnologies.com.unity.template.urpblank | tail -1
```

Expected output:
```
com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
```

Memorize the activity name — `com.unity3d.player.UnityPlayerGameActivity` — you'll use it in every `am start` command from now on.

### Step 4 — Launch the app, with logs streaming in another terminal

This is the pattern you'll use after EVERY rebuild. Run these in two terminals:

**Terminal A — launch the app:**
```bash
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c                                                                                    # clear log buffer
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
```

**Terminal B — watch logs live:**
```bash
adb logcat | grep -E 'Sophia|LiveKit|TMP|FATAL|NullReference'
```

Press `Ctrl+C` in Terminal B to stop the tail. The app keeps running on the device.

### Step 5 — Grant microphone permission (first launch only)

On the very first launch after install, Android will show a permission dialog: "Allow Sophia voice agent to record audio?". The Beam Pro's screen will display this. **Tap "While using the app"** (or "Allow only this time" — either grants it).

You'll see in Terminal B's log stream:
```
[Sophia] No microphone devices found.    ← script bailed before user tapped Allow
```

That's the known race condition (Detour 16, `livekit_doubts.md` Q47). Force-stop + relaunch and the second launch works:

```bash
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
```

This time Terminal B should show the full happy path:
```
[Sophia] Starting. room='sophia-glasses-...' identity='glasses-...' server='ws://100.69.34.194:7880'
[Sophia] Got token (len=457) for url=ws://100.69.34.194:7880
[Sophia] Connection state: ConnConnected
[Sophia] Connected to room 'sophia-glasses-...'
[Sophia] Using microphone [0] 'Android audio input'
[Sophia] Microphone publishing. You can speak now.
[Sophia] Participant connected: agent-AJ_...
[Sophia] Track subscribed: kind=KindAudio from participant='agent-AJ_...'
[Sophia] Remote audio wired to AudioSource on SophiaConnection.
[Sophia][agent_events] payload={"kind": "agent_state", "new": "listening"}
```

Verify permission is now persistent (one-time check):
```bash
adb shell dumpsys package com.UnityTechnologies.com.unity.template.urpblank | grep RECORD_AUDIO
# expected: android.permission.RECORD_AUDIO: granted=true, ...
```

### Step 6 — Test voice loop with Beam Pro speaker

Hold the Beam Pro near your face. Speak: "Hello, who are you?". Sophia replies through the Beam Pro's built-in speaker within ~1-3 seconds.

You'll see in the log:
```
[Sophia][agent_events] payload={"kind": "user_state", "old": "listening", "new": "speaking"}
[Sophia][agent_events] payload={"kind": "user_transcript", "text": "Hello, who are you?", "is_final": true, ...}
[Sophia][agent_events] payload={"kind": "agent_state", "old": "listening", "new": "thinking"}
[Sophia][agent_events] payload={"kind": "agent_state", "old": "thinking", "new": "speaking"}
[Sophia][transcription] from='agent-AJ_...' payload=Hi, I'm Sophia, ...
```

If this works, Beam Pro-alone Phase 1 is validated.

### Step 7 — Switch to glasses (set up wireless adb FIRST)

Glasses plug into the same USB-C port the cable is using. So you need adb running over WiFi/Tailscale before you unplug the USB cable, otherwise you lose access for installs/logs.

**While Beam Pro is STILL plugged into Mac via USB:**

```bash
adb tcpip 5555                          # tell adbd to listen on port 5555 over network
adb connect 100.69.32.120:5555          # connect via Tailscale (Beam Pro's Tailscale IP)
adb devices                             # confirm BOTH entries appear
```

Expected `adb devices` output:
```
List of devices attached
RHLM56L118630F           device                          ← USB
100.69.32.120:5555       device                          ← wireless
```

**Now you can unplug USB safely.** adb will keep working over the Tailscale connection.

### Step 8 — Plug glasses into Beam Pro + wear them

Plug the XREAL One Pro cable into the Beam Pro's USB-C port. The glasses' display lights up showing the Beam Pro's screen mirrored.

Put on the glasses.

The app may still be running from Step 6. Either way, restart it cleanly so you get a fresh session:

```bash
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
```

Watch the logs in another terminal:
```bash
adb logcat | grep -E 'Sophia|LiveKit|TMP|FATAL'
```

You'll hear Sophia through the **glasses' temple speakers** (which is what the OS auto-routes audio to when XREAL is plugged in). You should also see the HUD overlay (state pill, transcript, RAG sources) in the glasses display.

### Step 9 — Iterative dev loop after each rebuild

Every time you change code in Unity and rebuild:

```bash
# 1. Rebuild in Unity (Cmd+B or File > Build Profiles > Build) → overwrites the APK

# 2. Reinstall + restart on Beam Pro (via wireless adb if glasses are plugged in)
adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity

# 3. Watch logs in another terminal
adb logcat | grep -E 'Sophia|LiveKit|TMP|FATAL'
```

That's a 3-command cycle that works whether the Beam Pro is on USB or wireless. Wraps the entire dev loop.

### How to view adb logs — patterns

`adb logcat` is a big firehose of every system log. Filter or it's unreadable.

**Live tail with filter (most useful day-to-day):**
```bash
adb logcat | grep -E 'Sophia|LiveKit|TMP|FATAL|NullReference'
```

**Live tail with NO filter (for debugging weird Android-system issues):**
```bash
adb logcat
```

**Snapshot of recent buffer (one-shot, not streaming):**
```bash
adb logcat -d | grep -E 'Sophia|LiveKit' | tail -100
```

**Snapshot saved to file (useful for sharing with a teammate when something breaks):**
```bash
adb logcat -d > /tmp/sophia.log
# then share or grep the file:
grep -E 'Sophia|FATAL' /tmp/sophia.log | head -100
```

**Errors only (red-flag scan):**
```bash
adb logcat *:E
```

**Clear the buffer (start fresh — always do this before relaunching):**
```bash
adb logcat -c
```

**Pretty color output (nice in iTerm):**
```bash
adb logcat -v color | grep -E 'Sophia|LiveKit'
```

**Time-stamped with PID for filtering by process:**
```bash
adb shell pidof com.UnityTechnologies.com.unity.template.urpblank
# returns a number like 17353
adb logcat --pid=17353        # only this app's logs
```

### Quick troubleshooting matrix

| Symptom | Most likely cause | Quick check |
|---|---|---|
| `adb devices` shows nothing | USB mode wrong, or USB debugging off | Swipe down on Beam Pro, change USB to File Transfer; check Developer Options |
| `adb install` says `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | Signature mismatch (rare) | `adb uninstall com.UnityTechnologies.com.unity.template.urpblank` then reinstall |
| Logs show `[Sophia] Starting` but then `Room.Connect failed` | Backend not running, OR wrong Tailscale URL in SophiaConfig | `curl http://localhost:7880` from Mac; verify SophiaConfig.asset URL |
| Logs show `[Sophia] No microphone devices found` | Permission dialog hasn't been answered | Look at Beam Pro screen, tap Allow, force-stop + relaunch |
| Logs show `[Sophia] Microphone publishing` but Sophia never speaks | Agent worker not running OR `agent_name` mismatch | Check Terminal 4 logs for `entrypoint` line on each new room |
| App installs but nothing in logs at all | Wrong activity name, or app crashed at boot | `adb logcat *:E | grep FATAL` to see crash; verify `am start` uses `UnityPlayerGameActivity` |
| Wireless adb stopped working | Beam Pro slept/rebooted, lost adbd | Plug USB back in → `adb tcpip 5555` → `adb connect 100.69.32.120:5555` again |
| `am start` says `Activity class ... does not exist` | Using old `UnityPlayerActivity` name | Use `UnityPlayerGameActivity` (Unity 6 default), or re-run Step 3 to confirm |

---

## Appendix C — Multi-user discussion

Living section. The current architectural model + product use cases for multi-user are captured here. **All future multi-user questions get appended as new Q&A entries inside this appendix** rather than scattering across other Parts. Single home for the topic.

### The model: two scenarios, both already supported by the backend

Multi-user reduces to one config field on the client: `SophiaConfig.roomName`.

| | Scenario A — Shared room | Scenario B — Isolated rooms |
|---|---|---|
| **Config** | `roomName = "maintenance-bay-3"` (or any fixed string) | `roomName = ""` → auto-generates `sophia-glasses-<uuid>` per launch |
| **Room** | All users join the SAME LiveKit room | Each user joins their OWN room |
| **Agent** | ONE Sophia worker, shared across all users in the room | ONE Sophia worker per room (one per user) |
| **Chat context** | Shared — Sophia knows everyone's questions | Isolated — each user has private history |
| **Default in our code** | Off (must explicitly set the field) | **On** (this is what runs today) |

LiveKit's SFU handles room routing for us. Two users in `room-A` only see/hear each other; users in `room-B` are completely isolated. We get this for free, didn't have to build anything.

### Real-world use cases

**Scenario A (shared room) unlocks team-mode use cases:**

- **Field technician + remote expert.** On-site tech wears the XREAL glasses in a maintenance bay. Remote expert joins via the browser frontend from the office. Both in the same LiveKit room. Tech asks Sophia "what's the recommended torque for the M12 bolt?". Sophia answers with PDF source. Remote expert sees the same answer + sources on their browser, can interject with their own voice question. Sophia handles both, maintains shared context. Knowledge-augmented mentorship without a separate phone call.
- **Inspection + supervisor recording.** Tech does walkthrough wearing glasses. Supervisor on browser sees the full transcript + RAG sources in real time. Conversation auto-archives. Hands-free inspections with built-in audit trail.
- **Training scenarios.** Senior tech wearing one pair of glasses, trainee wearing another, both in the same shared room. Senior demonstrates how to phrase questions, trainee observes both the conversation AND the visual overlays in their own glasses. Ride-along learning without splitting attention.
- **Multi-tech equipment teardown.** Three people around a piece of equipment, all wearing glasses, all in `equipment-bay-7`. Anyone can ask Sophia anything; everyone hears the answer; everyone sees the source citations. Collaborative diagnostics where everyone stays informed.

**Scenario B (isolated rooms) is for individual use at scale:**

- **50 field techs across multiple sites.** Each launches the app, gets their own room and their own Sophia worker. Total isolation. Standard enterprise rollout — every user is independent.
- **Privacy-sensitive conversations.** Customer service rep asking Sophia about a customer's account, sales engineer asking about a deal — these shouldn't be visible to other employees. Isolated rooms enforce that.
- **Multi-tenancy.** Different customer companies, different deployments, different RAG indexes per tenant — all running on the same backend but partitioned by room naming convention (e.g., `acme-corp-<userid>`, `widgets-inc-<userid>`). SaaS-style deployment.

### How it works technically (already in place)

1. **Room ID is just a string.** Client tells the SFU which room to join via the JWT. Same string → same room. Different strings → different rooms. No "room creation" API exists — rooms exist when at least one participant joins.

2. **Agent dispatch is per-room.** `token_mint.py` attaches `RoomConfiguration(agents=[RoomAgentDispatch(agent_name="sophia-agent")])` to every JWT (the Part 6 fix). When the first user joins a given room, the SFU sees this claim and asks the registered worker named "sophia-agent" to dispatch a subprocess into that room. **Subsequent users joining the same room don't trigger a new dispatch** — there's already one Sophia in the room, they just join the existing conversation.

3. **Worker subprocess = one chat_ctx, one LLM session.** The Sophia worker in a given room maintains a single `chat_ctx.messages[]` array. Every user's speech adds to it; every Sophia response is appended. The shared LLM call sees the whole history every turn. That's the technical mechanism for shared context in Scenario A.

4. **Per-speaker attribution.** LiveKit's `user_input_transcribed` event includes a `speaker_id` field — derived from the participant's `identity` (which we set as `glasses-<uuid>` or whatever). So Sophia (and the UI) can distinguish "this question came from Anna" vs "this question came from Ben". For Scenario A, this is what would let Sophia address users by name once we wire it up.

5. **Scenario B is the default** because `SophiaConfig.roomName` is empty in the asset, and `SophiaConnection.cs` generates a unique room per launch:

```csharp
_resolvedRoom = string.IsNullOrWhiteSpace(config.roomName)
    ? $"sophia-glasses-{Guid.NewGuid().ToString("N").Substring(0, 12)}"
    : config.roomName.Trim();
```

Two glasses launching simultaneously today already get independent rooms and independent Sophias. **Multi-user Scenario B is shipping right now.**

### How to enable Scenario A from where we are today

Three paths, in increasing order of polish:

**Path 1 — Hardcoded shared room for a specific deployment.** Edit `SophiaConfig.asset` in Unity, set `roomName: "maintenance-bay-3"`. Rebuild APK. Install on all the glasses going into that bay. Everyone wearing that APK joins the same room. Testable today in 10 minutes. Limitation: one-room-per-build, you'd have to maintain different APK variants for different teams.

**Path 2 — Runtime room picker in the app.** Add a startup UI: "Enter session code" with on-screen keypad, OR scan a QR code printed on a wall in each maintenance bay (QR encodes the room name). Picker writes to `SophiaConfig.roomName` at runtime before `OnEnable` fires. One APK serves any room. ~half day of Unity work — one scene with TMP_InputField + a QRCodeScanner script using the Beam Pro camera. Most flexible path.

**Path 3 — Deep-link / Intent-based joining.** Pair the glasses APK with a companion mobile app (or web page) where the user picks who to call / which session to join. The companion app fires an Android intent like `intent://sophia-glasses/room/abc-123` that launches our APK with the room pre-set. Most enterprise-y but most setup. Right for production rollout.

**For the web frontend** to participate in Scenario A:
- Currently agent-starter-react auto-generates a UUID room name per session.
- Trivial change: honor a `?room=foo` URL query param if present.
- Sharing a URL like `localhost:3000?room=maintenance-bay-3` then lets browser users join an existing glasses session.
- Full code-level change spec in `livekit_deployment.md` Q23. ~5 min edit.

### Caveats worth knowing before shipping Scenario A

| Caveat | Impact | Mitigation |
|---|---|---|
| **Whisper has no speaker diarization.** When two people talk simultaneously, audio mixes before STT sees it. Result: garbled transcription, sometimes attributed to whichever participant the SFU happened to route. | Mild — most conversations are turn-based, simultaneous speech is rare | Use VAD-based speaker isolation if it becomes a problem. Or accept it as polite-conversation-required UX. |
| **Shared `chat_ctx` means no privacy between users in the same room.** Everyone sees everyone's questions and Sophia's answers. | Intentional for team scenarios, broken for "I want a private side-channel" | Use Scenario B for private side-channels. Or add per-user "whisper to Sophia" modes via key chord in Phase 3. |
| **Cold-fork latency on first user per room.** Spawning the agent worker subprocess takes ~2-3s. First user in `maintenance-bay-3` waits; users 2-10 joining shortly after are instant. | Mild on Scenario A (one cold start per room), worse on Scenario B (every user is "first user") | `AgentServer(num_idle_processes=2)` keeps a pool of pre-warmed workers. Already documented as a Phase 2 cleanup. |
| **TTS plays for everyone.** Sophia's voice is broadcast to all participants in the room — the asker AND the bystanders. | Feature for team mode (everyone stays in sync), annoyance for some workflows | Add per-user TTS subscription control in Phase 3 if needed. |
| **Worker memory cost in Scenario B at scale.** Each room = one worker subprocess, ~200-300 MB resident. 50 concurrent users (Scenario B) = ~15 GB just for workers. | Real cost when we scale | Move the worker pool to AWS, scale horizontally. Backend is already designed for that — single config change to migrate from Mac → EC2. |

### Bottom line

- **Scenario B is already live.** Right now, 10 glasses APKs launched simultaneously give you 10 independent Sophia sessions. Multi-user-at-scale is shipping.
- **Scenario A is one config field away.** Edit `SophiaConfig.asset.roomName`, rebuild → shared team mode for that deployment. Test in 10 minutes.
- **The interesting product question is which scenarios your industrial-equipment-manual use cases actually need.** Field tech alone troubleshooting in front of a pump = Scenario B. Tech + remote senior expert pairing = Scenario A. Most enterprise deployments end up being a mix: default Scenario B, with a "Join session" UI for the team modes.
- **Backend changes needed: zero.** Frontend changes for the picker UI: half a day on the glasses side, 5 minutes on the web side. The entire multi-user story is a frontend product decision now, not a backend engineering project.

### Q&A log (newest at the bottom)

Future multi-user questions get appended here as `Q1`, `Q2`, etc. Each entry: the question, the answer, the date, and any code/config changes that came out of it.

---

#### Q1 (2026-05-22) — Production multi-tenant deployment: where does the backend live, and how do multiple client companies use Sophia simultaneously with both Scenario A and B?

**Context:** Today the backend (livekit-server + token_mint + agent worker) runs on a single MacBook for development. The product is XREAL One Pro + Beam Pro glasses sold to multiple corporate clients (Acme Corp, Globex Inc, etc.), each with many employees who need both shared-room (Scenario A) and isolated-room (Scenario B) modes.

**Three deployment models, fitting different customer profiles:**

| Model | What we run | Per-client cost | Use case |
|---|---|---|---|
| **A. Single multi-tenant SaaS** | One AWS deployment, all clients share infrastructure, partitioned by `client_id` | Lowest | Self-serve SMB, default tier |
| **B. Dedicated per-client** | Separate VPC / EKS cluster per client, fully isolated | High | Enterprise, regulated industries (healthcare, finance, gov) |
| **C. Hybrid** | Control plane (auth, billing, dashboards) is SaaS; data plane (livekit-server + agent workers) can be shared OR dedicated per tier | Medium | Default tiering — "Pro" on shared, "Enterprise" on dedicated |

**Recommendation: start with Model C (hybrid).** SaaS multi-tenant for everyone by default, opt-in dedicated deployment for clients who pay for it / require it for compliance. This is what Zoom, Slack, Notion all do.

**Recommended production architecture**

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONTROL PLANE (shared SaaS)                  │
│                                                                 │
│  Auth (Cognito / Auth0 / per-client SSO)                       │
│  Identity DB (DynamoDB / Postgres):                            │
│    (user_id, client_id, role, permitted_rooms, device_id)      │
│  Admin dashboard (per-client RAG mgmt, user provisioning)      │
│  Billing & metering                                             │
│  Audit log & telemetry (OpenTelemetry → Grafana)               │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ JWT issuance
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATA PLANE (per-region)                      │
│                                                                 │
│  Token-mint service (ECS / Lambda, FastAPI)                    │
│   ↓ validates user, looks up client_id, mints JWT with         │
│   ↓ room_name = "{client_id}/{session_id}"                      │
│   ↓ + RoomConfiguration(agents=[RoomAgentDispatch(...)])        │
│                                                                 │
│  livekit-server cluster (EC2 / EKS, OSS Apache 2.0)            │
│   • Multi-region with global load balancer                     │
│   • TURN servers for NAT traversal                              │
│   • TLS (wss://) endpoints                                      │
│                                                                 │
│  Sophia agent worker pool (EKS, autoscaling)                   │
│   • Each room → one worker subprocess                           │
│   • Pool sized to peak concurrent rooms × ~250MB each          │
│   • Per-worker config loads client_id from room name            │
│   • Per-client RAG index lookup before retrieve                 │
│                                                                 │
│  Model serving (existing AWS GPU pods):                        │
│   • Whisper STT (shared, no client coupling)                    │
│   • Qwen3-VL LLM (shared)                                       │
│   • Kokoro TTS (shared)                                         │
│   • sophia-spatial-ai with per-client RAG indexes:             │
│       ├─ acme-corp/manuals-v3                                   │
│       ├─ globex-inc/manuals-v1                                  │
│       └─ ...                                                    │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ WebRTC (wss://livekit.sophia.ai)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       END-USER DEVICES                          │
│                                                                 │
│  Acme Corp's John   → glasses + Beam Pro → app w/ Acme tenant  │
│  Acme Corp's Anna   → glasses + Beam Pro → app w/ Acme tenant  │
│  Globex's Sarah     → glasses + Beam Pro → app w/ Globex tenant│
│                                                                 │
│  All devices run the SAME APK, configured at first launch via  │
│  SSO login → backend resolves client_id → app caches creds      │
└─────────────────────────────────────────────────────────────────┘
```

**Tenant isolation mechanism (the key)**

Room name becomes a hierarchical key: `{client_id}/{session_id}`.

- **Scenario A (Acme's shared bay)**: room = `acme/maintenance-bay-3`. Any Acme employee can join. Globex employees cannot.
- **Scenario B (John's private session)**: room = `acme/user-john-uuid`. Only John's JWT grants access.

Three layers of isolation enforced by the backend:

1. **JWT issuance**: token_mint won't issue a JWT for a room whose `client_id` prefix doesn't match the authenticated user's tenant. Even if Sarah at Globex *knows* the room name `acme/maintenance-bay-3`, she can't get a JWT for it.
2. **SFU validation**: livekit-server validates the JWT on connect. A forged room name fails JWT verification.
3. **Agent worker RAG scoping**: when the Sophia worker dispatches into `acme/...`, it parses the room name, extracts `acme`, and configures its `/retrieve` calls to query only `acme-corp/manuals-v3`. Globex's manuals are never visible to Acme's Sophia.

Net effect: zero cross-tenant data leakage even though everyone shares the same livekit-server cluster.

**What each party has to do**

**Us (Sophia platform team)**
- Run the entire backend stack on AWS — control plane + data plane.
- Provide an admin dashboard for client onboarding: create tenant, upload PDFs to that client's RAG index, configure SSO, generate enrollment codes.
- Maintain the Android APK (signed by us, distributed via Play Store private channel OR MDM).
- Provide SDKs / docs for the IT teams at large clients who want to integrate with their own systems.

**Client IT admin (one per client)**
- Sign up via our admin dashboard, configure their tenant.
- Upload their equipment manual PDFs to their RAG index.
- Configure SSO connection (SAML / OIDC with their corporate identity provider — Okta, Azure AD, etc.).
- Distribute Beam Pro + glasses hardware to their employees.
- Push the Sophia APK to employee devices via their MDM (MobileIron, Intune, etc.), OR have employees install from Play Store private channel.
- (Optional) print QR codes for shared session rooms (`acme/bay-3`, `acme/bay-7`, etc.) and stick them on walls in those locations.

**End user (Acme employee, e.g., John the field tech)**

First time:
1. Picks up Beam Pro + XREAL glasses from IT
2. Plugs glasses into Beam Pro
3. Taps Sophia app icon
4. **SSO login screen** appears in the glasses → John signs in with his Acme corporate credentials (Okta SSO redirect)
5. Backend identifies John, returns auth token, app caches it locally
6. App auto-launches voice loop in John's personal room (`acme/user-john-uuid`)

Every day after:
- Plug in glasses, tap app icon, voice loop starts. ~3 seconds.

Daily — Scenario B (private):
- Default. App joins John's personal room. Only John and Sophia. Private chat history.

Daily — Scenario A (team):
- Tap "Join session" in the in-glasses menu. Three options:
  - **Scan QR**: look at the wall-mounted QR for the bay. Beam Pro camera reads it → joins `acme/bay-3`.
  - **Enter code**: virtual keypad in the glasses, type the session code given by the team lead.
  - **Pick from list**: shows currently active rooms in the user's tenant (Acme's rooms only, never Globex's).
- App rejoins SFU under the new room name. Everyone in that room shares one Sophia.

**End-user devices need**
- XREAL One Pro glasses + XREAL Beam Pro (the flagship combo).
- WiFi or 4G/5G connectivity on the Beam Pro (no special VPN setup needed — TLS WebRTC to our public endpoint).
- The Sophia APK installed (via MDM or Play Store).
- That's it. No per-device provisioning steps for the user.

**Individual + team conversations side-by-side (same user, same day)**

The architecture supports both simultaneously:

- **Morning** — John alone troubleshooting a pump: launches app → defaults to `acme/user-john-uuid` (Scenario B) → private Sophia. "What's the recommended torque for the M12 bolt?" → answered from Acme's manual.
- **Mid-morning** — Senior engineer Sarah joins: John taps "Join session", shares the code; Sarah enters it → both in `acme/user-john-uuid`. Both audios reach the same Sophia, shared context, both hear answers.
- **Afternoon** — Team huddle in bay 7: John, Sarah, Mike scan the wall QR → all join `acme/bay-7`. Bay-specific context potentially pre-loaded.
- **Evening** — John ends shift, next morning defaults back to his personal room.

All while Globex's Sarah is running her own conversations in `globex/bay-2`, completely invisible to Acme employees.

**Migration path from current MacBook setup**

The code we have today works in production as-is. The lift is mostly operational, not engineering:

| Today (MacBook) | Production (AWS) | Lift |
|---|---|---|
| `livekit-server --config infra/livekit.yaml --dev` | Same binary, EC2/EKS, TLS cert, multi-region | DevOps |
| `pf-gpu.sh` port-forwards to AWS pods | Direct VPC routing, no port-forwarding | DevOps (already on AWS) |
| `token_mint.py` simple JWT issuer | Same code + add tenant validation (client_id check, room-name prefix enforcement) | ~1 day Python |
| `agent.py` worker | Same code + add per-client RAG index lookup (parse room name → set retrieve index) | ~half day Python |
| `SophiaConfig.asset` with hardcoded Tailscale URL | URL = `wss://livekit.sophia.ai` (our public endpoint), pulled from app config or first-launch SSO | Already a runtime config field |
| No auth | SSO login flow in app | ~1-2 weeks (proper SSO integration + caching) |
| Single user | Tenant database (DynamoDB), admin dashboard | ~2-3 weeks |
| No MDM | APK signing + Play Store private channel + MDM integration guides | Ops |
| No monitoring | OpenTelemetry → Grafana, audit logs to CloudWatch | ~1 week |

Total: roughly **1-2 person-months of focused work** to go from "works on Avinash's Mac" to "self-serve SaaS that any client can sign up for". Most of the architectural pattern (LiveKit + per-room agent dispatch + JWT-encoded room names) was already correct from day one — production-readiness is mostly auth + tenant management + ops, not rebuilding the voice agent.

**Key code/config changes implied by this answer (none built yet — these are the to-do list when we start production work):**

- `token_mint.py`: add `client_id` resolution from auth token, validate `room` parameter starts with `{client_id}/`, refuse if mismatch.
- `agent.py`: parse `room.name`, split on `/`, set RAG index based on `client_id` prefix.
- Unity APK: SSO login scene before SophiaConnection runs, cached credential storage (Android Keystore for the auth token).
- New: admin dashboard service (likely Next.js + the same shared backend).
- New: tenant database schema (DynamoDB or Postgres).
- New: APK signing pipeline + Play Store private channel setup + MDM integration documentation.

---

#### Q2 (2026-05-22) — What's in the APK today (empty roomName)? Confirming the two cases: Case 1 = same agent code, different rooms, different sessions; Case 2 = same agent in same room, same shared session.

**Current state of the APK shipped today:** `SophiaConfig.asset` has `roomName = ""` (empty string). Verified by source inspection AND by runtime logs from multiple recent launches showing different UUID-suffixed room names each time:

```
[Sophia] Starting. room='sophia-glasses-d9fef980b0b3' ...
[Sophia] Starting. room='sophia-glasses-763105ed058b' ...
[Sophia] Starting. room='sophia-glasses-043aeeb2f615' ...
```

So today's APK is **Case 1** (Scenario B / isolated rooms per launch).

**Case 1 confirmed with one precision.** Your understanding: "each process in Beam Pro deploys same Sophia agent but in different rooms = different sessions". Correct, with this nuance on the word "same agent":

There's a single agent **worker** running on the Mac (the `agent.py` process in Terminal 4). When the SFU dispatches "agent named sophia-agent into room X", the worker **forks a subprocess** to serve that specific room. Each room gets its own subprocess.

When 5 Beam Pros launch the APK in Case 1, you end up with:
- Mac: 1 long-running agent worker process + 5 spawned subprocesses (one per room)
- Each subprocess has its own VAD instance, own chat_ctx, own LLM session state — fully isolated
- All 5 subprocesses run the same `agent.py` code (= "same Sophia"), but they're 5 independent **instances**

| Layer | Same across all 5 | Different per room |
|---|---|---|
| Agent code | All 5 run the same `agent.py` | — |
| Agent worker name | All registered as `sophia-agent` | — |
| Subprocess | — | 5 separate Python subprocesses |
| chat_ctx (memory) | — | 5 isolated histories |
| Sessions | — | 5 fully independent conversations |

Net effect matches your statement: **"same Sophia code, different rooms, different sessions."**

**Case 2 confirmed exactly as stated.** Your understanding: "each process in Beam Pro uses same Sophia agent in same room and same session". Perfectly correct, no precision needed.

When 5 Beam Pros launch the APK in Case 2 (all with `roomName = "test-room-1"`):
- Mac: 1 long-running agent worker + just **1 subprocess** for room `test-room-1`
- That single subprocess has one chat_ctx, one VAD instance, one LLM session
- All 5 users feed audio into it, all 5 hear the same TTS output, all 5 see the same RAG results
- Anyone speaks → everyone hears Sophia answer → everyone's HUD updates with the same transcript + RAG sources

Net effect: **"same Sophia instance, same room, same session, shared across users."**

**The control surface** is one field in one file:
```
sophia-glasses/unity/Assets/Settings/SophiaConfig.asset
    roomName: ""              ← Case 1 (today's behaviour)
    roomName: "test-room-1"   ← Case 2 (all who run this APK share a room)
```

Edit in Unity Inspector → rebuild → reinstall → behaviour changes. No code change, no backend change. Phase 2 will add a runtime picker so one APK can do both depending on what the user selects at launch (see Q3 + Q4 below).

---

#### Q3 (2026-05-22) — All config params come from `SophiaConfig.asset` baked into the APK at build time. List all of them. Which auto-generate unique values when empty? What's the real-world UX path to switch from build-time config to runtime user choice?

**All 7 config fields in `SophiaConfig.cs`** — entire control surface for runtime behaviour. Edit them in `Assets/Settings/SophiaConfig.asset` in the Inspector, rebuild the APK, every user who runs that APK inherits those values.

| Field | Default in our asset today | What happens at runtime |
|---|---|---|
| **liveKitUrl** | `ws://100.69.34.194:7880` (Mac's Tailscale IP) | Used as-is. Same SFU for every user. In production this becomes `wss://livekit.sophia.ai`. |
| **tokenEndpoint** | `http://100.69.34.194:8001/token` (Mac's token_mint) | Used as-is. Same minter for every user. |
| **agentName** | `sophia-agent` | Used as-is. Goes into the JWT's `roomConfig.agents` claim. Must match what `agent.py` registers as. |
| **roomName** | `""` (empty) | **EMPTY → auto-generates `sophia-glasses-<12-hex-uuid>` per launch.** Set → uses that fixed string for all users of this APK. |
| **participantIdentity** | `""` (empty) | **EMPTY → auto-generates `glasses-<8-hex-uuid>` per launch.** Set → uses that fixed string for all users (bad if multiple users — identity collision in the room). |
| **participantName** | `""` (empty) | **EMPTY → defaults to literal `"Sophia Glasses User"` (NOT unique).** Set → uses that display name. Cosmetic only. |
| **microphoneDeviceIndex** | `-1` | -1 → uses device 0 (default mic, on Android always `"Android audio input"`). Set → picks a specific mic from `Microphone.devices`. |

**Which fields auto-generate uniqueness when empty?** Just two:

| Field | Empty behaviour | Why this design |
|---|---|---|
| **roomName** | Unique UUID per launch | Default to Scenario B (isolated rooms). Each user is alone with their own Sophia. |
| **participantIdentity** | Unique UUID per launch | Multiple users in the SAME room never collide. LiveKit requires unique identity per participant in a room. |

The other 5 fields are either fixed for the deployment (URLs, agent name) or fall back to a literal constant (display name "Sophia Glasses User") or device default (mic index 0).

**What this means for the two cases**:

- **Case 1** (APK with empty `roomName`, today's behaviour): 5 Beam Pros launch the same APK simultaneously. All 5 hit the same SFU/token_mint/agent_name (fixed). Each gets a unique `_resolvedRoom = "sophia-glasses-<different-uuid>"`. Each gets a unique `_resolvedIdentity = "glasses-<different-uuid>"`. All 5 display as "Sophia Glasses User" to the SFU (cosmetic, doesn't matter for isolation). Result: 5 separate rooms, 5 separate agent subprocesses, 5 isolated sessions.
- **Case 2** (APK with `roomName = "acme/bay-3"` baked): All 5 hit the same SFU/token_mint/agent_name. All 5 use `_resolvedRoom = "acme/bay-3"` (the baked value, no auto-generation). Each gets a unique `_resolvedIdentity` (so they don't collide as participants). Result: 1 room shared by all 5 users + 1 agent subprocess + 1 shared session.

The identity uniqueness is what keeps Case 2 from breaking — without it, two clients claiming the same identity would conflict at the SFU and one of them would get kicked.

**The real-world UX path** — build the APK once, decide at runtime which case you want:

```
TODAY (Phase 1-2 first cut)
└─ APK is built with empty roomName + empty participantIdentity
└─ Every launch = unique private room (Scenario B)
└─ No way to override at runtime
└─ To do Scenario A: edit SophiaConfig.asset, rebuild a SECOND APK with fixed roomName

REAL-WORLD UX (Phase 2 cleanup / Phase 3)
└─ Build ONE APK with both auto-generated defaults
└─ On launch, app shows a session picker scene BEFORE SophiaConnection.OnEnable fires:

    ┌────────────────────────────────────────────────┐
    │      ┌──────────────────────────────────┐     │
    │      │  Start Private Session           │     │
    │      │  (just you and Sophia)           │     │
    │      └──────────────────────────────────┘     │
    │                                                │
    │      ┌──────────────────────────────────┐     │
    │      │  Join Team Session               │     │
    │      │  [Scan QR]  [Enter Code]         │     │
    │      └──────────────────────────────────┘     │
    └────────────────────────────────────────────────┘

└─ User taps "Start Private Session":
    - SophiaConfig.roomName stays empty
    - SophiaConnection auto-generates UUID room
    - Joins own private room → own agent subprocess (Case 1)

└─ User taps "Join Team Session", enters "acme/bay-3":
    - Picker provides "acme/bay-3" as a runtime override
    - SophiaConnection sees non-empty effective roomName → uses "acme/bay-3" verbatim
    - Joins shared room → existing agent subprocess if anyone's already there,
      OR triggers dispatch if first user (Case 2)
```

Same APK, same code, runtime decision. The user's choice in the picker UI overrides the empty default from the ScriptableObject before `OnEnable` reads it.

**Implementation detail for the picker** (important): `SophiaConfig` is a ScriptableObject = a shared singleton asset. Mutating `roomName` at runtime persists for the rest of the session and can leak across runs (Unity sometimes serializes ScriptableObject changes back to disk in dev builds). Cleaner pattern: store the picker's choice in a **separate runtime variable** (e.g., a static `SophiaSessionContext` class — see Q4 below), and have SophiaConnection consult that variable first before falling back to the asset. Avoids polluting the persisted asset. ~half day of Unity work for the full picker + override + end-session UI.

---

#### Q4 (2026-05-22) — Build the picker UI. User can be in only one session at a time, end it, return to picker, pick again. How to actually close a session in the APK? (Browser had an End button.)

**The full lifecycle** maps cleanly onto Unity's MonoBehaviour lifecycle methods:

```
APP LAUNCH
    ↓
PICKER SCENE shown
    ↓
    ├─ User taps "Start Private Session"
    │       ↓
    │   SessionContext.RoomOverride = null (use auto-generated)
    │   SophiaConnection GameObject activated → OnEnable fires → ConnectFlow
    │   PICKER hidden
    │   IN-SESSION view shown (HUD overlays + "End" button)
    │
    └─ User taps "Join Team Session"
            ↓
        Show input/QR scanner → user provides "acme/bay-3"
        SessionContext.RoomOverride = "acme/bay-3"
        SophiaConnection GameObject activated → OnEnable fires → ConnectFlow
        PICKER hidden
        IN-SESSION view shown (HUD overlays + "End" button)

IN-SESSION (either path)
    ↓
    User taps "End Session" button
        ↓
    SophiaConnection GameObject deactivated → OnDisable fires
    OnDisable does cleanup:
        _micSource.Stop()      ← stop publishing mic
        _room.Disconnect()     ← graceful disconnect from LiveKit
    PICKER shown again
        ↓
    User picks again (Private or Team) → loop restarts
```

Continuous cycle: pick → use → end → pick → use → end. No app restart needed.

**How "end session" actually works at the system level** — three things happen in order when the user taps End:

1. **Unity side**: SophiaConnection's `OnDisable()` runs (already in Phase 1 code):
   ```csharp
   _micSource?.Stop();
   _room?.Disconnect();
   ```
   Mic capture stops. WebRTC connection to the SFU is torn down.

2. **SFU side**: detects the participant left the room. Removes them from the participant list. Broadcasts `ParticipantDisconnected` event to everyone else in the room.

3. **Agent worker side**: receives the event. Behaviour depends on scenario:
   - **Scenario B** (private, only this user was in it): agent subprocess detects "0 human participants left", waits a short timeout (~30s default in LiveKit), exits its session, gets recycled by the worker pool. Memory freed on Mac side.
   - **Scenario A** (shared, others still present): agent stays alive, keeps serving the remaining participants. Just one fewer user in its chat_ctx.

Same lifecycle the browser frontend's "End" button triggers. Disconnect is a first-class LiveKit operation, our `OnDisable()` already does it correctly.

**Three pieces to add — concrete implementation:**

**Piece 1: a runtime session context (replaces mutating SophiaConfig.asset)** — new file. Static class holding the user's current session choice.

```csharp
// Assets/Scripts/SophiaSessionContext.cs (NEW)
public static class SophiaSessionContext
{
    public enum Mode { None, Private, Team }
    public static Mode CurrentMode { get; set; } = Mode.None;
    public static string RoomOverride { get; set; } = null;
    public static void Reset()
    {
        CurrentMode = Mode.None;
        RoomOverride = null;
    }
}
```

Why static: simplest way to share state across scenes/scripts without singletons or DI. State lives for the app's lifetime.

**Piece 2: SophiaConnection.cs reads from SessionContext** — one-line change in `OnEnable`'s room-resolution block:

```csharp
// OLD:
_resolvedRoom = string.IsNullOrWhiteSpace(config.roomName)
    ? $"sophia-glasses-{Guid.NewGuid().ToString("N").Substring(0, 12)}"
    : config.roomName.Trim();

// NEW:
string desiredRoom = SophiaSessionContext.RoomOverride ?? config.roomName;
_resolvedRoom = string.IsNullOrWhiteSpace(desiredRoom)
    ? $"sophia-glasses-{Guid.NewGuid().ToString("N").Substring(0, 12)}"
    : desiredRoom.Trim();
```

If the picker set `RoomOverride = "acme/bay-3"` → uses it. If picker set `RoomOverride = null` (Private mode) → falls back to config (empty) → auto-generates UUID. **SophiaConfig.asset is never mutated.**

**Piece 3: a SessionPicker MonoBehaviour controlling activation:**

```csharp
// Assets/Scripts/SessionPicker.cs (NEW)
public class SessionPicker : MonoBehaviour
{
    [SerializeField] private GameObject sophiaConnectionGO;   // inactive by default
    [SerializeField] private GameObject pickerPanel;          // active by default
    [SerializeField] private GameObject inSessionPanel;       // inactive by default
    [SerializeField] private TMP_InputField roomCodeInput;    // for Team mode

    public void OnStartPrivate()
    {
        SophiaSessionContext.CurrentMode = SophiaSessionContext.Mode.Private;
        SophiaSessionContext.RoomOverride = null;
        StartSession();
    }

    public void OnJoinTeam()
    {
        var code = roomCodeInput.text.Trim();
        if (string.IsNullOrWhiteSpace(code)) return;
        SophiaSessionContext.CurrentMode = SophiaSessionContext.Mode.Team;
        SophiaSessionContext.RoomOverride = code;
        StartSession();
    }

    public void OnEndSession()
    {
        sophiaConnectionGO.SetActive(false);   // → fires OnDisable → cleanup
        inSessionPanel.SetActive(false);
        SophiaSessionContext.Reset();
        pickerPanel.SetActive(true);
    }

    private void StartSession()
    {
        pickerPanel.SetActive(false);
        inSessionPanel.SetActive(true);        // shows the End button + HUD
        sophiaConnectionGO.SetActive(true);    // → fires OnEnable → ConnectFlow
    }
}
```

Wire-up in Unity Inspector: drag the three GameObject references + the input field into the SerializeField slots. Wire the Buttons' OnClick events to call `OnStartPrivate`, `OnJoinTeam`, `OnEndSession`.

**Where the End button physically lives** — on the Beam Pro / glasses, the user has no keyboard/mouse. UI interaction is via the Beam Pro's touch screen. Options:

- **Recommended for Phase 2**: a Screen Space - Overlay 2D button on the Beam Pro screen (not in the AR HUD). Cleaner to tap accurately. The user always has the Beam Pro on their person. Hybrid: 2D button on Beam Pro, plus a "Session active" indicator floating in the glasses HUD so user knows the session is live.
- **Alternative**: floating "End" button rendered inside the world-space HUD (e.g., top-right of the state pill area, small red circle). User looks down at the Beam Pro screen (mirrors what the glasses see) and taps where the End button would be. Works but harder to hit accurately.
- **Future (Phase 3+)**: voice command "Sophia, end session" — needs a wake word + intent parser, more work.

**What about closing the whole app entirely?** Different from ending a session. The picker UI can have a small "Quit App" button at the bottom:

```csharp
public void OnQuit() => Application.Quit();
```

On Android this returns the user to the launcher. Unity process exits. SophiaConnection's `OnDisable` fires on the way out (cleanup happens). Next launch starts fresh from the picker.

**Handling Android pause/swipe-away** — in practice on Android, users rarely "quit" apps — they swipe to home. The OS may keep the app paused in background and eventually kill it for memory. Add `OnApplicationPause` and `OnApplicationQuit` handlers to SophiaConnection so the SFU doesn't see "phantom participants":

```csharp
// Add to SophiaConnection.cs
private void OnApplicationPause(bool isPaused)
{
    if (isPaused) { _micSource?.Stop(); _room?.Disconnect(); }
}
private void OnApplicationQuit()
{
    _micSource?.Stop(); _room?.Disconnect();
}
```

**Summary**

- **The "switch between sessions" cycle works exactly as described** — SophiaConnection's GameObject toggles active/inactive, Unity's lifecycle methods do the work.
- **End session = `SetActive(false)` → OnDisable → mic stop + room disconnect.** Already implemented from Phase 1. Just need a button to trigger it.
- **Three new files / changes for Phase 2 picker**: `SophiaSessionContext.cs` (static state holder), one-line edit in `SophiaConnection.cs` (read from context, not config), `SessionPicker.cs` (the picker MonoBehaviour with three button handlers).
- **End button lives on the Beam Pro screen** as a 2D Screen Space - Overlay button, easy to tap.
- **App pause/quit also disconnect cleanly** — ~5 extra lines for `OnApplicationPause` and `OnApplicationQuit` so the SFU doesn't see ghost participants when user swipes away.

Total Phase 2 picker work: **~half a day**. Backend unchanged.
