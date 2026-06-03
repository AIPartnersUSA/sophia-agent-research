# CLAUDE.md — Sophia Voice Agent Research

Orientation for any Claude session working in this directory. Durable conventions only — evolving state lives in the project memory file (see Memory pointer below).

## What this project is

Research + benchmarking effort for a voice agent (STT → RAG → TTS, or end-to-end STS) targeting **XREAL glasses tethered to an Android phone**. The Android phone is the LiveKit client; the glasses are display + optional mic/speaker/camera. Two architectures are being compared empirically: cascaded vs end-to-end STS.

Production deployment is leaning **OSS self-hosted** (not LiveKit Cloud), with the Cloud free tier acceptable during benchmarking.

**Phase status:**
- Phase 1 (model landscape research) — ✅ DONE
- Phase 2 (LiveKit-based plug-and-play benchmarking) — in progress

For current state, open questions, and the decided next sequence, **read the project memory** (see pointer below) — that file is updated continuously.

## Directory layout

```
sophia Agent Research/
├── CLAUDE.md                          ← this file
├── HANDOFF.md                         ← infra-team onboarding (the handoff doc)
├── livekit_architectur_ec2.md         ← end-to-end architecture of EC2 backend
├── production_deployment.md           ← future-state production design
├── mvp_deployment_shared_ec2.md       ← operational runbook for current MVP
├── livekit_deployment.md              ← deployment design rationale Q&A
├── git_setup.md, git_sync.md          ← repo + sync procedures
├── docker-compose.yml                 ← active EC2 compose config
├── sophia-agent/                      ← backend code (Python, uv-managed)
├── sophia-glasses/                    ← Unity client for XREAL
├── agent-starter-react/               ← Next.js frontend
├── my-agent/                          ← Cloud + Inference baseline LiveKit Agents project
│   ├── AGENTS.md                      ← my-agent's own conventions (uv, ruff, TDD, lk docs)
│   └── src/agent.py                   ← entrypoint
├── docs/
│   └── internal/                      ← our understanding / research notes / Q&A logs (NOT for infra)
│       ├── STT_models.md              ← Phase 1: ~30 STT models with citations
│       ├── TTS_models.md              ← Phase 1: ~30 TTS models
│       ├── STS_models.md              ← Phase 1: ~24 end-to-end STS / audio-LLM models
│       ├── COMPARISON.md              ← cross-category synthesis + Phase 2 test matrix
│       ├── livekit_doubts.md          ← LiveKit framework / plugin / debugging Q&A
│       ├── project_complete_doubts.md ← architecture/strategy Q&A (Q1, Q2, …)
│       ├── Sophia_Xreal-U2.md         ← XR engineer's repo architecture survey
│       ├── unity_approach.md          ← Unity narrative
│       ├── xr_build_voice_integration.md
│       ├── steps_to_run.md, demo_multiroom_recording.md
│       └── sophia_week*_presentation.html
├── livekit-agents/                    ← read-only reference clone (gitignored)
└── Sophia_Xreal-U2/                   ← XR engineer's repo, reference clone (gitignored)
```

**Boundaries:**
- Root-level `*.md` docs are the **infra-team handoff surface**. Keep them current.
- `docs/internal/` is **our understanding**: research, Q&A logs, presentations. Append to existing files via the Q&A logging convention below; don't restructure.
- `livekit-agents/` and `Sophia_Xreal-U2/` are **read-only reference clones**. Never commit changes there.
- `my-agent/` is one of two code dirs we touch. Follow `my-agent/AGENTS.md` for its conventions (uv, ruff, TDD, lk docs).

## Q&A logging convention (BLOCKING — always apply)

When the user asks a question and gets an answer worth keeping, append it to the matching file. The convention:

| Topic of the question | File to append to |
|---|---|
| Specific STT model (Whisper, Parakeet, Granite, Kyutai stt, etc.) | `docs/internal/STT_models.md` |
| Specific TTS model (Orpheus, CosyVoice, Kokoro, Chatterbox, etc.) | `docs/internal/TTS_models.md` |
| Specific STS / audio-LLM model (Moshi, Step-Audio, Qwen-Omni, etc.) | `docs/internal/STS_models.md` |
| Cross-category strategy, architectural fork, Phase 2 planning | `docs/internal/COMPARISON.md` |
| LiveKit framework, plugins, `my-agent` debugging, deployment | `docs/internal/livekit_doubts.md` |
| Architecture/strategy clarifications (XR-engineer integration, key topology, end-to-end flows) | `docs/internal/project_complete_doubts.md` |

