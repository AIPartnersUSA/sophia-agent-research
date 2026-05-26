# LiveKit Deployment Playbook -- Local OSS to Production

This document tracks what we are running on the laptop in 2026-05 and how the
same layout deploys to AWS unchanged. Single source of truth so a future
session (or a future teammate) can stand up either environment in an hour.

Repo context: this lives at the root of `sophia Agent Research/`. The agent
project lives in `sophia-agent/`. The Cloud + Inference benchmark twin is in
`my-agent/`.

---

## 1. Mental model

A LiveKit voice agent always has the same 4 logical components. What changes
between local and production is **where each one runs**, not what each one
does.

| Component                | Role                                                            | Local                                | Production                           |
|--------------------------|-----------------------------------------------------------------|--------------------------------------|--------------------------------------|
| 1. SFU                   | Routes WebRTC audio between participants                        | `livekit-server` in Docker on laptop | `livekit-server` in Docker on AWS EC2 (behind ALB w/ TLS) |
| 2. Token-mint            | Signs short-lived JWTs so clients can join SFU rooms            | FastAPI on `localhost:8001`          | FastAPI on AWS ECS / EC2 behind HTTPS |
| 3. Agent worker          | Runs the Sophia agent (`src/agent.py`); calls AWS STT/LLM/TTS   | `uv run python src/agent.py dev`     | `uv run python src/agent.py start` on EC2 (Docker) |
| 4. Client                | Captures mic, plays speaker, renders UI                         | agent-starter-react in a browser     | Native Android app on phone tethered to XREAL glasses |

Optional pieces (NOT required for local, often required for production):

- `coturn` for NAT traversal when client and SFU are not on the same network
- `redis` for multi-node SFU coordination
- `livekit-egress` for recording sessions to S3
- `livekit-ingress` for RTMP/WHIP/SIP ingestion
- DeepFilterNet 3 or Silero noise suppression as a substitute for ai-coustics
- OpenTelemetry + Grafana for production observability

Two things stay identical local vs prod and matter most:

- The orchestration framework (`livekit-agents`) is byte-for-byte the same on
  the laptop and on AWS. That is why VAD, turn detection, barge-in, AEC warmup,
  preemptive generation, false-interrupt recovery -- the whole "environment"
  from livekit_doubts.md Q37-Q38 -- work the same in both environments.
- The AWS STT, LLM, TTS endpoints are the same URLs in both environments. The
  agent worker calls them over HTTPS regardless of where the worker itself
  runs.

What changes is just transport and process placement.

---

## 2. Local stack (today's target)

### Architecture

```
                              laptop
  +-----------------------------+   +-----------------------------+
  | browser tab                 |   | livekit-server (Docker)     |
  | agent-starter-react         |<->| ws://localhost:7880         |
  | http://localhost:3000       |   | UDP 50000-50100 / TCP 7881  |
  +--------------+--------------+   +--------------+--------------+
                 |                                 ^
                 | (1) POST /token                 |
                 v                                 | (3) JWT in WS upgrade
  +-----------------------------+                  |
  | token-mint (FastAPI)        |                  |
  | http://localhost:8001       |                  |
  | uses LIVEKIT_API_SECRET     |                  |
  +-----------------------------+                  |
                                                   |
                                                   | (4) worker WS to SFU
                                                   |
  +-----------------------------+ <-----------------+
  | sophia-agent worker         |
  | uv run python src/agent.py  |  ---HTTPS--->  AWS STT  / AWS RAG-LLM / AWS TTS
  | Silero VAD in RAM           |
  | turn-detector inference     |
  | subprocess (auto-spawned)   |
  +-----------------------------+
```

Four processes, all on the laptop. Worker subprocess spawns its own inference
runner subprocess for turn detection (see `livekit_doubts.md` Q23).

### One-time install

Prereqs: Docker Desktop running, Python 3.11+, `uv`, `lk` CLI (>=2.15.0).

```bash
# Project root
cd "/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-agent"

# Python deps
cp .env.example .env.local        # then edit if you changed the dev key
uv sync
uv run python src/agent.py download-files

# Frontend deps (only once)
cd ../agent-starter-react
npm install   # or pnpm / bun
```

### Run order

Three terminals.

```bash
# Terminal 1: SFU
cd sophia-agent
docker compose -f infra/docker-compose.yml up
# Verify: curl -sf http://localhost:7880/ && echo OK

# Terminal 2: token-mint
cd sophia-agent
uv run uvicorn src.token_mint:app --host 0.0.0.0 --port 8001 --reload

# Terminal 3: agent worker
cd sophia-agent
uv run python src/agent.py dev

# Terminal 4 (or background): frontend
cd agent-starter-react
# Point the frontend at the local SFU and token endpoint via its .env.local
# (NEXT_PUBLIC_LIVEKIT_URL=ws://localhost:7880, plus a TOKEN_ENDPOINT it knows
#  to POST to). Specifics: see agent-starter-react's own README.
npm run dev
```

Open `http://localhost:3000` (or whatever port the frontend uses). Join the
default room. You should see the agent appear as a participant. Until STT/LLM/TTS
are wired the agent will be silent on speech -- this is the expected smoke-test
state.

### Verification checklist

1. `docker ps` shows `sophia-livekit-server` Up and Healthy.
2. `curl -sf http://localhost:7880/` returns the LiveKit landing HTML.
3. `curl -sf http://localhost:8001/health` returns `{"status":"ok"}`.
4. The agent log line `registered worker` appears, addressed to `ws://localhost:7880`.
5. The agent log line `inference` -- the turn-detector inference subprocess --
   shows up exactly once per worker.
6. Joining a room from the browser triggers a worker subprocess fork on the
   agent side (you will see a new prewarm log line).

### Files involved (local)

- `sophia-agent/infra/livekit.yaml` -- SFU config; port 7880, devkey/devsecret.
- `sophia-agent/infra/docker-compose.yml` -- runs livekit-server.
- `sophia-agent/.env.local` -- agent + token-mint env (LIVEKIT_URL, KEY, SECRET).
- `sophia-agent/src/token_mint.py` -- FastAPI JWT issuer.
- `sophia-agent/src/agent.py` -- the worker.

---

## 3. From local to production -- diff, not rewrite

The agent code does not change. The SFU image does not change. The token-mint
code barely changes. What changes is operational: real TLS, real DNS, real
secrets, real NAT traversal, real scaling.

### SFU placement

- **Local**: Docker on the laptop, `network_mode: host`, no TLS, devkey/devsecret.
- **AWS**: Same `livekit/livekit-server:latest` Docker image on an EC2 instance
  (or ECS task). Sits behind an Application Load Balancer terminating TLS on
  port 443; the ALB forwards WSS to the server's port 7880. UDP ports
  50000-60000 open in the security group (no LB -- UDP goes directly to the
  EC2 instance public IP). TCP fallback (7881) also exposed via NLB or directly.
  `livekit.yaml` changes: rotate keys (use a 32+ byte random secret stored in
  AWS Secrets Manager and injected at boot), set `use_external_ip: true`, point
  at a real `redis` if you go multi-node.

### Token-mint placement

- **Local**: `uvicorn` on `:8001`, CORS open.
- **AWS**: Same FastAPI image deployed to ECS Fargate or EC2 behind an ALB on
  HTTPS. CORS restricted to the production frontend origin. `LIVEKIT_API_SECRET`
  injected from AWS Secrets Manager. Rate-limited (token issuance is the
  spam-prone endpoint). Optional: tie identity issuance to your own auth
  system so anonymous clients can not mint tokens.

### Agent worker placement

- **Local**: `uv run python src/agent.py dev` directly on the laptop.
- **AWS**: Same Dockerfile, deployed to ECS Fargate (CPU-only, no GPU needed --
  inference is remote) or to a small EC2 fleet. Reads LIVEKIT_URL from
  Parameter Store (set to `wss://livekit.your-domain.com`). Worker WS connection
  to SFU is outbound, no inbound security-group rule needed for the worker.
  Scale horizontally by adding more workers -- each registers independently;
  LiveKit dispatches jobs across them.

### Client placement

- **Local**: browser running `agent-starter-react` against `ws://localhost:7880`.
- **AWS**: Native Android app using `livekit-android` SDK + NRSDK for XREAL.
  Token URL is the production token-mint HTTPS endpoint. LIVEKIT_URL is
  `wss://livekit.your-domain.com`. The Android client is also responsible for
  handling Bluetooth audio routing if the XREAL glasses are the mic/speaker.

### NAT traversal

- **Local**: not needed (all on `localhost`).
- **AWS**: `coturn` deployed on a separate EC2 instance (cheap; `t3.micro`) with
  ports 3478 (STUN/TURN UDP), 443 (TURN/TLS), and the relay range open. The
  SFU's `livekit.yaml` lists this TURN server. Without TURN, clients on
  corporate / cellular NATs will sometimes fail to connect.

### Noise cancellation

- **Local**: none. ai-coustics is intentionally NOT installed because it
  requires LiveKit Cloud auth and would fail.
- **AWS**: optional. DeepFilterNet 3 (Apache-licensed) is the recommended
  substitute (~90 percent of Krisp / ai-coustics quality per
  `project_sophia_voice_agent.md`). Add it inside the agent worker as a
  `noise_cancellation=` argument to `AudioInputOptions` once it is measurably
  needed in real recordings.

### Secrets

- **Local**: `.env.local`, gitignored, plain text.
- **AWS**: AWS Secrets Manager for `LIVEKIT_API_SECRET`, `SOPHIA_STT_API_KEY`,
  `SOPHIA_TTS_API_KEY`, `SOPHIA_LLM_API_KEY`. ECS task / EC2 IAM role grants
  read access. NEVER bake into the Docker image.

### Observability

- **Local**: agent's own log lines (`logger = logging.getLogger("sophia-agent")`).
- **AWS**: livekit-server exposes Prometheus metrics on `:6789/metrics`
  (uncomment in `livekit.yaml`). Pipe to Grafana / AWS Managed Prometheus.
  Agent worker logs go to CloudWatch. Add per-stage timing event listeners
  (`@session.on("metrics_collected")`) so you can graph TTFB per turn.

---

## 4. Concrete AWS package list (production)

What we install -- precise, no fluff:

LiveKit packages:
- `livekit/livekit-server:latest` -- Docker image of the SFU
- `livekit-agents[silero,turn-detector]` -- Python, on the worker
- `livekit-api` -- Python, on token-mint
- `livekit-android` -- Gradle artifact, in the Android app
- (later, if recording) `livekit/egress` -- separate Docker service
- (later, if telephony) `livekit/sip` -- separate Docker service

Non-LiveKit infra:
- coturn (Docker or apt)
- redis (if multi-node SFU)
- nginx or ALB for TLS termination
- AWS Secrets Manager
- AWS Parameter Store (for non-secret config like LIVEKIT_URL)
- CloudWatch + Prometheus + Grafana

Not installed (defer until measured need):
- DeepFilterNet 3
- LiveKit Cloud (we are explicitly avoiding it for the production stack)
- LiveKit Inference (same -- we hold our own model endpoints)
- ai-coustics (Cloud-locked)

---

## 5. What is the same between local and production

- The 4-component architecture and its data flow.
- The `livekit-server` Docker image and its config schema.
- The agent code in `sophia-agent/src/agent.py`.
- The token-mint code in `sophia-agent/src/token_mint.py`.
- The AWS STT / LLM / TTS endpoints the worker calls.
- The Silero VAD + turn-detector models loaded by the worker.
- The entire `livekit-agents` orchestration framework (Q24, Q37, Q38 insight:
  the framework -- not Cloud -- is what gives us smooth turn-taking, barge-in,
  preemption, etc.).

What changes is operational: TLS, secrets, DNS, scaling, NAT.

---

## 6. Open items / future revisions

- [ ] Fill in AWS STT endpoint shape and decide Route A vs Route B.
- [ ] Same for AWS TTS.
- [ ] Same for AWS RAG/LLM (`/query` endpoint -- see `livekit_doubts.md` Q12, Q14).
- [ ] Decide on coturn vs serverless NAT traversal for production.
- [ ] Decide on single-node vs multi-node SFU (redis required for multi).
- [ ] Add DeepFilterNet 3 only after a measured noise problem on real glasses.
- [ ] Wire OpenTelemetry / Prometheus when production rollout approaches.

---

## 7. References

- `sophia-agent/AGENTS.md` -- conventions for working in the new agent.
- `my-agent/AGENTS.md` -- conventions inherited from the Cloud benchmark.
- `livekit_doubts.md` Q29, Q30, Q31 -- earlier deployment-planning Q&A.
- `livekit_doubts.md` Q24, Q37, Q38 -- why we are staying on LiveKit through
  both phases (framework value, not Cloud value).
- `livekit-server-src/config-sample.yaml` -- annotated full SFU config.
- `livekit-cli-src/` -- source of the `lk` CLI.
- `agent-starter-react/` -- the local frontend we use for the browser client.

---

## 8. Doubts & Answers (sophia-agent setup, infra, deployment)

Routing convention: questions specifically about `sophia-agent`, its infra
files, its venv, its run/deploy story (local or production) go here.
General LiveKit framework / plugin / source-debugging questions still go in
`livekit_doubts.md`. Model-specific questions still go in
`STT_models.md` / `TTS_models.md` / `STS_models.md`.

### Q1 (2026-05-18): What do we need from the LiveKit ecosystem for a fully OSS local stack (no LiveKit Cloud, no LiveKit Inference)?

Six packages plus a couple of non-LiveKit pieces. Grouped:

**From LiveKit, must have:**
- `livekit-server` -- the Go SFU, run as a Docker container locally.
  Replaces LiveKit Cloud's SFU.
- `livekit-agents` -- Python framework for the worker. Already a dep in
  `my-agent`; mirrored in `sophia-agent`.
- `livekit-api` -- Python server SDK. Used in `src/token_mint.py` to mint JWTs.
- `livekit-plugins-silero` -- VAD (OSS, local-CPU ONNX). Already a dep.
- `livekit-plugins-turn-detector` -- end-of-turn model (OSS, local-CPU ONNX). Already a dep.
- `lk` CLI -- developer tool. Already installed; used for `lk docs search` and `lk docs get-page`.

