# HUD Direction A — subtitle-minimal layout

Designed for industrial technicians wearing XREAL One Pro tethered to Beam Pro. Goal: keep the user's central field of view clear so they can look at equipment, while still surfacing Sophia's state, her words, and where she's pulling answers from.

## Layout sketch (1920x1080 virtual glasses canvas)

```
+----------------------------------------------------------------------------+
|                                                                       (o)  |  <- tiny colored state dot (top-right, ~24 px)
|                                                                            |
|                                                                            |
|                                                                            |
|                                                                            |
|                                                                            |
|                CLEAR CENTER OF VISION (the real world)                     |
|                                                                            |
|                                                                            |
|                                                                            |
|                                                                            |
|                                                                            |
|                                                                            |
|             +------------------------------------------------+             |
|             |  x250_ug_en.pdf  p.35                          |             |  <- thin RAG source chip (lives ~60px above subtitle, fades out when no RAG)
|             +------------------------------------------------+             |
|                                                                            |
|         +------------------------------------------------------+           |
|         |  Sophia is answering, word by word as she speaks...  |           |  <- bottom-center subtitle (large, auto-fades 2s after Sophia stops)
|         +------------------------------------------------------+           |
|                                                                            |
|                                                                       [X]  |  <- tiny End chip on Beam Pro screen-space overlay (~80x80 px, bottom-right)
+----------------------------------------------------------------------------+
```

## Element-by-element

### State dot (top-right, world-space canvas)
- A solid filled circle, ~24 px diameter, in a corner ~40 px in from the top-right edge.
- Color tells everything; no text accompanies it.
  - Grey: connecting / idle.
  - Green: listening (Sophia is hearing you).
  - Amber: thinking (LLM running, no audio yet).
  - Blue: speaking (Sophia is talking).
- Subtle pulse animation while thinking + speaking; static while listening.

### Subtitle (bottom-center, world-space canvas)
- Single bottom-anchored panel, ~1200 px wide, max height ~180 px (2 lines of 56 px text + padding).
- Translucent near-black background (alpha 0.55) with a 1 px hairline white border (alpha 0.3).
- Shows ONLY the most recent line of conversation.
  - When user speaks: shows their STT as it streams in, then fades after Sophia starts.
  - When Sophia speaks: shows her TTS text word-by-word as it streams (via ReadIncremental). Fades 2s after the agent_state goes back to listening.
- Single-line truncate with ellipsis if too long. Don't grow upward.
- Font: 56 px (much larger than current 36 px), high contrast white.
- Optional: thin "Sophia:" / "You:" prefix in a muted color before the line.

### RAG chip (above subtitle, world-space canvas)
- A thin pill, ~auto-width to content, ~50 px tall.
- Sits ~60 px above the top edge of the subtitle.
- Translucent dark fill, hairline border, same style as subtitle but smaller.
- Content: single line — the filename + page number of the top-ranked retrieved source.
  - Example: `x250_ug_en.pdf  p.35`
  - Example: `GV70_Owners_Manual.pdf  p.8`
- Appears 200ms after a rag_result lands with mode=retrieve_injected.
- Fades out 500ms after Sophia finishes speaking.
- Not shown at all for retrieve_skipped (general chat).

### End chip (bottom-right, Beam Pro screen-space overlay)
- 80x80 px tappable button on the phone touchscreen.
- "X" icon or "End" text, tinted soft red.
- Almost invisible in glasses FOV (bottom-right corner is at the edge of XREAL's comfortable viewing area).
- Tap target lives on the phone, where the user can glance down briefly and tap.
- No "Session: (private)" label — that was the noisy part.

### What's removed (from current UI)
- Big LISTENING / THINKING / SPEAKING text pill (replaced with corner dot).
- User+Sophia transcript stacked box (replaced with single subtitle line, ephemeral).
- Big RAG sources side panel listing multiple files with scores (replaced with single chip showing top source).
- "Session: (private, just you)" label and big red End Session button (compressed to corner chip).

## Behavior timeline (one turn)

```
Time   State  | Visible elements
-------+------|-----------------------------------
t=0   listen  | (o) green dot.  No subtitle, no chip.
              |
t=1s  listen  | (o) green.  Subtitle fades in: "You: What is the tire pressure for the GV70?"
              |
t=2s  think   | (o) amber pulsing.  Subtitle still showing user's question.
              |
t=2.4 speak   | (o) blue pulsing.  Subtitle swaps to "Sophia: The recommended..." (word-by-word).
              | RAG chip fades in: "GV70_Owners_Manual.pdf  p.8"
              |
t=5s  speak   | (o) blue pulsing.  Subtitle: "Sophia: ...is 33 psi front, 33 psi rear."
              | Chip still visible.
              |
t=5.3 listen  | (o) green.  Subtitle still on Sophia's final line.  Chip starts fade-out.
              |
t=7.3 listen  | (o) green.  Subtitle has faded out.  Chip gone.  Clean field of view again.
```

## Implementation notes

- All animations 200ms ease-out via a tiny coroutine in SophiaOverlayUI (no DOTween dependency needed).
- ReadIncremental for transcripts means subtitle updates token-by-token in sync with TTS (already wired in SophiaConnection.LogTextStream after Q50).
- State events come from `sophia.agent_events` with `kind=agent_state` (already wired).
- RAG chip uses the top-ranked hit's source field from `sophia.rag_result` payload. Today's payload includes `hits[].source` and `hits[].page` — we'll grab the first hit when mode=retrieve_injected.
- Three knobs stay as [SerializeField] for live tuning: subtitleFadeOutSeconds (default 2.0), ragChipFadeDelay (default 0.5), dotPulseRate (default 1.2 Hz).

## What stays the same
- World-space Canvas parented to Camera.main at 2m focal distance.
- Existing JSON parsers in SophiaOverlayUI (whitespace-tolerant, Q51).
- Subscription to SophiaConnection.OnTextStreamMessage.
- SessionPicker's launch picker (Private / Team card) is untouched — only the in-session bar gets shrunk to the corner chip.

## What if RAG is more useful than I'm giving credit for
If during testing you want to see multiple sources at once (e.g. when Sophia cites two different manuals in the same answer), we can replace the single-line chip with a vertical strip of up to 3 chips. Easy to extend; the foundation supports it.
