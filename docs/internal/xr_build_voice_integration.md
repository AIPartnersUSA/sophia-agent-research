# xr_build_voice_integration.md — adding Sophia to an existing XR build

A guide for an XR engineer (or you, briefing one) who already has their own XR app build and wants to integrate the Sophia voice agent into it. Covers what carries over from this repo, what they need to add or adapt, and the two main integration paths.

Audience: someone with an existing Unity (or Unreal / native) XR project who wants Sophia's voice capabilities without re-doing all our work. They do NOT need to clone or rebuild this repo — they need to understand what to take from it.

For deep background read `livekit_architectur_ec2.md` (architecture mental model) BEFORE this file. For operational details read `mvp_deployment_shared_ec2.md`.

---

## TL;DR

Yes, you can. The voice agent splits into two independent layers:

- **Backend** = the EC2 deployment (SFU + token-mint + agent-worker + inference services). Runs anywhere your XR app can reach. Zero changes needed on the backend side to support a new client.
- **Client** = the part that lives in your app. Today there are two reference clients (browser, XREAL Beam Pro Android via Unity). Adding a third is mostly about wiring LiveKit Unity SDK + ~3 Unity scripts into your existing project.

Effort estimate: half a day to 2 days depending on integration approach + how clean your existing scene model is.

---

## What stays the same regardless of your build

All of these continue to work without modification:

- `livekit-server` (the SFU) on EC2 at `3.227.63.49:7880`.
- `token-mint` (FastAPI) at `3.227.63.49:8001/token` with X-API-Key auth.
- `agent-worker` (Python LiveKit Agents worker) registered as `sophia-agent`.
- The four EKS inference services accessed via kubectl port-forwards.

Your build joins the same LiveKit room as any other client. The SFU dispatches the same agent. The same STT → RAG → LLM → TTS pipeline runs. You get the same audio back. Sophia doesn't know (or care) which client type subscribed.

---

## Questions to answer before starting

Surface these first — they determine which integration path fits and what to adapt.

### Q1. What platform is the build for?

- **XREAL One Pro / Light** tethered to an Android device (like our Beam Pro setup) — Drop-in path works directly, audio routing is the same.
- **Meta Quest 2 / 3 / Pro** — Drop-in mostly works (Quest is Android underneath). Skip XREAL-specific code. Quest has hardware AEC so no echo on the device itself. Use Quest's input system for the picker UI.
- **Apple Vision Pro** — Different audio model + RealityKit instead of Unity world-space. LiveKit Unity SDK builds for visionOS but you'd need to validate. Vision Pro is strict about HTTPS — you'll need TLS on the backend first (not implemented yet, see `production_deployment.md`).
- **HoloLens 2** — Unity supports it via OpenXR. LiveKit Unity SDK should work. Audio I/O is on-device. Watch for MRTK conflicts with our SessionPicker UI building approach.
- **Other (Pico, Magic Leap, Varjo, etc.)** — Likely works if Unity-based; validate LiveKit Unity SDK runs on the platform first.

### Q2. Is the build Unity, Unreal, or native?

- **Unity** — Drop-in our scripts directly. Both reference clients use LiveKit Unity SDK; you'll use the same.
- **Unreal** — LiveKit ships an Unreal plugin (`livekit-unreal`). The agent dispatch + WebRTC flow is identical, but our C# scripts don't apply. You'll need to port the connection logic to C++/Blueprints. Estimated effort: 3-4 days.
- **Native Android / iOS** — LiveKit has native SDKs for both. Most relevant if you're building a non-Unity XR experience (e.g. an Android-native AR app). Port the connection logic to Kotlin/Swift. Estimated effort: 2-3 days.

### Q3. What Unity version (if Unity)?

- **Unity 6** — Same as ours. Our scripts compile and run directly. Read `livekit_doubts.md` Q55 (Custom Main Manifest for GameActivity) and Q60 (TMP_Text deprecation) before building Android.
- **Unity 2022 LTS** — Most of our Unity-6-specific workarounds don't apply. Should be slightly simpler.
- **Unity 2021 LTS or older** — LiveKit Unity SDK may have compatibility issues. Validate first.

### Q4. Does the build already have a room/session model?