**Not from LiveKit but required:**
- A client to talk to the agent. Two options: (a) the public Agents Playground
  via ngrok tunnel, or (b) `agent-starter-react` run locally and pointed at
  `ws://localhost:7880`. Option (b) is the natural stepping stone toward the
  Android client.
- Docker, `uv`, Python 3.11+.

**Defer for local (needed only in production):**
- `livekit-android` SDK -- for the real XREAL+phone client.
- `coturn` -- only for real NAT traversal.
- `livekit-egress` (recording), `livekit-ingress` (RTMP/WHIP), `livekit-sip` (telephony).
- `helm` charts -- only for Kubernetes.
- `ai-coustics` plugin -- intentionally excluded; Cloud-locked. DeepFilterNet 3
  is the OSS substitute if noise becomes a measured problem.

### Q2 (2026-05-18): Do we need to create a venv for `sophia-agent`, and how?

Yes, but `uv` does it automatically. Running `uv sync` inside `sophia-agent/`
creates `sophia-agent/.venv/` and installs everything from `pyproject.toml`.
You do not have to source/activate it -- every `uv run python …` and
`uv run uvicorn …` command transparently uses the local venv. That is the
recommended pattern.

If you prefer to activate (some IDE terminals or raw `python` use cases),
the command is `source .venv/bin/activate`, and `deactivate` exits.

To exit the previous `my-agent` venv before working in `sophia-agent`, type
`deactivate` and press enter. The `(agent-starter-python)` prefix disappears
and you are back to your normal shell.

### Q3 (2026-05-18): What are the two files inside `sophia-agent/infra/` (`livekit.yaml` and `docker-compose.yml`) and how do they interact?

Together they stand up the LiveKit SFU on the laptop. `docker-compose.yml`
tells Docker *how to run* the SFU container; `livekit.yaml` tells the SFU
*how to behave* once it is running. The Compose file mounts the YAML into the
container so the binary can read it at boot.

**`infra/livekit.yaml`** -- the SFU's own config, mounted at `/etc/livekit.yaml`.
Key fields:

| Field | Value (local dev) | What it does |
|---|---|---|
| `port` | `7880` | Main TCP port. Clients use it for signaling (room join, participant list, "publish my mic"). Worker agents register here over WS. Single entry point. |
| `rtc.tcp_port` | `7881` | WebRTC TCP fallback when UDP is blocked (corp firewalls, some VPNs). |
| `rtc.port_range_start` / `rtc.port_range_end` | `50000` – `50100` | UDP port range for actual media (audio packets). Each stream takes a port from here. 100 ports plenty locally; production opens thousands. |
| `rtc.use_external_ip` | `false` | Skip STUN-based public IP discovery. Localhost has no public IP. |
| `keys` | `devkey: devsecret-please-change` | API key/secret pair the SFU accepts. MUST match `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` in `.env.local` -- agent worker uses these to register, token-mint uses them to sign room JWTs. Three places, one pair. Rotate before any non-local deployment. |
| `logging.level` / `logging.json` | `info` / `false` | Human-readable INFO logs. Flip `json: true` in production. |

**`infra/docker-compose.yml`** -- the recipe that runs the SFU. One service
called `livekit-server`. Key directives:

| Directive | Value | What it does |
|---|---|---|
| `image` | `livekit/livekit-server:latest` | Official Go SFU binary from Docker Hub. Same image we use in production. |
| `container_name` | `sophia-livekit-server` | Friendly name in `docker ps`. |
| `restart` | `unless-stopped` | Auto-restart on crash. `docker compose down` still stops it cleanly. |
| `network_mode` | `host` | **Critical for WebRTC dev on macOS/Linux.** Container shares the host's network stack directly instead of being NAT'd. SFU opens 7880, 7881, and the UDP range *on the host* -- clients reach them at `localhost`. Without this, you would forward each UDP port individually. In production behind an ALB you go back to bridged networking with explicit port mapping. |
| `command` | `--config /etc/livekit.yaml --dev` | First arg points at the mounted YAML. `--dev` loosens production checks and makes logs more verbose. |
| `volumes` | `./livekit.yaml:/etc/livekit.yaml:ro` | Mount local YAML into container, read-only. Edit + `docker compose restart` = new config picked up. |

**Startup flow:**
1. `docker compose -f infra/docker-compose.yml up` reads the Compose file.
2. Docker pulls `livekit/livekit-server:latest` if not cached.
3. Container starts with host networking and YAML mounted.
4. Binary reads `/etc/livekit.yaml`, opens 7880/7881 TCP and 50000-50100 UDP on the host.
5. Waits for WS signaling on 7880. Idle until a client or worker connects.

Verification: `curl -sf http://localhost:7880/` returns the LiveKit landing HTML; `docker ps` shows `sophia-livekit-server` Up.

**Local-to-production diffs for these two files** (also captured in section 3):

| Field | Local | Production (AWS) |
|---|---|---|
| `rtc.use_external_ip` | `false` | `true` (EC2 needs STUN to discover its public IP) |
| `keys` | `devkey: devsecret...` | random 32+ byte secret from AWS Secrets Manager, injected at boot |
| `rtc.port_range_end` | `50100` | `60000` (more concurrent participants) |
| `network_mode` | `host` | bridged with explicit UDP port-range mapping; TLS termination at ALB on 443 forwarding WSS to 7880 |
| `command` | includes `--dev` | omit `--dev` |
| `logging.json` | `false` | `true` (CloudWatch / structured logs) |
| `redis` block | not set | set, if running multi-node SFU |
| `turn` block | not set | set, when `coturn` is deployed on a separate EC2 |

Mental model: Compose file is the "outer" recipe (where does the SFU live).
YAML is the "inner" recipe (how does the SFU behave). Both intentionally
small for local. Production grows both modestly but never re-architects --
same image, same schema, same data flow.

### Q4 (2026-05-18): What ports does the local stack actually open, and what does `--dev` (in `docker-compose.yml`'s `command:`) really do? Where is `--dev` defined in livekit-server source?

**Ports, two ways of counting.**

The SFU itself opens **three** things, not four. The "four ports" framing comes from counting the full local stack, not just the SFU.

SFU (livekit-server in Docker) opens:

| Port | Protocol | Purpose |
|---|---|---|
| `7880` | TCP | Signaling + WS upgrades. Clients connect for room join, participant list, etc. The agent worker also registers here over WS. |
| `7881` | TCP | WebRTC TCP fallback. Used when UDP is blocked (corp firewalls, VPNs). |
| `50000-50100` | UDP | WebRTC media port range. Each participant's audio stream takes one port. Technically 101 individual UDP ports, allocated dynamically as participants join. |

Full local stack opens (depending on what you call "the stack"):

| Listener | Port | Notes |
|---|---|---|
| SFU signaling | 7880 TCP | as above |
| SFU TCP fallback | 7881 TCP | as above |
| SFU media | 50000-50100 UDP | as above |
| token-mint (FastAPI) | 8001 TCP | from `uvicorn src.token_mint:app --port 8001` |
| frontend (agent-starter-react) | 3000 TCP | only while you are developing the UI |

So "3 SFU + 1 token-mint" = 4 if we exclude the browser frontend; "3 SFU + 1 token-mint + 1 frontend" = 5 with it. Earlier prose in this doc that said "four ports" was loose; the precise number is 3 at the SFU level and 4-5 across the whole laptop.

**What `--dev` actually does, with source citations.**

`--dev` is a CLI flag on the `livekit-server` binary. The flag's own usage string is: "sets log-level to debug, console formatter, and /debug/pprof. insecure for production." That undersells slightly -- here is the complete list.

Source path: `livekit-server-src/` (this is the read-only clone of `livekit/livekit` at the repo root).

1. **Flag declaration** -- `cmd/server/main.go:108-111`:
   ```go
   &cli.BoolFlag{
       Name:  "dev",
       Usage: "sets log-level to debug, console formatter, and /debug/pprof. insecure for production",
   },
   ```

2. **Stored on the config struct** -- `pkg/config/config.go:797`:
   ```go
   conf.Development = c.Bool("dev")
   ```

3. **Five behaviors gated by `conf.Development`:**

| Effect | File:Line | Production (no `--dev`) | Dev (`--dev`) |
|---|---|---|---|
| TURN relay port range default | `pkg/config/config.go:502-510` | 30000-40000 (10001 ports) | 30000-30002 (just 2 ports) -- so Docker port forwarding stays bearable |
| Default log level (when YAML omits it) | `pkg/config/config.go:516-518` | `info` | `debug` |
| API secret length warning | `pkg/config/config.go:635-641` | warn if any secret < 32 chars | skip the check (so `devsecret-please-change` does not spam the logs) |
| Debug HTTP endpoints | `pkg/service/server.go:134-140` | not registered | `/debug/goroutine` and `/debug/rooms` registered on the default ServeMux for live introspection |
| RTCService.isDev | `pkg/service/rtcservice.go:70` | false | true -- this field appears vestigial in the current code (set but not read anywhere); the other four effects above are the real ones |

**Bottom line on `--dev`:** more verbose logs by default, no secret warnings, debug HTTP endpoints on, and a small TURN range. The flag itself does **not** change anything about the user-visible 7880/7881/UDP ports. Drop `--dev` from `infra/docker-compose.yml`'s `command:` line when moving to production (and rotate the secret at the same time so the previously-skipped length warning would no longer fire anyway).

### Q5 (2026-05-18): I have Docker Desktop running locally. Will `docker compose up` show the container details there? And is there a better way given Docker Desktop is available?

**Yes, Docker Desktop shows everything.** Once you run `docker compose -f infra/docker-compose.yml up`, the container appears in Docker Desktop under the Containers tab (grouped under the compose stack name). You get for free:
- Live container status (Running / Stopped / Exited).
- Click-to-open log stream (same content as Terminal 1).
- CPU + memory stats.
- Click-to-exec terminal *into* the container (useful for `cat /etc/livekit.yaml` inside, etc.).
- Inspect view (full JSON config: env vars, mounts, networks).
- GUI start / stop / restart buttons -- same effect as `docker compose up/down`.
- Compose stack also appears under the Volumes and Networks tabs.

**Important caveat: `network_mode: host` on macOS.**

Our `infra/docker-compose.yml` uses `network_mode: host`. On Linux that means the container shares the host's network stack directly. On macOS, Docker Desktop runs containers inside a small Linux VM, so historically "host networking" on macOS meant "the VM's network, not your macOS host's" -- which would make ports inside the container unreachable from your browser at `localhost`.

Docker Desktop 4.29 (March 2024) added beta support for **true** host networking on macOS, but it must be enabled: Docker Desktop > Settings > Resources > Network > **Enable host networking**.

- **Toggle on**: our setup works as-is. The Ports column in the GUI will look empty -- correct with host networking, since there is no explicit port mapping.
- **Toggle off or older Docker Desktop**: SFU starts fine but `ws://localhost:7880` is unreachable from your browser. Fix is one of:
  1. Enable the beta toggle and restart Docker Desktop. (User confirmed doing this 2026-05-18; SFU now reachable.)
  2. Switch `infra/docker-compose.yml` to bridged networking with explicit port mapping: list 7880, 7881, and the 50000-50100 UDP range under a `ports:` block. More verbose, but works on any Docker Desktop version and Docker Desktop's Ports column then shows mappings clearly.

**Operational shortcut.** Once you confirm the SFU is healthy once via CLI (`curl -sf http://localhost:7880/`), using the Docker Desktop GUI to start/stop/inspect during development is genuinely nicer than the CLI -- especially for tailing logs. The CLI commands still work; pick whichever feels faster.

### Q6 (2026-05-18): Explain `sophia-agent/src/token_mint.py`. How is token minting handled when we use `my-agent` (the Cloud + Inference benchmark)?

#### What `token_mint.py` is, and why it has to exist

`token_mint.py` is a tiny FastAPI service (~70 lines) whose only job is to **issue short-lived signed JWTs** that browser / mobile clients hand to the SFU when joining a room.

The reason it exists, in one sentence: **clients can never hold `LIVEKIT_API_SECRET`** -- if they did, anyone who opened your browser dev-tools could mint admin tokens to any room. So the secret stays on a server we control (the token-mint), and the server issues per-user, per-room, time-limited JWTs that the client *can* safely hold. This is the LiveKit equivalent of "your backend signs an S3 upload URL; the browser uploads to that URL; the browser never sees your AWS keys."

Every LiveKit deployment (Cloud or self-hosted) needs *some* token-mint somewhere. The only thing that differs is who runs it and where it lives.

#### Walking through `sophia-agent/src/token_mint.py`

The file has five pieces:

1. **FastAPI app + permissive CORS.** Local dev only -- we let any origin hit `/token`. For production we tighten this to the real frontend origin.
2. **Env vars read at startup**: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`. Same values as in `sophia-agent/.env.local`, same values as in `infra/livekit.yaml`'s `keys:` block. Three places, one pair. If they disagree, JWTs won't validate against the SFU.
3. **`TokenRequest` model**: what the client posts -- `identity` (their user id), `room` (which room to join), optional `name`, `metadata`, `ttl_seconds` (default 3600 = 1 hour).
4. **`/token` endpoint** -- the actual JWT mint. Three steps:
   - Build a `VideoGrants` object stating what permissions the JWT carries. We grant `room_join=True`, scope to `req.room`, plus `can_publish`, `can_subscribe`, `can_publish_data`. This means "you can join this one room, send your mic, receive everyone else's mic, and send data messages."
   - Build an `AccessToken` signed with `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET`, attach the identity, name, grants, ttl, optional metadata.
   - Call `.to_jwt()` to produce the encoded string and return it along with `LIVEKIT_URL` so the client knows where to connect.
5. **`/health` endpoint**: trivial JSON ping. Used by load balancers and your own sanity checks.

#### The runtime flow (sophia-agent / OSS local)

1. Browser opens the frontend.
2. Frontend POSTs `http://localhost:8001/token` with the user's identity and the room name.
3. `token_mint.py` returns `{token: "eyJ...", url: "ws://localhost:7880"}`.
4. Frontend opens a WebSocket to `ws://localhost:7880`, presents the JWT in the upgrade.
5. SFU validates the JWT signature using the `keys:` block in `livekit.yaml` (matches `devkey` / `devsecret-please-change`), reads the embedded grants, joins the client to `req.room`.

