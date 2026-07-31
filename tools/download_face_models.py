"""Download and verify the versioned face-analysis ONNX artifacts.

The large model binaries intentionally do not live in Git.  This script makes a
fresh clone deployable by restoring exactly the files declared in the manifest,
then checking both byte length and SHA-256 before they can enter a Docker image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(__file__).with_name("face_models_manifest.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid(path: Path, entry: dict) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == int(entry["size"])
        and _sha256(path) == str(entry["sha256"]).lower()
    )


def _gcloud() -> str:
    for name in ("gcloud", "gcloud.cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("找不到 gcloud CLI，請先安裝並登入 Google Cloud SDK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    prefix = str(manifest["gcsPrefix"]).rstrip("/")
    failures: list[str] = []

    for entry in manifest["files"]:
        target = ROOT / entry["path"]
        if _valid(target, entry):
            print(f"[OK] {entry['path']}")
            continue
        if args.verify_only:
            failures.append(entry["path"])
            print(f"[MISSING/INVALID] {entry['path']}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        if temporary.exists():
            temporary.unlink()
        source = f"{prefix}/{entry['object']}"
        subprocess.run([_gcloud(), "storage", "cp", source, os.fspath(temporary)], check=True)
        if not _valid(temporary, entry):
            temporary.unlink(missing_ok=True)
            failures.append(entry["path"])
            print(f"[HASH MISMATCH] {entry['path']}")
            continue
        temporary.replace(target)
        print(f"[DOWNLOADED] {entry['path']}")

    if failures:
        print("模型驗證失敗：" + ", ".join(failures), file=sys.stderr)
        return 1
    print(f"face model bundle {manifest['version']} verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
