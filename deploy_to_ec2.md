# deploy_to_ec2.md

Complete runbook of the EC2 deployment for the Sophia voice agent MVP. Captures every step we executed in the 2026-05-26 session, every gotcha hit, the current state, and what's pending. Use this file to resume mid-stream OR to replay from scratch on a fresh machine.

Companion docs:
- `mvp_deployment_shared_ec2.md` — original plan + design rationale + architecture diagram.
- `production_deployment.md` — full production setup (separate, more complete, with TLS + domain + Secrets Manager). The MVP we're running here is a subset.
- `git_setup.md` — git remote + LFS setup (already done, prerequisite for this).

---

## Target architecture (MVP, no TLS)

Single EC2 instance hosts SFU + token-mint + agent worker. Frontend runs on the same EC2 or on the user's laptop. Browser and Beam Pro both connect to the public IP over plain HTTP/WS.

```
+----------+              public Internet               +--------------------------+
| browser  | -- HTTP --> :3000 (Next.js frontend) ----> | EC2: 3.227.63.49         |
|          | -- HTTP --> :8001 (token-mint)             | (shared GPU box)         |
|          | -- WS   --> :7880 (LiveKit signal)         |  /workspace/avinash/     |
|          | -- UDP  --> :50000-60000 (WebRTC media)    |  sophia/                 |
+----------+                                            |                          |
                                                        |  docker compose:         |
+----------+                                            |   livekit-server         |
| glasses  | -- WS   --> :7880 (signal)                 |   token-mint             |
| (Beam Pro| -- HTTP --> :8001 (/token)                 |   agent-worker (later)   |
|  +XREAL) | -- UDP  --> :50000-60000 (media)           |                          |
+----------+                                            +------------+-------------+
                                                                     |
                                                          same VPC (assumed)
                                                                     |
                                                        +------------v-------------+
                                                        | EKS (already running)    |
                                                        |  whisper / qwen3 /       |
                                                        |  kokoro / spatial-ai     |
                                                        +--------------------------+
```

---

## Current status (end of 2026-05-26 session)

DONE:
- Three pre-deploy code changes (auth on token-mint, env-driven inference URLs in agent.py, separate Dockerfile.token-mint).
- SSH access from laptop to EC2 (`ssh sophia-gpu`).
- EC2 environment surveyed; uv + Node 22 + Git LFS installed.
- SSH key generated on EC2 + added to GitHub.
- Repo cloned at `/workspace/avinash/sophia/` with all LFS objects pulled.
- Secrets generated (LiveKit key/secret + token-mint API key).
- `sophia-agent/.env.production` written (chmod 600).
- `sophia-agent/infra/livekit.prod.yaml` written (chmod 600).
- `docker-compose.yml` at workspace root written.
- token-mint Docker image built.
- livekit-server + token-mint started via docker compose.
- Verified locally on EC2: both services respond to curl on 127.0.0.1.

DONE 2026-05-26 (added):
- Discovered EKS cluster (`spatial-ai-staging`) is in us-west-2 while EC2 is in us-east-1. Cross-region setup.
- Confirmed via nslookup that cluster.local DNS doesn't resolve from EC2 (SERVFAIL). Switched to Option C plan: kubectl port-forward.
- Installed kubectl on EC2.
- Confirmed EC2 has AWS auth via IAM Instance Profile (`sophiaspatialai-ai-gpu-ec2`, account matches EKS account).
- Identified the role lacks `eks:DescribeCluster` so `aws eks update-kubeconfig` doesn't work — workaround via copying kubeconfig from Mac.

PENDING (in order):
- Copy kubeconfig from Mac to EC2 (`scp ~/.kube/config sophia-gpu:.kube/config`).
- Run `kubectl get nodes` on EC2. If Unauthorized, ask infra to add the IAM role to aws-auth ConfigMap.
- Once kubectl works, run `pf-gpu.sh` on EC2, verify port-forwards, then `docker compose up -d agent-worker`.
- Security group rules opened by infra (or user via AWS Console). Required before anyone external can reach the EC2 on our ports.
- Set up the frontend (either on EC2 or pointed at EC2 from laptop / Vercel).
- End-to-end test: browser opens http://3.227.63.49:3000, clicks Start Call, talks to Sophia.
- Glasses repointed at EC2 IP (Unity SophiaConfig.asset edits + rebuild APK).

---

## Phase 0 — Pre-deploy code changes (DONE)

Three changes made in `sophia-agent/` before deployment to make the code production-ready. Already committed and pushed.