The agent worker uses a different but parallel mechanism: it registers as a *worker* (not a client) using the same `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` directly from its env. It does not need a JWT from `token_mint.py` -- it authenticates directly because it is a trusted server-side component.

#### How `my-agent` handles this (Cloud + Inference benchmark)

`my-agent` does **not** ship its own token-mint script. The reason is convenience for development, not a fundamental architectural difference. The token-mint still exists -- it just lives somewhere else.

Two phases:

**Phase A: development with the LiveKit Agents Playground (what you have been using).**

When you ran `lk cloud auth` and then `lk app env -w -d .env.local`, the CLI populated `my-agent/.env.local` with `LIVEKIT_URL=wss://<your-project>.livekit.cloud`, `LIVEKIT_API_KEY=APIxxx...`, `LIVEKIT_API_SECRET=secret...` -- credentials for *your* Cloud project. The agent worker registers against Cloud using these.

For the client side: the Agents Playground (the web UI at `https://agents-playground.livekit.io` or whichever URL you joined from) accepts your `LIVEKIT_URL` + key + secret as inputs, and **mints tokens client-side in JavaScript** for testing purposes. That works only because you are the developer pasting in your own credentials on a localhost test rig. The Playground is essentially saying "I will pretend to be your token-mint just for this dev session." Convenient. Not safe for any real user-facing scenario.

So: the token *is* still being minted, by JavaScript in the Playground tab, using your secret. No backend service. That is why `my-agent/` has no `token_mint.py` file.

**Phase B: production for `my-agent` (hypothetical).**

If you were to ship `my-agent` as-is to real users, you would absolutely have to add a token-mint service. The choices:
- Write a FastAPI / Express / Go service almost identical to `sophia-agent/src/token_mint.py`, except `LIVEKIT_URL` points at Cloud. Same code, different upstream. Cloud's SFU validates JWTs signed with the same Cloud-issued API key/secret pair.
- Use LiveKit's hosted "Sandbox" or any of the agent-starter frontends (React, Swift, Flutter) which include a server-side token endpoint by default. Same shape, just pre-written.

So the **identical 70-line FastAPI pattern from `sophia-agent/src/token_mint.py` is what you would deploy for `my-agent` in production**, only changing one env var. This is why `livekit_deployment.md` section 5 lists "token-mint code in `sophia-agent/src/token_mint.py`" under "What is the same between local and production" -- it travels unchanged across Cloud vs OSS, dev vs prod.

#### Mental model

| Setup | Who mints tokens | Where the secret lives |
|---|---|---|
| `my-agent` + LiveKit Cloud + Playground (dev) | JavaScript in the Playground tab | Pasted into the Playground UI from `.env.local` -- in your browser. Acceptable only because it is you on localhost. |
| `my-agent` + LiveKit Cloud, production | Your own FastAPI / Node / Go service (would have to add it) | On the server hosting that service. |
| `sophia-agent` + OSS SFU, local | `src/token_mint.py` on `localhost:8001` | In `.env.local` on your laptop. |
| `sophia-agent` + OSS SFU, production | Same `src/token_mint.py`, deployed on AWS | In AWS Secrets Manager, injected at container start. |

The token-mint code is one of the few pieces of the stack that genuinely never changes shape across all four cells. Only `LIVEKIT_URL` and the source of the secret change.

### Q7 (2026-05-19): Restatement -- in my-agent + Cloud + Playground (dev), the Playground reads `.env.local` to get LIVEKIT_URL and API_KEY; in sophia-agent + OSS we run our own FastAPI to mint tokens; in my-agent production the Playground is not local so we also need a FastAPI in the cloud. Is that right?

Close, but two important corrections.

#### Correction 1 -- the Playground never reads `.env.local`

The Playground is a JavaScript app running in a browser tab. It has zero file-system access. The reason this is confusing is that `.env.local` *does* exist and *is* being used -- but by a different actor.

There are **three actors**, not two, sharing the same credentials in different ways:

| Actor | What it is | How it gets the credentials |
|---|---|---|
| **Agent worker** | `my-agent/src/agent.py` running as a Python process on your laptop. Registers as a worker against the Cloud SFU. | Reads `.env.local` directly via `load_dotenv(".env.local")`. Uses LIVEKIT_URL + API_KEY + API_SECRET to authenticate as a *worker* (server-side trust). No JWT needed -- workers authenticate with the raw API key/secret. |
| **Client** | The Playground browser tab (`https://agents-playground.livekit.io` or a local instance). Joins a room as a *participant*. | You paste LIVEKIT_URL + API_KEY + API_SECRET into the Playground's UI form, or you open it via a LiveKit Sandbox link that injects them. Now the secret is sitting in browser JS memory. |
| **Token-mint** | In Playground mode: **fused into the Playground itself**. The Playground signs JWTs in JavaScript using the secret you pasted. | Same credentials the client has in memory. No separate server. |

So when you use my-agent + Playground in dev, the credentials are duplicated in two places: in `.env.local` on disk (used by the worker), and in the Playground's JS memory (used by the client + fused token-mint). They are the same values, but they reach those two places by completely separate paths. The Playground never reads `.env.local`. The agent worker never reads from the Playground UI.

The reason this is acceptable in dev is that "you on localhost pasting your own secret into your own browser tab" is not a real security boundary. The reason it is **not** acceptable in production is the same fact: any user opening the Playground could read the secret out of JS memory via dev-tools, and use it to mint admin tokens for any room.

#### Correction 2 -- production my-agent does not use Playground at all

The framing "Playground is not local in production, so we need a FastAPI in the cloud" implies Playground is a thing you would still try to use in production -- it isn't. The Playground is purely a developer tool. In production for any LiveKit deployment (Cloud or OSS, my-agent shape or sophia-agent shape), you replace the Playground entirely with two separate production-grade components:

1. **A real frontend** -- React (e.g. `agent-starter-react`), Android (`agent-starter-android`), iOS, Flutter, etc. This is what your end users open. It is *not* the Playground.
2. **A real token-mint service** -- FastAPI / Node / Go / Lambda. Holds the API_SECRET server-side. Receives token requests from the frontend over HTTPS, returns short-lived JWTs.

So the **correct three-mode picture**:

| Mode | Worker reads | Client | Token-mint |
|---|---|---|---|
| my-agent + Cloud + Playground (dev) | `my-agent/.env.local` -> Cloud SFU | Playground browser tab | Playground JS (fused into client) |
| sophia-agent + OSS (local dev) | `sophia-agent/.env.local` -> `ws://localhost:7880` | `agent-starter-react` on `:3000` | `sophia-agent/src/token_mint.py` on `:8001` |
| my-agent + Cloud (hypothetical production) | secret from AWS Secrets Manager -> Cloud SFU | Your own frontend (React / Android / iOS) | Your own FastAPI service (almost identical to `token_mint.py`, just LIVEKIT_URL pointed at Cloud) |
| sophia-agent + OSS (production) | secret from AWS Secrets Manager -> self-hosted `livekit-server` on AWS | Your own frontend (React / Android / iOS) | The same `token_mint.py` deployed to AWS |

The crucial insight: **the token-mint always exists in some form, in every mode**. In dev with Playground it happens to be fused into the client. In every other mode it is a separate server-side service. That server-side service code is nearly identical regardless of Cloud-vs-OSS, dev-vs-prod -- only `LIVEKIT_URL` and the source of the secret change. `sophia-agent/src/token_mint.py` is what that code looks like, and you would deploy a near-copy of it for my-agent production too.

So the corrected restatement:

- **my-agent + Playground (dev)**: agent worker reads `.env.local`; Playground reads credentials from its own UI form (you paste them in); Playground signs JWTs in browser JS. Three actors but the last two are fused.
- **sophia-agent (local)**: agent worker reads `.env.local`; token_mint.py reads `.env.local`; frontend calls token_mint.py for JWTs. Three actors, all separate.
- **my-agent (production)**: no Playground at all. You build a real frontend + a real token-mint, both deployed separately from the agent worker. Same three actors, all separate, just like sophia-agent in production.

### Q8 (2026-05-19): When I run `uv run python src/agent.py download-files`, where does the `download-files` subcommand come from? It is not in agent.py.

Right -- it is not in `agent.py`. The `download-files` subcommand is added by the LiveKit Agents framework when `cli.run_app(server)` runs at the bottom of `agent.py`. That call wires `agent.py` into a typer-based CLI which exposes `console`, `dev`, `start`, `connect`, and `download-files` as subcommands. When you invoke `download-files`, the framework iterates `Plugin.registered_plugins` (every imported `livekit-plugins-*` package) and calls each plugin's `download_files()` method. Default implementation is a no-op. The `livekit-plugins-turn-detector` plugin overrides it to pull the EOT ONNX model from Hugging Face Hub. `livekit-plugins-silero` does nothing because its ONNX is already bundled inside the pip package.

Full source-cited deep-dive lives in `livekit_doubts.md` Q26 (framework concept, so it stays in the framework Q&A file per routing convention). This entry exists only as a cross-reference so a reader on the sophia-agent operational thread does not have to dig.

### Q9 (2026-05-19): How do I read the four-service startup logs and know everything is wired correctly?

When all four services come up cleanly, there are exactly **four "magic" lines** to look for, one per service. If you see all four, the local OSS stack is healthy.

| Service | Magic line | Why it matters |
|---|---|---|
| SFU (Docker) | `worker registered ... agentName: sophia-agent, workerID: AW_xxxx` | This is the **SFU's view** of your agent worker showing up. If you only see the SFU's own startup ("starting LiveKit server portHttp: 7880") but never this line, the worker is not reaching the SFU. |
| token-mint (uvicorn) | `Application startup complete.` | Lifespan startup ran without errors; `/token` and `/health` endpoints are live. Confirm with `curl -sf http://localhost:8001/health`. |
| agent worker (Python) | `registered worker ... id: AW_xxxx, url: ws://localhost:7880` | This is the **worker's view** of connecting to the SFU. The id must **match** the workerID printed by the SFU. Same id in both logs = handshake verified. |
| frontend (Next.js) | `Ready in 628ms` (or similar `Ready in ...`) plus `Environments: .env.local` | Frontend bundled and your env file was loaded. If `Environments` line is missing or shows a different file, the five env values are not being applied. |

**Other recurring lines and what they mean:**

- `starting in development mode` (SFU) -- `--dev` flag honored. Expected.
- `using single-node routing` (SFU) -- no redis, single instance. Expected for local.
- `plugin registered livekit.plugins.silero` (worker) -- Silero VAD plugin imported.
- `plugin registered livekit.plugins.turn_detector.base` printed **twice** (worker) -- once for the main worker process, once for the inference subprocess that holds the EOT ONNX. Normal.
- `starting inference executor` followed by `initializing process pid X, inference: true` and later `process initialized elapsed_time N` (worker) -- the turn-detector subprocess. `elapsed_time` ~3 s on first start (loads ONNX). Normal.
- `HTTP server listening on :54717` (worker) -- the worker's internal debug HTTP server on a random ephemeral port. Ignore.
- `InsecureKeyLengthWarning: The HMAC key is 23 bytes long` (worker) -- PyJWT complains because `devsecret-please-change` is 23 chars (RFC 7518 recommends >= 32). Harmless in dev. Goes away when we rotate to a 32-byte random secret in production (Q3 local-to-prod diff table).
- `Will watch for changes` and two pids (token-mint) -- uvicorn `--reload` pattern: outer reloader process + inner server process. Edits to `token_mint.py` hot-reload. Normal.
- `Local: http://localhost:3000` and `Network: http://<lan-ip>:3000` (frontend) -- Next.js binds locally and on your LAN IP. The LAN URL is useful only if you want to test from your phone on the same Wi-Fi.

**What still has to happen at step 6** (still pending as of 2026-05-19):

Open `http://localhost:3000` in a browser, join the default room. Two things should happen:
1. Your camera/mic tile appears (frontend got its JWT from `token_mint.py` and joined the SFU).
2. The agent worker terminal prints a new `prewarm` line as the framework forks a worker subprocess for the new session, then a new entrypoint log -- this is the agent joining the room as a second participant.

The agent will stay silent because STT, LLM, and TTS are not wired yet. That is the smoke-test pass condition for the OSS local stack. After that we move to Thread B: wiring AWS STT and TTS.

### Q10 (2026-05-19): What does `kokoro-tts-server.py` (from Sophia's infra repo) tell us about wiring AWS TTS into sophia-agent?

A lot. Headlines first, then the gotchas, then what is still missing.

**Headline 1 -- it is an OpenAI-compatible TTS server.** Endpoints are `GET /health`, `GET /v1/models`, `POST /v1/audio/speech` (returns WAV), `POST /v1/audio/speech/stream` (returns raw int16 PCM at 24000 Hz), and `GET /metrics`. Path shape and request body match the OpenAI TTS API.

**Headline 2 -- the same contract covers Kokoro, Orpheus, and qwen3-tts.** The docstring is explicit: "Drop-in replacement for the qwen3-tts / orpheus-tts servers in the Sophia speech pipeline -- same external contract." That means one plugin configuration works for all three; only the URL changes.

**Headline 3 -- wire-level voices are Sophia-branded, not Kokoro-native.** Valid `voice` values for any of the three TTS models: `aiden`, `dylan`, `eric`, `ono_anna`, `ryan`, `serena`, `sohee`, `uncle_fu`, `vivian`. Default `aiden`. Anything else returns 400.

**Request schema** -- `model` (optional, e.g. `kokoro-82m`), `input` (required), `voice` (optional, from the list above), `language` (optional: `a`=US English, `b`=UK English, `j`=Japanese, `z`=Mandarin), `speed` (0.5-2.0), `instruct` (ignored; parity field).

**Audio output** -- 24000 Hz mono, int16 PCM. WAV-wrapped on `/v1/audio/speech`, raw PCM on `/v1/audio/speech/stream`.

**Auth** -- zero auth code in the file. Either the AWS LB / VPC handles auth at the network layer, or the service is genuinely open inside the VPC. Need to confirm with the infra team before reaching it.

**Default port** -- 8122 (env var `PORT`).

**Two integration routes (Route A vs B per Q36 in `livekit_doubts.md`):**

