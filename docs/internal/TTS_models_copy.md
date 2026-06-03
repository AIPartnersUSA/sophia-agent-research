# Open-Source TTS Models — Landscape Report (May 2026)

## Introduction

Text-to-Speech (TTS) is the task of converting written text into intelligible, natural-sounding speech audio. The open-source TTS landscape has transformed dramatically over 2023-2026, evolving from older two-stage acoustic-model-plus-vocoder pipelines (Tacotron 2, FastSpeech 2 + HiFi-GAN) into four overlapping modern paradigms: (1) **autoregressive speech-LLMs** that treat speech as a sequence of neural-codec tokens predicted by a transformer (VALL-E, Tortoise, XTTS, MetaVoice, Spark-TTS, Orpheus, CSM, IndexTTS, OuteTTS, Step-Audio, Chatterbox); (2) **non-autoregressive flow-matching / diffusion** models that denoise a mel-spectrogram or latent in parallel (Voicebox, E2-TTS, F5-TTS, NaturalSpeech 3, Seed-TTS DiT, MaskGCT, Zonos hybrid); (3) **style-diffusion + adversarial GAN** decoder-only models (StyleTTS 2, Kokoro); and (4) **hybrid two-stage LLM-plus-diffusion / flow-matching** pipelines (CosyVoice 2, Fish Speech, FireRedTTS).

The dimensions used for comparison in this report are: license (commercial-permissive vs. non-commercial / research-only), parameter count and backbone architecture, audio codec used (EnCodec, SNAC, DAC, Mimi, BiCodec, FunCodec, custom VQ-VAE), multilingual coverage, zero-shot voice-cloning reference-audio requirements, support for emotion / style / non-verbal sounds, real-time factor (RTF) and time-to-first-byte (TTFB), streaming readiness, sample rate, hardware (VRAM at FP16/INT8) and quantization story, and documented limitations.

