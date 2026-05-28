# MVP deployment on shared EC2 (sophia-gpu) — personal reference

Personal reference for Avinash. Captures everything: how we deployed, how to RUN it day-to-day, every problem we hit, and how we fixed them. Read this when you come back to the project in three months and don't remember anything.

For the engineering-level deep dive: `deploy_to_ec2.md` at project root.
For design rationale (MVP vs production tradeoffs): see "Architecture" + "Why MVP" sections below.

---

## Current state (as of 2026-05-28)

Running on EC2 (verified working internally):
- LiveKit SFU (livekit-server in docker)
- Token-mint (FastAPI in docker)
- Agent worker (registered against SFU)
- kubectl port-forwards to EKS inference services (Whisper / Qwen3 / Kokoro / sophia-spatial-ai)

PENDING:
- Security group inbound rules — PR opened against aws-infra (waiting on infra to merge + run `terraform apply`). Until then no external client can reach the EC2.
- Frontend (built but not yet started — will start once SG opens)
- Glasses repointed at the EC2 public IP (still pointed at laptop Tailscale URL)
- End-to-end demo from a browser and from the glasses

---

## Key info / constants

| Thing | Value |
|---|---|
| EC2 instance ID | `i-0748ed7c188c337cc` |
| EC2 type | g5.2xlarge (NVIDIA A10G, 32 GB RAM, ~$1.21/hr) |
| Region | us-east-1, AZ us-east-1a |
| Public IP (Elastic) | 3.227.63.49 |
| Private IP | 10.20.1.90 |
| VPC | vpc-0eeab16713f4f744d |
| Security Group | sophiaspatialai-gpu-20260511165512897100000004 |
| OS | Ubuntu 22.04.5 LTS (Deep Learning AMI) |
| SSH user | ubuntu |
| SSH alias from laptop | `ssh sophia-gpu` (config at `~/.ssh/config`) |
| SSH key | `~/.ssh/sophiaspatialai-ai-us-east-1.pem` |
| Working dir on EC2 | `/workspace/avinash/sophia/` |
| Shared with | Ivana (her ports: 8888 Jupyter, 8501/8502 Streamlit, vLLM, cloudflared) |
| EKS cluster name | `spatial-ai-staging` |
| EKS region | us-west-2 (DIFFERENT region from EC2) |
| EKS account | 632872792182 |
| IAM Instance Profile role | `sophiaspatialai-ai-gpu-ec2` (lacks EKS permissions; see Problem 5) |
| GitHub repo | `git@github.com:AvinashSophia/sophia-agent-research.git` |
| AWS infra repo | `git@github.com:AIPartnersUSA/aws-infra.git` (branch `fix-state`) |

Ports we use (must be in SG inbound rules):
- TCP 3000 — Sophia frontend (Next.js)
- TCP 7880 — LiveKit SFU WebSocket signaling
- TCP 7881 — LiveKit TURN/TCP fallback
- TCP 8001 — Token-mint (FastAPI)
- UDP 50000-60000 — WebRTC media

---

## How to RUN the deployment day-to-day

### Cold start (EC2 was stopped)

1. Start EC2 from your laptop:
   ```bash
   aws ec2 start-instances --region us-east-1 --instance-ids i-0748ed7c188c337cc
   ```
   Wait ~1 minute.

2. SSH in:
   ```bash
   ssh sophia-gpu
   ```

3. Set AWS credentials in the SSH session (needed for kubectl port-forwards). Generate fresh temporary creds in AWS Console → IAM → your user → Security credentials → "Generate temporary credentials" (or use SSO). Then paste:
   ```bash
   export AWS_ACCESS_KEY_ID=ASIA...
   export AWS_SECRET_ACCESS_KEY=...
   export AWS_SESSION_TOKEN=...
   aws sts get-caller-identity   # confirm it shows YOUR user ARN
   ```

4. Start the kubectl port-forwards:
   ```bash
   cd /workspace/avinash/sophia
   ./sophia-agent/infra/pf-gpu.sh
   sleep 5
   # verify all four respond
   curl -s http://localhost:8122/health
   curl -s http://localhost:8080/v1/models | head -c 200
   curl -s http://localhost:18080/v1/models | head -c 200
   curl -s http://localhost:8106/health
   ```