- **Route A**: `livekit.plugins.openai.TTS(base_url="http://localhost:8122/v1", model="kokoro-82m", voice="aiden")`. Zero plugin code. Likely works because the openai plugin defaults to 24000 Hz PCM, matching Kokoro. **Three potential gotchas to test for**:
  1. The openai plugin sends `response_format` in the request body. Kokoro's pydantic schema does not declare it. If pydantic is lenient (default), ignored; if strict, 422 error.
  2. The openai plugin hits `/v1/audio/speech` (non-streaming), which returns WAV. The plugin's audio decoder may glitch on the 44-byte WAV header if it expects raw PCM. Many openai TTS clients handle WAV transparently, some do not.
  3. The openai plugin has no `language` field; language defaults server-side to `a` (US English). Fine for English. If we ever need JP / ZH, fall back to Route B.

- **Route B**: a ~80-line `SophiaTTS(tts.TTS)` subclass under `sophia-agent/src/plugins/sophia_tts.py`. Hits `/v1/audio/speech/stream` directly for lower TTFB. Full control of request body (set `language`, omit `response_format`). One class with a `model_url` constructor arg means one plugin shape for all three TTS models. Reference shape: `livekit-plugins-cartesia/.../tts.py` in the `livekit-agents/` clone.

**Recommendation**: try Route A first. If any gotcha bites, drop to Route B. Either way the wire shape is fully known from this file -- not blocked on AWS docs.

**What we still need from the infra team / user before wiring** -- (1) actual URLs / port-forward access to each of kokoro, orpheus, qwen3-tts; (2) auth model (VPC-only vs bearer token vs IAM); (3) confirmation Orpheus and qwen3-tts speak the same contract (or share their server files); (4) the analogous `*-stt-server.py` file or contract info for whichever STT model is on the cluster.

### Q11 (2026-05-19): Can we port-forward Sophia's TTS / STT services to localhost like we did for the previous project, and what does the script look like?

Yes. User's previous port-forward script was `kubectl port-forward` against namespace `multi-agent`, using a `forward()` helper that backgrounds each `kubectl port-forward svc/<name> <local>:<remote>` and traps EXIT/INT/TERM for cleanup. Confirmed the TTS stack is on EKS in that same namespace (in-cluster service-name DNS visible in `kokoro-tts-server.py` -- e.g. `MLFLOW_TRACKING_URI=http://mlflow:5000` -- is a k8s in-cluster pattern).

**Wrote sophia-agent's port-forward script at `sophia-agent/infra/port-forward.sh`** (chmod +x done). Mirrors the previous project's structure (background PIDS array, trap cleanup, `forward()` helper). Three modes: default (Kokoro + Orpheus + qwen3-tts + STT), `--tts-only`, `--kokoro-only` (for first integration test).

**Local-port plan**:

| Service | Local | Remote (in-cluster) |
|---|---|---|
| Kokoro | 8122 | 8122 (from `kokoro-tts-server.py` PORT default) |
| Orpheus | 8123 | 8122 (assumed; same contract per docstring) |
| qwen3-tts | 8124 | 8122 (assumed; same contract per docstring) |
| STT | 8200 | 8000 (placeholder until STT model decided) |

Different local ports so all four can run simultaneously without collision.

**Assumed defaults** (override with env vars before running): namespace `multi-agent`; service names `kokoro-tts` / `orpheus-tts` / `qwen3-tts`. User must run `kubectl get svc -n multi-agent | grep -iE 'kokoro|orpheus|qwen|tts|stt'` to confirm actual names, then either edit the defaults or pass `SOPHIA_KOKORO_SVC=<real-name> ./infra/port-forward.sh`.

**STT remains gated** on user choosing which STT model is on the cluster (`SOPHIA_STT_SVC` is empty by default; script skips STT until set).

**Verify after running** -- `curl -sf http://localhost:8122/health` should return JSON with `status: healthy, model: kokoro-82m` and the list of nine wire-level voices. If health check passes, Kokoro is reachable via the tunnel and the next step is wiring it into `sophia-agent/src/agent.py` (Route A, three lines).

### Q12 (2026-05-19): What each Sophia model server actually is, and what port-forward.sh should forward

User shared four FastAPI server files from the infra repo (placed at project root, NOT inside sophia-agent): `inference-server.py`, `kokoro-tts-server.py`, `qwen3-tts-server.py`, `whisper-inference-server.py`. Plus the original `kokoro-tts-server.py` already covered in Q10. Five facts that came out of reading them:

1. **`qwen3-inference` is NOT plain Qwen3 text.** `inference-server.py` loads `Qwen3VLForConditionalGeneration` from `/models/Qwen3-VL-8B-Instruct` -- this is the **vision-language** Qwen3, served via Transformers (not vLLM) with int8 quantization on A10G (24GB). MODEL_NAME = `qwen3-vl-8b-instruct`. The endpoint is the standard OpenAI `/v1/chat/completions` (streaming + non-streaming), so it CAN be used as a pure text LLM by sending text-only messages -- the vision path is just unused. Server has a slick server-side micro-batcher for non-streaming requests (`BATCH_ENABLED=1` default, `BATCH_MAX_SIZE=8`, `BATCH_WAIT_MS=50`), bypassed when `stream=true`. PORT default = 8080; matches the k8s `qwen3-inference` service. Sophia will pass `model="qwen3-vl-8b-instruct"` to `openai.LLM(...)`.

2. **`whisper-inference` is Whisper Large v3, batch-mode only.** `whisper-inference-server.py` loads `openai/whisper-large-v3` via Transformers' ASR pipeline (`AutoModelForSpeechSeq2Seq` + `AutoProcessor`). MODEL_NAME = `whisper-large-v3`. Endpoint = OpenAI-compatible `POST /v1/audio/transcriptions` accepting multipart file uploads with `language` + `response_format` (json | text | verbose_json) Form fields. There is **no streaming endpoint inside the server** -- the full audio file is buffered, transcribed, and returned as a single JSON. The LiveKit `openai.STT` plugin works because it chunks the LiveKit mic stream into short clips client-side and POSTs each as a separate /v1/audio/transcriptions call; expect ~200-500ms per-chunk latency. If end-to-end latency feels bad, swap whisper-large-v3 for faster-whisper-server later (same OpenAI contract). PORT default = 8080; matches the k8s `whisper-inference` service. Sophia will pass `model="whisper-large-v3"` to `openai.STT(...)`.

3. **`kokoro-tts` is unchanged from Q10's analysis.** Same OpenAI-compatible /v1/audio/speech (WAV) + /v1/audio/speech/stream (raw int16 PCM at 24000 Hz). MODEL_NAME = `kokoro-82m`. Nine voices (aiden default). PORT 8122 matches k8s.

4. **`qwen3-tts-server.py` exists in code but NOT deployed in k8s yet.** Server file describes Qwen3-TTS-12Hz-1.7B-CustomVoice (`/models/qwen3-tts-12hz-1.7b-customvoice`), MODEL_NAME = `qwen3-tts-12hz-1.7b-customvoice`, voices Aiden/Vivian/Ryan/Serena/Olivia/Noah/Mia/Ethan/Cherry, PORT default 8121. Docstring is explicit: "Drop-in replacement for the Orpheus TTS server in the Sophia speech pipeline -- same external contract." Has a sophisticated streaming endpoint with phrase-splitting (`/v1/audio/speech/stream` yields ~200ms PCM frames after first-phrase synth, single-flight lock around `generate_speech` to serialize concurrent requests). Will be added to port-forward.sh once `kubectl get svc -n multi-agent` shows it deployed. User instruction: do NOT plumb it speculatively.

5. **No auth on any of these servers.** Code review confirms zero auth-header handling -- security is purely VPC-level (ClusterIP services, no Ingress). Locally via `kubectl port-forward` we hit them with no auth, which works. For production-from-AWS-laptop access we'd need either an SSH bastion or to expose via API Gateway with IAM auth (Q10's note repeated).

