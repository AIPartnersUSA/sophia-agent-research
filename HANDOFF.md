# HANDOFF.md — Sophia voice agent → infra team

You are inheriting a working MVP voice-agent deployment that runs on a shared GPU EC2. Your job is to take it to real production (k8s manifests, ArgoCD, real auth, TLS, secrets management, CI/CD). This doc tells you exactly what you have, what you need to build, and the recommended order.

Read time: ~20 minutes. Then read `mvp_deployment_shared_ec2.md` (45 min) and `production_deployment.md` (15 min) for the deeper context.

For a structural understanding of HOW the system works end-to-end (every component, every port, every JWT field, both client paths step-by-step) read `livekit_architectur_ec2.md`. That doc is the engineering-mental-model reference and pairs well with this handoff doc.

---

## TL;DR

- A working voice-agent (STT → LLM-with-RAG → TTS) is live on a shared g5.2xlarge EC2 at `3.227.63.49`. Browser + XREAL Beam Pro glasses both work.
- Three services: `livekit-server` (WebRTC SFU), `token-mint` (FastAPI JWT minter), `agent-worker` (Python LiveKit Agents worker). Plus a Next.js frontend served by `npm start`.
- Inference services (Whisper, Qwen3-VL, Kokoro, sophia-spatial-ai) already run on the team's EKS cluster `spatial-ai-staging` in `us-west-2`. The EC2 reaches them via kubectl port-forward FROM the EC2 (cross-region pattern — works because port-forward goes through the EKS API endpoint, not VPC-internal networking).
- Orchestration is Docker Compose. NO k8s manifests, NO Helm, NO ArgoCD exist yet — that's your work.
- Auth on the token-mint is a shared X-API-Key header. NOT production-grade. Replace with real auth.
- TLS terminates nowhere — everything is HTTP. Replace with HTTPS via cert-manager or ALB+ACM.
- Repo: `git@github.com:AvinashSophia/sophia-agent-research.git` (private). You should be added as a collaborator before starting.

---

## What you are inheriting

### Live deployment

| Item | Where |
|---|---|
| Shared GPU EC2 | `3.227.63.49`, `i-0748ed7c188c337cc`, g5.2xlarge, us-east-1, AZ us-east-1a, VPC `vpc-0eeab16713f4f744d` |
| SG | `sophiaspatialai-gpu-...` — TCP 22, 3000, 7880, 7881, 8001 + UDP 50000-60000 from `var.allowed_cidrs` (defaults 0.0.0.0/0) |
| Workspace on EC2 | `/workspace/avinash/sophia/` |
| Running stack | `docker compose up -d` (livekit-server + token-mint + agent-worker) + `npm start` for the frontend |
| EKS cluster | `spatial-ai-staging` in us-west-2 — already runs Whisper, Qwen3-VL-8B, Kokoro-82M, sophia-spatial-ai (vector DB + retrieval) |
| Container registry | None in use today. Images are built locally on the EC2 with `docker compose build`. |

### What lives in the git repo

```
sophia-agent-research/
├── sophia-agent/                           ← Python backend
│   ├── src/
│   │   ├── agent.py                        ← LiveKit Agents worker entrypoint
│   │   ├── token_mint.py                   ← FastAPI JWT minter
│   │   └── ...
│   ├── Dockerfile                          ← agent-worker image build
│   ├── Dockerfile.token-mint               ← token-mint image build (slimmer)
│   ├── pyproject.toml + uv.lock            ← Python deps (uv-managed)
│   └── infra/
│       ├── pf-gpu.sh                       ← kubectl port-forward helper (cross-region EKS)
│       └── (livekit.prod.yaml is gitignored — see "Not in repo")
│
├── agent-starter-react/                    ← Next.js frontend (vendored, NOT submodule)
│   ├── app/api/token/route.ts              ← browser-side token endpoint (open route, no auth)
│   ├── app-config.ts                       ← agentName hardcoded
│   ├── components/                         ← UI components
│   ├── package.json + package-lock.json
│   └── next.config.ts
│
├── sophia-glasses/                         ← Unity client for XREAL glasses
│   ├── unity/Assets/Scripts/               ← 5 scripts we authored (Config, Connection, etc.)
│   ├── unity/Assets/Settings/SophiaConfig.asset   ← runtime config (URLs + tokenApiKey)
│   ├── unity/Assets/Plugins/Android/AndroidManifest.xml   ← Custom Main Manifest
│   ├── xreal-sdk/                          ← vendored XREAL SDK (via Git LFS)
│   └── client-sdk-unity/                   ← vendored LiveKit Unity SDK (via Git LFS)
│
├── docker-compose.yml                      ← workspace-root orchestration (3 services)
├── .gitignore + .gitattributes             ← LFS config + per-machine file exclusions
│
└── Documentation (canonical at repo root):
    ├── HANDOFF.md                          ← this file
    ├── mvp_deployment_shared_ec2.md        ← THE operational runbook + 19 documented problems
    ├── production_deployment.md            ← migration roadmap + Section 0 Keep/Replace/Defer
    ├── deploy_to_ec2.md                    ← original deployment narrative (superseded by mvp doc)
    ├── git_setup.md                        ← repo + LFS setup
    ├── git_sync.md                         ← Mac + EC2 + GitHub reconciliation procedure
    ├── livekit_doubts.md                   ← 62 Q&A items on LiveKit framework + debugging
    ├── livekit_deployment.md               ← deployment design rationale (Q1-Q29)
    ├── steps_to_run.md                     ← browser + glasses local-dev quick reference
    ├── demo_multiroom_recording.md         ← Scenario A/B demo recording plan
    ├── unity_approach.md                   ← 2500-line Unity/XREAL journey + Appendix B runbook
    ├── COMPARISON.md, STT_models.md, TTS_models.md, STS_models.md   ← Phase 1 model research
    └── sophia_week3_presentation.html      ← team demo deck (reveal.js)
```