5. Bring up the docker stack (they auto-start via `restart: unless-stopped` but may not start cleanly if Docker daemon was slow on boot, so verify):
   ```bash
   docker compose ps
   # if not up:
   docker compose up -d
   docker compose logs --tail 20 agent-worker
   ```
   Look for `registered worker ... url: ws://localhost:7880` in agent-worker logs.

6. Start the frontend:
   ```bash
   cd /workspace/avinash/sophia/agent-starter-react
   nohup npm start -- --port 3000 --hostname 0.0.0.0 > /workspace/avinash/sophia/frontend.log 2>&1 &
   disown
   sleep 3
   ss -tlnp | grep :3000
   ```

7. Test from your laptop browser: http://3.227.63.49:3000

### Warm start (EC2 already running, just need to restart services)

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia

# Re-export AWS creds if they expired (typical after ~1 hour for STS)
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...

# Restart port-forwards (they probably died with the old creds)
./sophia-agent/infra/pf-gpu.sh stop 2>/dev/null
./sophia-agent/infra/pf-gpu.sh

# Restart docker services to pick up fresh port-forwards
docker compose restart agent-worker

# Frontend (only if not running)
ps -ef | grep '[n]ode' | grep next
# if absent:
cd agent-starter-react
nohup npm start -- --port 3000 --hostname 0.0.0.0 > /workspace/avinash/sophia/frontend.log 2>&1 &
disown
```

### Status check at any time

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia

# Docker containers
docker compose ps

# Internal health
curl -s http://localhost:8001/health
curl -sI http://localhost:7880/ | head -1

# Port-forwards alive?
cat /tmp/pf-gpu.pids 2>/dev/null
ps -ef | grep '[k]ubectl port-forward' | head

# Inference services reachable via port-forward
curl -s --max-time 3 http://localhost:8080/v1/models | head -c 100

# Agent registration
docker compose logs --tail 5 agent-worker | grep -i registered

# Frontend
ss -tlnp | grep ':3000'
```

### Stop everything (save money)

```bash
# Tell Ivana before stopping the EC2 since she shares it.
# (Stopping docker doesn't save money, only stopping the EC2 does.)

ssh sophia-gpu
cd /workspace/avinash/sophia
./sophia-agent/infra/pf-gpu.sh stop
docker compose down
exit

# From laptop:
aws ec2 stop-instances --region us-east-1 --instance-ids i-0748ed7c188c337cc
```

Cost note: g5.2xlarge runs at ~$1.21/hour. Running 24/7 = ~$870/month. Stopping when not demoing saves real money. Elastic IP persists across stop/start so URL stays the same.

---

## Architecture (simplified)

```
+----------+              public Internet              +-------------------------+
| browser  | -- HTTP --> :3000 (Next.js frontend) ---> | EC2: 3.227.63.49        |
|          | -- HTTP --> :8001 (token-mint)            | shared GPU box,         |
|          | -- WS   --> :7880 (livekit-server)        | /workspace/avinash/     |
|          | -- UDP  --> :50000-60000 (WebRTC media)   |                         |
+----------+                                           |  docker compose:        |
                                                       |   livekit-server        |
+----------+                                           |   token-mint            |
| glasses  | -- WS   --> :7880 (signal)                |   agent-worker          |
| (Beam Pro| -- HTTP --> :8001 (/token)                |   frontend (Next.js)    |
|  +XREAL) | -- UDP  --> :50000-60000 (media)          |                         |
+----------+                                           +------------+------------+
                                                                    |
                                                       kubectl port-forward
                                                       (cross-region, via EKS API)
                                                                    |
                                                       +------------v------------+
                                                       | EKS spatial-ai-staging  |
                                                       | us-west-2 (different    |
                                                       | region from EC2)        |
                                                       |  whisper / qwen3 /      |
                                                       |  kokoro / spatial-ai    |
                                                       +-------------------------+
```

Browser and glasses talk directly to the EC2. The EC2 reaches the EKS inference services via kubectl port-forwards (cross-region — adds ~70ms latency but works).

