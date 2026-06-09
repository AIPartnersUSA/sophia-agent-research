# 6 questions for infra team before Documind smoke-test

Draft Slack/email message — fire this off so answers arrive in parallel with the code work.

---

**Subject: 6 questions before we wire Documind into sophia-agent**

Hey infra team,

Starting Documind integration into our sophia-agent (LiveKit voice agent worker). Code is being written today as opt-in via `USE_DOCUMIND=1` env var so the current Qwen3 path stays default. Before we flip the flag on EC2 and run a smoke test, want to confirm a few things:

**1. Auth for backend service worker**: Should sophia-agent use the `DOCUMIND_API_KEY` super-user key (env var on the worker container), or do you want us to use a service-account Cognito JWT? If JWT, where do we get one?

**2. Company slug**: We need to pass `company_slug` on every call. What slug should we use for Sophia's wearable content? Specific suggestion (e.g. `sophia`, `aip`, `default`)? We can hardcode `acme` for testing but want a canonical value.

**3. Reachable URL from our EC2 (us-east-1)**:
- In-cluster `documind:8502` would need kubectl port-forward (our EKS is us-west-2 — cross-region). Are you OK with us adding `documind` to our `pf-gpu.sh` `KNOWN_GPU_SERVICES`?
- External `https://staging.docu-mind.com/documind-api/health` returns connection-timeout from our EC2. Is `/health` the right path, and is the external URL reachable, or should we go in-cluster?

**4. Whisper STT consolidation**: Documind's `/look-and-ask` uses self-hosted Whisper internally. We already use `whisper-inference` (port 8080 in our port-forwards) via the LiveKit Agents framework STT plugin. Are these the SAME Whisper deployment, or different? Worth consolidating before we burn duplicate GPU.

**5. Ingest status**: Sophia currently grounds on the GV70 manual + other industrial-equipment PDFs via sophia-spatial-ai. Has any equivalent corpus been ingested into Documind yet, under a `company_slug` we can point at? If not — do we run `POST /admin/ingest` ourselves, or do you ingest on our behalf?

**6. Retire `sophia-spatial-ai` (port 8106)?**: Now that Documind does retrieval, is sophia-spatial-ai being deprecated? Affects whether we drop the port-forward + URL constant in agent.py. Don't want to leave dead code paths if it's going away.

Once you answer, we just need to set `DOCUMIND_API_KEY`, `DOCUMIND_URL`, `DOCUMIND_COMPANY_SLUG` env vars on EC2 + flip `USE_DOCUMIND=1` + restart agent-worker. ~5 min after we hear back.

Thanks!

---

### Sending tips

- Slack: post in the `#infra` (or wherever your infra coordination happens) channel. Or DM to the deploy lead.
- Email: `Cc:` the Documind dev who deployed it so the right person sees it without forwarding.
- Avoid: posting in a noisy general channel — these are 6 specific decisions that need 6 specific answers, easy to lose in scroll.