### 0.1 API-key auth on token-mint

File: `sophia-agent/src/token_mint.py`

Added:
- `SOPHIA_TOKEN_API_KEY` env var. When set, /token requires `X-API-Key` header to match. When unset, no auth (dev-friendly).
- `SOPHIA_CORS_ORIGINS` env var (comma-separated). Replaces hardcoded `["*"]` so prod can narrow to specific origins.
- Helper `_require_api_key()` raises HTTPException 401 if the header is missing/wrong.
- `mint_token` endpoint now takes `x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")` and calls the helper first.

### 0.2 Env-driven inference URLs in agent.py

File: `sophia-agent/src/agent.py`

Replaced hardcoded `http://localhost:8080`, `http://localhost:18080`, `http://localhost:8122`, `http://localhost:8106` with env-var-driven module constants. Added `import os` at top.

```python
SOPHIA_RAG_URL = os.environ.get("SOPHIA_RAG_URL", "http://localhost:8106")
WHISPER_URL = os.environ.get("WHISPER_URL", "http://localhost:8080")
QWEN3_URL = os.environ.get("QWEN3_URL", "http://localhost:18080")
KOKORO_URL = os.environ.get("KOKORO_URL", "http://localhost:8122")
```

Then changed the three openai plugin instantiations to use `f"{WHISPER_URL}/v1"`, `f"{QWEN3_URL}/v1"`, `f"{KOKORO_URL}/v1"`.

Defaults match the kubectl-port-forward local URLs so dev still works without env vars.

### 0.3 Dockerfile.token-mint

File (new): `sophia-agent/Dockerfile.token-mint`

