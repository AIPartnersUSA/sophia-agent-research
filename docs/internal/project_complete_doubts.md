# project_complete_doubts.md

Running log of doubts about the Sophia project and LiveKit components, with short accurate explanations + examples. Numbered monotonically. Format: `## Q<n> (YYYY-MM-DD): <question>` followed by the answer.

For deep LiveKit framework Q&A see `livekit_doubts.md` (62 items). This file is for "I'm reading the architecture and have a clarifying question" — shorter and more focused on understanding what's already there.

---

## Q1 (2026-06-01): The livekit-server deployment on EC2 — does it really just need a docker-compose file, since we only use the image?

**Yes, that's all it needs.** No Dockerfile, no build step, no custom code. Three pieces total:

1. **Docker Compose service block** (declares the image, network, volumes, command, restart policy).
2. **The image pulled from Docker Hub** (`livekit/livekit-server:latest` — already contains the compiled Go binary + everything it needs).
3. **A config file mounted in** (`livekit.prod.yaml` with port settings, API key/secret, RTC config).

Our actual block from docker-compose.yml on EC2:

```yaml
livekit-server:
  image: livekit/livekit-server:latest
  network_mode: host
  volumes:
    - ./sophia-agent/infra/livekit.prod.yaml:/etc/livekit.yaml:ro
  command: --config /etc/livekit.yaml --node-ip 3.227.63.49
  restart: unless-stopped
```

That's the entire deployment of the SFU. `docker compose up -d livekit-server` is the only command needed to start it.

### What each key in the service block does

- **`livekit-server`** (the top-level key, NOT a Docker keyword) — this is the SERVICE NAME you chose. It's used as: (a) the identifier when you run `docker compose <command> livekit-server` (e.g. `docker compose logs livekit-server`); (b) the DNS hostname other containers can use to reach this one IF they were on the same docker network (irrelevant for us because we use host networking — but normally `token-mint` could reach the SFU at `http://livekit-server:7880`).

- **`image: livekit/livekit-server:latest`** — which Docker image to pull and run. The `:latest` tag means "whatever upstream tags as latest right now." For production you'd usually pin a specific version like `livekit/livekit-server:v1.7.2` so a new upstream release can't surprise you. Format is `<repository>/<image>:<tag>`. Docker Hub is the default registry.

- **`network_mode: host`** — gives the container direct access to the host's network namespace. Without this it'd be on Docker's default bridge network and you'd need `ports:` declarations. Full rationale in Q2.

- **`volumes:`** — bind-mounts files or directories from the host filesystem INTO the container's filesystem. Each entry is `<host-path>:<container-path>:<options>`. Our line `- ./sophia-agent/infra/livekit.prod.yaml:/etc/livekit.yaml:ro` means: take the file `livekit.prod.yaml` on the host (relative to docker-compose.yml location) and make it visible inside the container at `/etc/livekit.yaml`, in `ro` (read-only) mode. Without this mount, that path wouldn't exist inside the container at all — the LiveKit binary would have nothing to load. **This is HOW the config gets into the container.** The container always sees `/etc/livekit.yaml`; we choose where the actual file lives on the host.

- **`command:`** — overrides the default CMD that the Docker image's Dockerfile baked in. Our value `--config /etc/livekit.yaml --node-ip 3.227.63.49` is two CLI arguments to the livekit-server binary (the image's ENTRYPOINT is `livekit-server`, so these append to it). Breaking it down:
  - `--config /etc/livekit.yaml` — tells the LiveKit binary to load its config from this path. This is the path INSIDE the container (where we mounted our config via `volumes`).
  - `--node-ip 3.227.63.49` — tells the SFU what IP to advertise in WebRTC candidates. Necessary because the SFU can't always detect its own public IP correctly (e.g. behind a NAT, on a cloud instance with separate public/private IPs). Without this flag the SFU might advertise the private IP `10.20.1.90` and clients couldn't reach it.

  **Without these CLI args, the SFU would use its built-in defaults — which would be wrong for our deployment** (wrong config path, no node-IP override).

- **`restart: unless-stopped`** — the restart policy. Container automatically restarts if it crashes OR if the Docker daemon restarts OR if the EC2 reboots. The ONLY thing that stops it is an explicit `docker compose stop livekit-server` or `docker compose down`. Other valid values: `no` (default — no auto-restart), `on-failure` (only restart on crash, not on normal exit), `always` (restart even if explicitly stopped). For a production-ish always-on service, `unless-stopped` is the right choice.

### About the three .yaml files (your "I see livekit.prod.yaml.example AND livekit.yaml locally" confusion)

You actually have THREE related yaml files in the project, for THREE different environments. They're easy to confuse — here's the map.

| File path | Environment | In git? | What it does |
|---|---|---|---|
| `sophia-agent/infra/livekit.yaml` | LOCAL DEV (your Mac) | Yes | Config used by `livekit-server --config infra/livekit.yaml --dev` when running the SFU natively (via `brew install livekit-server`) for local dev. References localhost / Tailscale IPs. |
| `sophia-agent/infra/livekit.prod.yaml` | SHARED EC2 (production-ish) | **No (gitignored)** | The REAL production config with the actual API key + secret inline. Lives ONLY on EC2 at `/workspace/avinash/sophia/sophia-agent/infra/livekit.prod.yaml`. Mounted into the docker container via the `volumes:` key. |
| `sophia-agent/infra/livekit.prod.yaml.example` | Documentation only | Yes | TEMPLATE that documents the schema of `livekit.prod.yaml` with placeholder values + `openssl rand` commands. Anyone setting up a fresh EC2 copies this to `livekit.prod.yaml` and fills in real values. Created 2026-06-01 as part of the secrets-template work. |

So the relationship:
- `livekit.yaml` (local dev) and `livekit.prod.yaml` (EC2) are TWO DIFFERENT runtime configs for two different environments.
- `livekit.prod.yaml.example` is the GIT-TRACKED documentation of what `livekit.prod.yaml` should look like. The `.example` and the real `.prod.yaml` are sibling files; the `.example` exists so you don't have to remember the schema from scratch.

The docker-compose.yml on EC2 references `livekit.prod.yaml` (the real one). It does NOT reference `livekit.prod.yaml.example` — that file is purely for humans to read when setting up.

In your local Mac, you have `livekit.yaml` (for local dev) and `livekit.prod.yaml.example` (the committed template) — but you do NOT have `livekit.prod.yaml` because that file lives only on EC2 and contains secrets. That's the gitignored split working correctly.

### Verifying what's ACTUALLY running on EC2 (don't trust file paths alone)

To prove which compose file launched the running SFU and which yaml file it mounts, inspect the running container directly:

```bash
ssh sophia-gpu
docker inspect sophia-livekit-server-1 | grep -E '(Source|Destination|Cmd|config_files)'
```

Output (verified 2026-06-01):

```
"Source": "/home/ubuntu/workspace/avinash/sophia/sophia-agent/infra/livekit.prod.yaml"
"Destination": "/etc/livekit.yaml"
"com.docker.compose.project.config_files": "/home/ubuntu/workspace/avinash/sophia/docker-compose.yml"

# command args:
["--config", "/etc/livekit.yaml", "--node-ip", "3.227.63.49"]
```

Reading that output:
- `config_files` label confirms the WORKSPACE-ROOT `docker-compose.yml` (at `/home/ubuntu/workspace/avinash/sophia/docker-compose.yml`) is the one Docker Compose used to launch this container.
- Volume `Source` is the REAL `livekit.prod.yaml` (with the actual API key + secret inline), `Destination` is where the container sees it (`/etc/livekit.yaml`).
- Command args confirm `--node-ip 3.227.63.49` (the public EC2 IP), no `--dev` flag.

So the SFU on EC2 is using `livekit.prod.yaml` with the REAL production keys. Not `livekit.yaml`, not `--dev` mode.

### Why this verification matters (historical confusion we hit 2026-06-01)

The repo used to have TWO `docker-compose.yml` files:
1. `/workspace/avinash/sophia/docker-compose.yml` (workspace root) — the PROD compose, mounting `livekit.prod.yaml`, `--node-ip 3.227.63.49`. **Active.**
2. `sophia-agent/infra/docker-compose.yml` — a LOCAL DEV compose for running the SFU in Docker on a Mac, mounting `livekit.yaml`, `--dev`, `--node-ip 127.0.0.1`. **Never used on EC2.**

Reading the second file led us to falsely conclude the EC2 was using devkey/devsecret — wrong, that file was authored for Mac dev (and was never the canonical local-dev path anyway because RUNBOOK.md uses native `brew install livekit-server` per the macOS mDNS bug in livekit_deployment.md Q13).

**The Mac-dev compose was DELETED from the repo on 2026-06-01** (commit `a7ac391`) so this confusion can't happen again. Only one compose file exists now: the workspace-root one, and `docker inspect` confirms it's what's running.

Rule of thumb: when in doubt about which file is mounted into a running container, `docker inspect` is authoritative. File presence in the repo doesn't mean a container is using it — the launching compose file (recorded as a label) and the actual mount Source path are what matter.

### What's NOT in the docker-compose.yml but the deployment needs

- **AWS Security Group ingress rules** for ports 7880 (TCP signal), 7881 (TCP fallback), 50000-60000 (UDP media). Without these, the container starts fine but no client can reach it from outside the EC2. Managed via Terraform in the `AIPartnersUSA/aws-infra` repo, not via docker-compose.
- **The livekit.prod.yaml file itself** — gitignored, lives only on EC2. Schema documented in `sophia-agent/infra/livekit.prod.yaml.example`.

### Compare with the other two services

`token-mint` and `agent-worker` in the same compose file have `build: { context: ..., dockerfile: ... }` instead of `image:` because we wrote CUSTOM Python code for them — those need to be compiled into images at deploy time. The SFU has ZERO custom code so we just use the prebuilt upstream image.

---

## Q2 (2026-06-01): Why `network_mode: host` for livekit-server in the compose file? Why not the default bridge network like a normal Docker app?

**Two reasons, both forced by WebRTC.**

### Reason 1 — WebRTC needs a wide UDP port range

WebRTC media (the actual audio/video packets) flows over UDP. The SFU listens on a configured range — in our case `50000-60000` UDP, which is 10,001 ports. With Docker's default bridge networking, you'd need to publish every port individually:

```yaml
# What it would look like WITHOUT host networking (DON'T do this):
livekit-server:
  image: livekit/livekit-server:latest
  ports:
    - "7880:7880/tcp"
    - "7881:7881/tcp"
    - "50000-60000:50000-60000/udp"   # 10,000 UDP ports!
```

Technically possible, but Docker creates an iptables rule per published port → slow startup, heavy CPU during NAT, and the underlying network stack struggles at scale.

### Reason 2 — The WebRTC "candidate IP" problem (the bigger reason)

WebRTC clients establish peer connections by exchanging "ICE candidates" — IP:port pairs the SFU advertises as reachable. With bridge networking, the SFU sees its OWN IP as the container's internal IP (e.g. `172.17.0.2`). It advertises `172.17.0.2:7880` to clients. Clients on the public internet try to connect to `172.17.0.2` → fails (private address).

The SFU has no way to know it's behind Docker's NAT layer. You can work around this with `--node-ip 3.227.63.49` (force the advertised IP), but then the media packets still have to traverse Docker NAT, adding latency.

### What `network_mode: host` solves

The container shares the host's network namespace directly:
- Container's `localhost` IS the host's `localhost`.
- Container binds ports directly on the host interface (`3.227.63.49:7880`).
- No Docker NAT layer, no port publishing.
- SFU sees the host's real public IP and advertises it correctly.
- Media packets flow directly between the host and the remote client, no Docker hop.

The cost: host networking gives the container the same network access as the host (no isolation). For a stock LiveKit binary from Docker Hub, this is acceptable. For arbitrary user code, it'd be a security concern.

### Side note — agent-worker also uses host networking, for a different reason

The agent-worker also has `network_mode: host` in our compose file, but the reason is loopback efficiency. The worker connects to the SFU as a participant. With host networking, the worker uses `ws://localhost:7880` (loopback inside the host kernel) instead of going out the public interface and back through the AWS Security Group. Faster + doesn't depend on SG state. See Problem 6 in `mvp_deployment_shared_ec2.md`.

### Production-grade equivalent (k8s)

In Kubernetes you'd use `hostNetwork: true` on the Pod spec, with the SFU running as a DaemonSet or single-replica Deployment pinned to a labeled node. Same outcome. See `HANDOFF.md` for the production migration discussion.

---

## Q3 (2026-06-01): How is token-mint deployed? Same as livekit-server (just a compose file + image)?

**No — token-mint is different from livekit-server in one big way: there's no prebuilt image to pull. We wrote custom Python code, so Docker has to BUILD the image at deploy time from a Dockerfile.** Four pieces total instead of three:

1. **Docker Compose service block** (declares the build instructions, ports, env file, restart policy).
2. **The Dockerfile** (`sophia-agent/Dockerfile.token-mint`) that defines how to build the image.
3. **The application code** (`sophia-agent/src/token_mint.py` + Python deps in `pyproject.toml` + `uv.lock`).
4. **The `.env.production` file** with secrets, loaded into the container at start via `env_file:`.

Our actual block from the workspace-root docker-compose.yml on EC2:

```yaml
token-mint:
  build:
    context: ./sophia-agent
    dockerfile: Dockerfile.token-mint
  ports:
    - "8001:8001"
  env_file:
    - ./sophia-agent/.env.production
  restart: unless-stopped
```

The build step happens once on first `docker compose up -d token-mint` (or any time the source code or Dockerfile changes and you run `docker compose build token-mint`). After that, it's the same as livekit-server — a container running from an image.

### What each key in the service block does

- **`token-mint:`** — service name. Same as livekit-server: used as identifier for `docker compose <command> token-mint` and as the DNS hostname other containers can reach it at if they shared a docker network (here irrelevant — see `ports:` below).

- **`build:`** — instead of `image:` (which pulls a prebuilt image), `build:` tells Compose to BUILD an image locally from a Dockerfile. Two sub-keys:
  - **`context: ./sophia-agent`** — the "build context," the directory Docker treats as root when running the Dockerfile. Every `COPY` in the Dockerfile is relative to this path. `./sophia-agent` (relative to the compose file location at workspace root) means Docker sends the contents of `sophia-agent/` as the build context. `COPY pyproject.toml uv.lock ./` inside the Dockerfile resolves to `sophia-agent/pyproject.toml` and `sophia-agent/uv.lock`.
  - **`dockerfile: Dockerfile.token-mint`** — which Dockerfile to use within the context. Default would be `Dockerfile` (capital D, no extension); we override because the `sophia-agent/` directory has both `Dockerfile` (for agent-worker) and `Dockerfile.token-mint` (for this service — slimmer because it skips the Silero VAD + turn-detector model download).

- **`ports: ["8001:8001"]`** — port publishing. Format is `"<host-port>:<container-port>"`. The container listens on port 8001 inside its own network namespace (set by `EXPOSE 8001` + the uvicorn `--port 8001` flag in the Dockerfile CMD). Docker forwards `<host-IP>:8001` → `<container-IP>:8001`. **This is the alternative to `network_mode: host`** — see Q4 for why we use this here but host networking for livekit-server.

- **`env_file: ["./sophia-agent/.env.production"]`** — load environment variables from this file at container start. Each `KEY=value` line in `.env.production` becomes an env var inside the container. This is HOW the secrets get into the container without being baked into the image. token_mint.py reads them via `os.environ.get(...)`:
  - `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` — used to sign JWTs.
  - `SOPHIA_TOKEN_API_KEY` — the X-API-Key shared secret for auth.
  - `SOPHIA_CORS_ORIGINS` — CORS allow-list.
  - `LIVEKIT_URL` — value embedded in the JSON response so clients know where to connect.

  Important gotcha: `env_file` changes are picked up only at container CREATE time, not at restart. Edit `.env.production` → must `docker compose down + up` (NOT just `docker compose restart`). Documented as Problem 18 in `mvp_deployment_shared_ec2.md`.

- **(no `command:` key)** — unlike livekit-server, we don't override the CMD. The Dockerfile's `CMD ["uv", "run", "uvicorn", "src.token_mint:app", "--host", "0.0.0.0", "--port", "8001"]` runs as-is. This launches uvicorn (the ASGI server) which loads the FastAPI app from `src/token_mint.py`.

- **`restart: unless-stopped`** — same as livekit-server. Container auto-restarts on crash, Docker daemon restart, or EC2 reboot. Explicit `docker compose stop` is what stops it.

### What's in Dockerfile.token-mint

Multi-stage build, ~30 lines. Two stages:

**Stage `base`**: starts from `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` — an upstream image from the uv project that has Python 3.13 + uv preinstalled on Debian slim. Sets two env vars: `PYTHONUNBUFFERED=1` (logs flush immediately), `UV_COMPILE_BYTECODE=1` (precompile .pyc files for faster startup).

**Stage `build`** (`FROM base AS build`): copies `pyproject.toml` + `uv.lock`, runs `uv sync --locked --no-dev` to install dependencies from the lockfile (production deps only, no test/lint packages). Then copies `src/` into the image. Result: a `/app` directory with the venv + source code.

**Final stage** (`FROM base`): creates a non-root user `appuser` (uid 10001, no shell, home `/app`). Copies `/app` from the build stage to the final image, owned by appuser. Switches to appuser. `EXPOSE 8001` documents the listening port. `CMD` launches uvicorn.

Why slimmer than the agent-worker Dockerfile: token-mint doesn't load any ML models. The main `Dockerfile` (agent-worker) has an additional build step `RUN uv run "src/agent.py" download-files` which pulls Silero VAD (~100 MB) and the turn-detector ONNX. Token-mint skips that.

### What's in src/token_mint.py

A FastAPI app, ~120 lines. Two endpoints + CORS middleware + auth helper:

**Module-level setup**:
- Imports FastAPI, CORS middleware, the `livekit.api` SDK (Python bindings for building JWTs), Pydantic for request/response schemas.
- Reads four env vars on startup: `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `SOPHIA_TOKEN_API_KEY`, `SOPHIA_CORS_ORIGINS`.
- Constant `DEFAULT_AGENT_NAME = "sophia-agent"` (must match the `agent_name` registered in `agent.py`).

**`_require_api_key(x_api_key)`** helper:
- If `SOPHIA_TOKEN_API_KEY` env var is EMPTY → no-op (auth disabled, MVP dev mode).
- If it's SET and the request's `X-API-Key` header is missing or doesn't match → raise HTTP 401 with body `Missing or invalid X-API-Key header`.

**`POST /token`** handler:
1. Calls `_require_api_key(x_api_key)` — bounces unauthorized requests.
2. Builds `api.VideoGrants(room_join=True, room=req.room, can_publish=True, can_subscribe=True, can_publish_data=True)` — the JWT claim listing what the participant is allowed to do in the room.
3. Builds `api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)` — the token builder, seeded with our signing credentials.
4. Chains `.with_identity(req.identity)` (sub claim), `.with_name(req.name or req.identity)` (display name), `.with_grants(grants)`, `.with_ttl(timedelta(seconds=req.ttl_seconds))` (default 3600s).
5. If `req.agent_name` is set (default `"sophia-agent"`), adds `RoomConfiguration(agents=[RoomAgentDispatch(agent_name=req.agent_name)])` — this is what tells the SFU to dispatch our agent worker into the room.
6. Returns `{token: <jwt>, url: <livekit-url>, identity, room}`.

**`GET /health`** handler: returns `{"status": "ok", "livekit_url": ...}`. Used by external probes + the cold-start verification curls in `mvp_deployment_shared_ec2.md`.

### Comparing to livekit-server's deployment

| Aspect | livekit-server | token-mint |
|---|---|---|
| Image source | `image: livekit/livekit-server:latest` (stock, pulled) | `build:` (custom, built locally) |
| Custom code | None | Yes, FastAPI app in `src/token_mint.py` |
| Custom Dockerfile | No | Yes, `Dockerfile.token-mint` (multi-stage uv-based) |
| Network | `network_mode: host` | `ports: ["8001:8001"]` (bridge + publish) |
| Config injection | `volumes:` (bind-mount livekit.prod.yaml as a file) | `env_file:` (inject secrets as env vars) |
| Command override | Yes (`--config /etc/livekit.yaml --node-ip 3.227.63.49`) | No (uses Dockerfile's CMD) |
| Restart policy | `unless-stopped` | `unless-stopped` |

The two patterns reflect two service types: token-mint is a vanilla HTTP service (standard Docker patterns work fine), livekit-server is a WebRTC SFU (needs host networking + a config file mount).

---

## Q4 (2026-06-01): Why does token-mint use `ports:` instead of `network_mode: host` like livekit-server?

**Because token-mint is plain HTTP — no WebRTC, no UDP, no candidate-IP problem.** All the reasons that forced host networking for the SFU (Q2) don't apply here.

Three properties of token-mint that make standard port publishing fine:

1. **Single TCP port (8001), no port range.** WebRTC needed 10,001 UDP ports (50000-60000) which is impractical to publish individually. token-mint needs ONE port. `ports: ["8001:8001"]` is trivial.

2. **No advertised-IP problem.** WebRTC clients need the SFU to advertise its real public IP in ICE candidates (otherwise clients can't connect). token-mint just answers HTTP requests — there's no concept of "advertising an IP." The client already knows where to send the request (the URL); the server just receives it and responds. NAT'ing through Docker's bridge layer adds milliseconds but doesn't break anything.

3. **Standard request/response model.** HTTP requests come in, the FastAPI handler signs a JWT, the response goes out. Docker's userspace proxy handles the NAT translation cleanly because the connection is short-lived and entirely TCP.

### What `ports: ["8001:8001"]` actually does

Three things happen at container start:

1. Docker creates a bridge network for the compose project (if not already created). The container gets a private IP on that bridge (e.g. `172.18.0.3`).
2. Docker programs iptables on the host to forward `host:8001` → `container:8001` in both directions. The `docker-proxy` userspace process backs this up.
3. The container's network namespace is isolated from the host. Inside the container, `localhost` is just the container's own loopback (not the EC2 host's). External traffic comes in via the bridge interface.

A client hits `3.227.63.49:8001`. AWS routes it to the EC2 host. iptables on the host forwards it to the container's port 8001. The FastAPI process accepts the connection. Response goes back the same way. Latency overhead: <1ms typically.

Compare to host networking: there'd be no bridge, no iptables forwarding, the FastAPI process would bind directly on the host's `0.0.0.0:8001`. Saves the <1ms NAT overhead but gives up network isolation. Not worth it for a service that doesn't have UDP/WebRTC constraints.

### Security side-benefit of using ports: over host:

With `ports:`, the container runs in its own network namespace. If the FastAPI process is ever exploited (untrusted input parsing, dependency CVE, etc.), the attacker is sandboxed inside the container's network — they can't directly bind to other ports on the host or access services running on the EC2's loopback. With host networking, the attacker would have full access to the host's network stack.

For livekit-server we accept the tradeoff because it's stock Go code from upstream LiveKit + WebRTC requires it. For token-mint there's no reason to accept it.

### Production-grade equivalent (k8s)

A standard `Service` of `type: ClusterIP` on port 8001 + an `Ingress` routing external traffic to it. Or `type: LoadBalancer` with cloud-provider integration. The Pod itself runs without any special networking (`hostNetwork: false`, the default). Identical mental model to `ports:` in docker-compose.

---

## Q5 (2026-06-01): How is agent-worker deployed? Same pattern as token-mint?

**Almost the same pattern as token-mint (custom code, BUILD an image), with three meaningful differences: heavier Dockerfile (loads ML models), `network_mode: host` instead of `ports:` (worker is a CLIENT not a server), and a `LIVEKIT_URL` env override layered on top of the env_file.** Four pieces total:

1. **Docker Compose service block** (declares build, network, env file + env override, restart policy).
2. **The Dockerfile** (`sophia-agent/Dockerfile` — the unsuffixed one, NOT Dockerfile.token-mint).
3. **The application code** (`sophia-agent/src/agent.py` ~700 lines + pyproject.toml + uv.lock).
4. **The `.env.production` file** with secrets + inference URLs, loaded via `env_file:`.

Our actual block from the workspace-root docker-compose.yml on EC2:

```yaml
agent-worker:
  build:
    context: ./sophia-agent
    dockerfile: Dockerfile
  network_mode: host
  env_file:
    - ./sophia-agent/.env.production
  environment:
    - LIVEKIT_URL=ws://localhost:7880
  restart: unless-stopped
```

### What each key in the service block does

- **`agent-worker:`** — service name. Used for `docker compose logs agent-worker`, `docker compose restart agent-worker`, etc. Container name on EC2 becomes `sophia-agent-worker-1` (project-name + service + replica index).

- **`build:`** — same idea as token-mint (build an image locally), but pointing at the OTHER Dockerfile.
  - **`context: ./sophia-agent`** — same context as token-mint.
  - **`dockerfile: Dockerfile`** — uses the bare `Dockerfile` (no extension) instead of `Dockerfile.token-mint`. This is the heavier one that pre-downloads Silero VAD + turn-detector ONNX models.

- **`network_mode: host`** — host networking, same as livekit-server. Why a worker (which acts as a CLIENT to the SFU, not a server) also needs host networking: see Q6 — this is the subtle one.

- **(no `ports:` key)** — the worker doesn't LISTEN on any port. It's purely outbound (connects to the SFU, connects to inference services). Nothing for clients to connect to.

- **`env_file: ["./sophia-agent/.env.production"]`** — same as token-mint. Loads all shared env vars: `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `SOPHIA_TOKEN_API_KEY` (unused here but harmless), `WHISPER_URL`, `QWEN3_URL`, `KOKORO_URL`, `SOPHIA_RAG_URL`, etc.

- **`environment: ["LIVEKIT_URL=ws://localhost:7880"]`** — **This is the critical difference from token-mint.** Docker Compose lets you both `env_file` and `environment` on the same service; `environment` values OVERRIDE `env_file` values. The `.env.production` file has `LIVEKIT_URL=ws://3.227.63.49:7880` (the public URL, used by other consumers). We explicitly override it to `ws://localhost:7880` for THIS container only. Full rationale in Q6.

- **(no `command:` key)** — uses the Dockerfile's `CMD ["uv", "run", "src/agent.py", "start"]`. The `start` subcommand puts the worker in production mode (vs `dev` which adds hot-reload + verbose logging).

- **`restart: unless-stopped`** — same as the other two services.

### What's in Dockerfile (vs Dockerfile.token-mint)

Same multi-stage uv-based shape as token-mint, with three extra things:

**1. Build-time compiler toolchain.** The `build` stage adds:

```dockerfile
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    python3-dev \
  && rm -rf /var/lib/apt/lists/*
```

Some Python deps (notably parts of onnxruntime, sounddevice / numpy native extensions) compile from source during `uv sync`. The slim base image doesn't include a C/C++ toolchain, so the build would fail. Token-mint doesn't need these because none of ITS deps require compilation.

**2. HF_HOME env var + model pre-download.** In both stages:

```dockerfile
ENV HF_HOME=/app/.cache/huggingface
RUN uv run "src/agent.py" download-files
```