---

## Why MVP (not full production)

- Shared GPU box already provisioned by infra — zero infra lead time.
- No domain / TLS / Secrets Manager — saves hours of setup. Browser shows "Not Secure" but voice loop works.
- Goal: validate the architecture for the team BEFORE asking for dedicated production infra.

When team approves moving past MVP, follow `production_deployment.md` for proper setup (separate t3.large in us-west-2 to eliminate cross-region latency, domain, TLS, Secrets Manager, SSO auth, etc.). The MVP work is the bridge.

---

## Initial deployment walkthrough (what we did)

### Phase 0 — Pre-deploy code changes (locally, then pushed to GitHub)

Three changes made to make the code production-ready (dev-safe — defaults preserve local behavior when env vars are unset):

1. `sophia-agent/src/token_mint.py`:
   - Added X-API-Key header check gated by `SOPHIA_TOKEN_API_KEY` env var. When unset, no auth.
   - Added `SOPHIA_CORS_ORIGINS` env var (comma-separated). When unset, defaults to `*`.

2. `sophia-agent/src/agent.py`:
   - Replaced hardcoded `http://localhost:8080` etc. with env-driven module constants (WHISPER_URL, QWEN3_URL, KOKORO_URL, SOPHIA_RAG_URL).
   - Defaults match the kubectl-port-forward localhost URLs so local dev unchanged.

3. New file `sophia-agent/Dockerfile.token-mint`:
   - Slimmer than the agent worker Dockerfile (skips Silero/turn-detector download).
   - Uses `uv sync --locked --no-dev`.
   - CMD runs uvicorn directly.

All three committed and pushed before starting EC2 work.

### Phase 1 — SSH access from laptop

1. Got from infra: public IP, instance ID, SSH user, .pem key file, instructions.
2. Moved .pem to `~/.ssh/` on Mac (had to use Finder since macOS Privacy blocks Terminal from `~/Downloads`).
3. `chmod 600 ~/.ssh/sophiaspatialai-ai-us-east-1.pem`.
4. Added Host alias to `~/.ssh/config`:
   ```
   Host sophia-gpu
       HostName 3.227.63.49
       User ubuntu
       IdentityFile ~/.ssh/sophiaspatialai-ai-us-east-1.pem
       ServerAliveInterval 60
   ```
5. `ssh sophia-gpu` — accepted the host key fingerprint on first connect.

### Phase 2 — Surveyed the EC2

Confirmed Docker + Compose + Git were already installed. Missing: uv, Node, Git LFS. Confirmed VPC (vpc-0eeab16713f4f744d) and SG name. Noted Ivana's services running on 8888 (Jupyter), 8501/8502 (Streamlit), vLLM, cloudflared. Verified our planned ports (3000/7880/7881/8001) were free.

### Phase 3 — Installed missing tools

```bash
mkdir -p /workspace/avinash/sophia
cd /workspace/avinash/sophia

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Node 22.x
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

# Git LFS
sudo apt-get install -y git-lfs
git lfs install
```

Hit the `needrestart` whiptail prompt on apt installs — Tab+Enter to accept defaults. To suppress: `export DEBIAN_FRONTEND=noninteractive; export NEEDRESTART_MODE=a`.

### Phase 4 — SSH key on EC2 + GitHub

```bash
ssh-keygen -t ed25519 -C "sophia-gpu-ec2"
cat ~/.ssh/id_ed25519.pub
# Copied output to GitHub > Settings > SSH and GPG keys > New SSH key
```

### Phase 5 — Cloned repo

```bash
cd /workspace/avinash/sophia
git clone git@github.com:AvinashSophia/sophia-agent-research.git .
# (trailing dot clones INTO current dir, not into a subdirectory)
git lfs pull
# verify binaries are real, not pointer text:
ls sophia-glasses/xreal-sdk/Runtime/Plugins/Android/ | head
```

### Phase 6 — Generated secrets

```bash
LIVEKIT_KEY=$(openssl rand -hex 16)
LIVEKIT_SECRET=$(openssl rand -hex 32)
TOKEN_API_KEY=$(openssl rand -hex 16)
echo "$LIVEKIT_KEY $LIVEKIT_SECRET $TOKEN_API_KEY"
# Saved values to a private note for later reuse in frontend env too.
```