Slimmer image than the existing `Dockerfile`. Skips the `download-files` step (token-mint doesn't load Silero or turn-detector models). Uses `uv sync --locked --no-dev` for a leaner install. CMD runs `uvicorn src.token_mint:app --host 0.0.0.0 --port 8001`.

Existing `Dockerfile` stays unchanged (it builds the full agent worker image).

---

## Phase 1 — SSH access from laptop (DONE)

Infra team provisioned a shared GPU EC2:
- Public IP: 3.227.63.49
- Instance ID: i-0748ed7c188c337cc
- Type: g5.2xlarge (NVIDIA A10G, 24 GB GPU, 32 GB RAM, 8 vCPU)
- Region: us-east-1, AZ us-east-1a
- VPC: vpc-0eeab16713f4f744d
- Private IP: 10.20.1.90
- OS: Ubuntu 22.04.5 LTS (Deep Learning AMI)
- User: ubuntu
- SSH key file: sophiaspatialai-ai-us-east-1.pem (provided by infra)
- Workspace: `/workspace` (300 GB persistent EBS)
- Shared with: Ivana

### 1.1 Move the .pem to ~/.ssh/

macOS Privacy & Security blocks Terminal from reading ~/Downloads by default. Two workarounds.

Either grant Terminal Full Disk Access permanently:
1. Apple menu → System Settings → Privacy & Security → Full Disk Access → click + → /Applications/Utilities/Terminal.app → Open → toggle ON
2. Cmd+Q to quit Terminal fully, then reopen.

Or use Finder to move the file once (no permission change needed): Cmd+Shift+G in Finder → `~/.ssh/` → drag-drop the .pem file from Downloads.

### 1.2 Lock down the key permissions

SSH refuses to use a key file with permissive permissions.

```bash
chmod 600 ~/.ssh/sophiaspatialai-ai-us-east-1.pem
ls -la ~/.ssh/sophiaspatialai-ai-us-east-1.pem
# Should show -rw-------
```

### 1.3 ~/.ssh/config alias

```bash
cat > ~/.ssh/config <<'EOF'
Host sophia-gpu
    HostName 3.227.63.49
    User ubuntu
    IdentityFile ~/.ssh/sophiaspatialai-ai-us-east-1.pem
    ServerAliveInterval 60
EOF
chmod 600 ~/.ssh/config
```

After this, the alias `ssh sophia-gpu` works without arguments.

### 1.4 First connection

```bash
ssh sophia-gpu
```

First time prompts to accept the host key fingerprint (`SHA256:XjuL5rIgdlQ1GOB1horyQoNntBxVlhK1+U3uANtaJEU` for this box). Type `yes` to add to known_hosts. Future connections are silent.

The welcome banner confirms this is a Deep Learning AMI with NVIDIA driver 580.x, CUDA 12.9, and an auto-activated conda env named `ai`.

---

## Phase 2 — Environment survey on EC2 (DONE)

Ran this once on the EC2 to know what's installed and what's running before changing anything:

```bash
echo "=== OS ==="
lsb_release -a 2>/dev/null

echo "=== Docker ==="
docker --version
docker compose version

echo "=== Git + uv + node ==="
git --version
which uv 2>&1 || echo "MISSING: uv"
node --version 2>&1 || echo "MISSING: node"

echo "=== Listening ports ==="
sudo ss -tlnp 2>&1 | head -20

echo "=== AWS metadata ==="
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/availability-zone
echo
MAC=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/network/interfaces/macs/ | head -1)
echo "VPC: $(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/network/interfaces/macs/${MAC}vpc-id)"

echo "=== Workspace ==="
ls /workspace/
df -h /workspace | tail -1
```

Results we got:
- Docker 29.4.2 + Compose v5.1.3 already present, no install needed.
- Git 2.34 present.
- uv MISSING.
- node MISSING.
- 290 GB disk, 194 GB free.
- VPC: `vpc-0eeab16713f4f744d`.
- Ports already listening (Ivana): 22 (sshd), 8888 (jupyter-lab), 8501 + 8502 (Streamlit), 8200 (vllm), high random ports on 10.20.1.90 (vllm engine), 127.0.0.1:5555 (nv-hostengine), 127.0.0.1:20241 (cloudflared).
- Our planned ports (3000, 7880, 7881, 8001) all FREE.

Also got the Security Group name (using a metadata path that doesn't have the MAC-newline issue):

```bash
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
echo "Security groups: $(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/security-groups)"
```

Result: `sophiaspatialai-gpu-20260511165512897100000004`

---

## Phase 3 — Install missing tools on EC2 (DONE)

### 3.1 Create our workspace

```bash
mkdir -p /workspace/avinash/sophia
cd /workspace/avinash/sophia
```

By convention: each person uses `/workspace/<their-name>/` to avoid collisions with Ivana.

### 3.2 Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
uv --version
```

### 3.3 Install Node 22.x

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version
npm --version
```

NOTE on Ubuntu 22.04: apt-installing packages triggers the `needrestart` whiptail prompt asking which services to restart. Press Tab to highlight OK, then Enter to accept defaults. To suppress this for the rest of the session:

```bash
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
```

### 3.4 Install Git LFS

```bash
sudo apt-get install -y git-lfs
git lfs install
git lfs --version
```

### 3.5 Verify our ports are still free

```bash
for p in 3000 7880 7881 8001; do
  if sudo ss -tlnp | grep -q ":$p "; then
    echo "PORT $p IS TAKEN"
  else
    echo "PORT $p OK"
  fi
done
```

All four reported OK.

---

## Phase 4 — Generate SSH key on EC2 + add to GitHub (DONE)

To pull/push from the EC2 without typing PATs every time.

On the EC2:

```bash
ssh-keygen -t ed25519 -C "sophia-gpu-ec2"
# Accept default path, skip passphrase (or set one — your call).
cat ~/.ssh/id_ed25519.pub
```

Copy the output (one line starting with `ssh-ed25519 AAAA...` ending with `sophia-gpu-ec2`).

In browser:
1. github.com → avatar → Settings → SSH and GPG keys → New SSH key.
2. Title: "sophia-gpu EC2".
3. Paste key. Save.

---

## Phase 5 — Clone repo + pull LFS (DONE)

On the EC2:

```bash
cd /workspace/avinash/sophia
git clone git@github.com:AIPartnersUSA/sophia-agent-research.git .
# Trailing dot clones INTO current dir, not into a sophia-agent-research subdir.
# First time you may get "The authenticity of host 'github.com' can't be established" — type yes.

git lfs pull
```

LFS pull downloads ~150 MB of binaries (XREAL SDK AARs + LiveKit FFI .so/.dylib/.dll/.bundle files). Takes 1-2 minutes.

Verify the binaries are real, not pointer files:

```bash
ls sophia-glasses/xreal-sdk/Runtime/Plugins/Android/ | head
ls sophia-glasses/client-sdk-unity/Runtime/Plugins/ | head
```

Should show .aar / .dll / .so files alongside their .meta sidecars. If file contents look like `version https://git-lfs.github.com/...` then LFS didn't pull — rerun `git lfs pull`.

---

## Phase 6 — Generate production secrets (DONE)

On the EC2:

```bash
cd /workspace/avinash/sophia
LIVEKIT_KEY=$(openssl rand -hex 16)
LIVEKIT_SECRET=$(openssl rand -hex 32)
TOKEN_API_KEY=$(openssl rand -hex 16)
echo "LIVEKIT_KEY=$LIVEKIT_KEY"
echo "LIVEKIT_SECRET=$LIVEKIT_SECRET"
echo "TOKEN_API_KEY=$TOKEN_API_KEY"
```

Recorded the three values to a private note (also needed on laptop later for frontend env).

---

## Phase 7 — Configuration files (DONE)

### 7.1 sophia-agent/.env.production

Built line-by-line because heredocs were getting mangled by terminal paste indentation:

```bash
{
  echo "LIVEKIT_URL=ws://3.227.63.49:7880"
  echo "LIVEKIT_API_KEY=$LIVEKIT_KEY"
  echo "LIVEKIT_API_SECRET=$LIVEKIT_SECRET"
  echo "SOPHIA_TOKEN_API_KEY=$TOKEN_API_KEY"
  echo "SOPHIA_CORS_ORIGINS=*"
  echo ""
  echo "WHISPER_URL=http://whisper-inference.multi-agent.svc.cluster.local:8080"
  echo "QWEN3_URL=http://qwen3-inference.multi-agent.svc.cluster.local:8080"
  echo "KOKORO_URL=http://kokoro-tts.multi-agent.svc.cluster.local:8122"
  echo "SOPHIA_RAG_URL=http://sophia-spatial-ai.multi-agent.svc.cluster.local:8106"
} > sophia-agent/.env.production
chmod 600 sophia-agent/.env.production
cat sophia-agent/.env.production
```

The inference URLs are PLACEHOLDERS. They assume the EC2 is in the same VPC as the EKS cluster. To be confirmed by infra. Will update once infra responds with either "yes same VPC use cluster.local" or "no, use these NLB hostnames".

### 7.2 Source the env into the shell

So that subsequent commands can interpolate `$LIVEKIT_API_KEY` etc.:

```bash
set -a
source sophia-agent/.env.production
set +a
echo "key=$LIVEKIT_API_KEY"
echo "secret length=${#LIVEKIT_API_SECRET}"
```

Should echo the actual values; secret length should be 64.

### 7.3 sophia-agent/infra/livekit.prod.yaml

Separate from the dev `livekit.yaml` so dev config isn't disturbed. Built line-by-line for the same reason as .env.production:

```bash
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
cat sophia-agent/infra/livekit.prod.yaml
```

Notes:
- UDP range is 50000-60000 (10x the dev range) so we can serve real concurrent traffic.
- `use_external_ip: false` is intentional. We pass `--node-ip 3.227.63.49` on the CLI in docker-compose; that overrides any STUN discovery.
- Keys are inlined directly. File is chmod 600 so only `ubuntu` user can read.

### 7.4 docker-compose.yml at workspace root

```bash
{
  echo "services:"
  echo "  livekit-server:"
  echo "    image: livekit/livekit-server:latest"
  echo "    network_mode: host"
  echo "    volumes:"
  echo "      - ./sophia-agent/infra/livekit.prod.yaml:/etc/livekit.yaml:ro"
  echo "    command: --config /etc/livekit.yaml --node-ip 3.227.63.49"
  echo "    restart: unless-stopped"
  echo ""
  echo "  token-mint:"
  echo "    build:"
  echo "      context: ./sophia-agent"
  echo "      dockerfile: Dockerfile.token-mint"
  echo "    ports:"
  echo "      - \"8001:8001\""
  echo "    env_file:"
  echo "      - ./sophia-agent/.env.production"
  echo "    restart: unless-stopped"
} > docker-compose.yml
cat docker-compose.yml
```

Notes:
- `network_mode: host` for livekit-server because it needs raw UDP port access for WebRTC (port mapping doesn't work cleanly for the 50000-60000 range under Docker bridge).
- token-mint uses port mapping (`8001:8001`) which is fine — it's just HTTP.
- agent-worker is intentionally OMITTED for now. Will add after infra confirms inference URLs.

---

## Phase 8 — Build + start (DONE)

### 8.1 Build the token-mint image

```bash
docker compose build token-mint
```

First build downloads the uv Python base image (~200 MB) + installs Python deps. Takes 2-3 minutes. livekit-server image is `pull`-ed automatically when we `up`, no build needed.

### 8.2 Bring up the two services

```bash
docker compose up -d livekit-server token-mint
docker compose ps
```

Both should show `Up` status.

### 8.3 Check logs

```bash
docker compose logs --tail 30 livekit-server
docker compose logs --tail 30 token-mint
```

LiveKit logs look like:
```
starting LiveKit server, version: 1.x.x ...
nodeIP: 3.227.63.49
listening for incoming connections at addr=:7880
```

Token-mint logs look like:
```
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

### 8.4 Local smoke test on EC2

```bash
curl -s http://127.0.0.1:8001/health
echo
curl -sI http://127.0.0.1:7880/ | head -1
```

Health returns `{"status":"ok","livekit_url":"ws://3.227.63.49:7880"}`. SFU returns `HTTP/1.1 200 OK`.

This confirms the services run correctly internally. External access depends on the SG (Phase 9).

---

## Phase 9 — Open the security group (PENDING)

Required before anything external can reach the EC2 on our ports. Until done, curl from your laptop times out.

### What to add to SG `sophiaspatialai-gpu-20260511165512897100000004`

| Port | Protocol | Source | Why |
|---|---|---|---|
| 3000 | TCP | 0.0.0.0/0 | Sophia frontend (Next.js) |
| 7880 | TCP | 0.0.0.0/0 | LiveKit SFU signaling (WS) |
| 7881 | TCP | 0.0.0.0/0 | TURN/TCP fallback |
| 8001 | TCP | 0.0.0.0/0 | Token-mint |
| 50000-60000 | UDP | 0.0.0.0/0 | WebRTC media |

If user has AWS console access:
1. EC2 console → Security Groups
2. Find `sophiaspatialai-gpu-20260511165512897100000004`
3. Inbound rules tab → Edit inbound rules
4. Add the five rules above. Save.

If not, message to infra:

> Hi infra, can you add these inbound rules to the security group `sophiaspatialai-gpu-20260511165512897100000004` (EC2 instance `i-0748ed7c188c337cc`)?
>
> - TCP 3000 from 0.0.0.0/0 (sophia voice agent frontend)
> - TCP 7880 from 0.0.0.0/0 (LiveKit SFU signaling)
> - TCP 7881 from 0.0.0.0/0 (LiveKit TURN/TCP fallback)
> - TCP 8001 from 0.0.0.0/0 (sophia voice agent token-mint)
> - UDP 50000-60000 from 0.0.0.0/0 (WebRTC media)
>
> Also: is this EC2 (VPC vpc-0eeab16713f4f744d) in the same VPC as the EKS cluster running Whisper/Qwen3/Kokoro/sophia-spatial-ai? Need to know if I can hit those services via their k8s service DNS directly. If not, can you set up VPC peering OR expose them via internal NLBs with stable DNS names?

---

## Phase 10 — External verification (PENDING SG)

Once the SG is open, from your laptop:

```bash
curl -sI http://3.227.63.49:8001/health
curl -sI http://3.227.63.49:7880/
```

Both should return HTTP 200. If timeout: SG isn't opened yet. If connection refused: docker compose isn't running on the box (`ssh sophia-gpu` and `docker compose ps`).

---

## Phase 11 — Wire agent worker (revised after 2026-05-26 findings)

**Cross-region finding**: the EKS cluster is `spatial-ai-staging` in `us-west-2` (account 632872792182). The EC2 is in `us-east-1`. These are DIFFERENT regions, therefore DIFFERENT VPCs (VPCs don't cross regions). Original Case A (same-VPC cluster.local DNS) is impossible. Tested with `nslookup whisper-inference.multi-agent.svc.cluster.local` from the EC2 — SERVFAIL as expected (no DNS path to cluster CoreDNS).

Cost + latency notes for cross-region:
- Data transfer: ~$0.02/GB out of us-west-2. Voice audio is ~32 kbps each way; a 5-min demo is ~12 MB = sub-cent.
- Latency: us-east-1 to us-west-2 adds ~70 ms RTT per inference call. STT/LLM/TTS each pay this once per turn. Demo feels slightly more sluggish than local laptop.
- For real production, move the EC2 to us-west-2 (same region as EKS) to eliminate cost + latency. MVP-acceptable.

### Chosen path: Option C — kubectl port-forward on the EC2

Same pattern your Mac uses (`pf-gpu.sh` against the cluster), but running on the EC2 instead. The agent worker connects to `localhost:<port>` and the port-forward proxies to the EKS service via the EKS API endpoint. This works ACROSS regions because port-forward goes through the public/private API endpoint, not VPC-internal networking.

### Step 11.1 — Install kubectl on the EC2

```bash
cd /tmp
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
kubectl version --client
```

### Step 11.2 — AWS auth already in place via IAM Instance Profile

The EC2 has an instance profile (role `sophiaspatialai-ai-gpu-ec2`). Verify:

```bash
aws sts get-caller-identity
```

Returns Account 632872792182 (matches EKS account). No need for `aws configure` or copying credentials.

Set the default region (cluster's region, not EC2's):

```bash
aws configure set region us-west-2
```

### Step 11.3 — Get a kubeconfig onto the EC2

The IAM role on the EC2 lacks `eks:DescribeCluster` so `aws eks update-kubeconfig` fails with AccessDeniedException. Workaround: copy your Mac's kubeconfig over (it already has the cluster endpoint + CA cert inlined, and uses `aws eks get-token` for auth which DOES work with the EC2's role).

From your Mac:

```bash
ssh sophia-gpu mkdir -p /home/ubuntu/.kube
scp ~/.kube/config sophia-gpu:.kube/config
```

### Step 11.4 — Verify cluster access from the EC2

```bash
kubectl config current-context
kubectl get nodes
```

Three possible outcomes:

a. Lists EKS nodes → IAM role is in the cluster's aws-auth ConfigMap. Proceed to 11.5.

b. `error: You must be logged in to the server (Unauthorized)` → role isn't in aws-auth. Ask infra:
   > Add IAM role `arn:aws:iam::632872792182:role/sophiaspatialai-ai-gpu-ec2` (attached to EC2 `i-0748ed7c188c337cc`) to the spatial-ai-staging cluster's aws-auth ConfigMap. Suggested mapping: username `sophia-gpu-ec2`, groups `system:masters` (or namespace-restricted if preferred).
   > Also (optional but useful) add `eks:DescribeCluster` to the role's IAM policy so I don't need to copy kubeconfig from my Mac.

c. Other error → paste it, diagnose case-by-case.

### Step 11.5 — Verify access to multi-agent namespace

```bash
kubectl get svc -n multi-agent
kubectl get pods -n multi-agent
```

Should list the four inference services (whisper-inference, qwen3-inference, kokoro-tts, sophia-spatial-ai) and their pods.

### Step 11.6 — Run port-forwards

```bash
cd /workspace/avinash/sophia
./sophia-agent/infra/pf-gpu.sh
sleep 5
curl -s http://localhost:8122/health
echo
curl -s http://localhost:8080/v1/models | head -c 200
echo
curl -s http://localhost:18080/v1/models | head -c 200
echo
curl -s http://localhost:8106/health
echo
```

All four endpoints should respond. If any fail, check `/tmp/pf-gpu-logs/<svc>.log` for the specific reason.

### Step 11.7 — Update .env.production to localhost URLs

The defaults in agent.py are already localhost — env vars override. Either delete the four inference URL lines from `.env.production` (uses defaults) or set them explicitly:

```bash
nano /workspace/avinash/sophia/sophia-agent/.env.production
```

Set to:
```
WHISPER_URL=http://localhost:8080
QWEN3_URL=http://localhost:18080
KOKORO_URL=http://localhost:8122
SOPHIA_RAG_URL=http://localhost:8106
```

These match where the port-forwards listen.

### Then add the agent-worker service to docker-compose

Edit `docker-compose.yml` to uncomment / add:

```yaml
  agent-worker:
    build:
      context: ./sophia-agent
      dockerfile: Dockerfile
    network_mode: host
    env_file:
      - ./sophia-agent/.env.production
    restart: unless-stopped
```

Then:

```bash
docker compose build agent-worker
docker compose up -d agent-worker
docker compose logs --tail 50 agent-worker
```

Look for `registered worker id=AW_xxx url=ws://localhost:7880` in the logs (since the agent connects to livekit-server on the host loopback, network_mode: host gives it direct access). Plus a successful prewarm of Silero VAD.

If agent worker fails because it can't reach an inference service, the error message in logs will say which URL is unreachable. Adjust the env file and `docker compose up -d agent-worker` again.

---

## Phase 12 — Frontend (PENDING SG)

Three deploy options for `agent-starter-react`. Pick A for simplicity.

### Option A — Run on the same EC2

```bash
cd /workspace/avinash/sophia/agent-starter-react
npm install
```

Create `.env.local` for the frontend:

```bash
{
  echo "LIVEKIT_URL=ws://3.227.63.49:7880"
  echo "LIVEKIT_API_KEY=$LIVEKIT_API_KEY"
  echo "LIVEKIT_API_SECRET=$LIVEKIT_API_SECRET"
} > .env.local
chmod 600 .env.local
```

Build + run:

```bash
npm run build
nohup npm start -- --port 3000 --hostname 0.0.0.0 > /workspace/avinash/sophia/frontend.log 2>&1 &
disown
sleep 5
ss -tlnp | grep ':3000'
```

For quick MVP, you can also use `npm run dev` instead (slower but auto-reloads on file changes).

Test from your laptop:

```bash
# In a browser:
open http://3.227.63.49:3000
```

### Option B — Vercel

Set repo → connect Vercel → set the env vars:
```
NEXT_PUBLIC_LIVEKIT_URL=ws://3.227.63.49:7880
LIVEKIT_API_KEY=<value>
LIVEKIT_API_SECRET=<value>
TOKEN_ENDPOINT=http://3.227.63.49:8001/token
AGENT_NAME=sophia-agent
```

Push to main → Vercel auto-deploys → visit https://sophia-app.vercel.app.

NOTE: Browser may block `getUserMedia` on HTTP from a non-localhost origin. Chrome's workaround is `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, add `http://3.227.63.49:3000`, restart Chrome. Or move to the production setup with TLS.

### Option C — On user's laptop pointing at EC2 SFU

Simplest for personal demos. Run `npm run dev` on laptop, edit `agent-starter-react/.env.local` to point `LIVEKIT_URL=ws://3.227.63.49:7880`. Browser connects to localhost:3000 frontend which signals to EC2 SFU.

---

## Phase 13 — Point the glasses (PENDING)

Open `sophia-glasses/unity/Assets/Settings/SophiaConfig.asset` in Unity:

```
liveKitUrl    = ws://3.227.63.49:7880
tokenEndpoint = http://3.227.63.49:8001/token
```

(Currently set to Tailscale URL `ws://100.69.34.194:7880`. Swap to production IP.)

Rebuild APK in Unity, then:

```bash
adb install -r '/Users/avinashbolleddula/Documents/sophia Agent Research/sophia-glasses/unity/sophia-glasses.apk'
adb shell am force-stop com.UnityTechnologies.com.unity.template.urpblank
adb logcat -c
adb shell am start -n com.UnityTechnologies.com.unity.template.urpblank/com.unity3d.player.UnityPlayerGameActivity
adb logcat | grep -E 'Sophia|LiveKit'
```

Should see the glasses connect to EC2 from anywhere on the internet, no Tailscale needed.

---

## Maintenance

### Stop the docker stack (keep EC2 running)

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia
docker compose down
```

### Restart the docker stack

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia
docker compose up -d
```

### Stop the EC2 entirely (save $1.21/hour)

From your laptop (requires AWS CLI configured):

```bash
aws ec2 stop-instances --region us-east-1 --instance-ids i-0748ed7c188c337cc
```

To resume:

```bash
aws ec2 start-instances --region us-east-1 --instance-ids i-0748ed7c188c337cc
# Wait ~1 minute for boot
ssh sophia-gpu
cd /workspace/avinash/sophia
docker compose up -d
```

Elastic IP persists across stop/start, so the URL `3.227.63.49` stays the same.

### Pull updates to the code on the EC2

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia
git pull
git lfs pull
docker compose build
docker compose up -d --build
```

### Rotate secrets

```bash
ssh sophia-gpu
cd /workspace/avinash/sophia
# Regenerate
NEW_LIVEKIT_KEY=$(openssl rand -hex 16)
NEW_LIVEKIT_SECRET=$(openssl rand -hex 32)
NEW_TOKEN_API_KEY=$(openssl rand -hex 16)

# Update both files
sed -i "s|^LIVEKIT_API_KEY=.*|LIVEKIT_API_KEY=$NEW_LIVEKIT_KEY|" sophia-agent/.env.production
sed -i "s|^LIVEKIT_API_SECRET=.*|LIVEKIT_API_SECRET=$NEW_LIVEKIT_SECRET|" sophia-agent/.env.production
sed -i "s|^SOPHIA_TOKEN_API_KEY=.*|SOPHIA_TOKEN_API_KEY=$NEW_TOKEN_API_KEY|" sophia-agent/.env.production
sed -i "s|^  .*:.*|  $NEW_LIVEKIT_KEY: $NEW_LIVEKIT_SECRET|" sophia-agent/infra/livekit.prod.yaml

# Restart
docker compose down
docker compose up -d

# Update the frontend env (wherever it runs) with the new keys + restart
```

---

## Troubleshooting matrix

| Symptom | Likely cause | Quick check |
|---|---|---|
| `ssh sophia-gpu` says "Permission denied (publickey)" | Wrong key path or wrong permissions on the .pem | `ls -la ~/.ssh/sophiaspatialai-ai-us-east-1.pem` shows `-rw-------`; verify the `IdentityFile` in `~/.ssh/config` |
| `docker compose build` fails on uv install | apt update on the Docker base image hit a stale mirror | Retry; usually transient |
| LiveKit log shows `nodeIP: 127.0.0.1` instead of 3.227.63.49 | `--node-ip 3.227.63.49` flag missing or yaml has wrong `use_external_ip` | Verify `docker-compose.yml` command line and `livekit.prod.yaml` |
| `curl http://3.227.63.49:7880` from laptop times out | SG inbound rules not yet added | Confirm with infra; or open via AWS Console yourself |
| `curl http://3.227.63.49:8001/health` from laptop returns "Connection refused" | docker compose isn't running on the EC2 | `ssh sophia-gpu` then `docker compose ps` |
| Browser at http://3.227.63.49:3000 fails to capture mic | Chrome blocks `getUserMedia` over plain HTTP from public IP | Use `chrome://flags/#unsafely-treat-insecure-origin-as-secure` workaround; or move to TLS |
| Agent worker logs `Cannot connect to whisper-inference.multi-agent.svc.cluster.local` | EC2 not in same VPC as EKS, OR DNS doesn't resolve | Confirm with infra; switch to NLB hostnames |
| `docker compose up` returns "permission denied while trying to connect to Docker daemon socket" | User not in `docker` group | `sudo usermod -aG docker $USER && newgrp docker`; or just `sudo docker compose up` |
| `needrestart` whiptail prompt during apt install | Ubuntu 22.04 default | Press Tab + Enter to accept; or `export NEEDRESTART_MODE=a` once per session |
| Heredoc paste in terminal adds leading whitespace and bash complains about unmatched EOF | Terminal paste normalization | Use line-by-line `{ echo "..."; ... } > file` instead |
| ports survey shows ports in use that we plan to use | Conflict with Ivana | Pick alternative ports, update yaml + docker-compose.yml accordingly |

---

## Open questions to ask infra (revised 2026-05-26)

1. ~~Is the EC2 in the same VPC as the EKS cluster?~~ **ANSWERED: NO.** Cluster `spatial-ai-staging` lives in us-west-2 (account 632872792182); EC2 is in us-east-1. Different regions = different VPCs by definition. Cross-region kubectl port-forward (Option C in Phase 11) is the chosen path.
2. ~~Set up VPC peering or provide internal NLB hostnames?~~ **NOT NEEDED for MVP.** Option C avoids this entirely. For real production we'd want to move the EC2 to us-west-2 instead.
3. Add the five inbound rules to SG `sophiaspatialai-gpu-20260511165512897100000004` per Phase 9. **STILL PENDING.** Until done, no external client can reach the EC2 on our ports.
4. **NEW**: Add the EC2's IAM role `arn:aws:iam::632872792182:role/sophiaspatialai-ai-gpu-ec2` to the spatial-ai-staging cluster's aws-auth ConfigMap. Suggested mapping: username `sophia-gpu-ec2`, groups `system:masters` (or namespace-scoped). Without this, kubectl from the EC2 returns Unauthorized even after the kubeconfig is in place.
5. **NEW (optional)**: Add `eks:DescribeCluster` to the IAM role's policy so `aws eks update-kubeconfig` works directly on the EC2 (avoids the manual scp-from-Mac workaround in Step 11.3).

Critical path: items 3 and 4 must both be done before external demo can happen. Item 5 is convenience.

---

## Cost note

g5.2xlarge runs at ~$1.21/hour = ~$870/month always-on. Stop with `aws ec2 stop-instances` when not in use.

The MVP doesn't NEED a GPU box. When the team approves moving past MVP, ask infra for a separate cheaper instance (t3.large = ~$60/month, sufficient for SFU + agent + token-mint since all inference is delegated to EKS). At that point follow `production_deployment.md` for the full prod setup with TLS, domain, Secrets Manager, etc.

---

## What this document does NOT cover

- TLS / HTTPS / WSS (not part of MVP; see `production_deployment.md`)
- Domain setup (not part of MVP)
- AWS Secrets Manager (using local .env.production for now)
- CI/CD auto-deploy (manual `git pull` + `docker compose up -d --build` for now)
- High availability / load balancing
- Backup / disaster recovery
- Multi-tenant room namespacing per client (Appendix C Q1 in unity_approach.md)

All of those are documented in `production_deployment.md` and can be layered on later.
