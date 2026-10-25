"""Security audit for all EXTERNAL code and assets this project pulls in.

Three real risks this project carries, and what this script does about them:

1. MODEL FILES CAN EXECUTE CODE.
   PyTorch `.pth/.pt/.ckpt/.bin` files are Python *pickles*. `torch.load()` on a
   malicious checkpoint runs arbitrary code — a well-known supply-chain attack.
   Our Wav2Lip weights came from third-party mirrors, not an official release.
   This script scans the pickle OPCODES WITHOUT EXECUTING THEM and flags any
   import of os/subprocess/socket/builtins.eval and friends.

2. TAMPERING / SILENT SUBSTITUTION.
   Every external asset is hashed (SHA-256) into `security.lock.json`. Re-running
   the audit reports anything that CHANGED, APPEARED, or VANISHED since then.

3. VULNERABLE DEPENDENCIES.
   Runs `pip-audit` against the live CVE database when it is installed.

Usage:
    python -m scripts.security_audit            # full audit
    python -m scripts.security_audit --update   # accept current state as the baseline
    python -m scripts.security_audit --no-deps  # skip the (slow) CVE scan
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pickletools
import subprocess
import sys
import zipfile
from pathlib import Path

from core.config import ROOT_DIR

LOCKFILE = ROOT_DIR / "security.lock.json"

# Files that are executable-by-deserialization.
_PICKLE_EXT = {".pth", ".pt", ".ckpt", ".bin", ".pkl"}
# Things a legitimate model checkpoint never needs to import.
_DANGEROUS = {
    "os", "nt", "posix", "subprocess", "sys", "shutil", "socket", "requests",
    "urllib", "httpx", "builtins", "__builtin__", "commands", "pty", "ctypes",
    "importlib", "runpy", "pickle", "code", "webbrowser", "glob", "tempfile",
}
# Globals that are fine inside a checkpoint.
_EXPECTED_PREFIXES = ("torch", "collections", "numpy", "numpy.core", "_codecs",
                      "argparse", "omegaconf", "typing")

# Directories holding third-party code/assets we did not write.
_EXTERNAL_DIRS = ["tools", "storage/voices", "storage/presenter"]


def _sha256(path: Path, limit_mb: int = 2048) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except Exception as exc:
        return f"ERROR:{exc}"
    return h.hexdigest()


# ── 1. pickle / model-file malware scan ─────────────────────────────────────
def _pickle_globals(raw: bytes) -> set[str]:
    """Collect every module.attr a pickle imports — WITHOUT unpickling it."""
    found: set[str] = set()
    try:
        for op, arg, _pos in pickletools.genops(io.BytesIO(raw)):
            name = op.name
            if name in ("GLOBAL", "INST"):
                if isinstance(arg, str):
                    found.add(arg.replace(" ", "."))
            elif name == "STACK_GLOBAL":
                found.add("<stack_global>")   # operands are on the stack
    except Exception:
        pass
    return found


def _torch_safe_load(path: Path) -> tuple[bool | None, str]:
    """Authoritative check: can torch load this with weights_only=True?

    weights_only=True uses a RESTRICTED unpickler that refuses to execute
    arbitrary code and raises on any disallowed global. If it loads, the file
    provably contains only tensors and safe primitives. This is stronger than
    opcode inspection, so it is the primary verdict.
    Returns (safe, detail); safe=None means "could not determine".
    """
    try:
        import torch
    except Exception:
        return None, "torch not installed"
    try:
        torch.load(str(path), map_location="cpu", weights_only=True)
        return True, "weights_only=True load succeeded (no executable content)"
    except Exception as exc:
        msg = " ".join(str(exc).split())[:300]
        low = msg.lower()
        # A refusal naming a forbidden global is a genuine red flag.
        if ("global" in low or "unsupported" in low or "forbidden" in low
                or "not an allowed" in low or "weights_only" in low):
            return False, f"restricted unpickler REJECTED it: {msg}"
        return None, f"inconclusive: {msg}"


def _scan_pickle_file(path: Path) -> dict:
    """Assess whether a model file can execute code when loaded."""
    result = {"globals": [], "dangerous": [], "format": "raw-pickle", "verdict": "unknown"}
    try:
        if zipfile.is_zipfile(path):
            result["format"] = "torch-zip"
            with zipfile.ZipFile(path) as zf:
                data = b"".join(zf.read(n) for n in zf.namelist()
                                if n.endswith(".pkl"))[: 8 << 20]
                for n in zf.namelist():
                    if n.endswith((".py", ".pyc", ".dll", ".so", ".exe", ".bat", ".sh")):
                        result["dangerous"].append(f"embedded executable file: {n}")
        else:
            data = path.read_bytes()[: 8 << 20]

        # Opcode scan (supplementary). Legacy torch files concatenate several
        # pickles, so walk forward through each one rather than stopping at the
        # first - that bug previously produced a FALSE 'no imports' result.
        globals_found: set[str] = set()
        offset = 0
        for _ in range(6):
            try:
                chunk = data[offset:]
                if not chunk:
                    break
                last = 0
                for op, arg, pos in pickletools.genops(io.BytesIO(chunk)):
                    last = pos
                    if op.name in ("GLOBAL", "INST") and isinstance(arg, str):
                        globals_found.add(arg.replace(" ", "."))
                    elif op.name == "STACK_GLOBAL":
                        globals_found.add("<stack_global>")
                offset += last + 1
            except Exception:
                break
        result["globals"] = sorted(globals_found)[:40]
        for g in globals_found:
            if g.split(".")[0].strip() in _DANGEROUS:
                result["dangerous"].append(f"imports {g}")
    except Exception as exc:
        result["dangerous"].append(f"unreadable: {exc}")

    safe, detail = _torch_safe_load(path)
    result["verdict"] = {True: "SAFE", False: "UNSAFE", None: "UNVERIFIED"}[safe]
    result["detail"] = detail
    if safe is False:
        result["dangerous"].append(detail)
    return result


# ── 2. inventory + tamper detection ─────────────────────────────────────────
def _inventory() -> dict:
    inv: dict[str, dict] = {}
    for rel in _EXTERNAL_DIRS:
        base = ROOT_DIR / rel
        if not base.exists():
            continue
        skip_parts = {".git", "__pycache__", "node_modules", ".pytest_cache", "venv", ".venv"}
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if skip_parts & set(p.parts):
                continue      # VCS/build noise, not third-party code we rely on
            # Skip our own generated media.
            if p.suffix.lower() in {".jpg", ".png", ".mp4", ".wav", ".gif", ".srt"} \
                    and "presenter" not in str(p):
                continue
            try:
                size = p.stat().st_size
            except Exception:
                continue
            if size < 1024:
                continue
            key = str(p.relative_to(ROOT_DIR)).replace("\\", "/")
            entry = {"sha256": _sha256(p), "size": size}
            if p.suffix.lower() in _PICKLE_EXT:
                entry["scan"] = _scan_pickle_file(p)
            inv[key] = entry
    return inv


def _compare(old: dict, new: dict) -> tuple[list, list, list]:
    changed, added, removed = [], [], []
    for k, v in new.items():
        if k not in old:
            added.append(k)
        elif old[k].get("sha256") != v.get("sha256"):
            changed.append(k)
    for k in old:
        if k not in new:
            removed.append(k)
    return changed, added, removed


# ── 3. dependency CVE scan ──────────────────────────────────────────────────
def _pip_audit() -> list[str]:
    try:
        proc = subprocess.run([sys.executable, "-m", "pip_audit",
                               "--progress-spinner", "off", "-f", "json"],
                              capture_output=True, text=True, timeout=900)
    except Exception as exc:
        return [f"pip-audit unavailable ({exc}); install with: pip install pip-audit"]
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return ["pip-audit produced no parsable report"]
    out = []
    for dep in data.get("dependencies", []):
        vulns = dep.get("vulns") or []
        if vulns:
            ids = ", ".join(v.get("id", "?") for v in vulns[:3])
            fix = (vulns[0].get("fix_versions") or ["?"])[0]
            out.append(f"{dep.get('name')} {dep.get('version')}: {len(vulns)} vuln(s) "
                       f"[{ids}] -> fixed in {fix}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit external code and assets")
    ap.add_argument("--update", action="store_true", help="accept current state as baseline")
    ap.add_argument("--no-deps", action="store_true", help="skip the CVE scan")
    args = ap.parse_args()

    print("=" * 70)
    print(f"  SECURITY AUDIT — {ROOT_DIR}")
    print("=" * 70)

    inv = _inventory()
    print(f"\n[1] External assets tracked: {len(inv)}")

    # Malware scan results
    risky = {k: v["scan"] for k, v in inv.items()
             if v.get("scan") and v["scan"]["dangerous"]}
    pickles = [k for k, v in inv.items() if v.get("scan")]
    print(f"\n[2] Deserialization scan — {len(pickles)} model file(s) checked")
    if risky:
        print("    !! DANGEROUS CONTENT FOUND:")
        for k, scan in risky.items():
            print(f"      {k}")
            for d in scan["dangerous"]:
                print(f"         - {d}")
    elif pickles:
        for k in pickles:
            s = inv[k]["scan"]
            tag = {"SAFE": "OK ", "UNVERIFIED": "??", "UNSAFE": "!!"}.get(s.get("verdict"), "??")
            print(f"    {tag} {k}")
            print(f"         {s.get('verdict')}: {s.get('detail','')}")
            print(f"         format={s['format']}, imports seen={len(s['globals'])}")
    else:
        print("    (no pickle-format model files present)")

    # Tamper detection
    old = {}
    if LOCKFILE.exists():
        try:
            old = json.loads(LOCKFILE.read_text(encoding="utf-8")).get("assets", {})
        except Exception:
            old = {}
    print("\n[3] Integrity vs baseline")
    if not old:
        print("    no baseline yet — run with --update to create one")
    else:
        changed, added, removed = _compare(old, inv)
        if not (changed or added or removed):
            print(f"    OK  all {len(inv)} asset hashes match the baseline")
        else:
            for k in changed:
                print(f"    !! CHANGED: {k}")
            for k in added:
                print(f"    +  new:     {k}")
            for k in removed:
                print(f"    -  missing: {k}")

    # Dependency CVEs
    print("\n[4] Dependency vulnerabilities (pip-audit)")
    if args.no_deps:
        print("    skipped (--no-deps)")
    else:
        findings = _pip_audit()
        if not findings:
            print("    OK  no known vulnerabilities")
        else:
            for f in findings:
                print(f"    !! {f}")

    if args.update:
        LOCKFILE.write_text(json.dumps({"assets": inv}, indent=2), encoding="utf-8")
        print(f"\nBaseline written: {LOCKFILE.name} ({len(inv)} assets)")

    print("\nRe-run after ANY new model/tool download to catch tampering.\n")


if __name__ == "__main__":
    main()