The current state of the art in May 2026 is roughly: F5-TTS, E2-TTS, MaskGCT, and Seed-TTS-class DiT flow-matching models dominate naturalness and zero-shot speaker similarity benchmarks; Llama-backed speech-LLMs (Orpheus, CSM-1B, IndexTTS-2, Step-Audio-TTS-3B, Chatterbox) dominate streaming latency and expressive / emotion-controlled generation; CosyVoice 2 leads bi-streaming multilingual production deployments; Kokoro-82M holds the price/quality crown on CPU/edge; XTTS-v2 and Fish-Speech 1.5 remain the workhorse multilingual cloning baselines; MMS-TTS is still the only model covering >1,000 languages. The TTS Arena V2 (TTS-AGI/TTS-Arena-V2 on Hugging Face) is the de-facto crowd-sourced ELO leaderboard; many of the models below are listed there, although Arena V2 does not publish per-model ELO numbers in a stable structured form. (https://huggingface.co/spaces/TTS-AGI/TTS-Arena-V2)

---

## Coqui XTTS-v2

- **Org / model / release / license** — Coqui AI; `coqui/XTTS-v2`; v2.0.3 final release December 2023 (paper INTERSPEECH 2024). License: **Coqui Public Model License (CPML) – non-commercial only**. (https://huggingface.co/coqui/XTTS-v2, https://coqui.ai/cpml)
- **Architecture & parameter count** — Tortoise-derived three-stage pipeline: (a) 13M-param VQ-VAE audio tokenizer (1024 filtered codes, 21.53 Hz frame rate), (b) **443M-param GPT-2 decoder-only transformer** with a 6,681-token BPE text tokenizer and a 6-layer Perceiver Resampler conditioning encoder producing 32 × 1024-dim speaker embeddings, (c) HiFi-GAN decoder (26M params) conditioned on H/ASP speaker embeddings. ~520M params total. (arXiv:2406.04904 https://arxiv.org/abs/2406.04904)
- **Quality metrics** — On English FLORES+ / DAPS reference protocol the XTTS paper reports SOTA CER among multilingual ZS-TTS, beating original YourTTS multilingual and Mega-TTS 2 on CER, with competitive UTMOS and SECS. CMOS over HierSpeech++ and Mega-TTS 2 is positive on naturalness and acoustic quality; SMOS slightly trails monolingual SOTA. No TTS-Arena ELO published by the authors.
- **Latency** — Streaming inference supported via the official `tts.stream_generation` and the `voice-chat-with-mistral` Space; RTF not formally reported; community measurements ~0.2-0.4 RTF on RTX 3090 (fp16).
- **Languages** — **17 languages**: English, Spanish, French, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Mandarin, Japanese, Hungarian, Korean, Hindi. (https://huggingface.co/coqui/XTTS-v2)
- **Capabilities** — Zero-shot voice cloning from **6 seconds** of reference audio; cross-language cloning (clone English voice, speak Hindi); emotion/style transfer; multi-speaker interpolation; streaming output supported via Coqui TTS API; no explicit SSML; sample rate **24 kHz** (VQ-VAE trained at 22.05 kHz, decoder upsampled to 24 kHz); no native non-verbal sound tokens.
- **Hardware** — Fits in ~4-6 GB VRAM at FP16 for inference; runs on CPU with `--use_cuda false` at ~3-5× real-time slower; community INT8 and GGUF ports exist.
- **Official links** — https://huggingface.co/coqui/XTTS-v2 ; https://github.com/coqui-ai/TTS ; paper https://arxiv.org/abs/2406.04904 ; demo https://huggingface.co/spaces/coqui/xtts
- **Known limitations** — Coqui as a company shut down in early 2024; CPML restricts commercial use; some accent / prosody drift on low-resource languages (Hungarian, Korean, Japanese have <600 hours each in training); occasional hallucination on long inputs; SMOS slightly below monolingual SOTAs.

## F5-TTS

- **Org / model / release / license** — SJTU X-LANCE Lab; `SWivid/F5-TTS`; v1 base released October 9 2024 (v1 weights `model_1250000.safetensors`). License: **CC-BY-NC 4.0** (non-commercial). (https://huggingface.co/SWivid/F5-TTS, paper https://arxiv.org/abs/2410.06885)
- **Architecture & parameter count** — Fully non-autoregressive **flow-matching with Diffusion Transformer (DiT)**: 22 DiT layers, 16 attention heads, 1024 / 2048 emb/FFN, with a 4-layer **ConvNeXt V2** text-refinement front-end (512/1024 dims). adaLN-zero conditioning. **335.8M parameters**. Vocoder: pretrained **Vocos**. Mel: 100-dim log mel-filterbank, 24 kHz, hop 256.
- **Quality metrics** — On LibriSpeech-PC test-clean: 32-NFE WER 2.42%, SIM-o 0.66 (vs ground-truth 2.23 / 0.69; vocoder-resynthesized 2.32 / 0.66). On Seed-TTS test-en CMOS +0.31 / SMOS 3.89, test-zh CMOS +0.21 / SMOS 3.83. Surpasses E2-TTS, CosyVoice 1, FireRedTTS, MaskGCT in WER. Sway Sampling at coefficient s = -1 gives best quality. (Table 1 of paper.)
- **Latency** — **RTF 0.15 at 16 NFE**, 0.31 at 32 NFE (RTX 3090, 10 s output). Not natively streaming (NAR over full duration), but chunked generation supported. CFG doubles inference time.
- **Languages** — Trained on **Emilia ~95K hours English + Mandarin**; supports both natively plus seamless **code-switching**. Many community-finetuned variants for Japanese, German, Spanish, Hindi, etc. (91 finetunes on HF).
- **Capabilities** — Zero-shot voice cloning from any reference (4-10 s recommended); speed control via duration scaling (no explicit duration predictor — duration estimated from char-length ratio); no emotion tags; Sway Sampling tunes naturalness without retraining; non-streaming; 24 kHz output; no non-verbal sound tokens.
- **Hardware** — ~6 GB VRAM at FP16; runs on consumer GPUs (3090, 4090, 5090); CPU inference possible but slow. Triton / TensorRT optimized forks exist.
- **Official links** — Repo https://github.com/SWivid/F5-TTS ; HF https://huggingface.co/SWivid/F5-TTS ; paper https://arxiv.org/abs/2410.06885 ; demo https://huggingface.co/spaces/mrfakename/E2-F5-TTS
- **Known limitations** — Non-commercial license blocks production use; duration estimation can mis-pace long sentences; relies on Vocos external vocoder; multilingual coverage is community-driven; SIM-o on LibriSpeech-PC trails E2-TTS slightly (0.66 vs 0.69).

## E2-TTS

- **Org / model / release / license** — Microsoft Research; "E2 TTS: Embarrassingly Easy Fully Non-Autoregressive Zero-Shot TTS" (Interspeech 2024). Original weights **not publicly released by Microsoft**; the canonical open-source implementation lives inside the F5-TTS repo as `E2TTS_Base` (`model_1200000.safetensors`), trained on Emilia 100K hours. License of community weights: **CC-BY-NC 4.0**. (Paper https://arxiv.org/abs/2406.18009; weights https://huggingface.co/SWivid/E2-TTS)
- **Architecture & parameter count** — Vanilla Transformer with **flat U-Net style skip connections** + conditional flow matching (OT path). Character sequence + filler tokens directly concatenated with mel spectrogram, no phoneme aligner, no duration predictor, no text encoder. 24 layers, 16 attention heads, 1024/4096 emb/FFN, **~333M parameters** (matching configuration used in F5-TTS comparison). Trained originally on 50K-hour Libriheavy + 200K-hour proprietary set by Microsoft.
- **Quality metrics** — Reproduced E2-TTS (community) achieves WER 2.95% / SIM-o 0.69 on LibriSpeech-PC test-clean with 32 NFE (slightly higher SIM than F5-TTS, slightly worse WER per F5 paper Table 1).
- **Latency** — RTF 0.68 at 32 NFE (midpoint ODE solver) — significantly slower than F5-TTS; non-streaming.
- **Languages** — English (Microsoft) + Multilingual (community Emilia weights cover English & Chinese; code-switching).
- **Capabilities** — Zero-shot voice cloning; "Extension 1" variant allows inference **without prompt transcription** (uses MFA-determined word boundaries); "Extension 2" allows pronunciation override via inline CMU phonemes in parentheses; 24 kHz; no emotion or non-verbal control.
- **Hardware** — ~6 GB VRAM FP16 (333M params + Vocos vocoder).
- **Official links** — Paper https://arxiv.org/abs/2406.18009 ; Microsoft demo https://aka.ms/e2tts/ ; community impl. inside https://github.com/SWivid/F5-TTS
- **Known limitations** — Slow convergence and lower robustness vs F5-TTS — the very issues F5 was designed to fix; flow alignment failures cannot be salvaged by re-ranking; official Microsoft weights remain unreleased.

## StyleTTS 2

- **Org / model / release / license** — Columbia University / Li et al.; `styletts2/styletts2`; NeurIPS 2023. **License: MIT**. (Paper https://arxiv.org/abs/2306.07691 ; https://github.com/yl4579/StyleTTS2)
- **Architecture & parameter count** — Style diffusion + adversarial training with large speech language models. Components: text encoder, PL-BERT prosodic encoder, 3-layer Transformer **style diffusion denoiser** (EDM formulation with DPM-2 ancestral sampler), acoustic + prosodic style encoders, HiFi-GAN or iSTFTNet decoder, duration & prosody predictors, **WavLM-large SLM discriminator** (12-layer, frozen, with 3-layer CNN head). Total ~148M generator params (LibriTTS config). 24 kHz output.
- **Quality metrics** — On LJSpeech, MOS-N 3.83 ± 0.08 vs ground-truth 3.81; CMOS +0.28 over ground truth (p=0.021) — **first model to surpass human MOS**. On VCTK, CMOS -0.02 vs ground truth (statistically indistinguishable from human). On LibriTTS zero-shot: MOS-N 4.15 / MOS-S 4.03 vs ground-truth 4.60/4.35; **outperforms VALL-E in naturalness by +0.67 CMOS using 250× less data** (245 hrs vs 60k hrs).
- **Latency** — **RTF 0.0185** on a single A40 GPU — ~3× faster than VITS, ~8× faster than diffusion-based baselines. Streaming-capable in chunks but no native streaming API.
- **Languages** — Original release English-only (LJSpeech / VCTK / LibriTTS). Community Japanese, Chinese, Korean fine-tunes exist.
- **Capabilities** — Zero-shot voice cloning via reference style encoder; **no emotion-tag interface** but style diffusion produces diverse prosody samples; long-form generation stable on OOD text (MOS-N 3.87 OOD vs 3.83 in-domain); 24 kHz; no non-verbal sounds.
- **Hardware** — <3 GB VRAM FP16; runs on CPU at ~real-time for short clips; trained on 4 × A40.
- **Official links** — https://github.com/yl4579/StyleTTS2 ; paper https://arxiv.org/abs/2306.07691 ; demo https://styletts2.github.io/
- **Known limitations** — English-centric; no multilingual support out of the box; voice-cloning quality depends heavily on reference recording quality; less expressive than modern speech-LLMs for emotion control; small training set (245 hrs).

## Kokoro-82M (and Kokoro v1.1-zh)

- **Org / model / release / license** — `hexgrad/Kokoro-82M` (v1.0 January 27 2025) and `hexgrad/Kokoro-82M-v1.1-zh` (February 26 2025). **License: Apache 2.0**. (https://huggingface.co/hexgrad/Kokoro-82M, https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)
- **Architecture & parameter count** — **StyleTTS 2-based decoder-only** architecture with **ISTFTNet vocoder** (no diffusion, no encoder). **82 million parameters**. Trained on permissively-licensed audio only (public-domain, Apache/MIT-licensed, synthetic from closed TTS).
- **Quality metrics** — Despite tiny size, Kokoro v1.0 has ranked at or near the top of **TTS Arena V1** human-preference leaderboard (community reports place it in the top tier alongside ElevenLabs and XTTS-v2). 9.7M monthly downloads. No published WER/MOS in model card.
- **Latency** — Extremely fast: small enough to run **real-time on CPU** and on browser via WASM; <0.1 RTF on consumer GPUs. No native streaming API but chunked generation trivial.
- **Languages** — v1.0: **8 languages** with **54 voices** (American English, British English, Japanese, Mandarin, Spanish, French, Hindi, Italian, Brazilian Portuguese — variants by accent). v1.1-zh: focused English + Chinese with **103 voices total** (100+ Chinese speakers from LongMaoData + 3 English voices Maple/Sol/Vale).
- **Capabilities** — Voice selection only (no zero-shot reference cloning — uses pre-baked speaker embeddings); no emotion tags; 24 kHz; no SSML; no non-verbal sounds; long-form via chunking.
- **Hardware** — <1 GB VRAM; runs on **CPU at faster-than-real-time**; mobile-friendly. Training cost ~$1,000 (1,000 A100-hours) for v1.0, ~$110 (120 A100-hours) for v1.1-zh.
- **Official links** — https://huggingface.co/hexgrad/Kokoro-82M ; https://github.com/hexgrad/kokoro ; demo https://hf.co/spaces/hexgrad/Kokoro-TTS
- **Known limitations** — No zero-shot voice cloning (fixed voice set); limited expressiveness vs speech-LLMs; v1.0 English voices less varied than v1.1; warning of scam websites with "kokoro" in the domain unaffiliated with the project.

## MetaVoice-1B

- **Org / model / release / license** — MetaVoice Labs; `metavoiceio/metavoice-1B-v0.1` (February 2024). **License: Apache 2.0**. (https://huggingface.co/metavoiceio/metavoice-1B-v0.1)
- **Architecture & parameter count** — Four-stage stack: (1) **causal GPT** predicting first two EnCodec hierarchies from BPE text + speaker condition (1.2B params, "flattened interleaved" pattern); (2) **non-causal transformer** predicting remaining 6 EnCodec hierarchies (~10M); (3) **Multi-Band Diffusion** waveform decoder from EnCodec tokens; (4) **DeepFilterNet** post-processing. Total ~1.2B params. 100K hours training data.
- **Quality metrics** — No formal WER/SIM-O / Arena ELO published. Authors claim no hallucinations and emotional rhythm capture.
- **Latency** — Multi-stage pipeline; no published RTF; multi-band diffusion stage is the bottleneck. Not natively streaming.
- **Languages** — Primarily **English** (American + British); validated on Indian English speakers.
- **Capabilities** — Zero-shot cloning from **30 s reference** (American/British) or **1 minute fine-tuning** for Indian speakers; emotional intonation; condition-free sampling for better cloning; long-form support; EnCodec 24 kHz.
- **Hardware** — ~6-8 GB VRAM FP16.
- **Official links** — https://github.com/metavoiceio/metavoice-src ; https://huggingface.co/metavoiceio/metavoice-1B-v0.1
- **Known limitations** — Project effectively dormant since mid-2024 (company pivoted); English-only; multi-stage pipeline is operationally complex; multi-band diffusion adds latency.

## Suno Bark

- **Org / model / release / license** — Suno AI; `suno/bark` and `suno/bark-small`; April 2023. **License: MIT**. (https://huggingface.co/suno/bark)
- **Architecture & parameter count** — **Three transformer stages** all over EnCodec tokens: (a) text→semantic (80M/300M, causal, BERT-tokenized text → 10,000 semantic vocab); (b) semantic→coarse (80M/300M, causal, 2 × 1024 EnCodec codebooks); (c) coarse→fine (80M/300M, non-causal, 6 × 1024 EnCodec codebooks). Small ~340M total, Large ~900M total. 24 kHz mono.
- **Quality metrics** — No formal benchmarks; Suno did not publish a paper. Known for novelty more than fidelity.
- **Latency** — Slow autoregressive 3-stage; no streaming; ~5-10× real-time on RTX 3090 large model.
- **Languages** — **13 languages** including English, German, Spanish, French, Hindi, Italian, Japanese, Korean, Polish, Portuguese, Russian, Turkish, Mandarin.
- **Capabilities** — **Non-verbal sounds via inline tags**: `[laughs]`, `[sighs]`, `[gasps]`, `[clears throat]`, `[music]`, `—` and `…` for pauses, MUSIC NOTES; can even generate music & sound effects. **Voice cloning is unofficial and unreliable** (community history-prompt approach). Random voice generation default. No SSML. Sample rate 24 kHz.
- **Hardware** — Large: ~12 GB VRAM FP16; Small: ~4 GB. INT8 / `bark-small` enables ~2-4 GB CPU operation.
- **Official links** — https://github.com/suno-ai/bark ; HF docs https://huggingface.co/docs/transformers/model_doc/bark
- **Known limitations** — Suno officially "research purposes only"; output not censored (can hallucinate profanity, music); poor speaker consistency across long generations; no controllable voice cloning; Bark-detect classifier shipped to mitigate misuse.

## Tortoise-TTS

- **Org / model / release / license** — James Betker; `jbetker/tortoise-tts-v2` (2022). License: **Apache 2.0** in repo (code), model weights effectively open. (https://huggingface.co/jbetker/tortoise-tts-v2)
- **Architecture & parameter count** — **Five separate models**: autoregressive decoder, diffusion decoder, **CLVP** (Contrastive Language-Voice Pre-training, à la CLIP), voice encoder, **UnivNet** vocoder. Largest model smaller than GPT-2 Large; ~420M for the AR. Trained on ~49K hours of audiobooks. 22.05 kHz output.
- **Quality metrics** — No paper-quality benchmarks (technical report only, https://arxiv.org/abs/2305.07243). Known for very high naturalness on narrative speech.
- **Latency** — **Extremely slow**: ~2 minutes per medium sentence on a Tesla K80; minutes per sentence on an RTX 3090 with `preset='fast'`. Not streaming.
- **Languages** — **English only**.
- **Capabilities** — Voice cloning via **3-5 reference clips ~10 s each**; expressive narrative prosody (audiobook-style); 22.05 kHz; built-in **Tortoise-detect classifier** for AI-audio detection.
- **Hardware** — Needs NVIDIA GPU; ~4-8 GB VRAM but ~minutes/sentence latency.
- **Official links** — https://github.com/neonbjb/tortoise-tts ; design doc https://nonint.com/2022/04/25/tortoise-architectural-design-doc/
- **Known limitations** — Slow; English audiobook bias (poor conversational, poor strong accents, poor minority voices); cannot reliably clone celebrities; superseded by XTTS and IndexTTS which extend the same architecture.

## MyShell OpenVoice v2

- **Org / model / release / license** — MyShell AI; `myshell-ai/OpenVoiceV2`; April 2024. **License: MIT** (commercial-friendly). (https://huggingface.co/myshell-ai/OpenVoiceV2 ; https://github.com/myshell-ai/OpenVoice)
- **Architecture & parameter count** — Two-stage: (a) base TTS speaker (multilingual VITS-style) + (b) tone-color converter (flow-based) that transfers reference speaker timbre onto the base output. Parameter count not explicitly published; ~150-200M total.
- **Quality metrics** — No formal benchmarks; community evaluations on Podonos place it mid-tier (below XTTS-v2 on similarity, on par on naturalness).
- **Latency** — Two-stage but fast; community reports near-real-time on RTX 3060.
- **Languages** — **6 natively trained languages**: English, Spanish, French, Mandarin, Japanese, Korean. **Cross-lingual cloning** (reference can be any language).
- **Capabilities** — Zero-shot voice cloning; **flexible style control over emotion, accent, rhythm, pauses, intonation** via inference parameters; non-streaming; no non-verbal sounds; ~24 kHz output.
- **Hardware** — ~2-4 GB VRAM FP16.
- **Official links** — https://huggingface.co/myshell-ai/OpenVoiceV2 ; https://github.com/myshell-ai/OpenVoice ; paper https://arxiv.org/abs/2312.01479
- **Known limitations** — Decoupled timbre-conversion approach can cause slight prosody mismatch; emotion control coarse compared to Chatterbox or Orpheus; less natural than F5-TTS / XTTS-v2 in blind tests.

## GPT-SoVITS

- **Org / model / release / license** — RVC-Boss / community; `lj1995/GPT-SoVITS`. **License: MIT**. (https://huggingface.co/lj1995/GPT-SoVITS ; https://github.com/RVC-Boss/GPT-SoVITS)
- **Architecture & parameter count** — Two-stage **GPT-based text-to-semantic + SoVITS (VITS-derived) acoustic decoder**. Optionally HuBERT-based semantic encoder. Several hundred million parameters total; small enough to fine-tune on consumer GPUs. v2 released 2024.
- **Quality metrics** — No formal paper; widely used in VTuber / dubbing community due to **excellent few-shot fine-tuning** (1-minute voice creates a passable clone; 5-minute creates a high-quality clone).
- **Latency** — Near-real-time on RTX 3060; supports chunked inference.
- **Languages** — **Chinese, English, Japanese, Korean, Cantonese** (v2 added Korean & Cantonese).
- **Capabilities** — **Few-shot voice cloning** (1-min fine-tune) and zero-shot 3-10 s reference cloning; cross-lingual voice cloning; 32 kHz output; no built-in emotion tags but emotion comes through reference; integrated UWebUI for fine-tuning.
- **Hardware** — Fine-tuning on 6 GB VRAM; inference on 4 GB.
- **Official links** — https://github.com/RVC-Boss/GPT-SoVITS ; https://huggingface.co/lj1995/GPT-SoVITS
- **Known limitations** — Documentation primarily in Chinese; pipeline is operationally complex (separate front-end, GPT, SoVITS, vocoder); occasional hallucination on long inputs; quality very dependent on reference clip recording quality.

## Fish Speech 1.5

- **Org / model / release / license** — Fish Audio; `fishaudio/fish-speech-1.5`; November 2 2024. **License: CC-BY-NC-SA 4.0** (non-commercial, share-alike). (https://huggingface.co/fishaudio/fish-speech-1.5 ; paper https://arxiv.org/abs/2411.01156)
- **Architecture & parameter count** — Decoder-only LLM (Llama-derived) over a custom dual-codebook semantic + acoustic tokenizer ("Firefly-GAN-VQ"). ~500M-1B parameters depending on variant. Two-stage: text→semantic LLM, then non-AR decoder→waveform.
- **Quality metrics** — Reported strong WER/SIM on internal benchmarks; surpasses XTTS-v2 in community A/B tests. **Top-3 placement reported on TTS Arena V1** in late 2024.
- **Latency** — Streaming-capable in chunks; ~0.2-0.5 RTF on RTX 4090.
- **Languages** — **13 languages**: English (>300K hr), Mandarin (>300K hr), Japanese (>100K hr), German, French, Spanish, Korean, Arabic, Russian (~20K hr each), Dutch, Italian, Polish, Portuguese (<10K hr each). **>1 million hours total training data**.
- **Capabilities** — Zero-shot voice cloning from short reference; emotion implied from reference; streaming; long-form stable; cross-lingual; no non-verbal sound tokens.
- **Hardware** — ~6-8 GB VRAM FP16; INT8 quantization supported.
- **Official links** — https://github.com/fishaudio/fish-speech ; demo https://fish.audio/
- **Known limitations** — Non-commercial license blocks production use without Fish Audio API; Korean/Arabic/Russian have proportionally less data; less expressive controllability than newer speech-LLMs like Orpheus.

## ChatTTS

- **Org / model / release / license** — 2noise; `2Noise/ChatTTS`; May 2024. **License: CC-BY-NC 4.0** (non-commercial). (https://huggingface.co/2Noise/ChatTTS ; https://github.com/2noise/ChatTTS)
- **Architecture & parameter count** — LLM-based with VQ-VAE codec; ~200M-400M params (not officially disclosed). Trained on 100K+ hours.
- **Quality metrics** — No formal benchmarks; designed for **conversational** speech (uhms, breaths, laughs, mid-sentence intonation), not single-utterance fidelity.
- **Latency** — Supports `compile=True` for speedup; ~real-time on RTX 3090. Supports batched inference.
- **Languages** — **Chinese and English** primarily.
- **Capabilities** — **Native non-verbal tokens**: `[laugh]`, `[uv_break]`, `[lbreak]`, `[oral_2]` etc., plus speed-control tokens `[speed_5]` and an inline speaker control `[spk_emb]`. Random-speaker mode. No SSML. 24 kHz. No native streaming API but chunkable.
- **Hardware** — ~4 GB VRAM FP16.
- **Official links** — https://github.com/2noise/ChatTTS ; https://huggingface.co/2Noise/ChatTTS
- **Known limitations** — Non-commercial only; output style is "podcast/conversational" which is great for dialog but unsuitable for narration; occasional hallucination of laughter/breath where not requested.

## Parler-TTS Large v1 (and Mini Multilingual v1.1)

- **Org / model / release / license** — Hugging Face / Dan Lyth / Simon King (Stability AI & Edinburgh); `parler-tts/parler-tts-large-v1` (and `parler-tts/parler-tts-mini-multilingual-v1.1`); 2024-2025. **License: Apache 2.0** (commercial-friendly). (https://huggingface.co/parler-tts/parler-tts-large-v1)
- **Architecture & parameter count** — Seq2Seq Transformer (T5-style) predicting **DAC** tokens, with a separate "description" prompt encoder. **Large v1: 2.2B params** trained on 45K hours; **Mini Multilingual v1.1: 0.9B params** trained on ~9,780 hours.
- **Quality metrics** — Paper (arXiv:2402.01912) reports strong MOS in English with description-prompt steerability; no Arena ELO.
- **Latency** — Slow autoregressive over DAC tokens; ~3-5× slower than F5-TTS at equivalent quality. Streaming token-by-token possible.
- **Languages** — Large v1: **English only**. Mini Multilingual v1.1: **English, French, Spanish, Portuguese, Polish, German, Italian, Dutch** (8 langs, +CML-TTS + Multilingual LibriSpeech non-English).
- **Capabilities** — **Description prompting is the unique selling point**: control gender, speaking rate, pitch, background noise level, reverberation, microphone proximity, named speaker (34 named speakers in Large; 16 in Multilingual Mini: Daniel, Christine, Richard, Nicole, etc.) via natural-language description. No zero-shot reference-audio cloning (description-only voice control). Sample rate 44.1 kHz (DAC native). No non-verbal sounds.
- **Hardware** — Large v1 ~10-12 GB VRAM FP16; Mini ~4-6 GB.
- **Official links** — https://github.com/huggingface/parler-tts ; paper https://arxiv.org/abs/2402.01912 ; checkpoints https://huggingface.co/parler-tts
- **Known limitations** — No reference-audio voice cloning (description only); slow autoregressive inference over high-rate DAC tokens; speaker consistency across long generations depends on description repetition; project went into maintenance mode in mid-2025.

## Meta MMS-TTS

- **Org / model / release / license** — Meta AI / FAIR; `facebook/mms-tts-*` (one model per language). **License: CC-BY-NC 4.0** (non-commercial). (https://huggingface.co/facebook/mms-tts ; paper https://arxiv.org/abs/2305.13516)
- **Architecture & parameter count** — Per-language **VITS** (Variational Inference with adversarial learning) checkpoints, ~36M parameters each. No shared multilingual backbone.
- **Quality metrics** — Bench: low-resource language coverage is the point, not fidelity. Quality is modest single-speaker VITS-tier.
- **Latency** — Fast (VITS is ~10× real-time on a 3090).
- **Languages** — **1,107 languages** with ISO 639-3 codes — by far the broadest language coverage of any open-source TTS. (https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html)
- **Capabilities** — **No voice cloning** (single fixed speaker per language); no emotion; no streaming API but fast enough not to need it; 16 kHz output.
- **Hardware** — <1 GB VRAM; CPU-feasible.
- **Official links** — https://github.com/facebookresearch/fairseq/tree/main/examples/mms ; HF docs https://huggingface.co/docs/transformers/main/en/model_doc/mms
- **Known limitations** — CC-BY-NC blocks commercial use; one model per language (1,107 separate ~36M checkpoints); no voice cloning; quality far below modern zero-shot TTS for the ~50 high-resource languages but unmatched for the long tail.

## Meta Voicebox / Audiobox

- **Org / model / release / license** — Meta AI / FAIR; **Voicebox** (NeurIPS 2023, arXiv:2306.15687) and **Audiobox** (December 2023, arXiv:2312.15821). **Weights NOT publicly released**; only research papers and a closed `audiobox.metademolab.com` demo. The only related Meta release is `facebook/audiobox-aesthetics` — a CC-BY 4.0 *audio-quality assessment* tool, **not** the generative model. (https://huggingface.co/facebook/audiobox-aesthetics)
- **Architecture (per paper)** — Voicebox: 330M-params flow-matching mel-spectrogram generator + duration model (NAR). Audiobox: extends to music/sound effects + natural-language description prompting.
- **Quality metrics** — Voicebox paper claims SOTA over VALL-E and YourTTS on intelligibility and similarity; comparison data only.
- **Languages** — Voicebox trained on 6 languages: English, Spanish, French, German, Polish, Portuguese.
- **Capabilities (per paper)** — Zero-shot TTS, content editing, noise removal, style transfer; not accessible to community.
- **Limitations** — **Not open-source**; included here only because community implementations (E2-TTS, F5-TTS, MaskGCT) are direct descendants. Use F5-TTS or E2-TTS as drop-in alternatives.

## Microsoft VALL-E / VALL-E X (community implementations)

- **Org / model / release / license** — Microsoft Research papers VALL-E (arXiv:2301.02111, Jan 2023) and VALL-E X (arXiv:2303.03926). **Official weights never released.** Community implementations include `Plachta/VALL-E-X` (MIT license, https://huggingface.co/Plachta/VALL-E-X) and `lifeiteng/vall-e` on GitHub.
- **Architecture & parameter count** — Neural codec language model: **EnCodec 8-codebook 75 Hz** tokenizer, then an AR transformer for codebook 1 + a NAR transformer for codebooks 2-8. ~370M params per official paper.
- **Quality metrics** — Original paper claimed SOTA zero-shot WER + SIM on LibriSpeech with 60K-hour training; VALL-E 2 (Microsoft, 2024) claimed parity with human MOS — but no public weights.
- **Languages** — VALL-E: English. VALL-E X: English + Chinese cross-lingual.
- **Capabilities** — Zero-shot cloning from 3 s; **cross-lingual cloning preserving speaker timbre and accent**.
- **Hardware** — Community fp16 weights run in ~4-6 GB VRAM.
- **Limitations** — Community weights trained on much smaller data than Microsoft's internal model and are notably weaker; superseded in practice by Spark-TTS, IndexTTS, F5-TTS, and Orpheus, which adopt similar codec-LM architecture with better tokenizers and training data.

## Sesame CSM-1B

- **Org / model / release / license** — Sesame AI Labs; `sesame/csm-1b`; March 2025. **License: Apache 2.0**. (https://huggingface.co/sesame/csm-1b ; demo https://www.sesame.com/voicedemo)
- **Architecture & parameter count** — **Llama backbone + smaller audio decoder** over **Mimi RVQ audio codes** (Kyutai's Mimi codec, 12.5 Hz / 24 kHz). **1B parameters** end-to-end. Natively supported by Hugging Face Transformers (`CsmForConditionalGeneration`) v4.52.1+.
- **Quality metrics** — Sesame's blog "Crossing the Uncanny Valley of Voice" claims SOTA conversational naturalness; no published WER/SIM. The Sesame voice-demo is widely regarded as among the most natural-sounding voice agents released in 2025.
- **Latency** — CUDA-graph and static-cache compilation supported; batched inference; **no formal streaming API in v1** but Mimi's low frame rate (12.5 Hz) makes streaming straightforward in practice (~150-250 ms TTFB in community demos).
- **Languages** — **English primary**; limited multilingual capacity (described as "data contamination"); not recommended for non-English production.
- **Capabilities** — Conversational context-aware generation (input is multi-turn `[speaker_id]text` history); produces voice variation, **not** speaker-fixed; no zero-shot voice cloning in v1; no emotion tags; 24 kHz; supports fine-tuning via Transformers Trainer.
- **Hardware** — ~3-4 GB VRAM FP16; CPU feasible at ~2-3× real-time.
- **Official links** — https://huggingface.co/sesame/csm-1b ; https://www.sesame.com/research/crossing_the_uncanny_valley_of_voice ; demo https://www.sesame.com/voicedemo
- **Known limitations** — English-only practically; v1 has no voice cloning (planned for v2); base model not finetuned to specific voices; need separate LLM for full conversational pipeline (CSM is just the voice).

## IndexTTS-1.5 (and IndexTTS-2)

- **Org / model / release / license** — Bilibili; `IndexTeam/IndexTTS-1.5` (released early 2025, paper Interspeech 2025 https://arxiv.org/abs/2502.05512) and `IndexTeam/IndexTTS-2` (paper arXiv:2506.21619, June 2025). **License: Apache 2.0**. (https://huggingface.co/IndexTeam/IndexTTS-1.5 ; https://huggingface.co/IndexTeam/IndexTTS-2)
- **Architecture & parameter count** — GPT-style **decoder-only LLM** based on XTTS + Tortoise lineage, with **Conformer-based Perceiver conditioning encoder** (replacing Tortoise's single-vector speaker), **FSQ-quantized speech codec** (Finite-Scalar Quantization, 8192 codes, levels `[8,8,8,6,5]`, near-100% codebook utilization), and **BigVGAN2 vocoder**. Trained on 34K hours filtered Chinese-English bilingual (25K Mandarin + 9K English from 120K-hour raw corpus). Sample rate 24 kHz; token rate 25 Hz interpolated to 100 Hz for BigVGAN2. Parameter count ~1-1.5B (not exactly disclosed).
- **Quality metrics** — Paper Table 3-5: **IndexTTS-1.5 significantly beats XTTS-v2, Fish-Speech, CosyVoice 2, FireRedTTS, and F5-TTS on WER on LibriSpeech, AISHELL-1, and CommonVoice zh/en** test sets. SS (speaker similarity) on par with CosyVoice 2 / F5-TTS. MOS outperforms all baselines on prosody, timbre similarity, and sound quality. IndexTTS-2 adds duration control and emotional expression.
- **Latency** — Paper claims faster inference than F5-TTS and Fish-Speech, but still autoregressive — practical RTF ~0.2-0.4 on RTX 4090. No native streaming in 1.5.
- **Languages** — **English and Mandarin** (1.5); IndexTTS-2 same.
- **Capabilities** — Zero-shot voice cloning from short reference (3-10 s); **character-pinyin hybrid input** for Chinese polyphone correction (replace ambiguous Hanzi with pinyin inline); punctuation-based pause control; IndexTTS-2 adds **emotional expression and duration control**.
- **Hardware** — ~6-8 GB VRAM FP16; quantization community-supported.
- **Official links** — https://github.com/index-tts/index-tts ; paper 1.5 https://arxiv.org/abs/2502.05512 ; paper 2 https://arxiv.org/abs/2506.21619 ; demos https://index-tts.github.io/ and https://index-tts.github.io/index-tts2.github.io/
- **Known limitations** — IndexTTS-1.5 has "insufficient capability to replicate rich emotional expressions" (authors' own words) — addressed by IndexTTS-2; only 2 languages supported; no instruct-style voice generation in 1.5; no native streaming.

## Spark-TTS 0.5B

- **Org / model / release / license** — HKUST + Mobvoi + SJTU + NPU; `SparkAudio/Spark-TTS-0.5B`; paper arXiv:2503.01710 (March 2025). **License: CC-BY-NC-SA 4.0** (recently changed from Apache 2.0 — non-commercial, share-alike). (https://huggingface.co/SparkAudio/Spark-TTS-0.5B)
- **Architecture & parameter count** — **Qwen2.5-0.5B LLM backbone** predicting **BiCodec** tokens: a novel single-stream codec splitting speech into **low-bitrate semantic tokens (linguistic)** and **fixed-length global tokens (speaker attributes)**. Trained on the new **VoxBox 100K-hour controllable-TTS dataset** with attribute annotations. Chain-of-thought (CoT) generation approach.
- **Quality metrics** — Paper reports SOTA WER + speaker similarity vs CosyVoice, MaskGCT, etc., on Seed-TTS test sets at substantially smaller size (0.5B vs 1B+).
- **Latency** — Single-stream BiCodec eliminates need for separate flow-matching decoder — directly reconstructs audio from LM-predicted codes. ~0.1-0.3 RTF.
- **Languages** — **English, Mandarin**, with cross-lingual code-switching.
- **Capabilities** — Zero-shot voice cloning; **coarse control** of gender / speaking style; **fine-grained control** of precise pitch values & speaking rate; 24 kHz; non-streaming.
- **Hardware** — ~2 GB VRAM FP16 — one of the smallest competitive speech-LLMs.
- **Official links** — https://github.com/SparkAudio/Spark-TTS ; paper https://arxiv.org/abs/2503.01710 ; demo https://sparkaudio.github.io/spark-tts/
- **Known limitations** — Recent license switch to CC-BY-NC-SA 4.0 makes production use legally fraught; 2-language coverage; smaller community than Fish/CosyVoice.

## Orpheus 3B (Canopy Labs)

- **Org / model / release / license** — Canopy Labs; `canopylabs/orpheus-3b-0.1-ft` (March 18 2025); **License: Apache 2.0**. (https://huggingface.co/canopylabs/orpheus-3b-0.1-ft ; https://github.com/canopyai/Orpheus-TTS)
- **Architecture & parameter count** — Speech-LLM **fine-tuned from Meta-Llama/Llama-3.2-3B-Instruct**. Predicts **SNAC (Multi-Scale Neural Audio Codec)** tokens — `hubertsiuzdak/snac_24khz`, a 24 kHz 0.98 kbps codec with 3 RVQ hierarchies at 12 Hz / 23 Hz / 47 Hz token rates and ~20M codec params. ~3B-4B params total (4B in safetensors F32).
- **Quality metrics** — No formal Arena ELO yet, but Canopy's blog reports ElevenLabs-comparable quality in blind tests.
- **Latency** — **~200 ms streaming TTFB; ~100 ms with input streaming** — among the lowest of any open-source TTS. Native token-by-token streaming.
- **Languages** — Primary English (with multilingual fine-tunes released subsequently); voices include `tara`, `leah`, `jess`, `leo`, `dan`, `mia`, `zac`, `zoe`.
- **Capabilities** — **Zero-shot voice cloning** plus **8 pre-baked voices**; **emotion tags** like `<laugh>`, `<sigh>`, `<chuckle>`, `<cough>`, `<sniffle>`, `<groan>`, `<yawn>`, `<gasp>` directly in text; human-like intonation and rhythm; **24 kHz** SNAC output; streaming ready.
- **Hardware** — ~8-10 GB VRAM FP16 for the 3B model; GGUF / vLLM / TensorRT-LLM ports available; one-click Baseten deployment.
- **Official links** — https://github.com/canopyai/Orpheus-TTS ; HF https://huggingface.co/canopylabs/orpheus-3b-0.1-ft ; blog https://canopylabs.ai/model-releases ; SNAC https://huggingface.co/hubertsiuzdak/snac_24khz
- **Known limitations** — Larger VRAM footprint than 0.5B speech-LLMs; emotion-tag set is fixed and small; primary training is English (multilingual variants community-driven); model access on HF requires accepting use-conditions.

## Zonos v0.1 (Zyphra)

- **Org / model / release / license** — Zyphra; `Zyphra/Zonos-v0.1-transformer` and `Zyphra/Zonos-v0.1-hybrid` (SSM/Mamba variant); February 2025. **License: Apache 2.0**. (https://huggingface.co/Zyphra/Zonos-v0.1-transformer)
- **Architecture & parameter count** — Two variants: a **pure transformer** and a **hybrid SSM (Mamba)** architecture. Pipeline: text → eSpeak-ng phonemization → **DAC token prediction** → decode to 44 kHz audio. Param count not officially disclosed; ~1-1.5B in safetensors.
- **Quality metrics** — Zyphra blog reports ElevenLabs-class naturalness; trained on **200K+ hours of multilingual speech**.
- **Latency** — **RTF ~2× real-time on RTX 4090**; no streaming.
- **Languages** — **5 languages**: English (US), Japanese, Mandarin, French, German.
- **Capabilities** — **Zero-shot voice cloning** from **10-30 s** speaker reference; direct speaker-embedding control; **audio-prefix inputs** for richer matching (e.g., whisper styles); fine-grained control of **speaking rate, pitch variation, audio quality, max frequency, emotions (happiness, fear, sadness, anger)**; 44 kHz native (one of the highest sample rates among open models).
- **Hardware** — **NVIDIA 30-series or newer with 6 GB+ VRAM**; Linux-only (Ubuntu 22.04/24.04 recommended); requires eSpeak-ng system library.
- **Official links** — https://huggingface.co/Zyphra/Zonos-v0.1-transformer ; https://huggingface.co/Zyphra/Zonos-v0.1-hybrid ; https://github.com/Zyphra/Zonos
- **Known limitations** — 5 languages only; Linux-only practically; phoneme-based front-end (eSpeak) limits novel-word handling; non-streaming; SSM hybrid is less mature than transformer variant.

## MARS5-TTS

- **Org / model / release / license** — CAMB.AI; `CAMB-AI/MARS5-TTS`; 2024. **License: GNU AGPL 3.0** (strong copyleft; commercial alternative licenses available from CAMB.AI). (https://huggingface.co/CAMB-AI/MARS5-TTS)
- **Architecture & parameter count** — Two-stage **AR-NAR** over EnCodec: (a) ~750M AR transformer predicting coarse codebook 0 from text; (b) ~450M Multinomial DDPM NAR refining remaining codebooks. **Total ~1.2B params (FP16)**. 24 kHz output.
- **Quality metrics** — No published Arena ELO; CAMB.AI claims competitive expressiveness, especially in long-form narration.
- **Latency** — Slow due to AR + diffusion combination; no streaming. ~1-2 × real-time on RTX 4090.
- **Languages** — **English in open-source release**; CAMB.AI's hosted API supports 140+ languages.
- **Capabilities** — Two voice-clone modes: **Shallow clone** (2-12 s reference, optimal ~6 s, no transcript needed, fast) and **Deep clone** (higher quality, requires accurate reference transcript); prosody steerable via punctuation, capitalization for emphasis, and inference params `top_k`, `temperature`, `top_p`, `rep_penalty_window`, `freq_penalty`.
- **Hardware** — **20 GB VRAM minimum** (1.2B params + activations).
- **Official links** — https://github.com/Camb-ai/MARS5-TTS ; https://huggingface.co/CAMB-AI/MARS5-TTS
- **Known limitations** — AGPL is hostile to closed-source product integration; high VRAM; English-only weights; no streaming; superseded for open use-cases by Orpheus / IndexTTS / F5-TTS.

## CosyVoice 2

- **Org / model / release / license** — Alibaba FunAudioLLM; `FunAudioLLM/CosyVoice2-0.5B`; December 2024 (arXiv:2412.10117). **License: Apache 2.0**. (https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B)
- **Architecture & parameter count** — Two-stage: **(a) text-to-supervised-semantic-token autoregressive LLM (0.5B params)** with custom FunCodec semantic tokens at 25 Hz, then **(b) flow-matching diffusion** from semantic tokens to mel + HiFi-GAN vocoder. Standard output 22.05 kHz / 16 kHz.
- **Quality metrics** — Seed-TTS benchmarks (model card): **test-zh CER 1.45%, test-zh SIM 75.7%, test-en WER 2.57%, test-en SIM 65.9%, test-hard CER 6.83%** — among the best open-source on Chinese.
- **Latency** — **Bi-streaming** (text-in streaming + audio-out streaming) with **latency as low as 150 ms**; KV-cache + SDPA-optimized; the only **commercially-licensed open model with first-class streaming today**.
- **Languages** — **9 languages**: Mandarin, English, Japanese, Korean, German, Spanish, French, Italian, Russian. **18+ Chinese dialects** (Cantonese, Sichuanese, Shanghainese, Dongbei, Shanxi, Tianjin, Shandong, Ningxia, Gansu, Minnan, etc.).
- **Capabilities** — Zero-shot voice cloning with savable speaker IDs (`add_zero_shot_spk`); **instruction-controlled** emotion / dialect / speed / volume; **pronunciation inpainting** via Pinyin (Chinese) and CMU phonemes (English); robust text normalization built in.
- **Hardware** — ~3-4 GB VRAM FP16 for the 0.5B LLM + flow-matching decoder.
- **Official links** — https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B ; https://github.com/FunAudioLLM/CosyVoice ; paper https://arxiv.org/abs/2412.10117
- **Known limitations** — English speaker similarity (65.9%) trails Chinese (75.7%); flow-matching stage adds latency vs single-stream codecs like Spark-TTS / Orpheus; bilingual emphasis means non-Chinese language coverage is weaker than XTTS-v2.

## OuteTTS 1.0 (and 0.3)

- **Org / model / release / license** — OuteAI; `OuteAI/OuteTTS-1.0-0.6B` (May 2025) and earlier `OuteAI/OuteTTS-0.3-1B` / `0.3-500M`. **License: Apache 2.0**. (https://huggingface.co/OuteAI/OuteTTS-1.0-0.6B)
- **Architecture & parameter count** — **Qwen3-0.6B LLM backbone** predicting **DAC (`ibm-research/DAC.speech.v1.0`)** audio tokens. Context length **8,192 tokens** (~42 s audio). Trained on **20,000 hours** from Multilingual LibriSpeech + Common Voice.
- **Quality metrics** — RTF benchmark on NVIDIA L40S documented; backed by GGUF / vLLM / EXL2 inference backends; community A/B tests favorable for English and major European languages.
- **Latency** — Batched inference supported (batches of 32+); no native streaming but token-rate is low enough for chunked streaming. Multiple async backends (vLLM, llama.cpp).
- **Languages** — **14 languages**: English, Mandarin, Dutch, French, Georgian, German, Hungarian, Italian, Japanese, Korean, Latvian, Polish, Russian, Spanish.
- **Capabilities** — **Zero-shot voice cloning** via `interface.create_speaker("audio.wav")` saved to JSON; required speaker reference for best quality (otherwise random voice); no emotion tags. Recommended sampling: temp 0.4, rep_penalty 1.1 over a **64-token sliding window** (critical — full-context rep-penalty harms quality), top-k 40, top-p 0.9, min-p 0.05.
- **Hardware** — ~2-3 GB VRAM FP16 with HF backend; **runs in llama.cpp / GGUF** for CPU inference; community Q4 quantization available.
- **Official links** — https://github.com/edwko/OuteTTS ; https://www.outeai.com/ ; https://huggingface.co/OuteAI/OuteTTS-1.0-0.6B
- **Known limitations** — Generation capped at ~42 s per run (8,192 tokens) — must chunk for longer; no emotion tags; speaker quality depends critically on reference clip (no random-voice mode); no streaming.

## Chatterbox (Resemble AI)

- **Org / model / release / license** — Resemble AI; `ResembleAI/chatterbox`; mid-2025. **License: MIT**. (https://huggingface.co/ResembleAI/chatterbox ; https://github.com/resemble-ai/chatterbox)
- **Architecture & parameter count** — **0.5B Llama-based** speech-LLM with **HiFi-GAN-based vocoder (HiFTNet)**; trained on **0.5M hours of cleaned audio data**. Built-in **PerTh neural watermarking** (imperceptible, survives MP3 compression).
- **Quality metrics** — Resemble AI's published Podonos blind-listening benchmarks show **Chatterbox outperforms ElevenLabs** on listener preference — making it one of very few open-source TTS to claim parity / superiority with the leading closed model.
- **Latency** — Not formally reported; community measurements ~real-time on RTX 4090.
- **Languages** — **23 languages**: Arabic, Danish, German, Greek, English, Spanish, Finnish, French, Hebrew, Hindi, Italian, Japanese, Korean, Malay, Dutch, Norwegian, Polish, Portuguese, Russian, Swedish, Swahili, Turkish, Mandarin.
- **Capabilities** — **Zero-shot voice cloning** (`audio_prompt_path` argument); **unique emotion-exaggeration knob** (default `exaggeration=0.5`, `0.7+` for dramatic; pair with `cfg ~0.3` for deliberate pacing) — first open-source TTS with explicit emotion-exaggeration control; built-in audio watermarking by default; MIT-licensed for commercial use.
- **Hardware** — ~2-3 GB VRAM FP16.
- **Official links** — https://huggingface.co/ResembleAI/chatterbox ; demo Space https://huggingface.co/spaces/ResembleAI/Chatterbox ; PyPI `pip install chatterbox-tts`
- **Known limitations** — Sample rate not explicitly documented (use `model.sr`); no streaming; emotion control is a single scalar (less expressive than tag-based Orpheus / ChatTTS); no SSML.

## Microsoft SpeechT5

- **Org / model / release / license** — Microsoft; `microsoft/speecht5_tts`; 2022. **License: MIT**. (https://huggingface.co/microsoft/speecht5_tts ; paper https://arxiv.org/abs/2110.07205)
- **Architecture & parameter count** — Unified-modal encoder-decoder pre-trained on speech & text (T5-style), with 6 modal-specific pre/post-nets, cross-modal vector quantization for shared latent space. ~150M params for the TTS variant. Trained on **LibriTTS**.
- **Quality metrics** — Modest; predates the modern zero-shot-cloning era. Standard MOS ~3.8 on LJSpeech-tier benchmarks.
- **Latency** — Fast (seq2seq + HiFi-GAN vocoder pipeline).
- **Languages** — Trained English-only.
- **Capabilities** — Speaker control via **x-vector embeddings** (`Matthijs/cmu-arctic-xvectors`); no zero-shot reference cloning of arbitrary speakers; **16 kHz output**; fine-tuning supported via Transformers Trainer; **1,384+ community fine-tunes** on HF.
- **Hardware** — <1 GB VRAM; CPU-feasible.
- **Official links** — https://huggingface.co/microsoft/speecht5_tts ; https://github.com/microsoft/SpeechT5 ; paper https://arxiv.org/abs/2110.07205
- **Known limitations** — Pre-LLM-era quality (well behind 2024+ models); 16 kHz only; x-vector approach is not modern zero-shot cloning; included here mainly because of huge community fine-tune ecosystem and permissive MIT license — good baseline for cheap deployments.

## Step-Audio-TTS-3B (StepFun)

- **Org / model / release / license** — StepFun AI; `stepfun-ai/Step-Audio-TTS-3B` (released alongside Step-Audio paper, Feb 2025, arXiv:2502.11946). **License: Apache 2.0**. (https://huggingface.co/stepfun-ai/Step-Audio-TTS-3B)
- **Architecture & parameter count** — **Dual-codebook LLM** distilled from StepFun's 130B-parameter unified speech-text model. **~3B (4B on disk in BF16)** parameters. Specialized vocoder trained with dual-codebook approach plus a dedicated humming vocoder.
- **Quality metrics** — On Seed TTS benchmark: **test-zh CER 1.31%, test-en CER 2.31%, test-en WER 2.0%** — beats CosyVoice 2 (1.45 / 2.38 / 2.57) and is among the SOTA Chinese-English open models in 2025.
- **Latency** — Not formally reported; AR speech-LLM at 3B size implies ~0.3-0.5 RTF on RTX 4090.
- **Languages** — **Chinese & English** primarily; instruction-driven control extends to **dialects, emotions, singing, and RAP**.
- **Capabilities** — **First open-source TTS capable of RAP generation** and **humming generation** (specialized vocoder); instruction-driven dynamic control of dialect, emotion, singing style; trained via LLM-Chat paradigm with synthetic data.
- **Hardware** — ~8-10 GB VRAM FP16.
- **Official links** — https://huggingface.co/stepfun-ai/Step-Audio-TTS-3B ; https://github.com/stepfun-ai/Step-Audio ; paper https://arxiv.org/abs/2502.11946
- **Known limitations** — Bilingual focus; documentation primarily in Chinese; large VRAM for the 4B BF16 weights.

## PlayDiffusion (PlayHT) — adjacent

- **Org / model / release / license** — PlayHT / play.ai; `PlayHT/PlayDiffusion`; July 2025. **License: Apache 2.0**. (https://huggingface.co/PlayHT/PlayDiffusion)
- **Architecture & parameter count** — **Non-autoregressive diffusion-based speech editor/inpainter**, not a from-scratch TTS. Audio encoder → text-conditioned non-causal masked diffusion → **BigVGAN decoder**. 10K-token BPE tokenizer optimized for English. Speaker conditioning via embedding model.
- **Capabilities** — **Audio inpainting** is the primary use case (edit "Neo" → "Trinity" in an existing recording with no boundary artifacts); voice cloning via speaker embeddings; English-only; PlayHT's flagship **PlayDialog conversational TTS is NOT open-source** — only the diffusion-editing model is released.
- **Limitations** — Not a from-scratch text-to-speech; English only; useful as an *adjunct* to other TTS for editing.

## Models that are commonly mentioned but NOT open-source / weights-unavailable

- **Hume Octave / Octave 2** — closed API only. (https://www.hume.ai/octave-text-to-speech)
- **PlayDialog / PlayDialog 2.0** — closed API; only the audio-editing PlayDiffusion checkpoint is open.
- **Qwen3-TTS** — Alibaba Qwen org has a HF Space (`Qwen/Qwen3-TTS`) but no public weights as of May 2026; only API access via `chat.qwen.ai`.
- **Meta Voicebox / Audiobox (generative)** — research papers only; only the *audio-quality assessment* fork `facebook/audiobox-aesthetics` is openly weighted.
- **OpenAI gpt-4o-tts / gpt-4o-mini-tts** — closed API only.
- **ElevenLabs Multilingual v2 / Flash v2.5** — closed API only.
- **Microsoft VALL-E / VALL-E 2** — research papers; community implementations exist but quality lags Microsoft internal model.
- **Lightning v3.x** — referenced in TTS Arena V2 model-request discussions but no public weights as of May 2026.

---

## Comparison Table

| Model | License | Params | RTF | TTFB | Streaming | Voice cloning | Languages | Sample rate | VRAM (FP16) |
|---|---|---|---|---|---|---|---|---|---|
| Coqui XTTS-v2 | CPML (NC) | ~520M | 0.2-0.4 | ~300-500 ms | Yes | 6 s zero-shot | 17 | 24 kHz | ~4-6 GB |
| F5-TTS | CC-BY-NC 4.0 | 336M | 0.15 (16 NFE) | non-streaming | No | 4-10 s zero-shot | EN+ZH (+community) | 24 kHz | ~6 GB |
| E2-TTS (community) | CC-BY-NC 4.0 | 333M | 0.68 (32 NFE) | non-streaming | No | zero-shot | EN+ZH | 24 kHz | ~6 GB |
| StyleTTS 2 | MIT | ~148M | 0.0185 | <100 ms | Chunked | Reference style | EN | 24 kHz | <3 GB |
| Kokoro-82M v1 / v1.1-zh | Apache 2.0 | 82M | <0.1 (CPU OK) | <100 ms | No | No (fixed voices) | 8 / 2 | 24 kHz | <1 GB |
| MetaVoice-1B | Apache 2.0 | 1.2B | ~1.0 | n/a | No | 30 s zero-shot | EN | 24 kHz | ~6-8 GB |
| Suno Bark | MIT | ~340M-900M | 5-10× slower | n/a | No | Unofficial only | 13 | 24 kHz | 4-12 GB |
| Tortoise-TTS | Apache 2.0 (repo) | ~420M | minutes/sentence | n/a | No | 3-5 clips × 10 s | EN | 22.05 kHz | 4-8 GB |
| MyShell OpenVoice v2 | MIT | ~150-200M | ~real-time | n/a | No | Yes | 6 | ~24 kHz | 2-4 GB |
| GPT-SoVITS v2 | MIT | ~hundreds M | ~real-time | chunked | Chunked | Few-shot 1 min / zero-shot 3-10 s | 5 (ZH/EN/JA/KO/Yue) | 32 kHz | 4-6 GB |
| Fish Speech 1.5 | CC-BY-NC-SA 4.0 | ~500M-1B | 0.2-0.5 | chunked | Chunked | Short reference | 13 | 44.1 kHz | 6-8 GB |
| ChatTTS | CC-BY-NC 4.0 | ~200-400M | ~real-time | n/a | No | Random/sampled | EN+ZH | 24 kHz | ~4 GB |
| Parler-TTS Large v1 | Apache 2.0 | 2.2B | slow AR | token-level | Possible | Description only (no ref-audio) | EN | 44.1 kHz (DAC) | 10-12 GB |
| Parler-TTS Mini Multi v1.1 | Apache 2.0 | 0.9B | slow AR | token-level | Possible | Description only | 8 EU | 44.1 kHz | 4-6 GB |
| Meta MMS-TTS | CC-BY-NC 4.0 | ~36M each | very fast | <100 ms | No | No | 1,107 | 16 kHz | <1 GB |
| Sesame CSM-1B | Apache 2.0 | 1B | ~real-time | 150-250 ms | de facto | No (v1) | EN | 24 kHz (Mimi) | 3-4 GB |
| IndexTTS-1.5 | Apache 2.0 | ~1-1.5B | 0.2-0.4 | n/a | No | Short ref | EN+ZH | 24 kHz | 6-8 GB |
| IndexTTS-2 | Apache 2.0 | ~1.5B | similar | n/a | No | Short ref + duration/emotion | EN+ZH | 24 kHz | 6-8 GB |
| Spark-TTS 0.5B | CC-BY-NC-SA 4.0 | 0.5B | 0.1-0.3 | n/a | No | Yes + attribute control | EN+ZH | 24 kHz | ~2 GB |
| Orpheus 3B | Apache 2.0 | 3B (4B on disk) | streaming | **~100-200 ms** | Yes (native) | Yes + 8 voices + emotion tags | EN (+ community ML) | 24 kHz (SNAC) | 8-10 GB |
| Zonos v0.1 transformer | Apache 2.0 | ~1-1.5B | 0.5 (2× RT) | n/a | No | 10-30 s zero-shot | 5 | 44 kHz (DAC) | 6 GB+ |
| MARS5-TTS | AGPL-3.0 | 1.2B | 1-2× RT | n/a | No | 2-12 s shallow / deep clone | EN | 24 kHz | 20 GB+ |
| CosyVoice 2 0.5B | Apache 2.0 | 0.5B | streaming | **150 ms** | **Yes (bi-stream)** | Yes + savable IDs + instruct | 9 + 18 ZH dialects | 22.05 kHz | 3-4 GB |
| OuteTTS 1.0 0.6B | Apache 2.0 | 0.6B | batched fast | n/a | No | Yes (saved JSON) | 14 | DAC | 2-3 GB / GGUF CPU |
| Chatterbox | MIT | 0.5B | ~real-time | n/a | No | Yes + emotion exaggeration | 23 | model.sr | 2-3 GB |
| SpeechT5 | MIT | ~150M | fast | <100 ms | No | x-vector only | EN | 16 kHz | <1 GB |
| Step-Audio-TTS-3B | Apache 2.0 | ~3B (4B BF16) | 0.3-0.5 | n/a | No | Yes + RAP/humming/dialect/emotion | EN+ZH | 24 kHz | 8-10 GB |
| PlayDiffusion (adjacent) | Apache 2.0 | n/a | edit-only | n/a | No | Speaker emb | EN | n/a | n/a |

---

## Sources & Leaderboards

**Leaderboards:**
- TTS Arena V2 (current crowd-sourced ELO): https://huggingface.co/spaces/TTS-AGI/TTS-Arena-V2
- TTS Arena V1 (legacy): https://huggingface.co/spaces/TTS-AGI/TTS-Arena
- Seed-TTS evaluation set (used by many recent papers): https://github.com/BytedanceSpeech/seed-tts-eval

**Key model cards:**
- Coqui XTTS-v2: https://huggingface.co/coqui/XTTS-v2
- F5-TTS: https://huggingface.co/SWivid/F5-TTS
- E2-TTS (community in F5 repo): https://huggingface.co/SWivid/E2-TTS
- StyleTTS 2: https://github.com/yl4579/StyleTTS2
- Kokoro-82M: https://huggingface.co/hexgrad/Kokoro-82M
- Kokoro-82M v1.1-zh: https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh
- MetaVoice-1B: https://huggingface.co/metavoiceio/metavoice-1B-v0.1
- Suno Bark: https://huggingface.co/suno/bark
- Tortoise-TTS: https://huggingface.co/jbetker/tortoise-tts-v2
- MyShell OpenVoice v2: https://huggingface.co/myshell-ai/OpenVoiceV2
- GPT-SoVITS: https://huggingface.co/lj1995/GPT-SoVITS
- Fish Speech 1.5: https://huggingface.co/fishaudio/fish-speech-1.5
- ChatTTS: https://huggingface.co/2Noise/ChatTTS
- Parler-TTS Large v1: https://huggingface.co/parler-tts/parler-tts-large-v1
- Parler-TTS Mini Multilingual v1.1: https://huggingface.co/parler-tts/parler-tts-mini-multilingual-v1.1
- Meta MMS-TTS: https://huggingface.co/facebook/mms-tts
- Sesame CSM-1B: https://huggingface.co/sesame/csm-1b
- IndexTTS-1.5: https://huggingface.co/IndexTeam/IndexTTS-1.5
- IndexTTS-2: https://huggingface.co/IndexTeam/IndexTTS-2
- Spark-TTS 0.5B: https://huggingface.co/SparkAudio/Spark-TTS-0.5B
- Orpheus 3B: https://huggingface.co/canopylabs/orpheus-3b-0.1-ft
- SNAC codec (used by Orpheus): https://huggingface.co/hubertsiuzdak/snac_24khz
- Zonos v0.1 transformer: https://huggingface.co/Zyphra/Zonos-v0.1-transformer
- Zonos v0.1 hybrid: https://huggingface.co/Zyphra/Zonos-v0.1-hybrid
- MARS5-TTS: https://huggingface.co/CAMB-AI/MARS5-TTS
- CosyVoice 2 0.5B: https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B
- OuteTTS 1.0 0.6B: https://huggingface.co/OuteAI/OuteTTS-1.0-0.6B
- Chatterbox: https://huggingface.co/ResembleAI/chatterbox
- SpeechT5: https://huggingface.co/microsoft/speecht5_tts
- Step-Audio-TTS-3B: https://huggingface.co/stepfun-ai/Step-Audio-TTS-3B
- PlayDiffusion: https://huggingface.co/PlayHT/PlayDiffusion
- Plachta VALL-E X community impl: https://huggingface.co/Plachta/VALL-E-X
- facebook/audiobox-aesthetics (NOT generative): https://huggingface.co/facebook/audiobox-aesthetics

**Key papers (arXiv):**
- F5-TTS: https://arxiv.org/abs/2410.06885
- E2-TTS: https://arxiv.org/abs/2406.18009
- StyleTTS 2: https://arxiv.org/abs/2306.07691
- XTTS: https://arxiv.org/abs/2406.04904
- IndexTTS (1.5): https://arxiv.org/abs/2502.05512
- IndexTTS-2: https://arxiv.org/abs/2506.21619
- Spark-TTS: https://arxiv.org/abs/2503.01710
- CosyVoice 2: https://arxiv.org/abs/2412.10117
- CosyVoice 1: https://arxiv.org/abs/2407.05407
- Fish Speech: https://arxiv.org/abs/2411.01156
- Parler-TTS: https://arxiv.org/abs/2402.01912
- MMS: https://arxiv.org/abs/2305.13516
- SpeechT5: https://arxiv.org/abs/2110.07205
- Voicebox (Meta, weights closed): https://arxiv.org/abs/2306.15687
- Audiobox (Meta, weights closed): https://arxiv.org/abs/2312.15821
- VALL-E (Microsoft, weights closed): https://arxiv.org/abs/2301.02111
- VALL-E X (Microsoft, weights closed): https://arxiv.org/abs/2303.03926
- Seed-TTS (ByteDance, weights closed): https://arxiv.org/abs/2406.02430
- Step-Audio: https://arxiv.org/abs/2502.11946
- Tortoise-TTS technical report: https://arxiv.org/abs/2305.07243
- FireRedTTS: https://arxiv.org/abs/2409.03283
- MaskGCT: https://arxiv.org/abs/2409.00750
- SNAC: https://arxiv.org/abs/2410.14411
- BigVGAN: https://arxiv.org/abs/2206.04658
- HiFi-GAN: https://arxiv.org/abs/2010.05646