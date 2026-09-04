"""小型 Firestore REST client，供本機匯入／訓練腳本更新後台訓練批次。

訓練環境不必安裝 google-cloud-firestore；沿用既有 gcloud access token 流程，讓「後台
送去訓練」與「本機真的跑完」共用同一份 Firestore 紀錄。
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUNS_COLLECTION = "face_training_runs"
METRICS_COLLECTION = "face_model_metrics"
# 訓練機的心跳。放在自己的集合裡，不要混進 face_training_runs——後台是用
# createdAt 排序整個集合來列出最近批次的，混進去會讓心跳文件擠掉一筆真的批次。
WORKERS_COLLECTION = "face_training_workers"


def _gcloud_exe() -> str:
    for name in ("gcloud", "gcloud.cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("找不到 gcloud，請先安裝 Google Cloud SDK 並執行 gcloud auth login")


_TOKEN_CACHE: dict[str, float | str] = {"value": "", "expires": 0.0}


def _token(force_refresh: bool = False) -> str:
    """取 access token，並在記憶體裡快取。

    原本每一次讀寫都 spawn 一次 gcloud，單次約 1 秒。腳本一輪只寫兩三次還好，
    但 training_worker 是每隔幾秒輪詢一次，那就變成整台機器都在跑 gcloud。

    **快取時間不能當成有效期。** `gcloud auth print-access-token` 回的是 gcloud
    自己快取的那一張，它可能已經用掉大半壽命了。2026-08-26 就踩到：worker 在
    13:05 拿到一張，程式假設它還有 45 分鐘，實際上 13:22 就過期——之後每一次
    Firestore 呼叫都 401，而快取還理直氣壯地把同一張過期 token 遞出去。
    所以真正的防線是下面 `_open()` 的「遇到 401 就換一張再試」，這裡的時間
    只是為了少 spawn 幾次 gcloud。
    """
    now = time.time()
    if not force_refresh and _TOKEN_CACHE["value"] and now < float(_TOKEN_CACHE["expires"]):
        return str(_TOKEN_CACHE["value"])
    out = subprocess.run([_gcloud_exe(), "auth", "print-access-token"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode:
        raise RuntimeError(f"gcloud 取得 Firestore token 失敗：{out.stderr.strip()[:300]}")
    token = out.stdout.strip()
    _TOKEN_CACHE["value"] = token
    _TOKEN_CACHE["expires"] = now + 45 * 60
    return token


def _open(build_request, timeout: int = 60):
    """送出請求；遇到 401 就換一張新 token 再試一次。

    `build_request(token)` 要回傳一個 urllib Request——每次重試都重建，因為
    Authorization 標頭要換成新的 token。

    只重試 401，而且只重試一次。401 的意思是「這張憑證不被接受」，換一張是
    唯一有意義的補救；其他錯誤（400 資料有問題、404 找不到、503 對方掛了）
    重試都只是把同一個錯誤再做一次。
    """
    try:
        return urllib.request.urlopen(build_request(_token()), timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise
        return urllib.request.urlopen(build_request(_token(force_refresh=True)), timeout=timeout)


def _unwrap(value):
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "booleanValue", "timestampValue"):
        if key in value:
            return value[key]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "mapValue" in value:
        return {k: _unwrap(v) for k, v in (value["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in value:
        return [_unwrap(v) for v in (value["arrayValue"].get("values") or [])]
    if "nullValue" in value:
        return None
    return value


def _wrap(value):
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        # NaN 與 Infinity 不是合法的 JSON，送出去會被 Firestore 打回 400。
        # 而它們**會**出現：某一類在驗證集裡一張都沒有時，該類的 recall 就是 NaN。
        if value != value or value in (float("inf"), float("-inf")):
            return {"nullValue": None}
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, (list, tuple)):
        # Firestore **不支援陣列裡再放陣列**。混淆矩陣正是二維陣列，所以
        # 「訓練跑完、寫回結果」這一步會回 400——訓練白跑，紀錄還停在 running。
        # （2026-08-26 實測踩到：eye/face 都訓練完、ONNX 也匯出了，卻寫不進去。）
        #
        # 巢狀的整包轉成 JSON 字串。看得到內容、對得起來，只是不能用 Firestore
        # 的欄位查詢去查——而混淆矩陣本來就不是拿來查詢的東西。
        if any(isinstance(v, (list, tuple)) for v in value):
            return {"stringValue": json.dumps(value, ensure_ascii=False, allow_nan=False,
                                              default=str)}
        return {"arrayValue": {"values": [_wrap(v) for v in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {str(k): _wrap(v) for k, v in value.items()}}}
    return {"stringValue": str(value)}


def _url(project: str, collection: str, doc_id: str) -> str:
    from urllib.parse import quote
    return (f"https://firestore.googleapis.com/v1/projects/{quote(project, safe='')}"
            f"/databases/(default)/documents/{quote(collection, safe='')}/{quote(doc_id, safe='')}")


def get_document(project: str, collection: str, doc_id: str) -> dict | None:
    build = lambda tok: urllib.request.Request(  # noqa: E731
        _url(project, collection, doc_id), headers={"Authorization": f"Bearer {tok}"})
    try:
        with _open(build) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return {k: _unwrap(v) for k, v in (data.get("fields") or {}).items()}


def patch_document(project: str, collection: str, doc_id: str, updates: dict) -> None:
    from urllib.parse import quote
    fields = "&".join(f"updateMask.fieldPaths={quote(str(k), safe='')}" for k in updates)
    payload = json.dumps({"fields": {str(k): _wrap(v) for k, v in updates.items()}}).encode("utf-8")
    build = lambda tok: urllib.request.Request(  # noqa: E731
        f"{_url(project, collection, doc_id)}?{fields}", data=payload,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        method="PATCH")
    with _open(build):
        pass


def _run_query(project: str, body: dict) -> list[dict]:
    from urllib.parse import quote
    url = (f"https://firestore.googleapis.com/v1/projects/{quote(project, safe='')}"
           f"/databases/(default)/documents:runQuery")
    payload = json.dumps(body).encode("utf-8")
    build = lambda tok: urllib.request.Request(  # noqa: E731
        url, data=payload,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        method="POST")
    with _open(build) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    out = []
    for row in rows:
        doc = row.get("document")
        if not doc:
            continue
        record = {k: _unwrap(v) for k, v in (doc.get("fields") or {}).items()}
        record.setdefault("runId", doc.get("name", "").rsplit("/", 1)[-1])
        out.append(record)
    return out


def list_runs(project: str, status: str | None = None, limit: int = 20) -> list[dict]:
    """列出訓練批次，最舊的排前面。

    worker 要先做最早排隊的那一批：管理員按下按鈕的順序就是他想要的順序，
    後進先出會讓最早送的那一批永遠排在後面。
    """
    query: dict = {"from": [{"collectionId": RUNS_COLLECTION}], "limit": int(limit)}
    if status:
        # 只篩選、不在查詢裡排序。Firestore 對「用 A 篩選、用 B 排序」要求一個複合
        # 索引，沒有就回 400 Bad Request——而排隊中的批次一次不會超過個位數，
        # 拿回來自己排比為了它建一個索引划算。
        query["where"] = {"fieldFilter": {
            "field": {"fieldPath": "status"}, "op": "EQUAL", "value": {"stringValue": status}}}
        rows = _run_query(project, {"structuredQuery": query})
        return sorted(rows, key=lambda row: str(row.get("createdAt") or ""))
    query["orderBy"] = [{"field": {"fieldPath": "createdAt"}, "direction": "ASCENDING"}]
    return _run_query(project, {"structuredQuery": query})


FEEDBACK_COLLECTION = "face_feedback"
# 後台的欄位名是中文（使用者看到的那個），訓練那端用部位代號。
_TRAINABLE_FIELDS = {"臉型", "眉型", "眼型", "鼻型", "嘴型"}


def _list_collection(project: str, collection: str) -> list[tuple[str, dict]]:
    """讀出整個集合。分頁要跟到底，漏掉的那些會被當成不存在。"""
    from urllib.parse import quote
    base = (f"https://firestore.googleapis.com/v1/projects/{quote(project, safe='')}"
            f"/databases/(default)/documents/{quote(collection, safe='')}")
    out: list[tuple[str, dict]] = []
    page = ""
    while True:
        url = base + "?pageSize=300" + (f"&pageToken={page}" if page else "")
        build = lambda tok, u=url: urllib.request.Request(  # noqa: E731
            u, headers={"Authorization": f"Bearer {tok}"})
        with _open(build) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for doc in data.get("documents", []):
            out.append((doc["name"].rsplit("/", 1)[-1],
                        {k: _unwrap(v) for k, v in (doc.get("fields") or {}).items()}))
        page = data.get("nextPageToken") or ""
        if not page:
            return out


def create_run_from_accepted(project: str, worker_id: str) -> dict | None:
    """把尚未進批次的已採用修正收成一批（舊流程相容用）。

    正式 Worker 預設不再呼叫這條路徑；只有明確傳入 ``--auto-collect`` 才會使用。
    正常流程由管理員按「送去訓練」或「重新送訓這一批」建立 queued 批次，避免
    開機自動把同一批回饋反覆收成新的訓練序號。

    為什麼由訓練機建立批次，而不是後台按鈕
    --------------------------------------
    後台的「送訓」按在單一部位上——那是管理員的判斷，一次一個。如果每按一次就建立
    一個批次，訓練機會為了一個新樣本跑完整整一輪（實測約 8 分鐘），而一個樣本對
    489 張的訓練集不會有任何統計意義。

    所以按鈕只負責記錄判斷（`reviewDecisions`），成批這件事留到訓練機真的要開工時
    才做：那時候「累積了哪些」才是確定的。批次紀錄的證據力不受影響——它記的仍然是
    哪一筆回饋的哪個部位進了這次訓練，而那些決定全都是人在後台按的。

    只收 accepted 與 corrected：
      accepted  用使用者的標籤
      corrected 用管理員改判的標籤（管理員看得到影像，使用者是憑印象改的）
    """
    rows = _list_collection(project, FEEDBACK_COLLECTION)
    selections: dict[str, dict[str, str]] = {}
    excluded: list[dict] = []

    for job_id, row in rows:
        feedback_id = row.get("feedbackId") or f"FB-{job_id}"
        if row.get("trainingRunId"):
            continue                      # 已經進過某一批了
        decisions = row.get("reviewDecisions") or {}
        if not decisions:
            continue                      # 還沒覆核，不是排除，是還沒輪到
        corrections = row.get("corrections") or {}
        labels = row.get("reviewLabels") or {}
        fields: dict[str, str] = {}
        for field, decision in decisions.items():
            if decision not in ("accepted", "corrected") or field not in corrections:
                continue
            if field not in _TRAINABLE_FIELDS:
                continue                  # 側臉鼻型走 PRO 那條線，不在這個訓練集裡
            label = labels.get(field) if decision == "corrected" else corrections.get(field)
            if isinstance(label, str) and label.strip():
                fields[field] = label.strip()
        if not fields:
            continue
        if not row.get("contributed"):
            # 有判斷但沒有影像，訓練不了。列出來讓人知道它為什麼沒被用，
            # 而不是安靜地跳過——安靜跳過會讓人以為系統漏了它。
            excluded.append({"feedbackId": feedback_id, "reason": "沒有使用者同意保存的影像"})
            continue
        selections[feedback_id] = fields

    if not selections:
        return None

    import secrets
    run_id = "TR-" + secrets.token_hex(8)
    now = now_iso()
    run = {
        "runId": run_id,
        "status": "queued",
        "model": "ConvNeXt-Tiny",
        "createdAt": now,
        "queuedAt": now,
        "feedbackIds": sorted(selections),
        "selections": selections,
        "sampleCount": sum(len(f) for f in selections.values()),
        "excluded": excluded,
        "source": f"worker:{worker_id}",
    }
    patch_document(project, RUNS_COLLECTION, run_id, run)

    # 蓋回批次編號，這一筆才不會被下一批再收一次。
    for feedback_id in selections:
        job_id = feedback_id[3:] if feedback_id.startswith("FB-") else feedback_id
        try:
            patch_document(project, FEEDBACK_COLLECTION, job_id,
                           {"trainingRunId": run_id, "trainingQueuedAt": now})
        except Exception:
            # 蓋不上去頂多讓它下次再被收一次，不值得讓整批停下來。
            pass
    return run


def claim_run(project: str, run_id: str, worker_id: str) -> dict | None:
    """把一筆 queued 批次收下來，回傳批次內容；已經被別人收走就回 None。

    這裡是先讀再寫，不是原子操作。實務上只有一台訓練機，這個競態跑不出來；
    真的要跑兩台的話，這一段必須換成 Firestore 的 updateTime precondition，
    否則兩台會同時訓練同一批（結果不會錯，但會白跑一次八分鐘）。
    """
    run = get_document(project, RUNS_COLLECTION, run_id)
    if not run or run.get("status") != "queued":
        return None
    patch_document(project, RUNS_COLLECTION, run_id, {
        "status": "running",
        "startedAt": now_iso(),
        "workerId": worker_id,
        "error": None,
    })
    run["status"] = "running"
    return run


def fail_run(project: str, run_id: str, message: str) -> None:
    """把批次標成失敗，並留下**看得懂的**原因。

    訊息會直接顯示在後台的對話框裡，所以要寫給人看，不是貼一整段 traceback。
    截斷是必要的：Firestore 單一欄位有大小上限，而一段 PyTorch 的錯誤輕易就上千字。
    """
    patch_document(project, RUNS_COLLECTION, run_id, {
        "status": "failed",
        "finishedAt": now_iso(),
        "error": (message or "訓練失敗，但沒有取得錯誤訊息").strip()[:1500],
    })
    # 記錄先寫，再推告警指標——後台要看的原因不能因為推指標失敗而遺失。
    #
    # 為什麼失敗要另外推一個指標：心跳那條盯的是「訓練機不見了」。
    # 訓練機活得好好的、只是這個批次炸了，心跳照樣在跳，那條告警不會響，
    # 於是失敗只出現在後台畫面上——要有人主動去看才會發現。
    # 2026-08-26 使用者說「模型失敗也沒告訴我」，講的就是這個缺口。
    _push_failure_metric(project, run_id)


ALIVE_METRIC = "custom.googleapis.com/training_worker/alive"
FAILURE_METRIC = "custom.googleapis.com/training_worker/run_failed"
_LAST_METRIC_PUSH = {"at": 0.0}


def push_alive_metric(project: str, worker_id: str) -> None:
    """往 Cloud Monitoring 推一個「訓練機還活著」的點。

    為什麼要推到雲端，而不是只寫 Firestore 的心跳
    ----------------------------------------------
    訓練機跑在本機。它死掉的原因很可能**就是網路斷了**——2026-08-26 那次正是
    DNS 解析失敗。這種時候本機不可能自己寄信通知你，因為寄信也要網路。

    負責發現的東西，不能是可能壞掉的那個東西。所以改成反過來：訓練機定期
    往 Google 推一個點，Google 那邊用 conditionAbsent（指標消失就告警）盯著。
    斷網時推不上去，Google 就會發現「這個指標不見了」並寄信；網路回來之後
    點又進來，告警自動關閉。

    推送失敗不重要，安靜忽略：它只是告訴外界「我還在」，不是訓練的一部分。
    真的推不上去，正好就是應該被告警的那個狀態。
    """
    now = time.time()
    # Cloud Monitoring 對同一條時間序列有最小寫入間隔，而且自訂指標按量計費。
    # 每分鐘一點對「15 分鐘沒心跳就告警」已經綽綽有餘。
    if now - float(_LAST_METRIC_PUSH["at"]) < 60:
        return
    _LAST_METRIC_PUSH["at"] = now
    _write_time_series(project, ALIVE_METRIC, {"worker_id": worker_id})


def _write_time_series(project: str, metric_type: str, labels: dict) -> None:
    """往 Cloud Monitoring 寫一個點。失敗安靜忽略。"""
    stamp = datetime.now(timezone.utc).isoformat()
    body = {"timeSeries": [{
        "metric": {"type": metric_type, "labels": labels},
        # global 資源：這台機器不是 GCP 的資源，沒有 instance id 可以填。
        "resource": {"type": "global", "labels": {"project_id": project}},
        "points": [{"interval": {"endTime": stamp}, "value": {"doubleValue": 1.0}}],
    }]}
    try:
        payload = json.dumps(body).encode("utf-8")
        build = lambda tok: urllib.request.Request(  # noqa: E731
            f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries",
            data=payload,
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            method="POST")
        with _open(build, timeout=30):
            pass
    except Exception:
        pass


def _push_failure_metric(project: str, run_id: str) -> None:
    """批次失敗時推一個點，讓 Cloud Monitoring 寄信。

    刻意**不**節流——心跳每分鐘一點所以要節流，失敗很少見而且每一次都要知道。

    run_id 不當成指標標籤：每個批次的 id 都不一樣，當標籤會讓時間序列
    無限增生（Monitoring 對每條序列計費，而且基數爆掉之後查詢會變慢）。
    要知道是哪一個批次，去後台看——告警只需要說「有一個炸了」。
    """
    _write_time_series(project, FAILURE_METRIC, {})


def heartbeat(project: str, worker_id: str, state: str, detail: str = "") -> None:
    """訓練機回報「我還在」。

    後台需要它才能分辨兩件會被混為一談的事：批次還沒開始，是因為**訓練機沒開**，
    還是因為**訓練失敗了**。沒有心跳的話，管理員按下按鈕看到「已排隊」會以為壞掉。
    """
    try:
        patch_document(project, WORKERS_COLLECTION, worker_id, {
            "workerId": worker_id,
            "state": state,
            "detail": detail[:300],
            "lastSeenAt": now_iso(),
        })
    except Exception:
        # 心跳寫不進去不該讓訓練停下來——它只是狀態顯示，不是訓練的一部分。
        pass
    # Firestore 那份是給後台畫面看的（要有人打開才看得到）；
    # 這一份是給 Google 的告警看的（沒人看也會寄信）。兩份都要。
    push_alive_metric(project, worker_id)


def model_digests(model_dir: Path) -> dict:
    """算出模型目錄裡每個 ONNX 的 sha256。

    這是把「這次訓練」跟「線上跑的那顆模型」綁在一起的那一環。少了它，紀錄只能
    證明「有一次訓練跑完、分數從 A 變成 B」，不能證明線上那顆就是它的產物——
    中間有人手動換掉模型，紀錄看不出來。tools/face_models_manifest.json 存的是
    同一種雜湊，兩邊可以直接比對。
    """
    digests = {}
    for onnx in sorted(Path(model_dir).glob("*.onnx")):
        digest = hashlib.sha256()
        with onnx.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digests[onnx.stem] = digest.hexdigest()
    return digests


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def macro_std_error(best: dict) -> float | None:
    """macro accuracy 的標準誤。取不到就回 None，不要用 0 冒充——0 代表「毫無誤差」。

    macro accuracy 是各類別 recall 的平均，所以

        Var(macro) = (1/K²) · Σ_c  recall_c · (1 - recall_c) / n_c

    其中 n_c 是該類別在保留集裡的張數（混淆矩陣的列和）。類別越小、recall 越接近
    0.5，它對誤差的貢獻越大——2 類的鼻型只要有一類樣本少，整體誤差就會明顯放大。

    為什麼需要它：保留集是 613 張、197 個身分，而部位各自只用得到其中一部分。
    在這個規模下，兩個批次差兩個百分點完全可能只是抽樣造成的。先前的換上線檢查
    拿一個沒有誤差範圍的數字當確定的事實，任何負數都整批擋下——那對訓練結果不公平，
    因為它把雜訊講成退步。`online_trust_score --by-version` 早就會印 Wilson 區間，
    理由一模一樣，只是那時沒有一併套到這裡。

    注意這是**保守**估計：兩次評分用的是同一批保留集影像，成對比較的變異其實更小。
    保守的方向是「比較容易說看不出差別」，所以判定退步時要更有把握才會擋。
    """
    recalls = best.get("per_class_recall")
    matrix = best.get("confusion_matrix")
    if not isinstance(recalls, (list, tuple)) or not isinstance(matrix, (list, tuple)):
        return None
    if not recalls or len(recalls) != len(matrix):
        return None
    total = 0.0
    for recall, row in zip(recalls, matrix):
        if not isinstance(recall, (int, float)) or not isinstance(row, (list, tuple)):
            return None
        n_c = sum(value for value in row if isinstance(value, (int, float)))
        if n_c <= 0:
            return None
        total += float(recall) * (1.0 - float(recall)) / float(n_c)
    return math.sqrt(total) / len(recalls)


def read_model_metrics(model_dir: Path) -> dict:
    """讀目前 ConvNeXt 模型的正式指標，供 training_runs 的 before/after 使用。"""
    result = {"architecture": "ConvNeXt-Tiny", "parts": {}}
    for part in ("face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape"):
        classes_path = model_dir / f"{part}_classes.json"
        metrics_path = model_dir / f"{part}_metrics.json"
        try:
            classes = json.loads(classes_path.read_text(encoding="utf-8"))
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            identity = metrics.get("identity") or {}
            best = identity.get("best") or {}
            result["parts"][part] = {
                "architecture": classes.get("architecture", "convnext_tiny"),
                "macroAccuracy": best.get("macro_accuracy"),
                "accuracy": best.get("accuracy"),
                # 有了樣本數與標準誤，後台才有辦法說「這個差距在誤差內」而不是
                # 把 -2.6 講得像確定退步。少了它們，畫面只能假裝數字是精確的。
                "valCount": best.get("val_count") or identity.get("val_count"),
                "macroStdErr": macro_std_error(best),
                "classes": classes.get("classes", []),
                "metricsFile": str(metrics_path),
            }
        except (OSError, ValueError, TypeError):
            continue
    return result


def publish_live_model_metrics(project: str, model_dir: Path) -> dict:
    """把「線上目錄現在實際是什麼分數」寫成 face_model_metrics/current。

    Gateway 已經優先讀這一份，讀不到才退回「往回找最後一個回報該部位的歷史批次」。
    而那個退路在換過一次模型之後就會過時：線上臉型已經是 53.4%，後台仍拿 46.6%
    去比，於是一個 48.9% 的批次被畫成 +2.3，其實是 -4.5。使用者按下換上線，
    才被 promote_model 用真實數字擋回來——按鈕在被按之前就講錯了。

    所以換上線一成功就把這份寫回去。這只能在訓練機上做：線上模型檔在它的檔案系統，
    Cloud Run 讀不到。
    """
    metrics = read_model_metrics(model_dir)
    patch_document(project, METRICS_COLLECTION, "current", {
        **metrics,
        "model": metrics.get("architecture", "ConvNeXt-Tiny"),
        "updatedAt": now_iso(),
        "source": "promotion",
    })
    return metrics
