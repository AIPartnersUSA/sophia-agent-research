# Open-Source Speech-to-Text (STT / ASR) Models — Landscape Report (May 2026)

## Introduction

Automatic Speech Recognition (ASR), also called Speech-to-Text (STT), converts a stream of audio into text tokens. For a voice-agent pipeline (speech → RAG → TTS), an STT model's value depends on more than raw word-error-rate (WER): latency (real-time factor / RTFx, first-token latency, streaming support), language coverage, license terms for commercial use, hardware footprint (VRAM, quantization options, CPU feasibility), and ancillary capabilities (word-level timestamps, automatic punctuation/casing, diarization, noise robustness, code-switching, long-form audio handling).

The primary objective evaluation framework throughout is the **Hugging Face Open ASR Leaderboard** ([leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard), [paper arXiv:2510.06961](https://arxiv.org/abs/2510.06961)), which standardizes evaluation over 10 datasets — AMI, CoVoST-2, Earnings22, FLEURS, GigaSpeech, LibriSpeech clean/other, MLS, SPGISpeech, TED-LIUM v3, and VoxPopuli — and reports both WER and RTFx (inverse real-time factor, where higher = faster, measured on a single NVIDIA A100-SXM4-80GB at batch sizes up to 64). Per the leaderboard paper, **the top four English models all combine a Conformer encoder with an LLM-based decoder**; CTC and TDT decoders win on RTFx but trade off WER ([arXiv 2510.06961, §3](https://arxiv.org/html/2510.06961)).

---

## OpenAI Whisper Large-v3

- **Org / model:** OpenAI / `openai/whisper-large-v3`. Released Dec 6, 2022. License **Apache 2.0**. [HF card](https://huggingface.co/openai/whisper-large-v3) · [paper arXiv:2212.04356](https://arxiv.org/abs/2212.04356).
- Transformer encoder-decoder, **1,550M params**, 32+32 layers, trained on ~1M h labeled + 4M h pseudo-labeled audio. 128 mel bins (vs 80 in v2), Cantonese token added.
- **Accuracy:** LibriSpeech test-clean **2.01 WER**, test-other **3.91**; Open-ASR mean WER **7.44**, rank 25, RTFx 145.51 ([leaderboard paper Table 3](https://arxiv.org/html/2510.06961v3#S2.T3)); AMI 15.95, GigaSpeech 10.02, Earnings22 11.29.
- **Capabilities:** 99 languages; speech translation to English; sentence- and word-level timestamps; long-form via sliding-window or chunked algorithms (30 s receptive field); not optimized for live streaming. Known to hallucinate on silence and produce repetitive outputs.
- **Hardware:** ~6 GB VRAM FP16, runs on CPU (slow). 27 community quantizations; CTranslate2/Faster-Whisper, GGML/whisper.cpp, ONNX, JAX implementations exist.

## OpenAI Whisper Large-v3-Turbo

- **Org / model:** OpenAI / `openai/whisper-large-v3-turbo`. Released **October 1, 2024** ([HF commit history](https://huggingface.co/openai/whisper-large-v3-turbo/commits/main)). License **MIT**. [HF card](https://huggingface.co/openai/whisper-large-v3-turbo).
- Same encoder as large-v3, but **decoder pruned 32 → 4 layers** then fine-tuned. **809M params** (FP16).
- **Accuracy:** LibriSpeech clean **2.1**, other **4.24**; Open-ASR mean WER **7.83**, RTFx 200.19 (HF card); AMI 16.13, Earnings22 11.63, SPGISpeech 2.97.
- **Capabilities:** retains all 99 Whisper languages; word-level timestamps; speech translation. No native streaming.
- **Hardware:** ~4–5 GB VRAM FP16; FA2 supported; works on Apple Silicon (MLX), CTranslate2, whisper.cpp.

## Distil-Whisper (distil-large-v3 and distil-large-v3.5)

- **Org / models:** Hugging Face / `distil-whisper/distil-large-v3` (Nov 1, 2023) and `distil-whisper/distil-large-v3.5`. License **MIT**. [v3 card](https://huggingface.co/distil-whisper/distil-large-v3) · [v3.5 card](https://huggingface.co/distil-whisper/distil-large-v3.5) · [paper arXiv:2311.00430](https://arxiv.org/abs/2311.00430).
- Encoder copied from Whisper large-v3 (frozen); decoder distilled. **756M params**.
- **Accuracy v3:** LibriSpeech clean 2.54, other 5.19; Open-ASR mean WER 7.52; RTFx 214.42.
- **Accuracy v3.5:** Short-form mean WER **7.10**; LibriSpeech clean **2.37**; GigaSpeech 9.84; long-form WER 10.04; RTFx **~1.46× faster than large-v3-turbo**, 49.34 RTFx long-form. Trained on 98 k h (vs 22 k h for v3) via patient-teacher distillation on 64 H100s. On the Open ASR Leaderboard: mean WER **7.21**, rank 21, RTFx 202.03 ([leaderboard paper Table 3](https://arxiv.org/html/2510.06961v3#S2.T3)).
- English only. Works as draft model for speculative decoding with large-v3 (~2× speedup, identical outputs).
- **Hardware:** ~3 GB VRAM FP16; 4-bit/8-bit quantization; CPU via whisper.cpp.

## Faster-Whisper & WhisperX (Implementations, not new models)

These are **runtimes**, not separate models.
- **Faster-Whisper** (`SYSTRAN/faster-whisper`, MIT) re-implements Whisper inference on CTranslate2 with INT8/FP16/INT8_FP16 quantization. The official conversion of large-v3 is `Systran/faster-whisper-large-v3` (FP16 weights, INT8 selectable at load via `compute_type`) — [HF card](https://huggingface.co/Systran/faster-whisper-large-v3). Typical speedup: 4–8× over openai/whisper.
- **WhisperX** (`m-bain/whisperX`) wraps Faster-Whisper + VAD pre-segmentation + wav2vec2 forced alignment for accurate word timestamps + pyannote diarization. Should be considered a deployment option for any Whisper or Distil-Whisper checkpoint, not double-counted.

## NVIDIA Parakeet Family

FastConformer-based, all **CC-BY-4.0** (commercial use allowed), 16 kHz mono input.

- **Parakeet-RNNT-1.1B** ([HF card](https://huggingface.co/nvidia/parakeet-rnnt-1.1b), May 8 2023, 1.1B). LibriSpeech clean **1.46**, other **2.47**; Open-ASR mean WER **7.12**; **RTFx 2,053**. English only, lowercase, no punctuation.
- **Parakeet-TDT-CTC-1.1B** ([HF card](https://huggingface.co/nvidia/parakeet-tdt_ctc-1.1b), 1.1B). LibriSpeech clean **1.82**, other **3.67**; TED 3.87; CV 8.69; SPGI 2.24. **Single-pass up to 11 h of audio**; ~90 min in <16 s on A100. English only.
- **Parakeet-TDT-0.6B-v2** ([HF card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2), May 1 2025, 0.6B). LibriSpeech clean **1.69**, other **3.19**, TED **3.38**; Open-ASR mean WER **6.05**; **RTFx 3,386 (rank 5)**. **Streaming via TDT decoder**, configurable chunks; word/char/segment timestamps; auto punctuation. Telephony μ-law 8 kHz 6.32 WER; SNR-10 noise 6.95 WER. 2 GB RAM min.
- **Parakeet-TDT-0.6B-v3** ([HF card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), Aug 14 2025, 0.6B, **25 European languages**). LibriSpeech clean **1.93**, other **3.59**; FLEURS-25 avg **11.97**; English Open-ASR mean **6.34**, RTFx 3,332 (rank 7). Adds auto language ID; up to 24 min full-attn / 3 h local-attn on A100 80 GB. Streaming via chunked inference.
- **Parakeet-CTC-1.1B**: mean WER **7.40, RTFx 2,728** — fastest competitive CTC model ([leaderboard paper Table 3](https://arxiv.org/html/2510.06961v3)).

## NVIDIA Canary Family

Multilingual ASR + AST. All **CC-BY-4.0**.

- **Canary-1B** (original; 0.97 B; en/de/fr/es): Open-ASR mean WER **6.50, RTFx 235**.
- **Canary-1B-Flash** ([HF card](https://huggingface.co/nvidia/canary-1b-flash); 883 M). LibriSpeech clean **1.48**, other **2.87**; CV-16.1 en 6.99, de 4.09, es 3.62, fr 6.15. Open-ASR mean **6.35**, rank 8, RTFx 1,045 (A100) / 1,669 (H100). ASR + AST en↔de/es/fr; optional punctuation/casing; experimental word/segment timestamps. Max input ~40 s.
- **Canary-180M-Flash** ([HF card](https://huggingface.co/nvidia/canary-180m-flash); 182 M; en/de/fr/es). LibriSpeech clean **1.87**, other **3.83**. RTFx **1,233** A100, **2,041** H100. Not streaming.
- **Canary-1B-v2** ([HF card](https://huggingface.co/nvidia/canary-1b-v2); Aug 14 2025; 978 M; **25 EU languages**). FLEURS-25 8.40, MLS-6 7.27, LibriSpeech clean 2.18. Open-ASR mean **7.15, RTFx 749**. ASR + bidirectional AST across all 25 langs; chunked inference with 1 s overlap. 6 GB RAM min.
- **Canary-Qwen-2.5B** ([HF card](https://huggingface.co/nvidia/canary-qwen-2.5b); Jul 17 2025; 2.5 B; SALM = FastConformer + Qwen LLM decoder). **#1 on Open ASR Leaderboard at the time of the leaderboard paper: mean WER 5.63, RTFx 418** ([Table 3](https://arxiv.org/html/2510.06961v3)). LibriSpeech clean **1.61**, other **3.10**; SPGI 1.90; TED 2.72. English only, max 40 s/pass, no native streaming.
- **Nemotron-Speech-Streaming-EN-0.6B** ([HF card](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b); released **March 13, 2026**; NVIDIA Open Model License — commercial OK). 600 M params, Cache-Aware FastConformer (24 layers) + RNNT, **purpose-built for streaming**. Configurable latency **80 ms / 160 ms / 560 ms / 1,120 ms**; at 1.12 s avg WER **6.93** (LS-clean 2.32, LS-other 4.84, AMI 11.73). English only; built-in punctuation/casing; dynamic runtime latency.

## Meta SeamlessM4T v2 Large

- `facebook/seamless-m4t-v2-large`, Dec 8 2023. License **CC-BY-NC 4.0 (non-commercial)** — major constraint for production. [HF card](https://huggingface.co/facebook/seamless-m4t-v2-large) · [paper arXiv:2312.05187](https://arxiv.org/abs/2312.05187). **2.3B params**, UnitY2 multitask. 101 in-speech / 96 in-text / 35 out-speech languages. Five tasks incl. ASR. WERs published in the official metrics zip; not on HF page.

## Meta MMS (Massively Multilingual Speech)

- `facebook/mms-1b-all`, May 22 2023. License **CC-BY-NC 4.0**. [HF card](https://huggingface.co/facebook/mms-1b-all) · [paper arXiv:2305.13516](https://arxiv.org/abs/2305.13516). Wav2Vec2 + per-language adapters; ~1B params; **1,162 languages** (FLEURS). LibriSpeech clean **12.63**, other **15.99**; AMI 42.02; Open-ASR mean WER **22.54, RTFx 230.79**. Optimized for **language breadth, not English accuracy**.

## Kyutai STT (Moshi-derived streaming models)

License **CC-BY 4.0**. Underlying [Moshi paper arXiv:2410.00037](https://arxiv.org/abs/2410.00037).

- **stt-2.6b-en** ([HF card](https://huggingface.co/kyutai/stt-2.6b-en)): 2.6 B params; streaming latency **2.5 s**. Open-ASR mean WER **6.40**, rank 9, **RTFx 88.37** ([Table 3](https://arxiv.org/html/2510.06961v3)); LS clean 1.70 / other 4.32; SPGI 2.03; GigaSpeech 9.81; AMI 12.17.
- **stt-1b-en_fr** ([HF card](https://huggingface.co/kyutai/stt-1b-en_fr)): 1 B params, EN+FR, streaming latency **0.5 s**, **built-in semantic VAD**.
- **stt-2.6b-en-trfs**: native Transformers integration (requires `transformers >= 4.53.0`).
- Architecture: decoder-only Transformer over **Mimi codec** tokens (12.5 Hz, 32 tokens/frame, 1.1 kbps, fully causal). Outputs capitalized & punctuated text; timestamps recoverable from frame offsets. Tested up to 2 h of audio.
- **The 1B EN/FR variant with 0.5 s latency + semantic VAD is one of the most production-ready streaming OSS ASR models for voice agents.**

## Microsoft Phi-4-Multimodal-Instruct

- `microsoft/Phi-4-multimodal-instruct`, Feb 2025. License **MIT**. [HF card](https://huggingface.co/microsoft/Phi-4-multimodal-instruct). 5.6 B params multimodal transformer (Phi-4-Mini-Instruct backbone, audio + image + text inputs). Trained 5T text + 2.3 M h speech + 1.1 T image-text tokens on 512× A100-80G for 28 days.
- **#1 on Open ASR Leaderboard at launch (March 4, 2025).** Current rank **4, mean WER 6.02, RTFx 151** ([Table 3](https://arxiv.org/html/2510.06961v3)). LibriSpeech clean **1.69**, other **3.82**; AMI 11.09, GigaSpeech 9.33, SPGISpeech 3.06.
- **Best multilingual ASR among leaderboard top tier** ([Table 4](https://arxiv.org/html/2510.06961v3#S2.T4)): DE 4.50 / FR 5.13 / IT 4.80 / ES 3.59 / PT 5.15.
- 8 audio languages (en, zh, de, fr, it, ja, es, pt); 23 text languages; 128K text context; ≤ 40 s for transcription, ≤ 30 min for summarization. Outperforms SeamlessM4T-v2-Large on translation directions it covers.
- ~12 GB VRAM; flash-attn 2.7.4 required for optimal performance; vLLM compatible.

## Alibaba SenseVoice / FunASR / Paraformer

- **SenseVoice-Small** ([HF card](https://huggingface.co/FunAudioLLM/SenseVoiceSmall), Jul 2024, model-license, ~244 M class). 50+ langs, optimized for Mandarin/Cantonese/English/Japanese/Korean; 400 k+ h training. **70 ms to process 10 s** of audio — **15× faster than Whisper-Large, 5× faster than Whisper-Small**. Outperforms Whisper on AISHELL-1/2 and Wenetspeech. Also performs **Spoken Language ID + Speech Emotion Recognition + Audio Event Detection** (applause/laughter/BGM/etc.) — uniquely useful as a richer front-end for voice agents. FSMN-VAD frontend.
- **Paraformer-zh** ([HF card](https://huggingface.co/funasr/paraformer-zh), Apache 2.0/FunASR, 220 M). Non-autoregressive parallel Transformer; 60 k h Mandarin training. **Streaming variant `paraformer-zh-streaming` ≈ 600 ms latency**. ~10× cheaper inference than autoregressive equivalents; top SpeechIO Mandarin leaderboard entry.

## IBM Granite Speech 3.x / 4.x

All **Apache 2.0**.

- **Granite-Speech-3.3-8B** ([HF card](https://huggingface.co/ibm-granite/granite-speech-3.3-8b), Jun 19 2025, ~9 B). Conformer speech encoder (16 blocks) + q-former projector + Granite-3.3-8B-Instruct LLM + LoRA rank-64. Open-ASR mean WER **5.74, rank 2, RTFx 145**. LibriSpeech clean **1.43**, other **2.86**. Langs: en/fr/de/es/pt; AST X↔En incl. ja/zh.
- **Granite-Speech-3.3-2B**: Open-ASR mean WER **6.00, rank 3, RTFx 260**.
- **Granite-Speech-4.1-2B** ([HF card](https://huggingface.co/ibm-granite/granite-speech-4.1-2b), released **April 29, 2026**, 2 B). Same modular design with Granite-4.0-1B LLM (128K ctx). **Best published Open-ASR average WER seen in this survey: 5.33**. LibriSpeech clean **1.33**, other **2.50**; TED 3.07; AMI 8.09; Earnings22 8.37; GigaSpeech 9.80; SPGISpeech 3.78; VoxPopuli 5.70. Langs: en/fr/de/es/pt/ja.
- **Granite-Speech-4.1-2B-Plus** ([HF card](https://huggingface.co/ibm-granite/granite-speech-4.1-2b-plus), April 28 2026). Open-ASR mean **5.71**.

## Mistral Voxtral-Mini-3B-2507

- [HF card](https://huggingface.co/mistralai/Voxtral-Mini-3B-2507). July 2025. License **Apache 2.0**. Ministral 3B + fine-tuned Whisper-derived audio encoder (5B total). 8 langs (en/es/fr/pt/hi/de/nl/it) with auto-LID. LibriSpeech clean **1.88**, other **4.10**; GigaSpeech 10.24; AMI 16.30. Open-ASR mean **7.05, RTFx 109.86** ([Table 3](https://arxiv.org/html/2510.06961v3)). Multilingual (Table 4): DE 5.36 / FR 5.96 / IT 5.88 / ES 3.81 / PT 4.80. 32 K context; audio up to 30 min (transcribe) / 40 min (understand). ASR + audio Q&A + summarization + **function calling from voice**. ~9.5 GB VRAM BF16. Newer realtime variant exists: `mistralai/Voxtral-Mini-4B-Realtime-2602`.

## Useful Sensors Moonshine

- `UsefulSensors/moonshine` (tiny 27 M, base 61 M). Oct 2024. License **MIT**. Built in Keras (Torch/TF/JAX backends). [HF card](https://huggingface.co/UsefulSensors/moonshine) · [paper arXiv:2410.15608](https://arxiv.org/abs/2410.15608).
- **Moonshine-Base 61 M**: LibriSpeech clean **3.38**, other **8.15**; Open-ASR mean **9.99, RTFx 565.97** ([HF moonshine-base card](https://huggingface.co/UsefulSensors/moonshine-base)).
- Built for **edge deployment** (microcontrollers, mobile, SBCs). Faster than Whisper-tiny at similar size with better accuracy. English-only.

## CrisperWhisper (Nyra Health)

- [HF card](https://huggingface.co/nyrahealth/CrisperWhisper). Paper [arXiv:2408.16589](https://arxiv.org/abs/2408.16589), INTERSPEECH 2024. License **CC-BY-NC-4.0 (non-commercial)**. 2 B params, fine-tuned Whisper Large v3.
- Open-ASR mean WER **6.67, rank 11, RTFx 84.05**. AMI **8.72** (vs Whisper-large-v3 16.01); TED-LIUM 3.35; LibriSpeech clean **1.74**.
- **Verbatim transcription** including fillers/disfluencies; **precise word-level timestamps** via DTW on cross-attention; trained with 1 % noise samples for hallucination resistance. English + German.
- #1 on OpenASR for verbatim datasets (TED, AMI). Requires custom transformers fork.

## Qwen3-ASR (Alibaba)

All **Apache 2.0**, released Jan 29 2026. Built on Qwen3-Omni foundation.

- **Qwen3-ASR-1.7B** ([HF card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B), 2 B BF16, **30 languages + 22 Chinese dialects**). LibriSpeech clean **1.63**, other **3.38**; GigaSpeech 8.45; CV-en 7.39. Chinese WenetSpeech net **4.97** / meeting **5.88** (Whisper-large-v3: 9.86 / 19.11); AISHELL-2 **2.71** (Whisper 5.06). **FLEURS multilingual avg 4.90 WER** — strongest open-source FLEURS result among large models. **Robust to songs+BGM** (M4Singer 5.98 WER) — rare. **Streaming via vLLM** (offline 2.69 vs streaming 3.33 avg). Word-level timestamps via companion `Qwen3-ForcedAligner-0.6B` (11 langs). ~6–8 GB VRAM.
- **Qwen3-ASR-0.6B** ([HF card](https://huggingface.co/Qwen/Qwen3-ASR-0.6B), 0.6 B). LS 2.11/4.55; CV-en 9.92; Fleurs-zh 2.88. **2000× throughput at concurrency 128**; **~2 GB VRAM**; RTFx 166. Best-in-class small multilingual ASR for high-concurrency serving.

## Cohere Transcribe 03-2026 (NEW SOTA)

- [HF card](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026). Released **March 26, 2026**. License **Apache 2.0**. 2 B params, large Conformer encoder + lightweight Transformer decoder.
- 14 langs: en/fr/de/it/es/pt/el/nl/pl/zh/ja/ko/vi/ar.
- **Average WER 5.42** on the English leaderboard slice — among the lowest published. LibriSpeech clean **1.25**, other **2.37**; TED 2.49; SPGISpeech 3.08; GigaSpeech 9.33; Earnings22 10.84; AMI 8.15.
- **RTFx 524.88** — ~3× faster than other Conformer-LLM models at comparable WER.
- Long-form via auto chunking + reassembly; punctuation control; batched inference.
- **Limitations: no automatic language detection; no timestamps or diarization; benefits from VAD/noise-gate.** Deployment: transformers, vLLM, mlx-audio (Apple Silicon), WebGPU, Rust.

## AssemblyAI Universal-2, Deepgram Nova-3, ElevenLabs Scribe v1, Speechmatics Enhanced, Rev AI Fusion, Aqua Voice Avalon (Proprietary)

These are **closed-source, API-only.** They appear on the Open ASR Leaderboard for comparison but cannot be self-hosted. The leaderboard paper notes RTFx cannot be fairly computed for them (upload latency, no GPU control) ([§3](https://arxiv.org/html/2510.06961v3)). The highest-ranked closed-source model is **Aqua Voice Avalon** at rank 6, mean WER **6.24** — beating all open-source models *except* the top 5 (Canary-Qwen-2.5B, Granite-Speech-3.3-8B, Granite-Speech-3.3-2B, Phi-4-Multimodal, Parakeet-TDT-0.6B-v2). ElevenLabs Scribe v1 covers **99 languages** at WER 6.88; Speechmatics Enhanced covers **55 languages** at WER 6.91.

## Whisper.cpp (deployment runtime)

- [HF card](https://huggingface.co/ggerganov/whisper.cpp). License **MIT**. Pure-C/C++ Whisper in **GGML** with broad quantization (q5_0, q5_1, q8_0).
- Sizes: Tiny 31–75 MiB · Base 57–142 MiB · Small 181–466 MiB · Medium 514 MiB – 1.5 GiB · Large 1.1–2.9 GiB. **CPU-only target**; standard deployment vehicle for Whisper on edge hardware.

## Additional 2025/2026 Releases of Interest

Trending ASR list on HF ([page](https://huggingface.co/models?pipeline_tag=automatic-speech-recognition&sort=trending)) surfaces:

- **Microsoft VibeVoice-ASR** — companion to VibeVoice TTS.
- **Xiaomi MiMo-V2.5-ASR** — Mandarin/English oriented.
- **AI4Bharat indic-conformer-600m-multilingual** — strong on Indian languages.
- **Atlasia moulsot.v0.3** — Moroccan Darija ASR.
- **Ivrit AI Whisper-Large-v3** — Hebrew community fine-tune.
- **MediaTek-Research Breeze-ASR-26** ([HF card](https://huggingface.co/MediaTek-Research/Breeze-ASR-26)) — Feb 26 2026, Apache 2.0, fine-tuned Whisper-large-v2 for Taiwanese Hokkien (Taigi) with Mandarin output; CER 30.13 % average. Code-switching support.
- **Pyannote Speaker Diarization 3.1** ([HF card](https://huggingface.co/pyannote/speaker-diarization-3.1)) — not ASR but the standard companion for diarization in WhisperX-style pipelines (MIT).

---

## Summary Comparison Table

WER below is LibriSpeech test-clean. "Streaming" = **native** streaming (not chunked-offline). VRAM is approximate FP16 inference footprint. Citations in each section above.

| Model | License | Params | LS clean WER | Open-ASR mean WER | Streaming | Languages | VRAM (FP16) |
|---|---|---|---|---|---|---|---|
| Whisper Large-v3 | Apache 2.0 | 1,550M | 2.01 | 7.44 | No (chunked) | 99 | ~6 GB |
| Whisper Large-v3-Turbo | MIT | 809M | 2.10 | 7.83 | No (chunked) | 99 | ~4 GB |
| Distil-Large-v3 | MIT | 756M | 2.54 | 7.52 | No (chunked) | EN | ~3 GB |
| Distil-Large-v3.5 | MIT | 756M | 2.37 | 7.21 | No (chunked) | EN | ~3 GB |
| Faster-Whisper-Large-v3 (runtime) | MIT | 1,550M | 2.01 | 7.44 | No | 99 | ~3 GB INT8 |
| Parakeet-RNNT-1.1B | CC-BY-4.0 | 1.1B | 1.46 | 7.12 | Limited | EN | ~4 GB |
| Parakeet-TDT-CTC-1.1B | CC-BY-4.0 | 1.1B | 1.82 | — | No | EN | ~4 GB |
| Parakeet-TDT-0.6B-v2 | CC-BY-4.0 | 0.6B | 1.69 | **6.05** | Yes (TDT) | EN | ~2.5 GB |
| Parakeet-TDT-0.6B-v3 | CC-BY-4.0 | 0.6B | 1.93 | 6.34 | Yes (chunked) | 25 EU | ~2.5 GB |
| Parakeet-CTC-1.1B | CC-BY-4.0 | 1.1B | — | 7.40 | No | EN | ~4 GB |
| Canary-180M-Flash | CC-BY-4.0 | 182M | 1.87 | — | No | en/de/fr/es | ~1 GB |
| Canary-1B-Flash | CC-BY-4.0 | 883M | 1.48 | 6.35 | No (≤40s) | en/de/fr/es | ~3 GB |
| Canary-1B-v2 | CC-BY-4.0 | 978M | 2.18 | 7.15 | Chunked | 25 EU | ~4 GB |
| **Canary-Qwen-2.5B** | CC-BY-4.0 | 2.5B | **1.61** | **5.63 (rank 1)** | No | EN | ~9 GB |
| Nemotron-Speech-Streaming-EN-0.6B | NVIDIA OML | 0.6B | 2.32 | 6.93 @1.12s | **Yes (80ms–1.12s)** | EN | ~2.5 GB |
| SeamlessM4T-v2-Large | CC-BY-NC-4.0 | 2.3B | — | — | No | 101 in / 35 out | ~10 GB |
| MMS-1B-all | CC-BY-NC-4.0 | 1B | 12.63 | 22.54 | No | **1,162** | ~4 GB |
| Kyutai STT-2.6B-en | CC-BY-4.0 | 2.6B | 1.70 | 6.40 | **Yes (2.5s)** | EN | ~10 GB |
| Kyutai STT-1B-en_fr | CC-BY-4.0 | 1B | — | — | **Yes (0.5s + VAD)** | en/fr | ~4 GB |
| Phi-4-Multimodal-Instruct | MIT | 5.6B | 1.69 | 6.02 (rank 4) | No | 8 audio | ~12 GB |
| SenseVoice-Small | model-license | ~244M | — | — | No (VAD frontend) | 50+ (zh/yue/en/ja/ko) | ~1 GB |
| Paraformer-zh | Apache 2.0/FunASR | 220M | — | — | **Yes (600ms)** | zh | ~1 GB |
| Granite-Speech-3.3-8B | Apache 2.0 | 9B | 1.43 | 5.74 (rank 2) | No | 5 | ~18 GB |
| Granite-Speech-3.3-2B | Apache 2.0 | 2B | — | 6.00 (rank 3) | No | 5 | ~5 GB |
| **Granite-Speech-4.1-2B** | Apache 2.0 | 2B | **1.33** | **5.33** | No | 6 | ~5 GB |
| Granite-Speech-4.1-2B-Plus | Apache 2.0 | 2B | 1.44 | 5.71 | No | 5 | ~5 GB |
| Voxtral-Mini-3B-2507 | Apache 2.0 | 3B+enc | 1.88 | 7.05 | No | 8 | ~9.5 GB |
| CrisperWhisper | CC-BY-NC-4.0 | 2B | 1.74 | 6.67 | No | en/de | ~5 GB |
| Qwen3-ASR-1.7B | Apache 2.0 | 2B | 1.63 | — | **Yes (vLLM)** | 30 + 22 zh dialects | ~6–8 GB |
| Qwen3-ASR-0.6B | Apache 2.0 | 0.6B | 2.11 | 6.42 | **Yes (vLLM)** | 30 | ~2 GB |
| **Cohere Transcribe 03-2026** | Apache 2.0 | 2B | **1.25** | **5.42** | No (chunked) | 14 | ~5 GB |
| Moonshine-Base | MIT | 61M | 3.38 | 9.99 | Edge/live | EN | <500 MB |
| Whisper.cpp (large-v3 q5) | MIT | (1.1 GiB disk) | ~2.0 | ~7.4 | No | 99 | CPU-only |

Closed-source reference: **Aqua Voice Avalon** rank 6 WER 6.24 · **ElevenLabs Scribe v1** rank 12 WER 6.88 (99 langs) · **Speechmatics Enhanced** rank 13 WER 6.91 (55 langs) · **Rev AI Fusion** rank 18 WER 7.12.

---

## Sources & Leaderboards

### Leaderboard / Survey
- Open ASR Leaderboard (HF Space): https://huggingface.co/spaces/hf-audio/open_asr_leaderboard
- Open ASR Leaderboard paper (Oct 2025): https://arxiv.org/abs/2510.06961 · HTML: https://arxiv.org/html/2510.06961
- Code: https://github.com/huggingface/open_asr_leaderboard
- SpeechIO Mandarin leaderboard: https://github.com/SpeechColab/Leaderboard

### Model Cards & Papers (key URLs)
- Whisper-large-v3: https://huggingface.co/openai/whisper-large-v3 · paper https://arxiv.org/abs/2212.04356
- Whisper-large-v3-turbo: https://huggingface.co/openai/whisper-large-v3-turbo
- Distil-Whisper v3: https://huggingface.co/distil-whisper/distil-large-v3 · paper https://arxiv.org/abs/2311.00430
- Distil-Whisper v3.5: https://huggingface.co/distil-whisper/distil-large-v3.5
- Faster-Whisper conversion: https://huggingface.co/Systran/faster-whisper-large-v3
- Faster-Whisper: https://github.com/SYSTRAN/faster-whisper · WhisperX: https://github.com/m-bain/whisperX · whisper.cpp: https://huggingface.co/ggerganov/whisper.cpp
- Parakeet TDT v2/v3, RNNT, TDT-CTC: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2 · https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3 · https://huggingface.co/nvidia/parakeet-rnnt-1.1b · https://huggingface.co/nvidia/parakeet-tdt_ctc-1.1b
- Canary 1B-Flash, 180M-Flash, v2, Qwen-2.5B: https://huggingface.co/nvidia/canary-1b-flash · https://huggingface.co/nvidia/canary-180m-flash · https://huggingface.co/nvidia/canary-1b-v2 · https://huggingface.co/nvidia/canary-qwen-2.5b
- Nemotron-Speech-Streaming-EN-0.6B: https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b
- SeamlessM4T v2 Large: https://huggingface.co/facebook/seamless-m4t-v2-large · paper https://arxiv.org/abs/2312.05187
- MMS-1B-all: https://huggingface.co/facebook/mms-1b-all · paper https://arxiv.org/abs/2305.13516
- Kyutai STT: https://huggingface.co/kyutai/stt-2.6b-en · https://huggingface.co/kyutai/stt-1b-en_fr · https://huggingface.co/kyutai/stt-2.6b-en-trfs · Moshi paper https://arxiv.org/abs/2410.00037
- Phi-4 Multimodal: https://huggingface.co/microsoft/Phi-4-multimodal-instruct
- SenseVoice / Paraformer: https://huggingface.co/FunAudioLLM/SenseVoiceSmall · https://huggingface.co/funasr/paraformer-zh · https://huggingface.co/funasr/paraformer-large
- Granite Speech: https://huggingface.co/ibm-granite/granite-speech-3.3-8b · https://huggingface.co/ibm-granite/granite-speech-4.1-2b · https://huggingface.co/ibm-granite/granite-speech-4.1-2b-plus
- Voxtral: https://huggingface.co/mistralai/Voxtral-Mini-3B-2507
- CrisperWhisper: https://huggingface.co/nyrahealth/CrisperWhisper · paper https://arxiv.org/abs/2408.16589
- Qwen3-ASR: https://huggingface.co/Qwen/Qwen3-ASR-1.7B · https://huggingface.co/Qwen/Qwen3-ASR-0.6B
- Moonshine: https://huggingface.co/UsefulSensors/moonshine · base https://huggingface.co/UsefulSensors/moonshine-base · paper https://arxiv.org/abs/2410.15608
- Cohere Transcribe: https://huggingface.co/CohereLabs/cohere-transcribe-03-2026
- Breeze-ASR-26: https://huggingface.co/MediaTek-Research/Breeze-ASR-26
- Pyannote Diarization: https://huggingface.co/pyannote/speaker-diarization-3.1
- HF Trending ASR: https://huggingface.co/models?pipeline_tag=automatic-speech-recognition&sort=trending

