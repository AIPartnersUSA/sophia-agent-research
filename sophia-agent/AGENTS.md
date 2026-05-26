# AGENTS.md -- sophia-agent

This is the OSS-replication twin of `../my-agent`. The two projects are kept
in parallel:

- `my-agent` runs on LiveKit Cloud + LiveKit Inference (Deepgram, OpenAI, Cartesia,
  ai-coustics). It is the **benchmark** for Sophia's target UX -- the bar we want to
  match.
- `sophia-agent` (this directory) runs on a fully self-hosted OSS stack:
  livekit-server in Docker locally, FastAPI token-mint, AWS-hosted STT/LLM/TTS.
  Goal: prove the OSS path can match my-agent's behaviour before we ship to
  production.

## Conventions inherited from my-agent

Same as my-agent's AGENTS.md unless noted below:

- Use `uv` for all dependency / run / test commands. Never raw pip.
- `src/agent.py` is the entrypoint (used by the Dockerfile).
- Format with `uv run ruff format` and `uv run ruff check` after edits.
- For LiveKit API specifics, prefer `lk docs search` / `lk docs get-page`
  (CLI v2.15.0+) over training-data recall.
- TDD when modifying agent behaviour. Write tests in `tests/`.

## What is different from my-agent

- **No LiveKit Cloud, no LiveKit Inference.** All `from livekit.agents import inference`
  references are removed. STT/LLM/TTS get real plugin instances pointing at AWS.
- **No `livekit-plugins-ai-coustics`.** It requires `Auth.livekit_cloud()` and will not
  authenticate against our self-hosted SFU. If noise becomes a measured problem we
  add DeepFilterNet 3; we do not add it speculatively.
- **LIVEKIT_URL = `ws://localhost:7880`** (not `wss://*.livekit.cloud`). The agent
  registers as a worker against the local Docker SFU.
- **Token issuance is our own** (`src/token_mint.py`, FastAPI). The browser/Android
  client POSTs `/token` to get a JWT signed with our API_SECRET.
- **`livekit.yaml`** (in `infra/`) configures the local SFU. Keys must match `.env.local`.

## Two integration paths for AWS STT/LLM/TTS

Pick per endpoint based on what AWS speaks:

- **Route A -- OpenAI-compatible HTTP**: the model server speaks Whisper API
  (`/v1/audio/transcriptions`), OpenAI TTS (`/v1/audio/speech`), or
  chat-completions. Use `livekit.plugins.openai.STT/LLM/TTS(base_url=..., api_key=...)`.
  Zero custom plugin code.
- **Route B -- custom protocol**: AWS endpoint has its own JSON or WebSocket
  shape. Subclass `livekit.agents.{stt,llm,tts}.<Base>` into
  `src/plugins/<name>.py`. Pattern: see `livekit_doubts.md` Q36 (VAD example;
  same template applies to STT/LLM/TTS).

The corresponding env vars are in `.env.example`. Fill the URL + API key for each
stage you swap in. Wire the plugin into `AgentSession(stt=..., llm=..., tts=...)`
in `src/agent.py`. Run `uv run python src/agent.py dev` to test.

## File map

- `src/agent.py` -- the agent worker entrypoint
- `src/token_mint.py` -- FastAPI service that issues room JWTs to clients
- `src/plugins/` (created when needed) -- custom STT/LLM/TTS plugins (Route B)
- `infra/livekit.yaml` -- SFU config
- `infra/docker-compose.yml` -- runs livekit-server locally
- `.env.example` -- env var template (copy to `.env.local`)
- `tests/` -- pytest evals (mirror my-agent's structure once plugins land)

## Run order, day one

1. `cp .env.example .env.local` and confirm values.
2. `docker compose -f infra/docker-compose.yml up -d` -- starts the SFU on :7880.
3. `uv sync` -- installs Python deps.
4. `uv run python src/agent.py download-files` -- pulls Silero VAD + turn-detector ONNX.
5. `uv run uvicorn src.token_mint:app --port 8001 --reload` (in one terminal) -- token mint.
6. `uv run python src/agent.py dev` (in another terminal) -- the agent worker.
7. From the agent-starter-react clone (`../agent-starter-react`), run the frontend
   pointed at `NEXT_PUBLIC_LIVEKIT_URL=ws://localhost:7880` and the token-mint at
   `http://localhost:8001/token`. Open the browser, join a room, talk.

Until STT/LLM/TTS are wired the agent will connect but not respond. That is the
expected "SFU smoke test" state.