The `download-files` subcommand pulls Silero VAD (~30 MB) + turn-detector ONNX (~70 MB) from HuggingFace into `$HF_HOME`. Setting `HF_HOME=/app/.cache/huggingface` (instead of the default `/root/.cache/...`) ensures the cache lands UNDER `/app`, which is what the final stage copies via `COPY --from=build /app /app`. Without the override, the cache would land under `/root` and get dropped by the multi-stage build — the runtime worker would crash on startup looking for missing models. **Documented as Problem 7 in `mvp_deployment_shared_ec2.md`.** Both the build stage and the final stage need the env var: build to write the cache there, final to read it at runtime.

**3. Heavier `uv sync`.** The build stage runs `uv sync --locked` (NOT `--no-dev`) to install all deps including the ML inference runtimes. Resulting image is much larger than token-mint's: ~2-3 GB vs ~500 MB.

Final stage is otherwise identical to token-mint: non-root `appuser` (uid 10001), `COPY --from=build /app /app`, switch to appuser, run the CMD.

### What's in src/agent.py

A LiveKit Agents worker, ~700 lines. Structurally three pieces:

**Module-level setup**:
- Imports from `livekit.agents` (Agent, AgentServer, AgentSession, JobContext, JobProcess, cli, llm) + `livekit.plugins.openai`, `livekit.plugins.silero`, `livekit.plugins.turn_detector.multilingual`.
- `load_dotenv(".env.local")` — for local dev only; on EC2 the env vars come from `env_file:` in docker-compose, not from .env.local.
- Reads four inference URLs from env (`WHISPER_URL`, `QWEN3_URL`, `KOKORO_URL`, `SOPHIA_RAG_URL`) with localhost defaults.
- Defines ~12 VAD/turn-handling tuning knobs (activation threshold, min silence duration, prefix padding, etc.) as module-level constants.

**`prewarm(JobProcess)`**: runs ONCE per worker subprocess at startup. Loads Silero VAD into `proc.userdata["vad"]` so each new room job doesn't pay the model-load cost. Registered via `server.setup_fnc = prewarm`.

**`@server.rtc_session(agent_name="sophia-agent")` decorator on entrypoint**: this is the most important line in the file.

```python
server = AgentServer()

@server.rtc_session(agent_name="sophia-agent")
async def sophia_agent(ctx: JobContext):
    session = AgentSession(
        stt=openai.STT(base_url=f"{WHISPER_URL}/v1", model="whisper-large-v3", api_key="not-needed"),
        llm=openai.LLM(base_url=f"{QWEN3_URL}/v1", model="qwen3-vl-8b-instruct", api_key="not-needed"),
        tts=openai.TTS(base_url=f"{KOKORO_URL}/v1", model="tts-1", voice="serena", api_key="not-needed", response_format="wav"),
        vad=ctx.proc.userdata["vad"],
        turn_handling=_build_turn_handling(),
        aec_warmup_duration=AEC_WARMUP_DURATION,
    )
    _attach_event_publishers(session)
    await session.start(agent=Assistant(), room=ctx.room)
    await ctx.connect()
```

The decorator registers this function as the entry point for any room dispatched to `agent_name: "sophia-agent"`. When a JWT arrives at the SFU with `roomConfig.agents: [{agentName: "sophia-agent"}]`, the SFU calls this function with a `JobContext` for that room. The function builds an `AgentSession` (the STT/LLM/TTS pipeline orchestrator), wires the event publishers (text-stream topics to frontend), and connects to the room.

The `Assistant` class (defined elsewhere in the file) has the `on_user_turn_completed` hook that does the always-retrieve RAG call.

**`cli.run_app(server)`**: the `if __name__ == "__main__"` line. When the Dockerfile CMD `uv run src/agent.py start` runs, this is the entry point. It:
1. Reads CLI args (`start` for production, `dev` for hot-reload local dev).
2. Opens a WebSocket to `LIVEKIT_URL` (the env var — `ws://localhost:7880` on EC2 thanks to the override).
3. Sends a `RegisterWorkerRequest` with `agent_name: "sophia-agent"`.
4. Waits for job dispatches from the SFU. Each dispatch forks a subprocess (per-room isolation), runs `prewarm`, then runs the `sophia_agent` entrypoint inside that subprocess.

### Comparing the three services on EC2

| Aspect | livekit-server | token-mint | agent-worker |
|---|---|---|---|
| Image source | stock (`image:`) | built (`build:` + Dockerfile.token-mint) | built (`build:` + Dockerfile) |
| Custom code | None | ~120-line FastAPI | ~700-line LiveKit Agents worker |
| ML models bundled | No | No | Yes (Silero VAD + turn-detector ONNX) |
| Image size | ~30 MB | ~500 MB | ~2-3 GB |
| Network | `network_mode: host` | `ports: ["8001:8001"]` | `network_mode: host` |
| Listens on a port | Yes (7880/7881/UDP range) | Yes (8001) | No — purely outbound |
| Config injection | `volumes:` (yaml file) | `env_file:` | `env_file:` + `environment:` override |
| Command override | Yes | No | No |
| Restart policy | unless-stopped | unless-stopped | unless-stopped |

---

## Q6 (2026-06-01): Why does agent-worker need BOTH `network_mode: host` AND a `LIVEKIT_URL=ws://localhost:7880` env override? Aren't those overlapping?

**They look related but solve different problems. Both are required — neither alone is sufficient.** This is the trickiest piece of the EC2 deploy and was the source of Problem 6 in `mvp_deployment_shared_ec2.md`.

### Why `network_mode: host` is needed

The agent-worker needs to reach `ws://localhost:7880` (the SFU). Three possible networking modes on Docker; only one works cleanly:

**Option A — host networking (what we use).** Container shares the EC2's network namespace. Container's `localhost` IS the EC2's loopback. SFU is also on host networking listening on `0.0.0.0:7880`, so the worker's `ws://localhost:7880` resolves to the local SFU instantly. No NAT, no public-interface roundtrip.

**Option B — default bridge networking with the SFU also on bridge.** Would let the worker reach the SFU at `ws://livekit-server:7880` (Docker DNS). BUT the SFU can't use bridge networking because WebRTC needs host network (Q2). So this option doesn't work as long as the SFU stays on host networking.

**Option C — default bridge networking with `extra_hosts: ["livekit-server:host-gateway"]`.** Would let the bridge-networked worker reach the host's loopback via a special DNS name. Works in theory but adds an extra hop through Docker's userspace proxy + makes the config more fragile. We never tried it.

So host networking is the only clean way for the worker to reach the SFU at `localhost`.

### Why the `LIVEKIT_URL=ws://localhost:7880` override is ALSO needed

This is the gotcha. The shared `.env.production` file has:

```
LIVEKIT_URL=ws://3.227.63.49:7880
```

That value is correct for OTHER consumers of the env file (the Next.js frontend's server-side route uses it to tell browser clients where the SFU is — and browsers need the public URL, not localhost). The agent-worker reads the SAME env file, so by default it would also pick up `ws://3.227.63.49:7880` (the public IP).

What happens if the worker uses the public IP:

1. Worker calls `WebSocket("ws://3.227.63.49:7880/worker")`.
2. Even with host networking on the EC2, the DNS resolves `3.227.63.49` to a public address.
3. The packet leaves the EC2 via the public interface.
4. It hits the AWS Security Group as INBOUND traffic.
5. If SG ingress on port 7880 is open → packet comes back IN through the same interface, reaches the local SFU. Works, but wastefully — every packet does an out-and-back through AWS infra.
6. If SG ingress on port 7880 is CLOSED (early in deployment, before the Phase 13 PR was merged) → packet is dropped. Worker shows `ConnectionTimeoutError: ws://3.227.63.49:7880`. This was the exact symptom of Problem 6.

Forcing `LIVEKIT_URL=ws://localhost:7880` for the worker container:
- Resolves to the EC2's loopback interface.
- Never leaves the host. Pure kernel-level packet routing inside the network namespace.
- Faster (microseconds, no AWS round-trip).
- Doesn't depend on SG state.

### How docker-compose handles the override

`env_file:` is processed FIRST (each `KEY=value` line becomes an env var). `environment:` is processed SECOND and OVERRIDES anything from `env_file:` with the same key. So inside the agent-worker container:

```
LIVEKIT_URL=ws://localhost:7880   ← from environment:, overrode env_file:
LIVEKIT_API_KEY=<from env_file>   ← unchanged
LIVEKIT_API_SECRET=<from env_file> ← unchanged
WHISPER_URL=http://localhost:8080  ← from env_file
... etc.
```

Inside `agent.py`, `os.environ.get("LIVEKIT_URL")` returns `ws://localhost:7880`. The worker connects to localhost. Done.

The token-mint container has NO override — it picks up `LIVEKIT_URL=ws://3.227.63.49:7880` from env_file. This value gets embedded in the JSON response (the `url` field) and ends up in the glasses' SophiaConfig as the public URL clients should use. Different consumers, different needs.

### Could we just edit .env.production to localhost?

No, because then the Next.js frontend (which reads the same file via its own `.env.local`) would tell browser clients to connect to `ws://localhost:7880` — which would resolve to the BROWSER's own localhost, not the EC2's. Browsers would fail to connect to the SFU. The override-per-container pattern is correct: the value of `LIVEKIT_URL` is consumer-specific.

### Production-grade equivalent (k8s)

In a Kubernetes setup with both SFU and worker on `hostNetwork: true` (same node), the same override applies: the worker's env would have `LIVEKIT_URL=ws://localhost:7880`. In a setup where the SFU runs as a Service (different Pod, ClusterIP), the worker would use `LIVEKIT_URL=ws://livekit-server.namespace.svc.cluster.local:7880`. The principle is the same: worker should reach the SFU via the FASTEST available path, which differs from what external clients should use. Encode that as a per-Pod env var.

---

## Q7 (2026-06-01): Complete end-to-end flow for the BROWSER application — who asks whom, who connects to whom, who sends what, who responds with what?

User opens Chrome, types `http://3.227.63.49:3000`, clicks Start Call, asks "What's the safety procedure for the X-200?", Sophia answers ~3 seconds later. Every step that happens between, named at the protocol level.

### Step 0 — One-time Chrome setup (per profile)

- **Actor**: User on their laptop.
- **Action**: Open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, paste `http://3.227.63.49:3000`, relaunch Chrome.
- **Why**: Chrome blocks `navigator.mediaDevices.getUserMedia()` on non-secure-context pages. Our public-IP HTTP page qualifies as non-secure → the mic API is literally `undefined` in page JavaScript without this flag.
- **Result**: That ONE origin is now treated as secure for this Chrome profile. The mic API becomes available. Flag persists until cleared.

### Step 1 — Page load

- **Actor**: Browser. **Target**: EC2's frontend on port 3000.
- **Request**: `GET / HTTP/1.1` to `http://3.227.63.49:3000/`.
- **Path through Docker**: AWS SG inbound rule for TCP 3000 → EC2 host → bypasses Docker (npm start runs natively, not in a container) → Next.js process bound on `0.0.0.0:3000`.
- **Response**: `200 OK` with the prebuilt React HTML + a `<script>` tag pointing at the JS bundle. ~200 KB total.
- **Result**: Browser starts loading + executing the React SPA. Page renders the welcome screen with a "Start Call" button.

### Step 2 — User clicks Start Call

- **Actor**: User clicks. **Target**: React component (`components/app/app.tsx` or similar).
- **Action**: React calls the LiveKit Agents Starter's `useConnection` hook, which kicks off the connection flow.
- **No network traffic yet** — purely client-side state change.

### Step 3 — Browser asks for a JWT (the "token request")

- **Actor**: Browser (JavaScript). **Target**: Next.js server-side route at SAME origin.
- **Request**: `POST /api/token HTTP/1.1` to `http://3.227.63.49:3000/api/token` with body `{}` (empty JSON).
- **Critically**: This is NOT the FastAPI token-mint at port 8001. Browser uses the Next.js built-in route at port 3000.
- **Server-side handler** (`agent-starter-react/app/api/token/route.ts`, running inside the `npm start` process):
  1. Reads `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` from its `.env.local`.
  2. Generates random room name like `sophia-2025-XXXX`.
  3. Generates random participant identity like `viewer-abc123`.
  4. Uses `livekit-server-sdk` (npm package) to build an `AccessToken` with the room, identity, video grants (canPublish/Subscribe/PublishData), and TTL.
  5. **Critically** adds `roomConfig.agents: [{agentName: 'sophia-agent'}]` — this is what tells the SFU to dispatch our worker.
  6. Signs the JWT using HS256 with `LIVEKIT_API_SECRET`.
- **Response**: `200 OK` with body `{ "serverUrl": "ws://3.227.63.49:7880", "participantToken": "eyJhbG...", "roomName": "...", "participantName": "..." }`.
- **Auth**: None on this route. It's open. Anyone who can hit `:3000/api/token` gets a token.

### Step 4 — Browser opens WebSocket to SFU

- **Actor**: Browser. **Target**: livekit-server (SFU) on EC2 port 7880.
- **Request**: WebSocket upgrade to `ws://3.227.63.49:7880/rtc?access_token=<jwt>&protocol=12&...`.
- **Path through Docker**: AWS SG inbound TCP 7880 → EC2 host → SFU listening on `0.0.0.0:7880` (because host networking).
- **SFU side**:
  1. Receives the WS handshake with the JWT in the query string.
  2. Decodes the JWT. Reads the `iss` claim = `LIVEKIT_API_KEY`. Looks up the matching secret in its `keys:` block (loaded from `livekit.prod.yaml`).
  3. Verifies HS256 signature with that secret. **If signature fails → close WS with error.** Otherwise proceed.
  4. Creates the room if it doesn't exist. Adds this participant.
- **Response**: SFU sends back a `JoinResponse` LiveKit protocol message over the WS containing the SFU's connection parameters (ICE candidates, fingerprints, supported codecs).

### Step 5 — SFU dispatches the agent worker (parallel to Step 4)

- **Trigger**: When SFU processes the JoinRequest in Step 4, it sees `roomConfig.agents: [{agentName: 'sophia-agent'}]` in the JWT.
- **Actor**: SFU. **Target**: agent-worker container on the same EC2.
- **Path**: The worker registered at startup via its own long-lived WebSocket to `ws://localhost:7880/worker` (because of the host networking + LIVEKIT_URL=ws://localhost:7880 override from Q6). SFU sends a `JobOffer` over that WS.
- **JobOffer payload** (LiveKit protobuf): `{job: {id, room: {name: ...}, participant: {identity, ...}}}`.
- **Worker responds**: `JobAccept` over the same WS.
- **SFU mints**: a server-side JWT for the worker (different from the one the browser got).
- **Worker action**: Uses that JWT to open a SEPARATE WebSocket connection to `ws://localhost:7880/rtc` and join the room as a new participant with identity `agent-<sid>`. The `agent-` prefix is what glasses clients filter on for audio playback (Q58).

Now the room has 2 participants: the browser (viewer) and the agent.

### Step 6 — WebRTC negotiation (browser ↔ SFU)

- **Actor**: Browser AND SFU together. Exchange SDP messages over the WS opened in Step 4.
- **SDP offer** (browser → SFU): "I support Opus codec, here are my ICE candidates for receiving media, here's my DTLS fingerprint."
- **SDP answer** (SFU → browser): "OK, here are MY ICE candidates, MY DTLS fingerprint, agreed codecs."
- **ICE connectivity check**: Browser and SFU each try to send STUN binding requests to the other's candidate IPs over UDP. The SFU's host candidate is `3.227.63.49:<random-from-50000-60000>`. Browser's candidate is whatever NAT gives it.
- **DTLS handshake** over UDP completes. SRTP encryption keys derived.
- **Result**: A WebRTC peer connection exists between browser and SFU. UDP packets flow over the public internet to the EC2 SG inbound UDP 50000-60000 → SFU.

### Step 7 — WebRTC negotiation (worker ↔ SFU, parallel)

Same as Step 6 but happens inside the EC2:
- Worker's ICE candidate is on the loopback / host interface.
- SFU's candidate is on `127.0.0.1:<port>`.
- DTLS + SRTP keys derived for the worker side too.
- **Result**: A SEPARATE WebRTC peer connection between worker and SFU on the same EC2.

### Step 8 — Browser requests microphone

- **Actor**: Browser. **Target**: Operating system / Chrome's mic permission gate.
- **Action**: `navigator.mediaDevices.getUserMedia({ audio: true })`.
- **First time**: Chrome shows the mic permission dialog. User clicks Allow.
- **Result**: Browser receives a `MediaStreamTrack` containing live mic audio frames at 48 kHz mono.

### Step 9 — Browser publishes mic track

- **Actor**: Browser. **Target**: SFU (via the existing peer connection).
- **Action**: `room.localParticipant.publishTrack(track, { source: TrackSource.SourceMicrophone })`.
- **What happens**: The browser starts encoding mic audio as Opus, packets it in SRTP, sends over the UDP peer connection.
- **SFU side**: Receives the packets, notes "this participant just published an audio track." Notifies other participants in the room (the agent-worker).

### Step 10 — Worker subscribes to user's audio

- **Actor**: SFU notifies worker. **Target**: Worker auto-subscribes.
- **Action**: SFU starts FORWARDING the browser's audio packets to the worker over the worker's peer connection.
- **Worker side** (Python code): The LiveKit Agents framework's `AgentSession.input` consumes the incoming audio frames. They're routed to Silero VAD (CPU inference, ~1ms per frame).

User starts speaking: "What's the safety procedure for the X-200?"

Audio flows: browser mic → SRTP/UDP → SFU → SRTP/UDP → worker → AgentSession → VAD frame-by-frame.

### Step 11 — Turn-detection fires end-of-turn

- **Actor**: Worker's MultilingualModel turn-detector (an ONNX model running inside the worker).
- **Input**: Accumulated audio + VAD state.
- **Output**: Decision "user is done talking."
- **Effect**: AgentSession finalizes the buffered audio (the full utterance) and triggers the STT call.

### Step 12 — Worker calls Whisper STT

- **Actor**: Worker. **Target**: whisper-inference service in EKS us-west-2, reached via kubectl port-forward.
- **Request**: `POST http://localhost:8080/v1/audio/transcriptions` with multipart/form-data body containing `file=<audio bytes>` and `model=whisper-large-v3`.
- **Path**: localhost:8080 → kubectl port-forward process on EC2 → EKS API endpoint (us-west-2, HTTPS public) → kube-proxy → whisper-inference Pod.
- **Response**: `200 OK` with body `{ "text": "What's the safety procedure for the X-200?" }`.
- **Latency**: ~400-600 ms total (includes cross-region hop).

### Step 13 — `on_user_turn_completed` hook fires (RAG)

- **Actor**: Worker. **Target**: sophia-spatial-ai in EKS, via port-forward at localhost:8106.
- **Request**: `POST http://localhost:8106/retrieve` with body `{ "question": "What's the safety procedure for the X-200?", "top_k": 5 }`.
- **Response**: `200 OK` with body like:
  ```json
  {
    "question": "...",
    "answer": "<pre-generated answer string>",
    "hits": [
      {"source": "manual_x200.pdf", "page": 42, "score": 0.78, "text": "..."},
      {"source": "manual_x200.pdf", "page": 43, "score": 0.71, "text": "..."}
    ],
    "mode": "...",
    "images": [...]
  }
  ```
- **Logic in the hook**: If `max(hit.score for hit in hits) >= 0.10` (RAG_SCORE_THRESHOLD), inject the top chunks into the LLM `chat_ctx` as a system message: "Here is relevant context from the maintenance manual: ...". Below threshold, skip injection.
- **Side effect**: Worker publishes a `sophia.rag_result` text-stream message over the data channel with the full payload. Browser subscribes and renders the RAG side panel.

### Step 14 — Worker calls LLM (Qwen3-VL-8B-Instruct)

- **Actor**: Worker. **Target**: qwen3-inference in EKS, via port-forward at localhost:18080.
- **Request**: `POST http://localhost:18080/v1/chat/completions` with body:
  ```json
  {
    "model": "qwen3-vl-8b-instruct",
    "messages": [
      {"role": "system", "content": "<system prompt>"},
      {"role": "system", "content": "<RAG chunks if injected>"},
      {"role": "user", "content": "What's the safety procedure for the X-200?"}
    ],
    "stream": true
  }
  ```
- **Response**: Server-sent events stream. Each chunk is `data: {"choices": [{"delta": {"content": "Sa"}}]}\n\n`, terminated by `data: [DONE]\n\n`.
- **Worker action**: Buffers tokens as they arrive, starts feeding them to TTS as complete sentence-fragments emerge (streaming TTS — doesn't wait for full LLM response).
- **Latency**: First token ~1-1.5 s, full response ~2-3 s.

### Step 15 — Worker calls TTS (Kokoro)

- **Actor**: Worker. **Target**: kokoro-tts in EKS, via port-forward at localhost:8122.
- **Request** (for each TTS chunk): `POST http://localhost:8122/v1/audio/speech` with body:
  ```json
  {
    "model": "tts-1",
    "voice": "serena",
    "input": "<text fragment to speak>",
    "response_format": "wav"
  }
  ```
- **Response**: Binary WAV audio bytes (raw, not SSE).
- **Worker action**: Receives WAV, hands it to a LiveKit `LocalAudioTrack` for publishing.

### Step 16 — Worker publishes its audio track

- **Actor**: Worker. **Target**: SFU (via the worker's WebRTC peer connection from Step 7).
- **Action**: Wraps the WAV audio in a `LocalAudioTrack`, calls `room.localParticipant.publishTrack(track)` on the worker side.
- **Effect**: Worker starts sending Opus-encoded TTS audio packets over its peer connection to the SFU.
- **SFU action**: Forwards those packets to every OTHER participant in the room (the browser).

### Step 17 — Browser subscribes to agent track

- **Actor**: SFU notifies browser. Browser auto-subscribes.
- **Action**: SFU forwards the worker's audio packets over the browser's peer connection (the one from Step 6).
- **Browser side**: The LiveKit JS SDK creates a new `RemoteAudioTrack`, attaches it to an `<audio>` DOM element, the element auto-plays.
- **Result**: User hears Sophia's voice through laptop speakers / headphones.

Round-trip from "stopped talking" to "Sophia starts talking": ~2-3 seconds.

### Step 18 — Text-stream side channel (throughout the whole flow)

While the audio is flowing, the worker ALSO publishes data-channel messages on three topics:
- **`sophia.agent_events`** — JSON events for state pill (`{kind: "agent_state", state: "thinking" | "speaking" | "listening"}`), user transcripts, metrics.
- **`lk.transcription`** — incremental transcript text (built-in LiveKit topic).
- **`sophia.rag_result`** — the full payload from Step 13.

Browser components subscribe via `room.on('dataReceived', handler)` or LiveKit's text-stream API. The state pill, scrolling transcript, and RAG sources side panel update in real time.

### Step 19 — End session

- **Actor**: User clicks End Call (or closes tab).
- **Action**: Browser sends `LeaveRequest` over its WS to the SFU.
- **SFU side**: Removes the participant. Since the agent is the only other participant, the SFU sends `RoomDisconnected` to the agent. Worker's `sophia_agent(ctx)` function awaits a final cleanup and returns. Worker subprocess ends, parent worker process goes back to "available" state ready for the next room dispatch.

### Quick summary of which connections exist during a session

- Browser ↔ Next.js frontend: 1 TCP connection for HTML/JS load (Step 1). 1 short TCP for token POST (Step 3). Both closed after.
- Browser ↔ SFU: 1 long-lived WS over TCP 7880 (Step 4). 1 long-lived WebRTC peer connection over UDP 50000-60000 (Steps 6, 9, 17).
- Worker ↔ SFU: 1 long-lived worker-registration WS (set up at worker startup). 1 long-lived job WS for the room (Step 5). 1 long-lived WebRTC peer connection over UDP (Steps 7, 10, 16).
- Worker ↔ Inference services: short-lived HTTP requests per turn (Steps 12, 13, 14, 15). All over localhost via kubectl port-forwards.
- SFU ↔ AgentServer registration: 1 long-lived WS established at agent-worker startup (before any room exists).

---

## Q8 (2026-06-01): Complete end-to-end flow for the XREAL GLASSES + Beam Pro application — who asks whom, who connects to whom, who sends what, who responds with what?

User puts on Beam Pro + XREAL One Pro glasses, taps the Sophia app icon, asks "What's the safety procedure for the X-200?", Sophia answers through the glasses temple speakers ~3 seconds later. Same backend, different client glue.

### Step 0 — Prerequisites (already done)

- Beam Pro has the Sophia APK installed via `adb install -r sophia-glasses.apk`.
- The APK has `SophiaConfig.asset` baked in with: `liveKitUrl=ws://3.227.63.49:7880`, `tokenEndpoint=http://3.227.63.49:8001/token`, `tokenApiKey=9a11fdf5...` (matches `SOPHIA_TOKEN_API_KEY` on EC2), `agentName=sophia-agent`.
- Beam Pro has RECORD_AUDIO permission either granted from a previous session or about to be granted on this launch.

### Step 1 — App launch

- **Actor**: User taps the app icon (or `adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity`).
- **Action**: Android starts the Unity activity. Unity loads `Assets/Scenes/sophia-scene.unity`.
- **In the scene at startup**:
  - `SessionPicker` GameObject ACTIVE → `OnEnable` builds the picker UI (landscape two-column card with Private / Team session buttons).
  - `SophiaConnection` GameObject DEACTIVATED → not running yet.
  - `SophiaOverlayUI` MonoBehaviour ACTIVE → builds the world-space HUD canvas (parented to Camera.main at 2m focal distance).
- **No network traffic yet.**

### Step 2 — User picks Private session

- **Actor**: User taps the Private button (touch on Beam Pro screen).
- **Action**: `SessionPicker.OnPrivateClicked` fires. It:
  1. Sets `SophiaSessionContext.CurrentMode = Mode.Private`.
  2. Hides the picker panel.
  3. Calls `connectionGameObject.SetActive(true)` — activates SophiaConnection.
- **Effect**: `SophiaConnection.OnEnable` starts the `ConnectFlow` coroutine.

### Step 3 — Glasses request a JWT (the token request)

- **Actor**: Beam Pro app (UnityWebRequest). **Target**: token-mint FastAPI on EC2 port 8001.
- **Path**: Beam Pro Android mobile data / WiFi → public internet → AWS SG inbound TCP 8001 → EC2 host → Docker port-mapping → token-mint container port 8001.
- **Request**: `POST http://3.227.63.49:8001/token HTTP/1.1`
  - Header: `Content-Type: application/json`
  - Header: `X-API-Key: 9a11fdf5ce05e3cecad28f933d778971` (added because `config.tokenApiKey` is non-empty)
  - Body: `{ "identity": "glasses-<random>", "room": "sophia-glasses-<random>" }` (or whatever the Unity client generates)
- **token-mint side** (`src/token_mint.py`):
  1. FastAPI dependency injection extracts `x_api_key` from the X-API-Key header.
  2. `_require_api_key(x_api_key)` compares against `SOPHIA_TOKEN_API_KEY` env var. Match → proceed. Mismatch → raise HTTP 401 with body `Missing or invalid X-API-Key header`.
  3. Builds `VideoGrants(room_join=True, room=req.room, can_publish=True, can_subscribe=True, can_publish_data=True)`.
  4. Builds `AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)` (these come from `env_file:.env.production`).
  5. Chains identity, name, grants, TTL.
  6. **Critically** adds `RoomConfiguration(agents=[RoomAgentDispatch(agent_name="sophia-agent")])` — same effect as the browser path.
  7. Signs JWT, returns it.
- **Response**: `200 OK` with body `{ "token": "eyJhbG...", "url": "ws://3.227.63.49:7880", "identity": "...", "room": "..." }`.
- **Failure modes**: If `X-API-Key` is wrong → 401 (Problem 17). If service is unreachable → connection timeout (SG closed or EC2 down).

### Step 4 — Glasses open WebSocket to SFU

- **Actor**: LiveKit Unity SDK on Beam Pro. **Target**: livekit-server on EC2 port 7880.
- **Request**: WebSocket upgrade to `ws://3.227.63.49:7880/rtc?access_token=<jwt>&...`.
- **Path**: Same as browser Step 4 — AWS SG inbound TCP 7880 → EC2 host → SFU.
- **SFU side**: Identical to browser flow Step 4. Verifies JWT signature, creates room (or joins existing), sends `JoinResponse`.

### Step 5 — SFU dispatches the agent worker (parallel to Step 4)

Identical to browser flow Step 5. SFU sees `roomConfig.agents` in the JWT → sends JobOffer to the already-registered agent-worker → worker accepts, joins room as `agent-<sid>`. The agent doesn't know or care that this is the glasses client vs the browser client.

### Step 6 — WebRTC negotiation (Beam Pro ↔ SFU)

- **Actor**: LiveKit Unity SDK on Beam Pro AND SFU together.
- **Inside Unity**: The SDK wraps a native libwebrtc implementation (FFI bindings from `client-sdk-unity/Runtime/Plugins/`) that handles the SDP offer/answer + ICE + DTLS + SRTP same as a browser would.
- **Path of media packets**: Beam Pro mobile network → ICE candidate exchange → public UDP to EC2's 50000-60000 range.
- **Result**: A WebRTC peer connection exists between the Beam Pro app and the SFU. Same protocol as the browser.

### Step 7 — WebRTC negotiation (worker ↔ SFU)

Identical to browser flow Step 7. Worker establishes its own peer connection to the SFU.

### Step 8 — Glasses request microphone

- **Actor**: SophiaConnection's ConnectFlow coroutine (Unity C#). **Target**: Android system / RECORD_AUDIO permission gate.
- **Action**: LiveKit Unity SDK's `MicrophoneSource` calls Android's `Microphone.Start(deviceName, ...)`.
- **If permission not granted**: Android shows the system permission dialog ON the Beam Pro screen. User taps Allow. The SophiaConnection.cs Path A code polls up to 20 seconds waiting for Android to register the grant.
- **Once granted**: `Microphone.Start` returns a Unity `AudioClip` that fills with live mic data at 48 kHz mono.

### Step 9 — Glasses publish mic track

- **Actor**: LiveKit Unity SDK. **Target**: SFU (over the peer connection from Step 6).
- **Action**: SDK wraps the `AudioClip` in a `LocalAudioTrack`, calls `room.LocalParticipant.PublishTrack(track, new TrackPublishOptions { Source = TrackSource.SourceMicrophone })`.
- **What happens**: Native libwebrtc inside the SDK encodes mic audio as Opus, packets in SRTP, sends to the SFU over UDP. Same as browser.

### Step 10 — Worker subscribes to user audio, Steps 11-15 (turn detect, STT, RAG, LLM, TTS)

**Identical to browser flow Steps 10-15.** The worker doesn't know which client type published the audio. STT → RAG → LLM → TTS pipeline runs the same way. Same inference service calls, same data shapes, same timing.

### Step 16 — Worker publishes TTS audio track

Identical to browser flow Step 16. Worker's WAV → SFU → forwarded to subscribers.

### Step 17 — Beam Pro subscribes to agent audio (CRITICAL DIFFERENCE FROM BROWSER)

- **Actor**: SFU notifies Beam Pro. LiveKit Unity SDK fires `Room.TrackSubscribed` event.
- **SophiaConnection.OnTrackSubscribed handler** (the Q58 production-correct contract):

```csharp
private void OnTrackSubscribed(RemoteTrack track, RemoteTrackPublication publication, RemoteParticipant participant)
{
    // FILTER: only play AGENT tracks. Skip other users' mic tracks
    // (which would create echo in multi-user rooms).
    if (!participant.Identity.StartsWith("agent-")) return;

    // ISOLATE: create a child GameObject per agent track so each AudioSource
    // has its own host. Stacking AudioSources on one GameObject causes
    // Unity's mixer to drop one.
    var speakerGo = new GameObject($"SophiaSpeaker_{publication.Sid}");
    speakerGo.transform.SetParent(speakerHost.transform);
    var audioSource = speakerGo.AddComponent<AudioSource>();
    audioStream = new AudioStream(track as RemoteAudioTrack, audioSource);
}
```

- **Result**: Unity's audio mixer plays the AudioSource through the device's primary audio output.

### Step 18 — USB Audio Class routes audio to glasses speakers

- **Actor**: Android USB audio subsystem (kernel + framework).
- **Hardware**: Beam Pro's audio output is the phone speaker by default. But with XREAL One Pro plugged in via USB-C, the OS detects a USB Audio Class device.
- **Effect**: Android auto-routes the primary output to the USB audio device (glasses). User hears Sophia through the glasses' temple speakers, not the phone speaker.
- **No code change needed** — this is OS-level routing.
- **Edge case (Q41/Q43)**: If glasses are NOT plugged in, audio comes out the phone speaker, which sits facing the phone mic → echo loop. Documented as expected behavior.

### Step 19 — World-space AR HUD updates (text-stream side channel)

- **Actor**: Worker publishes text-stream messages (same three topics as browser flow Step 18).
- **Receiver on glasses**: `SophiaConnection` has subscribers that fire a STATIC C# event `SophiaConnection.OnTextStreamMessage(topic, identity, payload)`.
- **SophiaOverlayUI listens** (no reference back to SophiaConnection — decoupled via the static event):
  - Topic `sophia.agent_events` with `kind: "agent_state"` → updates the colored pulsing dot top-right (LISTENING blue / THINKING amber / SPEAKING green) via a CanvasGroup.alpha smoothstep coroutine.
  - Topic `lk.transcription` → updates the bottom-center subtitle text. Speaker-colored prefix ("You: ..." vs "Sophia: ...") via the participant identity.
  - Topic `sophia.rag_result` → parses the JSON's `hits[]` array, deduplicates by (source, page), renders up to 6 chips in a vertical stack above the subtitle.
- **HUD rendering**: World-space Canvas parented to Camera.main at 2m focal distance. Head-locked — turn head, HUD follows. All transitions are 200 ms CanvasGroup.alpha smoothstep coroutines.

### Step 20 — End session

- **Actor**: User taps the End chip (bottom-right corner of Beam Pro screen).
- **Action**: `SessionPicker.OnEndSessionClicked` fires:
  1. Calls `connectionGameObject.SetActive(false)`.
  2. `SophiaConnection.OnDisable` runs → `Cleanup()` method.
  3. Cleanup stops the mic, disconnects from the room (sends LeaveRequest to SFU), destroys all `SophiaSpeaker_<sid>` child GameObjects.
- **SFU side**: Sees participant leave. Sends `RoomDisconnected` to the agent. Agent's session ends. Worker subprocess exits.
- **UI**: Picker UI re-shows, ready for next session.

### What's DIFFERENT from the browser flow (side-by-side)

| Aspect | Browser | Glasses |
|---|---|---|
| Token endpoint | Next.js `/api/token` at port 3000 (open route) | FastAPI `/token` at port 8001 (X-API-Key required) |
| Token-mint reachability | Same-origin (HTTP from page domain) | Cross-origin (CORS allowed by `SOPHIA_CORS_ORIGINS=*`) |
| WebRTC implementation | Chrome's built-in libwebrtc | LiveKit Unity SDK's bundled libwebrtc via FFI |
| Mic API | `getUserMedia({ audio: true })` | Unity `Microphone.Start()` + Android RECORD_AUDIO permission |
| Audio output | DOM `<audio>` element | Unity AudioSource on a child GameObject per agent track (Q58 pattern) |
| Audio routing | OS default (laptop speakers) | Beam Pro → USB Audio Class → glasses speakers |
| UI rendering | React DOM | Unity world-space Canvas (head-locked AR) |
| Text-stream consumption | `room.on('dataReceived')` React handlers | Static C# event `SophiaConnection.OnTextStreamMessage` consumed by SophiaOverlayUI |
| Echo behavior | None (browser AEC handles it) | Echo on Beam Pro alone, killed by glasses temple-speaker geometry (Q41/Q43) |
| Multi-user filtering | LiveKit JS SDK plays all subscribed tracks | Unity filters to `Identity.StartsWith("agent-")` to skip other users' mic tracks (Q58) |

Everything from the SFU outward to the inference services is identical. The differences are all client-side glue.

---

## Q9 (2026-06-02): When a user types `http://3.227.63.49:3000` in their browser, how does the request actually reach our Next.js process? What infrastructure is making this work?

**Six layers, each one had to be set up for the URL to work. If any single layer is missing or misconfigured, the URL fails in a specific way.** Tracing the packet from the user's keyboard to the Next.js process:

### Layer 1 — User's machine (browser + OS)

- User types `http://3.227.63.49:3000` in Chrome's address bar.
- **Browser parses the URL** into three pieces: protocol = `http`, host = `3.227.63.49`, port = `3000`. The path is `/` by default.
- **DNS lookup is SKIPPED** — `3.227.63.49` is already an IP address, not a hostname. Production with a real domain (e.g. `sophia.example.com`) would do a DNS A-record lookup here. We don't have a domain yet, so this layer is trivial for our MVP.
- **Browser asks the OS to open a TCP socket** to `3.227.63.49:3000`. OS picks an ephemeral source port (e.g. `54321`).
- **OS consults routing table**: destination not on local network → send via default gateway (the home router).
- **Packet leaves user's machine**: source `<user-public-IP>:54321`, destination `3.227.63.49:3000`, TCP SYN flag set (start of three-way handshake).

If this layer fails: it doesn't really — browser + OS + ISP routing are reliable. Mentioned for completeness.

### Layer 2 — Public internet routing

- The packet hops through ISP routers using BGP (the Border Gateway Protocol that routes IP blocks across the internet).
- AWS owns the IP block that contains `3.227.63.49` — they announce that prefix in BGP, so all routers on the internet know "for this destination, send packets toward AWS."
- After ~5-15 hops the packet reaches an AWS edge router somewhere in us-east-1 (the region where AWS allocated this IP to our account).
- **No setup needed on our side** — AWS handles BGP advertisement for all IPs they allocate to customers.

If this layer fails: you'd see issues like ISP outage, or AWS regional outage. Not something we control.

### Layer 3 — AWS network → our VPC → the EC2 instance

This is where AWS-specific infrastructure matters. Four things had to be in place:

**a) The Elastic IP allocation.** AWS allocated `3.227.63.49` to our account when the infra team provisioned the EC2 setup. This is a static IP (defined as `aws_eip.gpu` in the Terraform at `AIPartnersUSA/aws-infra/environments/single_g5x2large_us_east_1/main.tf`). **Why Elastic IP and not just the default public IP**: default public IPs CHANGE every time you stop+start the instance. Elastic IPs persist across stop/start. Without an EIP, `3.227.63.49` would be a different machine tomorrow.

**b) The EIP is ASSOCIATED with our EC2 instance.** The Terraform binds the EIP to the instance's ENI (Elastic Network Interface). AWS maintains a 1:1 NAT mapping: incoming packets to `3.227.63.49` get rewritten with destination `10.20.1.90` (the instance's private IP) before delivery. Outgoing packets get the reverse rewrite.

**c) The VPC has an Internet Gateway.** Our VPC is `vpc-0eeab16713f4f744d` at CIDR `10.20.0.0/16`. The Terraform defines `aws_internet_gateway.ai` attached to that VPC. The IGW is the actual component that AWS-network packets traverse to reach the public internet (and vice versa). Without an IGW, even with an EIP, packets couldn't enter or leave.