### Phase 7 — Created config files

`sophia-agent/.env.production` — built line-by-line because heredocs were getting mangled by terminal paste adding leading whitespace:

```bash
{
  echo "LIVEKIT_URL=ws://3.227.63.49:7880"
  echo "LIVEKIT_API_KEY=$LIVEKIT_KEY"
  echo "LIVEKIT_API_SECRET=$LIVEKIT_SECRET"
  echo "SOPHIA_TOKEN_API_KEY=$TOKEN_API_KEY"
  echo "SOPHIA_CORS_ORIGINS=*"
  echo ""
  # NOTE: these are localhost since kubectl port-forwards listen there
  echo "WHISPER_URL=http://localhost:8080"
  echo "QWEN3_URL=http://localhost:18080"
  echo "KOKORO_URL=http://localhost:8122"
  echo "SOPHIA_RAG_URL=http://localhost:8106"
} > sophia-agent/.env.production
chmod 600 sophia-agent/.env.production
```

`sophia-agent/infra/livekit.prod.yaml` — production-friendly LiveKit config:

```bash
set -a; source sophia-agent/.env.production; set +a
{
  echo "port: 7880"
  echo ""
  echo "rtc:"
  echo "  tcp_port: 7881"
  echo "  port_range_start: 50000"
  echo "  port_range_end: 60000"
  echo "  use_external_ip: false"
  echo ""
  echo "keys:"
  echo "  $LIVEKIT_API_KEY: $LIVEKIT_API_SECRET"
  echo ""
  echo "logging:"
  echo "  level: info"
  echo "  json: false"
} > sophia-agent/infra/livekit.prod.yaml
chmod 600 sophia-agent/infra/livekit.prod.yaml
```

`docker-compose.yml` at workspace root (this is the FINAL version after the agent-worker env override fix):

```yaml
services:
  livekit-server:
    image: livekit/livekit-server:latest
    network_mode: host
    volumes:
      - ./sophia-agent/infra/livekit.prod.yaml:/etc/livekit.yaml:ro
    command: --config /etc/livekit.yaml --node-ip 3.227.63.49
    restart: unless-stopped

  token-mint:
    build:
      context: ./sophia-agent
      dockerfile: Dockerfile.token-mint
    ports:
      - "8001:8001"
    env_file:
      - ./sophia-agent/.env.production
    restart: unless-stopped

  agent-worker:
    build:
      context: ./sophia-agent
      dockerfile: Dockerfile
    network_mode: host
    env_file:
      - ./sophia-agent/.env.production
    environment:
      # CRITICAL: override LIVEKIT_URL to localhost because agent worker
      # is co-located with livekit-server. Public IP would route through
      # SG (which would also need an outbound trip) — wasteful and fails
      # until SG is open. See Problem 6.
      - LIVEKIT_URL=ws://localhost:7880
    restart: unless-stopped
```

### Phase 8 — Built and started

```bash
docker compose build token-mint agent-worker
docker compose up -d livekit-server token-mint
sleep 5
curl -s http://localhost:8001/health    # JSON ok
curl -sI http://localhost:7880/         # HTTP 200
```

Agent-worker added LATER after the kubectl port-forwards were working (see Phase 11).

### Phase 9 — Discovered cross-region

Tried `nslookup whisper-inference.multi-agent.svc.cluster.local` from EC2 — SERVFAIL. Then checked from Mac:

```bash
kubectl config view --minify -o jsonpath='{.clusters[0].name}'
# returned: arn:aws:eks:us-west-2:632872792182:cluster/spatial-ai-staging
```

EKS is in us-west-2; EC2 is in us-east-1. Different regions → different VPCs → no same-VPC path. Pivoted to kubectl port-forward from the EC2 over the EKS public/private API endpoint (cross-region works, ~70ms latency penalty per inference call).

### Phase 10 — kubectl + AWS auth on EC2

```bash
# Install kubectl
cd /tmp
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
kubectl version --client
```

