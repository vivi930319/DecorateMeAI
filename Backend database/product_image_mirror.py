"""Serve same-origin copies of brand product images.

``mirror_product_images.py --deploy`` publishes WebP copies to Firebase Hosting
and writes ``product_image_mirror.json`` only after the release is verified.
The database keeps the original brand URL; API payloads swap in the mirror so
brand hotlink protection (403 / Cloudflare challenge) never reaches visitors.
"""
import hashlib
import json
import os
import threading
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent / "product_image_mirror.json"

_lock = threading.Lock()
_state = {"mtime": None, "base": "", "images": {}}


def mirror_key(url):
    return hashlib.sha256(str(url).strip().encode("utf-8")).hexdigest()[:32]


def _images():
    try:
        mtime = MANIFEST_PATH.stat().st_mtime
    except OSError:
        return "", {}
    with _lock:
        if _state["mtime"] != mtime:
            try:
                manifest = json.loads(MANIFEST_PATH.read_text("utf-8"))
                _state.update(mtime=mtime, base=str(manifest.get("base") or "").rstrip("/"),
                              images=dict(manifest.get("images") or {}))
            except (OSError, ValueError):
                _state.update(mtime=mtime, base="", images={})
        return _state["base"], _state["images"]


def mirrored_image_url(url):
    """Return the published mirror for ``url``, or ``url`` unchanged."""
    if os.getenv("PRODUCT_IMAGE_MIRROR_DISABLED") == "1":
        return url
    value = str(url or "").strip()
    if not value:
        return url
    base, images = _images()
    path = images.get(value)
    return f"{base}{path}" if base and path else url
