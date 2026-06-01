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