The EC2's IAM Instance Profile (`sophiaspatialai-ai-gpu-ec2`) lacks `eks:DescribeCluster`, so `aws eks update-kubeconfig` fails with AccessDenied. Two workarounds (use whichever you prefer day-to-day):

Workaround A — copy kubeconfig from Mac (the kubeconfig itself doesn't store secrets; it uses `aws eks get-token` at request time):

```bash
# From Mac:
scp ~/.kube/config sophia-gpu:.kube/config
```

But then kubectl auth still needs the EC2's identity to be in the cluster's aws-auth ConfigMap — and the EC2's IAM role isn't.

Workaround B (what we actually use) — export YOUR temporary STS credentials as env vars on the EC2 so kubectl uses YOUR user identity (which IS in aws-auth):

```bash
# On the EC2 (paste fresh values each session — STS creds expire ~1 hour):
export AWS_ACCESS_KEY_ID=ASIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...
aws sts get-caller-identity      # should show YOUR ARN, not the instance role
kubectl get nodes                 # should list cluster nodes
kubectl get svc -n multi-agent    # should list the inference services
```

Caveat: env vars only apply to the current shell session. SSH disconnect → need to re-export on reconnect. Also expire when STS session ends. So plan to re-export at start of each demo session.

### Phase 11 — Start port-forwards + agent-worker

```bash
cd /workspace/avinash/sophia
./sophia-agent/infra/pf-gpu.sh
sleep 5
curl -s http://localhost:8122/health     # all four should respond
```

Add agent-worker to docker-compose (the LIVEKIT_URL=ws://localhost:7880 override block from the final docker-compose.yml above). Then:

```bash
docker compose build agent-worker
docker compose up -d agent-worker
docker compose logs --tail 50 -f agent-worker
# Wait for: "registered worker ... url: ws://localhost:7880"
```

### Phase 12 — Frontend build (NOT yet running externally)

```bash
cd /workspace/avinash/sophia/agent-starter-react
npm install
# write .env.local
{
  echo "LIVEKIT_URL=ws://3.227.63.49:7880"
  echo "LIVEKIT_API_KEY=$LIVEKIT_API_KEY"
  echo "LIVEKIT_API_SECRET=$LIVEKIT_API_SECRET"
} > .env.local
npm run build
# (will start with `npm start` once SG is open)
```

### Phase 13 — Opened PR for SG rules

Cloned the aws-infra repo, created branch `feat/sophia-sg-opens` off `fix-state`, added 5 ingress blocks to `environments/single_g5x2large_us_east_1/main.tf`, pushed, opened PR. Waiting on infra to merge + `terraform apply`.

PR: <fill in URL after creation>

### Phase 14 — Glasses (PENDING)

Once SG is open, edit `sophia-glasses/unity/Assets/Settings/SophiaConfig.asset` in Unity to swap:
- liveKitUrl: `ws://100.69.34.194:7880` → `ws://3.227.63.49:7880`
- tokenEndpoint: `http://100.69.34.194:8001/token` → `http://3.227.63.49:8001/token`

Rebuild APK, install on Beam Pro, test.

---

## Problems we hit + fixes

### Problem 1 — macOS Privacy blocks Terminal from `~/Downloads`

Symptom: `mv ~/Downloads/sophiaspatialai-ai-us-east-1.pem ~/.ssh/` returns "Operation not permitted".

Cause: macOS Sequoia/Sonoma blocks Terminal access to `~/Downloads`, `~/Documents`, `~/Desktop` by default.

Fix: either grant Terminal Full Disk Access in System Settings > Privacy & Security > Full Disk Access (then quit + reopen Terminal), or use Finder to move the file (Finder is always allowed).

### Problem 2 — Heredoc paste in Terminal added leading whitespace

Symptom: `cat > file <<EOF` heredocs got mangled with leading spaces on every line including the EOF terminator, causing bash to wait forever for a matching EOF.

Cause: Terminal paste normalization added indentation.

Fix: use line-by-line `{ echo "..."; echo "..."; } > file` instead. Each line is its own command, paste-safe.

### Problem 3 — npm install ran from wrong dir

Symptom: `npm install` in `/workspace/avinash/sophia` → "Could not read package.json".

Cause: package.json is in `agent-starter-react/`, not at workspace root.

Fix: `cd agent-starter-react` first.

### Problem 4 — needrestart whiptail prompt during apt installs

Symptom: apt install pops up a colored dialog asking which services to restart, terminal stuck.

Cause: Ubuntu 22.04 default.

Fix: Tab + Enter to accept defaults. Or per-session: `export DEBIAN_FRONTEND=noninteractive; export NEEDRESTART_MODE=a`.

### Problem 5 — `aws eks update-kubeconfig` AccessDenied on EC2

Symptom: "is not authorized to perform: eks:DescribeCluster".

Cause: EC2's IAM Instance Profile `sophiaspatialai-ai-gpu-ec2` lacks EKS permissions.

Fix: either (a) copy kubeconfig from Mac via scp, or (b) export AWS env vars from your user's temporary STS creds. We use (b). See Phase 10 Workaround B.

### Problem 6 — Agent-worker timeout connecting to SFU

Symptom: agent-worker logs `ConnectionTimeoutError: Connection timeout to host ws://3.227.63.49:7880/agent`.

Cause: agent-worker was using LIVEKIT_URL=ws://3.227.63.49:7880 (the public IP) to reach the SFU, but both processes are on the SAME host. Packet goes out the public interface, hits the AWS SG (which doesn't have port 7880 open inbound yet), gets dropped → timeout.

Fix: override LIVEKIT_URL for the agent-worker container only via docker-compose `environment` block:

```yaml
agent-worker:
  ...
  env_file:
    - ./sophia-agent/.env.production
  environment:
    - LIVEKIT_URL=ws://localhost:7880   # override; loopback to local SFU
```

`network_mode: host` means agent-worker's `localhost` is the EC2's `localhost`, which is where livekit-server listens. Loopback, no SG involved, instant connection.

### Problem 7 — Turn-detector model not found

Symptom: agent-worker logs `RuntimeError: livekit-plugins-turn-detector initialization failed. Could not find file "model_q8.onnx"`.

Cause: The Dockerfile's `RUN uv run src/agent.py download-files` step downloads the model to `/root/.cache/huggingface/` in the BUILD stage. The multi-stage `COPY --from=build /app /app` only copies /app, so the cache (outside /app) gets dropped. Final stage runs as `appuser` with HOME=/app, can't find the model.

Fix: set `HF_HOME=/app/.cache/huggingface` in the Dockerfile BEFORE the download step so the cache ends up under /app and gets copied:

```dockerfile
# In build stage, before download-files:
ENV HF_HOME=/app/.cache/huggingface
RUN uv run "src/agent.py" download-files

# In final stage, after USER appuser:
ENV HF_HOME=/app/.cache/huggingface
```

Then `docker compose build agent-worker` and `up -d`.

### Problem 8 — Frontend build TypeScript error (Framer Motion)

Symptom: `next build` fails with `Type '{ duration: number; ease: string; }' is not assignable to type 'Transition<any> | undefined'`.

Cause: Latest Framer Motion's `transition.ease` type requires the `Easing` literal type, not generic `string`. TypeScript inferred `ease: 'linear'` as `string` because the object wasn't a const literal.

Fix: add `as const` to the VIEW_MOTION_PROPS object in `components/app/view-controller.tsx`:

```ts
const VIEW_MOTION_PROPS = {
  // ...existing
  transition: {
    duration: 0.5,
    ease: 'linear',
  },
} as const;
```

### Problem 9 — Frontend build ESLint prettier errors

Symptom: Build compiles but fails on ESLint with dozens of prettier formatting errors in starter-template files (opengraph-image.tsx, agent-events-panel.tsx, rag-result-panel.tsx, etc.).

Cause: Existing template files don't conform to prettier rules. Not our code.

Fix (quick, for MVP): add to `next.config.ts`:

```ts
const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  // ... existing config
};
```

Build succeeds. Long-term fix would be `npx prettier --write .` to auto-fix all the files.

### Problem 10 — SG blocks external access

Symptom: From laptop, `curl http://3.227.63.49:7880` times out, but on the EC2 itself `curl http://127.0.0.1:7880` works.

Cause: AWS Security Group denies all inbound by default. Only ports explicitly listed in inbound rules are reachable from the internet. SG had only 22 (SSH) and 8888 (Jupyter) open.

Fix: add the 5 needed ports (TCP 3000/7880/7881/8001 + UDP 50000-60000) as ingress blocks in `aws_security_group.gpu` in `environments/single_g5x2large_us_east_1/main.tf` in the aws-infra repo. Opened PR. Waiting on infra to merge + `terraform apply`.

### Problem 11 — Cross-region EKS

Symptom: `nslookup whisper-inference.multi-agent.svc.cluster.local` returns SERVFAIL from EC2.

Cause: EKS cluster is in us-west-2, EC2 is in us-east-1. Different regions = different VPCs by definition. cluster.local DNS only resolves from inside the cluster's VPC.

Fix: use kubectl port-forward from the EC2 instead. The EKS API endpoint is publicly reachable; port-forward works cross-region. Pay ~70ms latency penalty per inference call and ~$0.02/GB data transfer.

For real production, move the EC2 to us-west-2 (same region as EKS) to eliminate the penalty.

---

## Glasses repointing (when ready)

Once SG is open and browser demo works, point the glasses at the EC2.

In Unity Editor on your Mac:
1. Open `sophia-glasses/unity/`.
2. Open `Assets/Settings/SophiaConfig.asset` in the Inspector.
3. Edit two fields:
   - liveKitUrl: change to `ws://3.227.63.49:7880`
   - tokenEndpoint: change to `http://3.227.63.49:8001/token`
4. Save (Cmd+S).
5. File menu → Build Profiles → Build (outputs APK to `sophia-glasses/unity/sophia-glasses.apk`).

Install on Beam Pro:

```bash
adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
adb logcat | grep -E 'Sophia|LiveKit'
```

Tap Allow on mic permission. Pick Private Session. Speak. Sophia answers. No Tailscale needed, no laptop in the critical path.

---

## Caveats / known issues

Browser autoplay & mic permission over HTTP:
- Chrome may block `getUserMedia` over plain HTTP from a non-localhost public IP.
- Workaround: `chrome://flags/#unsafely-treat-insecure-origin-as-secure` → add `http://3.227.63.49:3000` → restart Chrome.
- Or test on Firefox (more permissive).
- Real fix: add TLS via a domain. Defer to production.

Cross-region latency:
- ~70ms extra per inference call (us-east-1 → us-west-2 round-trip).
- Demo feels slightly more sluggish than local laptop tests.
- Acceptable for MVP. Eliminate by moving EC2 to us-west-2 for production.

STS credential expiry:
- AWS env vars on EC2 expire ~1 hour after STS issue.
- kubectl + port-forwards stop working when they expire.
- Re-export fresh credentials at start of each session.

EC2 reboot recovery:
- Docker containers auto-restart (restart: unless-stopped policy).
- kubectl port-forwards do NOT (they need fresh AWS creds + the script re-run).
- Frontend `npm start` does NOT (no systemd unit yet).
- So after a reboot: re-export AWS creds, re-run pf-gpu.sh, re-start frontend.

Shared box with Ivana:
- Don't touch her ports (8888, 8501, 8502).
- Don't install global services without coordinating.
- Don't stop the EC2 without asking her.
- Keep everything in `/workspace/avinash/`.

---

## What's NOT in this MVP (defer to production_deployment.md)

- TLS (no domain, no Let's Encrypt)
- High availability (single point of failure)
- Auto-deploy from GitHub Actions
- Secrets in AWS Secrets Manager (using chmod 600 local files)
- CloudWatch log aggregation
- Multi-tenant room namespacing per client
- Token-mint behind proper SSO auth
- Same-region EKS+EC2 (currently cross-region us-east-1 → us-west-2)
- Backup / disaster recovery
- Cost-optimized non-GPU instance
- Systemd unit for docker-compose autostart

All of those are layered on when team approves moving past MVP. See `production_deployment.md` + the JupyterLab pattern in the aws-infra repo for reference.
