# Open-Source STS / Audio-LLM Models — Landscape Report (May 2026)

## Introduction

This report surveys the open-source landscape for speech-to-speech (STS) and end-to-end audio-LLM systems as of May 2026, written for a team building a voice agent (speech → RAG → TTS) who is evaluating whether to replace the explicit cascaded pipeline (STT → LLM → TTS) with a single end-to-end speech-to-speech model.

**Definitions used in this report:**

- **True end-to-end STS (speech-in / speech-out)**: Single model that consumes raw speech (or speech tokens) and emits raw speech (or speech tokens). Text may appear as an intermediate alignment signal (e.g., Moshi's "Inner Monologue"), but no external ASR or TTS module is required. Examples: Moshi, GLM-4-Voice, Mini-Omni/2, LLaMA-Omni/Omni2, SpeechGPT, Step-Audio 2, Baichuan-Audio, Hertz-dev, Qwen2.5-Omni, Qwen3-Omni, Kimi-Audio, SpeechGPT 2.0-preview, VITA-1.5.
- **Audio-input-only multimodal LLMs (speech in / text out)**: Audio understanding models that do not natively emit speech. Useful as the LLM stage of a cascade, not as a drop-in STS replacement. Examples: Qwen2-Audio, Phi-4-Multimodal, Ultravox, SALMONN, Audio-Flamingo 2.
- **Cascaded orchestration frameworks**: Glue code that runs ASR + LLM + TTS as a pipeline (with VAD, turn-detection, barge-in). Not models. Examples: LiveKit Agents, Pipecat, Vocode.
- **Voice-conversion / TTS-only**: Models like kNN-VC and OpenVoice that do voice conversion or speaker-cloning TTS but are not STS dialog systems and are excluded except where noted (Sesame CSM is included because it is marketed as a "conversational" speech model but is in fact a TTS-style audio decoder, not a chat model).

**Why end-to-end vs cascaded matters for this project:**

1. **Latency.** A cascade serializes ASR completion → LLM first token → TTS first audio. Even with streaming components, the floor is typically 600–1500 ms end-to-end. End-to-end models like Moshi (200 ms), Hertz-dev (~120 ms on RTX 4090), LLaMA-Omni (226 ms) and SpeechGPT 2.0-preview (<200 ms) operate in or near the human turn-taking window (~200 ms gap in natural conversation).
2. **Prosody / paralinguistics.** End-to-end models can attend to pitch, emotion, laughter, prosody, and produce expressive output that conditions on those signals; a cascade discards everything in the ASR text bottleneck. Moshi's Inner Monologue, Spirit-LM Expressive, GLM-4-Voice, and Qwen3-Omni explicitly preserve expressivity.
3. **Full-duplex / barge-in.** A cascade fundamentally turns-based unless you bolt on VAD + interruption logic. Moshi and Hertz-dev natively model two parallel audio streams (user + model) and can listen and speak simultaneously, handling overlap, backchannels and natural interruption.
4. **Tool use / RAG.** This is the critical weakness of current end-to-end STS for the user's RAG-driven agent use case: most STS-only models (Moshi, Mini-Omni, LLaMA-Omni, Hertz-dev, GLM-4-Voice, SpeechGPT) do **not** support function calling or structured tool output. Audio-LLMs that emit text (Qwen2.5-Omni, Qwen3-Omni, Phi-4-Multimodal, Step-Audio 2) do support tools but bring back cascade-like latency for the speech output side. Step-Audio 2 is one of the first end-to-end systems explicitly designed with tool calling + RAG built in.

The practical recommendation will be to weigh these trade-offs per model below.

---

## Kyutai Moshi (Moshiko / Moshika)

- **Org / release / license**: Kyutai (Paris). Public release September 11, 2024. Code on GitHub. Model weights under **CC-BY-4.0** (paper itself uses CC BY-NC-SA 4.0 — see paper PDF). Moshiko = male voice; Moshika = female voice.
- **Architecture & parameter count**: 7B-parameter Helium text transformer + RQ-Transformer hierarchical decoder + Mimi neural audio codec. Mimi runs at 12.5 Hz, 1.1 kbps, 8 RVQ codebooks (1 semantic VQ distilled from WavLM + 7 acoustic), 24 kHz audio. Total model emits 17 parallel streams per 80 ms frame: aligned text + Moshi's 8 audio codebooks + the user channel's 8 audio codebooks. The "Inner Monologue" trick predicts time-aligned text tokens **before** the audio tokens, hugely improving spoken-QA quality (NLL 3.75 → 2.77).
- **Modalities**: Speech-in + speech-out, with an internal text trace. No vision.
- **Latency**: **Theoretical 160 ms, practical 200 ms** end-to-end voice-in → voice-out. Below the ~230 ms natural-conversation turn-taking gap.
- **Quality / capability**: Mimi MUSHRA 81.0; ABX phonetic discriminability 8.1%. Spoken-QA LlaMA Questions 62.3%, Web Questions 26.6%. Streaming-derived ASR: 5.7% WER on LibriSpeech test-clean. Streaming TTS: 4.7% WER (beats VALL-E). MMLU on the underlying text Helium 49.7%, ARC 79.6.
- **Conversational features**: First open full-duplex real-time spoken LLM. Native parallel user/model streams allow simultaneous listen-and-speak, overlapping speech, interruptions, backchanneling.
- **Languages**: English only.
- **Hardware**: Bf16 weights ~16 GB; runs on a single consumer GPU (RTX 4090 / A100). Inference repo provides Rust, MLX (Apple Silicon), and PyTorch backends. Streaming is native.
- **Tool use / function calling**: **No.** Authors explicitly call it out as a limitation; designed for natural conversation, not task execution.
- **Official links**:
  - Model card: https://huggingface.co/kyutai/moshiko-pytorch-bf16
  - Repo: https://github.com/kyutai-labs/moshi
  - Paper: https://huggingface.co/papers/2410.00037 (arXiv 2410.00037), PDF: http://kyutai.org/Moshi.pdf
  - Demo: https://moshi.chat/
- **Known limitations** (from the authors): English only; single voice per model checkpoint; "limited abilities for complex tasks"; no tool use; "research only, not for professional use"; mid-range toxicity in safety benchmarks; domain biases from training data.

---

## Zhipu GLM-4-Voice

- **Org / release / license**: zai-org / Zhipu AI / Tsinghua THUDM. Released October 2024. Model weights and code on GitHub. License is the GLM-4 license (research-permitting, with commercial registration). Built on GLM-4-9B.
- **Architecture & parameter count**: 9B parameter LLM with a speech tokenizer derived from a supervised ASR encoder producing 12.5 Hz discrete tokens, and a CosyVoice-based flow-matching decoder for waveform reconstruction. End-to-end discrete speech-in → discrete speech-out via the LLM.
- **Modalities**: Speech-in + speech-out (Chinese and English), with optional text input/output.
- **Latency**: Streaming. Public demo shows sub-second response. No headline e2e number in the model card; the GLM-4-Voice GitHub README quotes streaming chunk-size latency under 1 second.
- **Quality / capability**: Strong Chinese spoken-QA and English spoken-QA scores reported by the team; supports emotion / intonation / speech-rate / dialect control via prompts.
- **Conversational features**: Streaming generation, emotion / prosody / dialect control. No native full-duplex (turn-based).
- **Languages**: Chinese + English (bilingual).
- **Hardware**: 9B in bf16 ≈ 18 GB; runs on a single 24 GB consumer GPU (RTX 4090) or A100.
- **Tool use**: Not supported as a first-class feature.
- **Official links**:
  - Model card: https://huggingface.co/THUDM/glm-4-voice-9b
  - Repo: https://github.com/THUDM/GLM-4-Voice
- **Known limitations**: Turn-based (no full-duplex), English quality lags Chinese, no tool calling, GLM license terms restrict some commercial uses.

---

## ICT/CAS LLaMA-Omni

- **Org / release / license**: ICT, Chinese Academy of Sciences (NLP group). Paper Sept 10, 2024 (arXiv 2409.06666). **Code Apache-2.0, model weights academic-research-only** (contact fengyang@ict.ac.cn for commercial).
- **Architecture & parameter count**: Llama-3.1-8B-Instruct backbone + speech encoder + speech adaptor + streaming HiFi-GAN-like vocoder. End-to-end speech-in → text+speech-out (simultaneous).
- **Modalities**: Speech-in + (text and speech)-out.
- **Latency**: **226 ms** speech-in → first-audio-out, as reported by authors.
- **Quality / capability**: Trained on ~200K speech instructions; competitive spoken-instruction-following.
- **Conversational features**: Simultaneous text + speech streaming; not full-duplex; no native barge-in.
- **Languages**: Primarily English (some Spanish/French/Italian from base data).
- **Hardware**: 8B bf16 ≈ 16 GB; trained on 4 GPUs in <3 days; inference runs on a single 24 GB GPU.
- **Tool use**: Not mentioned / not supported.
- **Official links**:
  - Model: https://huggingface.co/ICTNLP/Llama-3.1-8B-Omni
  - Repo: https://github.com/ictnlp/LLaMA-Omni
  - Paper: https://arxiv.org/abs/2409.06666
- **Known limitations**: Non-commercial weights; Gradio streaming has stability issues; English-centric; no tool calling.

---

## ICT/CAS LLaMA-Omni2

- **Org / release / license**: Same team as LLaMA-Omni. Paper arXiv 2505.02625, May 5, 2025, ACL 2025 main. Code Apache-2.0; **model weights academic-research-only** (same restriction as v1).
- **Architecture & parameter count**: Qwen2.5-Instruct backbones (0.5B / 1.5B / 3B / 7B / 14B / 32B). Speech encoder = Whisper-large-v3; speech decoder = CosyVoice 2 streaming flow-matching + vocoder. Streaming autoregressive speech decoder.
- **Modalities**: Speech-in + (text and speech)-out simultaneous.
- **Latency**: Real-time / streaming, designed for spoken chatbot; per-model numbers not publicly headlined but the design target is < ~300 ms.
- **Quality / capability**: Multi-turn speech-to-speech conversation; better spoken-QA than LLaMA-Omni v1 in their paper.
- **Conversational features**: Multi-turn S2S, streaming, no full-duplex.
- **Languages**: English-only and bilingual (Chinese + English) variants (e.g., LLaMA-Omni2-7B-Bilingual).
- **Hardware**: 7B bf16 ≈ 14 GB; runs on 24 GB consumer GPU.
- **Tool use**: Not stated.
- **Official links**:
  - Model collection: https://huggingface.co/collections/ICTNLP/llama-omni-67fdfb852c60470175e36e9c
  - 7B Bilingual card: https://huggingface.co/ICTNLP/LLaMA-Omni2-7B-Bilingual
  - Repo: https://github.com/ictnlp/LLaMA-Omni2
  - Dataset: https://huggingface.co/datasets/ICTNLP/Multiturn-Speech-Conversations
- **Known limitations**: Same academic-only weight license; no inference providers; bilingual is the upper limit (no broader multilingual).

---

## Tsinghua Mini-Omni

- **Org / release / license**: gpt-omni (Tsinghua). Paper August 29, 2024 (arXiv 2408.16725). **MIT** license.
- **Architecture & parameter count**: Qwen2-0.5B backbone, Whisper audio encoder, SNAC audio decoder, litGPT training; CosyVoice-style synthesis. ~0.5B params.
- **Modalities**: Speech-in + (speech and text)-out, simultaneous "talking while thinking" stream.
- **Latency**: Streaming; Gradio demo has perceived latency from autoplay quirks, not from the model.
- **Quality / capability**: Modest given the 0.5B scale; mainly a research demonstration of efficient end-to-end speech dialog.
- **Conversational features**: Real-time streaming; no full-duplex; no barge-in.
- **Languages**: English only on the output side.
- **Hardware**: Tiny — runs on a single ~8 GB GPU or even CPU.
- **Tool use**: No.
- **Official links**:
  - Model: https://huggingface.co/gpt-omni/mini-omni
  - Repo: https://github.com/gpt-omni/mini-omni
  - Paper: https://arxiv.org/abs/2408.16725
- **Known limitations**: Small base LLM hurts factuality and reasoning; English-only output.

---

## Tsinghua Mini-Omni2

- **Org / release / license**: gpt-omni. Paper Oct 15, 2024 (arXiv 2410.11190). **MIT**.
- **Architecture & parameter count**: Qwen2 LLM backbone + Whisper audio encoder + CLIP image encoder + SNAC audio decoder.
- **Modalities**: Image + audio + text → speech + text. Any-to-any small omni model.
- **Latency**: Not officially benchmarked; streaming.
- **Quality / capability**: Demonstration-scale; useful for prototyping any-to-any open models.
- **Conversational features**: Authors describe an interruption mechanism but label it ToDo in the repo.
- **Languages**: Whisper-side input multilingual; output English-only.
- **Hardware**: Small footprint; consumer GPU friendly.
- **Tool use**: No.
- **Official links**:
  - Model: https://huggingface.co/gpt-omni/mini-omni2
  - Repo: https://github.com/gpt-omni/mini-omni2
  - Paper: https://arxiv.org/abs/2410.11190
- **Known limitations**: Interrupt mechanism not fully shipped; English-only output; small-scale.

---

## Fudan SpeechGPT (v1)

- **Org / release / license**: Fudan NLP (OpenMOSS / 0nutation). Paper May 18, 2023 (arXiv 2305.11000). License unstated on HF card; code on GitHub under permissive terms.
- **Architecture & parameter count**: LLaMA-7B backbone, mHuBERT speech-to-unit encoder, HiFi-GAN unit vocoder. ~7B params. Three training stages: modality-adaptation pre-training, cross-modal instruction finetuning, chain-of-modality finetuning (LoRA).
- **Modalities**: Speech-in + text + speech-out; cross-modal instruction following.
- **Latency**: Not real-time; mostly a research artifact.
- **Quality / capability**: Pioneer system. Speech recognition and task-following are documented by the authors as not optimal.
- **Conversational features**: Multi-turn dialog supported via instruction-tuning stage.
- **Languages**: English; speech units come from mHuBERT trained on EN/ES/FR/IT.
- **Hardware**: 7B FP16 fits on 24 GB GPU.
- **Tool use**: No.
- **Official links**:
  - Model: https://huggingface.co/fnlp/SpeechGPT-7B-cm
  - Repo: https://github.com/0nutation/SpeechGPT
  - Paper: https://arxiv.org/abs/2305.11000
- **Known limitations** (authors' words): "Due to limited training data and resources, the performance of the open-source SpeechGPT is currently not optimal."

---

## Fudan SpeechGPT-Gen

- **Org / release / license**: Fudan / OpenMOSS. Companion model to SpeechGPT, focused on chain-of-information generation (decouples semantic and perceptual modeling). Code and partial weights on GitHub.
- **Architecture & parameter count**: 8B speech LLM with explicit semantic-to-perceptual chain; trained on 60K hours.
- **Modalities**: Speech-in + speech-out (and TTS / VC).
- **Quality / capability**: Improved naturalness over SpeechGPT v1; primarily a research stepping stone toward 2.0.
- **Languages**: English.
- **Tool use**: No.
- **Official link**: Project page on https://github.com/0nutation/SpeechGPT (SpeechGPT-Gen subdirectory) and paper search "SpeechGPT-Gen Scaling Chain-of-Information Speech Generation."
- **Note**: Listed for completeness; for production work, prefer SpeechGPT 2.0-preview below.

---

## Fudan SpeechGPT 2.0-preview

- **Org / release / license**: OpenMOSS (Fudan). Released 2025. **Apache 2.0**.
- **Architecture & parameter count**: 7B LLM (Qwen2.5-7B-Instruct backbone) + dedicated ultra-low-bitrate streaming codec (SpeechGPT-2.0-preview-Codec, 750 bps, 75 tokens/sec). "Codec Patchify" aggregates adjacent RVQ codec tokens into patches mapped to unified vectors; multiple LM heads autoregressively predict speech.
- **Modalities**: Speech (24 kHz) + text in, speech + text out.
- **Latency**: **<200 ms** real-time response latency, streaming I/O.
- **Quality / capability**: Multi-emotion, multi-style, multi-tone, role-play with character voices; natural real-time interruptions claimed.
- **Conversational features**: Real-time interruption interactions; streaming.
- **Languages**: **Chinese only** at preview.
- **Hardware**: 7B bf16 ≈ 14 GB; consumer GPU.
- **Tool use**: Not stated.
- **Official links**:
  - Codec card: https://huggingface.co/fnlp/SpeechGPT-2.0-preview-Codec
  - LLM card: https://huggingface.co/fnlp/SpeechGPT-2.0-preview-7B
  - Repo: https://github.com/OpenMOSS/SpeechGPT-2.0-preview
  - Demo: https://sp2.open-moss.com/
- **Known limitations**: Chinese only; preview-quality model; no English support.

---

## StepFun Step-Audio (v1)

- **Org / release / license**: StepFun. Released early 2025. **Apache 2.0**. Component on HF: Step-Audio-Chat plus separate Step-Audio-TTS-3B and Step-Audio-Tokenizer.
- **Architecture & parameter count**: Step-Audio-Chat is a **130B-parameter** multimodal LLM with audio understanding + generation, integrating ASR, dialog management, voice cloning, and TTS via dual-codebook design.
- **Modalities**: Audio + text → text (Step-Audio-Chat) and separately text → speech via Step-Audio-TTS-3B; orchestrated together they constitute a speech-in → speech-out pipeline.
- **Latency**: Not headlined; 130B at bf16 needs ≥260 GB so real-time on a single GPU is infeasible without sharding.
- **Quality / capability**: HSK-6 (Chinese) proficiency, RAP / singing instruction following.
- **Languages**: Multilingual, Chinese strength.
- **Hardware**: Multi-GPU server class.
- **Tool use**: Some demoed.
- **Official links**:
  - Model: https://huggingface.co/stepfun-ai/Step-Audio-Chat
  - TTS-3B: https://huggingface.co/stepfun-ai/Step-Audio-TTS-3B
  - Repo: https://github.com/stepfun-ai/Step-Audio
- **Known limitations**: Massive size makes on-prem real-time hard; documentation thin on latency.

---

## StepFun Step-Audio 2 (Step-Audio-2-mini)

- **Org / release / license**: StepFun. Paper arXiv 2507.16632, July 22, 2025. **Apache 2.0**.
- **Architecture & parameter count**: End-to-end multimodal LLM. Mini variant; base variant also released.
- **Modalities**: Audio in → text and speech out.
- **Latency**: Streaming; specific number not published. Tool-calling-friendly inference path.
- **Quality / capability**: ASR average WER 3.50 EN, CER 3.19 ZH; Cantonese CER 8.32 on Common Voice yue; FLEURS Japanese 4.67 CER; Arabic WER 16.46. URO-Bench speech-to-speech 86.08 ZH / 78.46 EN.
- **Conversational features**: Natural speech conversation, tool calling, multimodal RAG, speech timbre switching via retrieved speech samples.
- **Languages**: English, Chinese, Cantonese, Japanese, Arabic + Chinese dialects.
- **Hardware**: Python ≥3.10, PyTorch ≥2.3-cu121; mini variant is consumer-GPU friendly.
- **Tool use**: **Yes — supports tool calling** (audio-search, date/time, weather, web-search demos). Native multimodal RAG.
- **Official links**:
  - Mini: https://huggingface.co/stepfun-ai/Step-Audio-2-mini
  - Mini Base: https://huggingface.co/stepfun-ai/Step-Audio-2-mini-Base
  - Repo: https://github.com/stepfun-ai/Step-Audio2
  - Homepage: https://www.stepfun.com/docs/en/step-audio2
  - Paper: arXiv 2507.16632
- **Known limitations**: Arabic / low-resource performance noticeably weaker; size/latency numbers not formally published.
- **Note for the user**: This is currently one of the few open end-to-end STS systems with native tool calling and RAG, making it the strongest candidate to consider as a true STS replacement for the cascade.

---

## Meta Spirit-LM

- **Org / release / license**: Meta AI (FAIR). Paper arXiv 2402.05755 (HTML at https://arxiv.org/html/2402.05755). Code + weights at https://github.com/facebookresearch/spiritlm under FAIR Noncommercial Research License (research-only).
- **Architecture & parameter count**: **7B** pretrained text LLM (LLaMA-2-7B family) continuously trained on interleaved text + speech tokens. Two variants:
  - **Spirit-LM Base**: HuBERT phonetic units interleaved with BPE text.
  - **Spirit-LM Expressive**: HuBERT phonetic + pitch + style units, preserving expressivity (emotion, prosody).
- **Modalities**: Text and speech freely mixed in a single stream (any-to-any text↔speech).
- **Latency**: Not real-time-optimized; offline / batch oriented.
- **Quality / capability**: Demonstrates cross-modal few-shot for ASR, TTS, and Speech Classification; preserves expressivity (Expressive variant).
- **Languages**: English only.
- **Hardware**: 7B FP16 → 14 GB; single 24 GB GPU.
- **Tool use**: No.
- **Official links**:
  - Repo: https://github.com/facebookresearch/spiritlm
  - Paper: https://arxiv.org/abs/2402.05755
  - Samples: https://speechbot.github.io/spiritlm
- **Known limitations**: Non-commercial license; English only; not streaming / not a real-time chat model.

---

## Alibaba Qwen2-Audio

- **Org / release / license**: Alibaba Qwen team. Technical report July 15, 2024 (arXiv 2407.10759). **Apache 2.0**.
- **Architecture & parameter count**: 7B model; audio encoder + Qwen2-7B LLM. Speech-in → **text-out** only.
- **Modalities**: Audio + text → text. **NOT full STS — flag this clearly: speech-out is not native.**
- **Latency**: Not real-time speech-out; suitable as the LLM in a cascaded STT-replacement (where the audio encoder is the STT) feeding a TTS.
- **Quality / capability**: Two modes: Voice Chat (instructions delivered as audio) and Audio Analysis. Strong audio QA and ASR.
- **Languages**: English primary; Chinese strong; multilingual ASR.
- **Hardware**: 7B bf16 ≈ 14 GB on a single 24 GB GPU.
- **Tool use**: Yes via chat template (function calling possible since underlying Qwen2 supports it).
- **Official links**:
  - Model: https://huggingface.co/Qwen/Qwen2-Audio-7B-Instruct
  - Repo: https://github.com/QwenLM/Qwen2-Audio
  - Blog: https://qwenlm.github.io/blog/qwen2-audio/
  - Report: https://arxiv.org/abs/2407.10759
- **Known limitations**: No speech generation; therefore NOT an STS model on its own.

---

## Alibaba Qwen2.5-Omni

- **Org / release / license**: Alibaba Qwen. Paper arXiv 2503.20215, March 26, 2025. **Apache 2.0**.
- **Architecture & parameter count**: **Thinker–Talker architecture** with TMRoPE (Time-aligned Multimodal RoPE). 3B and 7B variants. End-to-end multimodal with native speech output via the Talker.
- **Modalities**: Text + image + audio + video → text + streaming speech.
- **Latency**: Real-time voice + video chat with streaming audio output; specific first-audio-token figures not published, but the architecture is streaming.
- **Quality / capability**: Multilingual ASR on Common Voice / Fleurs / Wenetspeech; multiple speakers (Chelsie, Ethan).
- **Conversational features**: Real-time voice + video chat, streaming.
- **Languages**: EN, Mandarin, Cantonese, French, and others.
- **Hardware**: 7B bf16 ~31 GB for 15 s video processing — high-end GPU territory. 3B fits more comfortably on consumer hardware.
- **Tool use**: Function calling not headlined (the system-prompt-driven workflow is the primary control surface). For RAG, integrate at the LLM-prompt layer.
- **Official links**:
  - Model card: https://huggingface.co/Qwen/Qwen2.5-Omni-7B
  - Paper: https://arxiv.org/abs/2503.20215
  - Chat: https://chat.qwen.ai/
- **Known limitations**: Requires a specific system prompt to enable audio output; talker can be disabled to save ~2 GB at cost of audio out; FlashAttention2 needed for speed; needs ffmpeg.

---

## Alibaba Qwen3-Omni

- **Org / release / license**: Alibaba Qwen. Released late 2025 (model collection updated Dec 2025). **Apache 2.0**.
- **Architecture & parameter count**: **MoE Thinker–Talker** with AuT pretraining and multi-codebook design. 30B-A3B MoE (35B total params, ~3B active). Variants for Instruct and other use cases.
- **Modalities**: Text + image + audio + video → text + natural speech.
- **Latency**: Designed for "low-latency streaming with natural turn-taking"; specific ms numbers not published.
- **Quality / capability**: 119 text languages; 18 speech input languages; 10 speech output languages; multiple speakers (Ethan, Chelsie, Aiden).
- **Conversational features**: Streaming, natural turn-taking, function calling via audio input.
- **Languages**: Speech in: EN, ZH, KO, JA, DE, RU, IT, FR, ES, PT, MS, NL, ID, TR, VI, Cantonese, AR, UR. Speech out: EN, ZH, FR, DE, RU, IT, ES, PT, JA, KO.
- **Hardware**: 78+ GB minimum VRAM for 15 s video; H100 / multi-GPU territory.
- **Tool use**: **Yes — audio-driven function calling** for agent-like behaviors.
- **Official links**:
  - Model: https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct
  - Repo: https://github.com/QwenLM/Qwen3-Omni
  - Tech report PDF: https://github.com/QwenLM/Qwen3-Omni/blob/main/assets/Qwen3_Omni.pdf
- **Known limitations**: Batch inference doesn't support audio output (must `return_audio=False`); vLLM only supports the Thinker; `use_audio_in_video` must be consistent across turns; heavy VRAM requirements.

---

## Microsoft Phi-4-Multimodal

- **Org / release / license**: Microsoft. Released February 2025. **MIT**.
- **Architecture & parameter count**: 5.6B params; Phi-4-Mini-Instruct backbone + vision + audio adapters. 128K context.
- **Modalities**: Text + vision + audio → **text only**. **FLAG: not full speech-out end-to-end**; for STS use you must pair it with a TTS.
- **Latency**: ASR RTFX 151 on OpenASR; vLLM supported.
- **Quality / capability**: #1 on Hugging Face OpenASR leaderboard at release (WER 6.14%); surpasses Whisper-v3 on multiple benchmarks; speech translation beats SeamlessM4T-v2-Large; MMMU 55.1, MMBench-en 86.7, DocVQA 93.2.
- **Conversational features**: Multi-turn chat via chat template.
- **Languages**: Text 23 languages; vision EN; audio EN, ZH, DE, FR, IT, JA, ES, PT.
- **Hardware**: Recommended A100 / A6000 / H100; runs on lesser hardware with `eager` attention.
- **Tool use**: **Yes — function calling supported**, tool-enabled chat format.
- **Official links**:
  - Model: https://huggingface.co/microsoft/Phi-4-multimodal-instruct
  - Report: https://arxiv.org/abs/2503.01743
  - Portal: https://aka.ms/phi-4-multimodal/azure
- **Known limitations**: Non-English text and non-American-English speech accents are weaker; 40 s audio recommended max (30 min for summarization); Speech-QA gap vs GPT-4o / Gemini 1.5 Flash; primary use is audio understanding, not audio generation.

---

## Fixie.ai Ultravox

- **Org / release / license**: Fixie.ai. v0.5 line (Llama-3.3-70B and Llama-3.1-8B variants). **MIT** license. Released through 2024 with iterative versions through 2025.
- **Architecture & parameter count**: Llama-3.3-70B (frozen) backbone + Whisper-large-v3-turbo audio encoder (fine-tuned) + multimodal adapter trained via knowledge distillation. Adapter ~0.7B over a 70B base. Smaller 8B variant also available.
- **Modalities**: Speech + text → text. **FLAG: not full speech-out** (their roadmap mentions audio token generation for future versions).
- **Latency**: Adapter design is intentionally lightweight; suitable for sub-second cascaded voice agents when paired with a TTS.
- **Quality / capability**: BigBench Audio 82.70; covost2 translation BLEU EN→DE 34.53, ES→EN 43.29, ZH→EN 21.37.
- **Conversational features**: Multi-turn, system prompts, voice-agent oriented.
- **Languages**: 42 languages for translation tasks.
- **Hardware**: 70B base needs serious hardware (≥80 GB) or quantized inference; 8B variant fits on a 24 GB GPU.
- **Tool use**: Not explicitly mentioned, but inherits Llama-3.3 function-calling capabilities through chat templates.
- **Official links**:
  - 70B model: https://huggingface.co/fixie-ai/ultravox-v0_5-llama-3_3-70b
  - Site: https://ultravox.ai
  - Repo: https://github.com/fixie-ai/ultravox
- **Known limitations**: Text-output only; no preference tuning; future revisions planned for audio output.

---

## Standard Intelligence Hertz-dev

- **Org / release / license**: Standard Intelligence (si.inc). **Apache 2.0**.
- **Architecture & parameter count**: 8.5B transformer-based audio model trained on 20 million hours of audio. Full-duplex base model.
- **Modalities**: Audio-to-audio. Base model (no instruction tuning / RLHF).
- **Latency**: **Theoretical 80 ms; practical 120 ms on a single RTX 4090.** 1.5–2× lower than the previous SOTA at release.
- **Quality / capability**: Human-like pauses, emotional inflections; designed as a foundation for downstream fine-tuning.
- **Conversational features**: Full-duplex (mono and full-duplex generation).
- **Languages**: Not specified; primarily English-trained data.
- **Hardware**: Single RTX 4090 demonstrated; flash-attention required; limited Windows support.
- **Tool use**: No.
- **Official links**:
  - HF: https://huggingface.co/si-pbc/hertz-dev
  - Blog: https://si.inc/hertz-dev/
  - Repo: https://github.com/Standard-Intelligence/hertz-dev
- **Known limitations**: It is a base model — no instruction-following or RLHF; you must fine-tune it for usable chat behavior; experimental client/server scripts; Windows largely unsupported.

---

## VITA-1.5

- **Org / release / license**: VITA-MLLM. Released January 3, 2025. License per repo (research-permitting). 8B parameters.
- **Architecture & parameter count**: 8B; vita-Qwen2 family; real-time vision + speech interaction; bf16.
- **Modalities**: Video + text + speech → text and speech.
- **Latency**: Targets GPT-4o-level real-time vision+speech interaction.
- **Quality / capability**: Paper "VITA-1.5: Towards GPT-4o Level Real-Time Vision and Speech Interaction" (arXiv 2501.01957).
- **Conversational features**: Real-time vision+speech.
- **Languages**: Not fully detailed on the card; Chinese + English emphasized.
- **Hardware**: 8B bf16 fits on 24 GB GPU.
- **Tool use**: Not detailed.
- **Official links**:
  - Model: https://huggingface.co/VITA-MLLM/VITA-1.5
  - Paper: https://huggingface.co/papers/2501.01957
  - Repo: https://github.com/VITA-MLLM/VITA
- **Known limitations**: License and language/perf details thin on the model card; refer to paper.

---

## Baichuan-Audio

- **Org / release / license**: Baichuan AI. Tech report arXiv 2502.17239, February 24, 2025. **Apache 2.0**.
- **Architecture & parameter count**: 10B params. Pipeline: Baichuan-Audio Tokenizer (Whisper-Large encoder + 8-layer RVQ at 12.5 Hz) → Audio LLM (interleaved text+audio tokens; backbone Qwen2.5-7B) → flow-matching decoder → HiFi-GAN vocoder (24 kHz output).
- **Modalities**: Speech + text in, speech + text out, interleaved.
- **Latency**: Not explicitly published; streaming-friendly tokenizer.
- **Quality / capability**: OpenAudioBench 2,701 evaluation points across ASR, QA, reasoning, logical understanding. Trained on 393K hours INTLV + 142K hours ITTS data.
- **Languages**: Multilingual emphasized; Chinese strong.
- **Hardware**: 10B class; single high-end consumer GPU borderline.
- **Tool use**: Not mentioned.
- **Official links**:
  - Model: https://huggingface.co/baichuan-inc/Baichuan-Audio-Instruct
  - Base: https://huggingface.co/baichuan-inc/Baichuan-Audio-Base
  - Dataset: https://huggingface.co/datasets/baichuan-inc/openAudioBench
  - Repo: https://github.com/baichuan-inc/Baichuan-Audio
  - Paper: arXiv 2502.17239
- **Known limitations**: Latency / hardware specs not published; data composition opaque.

---

## SALMONN

- **Org / release / license**: Tsinghua-EE (with ByteDance). v1 October 2023, 7B Nov 2023. **Apache 2.0**.
- **Architecture & parameter count**: Whisper-Large-v2 speech encoder + BEATs audio encoder + window-level Q-Former + Vicuna 13B (or 7B) + LoRA. 13B / 7B params.
- **Modalities**: Speech + audio + music → **text only**. **NOT speech-out.**
- **Latency**: Not real-time; offline reasoning.
- **Quality / capability**: ASR, audio captioning, speech translation, music captioning, speech-audio co-reasoning, emergent spoken instruction following.
- **Languages**: English; multilingual ASR/translation via Whisper.
- **Hardware**: A100 80 GB SXM required for 13B.
- **Tool use**: Not applicable.
- **Official links**:
  - 13B: https://huggingface.co/tsinghua-ee/SALMONN
  - 7B: https://huggingface.co/tsinghua-ee/SALMONN-7B
  - Papers: https://arxiv.org/abs/2310.13289 ; https://arxiv.org/abs/2406.15704
  - Demo: https://bytedance.github.io/SALMONN/
- **Known limitations**: Text-only output; large memory footprint; emergent (not robust) spoken instruction following.

---

## Audio-Flamingo 2

- **Org / release / license**: NVIDIA. Paper March 6, 2025 (arXiv 2503.03983). Code **MIT**; checkpoints under **NVIDIA OneWay Noncommercial** + Qwen Research + OpenAI ToS.
- **Architecture & parameter count**: Cross-attention Flamingo-style architecture over a 3B Qwen-2.5 language backbone.
- **Modalities**: Audio (up to 5 min) + text → text. **NOT STS.**
- **Quality / capability**: SOTA across 20+ benchmarks; outperforms GAMA, original Audio-Flamingo, Qwen-Audio/Qwen2-Audio, LTU, SALMONN, AudioGPT, Gemini Flash v2, Gemini Pro v1.5, GPT-4o-audio at release.
- **Languages**: English-primary.
- **Hardware**: 3B is consumer-GPU friendly.
- **Tool use**: Not headlined.
- **Official links**:
  - HF: https://huggingface.co/nvidia/audio-flamingo-2
  - Demo: https://research.nvidia.com/labs/adlr/AF2/
  - Repo: https://github.com/NVIDIA/audio-flamingo
  - Paper: https://arxiv.org/abs/2503.03983
- **Known limitations**: Non-commercial checkpoint license; no speech output.

---

## Sesame CSM (Conversational Speech Model)

- **Org / release / license**: Sesame. CSM-1B released March 13, 2025; native HF Transformers support since v4.52.1 (May 20, 2025). **Apache 2.0**.
- **Architecture & parameter count**: Llama backbone + smaller audio decoder producing Mimi codes; 1B parameters.
- **Modalities**: Text + (optional) audio context → audio (RVQ codes → WAV). **NOT a chat LLM — it does not generate text and is not an STS dialog model**. Despite the "Conversational Speech Model" branding, this is a context-aware TTS, not a chatbot.
- **Latency**: Supports CUDA graphs / full-graph compilation, batched inference, static cache — designed for low-latency TTS.
- **Quality / capability**: Strong context-aware voice continuation; multi-turn speaker memory.
- **Languages**: English primary; other languages explicitly weak.
- **Hardware**: CUDA preferred; CPU fallback; 1B is light.
- **Tool use**: N/A.
- **Official links**:
  - Model: https://huggingface.co/sesame/csm-1b
  - Demo: https://www.sesame.com/voicedemo
  - HF Space: https://huggingface.co/spaces/sesame/csm-1b
  - Blog: https://www.sesame.com/research/crossing_the_uncanny_valley_of_voice
- **Known limitations**: **Cannot generate text; must be paired with an LLM**; no pre-trained voice identity (base model); poor non-English; access requires sharing contact info on HF.
- **Note for the user**: Treat Sesame CSM as a candidate **TTS engine for the cascade**, not as an STS alternative.

---

## Moonshot Kimi-Audio

- **Org / release / license**: Moonshot AI. Last collection update Jan 27, 2024 per HF; updated extensively into 2025. Primary license **MIT**, with Apache 2.0 derived code from Qwen2.5-7B backbone.
- **Architecture & parameter count**: ~10B params (7B Qwen2.5 base + audio components). Hybrid audio input (continuous acoustic features + discrete semantic tokens), parallel text/audio LM heads, chunk-wise flow-matching streaming detokenizer.
- **Modalities**: Audio + text → audio + text (configurable per-call).
- **Latency**: Streaming via chunk-wise detokenizer at ~24 kHz output; concrete latency figures not headlined.
- **Quality / capability**: ASR, AQA, AAC, SER, SEC/ASC, end-to-end speech conversation. Pre-trained on 13M+ hours of audio + text.
- **Languages**: English + Chinese primary.
- **Hardware**: 10B class; runs on a single high-end GPU.
- **Tool use**: Not headlined.
- **Official links**:
  - Model: https://huggingface.co/moonshotai/Kimi-Audio-7B-Instruct
  - Repo: https://github.com/MoonshotAI/Kimi-Audio
  - Tech report: https://github.com/MoonshotAI/Kimi-Audio/blob/master/assets/kimia_report.pdf
- **Known limitations**: Streaming chunk latency in real-time apps; requires GPU; documentation gaps around full-duplex / interruption.

---

## Proprietary bars (for reference — not open source)

- **OpenAI GPT-4o Realtime API**: closed; end-to-end speech-in / speech-out via WebSocket realtime API; full-duplex with VAD-based interruption; supports tools/function calling; ~600 ms end-to-end with good network. Sets the user-perceived quality bar competitors are chasing. Docs: https://platform.openai.com/docs/guides/realtime
- **Google Gemini Live API**: closed; native audio + video streaming; bidirectional. https://ai.google.dev/gemini-api/docs/live
- **Anthropic / others**: text-LLM-first; speech goes through a cascade.

These are useful as the quality/latency yardstick. Open-source contenders that approach this bar are Moshi (latency), Qwen3-Omni (capability), Step-Audio 2 (tools + RAG), and Kimi-Audio (audio understanding breadth).

---

## Cascaded orchestration frameworks (not models)

For the user's "speech → RAG → TTS" architecture, the orchestration layer matters as much as the models. Brief mentions:

- **LiveKit Agents** — Open-source Python framework on top of LiveKit's WebRTC stack. Plug-and-play STT/LLM/TTS providers, native interruption / VAD / turn detection, and direct support for OpenAI's realtime end-to-end speech API as an alternative path. Apache 2.0. Repo: https://github.com/livekit/agents. Docs: https://docs.livekit.io/agents/
- **Pipecat (Daily.co)** — Modular Python framework for voice/video AI agents; pipeline of frame processors (STT → LLM → TTS); supports many providers and OpenAI realtime; BSD-2-Clause. Repo: https://github.com/pipecat-ai/pipecat
- **Vocode** — Open-source voice-agent library (Python + TypeScript); telephony integration, streaming, function calling. MIT. Repo: https://github.com/vocodedev/vocode-core

Use these to glue STT + LLM + TTS components, or to host an end-to-end STS model behind a WebRTC/SIP transport.

---

## Comparison Table

| Model | License | Params | E2E latency | Full-duplex | Speech-out | Languages | VRAM | Tool use |
|---|---|---|---|---|---|---|---|---|
| Moshi (Moshiko/Moshika) | CC-BY-4.0 (weights) | 7B | **200 ms** | **Yes (native)** | Yes | EN | ~16 GB | No |
| GLM-4-Voice | GLM-4 license | 9B | <1 s streaming | No | Yes | ZH, EN | ~20 GB | No |
| LLaMA-Omni | Code Apache-2.0, weights research-only | 8B | **226 ms** | No | Yes | EN | ~16 GB | No |
| LLaMA-Omni2 | Code Apache-2.0, weights research-only | 0.5–32B | ~300 ms streaming | No | Yes | EN or EN+ZH | ~14 GB (7B) | No |
| Mini-Omni | MIT | 0.5B | Streaming | No | Yes | EN | <8 GB | No |
| Mini-Omni2 | MIT | ~0.5B | Streaming | Planned | Yes | EN | <8 GB | No |
| SpeechGPT (v1) | Unclear / research | 7B | Offline | No | Yes | EN | ~16 GB | No |
| SpeechGPT-Gen | Research | 8B | Offline | No | Yes | EN | ~18 GB | No |
| SpeechGPT 2.0-preview | Apache 2.0 | 7B | **<200 ms** | Interrupt-only | Yes | ZH only | ~14 GB | No |
| Step-Audio v1 | Apache 2.0 | 130B | Multi-GPU | No | Yes (via TTS-3B) | ZH, EN | ≥260 GB bf16 | Some |
| **Step-Audio 2 mini** | **Apache 2.0** | Small/mid | Streaming | No | Yes | EN, ZH, JA, AR, Cantonese | ~16–24 GB | **Yes (native + RAG)** |
| Meta Spirit-LM | FAIR Noncommercial | 7B | Offline | No | Yes | EN | ~14 GB | No |
| Qwen2-Audio | Apache 2.0 | 7B | n/a (text out) | No | **No** (FLAG) | EN, ZH multi | ~14 GB | Yes (via Qwen) |
| Qwen2.5-Omni | Apache 2.0 | 3B / 7B | Streaming | No | Yes | EN, ZH, Cantonese, FR + | 31 GB (7B/15s vid) | Limited |
| **Qwen3-Omni 30B-A3B** | **Apache 2.0** | 35B MoE (~3B active) | Streaming, low-latency | Turn-taking | Yes | 119 text / 18 speech-in / 10 speech-out | **78+ GB** | **Yes (audio FC)** |
| Phi-4-Multimodal | MIT | 5.6B | RTFX 151 | No | **No** (FLAG) | 8 audio langs | ~12 GB | **Yes** |
| Ultravox (70B) | MIT | 70B (+0.7B adapter) | sub-second | No | **No** (FLAG) | 42 langs | ≥80 GB | Inherits Llama FC |
| **Hertz-dev** | **Apache 2.0** | 8.5B | **120 ms (RTX 4090)** | **Yes (native)** | Yes | EN | ~17 GB (4090) | No |
| VITA-1.5 | Research | 8B | "GPT-4o-level" target | Partial | Yes | ZH, EN | ~16 GB | n/d |
| Baichuan-Audio | Apache 2.0 | 10B | Streaming-capable | No | Yes | ZH, EN+ | ~20 GB | No |
| SALMONN-13B | Apache 2.0 | 13B | Offline | No | **No** (FLAG) | EN + Whisper langs | A100 80 GB | No |
| Audio-Flamingo 2 | Code MIT, weights NV-noncomm | 3B | Offline | No | **No** (FLAG) | EN | ~6 GB | No |
| Sesame CSM-1B | Apache 2.0 | 1B | Low-latency TTS | n/a | Yes (TTS only) | EN | <4 GB | n/a |
| Kimi-Audio | MIT (Apache 2.0 base) | ~10B | Chunk-streaming | No | Yes | EN, ZH | ~20 GB | n/d |

"FLAG" rows are speech-input multimodal LLMs that do **not** emit speech; they cannot serve as a drop-in STS replacement on their own.

---

## Practical guidance for the user's voice-agent project

Given the goal of speech → RAG → TTS with the option of swapping in a single STS model:

- **If RAG / tool-calling fidelity is non-negotiable**: stay cascaded (Whisper / Phi-4-MM or Qwen2-Audio as STT + your text LLM + a fast TTS), OR move to **Step-Audio 2 mini** — currently the only open end-to-end STS with native tool calling and multimodal RAG.
- **If latency dominates and tools can be lightweight**: **Moshi** (200 ms, full-duplex, English) or **Hertz-dev** (120 ms on 4090, full-duplex, requires your own fine-tune).
- **If you need bilingual EN+ZH and an open Apache license**: **Qwen2.5-Omni-7B**, or **Qwen3-Omni** if you have H100-class hardware.
- **If you need expressive prosody / emotion control**: **GLM-4-Voice**, **SpeechGPT 2.0-preview** (ZH only), **Spirit-LM Expressive** (research/noncommercial).
- **Production cascade with strongest open audio understanding**: **Phi-4-Multimodal** as the speech-encoding LLM (best OpenASR WER among open models at release; supports function calling).
- **Avoid as STS** (text-out only): Qwen2-Audio, Phi-4-Multimodal (use as STT/understanding), Ultravox, SALMONN, Audio-Flamingo 2.
- **Avoid as STS** (TTS-only, not a chat model): Sesame CSM (great TTS engine for the cascade, not a dialog model).

---

## Sources & Leaderboards

- Moshi paper: https://huggingface.co/papers/2410.00037 — arXiv 2410.00037
- Moshi model card: https://huggingface.co/kyutai/moshiko-pytorch-bf16
- Moshi repo: https://github.com/kyutai-labs/moshi
- GLM-4-Voice model: https://huggingface.co/THUDM/glm-4-voice-9b
- GLM-4-Voice repo: https://github.com/THUDM/GLM-4-Voice
- LLaMA-Omni model: https://huggingface.co/ICTNLP/Llama-3.1-8B-Omni
- LLaMA-Omni paper: https://arxiv.org/abs/2409.06666
- LLaMA-Omni2 model: https://huggingface.co/ICTNLP/LLaMA-Omni2-7B-Bilingual
- LLaMA-Omni2 collection: https://huggingface.co/collections/ICTNLP/llama-omni-67fdfb852c60470175e36e9c
- Mini-Omni model: https://huggingface.co/gpt-omni/mini-omni
- Mini-Omni paper: https://arxiv.org/abs/2408.16725
- Mini-Omni2 model: https://huggingface.co/gpt-omni/mini-omni2
- Mini-Omni2 paper: https://arxiv.org/abs/2410.11190
- SpeechGPT model: https://huggingface.co/fnlp/SpeechGPT-7B-cm
- SpeechGPT paper: https://arxiv.org/abs/2305.11000
- SpeechGPT 2.0-preview LLM: https://huggingface.co/fnlp/SpeechGPT-2.0-preview-7B
- SpeechGPT 2.0-preview codec: https://huggingface.co/fnlp/SpeechGPT-2.0-preview-Codec
- SpeechGPT 2.0-preview repo: https://github.com/OpenMOSS/SpeechGPT-2.0-preview
- SpeechGPT 2.0-preview demo: https://sp2.open-moss.com/
- Step-Audio v1 model: https://huggingface.co/stepfun-ai/Step-Audio-Chat
- Step-Audio TTS: https://huggingface.co/stepfun-ai/Step-Audio-TTS-3B
- Step-Audio repo: https://github.com/stepfun-ai/Step-Audio
- Step-Audio 2 mini: https://huggingface.co/stepfun-ai/Step-Audio-2-mini
- Step-Audio 2 repo: https://github.com/stepfun-ai/Step-Audio2
- Step-Audio 2 docs: https://www.stepfun.com/docs/en/step-audio2
- Meta Spirit-LM paper: https://arxiv.org/abs/2402.05755
- Meta Spirit-LM repo: https://github.com/facebookresearch/spiritlm
- Meta Spirit-LM samples: https://speechbot.github.io/spiritlm
- Qwen2-Audio model: https://huggingface.co/Qwen/Qwen2-Audio-7B-Instruct
- Qwen2-Audio blog: https://qwenlm.github.io/blog/qwen2-audio/
- Qwen2-Audio report: https://arxiv.org/abs/2407.10759
- Qwen2.5-Omni model: https://huggingface.co/Qwen/Qwen2.5-Omni-7B
- Qwen2.5-Omni paper: https://arxiv.org/abs/2503.20215
- Qwen3-Omni model: https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct
- Qwen3-Omni repo: https://github.com/QwenLM/Qwen3-Omni
- Qwen3-Omni tech report: https://github.com/QwenLM/Qwen3-Omni/blob/main/assets/Qwen3_Omni.pdf
- Phi-4-Multimodal model: https://huggingface.co/microsoft/Phi-4-multimodal-instruct
- Phi-4-Multimodal report: https://arxiv.org/abs/2503.01743
- Ultravox v0.5 70B: https://huggingface.co/fixie-ai/ultravox-v0_5-llama-3_3-70b
- Ultravox repo: https://github.com/fixie-ai/ultravox
- Hertz-dev model: https://huggingface.co/si-pbc/hertz-dev
- Hertz-dev blog: https://si.inc/hertz-dev/
- Hertz-dev repo: https://github.com/Standard-Intelligence/hertz-dev
- VITA-1.5 model: https://huggingface.co/VITA-MLLM/VITA-1.5
- VITA-1.5 paper: https://huggingface.co/papers/2501.01957
- VITA repo: https://github.com/VITA-MLLM/VITA
- Baichuan-Audio model: https://huggingface.co/baichuan-inc/Baichuan-Audio-Instruct
- Baichuan-Audio repo: https://github.com/baichuan-inc/Baichuan-Audio
- SALMONN-13B model: https://huggingface.co/tsinghua-ee/SALMONN
- SALMONN paper: https://arxiv.org/abs/2310.13289
- Audio-Flamingo 2 model: https://huggingface.co/nvidia/audio-flamingo-2
- Audio-Flamingo 2 paper: https://arxiv.org/abs/2503.03983
- Audio-Flamingo 2 repo: https://github.com/NVIDIA/audio-flamingo
- Sesame CSM-1B: https://huggingface.co/sesame/csm-1b
- Sesame blog: https://www.sesame.com/research/crossing_the_uncanny_valley_of_voice
- Kimi-Audio model: https://huggingface.co/moonshotai/Kimi-Audio-7B-Instruct
- Kimi-Audio repo: https://github.com/MoonshotAI/Kimi-Audio
- LiveKit Agents repo: https://github.com/livekit/agents
- LiveKit Agents docs: https://docs.livekit.io/agents/
- Pipecat repo: https://github.com/pipecat-ai/pipecat
- Vocode repo: https://github.com/vocodedev/vocode-core
- OpenAI Realtime docs: https://platform.openai.com/docs/guides/realtime
- Gemini Live docs: https://ai.google.dev/gemini-api/docs/live
- Hugging Face OpenASR leaderboard: https://huggingface.co/spaces/hf-audio/open_asr_leaderboard