- **Yes, they manage their own multiplayer / networking** — You probably don't want to drop in our SessionPicker. Use Custom integration path (below) — only bring SophiaConnection.cs as a "Sophia client" component they can activate when they want voice.
- **No, single-player or no networking yet** — Drop-in path is fine. Our SessionPicker becomes the session entry point.

### Q5. Does the build already have a microphone code path?

- **Yes** — Their mic code conflicts with ours. They need to hand the mic AudioClip to SophiaConnection instead of letting our `MicrophoneSource` open the device. Code change in `SophiaConnection.cs` ConnectFlow Step 3.
- **No** — Our code opens the mic directly. Fine.

### Q6. Does the build have its own world-space UI canvas?

- **Yes** — Skip our `SophiaOverlayUI.cs`. Let their UI subscribe to the same static event `SophiaConnection.OnTextStreamMessage(topic, identity, payload)` and render in their style. Much cleaner.
- **No** — Drop in SophiaOverlayUI. Tune the ~12 `[SerializeField]` knobs at the top of the script for your FOV.

### Q7. Are mic + speakers on the device or on tethered hardware?

- **On-device (Quest, Vision Pro, HoloLens)** — Standard Unity Microphone.Start() + AudioSource. No special routing.
- **Tethered (XREAL + Android phone, MagicLeap relay, etc.)** — Like our Beam Pro setup. Mic is on the phone, glasses speakers may or may not be routed via USB Audio Class. Validate audio routing manually.

---

## What they need to add to their build

For a Unity-based XR app, the minimum set:

### 1. LiveKit Unity SDK

Two options for installing.

**Option A — vendor it (matches our pattern, repo-portable).** Copy `sophia-glasses/client-sdk-unity/` into their repo (Git LFS for the FFI binaries, ~30 files). Add to `Packages/manifest.json`:

```json
"io.livekit.livekit-sdk": "file:../../client-sdk-unity"
```

The `file:../../` path math is critical — Unity resolves relative to `Packages/manifest.json` location, NOT project root (see `livekit_doubts.md` Q59).

**Option B — install via Unity Package Manager from a Git URL.** LiveKit hosts the SDK at `https://github.com/livekit/client-sdk-unity`. UPM can install from that URL directly. Simpler for one-off integration but you don't pin a specific version unless you specify a commit SHA.

### 2. XREAL SDK (only if their build targets XREAL glasses)

Skip if not XREAL. If yes, vendor `sophia-glasses/xreal-sdk/` (243 MB via LFS) and add to manifest:

```json
"com.xreal.xr": "file:../../xreal-sdk"
```

### 3. Unity scripts to copy

From `sophia-glasses/unity/Assets/Scripts/`:

- `SophiaConfig.cs` — ScriptableObject schema. Required.
- `SophiaSessionContext.cs` — static state shared between picker + connection. Required.
- `SophiaConnection.cs` — the voice loop (token fetch, room connect, mic publish, audio playback). Required.
- `SessionPicker.cs` — launch UI with Private/Team mode picker. **Optional** — skip if they have their own session entry point.
- `SophiaOverlayUI.cs` — world-space AR HUD with subtitle + state dot + RAG chips. **Optional** — skip if they have their own UI.

From `sophia-glasses/unity/Assets/Settings/`:

- `SophiaConfig.asset` — runtime config instance. Required. Edit values before building (see "Configure SophiaConfig" below).

