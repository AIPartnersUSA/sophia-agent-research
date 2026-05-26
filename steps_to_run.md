# steps_to_run.md

Two run sequences for the Sophia voice agent:

1. **Local browser application** (5 terminals on Mac, open http://localhost:3000)
2. **XREAL glasses + Beam Pro** (depends on the same Mac backend being up)

Always run the browser path first to confirm the backend is healthy, then move to glasses.

---

## Part 1 — Local browser application

Open 5 separate terminals. The first 4 are inside the `sophia-agent` directory; terminal 5 is inside `agent-starter-react`.

Common cd for terminals 1–4:

```bash
cd '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-agent'
```

### Terminal 1 — LiveKit SFU (room server)

```bash
livekit-server --config infra/livekit.yaml --dev
```

Foreground. SFU log line should show `nodeIP: 127.0.0.1` (or your Tailscale IP `100.69.34.194`). Ctrl-C to stop.

### Terminal 2 — kubectl port-forwards to AWS models

```bash
./infra/pf-gpu.sh
```

Forwards: whisper-inference 8080, qwen3-inference 18080, kokoro-tts 8122, orpheus-tts 8120 (often no ready pod, OK), sophia-spatial-ai 8106, voice-relay 8111, infra-prometheus-grafana 3030 (cross-namespace `monitoring`).

Helpers: `./infra/pf-gpu.sh list` to print discovery table only. `./infra/pf-gpu.sh stop` to tear down.

### Terminal 3 — Token mint (JWT issuer)

```bash
uv run uvicorn src.token_mint:app --host 0.0.0.0 --port 8001 --reload
```

Look for `Uvicorn running on http://0.0.0.0:8001` and `Application startup complete.`

### Terminal 4 — Sophia agent worker

```bash
uv run python src/agent.py dev
```

Look for, in order:
- `prewarm` line (Silero VAD loaded)
- `inference` line (turn-detector subprocess started)
- `registered worker ... id: AW_xxxx, url: ws://localhost:7880, agent_name: sophia-agent`

### Terminal 5 — Frontend (different directory)

```bash
cd '/Users/avinashbolleddula/Documents/sophia Agent Research/agent-starter-react'
npm run dev
```

Look for `Ready in ~Xms` and `Environments: .env.local`.

### Open the app

http://localhost:3000 in a browser → click **Start Call** → speak → hear Sophia answer through your speakers.

### Quick health checks

```bash
curl -sf http://localhost:7880/ && echo OK            # SFU
curl -sf http://localhost:8001/health                 # token mint
curl -sf http://localhost:8122/health                 # Kokoro TTS
curl -sf http://localhost:8080/v1/models              # Whisper STT
curl -sf http://localhost:18080/v1/models             # Qwen3-VL LLM
curl -sf http://localhost:8106/health                 # sophia-spatial-ai RAG
```

### Stopping

Ctrl-C in each terminal (1, 3, 4, 5). For Terminal 2: `./infra/pf-gpu.sh stop`.

---

## Part 2 — XREAL glasses + Beam Pro

Backend from Part 1 must already be running on the Mac (Terminals 1–4 — frontend Terminal 5 is not needed for glasses; the glasses are their own client).

### Step 1 — Set three Editor knobs in Unity (one-time before next rebuild)

Open `sophia-glasses/unity/` in Unity, then:

1. **Player Settings** → Edit menu → Project Settings → Player → Resolution and Presentation:
   - Default Orientation = **Landscape Left**
   - Allowed Orientations = check only **Landscape Left** and **Landscape Right** (un-check Portrait + Portrait Upside Down)
2. **Audio Settings** → Edit menu → Project Settings → Audio:
   - System Sample Rate = **48000**
3. **Game view aspect** → Game view tab top dropdown:
   - Pick **1920x1080 Landscape** (Editor preview only — matches the world-space canvas)

### Step 2 — Rebuild the APK

In Unity: File menu → **Build Profiles** → **Build**. Overwrite the existing path at:

```
/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk
```

### Step 3 — Plug Beam Pro into Mac via USB-C

Swipe down on the Beam Pro notification shade → set USB mode to **File Transfer** (not Charge Only). Then verify:

```bash
adb devices -l
```

Expected line with `model:X4000`.

### Step 4 — RESET permission state (so we can validate the new Path A fix)

```bash
adb uninstall com.UnityTechnologies.com.unity.template.urpblank
```

(Skip this on subsequent rebuilds. Only needed once to reset Android's persisted `granted=true` so the new poll-retry code path actually fires.)

### Step 5 — Install the fresh APK

```bash
adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
```

Expected output: `Performing Streamed Install` then `Success`.

### Step 6 — Start log tail (one terminal, leave running)

```bash
adb logcat -c
adb logcat | grep -E 'Sophia|LiveKit|TMP|FATAL'
```

### Step 7 — Launch the app (another terminal)

```bash
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
```

Tap **Allow** on the permission dialog when it appears on the Beam Pro screen.

Expected log sequence (Path A working):

```
[Sophia] Starting. room=...
[Sophia] Got token (len=457) ...
[Sophia] Connected to room ...
[Sophia] No microphone devices yet. Waiting up to 20s for Android to grant RECORD_AUDIO ...
   ← dialog appears, you tap Allow
[Sophia] Microphone became available after 4.2s.
[Sophia] Using microphone [0] 'Android audio input'
[Sophia] Microphone publishing. You can speak now.
[Sophia] Participant connected: agent-AJ_...
```

### Step 8 — Test voice loop with Beam Pro speaker (no glasses yet)

Hold Beam Pro near your face. Say "Hello, who are you?". Sophia should answer through the phone speaker within 2–3s.

Validation checks for the four 2026-05-22 HUD parity fixes:
- **Q49**: Session picker shows landscape two-column card layout, not portrait clipped.
- **Q47/Path A**: "Waiting up to 20s..." log appeared on first launch (proves poll-retry fired).
- **Q50**: HUD transcript text scrolls in sync with TTS playback, not after.
- **Q51**: State pill flips listening / thinking / speaking in real time; RAG sources populate for manual questions.

### Step 9 — Set up wireless adb BEFORE unplugging USB

Glasses occupy the only USB-C port, so wireless adb must be live before you switch.

While Beam Pro is **still plugged in via USB:**

```bash
adb tcpip 5555
adb connect 100.69.32.120:5555
adb devices
```

Expected: TWO entries (USB device id `RHLM56L118630F` AND `100.69.32.120:5555`).

**Now unplug USB safely.** adb will keep working over Tailscale.

### Step 10 — Plug glasses into Beam Pro + wear them

Plug the XREAL One Pro cable into the Beam Pro USB-C port. Display lights up mirroring Beam Pro. Put glasses on.

Audio auto-routes to the glasses' temple speakers and mic (Android USB Audio Class auto-routing).

### Step 11 — Restart the app cleanly for a fresh session

```bash
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
```

Speak. Sophia answers through the glasses' temple speakers. The world-space HUD (state pill, transcript, RAG sources) floats ~2 meters in front of you.

### Iterative dev loop (after every code change)

```bash
# 1. Rebuild in Unity (Cmd+B or File > Build Profiles > Build) — overwrites the APK

# 2. Reinstall + relaunch (works on USB or wireless)
adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity

# 3. Watch logs in another terminal
adb logcat | grep -E 'Sophia|LiveKit|TMP|FATAL'
```

### Troubleshooting matrix

| Symptom | Most likely cause | Quick check |
|---|---|---|
| `adb devices` shows nothing | USB mode wrong, or USB debugging off | Swipe down on Beam Pro, change USB to File Transfer; verify Developer Options is on |
| `adb install` says `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | Signature mismatch | `adb uninstall com.UnityTechnologies.com.unity.template.urpblank` then reinstall |
| `[Sophia] Starting` then `Room.Connect failed` | Backend not running, or wrong Tailscale URL in SophiaConfig | `curl http://localhost:7880` from Mac; verify SophiaConfig.asset URL is `ws://100.69.34.194:7880` |
| `[Sophia] No microphone devices found` (and no "Waiting up to 20s" log) | Old APK without Path A fix is still installed | Confirm you rebuilt after 2026-05-22; uninstall + reinstall |
| `[Sophia] Microphone publishing` but Sophia never speaks | Agent worker not running, or `agent_name` mismatch | Check Terminal 4 logs for `entrypoint` line on each new room join |
| App installs but nothing in logs | Wrong activity name, or app crashed at boot | `adb logcat *:E \| grep FATAL`; verify `am start` uses `UnityPlayerGameActivity` (not `UnityPlayerActivity`) |
| Wireless adb stopped working | Beam Pro slept/rebooted, lost adbd | Plug USB back in → `adb tcpip 5555` → `adb connect 100.69.32.120:5555` |
| `am start` says `Activity class ... does not exist` | Using old `UnityPlayerActivity` name | Use `UnityPlayerGameActivity` (Unity 6 default) |

### Useful log filter patterns

```bash
adb logcat | grep -E 'Sophia|LiveKit|TMP|FATAL'        # day-to-day
adb logcat -d | grep -E 'Sophia|LiveKit' | tail -100   # snapshot (not streaming)
adb logcat *:E                                          # errors only
adb logcat -c                                           # clear buffer (do before relaunch)
adb shell pidof com.UnityTechnologies.com.unity.template.urpblank   # → pid
adb logcat --pid=<pid>                                  # only this app's logs
```

### Stopping everything

- App on Beam Pro: `adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank`
- All Mac terminals: Ctrl-C in each (and `./infra/pf-gpu.sh stop` for Terminal 2)
