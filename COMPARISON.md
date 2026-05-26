# Sophia Voice Agent — Cross-Category Master Comparison

**Created:** 2026-05-11 · **Sources:** `STT_models.md`, `TTS_models.md`, `STS_models.md` in this directory.

This is the navigation + synthesis layer. Use it to compare across categories and decide which combinations to actually benchmark in Phase 2. Open the individual category files for full per-model details and citations.

---

## 1. The architectural fork

Two viable pipelines for a voice agent (speech → answer → speech):

### A. Cascaded — STT → text-LLM (with RAG) → TTS
- **Pros:** mature; tool calling / RAG works natively at the LLM step; each stage is swappable and individually benchmarkable; the LLM doesn't need to "know" anything about audio.
- **Cons:** end-to-end latency floor ~600–1500 ms even with streaming; everything paralinguistic (emotion, prosody, laughter) is destroyed at the ASR text bottleneck; building true full-duplex / barge-in requires bolted-on VAD + interruption logic.
- **What to optimize:** pick the lowest-latency streaming STT + the lowest-TTFB streaming TTS, and a fast text LLM. RTT is roughly `STT first-token + LLM first-token + TTS first-byte`.

### B. End-to-end STS — single audio-LLM that takes speech in and emits speech out
- **Pros:** sub-300 ms end-to-end latency is achievable on consumer GPUs; preserves prosody/emotion; native full-duplex / barge-in in the strongest models (Moshi, Hertz-dev); fewer moving parts.
- **Cons:** most open STS models **don't support function calling / RAG** today — the major exception is **Step-Audio 2 mini** (Apache 2.0, native tool calling + multimodal RAG). Less swappable — you're committing to one model's voice, languages, and reasoning quality together.
- **What to optimize:** if you need RAG, pick Step-Audio 2 mini or a tool-capable audio LLM. Otherwise pick on latency + voice quality.

**Bottom line for your project:** if RAG is non-negotiable, lean cascaded — *unless* Step-Audio 2 mini's tool calling holds up in your testing.

---

## 2. License landscape (the gotcha)

A surprisingly large share of "popular" open models are **non-commercial only**. If commercial deployment is on the table, filter aggressively.

### Commercial-permissive (Apache 2.0 / MIT / CC-BY-4.0 / CC-BY-NC* with caveats)
**STT (Apache/MIT/CC-BY-4.0):** Granite-Speech-4.1-2B, Granite-Speech-3.3-8B/2B, Cohere Transcribe 03-2026, Parakeet TDT/RNNT (CC-BY-4.0), Canary family (CC-BY-4.0), Canary-Qwen-2.5B, Nemotron-Speech-Streaming, Phi-4-MM (MIT), Voxtral-Mini, Qwen3-ASR, Whisper large-v3 (Apache 2.0), Distil-Whisper (MIT), Moonshine (MIT), Kyutai STT (CC-BY-4.0), Paraformer-zh (Apache).

**TTS (Apache/MIT):** Kokoro-82M, MetaVoice-1B, Suno Bark, MyShell OpenVoice v2, GPT-SoVITS, Parler-TTS, Sesame CSM-1B, IndexTTS-1.5/2, Orpheus 3B, Zonos v0.1, CosyVoice 2, OuteTTS, Chatterbox (MIT), SpeechT5, Step-Audio-TTS-3B, PlayDiffusion.

**STS (Apache/MIT):** Moshi (CC-BY-4.0 weights), Step-Audio v1 / Step-Audio 2 mini (Apache), SpeechGPT 2.0-preview (Apache), Qwen2-Audio / Qwen2.5-Omni / Qwen3-Omni (Apache), Mini-Omni / Mini-Omni2 (MIT), Phi-4-MM (MIT), Ultravox (MIT), Hertz-dev (Apache), Baichuan-Audio (Apache), SALMONN (Apache), Kimi-Audio (MIT), Sesame CSM-1B (Apache).

### Non-commercial / research-only — avoid for production
- **STT:** SeamlessM4T-v2 (CC-BY-NC), MMS (CC-BY-NC), CrisperWhisper (CC-BY-NC).
- **TTS:** XTTS-v2 (CPML), F5-TTS (CC-BY-NC), E2-TTS (CC-BY-NC), Fish Speech 1.5 (CC-BY-NC-SA), ChatTTS (CC-BY-NC), MMS-TTS (CC-BY-NC), Spark-TTS (CC-BY-NC-SA — switched from Apache, watch out), MARS5-TTS (AGPL).
- **STS:** LLaMA-Omni / LLaMA-Omni2 (weights research-only), Meta Spirit-LM (FAIR Noncommercial), Audio-Flamingo 2 (NV-noncomm).

---

## 3. Top candidates per category (curated shortlist)

### STT — best of breed by goal

| Goal | Model | Why |
|---|---|---|
| Lowest WER (English) | **Granite-Speech-4.1-2B** (Apache 2.0) | Open-ASR mean WER 5.33, LibriSpeech clean 1.33. Released Apr 2026. |
| Lowest WER alt | Cohere Transcribe 03-2026 (Apache 2.0) | Mean WER 5.42, RTFx 525 (very fast). No timestamps/diarization. |
| Lowest-latency streaming | **Kyutai stt-1b-en_fr** (CC-BY-4.0) | 0.5 s streaming latency + semantic VAD built in — best-fit for voice agents. |
| Lowest-latency streaming alt | Nemotron-Speech-Streaming-EN-0.6B (NVIDIA OML) | Configurable 80 ms–1.12 s, March 2026. |
| Best multilingual | Qwen3-ASR-1.7B (Apache 2.0) | FLEURS avg 4.90 WER, 30 langs + 22 ZH dialects, robust to music. |
| Smallest commercial-fast | Parakeet-TDT-0.6B-v2 (CC-BY-4.0) | Mean WER 6.05, RTFx 3,386, streaming via TDT, 2.5 GB VRAM. |
| Edge / CPU | Moonshine-Base (MIT) | 61 M params, <500 MB, microcontroller-capable. |
| Word-level timestamps + diarization | Whisper large-v3 + WhisperX + Pyannote 3.1 | Standard stack; not lowest WER anymore but tooling is best. |

