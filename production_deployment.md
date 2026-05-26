# Production deployment plan — Sophia on AWS EC2

Move the SFU + token-mint + agent worker from your laptop onto a single EC2 instance in the same VPC as your existing EKS inference services. Frontend on Vercel (free, simplest) or co-hosted on the EC2. Beam Pro / glasses client connects to the EC2's public DNS over WSS.

This is the FIRST production deploy — single instance, manually orchestrated, Docker Compose. Not multi-instance, not auto-scaling, not behind ECS or Kubernetes. Those are valid next steps after this works.

---

## Architecture diagram

```
                                                  +-----------------------------+
                                                  |  AWS EKS cluster            |
                                                  |  namespace: multi-agent     |
                                                  |  (you already have this)    |
                                                  |                             |
                                                  |  - whisper-inference :8080  |
                                                  |  - qwen3-inference :8080    |
                                                  |  - kokoro-tts :8122         |
                                                  |  - sophia-spatial-ai :8106  |
                                                  |  - orpheus-tts :8120        |
                                                  +--------------^--------------+
                                                                 |
                                                                 | private VPC
                                                                 | (same VPC,
                                                                 |  service DNS)
                                                                 |
+----------------------+          public Internet           +----v--------------+
|  Beam Pro / Glasses  |  ←-- WSS signal + WebRTC media --→ |  EC2 (Sophia)     |
|  + browser users     |                                    |  t3.large or      |
+----------------------+                                    |  t3.xlarge        |
                                                            |                   |
                                                            | docker compose:   |
                                                            |  - livekit-server |
                                                            |  - token-mint     |
                                                            |  - agent worker   |
                                                            |  - nginx (TLS)    |
                                                            +-------------------+
                                                                     ^
                                                                     |
                                            +------------------------+
                                            |
                                            |  Frontend (one of):
                                            |   A. Vercel (recommended)
                                            |   B. CloudFront + S3
                                            |   C. nginx on same EC2
                                            v
                                  +---------------------+
                                  |  agent-starter-react |
                                  |  https://sophia-app  |
                                  +---------------------+

Auxiliary:
  - Route 53: sophia.example.com -> EC2 elastic IP
  - ACM or Let's Encrypt: TLS cert for wss://
  - Secrets Manager: LIVEKIT_API_SECRET (no more devsecret-please-change)
  - CloudWatch: container stdout + stderr
  - Prometheus + Grafana (already in EKS): scrape EC2's /metrics
```

Network flow per user turn:
1. User opens https://sophia-app (frontend on Vercel).
2. Frontend POSTs https://sophia.example.com/token (token-mint on EC2).
3. Frontend opens WSS to sophia.example.com:443 (nginx terminates TLS, proxies to livekit-server on :7880).
4. WebRTC peer connection negotiates; audio flows UDP to EC2 on port 50000-60000.
5. Agent worker (in same Docker network as livekit-server) receives the user's audio track.
6. Agent worker calls EKS services over private VPC (whisper -> qwen3 -> kokoro + sophia-spatial-ai for RAG).
7. Sophia's TTS audio published back to the room; client plays it.

Round-trip latency stays in the 2-3s range we're seeing locally (already validated). Network adds 30-80 ms of WAN if the client is anywhere in the same continent as your AWS region. Negligible.

---

## What's in / what's NOT in this first deploy

In scope:
- One EC2 instance running the four processes via docker-compose
- TLS termination so clients can use wss://
- Token-mint reachable at a stable HTTPS URL
- Secrets in AWS Secrets Manager, not in repo
- Frontend deployed to a stable public URL
- Glasses + browser both connect to the same production stack
- CloudWatch + existing Grafana for monitoring

Out of scope (defer until you actually need them):
- High availability (multi-AZ EC2, redundant SFU)
- Auto-scaling (single EC2 handles dozens of concurrent rooms; only matters at hundreds)
- ECS / Kubernetes / Nomad (over-engineered for the workload)
- TURN server with TLS (livekit-server includes a built-in TURN; sufficient until you have clients behind super strict NAT)
- DDoS protection beyond what's free on the SG
- Multi-tenancy / per-client_id room namespacing (Q1 in unity_approach.md Appendix C, can layer on later)
- CI/CD pipeline (manual `git pull && docker compose up -d` for now, automate later)

