"""Mirror storefront product images onto Firebase Hosting.

Brand sites (Dior, Estée Lauder, Bobbi Brown, Cloudflare-protected Lancôme …)
reject or challenge images embedded from decorate-me.web.app.  This script
downloads each product image server-side, stores a 600px WebP copy, publishes
the copies under https://decorate-me.web.app/product-images/ and then writes
``product_image_mirror.json``.  The API reads that manifest and serves the
same-origin copy; the original URL stays untouched in the database.

Usage:
    python mirror_product_images.py            # download/convert only
    python mirror_product_images.py --deploy   # download/convert + publish + manifest

Re-running is incremental: already converted URLs are skipped and Hosting only
receives files it does not already have.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from PIL import Image

from deploy_firebase_password_reset_fix import (
    API_ROOT, PUBLIC_ROOT, SITE_ID, access_token, api_headers, checked,
    current_release, version_files,
)
from product_image_mirror import MANIFEST_PATH, mirror_key

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "product_image_mirror"
CACHE_INDEX = CACHE_DIR / "index.json"
CATALOG_API = "http://127.0.0.1:5000/api/products"
MAX_SIDE = 600
WEBP_QUALITY = 82
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")


def catalog_image_urls() -> list[str]:
    urls, cursor = set(), None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        payload = checked(requests.get(CATALOG_API, params=params, timeout=120)).json()
        for item in payload.get("items") or []:
            url = str(item.get("sourceImageUrl") or item.get("imageUrl") or "").strip()
            if url.startswith("https://") and not url.startswith(PUBLIC_ROOT):
                urls.add(url)
        cursor = payload.get("nextCursor")
        if not cursor:
            return sorted(urls)


def fetch_url(url: str) -> str:
    """Ask resizing CDNs for a MAX_SIDE rendition instead of a stored tiny thumbnail."""
    parsed = urlsplit(url)
    if "/dw/image/" in parsed.path:  # Salesforce Commerce Cloud (Lancôme, YSL …) stores e.g. ?sw=70
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in {"sw", "sh"}]
        query += [("sw", str(MAX_SIDE)), ("sh", str(MAX_SIDE))]
        return urlunsplit(parsed._replace(query=urlencode(query)))
    return url


def _download(url: str) -> bytes:
    url = fetch_url(url)
    attempts = (
        {},  # several brand CDNs reject browser-like hotlink headers but not a plain fetch
        {"User-Agent": BROWSER_UA, "Accept": "image/webp,image/jpeg,image/png,*/*;q=0.8",
         "Referer": f"https://{requests.utils.urlparse(url).hostname}/"},
    )
    last_error = None
    for headers in attempts:
        for _ in range(2):
            try:
                response = requests.get(url, headers=headers, timeout=45)
                content_type = response.headers.get("content-type", "")
                if response.ok and content_type.startswith("image/"):
                    return response.content
                last_error = f"HTTP {response.status_code} {content_type}"
                break
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(1)
    raise RuntimeError(last_error or "download failed")


def convert(url: str) -> dict:
    key = mirror_key(url)
    target = CACHE_DIR / f"{key}.webp"
    try:
        with Image.open(io.BytesIO(_download(url))) as image:
            image.load()
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=WEBP_QUALITY, method=6)
            size = image.size
    except Exception as exc:  # keep going; failures are reported, originals stay in use
        return {"url": url, "error": f"{type(exc).__name__}: {exc}"[:300]}
    target.write_bytes(buffer.getvalue())
    return {"url": url, "fetchUrl": fetch_url(url), "path": f"/product-images/{key}.webp",
            "width": size[0], "height": size[1], "bytes": len(buffer.getvalue())}


def mirror(urls: list[str], workers: int) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    index = json.loads(CACHE_INDEX.read_text("utf-8")) if CACHE_INDEX.exists() else {}
    todo = [url for url in urls
            if not (url in index and "path" in index[url]
                    and index[url].get("fetchUrl") == fetch_url(url)
                    and (CACHE_DIR / Path(index[url]["path"]).name).exists())]
    print(f"catalog images={len(urls)} cached={len(urls) - len(todo)} to_download={len(todo)}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for done, result in enumerate(pool.map(convert, todo), 1):
            index[result["url"]] = {k: v for k, v in result.items() if k != "url"}
            if done % 100 == 0 or done == len(todo):
                CACHE_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
                print(f"  {done}/{len(todo)}", flush=True)
    CACHE_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    return index


def _gzip_asset(body: bytes) -> tuple[str, bytes]:
    compressed = gzip.compress(body, compresslevel=9, mtime=0)
    return hashlib.sha256(compressed).hexdigest(), compressed


def deploy(index: dict) -> dict:
    token = access_token()
    session = requests.Session()
    session.headers.update(api_headers(token))
    release = current_release(session)
    current_version = release["version"]
    files = version_files(session, current_version["name"])
    bodies = {}
    for url, entry in index.items():
        if "path" not in entry:
            continue
        digest, body = _gzip_asset((CACHE_DIR / Path(entry["path"]).name).read_bytes())
        files[entry["path"]] = digest
        bodies[digest] = body

    created = checked(session.post(
        f"{API_ROOT}/sites/{SITE_ID}/versions",
        json={"config": current_version.get("config") or {}, "labels": {"source": "product-image-mirror"}},
        timeout=60,
    )).json()
    version_name = created["name"]
    required, upload_url = set(), None
    paths = sorted(files)
    for start in range(0, len(paths), 1000):
        batch = {path: files[path] for path in paths[start:start + 1000]}
        populated = checked(session.post(
            f"{API_ROOT}/{version_name}:populateFiles", json={"files": batch}, timeout=180
        )).json()
        required.update(populated.get("uploadRequiredHashes") or [])
        upload_url = populated.get("uploadUrl") or upload_url
    unknown = required - set(bodies)
    if unknown:
        raise RuntimeError(f"Hosting requested {len(unknown)} existing site assets; aborting without release")

    upload_headers = api_headers(token)
    upload_headers["Content-Type"] = "application/octet-stream"

    def upload(digest: str) -> None:
        for attempt in range(3):
            try:
                checked(requests.post(f"{upload_url.rstrip('/')}/{digest}", headers=upload_headers,
                                      data=bodies[digest], timeout=120))
                return
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)

    print(f"uploading {len(required)} new image files", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(upload, sorted(required)))
    checked(session.patch(f"{API_ROOT}/{version_name}", params={"updateMask": "status"},
                          json={"status": "FINALIZED"}, timeout=60))
    released = checked(session.post(f"{API_ROOT}/sites/{SITE_ID}/releases",
                                    params={"versionName": version_name}, timeout=60)).json()

    published = {url: entry for url, entry in index.items() if "path" in entry}
    samples = list(published.values())[:: max(1, len(published) // 5)][:5]
    verified = all(
        (r := requests.get(f"{PUBLIC_ROOT}{entry['path']}", timeout=30)).ok
        and r.headers.get("content-type", "").startswith("image/webp")
        for entry in samples
    )
    if not verified:
        raise RuntimeError("Released, but sample mirrored images did not load; manifest not updated")
    manifest = {
        "base": PUBLIC_ROOT,
        "hostingVersion": version_name,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "images": {url: entry["path"] for url, entry in sorted(published.items())},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    return {"previousVersion": current_version["name"], "version": version_name,
            "release": released.get("name"), "uploaded": len(required), "mirrored": len(published)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true", help="publish to Firebase Hosting and write manifest")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    index = mirror(catalog_image_urls(), args.workers)
    failures = {url: entry["error"] for url, entry in index.items() if "error" in entry}
    total_bytes = sum(entry.get("bytes", 0) for entry in index.values())
    print(json.dumps({"converted": len(index) - len(failures), "failed": len(failures),
                      "totalMB": round(total_bytes / 1e6, 1),
                      "failureSamples": dict(list(failures.items())[:10])}, ensure_ascii=False, indent=2))
    if args.deploy:
        print(json.dumps(deploy(index), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"MIRROR_FAILED: {exc}", file=sys.stderr)
        raise