Format: `## Q<n> (YYYY-MM-DD): <question>` followed by the answer. Number monotonically within each file. Save **only after** the answer has converged — don't log half-answers.

The user often types just `save` after an answer they liked — that's the signal to append.

## Sourcing & decision principles

- **Open-source-only** for actual deployment candidates. Proprietary models (GPT-4o realtime, Gemini Live, ElevenLabs, Cartesia, Deepgram) appear in research files only as reference bars, never as Sophia's candidates.
- **Cite every claim with a URL.** Acceptable: arXiv, HF model cards, GitHub repos, vendor docs. NOT acceptable as primary citation: blog summaries, X threads, news articles.
- **Breadth before narrowing.** When the user asks for a research pass, deliver the full option space first; do not pre-filter on hardware/language/latency unless the user has constrained.
- **License rigor.** Verify Apache 2.0 / MIT / CC-BY-4.0 vs CC-BY-NC / CPML / AGPL. Watch for retroactive license changes (Spark-TTS Apache → CC-BY-NC-SA is a known trap). Surface non-commercial licenses explicitly.

## Code conventions inside `my-agent/`

Defer to `my-agent/AGENTS.md` for the authoritative list. Key points:
- `uv` for all dependency / run / test commands. Never raw `pip`.
- `src/agent.py` is the entrypoint (used by the Dockerfile).
- Format with `uv run ruff format` and `uv run ruff check`.
- For LiveKit API specifics, prefer `lk docs search` / `lk docs get-page` (CLI v2.15.0+) over training-data recall — the API evolves.
- TDD when modifying core agent behavior (instructions, tools, workflows).
- Custom plugins go in `src/plugins/<name>.py` and import into `agent.py`.

## How custom plugins relate to the model layer

LiveKit's plugin system has three layers — only one of them is the model layer. Plugins replace ONLY the model layer:

1. **Network (SFU)** — `livekit-server` (self-hosted) or LiveKit Cloud. Plugins do not replace this.
2. **Audio enhancement** — optional (ai-coustics is Cloud-locked; DeepFilterNet 3 / Silero are OSS substitutes).
3. **Model layer** — STT + LLM + TTS plugins, pointing wherever (Replicate, fal, localhost, self-hosted GPU, AWS).

Two routes for custom open-source models:
- **Route A:** Model server speaks OpenAI-compatible HTTP (vLLM, Faster-Whisper-Server, etc.) → use existing `openai` plugin with `base_url=...` — zero custom code.
- **Route B:** Custom protocol → subclass `livekit.agents.{stt,tts,llm,vad}` base classes into `src/plugins/<name>.py`.

## Chat history

LiveKit owns `ChatContext` client-side and re-sends full `messages[]` every turn (chat-completions APIs are stateless). Exception = OpenAI Realtime / Gemini Live (server-side session via `openai.realtime.RealtimeModel(...)`). When wiring custom LLM plugins, the plugin receives the full history in `chat_ctx.messages[]`; it's the plugin's job to pass it through in a shape the backend can use.

## Memory pointer (evolving state)

Durable session-spanning state lives in:
```
~/.claude/projects/-Users-avinashbolleddula-Documents-sophia-Agent-Research/memory/
├── MEMORY.md                              ← index
├── project_sophia_voice_agent.md          ← current Phase 2 state, decided sequence, open questions
├── feedback_breadth_before_narrowing.md
└── feedback_doubts_log_per_category.md
```

Read the project memory file at the start of any session to recover what's been decided and what's pending. **Update it as work progresses** — when decisions are made, when new constraints surface, when next-action changes, when files get added.

## What NOT to do

- Don't create new top-level `.md` files at the project root unless they're infra-handoff material. Research / Q&A / understanding goes in `docs/internal/` via the Q&A logging convention; append to existing files when possible.
- Don't modify `livekit-agents/` — it's a read-only reference clone.
- Don't introduce `pip` or `poetry` commands in `my-agent/` — use `uv`.
- Don't cite blog summaries as primary sources.
- Don't pre-filter the research landscape on hardware/language/latency unless the user has constrained.
- Don't recommend proprietary models as Sophia deployment candidates.
- Don't log Q&A while an answer is still in flight — wait until it has converged.