Also copy the `.meta` files for each (Unity tracks GUIDs via .meta — don't forget them or scene references break).

### 4. (Android-only) Custom Main Manifest

If their build targets Android with Unity 6 GameActivity, copy our pattern from `sophia-glasses/unity/Assets/Plugins/Android/AndroidManifest.xml`. See `livekit_doubts.md` Q55 for the full rationale on why this is needed.

### 5. (Unity 6 only) AudioManager.asset sample rate

Set Project Settings > Audio > System Sample Rate = 48000. On macOS Editor also set Audio MIDI Setup format to 48 kHz (`livekit_doubts.md` Q52).

---

## Configure SophiaConfig.asset for their backend

Their SophiaConfig.asset must point at a working backend. Three fields:

```yaml
liveKitUrl: ws://3.227.63.49:7880        # or your own SFU
tokenEndpoint: http://3.227.63.49:8001/token   # or your own token-mint
tokenApiKey: 9a11fdf5ce05e3cecad28f933d778971   # must match SOPHIA_TOKEN_API_KEY on the backend; empty if no auth
agentName: sophia-agent                  # matches the agent_name registered by agent.py
roomName:                                # empty = unique per launch; set for shared rooms
```

If they want to point at OUR shared EC2 demo, use the values above as-is. If they want their own backend, they'll need to deploy the EC2 stack themselves (see `mvp_deployment_shared_ec2.md`) and use their own URLs + their own SOPHIA_TOKEN_API_KEY.

---

## Two integration paths

### Path A — Drop-in (fast, validates quickly)

For when their build is greenfield or doesn't have its own session/UI conventions yet.

Steps:
1. Copy all 5 scripts + `SophiaConfig.asset` + the LiveKit Unity SDK into their project.
2. Create an empty GameObject in their main scene, name it `SophiaSession`.
3. Under SophiaSession, create three child GameObjects: `SessionPicker` (with SessionPicker.cs attached), `SophiaConnection` (with SophiaConnection.cs attached, DEACTIVATED by default), `SophiaOverlayUI` (with SophiaOverlayUI.cs attached).
4. In the SophiaConnection.cs Inspector, drag SophiaConfig.asset into the `config` field. Drag an empty GameObject named `SpeakerHost` (under SophiaSession) into the `speakerHost` field.
5. Build for their target platform. Test.

Estimated effort: 3-4 hours for someone familiar with Unity.

What they get out of the box: launch picker → click Private → mic captures → Sophia answers → AR HUD shows state + transcript + RAG sources. Looks like our demo but in their app's context.

### Path B — Custom integration (cleaner long-term)

For when their build has its own scene management, room/session model, or UI conventions they want to keep.

Steps:
1. Copy ONLY 3 scripts: `SophiaConfig.cs`, `SophiaSessionContext.cs`, `SophiaConnection.cs`. Skip SessionPicker.cs and SophiaOverlayUI.cs.
2. Create the SophiaConfig.asset.
3. Add a `SophiaConnection` GameObject to whichever scene needs voice, deactivated by default.
4. In their existing code, replace whatever invokes "start Sophia session" with:
   ```csharp
   SophiaSessionContext.CurrentMode = SophiaSessionContext.Mode.Private;
   sophiaConnectionGameObject.SetActive(true);
   ```
   And "end Sophia session" with:
   ```csharp
   sophiaConnectionGameObject.SetActive(false);
   ```
5. In their existing UI code, subscribe to the static event:
   ```csharp
   SophiaConnection.OnTextStreamMessage += (topic, identity, payload) => {
       // route to their own UI rendering
       switch (topic) {
           case "sophia.agent_events": /* parse + update state pill */ break;
           case "sophia.rag_result":   /* parse + show RAG sources */ break;
           case "lk.transcription":    /* update subtitle */ break;
       }
   };
   ```
6. Optionally write a JSON parser for `sophia.agent_events` and `sophia.rag_result` payloads (or copy ours from SophiaOverlayUI.cs lines that parse `ExtractJsonString` + `ExtractHits`).

Estimated effort: 1-2 days. Cleaner because their existing patterns aren't disrupted and the integration is a clear sub-system rather than a UI takeover.

---

## What might NOT work without adaptation

### XREAL-specific code paths

If they're NOT on XREAL, skip:
- The XREAL SDK package
- `SophiaOverlayUI.cs` knobs tuned for XREAL One Pro FOV (their FOV will differ — tune the `subtitleBottomMargin`, `dotEdgeMargin`, `chipFontSize` etc.)
- The Custom Main Manifest's `<provider tools:node="remove"/>` for AutoLogcatProvider (only matters for XREAL Auto Logcat AAR)

### Echo on tethered audio setups (like our Beam Pro)

Our setup has a known echo loop when the Beam Pro speakers face the Beam Pro mic (Q41 + Q43 in `livekit_doubts.md`). Glasses geometry kills it. If their hardware is different:
- **On-device mic + speakers (Quest, Vision Pro)** — no echo by design. Hardware AEC handles it.
- **Wired headset** — no echo.
- **Other tethered setups** — validate empirically. If echo, follow the glasses-temple-speaker-geometry workaround OR add software AEC (DeepFilterNet, Krisp, etc. — `STS_models.md` covers options).

### Android mic permission race

`SophiaConnection.cs` has Path A poll-retry code waiting up to 20 seconds for Android to grant RECORD_AUDIO on first launch. This handles the first-launch dialog without crashing. If their target is iOS / visionOS / standalone Quest, the permission flow differs:
- **iOS / visionOS** — Info.plist `NSMicrophoneUsageDescription` + system-managed permission prompt.
- **Quest** — Android-based, same as our pattern.
- **HoloLens** — UWP capability declaration + system prompt.

The point is: don't expect the Path A poll-retry to work cross-platform. Test the mic permission grant on their target before integrating further.

### Plain HTTP origins blocked

The MVP backend is plain HTTP/WS (no TLS). Some XR platforms refuse mic capture from non-secure origins:
- **Vision Pro** is particularly strict.
- **Browser-based XR (WebXR)** also strict.
- **Quest standalone** generally tolerates plain HTTP for the LiveKit WS protocol.

If their platform refuses, you'll need to add TLS to the backend first (production migration — see `HANDOFF.md`).

### Multi-user audio playback

Our `SophiaConnection.OnTrackSubscribed` filters to `participant.Identity.StartsWith("agent-")` and creates a child GameObject per agent track. This handles the production-correct multi-user contract (Q58). If their build has multiplayer and you want users to hear EACH OTHER as well as Sophia, you'd remove the agent-only filter and play other participants' tracks too (in separate child GameObjects to avoid the AudioSource collision documented in Q58).

### Bundle ID + signing

Our APK uses bundle ID `com.UnityTechnologies.com.unity.template.urpblank` (Unity 6 default — not renamed because it's on the Phase 2 hardening list). Their build has its own bundle ID. If they install our APK alongside theirs, two separate apps. If they integrate our scripts INTO theirs, one app under their bundle ID. The signing certificates also differ. None of this affects voice agent behavior, just install management.

---

## Recommended workflow

1. **Send them this doc + `livekit_architectur_ec2.md`** for context.
2. **Have them answer Q1-Q7** above before any code work.
3. **Pick a path** (Drop-in for greenfield/simple builds, Custom for sophisticated existing apps).
4. **Get a "hello world" working first** — just the voice loop, no HUD, no fancy UI. Have them speak, Sophia answers. Validates token + room + audio.
5. **Then layer UI.** Either drop in SophiaOverlayUI or write their own around the OnTextStreamMessage event.
6. **Iterate on knobs.** FOV-specific HUD sizes, mic gain, AEC if needed, etc.

Common timeline:
- Day 1: SDK install + scripts copied + first connection attempt (likely fails on permission or token endpoint).
- Day 2: Voice loop working without HUD. Probably hit one of the "common failures" from `livekit_architectur_ec2.md`.
- Day 3+: UI integration, platform-specific polish.

---

## Cross-references

- `livekit_architectur_ec2.md` — architectural mental model. Read FIRST.
- `mvp_deployment_shared_ec2.md` — operational runbook for the backend (if they want to run their own backend).
- `sophia-glasses/READING_GUIDE.md` — Unity codebase tour. Step 4 (SophiaConfig fields), Step 7 (SophiaConnection voice loop) are most relevant.
- `livekit_doubts.md` — Q&A. Q41/Q43 (echo), Q49-Q51 (HUD), Q55 (Custom Main Manifest), Q58 (multi-user audio), Q59 (manifest path math), Q60 (Unity 6 TMP), Q61 (auth paths), Q62 (network_mode).
- `unity_approach.md` Appendix B — operational runbook for the glasses path. Useful template for their own runbook.
- `HANDOFF.md` — if they end up needing to deploy their own production backend.

---

## When to update this file

- New XR platform tested + integrated (add platform-specific findings to "What might NOT work").
- New integration path discovered (e.g. WebXR + livekit-client.js instead of Unity SDK).
- Backend protocol changes (e.g. auth model upgraded) — update the SophiaConfig.asset section.
- Common pitfall surfaces that another XR engineer hit — add to the relevant Q1-Q7 answer.
