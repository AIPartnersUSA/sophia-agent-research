# AGENTS.md -- sophia-glasses

Conventions for any Claude session working in this directory.

## What this project is

XREAL One Pro + Beam Pro + Eye client for the Sophia voice agent. See
`README.md` for the full picture.

The agent backend (`../sophia-agent/`) is the source of truth for
behaviour. This project is a CLIENT only. Do NOT change backend code,
text-stream topic names, or LiveKit room semantics from here. If the
backend needs a change, do it in `../sophia-agent/` and update its
CHAT.md / project memory accordingly.

## Stack

- Unity 6.3 LTS (Editor)
- XREAL SDK 3.1.0 (UPM tarball, Unity XR Plugin Manager)
- livekit-unity (Apache 2.0)
- Target: Android (Beam Pro)

## Conventions

### Modularity

Build small, swappable MonoBehaviours. Each component should:
- Subscribe to ONE data source (a text-stream topic, a LiveKit event,
  or a NRSDK input).
- Render to ONE UI panel or perform ONE side effect.
- Not know about the other components.

Example: `RagSourcePanel.cs` subscribes to `sophia.rag_result` and
updates a TMP_Text. It does not know about `AgentStatePill.cs` or
`TranscriptPanel.cs`. They all live as separate scripts on separate
GameObjects.

### Configuration

All runtime configuration (server URLs, room names, user identity)
goes through a single `SophiaConfig.asset` ScriptableObject. Edit in
the Inspector, no recompile needed.

### Naming

- C# scripts: PascalCase (`SophiaConnection.cs`, `RagSourcePanel.cs`).
- ScriptableObject assets: PascalCase + `.asset` (`SophiaConfig.asset`).
- Scenes: PascalCase + `.unity` (`MainScene.unity`).
- Prefabs: PascalCase + `.prefab`.

### Text-stream topics (must match `../sophia-agent/src/agent.py`)

Topic names to subscribe to from this client:

- `sophia.rag_result` -- per-turn RAG retrieve result + chunks
- `sophia.agent_events` -- AgentSession state changes + per-stage metrics
- `lk.transcription` -- LiveKit-native transcription stream

Do NOT change these names client-side without updating the backend
publisher (in `../sophia-agent/src/agent.py`'s
`_attach_event_publishers` and `_publish_rag_result`).

### Audio routing

Don't override Android's default audio routing unless absolutely
necessary. When XREAL One Pro is plugged into Beam Pro, the OS
should auto-select USB mic input and USB speaker output. If we need
forced routing, do it via `AudioManager.setCommunicationDevice(...)`
inside a separate `AudioRouting.cs` script -- don't bury it inside
the connection logic.

### LiveKit room semantics

- Default to UNIQUE room name per app launch (Scenario B = isolated
  per-user Sophia sessions). Generate a UUID-suffixed room name in
  `SophiaConnection.OnEnable()`.
- Add a `SophiaConfig.roomName` override field (string). If set, use
  that exact name (Scenario A = shared room for multi-user demos).
  If empty, generate.

### Build conventions

- Debug builds: `Development Build` checkbox ON, scripting backend
  IL2CPP, target architecture ARM64.
- Release builds: `Development Build` OFF, same backend + arch.
- Keystore: TBD in Phase 4 (signing for distribution).
- Output: `sophia-glasses/unity/Builds/<config>/sophia-glasses.apk`.

### Install on Beam Pro

Two modes, both fine:

1. USB: `adb install -r path/to/sophia-glasses.apk`
2. Wireless adb (when Beam Pro USB-C is occupied by glasses):
   ```
   adb tcpip 5555  # while still on USB
   # unplug USB, plug in glasses
   adb connect <beam-pro-tailscale-ip>:5555
   adb install -r path/to/sophia-glasses.apk
   ```

### Networking notes

- LiveKit server runs natively on the Mac at port 7880. Mac's
  Tailscale IP (currently `100.69.34.194`) is reachable from Beam
  Pro as long as Tailscale is on both ends.
- Token-mint runs natively on the Mac at port 8001.
- AWS reachability NOT needed from Beam Pro -- the agent on the Mac
  does the AWS calls. The Beam Pro app only needs to reach the SFU
  and the token-mint.

### What NOT to do

- Don't add LiveKit Cloud / Inference / ai-coustics references. We
  are full OSS, mirroring `../sophia-agent`'s decisions.
- Don't change the backend's text-stream topic names from this
  client (they'd silently break the parallel web client).
- Don't bundle the XREAL SDK tarball into git. Keep it referenced
  via Package Manager pointing at an external path.
- Don't commit `Library/`, `Temp/`, `Logs/`, `Builds/`, or
  `UserSettings/` (covered by `.gitignore`).
- Don't add iOS / macOS / Windows / Web / Linux build targets. We
  are Android-only for now.

## How to resume in a fresh Claude session

1. Read `README.md` + this file.
2. Read the latest entries in `../sophia-agent/CHAT.md`. The XREAL
   build is being tracked in CHAT.md turns 48 onwards. Look for the
   most recent turn referencing `sophia-glasses` or Phase 1/2/3/4.
3. Check current phase in the bigger memory file at
   `~/.claude/projects/-Users-avinashbolleddula-Documents-sophia-Agent-Research/memory/project_sophia_voice_agent.md`
   -- specifically the "Most-likely next action" section.