### TTS — best of breed by goal

| Goal | Model | Why |
|---|---|---|
| Lowest streaming TTFB + voice cloning + commercial | **Orpheus 3B** (Apache 2.0) | ~100–200 ms TTFB, native streaming, 8 voices + zero-shot clone, emotion tags. |
| Streaming + multilingual + commercial | **CosyVoice 2 0.5B** (Apache 2.0) | Bi-streaming 150 ms TTFB, 9 langs + 18 ZH dialects, instruction control. |
| Highest naturalness with permissive license | **Chatterbox** (MIT) | Resemble AI claims beats ElevenLabs in blind tests, 23 langs, emotion knob, MIT. |
| CPU-realtime / edge | **Kokoro-82M v1** (Apache 2.0) | 82 M, browser/WASM-capable, 8 langs, no cloning. |
| Highest naturalness (any license) | F5-TTS (CC-BY-NC) or IndexTTS-2 (Apache 2.0) | F5 wins on objective WER/SIM; IndexTTS-2 wins among commercial. |
| Description-prompt control | Parler-TTS Large v1 (Apache 2.0) | Natural-language voice/style description. No reference-audio cloning. |
| Highest sample rate + commercial | Zonos v0.1 (Apache 2.0) | Native 44 kHz, 5 langs, emotion controls. Linux-only. |
| Long-tail languages | MMS-TTS (CC-BY-NC) | 1,107 languages — unmatched coverage but NC license. |

### STS — best of breed by goal

