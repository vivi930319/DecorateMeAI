"""高風險管理操作的稽核紀錄（P1「權限與管理員」）。

要回答的問題只有一個：**「這筆資料是誰刪的、什麼時候刪的？」**

刻意不記錄的東西比記錄的還重要。稽核 log 一旦寫進 email、商品內容或請求 body，
它自己就變成第二份會員名冊——出事時外洩的範圍反而比原始資料庫更廣，因為稽核紀錄
通常保存得更久、權限也開得更鬆。所以這裡只留：

- `actorId`：管理員的**不可逆雜湊**（跟 Gateway 其他地方用同一個 `opaque_actor_id`），
  同一位管理員在不同事件之間對得起來，但無法從紀錄反推是誰。
- `targetRef`：被操作的對象。商品 ID 不是個資，原樣保留；會員一律先雜湊。
- 動作、結果狀態碼、requestId、時間。

保存期限交給 Firestore TTL（`expiresAt` 欄位），跟限流計數器同一套做法。
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import job_store

AUDIT_COLLECTION = os.getenv("ADMIN_AUDIT_COLLECTION", "admin_audit_events")
AUDIT_RETENTION_DAYS = max(1, int(os.getenv("ADMIN_AUDIT_RETENTION_DAYS", "180")))

_logger = logging.getLogger("ai-gateway.audit")


def record_admin_action(
    action: str,
    *,
    actor_id: str,
    target_ref: str = "",
    status_code: int = 0,
    request_id: str = "",
    **extra,
) -> dict:
    """寫一筆稽核事件並回傳它。永遠不丟例外。

    稽核失敗不能把使用者本來要做的事一起弄掉：刪商品已經成功了，卻因為寫不進稽核
    而回一個錯誤給管理員，只會讓他再按一次、再刪一次。寫不進去就至少留在服務 log 裡
    （那份 log 有遮罩，見 api_errors.RedactingFormatter）。
    """
    now = datetime.now(timezone.utc)
    event = {
        "eventId": uuid.uuid4().hex,
        "action": str(action)[:64],
        "actorId": str(actor_id or "")[:64],   # 已是雜湊，呼叫端負責
        "targetRef": str(target_ref or "")[:128],
        "statusCode": int(status_code or 0),
        "outcome": "success" if 200 <= int(status_code or 0) < 300 else "failure",
        "requestId": str(request_id or "")[:128],
        "at": now.isoformat(),
        "expiresAt": now + timedelta(days=AUDIT_RETENTION_DAYS),
    }
    for key, value in extra.items():
        # 只收純量。傳進來的 dict／list 很可能就是請求 body——那正是不該落地的東西。
        if isinstance(value, (str, int, float, bool)) or value is None:
            event[key] = value
    try:
        job_store.create(AUDIT_COLLECTION, event["eventId"], event)
    except Exception:  # noqa: BLE001
        _logger.warning(
            "audit_write_failed action=%s actor=%s status=%s",
            event["action"], event["actorId"], event["statusCode"],
        )
    _logger.info(
        "admin_action action=%s actor=%s target=%s status=%s request_id=%s",
        event["action"], event["actorId"], event["targetRef"],
        event["statusCode"], event["requestId"],
    )
    return event


def recent_admin_actions(limit: int = 100) -> list[dict]:
    """最近的稽核事件，新到舊。給管理後台的稽核頁用。"""
    try:
        events = job_store.all_jobs(
            AUDIT_COLLECTION,
            limit=max(1, min(int(limit), 500)),
            order_by="at",
            descending=True,
        )
    except Exception:  # noqa: BLE001
        return []
    return events
