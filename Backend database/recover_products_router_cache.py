"""Force browsers onto the verified router asset after a bad Hosting release."""
from __future__ import annotations

import json
import re
import sys
import time

import requests

from deploy_firebase_password_reset_fix import (
    API_ROOT, PUBLIC_ROOT, SITE_ID, access_token, api_headers, checked,
    compressed_asset, current_release, version_files,
)


def deploy() -> dict:
    token = access_token()
    session = requests.Session()
    session.headers.update(api_headers(token))
    release = current_release(session)
    version = release["version"]
    files = version_files(session, version["name"])
    index = checked(requests.get(f"{PUBLIC_ROOT}/?router-recovery={int(time.time())}", timeout=30)).text
    cache_tag = str(int(time.time()))
    updated, count = re.subn(
        r"js/router\.js\?v=[^\"']+",
        f"js/router.js?v=product-page-recovery-{cache_tag}",
        index,
        count=1,
    )
    if count != 1:
        raise RuntimeError("router.js cache marker was not found in index.html")
    index_hash, index_body = compressed_asset(updated)
    files["/index.html"] = index_hash
    created = checked(session.post(
        f"{API_ROOT}/sites/{SITE_ID}/versions",
        json={"config": version.get("config") or {}, "labels": {"source": "product-page-router-recovery"}},
        timeout=30,
    )).json()
    target = created["name"]
    populated = checked(session.post(
        f"{API_ROOT}/{target}:populateFiles", json={"files": files}, timeout=90
    )).json()
    required = populated.get("uploadRequiredHashes") or []
    if any(value != index_hash for value in required):
        raise RuntimeError("Hosting requested an unchanged asset; aborting recovery")
    headers = api_headers(token)
    headers["Content-Type"] = "application/octet-stream"
    for value in required:
        checked(requests.post(
            f"{populated['uploadUrl'].rstrip('/')}/{value}", headers=headers, data=index_body, timeout=90
        ))
    checked(session.patch(
        f"{API_ROOT}/{target}", params={"updateMask": "status"}, json={"status": "FINALIZED"}, timeout=30
    ))
    released = checked(session.post(
        f"{API_ROOT}/sites/{SITE_ID}/releases", params={"versionName": target}, timeout=30
    )).json()
    verify = checked(requests.get(f"{PUBLIC_ROOT}/?verify-router-recovery={time.time_ns()}", timeout=30)).text
    marker = f"js/router.js?v=product-page-recovery-{cache_tag}"
    return {"version": target, "release": released.get("name"), "verified": marker in verify}


if __name__ == "__main__":
    try:
        print(json.dumps(deploy(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"RECOVERY_FAILED: {exc}", file=sys.stderr)
        raise
