"""Deploy the before-makeup skin baseline contract to Firebase Hosting.

The web source is hosted only in Firebase.  This script clones the current
release, changes the two small JavaScript assets and cache-busts their script
URLs in index.html.  It never changes the database host or cloudflared.
"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

from deploy_firebase_password_reset_fix import (
    API_ROOT, PUBLIC_ROOT, SITE_ID, access_token, api_headers, checked,
    compressed_asset, current_release, validate_javascript, version_files,
)


def patch_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"Missing {label} marker")
    return source.replace(old, new, 1)


def patch_api(source: str) -> str:
    source = source.replace("\r\n", "\n")
    source = patch_once(source, """            const browLab      = this._labToArrayStrict(fa?.browLab ?? fa?.hairLab);

            const gen = analysisPackage?.generativeText || {};""", """            const browLab      = this._labToArrayStrict(fa?.browLab ?? fa?.hairLab);
            // The first, before-makeup analysis stores a clean skin baseline in
            // the same session package.  It is intentionally a narrow LAB-only
            // object: no image, account or other identity data leaves the page.
            const rawBaseline = fa?.baselineSkin;
            const baselineLab = this._labToArrayStrict(rawBaseline?.lab);
            const baselineSkin = (this._isUsableLab(baselineLab)
                && rawBaseline?.labReliable !== false
                && ['before_makeup', 'pre_makeup'].includes(String(rawBaseline?.source || '').toLowerCase()))
                ? {
                    lab: baselineLab,
                    season: String(rawBaseline.season || fa?.skinTone?.season || '').slice(0, 40),
                    level: String(rawBaseline.level || fa?.skinTone?.level || '').slice(0, 80),
                    labReliable: true,
                    source: 'before_makeup'
                } : null;

            const gen = analysisPackage?.generativeText || {};""", "baseline request preparation")
    source = patch_once(source, """                            lipLab: lipLab,
                            ...(browLab ? { browLab } : {}),""", """                            ...(baselineSkin ? { baselineSkin } : {}),
                            lipLab: lipLab,
                            ...(browLab ? { browLab } : {}),""", "baseline request field")
    source = patch_once(source, """    update(pkg, patch) {
        return { ...(pkg || this.create({ mode: 'basic' })), ...patch, updatedAt: new Date().toISOString() };
    },""", """    update(pkg, patch) {
        const previous = pkg || this.create({ mode: 'basic' });
        const facePatch = patch?.faceAnalysis;
        // Analysis corrections replace faceAnalysis as a whole.  Preserve the
        // original before-makeup baseline unless a caller deliberately supplies
        // a newer baseline, otherwise a post-makeup re-analysis could overwrite
        // the foundation reference.
        const faceAnalysis = facePatch ? {
            ...(previous.faceAnalysis || {}), ...facePatch,
            baselineSkin: facePatch.baselineSkin ?? previous.faceAnalysis?.baselineSkin ?? null
        } : previous.faceAnalysis;
        return {
            ...previous, ...patch,
            ...(facePatch ? { faceAnalysis } : {}),
            updatedAt: new Date().toISOString()
        };
    },""", "analysis package baseline preservation")
    return source


def patch_router(source: str) -> str:
    source = source.replace("\r\n", "\n")
    source = patch_once(source, """function userLabFor(kind) {
    const fa = Router.analysisPackage?.faceAnalysis;
    if (!fa) return null;
    const raw = kind === 'lip' ? fa.lipLab : fa.skinTone?.lab;""", """function foundationSkinTone() {
    const face = Router.analysisPackage?.faceAnalysis;
    const baseline = face?.baselineSkin;
    return (Array.isArray(baseline?.lab) && baseline.lab.length === 3)
        ? { ...(face?.skinTone || {}), ...baseline } : (face?.skinTone || null);
}

function userLabFor(kind) {
    const fa = Router.analysisPackage?.faceAnalysis;
    if (!fa) return null;
    const raw = kind === 'lip' ? fa.lipLab : foundationSkinTone()?.lab;""", "baseline display helper")
    source = patch_once(source,
                        "const reliable = Router.analysisPackage?.faceAnalysis?.skinTone?.labReliable !== false;",
                        "const reliable = foundationSkinTone()?.labReliable !== false;",
                        "baseline reliability display")
    source = patch_once(source,
                        "const skin = Router.analysisPackage?.faceAnalysis?.skinTone;\n    const lab = userLabFor('skin');",
                        "const skin = foundationSkinTone();\n    const lab = userLabFor('skin');",
                        "product detail skin display")
    source = patch_once(source,
                        "const skin = Router.analysisPackage?.faceAnalysis?.skinTone;\n    const lab = skin?.lab;",
                        "const skin = foundationSkinTone();\n    const lab = skin?.lab;",
                        "recommendation skin display")
    source = patch_once(source, """                    faceAnalysis: AnalysisPackage.fromRawFaceAnalysis(data, mode),
                    analysis: {""", """                    faceAnalysis: (() => {
                        const face = AnalysisPackage.fromRawFaceAnalysis(data, mode);
                        const existing = Router.analysisPackage?.faceAnalysis?.baselineSkin;
                        // A session captures its bare-skin reference once.  A
                        // render never replaces it, and later analysis edits
                        // preserve it through AnalysisPackage.update.
                        const source = (Array.isArray(existing?.lab) && existing.lab.length === 3)
                            ? existing : face.skinTone;
                        if (Array.isArray(source?.lab) && source.lab.length === 3
                            && source.lab.every(Number.isFinite) && source.labReliable !== false) {
                            face.baselineSkin = {
                                lab: source.lab.map(Number), season: source.season || null,
                                level: source.level || null, labReliable: true,
                                source: 'before_makeup'
                            };
                        }
                        return face;
                    })(),
                    analysis: {""", "capture before-makeup baseline")
    return source


def patch_index(source: str, tag: str) -> str:
    source, api_count = re.subn(r"js/api\.js\?v=[^\"']+", f"js/api.js?v=baseline-skin-{tag}", source, count=1)
    source, router_count = re.subn(r"js/router\.js\?v=[^\"']+", f"js/router.js?v=baseline-skin-{tag}", source, count=1)
    if api_count != 1 or router_count != 1:
        raise RuntimeError("Could not cache-bust api.js and router.js in index.html")
    return source


def deploy() -> dict:
    token = access_token()
    session = requests.Session()
    session.headers.update(api_headers(token))
    release = current_release(session)
    version = release["version"]
    files = version_files(session, version["name"])
    required_paths = ("/index.html", "/js/api.js", "/js/router.js")
    if any(path not in files for path in required_paths):
        raise RuntimeError("Current Hosting version is missing a baseline-contract asset")
    unique = str(time.time_ns())
    index = checked(requests.get(f"{PUBLIC_ROOT}/?baseline-source={unique}", timeout=30)).text
    api = checked(requests.get(f"{PUBLIC_ROOT}/js/api.js?baseline-source={unique}", timeout=30)).text
    router = checked(requests.get(f"{PUBLIC_ROOT}/js/router.js?baseline-source={unique}", timeout=30)).text
    api, router, index = patch_api(api), patch_router(router), patch_index(index, unique)
    for name, body in (("api.js", api), ("router.js", router)):
        validate_javascript(name, body)
    api_hash, api_body = compressed_asset(api)
    router_hash, router_body = compressed_asset(router)
    index_hash, index_body = compressed_asset(index)
    files.update({"/js/api.js": api_hash, "/js/router.js": router_hash, "/index.html": index_hash})
    created = checked(session.post(
        f"{API_ROOT}/sites/{SITE_ID}/versions",
        json={"config": version.get("config") or {}, "labels": {"source": "before-makeup-baseline"}},
        timeout=30,
    )).json()
    target = created["name"]
    populated = checked(session.post(f"{API_ROOT}/{target}:populateFiles", json={"files": files}, timeout=90)).json()
    bodies = {api_hash: api_body, router_hash: router_body, index_hash: index_body}
    needed = populated.get("uploadRequiredHashes") or []
    if any(item not in bodies for item in needed):
        raise RuntimeError("Hosting requested an unchanged asset; aborting")
    headers = api_headers(token)
    headers["Content-Type"] = "application/octet-stream"
    for item in needed:
        checked(requests.post(f"{populated['uploadUrl'].rstrip('/')}/{item}", headers=headers,
                              data=bodies[item], timeout=90))
    checked(session.patch(f"{API_ROOT}/{target}", params={"updateMask": "status"},
                          json={"status": "FINALIZED"}, timeout=30))
    released = checked(session.post(f"{API_ROOT}/sites/{SITE_ID}/releases",
                                    params={"versionName": target}, timeout=30)).json()
    verified = checked(requests.get(f"{PUBLIC_ROOT}/?baseline-verify={time.time_ns()}", timeout=30)).text
    return {"previousVersion": version["name"], "version": target,
            "release": released.get("name"),
            "verified": f"js/api.js?v=baseline-skin-{unique}" in verified
            and f"js/router.js?v=baseline-skin-{unique}" in verified,
            "uploadedFileCount": len(needed)}


if __name__ == "__main__":
    try:
        print(json.dumps(deploy(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"DEPLOY_FAILED: {exc}", file=sys.stderr)
        raise
