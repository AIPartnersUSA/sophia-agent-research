# MVP deployment on shared EC2 (sophia-gpu) — personal reference

Personal reference for Avinash. Captures everything: how we deployed, how to RUN it day-to-day, every problem we hit, and how we fixed them. Read this when you come back to the project in three months and don't remember anything.

For the engineering-level deep dive: `deploy_to_ec2.md` at project root.
For design rationale (MVP vs production tradeoffs): see "Architecture" + "Why MVP" sections below.

---

**Handing this off to the infra team?** Point them at `HANDOFF.md` at the project root. That doc is written specifically for someone tasked with the MVP→production migration and tells them what's in the repo, what's intentionally not, what to preserve, and what to build. This file (the one you're reading) is the operational runbook for the MVP itself — your infra colleague should read HANDOFF.md FIRST, then this file SECOND.

**Want to understand HOW it all works end-to-end (not just how to operate it)?** Read `livekit_architectur_ec2.md`. It walks through both client paths (browser + XREAL glasses) step-by-step from page load / app launch all the way to Sophia answering, naming every component, every port, every JWT field, every inference call.

**Have an XR engineer with their own build who wants Sophia voice in it?** Send them `xr_build_voice_integration.md`. It's a focused guide for integrating Sophia into an existing XR project (Quest, Vision Pro, XREAL, HoloLens, etc.) — what stays the same on the backend, what they need to copy/adapt on the client, two integration paths with effort estimates, platform-specific gotchas.

## Current state (as of 2026-05-29 — DEMO WORKING END-TO-END)

Running on EC2 + verified externally:
- LiveKit SFU (livekit-server in docker)
- Token-mint (FastAPI in docker, with X-API-Key auth ENABLED via SOPHIA_TOKEN_API_KEY)
- Agent worker (registered against SFU)
- kubectl port-forwards to EKS inference services (Whisper / Qwen3 / Kokoro / sophia-spatial-ai)
- Frontend (Next.js production build serving on :3000)

DONE 2026-05-29 (the demo unblock day):
- Infra merged the SG PR and ran `terraform apply` (Aziz). External access works: laptop curl to :8001 / :7880 returns 200.
- Browser demo working at http://3.227.63.49:3000 from Chrome (requires the chrome://flags#unsafely-treat-insecure-origin-as-secure flag for the public IP since plain HTTP).
- Glasses demo working on Beam Pro + XREAL One Pro. APK rebuilt with EC2 URL in SophiaConfig.asset + the X-API-Key wired in SophiaConfig + SophiaConnection. Connects from anywhere on the internet, no Tailscale, no laptop in the loop.

Open caveats (known, deferred):
- Editor + Beam Pro speakers have the expected echo loop (Sophia's voice → mic → STT → loop). Glasses temple speakers + glasses mic geometry kill it for the real demo. Q41/Q43 in livekit_doubts.md predicted this and the prediction holds.
- Browser uses plain HTTP — Chrome needs the flag per-machine. Real TLS deferred to production.
- AWS env vars on EC2 expire ~1h (STS); kubectl port-forwards die when they expire. Re-export + restart pf-gpu.sh per session.

What's NEXT (post-MVP, when team approves real production):
- Move EC2 to us-west-2 (same region as EKS) to kill the cross-region ~70ms penalty.
- Real domain + Let's Encrypt TLS → solves browser mic + no per-Chrome flag needed.
- Proper SSO auth on token-mint (replace the shared API key).
- See `production_deployment.md` for the full plan.

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
| GitHub repo | `git@github.com:AIPartnersUSA/sophia-agent-research.git` |
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

6. Start the frontend (kill any old next-server process first if it's still running):
   ```bash
   cd /workspace/avinash/sophia/agent-starter-react

   # Safety: kill anything still bound to 3000 from a previous session
   sudo fuser -k 3000/tcp 2>/dev/null
   sleep 2

   nohup npm start -- --port 3000 --hostname 0.0.0.0 > /workspace/avinash/sophia/frontend.log 2>&1 &
   disown
   sleep 6
   ss -tlnp | grep :3000
   tail -10 /workspace/avinash/sophia/frontend.log
   ```
   The log should show `▲ Next.js 15.5.18 ... ✓ Ready in Xms`. The ss should show node listening on 3000.

7. Test from your laptop:
   ```bash
   # From laptop terminal:
   curl -s --max-time 5 http://3.227.63.49:8001/health      # token-mint reachable
   curl -sI --max-time 5 http://3.227.63.49:7880/            # SFU reachable
   curl -s -X POST -H "Content-Type: application/json" -d '{}' http://3.227.63.49:3000/api/token | head -c 200
   ```
   The last curl returns JSON with `participantToken` if everything's wired. If 500, the production fixes from Phase 12 NOTE aren't applied. If 401 on the token-mint curl, the SOPHIA_TOKEN_API_KEY auth is enabled and browser uses a different path (Next.js route on :3000) — only matters for glasses.

8. Open browser at http://3.227.63.49:3000 (Chrome with the flag — see "Sharing the demo" section).

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

# Frontend (Node.js process)
ss -tlnp | grep ':3000'
ps -ef | grep '[n]ode' | grep next

# AWS auth still valid? (env vars haven't expired)
aws sts get-caller-identity 2>&1 | head -3
# Should show YOUR ARN. If "ExpiredToken" → re-export AWS_ACCESS_KEY_ID etc.

# Local repo in sync with origin
git status
git log --oneline origin/main..HEAD 2>/dev/null     # any unpushed commits?
git log --oneline HEAD..origin/main 2>/dev/null     # any unpulled commits?

# Disk usage (don't fill up the shared 290GB EBS)
df -h /workspace | tail -1
docker system df
```

### Running the demo on XREAL glasses (after backend is up)

Prereq: the browser test at `http://3.227.63.49:3000` works. If not, fix the backend first — the glasses path won't work in isolation.

The APK lives at `sophia-glasses/unity/sophia-glasses.apk` (~200 MB). If you haven't touched `SophiaConfig.asset` since 2026-05-29 the existing APK already has the EC2 URL + X-API-Key + agent name baked in — no Unity rebuild needed. Skip to step 5.

If you DID change SophiaConfig.asset (e.g. rotated the SOPHIA_TOKEN_API_KEY) you must rebuild the APK first — see "Glasses repointing" section below for the Unity build sequence.

1. Plug the Beam Pro into your Mac via USB-C. Mac → Mac terminal. If you only want power, plug to a power brick — but USB to Mac is better because you get `adb logcat`.

2. On the Beam Pro screen, if "Allow USB debugging?" prompt appears, tap Allow. If not, you're already authorized from a previous session.

3. Verify Mac sees the device:
   ```bash
   adb devices
   ```
   Look for one device with status `device` (not `unauthorized`, not empty).

4. Reinstall the APK on Beam Pro (idempotent — `-r` keeps app data):
   ```bash
   adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
   ```
   ~30 seconds. Skip if the app is already installed from the last session and you're confident SophiaConfig.asset didn't change.

5. Force-stop + launch the app:
   ```bash
   adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
   adb logcat -c                              # clear old logs
   adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
   ```
   Bundle ID is the Unity template default — rename to `com.sophia.glasses` is on the Phase 2 hardening list, not done yet.

6. On Beam Pro screen, tap Allow on mic permission if prompted. Same for any other permission prompts (camera, storage). After the first time, these are remembered.

7. Plug XREAL One Pro glasses into the Beam Pro's other USB-C port.

8. The Sophia picker UI appears (two columns: Private session / Team session). Tap Private for solo testing. The voice loop starts.

9. Speak. Wait ~2-3 seconds. Sophia answers through the glasses temple speakers. You should see the colored state dot top-right of the AR HUD pulse (LISTENING → THINKING → SPEAKING) and the subtitle text appear at the bottom.

Watch logs in a separate Mac terminal while testing:
```bash
adb logcat -v time | grep -E '\[Sophia|LiveKit|Unity'
```

Expected log markers (see "Glasses repointing" section for the full sequence):
- `[Sophia] Got token (len=...)` → X-API-Key auth succeeded
- `[Sophia] Connected to room ...` → SFU connection succeeded
- `[Sophia] Track subscribed: kind=KindAudio from participant='agent-...'` → Sophia's audio is wired

Common failure modes:
- **"Token mint failed HTTP 401"** → SOPHIA_TOKEN_API_KEY mismatch between SophiaConfig.asset (`9a11fdf5...`) and EC2 `.env.production`. Rotate carefully.
- **"Connection timeout to ws://3.227.63.49:7880"** → EC2 stopped OR SG closed. From your laptop: `curl -sI --max-time 5 http://3.227.63.49:7880/` should return 200.
- **Sophia subscribes but never speaks** → port-forwards on EC2 died (STS creds expired ~1h). On EC2: `./sophia-agent/infra/pf-gpu.sh stop && ./sophia-agent/infra/pf-gpu.sh && docker compose restart agent-worker`.
- **Echo on Beam Pro alone (without glasses)** → expected per Q41/Q43 in livekit_doubts.md. Plug the glasses in; geometry kills the loop.

To end the session: tap the End chip in the bottom-right corner of the Beam Pro screen. The picker reappears for the next session.

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
git clone git@github.com:AIPartnersUSA/sophia-agent-research.git .
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

**Shortcut for fresh setups:** Three template files now live in the repo with every variable documented + commands to generate fresh values:
- `sophia-agent/.env.production.example`
- `sophia-agent/infra/livekit.prod.yaml.example`
- `agent-starter-react/.env.local.example`

Copy each `.example` to its non-example sibling, fill in values (the comments tell you which `openssl rand` to run), then `chmod 600`. The narrative below is what we did the first time and is retained for the historical record + fallback if you prefer line-by-line.

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

NOTE for fresh rebuilds: before `npm run build` works in production mode, three code fixes must be applied (covered in Problems 8, 9, 14, 16):
- `components/app/view-controller.tsx` — `as const` on VIEW_MOTION_PROPS (Framer Motion typing)
- `next.config.ts` — `eslint: { ignoreDuringBuilds: true }` (skip prettier rules in starter)
- `app/api/token/route.ts` — remove the production-only `throw` guard (or replace with proper auth)
- `app-config.ts` — hardcode `agentName: 'sophia-agent'` (env var indirection doesn't survive client bundle)

All four are committed in the repo by now, so a fresh `git clone` + `npm install` + `npm run build` should just work. If you ever rebuild from a snapshot before those fixes, refer to the problems for the exact patches.

### Phase 13 — Opened PR for SG rules

Process (mirror this for any future infra change):

```bash
# In your usual repos directory (e.g. ~/Documents/repos)
cd ~/<your-repos-dir>
git clone git@github.com:AIPartnersUSA/aws-infra.git
cd aws-infra
git fetch origin
git checkout fix-state
git pull origin fix-state
git checkout -b feat/sophia-sg-opens
nano environments/single_g5x2large_us_east_1/main.tf
# (paste the 5 ingress blocks shown below inside aws_security_group.gpu)
git diff environments/single_g5x2large_us_east_1/main.tf   # verify only +ingress blocks
git add environments/single_g5x2large_us_east_1/main.tf
git commit -m "Add SG ingress rules for Sophia voice agent MVP"
git push -u origin feat/sophia-sg-opens
# (if push errors with 'write access denied' → ask infra to add you as Collaborator with Write on the repo)
gh pr create --base fix-state \
  --title "Add SG inbound rules for Sophia voice agent MVP" \
  --body "Five new ingress rules following the var.allowed_cidrs pattern used by JupyterLab."
```

The 5 ingress blocks added inside `resource "aws_security_group" "gpu"` (right after the existing TensorBoard / generic-ML ingress blocks):

```hcl
  ingress {
    description = "Sophia voice agent frontend"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "LiveKit SFU WebSocket signaling"
    from_port   = 7880
    to_port     = 7880
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "LiveKit TURN/TCP fallback"
    from_port   = 7881
    to_port     = 7881
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "Sophia voice agent token-mint"
    from_port   = 8001
    to_port     = 8001
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "LiveKit WebRTC media (UDP)"
    from_port   = 50000
    to_port     = 60000
    protocol    = "udp"
    cidr_blocks = var.allowed_cidrs
  }
```

`var.allowed_cidrs` defaults to `["0.0.0.0/0"]` per the existing variables.tf, so these rules are open to the internet — same as JupyterLab and TensorBoard.

Reminder when pinging infra: ask them to BOTH merge the PR AND run `terraform apply`. Merge alone doesn't open the AWS ports; the apply is what makes the SG change live.

PR was merged + applied by Aziz on 2026-05-29.

### Phase 14 — Glasses (DONE 2026-05-29)

Procedure now documented in the dedicated "Glasses repointing" section further down — see that section for the exact three-field edit (liveKitUrl + tokenEndpoint + tokenApiKey), the build/install commands, the expected log lines, and the echo-loop caveat. Brief summary: glasses connect to ws://3.227.63.49:7880, fetch token from http://3.227.63.49:8001/token, send X-API-Key header matching SOPHIA_TOKEN_API_KEY on the EC2.

---

## Git workflow + sync between Mac and EC2

Adopted pattern: edit on Mac → commit + push to GitHub → `git pull` on EC2. Do NOT edit the same file in both places independently — that creates conflicts (Problem 12).

**If both sides DO get out of sync** (e.g. you edited code directly on EC2 during a demo and now Mac + EC2 + GitHub all disagree): read `git_sync.md` at the project root. It has the full 8-step reconciliation procedure (triage unexpected dirty files, handle secrets in untracked files like `livekit.prod.yaml`, decide what to commit vs gitignore, push from EC2, pull on Mac, push from Mac, pull on EC2, verify). Don't try to reconcile by ad-hoc copying — the procedure handles the secret-file edge cases that bite you otherwise.

### Files in git (versioned across Mac + EC2)

- All source code under `sophia-agent/`, `agent-starter-react/`, `sophia-glasses/`
- All `*.md` documentation at project root
- `sophia-agent/Dockerfile` and `sophia-agent/Dockerfile.token-mint`
- `.gitignore`, `.gitattributes`

### Files NOT in git (local to each environment)

These live ONLY on the EC2 in `/workspace/avinash/sophia/`. They contain secrets or environment-specific values; they're chmod 600 and untracked.

- `sophia-agent/.env.production` (LiveKit keys, token-mint API key, inference URLs)
- `sophia-agent/infra/livekit.prod.yaml` (LiveKit prod config with keys inlined)
- `docker-compose.yml` at workspace root (deployment-specific service composition)
- `agent-starter-react/.env.local` (frontend env with keys for browser-side use)

If the EC2 is rebuilt from scratch, recreate these from the templates in Phases 6 + 7 above. Keep the generated key/secret values somewhere safe outside the repo (1Password, AWS Secrets Manager, etc.).

### Reference files in git (for context, not code we own)

- `user_data.sh.tftpl` was a sample we pasted from infra. Decided to gitignore it (added to `.gitignore`) since it's not our code and would go stale if infra updates their version. View their canonical copy at https://github.com/AIPartnersUSA/aws-infra/blob/fix-state/environments/single_g5x2large_us_east_1/user_data.sh.tftpl

### Daily flow

When editing on Mac:

```bash
cd "/Users/avinashbolleddula/Documents/sophia Agent Research"
# make edits
git status                          # see what changed
git diff                            # review diffs
git add <files>
git commit -m "..."
git push
```

Then on the EC2:

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia
git pull
# if any service depends on the changed file, restart it:
docker compose build agent-worker && docker compose up -d agent-worker
# or
cd agent-starter-react && npm run build
```

### Two-commit pattern (we used this for the deploy cleanup)

When a session produces both code fixes AND documentation, split them so the code-change diff is reviewable on its own:

```bash
# Commit 1: code-level changes (production behavior)
git add <code files>
git commit -m "MVP deployment fixes: <description>"

# Commit 2: documentation
git add <docs>
git commit -m "Document MVP EC2 deployment: <description>"

git push
```

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

### Problem 12 — `git pull` on EC2 conflicts with local uncommitted edits

Symptom: After pushing code changes from Mac to GitHub, running `git pull` on the EC2 errors with:

```
error: Your local changes to the following files would be overwritten by merge:
        agent-starter-react/next.config.ts
        sophia-agent/Dockerfile
Please commit your changes or stash them before you merge.
Aborting
```

Cause: We edited the same files via `nano` directly on the EC2 earlier (for the ESLint disable in next.config.ts and the HF_HOME fix in Dockerfile) and never committed those edits. When the Mac-committed versions arrived via `git pull`, git refused to overwrite the dirty EC2 working tree.

Fix: discard the EC2's local versions (since they're functionally identical to what's incoming from main) and pull:

```bash
git checkout -- agent-starter-react/next.config.ts sophia-agent/Dockerfile
git pull
```

`git checkout --` reverts those files to HEAD; `git pull` then fast-forwards to the canonical version from origin.

Prevention: always edit ONLY on the Mac going forward, push to GitHub, pull on EC2. The "edit in both places" pattern is what caused this. Captured as a workflow rule in the Git workflow section above.

### Problem 13 — GitHub push rejected with "write access not granted"

Symptom: `git push -u origin feat/sophia-sg-opens` against `AIPartnersUSA/aws-infra` returns `Permission to AIPartnersUSA/aws-infra.git denied`.

Cause: Your GitHub user wasn't a Collaborator with Write role on the repo. By default, even repo Read-only users can clone but not push.

Fix: ask infra to add you (GitHub username `AvinashSophia`) as a Collaborator with Write access. Once granted, the existing local branch + commits push successfully on retry. No need to redo any work.

Pattern note: branch-level permission isn't a separate thing on GitHub. Write access is granted at the repo level, and branch protection rules (separate concept) restrict which branches can be pushed to directly. Our workflow uses PRs against `fix-state`, so branch protection on `fix-state` doesn't affect us — we just need repo-level Write to push our feature branch.

### Problem 14 — `/api/token` returns 500 in production build

Symptom: browser loads the frontend at http://3.227.63.49:3000, clicks Start Call, immediately sees 500 from `/api/token`. frontend.log shows:

```
Error: THIS API ROUTE IS INSECURE. DO NOT USE THIS ROUTE IN PRODUCTION WITHOUT AN AUTHENTICATION LAYER.
    at .next/server/app/api/token/route.js:1:91707
```

Cause: the starter template's `app/api/token/route.ts` has a hardcoded guard at the top of the POST handler:

```ts
if (process.env.NODE_ENV !== 'development') {
  throw new Error('THIS API ROUTE IS INSECURE. ...');
}
```

This deliberately blocks the dev-only route from working in production builds (`npm start` sets NODE_ENV=production). The starter expects you to swap in a real auth layer for production.

Fix: for MVP, remove the guard. Edit `agent-starter-react/app/api/token/route.ts`, comment out the `throw` block. The route still mints unauthenticated tokens — acceptable for the MVP demo posture (EC2 stopped between demos, URL not broadly shared). Then `npm run build` + restart.

Long-term: add API-key auth to the Next.js route (mirror the SOPHIA_TOKEN_API_KEY pattern from token-mint) OR switch the frontend to use the external token-mint on port 8001 directly. Either way is a proper production fix.

### Problem 15 — Safari + Chrome refuse `getUserMedia` over plain HTTP from public IP

Symptom: clicking Start Call in the browser shows console error `Unhandled Promise Rejection: TypeError: undefined is not an object (evaluating 'navigator.mediaDevices.getUserMedia')` and an explicit `Accessing media devices is available only in secure contexts (HTTPS and localhost)`.

Cause: browser security boundary. `navigator.mediaDevices` is not exposed to non-secure contexts (anything that's not HTTPS or localhost). Our public-IP HTTP page is non-secure → the API doesn't exist at all in the page's JavaScript.

Fix for Chrome only (Safari has no equivalent): open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, set to Enabled, paste `http://3.227.63.49:3000` into the text box, relaunch Chrome. After relaunch, the page is treated as secure for that one origin — `navigator.mediaDevices.getUserMedia` works, mic permission can be granted.

Limitation: the flag is per-Chrome-profile. Every viewer of the demo needs to do this once. Safari users have to switch to Chrome (or use the proper production fix).

Long-term: add TLS via a real domain. Eliminates the issue for everyone, every browser.

### Problem 16 — Agent never joins the room ("session ended, agent did not join")

Symptom: browser successfully joins SFU room, but no agent participant ever appears. After ~30s, frontend shows "session ended". agent-worker logs show NO job request received.

Cause: the JWT minted by the Next.js `/api/token` route had `roomConfig.agents: []`. The SFU has no instruction to dispatch our worker. Decode the JWT at jwt.io to verify.

The root cause traces to `agent-starter-react/app-config.ts`:

```ts
agentName: process.env.AGENT_NAME ?? undefined,
```

`AGENT_NAME` doesn't have the `NEXT_PUBLIC_` prefix. Next.js production builds strip all non-`NEXT_PUBLIC_*` env vars from CLIENT-SIDE code at build time. `app-config.ts` is imported by client components → `process.env.AGENT_NAME` becomes `undefined` in the browser bundle. The frontend passes `undefined` to the agent dispatch hook, the SFU gets a token without `agents`.

Fix: hardcode the value in `app-config.ts`:

```ts
agentName: 'sophia-agent',
```

Then `rm -rf .next && npm run build` and restart. The JWT now includes `roomConfig.agents: [{"agentName": "sophia-agent"}]`. SFU dispatches the worker; voice loop runs.

Rationale: the env-var indirection makes sense for LiveKit Cloud where agent names vary per deployment. For our self-hosted setup, the agent name is hardcoded in `agent.py` as `sophia-agent`. No reason to indirect through env vars — hardcoding removes a class of build-time vs runtime bugs.

### Problem 17 — Glasses get 401 from token-mint after server-side auth turned on

Symptom: Beam Pro launches the app, fetches token from `http://3.227.63.49:8001/token`, gets HTTP 401 with body `Missing or invalid X-API-Key header`. App shows "Token mint failed" and refuses to connect.

Cause: we set `SOPHIA_TOKEN_API_KEY` in `.env.production` (turning on the auth check in token_mint.py). Browser uses the Next.js `/api/token` route on port 3000 which bypasses token-mint entirely, so browser unaffected. Glasses POST directly to token-mint on port 8001, where the auth is now enforced. The glasses code didn't know about the header.

Fix: added X-API-Key support to the glasses (matches the opt-in env pattern on token-mint).

`SophiaConfig.cs` — added a serialized field:

```csharp
[Tooltip("Optional shared API key for the token-mint endpoint. " +
         "When set, the X-API-Key header is sent on every /token POST. " +
         "Must match SOPHIA_TOKEN_API_KEY in sophia-agent/.env.production. " +
         "Leave EMPTY to skip auth.")]
public string tokenApiKey = "";
```

`SophiaConnection.cs` — in the token fetch UnityWebRequest, add the header when the field is non-empty:

```csharp
www.SetRequestHeader("Content-Type", "application/json");
if (!string.IsNullOrEmpty(config.tokenApiKey))
{
    www.SetRequestHeader("X-API-Key", config.tokenApiKey);
}
```

Then in Unity Inspector, open `Assets/Settings/SophiaConfig.asset` and paste the SOPHIA_TOKEN_API_KEY value from the EC2's `.env.production` into the new tokenApiKey field. Save, rebuild APK, install, test.

Both sides must use the exact same key value. Verify with:

```bash
ssh sophia-gpu "grep SOPHIA_TOKEN_API_KEY /workspace/avinash/sophia/sophia-agent/.env.production"
grep tokenApiKey "/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/Assets/Settings/SophiaConfig.asset"
```

Outputs should have matching values.

### Problem 18 — `docker compose restart` doesn't reload env_file

Symptom: edited `.env.production` to add SOPHIA_TOKEN_API_KEY, ran `docker compose restart token-mint`, but token-mint behaved as if the env var was still missing. curl with the correct key still returned 401.

Diagnostic: `docker compose exec token-mint env | grep SOPHIA_TOKEN_API_KEY` showed the old (unset) value, not the new one we'd added.

Cause: `docker compose restart` performs a process restart but reuses the SAME container with its EXISTING environment. The `env_file:` directive in docker-compose.yml is evaluated when the container is CREATED (`docker compose up`), not when it's restarted. Updates to the env file don't propagate via restart.

Fix: full down + up to recreate the container with the latest env:

```bash
docker compose down
docker compose up -d livekit-server token-mint agent-worker
sleep 5
docker compose exec token-mint env | grep SOPHIA_TOKEN_API_KEY  # should now show the new value
```

Pattern note: any change to a file referenced by `env_file:` requires `down + up`, not just `restart`. Same for changes to bind-mounted files that the service reads at startup. `restart` is only safe when the change is in already-running container state.

### Problem 19 — Duplicate `SOPHIA_TOKEN_API_KEY` lines in .env.production

Symptom: after using `echo "SOPHIA_TOKEN_API_KEY=$VAL" >> sophia-agent/.env.production` more than once (e.g. trying to rotate the key), the file has multiple `SOPHIA_TOKEN_API_KEY=...` lines. Behavior depends on which line the dotenv parser uses (usually the last one), but it's confusing and fragile.

Cause: the `>>` operator APPENDS to a file, doesn't replace. Easy mistake when iterating on env values.

Fix: delete duplicates and keep one:

```bash
# Pattern that replaces (delete then append) instead of just appending:
sed -i '/^SOPHIA_TOKEN_API_KEY=/d' sophia-agent/.env.production
echo "SOPHIA_TOKEN_API_KEY=$VAL" >> sophia-agent/.env.production

# Verify exactly one line per var:
grep -c SOPHIA_TOKEN_API_KEY sophia-agent/.env.production  # should print: 1
sort sophia-agent/.env.production | uniq -d                # any dupes show here
```

After cleaning, do the `docker compose down + up` from Problem 18 to actually load the deduped file.

---

## Glasses repointing (DONE 2026-05-29)

Walked through this on 2026-05-29 successfully. Documented for repeatability.

In Unity Editor on your Mac:
1. Open `sophia-glasses/unity/`.
2. Open `Assets/Settings/SophiaConfig.asset` in the Inspector.
3. Edit THREE fields (note: third one was added 2026-05-29 — see Problem 17):
   - `liveKitUrl`: change to `ws://3.227.63.49:7880`
   - `tokenEndpoint`: change to `http://3.227.63.49:8001/token`
   - `tokenApiKey`: paste the same value as `SOPHIA_TOKEN_API_KEY` in EC2's `.env.production`. Empty if token-mint auth is off.
4. Save (Cmd+S).
5. File menu → Build Profiles → Build (outputs APK to `sophia-glasses/unity/sophia-glasses.apk`).
6. Click Yes on the "not a member of project" Unity warning — about Unity Cloud services, harmless for our build.

Install on Beam Pro:

```bash
adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
adb logcat | grep -E 'Sophia|LiveKit'
```

Tap Allow on mic permission. Pick Private Session. Plug in XREAL One Pro. Speak. Sophia answers via the glasses temple speakers. No Tailscale needed, no laptop in the critical path. The whole demo runs through 3.227.63.49 (public EC2 IP) over plain internet.

Expected logs on first successful run:

```
[Sophia] Starting. room='sophia-glasses-...' identity='glasses-...' server='ws://3.227.63.49:7880'
[Sophia] Got token (len=457) for url=ws://3.227.63.49:7880
[Sophia] Connected to room ...
[Sophia] Microphone publishing. You can speak now.
[Sophia] Participant connected: agent-...
[Sophia] Track subscribed: kind=KindAudio from participant='agent-...'
```

Echo loop on Beam Pro speakers alone (not glasses):
- If you test without plugging in the glasses, the Beam Pro speaker + Beam Pro mic will create an echo loop (Sophia hears her own TTS).
- This is expected per Q41/Q43 in livekit_doubts.md. We deliberately did NOT add mic gating in code because the glasses geometry (temple speakers + temple mics, opposite sides of the head) is what kills the loop.
- For demo recording on Beam Pro alone, use headphones plugged into the phone.
- With glasses plugged in, the loop disappears naturally.

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

## Sharing the demo with the team (browser)

For someone else to use the demo from THEIR machine:

1. Send them `http://3.227.63.49:3000`.
2. Tell them to use Chrome (Safari and Firefox will block mic over HTTP, no clean workaround).
3. Tell them to set up the secure-origin flag ONCE (per Chrome profile):
   - Open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
   - Set to Enabled
   - Paste `http://3.227.63.49:3000` in the text box
   - Click Relaunch (bottom right)
4. After Chrome relaunches, open the URL, click Start Call, grant mic permission, talk.

Once the flag is set per profile, future demo visits "just work" without resetting. If they have multiple Chrome profiles, each one needs the flag set.

Token-mint auth note: the FRONTEND (port 3000) uses the Next.js built-in `/api/token` route, which mints LiveKit JWTs WITHOUT requiring the X-API-Key header. Only the standalone `token-mint` service (port 8001) requires the header — and only the glasses use that endpoint directly. So browser users don't need to know about API keys at all; just URL + Chrome flag.

## Sharing the demo with the team (glasses)

This is harder because each Beam Pro needs the APK installed and SophiaConfig.asset baked with the right key value at build time. Options:

1. Pre-build a single APK with everything baked in. Distribute via GitHub Releases or similar. Each viewer installs via `adb install`. Works as long as the SOPHIA_TOKEN_API_KEY on the EC2 matches what was baked in.
2. Give them your Mac and let them watch you build + install. Cumbersome but precise.

For Aziz / infra-team viewers who just want to see the demo, browser is the easier path. Glasses are for the technical deep-dive viewers who specifically want to see the XREAL experience.

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