**port-forward.sh final shape** (after the simplification per user's instruction "remove all customizations, just forward what we gave in the code"): hardcoded four-line list, no env overrides, no modes. Matches the user's previous benchmarking project's shape (just PIDS + forward() + trap cleanup):

```bash
forward kokoro-tts          8122:8122
forward orpheus-tts         8120:8120
forward whisper-inference   8080:8080
forward qwen3-inference     8081:8080   # local 8081 to avoid collision with whisper on 8080
```

**Sophia agent.py wiring (Route A, zero plugin code)** -- once port-forward is up and `/v1/models` confirmed:

```python
session = AgentSession(
    vad=silero.VAD.load(),
    stt=openai.STT(base_url="http://localhost:8080/v1", model="whisper-large-v3", api_key="not-needed"),
    llm=openai.LLM(base_url="http://localhost:8081/v1", model="qwen3-vl-8b-instruct", api_key="not-needed"),
    tts=openai.TTS(base_url="http://localhost:8122/v1", model="kokoro-82m", voice="aiden", api_key="not-needed"),
    turn_detection=MultilingualModel(),
)
```

LLM is a vision-language model used in text-only mode. Voice loop will work end-to-end but answers are generic (not RAG-grounded). Real RAG endpoint (`/query`) wiring is the still-parked Thread C work (livekit_doubts.md Q12, Q14).

### Q13 (2026-05-19): Why we abandoned Docker for local livekit-server and switched to native brew install -- two WebRTC failures and a production-parity argument

Three-step diagnostic chain that ended with us deleting Docker from the local stack entirely.

**Failure 1 -- Docker-on-macOS advertises VM IP as ICE candidate.** First browser join attempt failed with "could not establish pc connection". SFU logs showed `nodeIP: 192.168.65.3`. Even with `network_mode: host` and Docker Desktop's host-networking beta toggle on, on macOS the container's network namespace reports the Docker-VM gateway IP (192.168.65.x) as the primary interface IP. The SFU auto-detects this and advertises it as the ICE candidate. Browser cannot reach 192.168.65.3 from outside the VM -> DTLS handshake timeout. **Fix:** added `--node-ip 127.0.0.1` to the livekit-server command in `infra/docker-compose.yml`. That overrides the auto-detect.

**Failure 2 -- Safari mDNS vs Docker namespace.** Node-ip fix worked for the agent (Python livekit-rtc client connects via UDP, local 127.0.0.1 + remote 100.69.34.x), but the BROWSER still fails. SFU candidate-pair stats showed all `state: failed, requestsSent: 8, responsesReceived: 0`. Looking at publisherCandidates: host candidates show `udp host :49218` (empty IP before colon). Safari sends host candidates as mDNS-obfuscated `.local` addresses for privacy. The SFU inside the Docker container cannot resolve `*.local` mDNS (Docker namespace doesn't see Bonjour) so they get stripped to empty IPs. Only srflx (public-IP-via-STUN) candidates remain, pointing at the router's public IP (66.253.176.x), which the SFU inside Docker also cannot reach. Every candidate pair `state: failed`.

**Fix that ended all of this -- run livekit-server natively:** stopped Docker, `brew install livekit` (v1.12.0, same version as the Docker image), updated `infra/docker-compose.yml` to be the canonical EC2 production reference (Linux Docker doesn't have the mDNS bug), updated `RUNBOOK.md` Step 1 to `livekit-server --config infra/livekit.yaml --dev`. The `infra/livekit.yaml` is unchanged and loaded by the native binary as-is. Native binary picks `nodeIP: 100.69.34.194` (the laptop's actual local network interface, a Tailscale 100.x address) -- both agent and browser are on the same machine and reach it cleanly.

**Production parity rationale:** EC2 Linux production CAN use either Docker or native, but native is simpler (no Docker daemon, fewer moving parts). Running native locally matches production exactly. The `infra/docker-compose.yml` stays in the repo as a reference for the EC2 path if we ever want it.

**One-line takeaway:** never use Docker for livekit-server on macOS. Always native via brew (or, in production, native via systemd / launchd / k8s pod with hostNetwork on Linux).

### Q14 (2026-05-19): Infra team's `pf-gpu.sh` script -- what it does, conventions, and what it unlocked

The infra team handed us `pf-gpu.sh` (dropped at `sophia-agent/infra/pf-gpu.sh`). We adopted it as the canonical port-forward script and deleted our 4-line `port-forward.sh`.

**What it adds over our simple version:**
- kubectl-discovers remote ports from the Service manifest (single source of truth)
- Persistent PID file at `/tmp/pf-gpu.pids` (so `./infra/pf-gpu.sh stop` works from a different shell)
- Per-service log files at `/tmp/pf-gpu-logs/<svc>.log`
- Three subcommands: `start` (default), `stop`, `list` (cluster-wide GPU pod inventory)
- lsof port-collision check (skips with warning if local port already bound)
- Skips services with no ready pods (orpheus-tts often)
- Requires `jq` (already installed on the Mac)

**Critical convention:** local port = remote port unless collision; collision-resolver = prepend "1". So `qwen3-inference` ends up on local **18080** (in-cluster 8080), NOT 8081 as we originally chose. `agent.py` was updated to match.

**Services it forwards (curated list in the script):**

| Service | Local | In-cluster | Notes |
|---|---|---|---|
| whisper-inference | 8080 | 8080 | STT |
| qwen3-inference | 18080 | 8080 | Canonical online LLM (Qwen3-VL-8B-Instruct int4) |
| kokoro-tts | 8122 | 8122 | TTS |
| orpheus-tts | 8120 | 8120 | Historical, may be gone (script skips gracefully) |
| sophia-spatial-ai | 8106 | 8106 | **RAG endpoint** — this is the unlock |
| voice-relay | 8111 | 8111 | CPU, not GPU but included |

**Critical commentary embedded in the script (worth quoting in full so future-us doesn't get it wrong):**
- `qwen3-inference` is the canonical online LLM that voice-relay, sophia, dashboard all use.
- `qwen3-vl-vllm` (same model, different serving stack) is **ingestion-only batch pipeline** -- scaled manually, may not be running, tuned for batch-throughput not single-prompt latency. **Do not point research at qwen3-vl-vllm.**
- Future KEDA work consolidates the two: qwen3-vl-vllm becomes the canonical target and qwen3-inference retires. Until then, use qwen3-inference.

**Internal `./scripts/pf-gpu.sh` paths updated to `./infra/pf-gpu.sh`** when we adopted the script (cosmetic; the usage strings).

**Old `infra/port-forward.sh` deleted** after this adoption -- pf-gpu.sh is a strict superset.

### Q15 (2026-05-19): RAG endpoint sophia-spatial-ai -- discovery, contract, and the function_tool wiring we picked

User asked: "can we replace the LLM with RAG?". Three-step investigation:

**Step 1 -- service identity.** `curl /.well-known/agent.json` revealed sophia-spatial-ai is a Spatial AI assistant for **industrial equipment PDF manuals** (NOT general chat). Uses ColPali/Byaldi retrieval + Qwen3-VL reasoning + TF-IDF hybrid index. Four advertised skills: `manual_qa`, `image_qa`, `process_document`, `component_lookup`. Knowledge base currently has Genesis GV70 owner's manual + an x250 manual (the live test query "What is Sophia?" returned image refs from those two PDFs).

**Step 2 -- contract.** `/v1/models` returns 404 -> NOT OpenAI-compatible, so a one-line LLM base_url swap (Path A) is out. `/openapi.json` revealed 21 routes; the relevant ones:
- `POST /question` -- main QA. Body schema `QuestionRequest`: `{question: str (required), top_k?: int=4, concise?: bool=true, retrieval_mode?: str="Auto", answer_mode?: str="Auto"}`. Response: `{status, answer, hits, images, mode}`. **Single JSON, NOT streaming.**
- `POST /retrieve` -- same QuestionRequest schema, "fast retrieval-only endpoint (no LLM generation), <150ms typical". For when you want chunks back without generation.
- `POST /image-question` -- vision RAG (for future glasses-camera frames).
- `/cache/{warm,stats,clear}` -- worth calling `/cache/warm` at agent startup so first user question is not cold.
- Other routes are ingestion (`/ingest`, `/process-document`, `/reingest`) and admin (`/metrics`, `/index-info`, OAuth callback).

**Step 3 -- decision matrix.**

- **Path A (one-line LLM swap):** OUT, /v1/chat/completions doesn't exist.
- **Path B (function_tool):** keep qwen3-vl as conversational LLM with streaming intact, add a `@function_tool` qwen3 calls only for manual-related questions.
- **Path C (custom plugin replacing LLM):** subclass `livekit.agents.llm.LLM` and route every turn to /question. **Two killer downsides:** (1) /question is single-JSON so we lose all token-stream TTFB (every reply arrives as one blob after 1500ms+ internal LLM deadline); (2) sophia-spatial-ai is domain-specific -- "hi Sophia" returns "I could not find a relevant answer in the uploaded manuals" -> awful general-chat UX.

**Picked Path B.** Wired into `sophia-agent/src/agent.py`:

```python
import httpx
from livekit.agents import RunContext, function_tool

SOPHIA_RAG_URL = "http://localhost:8106"

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="""
            You are Sophia, a voice assistant for industrial equipment
            technicians... When the user asks about specific equipment,
            components, procedures, troubleshooting, error codes, or
            anything that would plausibly appear in an equipment manual,
            call the lookup_manual tool. For general conversation answer
            directly without calling the tool.
        """)

    @function_tool
    async def lookup_manual(self, context: RunContext, question: str) -> str:
        """Look up an answer in Sophia's industrial equipment manuals."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{SOPHIA_RAG_URL}/question",
                json={"question": question, "concise": True},
            )
            resp.raise_for_status()
            data = resp.json()
        answer = data.get("answer", "").strip()
        hits = data.get("hits") or []
        if not answer:
            return "I could not find a relevant answer in the manuals."
        if hits:
            sources = ", ".join(sorted({h.get("source", "") for h in hits if h.get("source")}))
            if sources:
                return f"{answer} (Source: {sources}.)"
        return answer
```

**Test plan** (logged in CHAT.md turn 28):
- General question: "Hi Sophia, who are you?" -> qwen3 answers directly, no tool call.
- Manual question: "What is the tire pressure for the GV70?" -> qwen3 calls lookup_manual, worker logs show `function_call_started` + `function_call_completed`, spoken answer includes "(Source: GV70_Owners_Manual.pdf)".

**Parked follow-ups (not blocking):**
- Add a faster `search_chunks` tool against `/retrieve` so OUR qwen3 generates the answer from chunks instead of chaining through sophia-spatial-ai's internal LLM (saves the 1500ms LLM deadline, maintains streaming).
- Call `/cache/warm` at agent startup to avoid cold first-question latency.
- `image_question` tool for glasses-camera RAG when vision input lands.
- Tune `retrieval_mode` / `answer_mode` if specific modes work better than "Auto".

### Q16 (2026-05-19): Per-stage behaviour of the working OSS voice loop -- streaming, batching, and where to optimize next

After the voice loop confirmed working end-to-end, captured the actual data shape per stage for future optimization decisions.

**Pipeline shape:**
```
user speaks
  -> [30ms mic frames at 16kHz] Silero VAD per-frame binary classifier
  -> END_OF_SPEECH event
  -> [~1.5s] openai.STT plugin POSTs whole utterance multipart to /v1/audio/transcriptions
     -> whisper-large-v3 batch transcribes, returns single JSON {text: "..."}
  -> transcript appended to chat_ctx
  -> [~30ms] turn detector ONNX returns P(end-of-utterance)
  -> preemptive generation: LLM call issued ~26ms BEFORE formal turn-end
     (observed via "preemptive_lead_time": 0.026s log)
  -> openai.LLM POSTs to /v1/chat/completions with stream=true
     -> qwen3-vl-8b TOKEN STREAMS via SSE chunks (~30-100ms per token)
     -> framework segments stream into sentences as they complete
  -> for each completed sentence, openai.TTS (AudioChunkedStream mode)
     POSTs to /v1/audio/speech and uses iter_bytes()
     -> kokoro-82m server: full-clip synth per sentence, then sends whole WAV
        via HTTP chunked transfer
  -> WAV bytes decoded to 24kHz int16 PCM frames
  -> SpeechHandle scheduler pushes frames to SFU
  -> SFU encodes opus, forwards to browser over WebRTC UDP
  -> browser plays
```

**Per-stage streaming nature (table for quick reference):**

| Stage | Server-side behaviour | Network behaviour | Optimization knob |
|---|---|---|---|
| STT (whisper-large-v3) | BATCH per utterance, full clip then single JSON | Single POST + JSON response | Swap to faster-whisper-server (~1s saved) |
| LLM (qwen3-vl-8b) | TOKEN STREAMING via TextIteratorStreamer | SSE chunks every 30-100ms | Already optimal |
| TTS (kokoro-82m on /v1/audio/speech) | Per-sentence full-clip synth on server, no internal streaming | HTTP chunked transfer (bytes start flowing only after synth completes) | Custom Route B plugin against `/v1/audio/speech/stream` (~500ms TTFB saved -- the stream endpoint yields ~80ms first chunk and 200ms tail chunks) |
| Turn detection | Inference subprocess shared by all workers, ~30ms per prediction | IPC local | Already optimal |
| Preemptive generation | Fires LLM call before user definitively stops | -- | Already enabled |

**End-to-end first-response latency budget (observed):**
- Mic chunk + VAD endpointing: ~300-500ms
- Whisper batch transcribe: ~1.5s
- Turn detector + preemptive offset: ~0ms (preemptive bypasses)
- Qwen3-VL first token: ~100-300ms
- Kokoro first sentence synth: ~500-1000ms
- TTS chunked transfer + decode + opus encode + SFU + browser play: ~50-100ms
- **Total round-trip: ~2-3s for first response.** Subsequent responses faster (LLM warmed, sentences pipelined).

**Where the two known latency wins live:**
1. STT: whisper-large-v3 -> faster-whisper-server keeps Route A (same OpenAI contract), just different model server. Saves ~1s.
2. TTS: kokoro `/v1/audio/speech` -> `/v1/audio/speech/stream` needs a custom Route B plugin (`sophia-agent/src/plugins/sophia_tts.py`) because the openai plugin only hits `/v1/audio/speech`. The qwen3-tts-server.py source we already have describes the phrase-streaming pattern -- 80ms first chunk after first-phrase synth. Saves ~500ms TTFB.

### Q17 (2026-05-19): OSS audit of sophia-agent -- is everything truly open-source?

User asked for confirmation. Yes, every component is open-source, all permissive licenses (Apache 2.0 / MIT). Zero LiveKit Cloud, zero proprietary plugins.

**Local stack:**

| Component | What it is | License | Where it runs |
|---|---|---|---|
| livekit-server | Go binary, SFU | Apache 2.0 | Native on Mac (brew); EC2 native in production |
| livekit-agents | Python framework (VAD/turn/orchestration/SpeechHandle/AEC warmup/barge-in) | Apache 2.0 | uv .venv |
| livekit-api | Python server SDK (`AccessToken` + `VideoGrants` for JWT mint) | Apache 2.0 | uv .venv |
| livekit-plugins-openai | OpenAI-compatible HTTP client for STT/LLM/TTS | Apache 2.0 | uv .venv |
| livekit-plugins-silero | Silero VAD wrapper | Apache 2.0 wrapper, MIT for Silero ONNX | uv .venv |
| livekit-plugins-turn-detector | LiveKit's turn-detector ONNX (MultilingualModel) | Apache 2.0 | uv .venv (inference subprocess) |
| agent-starter-react | Frontend template | Apache 2.0 | npm + Next.js |
| `token_mint.py` | ~70 LOC FastAPI we wrote | our code | sophia-agent/src/ |

**Models on AWS EKS (multi-agent namespace):**

| Model | License |
|---|---|
| whisper-large-v3 | MIT (OpenAI) |
| Qwen3-VL-8B-Instruct | Apache 2.0 (Alibaba Qwen3 family) |
| Kokoro-82M | Apache 2.0 |
| sophia-spatial-ai (RAG service) | Sophia internal -- closed-source but self-hosted, no external dependency |

**Orchestration confirmation:**
- VAD, turn handling, preemptive generation, transcription synchronisation, AEC warmup, barge-in detection, SpeechHandle scheduling, ChatContext stateful history -- all the livekit-agents framework (Apache 2.0) running in our local Python venv. Per Q37-Q38 of livekit_doubts.md, this orchestration layer is ~70-85% of the framework value vs raw model quality.
- livekit-api is used for token minting: our 70-LOC FastAPI (`src/token_mint.py`) uses `livekit.api.AccessToken` and `VideoGrants` to sign JWTs with the devkey/devsecret pair. Same code travels unchanged to production -- only the secret rotates and `LIVEKIT_URL` changes from `ws://localhost:7880` to the EC2 SFU URL.
- livekit-server is running natively (brew install) and acts as the pipe: WS signalling on 7880, TCP fallback for media on 7881, UDP range 50000-50100 for actual RTP audio frames.

**Production EC2 diff (zero agent code change):**
- SFU on EC2 instead of laptop
- Model endpoints reached via private VPC instead of kubectl port-forward
- Secrets from AWS Secrets Manager instead of `.env.local`

That's it. The agent.py + token_mint.py + livekit.yaml + plugins all stay identical.

### Q18 (2026-05-19): How do I see live transcripts in the frontend like the LiveKit Playground does?

The `agent-starter-react` template already ships with a chat/transcript panel identical to the Playground's. It is built on `AgentChatTranscript` + the `useSessionMessages` hook from `@livekit/components-react`. The panel was just hidden behind a toggle button.

**Source location:**
- Panel component: `components/agents-ui/agent-chat-transcript.tsx`
- Wired in: `components/agents-ui/blocks/agent-session-view-01/components/agent-session-block.tsx`
- Gated on `supportsChatInput: true` in `app-config.ts` (default true)

**To make it visible by default (instead of toggle):**

In `agent-session-block.tsx` line ~180, change:
```tsx
const [chatOpen, setChatOpen] = useState(false);
```
to:
```tsx
const [chatOpen, setChatOpen] = useState(true);
```

Done. Hard-refresh, transcript panel opens automatically when you Start Call. Shows:
- Your spoken words as Whisper transcribes them (appears ~1.5-2s after you stop, when the batch transcription returns)
- Sophia's reply text as Qwen3-VL streams tokens (live, sentence-by-sentence as TTS speaks each one)

The TTS-spoken text is the same text the LLM produced, so what you see is exactly what you hear. The synchronization is handled by livekit-agents' `TranscriptSynchronizer` (visible in the worker debug log line `using transcript io: AgentSession -> TranscriptSynchronizer -> RoomIO`).

**Alternative if you want the toggle behaviour back:** keep `useState(false)` and click the chat-bubble icon in the call control bar.

### Q19 (2026-05-19): Why isn't qwen3-vl actually calling the `lookup_manual` tool we wired? And what is the workaround?

User's test conversation revealed qwen3-vl was NEVER calling our `@function_tool lookup_manual`. Worse: it hallucinated detailed manual contents ("Siemens 3VA1, ABB ACS150, Cutler-Hammer H-100 series" when our KB only has GV70 + x250) AND when asked directly "are you calling the rag function call?" it confidently answered "no, I'm just helping you directly".

**Root cause (5-minute source dig):** `inference-server.py`'s `ChatCompletionRequest` schema (line 203) defines only `{model, messages, temperature, top_p, max_tokens, stream, stop}`. No `tools`, no `tool_choice`. Pydantic v2 default behaviour is `extra='ignore'` -- unknown fields are SILENTLY dropped. So:

1. LiveKit's `openai.LLM` plugin sends `tools=[{...lookup_manual...}]` in the POST body.
2. Pydantic strips it before `generate_completion` sees it.
3. `generate_completion` calls `processor.apply_chat_template(qwen_messages, ...)` with NO `tools=` argument.
4. Qwen chat template has no tool definitions in the rendered prompt.
5. The model has no idea function-calling is an option -> hallucinates plausible-sounding manual contents.

This is NOT a LiveKit bug, NOT a qwen3 model bug. It's an infra-server-wrapper omission. Qwen3-VL-8B-Instruct natively supports tool-calling via its chat template.

**Five paths analyzed (full list in CHAT.md turn 33):**
- PATH 1: always-retrieve, no tool-calling (chose this)
- PATH 2: ask infra to add `tools` + `tool_choice` to ChatCompletionRequest + pass into apply_chat_template + parse Qwen `<tool_call>` output tags -- proper long-term fix, blocked on infra
- PATH 3: use qwen3-vl-vllm (vLLM has `--enable-auto-tool-choice`) -- pf-gpu.sh says not to use it (ingestion-tuned)
- PATH 4: two-LLM-call router pattern -- +500-1000ms latency
- PATH 5: hacky in-stream tag parsing -- conflicts with streaming TTS

**PATH 1 implementation (current state):**
- Removed `@function_tool lookup_manual` from Assistant class.
- Added `on_user_turn_completed(turn_ctx, new_message)` hook on Assistant. Fires AFTER STT finalizes user turn, BEFORE LLM runs. Perfect injection point.
- Hook always calls `POST /retrieve` with the user's text (<150ms, infra team explicitly designed this for "callers can decide whether to use RAG context or fall back to pure chat").
- Gates injection on `max_score >= RAG_SCORE_THRESHOLD` (0.30 default, tunable env var):
  - Above threshold -> add a `system` message at end of chat_ctx: `"Relevant excerpts from indexed manuals (score X.XX): [source p.N]\n<text>\n\n[...]"`.
  - Below threshold -> skip injection, qwen3 answers as general chat.
- Publishes to `sophia.rag_result` topic either way (`mode: retrieve_injected` or `retrieve_skipped`) so the RagResultPanel shows scores and lets user tune the threshold from observed values.
- Rewrote system prompt: "When excerpts present, ground only in them and cite source + page. When no excerpts, treat as general chat. NEVER claim to have looked up a manual when no excerpts are present." Anti-hallucination clause is the critical bit.

**Concrete ask for infra to unlock PATH 2:**
```
1. Add to inference-server.py ChatCompletionRequest:
     tools: Optional[list[dict]] = None
     tool_choice: Optional[Union[str, dict]] = None
2. In generate_completion / generate_stream, pass tools to apply_chat_template:
     inputs = processor.apply_chat_template(
         qwen_messages, tools=params.tools, ...
     )
3. After generation, parse <tool_call>{json}</tool_call> tags from
   decoded text and return as OpenAI-style tool_calls in the response.
   Reference: Qwen3 tool-use docs at huggingface.co/Qwen/Qwen3-7B-Instruct
```
Once PATH 2 ships, we can swap back to @function_tool and skip per-turn /retrieve cost for general chat.

### Q20 (2026-05-19): How do we surface "what is happening on the server" in the React frontend (state pill, event log, per-stage latency metrics)?

Built all three levels from CHAT.md turn 30's priority list in one shot. Architecture: backend publishes JSON events via LiveKit's text-stream API on a dedicated topic, frontend subscribes via `useTextStream` hook.

**Backend (`sophia-agent/src/agent.py`):**

Three new module-level pieces:
- `AGENT_EVENTS_TOPIC = "sophia.agent_events"`
- `_BG_TASKS: set[asyncio.Task]` + `_fire(coro)` helper -- proper RUF006-clean fire-and-forget for sync event handlers (keeps strong task references in a set, removes them on done so GC doesn't kill in-flight publishes).
- `_publish_event(payload)` -- same shape as `_publish_rag_result` but on the agent-events topic, always stamps `ts` (epoch seconds).
- `_attach_event_publishers(session)` -- registers `@session.on(...)` listeners for 9 AgentSession event kinds (full list in agent.py).

Called once in `sophia_agent` entrypoint right after AgentSession ctor, before `session.start(...)`.

Event payload shapes published:

| Kind | Body |
|---|---|
| `agent_state` | `{old, new}` -- initializing/idle/listening/thinking/speaking transitions |
| `user_state` | `{old, new}` -- speaking/listening/away |
| `user_transcript` | `{text, is_final, language}` |
| `speech_created` | `{}` |
| `tools_executed` | `{}` (unused with current always-retrieve setup) |
| `false_interruption` | `{resumed: bool}` |
| `metrics` | `{metric_type, label, +scalar timing/count fields present on the variant}` |
| `error` | `{error: str, source: str (class name)}` |
| `close` | `{}` |

The metrics handler copies every scalar field that exists on the specific metric variant (STTMetrics/LLMMetrics/TTSMetrics/EOUMetrics/VADMetrics): `duration`, `ttft`, `ttfb`, `audio_duration`, `completion_tokens`, `prompt_tokens`, `total_tokens`, `end_of_utterance_delay`, `transcription_delay`, `on_user_turn_completed_delay`, `cancelled`, `inference_duration_total`, `inference_count`, `idle_time`. Only present + scalar values get serialised; complex objects skipped.

**Frontend (`agent-starter-react`):**

Two new components, both fixed-position overlays so they don't fight with the existing chat-transcript / RAG panel / control bar:

1. `components/agents-ui/agent-state-pill.tsx` (LEVEL 1) -- top-left small pill using `useAgent().state`. Color-coded background (grey/green/amber/sky) + pulsing dot for thinking/speaking. Zero subscription -- LiveKit framework already publishes agent state.

2. `components/agents-ui/agent-events-panel.tsx` (LEVEL 2+3) -- bottom-left scrolling log subscribed to `sophia.agent_events` via `useTextStream(EVENTS_TOPIC)`. Keeps most recent 50 events. Each row: timestamp (HH:MM:SS) + 5-char colored kind tag (AGENT/USER /TRANS/SPEAK/TOOLS/FALSE/METR /ERROR/CLOSE) + event-specific body. Header has a `metrics` checkbox toggle to mute the noisy metrics rows + collapse chevron.

Event body rendering examples:
- `listening → thinking` (state transitions)
- `final [en]: "what is the gv70 tire pressure"` (transcripts)
- `stt_metrics (openai.stt) dur=1.62 audio=2.34` (Whisper RTF)
- `llm_metrics ttft=0.31 dur=0.84 tokens_out=42` (qwen3 streaming)
- `tts_metrics ttfb=0.55 dur=1.10 audio=2.5` (Kokoro)
- `eou_metrics eou=0.03 trans=1.58` (turn detector + STT delay)

Wired into `agent-session-block.tsx` with three lines at the top of the `<section>`: `<AgentStatePill />`, `<AgentEventsPanel />`, `<RagResultPanel />`. Layout: three corners (top-left state, top-right RAG, bottom-left events), center stays clear for transcript.

**TypeScript catch we hit:** `JSON.parse(stream.text) as Omit<AgentEvent, 'id'>` triggered TS2345 because the parsed type couldn't be inferred as having `ts`/`kind`. Fix: parse as `Record<string, unknown>` and explicitly cast ts/kind with safe defaults.

**Unlocks per-stage latency observation without leaving the app:**
- Whisper RTF (duration / audio_duration on stt_metrics)
- qwen3 TTFT + token throughput (ttft + completion_tokens / duration)
- Kokoro TTFB + RTF (ttfb + duration / audio_duration)
- Turn detector EOU delay vs Whisper transcript delay (separate fields on eou_metrics)
- Error source identification (class name on error events: LLMError/STTError/TTSError)

All three panels typecheck clean. Pre-existing unrelated motion/react error in `view-controller.tsx` still there, unaffected.

### Q21 (2026-05-19): Full catalog of VAD + turn-handling tunable constants exposed in sophia-agent's agent.py

After playing with the orchestration knobs, refactored `agent.py` to surface every documented field from `silero.VAD.load()` + `EndpointingOptions` + `InterruptionOptions` + `PreemptiveGenerationOptions` + the MultilingualModel threshold + AEC warmup as named module-level constants at the top of the file. 24 total, all with defaults matching the framework's documented defaults so behaviour at start is unchanged. Migrated off the deprecated `turn_detection=` + `preemptive_generation=` kwargs to the unified `turn_handling=TurnHandlingOptions(...)` block via a `_build_turn_handling()` helper that handles TypedDict total=False conditional-include logic.

**Catalog (group → constant → default → observable signal in AgentEventsPanel):**

| Group | Constant | Default | Observable signal |
|---|---|---|---|
| VAD | `VAD_ACTIVATION_THRESHOLD` | 0.5 | fewer/more `agent_state listening→thinking` transitions |
| VAD | `VAD_DEACTIVATION_THRESHOLD` | None (auto) | mid-utterance false-end frequency |
| VAD | `VAD_MIN_SPEECH_DURATION` | 0.05s | cough/click triggering turns or not |
| VAD | `VAD_MIN_SILENCE_DURATION` | 0.55s | end-of-speech declaration timing |
| VAD | `VAD_PREFIX_PADDING_DURATION` | 0.5s | clipped-first-syllable in transcripts |
| VAD | `VAD_MAX_BUFFERED_SPEECH` | 60.0s | only matters for very long monologues |
| VAD | `VAD_SAMPLE_RATE` | 16000 | `vad_metrics.inference_duration_total` (8000 ~halves) |
| Endpointing | `ENDPOINTING_MODE` | "fixed" | per-turn delay adaptation vs constant |
| Endpointing | `ENDPOINTING_MIN_DELAY` | 0.5s | snappy vs patient responses |
| Endpointing | `ENDPOINTING_MAX_DELAY` | 3.0s | hard cap on waiting |
| Endpointing | `ENDPOINTING_ALPHA` | 0.9 | EMA smoothing (dynamic mode only) |
| Interruption | `INTERRUPTION_ENABLED` | True | barge-in on/off (demo mode = False) |
| Interruption | `INTERRUPTION_MODE` | None (auto) | "vad" vs "adaptive" (backchannel classifier) |
| Interruption | `INTERRUPTION_MIN_DURATION` | 0.5s | cough-vs-real-interrupt threshold |
| Interruption | `INTERRUPTION_MIN_WORDS` | 0 | STT-mode word count required to interrupt |
| Interruption | `INTERRUPTION_DISCARD_AUDIO_IF_UNINTERRUPTIBLE` | True | drop vs buffer audio during uninterruptible windows |
| Interruption | `INTERRUPTION_RESUME_FALSE` | True | resume prior utterance after false interrupt |
| Interruption | `INTERRUPTION_FALSE_INTERRUPTION_TIMEOUT` | 2.0s | silence-to-classify-as-false window |
| Interruption | `INTERRUPTION_BACKCHANNEL_BOUNDARY` | (1.0, 3.5) | adaptive-interrupt suppression around agent-speak boundaries |
| Preemption | `PREEMPTIVE_GENERATION_ENABLED` | True | LLM starts before formal turn-end |
| Preemption | `PREEMPTIVE_TTS_ENABLED` | False | TTS also speculative (most aggressive) |
| Preemption | `PREEMPTIVE_MAX_SPEECH_DURATION` | 10.0s | skip preemption for very long utterances |
| Preemption | `PREEMPTIVE_MAX_RETRIES` | 3 | per-turn cap on speculation re-runs; visible as `llm_metrics cancelled=true` |
| Turn detector | `TURN_DETECTOR_UNLIKELY_THRESHOLD` | 0.15 | conservatism of `eou_metrics.end_of_utterance_delay` |
| AEC | `AEC_WARMUP_DURATION` | 3.0s | "aec warmup active" log line + no early self-interrupt |

**Conditional-include logic (in `_build_turn_handling()`)**:
- `ENDPOINTING_ALPHA` only passed when mode is "dynamic" (otherwise ignored by framework but cleaner to omit).
- `INTERRUPTION_MODE = None` -> omit the key so framework auto-picks adaptive (if classifier model available) or vad (fallback).
- `INTERRUPTION_FALSE_INTERRUPTION_TIMEOUT` and `INTERRUPTION_BACKCHANNEL_BOUNDARY` accept None as a meaningful value (disables that feature), so we always pass them.
- `VAD_DEACTIVATION_THRESHOLD = None` -> omit the key in `silero.VAD.load()` to let Silero auto-pick (typically activation_threshold - 0.15).

**Source of truth:** `livekit/agents/voice/turn.py` (EndpointingOptions / InterruptionOptions / PreemptiveGenerationOptions / TurnHandlingOptions) + `livekit/plugins/silero/vad.py` (load classmethod) + `livekit/agents/voice/agent_session.py` (aec_warmup_duration kwarg).

**Experiment recipes per knob captured in CHAT.md turns 37-41.** Standard workflow: edit constant in agent.py → save (dev watcher reloads or Ctrl-C+restart) → hard-refresh browser → talk → observe vad_metrics / eou_metrics / llm_metrics / tts_metrics rows in the bottom-left AgentEventsPanel.

### Q22 (2026-05-19): How is AEC (acoustic echo cancellation) handled in sophia-agent? Three layers explained

User asked the right question. AEC works today, but the ACTUAL echo cancellation algorithm runs in the BROWSER, not in our agent. Three independent layers; we have Layer 1 + Layer 2 wired, Layer 3 explicitly skipped.

**LAYER 1 — Browser WebRTC AEC (the real worker)**
- Runs in the browser's audio capture pipeline via libwebrtc's AEC module.
- Subtracts the agent's speaker output from the user's mic input BEFORE the audio bytes leave the browser.
- Enabled by default via `getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}})`.
- `livekit-client`'s `AudioCaptureOptions` interface (verified in node_modules) defaults all three to true.
- `agent-starter-react` never overrides these → Sophia inherits all three.
- Modern browsers (Safari, Chrome, Firefox) all support this.
- This is what actually keeps the agent from interrupting itself in steady state.

**LAYER 2 — LiveKit framework warmup workaround**
- `aec_warmup_duration` on `AgentSession`. Default 3.0s, exposed as `AEC_WARMUP_DURATION` constant in agent.py.
- During the first N seconds of each session, IGNORE user audio for interruption purposes — because Layer 1's AEC is still calibrating its echo profile and might leak some echo into the mic stream.
- Visible in worker logs: `"aec warmup active, disabling interruptions for 3.00s"` at session start, `"aec warmup expired, re-enabling interruptions"` when the timer fires.
- NOT echo cancellation itself — purely a safety window so leaked echo doesn't trigger a false interruption of the agent's greeting.
- Set to None to disable (safe with headphones since there's no echo path at all, or with dedicated AEC hardware like USB conference mics).

**LAYER 3 — Server-side enhancement (NOT in sophia-agent)**
- Plugins that would take post-Layer-1 audio and apply additional noise suppression / residual-echo removal:
  - `ai-coustics` — LiveKit Cloud-locked, removed from sophia-agent's deps.
  - `DeepFilterNet 3` — Apache 2.0, OSS, parked in production plan.
  - `Silero noise suppression` — alternative OSS option.
- Sophia uses NONE of these today. Per the OSS migration plan: add DeepFilterNet 3 IF measured noise becomes a problem. Speculative until then.
- Symptoms that would prompt adding Layer 3: persistent residual echo after Layer 1+2, HVAC/fan noise causing false START_OF_SPEECH events, hollow/reverberant rooms, multi-speaker scenarios.

**Experiment to prove Layer 1 is the real worker:**
- Set `AEC_WARMUP_DURATION = None` (disables Layer 2 entirely).
- Use HEADPHONES — no echo path, agent never self-interrupts, proves Layer 1 wasn't needed.
- Switch to SPEAKERS, same setting. If agent STILL doesn't self-interrupt, that's Layer 1 working silently in the browser. If it DOES, that's Layer 1 calibration time you just bypassed.

For sophia-agent's typical industrial-technician-with-headset scenario, Layer 1 alone is plenty. Adding Layer 3 stays parked.

### Q23 (2026-05-19): Can two different users interact with sophia-agent simultaneously?

Yes, both ways. Both work today without code changes.

**Scenario A — two users SAME room, ONE shared Sophia.**
- Both browsers join `voice_assistant_room_XYZ`.
- Dispatcher spawns ONE agent worker subprocess for the room.
- That subprocess subscribes to ALL microphone tracks in the room (RoomIO).
- Both users hear the same Sophia replies (one TTS output track, distributed by the SFU to everyone in the room).
- Both users see the same RagResultPanel + AgentEventsPanel data because they subscribe to the same room's text-stream topics.
- Use case: two technicians on-site collaboratively asking Sophia about the same equipment.

**Scenario B — two users DIFFERENT rooms, TWO independent Sophias.**
- Each browser joins its own room name.
- Dispatcher spawns one subprocess per room. Total isolation.
- Each Sophia has its own chat_ctx, RAG hook, metrics.
- Use case: standard SaaS multi-tenancy.
- **This already happens by default** -- `agent-starter-react/app/api/token/route.ts` generates a random room name per page-load: `voice_assistant_room_${Math.floor(Math.random() * 10_000)}`. Open two browser tabs → two different rooms → two separate Sophias.

**To enable Scenario A** -- ~5-min frontend tweak to honor a query param:
```ts
// in app/api/token/route.ts
const roomName = req.nextUrl.searchParams.get('room')
              ?? `voice_assistant_room_${Math.floor(Math.random() * 10_000)}`;
```
Both browsers visit `http://localhost:3000/?room=demo` and land in the same room.

**How the agent distinguishes the two users in Scenario A:**
- `user_input_transcribed` event already carries `speaker_id: str | None` (per livekit/agents/voice/events.py).
- When two users speak, each transcript event includes which participant said it.
- The agent CAN tell who said what -- could update the system prompt to "You are talking to two people, address them by name when relevant" and pass speaker_id into LLM metadata.

**Caveats for Scenario A:**
- Overlapping speech: if both users talk simultaneously, Whisper transcribes the mixed audio. No per-speaker diarization in current STT pipeline. Solution would be track-by-track STT (each user's audio transcribed separately) — out of scope today.
- Shared chat context: qwen3 sees one merged chat_ctx. No per-user memory isolation. Privacy implications if user A asks something user B should not see.
- Shared RAG retrieval: every turn calls `/retrieve` against whatever was said. Both users' queries land in the same room's panel cards. Feature or bug depending on use case.
- Cold-fork latency: subsequent users joining new rooms each pay ~700ms subprocess cold-fork (`num_idle_processes=0` default). Parked cleanup.

### Q24 (2026-05-20): Why did the LLM say "I don't have any relevant manuals" when the RAG panel clearly showed retrieve_injected with tire-pressure chunks? Partial-relevance handling via system prompt tuning

User asked "Hello, what is the recommended tire pressure for GV70?". Frontend RagResultPanel showed `retrieve_injected` mode card with 3 chunks from GV70_Owners_Manual.pdf scoring 0.21 each, all explicitly discussing tire pressure (TPMS warning indicator on page B-8, "Check Tire Pressure" cluster Utility menu on page 8-8, etc.). Despite the chunks being clearly relevant AND visibly present in the panel, the LLM answered: "I don't have any relevant manuals in the indexed knowledge base to provide the recommended tire pressure for GV70."

**The chunks WERE injected.** The RagResultPanel showing `retrieve_injected` is dispositive proof: that mode tag is only set inside the `on_user_turn_completed` hook AFTER `turn_ctx.add_message(role="system", content=context_block)` executes. So the system message was definitely appended to chat_ctx before the LLM ran.

**The chunks ARE relevant.** They mentioned "tire pressure" explicitly, how to check it via the cluster Utility menu, the TPMS warning indicator. But they did NOT contain the specific recommended PSI value (which lives on the tire placard inside the driver's door, or possibly on a different page that didn't make the top-4 retrieval).

**Root cause: the LLM conflated two distinct cases in the original system prompt.** The prompt previously had two branches:
- "When excerpts present: ground in them, cite, if they don't contain the answer say so plainly, do not invent."
- "When no excerpts: NEVER claim to have looked up a manual, say you do not have anything relevant in the indexed knowledge base."

Qwen3-VL interpreted "excerpts don't contain the exact PSI value" as falling under "do not contain the answer" -> fell back to the "no excerpts" phrasing about "no anything relevant in the indexed knowledge base" instead of acknowledging the partially-relevant content. This is a common failure mode for instruction-tuned LLMs given a binary excerpts/no-excerpts framing.

**Fix: three-case partial-relevance handling in the system prompt.** Updated `Assistant.__init__` instructions block in `sophia-agent/src/agent.py` to explicitly distinguish:
1. Excerpts fully answer the question -> ground in them, cite source+page.
2. **Excerpts contain PART of the answer but not all -> SHARE what was found, NOTE what's missing, do NOT refuse.** Includes a concrete example response in the prompt: "The manual covers checking tire pressure via the cluster Utility menu (GV70 page 8-8), but the specific recommended pressure value isn't in the retrieved pages -- it's usually on the tire placard inside the driver's door."
3. Excerpts completely unrelated to the question -> say so directly and offer to help with what IS covered.

The "no excerpts" block stays separate and unchanged.

**Diagnostic for next session: if the new prompt works, the same question should produce something like** "The GV70 manual explains how to check tire pressure in the Utility menu (page 8-8) and describes the TPMS warning indicator (page B-8), but the specific recommended pressure value isn't in the retrieved pages -- it's typically on the placard inside the driver's door."

**Generalisation: this pattern matters for ANY RAG that returns retrieval scores in a "gray zone" (0.20-0.40 range).** With high-confidence chunks (0.5+) the LLM usually grounds correctly. With clearly-irrelevant chunks (< 0.15) the threshold gate filters them out before the LLM sees them. The dangerous middle ground is partially-relevant chunks that pass the threshold but don't contain the specific fact -- those need explicit "share-what-you-found" prompt scaffolding.

**Side note about RAG_SCORE_THRESHOLD.** User lowered it from 0.30 default to 0.10 because real matches in this corpus score only 0.21 (gray zone). Keep at 0.10 until we observe higher-scoring hits OR investigate sophia-spatial-ai's `retrieval_mode` / `answer_mode` parameters per Q15. The "Thank you" general-chat turn correctly got `retrieve_skipped` even with threshold 0.10, so the gate is still useful at the very-low end.

**Side note about chunk-text rendering.** As part of this debugging round, finally added the actual chunk text to each hit card in the RagResultPanel (Option A, source-grouped, with 180-char truncation + "show more" expand button). The data was already in the payload; the panel just wasn't rendering it. New `HitChunk` component in `agent-starter-react/components/agents-ui/rag-result-panel.tsx`. RagHit interface extended with text/snippet/content/page_content fallback fields (same multi-name extraction the backend hook uses, since we still don't know which exact field name sophia-spatial-ai uses).

### Q25 (2026-05-20): How do we deploy Sophia voice agent to XREAL One Pro + Beam Pro + Eye? Full architecture + phased build plan

User raised the PROJECT'S ORIGINAL DEPLOYMENT GOAL (per `CLAUDE.md` at project root): XREAL glasses tethered to an Android device, with Sophia running on the backend. User confirmed three pieces of hardware in hand from their company: XREAL One Pro (glasses), XREAL Beam Pro (Android compute), XREAL Eye (first-person camera).

**Hardware-to-role mapping:**

| Device | Role | Capabilities for Sophia |
|---|---|---|
| XREAL One Pro | Display + audio I/O | OLED lens displays, stereo speakers, mic, ~57° FOV, 3DoF spatial tracking (X1 chip), USB-C tether |
| XREAL Beam Pro | Compute (Android) | Full Android (NebulaOS), cellular + WiFi, runs APKs. Replaces the "Android phone" role from original plan. THIS IS WHERE OUR NEW APP LIVES. |
| XREAL Eye | Camera | Snap-on first-person camera. Feeds sophia-spatial-ai's `/image-question` endpoint for vision RAG (industrial-technician use case: "what is this part") |

**Key insight: the entire backend we built stays as-is.** The Beam Pro is just a NEW CLIENT replacing the browser. The same livekit-server + sophia-agent + RAG hook + AWS models work without changes. The text-stream topics we publish (`sophia.rag_result`, `sophia.agent_events`) are language-agnostic -- subscribed via livekit-android's APIs the same way the React frontend's `useTextStream` subscribes.

**Architecture -- LOCAL DEV (today's stack + glasses):**

```
XREAL One Pro (mic, speakers, displays, optional Eye camera)
  ↕ USB-C
XREAL Beam Pro (Android)
  └── NEW Sophia Companion App (Kotlin + livekit-android + NRSDK)
       ↕ WiFi to laptop
Mac (livekit-server :7880 + token_mint :8001 + sophia-agent worker + pf-gpu.sh)
       ↕ kubectl port-forward
AWS EKS (whisper / qwen3 / kokoro / sophia-spatial-ai)
```

**Architecture -- PRODUCTION:** same shape, Beam Pro hits an EC2 SFU URL instead of laptop; models stay in same VPC. Zero agent code changes.

**Stack pick (recommended): Native Android Kotlin + NRSDK.**
- `livekit-android` (Apache 2.0) -- official LiveKit Android SDK, identical Room/Track/DataChannel APIs to the web SDK.
- NRSDK -- XREAL's SDK, has both Unity and native Android bindings. Native is lighter for a 2D UI overlay. Unity recommended only if doing complex 3D AR (spatial models pinned to real objects).
- Single APK, `adb install` for dev, internal-app distribution for prod.

**Web-frontend → Beam-Pro-app component mapping:**

| Web (already built) | Android equivalent |
|---|---|
| `AgentStatePill` (useAgent state) | NRSDK panel + livekit-android Room state listener |
| `AgentEventsPanel` (useTextStream "sophia.agent_events") | Kotlin TextStream handler on same topic |
| `RagResultPanel` (useTextStream "sophia.rag_result") | Kotlin TextStream handler on same topic |
| `AgentChatTranscript` (useSessionMessages) | livekit-android transcript API |
| `getUserMedia` browser mic | Android AudioRecord via livekit-android |
| Browser WebRTC AEC | Android WebRTC AEC (same libwebrtc) -- even cleaner because no acoustic feedback through room when wearing glasses headset |

**Audio routing detail:** When XREAL One Pro connects via USB-C, Android sees it as a USB-Audio class device. Default Android audio routing should switch input to glass mic and output to glass speakers. If not, force via `AudioManager.setCommunicationDevice(...)`. livekit-android uses AudioManager internally and will pick up the active route.

**Display: head-locked 2D panel (NOT spatial 3D).** Simple UI overlay ~2 meters in front of user: state pill row, live transcript row, agent response row, RAG citation row. NRSDK supports head-locked / world-locked / hand-locked positioning; head-locked is right for a voice agent (UI always visible while user works on equipment).

**XREAL Eye → vision RAG (Phase 3):**
- **Pattern A (always-on video track):** Eye camera published as low-res video track; agent subscribes when needed. Higher bandwidth, fresher visual context.
- **Pattern B (snapshot-on-demand, RECOMMENDED):** Explicit user gesture (volume key tap, voice "look at this") triggers a single frame capture, JPEG POST to `/image-question`, answer injected as context. Lower bandwidth, clearer UX (user knows when Sophia is "looking"). Integrates naturally alongside our existing `on_user_turn_completed` text-RAG hook -- add a separate `look_at()` trigger.

**Phased build plan (~2 weeks total for usable):**

- **Phase 1 (~2-3 days)** -- Voice-only on Beam Pro. Android Studio project, livekit-android, hardcoded room+token from laptop's token_mint, mic capture from glasses, speaker playback. Goal: hear Sophia in your ears, talk back, while wearing the glasses. No UI overlay yet.
- **Phase 2 (~3-5 days)** -- AR UI overlay via NRSDK. Head-locked panel showing transcript + state + RAG sources. Subscribes to same text-stream topics as web frontend.
- **Phase 3 (~2-4 days)** -- XREAL Eye + vision RAG. Snapshot-on-demand pattern. POST to `/image-question`.
- **Phase 4 (~1-2 days)** -- Polish, settings, error recovery, internal-distribution build.

New directory `sophia-glasses/` parallel to `sophia-agent/` planned to hold the Android codebase.

**External blockers to verify BEFORE Phase 1 starts:**
1. NRSDK access from developer.xreal.com (free for non-commercial, paid tiers for commercial -- verify company's plan).
2. Beam Pro USB-debugging enabled.
3. Laptop reachable from Beam Pro on WiFi. **Watch out**: livekit-server currently advertises `nodeIP: 100.69.34.194` which is the laptop's Tailscale 100.x address. Either (a) install Tailscale on Beam Pro too, or (b) restart livekit-server with `--node-ip <laptop-LAN-IP>` so Beam Pro can reach it over plain WiFi.
4. NRSDK + livekit-android version compatibility check (both need API level 26+ which Beam Pro is fine for).
5. AWS reachability NOT needed from Beam Pro -- chain is Beam Pro → laptop SFU → laptop agent → kubectl port-forward → AWS. The port-forward stays on the laptop.

**Two open strategic Qs for user before scaffolding:**
- Q1: native Kotlin vs Unity (recommendation: Kotlin -- simpler for 2D UI; Unity only if doing complex 3D AR later)
- Q2: Phase 1 voice-only first vs all-at-once (recommendation: Phase 1 first -- "hear Sophia in your ears through the glasses" is the milestone that proves end-to-end works)

### Q26 (2026-05-21): Setting up the XREAL Beam Pro development environment -- prerequisites, networking, and the wireless-adb gotcha

User started the XREAL build today (Phase 1 of the 4-phase plan in Q25). Captured here is the concrete dev-env setup that worked, including a couple of gotchas worth recording.

**Hardware decisions made:**
- Unity + NRSDK Unity (vs native Kotlin/Android). Reason: future-proof for 3D AR overlays beyond Phase 2.
- Phased approach (Phase 1 voice-only first, no UI yet). Reason: prove audio loop works through glasses before adding NRSDK complexity.

**Stack versions:**
- Unity Hub: latest from `unity.com/download` (just a launcher, ~200MB)
- Unity Editor: **6.3 LTS (6000.3.16f1)**. XREAL SDK 3.x docs say "Unity 2021.3.X and above" so 6.3 LTS is well above minimum and is a proper LTS line.
- Android modules installed alongside Editor: **Android Build Support** (parent) + **OpenJDK** (sub) + **Android SDK & NDK Tools** (sub). NOT iOS/tvOS/visionOS/Linux/Mac/Web/Windows or any dedicated server modules.
- XREAL SDK: **3.1.0**. Distributed as a UPM tarball (`com.xreal.xr.tar`) which extracts to a folder containing `package.json` -- NOT the old NRSDK `.unitypackage` format. Install later via Package Manager > Install from disk.

**Network setup -- Tailscale is the magic:**
- Mac's Tailscale IP: `100.69.34.194`. This is what `livekit-server --dev --node-ip 100.69.34.194` already advertises (was set previously when the user was on Tailscale-only network).
- Beam Pro's Tailscale IP: `100.69.32.120` (different /24 from Mac because Tailscale's overlay isn't strict subnet but works fine over CGNAT).
- Verified from Beam Pro shell:
  ```
  adb shell
  curl -v http://100.69.34.194:7880
  ```
  Returns HTTP 200 with "OK" body -- the livekit-server's tiny landing endpoint. Proves Beam Pro can hit the SFU over Tailscale.
- **CRITICAL TAKEAWAY:** if Tailscale is already on both ends, the `--node-ip <LAN-IP>` restart from Q13's original recommendation is NOT NEEDED. The existing Tailscale-advertised nodeIP works. Saves a step.

**adb setup on Beam Pro:**
- Settings > About > tap Build Number 7 times to unlock Developer Options.
- Settings > Developer Options > USB Debugging ON.
- Plug into Mac via USB-C. On the Beam Pro, swipe down the notification shade, tap the "USB charging this device" notification, change mode to "File Transfer" (MTP) -- this is what makes the "Allow USB debugging from this computer" dialog appear on the Beam Pro screen.
- On Mac: `adb devices` should now show the Beam Pro by its serial (e.g. `RHLM56L118630F`).

**Wireless adb -- mandatory once glasses are connected:**

The Beam Pro's USB-C port is a SHARED port: it carries data (for adb / file transfer) AND DisplayPort Alt Mode (for driving the glasses). It can't do both at once. So when actively testing with the glasses, USB adb is unavailable -- you need wireless adb over Tailscale instead.

Setup sequence:
```
# Step 1 -- while Beam Pro is on USB to Mac:
adb tcpip 5555

# Step 2 -- unplug USB. Plug glasses into Beam Pro's USB-C.
# Step 3 -- on Mac:
adb connect 100.69.32.120:5555    # Beam Pro's Tailscale IP, port 5555
adb devices                       # should list the Beam Pro at that IP

# Now adb works over the network. Glasses keep working on USB-C.
# To revert later: `adb usb` (Beam Pro must be plugged in via USB for this command).
```

This is a one-time setup per Beam Pro reboot -- if you reboot the Beam Pro, you have to re-do `adb tcpip 5555` over USB.

**Token-mint reachability:** sophia-agent's `token_mint.py` runs at `http://localhost:8001/token` on the Mac, but since the Beam Pro reaches the Mac via Tailscale at `http://100.69.34.194:8001/token`, the same IP works for the token endpoint too. The Unity app's `SophiaConfig.tokenEndpoint` will be set to that URL.

**Pre-flight what-could-go-wrong checklist** (we hit none of these but worth recording):
- USB-C cable was charge-only (no data lines) -- swap cables, retry. Typical sign: no notification appears on Beam Pro when plugged in.
- Beam Pro plugged into glasses while expecting USB data to Mac -- unplug glasses first, or use wireless adb.
- Mac firewall blocking port 7880 -- System Settings > Network > Firewall. We didn't hit this; standard Tailscale connections aren't typically firewalled.
- Tailscale not running on Beam Pro -- check Beam Pro Settings for Tailscale app, run `adb shell tailscale status` or check that the Beam Pro's IP starts with `100.x.x.x`. If not, install Tailscale on Beam Pro OR use the Mac's actual WiFi LAN IP via `--node-ip <LAN-IP>`.

**P1-1 (sophia-glasses/ scaffolding) DONE:**

Three files created at project root, no Unity code yet:
- `sophia-glasses/README.md` -- project positioning, stack, phased plan
- `sophia-glasses/AGENTS.md` -- modularity + naming + text-stream-topic + network conventions for any future Claude session
- `sophia-glasses/.gitignore` -- standard Unity exclusions (Library/, Temp/, builds, OS junk)

Conventions baked in:
- This is a CLIENT only -- backend stays untouched. Don't change backend topic names from here.
- Default room semantics: UUID-suffixed per launch (Scenario B isolation), `SophiaConfig.roomName` override for shared rooms (Scenario A).
- Text-stream topics MUST match backend publisher: `sophia.rag_result`, `sophia.agent_events`, `lk.transcription`.
- Single ScriptableObject for runtime config (`SophiaConfig.asset`).
- Modular MonoBehaviours: one component, one data source, one panel.

**P1-2 next (USER's job, ~5 min):** create the Unity project from Hub at `sophia-glasses/unity/` with template "3D (URP)" and Editor "Unity 6.3 LTS". Full instructions in `sophia-agent/CHAT.md` turn 53.

**P1-3 onwards (CLAUDE's job, after P1-2 ack):** add LiveKit Unity SDK via UPM git URL, import XREAL SDK 3.1.0 from disk, switch build target to Android, create SophiaConfig + first scene + SophiaConnection script, build APK, install on Beam Pro, verify voice loop end-to-end through the glasses.


### Q27 (2026-05-21): Phase 1 of XREAL build -- backend tweak + Unity project scaffolding + LiveKit Unity SDK API quirks

Full Phase 1 walkthrough captured here for next-session pickup. Sophia-agent backend got one necessary tweak; sophia-glasses Unity project got scaffolded with the bare-minimum voice-loop scripts; we hit and resolved 4 distinct dependency/API issues with the LiveKit Unity SDK that aren't documented in their README.

**Backend tweak to `sophia-agent/src/token_mint.py`:**
- Added optional `agent_name: Optional[str] = "sophia-agent"` field to `TokenRequest`.
- When set (default), attaches a `RoomConfiguration(agents=[RoomAgentDispatch(agent_name=...)])` to the JWT via `AccessToken.with_room_config(...)`.
- Why needed: sophia-agent's worker registers with `agent_name="sophia-agent"` (explicit dispatch mode). Without this addition, a non-web client (Unity glasses) would join a room and the agent worker would never auto-dispatch into it. The web frontend has its OWN token route (in agent-starter-react) that already does this; our token_mint didn't.
- Web frontend unaffected (uses its own token route).
- Verified `livekit.api.RoomConfiguration` and `RoomAgentDispatch` classes exist; `AccessToken.with_room_config(...)` is the public method.
- ruff format + check clean. User restarts token_mint to pick up.

**sophia-glasses/ directory scaffolded:**
- README.md (positioning, stack, phased plan)
- AGENTS.md (modularity + naming + text-stream-topic + network conventions)
- .gitignore (Unity-standard exclusions: Library/, Temp/, Logs/, builds, *.apk)
- unity/ subdirectory created by user via Unity Hub: Editor Unity 6.3 LTS, template "3D (URP)" (Universal Render Pipeline -- the "Universal 3D" template with SRP badge IS URP, despite the badge looking different).

**LiveKit Unity SDK install + 4 quirks NOT in the README:**

1. **Google.Protobuf dependency missing.** The SDK is auto-generated from `.proto` files and uses `Google.Protobuf` runtime types (IMessage, IBufferMessage, MessageParser<T>) but doesn't bundle the protobuf library. Installing via the git URL gets ~3000 errors like "type or namespace name 'Google' could not be found". README doesn't mention it.
    - Standard fix: NuGetForUnity package + install Google.Protobuf via that.
    - BUT: errors put Unity in Safe Mode, which HIDES custom menus (including NuGet's), making the standard fix a chicken-and-egg problem.
    - Workaround: drop `Google.Protobuf.dll` (netstandard2.0, version 3.27.4) directly into `Assets/Plugins/`. Bypasses Safe Mode entirely. Downloaded from `https://www.nuget.org/api/v2/package/Google.Protobuf/3.27.4` (just a zip; .nupkg unzips to `lib/netstandard2.0/Google.Protobuf.dll`).

2. **`Room.Connect(string, string, RoomOptions)` requires the third arg.** README quickstart shows `room.Connect(url, token)` with two args; ACTUAL signature requires `RoomOptions options` -- no two-arg overload exists. Workaround: `_room.Connect(url, token, new LiveKit.RoomOptions())`.

3. **`RoomOptions` is ambiguous.** Both `LiveKit.RoomOptions` and `LiveKit.Proto.RoomOptions` exist. When `using LiveKit.Proto;` is present (which we need for `TrackPublishOptions` + `TrackSource`), referencing `new RoomOptions()` is an ambiguity error. Fix: fully-qualify as `new LiveKit.RoomOptions()`.

4. **`ConnectInstruction` and `PublishTrackInstruction` have only `IsError` (bool), NO `Error` (string).** README example showed `connectOp.Error` -- doesn't exist. The instruction classes expose only `IsDone` + `IsError`; detailed error messages land in Unity Console via the SDK's own logger, not as instance properties. Workaround: drop the `.Error` access, just log a generic failure message.

5. **`TextStreamReader.ReadAllInstruction` exposes `.Text`, NOT `.ReadAllText`.** README naming was wrong. Verified in `TextDataStream.cs:109`.

6. **`LocalAudioTrack` has no `Stop()` method.** The sealed class extending Track + ILocalTrack + IAudioTrack doesn't expose Stop. Tearing down `MicrophoneSource` (which DOES have `Stop()`) plus `Room.Disconnect()` is enough -- track is GC'd on reference drop.

**`TrackPublishOptions` + `TrackSource` live in `LiveKit.Proto` namespace** (auto-generated from protos), not the top-level `LiveKit` namespace. Need `using LiveKit.Proto;` to reference them unqualified. `TrackSource` enum values use SnakeUpperCase-converted PascalCase: `SourceMicrophone = 2`, `SourceCamera = 1`, etc.

**Final working SophiaConnection.cs API patterns** (Phase 1 reference):

```csharp
using LiveKit;
using LiveKit.Proto;  // for TrackPublishOptions, TrackSource

// Connect:
var connectOp = _room.Connect(url, token, new LiveKit.RoomOptions());
yield return connectOp;
if (connectOp.IsError) { /* log without details */ }

// Publish mic:
var micSource = new MicrophoneSource(micName, gameObject);
var micTrack = LocalAudioTrack.CreateAudioTrack("sophia-mic", micSource, _room);
var pubOpts = new TrackPublishOptions { Source = TrackSource.SourceMicrophone };
var pubOp = _room.LocalParticipant.PublishTrack(micTrack, pubOpts);
yield return pubOp;
if (pubOp.IsError) { /* log without details */ }
micSource.Start();

// Subscribe to remote audio:
_room.TrackSubscribed += (track, pub, participant) => {
    if (track is RemoteAudioTrack audio) {
        var src = gameObject.AddComponent<AudioSource>();
        new AudioStream(audio, src);  // hold via component lifetime
    }
};

// Text-stream subscribe:
_room.RegisterTextStreamHandler("sophia.rag_result", (reader, identity) =>
    StartCoroutine(HandleReader(reader, identity)));

// Inside the coroutine:
var readAll = reader.ReadAll();
yield return readAll;
var text = readAll.Text;  // NOT ReadAllText
```

**Status at end of 2026-05-21:**
- ✅ All pre-flight checks green
- ✅ sophia-glasses/ directory scaffolded
- ✅ Unity 6.3 LTS project created (URP template) at sophia-glasses/unity/
- ✅ LiveKit Unity SDK installed (git URL)
- ✅ XREAL SDK 3.1.0 installed (Install from disk pointing at ~/Downloads/package/)
- ✅ Google.Protobuf.dll dropped at Assets/Plugins/
- ✅ SophiaConfig.cs + SophiaConnection.cs written, all compile errors fixed, Console CLEAR
- ✅ token_mint.py extended with agent dispatch
- PENDING -- user actions in Unity Editor:
  - P1-4a: switch build target to Android (File > Build Profiles > Android > Switch Platform)
  - P1-4c: create SophiaConfig.asset in Project panel (right-click Assets/Settings > Create > Sophia > Config)
  - P1-4d: create empty GameObject "SophiaConnection" in scene, Add Component > SophiaConnection, drag SophiaConfig.asset onto Config slot
  - P1-4e (optional): Play in Editor to sanity-check voice loop from Mac itself before APK
- PENDING -- Claude tasks:
  - P1-7: Android manifest permissions (RECORD_AUDIO + INTERNET) -- usually Unity auto-adds, verify in Player settings
  - P1-8: build APK
  - P1-8b: adb install on Beam Pro
  - P1-9: write RUNBOOK.md for sophia-glasses
