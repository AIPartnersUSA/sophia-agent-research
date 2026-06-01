# sophia-agent local stack runbook

Step-by-step to bring up the full local OSS LiveKit stack on the laptop.
Read this in your IDE -- the commands are in fenced code blocks for easy
copy-paste. Status at any point: see the "Where you are now" section at
the bottom and update it as you progress.

All commands assume your current directory is:

```
/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-agent
```

## Prereqs (one-time)

- `livekit-server` installed natively (`brew install livekit`). Same binary
  the EC2 production deploy will run. We do NOT use Docker locally because
  on macOS Docker Desktop the SFU's network namespace cannot resolve the
  Safari browser's mDNS `.local` host candidates, which breaks WebRTC.
- `uv` installed.
- `.env.local` exists (copied from `.env.example`).
- `.venv/` exists and `uv.lock` is checked in (i.e. `uv sync` was run).
- `lk` CLI installed (only needed for `lk docs` lookups, not for running).

## Step 1 -- start the SFU (native binary)

```
livekit-server --config infra/livekit.yaml --dev
```

This stays in the foreground and streams SFU logs. Press Ctrl C to stop.

Verify (in another terminal):

```
curl -sf http://localhost:7880/ && echo OK
```

You should see a small HTML landing page plus the word OK on the next line.
SFU startup log should show `nodeIP: 127.0.0.1` -- if it shows a different
IP, browser WebRTC will fail.

For the EC2 production deployment, the SFU runs in Docker (Linux Docker does
not have the macOS mDNS/namespace bug). See `mvp_deployment_shared_ec2.md`
and the workspace-root `docker-compose.yml` on EC2 — not in this directory.

## Step 2 -- pre-download Silero VAD and turn-detector ONNX (once)

```
uv run python src/agent.py download-files
```

Pulls about 100 MB into `~/.cache/huggingface/hub/`. One-time. Skip if
you have already run it for this venv.

## Step 3 -- start the token-mint (in a new terminal)

```
uv run uvicorn src.token_mint:app --host 0.0.0.0 --port 8001 --reload
```

Leave this running. You should see uvicorn boot lines ending with:

```
Uvicorn running on http://0.0.0.0:8001
```

Verify in any other terminal:

```
curl -sf http://localhost:8001/health
```

Should return JSON like `{"status":"ok","livekit_url":"ws://localhost:7880"}`.

## Step 4 -- start the agent worker (in another new terminal)

```
uv run python src/agent.py dev
```

Leave this running. You should see, in order:

- A `prewarm` line (Silero VAD loaded into the worker subprocess).
- An `inference` line (turn-detector subprocess started).
- A `registered worker` line addressed to `ws://localhost:7880`.

That last line is the proof the worker successfully reached the SFU.

## Step 5 -- start the frontend (in another new terminal)

From the project root, change into the React clone:

```
cd ../agent-starter-react
```

If not yet installed:

```
npm install
```

Then run:

```
npm run dev
```

The frontend boots on http://localhost:3000.

Before joining a room, set the frontend's env to point at your local
stack. In `agent-starter-react/.env.local` (create if missing), use
exactly these values -- they match `infra/livekit.yaml`'s `keys:` block
and `sophia-agent/.env.local`:

```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret-please-change
TOKEN_ENDPOINT=http://localhost:8001/token
AGENT_NAME=sophia-agent
```

Why each one:

- `LIVEKIT_URL` -- where the browser opens its WebSocket to the SFU.
- `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` -- Next.js needs these on its
  server side for its built-in token route (a fallback if `TOKEN_ENDPOINT`
  is not used). Values must match `devkey` / `devsecret-please-change`.
- `TOKEN_ENDPOINT` -- tells agent-starter-react to fetch JWTs from our
  own `sophia-agent/src/token_mint.py` instead of using its built-in
  route. This is the path we want, because it exercises the same flow
  we will use in production.
