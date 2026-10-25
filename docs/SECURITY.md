# Security of external code and assets

This project pulls in third-party code (Wav2Lip, ComfyUI), model weights, Python
packages, and downloaded media. Each is a supply-chain surface. Run the audit
after **any** new download:

```bash
python -m scripts.security_audit
```
```bash
python -m scripts.security_audit --update   # accept current state as baseline
```

## What it checks

**1. Model files that can execute code.** PyTorch `.pth/.pt/.ckpt/.bin` files are
Python *pickles* — `torch.load()` on a malicious checkpoint runs arbitrary code.
This is a real, actively exploited attack. The audit's authoritative test is
`torch.load(weights_only=True)`, which uses a **restricted unpickler** that
refuses to execute code; if the file loads, it provably contains only tensors.
It also walks the pickle opcodes (without executing) looking for imports of
`os`, `subprocess`, `socket`, `builtins` and similar, and flags executables
embedded inside checkpoint archives.

**2. Tampering.** Every external asset is SHA-256 hashed into
`security.lock.json`. Re-running reports anything CHANGED, ADDED or REMOVED —
so a silently swapped model or a trojanised tool file is caught.

**3. Vulnerable dependencies.** Runs `pip-audit` against the live CVE database.

## Current status (last audited)

- `wav2lip_gan.pth` — **SAFE** (restricted load succeeded)
- `s3fd.pth` — **SAFE** (restricted load succeeded)
- ComfyUI — cloned from the **official** `comfyanonymous/ComfyUI`;
  `custom_nodes/` contains only shipped examples.
- Dependencies — project-critical packages patched (see below); no CVEs
  outstanding in anything this project imports.

### Patched: Pillow (the one that actually mattered)

`pip-audit` found **37 vulnerabilities in Pillow 12.3.0**. That was not
theoretical for us: the pipeline downloads **untrusted images** from Wikimedia,
Openverse and flickr and decodes them with Pillow, so a malicious image was a
real attack path. Upgraded to **Pillow 13.0.0** (a major version bump), then
re-verified: 34 tests pass and all three render paths — animation, subtitle
overlay, presenter badge — still work.

Also upgraded: `urllib3` 2.8.0, `certifi` 2026.10.23, `filelock`, `setuptools`.

**Untrusted input rule:** anything downloaded from the internet (images, video,
audio) is untrusted. Keep Pillow and ffmpeg current, since they are the two
components that parse it.

## Standing risks and rules

**ComfyUI custom nodes are the main danger.** Core ComfyUI is reputable, but
custom nodes are arbitrary Python executed at startup, installed from
third parties. Real credential-stealing nodes have shipped in the wild. Rules:

- Install custom nodes only from sources you have independently verified.
- Re-run `scripts.security_audit` immediately after installing any node.
- Prefer `.safetensors` models over `.ckpt`/`.pth` — safetensors cannot execute code.

**Model weights.** Our Wav2Lip weights came from third-party mirrors (the
official links are dead), which is why they are hash-pinned and scanned. Never
add a checkpoint without running the audit.

**Dependency isolation — DONE.** The project now runs from an isolated `.venv`.
The before/after `pip-audit` comparison is the clearest result of this work:

| Environment | Vulnerable packages |
|---|---|
| Global Python (shared with other projects) | **~20** — `pyjwt`, `pypdf`, `chromadb`, `gitpython`, `mcp`, `aiohttp`, ... |
| **Project `.venv`** (Mind_Vault deps only) | **0 — "No known vulnerabilities found"** |

Every CVE the audit had been reporting belonged to *other* projects sharing the
interpreter. Isolation also stops another project from silently downgrading a
package we pin as a security floor (see `requirements.txt`).

**Use the venv** for all project work:

```bash
.venv\Scriptsctivate
```
New machines get one automatically: `python -m scripts.setup_machine`.

**Downloaded media** (Internet Archive, Wikimedia) is processed by ffmpeg and
never executed. The licence gate in `core/media/stock_video.py` is a *copyright*
control, not a security one.

**Secrets** live only in `.env` / GitHub Secrets, never in code or YAML, and
`.env` is gitignored. Publishing stays credential-gated and dry-run by default.
