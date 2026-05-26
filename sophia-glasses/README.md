# sophia-glasses

XREAL One Pro + Beam Pro + Eye client app for the Sophia voice agent.

## What this is

A Unity-based Android app that runs on the **XREAL Beam Pro** and connects
the **XREAL One Pro glasses** to the Sophia voice agent running on
`../sophia-agent`.

Position in the bigger picture:

```
[XREAL One Pro glasses]                  ← mic, speakers, AR displays, optional Eye camera
       ↕ USB-C
[XREAL Beam Pro (Android)]               ← THIS DIRECTORY's APK runs here
       ↕ WiFi / Tailscale
[Mac running ../sophia-agent stack]      ← livekit-server + agent + RAG hook
       ↕ kubectl port-forward
[AWS EKS multi-agent namespace]          ← whisper / qwen3-vl / kokoro / sophia-spatial-ai
```

The agent backend (`../sophia-agent`) stays UNTOUCHED. The Beam Pro app
is just another LiveKit client, equivalent to the browser at
`../agent-starter-react`. Both clients work in parallel against the same
backend.

## Stack picks

- **Unity 6.3 LTS** (Editor) -- decided 2026-05-21. Future-proof for
  3D AR overlays planned beyond Phase 2.
- **XREAL SDK 3.1.0** (UPM package, Unity XR Plugin Manager) -- the
  successor to NRSDK 2.x. Cleaner integration.
- **livekit-unity** SDK -- Apache 2.0 wrapper around the LiveKit Rust
  client. Same Room/Track/DataChannel APIs as the web SDK.
- **Native Android target** (Beam Pro runs NebulaOS, standard Android
  APK installable via adb).

## Phased build plan

| Phase | Scope | Duration |
|---|---|---|
| 1 | Voice-only loop on glasses (no UI) | ~2-3 days |
| 2 | NRSDK head-locked AR UI overlay (transcript + state + RAG sources) | ~3-5 days |
| 3 | XREAL Eye snapshot-on-demand → `/image-question` vision RAG | ~2-4 days |
| 4 | Polish, settings, error recovery, distribution build | ~1-2 days |

Full plan + rationale: see `sophia-agent/CHAT.md` turns 48-49.

## Directory layout (will fill in as we build)

```
sophia-glasses/
├── README.md           ← this file
├── AGENTS.md           ← conventions for any Claude session working here
├── .gitignore          ← Unity-standard ignores
└── unity/              ← Unity project (Phase 1 onwards)
    ├── Assets/         ← C# scripts, scenes, prefabs
    │   ├── Scripts/    ← our MonoBehaviours
    │   ├── Scenes/     ← MainScene.unity etc
    │   └── Settings/   ← ScriptableObject configs
    ├── ProjectSettings/
    ├── Packages/
    │   └── manifest.json  ← UPM package list (livekit-unity, XREAL SDK refs)
    └── ...              ← Unity-generated folders (Library/, Logs/, Temp/, Build/ — gitignored)
```

## Running

See `RUNBOOK.md` once Phase 1 is done.

## What does NOT live here

- The voice agent backend: `../sophia-agent/`
- The web client (parallel/alternative to glasses): `../agent-starter-react/`
- AWS-hosted model servers: external EKS, accessed via `../sophia-agent/infra/pf-gpu.sh`
- LiveKit SFU: runs natively on the Mac via `brew install livekit`, started from
  `../sophia-agent/infra/livekit.yaml`