---

## EC2 sizing

Recommended starting point: **t3.large** (2 vCPU, 8 GB RAM). Reasons:

- livekit-server is light: Go binary, single-digit % CPU per active room.
- token-mint is trivial: FastAPI with ~50 LOC, near-zero CPU.
- agent worker is the heaviest: Silero VAD loaded in EACH worker subprocess (~few hundred MB RAM per subprocess), turn-detector loaded once in an inference subprocess (~100 MB RAM), Python event loop. One subprocess per active room. Plan for ~500 MB per concurrent room with some headroom.
- nginx is trivial.

For testing + a handful of concurrent users: t3.large is plenty. For 10-20 concurrent rooms: bump to t3.xlarge (4 vCPU, 16 GB RAM, ~$120/month on-demand or ~$40 with a reserved instance). For 50+ concurrent: split the agent workers onto a separate instance and let the SFU host run on a smaller instance — that's the next milestone, not now.

Storage: 30 GB gp3 EBS is fine. The OS + Docker + image layers + logs come in under 10 GB.

Network: Standard, no enhanced networking needed at this scale.

---

## VPC + networking

### Same VPC as EKS

Critical: the EC2 instance MUST live in the SAME VPC (or a peered VPC) as your EKS cluster. Otherwise the agent worker can't reach the inference services without going over the public Internet, which defeats the whole architecture.