**d) The public subnet routes to the IGW.** Our subnet `aws_subnet.public` at `10.20.1.0/24` has a route table with a default route `0.0.0.0/0 → IGW`. The EC2 lives in this subnet (private IP `10.20.1.90`). Without this route, the instance would have no path to the internet.

The packet arrives at the instance's ENI as: source `<user-public-IP>:54321`, destination `10.20.1.90:3000`.

If this layer fails: usually a Terraform misconfiguration during setup. Diagnose with `aws ec2 describe-instances`, `aws ec2 describe-route-tables`. Not a day-to-day failure mode.

### Layer 4 — AWS Security Group (the firewall, default-deny)

**This is the layer that bit us most during deployment** — see Problem 10 in `mvp_deployment_shared_ec2.md`.

- AWS Security Groups are stateful packet filters that run at the hypervisor level, BEFORE the packet reaches the instance kernel.
- **Default policy is DENY all inbound.** Only explicitly-listed rules let traffic through.
- Our SG is `sophiaspatialai-gpu-...`, defined in the same Terraform as the rest of the infra (file: `environments/single_g5x2large_us_east_1/main.tf`).
- Relevant ingress rule for our case:
  ```hcl
  ingress {
    description = "Sophia voice agent frontend"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs   # defaults to ["0.0.0.0/0"]
  }
  ```
- Because `var.allowed_cidrs` defaults to `0.0.0.0/0`, this rule allows TCP port 3000 from ANY source IP. **That's what makes the URL reachable from anywhere on the internet.**
- This rule was added by the PR Aziz merged + applied on 2026-05-29 (Phase 13 in the MVP doc). Before that day, port 3000 was NOT in the SG → connections silently dropped → browser hung for ~30s then timed out.

If this layer fails: the symptom is `curl: (28) Connection timed out` (NOT `Connection refused`). The packet hits the hypervisor, SG evaluates the rules, no match, packet silently dropped. From the client side it looks like the server is unreachable. Diagnose with `aws ec2 describe-security-groups`.

After the SG passes the packet, it gets delivered to the EC2 instance's ENI.

### Layer 5 — EC2 instance kernel + listening process

- The Linux kernel on the EC2 receives the packet on `eth0` (the only network interface).
- Kernel looks at the destination port (3000), checks its socket table, finds: a process listening on `0.0.0.0:3000`.
- That process is the Next.js production server (started via `nohup npm start -- --port 3000 --hostname 0.0.0.0 ...`). Specifically, `npm start` spawns a Node.js process named `next-server` that binds the socket.
- Kernel hands the SYN packet to the Node.js process → process responds with SYN-ACK → TCP handshake completes → connection established.
- **Critically**: this process is NOT inside Docker. The Next.js frontend runs natively on the EC2 via `npm start`, not via docker-compose. So no docker port mapping is involved here — the process binds directly on the host's port 3000.

If this layer fails: the symptom is `curl: (7) Failed to connect to 3.227.63.49 port 3000: Connection refused` (NOTE — different from SG-blocked which is "timed out"). "Refused" means the SG let the packet through, but no process is listening. Diagnose on EC2 with `ss -tlnp | grep :3000` (should show `node` listening) or `ps -ef | grep next`.

### Layer 6 — Next.js serves the response

- Node.js process accepts the TCP connection.
- Reads the HTTP request: `GET / HTTP/1.1\r\nHost: 3.227.63.49:3000\r\nUser-Agent: ...\r\n\r\n`.
- Looks at the path (`/`), finds the matching React page (built into `.next/server/app/`).
- Returns `HTTP/1.1 200 OK` with the prebuilt HTML containing `<script src="/_next/static/.../main.js">...` references.
- Browser then makes follow-up GET requests for each JS bundle, also routed through layers 1-5.
- React app boots in the browser → renders the welcome screen with the Start Call button.

### Failure-mode mapping

| Symptom | Layer that broke | How to confirm |
|---|---|---|
| "Connection timed out" | Layer 4 (SG missing rule) | `aws ec2 describe-security-groups --group-ids sg-xxx` from your laptop; or `curl -sI --max-time 5 http://3.227.63.49:3000` shows hang |
| "Connection refused" | Layer 5 (process not running) | On EC2: `ss -tlnp \| grep :3000` empty; check `frontend.log` |
| "Could not resolve host" | Layer 1 (DNS) — N/A for IP, but happens with bad domain | `ping <hostname>` returns "Unknown host" |
| "No route to host" | Layer 3 (rare — IGW or route table misconfigured) | `aws ec2 describe-route-tables`; usually a Terraform issue |
| Connects but page is blank / errors | Layer 6 (Next.js process is up but broken) | `tail frontend.log`; common = the production build fixes from Problems 8, 9, 14, 16 not applied |
| Mic doesn't work after connecting | NOT a connection issue — Chrome blocks `getUserMedia` on non-secure-context HTTP from public IP. Workaround = `chrome://flags#unsafely-treat-insecure-origin-as-secure` (Problem 15). |

### What's NOT in this flow today but WOULD be in production

- **DNS** — a domain like `sophia.example.com` → A-record → `3.227.63.49`. Adds a DNS lookup hop. Required for users to remember the URL.
- **TLS / HTTPS** — request would go to port 443, get terminated by nginx / ALB / cloudfront, decrypted, then forwarded to Next.js on port 3000 (or kept on 443 if Next.js handles TLS itself). Required for browser mic permission (no Chrome flag needed) and security.
- **CDN** — CloudFront in front would cache static assets globally, dropping latency for distant users.
- **Load balancer** — ALB / NLB for multi-instance HA, health checks, automatic instance replacement.
- **WAF** — Web Application Firewall for rate limiting, bot blocking.

For MVP we skip all of these and rely on the raw EC2 EIP + SG + Next.js process. The URL works because all 6 layers above are in place.

### The condensed "why it works" answer

`http://3.227.63.49:3000` reaches our Next.js process because:
1. AWS allocated us a static Elastic IP `3.227.63.49`.
2. AWS Internet Gateway + VPC routing delivers internet traffic to our instance.
3. AWS Security Group has TCP 3000 open from anywhere (added via the Phase 13 Terraform PR).
4. EC2 instance is running with Node.js (`npm start`) listening on `0.0.0.0:3000`.
5. The browser handles HTTP semantics on top of the TCP connection.

Take any of those five away and the URL stops working with a specific, diagnosable symptom.

---

## Q10 (2026-06-02): I'm confused about the keys. There are multiple "API keys" floating around — `SOPHIA_TOKEN_API_KEY`, the key in `livekit.prod.yaml`, the LiveKit API key the Next.js server uses. Are they different keys? When are they generated? Where does each one live?

**Yes, they're TWO completely separate keys serving two different purposes — except one of them is actually a key+secret PAIR, so the count is THREE distinct secrets in total. Easy to confuse because they're all called "API key" colloquially.** Here's the full picture.

### The three secrets and what each one does

**Secret 1: `LIVEKIT_API_KEY`** (a ~32-hex-char identifier, e.g. `7baeb38a5bfadcfed6a713152b8d1c70`)

- Not really "secret" — it's an IDENTIFIER for who is signing JWTs. Think of it like a username, while the API_SECRET is the password.
- Goes into every minted JWT as the `iss` (issuer) claim.
- Generated by `openssl rand -hex 16` during EC2 setup (Phase 6 in the MVP runbook).

**Secret 2: `LIVEKIT_API_SECRET`** (a ~64-hex-char actual secret, e.g. `d4b851178693ae3bd53bdec3fbfc5f2d4bc494645349e85814f680e195aa16de`)

- The REAL secret. Used as the HS256 signing key for every JWT.
- Anyone who has this can mint JWTs that the SFU will accept → can join any room as any participant. Treat as a password.
- Generated by `openssl rand -hex 32` during EC2 setup.

These two ALWAYS travel together as a PAIR. Wherever one lives, both must live and they must match what's in `livekit.prod.yaml`'s `keys:` block.

**Secret 3: `SOPHIA_TOKEN_API_KEY`** (a ~32-hex-char shared secret, e.g. `9a11fdf5ce05e3cecad28f933d778971`)

- Completely UNRELATED to LiveKit JWTs. This one is just an HTTP-level "are you allowed to call our `/token` endpoint" gate.
- Used by the standalone FastAPI token-mint on port 8001 to check the `X-API-Key` header on incoming POST requests.
- Glasses send this header; browser doesn't (the browser uses a different endpoint).
- Generated by `openssl rand -hex 16` during EC2 setup.

### How they relate (the full topology)

```
                    EC2 backend                                           Clients
┌───────────────────────────────────────────────┐         ┌────────────────────────────────┐
│                                                │         │                                │
│  livekit.prod.yaml (gitignored):              │         │  agent-starter-react/.env.local│
│    keys:                                       │◄────────│  on EC2 (gitignored):          │
│      <LIVEKIT_API_KEY>: <LIVEKIT_API_SECRET>  │  must   │   LIVEKIT_API_KEY=<same>       │
│                                                │  match  │   LIVEKIT_API_SECRET=<same>    │
│  SFU verifies JWTs against this pair          │         │  Next.js server-side route     │
│                                                │         │  signs browser JWTs with this  │
│                                                │         │                                │
│  .env.production (gitignored):                │         │                                │
│    LIVEKIT_API_KEY=<same as livekit.prod.yaml>│         │  Unity SophiaConfig.asset      │
│    LIVEKIT_API_SECRET=<same>                  │         │  (committed in git):           │
│    SOPHIA_TOKEN_API_KEY=<separate secret>     │◄────────│   tokenApiKey=<must match      │
│                                                │  must   │     SOPHIA_TOKEN_API_KEY>      │
│  token-mint signs glasses JWTs with KEY+SECRET│  match  │  Glasses send this in          │
│  AND verifies X-API-Key header with the third │         │  X-API-Key header on /token    │
└────────────────────────────────────────────────┘         └────────────────────────────────┘
```

### Which key is checked where — answering your specific question

**For BROWSER:** The browser does NOT hit the FastAPI token-mint on port 8001. It hits the Next.js `/api/token` route on port 3000 (same origin as the page). That Next.js route reads `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` from `agent-starter-react/.env.local` and signs the JWT directly. **Browser cares about the LiveKit pair (key+secret), nothing about `SOPHIA_TOKEN_API_KEY`.** When the SFU verifies the browser's JWT, it compares the JWT's signature against `livekit.prod.yaml`'s `keys:` block — so those values must match between `livekit.prod.yaml` and `.env.local`.

**For GLASSES:** Glasses hit the FastAPI token-mint at port 8001 with the X-API-Key header. The FastAPI service checks the header against `SOPHIA_TOKEN_API_KEY` (loaded from `.env.production`). If match → the FastAPI signs a JWT using `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` (also from `.env.production`) and returns it. The glasses then use that JWT to connect to the SFU, which verifies it against `livekit.prod.yaml`'s `keys:` block. **Glasses care about both: SOPHIA_TOKEN_API_KEY (to get a token) AND the LiveKit pair (used server-side to sign the token they receive).**

### Where each secret lives (the full table)

