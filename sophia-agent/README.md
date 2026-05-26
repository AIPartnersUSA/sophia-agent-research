# sophia-agent

Sophia voice agent on fully self-hosted OSS LiveKit.

This is the **OSS-replication twin** of `../my-agent`. The goal is to prove the
self-hosted path (local livekit-server + AWS STT/LLM/TTS) matches the UX of the
Cloud + Inference baseline before we ship to production.

See `AGENTS.md` for the full project guide, integration routes (A vs B), and
day-one run order. See `../livekit_deployment.md` (repo root) for the
local-vs-production deployment playbook.
