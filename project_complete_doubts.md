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

Two things ALSO needed but they're NOT in the docker-compose file:

- **AWS Security Group ingress rules** for ports 7880 (TCP signal), 7881 (TCP fallback), 50000-60000 (UDP media). Without these, the container starts fine but no client can reach it.
- **The livekit.prod.yaml file itself** — gitignored on EC2 (has secrets). Schema documented in `sophia-agent/infra/livekit.prod.yaml.example`.

Compare with the other two services in the same compose file (token-mint, agent-worker): those have `build: { context: ..., dockerfile: ... }` instead of `image:`, because we wrote custom Python code for them. The SFU has zero custom code — pure stock LiveKit binary.

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
