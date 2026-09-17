"""Deploy the product-detail foundation shade ladder to every foundation.

The Hosting source tree is not present locally.  This safely clones the current
Hosting release, replaces router.js only, validates it, and publishes the new
version while retaining every unchanged asset hash.
"""
from __future__ import annotations

import json
import sys
import time

import requests

from deploy_firebase_password_reset_fix import (
    API_ROOT, PUBLIC_ROOT, SITE_ID, access_token, api_headers, checked,
    compressed_asset, current_release, validate_javascript, version_files,
)


def patch_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise RuntimeError(f"Missing router marker: {label}")
    return source.replace(old, new, 1)


def patch_router(source: str) -> str:
    # Hosting currently serves CRLF; use one internal newline convention so the
    # structural markers remain stable across releases.
    source = source.replace("\r\n", "\n")
    helper_marker = "function shadeRecommendationHtml(p) {"
    helper = r'''// 商品詳情的三色階必須以「正在看的粉底」為錨點，而不是只沿用本次
// 個人化推薦的主推薦。後端 /shade-matches 已針對每支粉底算出較淺、最相近、
// 較深三個安全的色彩參考；這裡只負責讀取並顯示，不在瀏覽器重算色差。
function currentProductShadeRecommendation(p) {
    const own = p?.__foundationShadeLadder;
    if (own?.anchor) return own;
    const global = currentShadeRecommendation(p);
    const anchorId = String(global?.anchor?.product?.id ?? '');
    return anchorId && String(p?.id ?? '') === anchorId ? global : null;
}

function shadeRecommendationHtml(p) {'''
    source = patch_once(source, helper_marker, helper, "shade recommendation function")
    source = patch_once(
        source,
        "function shadeRecommendationHtml(p) {\n    const sr = currentShadeRecommendation(p);",
        "function shadeRecommendationHtml(p) {\n    const sr = currentProductShadeRecommendation(p);",
        "per-product shade recommendation call",
    )
    source = patch_once(
        source,
        """if (!sr || !sr.anchor) {
        if (!isFoundationProduct(p)) return '';""",
        """if (!sr || !sr.anchor) {
        if (!isFoundationProduct(p)) return '';
        if (p?.__foundationShadeLadderLoading) {
            return `<div class="shade-rec"><div class="shade-rec-empty">
                <p>正在讀取這支粉底的較淺／主推／較深色階…</p>
            </div></div>`;
        }""",
        "foundation ladder loading state",
    )
    loader_marker = "            const area = document.getElementById('productsArea');"
    loader = r'''            // 不論這支粉底是否是這次推薦的主推，都讀取它自己的三個色階。
            // 這是一個小型單品請求，色差在後端預先計算；不會重新下載整個商品目錄。
            if (isFoundationProduct(p) && !p.__foundationShadeLadderLoaded
                && !p.__foundationShadeLadderLoading && detailId
                && typeof Api !== 'undefined'
                && typeof Api.listFoundationShadeMatches === 'function') {
                p.__foundationShadeLadderLoading = true;
                Api.listFoundationShadeMatches(detailId, String(p.brand || ''), 3)
                    .then(result => {
                        const rows = Array.isArray(result?.shadeLadder) ? result.shadeLadder : [];
                        const toNode = (row) => {
                            const relation = String(row?.shadeMatch?.relation || '').trim();
                            const product = typeof Api._normalizeProduct === 'function'
                                ? Api._normalizeProduct(row) : row;
                            if (!product || !relation) return null;
                            const label = String(row?.shadeMatch?.label || (
                                relation === 'lighter' ? '較淺相近色' :
                                relation === 'darker' ? '較深相近色' : '主推膚色色號'
                            ));
                            const descriptions = {
                                lighter: '適合希望提亮膚色或呈現較明亮妝效時比較。',
                                closest: '這支是目前查看的主推色號。',
                                darker: '適合近期有日曬或偏好自然健康妝效時比較。'
                            };
                            return {
                                product, label, shadeCode: row?.shadeCode || product.shadeCode,
                                matchPercent: row?.shadeMatch?.matchPercent,
                                anchorDeltaE: relation === 'closest' ? null : row?.shadeMatch?.deltaE,
                                description: descriptions[relation] || '', relation
                            };
                        };
                        const nodes = rows.map(toNode).filter(Boolean);
                        const anchor = nodes.find(node => node.relation === 'closest');
                        if (anchor) {
                            p.__foundationShadeLadder = {
                                anchor,
                                lighter: nodes.find(node => node.relation === 'lighter') || null,
                                darker: nodes.find(node => node.relation === 'darker') || null,
                                method: 'lab_lightness_approximation',
                                disclaimer: '較淺／較深色號依色彩資料比對，請以實際至實體專櫃試色與購買體驗為準。'
                            };
                        }
                    })
                    .catch(() => null)
                    .finally(() => {
                        p.__foundationShadeLadderLoading = false;
                        p.__foundationShadeLadderLoaded = true;
                        if (Router.currentPage === 'products') renderProductDetail(id);
                    });
            }

            const area = document.getElementById('productsArea');'''
    return patch_once(source, loader_marker, loader, "per-product foundation ladder loader")