| Goal | Model | Why |
|---|---|---|
| **Tool calling + RAG (closest to user's use case)** | **Step-Audio 2 mini** (Apache 2.0) | Only open end-to-end STS with native function calling + multimodal RAG. |
| Lowest latency, full-duplex | **Moshi** (CC-BY-4.0) | 200 ms E2E, native full-duplex, Inner Monologue trick. English only, no tools. |
| Lowest latency alt (base model) | Hertz-dev (Apache 2.0) | 120 ms on RTX 4090, full-duplex, but NO instruction tuning — you must fine-tune. |
| Streaming + bilingual EN+ZH | Qwen2.5-Omni-7B (Apache 2.0) | Thinker–Talker, runs on 24 GB consumer GPU. |
| Multilingual + tools, high-end HW | Qwen3-Omni 30B-A3B (Apache 2.0) | 18 speech-in / 10 speech-out langs, audio function calling. Needs 78+ GB VRAM. |
| Lowest latency, Chinese | SpeechGPT 2.0-preview (Apache 2.0) | <200 ms streaming, Chinese only. |

**Do NOT pick these as STS** (they're speech-in, text-out only — use them as the LLM in a cascade): Qwen2-Audio, Phi-4-Multimodal, Ultravox, SALMONN, Audio-Flamingo 2.

**Do NOT pick this as a chat model** (it's a TTS despite the name): Sesame CSM-1B.

---

## 4. Latency budget — cascaded vs end-to-end

Approximate end-to-end voice-in → voice-out latency on a single consumer GPU (RTX 4090-class). Real-world numbers will vary; these are vendor/paper claims to validate in Phase 2.

| Pipeline | E2E latency | Tool calling | Notes |
|---|---|---|---|
| Whisper large-v3 + text LLM + XTTS-v2 | 1500–2500 ms | Yes | Legacy baseline. Whisper isn't streaming. |
| Kyutai stt-1b + 7B LLM streaming + Orpheus 3B | ~600–900 ms | Yes | **Best cascaded latency w/ Apache stack.** |
| Nemotron Streaming + 7B LLM + CosyVoice 2 | ~500–800 ms | Yes | Multilingual cascade. |
| Phi-4-MM (audio-LLM) + CosyVoice 2 | ~400–700 ms | Yes | Single audio encoder + streaming TTS. |
| **Step-Audio 2 mini (end-to-end + RAG)** | streaming | **Yes** | Single model. Numbers not formally published. |
| Moshi (end-to-end full-duplex) | **200 ms** | **No** | English only. No tools. |
| Hertz-dev (end-to-end base) | **120 ms** | **No** | Needs fine-tune; experimental. |
| OpenAI GPT-4o Realtime (proprietary bar) | ~600 ms | Yes | Closed reference point. |

Phase 2 will replace these with measured numbers.

---

## 5. Suggested Phase 2 test matrix

Don't try to benchmark every model. Focus on these high-value combinations:

### A. Cascaded — best commercial latency
- **STT:** Kyutai stt-1b-en_fr (0.5 s + VAD) OR Nemotron Streaming
- **LLM:** local 7B–8B (e.g., Llama-3.1-8B-Instruct, Qwen2.5-7B-Instruct) with RAG
- **TTS:** Orpheus 3B (English) OR CosyVoice 2 (multilingual)

### B. Cascaded — best quality (latency secondary)
- **STT:** Granite-Speech-4.1-2B OR Cohere Transcribe 03-2026
- **LLM:** same as A
- **TTS:** IndexTTS-2 OR Chatterbox

### C. Cascaded — audio-LLM as combined STT+LLM
- **Audio-LLM:** Phi-4-Multimodal (MIT, function calling) OR Qwen2-Audio
- **TTS:** Orpheus 3B OR CosyVoice 2

### D. End-to-end STS — RAG-capable
- **Single model:** Step-Audio 2 mini (validate the tool-calling + RAG claims)

### E. End-to-end STS — ultra-low-latency, English, no tools
- **Single model:** Moshi (validate the 200 ms claim and conversational quality)

### F. End-to-end STS — multilingual, tool-capable, high-end HW
- **Single model:** Qwen2.5-Omni-7B (or Qwen3-Omni if you have H100-class hardware)

### Metrics to capture for every combination in Phase 2
1. **End-to-end latency** — wall clock from user-stops-speaking to first audio out
2. **First-token latency per stage** (cascaded only)
3. **Streaming smoothness** — gaps, glitches, mid-utterance pauses
4. **WER** on a fixed test set (validates STT)
5. **MOS / blind A/B** on TTS output (validates TTS)
6. **Task accuracy** on RAG-grounded questions (validates LLM + retrieval)
7. **Interruption / barge-in behavior** (full-duplex models vs cascade with VAD)
8. **VRAM and throughput** under load
9. **Cold start time** (matters for serverless)
10. **License-cleared for commercial?** (re-verify before shipping)

---

## 6. What's notable / surprising from the research

1. **Whisper large-v3 is no longer at the top** — it ranks 25th on the Open ASR Leaderboard. Top spots all go to 2025–2026 models combining Conformer encoders with LLM decoders.
2. **Apache 2.0 models now lead the STT WER frontier.** Granite-Speech-4.1-2B (5.33) and Cohere Transcribe 03-2026 (5.42) beat every CC-BY-NC option. This wasn't true 18 months ago.
3. **Kokoro-82M was trained for ~$1,000** and competes with billion-parameter TTS models. Counterintuitive cost/quality crown for canned voices.
4. **Most STS models can't do tool calling** — Moshi, GLM-4-Voice, Mini-Omni, LLaMA-Omni, Hertz-dev, SpeechGPT all lack it. Step-Audio 2 mini is currently the lone open end-to-end exception with native RAG.
5. **License-name traps to watch:** Sesame CSM is a TTS, not a chat model. Spark-TTS quietly switched from Apache to CC-BY-NC-SA. MARS5 is AGPL (hostile to closed-source product integration). XTTS-v2 is CPML — non-commercial despite "open" branding.
6. **Streaming is now a first-class STT concern.** Three real options: Kyutai stt-1b-en_fr, Nemotron-Speech-Streaming, Qwen3-ASR-via-vLLM. Whisper still has no native streaming.

---

## 7. Open questions for the user (Phase 2 scoping)

Before building the UI, the following decisions narrow the test matrix significantly. None block Phase 2 from starting, but answering them sharpens the focus:

- **Languages required at launch?** (English-only opens up Moshi, Orpheus; multilingual narrows to Qwen-Omni / CosyVoice / Chatterbox.)
- **Hardware target for the live demo?** (RTX 4090 / single A100 / H100 / Mac Silicon / CPU-only? Decides whether 30B+ models are in scope.)
- **Commercial deployment?** (If yes, drop the CC-BY-NC / research-only models from the matrix.)
- **Voice cloning needed, or pre-baked voices acceptable?** (Decides Kokoro vs Orpheus vs Chatterbox vs CosyVoice 2.)
- **Function-calling / RAG integration depth?** (If RAG is heavy, lean cascaded — or commit to Step-Audio 2 mini.)
- **Full-duplex interruption required?** (Only Moshi and Hertz-dev do this natively. Otherwise plan on VAD + interruption logic in the orchestration layer.)

---

## 8. Orchestration layer (Phase 2 scaffolding)

For the plug-and-play UI, consider building on top of an existing voice-agent framework rather than rolling your own pipeline plumbing:

- **LiveKit Agents** (Apache 2.0, https://github.com/livekit/agents) — WebRTC-based, plug-and-play STT/LLM/TTS providers, native VAD + turn detection + barge-in, also supports OpenAI realtime as an alternative path.
- **Pipecat** (BSD-2, https://github.com/pipecat-ai/pipecat) — Python frame-processor pipeline; many providers; supports realtime audio.
- **Vocode** (MIT, https://github.com/vocodedev/vocode-core) — Python + TypeScript; telephony-friendly.

Any of these will save weeks vs building the streaming WebRTC layer from scratch. They also abstract STT/TTS swaps behind a uniform interface, which is exactly the plug-and-play property you want.

---

## 9. Files in this directory

- `STT_models.md` — ~30 STT/ASR models with full per-model details, comparison table, sources.
- `TTS_models.md` — ~30 TTS models with full per-model details, comparison table, sources.
- `STS_models.md` — ~24 STS / audio-LLM models with full per-model details, comparison table, and a "Practical guidance" section.
- `COMPARISON.md` (this file) — cross-category synthesis and Phase 2 planning.

---

## Doubts & Answers (cross-category)

Cross-cutting questions that apply across STT/TTS/STS. Category-specific Q&A lives in the matching category file.

### Q1 (2026-05-11): I want to test models live, use their capabilities, and tweak APIs/parameters. Can I use LiveKit / Pipecat / Vocode for this? Which is best and how do I use them?

**Important clarification:** LiveKit, Pipecat, and Vocode are **orchestration frameworks**, not model evaluation tools. They wire STT + LLM + TTS into a full voice agent (with VAD, turn detection, barge-in) — they don't host models or expose model parameters. For evaluating individual models and tweaking their parameters, the right tools are different.

**Right tools for model evaluation + parameter tweaking:**

| Tool | What it gives | Cost | Best for |
|---|---|---|---|
| HF Spaces | Browser UI with author-exposed parameters | Free | First-listen, ear-test |
| **Replicate** | **REST API, most parameters exposed, no install** | **~$0.001–0.01 per call** | **Sweet spot for capability + parameter testing** |
| fal.ai | Same pattern as Replicate, often lower latency | Pay-per-call | Same use case |
| Modal | Custom Python wrapper on rented GPU | Free credits + pay-as-you-go | When Replicate/fal don't host the model |
| Colab notebooks | Full official repo code, every parameter, your data | Free T4 / Pro A100 | Exact repo code path needed |
| Local Gradio demo | Most repos ship `python app.py` with all knobs | Free, install pain | Pre-local-deploy testing |

**Recommendation:** **Replicate as the daily driver**, **Colab when Replicate doesn't host the model**. Covers ~90% of what you need.

**How to use Replicate:**
1. Sign up at https://replicate.com → free credits to start.
2. Find the model, e.g. https://replicate.com/canopylabs/orpheus-3b-0.1-ft
3. Use the in-browser UI: edit parameters, click Run, listen.
4. Script it:
   ```python
   import replicate
   output = replicate.run(
       "canopylabs/orpheus-3b-0.1-ft",
       input={"text": "Hello world <laugh>", "voice": "tara", "temperature": 0.6}
   )
   ```

**How to use Colab:** open the model repo's `notebooks/` folder or click "Open in Colab" in the README; Runtime → T4 GPU; upload your audio; run cells.

**How to use HF Spaces:** visit `https://huggingface.co/spaces/<author>/<model>` and use the Gradio UI. Limitation: only the parameters the Space author chose to expose.

**Concrete starting points for the shortlist:**

| Category | Model | Where to test now |
|---|---|---|
| STT | Parakeet TDT v2 | Replicate / HF Space `nvidia/parakeet-tdt-0.6b-v2` |
| STT | Kyutai stt | https://unmute.sh/ (live streaming) |
| STT | Qwen3-ASR | HF Space or chat.qwen.ai |
| TTS | Orpheus 3B | https://replicate.com/canopylabs/orpheus-3b-0.1-ft |
| TTS | CosyVoice 2 | Replicate or repo Colab |
| TTS | Kokoro-82M | https://huggingface.co/spaces/hexgrad/Kokoro-TTS |
| TTS | F5-TTS | https://huggingface.co/spaces/mrfakename/E2-F5-TTS |
| TTS | Chatterbox | https://huggingface.co/spaces/ResembleAI/Chatterbox |
| STS | Moshi | https://moshi.chat/ (live full-duplex) |
| STS | Qwen2.5/3-Omni | https://chat.qwen.ai/ voice mode |
| STS | Step-Audio 2 mini | HF Space `stepfun-ai/Step-Audio-2-mini` |

**When LiveKit/Pipecat come in:** **later** — after picking your 1–2 finalists per category. Then they let you wire the chosen STT + LLM + TTS into a working voice agent in ~30 lines of Python with VAD/barge-in already handled. That's when you measure end-to-end conversational latency, not just per-model latency.

**The path:**
```
Replicate / HF Spaces / Colab  →  Pick finalists  →  LiveKit Agents  →  Measure full pipeline
   (model evaluation)              (your choice)      (agent assembly)    (final benchmarks)
```

### Q2 (2026-05-11): So VAD / barge-in / interruption can't be tweaked from model APIs or parameters? After selecting models, am I basically building my own LiveKit, with these handled by my code?

**Yes — your mental model is correct.** VAD, turn detection, and barge-in are **orchestration concerns**, not model parameters, for almost all models. A few exceptions where some of this is baked in:

1. **Kyutai stt-1b-en_fr** — has **built-in semantic VAD** and emits end-of-turn signals; you don't need a separate VAD component for turn detection.
2. **Moshi (full-duplex STS)** — listens and speaks simultaneously; no turn-based VAD needed; barge-in intrinsic.
3. **Hertz-dev (full-duplex STS)** — same as Moshi, native full-duplex.

**Everything else** (Whisper, Parakeet, Canary, Granite, Cohere Transcribe, Orpheus, CosyVoice, Kokoro, …) is "blind" to VAD/barge-in — the model just transcribes or synthesizes. The orchestration layer must run a VAD upstream of STT, detect user-start-of-speech while TTS is playing, cancel in-flight TTS + LLM streams, and manage the listening/thinking/speaking/interrupted state machine.

**What a "homemade LiveKit" must implement:**
- Audio I/O (WebRTC or local mic/speaker)
- VAD (Silero VAD is the standard) — params: threshold, min_silence_duration_ms, speech_pad
- Turn detector (silence-based or semantic-model-based)
- STT client + LLM client + TTS client
- **Interruption controller**: on user-speech-start while TTS playing → cancel TTS playback + cancel in-flight LLM stream + flush partial text + start new STT
- State machine
- Streaming glue (async queues, backpressure between stages)

**Build-vs-buy take:**

| Goal | Right choice |
|---|---|
| Evaluate models plug-and-play, fast | **Use LiveKit Agents or Pipecat** — swap providers behind a uniform interface, get VAD/barge-in for free |
| Productionize non-standard UX (telephony, embedded, custom transport) | Build your own — you'll need the control |
| Learn end-to-end how voice agents work | Build once, then use a framework |

**Recommendation for Sophia's Phase 2:** use LiveKit Agents as the scaffold (Apache 2.0, plug-and-play for every shortlisted STT/TTS/STS, VAD + turn-detection + barge-in built in with tunable parameters). The "plug-and-play UI" is essentially what LiveKit's Playground (https://agents-playground.livekit.io/) already gives — fork their playground UI as the starting point. VAD threshold / interruption latency / turn-detection settings are still **your** knobs even when LiveKit owns the implementation — you're getting orchestration code as a library, not a black box.

### Q3 (2026-05-11): How do I use LiveKit Agents now?

**5-minute quickstart:**

**1. Install:**
```bash
pip install "livekit-agents[openai,silero,deepgram,cartesia,elevenlabs]"
```

**2. Get a LiveKit endpoint** — either https://cloud.livekit.io (free tier; grab `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`) or self-host with `livekit-server --dev`. Put credentials in a `.env`.

**3. Write `agent.py`:**
```python
from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai, silero, deepgram, cartesia

load_dotenv()

async def entrypoint(ctx: JobContext):
    await ctx.connect()
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(voice="sonic-english"),
    )
    agent = Agent(instructions="You are a helpful voice assistant. Be brief.")
    await session.start(agent=agent, room=ctx.room)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
```

**4. Run:** `python agent.py dev`

**5. Talk to it:** open https://agents-playground.livekit.io/, connect to your project, click the mic. Working voice agent with VAD + barge-in + interruption out of the box.

**Plug-and-play swaps (the part you care about):**

STT:
```python
stt=openai.STT(base_url="http://localhost:8000/v1",   # local Whisper/Parakeet via OpenAI-compat server
               model="Systran/faster-whisper-large-v3")
```
LLM:
```python
llm=openai.LLM(base_url="http://localhost:8001/v1",   # local Llama/Qwen via vLLM
               model="llama-3.1-8b-instruct")
```
TTS — first-party plugins for OpenAI, Cartesia, ElevenLabs. For **Orpheus / CosyVoice / Kokoro / Chatterbox** write a short custom plugin or hit a Replicate endpoint. LiveKit's plugin interface is small (https://docs.livekit.io/agents/build/).

**Tuning the orchestration knobs (the homemade-LiveKit equivalents):**
```python
session = AgentSession(
    vad=silero.VAD.load(
        min_speech_duration=0.1,
        min_silence_duration=0.5,
        prefix_padding_duration=0.5,
        threshold=0.5,
    ),
    allow_interruptions=True,
    min_interruption_duration=0.5,
    min_endpointing_delay=0.5,
    max_endpointing_delay=6.0,
)
```
Optional semantic turn detector (replaces silence-based turn detection with a small LLM):
```python
from livekit.plugins import turn_detector
session = AgentSession(turn_detection=turn_detector.MultilingualModel(), ...)
```

**Caveats:**
- First-party plugins cover OpenAI, Anthropic, Deepgram, Cartesia, ElevenLabs. For the open-source shortlist (Parakeet, Kyutai, Orpheus, CosyVoice) you'll need community or short custom plugins. Not hard, just not zero-effort.
- Cloud-provider latency ≠ local-model latency — when benchmarking, run the same model locally vs cloud to separate model latency from network.
- Playground is great for demos; for benchmarking, run LiveKit Agents headless and log every event.

**First-session order:**
1. Get the skeleton running with all-cloud providers (Deepgram + OpenAI + Cartesia) — confirms plumbing.
2. Talk to it in the Playground — feel VAD/barge-in.
3. Swap one provider at a time for OSS (easiest first swap: Orpheus TTS via Replicate).
4. Tune VAD params until interruption feels natural.
5. Add timing logs to measure end-to-end latency per turn.

### Q4 (2026-05-11): Where are the official docs / getting-started guides for LiveKit (and the alternatives)?

**LiveKit Agents (primary):**

| Resource | URL |
|---|---|
| Main docs hub | https://docs.livekit.io/agents/ |
| Quickstart (build a voice AI agent) | https://docs.livekit.io/agents/start/voice-ai/ |
| Concepts / build guide | https://docs.livekit.io/agents/build/ |
| STT integrations | https://docs.livekit.io/agents/integrations/stt/ |
| TTS integrations | https://docs.livekit.io/agents/integrations/tts/ |
| LLM integrations | https://docs.livekit.io/agents/integrations/llm/ |
| Realtime / end-to-end models | https://docs.livekit.io/agents/integrations/realtime/ |
| VAD & turn detection | https://docs.livekit.io/agents/build/turns/ |
| Examples (GitHub) | https://github.com/livekit/agents/tree/main/examples |
| Main repo | https://github.com/livekit/agents |
| Playground UI source (fork starting point) | https://github.com/livekit/agents-playground |
| Live Playground | https://agents-playground.livekit.io/ |
| LiveKit Cloud signup | https://cloud.livekit.io |
| Discord | https://livekit.io/discord |

The Quickstart includes `lk app create` (LiveKit CLI) which scaffolds a working project with `.env` template — even faster than copy-pasting.

**Pipecat (alternative):**

| Resource | URL |
|---|---|
| Main docs | https://docs.pipecat.ai/ |
| Quickstart | https://docs.pipecat.ai/getting-started/quickstart |
| Supported services (plugin list) | https://docs.pipecat.ai/server/services/supported-services |
| Examples | https://github.com/pipecat-ai/pipecat/tree/main/examples |
| Main repo | https://github.com/pipecat-ai/pipecat |

**Vocode (alternative):**

| Resource | URL |
|---|---|
| Main docs | https://docs.vocode.dev/ |
| Main repo | https://github.com/vocodedev/vocode-core |

**Doc-URL caveat:** these are accurate as of recent versions; framework docs reshuffle nav paths regularly. If a deep link 404s, go to the main docs hub and follow current sidebar.

**Pragmatic reading order for LiveKit:**
1. Quickstart — get the skeleton running
2. Integrations → STT / TTS / LLM — find plugin names for shortlist models
3. Build → Turns — VAD + turn-detection knobs
4. Examples on GitHub — copy from there rather than from scratch
5. Voice realtime API page — only if A/B testing against OpenAI Realtime / Gemini Live

### Q5 (2026-05-12): I ran the LiveKit starter (`lk agent init … --template agent-starter-python` → `uv sync` → `uv run src/agent.py download-files` → `uv run src/agent.py dev`). Output shows `[transformers] PyTorch was not found` plus `registered worker` lines. Is this an error?

**Not an error — the agent is running successfully.** Decoded output:

- `initializing process {"pid": …, "inference": true}` → worker spawned with in-process inference enabled
- `[transformers] PyTorch was not found …` → **warning**: the semantic turn detector needs PyTorch; without it, LiveKit falls back to silence-based turn detection. Agent still works
- `process initialized` + `HTTP server listening on :49795` → inference subsystem ready, local control server up
- `registered worker {url: wss://…livekit.cloud, region: US Central}` → **agent connected to LiveKit Cloud and is registered as a worker**, idle, waiting for a participant to join

**Next step — actually talk to it:**
1. Open https://agents-playground.livekit.io/
2. Click Connect (auto-detects same Cloud account, otherwise paste `LIVEKIT_URL` + sandbox token from Cloud dashboard)
3. Grant mic permission, click the mic icon, start talking
4. Terminal will start logging incoming audio, STT output, LLM responses, TTS playback

**Optional: enable the semantic turn detector**
```bash
uv add torch
uv run src/agent.py dev
```
Removes the PyTorch warning and loads LiveKit's smarter semantic end-of-thought detector instead of pure silence-based.

**Common follow-up issues:**

| Symptom | Likely cause |
|---|---|
| Playground says "no agent in room" | `agent_name` in code doesn't match Playground request — check `WorkerOptions(agent_name="my-agent")` |
| No audio | Browser denied mic access — check URL-bar permissions |
| Terminal silent when talking | VAD threshold too high — set `silero.VAD.load(threshold=0.4)` |

### Q6 (2026-05-12): Can I write my own plugin around a self-hosted open-source model on my GPU and use it inside `AgentSession`?

**Yes — custom plugins are the standard pattern.** Two routes:

**Important shift first:** The `my-agent` starter project uses **LiveKit Inference** (a hosted abstraction proxying to OpenAI / Cartesia / Deepgram). That doesn't support self-hosted GPU models. To use your own model, switch from Inference to the **plugin** path. Per `my-agent/README.md`: "If you choose to self-host, you'll need to also use model plugins instead of LiveKit Inference and will need to remove the LiveKit Cloud noise cancellation plugin."

**Route A: OpenAI-compatible server (zero custom code)** — works for ~70% of open-source models. If the model server speaks OpenAI's HTTP protocol (vLLM, Faster-Whisper-Server, llama.cpp `server`, LM Studio, Ollama, TGI), just use the existing `openai` plugin pointed at it:
```python
from livekit.plugins import openai, silero
session = AgentSession(
    vad=silero.VAD.load(),
    stt=openai.STT(base_url="http://localhost:8000/v1",
                   api_key="any", model="Systran/faster-whisper-large-v3"),
    llm=openai.LLM(base_url="http://localhost:8001/v1",
                   api_key="any", model="Qwen/Qwen2.5-7B-Instruct"),
)
```

**Route B: Subclass the abstract base class** — for models with non-OpenAI protocols (Orpheus over SNAC, CosyVoice bi-streaming, Kyutai WebSocket, Moshi, Chatterbox). Subclass `livekit.agents.tts.TTS` / `stt.STT` / `llm.LLM` / `vad.VAD`. Skeleton in conversation log; verify exact signatures with `lk docs search "custom <tts|stt> plugin"` since the API evolves. Drop into `src/plugins/<your_plugin>.py`, import in `src/agent.py`, slot into `AgentSession(...)` like any built-in. Orchestration (VAD, turn detection, barge-in, interruption) is unchanged.

**Per `my-agent/AGENTS.md`:**
- Use `uv add <pkg>` for deps (not pip).
- Verify current plugin-API signatures with `lk docs search "custom tts plugin"` / `lk docs get-page /agents/build/` (CLI v2.15.0+) or the LiveKit Docs MCP server — the project explicitly prefers this over guessing.
- Format with `uv run ruff format` and `uv run ruff check`.
- TDD: write tests in `tests/` for the plugin behavior, then iterate to pass — `uv run pytest`.

**Routing the Sophia shortlist:**

| Model | Route |
|---|---|
| Whisper / Parakeet (STT) | A via Faster-Whisper-Server or Triton |
| Kyutai stt-1b | B — custom WebSocket plugin |
| Qwen3-ASR | A via vLLM |
| 7B–8B text LLM | A via vLLM |
| Orpheus TTS | B — wrap FastAPI server (~50 lines) |
| CosyVoice 2 | B — wrap bi-streaming gRPC/HTTP |
| Kokoro-82M | B — small, straightforward |
| Chatterbox | B — wrap Python API |

**Suggested first iteration:** all-Inference agent talking → swap LLM via Route A (vLLM, easy win) → swap STT via Route A (Faster-Whisper-Server) → swap TTS via Route B (last, where most novelty lives).

### Q7 (2026-05-12): I want to understand LiveKit deeply — business model + realtime voice. Can we clone the repo and debug?

**Business model (3 lines):**
- Open-source core (Apache 2.0): SFU server (`livekit/livekit`, Go) + agents framework (`livekit/agents`, Python). Fully self-hostable.
- Paid hosted layer (LiveKit Cloud): managed global WebRTC, SIP trunks, agent observability, "LiveKit Inference" proxy.
- Same pattern as Vercel/Next.js, Supabase/Postgres.

**Repo cloned to `livekit-agents/`** in the working directory (depth-50 shallow clone). Most relevant repo for realtime voice is `livekit/agents` (not the SFU server).

**Repo map (key dirs only):**
```
livekit-agents/
├── livekit-agents/livekit/agents/
│   ├── voice/             ← Realtime voice pipeline ⭐
│   ├── stt/  tts/  llm/  vad.py   ← Base classes for custom plugins
│   ├── worker.py  job.py  cli/    ← Lifecycle, room joining, CLI
│   └── inference/         ← Hosted-Inference path (skip for self-hosted)
├── livekit-plugins/        ← 69 provider plugins
├── examples/              ← Runnable patterns
└── tests/
```

**Recommended reading order for the realtime voice pipeline:**

*Tier 1 — orientation (15 min):*
- `README.md`
- `examples/minimal_worker.py` (smallest possible voice agent)
- `examples/voice_agents/`

*Tier 2 — realtime pipeline (1–2 hrs) — the `voice/` directory IS the loop:*
1. `voice/agent_session.py` — `AgentSession` entry point. Trace `__init__` and `start()`.
2. `voice/agent_activity.py` — state machine (listening/thinking/speaking/interrupted).
3. `voice/audio_recognition.py` — STT side: audio → VAD → STT → transcripts.
4. `voice/turn.py` — turn-taking and endpointing.
5. `voice/endpointing.py` — endpoint utilities.
6. `voice/generation.py` — LLM → TTS streaming (the low-TTFB magic).
7. `voice/io.py` — audio I/O.

*Tier 3 — custom-plugin base classes (30 min):*
- `stt/stt.py`, `tts/tts.py`, `llm/llm.py`, `vad.py`

*Tier 4 — reference plugin reads (30 min):*
- `livekit-plugins/livekit-plugins-silero/` (VAD, small/clean)
- `livekit-plugins/livekit-plugins-openai/` (STT+LLM+TTS in one)
- `livekit-plugins/livekit-plugins-deepgram/` (streaming WebSocket STT — closest pattern to Kyutai stt-1b)
- `livekit-plugins/livekit-plugins-cartesia/` (streaming TTS over WebSocket — closest pattern to Orpheus/CosyVoice)

**Debug experiment to crystallize the loop:** set logging to DEBUG in `my-agent/src/agent.py`; add prints/breakpoints in `audio_recognition.py`, `turn.py`, `generation.py`; run `uv run src/agent.py dev`; talk via Playground; watch one utterance trace: audio frame → VAD → STT chunk → endpoint → LLM tokens → TTS chunks → audio out.

**Skip on first read:** `inference/` (only for hosted path), `avatar/`, `ivr/`, `recorder_io/`, `amd/`, `evals/`, `metrics/`, `telemetry/`, `beta/`.

**69 plugins available** — check `ls livekit-agents/livekit-plugins/` before writing custom code. Notable for shortlist: `livekit-plugins-fishaudio`, `livekit-plugins-baseten`, `livekit-plugins-fal`, etc. — possible existing wrappers for shortlist models.

---

### Q8 (2026-05-13): My plan is to write LiveKit plugins for each shortlist model, run them locally in `my-agent`, screen-record the agent, then delete the model and repeat — I don't have a GPU. Is this right?

**Architecture is right, execution plan is broken in one big way.** Most of the shortlist models will not run usefully on CPU. The whole point of benchmarking is to validate vendor latency/quality claims — and on CPU you'd mostly be measuring "my laptop is slow," not "this model is good."

#### What's right
- Custom plugin path is correct for self-hosted OSS models (skip LiveKit Inference for these tests).
- Swap-one-component-at-a-time in `AgentSession` is exactly the plug-and-play property.
- Screen recording is fine for qualitative "feel" (naturalness, barge-in, conversation flow).

#### What's wrong / risky

**1. Most shortlist models need a GPU. CPU won't approximate them — it'll invalidate them.**

| Category | CPU-realistic | Needs GPU |
|---|---|---|
| **STT** | Moonshine (designed for edge), Distil-Whisper-small, Whisper-tiny/base via Faster-Whisper int8 | Granite-Speech-4.1-2B, Kyutai stt-1b, Parakeet TDT (slow), Qwen3-ASR, Cohere Transcribe |
| **TTS** | **Kokoro-82M** (the only one designed for CPU realtime) | Orpheus 3B, CosyVoice 2, Chatterbox, IndexTTS-2, F5-TTS, Zonos |
| **STS** | **None.** All audio-LLMs are 7B+ params, won't be realtime on CPU and will OOM on most Macs. | Moshi, Step-Audio 2 mini, Qwen2.5-Omni, Hertz-dev, etc. |

So the "run locally, delete, repeat" loop only realistically works for ~3 models in the entire shortlist.

**2. Plugins don't need to talk to localhost.** A LiveKit plugin is streaming glue — it can point at a **Replicate / fal.ai / Modal / rented GPU** endpoint exactly the same way it points at `localhost:8000`. This is the unlock: keep the plug-and-play LiveKit setup AND test the actual models. See Q1 above — Replicate as daily driver was already the recommendation.

**3. Screen recording captures "feel" but misses the metrics §5 calls for.** Phase 2 needs: end-to-end latency, per-stage latency, WER, MOS, task accuracy, interruption behavior, VRAM/throughput. Those need **logged numbers** (LiveKit's built-in metrics + plugin-level timing logs), not just video.

#### The realistic execution paths

**Path A — Remote GPU via Replicate/fal (recommended primary).** Write LiveKit plugins that hit Replicate's REST API. ~$0.001–0.01 per call. Validates real latency (modulo ~50–150 ms network RTT — measurable and subtractable). Works for almost every shortlist model.

**Path B — Rent a GPU by the hour.** Modal / RunPod / Lambda Labs / Vast.ai. ~$0.30–2/hr for A10/A100. Spin up the model server, hit it from `agent.py` over the network, kill the instance after. Best for models Replicate doesn't host (Kyutai stt, Hertz-dev, niche STS).

**Path C — Local CPU subset only.** Run Kokoro + Moonshine + Distil-Whisper-small locally. Useful for the "edge/CPU tier" picks but cannot stand in for the SOTA tier.

**Path D — HF Spaces / public demos as smoke test.** Pure listening test, no plugin needed (Q1 table). No latency data, but free and instant.

**Recommended mix: A as primary + C for the CPU-friendly models + B for the gaps + D for first-listen.**

#### Hardware-gated mini-plans

| Mac spec | Suggested mix |
|---|---|
| M-series + 16 GB | Path A primary, Path C for Kokoro/Moonshine. MLX builds of some models (Whisper, Llama) give a Neural-Engine boost over pure CPU. |
| M-series + 32–64 GB | A + C above, plus you can locally run 7B text LLMs (via llama.cpp/MLX) for cascade tests. |
| Intel Mac | A almost exclusively. CPU inference will be painful. |

(Final mix depends on actual Mac spec — to be filled in when user reports it.)

---

### Q9 (2026-05-15): On the cascaded-vs-STS architecture comparison, what does "RAG integration: Native (LLM is text-in)" mean for cascaded, and what does "Needs native function-calling" mean for STS?

These two short cells in the comparison table compress a lot. Unpacked:

**Cascaded — "Native (LLM is text-in)"**

The middle stage is a standard text-in/text-out LLM (GPT, Claude, Llama, Mistral). RAG integrates trivially because the model's context window is just text:

```
user audio → STT → "What's our Q3 revenue?"   ← plain text
                          │
                          ▼
                   ┌─────────────┐
                   │ RAG retrieve│  ← text query → vector search → text chunks
                   └──────┬──────┘
                          │
            ┌─────────────▼─────────────┐
            │ LLM context window:        │
            │   system: ...              │
            │   user: "What's our Q3..." │
            │   <retrieved>: "Q3 revenue │  ← shoved into the prompt as text
            │     was $4.2M..."          │
            └─────────────┬─────────────┘
                          │
                          ▼
                "Q3 revenue was..."  → TTS → audio
```

Two ways to integrate, both work in any text LLM with no special training:
1. **Pre-retrieval (prompt injection)** — search docs first, prepend chunks to the prompt as plain text. Works with literally any text LLM, including legacy models.
2. **Tool calling** — LLM emits a `search_docs(query)` tool call, runtime executes it, returns text result, LLM continues. Most modern LLMs (GPT-4+, Claude, Llama 3.1+) support this natively.

Both are textbook RAG. The LLM doesn't need to know about RAG specifically — it just sees text in its context window.

**End-to-end STS — "Needs native function-calling"**

The middle stage is an audio-LLM (Moshi, Qwen2.5-Omni, Step-Audio 2, etc.) — audio in, audio out. The model is reasoning over audio tokens directly. There is no plain-text "context window" to inject into:

```
user audio → audio-LLM (Moshi / Qwen-Omni / Step-Audio) → audio out
                  │
                  │  ← where do you inject retrieved text?
                  │     There's no "shove text into the prompt" step
                  │     because the model wants audio context
                  ▼
           ??? RAG happens HOW ???
```

Three options, and most OSS STS models support **none** of them well:

| Option | What it needs | Reality |
|---|---|---|
| Inject retrieved text into context | Audio-LLM must accept mixed text+audio context | Some do (Qwen2.5-Omni), but quality varies and breaks the latency advantage |
| **Function/tool calling** | Audio-LLM must natively emit tool calls (`search_docs(query)`) and consume tool results, interleaved with audio generation | **Only Step-Audio 2 mini does this in OSS** |
| Pre-retrieval based on heuristics | Build a parallel text classifier that intercepts intent, retrieves, and prepends | Ugly hack; defeats end-to-end latency advantage; you've basically re-built a cascade |

**Why "native function-calling" specifically:** In a cascade, you can bolt RAG onto any text LLM with prompt engineering after the fact. In STS, the audio-LLM has to be **trained** to interleave tool calls into its audio generation stream — you can't add it post-hoc. If the model wasn't trained for it, you don't have RAG.

This is why the STT/TTS shortlists each have ~5 viable production picks, but the STS shortlist effectively has **one** for RAG-grounded use cases (Step-Audio 2 mini).

---

### Q10 (2026-05-15): What does "emit tool calls" actually mean for an LLM (text or audio)? And what counts as a "tool" — Python function calls or MCP server tools?

**Mechanically, "emit a tool call" means the LLM decides to produce structured output that says "I want to invoke this function with these arguments" instead of generating regular response tokens.**

Step-by-step for a text LLM (the standard case):

```
1. RUNTIME PRE-FLIGHT
   ──────────────────
   The runtime hands the LLM both the chat context AND a tool catalog:
   tools = [
     {
       "name": "search_docs",
       "description": "Search internal knowledge base",
       "parameters": {
         "type": "object",
         "properties": {"query": {"type": "string"}},
         "required": ["query"]
       }
     },
     ...
   ]
   This catalog is serialized into the LLM's context.

2. LLM DECIDES MID-GENERATION
   ───────────────────────────
   Generating its response, the LLM hits a moment where it needs
   information it doesn't have. Instead of producing more
   conversational tokens, it produces structured output:
   {
     "tool_call": {
       "name": "search_docs",
       "arguments": {"query": "Q3 revenue"}
     }
   }

3. RUNTIME INTERCEPTS
   ──────────────────
   The runtime parses this, looks up the actual implementation of
   search_docs (a Python function, an HTTP call, an MCP server, …),
   and executes it. It gets back text:
   "Q3 revenue was $4.2M, up 18% YoY..."

4. RESULT FED BACK
   ────────────────
   The runtime appends a tool-result message to the chat context and
   re-invokes the LLM. The LLM now sees its own tool call AND the
   result, and continues generating with that information available.

5. FINAL RESPONSE
   ───────────────
   "Our Q3 revenue was four point two million dollars, up about 18%."
```

This entire dance is called the **tool-use loop**, and it can iterate (LLM calls tool → sees result → calls another tool → …). LiveKit caps it at `max_tool_steps=3` per turn by default.

**For an audio LLM:** the concept is identical but the model's output stream is audio tokens. To support tool calling, the model must have been **trained** to seamlessly switch between audio-token generation and structured tool-call generation in the same output stream. This requires explicit multi-modal training data with interleaved audio + tool calls. Most OSS audio-LLMs were not trained this way; that's why "needs native function-calling" is a real gating constraint for STS+RAG (see Q9). Step-Audio 2 mini is the only OSS audio-LLM that was trained for this, currently.

**What counts as a "tool"** — it's a generic abstraction. From the LLM's perspective, a tool is just a name + description + parameter schema. The implementation behind it can be anything:

| Tool type | What it actually is | Where it lives |
|---|---|---|
| **Python function** | A regular function decorated with `@function_tool` (LiveKit) or registered with `client.tools` (Anthropic SDK) | In your agent code |
| **MCP server tool** | A tool exposed by an external MCP (Model Context Protocol) server over HTTP/stdio | Anywhere reachable — local process, remote server |
| **HTTP API wrapper** | A function that wraps a REST call to your backend | In your agent code |
| **Database query** | A function that runs a SQL/vector query | In your agent code |

In LiveKit Agents specifically (Q18 in `livekit_doubts.md`):
- `@function_tool` decorator wraps a Python method on the `Agent` subclass — auto-discovered via `find_function_tools(self)`
- `mcp_servers=[...]` on `Agent` or `AgentSession` adds external MCP tools
- Both flow into the same `Agent.tools` list
- The framework serializes them all to JSON schema and passes them to the LLM via the `tools=[...]` kwarg in `LLM.chat()`

So when the slide says "Audio-LLM must emit tool calls," it means: **for RAG to work in STS, the audio-LLM must be trained to produce structured `search_docs(query="…")` outputs interleaved with its audio stream, so the runtime can intercept, execute the search, return text results, and let the audio-LLM continue speaking with the retrieved knowledge in context.** Without that training, you have no clean way to ground STS responses in retrieved data.