- `AGENT_NAME` -- set to `sophia-agent` so the SFU does explicit dispatch
  to our registered worker (id from step 4). Leaving it blank uses
  automatic dispatch, which can be flaky when more than one worker is
  registered.

## Step 6 -- join a room and verify the SFU smoke test

Open http://localhost:3000 in a browser. Join the default room.

You should see:

- Your own browser tab as a participant.
- The `sophia-agent` worker join the room as another participant
  (a new prewarm log line appears in Terminal 3 / the worker terminal).
- The agent stays silent on your speech. **This is expected.** Until
  STT, LLM, and TTS plugins are wired (next phase), the agent has no
  speech pipeline.

If all three things happen, the SFU layer of the local OSS stack is
verified working. Move on to wiring AWS STT and TTS.

## Where you are now

Update this as you progress (Phase 2 Thread A).

- [x] Docker Desktop host networking enabled and restarted.
- [x] `.env.local` and `.venv` created.
- [x] Step 1 -- SFU container Up at `localhost:7880`.
- [x] Step 2 -- download-files run.
- [x] Step 3 -- token-mint running on `:8001`. (uvicorn reloader + server processes; `Application startup complete`.)
- [x] Step 4 -- agent worker registered against the SFU. (Latest worker id `AW_3AocQYjpdL4Z`, url `ws://localhost:7880`, agent_name `sophia-agent` -- confirmed 2026-05-19. Worker id matches the "worker registered" line in the SFU log -- handshake verified.)
- [x] Step 5 -- frontend running on `:3000`. (Next.js 15.5.18 + Turbopack; `.env.local` loaded; `Ready in 628ms`.)
- [x] Step 6 -- browser joined a room; agent dispatched + mic stream attached. **(PASSED 2026-05-19 08:04-08:05.)** Worker received two job requests (`voice_assistant_room_8722` then `voice_assistant_room_7608`), spawned subprocesses (pids 16725, 16756), attached to room audio, `start reading stream ... SOURCE_MICROPHONE` confirmed mic audio reaching the agent. Agent stayed silent because STT/LLM/TTS not wired -- expected smoke-test pass condition.

**OSS local stack smoke test = PASS.** Next phase: Thread B (AWS STT + TTS plugins). See latest entry in `sophia-agent/CHAT.md`.

Note: step 3 and step 4 are independent and can run in either order. The worker uses raw API key+secret to register (no JWT). The token-mint exists to serve JWTs to the *browser client*, so step 3 must be running before step 6 can succeed, but it does not gate step 4 or step 5.

## Stopping everything

- Frontend (Terminal 4): Ctrl C.
- Agent worker (Terminal 3): Ctrl C.
- Token-mint (Terminal 2): Ctrl C.
- SFU (Terminal 1): Ctrl C in the `livekit-server` terminal.

## Troubleshooting one-liners

- SFU running but `curl http://localhost:7880` hangs: confirm the
  `livekit-server` process is actually up (`pgrep -fl livekit-server`)
  and that nothing else is bound to port 7880 (`lsof -iTCP:7880`).
- Agent worker logs "failed to register" or hangs: confirm
  `LIVEKIT_URL=ws://localhost:7880` in `.env.local` and that the SFU is up.
- Token-mint returns 500 on `/token`: confirm `LIVEKIT_API_KEY` and
  `LIVEKIT_API_SECRET` in `.env.local` match the `keys:` block in
  `infra/livekit.yaml` (default pair is `devkey` / `devsecret-please-change`).
- Frontend joins but agent never appears: the worker is not registered.
  Check the worker terminal for the `registered worker` line.
- `InsecureKeyLengthWarning: The HMAC key is 23 bytes long` on agent
  worker start: harmless in dev. Our `LIVEKIT_API_SECRET` is the 23-char
  `devsecret-please-change` so the PyJWT library warns it is below the
  RFC 7518 recommended 32-byte minimum for SHA256. Will go away in
  production once we rotate to a 32+ byte random secret from AWS
  Secrets Manager (already in the local-to-prod diff table, Q3).