def deploy() -> dict:
    token = access_token()
    session = requests.Session()
    session.headers.update(api_headers(token))
    release = current_release(session)
    current_version = release["version"]
    files = version_files(session, current_version["name"])
    if "/js/router.js" not in files:
        raise RuntimeError("Current Hosting version is missing /js/router.js")
    router_source = checked(requests.get(
        f"{PUBLIC_ROOT}/js/router.js?foundation-ladder={int(time.time())}", timeout=30
    )).text
    router_source = patch_router(router_source)
    required = (
        "function currentProductShadeRecommendation(p)",
        "正在讀取這支粉底的較淺／主推／較深色階",
        "不論這支粉底是否是這次推薦的主推",
    )
    if not all(marker in router_source for marker in required):
        raise RuntimeError("Patched router.js failed required marker verification")
    validate_javascript("router.js", router_source)
    router_hash, router_body = compressed_asset(router_source)
    files["/js/router.js"] = router_hash
    created = checked(session.post(
        f"{API_ROOT}/sites/{SITE_ID}/versions",
        json={"config": current_version.get("config") or {},
              "labels": {"source": "foundation-ladder-every-product"}},
        timeout=30,
    )).json()
    version_name = created["name"]
    populated = checked(session.post(
        f"{API_ROOT}/{version_name}:populateFiles", json={"files": files}, timeout=90
    )).json()
    needed = populated.get("uploadRequiredHashes") or []
    if any(value != router_hash for value in needed):
        raise RuntimeError("Hosting unexpectedly requested an unchanged asset; aborting")
    upload_headers = api_headers(token)
    upload_headers["Content-Type"] = "application/octet-stream"
    for value in needed:
        checked(requests.post(
            f"{populated['uploadUrl'].rstrip('/')}/{value}", headers=upload_headers,
            data=router_body, timeout=90,
        ))
    checked(session.patch(
        f"{API_ROOT}/{version_name}", params={"updateMask": "status"},
        json={"status": "FINALIZED"}, timeout=30,
    ))
    released = checked(session.post(
        f"{API_ROOT}/sites/{SITE_ID}/releases", params={"versionName": version_name}, timeout=30
    )).json()
    verified = checked(requests.get(
        f"{PUBLIC_ROOT}/js/router.js?verify-foundation-ladder={int(time.time())}", timeout=30
    )).text
    return {"previousVersion": current_version["name"], "version": version_name,
            "release": released.get("name"), "uploadedFileCount": len(needed),
            "verified": all(marker in verified for marker in required)}


if __name__ == "__main__":
    try:
        print(json.dumps(deploy(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"DEPLOY_FAILED: {exc}", file=sys.stderr)
        raise