| Secret | livekit.prod.yaml (EC2) | sophia-agent/.env.production (EC2) | agent-starter-react/.env.local (EC2) | Unity SophiaConfig.asset (in git) | EC2's .env.production has it? |
|---|---|---|---|---|---|
| `LIVEKIT_API_KEY` (identifier) | ✅ key in `keys:` pair | ✅ as env var | ✅ as env var | ❌ (not needed client-side) | ✅ |
| `LIVEKIT_API_SECRET` (signing key) | ✅ value in `keys:` pair | ✅ as env var | ✅ as env var | ❌ (NEVER ship secrets to clients) | ✅ |
| `SOPHIA_TOKEN_API_KEY` (X-API-Key gate) | ❌ (not LiveKit's concern) | ✅ as env var | ❌ (browser uses a different path) | ✅ as `tokenApiKey` field | ✅ |

Three files on EC2 must agree on the LiveKit pair (livekit.prod.yaml + .env.production + .env.local). Two places must agree on SOPHIA_TOKEN_API_KEY (.env.production + Unity SophiaConfig.asset on the Mac that builds the APK).

### When the keys were generated and placed (the timeline)

From the MVP deployment runbook, Phase 6 was the "generate secrets" step. Done ONCE during initial EC2 setup on 2026-05-26:

```bash
# On the EC2 (run once):
LIVEKIT_KEY=$(openssl rand -hex 16)        # 32 hex chars
LIVEKIT_SECRET=$(openssl rand -hex 32)     # 64 hex chars
TOKEN_API_KEY=$(openssl rand -hex 16)      # 32 hex chars

echo "$LIVEKIT_KEY $LIVEKIT_SECRET $TOKEN_API_KEY"
# Saved to a private note for reuse in later phases.
```

Then placed in five files across Phases 7-12 + the Unity asset:

| Phase | When | What got written |
|---|---|---|
| Phase 7 (Phase 6 secrets in hand) | 2026-05-26, on EC2 | `livekit.prod.yaml` `keys:` block gets `$LIVEKIT_KEY: $LIVEKIT_SECRET`. `.env.production` gets all three as env vars. Both files chmod 600. |
| Phase 12 (frontend build) | 2026-05-26, on EC2 | `agent-starter-react/.env.local` gets `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` (not `SOPHIA_TOKEN_API_KEY` — browser doesn't need it). |
| Glasses repointing (Unity work on Mac) | 2026-05-29, on Avinash's Mac | Unity `SophiaConfig.asset.tokenApiKey` gets the same `$TOKEN_API_KEY` value. APK rebuilt + installed on Beam Pro. |

After that, no key generation has happened. The keys from 2026-05-26 are still the ones running today (~6 days later).

### When to rotate (production migration concern)

For MVP, the keys live indefinitely. For real production (per `HANDOFF.md`):

- Rotate ALL THREE before the demo goes broadly internet-accessible OR before non-trusted users get access. Reason: the LiveKit pair is in this Claude session's chat history (we read `livekit.prod.yaml` content earlier). `SOPHIA_TOKEN_API_KEY` is in git history via `SophiaConfig.asset` (Option B was chosen for MVP speed). Treat all three as compromised for production purposes.
- Rotation procedure: generate three fresh values via `openssl rand -hex N`, update all five locations (livekit.prod.yaml + .env.production + .env.local on EC2; SophiaConfig.asset in Unity), `docker compose down + up -d` on EC2 (because env_file changes need full container recreate per Problem 18), rebuild the APK and reinstall on every Beam Pro that needs the new key.

### Failure modes (which key mismatch causes which symptom)

| Mismatch | Symptom | How to diagnose |
|---|---|---|
| `LIVEKIT_API_KEY` differs between any of {livekit.prod.yaml, .env.production, .env.local} | Browser/glasses get a token but SFU rejects WS connection with "invalid token" | Decode the JWT at jwt.io, check `iss` claim, compare against `livekit.prod.yaml`'s `keys:` left side |
| `LIVEKIT_API_SECRET` differs | Same as above — SFU rejects on signature verification | Same |
| `SOPHIA_TOKEN_API_KEY` differs between .env.production and SophiaConfig.asset | Glasses get HTTP 401 from /token, never get a JWT to begin with | `ssh sophia-gpu "grep SOPHIA_TOKEN_API_KEY /workspace/avinash/sophia/sophia-agent/.env.production"` vs `grep tokenApiKey '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/Assets/Settings/SophiaConfig.asset'` (Problem 17) |
| `SOPHIA_TOKEN_API_KEY` not set on EC2 at all | Glasses succeed without any X-API-Key header (auth disabled, dev mode) | `_require_api_key()` returns early if the env var is empty |
| Browser uses correct keys but glasses use wrong `SOPHIA_TOKEN_API_KEY` | Browser works fine, glasses get 401 | The two paths are independent — browser bypasses SOPHIA_TOKEN_API_KEY entirely |

### Short-form answer to your exact confusion

- "key in livekit.prod.yaml on ec2 should match LiveKit API key from Next.js server" → YES, but actually it's the PAIR (key + secret), not just the key. Both `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` must match between `livekit.prod.yaml` and the Next.js's `agent-starter-react/.env.local`. SFU uses livekit.prod.yaml to VERIFY signatures; Next.js uses .env.local to GENERATE them.
- "API key in scene should match `SOPHIA_TOKEN_API_KEY` on EC2" → YES. Unity `SophiaConfig.asset.tokenApiKey` field must match `.env.production`'s `SOPHIA_TOKEN_API_KEY`. This gates whether the glasses can even reach `/token` — has nothing to do with the JWT itself.
- "Are they different keys? `SOPHIA_TOKEN_API_KEY` and key in livekit.prod.yaml?" → YES. Completely different keys, different purposes, different files, generated by separate `openssl rand` calls. They never interact.
- When generated: ONCE at EC2 setup (2026-05-26), via three separate `openssl rand` calls.
- When placed: Phase 7 wrote livekit.prod.yaml + .env.production on EC2. Phase 12 wrote .env.local for the frontend on EC2. Glasses-repointing day (2026-05-29) wrote the SOPHIA_TOKEN_API_KEY value into the Unity SophiaConfig.asset on Avinash's Mac, then rebuilt the APK.

---

## Q11 (2026-06-02): I want to give the codebase to the infra team for deployment. Local, GitHub remote, and EC2 don't look identical — EC2 has files like `docker-compose.yml` etc. that I'm not sure are in local. Which codebase do I give them, and how do I make sure all three are the same and working?

**Premise correction first: the CODE is already identical across all three machines. What you're seeing on EC2 that ISN'T on local Mac are NOT extra code files — they're SECRETS + RUNTIME ARTIFACTS that are intentionally gitignored.** This is the correct security posture, not a misalignment to fix.

### Verification — local, EC2, and GitHub are at the same commit

Just verified 2026-06-02 (this session):

```bash
# LOCAL Mac:
$ git log --oneline -1
85c8df3 Add Q10: three keys explained (...)
$ git status
nothing to commit, working tree clean

# EC2:
$ git log --oneline -1
85c8df3 Add Q10: three keys explained (...)
$ git status
nothing to commit, working tree clean
```

Both at commit `85c8df3`. Working trees clean. Every tracked file in the repo is byte-identical between LOCAL Mac, EC2, and GitHub.

### About docker-compose.yml specifically

You mentioned EC2 has `docker-compose.yml` at `/workspace/avinash/sophia/` that you weren't sure was in local. **It IS in the repo.** Verified:

```bash
$ git ls-files | grep -E '^docker-compose\.yml$'
docker-compose.yml
```

It's tracked at the REPO ROOT. The version on your Mac at `/Users/avinashbolleddula/Documents/sophia Agent Research/docker-compose.yml` and the one on EC2 at `/workspace/avinash/sophia/docker-compose.yml` are the same file — same content, came from the same commit. You can verify with `diff` or `git diff`.

### What's actually on EC2 that's NOT on local Mac (and intentionally NOT in git)

Seven items, all categorized:

```
agent-starter-react/.env.local            ← SECRET (LIVEKIT_API_KEY/SECRET for Next.js)
agent-starter-react/.next/                ← BUILD ARTIFACT (output of `npm run build`)
agent-starter-react/next-env.d.ts         ← BUILD ARTIFACT (auto-generated by Next.js)
agent-starter-react/node_modules/         ← INSTALLED DEPS (npm install regenerates from package-lock.json)
frontend.log                              ← RUNTIME LOG (output of `npm start`)
sophia-agent/.env.production              ← SECRET (LIVEKIT keys + SOPHIA_TOKEN_API_KEY + inference URLs)
sophia-agent/infra/livekit.prod.yaml      ← SECRET (LiveKit signing key+secret inline)
```

All seven are excluded by the various `.gitignore` files. Three of them (the secrets) have committed `.example` templates that document their schema. Four of them are regeneratable from source (build artifacts, runtime logs, installed deps).

**This is the correct pattern.** Secrets and build artifacts NEVER belong in git. The repo is portable; secrets are environment-specific.

### What the infra team actually needs from you

A repo URL + access. That's the entire handoff. Not a tarball, not a snapshot.

Step-by-step:

1. **Give them the GitHub repo URL**: `git@github.com:AIPartnersUSA/sophia-agent-research.git`.
2. **Add them as Collaborators with Read access** on GitHub (Settings → Collaborators). For active development they'd want Write too.
3. **Point them at `HANDOFF.md`** as the entry point. That doc tells them:
   - What's in/not-in the repo (the same answer as this Q).
   - What architecture to preserve (host networking for SFU, etc.).
   - What to build for production (k8s manifests, real auth, TLS, CI/CD).
   - 12-step recommended migration sequence.
   - Things NOT to do.

When they want to BRING UP THEIR OWN INSTANCE (which is what production deployment means — separate from your shared EC2):

1. Clone the repo. `git lfs pull` for the Unity SDK binaries.
2. Generate THEIR OWN secrets (don't reuse yours):
   ```bash
   openssl rand -hex 16   # → LIVEKIT_API_KEY
   openssl rand -hex 32   # → LIVEKIT_API_SECRET
   openssl rand -hex 16   # → SOPHIA_TOKEN_API_KEY
   ```
3. Copy the three `.example` templates to their non-example siblings and fill in the values:
   - `cp sophia-agent/.env.production.example sophia-agent/.env.production` → edit
   - `cp sophia-agent/infra/livekit.prod.yaml.example sophia-agent/infra/livekit.prod.yaml` → edit
   - `cp agent-starter-react/.env.local.example agent-starter-react/.env.local` → edit
   - `chmod 600` each of the three real files.
4. For production they'd replace step 3 with their secrets manager of choice (AWS Secrets Manager + External Secrets Operator is the recommended pattern from HANDOFF.md).
5. `docker compose up -d`. The same workspace-root `docker-compose.yml` that runs on YOUR EC2 will run on theirs.
6. Open AWS SG ingress for the required ports (TCP 3000/7880/7881/8001 + UDP 50000-60000) — they'd write their own Terraform / IaC for this.
7. They'd write k8s manifests / ArgoCD config to replace the docker-compose pattern for real production scale.

The handoff is: code (from git) + setup procedure (HANDOFF.md + mvp_deployment_shared_ec2.md) + secret templates (.env.*.example). The actual secret VALUES never leave your control.

### Why the secrets pattern is what you want, not a problem to fix

Imagine you committed `livekit.prod.yaml` with the real signing secret. Then:
- Anyone with read access to the GitHub repo (Collaborators, departing employees, GitHub itself, accidental public-toggle) can join any room as any participant on your EC2.
- Rotating the secret means a commit, a push, a force-rewrite of history (because old commits still contain it), and all consumers updating.
- Different environments (staging, prod, dev) can't have different secrets without branches-per-environment or convoluted templating.

The gitignored-with-template pattern fixes all of this:
- Repo contents are safe to share, fork, screenshot.
- Each environment has its own secrets in its own runtime files.
- Rotation is updating runtime files + restarting containers, no git involvement.
- Templates in git document what fields exist without exposing values.

This is industry-standard (12-factor app's "store config in the environment" principle). Don't try to "fix" the local-vs-EC2 file difference — it's the design.

### How to PROVE to yourself + infra that the three are aligned

```bash
# On LOCAL Mac:
cd "/Users/avinashbolleddula/Documents/sophia Agent Research"
git log --oneline -1
git status
git rev-parse HEAD       # prints the full SHA

# On EC2:
ssh sophia-gpu
cd /workspace/avinash/sophia
git log --oneline -1
git status
git rev-parse HEAD       # should print the same SHA

# On GitHub (in browser):
# Visit https://github.com/AIPartnersUSA/sophia-agent-research/commits/main
# Top commit should have the same SHA.
```

If all three SHAs match and both `git status` outputs say "nothing to commit, working tree clean", you have full alignment. Currently true (commit `85c8df3` as of session end 2026-06-02).

### Short-form answer

- The CODE is already identical across LOCAL Mac, GitHub remote, and EC2 — all at commit `85c8df3`.
- The EC2 has 7 extra files that you correctly noticed, but those are NOT code. They're secrets (3 files) + build artifacts / runtime logs (4 files). All intentionally gitignored.
- Your handoff to infra = (a) GitHub repo URL, (b) point them at HANDOFF.md, (c) they generate their own secrets via the `.env.*.example` templates. Don't ship secret values; ship templates.
- No "snapshot" or "tarball" needed. The repo at any of the three locations is the canonical artifact — they all produce the same code when cloned + `git lfs pull`.

---

## Q12 (2026-06-02): My XR engineer has a working voice agent loop WITHOUT LiveKit. We want to integrate LiveKit orchestration into his codebase. (1) What benefits does LiveKit give over whatever he has now? (2) What do we need from him (codebase shape like sophia-glasses) before we can integrate?

### Part 1 — Why LiveKit at all

Without LiveKit, a "voice agent loop" typically looks like one of these:

- **Push-to-talk over HTTPS**: user holds a button → app records audio with `Microphone.Start()` → on release, POSTs the audio blob to STT → gets text → POSTs to LLM → gets response → POSTs to TTS → gets audio → plays via AudioSource.
- **Custom WebSocket protocol**: app opens a WS to a server, streams audio frames, server streams back transcript + TTS audio chunks. Has to invent the framing, reconnect logic, encoding.
- **Polling-based**: app uploads audio, polls a status endpoint, downloads result.

All of these work but they all hand-roll problems that LiveKit + WebRTC have already solved. Here's what LiveKit gives you that's painful or impossible to build yourself:

**1. Full-duplex real-time audio (the BIG one).** WebRTC lets the user and agent both transmit audio AT THE SAME TIME. User can INTERRUPT the agent mid-sentence ("barge-in"). The agent stops talking the moment the user starts. Without WebRTC, you're stuck with PTT or "wait for AI to finish" patterns that feel unnatural.

**2. No reinventing WebRTC.** WebRTC handles: Opus codec encoding/decoding, jitter buffer (smoothing out network packet timing), packet loss concealment (FEC + retransmission), echo cancellation negotiation, adaptive bitrate (slows down audio quality on bad networks instead of dropping), NAT traversal (STUN/TURN for participants behind firewalls), DTLS-SRTP encryption end-to-end. Implementing any one of these from scratch is a multi-week project. WebRTC libraries (libwebrtc in the LiveKit Unity SDK) handle all of them transparently.

**3. Server-side agent orchestration framework.** The LiveKit Agents Python framework (`livekit-agents`) handles VAD (Silero), turn detection (when to stop listening to user), STT/LLM/TTS plugin wiring, streaming TTS that starts playing the response as the LLM tokens arrive, AEC warmup, interrupt detection. You write Python that says "use Whisper for STT, Qwen for LLM, Kokoro for TTS, here's my system prompt," and the framework runs the loop. Without it, you'd write the orchestration state machine yourself in client code.

**4. Streaming TTS as LLM tokens arrive.** With direct HTTP, you wait for the full LLM response, then send to TTS, then wait for full TTS audio, then play. End-to-end latency = sum of all steps. With LiveKit's streaming pipeline, the agent sends each TTS chunk to the user's speaker as soon as the LLM emits a sentence-fragment. User hears the start of the answer ~1 second after they stop talking. Without streaming TTS, that latency is 3-5 seconds.

**5. Standard cross-platform protocol.** LiveKit clients exist for: JavaScript (browser), Unity (what we use for XREAL), Swift (iOS/visionOS), Kotlin (Android native), Flutter, Python, React Native. Any of them can join the same room and exchange the same audio + data tracks. Switching platforms or adding a new client type costs hours, not days. With a custom WS protocol you'd implement the client three times.

**6. Data channels for UI updates.** Alongside audio, LiveKit lets you publish JSON messages on named "topics" (we use `sophia.agent_events`, `sophia.rag_result`, `lk.transcription`). Both browser and glasses subscribe and update their UI in real time — state pill, scrolling transcript, RAG source chips, all without an HTTP polling loop or separate WebSocket. Without it, UI updates lag behind audio or require a parallel side-channel.

**7. Multi-participant support out of the box.** A "room" can have N users + the agent. Everyone subscribes to everyone else's audio + data. Useful for collaborative scenarios (Scenario A in our demo: browser user + glasses user share a room, both talk to Sophia, both hear each other and Sophia). Without LiveKit you'd build an SFU yourself, which is a months-of-work project (LiveKit IS an SFU).

**8. Production-grade scaling story.** LiveKit's worker dispatch model: register N agent-worker processes against the SFU, each new room is dispatched to an available worker, scale workers horizontally to handle concurrent sessions. SFU itself can cluster with Redis for HA. This is built-in, not a custom dispatcher.

**9. AEC + echo behavior on browser is automatic.** Chrome/Safari/Firefox apply hardware AEC + noise suppression to mic input when WebRTC is in use. Direct HTTPS audio upload doesn't trigger this; you'd have to do echo cancellation server-side or implement it yourself.

**10. Observability tools.** `lk` CLI inspects rooms, participants, tracks live. WebRTC stats API gives jitter, packet loss, codec choice per peer connection. Debugging "why is the audio bad" is straightforward. Custom protocols give you whatever you logged manually.

**11. Recording (when you need it later).** LiveKit Egress can record full sessions (audio, video, data tracks) to S3 / GCS with one config change. Important for compliance / training data.

**Costs / downsides** to be honest about:

- WebRTC requires open UDP ports (50000-60000 in our case). Some corporate networks block this; LiveKit has TCP fallback (port 7881) which works but is higher latency.
- The LiveKit Unity SDK adds ~150 MB to the APK (FFI binaries for libwebrtc per platform). Vendored via Git LFS in our case.
- WebRTC is more complex than HTTP. Debugging requires understanding ICE candidates + DTLS handshake (rare, but real).
- LiveKit-Cloud-vs-self-hosted choice — we chose self-hosted for full OSS; LiveKit Cloud would be a managed service at additional cost.

**For Sophia specifically**, the deciding factors were: barge-in (XREAL glasses demo feels broken without interrupt), streaming TTS (latency), multi-participant (future demos with multiple users in a room), and the LiveKit Agents framework taking ~1 week of orchestration code off the table.

If the XR engineer's current loop is PTT-based with multi-second latency and no interrupt, switching to LiveKit alone makes the agent feel ~3x more natural.

### Part 2 — What we need from the XR engineer before integration

Mirrors `xr_build_voice_integration.md` Q1-Q7. Here it is in actionable form — the literal artifacts + answers we need before touching anything:

**A. A clone or copy of his codebase.** Not just screenshots. We need to read the project structure, scene hierarchy, his existing audio code, his existing UI code. If it's git-hosted, share the URL. If not, a zip of the project directory excluding `Library/`, `Temp/`, `node_modules/`, build outputs (basically anything in our `.gitignore`).

**B. Answers to seven questions** (sourced from `xr_build_voice_integration.md`):

1. **Platform**: What XR target? XREAL One Pro? Meta Quest 2/3/Pro? Apple Vision Pro? HoloLens? Pico? Other? (Determines audio routing, permission model, SDK choice.)
2. **Engine + version**: Unity? Unreal? Native Android/iOS? If Unity, which version (Unity 6, 2022 LTS, 2021 LTS, older)? (Determines whether our scripts drop in or need adaptation.)
3. **Existing session/room model**: Does his app already have multiplayer / networking / room management? Or single-player? (Determines Drop-in vs Custom integration path.)
4. **Existing microphone code**: Does he already call `Microphone.Start()` somewhere? Does he have audio capture wired? (Determines if his mic code conflicts with LiveKit's `MicrophoneSource` — usually we'd let LiveKit own the mic.)
5. **Existing audio playback**: How does he currently play AI responses? `AudioSource` on which GameObject? (Determines if we drop in our Q58 child-GameObject pattern or wire into his existing audio.)
6. **Existing UI**: Does he have a world-space UI canvas already? How does he render the AI's spoken text / state / sources? (Determines if we drop in `SophiaOverlayUI.cs` or have him subscribe to the static `OnTextStreamMessage` event and render in his style.)
7. **Backend target**: Will his app point at OUR shared EC2 (3.227.63.49) for the demo, or does the infra team need to deploy a parallel backend for him? (Determines what URL goes in his SophiaConfig.)

**C. Codebase structure expectations.** Once we have his project + answers, we'd map the integration like this. The shape we'd aim for (mirroring `sophia-glasses/unity/Assets/Scripts/`):

```
<his-unity-project>/Assets/Scripts/
├── <his existing scripts>            ← untouched
├── SophiaConfig.cs                   ← NEW (copied from us, ScriptableObject schema)
├── SophiaConfig.asset                ← NEW (instance with EC2 URLs + tokenApiKey)
├── SophiaSessionContext.cs           ← NEW (static state)
├── SophiaConnection.cs               ← NEW (voice loop, copied from us, possibly trimmed)
└── (optional) SophiaOverlayUI.cs    ← NEW if he doesn't have his own UI; SKIP if he does
```

Plus in his `Packages/manifest.json`:
```json
"io.livekit.livekit-sdk": "file:../../client-sdk-unity"
```
(if vendoring like we did) or a UPM Git URL pointing at LiveKit's upstream repo.

Plus the LiveKit Unity SDK + (if XREAL target) XREAL SDK vendored or installed via UPM.

**D. Conflict surfacing.** Once we have the codebase + answers, we'd surface conflicts BEFORE integrating:

- "Your `<HisAudioManager>.cs` already calls `Microphone.Start(0)`. LiveKit's `MicrophoneSource` will also try to open mic 0 → conflict. Plan: either rip out your mic code and let LiveKit own it, OR keep yours and feed the AudioClip into LiveKit as a custom `LocalAudioTrack`."
- "Your scene's MainCamera is `XRRig/Camera Offset/Main Camera`. Our `SophiaOverlayUI.cs` parents to `Camera.main` at hardcoded `z=2`. Plan: change the parenting / focal distance to match your XR rig."
- "Your bundle ID is `com.companyname.appname`. Our APK is `com.UnityTechnologies.com.unity.template.urpblank`. No conflict — but he gets to keep his bundle ID."
- etc.

**E. Decision: Drop-in vs Custom integration path** (covered in detail in `xr_build_voice_integration.md`):
- **Drop-in** (3-4 hours): bring all 5 of our scripts + the asset. Use SessionPicker + SophiaOverlayUI as-is. Cleanest if his app doesn't already have session/UI conventions.
- **Custom integration** (1-2 days): bring only SophiaConfig + SophiaSessionContext + SophiaConnection. Skip SessionPicker (use his entry point) + SophiaOverlayUI (subscribe to static event, render in his style). Cleaner if his app has sophisticated existing patterns.

### Concrete next steps to propose to your XR engineer

1. **Read `xr_build_voice_integration.md`** at the repo root. That doc IS the integration plan, distilled.
2. **Share his codebase** (git URL or zip).
3. **Answer the 7 questions** in that doc (platform, engine version, existing session model, mic code, audio playback, UI canvas, backend target).
4. **We meet for 30 min** to look at his code together, surface conflicts, pick integration path.
5. **Do a "hello world" first** — just the voice loop, no HUD, no fancy UI. Have him speak through his app, Sophia answers. Validates token + room + audio.
6. **Then layer UI** — either drop in `SophiaOverlayUI` or wire into his existing UI via the static event.
7. **Then platform polish** — FOV-specific HUD sizes, mic gain, echo behavior, etc.

Total estimated time for a working integration on a Unity project: half a day for greenfield (Drop-in), 1-2 days for sophisticated existing app (Custom).

### Short-form answer

**Why LiveKit**: real-time full-duplex audio with barge-in, streaming TTS, server-side agent orchestration framework, cross-platform clients, built-in data channels for UI, multi-participant support, production-grade scaling — none of which you'd want to build yourself.

**What we need from him**: (a) his codebase (git URL or zip), (b) answers to the 7 questions in `xr_build_voice_integration.md` (platform, engine version, existing session model, existing mic/audio/UI code, backend target), (c) 30 minutes together to map the integration. Once we have all that, we pick Drop-in or Custom integration path, copy 3-5 scripts from `sophia-glasses/unity/Assets/Scripts/` into his project, add the LiveKit Unity SDK to his Packages/manifest.json, wire one GameObject, build + test. Half a day to 2 days depending on existing app complexity.

---

## Q13 (2026-06-02): I gave you the XR engineer's git URL. What does his codebase look like, and how does that change the integration recommendation?

Cloned `git@github.com:AIPartnersUSA/Sophia_Xreal-U2.git` (development branch, head `cfae9f73 v3.12.1`) into project root as `Sophia_Xreal-U2/` (gitignored as a reference clone, NOT tracked in our repo). With LFS smudge skipped — text + source files only, no binary assets needed for research.

### What he has — top-level findings

It's a sophisticated existing wearable XR client with a CLEAN provider-abstraction pattern. Much more mature than I assumed before seeing it.

- **Unity version**: 6000.3.12f1 (Unity 6, slightly newer minor than ours but same major).
- **XREAL SDK installed** (`com.xreal.xr` UPM package). Same target hardware as us.
- **AR Foundation 6.3.3** with ARCore + ARKit + XR Hands + XRI 3.3.1 + OpenXR 1.14.0. More mature AR stack than our sophia-glasses setup.
- **Netcode for GameObjects 2.11.0** — they already have multiplayer infra.
- **Plus**: Convai's OpenAI Unity package, NativeWebSocket Unity lib, UnityGLTF, Recorder, etc.
- Repo layout: `Sophia_Wearable/` (the Unity client), `Sophia_UnityServer/` (optional local test server for AWS parity), `AWS_References/` (handoff docs to AWS), `Planning_References/`, `docs/`, `tools/`.
- README documents 5 distinct gateway integrations: OpenAI Realtime, Whisper STT, Vision (Google + Qwen), Product DB, Self-hosted Voice Relay.
- Cursor IDE conventions visible (`.cursor/rules/`, `.cursor/skills/`) — he's using Cursor as his AI-augmented dev environment.

### The KEY insight — they already have a Provider plug-in pattern

The Conversational AI module has clean abstractions:

```
Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/
├── Abstractions/          ← interfaces (the contract for providers)
│   ├── ILLMProvider.cs
│   ├── IAudioProvider.cs
│   ├── IVisionProvider.cs
│   └── IToolRegistry.cs
├── Providers/             ← concrete implementations of those interfaces
│   ├── OpenAI/            (OpenAI Realtime API integration)
│   ├── Gemini/
│   ├── GoogleVision/      (vision provider)
│   └── VoiceRelay/        (their CUSTOM self-hosted WSS path)
│       └── VoiceRelayLlmProvider.cs
├── Core/                  (orchestration: AIContextOrchestrator, ProviderManager, etc.)
├── Config/                (ProviderConfig — config-driven provider selection)
├── UI/, Hud/              (their existing UI for transcripts / state / etc.)
├── Services/, Tools/, Personas/, Common/
└── Sophia.ConversationalAI.asmdef   (Unity Assembly Definition — clean module boundary)
```

Their `ProviderFactory` selects which provider to use at runtime based on `ProviderConfig.awsSingleEndpointConversationPipeline`. Switching providers is a config change, not a code change. Each provider implements `ILLMProvider` with events like `OnAudioReceived`, `OnTranscriptReceived`, `OnUserSpeaking`, `OnAgentSpeaking`, `OnError`, etc.

**This is a much better integration surface than I described in Q12.** They've already done the architectural work — we just plug in.

### What VoiceRelayLlmProvider does (and why it overlaps with LiveKit)

Their `VoiceRelayLlmProvider.cs` is a 700+ line `MonoBehaviour` that:

1. Opens a JSON WebSocket to `wss://<host>/ws` (gateway-routed).
2. Sends `{type: "config", voice, system_prompt, ...}` once.
3. Streams 16 kHz PCM16 mono mic chunks as `{type: "audio", data: <base64>}` continuously.
4. Receives `{type: "transcript"}`, `{type: "audio"}` (TTS frames at 24 kHz), `{type: "audio_end"}`, `{type: "error"}` from the server.
5. Sends `{type: "interrupt"}` for barge-in.
6. Exposes events that other modules subscribe to (transcripts, audio, agent-speaking state).

**This is exactly what LiveKit gives them, except over a standardized WebRTC protocol with better real-time audio handling.** Reference server at `AWS_References/Reference_Materials/Archive/main.py` — they aligned with the `agentic-infra/voice_relay` upstream.

### What changes about the integration recommendation

Forget the Drop-in / Custom paths from Q12 — those were for greenfield. **The right pattern for him is "add a new Provider":**

1. **Create `LiveKitLlmProvider.cs`** in `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/`. Mirror the shape of `VoiceRelayLlmProvider.cs`.
2. **Implement `ILLMProvider`** — the same interface VoiceRelay implements. Wire the existing events (OnAudioReceived, OnTranscriptReceived, OnUserSpeaking, OnAgentSpeaking, OnError) to LiveKit's track-subscribed + text-stream events.
3. **Internally use the LiveKit Unity SDK** — token fetch (UnityWebRequest to FastAPI token-mint with X-API-Key), Room.Connect, MicrophoneSource publish, track subscription. Same patterns from our `SophiaConnection.cs` but wrapped in his ILLMProvider contract.
4. **Add to `ProviderFactory`** — a new selection arm: `ConversationProviderType.LiveKit` → return new `LiveKitLlmProvider()`.
5. **Extend `ProviderConfig`** — add a `LiveKitConfig` block (URL, tokenEndpoint, tokenApiKey, agentName) matching our SophiaConfig.asset schema.
6. **Add LiveKit Unity SDK to `Sophia_Wearable/Packages/manifest.json`** — either vendor our `sophia-glasses/client-sdk-unity/` (Git LFS) or UPM Git URL pointing at upstream.

### What we KEEP UNTOUCHED in his codebase

Everything else. Specifically:
- Their scene, XR rig, AR Foundation setup, camera, controller mappings.
- Their UI (`UI/`, `Hud/`) — they already have transcript rendering, state pills, etc. wired to `OnTranscriptReceived` / `OnAgentSpeaking` events from the provider. New provider fires the same events → UI works without changes.
- Their `AIContextOrchestrator`, `ProviderManager`, `ToolPermissionManager`, etc. — orchestration layer is provider-agnostic.
- Their multiplayer (Netcode for GameObjects) — could LATER be enhanced to map Netcode rooms to LiveKit rooms, but not required for v1.
- Their mic capture path (`MicrophoneStreamer`) — IF they want to share mic between providers, we'd wire it in. If LiveKit's `MicrophoneSource` is fine for the LiveKit provider, we let LiveKit open the mic.
- Their build settings, bundle ID, assembly definitions, ProjectSettings.

### Effort estimate (revised down from Q12)

- **Provider integration only (no UI work)**: 1-1.5 days. Write LiveKitLlmProvider.cs (~500-700 lines), wire ILLMProvider events, add to ProviderFactory, add LiveKitConfig, add SDK to manifest, build + smoke-test against EC2.
- **Optional polish**: another 0.5-1 day for tuning audio levels, AEC behavior on his target hardware, possibly hooking up the existing UI events to LiveKit's text-stream topics (sophia.agent_events, sophia.rag_result, lk.transcription).

Half the original 2-day estimate from Q12 because we don't need to drag in SessionPicker / SophiaOverlayUI / our scene setup. His existing app already has all of that.

### Concrete next steps

1. **Read his `ILLMProvider.cs` interface in full** — that's the contract our new provider must satisfy. (TODO when starting integration work — file at `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Abstractions/ILLMProvider.cs`.)
2. **Read his `VoiceRelayLlmProvider.cs` in full** — that's our template. Same shape, just LiveKit instead of WSS.
3. **Read his `ProviderFactory`** and `ProviderConfig` — understand how providers are selected.
4. **Confirm the backend target with him**: will his LiveKitLlmProvider point at OUR shared EC2 (3.227.63.49) for initial testing? Or does his infra team need to deploy a parallel backend? (Easy answer: use ours for v1 — same X-API-Key + LiveKit pair we already have.)
5. **Branch strategy**: when we actually start writing `LiveKitLlmProvider.cs`, we `git checkout -b feat/livekit-provider` off `development` in his repo. All work goes on that branch, PR back to `development` for review.

### Short-form answer

His codebase is a mature wearable XR client with a CLEAN provider-abstraction pattern (`ILLMProvider` interface, `ProviderFactory` runtime selection). He already has a custom WSS voice relay (`VoiceRelayLlmProvider.cs`) that does STT→LLM→TTS — LiveKit would be a NEW provider next to it, not a replacement of his entire client. Integration is now "write `LiveKitLlmProvider.cs` implementing `ILLMProvider`, plug into `ProviderFactory`, add SDK to manifest" — 1-1.5 days of focused work, zero changes to his scene, UI, AR setup, or multiplayer code. Much cleaner than dropping in SophiaConnection/SessionPicker/SophiaOverlayUI like we'd have to do for a greenfield project.

---

## Q14 (2026-06-02): Let me confirm my understanding. Currently `sophia-glasses/` (Unity for XREAL + Beam Pro) talks to `sophia-agent/` (the backend deployed on EC2) and the agent-worker reaches EKS for the inference models. The integration goal is for `Sophia_Xreal-U2/` (the XR engineer's client) to ALSO use `sophia-agent/` as its backend — is that right?

**Yes, your understanding is correct.** Both clients aim at the same backend. Two clarifying precisions so the mental model is exact:

### What "uses sophia-agent/ as backend" actually means

`sophia-agent/` (this repo) is the SOURCE CODE for two of the three EC2 containers:
- `agent-worker` container is built from `sophia-agent/Dockerfile` (loads `src/agent.py` — the LiveKit Agents worker that orchestrates STT→RAG→LLM→TTS).
- `token-mint` container is built from `sophia-agent/Dockerfile.token-mint` (loads `src/token_mint.py` — the FastAPI JWT minter).

The third EC2 container (`livekit-server`) is the stock `livekit/livekit-server:latest` image from Docker Hub — no custom code from our repo.

So when you say "uses sophia-agent as backend," what actually happens at runtime is: client connects to the EC2's livekit-server (SFU on port 7880) AND to the EC2's token-mint (FastAPI on port 8001). The agent-worker is a worker that registers with the SFU and gets dispatched into rooms — clients don't talk to it directly; they talk to the SFU and the SFU brokers between them and the worker.

### The architectural mirror — yes, exact same pattern

```
sophia-glasses (Unity)  ─┐
                          ├──► EC2 backend (livekit-server + token-mint + agent-worker)
Sophia_Xreal-U2 (Unity) ─┘                  │
                                              └──► EKS inference services
                                                   (Whisper / Qwen3 / Kokoro / sophia-spatial-ai)
                                                   via kubectl port-forwards from EC2
```

Both Unity clients are LiveKit participants joining LiveKit rooms on the same SFU. Same X-API-Key auth path through token-mint. Same agent dispatch (`agent_name: "sophia-agent"`). Same inference pipeline behind the agent-worker. The backend cannot tell the two clients apart — both look like "a Unity participant publishing an audio track + subscribing to the agent's audio track."

### The ONE precision — Sophia_Xreal-U2 keeps its OTHER backends too

The XR engineer's app already has FOUR provider integrations: OpenAI Realtime, Gemini, GoogleVision, and his custom VoiceRelay (WSS). Each provider points at a different backend (different AWS gateway routes, different inference services).

When we add LiveKit as a NEW provider, we don't TAKE AWAY his other providers. His app gains the ABILITY to use `sophia-agent` as its backend WHEN his `ProviderConfig` is set to select LiveKit. The other providers stay functional for whichever scenarios he wants them for.

In other words:
- BEFORE integration: his app can talk to OpenAI Realtime, Gemini, GoogleVision, or his own VoiceRelay WSS server. Not to our sophia-agent.
- AFTER integration: his app can talk to OpenAI Realtime, Gemini, GoogleVision, his own VoiceRelay WSS, OR our sophia-agent via LiveKit. He picks per-deployment via his ProviderConfig.

So the GOAL of integration is "give his app the OPTION of using sophia-agent as backend," not "force his app to use sophia-agent."

### Side-by-side of the two clients after integration

| Aspect | sophia-glasses/ (ours) | Sophia_Xreal-U2/ (his) |
|---|---|---|
| Unity version | Unity 6 (6000.x — verify exact) | Unity 6.0.3.12f1 |
| XREAL SDK | Vendored at `xreal-sdk/` via Git LFS | UPM package `com.xreal.xr` |
| LiveKit SDK | Vendored at `client-sdk-unity/` via Git LFS | TBD — vendor or UPM Git URL (recommend vendoring for consistency) |
| Connection layer | `SophiaConnection.cs` (single MonoBehaviour) | `LiveKitLlmProvider.cs` implementing `ILLMProvider` (slots into his existing ProviderFactory) |
| Config schema | `SophiaConfig.asset` (single ScriptableObject) | New `LiveKitConfig` block added to his existing `ProviderConfig` |
| UI | `SophiaOverlayUI.cs` (our world-space HUD) | His existing UI (`Modules/ConversationalAI/UI/`, `Hud/`) — fires same events |
| Backend endpoint | `ws://3.227.63.49:7880` + `http://3.227.63.49:8001/token` | SAME (when LiveKit provider selected) |
| Auth | X-API-Key + LiveKit JWT pair | SAME |
| Agent dispatched | `sophia-agent` | SAME |

Both clients become functionally interchangeable from the backend's perspective. The differences are all internal to each Unity project.

### Short-form answer

Yes, exactly right. The goal is "make Sophia_Xreal-U2 able to use sophia-agent as its backend via a new LiveKit provider" — same backend topology that sophia-glasses uses today, just plumbed through his existing provider abstraction instead of through a standalone connection MonoBehaviour. The two clients end up as siblings pointing at the same EC2 infrastructure.

---

## Q15 (2026-06-02): I want to lock in the phased plan: Sophia_Xreal-U2 is the PRODUCTION Unity client. Right now LiveKit services live on EC2 (MVP). Eventually infra team takes over and deploys LiveKit on standard AWS infrastructure. So we integrate LiveKit against the EC2 backend FIRST (because EC2 is up, infra needs time), validate end-to-end working, then later infra migrates the backend and we re-point the client. Later still: latency + optimization. Is this the right sequence?

**Yes, this is the right sequence. The provider-abstraction pattern in his codebase makes it cost-free to do it this way — code stays identical across phases, only config values change.** Locking it in as the canonical plan.

### The phase plan

**Phase 1 (NOW) — Integrate LiveKit provider into Sophia_Xreal-U2, point at our EC2 backend**

- Write `LiveKitLlmProvider.cs` in `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/` implementing `ILLMProvider`.
- Add LiveKit Unity SDK to `Sophia_Wearable/Packages/manifest.json`.
- Add new `LiveKitConfig` block to his existing `ProviderConfig` schema.
- Wire into his existing `ProviderFactory` — when config says "use LiveKit," return our new provider.
- Configure the provider with our EC2 endpoints: `liveKitUrl=ws://3.227.63.49:7880`, `tokenEndpoint=http://3.227.63.49:8001/token`, `tokenApiKey=9a11fdf5...`, `agentName=sophia-agent`.
- Build APK, install on Beam Pro, validate voice loop end-to-end (mic → STT → RAG → LLM → TTS → speakers).
- Branch in his repo: `feat/livekit-provider` off `development`. PR back to `development` when stable.
- **Success criteria**: he can put on the Beam Pro + XREAL glasses, talk, Sophia answers via the EXACT SAME inference pipeline our sophia-glasses uses. Validates that the integration is correct.
- **Estimated effort**: 1-1.5 days focused work.

**Phase 1.5 (interim) — Run both clients side-by-side**

- Sophia_Xreal-U2 + sophia-glasses both connect to the SAME EC2 backend.
- Useful for: regression testing (does Sophia_Xreal-U2 produce the same UX?), Scenario A demos (two devices in the same room), confirming the backend handles concurrent participants from heterogeneous clients.
- No new code. Just two APKs installed on two Beam Pros (or one device + browser).

**Phase 2 (LATER, when infra team is ready) — Backend migrates from MVP EC2 to standard AWS production**

- Infra team uses `HANDOFF.md` + `production_deployment.md` to deploy `livekit-server` + `token-mint` + `agent-worker` to proper AWS (us-west-2 same-region as EKS, dedicated EC2 OR ECS/EKS pods, ALB with TLS, real domain like `sophia.aipartnersusa.com`, AWS Secrets Manager, real auth instead of shared X-API-Key, etc.).
- They generate fresh secrets (not reusing our MVP `7baeb38a... / d4b85117... / 9a11fdf5...` values).
- They produce: a production-grade backend reachable at e.g. `wss://sophia.aipartnersusa.com` with new credentials.
- **Sophia_Xreal-U2 code does NOT change.** Only the `LiveKitConfig` values in his `ProviderConfig` update:
  - `liveKitUrl: wss://sophia.aipartnersusa.com:7880` (or whatever domain + TLS)
  - `tokenEndpoint: https://sophia.aipartnersusa.com/token`
  - `tokenApiKey: <NEW production X-API-Key from secrets manager>`
- Smoke test from his app: switch ProviderConfig to point at prod, build APK, validate the same voice loop works against the new backend.
- **Success criteria**: the integration code written in Phase 1 keeps working without modification when the URLs flip to production.
- **The MVP EC2 (3.227.63.49) stays running** until production is validated. Then it's decommissioned (notify Ivana before stopping the shared EC2).

**Phase 3 (AFTER PRODUCTION IS UP) — Latency + optimization tuning**

- Measure: STT first-byte, LLM first-token, TTS first-chunk, end-to-end response time. Use the `[DEBUG_0605_VoiceRelayLegs]` pattern already in his codebase for the VoiceRelay path (he has similar telemetry hooks for LiveKit by then).
- Cross-region penalty: Phase 1 + 2 still go through kubectl port-forwards (EC2 us-east-1 → EKS us-west-2 = +70ms per inference call). Phase 3 eliminates this by either: (a) moving the backend EC2 to us-west-2, OR (b) deploying agent-worker pods INSIDE the EKS cluster so they reach inference services via cluster-internal DNS at single-digit ms.
- Streaming TTS tuning: validate sentence-fragment-level TTS chunking is firing (low time-to-first-audio).
- Audio quality tuning: WebRTC AEC behavior on his hardware, possibly add DeepFilterNet 3 if echo is a problem.
- Multi-participant validation: Scenario A with two glasses + browser in one room, check audio routing per Q58 contract.
- Bundle ID rename (Phase 2 hardening item from sophia-glasses) — relevant if his app's bundle ID needs aligning.
- Real auth replaces shared X-API-Key: integrate with Cognito / Auth0 / Clerk / mTLS depending on what infra team picks.

### Why this order is correct

1. **Don't block on infra.** EC2 backend is up and stable right now. Infra team needs days-to-weeks for proper AWS deployment. Starting integration work now means the LiveKitProvider lands in his repo while infra works in parallel.
2. **De-risk integration before scaling.** If the provider plugin has issues (mic permission flow, audio routing, event wiring to his existing UI, etc.), better to surface them against a stable MVP backend than to debug them simultaneously with infra deployment issues.
3. **Provider-abstraction means zero rework.** Because `LiveKitLlmProvider.cs` only reads URLs + keys from `LiveKitConfig`, swapping EC2 → AWS production = change config values, redeploy. No code refactor.
4. **Two siblings produce two demo paths.** During the transition window, you have sophia-glasses on EC2 AND Sophia_Xreal-U2 on EC2 both proving the same backend. Less likely a regression slips through.
5. **Optimization is empirical.** You can't sensibly tune latency until you have real production network paths, real concurrency, real measurements. Phase 3 has the data to drive decisions; Phase 1 doesn't.

### What HANDS OFF between phases

- **End of Phase 1**: Sophia_Xreal-U2 with `LiveKitLlmProvider.cs` merged to `development` (or kept on branch until validated). Working APK pointed at EC2 backend.
- **End of Phase 2 (infra-driven)**: Production AWS backend with new credentials + URLs. Update Sophia_Xreal-U2's `ProviderConfig` defaults to point at production. Optional: keep EC2 endpoints as a "staging" config in the same enum.
- **End of Phase 3**: Tuned end-to-end latency under target SLO (whatever the team picks — typical voice-agent SLO is ~1.5s first-token TTS). Production hardening complete (real auth, TLS, secrets manager, monitoring).

### Risk + mitigation for each phase

| Phase | Risk | Mitigation |
|---|---|---|
| Phase 1 | Mic / audio routing differs between his XR rig and our sophia-glasses setup → audio doesn't flow correctly | Compare his XR rig against our `Camera.main` parenting; validate the `MicrophoneSource` opens the right device; have him run `adb logcat` while testing |
| Phase 1 | His `ILLMProvider` event signatures don't quite match what LiveKit emits → his existing UI doesn't update | Read `ILLMProvider.cs` carefully, map each event (`OnTranscriptReceived` ↔ `lk.transcription` text-stream, `OnAgentSpeaking` ↔ agent track subscribe/unsubscribe, `OnAudioReceived` ↔ audio frames if applicable) |
| Phase 2 | New production keys leak before being rotated → security incident | Infra team uses Secrets Manager from day one; never paste prod keys into chat / Slack / git |
| Phase 2 | Production URL changes break the APK in the field | Use a feature-flag pattern: ProviderConfig can hold MULTIPLE LiveKit endpoint sets; switch at runtime via in-app config without rebuilding APK |
| Phase 3 | Optimization changes regress correctness | Always keep a sophia-glasses build for A/B comparison; have both APKs running side-by-side during tuning |

### Short-form answer

Right sequence. Phase 1: build LiveKitLlmProvider into Sophia_Xreal-U2 against EC2 backend (1-1.5 days, branch `feat/livekit-provider`). Phase 2: infra team migrates backend to standard AWS (days-to-weeks, parallel work using HANDOFF.md), then we update ProviderConfig values to point at production — no code change. Phase 3: measure latency, tune cross-region, harden auth/TLS. The provider abstraction is the load-bearing decision — it makes the EC2-to-production migration a config swap instead of a refactor.

---

## Q16 (2026-06-02): Now that we've seen what Sophia_Xreal-U2 actually does, does our LiveKit integration add a lot of value compared to what they already have? What difference does it bring? Any cons?

**Honest answer up front: this is a sharper question than Q12, and the answer is more nuanced.** Q12 was written assuming a generic XR client with a PTT-or-simple-WS path. After surveying his code (per `Sophia_Xreal-U2.md`), the real comparison point is NOT "no real-time voice" — it's his existing **VoiceRelay** provider, which is already a sophisticated self-hosted streaming STT→LLM→TTS WebSocket path with full-duplex, barge-in, structured observability, and per-leg latency telemetry. That changes the calculus.

So the question is really: "What does LiveKit bring over VoiceRelay specifically?" Below is the actual delta. No marketing.

### What VoiceRelay already delivers (so LiveKit does NOT add these)

These were the big-ticket Q12 wins. He has them already:

| Capability | His VoiceRelay implementation |
|---|---|
| Full-duplex streaming audio | Streams 16 kHz PCM16 mic chunks as base64 over WSS; receives 24 kHz TTS PCM streamed back from server |
| Barge-in / interrupt | Sends `{type: "interrupt"}` on first mic chunk while agent is speaking |
| Streaming TTS | Server streams TTS chunks as they're synthesized; client queues them via `PcmAudioPlayer` |
| Server-side orchestration framework | Server owns the STT→LLM→TTS pipeline; client just streams audio |
| Self-hosted | His server, his infrastructure — no third-party vendor lock |
| Structured observability | `[DEBUG_0605_VoiceRelayLegs]` per-leg timings (stt_complete, rag_complete, llm_first_token, tts_first_byte, end_to_end_ms); traceparent + correlation IDs; v1.1 wire-level observability |
| Provider abstraction | His `ILLMProvider` interface already lets him swap providers; LiveKit is a new sibling, not a replacement |
| Reconnect handling | Exponential backoff WS reconnect in VoiceRelay |
| Tool calling | Already wired via `OnFunctionCall` + his `IToolRegistry` auto-discovery |

That's a long list. Most of "why use LiveKit" arguments from Q12 don't apply against THIS baseline.

### What LiveKit DOES add over VoiceRelay (real differentiators)

These are the genuine wins. Ranked by how much they actually matter for his app:

**1. WebRTC transport vs raw WebSocket — biggest technical win.**

WebSocket over TCP is reliable but rigid:
- TCP head-of-line blocking: one lost packet stalls the whole stream until retransmit. On 4G/5G with 1-3% packet loss, audio gaps audibly.
- No FEC (forward error correction). One lost frame = silence gap. WebRTC's Opus has built-in FEC + PLC (packet-loss concealment) so a 5% loss rate is barely audible.
- No adaptive bitrate. On bad networks WSS keeps sending full-quality and either delivers late or drops the connection. WebRTC downgrades bitrate before disconnecting.
- No jitter buffer. WSS audio arrives in TCP-ordered bursts; you have to buffer client-side or hear stuttering. WebRTC's jitter buffer is automatic.
- NAT traversal: WSS works through any HTTPS-permitted network. WebRTC has STUN + TURN for hostile NAT setups, plus TCP fallback (LiveKit port 7881) for networks that block UDP.

For a wearable on cellular / public WiFi / glasses tethered via USB-OTG, this difference is real. Audible-glitch rate on flaky networks drops significantly with WebRTC.

**2. Multi-participant rooms (SFU pattern) — the architectural differentiator.**

VoiceRelay is 1:1 by design: one user, one WS, one agent. Multi-user collaborative sessions are not in its protocol model. LiveKit is built around the SFU pattern: a room has N participants + 1 agent, everyone subscribes to everyone else's tracks. Use cases this unlocks:
- Two technicians in the same XR room both looking at the same equipment, both able to talk to Sophia, both hearing Sophia and each other.
- A field tech + a remote expert sharing a session, with Sophia as a third voice.
- Multi-glasses training scenarios.

If multi-user collaborative XR is on his roadmap (which the Netcode for GameObjects 2.11.0 dependency hints at — he already has multiplayer infra), LiveKit is the right voice substrate. Building this on VoiceRelay would require an SFU layer on top, which IS a months-of-work project.

**3. Opus codec efficiency over PCM16.**

VoiceRelay streams 16 kHz PCM16 mic = 256 kbps uplink. LiveKit's Opus at 16 kHz mono = 24-32 kbps. ~8-10x bandwidth reduction. On cell data this matters for both battery and data caps. Downlink is similar: 24 kHz PCM16 = 384 kbps vs Opus at ~48 kbps.

**4. Cross-platform SDK ecosystem.**

VoiceRelay's WSS protocol is custom — every new client platform (iOS native, web, Quest, Vision Pro) is a from-scratch implementation. LiveKit ships SDKs for Unity, Swift, Kotlin, JS, Flutter, React Native, Python, Go. Adding a web companion app or an iOS variant becomes hours, not weeks.

**5. LiveKit Agents framework on the server side.**

His VoiceRelay server is custom code he wrote. LiveKit Agents (Python) gives him out-of-the-box: Silero VAD, MultilingualModel turn detection, OpenAI-plugin-compatible STT/LLM/TTS swapping, preemptive_generation, AEC warmup, interrupt detection. He could replace his VoiceRelay server with a livekit-agents agent.py (~200 lines) and get more features. This isn't a client-side gain but it's a "what could we delete" gain.

**6. Built-in encryption + auth pattern.**

WebRTC mandates DTLS-SRTP end-to-end encryption. WSS-over-TLS is encrypted in transit but he'd want to verify his auth pattern (bearer token? mTLS?). LiveKit uses signed JWTs minted by a token service — standard pattern, easy to integrate with Cognito/Auth0/Clerk later.

**7. Ecosystem of plugins for swapping STT/LLM/TTS.**

LiveKit's openai-plugin + cartesia-plugin + deepgram-plugin etc. let him point at any OpenAI-compatible endpoint with `base_url=...`. His VoiceRelay path bakes the model pipeline into his server. With LiveKit, swapping Whisper → Parakeet → Granite is a 1-line config change in agent.py.

### What LiveKit does NOT do better (or does worse)

Honest list of cons. These are the costs to weigh:

**1. Duplicates capability he already shipped (~2000 lines of VoiceRelay).**

He spent real time building VoiceRelay. It works, has observability, has reconnect. Adding LiveKit means maintaining two real-time voice paths in parallel, or eventually deprecating VoiceRelay (which is a migration project of its own).

**2. Adds a major SDK dependency.**

LiveKit Unity SDK + native FFI binaries = ~150 MB of vendored libraries (libwebrtc per-platform). VoiceRelay uses NativeWebSocket which is tiny. APK size grows accordingly. For wearable distribution that matters somewhat.

**3. WebRTC is harder to debug than WSS.**

When VoiceRelay misbehaves, the protocol is human-readable JSON over a single WS connection. You read packets in Wireshark, you log to console, you see what's happening. When LiveKit misbehaves you're debugging ICE candidates, DTLS handshakes, codec negotiations, jitter buffer state — much more SDK-internal, less inspectable.

**4. Adds self-hosted infrastructure complexity.**

VoiceRelay needs one HTTPS endpoint. LiveKit self-hosted needs: SFU process (livekit-server), open UDP port range (50000-60000), eventually a TURN server for restrictive NATs, redis for clustering at scale, token-mint backend. More moving parts to operate.

**5. WebRTC session-start latency.**

ICE candidate gathering + DTLS handshake adds 200-500 ms to session establishment vs ~50 ms for WSS. Steady-state audio latency is competitive (~10-30 ms) but the "press start, wait for connect" moment is longer. For PTT-style apps this is invisible; for app-launch-to-voice-ready this is noticeable.

**6. His existing observability story is BETTER granularity than LiveKit's defaults.**

His `[DEBUG_0605_VoiceRelayLegs]` emits stt_complete, rag_complete, llm_first_token, tts_first_byte separately. LiveKit Agents framework emits `metrics` events but at coarser granularity. We'd have to add custom telemetry in agent.py to match his per-leg fidelity. Net: rebuild observability, don't inherit.

**7. Tool calling parity uncertain.**

His SpatialAI module auto-discovers tools and registers them with the active `ILLMProvider`. Our LiveKit agent.py doesn't have any tool calls wired today. For v1, his tool flow would NOT work through the LiveKit provider — he'd have to fall back to OpenAI/VoiceRelay for tool-using turns. Closes some functionality.

**8. Vision flow is awkward over LiveKit.**

His `IVisionProvider.SendImageAsync(imageDataUrl)` is HTTP-based and simple. LiveKit can carry images via the data channel but it's not the natural primitive — you'd be using a real-time transport for one-shot uploads. His existing GoogleVision HTTP path is the right tool for vision; LiveKit doesn't improve it.

**9. The provider-abstraction gain is symmetric, not asymmetric.**

LiveKit being added as a new `ILLMProvider` is clean — but it's clean BECAUSE he built the abstraction well. It doesn't make his code better. We're benefiting from his architecture, not contributing to it.

### Honest verdict by audience

**If his roadmap includes multi-user collaborative XR sessions** (which Netcode for GameObjects hints at): LiveKit is a strategic add. SFU + shared rooms + cross-platform participants is the entire reason LiveKit exists. VoiceRelay would need an SFU layer bolted on, which IS the project.

**If his roadmap is single-user XR voice agent with his current VoiceRelay path working acceptably**: LiveKit is a marginal win. The WebRTC robustness improvements + Opus efficiency are real but not transformative if VoiceRelay already meets the latency + reliability bar in his deployment environment. He'd be adding a second voice transport to maintain for moderate gain.

**If he's worried about deployment environments with flaky networks / restrictive NATs** (corporate firewalls, public WiFi, cellular): LiveKit's WebRTC + TCP fallback + TURN story is meaningfully better than raw WSS. Tip the scale toward LiveKit.

**If he wants to delete VoiceRelay server code and run on LiveKit Agents framework instead**: meaningful server-side simplification, ~2000 lines of his VoiceRelayLlmProvider.cs gets to retire, replaced by a thinner LiveKitLlmProvider.cs.

### What I'd actually recommend

**Run Phase 1 as a measurement spike, not a commitment.** The phase plan already calls for 1-1.5 days. Use that to:

1. Write `LiveKitLlmProvider.cs`, get it talking to our EC2 backend.
2. Side-by-side with VoiceRelay against the same user flow, measure:
   - End-to-end latency (mic-stop to first TTS audio byte)
   - Audio quality on his target network (cellular + glasses tether)
   - Glitch rate on simulated 2-5% packet loss
   - APK size delta
   - Session-start time
   - Battery on the Beam Pro during a 10-minute session
3. Run the same 7 open questions in `Sophia_Xreal-U2.md` against the actual integrated provider — confirm his audio routing, his UI events, his reconnect policy all hold up.

If the numbers say LiveKit wins meaningfully on his target networks, keep going (Phase 2 + 3). If they say VoiceRelay is actually fine and LiveKit just duplicates capability, you have empirical data to decide whether the multi-user / cross-platform / framework-simplification reasons alone justify the migration. Either outcome is a good outcome — you've stopped guessing.

The provider-abstraction pattern is doing real work here: it lets you ADD LiveKit without REMOVING VoiceRelay. So this is a low-regret experiment. The cost is the spike time (Phase 1), not a one-way door.

### Short-form answer

Less value than Q12 implied, because his VoiceRelay path already covers full-duplex + streaming TTS + barge-in + observability + self-hosting. The REAL LiveKit wins over his existing path are: (1) WebRTC transport for flaky networks (Opus FEC + jitter buffer + adaptive bitrate vs raw WSS), (2) multi-participant SFU rooms for collaborative XR sessions, (3) Opus codec efficiency (~8-10x bandwidth savings), (4) cross-platform SDK ecosystem, (5) LiveKit Agents framework for server-side simplification, (6) plugin ecosystem for swapping STT/LLM/TTS. Real cons: (1) duplicates his 2000-line VoiceRelay capability, (2) adds ~150 MB SDK + UDP infra, (3) harder to debug than WSS, (4) WebRTC session-start latency, (5) his per-leg observability is better than LiveKit defaults, (6) tool calling + vision don't have parity with his existing providers in v1. Recommendation: treat Phase 1 as a measurement spike against VoiceRelay, decide on data not anticipation. Low regret because provider-abstraction lets both paths coexist.

---

# Unity client + LiveKit integration doubts

Q&A focused on the active Phase 1 integration of `LiveKitLlmProvider` into `Sophia_Xreal-U2/` (the XR engineer's production Unity client) against our EC2 backend. Distinct from the architecture/strategy Q1–Q16 above. Numbering continues monotonically.

**Working rules for this section:**
- No edits to `Sophia_Xreal-U2/` without explicit per-change "go" from the user.
- When we do touch it, stay on the branch we own (`feat/livekit-provider` off his `development`). Never commit to his `main` / `development` directly.
- Backend target for Phase 1 stays EC2 (`ws://3.227.63.49:7880`, `http://3.227.63.49:8001/token`, `tokenApiKey=9a11fdf5...`, `agentName=sophia-agent`). Phase 2 will swap these for production AWS endpoints — code unchanged.

---

## Q17 (2026-06-03): What information do you still need to complete the LiveKit integration, or do you have everything?

I have most of what I need from reading the code (Q16 plus the deep-read of the 5 critical files in his repo). What's still missing splits into two categories: things I can verify autonomously without touching his repo, and things only the XR engineer can answer.

### What I HAVE (from prior work)

- Full `ILLMProvider` contract — 6 events (`OnAudioReceived`, `OnTranscriptReceived`, `OnFunctionCall`, `OnError`, `OnUserSpeaking`, `OnAgentSpeaking`), plus the `EventArgs` shapes including the voice-relay-v1.1 extensions (`RelayPhase`, `RelayCommit`, `ErrorStage`, etc.).
- `ConversationalAIController` orchestration patterns (1635 lines): provider-type-sniff branches at lines 392-399, 886-887, 980-1012; reconnect coroutine with 1.5×2^n exponential backoff capped at 32s (lines 635-666, 674-800); audio-first caption gating (line 1063, 1200-1214); mic→provider chunk path via `OnMicrophoneAudioChunk` decoding base64 only for non-OpenAI providers (line 1541).
- `VoiceRelayLlmProvider` as the template to mirror (879 lines): MonoBehaviour, `Initialize(ProviderConfig)`, `ConnectAsync` with `GatewayRuntimeBootstrapService.EnsureReadyAsync` bootstrap, `SendInterruptAsync` throttled at 350 ms, `DisconnectAsync` fire-and-forget from `OnDestroy`, 24 kHz pcm16 down via `OnAudioReceived` matching what `PcmAudioPlayer.EnqueueBase64Audio` expects.
- `ProviderFactory` pattern (234 lines): enum value in `ConversationProviderType` + `CreateXxxProvider()` method that does `FindFirstObjectByType<T>()` or `new GameObject(...).AddComponent<T>()` parented under the factory + `provider.Initialize(_config)`.
- `MicrophoneStreamer` surface (757 lines): `Action<string> OnAudioChunk` (base64 PCM 16 kHz mono, 1024 samples/chunk ~64 ms), `OnMicChunkRmsForClientVad` RMS probe, XREAL/phone device-selection heuristic, `AndroidAudioSessionHelper.ConfigureForInputDevice` for VOICE_COMMUNICATION routing.
- Backend connection values: `ws://3.227.63.49:7880`, `http://3.227.63.49:8001/token` with `X-API-Key: 9a11fdf5ce05e3cecad28f933d778971`, agentName `sophia-agent`.
- 5 of the 7 open questions from `Sophia_Xreal-U2.md` answered from code reading: Q2 audio playback routing (route through `PcmAudioPlayer`), Q4 tool registry (no-op `SetToolRegistry` for v1; tools live server-side in agent.py), Q5 VAD coordination (surface `OnMicChunkRmsForClientVad` for telemetry, don't suppress; barge-in driven by LiveKit server-side Silero), Q6 reconnect (make `IsConnected` return true during SDK's `Reconnecting` state to absorb the controller's 1.5s grace timer), Q7 asmdef (add `LiveKitLlmProvider.cs` to existing `Sophia.ConversationalAI.asmdef`, reference the LiveKit SDK asmdef).

### What I still need — AUTONOMOUS (I can do, blocked only on you saying go)

1. **LiveKit Unity SDK API verification.** (T1 — RESOLVED 2026-06-03 from reading `sophia-glasses/client-sdk-unity/Runtime/Scripts/`. Both sub-questions answered YES.)

   Two sub-questions need to be answered before we know whether the integration is clean or has a meaningful regression:

   **Q1a: Does the SDK expose a custom/buffered audio source we can write PCM bytes into for the uplink `LocalAudioTrack`?**

   Why this matters — real-world example. User wearing XREAL One Pro glasses with Beam Pro phone in their pocket on a factory floor says "Sophia, how do I clear error E47 on conveyor B?":

   - **YES path** (custom audio source supported): `MicrophoneStreamer` stays in control. It picks the XREAL boom mic (~5 cm from the user's mouth) instead of the phone mic in their pocket, puts Android into VOICE_COMMUNICATION audio mode (same mode phone calls use — turns on hardware echo cancellation), and hands the cleaned-up PCM bytes to LiveKit through a buffer adapter to publish to the SFU. User gets clean voice, factory background noise suppressed. When they interrupt Sophia mid-sentence ("wait, just give me the part number"), Sophia's TTS coming out of the XREAL temple speakers leaks back into the boom mic only faintly — and the hardware AEC kills that leak before MicrophoneStreamer's buffer sees it. Barge-in works clean.

   - **NO path** (no custom source, LiveKit's `MicrophoneSource` must own the mic): LiveKit calls Android's default `Microphone.Start()`, picks the loudest default device (= phone mic in the user's pocket), uses default audio mode (general MIC, not VOICE_COMMUNICATION). User's voice gets captured from inside their pocket through clothing — muffled, with conveyor noise mixed in. Whisper STT mis-transcribes "error E47 on conveyor B" as "airfare E47 on the rover B" or asks them to repeat. Sophia's voice routed to glasses temple speakers is fine in isolation, but if USB Audio routing momentarily drops (cable jiggle, Android audio policy reset), the audio falls back to the Beam Pro speaker and creates the Q41/Q43 echo loop with no hardware AEC to suppress it.

   The desk demo with earphones works either way. The actual XREAL-on-head factory deployment is where the YES vs NO path diverges into "product works" vs "product fails".

   **Finding (YES):** `Runtime/Scripts/RtcAudioSource.cs` defines an abstract base class with `RtcAudioSourceType.AudioSourceCustom = 0`. Subclass it, override `event Action<float[], int, int> AudioRead`, call `AudioRead?.Invoke(buffer, channels, sampleRate)` to push frames. The base class handles float→int16 conversion and the native FFI CaptureAudioFrame call. The canonical example is `Tests/PlayMode/Utils/SineWaveAudioSource.cs` (94 lines, Timer-based 20ms frames). Our adapter would be ~80 lines: subscribe to `MicrophoneStreamer.OnAudioChunk(base64)`, decode to float[], call `AudioRead.Invoke(buffer, 1, 16000)`. MicrophoneStreamer keeps mic ownership, the XREAL device-selection heuristic + AndroidAudioSessionHelper VOICE_COMMUNICATION mode + OnMicChunkRmsForClientVad probe are all preserved. Bonus: `RtcAudioSource` constructor already enables WebRTC-level `EchoCancellation = true, AutoGainControl = true, NoiseSuppression = true` in `AudioSourceOptions` (lines 102-104) — so even in the NO path we wouldn't be naked, just less efficient (software APM in WebRTC vs hardware APM via VOICE_COMMUNICATION). Bonus 2: `Runtime/Scripts/MicrophoneSource.cs` exists too — the NO path is also a real option if the XR engineer prefers simplicity over preserving his tuning. Net: mic-ownership becomes a preference question (Q3 for the XR engineer), not a technical blocker.

   **Q1b: What `Reconnecting` / `Reconnected` events does `Room` expose?**

   Why this matters — real-world example. Same factory user, walking from one zone to another. The WiFi access points covering different zones force a 1-2 second WiFi handoff as they cross the boundary — totally routine, happens dozens of times a day on any large-area WiFi deployment. There are TWO independent reconnect mechanisms watching the connection:

   - Layer 1 — LiveKit's Room (the SDK). When transport drops, it fires `Reconnecting`, performs ICE restart + DTLS re-handshake to recover the existing session in 1-3 seconds, fires `Reconnected`. Whole recovery is quiet and SDK-internal.
   - Layer 2 — His `ConversationalAIController`. Every Update() frame checks `_currentProvider.IsConnected`. If false for more than 1.5 seconds (grace timer at line 659), it fires DisconnectAsync + ConnectAsync from scratch via `ConversationProviderReconnectRoutine` (lines 674-800) — new token mint POST, new Room.Connect, new ICE/DTLS, agent re-dispatch, agent participant rejoin. Takes 5-8 seconds total.

   Without the IsConnected-stays-true-during-reconnect pattern (naive impl where IsConnected just returns `room.ConnectionState == Connected`):

   - User says "Sophia, status on the polishing station?"
   - Walks across handoff zone.
   - LiveKit's Room sees transport blip, fires Reconnecting, starts its own quiet recovery.
   - Our LiveKitLlmProvider.IsConnected returns false (room not Connected anymore).
   - Controller's grace timer fires after 1.5s, calls DisconnectAsync — tears down LiveKit's in-flight recovery.
   - Controller's ConnectAsync fires — full session rebuild from scratch, 5-8 seconds of dead air.
   - User finished walking and hasn't heard anything; asks again from confusion.

   With the pattern (provider subscribes to Reconnecting, sets `_isReconnecting = true`; IsConnected returns `room.IsConnected || _isReconnecting`; Reconnected clears the flag):

   - Same scenario.
   - LiveKit fires Reconnecting → our `_isReconnecting = true` → our IsConnected stays true.
   - Controller never sees a problem, grace timer never starts.
   - 1-2 seconds later transport recovers, LiveKit fires Reconnected → flag clears.
   - User heard a brief audio pause; Sophia answers the polishing-station question right after.

   Same logic applies to cellular tower handoffs (one tower to another as user walks across a large facility) and momentary Bluetooth-tether glitches between glasses and phone. Any transient network turbulence the SDK can recover from quietly.

   **Finding (YES):** `Runtime/Scripts/Room.cs` exposes:
   - `event ConnectionDelegate Reconnecting` (line 160) — fires when transport drops and SDK starts recovery.
   - `event ConnectionDelegate Reconnected` (line 161) — fires when transport recovers.
   - `event ConnectionStateChangeDelegate ConnectionStateChanged` (line 157) — fires on every state transition.
   - `ConnectionState ConnectionState` (line 138) — current state property.
   - `bool IsConnected => RoomHandle != null && ConnectionState != ConnDisconnected` (line 139) — built-in convenience.

   Wiring is straightforward: in `LiveKitLlmProvider.ConnectAsync`, after `Room.Connect(...)`, subscribe `room.Reconnecting += _ => _isReconnecting = true;` and `room.Reconnected += _ => _isReconnecting = false;`. Our public `IsConnected` getter becomes `=> room.IsConnected || _isReconnecting`. Controller sees a stable true throughout transient blips.

   **Net effect on integration plan:** mic-ownership decision and reconnect coexistence are both unblocked. Item 1 was the riskiest unknown going in; both answers are favorable, and the YES paths preserve his existing tuning + cleanly coexist with the controller's reconnect loop.

2. **Backend conventions check.** (T2 — RESOLVED 2026-06-03 from reading `sophia-agent/src/agent.py` + cross-checking the working `sophia-glasses/unity/Assets/Scripts/SophiaConnection.cs` to confirm the conventions match in production.)

   Two sub-questions need answering so OnAgentSpeaking, OnUserSpeaking, OnTranscriptReceived, and OnError fire correctly in the LiveKit provider:

   **Q2a: What is the exact agent identity prefix in the room?**

   Why this matters — real-world example. Two users join the same room for a shift handoff in the factory: a field tech wearing XREAL glasses on-site + a remote expert on a browser at headquarters. Both want to talk to Sophia + each other:

   - **Without an identity filter** (LiveKit provider subscribes audio + fires OnAgentSpeaking for every remote participant): glasses client subscribes to both the remote expert's mic AND Sophia's TTS, plays them BOTH through `PcmAudioPlayer`. When the expert says "the conveyor is at the back near the loading dock" while Sophia simultaneously starts answering a prior question with "looking at the polishing station, the temperature should be...", the field tech hears them mixed and can't tell who's speaking. Worse, OnAgentSpeaking fires for the expert too — the HUD state pill animates "agent is talking" when actually it's the remote human. Field tech thinks Sophia is responding when it's just the expert. The session feels broken.

   - **With an "agent-" prefix filter** (Q58 fix already shipped in sophia-glasses, the pattern we need to mirror): glasses client only subscribes audio playback for tracks whose `participant.Identity.StartsWith("agent-")`. The expert's mic track is still subscribed (so the room knows about it for state) but NOT played locally — each user owns their own speaker, never plays the OTHER user's mic. Only Sophia's voice plays through glasses speakers. OnAgentSpeaking fires ONLY when the actual agent participant speaks. HUD pill is accurate. Field tech and remote expert can both carry on their own conversation with Sophia without crosstalk.

   This is exactly the Q58 production multi-user audio fix already shipped. The LiveKit provider must mirror the same filter to inherit that correctness.

   **Finding:**
   - **Agent NAME (worker registration)** = `"sophia-agent"` — line 567 of `agent.py`: `@server.rtc_session(agent_name="sophia-agent")`. This is what clients put in `roomConfig.agents = [{name: "sophia-agent"}]` in their token request to ask the SFU's worker dispatcher to assign an instance of this worker to the room.
   - **Agent runtime room IDENTITY prefix** = `"agent-"` — confirmed empirically from `sophia-glasses/unity/Assets/Scripts/SophiaConnection.cs` line 332-333: `bool isAgent = !string.IsNullOrEmpty(participant?.Identity) && participant.Identity.StartsWith("agent-");`. This is the LiveKit Agents framework default — the framework auto-generates participant identity `agent-<job_id>` when the agent joins a room. The full suffix varies per session (e.g., `agent-7f3a9b2c-1a4e-4d5f`).
   - For the LiveKit provider: any check that needs to distinguish "the agent" from "another user" uses `participant.Identity.StartsWith("agent-")`. Don't hardcode the suffix; it's per-session.

   **Q2b: What text-stream topics does the agent publish to, and what's the JSON shape?**

   Why this matters — real-world example. Field tech wearing glasses says "Sophia, status on the polishing station?" Three text-stream topics carry different parts of the conversation. Each one missing breaks a specific part of the HUD:

   - If `sophia.agent_events` NOT subscribed: STT transcribes the user's question and `agent.py` publishes `{kind: "user_transcript", text: "...", is_final: true}` to this topic. Without it, the HUD shows NO user caption — field tech can't visually confirm Sophia heard the question correctly. Also no `agent_state` / `user_state` events arrive, so the HUD pulsing state dot doesn't animate (stays idle even when Sophia is thinking or speaking). Also no `metrics` events — Phase-3 latency tuning has no per-leg data to work from.
   - If `lk.transcription` NOT subscribed: LiveKit's framework auto-publishes Sophia's spoken words (TTS-to-text) on this default topic. Without it, the HUD shows NO agent caption — user HEARS Sophia speaking via the glasses speakers but can't read what she said. Bad if audio is unclear, accent doesn't carry, or factory noise mixes in.
   - If `sophia.rag_result` NOT subscribed: every user turn triggers RAG retrieval; `agent.py` publishes the source chunks + page numbers as JSON on this topic. Without it, the HUD shows no source chips — field tech can't verify "Sophia is answering from MANUAL-23 page 14" before trusting her answer.

   With all three correctly subscribed: user speaks → `user_transcript` arrives → user subtitle renders → `agent_state` flips to thinking → state dot animates → `sophia.rag_result` arrives → source chips appear → `lk.transcription` streams Sophia's delta tokens → agent subtitle fades in → audio plays → `agent_state` flips back to listening → state dot returns to idle. Every HUD component depends on its specific topic.

   **Finding:**
   - **Topic constants** at top of `agent.py` (lines 56-57):
     ```python
     RAG_RESULT_TOPIC = "sophia.rag_result"
     AGENT_EVENTS_TOPIC = "sophia.agent_events"
     ```
   - **Plus framework default** `lk.transcription` — auto-emitted by the LiveKit Agents framework's transcription pipeline; carries both user and agent transcribed text. NOT explicitly published in our `agent.py` code; framework handles it.
   - **Publish API** (line 365-367): `await room.local_participant.send_text(json.dumps(payload), topic=AGENT_EVENTS_TOPIC)`.
   - **Subscribe API** (Unity SDK, proven in sophia-glasses lines 208-212): `room.RegisterTextStreamHandler("sophia.agent_events", (reader, identity) => ...)` — fires per message; reader yields the full string payload.
   - **`sophia.agent_events` payload shape** (every payload includes `ts` epoch seconds + `kind`):
     | kind | additional fields | when |
     |---|---|---|
     | `user_transcript` | `text`, `is_final`, `language` | STT finalizes a user turn (line 405-416) |
     | `agent_state` | `old`, `new` (e.g., "listening" → "thinking" → "speaking") | agent state machine transitions (line 381-391) |
     | `user_state` | `old`, `new` | user state (speaking/listening) transitions (line 393-403) |
     | `speech_created` | (empty) | TTS started synthesis (line 418-420) |
     | `tools_executed` | (empty) | function tools ran (line 422-424) |
     | `false_interruption` | `resumed` (bool) | barge-in heuristic decided it was noise (line 426-428) |
     | `metrics` | `metric_type`, `label`, plus any of: `duration`, `ttft`, `ttfb`, `audio_duration`, `completion_tokens`, `prompt_tokens`, `total_tokens`, `end_of_utterance_delay`, `transcription_delay`, `on_user_turn_completed_delay`, `cancelled`, `inference_duration_total`, `inference_count`, `idle_time` | every metric the framework emits (line 430-462) |
     | `error` | `error` (str), `source` (str) | exception in any stage (line 464-474) |
     | `close` | (empty) | session ending (line 476-478) |
   - **`sophia.rag_result` payload shape**: produced by `_publish_rag_result(payload)` called from the `on_user_turn_completed` hook; carries the retrieved chunks + scores. Exact shape determined by the RAG retriever (frontend `RagResultPanel` renders it).
   - **`lk.transcription` payload shape**: LiveKit framework's standard transcription format — typically `{participant_identity, segments: [{text, start, end, final, language}]}`. Already consumed by the working sophia-glasses client; the LiveKit Unity SDK's framework adapter parses it.

   **LiveKit provider event mapping** (this is the wiring `LiveKitLlmProvider.cs` will do):
   - `OnTranscriptReceived(TranscriptType.User, final|delta)` ← `sophia.agent_events` kind=`user_transcript` (use `is_final` for final flag)
   - `OnTranscriptReceived(TranscriptType.Agent, final|delta)` ← `lk.transcription` topic, filtered to messages where `participant.Identity.StartsWith("agent-")`
   - `OnAgentSpeaking(true)` ← `sophia.agent_events` kind=`agent_state` with new=`speaking`
   - `OnAgentSpeaking(false)` ← `sophia.agent_events` kind=`agent_state` with new=`listening` (or any non-speaking state)
   - `OnUserSpeaking(true/false)` ← `sophia.agent_events` kind=`user_state` analogously
   - `OnAudioReceived` ← `Room.OnTrackSubscribed` audio frames, filtered to identity starting with "agent-" (Q58 pattern)
   - `OnError(ErrorStage=...)` ← `sophia.agent_events` kind=`error`
   - For `[DEBUG_LiveKit]` / `[DEBUG_LiveKitLegs]` telemetry parity with VoiceRelay's v1.1 observability: log `sophia.agent_events` kind=`metrics` payloads with prefix `[DEBUG_LiveKitLegs] stage=<metric_type> ttft=<ttft> ttfb=<ttfb> end_to_end_ms=<duration>` etc.

   **Net effect on integration plan:** transcript / state / metrics event wiring is fully specified. The LiveKit provider will subscribe to the same three topics the working sophia-glasses client already proves out — `sophia.agent_events`, `sophia.rag_result`, `lk.transcription` — apply the same `agent-` identity filter, and map payloads to the corresponding ILLMProvider events. No backend changes needed; the agent already publishes everything the provider needs.

### What I still need — FROM THE XR ENGINEER

3. **Mic ownership preference.** Does he want `MicrophoneStreamer` to keep ownership (preserves his XREAL device-selection heuristic + `AndroidAudioSessionHelper` VOICE_COMMUNICATION + `OnMicChunkRmsForClientVad` probe), OR is he OK letting LiveKit's `MicrophoneSource` open the mic directly (simpler integration, but loses those XREAL-specific bits)? The answer depends partly on item 1 — if the SDK doesn't expose a custom audio source, keeping ownership becomes a much bigger lift.

4. **Vision behavior for v1.** Three options: (a) `SendImageAsync` returns `Task.CompletedTask` like VoiceRelay does today (vision silently unavailable for LiveKit sessions, recommended for v1), (b) forward via LiveKit data channel (backend has no handler today), (c) composite-defer-to-`GoogleVisionProvider` (mirror how `OpenAIProvider` degrades to Qwen description). Which?

5. **Repo access on `AIPartnersUSA/Sophia_Xreal-U2`.** Add us as Collaborator with Write so we can push `feat/livekit-provider`, OR he prefers patch/fork+PR workflow. Either is fine; we just need to know.

6. **LiveKit Unity SDK source.** Vendor a copy mirroring our `sophia-glasses/client-sdk-unity/` Git LFS pattern, OR UPM Git URL pointing at LiveKit's upstream repo, OR the official UPM package if one exists for his Unity 6 (6000.3.12f1)? Affects how we add it to his `Packages/manifest.json`.

7. **Branch name + base confirmation.** Plan is `feat/livekit-provider` off `development`. Confirm this matches his team's branching convention, or override.

### Once those 7 land, integration starts

The actual code work after items 1-7 are answered is:

1. Add `ConversationProviderType.LiveKit` enum value in his `ProviderConfig.cs`.
2. Add `LiveKitProviderSettings` ScriptableObject (mirrors `OpenAISettings` pattern — cleaner than mutating `ProviderConfig.cs` which is touched-by-everything).
3. Write `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs` (~900 lines, closer to VoiceRelay sized than OpenAI).
4. Extend `ProviderFactory.cs` switch + new `CreateLiveKitProvider()` method.
5. Add LiveKit SDK reference to `Sophia.ConversationalAI.asmdef`.
6. Vendor or UPM-link the LiveKit Unity SDK per item 6.
7. Smoke test against EC2.
8. Measurement spike per Q16 (latency, glitch rate, session-start time, APK size delta, battery).

Estimated time after items 1-7 resolve: 1-1.5 days for steps 1-7 above (matches Phase 1 estimate in Q15).

### Short-form answer

I have the contract + patterns + backend values. I still need: (autonomous, I can do now if you say go) LiveKit Unity SDK API check for custom audio source + reconnect events, and backend agent identity prefix + transcript topic verification. (From XR engineer) mic ownership preference, vision behavior choice, repo Collaborator access, SDK source preference, branch name confirmation. Once those land, I'm unblocked to write `LiveKitLlmProvider.cs`.

---

## Q18 (2026-06-03): Are we sure integrating LiveKit into HIS framework is the right thing to do? Why not just use our sophia-glasses (which already does end-to-end LiveKit voice on its own), or let LiveKit Agents replace his whole codebase since it already provides VAD, turn detection, streaming TTS, etc.?

Fundamental scope check before we commit to writing code. Five concerns walked through:

**1. We're fitting LiveKit into his framework. Yes — that IS Phase 1.** The plan from Q15 is: write `LiveKitLlmProvider.cs` implementing his `ILLMProvider`, add to his `ProviderFactory`. So the question is whether that's the right thing, not what it is.

**2. Why not just use sophia-glasses?** Because sophia-glasses isn't a product — it's a research/demo client. Its scope is `SophiaConnection.cs` (voice) + `SophiaOverlayUI.cs` (HUD) + `SessionPicker.cs` (entry UI). That's it. His `Sophia_Xreal-U2` has months of production AR work on top: AR Foundation 6.3.3, ARCore + ARKit, XR Hands, XRI 3.3.1, OpenXR, hand tracking, virtual product manipulation, scenario controllers (warehouse / retail / training), user session DB, image masking, part animation, AR session calibration, scenario controllers, etc. If we shipped sophia-glasses as "the product", we'd be throwing away all his AR investment. Not a real shortcut.

**3. Does LiveKit Agents already do what his whole codebase does?** Partial yes, partial no — and the distinction is what matters.

What LiveKit Agents DOES replace from his code (server side, if he switches to LiveKit provider):
- STT/LLM/TTS streaming orchestration
- Silero VAD
- Turn detection (MultilingualModel via `turn_handling=` config)
- Streaming TTS as LLM tokens arrive
- Interrupt detection + barge-in coordination
- Wire protocol for audio streaming (LiveKit Unity SDK handles this)

What LiveKit Agents does NOT replace from his code (client side):
- AR HUD rendering, world-space canvases, caption display — pure UI code, lives in his app
- Hand controls, gesture input — XR input plumbing
- Scene management, scenario controllers — product business logic
- Virtual product manipulation — actual wearable product feature
- The `ILLMProvider` abstraction itself — how his app stays provider-agnostic so he can A/B swap OpenAI / Gemini / VoiceRelay / LiveKit at will

So his 1635-line `ConversationalAIController` is mostly UI-glue + reconnect orchestration + provider lifecycle — NOT voice processing. The voice processing happens server-side via LiveKit Agents (when LiveKit provider is active). `ConversationalAIController` is just the bridge between "voice provider emitted an event" and "HUD should update".

**4. So why is the integration small?** Because we're not duplicating his AR / UI / scene work; we're swapping out the voice provider underneath it. Estimated sizes: ~900 lines for `LiveKitLlmProvider.cs` + ~80 lines for the mic adapter + 5 lines to extend `ProviderFactory`. The other ~6000 lines of his orchestration / UI / AR code is reused as-is.

**5. The comparison framing matters.** The Q16 measurement spike comparison ISN'T client-vs-client (sophia-glasses vs Sophia_Xreal-U2). That would confound two variables — the client UX AND the voice transport. We can't tell from that whether better numbers come from LiveKit's transport or from sophia-glasses being a simpler client.

The right comparison is provider-vs-provider INSIDE HIS SAME CLIENT: `Sophia_Xreal-U2` running with `ConversationProviderType.VoiceRelay` vs the SAME APK running with `ConversationProviderType.LiveKit`. Same hand tracking, same scene, same HUD, same backend models — ONLY variable is transport + orchestration. Clean A/B.

### Short-form answer

His app is the product, sophia-glasses is the reference. We integrate LiveKit into his app because he ships, we don't. LiveKit Agents replaces his SERVER-SIDE voice orchestration when his app uses LiveKit provider; it does NOT replace his CLIENT-SIDE AR / UI / scene work, which is what most of his codebase is. The integration is small (~900 lines for the provider + ~80 for the mic adapter) because we're only swapping the voice provider underneath his unchanged AR app. The measurement comparison is provider-A vs provider-B inside his same client, not client-A vs client-B.

---

## Q19 (2026-06-03): When we swap his client from VoiceRelay to LiveKit, what exactly bypasses in his code and what stays? I want the precise boundary.

The split has a clean technical line, but the line is NOT "everything voice-related." Some voice-related code in his client (mic capture, audio playback) stays in use even when LiveKit is the active provider — because bypassing it would regress audio quality on his hardware.

**What we DO bypass when LiveKit is the active provider:**
- His VoiceRelay WSS protocol code (`VoiceRelayLlmProvider.cs`).
- His voice-relay server (`Sophia_UnityServer/` for local dev twin; the AWS gateway voice-relay endpoint in production).
- His custom WSS framing (audio chunks as base64 over WSS, `{type:"interrupt"}` messages, etc.).
- Anything voice-relay-protocol-specific.

**What we KEEP using from his client even when LiveKit is the active provider:**
- His `MicrophoneStreamer` (per Q17 Q1a YES path) — captures via XREAL boom mic, applies VOICE_COMMUNICATION mode, runs the device-selection heuristic. We feed its output into a LiveKit `RtcAudioSource` subclass adapter. Bypassing this would regress the factory-floor audio quality (mic in pocket vs mic at mouth, no hardware AEC).
- His `PcmAudioPlayer` (per Q17 mapping) — plays TTS audio with dual-output routing (phone speaker + glasses temple speakers via Audio Mixer). LiveKit audio frames flow through it. Bypassing this would lose dual-output.
- His `ConversationalAIController` — still orchestrates provider lifecycle, reconnect coordination, event routing to HUD. Just dispatches against `LiveKitLlmProvider` instead of `VoiceRelayLlmProvider`.
- His HUD, his AR scene, his hand controls, his scenarios, his virtual product manipulation — everything-else.

**Two-line summary of what swaps:**
- The VOICE TRANSPORT changes: WebSocket (TCP, custom JSON framing to his AWS gateway) → WebRTC (UDP with TCP 7881 fallback, Opus codec, LiveKit SFU).
- The VOICE ORCHESTRATION changes: his AWS voice-relay server (custom Python on his AWS infra) → our `sophia-agent/src/agent.py` running under LiveKit Agents framework.

His client's mic pipeline (device selection + AEC mode) and audio playback pipeline (dual-output routing) stay his. His HUD stays his. His AR stays his. The only thing that changes is "how does audio get from this mic to a server, get processed, and come back as audio to that speaker."

### Short-form answer

Same mic capture, same speaker routing, same HUD, same AR — but the protocol/transport in the middle is WebRTC instead of WSS, and the server-side STT/LLM/TTS orchestration is LiveKit Agents (Python) instead of his voice-relay server (also Python but custom on his AWS).

---

## Q20 (2026-06-03): Which folder in his code currently does the STT-LLM-TTS orchestration? And what's he doing for VAD + turn detection?

His architecture splits client from server exactly like ours does. The orchestration is NOT in his Unity client repo — the client is just a streaming pipe. Two layers:

**For the VoiceRelay path (his fully-OSS analog to our LiveKit path):**

*Client side, what runs in his Unity app:*
- `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/VoiceRelay/VoiceRelayLlmProvider.cs` (879 lines) — pure WSS client. Streams audio up, receives audio down. Zero orchestration logic.

*Server side, where the real STT→LLM→TTS pipeline runs:*
- HIS AWS gateway voice-relay endpoint, owned by HIS AWS team. The handoff doc is at `Sophia_Xreal-U2/docs/AI_Agent_Handoffs/Handoff_Voice-Relay-AWS-handoff_2026-05-06.md` and the wire contract at `Sophia_Xreal-U2/docs/docs_client/WEARABLE_VOICE_RELAY_CLIENT_API.md`. He doesn't ship that server source in this repo because it's a separate AWS deployment owned by a different team.
- LOCAL DEV TWIN of that server lives in `Sophia_Xreal-U2/Sophia_UnityServer/` at the top of his repo — a Unity-hosted test server that mocks the AWS gateway shape so he can dev offline. Key files: `Sophia_UnityServer/Assets/_Scripts/Server/ServerEntryPoint.cs`, `RealtimeWebSocketTcpHost.cs`, `OpenAiRealtimeGatewayProxy.cs`, `GatewayHttpForwarder.cs`.

**For the OpenAI Realtime path (his other primary provider):**

Orchestration runs inside OpenAI's hosted Realtime service. The client side at `OpenAIProvider.cs` (2753 lines) is heavier because it sends VAD config / turn-detection config / function call definitions in JSON over the WSS to OpenAI, but the actual STT→LLM→TTS happens on OpenAI's servers.

**Substitution map (his VoiceRelay world ↔ our LiveKit Agents world):**

| Server-side function | His VoiceRelay world | Our LiveKit Agents world |
|---|---|---|
| Process host | AWS gateway voice-relay endpoint (his AWS team) | `sophia-agent` worker container |
| Entry point | Their gateway lambda/server | `sophia-agent/src/agent.py` line 567: `@server.rtc_session(agent_name="sophia-agent")` |
| Local dev twin | `Sophia_UnityServer/` | `livekit-server --dev` natively + `agent.py` running locally |
| Pipeline | STT(Whisper) → LLM(Qwen3) → TTS(Kokoro) on AWS | STT(Whisper) → LLM(Qwen3) → TTS(Kokoro) on EKS — SAME models, SAME backend pods |

**VAD and turn detection — two layers (same split as orchestration):**

*Client-side VAD (low-latency local detection, primarily for barge-in):*
- `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Core/ClientSideVadService.cs` — service that consumes the RMS probe.
- `MicrophoneStreamer.cs` line 29 fires `event Action<float, float, float> OnMicChunkRmsForClientVad(rms, realtime, durSec)` every chunk — feeds the service.
- This is a simple energy-based detector that says "the user started talking now". Used to trigger the interrupt message (`SendInterruptAsync` at `VoiceRelayLlmProvider.cs` line 156) when Sophia is mid-sentence and the user barges in. Doesn't decide turn boundaries — just "is sound happening".

*Server-side VAD + turn detection (decides when user finished talking, when to fire the LLM):*
- His side: runs on the AWS voice-relay server. The client sees its decisions via the response's `vad_endpoint_ms` timing field, surfaced in `VoiceRelayLlmProvider.cs` line 631 (`vadEnd = Ms(timings, "vad_endpoint_ms")`) and propagated as observability via `Sophia_Wearable/Assets/_Scripts/Core/IVoiceRelayTurnDetectionProvider.cs`. The actual VAD model isn't visible in his client repo — likely WebRTC VAD or Silero on the AWS gateway side.
- For OpenAI Realtime path: OpenAI's built-in server-side VAD (configured in `OpenAISessionConfigBuilder.cs` via the session.update message).
- Our LiveKit Agents world: `sophia-agent/src/agent.py` line 547-561 — `prewarm(proc: JobProcess)` loads Silero VAD with explicit knobs (activation_threshold, min_speech_duration, min_silence_duration, prefix_padding_duration, max_buffered_speech, sample_rate). Turn detection via LiveKit Agents framework's `turn_handling=` block (around line 615) which uses MultilingualModel turn-detector predicting P(end-of-utterance) over the last N transcript turns.

**VAD/turn-detection substitution map:**

| Function | His VoiceRelay world | Our LiveKit Agents world |
|---|---|---|
| Client RMS probe (barge-in) | `ClientSideVadService.cs` + `MicrophoneStreamer.OnMicChunkRmsForClientVad` | Same code, kept as-is (just for telemetry in LiveKit path) |
| Server VAD (start/end of speech) | AWS voice-relay internal | `silero.VAD.load(...)` in `agent.py` prewarm |
| Server turn detection (end-of-utterance prediction) | AWS voice-relay internal, reported via `vad_endpoint_ms` field | LiveKit Agents `turn_handling=` with MultilingualModel in `agent.py` |
| How client learns about turn end | `vad_endpoint_ms` in WSS timings response | `agent_state` text-stream event (kind=agent_state, new=thinking) |

### Short-form answer

His client just streams audio (`VoiceRelayLlmProvider.cs`, 879 lines). The STT→LLM→TTS orchestration lives on the SERVER — his AWS gateway voice-relay endpoint in production, with `Sophia_UnityServer/` as the local dev twin. VAD has two layers everywhere: client-side RMS probe (his `ClientSideVadService.cs` + `MicrophoneStreamer` RMS event) for barge-in, server-side VAD + turn detection for end-of-utterance decisions. We swap the SERVER from his AWS gateway to our `sophia-agent/src/agent.py` (LiveKit Agents framework). The client-side RMS probe code stays untouched.

---

## Q21 (2026-06-03): To properly compare his orchestration to ours apples-to-apples, we need to see his AWS voice-relay server code. How do we do that comparison?

**Practical reality first:** his AWS production server code is NOT in his Unity repo. The repo only has the CLIENT side of the voice-relay relationship. The actual server runs on his AWS team's infrastructure — separate deployment, separate codebase, likely a separate repo we don't have access to. We'd need to ask him or his AWS team to share their server source.

**What IS in his repo that tells us about the server side (without seeing actual source):**
- `Sophia_Xreal-U2/docs/docs_client/WEARABLE_VOICE_RELAY_CLIENT_API.md` — wire contract (what client sends/receives, the JSON shapes, the per-leg timing fields). Documents the API his AWS team must implement.
- `Sophia_Xreal-U2/docs/AI_Agent_Handoffs/Handoff_Voice-Relay-AWS-handoff_2026-05-06.md` — original handoff to the AWS team describing what server they need to build.
- `Sophia_Xreal-U2/Sophia_UnityServer/` — LOCAL DEV TWIN. Unity-hosted mock server with the SAME wire contract so he can dev offline against a server that behaves like AWS. Not the real AWS deployment but a behaviorally-similar one.
- `Sophia_Xreal-U2/docs/reference/end-to-end-voice-turn-latency.md` — likely has per-leg latency targets and what the server emits.

**Two-phase comparison strategy:**

*Phase A — contract-level comparison (autonomous, ~1 hour):*
- Read his three docs above + the `Sophia_UnityServer/` dev twin code to map his server contract: input audio shape, VAD config, turn detection algorithm, per-leg timing fields emitted, error model, interrupt semantics.
- Map our `agent.py` + LiveKit Agents framework against the same dimensions.
- Output: a side-by-side table of "what each orchestration does at each stage". Tells us functional parity and where they architecturally differ. Doesn't tell us which is faster.

*Phase B — actual-runtime comparison (the Q16 measurement spike):*
- Same client (his `Sophia_Xreal-U2`), flip `ProviderConfig` enum.
- VoiceRelay path hits his AWS server (orchestrated however that's actually implemented).
- LiveKit path hits our sophia-agent (orchestrated by LiveKit Agents).
- Measure: end-to-end mic-stop-to-first-TTS-byte latency, glitch rate on bad network, session-start time, APK size delta, battery during 10-min session.
- Output: numbers that show which performs better, regardless of what's literally inside his AWS server. The empirical answer.

**Why we don't need his AWS source for the measurement spike:** Phase B measures user-perceived behavior. That's what actually matters for the deployment decision. His AWS server code could be doing anything internally — what we care about is whether his stack OR our stack delivers a better experience to the wearer.

**Why Phase A still has value even without his source:** it gives us architectural intuition for WHY the Phase B numbers fall where they fall. If LiveKit wins on session-start by 2 seconds, was it because his AWS gateway does a slow handshake, or because WebRTC has session-start overhead his WSS doesn't have? Phase A lets us interpret. Without Phase A we'd have numbers but no narrative.

**If LiveKit wins meaningfully in Phase B and the team decides to standardize on it,** then the deeper "what is his AWS code literally doing" investigation can happen Phase 1.5 / Phase 2 with proper access from his AWS team. For Phase 1, we don't need it.

### Short-form answer

We don't have his AWS server source — it's owned by his AWS team. What we have is his wire contract docs + the `Sophia_UnityServer/` local dev twin. That's enough for Phase A (contract-level side-by-side, ~1 hour autonomous read). The empirical comparison happens via Phase B (Q16 measurement spike inside his same client, flip the provider enum, measure user-perceived numbers). Phase A gives the architectural picture, Phase B gives the numbers. Together they tell us which orchestration is better AND why.

---

## Q22 (2026-06-03): Final lock — orchestration and transport change, everything else stays the same?

Yes. Crystal clear summary:

**Same:** APK, XREAL hardware, EKS backend models (Whisper / Qwen3 / Kokoro), MicrophoneStreamer (XREAL boom mic + device-selection heuristic + AndroidAudioSessionHelper VOICE_COMMUNICATION mode + RMS probe), PcmAudioPlayer (dual-output to phone speaker + glasses temple speakers via Audio Mixer), ConversationalAIController (provider lifecycle + reconnect coordination + event-to-HUD routing), HUD, AR Foundation, hand controls, scenarios, virtual product manipulation, user sessions, everything-else.

**Changes when ProviderConfig flips from VoiceRelay → LiveKit:**
- **Transport**: WebSocket (TCP, custom JSON framing) → WebRTC (UDP with TCP 7881 fallback, Opus codec).
- **Server-side orchestration**: His AWS voice-relay gateway (his AWS team's Python) → our `sophia-agent/src/agent.py` (LiveKit Agents framework, Python).

That's it. Two backends, two transports, everything else identical. Then we measure both inside the same client and compare.

### Short-form answer

Yes, locked. Same APK, same hardware, same backend models, same client mic + speaker + HUD code. Two things flip: transport (WSS → WebRTC) and orchestration (his AWS voice-relay → our agent.py + LiveKit Agents). Clean A/B inside his same client.

---

## Q23 (2026-06-03): For Q17 item 4 (vision behavior), what is his VoiceRelay path doing for vision today? Would a LiveKit no-op be a regression vs his current production?

Checked directly in his code. Vision is already a no-op in VoiceRelay sessions today — exact parity, not a regression.

**Verbatim from `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/VoiceRelay/VoiceRelayLlmProvider.cs` lines 303-307:**

```csharp
public Task SendImageAsync(string imageDataUrl, string overlayImageDataUrl = null)
{
    if (enableDebugLogging)
        PlaySessionVerboseLog.Log($"{VoiceRelayTrace} SendImageAsync ignored (voice relay is audio-first).");
    return Task.CompletedTask;
}
```

Pure no-op. Logs that it was ignored, returns CompletedTask, never sends the image anywhere.

**How vision dispatch works in his controller (`ConversationalAIController.cs` lines 805-874):**

His `SendImage()` flow on the controller is provider-agnostic:
1. Captures the current camera frame (line 805+).
2. Logs `SendImage: forwarding to provider dataUrlChars=... overlay=yes/no` (line 865).
3. Calls `await _currentProvider.SendImageAsync(rawImageDataUrl, overlayImageDataUrl);` (line 867).
4. Whatever the active provider does with that image is up to the provider.

So vision behavior depends entirely on which `ILLMProvider` is active:
- `OpenAIProvider.SendImageAsync` (line 1365+) — real vision via OpenAI Realtime multimodal, with composite fallback to `GoogleVisionProvider` for Qwen text descriptions.
- `GeminiProvider.SendImageAsync` — real vision via Gemini Live multimodal.
- `VoiceRelayLlmProvider.SendImageAsync` (line 303) — no-op, silently ignored.
- `LiveKitLlmProvider.SendImageAsync` (our future v1) — no-op, matching VoiceRelay's pattern.

**What this means for users today:**

When his users run a VoiceRelay session and trigger a vision query (camera capture + ask Sophia about what they see), nothing happens at the provider level. The capture log shows the image was forwarded; the AI never sees it; Sophia answers from text only. Users who need vision today are switching to OpenAI or Gemini providers for those queries — and presumably the product UX makes that switch explicit or transparent.

**Implication for our LiveKit v1 decision:**

LiveKit v1 doing the same no-op as VoiceRelay achieves exact behavior parity. Not a regression — it's matching his current shipping baseline. Users who need vision today aren't using VoiceRelay for it; they won't use LiveKit for it either.

If at some point Sophia's product roadmap says "vision must work over LiveKit too," we add the composite-defer-to-GoogleVision path later (the option-c flow from Q17 item 4 — mirror what OpenAIProvider does when it can't handle vision directly). That's a small follow-up to add to `LiveKitLlmProvider`, not a v1 blocker.

**Net effect on Q17 item 4:** This question collapses from "his preference needed" to "default to no-op matching his existing VoiceRelay behavior, revisit when product roadmap demands it." One less thing the XR engineer needs to answer before we start coding.

### Short-form answer

His VoiceRelay path has `SendImageAsync` as a no-op (`VoiceRelayLlmProvider.cs` lines 303-307: log + return CompletedTask). Vision is silently ignored today in VoiceRelay sessions; users needing vision use OpenAI or Gemini providers. Our LiveKit v1 no-op matches that exact behavior — not a regression. Vision-over-LiveKit can be added later via composite-defer-to-GoogleVision (Q17 item 4 option c) when product roadmap demands.

---

## Q24 (2026-06-03): Do I have write access to AIPartnersUSA/Sophia_Xreal-U2 so we can push the LiveKit integration branch directly?

Verified via GitHub API. Current access is read-only.

**API call:**
```
gh api repos/AIPartnersUSA/Sophia_Xreal-U2 --jq '{name, full_name, private, permissions, default_branch}'
```

**Response:**
```json
{
  "default_branch": "main",
  "full_name": "AIPartnersUSA/Sophia_Xreal-U2",
  "name": "Sophia_Xreal-U2",
  "private": true,
  "permissions": {
    "admin": false,
    "maintain": false,
    "pull": true,
    "push": false,
    "triage": false
  }
}
```

**What this means:**
- `pull: true` — can read/clone (which is how we already have the reference clone via `GIT_LFS_SKIP_SMUDGE=1 git clone`).
- `push: false` — cannot push branches to the repo.
- No admin, maintain, or triage — cannot grant access to others or modify repo settings.

Auth context: gh CLI is logged in as `AvinashSophia` personal account with token scopes `repo, read:org, gist, workflow`. The token scope is sufficient for repo operations; the read-only status comes from the repo-level ACL, not the token.

**Two side findings from the same response:**

1. **Default branch is `main`**, not `development`. The Q15 plan said "feat/livekit-provider off development" — need to confirm with the XR engineer that `development` is still the right base (it exists, see next point), or branch off `main` instead.

2. **Branch list** (via `gh api repos/AIPartnersUSA/Sophia_Xreal-U2/branches --jq '.[].name'`):
   - `archive/agent-test`
   - `archive/fix-rgb-camera`
   - `archive/integration-rgb-camera-merge-main`
   - `archive/main-before-rgb-merge`
   - `development`
   - `main`

   So `development` does exist. Q15's plan of branching from it remains valid pending the engineer's confirmation that it's the active dev branch (vs `main`).

**Two paths to unblock writing the code:**

*Path A — Get Write or Maintain access on AIPartnersUSA/Sophia_Xreal-U2.*
- Requires the XR engineer or an org admin on AIPartnersUSA to grant it. Same pattern as how Avinash got Write on `aws-infra`.
- Workflow once granted: push `feat/livekit-provider` directly to his repo, open PR to `development` when ready.
- Cleanest. Matches standard org collaboration pattern.
- Time cost: depends on how quickly the engineer can grant it.

*Path B — Fork-then-PR workflow.*
- Fork `AIPartnersUSA/Sophia_Xreal-U2` to `AvinashSophia/Sophia_Xreal-U2` (personal account).
- Work on `feat/livekit-provider` in the fork.
- Open PR from `AvinashSophia/Sophia_Xreal-U2:feat/livekit-provider` → `AIPartnersUSA/Sophia_Xreal-U2:development` when ready.
- Works without anyone granting permissions — we can start immediately.
- Higher friction: extra remote to manage, PR review happens at fork boundary, harder to push WIP commits for review iteration.

**Recommendation:** Path A. Ask the XR engineer: "Can you add `AvinashSophia` as Collaborator with Write on `AIPartnersUSA/Sophia_Xreal-U2` so we can push the LiveKit integration branch directly?" If he can't or it'll take time, Path B is the fallback — we don't have to wait, we fork now and PR later.

**Net effect on Q17 item 5:** Confirmed read-only today. One concrete ask in the handoff package: grant Write. Fallback path B available if granting is slow or denied.

### Short-form answer

Read-only access today (`pull: true, push: false`). `development` branch exists (Q15's plan still applies); `main` is the default. Path A: ask the XR engineer to grant `AvinashSophia` Write access on AIPartnersUSA/Sophia_Xreal-U2 — same pattern as aws-infra. Path B fallback: fork to AvinashSophia/Sophia_Xreal-U2, work in fork, PR back. Path A is cleaner; Path B doesn't block.

---

## Q25 (2026-06-04): Integration journal — running state of the Phase 1 LiveKit integration work in Sophia_Xreal-U2-main. What's done, what's next, where things live, key decisions baked in.

This is a LIVING entry. Updated as each step lands. Future Claude or future-Avinash should be able to read this and know exactly where the work is parked.

### Setup state

- **Work clone**: `/Users/avinashbolleddula/Documents/repos/Sophia_Xreal-U2-main/` (existing clone in your repos folder; separate from the read-only reference clone at `Sophia_Xreal-U2/` in the research project root).
- **Branch**: `avinash/livekit-provider` off `development` (commit `6294ecb1 v3.12.2 - ARCore Geospatial and build flavor gating`). Branch name chosen by Avinash (XR engineer gave free rein: "feel free to add a branch with a clear name").
- **Write access**: granted 2026-06-04 via the AIP_All team grant from XR engineer. Push verified working (`gh api repos/AIPartnersUSA/Sophia_Xreal-U2 --jq .permissions` shows `push: true`).
- **Repo remote**: `https://github.com/AIPartnersUSA/Sophia_Xreal-U2.git`.
- **v3.12.1 → v3.12.2 diff check** (commit `cfae9f73` → `6294ecb1`): only 1 commit, only AR / build-tooling changes. ZERO files touched in `Modules/ConversationalAI/**`, `Modules/Audio/**`, `Modules/Networking/**`, `Modules/ProviderConfiguration/**`. All our Q17 line numbers + contracts remain valid at v3.12.2.
- **LiveKit Unity SDK source for our integration**: vendoring our `sophia-glasses/client-sdk-unity/` copy is the planned approach (Q17 item 6). Not yet added to his `Packages/manifest.json`.

### Baseline validation (his client runs cleanly on Mac before we touch anything)

Confirmed working on Avinash's Mac in Unity 6000.3.12f1 Editor Play Mode on 2026-06-04:
- ✅ **OpenAI Realtime direct** — Customized Endpoints mode + Active Conversation Provider = OpenAI Direct API. Uses the `sk-svca...` service-account key committed in `Assets/Resources/ProviderConfigurations/ProviderConfig.asset`. Spoke into Mac mic, Sophia responded.
- ✅ **AWS cascaded "Voice Step" (Whisper + LLM + Kokoro via gateway)** — Customized Endpoints + Active Conversation Provider = "AWS – Voice Step (Whisper + LLM + Kokoro TTS)". Endpoint `https://staging.docu-mind.com`. Works.
- ❌ **VoiceRelaySelfHosted** (Single Endpoint mode + AWS bundle + VoiceRelaySelfHosted pipeline) — fails at the bootstrap call to `GET /gateway/sophia-speech/client-config` with error `"Header value contains invalid characters"`. Pre-existing bug in his project: the committed bearer token has bad characters (likely trailing `\n` or `\r` from paste). NOT a blocker for us — this is his config issue. Sent to XR engineer as FYI; we proceed regardless.

**Implication**: his client is fully validated as a working development environment. The AWS cascaded path is also the IDEAL comparison baseline for our LiveKit work — same model families (Whisper + Kokoro on both sides), same backend deployment pattern, only orchestration framework + transport differ. Q16 measurement spike will compare LiveKit (WebRTC + agent.py + LiveKit Agents framework) vs AWS Cascaded (WSS + his AWS gateway server).

**Editor noise to ignore** during Play Mode:
- `DllNotFoundException: XREALXRPlugin` — XREAL native plugin only loads on Android device; expected on macOS Editor; harmless.
- `Disabling Analytics Reporting in External Dependency Manager` — Google ARCore extensions setup; harmless.
- `[CDEBUG_0521_EditorOverhead]` perf summary logs — his profiler; informational.

### Code work plan — 8 deltas total

1. ✅ **Create `Providers/LiveKit/` folder** in his repo. Done.
2. ✅ **Write `LiveKitLlmProvider.cs`** (556 lines). Done. Location: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs`. Has compile dependency on `using LiveKit;` namespace until step 4 vendors the SDK.
3. ✅ **Write `MicrophoneStreamerAudioSource.cs`** (118 lines). Done 2026-06-04. Location: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/MicrophoneStreamerAudioSource.cs`. Has same `using LiveKit;` dependency.
4. ✅ **Add LiveKit Unity SDK via UPM Git URL** to `Sophia_Wearable/Packages/manifest.json`. Done 2026-06-04. One-line addition: `"io.livekit.livekit-sdk": "https://github.com/livekit/client-sdk-unity.git#v1.3.7"` between `com.xreal.xr` and `org.khronos.unitygltf` (alphabetical). Picked over LFS-vendored approach because (a) his manifest already uses UPM Git URLs for 5 other packages so the pattern fits his ecosystem, (b) his Newtonsoft.Json `3.2.2` satisfies SDK's `3.2.1` dependency, (c) v1.3.7 is the exact version we tested with in `sophia-glasses/client-sdk-unity/package.json`, (d) Unity caches to `Library/PackageCache/` after first resolve so no ongoing network dependency, (e) one-line diff vs ~150 MB of LFS binaries.
5. ✅ **Edit `ProviderConfig.cs`** — added `LiveKit = 6` value to the `ConversationProviderType` enum. Done 2026-06-04. 3-line addition at the end of the enum (after `AwsVoiceRelaySelfHosted = 5`). Mirrors the existing pattern: `/// <summary>` XML doc comment + `[InspectorName("LiveKit (WebRTC + LiveKit Agents)")]` attribute for the friendly Inspector dropdown label + enum value `LiveKit = 6`. Sequential numbering continues from the existing entries.
6. ✅ **Edit `ProviderFactory.cs`** — added `CreateLiveKitProvider()` method + new `case ConversationProviderType.LiveKit:` arm in `CreateLLMProvider(ConversationProviderType)` switch. Done 2026-06-04. Mirrors the existing `CreateVoiceRelayLlmProvider` pattern exactly (FindFirstObjectByType / new GameObject / AddComponent / SetParent / Initialize / return). ~15 lines added across 2 hunks. Did NOT touch the legacy `CreateLLMProvider(ProviderType)` method since VoiceRelay isn't in that enum either; only ConversationProviderType is the active code path.
7. ⬜ **Edit `ConversationalAIController.cs`** — add `else if (provider is LiveKitLlmProvider lk)` branch in the controller's mic-forwarding code (line ~1541 from the deep-read). LiveKit owns mic via `MicrophoneStreamerAudioSource`; controller should skip its byte[] mic-forwarding when LiveKit is active.
8. ⬜ **Wire scene + Inspector** — add a `LiveKitLlmProvider` MonoBehaviour to the scene (factory will instantiate at runtime — but for dev we may pre-add). Assign `MicrophoneStreamer` ref + `speakerHost` Transform + tokenApiKey + URLs via Inspector. Set Active Conversation Provider in the Provider Configuration Manager to LiveKit.

After 1-8 land: smoke test in Editor Play Mode, then APK + Beam Pro, then measurement spike.

### Done so far — file-by-file

#### LiveKitLlmProvider.cs (556 lines) — 2026-06-04

Location: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/LiveKitLlmProvider.cs`

**Design decisions baked in** (each tied to a Q17 finding — see those for rationale):

1. **Sealed MonoBehaviour implementing ILLMProvider**. Mirrors `VoiceRelayLlmProvider` shape exactly (same template per the deep-read).
2. **Mic uplink via custom `RtcAudioSource` subclass** (Q1a YES path). `SendAudioChunkAsync` is a no-op — audio flows out-of-band through `MicrophoneStreamerAudioSource` (the file in step 3). Preserves XREAL boom mic device-selection + VOICE_COMMUNICATION audio mode + RMS probe.
3. **Audio downlink via SDK's auto-attached `AudioSource` on child GameObject** (Q58 pattern from sophia-glasses). Filter `participant.Identity.StartsWith("agent-")` to skip non-agent tracks. One child GameObject named `SophiaSpeaker_<sid>` per agent track under `_speakerHost`. **v1 limitation accepted**: bypasses his `PcmAudioPlayer` dual-output routing. Revisit if his demo needs dual-output.
4. **OnAudioReceived NOT raised in v1**. If his audio-first caption gating depends on this event, captions won't gate. Fix path: raise dummy events on track activity (cheap follow-up).
5. **OnAgentSpeaking driven by `sophia.agent_events` kind=`agent_state`** (new=`speaking` → true, anything else → false). Also fires `true` on track-subscribed for redundancy with HUD pill.
6. **OnUserSpeaking driven by `sophia.agent_events` kind=`user_state`**.
7. **Three text-stream topics** subscribed in `ConnectAsync` BEFORE `Room.Connect`: `sophia.agent_events`, `sophia.rag_result`, `lk.transcription`.
8. **Reconnect coexistence (Q6)**: `IsConnected => (_room.ConnectionState == ConnConnected) || _isReconnecting`. Subscribe to `Reconnecting`/`Reconnected` events to flip the flag. Absorbs the controller's 1.5s grace timer during SDK transient blips.
9. **SendImageAsync = no-op** (Q23 finding — matches VoiceRelay's existing behavior, not a regression).
10. **SetToolRegistry accepts and stores but doesn't use** the registry. Tools live server-side in `agent.py`. API parity for the controller's type-sniff branch.
11. **Token fetch via UnityWebRequest POST** to `_tokenEndpoint` with `X-API-Key` header. Body: `{room, identity, agent_name}`. Backend returns `{token, serverUrl}`.
12. **Config for v1 is `[SerializeField]` Inspector fields** (`_liveKitUrl`, `_tokenEndpoint`, `_tokenApiKey`, `_agentName`, `_roomName`, `_participantIdentity`). `Initialize(ProviderConfig _)` is a no-op for v1 — accepts the arg for ProviderFactory's call to compile, but reads nothing from it. Future: refactor to pull from `ProviderConfig.LiveKit` subblock.
13. **Debug logging prefix**: `[DEBUG_0604_LiveKit]` for grep parity with VoiceRelay's `[DEBUG_*_VoiceRelay*]` tags. Metrics events log under `[DEBUG_0604_LiveKitLegs]` (mirror VoiceRelay's `[DEBUG_0605_VoiceRelayLegs]`).
14. **OnDestroy fire-and-forget DisconnectAsync** (VoiceRelay pattern).
15. **Error plumbing via `RaiseError(stage, code, ex)`** helper — fills `ErrorEventArgs` including `ErrorStage` (the v1.1 observability extension already in `ILLMProvider.cs`).

**v1 limitations explicitly documented in the file header**:
- `SendAudioChunkAsync` is no-op (audio flows out-of-band via custom source).
- `SendImageAsync` is no-op (matches VoiceRelay).
- `OnAudioReceived` not raised (audio plays via SDK, not via `PcmAudioPlayer`).
- Tools no-op (server-side).

#### MicrophoneStreamerAudioSource.cs (118 lines) — 2026-06-04

Location: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/MicrophoneStreamerAudioSource.cs`

The bridge between his `MicrophoneStreamer` and LiveKit's `RtcAudioSource` capture pipeline. The provider constructs one of these in `ConnectAsync` and passes it to `LocalAudioTrack.CreateAudioTrack(..., source, ...)`.

**Design decisions baked in:**

1. **Subclasses `RtcAudioSource`** with `RtcAudioSourceType.AudioSourceCustom` and `channels: 1` (mono). Per the SineWaveAudioSource pattern from T1.
2. **Constructor takes a `MicrophoneStreamer` reference**. Null-guards on construction.
3. **Sample-rate mismatch handled by naive 3x upsampling.** MicrophoneStreamer emits 16 kHz; `RtcAudioSource`'s `_expectedSampleRate` for Custom type is locked to `DefaultSampleRate = 48000` by the base constructor (no per-instance override available). We triplicate each int16 sample → 3 consecutive floats. Quality acceptable for voice; STT (Whisper) resamples internally; can be replaced with linear interpolation if quality issues arise. **Known v1 limitation, documented in file header.**
4. **Subscription via `-= then +=` pattern**, not direct `=`. Required because `MicrophoneStreamer.OnAudioChunk` is a public `Action<string>` field (not a multicast event), and the controller already subscribes for its byte[] forwarding path. The minus-then-plus idiom safely adds us alongside without clobbering the existing subscription.
5. **AudioRead invoked with `(floatBuffer, 1, 48000)`** — channels=1, sampleRate=48000 matches the base's `_expectedChannels` + `_expectedSampleRate` so no metadata-mismatch warning fires.
6. **Single-pass conversion**: decode base64 → reinterpret bytes as int16 little-endian → upsample → convert to float [-1, 1], all in one loop with one allocation per chunk.
7. **Frame size**: MicrophoneStreamer's ~64 ms chunks (1024 samples at 16 kHz) become ~64 ms output chunks (3072 samples at 48 kHz). RtcAudioSource buffers internally; no need to slice into 20 ms WebRTC frames.
8. **Lifecycle parity with VoiceRelay pattern**: Start/Stop manages subscription, Dispose chains Stop + base.Dispose, finalizer for GC-driven safety.

**What this file does NOT do**:
- Echo cancellation, noise suppression, AGC — RtcAudioSource constructor enables these at the WebRTC layer (`AudioSourceOptions { EchoCancellation = true, AutoGainControl = true, NoiseSuppression = true }`). Plus MicrophoneStreamer's VOICE_COMMUNICATION mode gives hardware AEC on Android. Two layers of AEC; both run independently.
- Voice activity detection — that's `MicrophoneStreamer.OnMicChunkRmsForClientVad` (kept for client-side telemetry; not consumed by this adapter).
- Resampling beyond naive upsampling — proper polyphase / linear interp is a follow-up if needed.

#### manifest.json edit (1 line) — 2026-06-04

Location: `Sophia_Wearable/Packages/manifest.json`. Diff:

```
     "com.xreal.xr": "file:com.xreal.xr",
+    "io.livekit.livekit-sdk": "https://github.com/livekit/client-sdk-unity.git#v1.3.7",
     "org.khronos.unitygltf": "https://github.com/KhronosGroup/UnityGLTF.git",
```

What happens at first Unity Editor open after this lands: Unity reads manifest, resolves the Git URL, fetches LiveKit SDK v1.3.7 from upstream, caches to `Library/PackageCache/io.livekit.livekit-sdk@v1.3.7/`. After that, all `using LiveKit;` and `using LiveKit.Proto;` references in our two .cs files resolve. The native FFI binaries for each platform (macOS arm64, Android arm64/armv7/x86_64, iOS arm64, Windows arm64/x86_64, Linux x86_64) ship with the package — no separate native binary install needed.

**Versions confirmed for parity with sophia-glasses**:
- Our `sophia-glasses/client-sdk-unity/package.json` says `version: 1.3.7`.
- His new manifest entry pins to `v1.3.7` tag upstream.
- Both clients now on identical SDK bits — important for comparison testing.

#### ProviderConfig.cs edit (3 lines added) — 2026-06-04

Location: `Sophia_Wearable/Assets/_Scripts/Modules/ProviderConfiguration/ProviderConfig.cs` (lines 119-135 after the edit).

The enum now reads:

```csharp
public enum ConversationProviderType
{
    None = 0,
    [InspectorName("OpenAI Realtime")]
    OpenAI = 1,
    Gemini = 2,
    [InspectorName("Sophia AWS Server")]
    Sophia = 3,
    [InspectorName("Sophia Local Unity Server")]
    SophiaLocalUnityServer = 4,
    /// <summary>Self-hosted voice relay (Whisper → LLM → Kokoro) via <c>/gateway/sophia-speech/ws</c>.</summary>
    [InspectorName("AWS — Voice relay (Whisper → LLM → Kokoro TTS)")]
    AwsVoiceRelaySelfHosted = 5,
    /// <summary>Self-hosted LiveKit (WebRTC SFU + LiveKit Agents framework) — see sophia-agent/src/agent.py.</summary>
    [InspectorName("LiveKit (WebRTC + LiveKit Agents)")]
    LiveKit = 6
}
```

Three additions:
1. Trailing comma added after `AwsVoiceRelaySelfHosted = 5` (was previously the terminal entry).
2. `/// <summary>` XML doc comment matching the AwsVoiceRelaySelfHosted style.
3. `[InspectorName("LiveKit (WebRTC + LiveKit Agents)")]` attribute + `LiveKit = 6` enum value.

Naming rationale:
- Enum identifier `LiveKit` — plain, matches the pattern `OpenAI`, `Gemini`, `Sophia`.
- InspectorName "LiveKit (WebRTC + LiveKit Agents)" — tells the user in the Provider Configuration Manager dropdown what kind of LiveKit, distinguishing from hypothetical LiveKit Cloud variants.
- Numeric value `6` continues the sequence cleanly.

After this lands, the controller and factory can reference `ConversationProviderType.LiveKit` in switch statements. Step 6 (ProviderFactory) is what actually consumes this enum value.

#### ProviderFactory.cs edit (15 lines added across 2 hunks) — 2026-06-04

Location: `Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Core/ProviderFactory.cs`

**Hunk 1** — case arm inside `CreateLLMProvider(ConversationProviderType type)` switch (around line 42):

```csharp
case ConversationProviderType.AwsVoiceRelaySelfHosted:
    return CreateVoiceRelayLlmProvider();

+ case ConversationProviderType.LiveKit:
+     return CreateLiveKitProvider();

case ConversationProviderType.Gemini:
    return CreateGeminiProvider();
```

**Hunk 2** — new `CreateLiveKitProvider()` method right after `CreateVoiceRelayLlmProvider()` (around line 190):

```csharp
private ILLMProvider CreateLiveKitProvider()
{
    var p = FindFirstObjectByType<Sophia.ConversationalAI.Providers.LiveKit.LiveKitLlmProvider>();
    if (p == null)
    {
        var go = new GameObject("LiveKitLlmProvider");
        p = go.AddComponent<Sophia.ConversationalAI.Providers.LiveKit.LiveKitLlmProvider>();
        go.transform.SetParent(transform);
    }

    p.Initialize(config);
    return p;
}
```

Mirrors `CreateVoiceRelayLlmProvider` exactly — same shape, same call sequence (FindFirstObjectByType → conditional create → SetParent → Initialize → return). No deviations.

The factory pattern: if a `LiveKitLlmProvider` MonoBehaviour already exists in the scene (e.g., we pre-added it for the Inspector to configure), reuse it. Otherwise create one as a child of the ProviderFactory's GameObject. Either way, call `Initialize(config)` (which is a no-op for v1 — our provider reads from `[SerializeField]` Inspector fields instead). Return the `ILLMProvider` to the controller.

Note on what we DID NOT touch:
- `CreateLLMProvider(ProviderType type)` — legacy method using the old `ProviderType` enum (different from `ConversationProviderType`). Lines 57-78. VoiceRelay isn't in this enum either, so the active code path is purely the new switch. Leaving the legacy method alone is the right call.
- `CreateVisionProvider` — vision-only providers (OpenAI vision, Gemini vision, GoogleVision HTTP). We're a no-op for vision (Q23), so no entry needed here. The controller's vision dispatch goes through `_currentProvider.SendImageAsync` which our LiveKit provider handles with a no-op.
- The `CreateOpenAIProvider` divert-to-VoiceRelay branch (line 159): special case where if the AWS single-endpoint pipeline is VoiceRelay, OpenAI requests reroute to VoiceRelay. Not relevant for LiveKit; LiveKit is its own first-class enum entry.

### Next step (step 7 of 8 in the plan)

Edit `ConversationalAIController.cs` — add `else if (provider is LiveKitLlmProvider lk)` branch in the controller's mic-forwarding code (line ~1541 from the deep-read). LiveKit owns mic via `MicrophoneStreamerAudioSource`; the controller should skip its byte[] mic-forwarding when LiveKit is the active provider to avoid double-pushing the same audio (which would result in echoey / doubled uplink). Small surgical edit, ~5-10 lines.

After step 7: step 8 (scene wiring + Inspector config — add LiveKitLlmProvider GameObject to the scene, assign MicrophoneStreamer ref + speakerHost + tokenApiKey + URLs). Then Unity opens for the first compile-clean state of our integration — first chance to smoke test the voice loop against EC2.

---

## Q27 (2026-06-04): What's the difference between adding LiveKit Unity SDK via UPM Git URL vs vendor-copy (adding the SDK files into his repo's Packages/)? Why did we pick UPM Git URL?

Both approaches end up at the same place at runtime — LiveKit Unity SDK v1.3.7 compiled into the Unity project, same native FFI binaries, same C# wrapper, same `using LiveKit;` references resolve. The trade-off is repo footprint + self-containment vs lean diff + network dependency.

### UPM Git URL (what we picked — step 4 of the 8-delta plan)

What lands in his repo:
```
// in Sophia_Wearable/Packages/manifest.json
+    "io.livekit.livekit-sdk": "https://github.com/livekit/client-sdk-unity.git#v1.3.7",
```

One line. Nothing else.

What happens at first Unity Editor open after the manifest edit:
1. Unity reads the manifest dependency.
2. Recognizes the URL-with-tag pattern → "this is a UPM Git package."
3. Clones the upstream `livekit/client-sdk-unity` repo at tag `v1.3.7` (~150 MB of native FFI binaries per platform + ~200 .cs files + tests + docs).
4. Caches it locally at `<project>/Library/PackageCache/io.livekit.livekit-sdk@v1.3.7/`.
5. Indexes the cached package into the Unity asset database.
6. Our `using LiveKit;` references resolve. Compile succeeds (after our subsequent enum/factory/controller edits).
7. Subsequent opens: uses the cache, no network needed.

`Library/` is gitignored by Unity convention, so the actual SDK bits live OUTSIDE his tracked files. Other devs cloning the repo run their own first-time download.

### Vendor-copy (alternative — the path we did NOT pick)

What would have landed in his repo:
```
+ Sophia_Xreal-U2-main/client-sdk-unity/            (or Sophia_Wearable/Packages/com.livekit.livekit-sdk/)
+   ├── package.json
+   ├── Runtime/Scripts/*.cs                         (~200 C# source files)
+   ├── Runtime/Plugins/ffi-macos-arm64/*.dylib      (~10 MB native binary, LFS)
+   ├── Runtime/Plugins/ffi-android-arm64/*.so       (~12 MB native binary, LFS)
+   ├── Runtime/Plugins/ffi-android-armv7/*.so       (~10 MB)
+   ├── Runtime/Plugins/ffi-android-x86_64/*.so      (~13 MB)
+   ├── Runtime/Plugins/ffi-ios-arm64/*.a            (~25 MB)
+   ├── Runtime/Plugins/ffi-ios-sim-arm64/*.a        (~25 MB)
+   ├── Runtime/Plugins/ffi-macos-x86_64/*.dylib     (~12 MB)
+   ├── Runtime/Plugins/ffi-windows-arm64/*.dll      (~10 MB)
+   ├── Runtime/Plugins/ffi-windows-x86_64/*.dll     (~11 MB)
+   ├── Runtime/Plugins/ffi-linux-x86_64/*.so        (~12 MB)
+   ├── Documentation~/, Samples~/, Tests/, etc.
+   └── ... ~150 MB total via Git LFS

// in Sophia_Wearable/Packages/manifest.json
+    "io.livekit.livekit-sdk": "file:../../client-sdk-unity",   // or wherever we put it
```

Note: the `file:` URI path is relative to `manifest.json`'s LOCATION. Unity resolves `Packages/manifest.json` + `file:../../client-sdk-unity` = `Sophia_Wearable/Packages/../../client-sdk-unity` = `Sophia_Xreal-U2-main/client-sdk-unity/`. That's the path-math gotcha documented in `docs/internal/livekit_doubts.md` Q59.

What would happen at first Unity Editor open after this approach:
1. Unity reads the manifest.
2. Recognizes the `file:` path → "this is a local filesystem package."
3. Resolves the relative path, finds the package folder.
4. Indexes from disk. NO download (all bits already in repo).
5. After other devs clone, they need `git lfs pull` to materialize the native binaries before Unity will work. Without LFS pull, they get pointer-text instead of real .so/.dylib/.a/.dll files and Unity import fails.

### Side-by-side comparison

| Dimension | UPM Git URL (picked) | Vendor-copy (alternative) |
|---|---|---|
| Lines added to his repo | 1 | ~thousands (200 .cs + 10 native binaries via LFS) |
| Size added to his git/LFS | ~0 | ~150 MB |
| Network at first clone+build | Yes (Unity downloads SDK from upstream) | No (LFS pull does it) |
| Network at incremental builds | No (cached in Library/PackageCache/) | No |
| Uses org LFS quota | No | Yes (AIPartnersUSA LFS quota) |
| Reproducibility | Pin to v1.3.7 tag (Git-content-addressed, ≈immutable but tag could in theory move) | Bit-exact files in his repo (truly immutable) |
| Audit in PR review | Need to inspect upstream LiveKit repo | All bits visible in his diff |
| If upstream LiveKit repo became unavailable | First-time clones would fail; existing devs/CI with cache survive | Always works |
| CI pipeline | Needs internet for first build (then caches) | Pure git clone + lfs pull |
| Upgrade later | Bump tag in manifest.json (1 char change) | Replace folder contents + commit binaries |
| Matches his existing patterns | Yes — 5 of his packages already use UPM Git URLs (com.convai.openai, NativeWebSocket, ARCore extensions, ARKit, UnityGLTF) | No — he has only ONE local `file:` package (com.sophia.productserver) |
| Matches our sophia-glasses pattern | No — sophia-glasses uses vendor-copy via `file:../../client-sdk-unity` | Yes — identical setup as sophia-glasses |

### Why we picked UPM Git URL

- **Matches his existing manifest patterns.** 5 of his packages are UPM Git URLs already; his team understands this idiom. Vendor-copy via `file:` is only used for ONE package in his manifest (`com.sophia.productserver`), and that's a tiny package of his own.
- **No LFS quota disturbance.** His repo already has substantial LFS content (3D models, textures, audio). Adding ~150 MB more would notably bump his quota. UPM keeps the SDK out of git entirely.
- **Same v1.3.7 bits in both clients.** Our `sophia-glasses/client-sdk-unity/package.json` declares `version: 1.3.7`. His new manifest entry pins to `v1.3.7` tag upstream. Same release tag = same release artifact = identical bits at runtime. Important for the comparison testing scenario where we want both clients running the same SDK.
- **One-line PR diff** when the engineer reviews this work. Much easier review than auditing 200+ files.
- **Fewer integration risks** than embedding a vendor package — no risk of accidentally tracking native binaries via regular git (LFS gotcha), no risk of misplaced .gitattributes for new patterns, no manifest path-math errors.

### When vendor-copy WOULD have been the right call

- His team has a strict "no internet at build time" policy that we know about (we don't).
- Compliance audit requires every shipped binary to live in their repo (we haven't heard this requirement).
- Concerned about upstream LiveKit availability long-term (LiveKit is a well-funded company with a stable repo; low risk).
- LFS quota truly isn't a concern AND he wants the SDK source readable in his IDE without leaving the repo.

If any of those become true later, switching is reversible: change the manifest entry from Git URL to `file:` path, copy our `sophia-glasses/client-sdk-unity/` into his repo, commit. ~10 minutes of work plus the LFS storage cost.

### Risk we accepted with UPM choice

The `v1.3.7` tag on LiveKit's upstream is, in principle, mutable — a maintainer could move it. In practice GitHub release tags don't get moved (it would break every downstream consumer). If we want truly immutable pinning, swap the tag for the commit SHA at that tag's HEAD:

```
"io.livekit.livekit-sdk": "https://github.com/livekit/client-sdk-unity.git#<full-40-char-sha>"
```

Commits are content-addressed and cannot be moved without breaking the SHA. We didn't bother for v1 — tags from a serious upstream are reliable. Mention this if anyone audits the approach.

### Short-form answer

UPM Git URL adds 1 line to his manifest; Unity downloads + caches the SDK at first Editor open, lives in gitignored `Library/PackageCache/`, no LFS quota impact. Vendor-copy puts ~150 MB of native binaries + C# source physically in his repo via LFS, fully self-contained, audit-able in PR. Both result in identical bits at runtime. We picked UPM because (a) his manifest already uses 5 UPM Git URLs so the pattern fits his ecosystem, (b) his LFS quota gets preserved, (c) same v1.3.7 bits in both clients, (d) one-line diff easier to review. Reversible if his team needs vendor-copy later.

### Things to remember when resuming

- **Per-change `go` required** before any edit/write into the work clone. Saved process rule (`feedback_xr_repo_modification_rules.md`). User confirms each file before Write tool runs.
- **Unity Editor must be CLOSED** while we're writing files that depend on yet-unwritten classes — otherwise Unity tries to compile, surfaces errors, blocks Play. Open Unity again only after a known-good compile state.
- **Don't `git add -A`** in the work clone — Unity creates lots of import/play noise (modified .meta files, log files, ProviderConfig.asset edits, .vscode/, Sophia_Wearable.slnx, the auto-created LiveKit.meta folder marker). Add files selectively (`git add Sophia_Wearable/Assets/_Scripts/Modules/ConversationalAI/Providers/LiveKit/` etc.).
- **2026-06-04 movement note**: Avinash moved `LiveKitLlmProvider.cs` to `/tmp/LiveKitLlmProvider.cs.bak` before the baseline test so Unity could compile his existing code without our WIP file. Moved back to the work clone path after baseline confirmed working. File restoration log: 2026-06-04 12:08.
- **The 2 red 3ds Max errors** at first Unity import (`.max files only on Windows`) are harmless. Those are source-of-record files; runtime uses the .fbx exports.
- **EC2 backend still up** for when smoke test happens — ws://3.227.63.49:7880 + http://3.227.63.49:8001/token + tokenApiKey `9a11fdf5ce05e3cecad28f933d778971` + agentName `sophia-agent`. Phase 2 will swap these for production AWS values via Inspector edit, no code change.

### When this Q gets extended

Each subsequent file we write (steps 3-7 above) gets its own subsection under "Done so far" mirroring the LiveKitLlmProvider section above — design decisions, line count, location, design rationale. Step 8 (scene wiring) gets an entry too. When smoke test passes, add a "Smoke test results" section. When measurement spike runs, add the numbers.

---

## Q26 (2026-06-04): Now that AWS cascaded (Whisper + LLM + Kokoro via gateway) is baselined and working in his client, what does the Q16 measurement spike actually compare today vs after consolidation?

The baseline test on 2026-06-04 surfaced an important clarification: the AWS "Voice Step" cascaded path (NOT VoiceRelaySelfHosted) is the right comparison baseline against our LiveKit path, AND the comparison gets meaningfully cleaner once Phase 2 consolidates both stacks onto the same backend model endpoints.

### Phase 1 today — comparison has 3 changing variables

Same model FAMILIES on both sides (Whisper + Kokoro confirmed; LLM identity on his side TBC), but the underlying compute differs:

| | His AWS cascaded path | Our LiveKit path |
|---|---|---|
| Client | Sophia_Xreal-U2 (same APK) | Sophia_Xreal-U2 (same APK, with LiveKit provider) |
| Transport | WebSocket (TCP) | WebRTC (UDP + Opus, TCP 7881 fallback) |
| Orchestration server | His AWS gateway (custom Python) | sophia-agent/src/agent.py (LiveKit Agents framework) |
| Model deployment | His AWS GPU instances | Our EKS cluster `spatial-ai-staging` |
| STT model | Whisper (probably Large v3) | Whisper Large v3 |
| LLM model | Unknown (proxy to OpenAI? Qwen3? something else? — ask XR engineer) | Qwen3-VL-8B-Instruct |
| TTS model | Kokoro | Kokoro-82M |

Three variables shifting simultaneously: transport, orchestration, model deployment. The latency/glitch comparison is still meaningful for the "which feels better" verdict but isolating individual contributors is harder.

### Phase 2 after consolidation (per HANDOFF.md) — clean A/B

Once infra team deploys sophia-agent's full stack on production AWS, the intent is that BOTH paths target the same backend model endpoints. The variable matrix collapses to:

| | His AWS cascaded path | Our LiveKit path |
|---|---|---|
| Client | Same | Same |
| Transport | WebSocket (TCP) | WebRTC (UDP + Opus) |
| Orchestration server | His AWS gateway code | agent.py + LiveKit Agents framework |
| **Model endpoint** | **Same — shared deployment** | **Same — shared deployment** |
| STT/LLM/TTS | Identical | Identical |

Only two variables change: transport + orchestration. THAT's the apples-to-apples comparison we ultimately want.

### Why this matters for the measurement spike (Q16)

- For Phase 1 spike (now-ish, before consolidation): run the spike but interpret numbers carefully — some delta is from different model deployments not framework. Useful directional answer but not the final word.
- For Phase 2 re-run (after consolidation): same spike, but model variance is gone. The numbers will tell us decisively whether LiveKit's WebRTC + LiveKit Agents framework wins over his existing AWS WebSocket + custom Python orchestration. THIS is the answer for the standardize-or-keep-both product decision.

### Why this beats comparing against VoiceRelaySelfHosted

His VoiceRelay path is also self-hosted streaming voice over WSS, but with a custom JSON framing protocol that's specific to his AWS deployment. Comparing LiveKit against VoiceRelay would conflate "WebRTC vs WSS" with "LiveKit's standardized protocol vs his custom framing" — too many shape differences for a clean comparison. The AWS cascaded path uses a more conventional streaming pattern (STT/LLM/TTS each running on their own HTTP/WSS endpoints orchestrated by the gateway) which maps more cleanly onto how agent.py works. That makes it the more honest A/B.

### Action item for the user

Send the XR engineer a one-line clarification: "For the LiveKit comparison spike, what LLM does the AWS voice-step pipeline actually call? Is it Qwen3 / OpenAI / something else?" His answer tells us whether the Phase 1 spike comparison has 1 or 2 backend model differences (LLM the only one, or LLM + GPU pool both).

### Short-form answer

Phase 1 spike compares LiveKit (WebRTC + agent.py + LiveKit Agents + our EKS models) vs AWS cascaded (WSS + his AWS gateway + his AWS models). Three variables changing — transport, orchestration, model deployment. Phase 2 after infra consolidation: only transport + orchestration change. Same model endpoints serve both. The Phase 2 re-run is the cleanest possible A/B for the standardize-or-keep-both decision. We pick AWS cascaded over VoiceRelaySelfHosted because it's a more conventional streaming pattern that maps cleanly onto agent.py's shape.
