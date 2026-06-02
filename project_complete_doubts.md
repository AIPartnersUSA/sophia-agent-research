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
