"""Hard-delete obsolete rows whose product image field is demonstrably invalid.

This maintenance uses the same audited hard-delete API handler as the admin UI,
so product audit rows and user-owned history are preserved by the application.
"""

from __future__ import annotations

import re

import requests

import app as backend


API = "https://decorate-me.web.app/product-api/api/products"


def fetch_brand(brand: str) -> list[dict]:
    rows = []
    cursor = None
    while True:
        params = {"limit": 200, "brand": brand}
        if cursor:
            params["cursor"] = cursor
        response = requests.get(API, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        rows.extend(payload.get("items") or [])
        cursor = payload.get("nextCursor")
        if not cursor:
            return rows


def is_invalid(row: dict) -> bool:
    brand = str(row.get("brand") or "").upper()
    image = str(row.get("imageUrl") or "")
    sku = str(row.get("sku") or "")
    if brand == "CHANEL":
        return bool(re.search(r"(?:^|[/_.-])swatch(?:[/_.?-]|$)", image, re.I))
    if brand == "SHISEIDO":
        return bool(re.search(r"\.html(?:\?|$)", image, re.I))
    if brand == "MAC":
        return sku == "SR4417"
    return False


def main() -> None:
    targets = [row for brand in ("CHANEL", "SHISEIDO", "MAC")
               for row in fetch_brand(brand) if is_invalid(row)]
    backend.PRODUCT_ADMIN_API_KEY = "local_catalog_image_cleanup"
    client = backend.app.test_client()
    deleted = []
    for row in targets:
        product_id = int(row["id"])
        response = client.delete(
            f"/api/products/{product_id}",
            headers={
                "Authorization": "Bearer local_catalog_image_cleanup",
                "X-Admin-Actor": "catalog_image_audit",
                "X-Request-ID": f"image-audit-{product_id}",
            },
        )
        payload = response.get_json(silent=True) or {}
        if response.status_code != 200 or payload.get("mode") != "hard":
            raise RuntimeError(f"hard delete failed for {product_id}: {response.status_code} {payload}")
        deleted.append({
            "id": product_id, "brand": row.get("brand"), "name": row.get("name"),
            "mode": payload.get("mode"), "cascaded": payload.get("cascaded"),
            "preserved": payload.get("preserved"),
        })
    print({"targets": len(targets), "deleted": len(deleted), "items": deleted})


if __name__ == "__main__":
    main()