### Three production-relevant code facts

1. **`agent-starter-react/app/api/token/route.ts`** has the original Next.js starter's `NODE_ENV !== 'development'` throw guard REMOVED. This was needed so production builds can mint tokens. Currently the route is open (no auth). When you add real auth, restore a guard but make it auth-based, not env-based.

2. **`agent-starter-react/app-config.ts`** has `agentName: 'sophia-agent'` HARDCODED, not env-driven. This is because Next.js strips non-`NEXT_PUBLIC_` env vars from the client bundle at build time, leaving the JWT roomConfig.agents empty if agentName comes from `process.env.AGENT_NAME`. If you want it env-driven in production, prefix with `NEXT_PUBLIC_` OR mint the JWT entirely server-side (recommended).

3. **`sophia-agent/Dockerfile`** has `ENV HF_HOME=/app/.cache/huggingface` set in BOTH the build stage and the final stage. This is so the turn-detector model gets downloaded under `/app/.cache` (which gets copied through the multi-stage build) rather than `/root/.cache` (which doesn't). Don't remove this.

---

## What is intentionally NOT in the repo

These files contain secrets or environment-specific values. They are `chmod 600`, gitignored, and live ONLY on the EC2 today. You will need to recreate equivalents in your production secrets-management system.

**Three template files ARE in the repo to make this easier:**
- `sophia-agent/.env.production.example` — backend env template with every variable documented + `openssl rand` commands for generating values.
- `sophia-agent/infra/livekit.prod.yaml.example` — SFU config template.
- `agent-starter-react/.env.local.example` — frontend env template.

Copy each `.example` file to its non-example sibling, fill in real values (the comments tell you exactly how to generate each one), and `chmod 600`. For production, do NOT use these as runtime files directly — load the same variables from your secrets manager (External Secrets Operator pulling from AWS Secrets Manager is the recommended pattern).

### `sophia-agent/.env.production` (on EC2)

```bash
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=<32-hex-chars>
LIVEKIT_API_SECRET=<64-hex-chars>
SOPHIA_TOKEN_API_KEY=<32-hex-chars>          # shared API key for /token endpoint
SOPHIA_CORS_ORIGINS=*

# Inference URLs (currently localhost because kubectl port-forwards):
WHISPER_URL=http://localhost:8080
QWEN3_URL=http://localhost:18080
KOKORO_URL=http://localhost:8122
SOPHIA_RAG_URL=http://localhost:8106
```

For production: stop using port-forwards. Either co-locate the agent-worker in the same EKS cluster as the inference services (cluster-internal DNS like `whisper-inference.multi-agent.svc.cluster.local:8080`), OR put the inference services behind an internal NLB and let the agent-worker hit that.

### `sophia-agent/infra/livekit.prod.yaml` (on EC2)

```yaml
port: 7880

rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 60000
  use_external_ip: false       # set to true if behind NAT

keys:
  <api-key>: <api-secret>       # SAME values as LIVEKIT_API_KEY/SECRET in .env.production

logging:
  level: info
  json: false
```

The `keys:` block must contain the SAME API key/secret pair that the token-mint uses to sign JWTs (otherwise the SFU rejects the tokens). In production, mount this via a k8s Secret rather than chmod-600 file.

### `agent-starter-react/.env.local` (on EC2)

```bash
LIVEKIT_URL=ws://3.227.63.49:7880
LIVEKIT_API_KEY=<same as .env.production>
LIVEKIT_API_SECRET=<same as .env.production>
```

These are used by the Next.js route handler at `/api/token` (server-side, not exposed to browser).

---

## Architecture you should preserve

### The SFU needs host networking (or equivalent UDP exposure)

`livekit-server` runs in docker-compose with `network_mode: host` because WebRTC uses a UDP port range (50000-60000) for media plus TCP 7880 for signal. Docker's default bridge networking would force you to publish each port individually, which doesn't scale, and breaks NAT traversal because the SFU advertises its container IP (not the host IP) in candidate negotiation.

In k8s, the equivalent options are:

- **Recommended**: `hostNetwork: true` on the Pod spec, run as a DaemonSet or single-replica Deployment pinned to a labeled node. Same outcome as docker host network.
- **Alternative**: dedicated NodePort service with the full UDP range exposed. Works but the YAML is verbose (you have to list every port) and Kubernetes generally dislikes large port ranges.
- **NOT recommended**: putting the SFU behind a generic ALB or k8s Service of type=LoadBalancer. ALBs don't handle UDP. Network Load Balancers do but you still hit the candidate-IP problem.

Read `livekit_doubts.md` Q62 for the full rationale on why host networking matters for the SFU specifically.

### Agent-worker needs same-network access to the SFU + outbound access to inference

The agent-worker connects to the SFU as a LiveKit participant. In docker-compose it's on host network too with `LIVEKIT_URL=ws://localhost:7880` override so it loops back to the local SFU. In k8s either:

- Put both Pods on host network so the worker can use `ws://localhost:7880`.
- Or use a ClusterIP Service for the SFU and set `LIVEKIT_URL=ws://livekit-server.namespace.svc.cluster.local:7880`.

The worker also needs OUTBOUND access to the inference services. Today that's via kubectl port-forwards FROM the EC2; in production, since the inference cluster is in `us-west-2` and the workload would presumably move there too, this becomes same-cluster service-to-service traffic (cheap, fast, no port-forwards).

### Token-mint is just plain HTTP

`token-mint` is a FastAPI service on port 8001. Plain HTTP, request-response. Standard k8s Service of type=ClusterIP behind an Ingress is fine.

### The Next.js frontend has a server-side token route too

`agent-starter-react/app/api/token/route.ts` mints LiveKit JWTs using `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` from its own env (the Next.js process env). This is the BROWSER path — browser clients hit this, not the FastAPI token-mint. The FastAPI token-mint is for non-browser clients (glasses APK, future iOS/CLI clients).

For production: decide whether to keep both paths (browser uses Next route, others use FastAPI) or collapse them (all clients use FastAPI). Two paths is fine for MVP, one path is cleaner long-term.

---

## What you need to build for production

In rough priority order:

### 1. Kubernetes manifests (or Helm chart) for the three services

Translate `docker-compose.yml` into k8s. Required resources per service:

**livekit-server**
- Deployment (or DaemonSet) with `hostNetwork: true`, single replica or pinned to a node label
- ConfigMap (or Secret) for `livekit.prod.yaml`
- No Service needed if hostNetwork; if not, NodePort with the full UDP range
- PodDisruptionBudget if you want HA across nodes (requires LiveKit redis-backed clustering — separate undertaking)

**token-mint**
- Deployment, multiple replicas OK (it's stateless)
- Service (ClusterIP, port 8001)
- Secret containing `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `SOPHIA_TOKEN_API_KEY` (or whatever auth replaces it)
- Ingress with TLS for external clients (glasses) to hit

**agent-worker**
- Deployment, replicas = however many concurrent sessions you support (each worker handles one room at a time in the LiveKit Agents pattern)
- Same Secret as token-mint (needs LIVEKIT_API_KEY/SECRET for SFU connection) + inference service URLs
- No Service needed (worker is a CLIENT to the SFU, not a server)
- Consider HorizontalPodAutoscaler driven by worker registration metrics, OR LiveKit's job dispatch system if scaling per-session

**frontend (Next.js)**
- Two options: (a) build as static export → host on CloudFront + S3, no k8s. (b) keep as `npm start` server → Deployment + Service + Ingress.
- Has its own Secret for `LIVEKIT_API_KEY/SECRET` (used by the server-side /api/token route)

### 2. Secrets management

Today's secrets are in chmod-600 files on the EC2. Pick one of:

- **AWS Secrets Manager** + External Secrets Operator (k8s-native, syncs into k8s Secrets)
- **HashiCorp Vault** + Vault Agent Injector
- **Sealed Secrets** (simpler, less infrastructure, secrets-in-git-but-encrypted)

For each environment (staging, prod), maintain separate secret sets. Never reuse the MVP keys for prod (the LiveKit API key + secret pair are in this conversation's git history, in `livekit.prod.yaml`; treat them as compromised for production purposes).

### 3. TLS termination

Today everything is HTTP. Browsers REQUIRE HTTPS for `navigator.mediaDevices` (the mic API), which is why the MVP demo needs the `chrome://flags#unsafely-treat-insecure-origin-as-secure` workaround.

Production needs:
- A domain name (e.g. `sophia.aipartnersusa.com`)
- TLS cert via cert-manager + Let's Encrypt OR AWS ACM + ALB
- WSS (not WS) for the SFU signal port — the LiveKit server can terminate TLS itself, OR you put it behind a TCP-passthrough load balancer with TLS termination upstream
- HTTPS for token-mint + frontend (standard k8s Ingress + cert-manager)

### 4. Real auth on token-mint

Replace the shared X-API-Key with one of:

- **Auth0 / Clerk / Cognito** JWT verification (most common for SaaS)
- **OAuth proxy** in front of the token-mint Service
- **mTLS** if all clients are owned hardware (the glasses fit this)

Per-user identity, not per-deployment. Currently any caller with the key can mint a JWT for ANY identity — production needs the caller's identity to bind to the JWT's `sub` claim.

### 5. Agent-worker scaling

Today there's ONE agent-worker process registered against the SFU. It can handle ONE room at a time. Multiple users → multiple rooms → need multiple workers.

Two approaches:

- **Static replicas**: deploy N workers. Each registers with the SFU. SFU dispatches incoming rooms round-robin. Simple. Wastes resources during low load.
- **LiveKit Job Dispatch**: workers register as available, SFU sends a "job offer" per new room, worker accepts and joins. Scales to zero. Requires reading LiveKit Agents source for the dispatch protocol.

Read `livekit-agents/` (vendored upstream source at sibling of project root) for the dispatch pattern. The MVP doesn't exercise this.

### 6. CI/CD

GitHub Actions workflow on push to `main`:

1. Run linters + tests
2. Build container images (`sophia-agent` and `sophia-agent-token-mint`), tag with git SHA
3. Push to ECR
4. Trigger ArgoCD sync (or update the image tag in a values.yaml that ArgoCD watches)

ArgoCD Application manifest points at this repo's `deploy/k8s/` (or `deploy/helm/`) path. App-of-Apps pattern if you split staging vs prod.

### 7. DNS + domain

Decide on a public domain. Point an A or ALIAS record at the production load balancer. cert-manager picks up the domain for Let's Encrypt automatic renewal.

### 8. Observability

Today: docker logs + `adb logcat` for glasses + browser DevTools. Production needs:

- Container stdout → CloudWatch / Loki / Datadog
- LiveKit's `/metrics` endpoint (Prometheus format) → existing Grafana
- Application traces (OpenTelemetry) — agent-worker has natural span boundaries (STT call, RAG call, LLM call, TTS call)
- Alerts on: worker registration failures, JWT verification failures, inference call latency p99

---

## Recommended migration sequence

Order matters — each step builds on the previous one. Do not attempt #5 before #2.

1. **Read the docs in this order**: this file → `mvp_deployment_shared_ec2.md` → `production_deployment.md` → `livekit_doubts.md` Q61 + Q62 → `livekit_deployment.md` Q28 + Q29.
2. **Watch a demo of the live MVP** (ask Avinash for 30 min). See what works before redesigning.
3. **Write Dockerfile.frontend** for the agent-starter-react app. The MVP runs it via `npm start` directly. Containerize it for k8s.
4. **Set up secrets management** (AWS Secrets Manager + External Secrets Operator, or your team's standard). Populate with NEW values for production — do NOT reuse the MVP keys.
5. **Write k8s manifests** for the four services (livekit-server, token-mint, agent-worker, frontend). Start with vanilla YAML; convert to Helm later if needed. Test in a staging namespace.
6. **Set up TLS + domain** before exposing externally. Get HTTPS working on the staging URL.
7. **Migrate inference access**. Move the agent-worker into the same EKS cluster as the inference services (or set up an internal NLB) so the port-forwards go away.
8. **Replace shared API key with real auth**. Token-mint accepts an auth-provider JWT instead of `X-API-Key`.
9. **Set up ArgoCD** pointing at the manifests. Test sync.
10. **Set up CI** to build images on push and update the image tags.
11. **Smoke-test from browser + glasses on the new domain**. Compare against the MVP behavior. If anything breaks, the MVP runbook (`mvp_deployment_shared_ec2.md`) is your reference.
12. **Decommission the shared EC2** once the new production environment is stable. Notify Ivana before stopping the EC2 (it's shared with her Jupyter + Streamlit work).

---

## Things NOT to do

- **Don't put the SFU behind a generic ALB.** ALBs don't handle UDP. The SFU needs host networking or NLB with the full port range — see `livekit_doubts.md` Q62.
- **Don't reuse the MVP LiveKit keys for production.** The MVP `livekit.prod.yaml` contents have been seen in chat logs; rotate before production.
- **Don't `git checkout --` files on the EC2 without diffing first.** Some files on EC2 may have intentional edits the team hasn't committed yet. Use `git status` + `git diff` first.
- **Don't add real production code to the MVP `docker-compose.yml`.** That file is a baseline reference. Treat it as read-only and build new k8s manifests next to it.
- **Don't put the SFU and worker on the same Pod.** They scale differently — SFU is one-per-cluster, worker is N-per-cluster.
- **Don't run `npm install` on a production container build** — use `npm ci` to respect the lockfile. The MVP repo had npm-install drift between machines; lockfile-based installs prevent this.
- **Don't enable LiveKit E2EE without reading the production_deployment.md note on it.** It's not on by default for good reasons.
- **Don't deploy to production without testing the glasses path.** The XREAL Beam Pro client speaks the same LiveKit protocol as the browser but has different audio behavior (Q41, Q43, Q58 in livekit_doubts.md). Glasses validation is a separate test pass.

---

## Open questions for product / team

Decisions the infra team should NOT make alone — surface these to Avinash + product:

- **Multi-tenancy model**: one Sophia per customer? Per facility? Per device? Affects room-naming convention and identity model.
- **Recording / compliance**: does Sophia store any session audio? Transcripts? If yes, where + retention? (LiveKit Egress can record sessions but it's separate infra.)
- **Per-user auth**: real auth provider choice (Auth0? Cognito? something internal?)
- **SLA / availability targets**: are we 99.5% or 99.9%? Drives HA decisions (LiveKit redis clustering, multi-AZ, etc.)
- **Cost ceiling per month**: drives instance sizing, scaling policy, idle-worker behavior.
- **XREAL glasses authentication**: do glasses authenticate as a USER or as a DEVICE? Affects the JWT identity scheme.

---

## Where to ask Avinash questions

Avinash (`avinash.bolleddula@gmail.com`) built the MVP and authored most of the docs in this repo. The fastest unblock path:

1. Search the doc first. `mvp_deployment_shared_ec2.md` has 19 documented problems with symptom→cause→fix. `livekit_doubts.md` has 62 Q&A items. Chances are your question is already answered.
2. If not, ask Avinash with the file + line number you're looking at — that grounds the question.
3. Most-likely-to-need-clarification topics: the cross-region EKS access pattern (mvp doc Phase 9-10), the multi-user audio contract (livekit_doubts Q58), the manifest path math for Unity (Q59), the Custom Main Manifest gotchas (Q55).

---

## Cross-references — read this also

- `mvp_deployment_shared_ec2.md` — the daily operations doc for the current MVP. Phases 1-14 walk through how it got built. 19 documented problems. Read this BEFORE designing production replacements.
- `production_deployment.md` — earlier production design doc. Section 0 has Keep/Replace/Defer lists which are the high-level migration intent.
- `git_sync.md` — the procedure for reconciling code edits across the Mac dev box, the EC2 demo box, and GitHub. Useful when you start making changes.
- `git_setup.md` — repo structure + LFS appendix. Read if you need to understand how the XREAL + LiveKit Unity SDKs are vendored.
- `livekit_deployment.md` — Q1-Q29 covering deployment design rationale. Q28 + Q29 are about the MVP + auth. Q1-Q27 cover the journey from local dev to the EC2 architecture choice.
- `livekit_doubts.md` — 62 Q&A items on LiveKit framework, plugin debugging, glasses-specific issues. Search this before re-deriving anything from first principles.
- `unity_approach.md` — the 2500-line Unity narrative. Appendix B is the operational runbook for the glasses path; the rest is mostly for the Unity engineer, not infra.

---

## When to update this file

- After your first prod deploy lands — replace the "What you need to build" section with "What's now deployed in production" + a "What's still TODO" section.
- When new constraints emerge from compliance / legal / customer requirements (these tend to invalidate parts of the architecture).
- When a service is added or removed.
- When the auth model changes.