Pick a subnet in the same VPC. Probably a private subnet (so the instance isn't exposed) and put it behind a NAT gateway for outbound. Or use a public subnet with an elastic IP if you want the simpler path; security comes from the security group.

### Security group

Inbound rules on the EC2's SG:
| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | Your home IP only | SSH |
| 443 | TCP | 0.0.0.0/0 | HTTPS (frontend if co-hosted) + WSS (signaling) |
| 80 | TCP | 0.0.0.0/0 | HTTP for Let's Encrypt cert renewal |
| 50000-60000 | UDP | 0.0.0.0/0 | WebRTC media |
| 7881 | TCP | 0.0.0.0/0 | TURN/TCP fallback (optional, recommended) |

Outbound: allow all (default).

EKS services SG (already exists): add an inbound rule allowing the EC2's SG on ports 8080, 8106, 8120, 8122 (the inference service ports). This is the equivalent of kubectl port-forward but VPC-native.

### Service DNS from EC2

Inside the VPC, EKS services are reachable via their k8s service names. From the EC2 you can hit:
```
http://whisper-inference.multi-agent.svc.cluster.local:8080
http://qwen3-inference.multi-agent.svc.cluster.local:8080
http://kokoro-tts.multi-agent.svc.cluster.local:8122
http://sophia-spatial-ai.multi-agent.svc.cluster.local:8106
```

EXCEPT: EC2 doesn't natively resolve `*.svc.cluster.local`. Two options:

A. Put the EC2 inside a node group of the cluster itself (treat it like a k8s node). Then DNS works. More complex setup.

B. Use VPC Endpoint Services + ALB in front of each inference service. Each service gets a stable internal DNS name like `whisper.sophia.internal`. Cleaner separation but adds ~$15/mo per ALB.

C. (Pragmatic) Use the EKS LoadBalancer service hostnames or NodePort + private DNS. Have the infra team expose each inference service via an internal NLB (Network Load Balancer, ~$16/mo each, but only one needed if you put a router in front). Simplest day-to-day after setup.

Recommendation: **Option C** for the first deploy. Ask infra to put an internal NLB in front of each service (or one NLB + ALB rules per service) and give you stable DNS names. Then update `sophia-agent/.env.local` on the EC2 to point at those names instead of localhost ports.

---

## Per-component deployment

### Component 1 — livekit-server (the SFU)

Container: official `livekit/livekit-server:latest`. Same image we already vendored as a reference for Docker compose locally.

Config: `infra/livekit.yaml` (already exists in `sophia-agent/infra/`). Update for production:

```yaml
port: 7880
rtc:
  port_range_start: 50000
  port_range_end: 60000
  tcp_port: 7881
  use_external_ip: true        # CRITICAL: tells SFU to advertise its public IP
                                # so browser/Beam Pro can establish WebRTC

keys:
  ${SOPHIA_API_KEY}: ${SOPHIA_API_SECRET}    # injected via env, not hardcoded

logging:
  level: info
  pion_level: warn

webhook:                       # optional, for production observability
  api_key: ${SOPHIA_API_KEY}
  urls: []
```

Override the `--dev` flag we use locally. Production runs without it (no auto-room-creation, stricter auth). Pass real API key + secret from Secrets Manager via env vars.

### Component 2 — token-mint

Container: build from `sophia-agent/Dockerfile`. The current Dockerfile builds the whole agent — for production split out the token-mint into its own image:

```dockerfile
# sophia-agent/Dockerfile.token-mint
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ ./src/
EXPOSE 8001
CMD ["uv", "run", "uvicorn", "src.token_mint:app", "--host", "0.0.0.0", "--port", "8001"]
```

**SECURITY: Add auth to token-mint before production.** The current `app/api/token/route.ts` (Next.js dev fallback) throws in production mode for exactly this reason. The standalone `sophia-agent/src/token_mint.py` we use today has zero auth — anyone who can reach the endpoint can mint tokens for any room. Two patterns:

A. Require a signed bearer JWT from your identity provider (auth0, AWS Cognito, etc.) on the /token endpoint. token-mint verifies, then mints a LiveKit token scoped to the right room.

B. For a closed-deployment scenario (e.g. internal company tool), require a shared API key in the request header. Simpler, less secure.

For an MVP, option B is acceptable. Long-term, option A.

### Component 3 — agent worker

Container: same Dockerfile as today's `sophia-agent/Dockerfile`. The agent talks to:
- livekit-server at `ws://livekit-server:7880` (same Docker network)
- whisper-inference, qwen3-inference, kokoro-tts, sophia-spatial-ai at their VPC-internal DNS names

Update `sophia-agent/.env.local` on the EC2 (or via Docker secrets):
```
LIVEKIT_URL=ws://livekit-server:7880
LIVEKIT_API_KEY=<from Secrets Manager>
LIVEKIT_API_SECRET=<from Secrets Manager>

# These were localhost ports before; now they're VPC-internal NLB DNS names
WHISPER_URL=http://whisper.sophia.internal:8080
QWEN3_URL=http://qwen3.sophia.internal:8080
KOKORO_URL=http://kokoro.sophia.internal:8122
SOPHIA_SPATIAL_URL=http://sophia-spatial.sophia.internal:8106
```

The agent code needs to be updated to read these env vars instead of the hardcoded `http://localhost:8080` etc. that's there today. Currently `src/agent.py` has them hardcoded inline. About 4 lines of edit.

Multiple agent worker subprocesses: AgentServer auto-spawns one per active room. `num_idle_processes=2` pre-warms a couple so the first session doesn't pay cold-fork latency. Memory and queue-tuning needed past ~20 concurrent rooms.

### Component 4 — nginx (TLS termination + reverse proxy)

Single nginx container in the compose stack handles:
- HTTPS (port 443) for the frontend (if co-hosted) AND the token-mint endpoint
- WSS (port 443 with Upgrade header) proxied to livekit-server :7880

Sample `nginx/sophia.conf`:
```nginx
server {
    listen 443 ssl http2;
    server_name sophia.example.com;

    ssl_certificate     /etc/letsencrypt/live/sophia.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sophia.example.com/privkey.pem;

    # Token mint
    location /token {
        proxy_pass http://token-mint:8001/token;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # LiveKit WebSocket signaling
    location / {
        proxy_pass http://livekit-server:7880;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```

Use `certbot` (via docker compose or a sidecar) for Let's Encrypt cert provisioning and auto-renewal. Or use AWS ACM if you front everything with an ALB instead of nginx.

### Component 5 — frontend hosting

Three options:

A. **Vercel** (recommended): connect the GitHub repo, point Vercel at `agent-starter-react/`, set env vars (NEXT_PUBLIC_LIVEKIT_URL = wss://sophia.example.com, etc.). Auto-deploys on push to main. Free for low traffic.

B. **CloudFront + S3**: build the Next.js app statically (`next export`) and upload `out/` to S3 + put CloudFront in front. Costs pennies. Requires a build step on every change.

C. **Same EC2 nginx**: build the app on the EC2 with `npm run build`, run `npm start` in a container, nginx serves it. Simplest infrastructure but you're conflating "media plane" (livekit) and "control plane" (web app) on one box.

Recommend A. Vercel is the path of least friction for Next.js.

---

## Docker compose file (sample, for EC2)

```yaml
# /opt/sophia/docker-compose.yml on the EC2
version: '3.9'

services:
  livekit-server:
    image: livekit/livekit-server:latest
    network_mode: host        # required for UDP port ranges on Linux
    volumes:
      - ./infra/livekit.yaml:/etc/livekit.yaml:ro
    command: --config /etc/livekit.yaml
    environment:
      - SOPHIA_API_KEY=${SOPHIA_API_KEY}
      - SOPHIA_API_SECRET=${SOPHIA_API_SECRET}
    restart: unless-stopped

  token-mint:
    build:
      context: ./sophia-agent
      dockerfile: Dockerfile.token-mint
    expose:
      - "8001"
    environment:
      - LIVEKIT_URL=ws://127.0.0.1:7880
      - LIVEKIT_API_KEY=${SOPHIA_API_KEY}
      - LIVEKIT_API_SECRET=${SOPHIA_API_SECRET}
    restart: unless-stopped

  agent-worker:
    build:
      context: ./sophia-agent
      dockerfile: Dockerfile
    environment:
      - LIVEKIT_URL=ws://127.0.0.1:7880
      - LIVEKIT_API_KEY=${SOPHIA_API_KEY}
      - LIVEKIT_API_SECRET=${SOPHIA_API_SECRET}
      - WHISPER_URL=http://whisper.sophia.internal:8080
      - QWEN3_URL=http://qwen3.sophia.internal:8080
      - KOKORO_URL=http://kokoro.sophia.internal:8122
      - SOPHIA_SPATIAL_URL=http://sophia-spatial.sophia.internal:8106
    restart: unless-stopped

  nginx:
    image: nginx:1.27-alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx/sophia.conf:/etc/nginx/conf.d/sophia.conf:ro
      - ./certbot/conf:/etc/letsencrypt:ro
      - ./certbot/www:/var/www/certbot:ro
    restart: unless-stopped

  certbot:
    image: certbot/certbot:latest
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done'"
    restart: unless-stopped
```

Notes:
- livekit-server uses `network_mode: host` because Docker on Linux can route UDP through bridge networks but it adds NAT hops; host networking is simpler and cheaper. (Linux Docker doesn't have the macOS mDNS bug we hit in dev per livekit_deployment.md Q13.)
- token-mint and agent-worker don't need public ports; nginx proxies token-mint, agent-worker connects to livekit-server via host loopback.

---

## Step-by-step EC2 setup

### Prereqs

- AWS account with EKS cluster running in a VPC
- Route 53 hosted zone for your domain
- GitHub repo set up per `git_setup.md`
- IAM user with permissions to launch EC2, manage Route 53, read Secrets Manager

### Step 1 — Launch the EC2

```bash
# Via AWS CLI
aws ec2 run-instances \
  --image-id ami-0c80e2b6ccb9ad6d1 \                # Amazon Linux 2023, us-east-1
  --instance-type t3.large \
  --key-name your-keypair \
  --security-group-ids sg-xxxxxxxxxxxx \             # the SG defined above
  --subnet-id subnet-xxxxxxxx \                      # subnet in your VPC
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=sophia-agent-prod}]'
```

Or via console: EC2 -> Launch Instance, t3.large, Amazon Linux 2023, your SG, your VPC subnet, 30 GB gp3.

Once it's running, allocate an Elastic IP and associate with the instance. Point your Route 53 A record `sophia.example.com` at that EIP.

### Step 2 — Install Docker + Compose + Git

SSH in:
```bash
ssh -i your-keypair.pem ec2-user@<elastic-ip>
```

Then on the instance:
```bash
sudo dnf update -y
sudo dnf install -y docker git
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user
# Log out and back in for the group change

# Docker Compose plugin
sudo dnf install -y docker-compose-plugin
docker compose version
```

### Step 3 — Clone the repo

```bash
cd /opt
sudo git clone https://github.com/<your-user>/sophia-agent-research.git sophia
sudo chown -R ec2-user:ec2-user /opt/sophia
cd /opt/sophia
```

### Step 4 — Configure secrets

```bash
# Store secrets in AWS Secrets Manager
aws secretsmanager create-secret \
  --name sophia/livekit \
  --secret-string '{"LIVEKIT_API_KEY":"<random32chars>","LIVEKIT_API_SECRET":"<random64chars>"}'

# On the EC2, fetch them at boot time. Either:
# A. Manually populate /opt/sophia/.env.production once
# B. Add a systemd service that runs `aws secretsmanager get-secret-value` on boot and writes the .env file
# C. Use the AWS Secrets Manager Docker driver (Docker Compose can read secrets directly)

# Simplest for first deploy: option A
cat > /opt/sophia/.env.production << EOF
SOPHIA_API_KEY=<random32chars>
SOPHIA_API_SECRET=<random64chars>
EOF
chmod 600 /opt/sophia/.env.production
```

### Step 5 — Get TLS cert

```bash
# Bootstrap Let's Encrypt cert (one-time)
docker run --rm -p 80:80 \
  -v /opt/sophia/certbot/conf:/etc/letsencrypt \
  -v /opt/sophia/certbot/www:/var/www/certbot \
  certbot/certbot certonly --standalone -d sophia.example.com \
  --email you@example.com --agree-tos --non-interactive
```

After this, the cert lives at `/opt/sophia/certbot/conf/live/sophia.example.com/`. The certbot sidecar in the compose stack handles renewals automatically.

### Step 6 — Bring up the stack

```bash
cd /opt/sophia
docker compose --env-file .env.production up -d
docker compose ps                  # all four should be Up
docker compose logs --tail 50 livekit-server  # confirm SFU started
docker compose logs --tail 50 agent-worker   # confirm worker registered against SFU
docker compose logs --tail 50 nginx          # confirm cert loaded
```

### Step 7 — Verify externally

From your laptop (not the EC2):
```bash
curl -sI https://sophia.example.com/token | head -5   # 200 (or 405 if it's POST-only) means nginx + token-mint reachable
wscat -c wss://sophia.example.com                      # WebSocket handshake; LiveKit returns its banner
```

If wscat connects and shows the LiveKit signal protocol, the SFU is reachable over WSS.

### Step 8 — Point the frontend at production

Vercel: set env vars on the project:
```
NEXT_PUBLIC_LIVEKIT_URL=wss://sophia.example.com
TOKEN_ENDPOINT=https://sophia.example.com/token
LIVEKIT_API_KEY=<random32chars>     # only needed for the fallback Next.js route
LIVEKIT_API_SECRET=<random64chars>
AGENT_NAME=sophia-agent
```

Push to GitHub main; Vercel auto-deploys; visit https://sophia-app.vercel.app and click Start Call.

### Step 9 — Point the glasses at production

In Unity Editor, open `sophia-glasses/unity/Assets/Settings/SophiaConfig.asset` and change:
```
liveKitUrl    = wss://sophia.example.com
tokenEndpoint = https://sophia.example.com/token
```

Rebuild APK, reinstall on Beam Pro. The glasses now connect to your EC2 stack from anywhere on the Internet (no more Tailscale required).

---

## Migration path from current laptop

You don't have to abandon the laptop dev environment. Run both in parallel:

- Dev: keep your laptop stack running (`livekit-server --dev` + token-mint + agent + frontend). Tweak code, iterate, test in browser at localhost:3000.
- Production: deploy via `git push` -> SSH to EC2 -> `git pull && docker compose up -d --build`. Test at https://sophia-app.vercel.app.

For glasses: SophiaConfig.asset is the only switch. Swap between Tailscale dev URL and production URL per build. Eventually wrap both in a build-time `#if DEVELOPMENT_BUILD` so Development builds talk to laptop, Release builds talk to production.

---

## Cost estimate (first month)

| Item | Monthly |
|---|---|
| t3.large EC2, on-demand | ~$60 |
| 30 GB gp3 EBS | ~$3 |
| Elastic IP (associated) | $0 |
| Route 53 hosted zone | $0.50 |
| Route 53 queries (low) | ~$0.40 |
| Data transfer out (~50 GB/month, WebRTC) | ~$4.50 |
| Vercel hobby plan | $0 |
| Let's Encrypt cert | $0 |
| AWS Secrets Manager (1 secret) | $0.40 |
| CloudWatch logs (5 GB/mo) | ~$2.50 |
| Optional NLBs for inference services (3 x $16) | ~$48 |
| **Total (without NLBs)** | **~$70** |
| **Total (with NLBs)** | **~$120** |

Reserved instance for the EC2 brings it to ~$40/mo (1-year, no upfront). NLB costs are the biggest variable; can avoid by joining the EC2 to the EKS node group instead.

---

## What can go wrong + how to fix

| Symptom | Cause | Fix |
|---|---|---|
| Browser shows "could not establish PC connection" | use_external_ip not set or SG blocks UDP | Confirm livekit.yaml has `use_external_ip: true`; confirm SG allows UDP 50000-60000 from 0.0.0.0/0 |
| Agent worker can't reach Whisper | wrong VPC or SG between EC2 and EKS | confirm SG on EKS services allows EC2's SG on the service port |
| Token-mint returns 500 on /token | secrets not loaded into container env | check `docker compose logs token-mint`; confirm .env.production is loaded by `--env-file` |
| TLS cert won't renew | certbot can't reach port 80 | SG rule allows port 80; nginx has webroot path for /.well-known/acme-challenge/ |
| Glasses can't connect from outside Wi-Fi | DNS not propagated, or wss not properly proxied | dig sophia.example.com from phone's network; curl -v https://sophia.example.com from phone tether |
| `docker compose up` fails on agent worker due to OOM | t3.large too small for many concurrent rooms | bump to t3.xlarge, or split agent worker onto its own instance |

---

## Next steps after this works

1. **Auth on token-mint**: replace shared-key auth with proper JWT verification from your auth provider.
2. **Multi-tenant room naming**: enforce `{client_id}/{session_id}` per Appendix C Q1 in unity_approach.md.
3. **Auto-deploy via GitHub Actions**: on push to main, SSH to EC2 and `git pull && docker compose up -d --build`.
4. **High availability**: second EC2 behind ALB for failover; LiveKit redis-backed clustering for multi-node SFU.
5. **CDN for the frontend**: CloudFront in front of Vercel (or replace Vercel with CloudFront + S3).
6. **Egress recording**: livekit-egress for session recording.
7. **Observability**: ship docker logs to CloudWatch, scrape /metrics into existing Grafana, set up alerts.

---

## Quick reference

| What you want | Where |
|---|---|
| Architecture diagram | top of this file |
| EC2 size + cost | "EC2 sizing" + "Cost estimate" sections |
| Networking setup | "VPC + networking" section |
| Per-component config | "Per-component deployment" section |
| The actual docker-compose.yml | "Docker compose file" section |
| Step-by-step setup | "Step-by-step EC2 setup" section |
| Frontend hosting options | "Component 5 — frontend hosting" |
| Glasses client repointing | "Step 9 — Point the glasses at production" |
| Common failures | "What can go wrong" matrix |
