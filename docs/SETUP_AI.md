# Setup guide — real LLM, natural voice, photoreal presenter

Run the doctor any time to see what's active and what's missing:

```bash
python -m scripts.doctor
```

Everything below is **free / open-source**. Nothing here is required to run the
$0 offline pipeline — these upgrade quality.

---

## 1. Real scripts with Ollama (free, local, recommended)

The offline **stub** writes templated prose. Ollama runs real open models locally
with no API key, turning the script/hook/title/research agents into genuinely
high-quality writers.

```bash
# Install Ollama:  https://ollama.com  (Windows installer available)
ollama pull llama3.1        # ~4.7 GB; or a smaller model (see below)
```

Then in `config/settings.yaml`:

```yaml
llm:
  provider: ollama
  model: llama3.1
```

Verify:

```bash
python -m scripts.doctor            # should show Ollama reachable + model present
python -m scripts.run_pipeline      # scripts are now real prose
```

**On a small GPU (e.g. NVIDIA MX550, 2 GB) or CPU:** prefer a small model so it
fits and stays fast:

```bash
ollama pull llama3.2:3b      # or qwen2.5:3b / phi3.5
```
```yaml
llm: { provider: ollama, model: "llama3.2:3b" }
```
Ollama automatically uses the GPU if it fits, else CPU. Smaller models also fix
the offline originality issue — real prose diverges far more than the stub, so
multiple distinct topics publish freely.

---

## 2. Natural female voice with Piper (free, CPU, fast)

```bash
pip install piper-tts
```

Download a **female** English voice from
<https://huggingface.co/rhasspy/piper-voices> (each voice = an `.onnx` + a
`.onnx.json`). Good picks: `en_US-amy-medium`, `en_GB-jenny_dioco-medium`.
Drop both files into `storage/voices/` (or set `PIPER_MODEL` / `tts.piper_model`).

```yaml
tts: { provider: piper, gender: female }
```

Coqui XTTS is an even more expressive option (`pip install TTS`, `tts.provider: coqui`);
it benefits from a GPU but runs on CPU too.

Verify: `python -m scripts.doctor` → Piper installed + voice model found.

---

## 3. Photoreal presenter "Aria" (needs an NVIDIA GPU)

Aria is a **fictional, AI-generated** persona (never a real person), disclosed as
AI in every description. Config: `agents/presenter_agent/config.yaml`.

### 3a. Her face — Stable Diffusion

```bash
pip install diffusers transformers accelerate torch   # CUDA build of torch
```
```yaml
# agents/presenter_agent/config.yaml
avatar_provider: stable_diffusion
```
Delete `storage/presenter/aria.png` once so it regenerates the photoreal face from
her fixed seed (keeps her consistent across every video).

> **VRAM note:** SD needs ~4–6 GB VRAM for comfort. A 2 GB MX550 will likely be
> very slow or run out of memory. Options: use a cloud GPU (Colab/RunPod) to
> pre-render `aria.png` once and commit it, or keep the stylized portrait.

### 3b. Lip-sync — SadTalker (or Wav2Lip)

```bash
git clone https://github.com/OpenTalker/SadTalker   # download its checkpoints per its README
```
Then set the command template in `agents/presenter_agent/config.yaml`:

```yaml
lipsync_provider: sadtalker
sadtalker_cmd: "python /path/SadTalker/inference.py --source_image {image} --driven_audio {audio} --result_dir {outdir} --still --preprocess full"
```
The agent runs it with `{image}`, `{audio}`, `{outdir}` filled in, then composites
the talking clip as picture-in-picture over the documentary.

### No GPU? Paid drop-in alternatives (optional, breaks strict $0)
- **Avatar/lip-sync:** HeyGen or D-ID API → implement behind `PresenterAgent._sadtalker`.
- **Voice:** ElevenLabs → add an `elevenlabs` branch in `core/media/tts.py`.
Both slot behind the existing interfaces; nothing else changes.

---

## Quick reference

| Want | Install | Config |
|---|---|---|
| Real scripts | Ollama + `ollama pull llama3.2:3b` | `llm.provider: ollama` |
| Natural voice | `pip install piper-tts` + voice `.onnx` | `tts.provider: piper` |
| Photoreal face | `pip install diffusers torch` (GPU) | `avatar_provider: stable_diffusion` |
| Talking head | SadTalker repo + checkpoints (GPU) | `lipsync_provider: sadtalker` + `sadtalker_cmd` |
