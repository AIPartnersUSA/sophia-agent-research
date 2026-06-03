# Multi-room demo recording plan

Goal: record two short videos demonstrating Sophia's multi-room architecture using ONE Beam Pro + XREAL One Pro + your Mac browser as the second client.

- Demo 1 — Scenario B (Private / isolated rooms): two independent Sophia conversations happening simultaneously. Proof of multi-tenant isolation.
- Demo 2 — Scenario A (Team / shared room): one Sophia heard by both clients in the same room. Proof of collaborative session.

Both demos use the same backend (the 4 terminals from `steps_to_run.md` Part 1). No agent code change.

---

## One-time prerequisite — install scrcpy to mirror Beam Pro on the Mac

scrcpy mirrors the phone's screen to a Mac window in real time and uses USB or wireless adb. It's the cleanest way to capture Beam Pro screen + browser side-by-side in a single screen recording.

```bash
brew install scrcpy
```

After install, verify with:

```bash
scrcpy --help | head -3
```

To launch mirroring (Beam Pro plugged in or wireless adb connected):

```bash
scrcpy --window-title="Beam Pro" --max-size=1024
```

A new desktop window appears showing the Beam Pro's screen live. Drag it next to the browser. You can pull it onto half the screen for side-by-side recording.

---

## Window layout for recording

Arrange:

- Left half of Mac screen: scrcpy window titled "Beam Pro" (the glasses view is what the Beam Pro shows)
- Right half of Mac screen: Chrome with `http://localhost:3000`
- Optional bottom strip: Terminal showing `adb logcat | grep -E 'Sophia|LiveKit'` so viewers see the underlying events flowing

Then use Cmd+Shift+5, pick "Record Selected Portion", drag a box covering both windows, hit Record. Use the floating control bar to stop when done.

If you'd rather record full screen at native resolution, Cmd+Shift+5 then "Record Entire Screen". You can crop in post.

---

## Demo 1 — Scenario B (Private rooms, isolated tenants)

No code changes required. Glasses' Private session generates a UUID; browser opens its own auto-generated room. Both Sophias are independent.

### Setup (~2 min)

1. Bring up the backend (4 terminals per `steps_to_run.md`).
2. Plug in earphones to your Mac (kills the echo loop for the browser-side Sophia).
3. Plug Beam Pro into Mac via USB-C, verify `adb devices` shows it.
4. Set up wireless adb so glasses can plug in later (still on USB):
   ```bash
   adb tcpip 5555
   adb connect 100.69.32.120:5555
   adb devices                       # should show both USB and wireless entries
   ```
5. Unplug USB and plug glasses into Beam Pro. Put glasses on.
6. Launch scrcpy in another terminal so Beam Pro screen mirrors to Mac:
   ```bash
   scrcpy --window-title="Beam Pro" --max-size=1024
   ```
7. Open Chrome at `http://localhost:3000`. DON'T click Start Call yet.

### Recording sequence

1. Start screen recording (Cmd+Shift+5, "Record Selected Portion", capture both windows).
2. On scrcpy / glasses: tap "Start Private Session" in the picker.
3. On browser: click "Start Call".
4. Wait ~3 seconds for both connections to establish.
5. Speak through glasses: "Hi Sophia, what is the tire pressure for the GV70?"
6. Sophia answers through glasses. Browser also has its own session running but does NOT hear this answer because they're in different rooms.
7. Click into browser, click its mic (or type if it supports text). Speak: "Hi Sophia, what manuals do you have?" Sophia answers through Mac headphones.
8. Glasses do NOT hear this answer — that's the proof of isolation.
9. Optionally ask different follow-ups on each side simultaneously to show they don't bleed into each other.
10. Stop recording.

What to call out in narration:

- "These are two completely independent sessions. Same agent worker, but two different rooms."
- "Each user has their own conversation history, their own RAG context, their own Sophia voice replying to them."
- "In production this is how a corporate client's 50 field technicians each get a private session."

Expected duration: ~90 seconds.

---

## Demo 2 — Scenario A (Team room, shared session)

Browser needs a 5-line patch to honor a `?room=` URL parameter so it can join the same room as the glasses. The glasses' Team Session already supports this via the room code input.

### One-time code patch to agent-starter-react

The frontend currently auto-generates a room name on every page load. We need it to use the `?room=X` query parameter when present.

The room logic lives in the agent-session-block component or the API token route. To find the right file:

```bash
cd /Users/avinashbolleddula/Documents/sophia\ Agent\ Research/agent-starter-react
grep -rln "roomName\|generateRoomName\|api/token" components app 2>/dev/null | grep -v node_modules | head
```

When the page sends its token request to `/api/token`, intercept and inject the URL's `?room=` if present. Easiest fix is at the call site: wherever the page picks a room name, check `new URLSearchParams(window.location.search).get('room')` first and use that if present.

If you'd rather I write the exact patch, tell me which file the grep above points to (likely `app/api/token/route.ts` or a component file) and I'll do the edit. About 5 lines.

### Setup (~2 min)

Same as Demo 1 setup. Backend up, scrcpy mirroring Beam Pro, browser open.

### Recording sequence

1. Pick a room code, e.g. `demo-team`. Both clients will use it.
2. Start screen recording.
3. On glasses: tap "Join Team Session", type `demo-team` in the input, tap the button.
4. On browser: navigate to `http://localhost:3000?room=demo-team`. Click Start Call.
5. Wait ~3 seconds for both to connect to the SAME room.
6. Speak through glasses: "Hi Sophia, what manuals do you have?"
7. Sophia answers. Both the glasses display AND the browser transcript panel show her words. Same audio plays in both places.
8. Click into browser. Speak through the Mac mic: "And what about the GV70 tire pressure specifically?"
9. Sophia continues the SAME conversation. Glasses' HUD updates with the new answer. Browser transcript also updates.
10. Stop recording.

What to call out in narration:

- "Both clients are in the same LiveKit room. One Sophia worker subprocess on the Mac handles both."
- "Sophia maintains a single conversation history across both users — notice the second question is a follow-up to the first, and she handles it as one thread."
- "In production this is how a field technician on glasses and a remote expert on browser collaborate on the same equipment problem."

Expected duration: ~2 minutes.

---

## Tips for cleaner recordings

- Headphones on the Mac side (not speakers) — the browser's Sophia plays through speakers otherwise creates the Q41 echo loop where Sophia answers her own voice.
- Beam Pro brightness: tap the volume rocker and use the system slider to raise glasses brightness if scrcpy mirror looks dim.
- Mute Mac system notifications during recording: Apple menu, Do Not Disturb.
- Don't move the glasses on your head during recording — head-locked HUD looks much smoother when stationary.
- Sample rate fix from earlier session: ensure macOS Audio MIDI Setup output device is set to 48000 Hz, or the LiveKit Editor mic capture will error on first frame.
- If scrcpy lags or stutters, lower the bitrate: `scrcpy --max-size=800 --bit-rate=2M`.

## Optional flourish — show both demos in one cut

You can record both back-to-back as one continuous take if you want a single-file demo:

1. Open demo 1 (Private). Run for ~90s.
2. End both sessions (tap End on glasses, click End Call in browser).
3. Without stopping the screen recording, immediately start demo 2 (Team room).
4. Run for ~2 min.

Add a slide title in post ("Multi-tenant isolation" / "Shared team session") so the viewer knows which demo is which.
