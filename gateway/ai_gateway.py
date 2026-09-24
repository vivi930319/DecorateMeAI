import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from urllib.parse import quote, unquote, urlsplit

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from admin_audit import record_admin_action, recent_admin_actions
from api_errors import install_api_error_handling, rate_limited_error, secret_equals
from fastapi.responses import JSONResponse, RedirectResponse, Response
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
from pydantic import BaseModel, Field

from dev_server_utils import get_cors_origins
import job_store


@dataclass(frozen=True)
class Upstream:
    base_url: str
    api_key: str
    client_api_key: str
    allowed_paths: tuple[re.Pattern[str], ...]
    requires_upstream_api_key: bool = True
    requires_cloud_run_iam: bool = True
    required_in_production: bool = True


FACE_JOB_ID = r"JOB-[0-9a-f]{12}"
RENDER_JOB_ID = r"[0-9a-f]{32}"


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rf"^{value}$") for value in values)


def _service_url(env_name: str) -> str:
    return os.getenv(env_name, "").strip().rstrip("/")


ALLOW_EXTERNAL_TEXT_UPSTREAM = os.getenv("GATEWAY_ALLOW_EXTERNAL_TEXT_UPSTREAM", "").strip().lower() in {"1", "true", "yes", "on"}


# 使用者修正的集合名。跟 face_feedback.FEEDBACK_COL 是同一個字串——
# 那邊是寫入方、這裡是讀取方，兩邊都直接讀同一個 Firestore 集合。
# 改名的話兩處要一起改；沒有共用模組是因為 gateway 與 face 是兩個部署，
# 為了一個常數多一個共用檔不划算，但值得在這裡指出關聯。
FACE_FEEDBACK_COL = "face_feedback"
FACE_TRAINING_RUNS_COL = "face_training_runs"
# BASIC 五官分類的訓練集只吃這五個部位。側臉鼻型是 PRO 的模型，不在這裡。
# 這份清單必須跟 training/training_run_store.py 的 _TRAINABLE_FIELDS 一致——
# 兩邊不一致的症狀是「批次建得起來但訓練一定失敗」，而那筆回饋會被蓋上
# trainingRunId 之後永遠不再被收。
BASIC_TRAINABLE_FIELDS = frozenset({"臉型", "眉型", "眼型", "鼻型", "嘴型"})
# 訓練機的心跳。後台需要它才能分辨「批次還在排隊是因為訓練機沒開」與
# 「訓練失敗了」——兩者在畫面上長得一樣，處理方式卻完全不同。
FACE_TRAINING_WORKERS_COL = "face_training_workers"
# 換模型上線的請求。Gateway 只負責記下「要換哪個批次的哪些部位」——模型檔在訓練機
# 的檔案系統上，雲端這裡碰不到，所以實際的複製、類別檢查與 manifest 更新都由
# tools/promote_model.py 在本機執行，跟訓練批次是同一套「後台下單、本機執行」的模式。
FACE_MODEL_PROMOTIONS_COL = "face_model_promotions"
# 純部署請求：不換模型，只把目前的程式碼重新建置並部署。
# 換模型那條路徑本來就會部署，這一條是給「只改了程式碼」的情況用的。
FACE_DEPLOYMENTS_COL = "face_service_deployments"
# 能從後台觸發的服務。Ollama 建議服務不在裡面——它跑在另一台機器上，
# 這邊的訓練機碰不到，列進來只會做出一顆按了沒反應的按鈕。
DEPLOYABLE_SERVICES = ("face", "gateway", "render")
# 這份清單必須跟 tools/promote_model.py 的 PARTS 一致。兩邊都是寫死的中文部位名，
# 因為後台、回饋表與訓練報告用的都是中文；不一致時 worker 會找不到對應檔名而整批失敗。
PROMOTABLE_PARTS = ("臉型", "眉型", "眼型", "鼻型", "唇型")
FACE_MODEL_METRICS_COL = "face_model_metrics"

# 中文部位名 → 模型檔的部位代號。換上線請求記的是中文（後台、回饋表、訓練報告都用
# 中文），但分數是以代號為鍵存在 face_model_metrics 的 parts 底下，要比較就得換算。
# 這份對應在 training/import_feedback_samples.py 與 tools/apply_review.py 也各有一份；
# Gateway 匯入不到那兩個模組（容器裡的檔案是攤平複製的，training/ 不在裡面），
# 所以這裡只能再寫一次。改任何一份都要三份一起改。
PART_MODEL_KEYS = {
    "臉型": "face_shape", "眉型": "brow_shape", "眼型": "eye_shape",
    "鼻型": "nose_shape", "唇型": "lip_shape",
}

# 「這筆還沒做完」的狀態。換模型與部署共用同一組，因為兩邊的生命週期一樣：
#   queued → claimed → running → deployed / prepared / failed
#
# running 一定要在裡面。 換模型那條路徑原本只擋 queued 與 claimed，而 running
# 正是 build 加部署那幾分鐘——一筆請求絕大部分的時間都待在那裡。漏掉它等於
# 「只有在訓練機還沒撿走的那幾秒內」才擋得住連按，而人會連按的時機恰恰是
# 進度看起來停住的時候，也就是 running。
IN_FLIGHT_STATUSES = {"queued", "claimed", "running"}

UPSTREAMS = {
    "face-basic": Upstream(
        base_url=_service_url("FACE_BASIC_URL"),
        api_key=os.getenv("UPSTREAM_FACE_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_FACE_API_KEY", ""),
        allowed_paths=_patterns(
            r"health",
            r"v1/face/pose",
            r"v1/face/analyze/basic",
            r"v1/face/jobs/basic",
            rf"v1/face/jobs/{FACE_JOB_ID}",
            rf"v1/face/jobs/{FACE_JOB_ID}/result",
            # 使用者對五官判斷的修正。與 /result 同一套 job token 驗證，
            # 不放行的話端點做好了也進不來。
            rf"v1/face/jobs/{FACE_JOB_ID}/feedback",
        ),
    ),
    "face-pro": Upstream(
        base_url=_service_url("FACE_PRO_URL"),
        api_key=os.getenv("UPSTREAM_FACE_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_FACE_API_KEY", ""),
        allowed_paths=_patterns(
            r"health",
            r"v1/face/analyze/pro",
            r"v1/face/jobs/pro",
            rf"v1/face/jobs/{FACE_JOB_ID}",
            rf"v1/face/jobs/{FACE_JOB_ID}/result",
            rf"v1/face/jobs/{FACE_JOB_ID}/feedback",
        ),
    ),
    "render-service": Upstream(
        base_url=_service_url("RENDER_URL"),
        api_key=os.getenv("UPSTREAM_RENDER_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_RENDER_API_KEY", ""),
        allowed_paths=_patterns(
            r"health",
            r"render",
            r"render/jobs",
            rf"render/jobs/{RENDER_JOB_ID}",
            # Ownership-sensitive render routes (signed-url, content, retain,
            # artifact, media/*, users/*) are deliberately absent.  The Gateway
            # reaches them through _render_internal_request(), which builds the
            # upstream URL directly and never consults this allowlist, so the
            # browser has no reason — and no way — to call them.
        ),
    ),
    "text-suggestion": Upstream(
        base_url=_service_url("TEXT_SUGGESTION_URL"),
        api_key=os.getenv("UPSTREAM_TEXT_SUGGESTION_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_TEXT_SUGGESTION_API_KEY", ""),
        allowed_paths=_patterns(
            r"health",
            r"suggest",
        ),
        requires_upstream_api_key=False,
        requires_cloud_run_iam=False,
        required_in_production=ALLOW_EXTERNAL_TEXT_UPSTREAM,
    ),
    # Member API calls use the signed session as the access control.  The
    # database URL and any upstream credential stay inside Cloud Run.
    "member-database": Upstream(
        base_url=_service_url("MEMBER_DATABASE_URL"),
        api_key=os.getenv("UPSTREAM_MEMBER_API_KEY", "").strip(),
        client_api_key=os.getenv("GATEWAY_MEMBER_API_KEY", ""),
        allowed_paths=_patterns(
            r"api/recommend/personal",
            r"api/favorites/toggle",
            r"api/members",
            r"api/members/[^/]+",
            r"api/members/[^/]+/points",
            # 收藏的「寫」走 api/favorites/toggle，「讀」走這條。少了它，前端把收藏
            # 同步回本機的那段永遠拿到 Gateway 的 404——寫得進去、讀不回來，
            # 換裝置就看不到自己收藏過的東西，而且畫面完全正常不會報錯。
            r"api/members/[^/]+/favorites",
            # 購物車跟收藏同一個模式：跨裝置同步靠會員 session。GET 讀回、POST 整台覆蓋。
            # 授權沿用 _authorize_member_path（MEMBER_SCOPE_RE）——只准存取自己 email
            # 底下的車，別人的擋 403。少了這條，前端寫得進 localStorage 卻同步不到伺服器，
            # 換裝置就看不到自己的購物車，而且畫面完全正常不會報錯（跟收藏當初一模一樣的坑）。
            r"api/members/[^/]+/cart",
            r"api/members/[^/]+/check-in",
            r"api/members/[^/]+/tasks",
            r"api/members/[^/]+/tasks/[^/]+/claim",
            r"api/members/[^/]+/theme-shop/[^/]+/redeem",
            r"api/members/[^/]+/saved-looks",
            r"api/members/[^/]+/saved-looks/[^/]+",
        ),
        requires_upstream_api_key=False,
        requires_cloud_run_iam=False,
    ),
}

MAX_BODY_BYTES = max(1024, int(os.getenv("AI_GATEWAY_MAX_BODY_BYTES", str(13 * 1024 * 1024))))
UPSTREAM_TIMEOUT_SECONDS = max(10, int(os.getenv("AI_GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "600")))


def _timeout_env(name: str, default: int) -> int:
    # A read never has any business holding the 600-second connect budget the
    # client is built with: a slow member database or a Quick Tunnel that stops
    # answering would otherwise pin a worker for ten minutes and starve everyone
    # else.  Each upstream gets its own bound, capped so a stray env value can
    # never re-open that window.
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(5, min(value, UPSTREAM_TIMEOUT_SECONDS))


# Per-service read timeouts.  Face and render are job-based (a quick submit,
# then polling), so they do not need the long default either.  The external
# text suggestion upstream is reached over a Quick Tunnel and must never hold a
# ten-minute connection.
UPSTREAM_TIMEOUTS = {
    "face-basic": _timeout_env("AI_GATEWAY_FACE_TIMEOUT_SECONDS", 120),
    "face-pro": _timeout_env("AI_GATEWAY_FACE_TIMEOUT_SECONDS", 120),
    "render-service": _timeout_env("AI_GATEWAY_RENDER_TIMEOUT_SECONDS", 120),
    "text-suggestion": _timeout_env("AI_GATEWAY_TEXT_TIMEOUT_SECONDS", 60),
    "member-database": _timeout_env("AI_GATEWAY_MEMBER_TIMEOUT_SECONDS", 30),
}


def upstream_timeout(service: str) -> int:
    return UPSTREAM_TIMEOUTS.get(service, _timeout_env("AI_GATEWAY_DEFAULT_TIMEOUT_SECONDS", 60))
# 會員資料庫 2026-07-26 的改版新增了 `X-Gateway-Key`（見對方 app.py 的 `_check_gateway_key`），
# 套用在 /api/login、/api/register、/api/send-otp、/api/verify-otp 四支「登入前」端點上。
# 對方預設是寬鬆模式（不帶也放行），但一旦切成嚴格模式，沒帶的請求一律 401——2026-07-27
# 整站無法登入、註冊、收驗證碼就是這樣來的，而商品端點不在他們的清單裡所以還活著。
#
# 金鑰目前還沒拿到，所以這裡讀環境變數：沒設就不送，行為與現在完全相同；
# 拿到之後只要在 Cloud Run 設一個環境變數，不必再重新建置與部署一次映像。
MEMBER_GATEWAY_KEY = os.getenv("UPSTREAM_MEMBER_API_KEY", "").strip()


def with_member_gateway_key(headers: dict[str, str]) -> dict[str, str]:
    """對會員資料庫的請求補上 `X-Gateway-Key`；未設定金鑰時原樣回傳。"""
    if MEMBER_GATEWAY_KEY:
        headers["X-Gateway-Key"] = MEMBER_GATEWAY_KEY
    return headers


MEMBER_DATABASE_URL = _service_url("MEMBER_DATABASE_URL")
PRODUCT_DATABASE_URL = _service_url("PRODUCT_DATABASE_URL")
PRODUCT_ADMIN_API_KEY = os.getenv("PRODUCT_ADMIN_API_KEY", "")
ADMIN_PROXY_TIMEOUT_SECONDS = max(5, min(int(os.getenv("ADMIN_PROXY_TIMEOUT_SECONDS", "15")), 60))
ADMIN_PROXY_MAX_BODY_BYTES = max(1024, min(int(os.getenv("ADMIN_PROXY_MAX_BODY_BYTES", "1048576")), 5 * 1024 * 1024))
SESSION_SECRET = os.getenv("GATEWAY_SESSION_SECRET", "")
SESSION_TTL_SECONDS = max(300, min(int(os.getenv("GATEWAY_SESSION_TTL_SECONDS", "7200")), 86400))
SESSION_ONLY_MODE = os.getenv("GATEWAY_SESSION_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}
LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("GATEWAY_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "600")))
LOGIN_RATE_LIMIT_MAX_REQUESTS = max(1, int(os.getenv("GATEWAY_LOGIN_RATE_LIMIT_MAX_REQUESTS", "10")))
# 註冊與驗證碼使用獨立配額，避免登入失敗影響所有人的註冊流程。
# 此處主要限制寄信濫用，因此配額比登入流程寬鬆。
SIGNUP_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("GATEWAY_SIGNUP_RATE_LIMIT_WINDOW_SECONDS", "600")))
SIGNUP_RATE_LIMIT_MAX_REQUESTS = max(1, int(os.getenv("GATEWAY_SIGNUP_RATE_LIMIT_MAX_REQUESTS", "40")))
IS_PRODUCTION = os.getenv("APP_ENV", "").strip().lower() in {"prod", "production"}
# Firebase Hosting forwards exactly one cookie to a Cloud Run rewrite: the one
# named `__session`.  Every other cookie is dropped at the CDN before the request
# is proxied, which is why the session used to vanish between the browser and
# this service even though the browser was sending it (S56).  Both halves of the
# session therefore have to travel inside this single name.
SESSION_COOKIE = "__session"
# The gateway access token is a JWT (base64url plus dots) and the sealed upstream
# jar is a Fernet token (base64 plus padding).  Neither alphabet contains "|", so
# it can separate them unambiguously.
SESSION_COOKIE_SEPARATOR = "|"
MAX_SEALED_MEMBER_SESSION_BYTES = 3500

# 多帳號（同一個瀏覽器、跨分頁登入多個帳號）。
# 一個瀏覽器只有一份 `__session` cookie，所以多個帳號必須共存在它裡面，做成好幾個
# 「(gateway token, 封裝過的上游 cookie)」槽位。每個分頁用 `X-Expected-Actor`——就是
# 分頁本來就綁的那個不含 email 的 opaque actor——選出要用哪一個槽位。旗標關掉時，
# 關閉多帳號模式時只保留一個槽位，行為與單帳號模式相同。
MULTI_SESSION_ENABLED = os.getenv("GATEWAY_MULTI_SESSION", "").strip().lower() in {"1", "true", "yes", "on"}
MAX_SESSION_SLOTS = max(1, min(int(os.getenv("GATEWAY_MAX_SESSION_SLOTS", "4")), 8))
MULTI_SESSION_PREFIX = "v2."
# cookie 必須遠低於瀏覽器約 4 KB 的上限。每個槽位是一個 JWT 加一份 Fernet 封裝的上游
# cookie；這個上限決定同時能存在幾個槽位，超過就從最舊的開始淘汰。
MAX_SESSION_COOKIE_BYTES = max(1024, min(int(os.getenv("GATEWAY_MAX_SESSION_COOKIE_BYTES", "3800")), 4000))
LOGIN_LIMIT_COLLECTION = os.getenv("GATEWAY_LOGIN_LIMIT_COLLECTION", "gateway_login_limits")

# ── 訪客試用 ────────────────────────────────────────────────────────────────
# 未登入的人可以跑完整的「臉部分析 → 妝容渲染」，但只有固定次數，而且不能存圖：
# 收藏走 member-database，那條路對訪客一律維持 401，不在這裡開任何缺口。
#
# 訪客身分不能放 cookie。Firebase Hosting 只把 `__session` 轉發給 Cloud Run，
# 其他 cookie 在 CDN 就被丟掉了（見上方 SESSION_COOKIE 的註解），所以新開一個
# `dm_guest` cookie 根本到不了這裡。改成：Gateway 簽一個帶 HMAC 的訪客票券，
# 前端自己保管並用 `X-Guest-Ticket` 標頭送回來。
#
# 這樣擋得住「偽造一個票券」（HMAC 驗不過），擋不住「把票券刪掉再要一張新的」。
# 後者用簽發端的 IP 限流補：換票券要成本，一般使用者不會去做，而額度本身是按
# 票券算的，所以不會像純 IP 方案那樣讓整間學校共用同一份三次。
GUEST_TRIAL_ENABLED = os.getenv("GATEWAY_GUEST_TRIAL", "").strip().lower() in {"1", "true", "yes", "on"}
GUEST_TRIAL_MAX_RUNS = max(1, min(int(os.getenv("GATEWAY_GUEST_TRIAL_MAX_RUNS", "3")), 50))
# 額度窗預設 30 天。這是「一個訪客票券總共能跑幾次」，不是每日配額。
GUEST_TRIAL_WINDOW_SECONDS = max(3600, int(os.getenv("GATEWAY_GUEST_TRIAL_WINDOW_SECONDS", str(30 * 24 * 3600))))
GUEST_TRIAL_COLLECTION = os.getenv("GATEWAY_GUEST_TRIAL_COLLECTION", "gateway_guest_trials")
# 同一個 IP 一天能領幾張票券。調低會誤傷共用出口 IP 的場合（教室、公司）。
GUEST_TICKET_ISSUE_WINDOW_SECONDS = max(600, int(os.getenv("GATEWAY_GUEST_TICKET_WINDOW_SECONDS", "86400")))
GUEST_TICKET_ISSUE_MAX = max(1, min(int(os.getenv("GATEWAY_GUEST_TICKET_MAX_PER_IP", "12")), 200))
GUEST_TICKET_LIMIT_COLLECTION = os.getenv("GATEWAY_GUEST_TICKET_COLLECTION", "gateway_guest_tickets")
GUEST_TICKET_HEADER = "x-guest-ticket"
# 配額後端連不上時翻成 True，並在 /health 回報。見 _note_quota_backend_down。
_GUEST_QUOTA_DEGRADED = False
GUEST_TICKET_TTL_SECONDS = GUEST_TRIAL_WINDOW_SECONDS
# 訪客只能碰這兩個服務。member-database／admin-api／face-pro 不在內，
# 少一個名字就少一條要驗的路徑，這份清單刻意寫死而不是用設定檔開關。
GUEST_ALLOWED_SERVICES = frozenset({"face-basic", "render-service"})
# 訪客在這些路徑上可以做寫入（POST）。其餘寫入一律回到會員驗證。
GUEST_WRITE_PATHS = {
    "face-basic": _patterns(r"v1/face/pose", r"v1/face/jobs/basic"),
    # 前端走的是非同步的 render/jobs；同步的 render 一併放行，兩條都是「開始一次渲染」。
    "render-service": _patterns(r"render", r"render/jobs"),
}
# 只有「開始一次臉部分析」會扣額度。渲染、輪詢狀態、讀結果都不扣——
# 一次流程扣一次，中途重試不該把使用者的三次吃光。
GUEST_QUOTA_SPEND_PATHS = {"face-basic": _patterns(r"v1/face/jobs/basic")}

# 跨品牌底妝近似色號（商品後端契約 2026-08-28）。這一條沒放行的話 Gateway 會先
# 回 404「Route not found」，而那個訊息長得跟上游沒有這個端點一模一樣——
# 讀起來像是對方沒做，實際上是我們沒開。id 段落限制成不含斜線，避免用路徑
# 穿越到商品服務的其他端點。
#
# `health` 是部署後的驗收入口（商品後端契約 2026-08-28 §正式部署責任邊界第 4 步）：
# 切換 PRODUCT_DATABASE_URL 之後要能從正式站確認「Gateway 指到的是哪一版、幾筆商品」。
# 沒有它就只能靠 `api/products` 的 total 猜，而那個數字不會說服務版本。
# 它只回服務自己的版本與統計，沒有任何會員或商品明細。
# 商品 id 那一段。排除 `.` 與 `..`，否則 `api/products/../shade-matches` 這種寫法
# 會配對成功，然後被組成 `{PRODUCT_DATABASE_URL}/api/products/../shade-matches`
# 送出去——上游（或中間任何一層）把它正規化之後就變成 `/api/shade-matches`，
# 等於用一條公開、不需登入的路徑去打白名單沒放行的端點。
#
# 這個洞在 2026-09-11 之前就存在於 shade-matches 那條（`[^/]+` 擋得住斜線但擋不住點），
# 只是當時沒有人試。補商品詳情時兩條一起收緊。
# 注意 lookahead 要同時擋「點在結尾」與「點後面接斜線」。只寫 `(?!\.\.?$)` 的話，
# `api/products/../shade-matches` 仍然會通過——那一段的 `..` 後面接的是 `/`，不是結尾。
PRODUCT_ID_SEG = r"(?!\.\.?(?:/|$))[^/]+"
PUBLIC_PRODUCT_PATHS = _patterns(r"api/products", r"recommend-products",
                                 # 商品詳情。2026-09-11 補上：`/shade-matches` 穿得過、裸 id
                                 # 穿不過，於是推薦卡片點進商品詳情一律 404（而且是 Gateway
                                 # 自己的錯誤格式，不是上游缺商品）。上游本來就有這支，
                                 # 漏的只是這條白名單。
                                 rf"api/products/{PRODUCT_ID_SEG}",
                                 rf"api/products/{PRODUCT_ID_SEG}/shade-matches",
                                 # 化妝包反推妝容（2026-09-25）。跟上面 shade-matches 同一類：
                                 # 上游兩個別名都有，漏的只是這條白名單，症狀一樣是 Gateway
                                 # 自己的 404——看起來像上游沒做，實際上是這裡沒放行。
                                 r"recommend-styles",
                                 r"api/recommend-styles",
                                 r"health")
# 公開商品路徑裡，只有這些收 POST；其餘一律只收 GET。
#
# 方向很重要。原本的寫法是「列出哪些路徑只收 GET」，那等於**新增白名單路徑時預設開放
# 寫入**——忘記補進那串列舉，POST 就會被轉發到商品服務，而這整條路徑是**不需要登入**的。
# 2026-09-11 補 api/products/{id} 時就差點踩到。
#
# 改成「預設 GET，要寫入的明確列出來」之後，漏掉的後果是 405 被擋下，不是放行。
PUBLIC_PRODUCT_POST_PATHS = frozenset({"recommend-products",
                                       "recommend-styles", "api/recommend-styles"})
SAVED_LOOK_PATH_RE = re.compile(r"^api/members/([^/]+)/saved-looks(?:/([^/]+))?$")
MEMBER_PATH_RE = re.compile(r"^api/members/([^/]+)$")
MEMBER_SCOPE_RE = re.compile(r"^api/members/([^/]+)(?:/|$)")
# The bare roster path — no member id — returns every account, so it is an
# administrator-only view rather than the self-scoped `api/members/<id>` route.
MEMBER_LIST_PATH_RE = re.compile(r"^api/members$")
# 妝前圖的網址多一段 /before，這裡要一起認得——否則從 saved_looks 讀回的
# beforeImageUrl 解析不出 job id，retain 與刪除都會把它當成不相干的外部網址略過。
STABLE_RENDER_URL_RE = re.compile(r"(?:https://[^/]+)?/media/render/([0-9a-f]{32})(?:/before)?(?:[?#].*)?$")
PRIVATE_RENDER_URL_RE = re.compile(
    r"^https://storage\.googleapis\.com/decorate-me-renders/(?:rendered|temporary|retained)/[A-Za-z0-9._/-]+$"
)


def _validate_configuration() -> None:
    if not IS_PRODUCTION:
        return
    missing = []
    for name, upstream in UPSTREAMS.items():
        if upstream.required_in_production and not upstream.base_url:
            missing.append(f"{name}.base_url")
        if upstream.requires_upstream_api_key and not upstream.api_key:
            missing.append(f"{name}.upstream_api_key")
        if not SESSION_ONLY_MODE and not upstream.client_api_key:
            missing.append(f"{name}.gateway_api_key")
    if not MEMBER_DATABASE_URL:
        missing.append("member_database_url")
    if len(SESSION_SECRET) < 32:
        missing.append("gateway_session_secret")
    if missing:
        raise RuntimeError(f"Missing production AI Gateway configuration: {', '.join(missing)}")


_validate_configuration()


class IdentityTokenCache:
    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _expiry(token: str) -> float:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return 0

    def get(self, audience: str) -> str:
        now = time.time()
        with self._lock:
            cached = self._tokens.get(audience)
            if cached and cached[1] > now + 60:
                return cached[0]

            token = id_token.fetch_id_token(GoogleAuthRequest(), audience)
            self._tokens[audience] = (token, self._expiry(token))
            return token


TOKEN_CACHE = IdentityTokenCache()
_login_rate_lock = threading.Lock()
_login_rate_hits: dict[str, deque[float]] = {}


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def is_path_allowed(upstream: Upstream, path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in upstream.allowed_paths)


def require_client_api_key(upstream: Upstream, supplied: str) -> None:
    if upstream.client_api_key and not secret_equals(supplied, upstream.client_api_key):
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing API key."}})


def require_any_client_api_key(supplied: str) -> None:
    expected = {upstream.client_api_key for upstream in UPSTREAMS.values() if upstream.client_api_key}
    if expected and not any(secret_equals(supplied, key) for key in expected):
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing API key."}})


def _valid_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return ""


def client_ip(request: Request) -> str:
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    # Cloud Run appends its load-balancer address. The entry immediately before it
    # is the caller address and is safer than trusting the first user-supplied value.
    if len(forwarded) >= 2:
        candidate = _valid_ip(forwarded[-2])
        if candidate:
            return candidate
    if request.client:
        candidate = _valid_ip(request.client.host)
        if candidate:
            return candidate
    return "unknown"


def _login_quota_check(
    key: str,
    now: float,
    window: int = LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    max_requests: int = LOGIN_RATE_LIMIT_MAX_REQUESTS,
) -> int | None:
    """這個 key 目前是否超量：超量回「還要等幾秒」，否則 None。不消耗任何額度。

    只讀不寫是關鍵：登入成功不該計入限流，否則一個正在反覆測試的管理員用正確
    密碼也會把自己鎖住（實測發生過）。額度只在「登入失敗」時才消耗，見
    `record_failed_login`。

    `window` / `max_requests` 可以覆寫，讓註冊那組用自己的額度——key 已經帶了 scope
    前綴，兩組不會互相消耗。
    """
    durable = job_store.peek_window_quota(
        LOGIN_LIMIT_COLLECTION, key, window, max_requests, now=now,
    )
    if durable is not None:
        allowed, _, retry_after = durable
        return None if allowed else retry_after
    cutoff = now - window
    with _login_rate_lock:
        bucket = _login_rate_hits.setdefault(key, deque())
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= max_requests:
            return max(1, int(bucket[0] + window - now))
        return None


def _login_quota_record(
    key: str,
    now: float,
    window: int = LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    max_requests: int = LOGIN_RATE_LIMIT_MAX_REQUESTS,
) -> None:
    """把一次「失敗」的登入記進視窗。跨 instance 一致優先走 Firestore，否則記憶體。"""
    durable = job_store.consume_window_quota(
        LOGIN_LIMIT_COLLECTION, key, window, max_requests, now=now,
    )
    if durable is not None:
        return
    cutoff = now - window
    with _login_rate_lock:
        bucket = _login_rate_hits.setdefault(key, deque())
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        bucket.append(now)


def _login_rate_keys(request: Request, email: str, scope: str = "login") -> list[str]:
    # 兩個維度：呼叫端 IP（擋「一台主機狂試很多帳號」）與被鎖定的帳號（擋「一群 IP
    # 一起暴力破解同一個帳號」，只看 IP 抓不到）。帳號那把 key 是雜湊過的——限流器
    # 從不儲存 email 本身。
    #
    # IP 只在「確實辨識得出呼叫端」時才當一個維度。Firebase Hosting → Cloud Run 這條
    # 路徑上，client_ip 可能因為 X-Forwarded-For 的層數而解不出真正的使用者位址，
    # 退回 "unknown"。若照樣用 `ip:unknown` 當 key，就會把所有人塞進同一個桶——
    # 十次失敗就讓全站登入一起 429（實測：不同帳號、不同裝置都被擋）。辨識不出來時
    # 寧可不設 IP 維度，讓「帳號維度」單獨守著；那一維是可靠的（以雜湊帳號為鍵）。
    #
    # `scope` 把不同用途的桶分開。登入與註冊共用一個桶時的實際後果，見
    # SIGNUP_RATE_LIMIT_* 的註解：十次失敗登入會讓全場都註冊不了。
    keys = []
    ip = client_ip(request)
    if ip and ip != "unknown":
        keys.append(f"{scope}:ip:{ip}")
    normalized = str(email or "").strip().lower()
    if normalized:
        keys.append(f"{scope}:account:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest())
    return keys


def enforce_login_rate_limit(request: Request, email: str = "") -> None:
    """登入前檢查是否已超量（只讀）。額度只在失敗時消耗，成功登入不計入。"""
    now = time.time()
    for key in _login_rate_keys(request, email):
        retry_after = _login_quota_check(key, now)
        if retry_after is not None:
            raise rate_limited_error(
                "LOGIN_RATE_LIMITED",
                f"登入嘗試次數過多，請在 {retry_after} 秒後再試。",
                retry_after,
            )


def enforce_signup_rate_limit(request: Request, email: str = "") -> None:
    """註冊／寄驗證碼／驗驗證碼的額度。與登入分開，且這裡就消耗額度。

    登入是「失敗才算」，因為成功登入不是攻擊。這條路徑相反：要擋的是把它當寄信機用，
    寄成功才是要算的那一次，所以每一次請求都記。

    有 email 時一併記帳號維度——IP 在 Firebase Hosting → Cloud Run 這條路徑上可能是
    共用位址（見 `client_ip`），只靠 IP 會把所有人算成同一個來源。
    """
    now = time.time()
    keys = _login_rate_keys(request, email, scope="signup")
    for key in keys:
        retry_after = _login_quota_check(
            key, now, SIGNUP_RATE_LIMIT_WINDOW_SECONDS, SIGNUP_RATE_LIMIT_MAX_REQUESTS
        )
        if retry_after is not None:
            raise rate_limited_error(
                "MEMBER_SERVICE_RATE_LIMITED",
                f"操作次數過多，請在 {retry_after} 秒後再試。",
                retry_after,
            )
    for key in keys:
        _login_quota_record(
            key, now, SIGNUP_RATE_LIMIT_WINDOW_SECONDS, SIGNUP_RATE_LIMIT_MAX_REQUESTS
        )


def record_failed_login(request: Request, email: str = "") -> None:
    """記一次登入失敗。只有「帳密錯誤」這類失敗才呼叫，服務暫時故障（5xx）不算——
    資料庫掛掉不該把使用者鎖在門外。"""
    now = time.time()
    for key in _login_rate_keys(request, email):
        _login_quota_record(key, now)


def issue_access_token(email: str, role: str = "", status: str = "active") -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + SESSION_TTL_SECONDS
    token = jwt.encode(
        {
            "iss": "decorate-me-ai-gateway",
            "aud": "decorate-me-ai",
            "sub": email.strip().lower(),
            "role": role[:64],
            "status": status[:32],
            "iat": now,
            "exp": expires_at,
        },
        SESSION_SECRET,
        algorithm="HS256",
    )
    return token, expires_at


def issue_legacy_media_token(url: str, owner_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "decorate-me-ai-gateway",
            "aud": "decorate-me-private-media",
            "url": url,
            "ownerId": owner_id,
            "iat": now,
            "exp": now + 600,
        },
        SESSION_SECRET,
        algorithm="HS256",
    )


def _member_cookie_cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(SESSION_SECRET.encode("utf-8")).digest())
    return Fernet(key)


def _upstream_cookie_header(response: httpx.Response) -> str:
    jar = SimpleCookie()
    for value in response.headers.get_list("set-cookie"):
        try:
            jar.load(value)
        except Exception:
            continue
    if not jar:
        return "; ".join(f"{name}={value}" for name, value in response.cookies.items())
    return "; ".join(f"{name}={morsel.value}" for name, morsel in jar.items())


def _is_cookie_deletion(morsel) -> bool:
    """A Set-Cookie that clears a name rather than rotating its value."""
    if not morsel.value:
        return True
    max_age = str(morsel.get("max-age") or "").strip()
    if max_age:
        try:
            return int(max_age) <= 0
        except ValueError:
            return False
    return False


def merge_upstream_cookies(existing: str, response: httpx.Response) -> str:
    """Fold a response's Set-Cookie headers into the session cookie jar.

    The member database rotates one cookie at a time and also sets unrelated
    cookies (CSRF, locale).  Replacing the whole jar with just the names in the
    latest response silently drops the session cookie, so the next request is
    rejected upstream and the browser sees a spurious 401.
    """
    jar: dict[str, str] = {}
    for pair in str(existing or "").split(";"):
        name, _, value = pair.partition("=")
        if name.strip():
            jar[name.strip()] = value.strip()

    incoming = SimpleCookie()
    for value in response.headers.get_list("set-cookie"):
        try:
            incoming.load(value)
        except Exception:
            continue
    if not incoming:
        for name, value in response.cookies.items():
            jar[name] = value
        return "; ".join(f"{name}={value}" for name, value in jar.items())

    for name, morsel in incoming.items():
        if _is_cookie_deletion(morsel):
            jar.pop(name, None)
        else:
            jar[name] = morsel.value
    return "; ".join(f"{name}={value}" for name, value in jar.items())


def seal_member_cookie(cookie_header: str) -> str:
    if not cookie_header:
        return ""
    sealed = _member_cookie_cipher().encrypt(cookie_header.encode("utf-8")).decode("ascii")
    if len(sealed) > MAX_SEALED_MEMBER_SESSION_BYTES:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "MEMBER_SESSION_TOO_LARGE", "message": "Member authentication failed."}},
        )
    return sealed


def read_session_cookie(request: Request) -> tuple[str, str]:
    """Split `__session` into the gateway access token and the sealed upstream jar."""
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw:
        return "", ""
    token, _, sealed = raw.partition(SESSION_COOKIE_SEPARATOR)
    return token, sealed


def request_access_token(request: Request) -> str:
    """The gateway access token for this request, from the header or the cookie."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return read_session_cookie(request)[0]


def set_session_cookie(response: Response, access_token: str, sealed_member_cookie: str) -> None:
    """Write both halves of the session as the single cookie Firebase forwards."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=f"{access_token}{SESSION_COOKIE_SEPARATOR}{sealed_member_cookie}",
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )


# ── CSRF：double-submit cookie ───────────────────────────────────────────────
# session cookie 是 `SameSite=Lax`，這擋得住跨站的簡單表單 POST，但擋不了同站的
# 子網域、也擋不了 Lax 仍然允許的頂層導覽情境。管理端的寫入（改權限、刪商品、
# 停權會員）不該只靠 cookie 就成立，所以再要求一個「JS 讀得到 cookie 才拿得到」
# 的隨機值：攻擊者的頁面送得出請求，但讀不到我們網域的 cookie，補不出這個標頭。
CSRF_COOKIE = "dm_csrf"
CSRF_HEADER = "x-csrf-token"
# 「哪些方法算寫入」跟 X-Expected-Actor 用同一份定義（見下方 enforce_expected_actor）。
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# HTTP 方法 → 稽核事件動詞。商品與會員兩個稽核點共用同一張表，別各寫各的。
_METHOD_VERB = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}


def _audit_action(prefix: str, method: str) -> str:
    """組稽核事件名，例如 `product.delete`／`member.update`。"""
    verb = _METHOD_VERB.get(str(method or "").upper(), str(method or "").lower())
    return f"{prefix}.{verb}"


def issue_csrf_cookie(response: Response) -> str:
    """發一個新的 CSRF token 並寫進 cookie（刻意不是 HttpOnly——前端要讀它）。"""
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=False,  # 前端必須讀得到才能回填標頭；這正是 double-submit 的運作方式
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )
    return token


def _refresh_csrf_cookie(request: Request, response: Response) -> None:
    """已經登入、但還沒有 CSRF cookie 的瀏覽器，在下一次 `/auth/session` 補發一個。

    這條路徑是為了「上線當下」存在的：這個防護開始生效時，所有人的 session 都還在，
    但沒有人有 token。少了補發，他們的管理端寫入會一路 403，直到重新登入為止——
    等於用一次安全性修補換一次全體登出。前端進私有頁前一定會先打 `/auth/session`，
    所以補發會在他們按下任何按鈕之前就完成。
    """
    if not request.cookies.get(CSRF_COOKIE):
        issue_csrf_cookie(response)


def enforce_csrf(request: Request) -> None:
    """狀態變更請求必須讓標頭與 cookie 帶著同一個 token。

    舊版只有 `X-Expected-Actor` 在擋跨帳號寫入——它擋的是「寫到別人的資料上」，
    不是「別的網站叫你的瀏覽器寫」。兩者是不同的攻擊，需要不同的檢查。
    """
    if str(request.method or "").upper() not in STATE_CHANGING_METHODS:
        return
    cookie_token = str(request.cookies.get(CSRF_COOKIE) or "")
    header_token = str(request.headers.get(CSRF_HEADER) or "")
    if not cookie_token or not header_token or not secret_equals(header_token, cookie_token):
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "CSRF_TOKEN_INVALID",
                              "message": "這次操作的安全驗證失敗，請重新整理頁面後再試。",
                              "retryable": False}},
        )


def require_upstream_member_cookie(request: Request) -> str:
    sealed = read_session_cookie(request)[1]
    if not sealed:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_SESSION_REQUIRED", "message": "Member sign-in is required."}},
        )
    return unseal_member_cookie(sealed)


def unseal_member_cookie(sealed: str) -> str:
    """解開一份封裝過的上游 cookie；缺少或無效就回 401。"""
    if not sealed:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_SESSION_REQUIRED", "message": "Member sign-in is required."}},
        )
    try:
        return _member_cookie_cipher().decrypt(
            sealed.encode("ascii"),
            ttl=SESSION_TTL_SECONDS,
        ).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_SESSION_INVALID", "message": "Member session is invalid or expired."}},
        )


# ── 多帳號 session 槽位 ───────────────────────────────────────────────────────
# `__session` cookie 可能是舊的單槽格式（"token|sealed"），也可能是 v2 多槽格式
# （"v2." + base64url(JSON 的 {t, s} 陣列)）。讀取一律兩種都吃；寫入則看呼叫端選哪種
# （單帳號用舊格式，所以在多帳號旗標打開之前什麼都不會變）。

def read_session_slots(request: Request) -> list[tuple[str, str]]:
    """回傳 `__session` 裡的每一個 (gateway_token, 封裝上游 cookie) 槽位。"""
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw:
        return []
    if raw.startswith(MULTI_SESSION_PREFIX):
        try:
            decoded = base64.urlsafe_b64decode(raw[len(MULTI_SESSION_PREFIX):].encode("ascii")).decode("utf-8")
            items = json.loads(decoded)
        except (ValueError, TypeError):
            # base64 壞掉會丟 binascii.Error（是 ValueError 的子類），JSON 壞掉也是。
            return []
        slots: list[tuple[str, str]] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                token = str(item.get("t") or "")
                sealed = str(item.get("s") or "")
                if token:
                    slots.append((token, sealed))
        return slots
    token, _, sealed = raw.partition(SESSION_COOKIE_SEPARATOR)
    return [(token, sealed)] if token else []


def serialize_session_slots(slots: list[tuple[str, str]]) -> str:
    data = [{"t": token, "s": sealed} for token, sealed in slots]
    encoded = base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return MULTI_SESSION_PREFIX + encoded


def set_session_slots(response: Response, slots: list[tuple[str, str]]) -> None:
    """寫出多槽的 `__session`，從最舊的槽位開始淘汰直到大小塞得下。"""
    kept = slots[-MAX_SESSION_SLOTS:] if len(slots) > MAX_SESSION_SLOTS else list(slots)
    value = serialize_session_slots(kept)
    # 絕不送出瀏覽器會默默丟掉的過大 cookie：從最舊的帳號開始砍，直到塞得下，
    # 但至少保留最新的那一個。
    while len(value) > MAX_SESSION_COOKIE_BYTES and len(kept) > 1:
        kept = kept[1:]
        value = serialize_session_slots(kept)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=value,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )


def _slot_claims(access_token: str) -> dict | None:
    """驗證某個槽位的 gateway token 並回傳 claims；無效或過期則回 None。"""
    if not access_token:
        return None
    try:
        return jwt.decode(
            access_token,
            SESSION_SECRET,
            algorithms=["HS256"],
            audience="decorate-me-ai",
            issuer="decorate-me-ai-gateway",
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        return None


def session_accounts(request: Request) -> list[dict]:
    """這個瀏覽器 `__session` 裡所有已登入的帳號，無效槽位會被丟掉。

    最新的排在最後。每一筆帶著 opaque actor、subject（email）、role，以及要以該帳號
    身分發出請求所需的原始 token 與封裝上游 cookie。
    """
    accounts: list[dict] = []
    seen: set[str] = set()
    for token, sealed in read_session_slots(request):
        claims = _slot_claims(token)
        if not claims:
            continue
        sub = str(claims.get("sub") or "").strip().lower()
        if not sub:
            continue
        actor = opaque_actor_id(sub)
        if actor in seen:
            # 同一個帳號重新登入過：只保留最新的槽位。
            accounts = [a for a in accounts if a["actorId"] != actor]
        seen.add(actor)
        accounts.append({
            "actorId": actor,
            "sub": sub,
            "role": str(claims.get("role") or "member"),
            "status": str(claims.get("status") or "active"),
            "token": token,
            "sealed": sealed,
            "claims": claims,
        })
    return accounts


def select_account(request: Request, *, for_write: bool) -> dict:
    """用 `X-Expected-Actor` 選出這個請求要以哪一個已登入帳號的身分執行。

    這個選擇器就是跨分頁隔離用的那個 per-tab opaque actor；在這裡它同時「挑出」槽位，
    所以一個請求永遠只能以「真的在這個瀏覽器登入過」的帳號身分執行。寫入時缺選擇器
    一律 fail closed；選擇器指到的帳號若沒登入在這裡，就拒絕，讓分頁去請那個帳號重新
    登入，而不是默默用成別的帳號。
    """
    accounts = session_accounts(request)
    if not accounts:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_AUTH_REQUIRED", "message": "Member sign-in is required."}},
        )
    selector = str(request.headers.get("x-expected-actor") or "").strip()
    if selector:
        for account in accounts:
            if secret_equals(selector, account["actorId"]):
                return account
        # 分頁指定的帳號不存在或已過期時要求重新登入，不能改用其他帳號。
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "ACCOUNT_NOT_AVAILABLE", "message": "登入帳號已在其他分頁變更，請重新整理頁面後再操作。"}},
        )
    if for_write:
        # 寫入一定要指名帳號，才絕不會落到錯的帳號上。
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "EXPECTED_ACTOR_REQUIRED", "message": "無法確認目前分頁的登入身分，請重新登入後再操作。"}},
        )
    if len(accounts) == 1:
        return accounts[0]
    # 讀取時登入了好幾個帳號卻沒帶選擇器，無法判斷要用哪一個。
    raise HTTPException(
        status_code=409,
        detail={"error": {"code": "EXPECTED_ACTOR_REQUIRED", "message": "無法確認目前分頁的登入身分，請重新登入後再操作。"}},
    )


async def _validate_upstream_member_cookie(request: Request, upstream_cookie: str, subject: str) -> str:
    """Return the accepted (and possibly rotated) upstream session cookie."""
    subject = str(subject or "").strip().lower()
    if not upstream_cookie or not subject or not MEMBER_DATABASE_URL:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}},
        )
    headers = with_member_gateway_key({"Accept": "application/json", "Cookie": upstream_cookie})
    try:
        response = await request.app.state.http_client.get(
            f"{MEMBER_DATABASE_URL}/api/members/{quote(subject, safe='')}",
            headers=headers,
            timeout=10,
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}},
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}},
        )
    # 404 與 401/403 是兩件不同的事，不能都說成「session 無效」。
    #
    # 404 = 這個 session 有效，但它的 subject 在會員資料庫裡**找不到這個人**。
    # 重新登入一百次也不會好——那個帳號不存在於上游，不是憑證過期。
    #
    # 2026-08-29 就是這樣把管理員每 90 秒踢出去一次的：後台的
    # `admin@decoratme.local` 是 Gateway 端的內建管理員（`.local` 是假網域），
    # 上游查無此人回 404，這裡轉成 MEMBER_SESSION_INVALID，而那個碼在前端的
    # 登出清單裡。使用者看到的是「請重新登入」，登入後 90 秒又被踢，
    # 而真正的問題（上游沒有這組 admin）畫面上一個字都沒說。
    if response.status_code == 404:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_NOT_PROVISIONED",
                              "message": "This account does not exist in the member directory."}},
        )
    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_SESSION_INVALID", "message": "Member session is invalid or expired."}},
        )
    if not response.is_success:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}},
        )
    return merge_upstream_cookies(upstream_cookie, response) or upstream_cookie


async def validate_upstream_member_session(request: Request, claims: dict) -> str:
    """Confirm the sealed upstream cookie is still accepted by the member DB.

    A sealed cookie can be cryptographically valid while the upstream session
    has already been revoked or expired.  A small profile read makes the
    session preflight reflect the real upstream authentication state without
    exposing the member email or cookie to the browser.
    """
    upstream_cookie = require_upstream_member_cookie(request)
    return await _validate_upstream_member_cookie(request, upstream_cookie, str(claims.get("sub") or ""))


async def require_pro_analysis_access(request: Request, claims: dict, sealed: str = "") -> tuple[str, str]:
    """Authorize a new PRO job from the trusted member service, not browser state.

    Return the old/new member cookie so a rotated session is preserved. Existing
    job polling and feedback remain available after a plan change.
    """
    if str(claims.get("status") or "active").lower() != "active":
        raise HTTPException(403, detail={"error": {"code": "PRO_ACCESS_DENIED", "message": "目前帳號狀態無法使用 PRO 分析。"}})
    if str(claims.get("role") or "").lower() == "admin":
        # Gateway-issued admin identity also supports the built-in admin account.
        return "", ""
    subject = str(claims.get("sub") or "").strip().lower()
    if not subject or not MEMBER_DATABASE_URL:
        raise HTTPException(503, detail={"error": {"code": "PRO_PERMISSION_UNAVAILABLE", "message": "目前無法確認 PRO 權限，請稍後再試。", "retryable": True}})
    cookie = unseal_member_cookie(sealed) if MULTI_SESSION_ENABLED else require_upstream_member_cookie(request)
    try:
        response = await request.app.state.http_client.get(
            f"{MEMBER_DATABASE_URL}/api/members/{quote(subject, safe='')}",
            headers=with_member_gateway_key({"Accept": "application/json", "Cookie": cookie}),
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, detail={"error": {"code": "PRO_PERMISSION_UNAVAILABLE", "message": "目前無法確認 PRO 權限，請稍後再試。", "retryable": True}}) from exc
    if response.status_code in {401, 403, 404}:
        raise HTTPException(403, detail={"error": {"code": "PRO_ACCESS_DENIED", "message": "無法確認有效的 PRO 會員身分。"}})
    try:
        data = response.json() if response.is_success else None
        member = data.get("member", data) if isinstance(data, dict) else None
        if not isinstance(member, dict):
            raise ValueError("Member payload is not an object")
    except (ValueError, TypeError) as exc:
        # 回的不是能解析的 JSON 物件——這才是真正的「暫時看不出來」，值得重試。
        raise HTTPException(503, detail={"error": {"code": "PRO_PERMISSION_UNAVAILABLE", "message": "目前無法確認 PRO 權限，請稍後再試。", "retryable": True}}) from exc
    # 上游對「這一列是誰」有三種欄位拼法。member_directory_emails()（本檔 api/members
    # 名冊的讀法）三種都認，這裡只認 email 的話，資料列用 memberEmail 或 account 存
    # 信箱的會員就會被判成身分不符，然後拿到一個標著 retryable 的 503：畫面說「請稍後
    # 再試」，但欄位名不會因為等一下就改變，他重試幾次都一樣，永遠開不了 PRO 也不知道
    # 為什麼。兩處對同一份資料的讀法必須一致。
    identity = ""
    for field in ("email", "memberEmail", "account"):
        candidate = str(member.get(field) or "").strip().lower()
        if candidate:
            identity = candidate
            break
    if not identity:
        # 三種拼法都沒有。這筆是用 /api/members/<subject> 指名取回的，URL 本身已經
        # 圈定了對象，再要求回應複述一次只是多一層防護；欄位不存在時那層防護量不到
        # 東西，不該因此把人擋在門外。留一筆警告，讓上游改了格式時看得出來。
        logging.warning("會員資料未帶身分欄位，改以 URL 指名為準 subject=%s", subject)
    elif identity != subject:
        # 指名要 A 卻拿回 B。這是權限問題不是暫時故障，回不可重試的 403，
        # 不要用 503 叫人去重試一個永遠不會變的結果。
        logging.warning("會員資料身分不符 subject=%s", subject)
        raise HTTPException(403, detail={"error": {"code": "PRO_ACCESS_DENIED", "message": "無法確認有效的 PRO 會員身分。"}})
    permission = member.get("permission") if isinstance(member.get("permission"), dict) else {}
    status = str(member.get("status") or permission.get("status") or "active").lower()
    role = str(member.get("role") or member.get("member_role") or permission.get("role") or "").lower()
    pages = member.get("allowedPages") or permission.get("allowedPages") or []
    allowed = (role == "admin" or member.get("level") in {"VIP會員", "PRO會員", "管理員"}
               or (isinstance(pages, list) and "analysisPro" in pages))
    if status != "active" or not allowed:
        raise HTTPException(403, detail={"error": {"code": "PRO_ACCESS_DENIED", "message": "此帳號尚未開通 PRO 分析權限。"}})
    return cookie, merge_upstream_cookies(cookie, response) or cookie


def opaque_actor_id(subject: str) -> str:
    digest = hashlib.sha256(f"{SESSION_SECRET}:{subject.strip().lower()}".encode("utf-8")).hexdigest()
    return f"actor_{digest[:24]}"


def enforce_expected_actor(request: Request, acting_owner_id: str) -> None:
    """Reject a write whose tab was pinned to a different signed-in account.

    Every browser tab shares one `__session` cookie, so signing in elsewhere in
    the same browser silently rebinds this tab's requests to the new account.
    On login the tab records its opaque actor (see `/auth/session`) and echoes
    it back as `X-Expected-Actor`.  When the cookie has since been replaced, the
    actor derived from the *current* session no longer matches, and the write is
    stopped here — before it can reach the upstream and touch the wrong account.

    Safe reads do not need the header.  State-changing requests fail closed:
    an older or broken client that omits the pinned actor is refused instead of
    being allowed to write using whichever shared cookie happens to be current.
    """
    if str(request.method or "").upper() not in STATE_CHANGING_METHODS:
        return
    expected = str(request.headers.get("x-expected-actor") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "EXPECTED_ACTOR_REQUIRED", "message": "無法確認目前分頁的登入身分，請重新登入後再操作。"}},
        )
    if not secret_equals(expected, acting_owner_id):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "SESSION_OWNER_CHANGED", "message": "登入帳號已在其他分頁變更，請重新整理頁面後再操作。"}},
        )


def require_member_access(request: Request) -> dict:
    token = request_access_token(request)
    if not token:
        raise HTTPException(status_code=401, detail={"error": {"code": "MEMBER_AUTH_REQUIRED", "message": "Member sign-in is required."}})
    try:
        return jwt.decode(
            token,
            SESSION_SECRET,
            algorithms=["HS256"],
            audience="decorate-me-ai",
            issuer="decorate-me-ai-gateway",
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail={"error": {"code": "MEMBER_AUTH_INVALID", "message": "Member session is invalid or expired."}})


# ── 訪客票券 ────────────────────────────────────────────────────────────────


def _guest_ticket_mac(guest_id: str, expires_at: int) -> str:
    return hmac.new(
        SESSION_SECRET.encode("utf-8"),
        f"guest:{guest_id}:{expires_at}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


def guest_actor_id(guest_id: str) -> str:
    """訪客版的 opaque actor。前綴刻意與會員的 `actor_` 不同——
    渲染服務用它判定圖片擁有者，兩種身分的命名空間絕不能重疊。"""
    digest = hashlib.sha256(f"{SESSION_SECRET}:guest:{guest_id}".encode("utf-8")).hexdigest()
    return f"guest_{digest[:24]}"


def issue_guest_ticket(request: Request) -> dict:
    """簽一張訪客票券。同一個 IP 的簽發次數有上限，避免刪掉票券就能無限重來。"""
    ip = client_ip(request)
    if ip and ip != "unknown":
        spent = job_store.consume_window_quota(
            GUEST_TICKET_LIMIT_COLLECTION,
            f"guest_ticket:ip:{ip}",
            GUEST_TICKET_ISSUE_WINDOW_SECONDS,
            GUEST_TICKET_ISSUE_MAX,
        )
        # Firestore 不可用時回 None。本機開發沒有 Firestore，這裡放行而不是擋死；
        # 正式環境有 Firestore，限流才是實際生效的那一份。
        if spent is not None and not spent[0]:
            raise rate_limited_error(
                "GUEST_TICKET_RATE_LIMITED",
                "體驗次數已達上限，請登入會員後繼續使用。",
                spent[2],
            )
    guest_id = secrets.token_urlsafe(18)
    expires_at = int(time.time()) + GUEST_TICKET_TTL_SECONDS
    ticket = f"{guest_id}.{expires_at}.{_guest_ticket_mac(guest_id, expires_at)}"
    return {"ticket": ticket, "expiresAt": expires_at, "maxRuns": GUEST_TRIAL_MAX_RUNS}


def read_guest_id(request: Request, *, allow_query: bool = False) -> str:
    """從 `X-Guest-Ticket` 取出訪客身分。簽章不符或過期一律當作沒有票券。

    `allow_query` 只給圖片端點用。`<img src>` 送不出自訂標頭，會員那邊靠 cookie
    自動帶（Firebase 只轉發 `__session`），訪客沒有 cookie，所以圖片網址得自己
    帶票券。票券換得到的只有「自己這幾張圖」，換不到會員資料。
    """
    raw = str(request.headers.get(GUEST_TICKET_HEADER) or "").strip()
    if not raw and allow_query:
        raw = str(request.query_params.get("gt") or "").strip()
    if not raw:
        return ""
    guest_id, _, rest = raw.partition(".")
    expires_raw, _, mac = rest.partition(".")
    if not guest_id or not expires_raw or not mac:
        return ""
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return ""
    if expires_at <= int(time.time()):
        return ""
    if not secret_equals(mac, _guest_ticket_mac(guest_id, expires_at)):
        return ""
    return guest_id


def _note_quota_backend_down(where: str) -> None:
    """配額後端不可用時吼一聲，而且只吼一次。

    `job_store` 的配額函式在 Firestore 失敗時回 None 而不是拋例外——那是為了讓本機
    開發不必架 Firestore。代價是正式環境一旦連不上，次數限制會**安靜地**失效：
    端點照常回 200，剩餘次數永遠顯示滿額，看起來一切正常，實際上訪客可以無限使用。
    2026-08-17 上線時就是這樣，原因是服務帳號少了 roles/datastore.user，
    而且同一個問題早就讓登入限流的持久化配額失效很久了，沒有任何地方看得出來。
    """
    global _GUEST_QUOTA_DEGRADED
    if _GUEST_QUOTA_DEGRADED:
        return
    _GUEST_QUOTA_DEGRADED = True
    print(f"[guest-trial] 配額後端不可用（{where}）：訪客次數限制目前沒有生效。"
          f"請確認服務帳號有 roles/datastore.user。", flush=True)


def guest_trial_remaining(guest_id: str) -> int:
    """還剩幾次。Firestore 不可用時回滿額，讓本機開發不會整個卡住。"""
    peeked = job_store.peek_window_quota(
        GUEST_TRIAL_COLLECTION, f"guest_trial:{guest_id}",
        GUEST_TRIAL_WINDOW_SECONDS, GUEST_TRIAL_MAX_RUNS,
    )
    if peeked is None:
        _note_quota_backend_down("peek")
        return GUEST_TRIAL_MAX_RUNS
    return max(0, GUEST_TRIAL_MAX_RUNS - peeked[1])


def guest_trial_guard(guest_id: str) -> None:
    """額度用完就擋在送出之前。只讀不扣——扣款在上游確實受理之後才發生。"""
    if guest_trial_remaining(guest_id) > 0:
        return
    raise HTTPException(
        status_code=403,
        detail={"error": {
            "code": "GUEST_TRIAL_EXHAUSTED",
            "message": f"免費體驗已用完 {GUEST_TRIAL_MAX_RUNS} 次，註冊會員後可以繼續使用並保存成果。",
        }},
    )


def guest_trial_record(guest_id: str) -> None:
    """分析確實被受理之後才扣這一次。

    順序是刻意的：先扣再送，上游一掛掉使用者就白白少一次，而總共只有三次。
    代價是併發送出多筆時可能多放行一兩次——那比讓故障吃掉別人的額度好。
    """
    spent = job_store.consume_window_quota(
        GUEST_TRIAL_COLLECTION, f"guest_trial:{guest_id}",
        GUEST_TRIAL_WINDOW_SECONDS, GUEST_TRIAL_MAX_RUNS,
    )
    if spent is None:
        _note_quota_backend_down("consume")


def _guest_path_allowed(service: str, path: str, method: str) -> bool:
    """訪客能不能走這條路。讀取放行，寫入只放行明確列出的那幾條。"""
    if service not in GUEST_ALLOWED_SERVICES:
        return False
    # 回饋沿用有效訪客票券，FACE 另驗 job token；不開放覆核或 PRO。
    if service == "face-basic" and re.fullmatch(r"v1/face/jobs/[^/]+/feedback", path):
        return str(method or "").upper() == "POST"
    if str(method or "").upper() not in STATE_CHANGING_METHODS:
        return True
    return any(pattern.fullmatch(path) for pattern in GUEST_WRITE_PATHS.get(service, ()))


def _guest_spends_quota(service: str, path: str, method: str) -> bool:
    if str(method or "").upper() != "POST":
        return False
    return any(pattern.fullmatch(path) for pattern in GUEST_QUOTA_SPEND_PATHS.get(service, ()))


def _require_admin_claims(claims: dict) -> dict:
    if str(claims.get("status") or "active").lower() != "active":
        raise HTTPException(status_code=403, detail={"error": {"code": "ADMIN_SUSPENDED", "message": "Administrator account is suspended."}})
    if str(claims.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail={"error": {"code": "ADMIN_REQUIRED", "message": "Administrator permission is required."}})
    return claims


def require_admin_access(request: Request) -> dict:
    return _require_admin_claims(require_member_access(request))


def validate_path_segment(value: str, _code: str = "INVALID_PRODUCT_ID") -> str:
    """消毒要塞進上游路徑的識別碼。

    名字叫 segment 不叫 product_id：暫存商品的主鍵也走這裡，而它不是商品 id。
    錯誤碼留成參數，呼叫端要的話可以講自己領域的話；預設維持 INVALID_PRODUCT_ID，
    既有的商品路由回應不變。"""
    value = str(value or "").strip()
    if not value or len(value) > 160 or "/" in value or "\\" in value or ".." in value or any(ord(char) < 32 for char in value):
        raise HTTPException(status_code=400, detail={"error": {"code": _code, "message": "Invalid identifier."}})
    return value


def build_upstream_headers(request: Request, upstream: Upstream, identity_token: str) -> dict[str, str]:
    headers = {
        "Accept": request.headers.get("accept", "application/json"),
        "X-Forwarded-For": client_ip(request),
    }
    if upstream.api_key:
        headers["X-API-Key"] = upstream.api_key
    if upstream.requires_cloud_run_iam and identity_token:
        headers["X-Serverless-Authorization"] = f"Bearer {identity_token}"
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    result_token = request.headers.get("x-job-token")
    if result_token:
        headers["X-Job-Token"] = result_token
    return headers


def _authorize_member_path(claims: dict, path: str) -> str | None:
    """Return a target member e-mail and block cross-member path changes."""
    match = MEMBER_SCOPE_RE.match(path)
    if not match:
        return None
    target_email = unquote(match.group(1)).strip().lower()
    subject = str(claims.get("sub") or "").strip().lower()
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    if target_email != subject and not is_admin:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "MEMBER_SCOPE_FORBIDDEN", "message": "Another member's data cannot be accessed."}},
        )
    return target_email


def _render_job_id_from_url(value: str | None) -> str | None:
    match = STABLE_RENDER_URL_RE.fullmatch(str(value or "").strip())
    return match.group(1) if match else None


async def _render_internal_request(
    request: Request,
    method: str,
    path: str,
    *,
    user_id: str = "",
    admin: bool = False,
    json_body: dict | None = None,
) -> httpx.Response | None:
    upstream = UPSTREAMS["render-service"]
    if not upstream.base_url:
        return None
    try:
        identity_token = ""
        if upstream.requires_cloud_run_iam:
            identity_token = await asyncio.to_thread(TOKEN_CACHE.get, upstream.base_url)
        headers = {"Accept": "application/json", "X-API-Key": upstream.api_key}
        if identity_token:
            headers["X-Serverless-Authorization"] = f"Bearer {identity_token}"
        if user_id:
            headers["X-User-ID"] = user_id
        if admin:
            headers["X-Admin-Request"] = "1"
        return await request.app.state.http_client.request(
            method=method,
            url=f"{upstream.base_url}/{path}",
            headers=headers,
            json=json_body,
            timeout=30,
        )
    except Exception:
        return None


def _safe_render_gateway_url(request: Request, job_id: str, variant: str = "") -> str:
    # Relative URLs keep local development and the formal Firebase origin on
    # the same authenticated path. They also fit the member DB's 500-char field.
    #
    # variant 只有 "" 與 "/before" 兩種；妝前圖是使用者的原始照片，走同一條
    # 需驗證的路徑，權限與妝後圖完全相同。
    #
    # 訪客要多帶票券：這個網址會被放進 `<img src>`，而 img 送不出自訂標頭，
    # 訪客又沒有 cookie 可以自動帶。會員維持乾淨的相對網址，靠 `__session`。
    ticket = str(request.headers.get(GUEST_TICKET_HEADER) or "").strip()
    if ticket and GUEST_TRIAL_ENABLED and not request_access_token(request):
        return f"/media/render/{job_id}{variant}?gt={quote(ticket, safe='')}"
    return f"/media/render/{job_id}{variant}"


def _sanitize_render_payload(request: Request, payload):
    if isinstance(payload, list):
        return [_sanitize_render_payload(request, item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    result = {key: _sanitize_render_payload(request, value) for key, value in payload.items()}
    # 渲染服務的 job 紀錄是整包回來的（_job_view 只濾掉 token），裡面有幾個純內部欄位：
    # objectName / beforeObjectName 是 GCS 的物件路徑（而且含擁有者的 actor id），
    # ownerId 是內部識別碼。bucket 是私有的，拿到路徑也開不了，但這些是實作細節，
    # 瀏覽器不需要、也不該知道——洩漏儲存結構只會幫到想摸清系統的人。
    for internal in ("objectName", "beforeObjectName", "ownerId"):
        result.pop(internal, None)

    job_id = str(result.get("jobId") or "")
    if re.fullmatch(RENDER_JOB_ID, job_id) and result.get("afterImageUrl"):
        result["afterImageUrl"] = _safe_render_gateway_url(request, job_id)
        result.pop("replicateTempUrl", None)
        result["isPermanent"] = True
        # 妝前圖同樣要改寫。渲染服務回的是 GCS 直連網址，那個網址不該進瀏覽器——
        # 改寫成 /media/render/<job>/before，讀取時才會經過擁有者檢查。
        if result.get("beforeImageUrl"):
            result["beforeImageUrl"] = _safe_render_gateway_url(request, job_id, "/before")
    return result


async def _sign_legacy_media(request: Request, value: str, owner_id: str) -> str:
    if not PRIVATE_RENDER_URL_RE.fullmatch(str(value or "").strip()):
        return value
    response = await _render_internal_request(
        request,
        "POST",
        "render/media/sign",
        user_id=owner_id,
        json_body={"url": value},
    )
    if response is None or not response.is_success:
        return f"/media/legacy/{issue_legacy_media_token(value, owner_id)}"
    try:
        signed = str(response.json().get("signedUrl") or "")
        parsed = urlsplit(signed)
        return signed if parsed.scheme == "https" and parsed.netloc == "storage.googleapis.com" else value
    except (TypeError, ValueError):
        return value


async def _refresh_saved_look_media(request: Request, payload, owner_id: str):
    if not isinstance(payload, dict):
        return payload
    looks = payload.get("looks")
    if not isinstance(looks, list):
        return payload
    # 舊收藏可能仍保存 GCS 的原始網址。妝後與妝前都是私人媒體，
    # 兩邊都要在 Gateway 重新換成短效網址；只刷新 after 會讓收藏紀錄存在，
    # 但管理員／會員打開妝前時拿著過期或被擋的 URL，畫面就像「妝前圖消失」。
    media_fields = ("afterImageUrl", "after_image_url", "beforeImageUrl", "before_image_url")
    raw_urls = []
    for look in looks:
        if not isinstance(look, dict):
            continue
        for field in media_fields:
            value = str(look.get(field) or "")
            if PRIVATE_RENDER_URL_RE.fullmatch(value):
                raw_urls.append(value)
    raw_urls = list(dict.fromkeys(raw_urls))
    signed_values = await asyncio.gather(*[_sign_legacy_media(request, value, owner_id) for value in raw_urls])
    replacements = dict(zip(raw_urls, signed_values))
    if not replacements:
        return payload
    result = dict(payload)
    result["looks"] = []
    for look in looks:
        item = dict(look) if isinstance(look, dict) else look
        if isinstance(item, dict):
            for key in media_fields:
                if item.get(key) in replacements:
                    item[key] = replacements[item[key]]
        result["looks"].append(item)
    return result


async def _rollback_saved_look_after_retain_failure(
    request: Request,
    upstream: Upstream,
    path: str,
    response: httpx.Response,
    headers: dict[str, str],
) -> None:
    """Remove a just-created DB row if media retention failed afterwards.

    The member database has no transaction spanning its row and Render's GCS
    objects. If the row was written first and retain then failed, leaving it
    in place creates the exact half-saved look that made the before image
    appear to disappear. This is best-effort cleanup; the original error is
    still returned so the caller can retry.
    """
    try:
        created = response.json()
    except ValueError:
        created = {}
    created_id = created.get("id") if isinstance(created, dict) else None
    if created_id is None and isinstance(created, dict) and isinstance(created.get("look"), dict):
        created_id = created["look"].get("id")
    if created_id is None:
        logging.getLogger(__name__).error("saved look retain failed but DB response had no row id")
        return
    try:
        rollback = await request.app.state.http_client.delete(
            f"{upstream.base_url}/{path}/{quote(str(created_id), safe='')}",
            headers=headers,
            timeout=upstream_timeout("member-database"),
        )
        if not rollback.is_success:
            logging.getLogger(__name__).error(
                "saved look rollback failed status=%s", rollback.status_code
            )
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("saved look rollback failed")


def _saved_media_urls(payload, saved_look_id: str | None = None) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("looks"), list):
        return []
    values = []
    for look in payload["looks"]:
        if not isinstance(look, dict):
            continue
        if saved_look_id is not None and str(look.get("id")) != str(saved_look_id):
            continue
        value = str(look.get("afterImageUrl") or look.get("after_image_url") or "").strip()
        if _render_job_id_from_url(value) or PRIVATE_RENDER_URL_RE.fullmatch(value):
            values.append(value)
    return list(dict.fromkeys(values))


async def _delete_saved_media(
    request: Request,
    values: list[str],
    owner_id: str,
    *,
    admin: bool,
) -> None:
    for value in values:
        job_id = _render_job_id_from_url(value)
        if job_id:
            response = await _render_internal_request(
                request,
                "DELETE",
                f"render/jobs/{job_id}/artifact",
                user_id=owner_id,
                admin=admin,
            )
        elif PRIVATE_RENDER_URL_RE.fullmatch(value):
            response = await _render_internal_request(
                request,
                "DELETE",
                "render/media",
                user_id=owner_id,
                admin=admin,
                json_body={"url": value},
            )
        else:
            continue
        if response is None or not response.is_success:
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "MEDIA_DELETE_INCOMPLETE", "message": "圖片刪除尚未完成，請稍後重試。"}},
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # retries 放在傳輸層：httpx 只在**連線還沒建立**時重試，請求根本沒送出去，
    # 所以對 POST 也是安全的——這跟 request_upstream 那層「只重放讀取」不衝突，
    # 兩者處理的是不同的失敗點（連不上 vs 連上了但邊緣回 5xx）。
    #
    # limits 必須跟著搬到 transport。 給了自訂 transport 之後，AsyncClient 上的
    # limits 會被忽略——留在原地等於預設值悄悄變回 httpx 的 100/20 以外的東西，
    # 而連線池爆掉的症狀（間歇性逾時）跟 tunnel 抖幾乎分不出來。
    app.state.http_client = httpx.AsyncClient(
        follow_redirects=False,
        transport=httpx.AsyncHTTPTransport(
            retries=2,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        ),
        timeout=httpx.Timeout(UPSTREAM_TIMEOUT_SECONDS, connect=10),
    )
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="DecorateMe AI Gateway", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "If-Match", "X-API-Key", "X-Expected-Actor", "X-Guest-Ticket", "X-Job-Token"],
    # 跨來源時瀏覽器預設只讓 JS 讀到少數幾個標頭。不明講的話，前端在非同源情境下
    # 拿不到 Retry-After（顯示不出「請等 N 秒」），也拿不到 X-Request-ID（回報問題時
    # 對不上 log）。正式站走同源 rewrite 用不到這行，本機與 App 開發會用到。
    expose_headers=["Retry-After", "X-Request-ID", "X-Guest-Trial-Remaining", "X-Guest-Trial-Max"],
    max_age=3600,
)
install_api_error_handling(app, "ai-gateway")


# 這道 middleware 必須在 install_api_error_handling 之後註冊：後註冊的在最外層，
# 拿到的是錯誤處理器與 normalize_error_response 都跑完的那個最終回應物件，
# 在它上面設 cookie 才不會被後面重建回應的步驟丟掉。
@app.middleware("http")
async def _apply_pending_member_cookie(request: Request, call_next):
    """把處理過程中輪替出來的會員 session 補到最終回應上。

    上游輪替 session 之後，舊的那份在上游就作廢了。若只在成功的那條路徑把新的封回
    瀏覽器，任何一種失敗（逾時、502、503、被拋出的 HTTPException）都會讓瀏覽器留著
    一份已經作廢的 cookie，下一個請求直接被登出——使用者看到的卻是「分析逾時」，
    兩件事之間沒有任何線索可以連起來。

    所以改成由這個單一出口統一補。端點只要把「怎麼補」放進 request.state。
    """
    response = await call_next(request)
    apply = getattr(request.state, "apply_member_cookie", None)
    if apply is not None:
        try:
            apply(response)
        except Exception:  # noqa: BLE001 — 補不上就維持原樣，不能讓它蓋掉真正的回應
            logging.exception("重新封裝輪替後的會員 session 失敗")
    return response


@app.get("/health")
async def health():
    configured = all(upstream.base_url for upstream in UPSTREAMS.values() if upstream.required_in_production)
    return {
        "status": "ok" if configured else "degraded",
        "service": "ai-gateway",
        "privateUpstreamAuth": "cloud-run-iam",
        "memberAuth": "short-lived-access-token",
        "browserAuth": "member-session-only" if SESSION_ONLY_MODE else "client-key-and-member-session",
        "externalTextUpstream": "enabled-for-demo" if ALLOW_EXTERNAL_TEXT_UPSTREAM else "disabled",
        # "quota-backend-down" 代表訪客次數限制沒有生效——功能還在跑，但已經不限次數。
        # 這一欄存在的理由見 _note_quota_backend_down：不寫出來就沒有人會發現。
        "guestTrial": (
            "disabled" if not GUEST_TRIAL_ENABLED
            else "quota-backend-down" if _GUEST_QUOTA_DEGRADED
            else f"enabled-{GUEST_TRIAL_MAX_RUNS}-runs"
        ),
    }


@app.get("/public-config")
async def public_config():
    """Only publish stable same-origin Gateway paths; never reveal upstream URLs."""
    return {
        "apiMode": "gateway",
        "memberDatabaseUrl": "/member-database",
        "productUrl": "/product-api",
        "crawlerUrl": "/admin-api",
        # 前端據此決定要不要顯示「免費體驗」入口。關掉時前端就照舊要求登入。
        "guestTrialEnabled": GUEST_TRIAL_ENABLED,
        "guestTrialMaxRuns": GUEST_TRIAL_MAX_RUNS if GUEST_TRIAL_ENABLED else 0,
    }


@app.post("/guest/session")
async def guest_session(request: Request):
    """發一張訪客票券，讓未登入的人跑完整的分析與渲染。

    票券只是「這是同一個訪客」的證明，不含任何個資，也換不到會員資料——
    proxy 只認 GUEST_ALLOWED_SERVICES 那兩個服務。
    """
    if not GUEST_TRIAL_ENABLED:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "GUEST_TRIAL_DISABLED", "message": "Guest trial is not enabled."}},
        )
    if not SESSION_SECRET:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "NOT_CONFIGURED", "message": "Gateway session secret is not configured."}},
        )
    issued = issue_guest_ticket(request)
    return {
        "ticket": issued["ticket"],
        "expiresAt": issued["expiresAt"],
        "maxRuns": issued["maxRuns"],
        "remaining": issued["maxRuns"],
    }


@app.get("/guest/quota")
async def guest_quota(request: Request):
    """訪客還剩幾次。票券無效時回 0，前端據此把入口收起來。"""
    if not GUEST_TRIAL_ENABLED:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "GUEST_TRIAL_DISABLED", "message": "Guest trial is not enabled."}},
        )
    guest_id = read_guest_id(request)
    return {
        "maxRuns": GUEST_TRIAL_MAX_RUNS,
        "remaining": guest_trial_remaining(guest_id) if guest_id else 0,
        "ticketValid": bool(guest_id),
    }


@app.get("/media/render/{job_id}/before")
async def render_media_before(job_id: str, request: Request):
    """妝前圖。權限與妝後圖完全相同——它是使用者的原始照片，只能更嚴不能更鬆。"""
    return await _serve_render_media(job_id, request, variant="before")


@app.get("/media/render/{job_id}")
async def render_media(job_id: str, request: Request):
    return await _serve_render_media(job_id, request, variant="after")


async def _serve_render_media(job_id: str, request: Request, variant: str = "after"):
    """Authenticate a member, then redirect to a ten-minute private GCS URL.

    ## 妝前圖對管理員開放（2026-08-29，專案負責人決定）

    2026-07-29 這裡刻意把妝前圖擋在管理員之外，理由是它是使用者上傳的原始臉部
    照片、屬於生物特徵資料，而管理員需要它的正當理由不存在。

    那個「正當理由不存在」的判斷被推翻了：渲染結果的好壞只看妝後圖判斷不了——
    沒有妝前圖就不知道那張臉本來長什麼樣，也就分不出「模型畫得很好」與
    「模型把人換掉了」。負責人兩次明確要求後台要看得到。

    **放寬的是「誰看得到」，不是「看了有沒有痕跡」。** 管理員讀圖一律寫進
    admin_audit_events，成功與失敗都記，`variant` 欄位註明這一次讀的是妝前還是
    妝後——查得出「誰、什麼時候、看了哪一個 job 的原始照片」。這是這種資料唯一
    該有的代價，不要因為「後台本來就看得到」而把它省掉。

    ⚠️ 渲染服務端（`_require_job_owner`）必須同時放行。只改一邊的話，gateway 送了
    admin 旗標而渲染服務照擋，畫面顯示的是「此妝容圖已過期」——那句話跟權限一個字
    都沒關係，會把人帶去完全錯的方向查。
    """
    if not re.fullmatch(RENDER_JOB_ID, job_id):
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    # variant 只會是這兩個字面值，直接拼進 query 沒有注入空間
    query = "?variant=before" if variant == "before" else ""
    # 訪客也要看得到自己剛跑出來的妝前妝後圖。這裡只換出 owner id，實際「這張圖是不是
    # 你的」仍由渲染服務比對 job 的 ownerId——訪客與會員的 id 命名空間不重疊，
    # 所以拿訪客身分換不到任何會員的圖。
    guest_id = read_guest_id(request, allow_query=True) if (GUEST_TRIAL_ENABLED and not request_access_token(request)) else ""
    if guest_id:
        is_admin = False
        owner_id = guest_actor_id(guest_id)
    else:
        claims = require_member_access(request)
        is_admin = str(claims.get("role") or "").strip().lower() == "admin"
        owner_id = opaque_actor_id(str(claims.get("sub") or ""))
    # 妝前妝後都套用管理員豁免（2026-08-29 決定，見上面的 docstring）。
    # 讀取放行，但底下的 _audit 會把這一次讀取記下來，含 variant。
    admin_bypass = is_admin

    audited = False

    def _audit(status_code: int) -> None:
        """管理員讀圖時留一筆。只在 is_admin 記——一般會員讀的一定是自己的，
        擁有者檢查已經保證了這件事，全部記只會把稽核表塞滿而看不出重點。"""
        nonlocal audited
        if not is_admin or audited:
            return
        audited = True
        record_admin_action(
            "render_media.view",
            actor_id=owner_id,
            target_ref=job_id,          # 隨機 32 位十六進位，不是個資
            status_code=status_code,
            request_id=request.headers.get("x-request-id", "")[:128],
            variant=variant,
        )
    response = await _render_internal_request(
        request,
        "GET",
        f"render/jobs/{job_id}/signed-url{query}",
        user_id=owner_id,
        admin=admin_bypass,
    )
    if response is None:
        _audit(503)
        raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
    if response.status_code in {403, 404}:
        _audit(response.status_code)
        raise HTTPException(status_code=response.status_code, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    if not response.is_success:
        fallback = await _render_internal_request(
            request,
            "GET",
            f"render/jobs/{job_id}/content{query}",
            user_id=owner_id,
            admin=admin_bypass,
        )
        if fallback is None or not fallback.is_success:
            _audit(fallback.status_code if fallback is not None else 503)
            raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
        content_type = str(fallback.headers.get("content-type") or "")
        if not content_type.startswith("image/"):
            _audit(503)
            raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
        _audit(200)
        return Response(
            content=fallback.content,
            media_type=content_type.split(";", 1)[0],
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
    try:
        signed_url = str(response.json().get("signedUrl") or "")
    except ValueError:
        signed_url = ""
    parsed = urlsplit(signed_url)
    if parsed.scheme != "https" or parsed.netloc != "storage.googleapis.com":
        _audit(503)
        raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
    _audit(302)
    return RedirectResponse(
        url=signed_url,
        status_code=302,
        headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"},
    )


@app.get("/media/legacy/{media_token}")
async def legacy_render_media(media_token: str, request: Request):
    """Serve an old saved GCS URL through an expiring, member-bound link."""
    claims = require_member_access(request)
    try:
        media_claims = jwt.decode(
            media_token,
            SESSION_SECRET,
            algorithms=["HS256"],
            audience="decorate-me-private-media",
            issuer="decorate-me-ai-gateway",
            options={"require": ["exp", "iat", "url", "ownerId"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    acting_owner_id = opaque_actor_id(str(claims.get("sub") or ""))
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    if acting_owner_id != str(media_claims.get("ownerId") or "") and not is_admin:
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    media_url = str(media_claims.get("url") or "")
    if not PRIVATE_RENDER_URL_RE.fullmatch(media_url):
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    response = await _render_internal_request(
        request,
        "POST",
        "render/media/content",
        user_id=acting_owner_id,
        admin=is_admin,
        json_body={"url": media_url},
    )
    if response is None or not response.is_success:
        raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
    content_type = str(response.headers.get("content-type") or "")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
    return Response(
        content=response.content,
        media_type=content_type.split(";", 1)[0],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/auth/login")
async def login(body: LoginRequest, request: Request):
    # In session-only mode the browser has no reusable API key.  Login is
    # protected by the rate limiter and the member credentials themselves.
    if not SESSION_ONLY_MODE:
        require_any_client_api_key(request.headers.get("x-api-key", ""))
    enforce_login_rate_limit(request, body.email)
    if not MEMBER_DATABASE_URL or not SESSION_SECRET:
        raise HTTPException(status_code=503, detail={"error": {"code": "AUTH_NOT_CONFIGURED", "message": "Member authentication is unavailable."}})

    try:
        response = await request.app.state.http_client.post(
            f"{MEMBER_DATABASE_URL}/api/login",
            json={"email": body.email, "password": body.password},
            headers=with_member_gateway_key({"Accept": "application/json"}),
            timeout=20,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}})

    # 「信箱尚未驗證」必須與「帳密錯誤」分開，否則使用者只會看到「帳號或密碼錯誤」，
    # 完全不知道要去收驗證信——照著重試密碼永遠不會成功。
    #
    # 這裡刻意只透傳這一個碼，不是把上游的錯誤照單全收：其餘的 401/403/404 仍然
    # 一律壓成同一句 INVALID_CREDENTIALS，避免用回應差異枚舉哪些信箱已註冊。
    if response.status_code == 403 and _upstream_error_code(response) == "EMAIL_NOT_VERIFIED":
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "EMAIL_NOT_VERIFIED",
                              "message": "此帳號尚未完成信箱驗證，請至信箱收取驗證碼。",
                              "retryable": False}},
        )
    if response.status_code in {401, 403, 404}:
        # 帳密錯誤才計入限流（這就是暴力破解的樣子）。EMAIL_NOT_VERIFIED 上面已先攔掉，
        # 不會落到這裡——尚未驗證不是猜密碼，不該累積封鎖。
        record_failed_login(request, body.email)
        raise HTTPException(status_code=401, detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."}})
    if response.status_code == 429:
        # 這個 429 是會員資料庫回的，不是 Gateway 自己的限流。用不同的 code 標出來，
        # 否則兩層限流長得一模一樣，出事時分不清是哪一層在擋（實測就卡在這：不同帳號、
        # 不同裝置都被 429，需要先知道是 Gateway 還是 DB 才查得下去）。
        # 注意：若 DB 是以「呼叫端 IP」限流，而它看到的呼叫端永遠是 Gateway 的單一
        # egress IP，那它會把所有使用者的登入都算成同一個來源——這需要 DB 端改成
        # 依 X-Forwarded-For 的真實使用者位址計算（屬資料庫端）。
        upstream_retry = str(response.headers.get("retry-after") or "").strip()
        retry_after = int(upstream_retry) if upstream_retry.isdigit() else LOGIN_RATE_LIMIT_WINDOW_SECONDS
        raise rate_limited_error(
            "MEMBER_SERVICE_RATE_LIMITED",
            f"會員服務目前限制登入頻率，請在 {retry_after} 秒後再試。",
            retry_after,
        )
    if not response.is_success:
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SERVICE_ERROR", "message": "Member authentication failed."}})

    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SERVICE_ERROR", "message": "Member authentication failed."}})
    if payload.get("success") is False:
        record_failed_login(request, body.email)
        raise HTTPException(status_code=401, detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."}})

    member = payload.get("member") or payload.get("user")
    if not isinstance(member, dict) or not member:
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SERVICE_ERROR", "message": "Member authentication failed."}})
    verified_email = str(member.get("email") or "").strip().lower()
    if not verified_email or verified_email != body.email.strip().lower():
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SERVICE_ERROR", "message": "Member authentication failed."}})
    role = str(member.get("role") or member.get("member_role") or "")
    member_status = str(member.get("status") or "active")
    access_token, expires_at = issue_access_token(verified_email, role, member_status)
    upstream_cookie = _upstream_cookie_header(response)
    if not upstream_cookie:
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SESSION_MISSING", "message": "Member authentication failed."}})
    try:
        upstream_cookie = await _validate_upstream_member_cookie(request, upstream_cookie, verified_email)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise HTTPException(
                status_code=502,
                detail={"error": {"code": "MEMBER_SESSION_UNUSABLE", "message": "Member authentication session could not be established."}},
            )
        raise
    actor_id = opaque_actor_id(verified_email)
    payload = {"success": True, "member": member, "expiresAt": expires_at, "actorId": actor_id}
    if not SESSION_ONLY_MODE:
        payload.update({"accessToken": access_token, "tokenType": "Bearer"})
    result = JSONResponse(content=payload)
    sealed_new = seal_member_cookie(upstream_cookie)
    if MULTI_SESSION_ENABLED:
        # 把這個帳號「加」到這個瀏覽器已登入的其他帳號旁邊。
        # 同一個帳號重複登入，就更新（覆蓋）它自己那一個槽位。
        slots = [
            (token, sealed)
            for token, sealed in read_session_slots(request)
            if not (_slot_claims(token) and opaque_actor_id(str(_slot_claims(token).get("sub") or "").strip().lower()) == actor_id)
        ]
        slots.append((access_token, sealed_new))
        set_session_slots(result, slots)
    else:
        set_session_cookie(result, access_token, sealed_new)
    # 每次登入換一個新的 CSRF token，跟 session 同生命週期。
    issue_csrf_cookie(result)
    return result


@app.post("/auth/logout")
async def logout(request: Request):
    result = JSONResponse(content={"ok": True})
    # 多帳號：帶 `?actor=<id>` 只登出那一個帳號，這個瀏覽器上的其他帳號維持登入。
    # 沒帶（或旗標關掉）時，就跟以前一樣把整個 session 清掉。
    actor = str(request.query_params.get("actor") or "").strip()
    remaining: list[tuple[str, str]] = []
    if MULTI_SESSION_ENABLED and actor:
        for token, sealed in read_session_slots(request):
            claims = _slot_claims(token)
            slot_actor = opaque_actor_id(str(claims.get("sub") or "").strip().lower()) if claims else ""
            if slot_actor and slot_actor != actor:
                remaining.append((token, sealed))
    if remaining:
        set_session_slots(result, remaining)
        return result
    result.delete_cookie(key=SESSION_COOKIE, path="/", secure=IS_PRODUCTION, httponly=True, samesite="lax")
    # CSRF token 跟著 session 一起走：留著一個對應不到任何 session 的 token 沒有用處，
    # 只會讓下一位使用者接手一個舊值。
    result.delete_cookie(key=CSRF_COOKIE, path="/", secure=IS_PRODUCTION, httponly=False, samesite="lax")
    # Browsers that signed in before S56 still carry the two retired cookies.
    # Nothing reads them any more, but clearing them on the way out keeps stale
    # credentials from sitting in the jar until they expire on their own.
    for retired in ("dm_session", "dm_member_session"):
        result.delete_cookie(key=retired, path="/", secure=IS_PRODUCTION, httponly=True, samesite="lax")
    return result


@app.get("/auth/session")
async def session_status(request: Request):
    """Verify both Gateway and upstream member sessions before loading private pages."""
    if not MULTI_SESSION_ENABLED:
        claims = require_member_access(request)
        upstream_cookie = await validate_upstream_member_session(request, claims)
        # `sub` tells the browser *who* this session belongs to.  Without it a page
        # that still holds a stale profile in localStorage keeps addressing member
        # routes as the previous account: signing in as an administrator replaces
        # the single `__session` cookie, every member call then asks the database
        # for somebody else's rows, and the 403 that comes back is indistinguishable
        # from a permission bug.  The subject is the caller's own identity, so
        # returning it to the authenticated owner reveals nothing new.
        result = JSONResponse(content={
            "ok": True,
            "sub": str(claims.get("sub") or ""),
            "actorId": opaque_actor_id(str(claims.get("sub") or "")),
            "role": str(claims.get("role") or "member"),
            "status": str(claims.get("status") or "active"),
            "expiresAt": int(claims.get("exp") or 0) * 1000,
        })
        set_session_cookie(result, request_access_token(request), seal_member_cookie(upstream_cookie))
        _refresh_csrf_cookie(request, result)
        return result

    # 多帳號：回報這個分頁選中的帳號（全新分頁則預設用最新登入的那個），外加這個
    # 瀏覽器上所有已登入帳號的清單，讓前端可以畫出「帳號切換器」。只回傳 opaque actor
    # 與呼叫者自己本來就擁有的 subject——不會外洩其他帳號的任何資料。
    accounts = session_accounts(request)
    if not accounts:
        require_member_access(request)  # preserves the 401 MEMBER_AUTH_* contract
    selector = str(request.headers.get("x-expected-actor") or "").strip()
    account = None
    if selector:
        for candidate in accounts:
            if secret_equals(selector, candidate["actorId"]):
                account = candidate
                break
        if account is None:
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "ACCOUNT_NOT_AVAILABLE", "message": "登入帳號已在其他分頁變更，請重新整理頁面後再操作。"}},
            )
    else:
        account = accounts[-1]  # 全新分頁沒帶選擇器時，預設用最新登入的帳號
    upstream_cookie = await _validate_upstream_member_cookie(
        request, unseal_member_cookie(account["sealed"]), account["sub"]
    )
    result = JSONResponse(content={
        "ok": True,
        "sub": account["sub"],
        "actorId": account["actorId"],
        "role": account["role"],
        "status": account["status"],
        "expiresAt": int(account["claims"].get("exp") or 0) * 1000,
        "accounts": [
            {"actorId": a["actorId"], "sub": a["sub"], "role": a["role"], "status": a["status"]}
            for a in accounts
        ],
    })
    sealed = seal_member_cookie(upstream_cookie)
    rebuilt: list[tuple[str, str]] = []
    for token, slot_sealed in read_session_slots(request):
        slot_claims = _slot_claims(token)
        slot_actor = opaque_actor_id(str(slot_claims.get("sub") or "").strip().lower()) if slot_claims else ""
        rebuilt.append((account["token"], sealed) if slot_actor == account["actorId"] else (token, slot_sealed))
    set_session_slots(result, rebuilt)
    _refresh_csrf_cookie(request, result)
    return result


def _upstream_error_code(response) -> str:
    """取出上游 JSON 裡的 error.code；格式不符時回空字串。

    上游壞掉或回了非 JSON 時不能讓登入整個爆掉——取不到就當作沒有，
    呼叫端會落到一般的錯誤處理。
    """
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "")
    return str(payload.get("code") or "")


# Cloudflare 的邊緣錯誤碼（520–530）跟一般 5xx 一樣，都代表「上游這次沒回答」。
# tunnel 斷線是 1033，也就是 530——它是一個**成功抵達**的 HTTP 回應，所以 httpx
# 不會拋例外，呼叫端那些 except httpx.HTTPError 一個都不會進。
UPSTREAM_EDGE_FAILURE_STATUSES = frozenset(range(520, 531)) | {502, 503, 504}
# 可以安全重放的方法。POST/PUT/PATCH/DELETE 一律不重試：上游可能已經處理完才斷線，
# 重放會變成第二筆收藏、第二次扣點、第二張訂單。
REPLAYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
UPSTREAM_RETRY_BACKOFF_SECONDS = (0.25, 0.75)


async def request_upstream(client, *, method: str, url: str, **kwargs):
    """送出上游請求，可安全重放的方法在邊緣故障時重試。

    自架上游走的是 trycloudflare 快速通道，斷線是常態不是例外：三天的日誌裡有
    約四十筆 502/503/530。其中不少是**孤立的單筆**——tunnel 抖一下就自己回來了，
    但 httpx 預設 retries=0，所以那一瞬間的每個請求都變成使用者看得到的錯誤。

    這只減少雜訊，不能代替穩定的通道。 2026-09-04 那次斷了兩分半，重試救不了；
    它救得了的是那種一筆就過去的閃斷。

    只重試讀取。 重試寫入等於在「上游其實做完了，只是回應沒送到」的情況下再做一次，
    而那正是收藏、扣點、下單會長出重複資料的路徑。
    """
    attempts = (len(UPSTREAM_RETRY_BACKOFF_SECONDS) + 1
                if str(method or "").upper() in REPLAYABLE_METHODS else 1)
    for attempt in range(attempts):
        final = attempt + 1 >= attempts
        try:
            response = await client.request(method=method, url=url, **kwargs)
        except httpx.HTTPError:
            # 最後一次要把例外原樣丟回去，讓呼叫端既有的 except 照常決定
            # 要回 502 還是 504——這裡不該自己發明新的錯誤形狀。
            if final:
                raise
        else:
            if final or response.status_code not in UPSTREAM_EDGE_FAILURE_STATUSES:
                return response
        await asyncio.sleep(UPSTREAM_RETRY_BACKOFF_SECONDS[attempt])


def upstream_failure_payload(response) -> tuple[int, dict] | None:
    """上游失敗而且回的不是它自己的 JSON 時，換一份乾淨的。照原樣轉就回 None。

    Cloudflare 的 tunnel 錯誤頁（Error 1033）是一整頁 HTML，而且**頁面裡印著
    tunnel 的主機名稱**。原樣轉出去會同時壞掉兩件事：

      1. 前端在等 JSON，拿到的是 7KB 的 HTML。res.json() 直接爆，所以使用者看到
         的永遠是一句沒有資訊的通用錯誤——即使上游其實把話講得很清楚。
      2. 那個主機名稱會出現在瀏覽器裡。Gateway 存在的理由之一就是「瀏覽器永遠
         不會知道上游網址」（見 proxy_public_member_request 的 docstring），
         而那些 tunnel 沒有 Gateway 這一層的授權檢查。上游正常時這個保證成立，
         上游一掛就破功——偏偏那正是有人會打開 F12 的時候。

    上游自己的 JSON 錯誤要原樣保留。 「收藏妝容已達 50 筆上限」這種訊息是使用者
    唯一能據以行動的東西；把它一起換成「服務暫時無法使用」等於把診斷資訊丟掉，
    而那正是這次查了兩天才查到上限的原因。
    """
    if response.is_success:
        return None
    if "json" in str(response.headers.get("content-type") or "").lower():
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, (dict, list)):
            return None
    if response.status_code >= 500:
        # 上游的 5xx 對前端沒有意義，尤其 530 這種 Cloudflare 專用碼。
        # 一律收斂成 502，跟連不上時的既有行為一致。
        return 502, {"error": {"code": "UPSTREAM_UNAVAILABLE",
                               "message": "服務暫時無法使用，請稍後再試。",
                               "retryable": True}}
    return response.status_code, {"error": {"code": "UPSTREAM_ERROR",
                                            "message": "上游服務無法處理這次請求。",
                                            "retryable": False}}


async def proxy_public_member_request(request: Request, upstream_path: str):
    """Forward only the three pre-login member operations.

    These routes deliberately do not accept arbitrary paths.  The browser can
    register or verify an OTP, but it never learns the member database URL.
    Login attempts and OTP operations share the gateway rate limiter.
    """
    body = await request.body()
    # 從 body 取 email 只為了限流的帳號維度，取不到就退回只有 IP 那一維——這裡不驗證
    # 格式，也不因為解析失敗就擋下請求，那是上游會員資料庫的判斷。
    signup_email = ""
    try:
        parsed = json.loads(body.decode("utf-8")) if body else {}
        if isinstance(parsed, dict):
            signup_email = str(parsed.get("email") or "")
    except (UnicodeDecodeError, json.JSONDecodeError):
        signup_email = ""
    enforce_signup_rate_limit(request, signup_email)
    if len(body) > 256 * 1024:
        raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}})
    if not MEMBER_DATABASE_URL:
        raise HTTPException(status_code=503, detail={"error": {"code": "AUTH_NOT_CONFIGURED", "message": "Member authentication is unavailable."}})
    headers = with_member_gateway_key({
        "Accept": request.headers.get("accept", "application/json"),
        "Content-Type": request.headers.get("content-type", "application/json"),
    })
    try:
        response = await request.app.state.http_client.post(
            f"{MEMBER_DATABASE_URL}{upstream_path}",
            content=body,
            headers=headers,
            timeout=20,
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": {"code": "MEMBER_SERVICE_TIMEOUT", "message": "Member service timed out."}})
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member service is unavailable."}})
    response_headers = {"X-Content-Type-Options": "nosniff"}
    if response.headers.get("content-type"):
        response_headers["content-type"] = response.headers["content-type"]
    # 這條路徑最需要這道處理，卻是最後才補上的。
    #
    # 登入、註冊、忘記密碼、驗證碼是**未登入的人**也打得到的四條路由，而且會員資料庫
    # 的 tunnel 斷線時它們正好是最常被打的：2026-09-02 到 09-03 的日誌裡有 13 筆
    # 502/530 落在 /auth/register 與 /auth/forgot-password 上。原樣轉出去的話，
    # 那頁 Cloudflare 錯誤頁會把 *.trycloudflare.com 的主機名稱印給任何一個
    # 打得開 F12 的訪客看——而這支函式的 docstring 正好寫著「瀏覽器永遠不會知道
    # 會員資料庫的網址」。
    sanitised = upstream_failure_payload(response)
    if sanitised is not None:
        status_code, payload = sanitised
        response_headers["content-type"] = "application/json"
        return Response(content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        status_code=status_code, headers=response_headers)
    return Response(content=response.content, status_code=response.status_code, headers=response_headers)


@app.post("/auth/register")
async def register(request: Request):
    return await proxy_public_member_request(request, "/api/register")


@app.post("/auth/send-otp")
async def send_otp(request: Request):
    return await proxy_public_member_request(request, "/api/send-otp")


@app.post("/auth/forgot-password")
async def forgot_password(request: Request):
    return await proxy_public_member_request(request, "/api/forgot-password")


@app.post("/auth/verify-otp")
async def verify_otp(request: Request):
    return await proxy_public_member_request(request, "/api/verify-otp")


async def proxy_admin_request(request: Request, upstream_path: str):
    # 管理端的寫入（改權限、刪商品、停權會員）要多過一關 double-submit CSRF。
    # `X-Expected-Actor` 擋的是「寫到別人的帳號上」，擋不了「別的網站叫你的瀏覽器寫」。
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        is_write = str(request.method or "").upper() in STATE_CHANGING_METHODS
        claims = _require_admin_claims(select_account(request, for_write=is_write)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))
    if not PRODUCT_DATABASE_URL or not PRODUCT_ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail={"error": {"code": "ADMIN_PROXY_NOT_CONFIGURED", "message": "Admin proxy is not configured."}})

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > ADMIN_PROXY_MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail={"error": {"code": "REQUEST_TOO_LARGE", "message": "Request body is too large."}})
        except ValueError:
            raise HTTPException(status_code=400, detail={"error": {"code": "BAD_CONTENT_LENGTH", "message": "Invalid Content-Length header."}})
    body = await request.body()
    if len(body) > ADMIN_PROXY_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"error": {"code": "REQUEST_TOO_LARGE", "message": "Request body is too large."}})

    headers = {
        "Accept": request.headers.get("accept", "application/json"),
        "Authorization": f"Bearer {PRODUCT_ADMIN_API_KEY}",
        "X-Admin-Actor": opaque_actor_id(str(claims.get("sub") or "")),
        "X-Request-ID": request.headers.get("x-request-id", secrets.token_hex(16))[:128],
    }
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    if request.headers.get("if-match"):
        headers["If-Match"] = request.headers["if-match"][:32]

    try:
        response = await request_upstream(
            request.app.state.http_client,
            method=request.method,
            url=f"{PRODUCT_DATABASE_URL}{upstream_path}",
            params=list(request.query_params.multi_items()),
            headers=headers,
            content=body,
            timeout=ADMIN_PROXY_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"detail": {"error": {"code": "PRODUCT_UPSTREAM_TIMEOUT", "message": "Product service timed out.", "retryable": True}}})
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"detail": {"error": {"code": "PRODUCT_SERVICE_UNAVAILABLE", "message": "Product service is unavailable.", "retryable": True}}})

    # 上游用「商品管理金鑰」認我們，跟瀏覽器的登入 session 是兩回事。
    #
    # 走到這裡代表管理員的 session 已經驗過了（上面的 _require_admin_claims）。
    # 所以上游再回 401/403，講的一定是**它不接受我們的金鑰**，或它根本不是商品服務——
    # 原樣傳回去的話，前端會照 401 顯示「登入狀態已失效，請重新登入」，
    # 而使用者才剛登入，重登一百次也不會好。
    #
    # 2026-08-28 就是這樣：PRODUCT_DATABASE_URL 指到會員資料庫，
    # 它不認得商品管理金鑰，於是新增／刪除／稽核全部變成「請先登入」。
    if response.status_code in (401, 403):
        logging.warning("商品上游拒絕管理請求 status=%s path=%s", response.status_code, upstream_path)
        return JSONResponse(
            status_code=502,
            content={"detail": {"error": {
                "code": "PRODUCT_UPSTREAM_REJECTED",
                "message": "商品服務不接受這次管理操作（你的登入是有效的）。"
                           "請確認 Gateway 的 PRODUCT_DATABASE_URL 指向商品服務。",
                "retryable": False,
                "details": {"upstreamStatus": response.status_code},
            }}},
        )

    response_headers = {"X-Content-Type-Options": "nosniff"}
    for header in ("content-type", "cache-control", "retry-after", "x-request-id"):
        if response.headers.get(header):
            response_headers[header] = response.headers[header]
    # 商品的建立／修改／刪除留一筆稽核。商品 ID 不是個資，可以原樣記；管理員一律
    # 只記雜湊後的 actorId。成功與失敗都記——「有人試著刪但被擋下」同樣是要知道的事。
    method = str(request.method or "").upper()
    if method in STATE_CHANGING_METHODS:
        record_admin_action(
            _audit_action("product", method),
            actor_id=headers["X-Admin-Actor"],
            target_ref=upstream_path,
            status_code=response.status_code,
            request_id=headers["X-Request-ID"],
            # 失敗時把上游的錯誤**代碼**一併記下來。
            #
            # 2026-08-26：稽核裡出現一筆 `product.create → 400 failure`，但只有狀態碼，
            # 查不出是哪個欄位不合格——只好回頭問管理員「你看到什麼訊息」。
            # 一筆記錄不下去原因的失敗紀錄，等於把診斷工作丟回給人做。
            #
            # 只記代碼不記訊息與 body：body 很可能就是商品資料，而 message 是給人看的
            # 自由文字，兩者都不該落進稽核表（見 record_admin_action 對 extra 的限制）。
            # 成功時不記——稽核已經有狀態碼，多一個空欄位只是雜訊。
            upstream_error=(_upstream_error_code(response)
                            if response.status_code >= 400 else ""),
        )
    sanitised = upstream_failure_payload(response)
    if sanitised is not None:
        status_code, payload = sanitised
        response_headers["content-type"] = "application/json"
        response_headers.pop("cache-control", None)
        # 這條路徑的錯誤外層多包一層 detail，跟上面那兩個 JSONResponse 一致——
        # 後台的錯誤解析讀的是 detail.error，少了它會變成「未知錯誤」。
        return Response(content=json.dumps({"detail": payload}, ensure_ascii=False).encode("utf-8"),
                        status_code=status_code, headers=response_headers)
    return Response(content=response.content, status_code=response.status_code, headers=response_headers)


@app.api_route("/admin-api/products", methods=["GET", "POST"])
async def admin_products(request: Request):
    return await proxy_admin_request(request, "/api/products")


@app.api_route("/admin-api/products/{product_id}", methods=["GET", "PATCH", "DELETE"])
async def admin_product(product_id: str, request: Request):
    safe_id = validate_path_segment(product_id)
    return await proxy_admin_request(request, f"/api/products/{safe_id}")


# 刪除前的影響查詢：這一筆商品被幾個人收藏、放在幾個購物車裡。
#
# 硬刪除是不可逆的，而它會讓別人的收藏變成「已下架」。在按下之前先看到
# 「這會影響 12 個人的收藏」，跟按下之後才知道，是兩件不同的事。
#
# 這條路由必須獨立寫：上面那條的 {product_id} 只吃單一片段，
# `901/delete-impact` 有斜線，配不到，前端打過來會是 404。
@app.get("/admin-api/products/{product_id}/delete-impact")
async def admin_product_delete_impact(product_id: str, request: Request):
    safe_id = validate_path_segment(product_id)
    return await proxy_admin_request(request, f"/api/products/{safe_id}/delete-impact")


# 爬蟲只寫入 crawler_staging_products，不再與前端直連。
# 新流程為：爬蟲、暫存表、管理員審核、匯入正式商品。
#
# 上游路徑集中在這一個常數。 商品後端還沒回覆最終路徑，這裡先照
# 「給商品後端_暫存商品審核與匯入_接入規格書_2026-07-29.md」§1 的提案接。
# 對方定案後只要改這一行，四條路由與前端都不必動。
_STAGING_BASE = "/api/crawler-staging/products"


@app.get("/admin-api/crawler-staging/products")
async def admin_staging_list(request: Request):
    return await proxy_admin_request(request, _STAGING_BASE)


# GET 與 PATCH 同一條路徑、同一個函式體，照鄰居 admin_product 的寫法合併成一條。
# GET 目前前端沒用（列表已帶齊欄位），但放行它不增加風險——上游沒做就是 404。
@app.api_route("/admin-api/crawler-staging/products/{staging_id}", methods=["GET", "PATCH"])
async def admin_staging_item(staging_id: str, request: Request):
    return await proxy_admin_request(request, f"{_STAGING_BASE}/{validate_path_segment(staging_id)}")


@app.post("/admin-api/crawler-staging/products/{staging_id}/import")
async def admin_staging_import(staging_id: str, request: Request):
    return await proxy_admin_request(request, f"{_STAGING_BASE}/{validate_path_segment(staging_id)}/import")



async def _face_internal_request(request: Request, method: str, path: str, *,
                                 user_id: str = "", admin: bool = False,
                                 json_body: dict | None = None):
    """打臉部服務的內部呼叫。跟 _render_internal_request 同一套，只是換上游。

    BASIC 與 PRO 是兩個部署，但貢獻樣本存在同一個 GCS 前綴，所以刪除打其中一個就夠。
    這裡固定用 face-basic：PRO 不見得有部署，而刪除不該因為某個服務沒開就漏做。
    """
    upstream = UPSTREAMS["face-basic"]
    if not upstream.base_url:
        return None
    try:
        identity_token = ""
        if upstream.requires_cloud_run_iam:
            identity_token = await asyncio.to_thread(TOKEN_CACHE.get, upstream.base_url)
        headers = {"Accept": "application/json", "X-API-Key": upstream.api_key}
        if identity_token:
            headers["X-Serverless-Authorization"] = f"Bearer {identity_token}"
        if user_id:
            headers["X-User-ID"] = user_id
        if admin:
            headers["X-Admin-Request"] = "1"
        return await request.app.state.http_client.request(
            method=method, url=f"{upstream.base_url}/{path}", headers=headers, timeout=60,
            json=json_body,
        )
    except Exception:
        return None


@app.patch("/admin-api/face-feedback/{feedback_id}/review")
async def admin_review_face_feedback(feedback_id: str, request: Request):
    """管理員把一筆修正標成採用或退回。

    這是「使用者修正 → 人工覆核 → 進訓練集」這條線的中間那一段。少了它，
    上面 admin_face_feedback 就只是一個看得到、動不了的列表：修正躺在 Firestore 裡，
    重訓時只能全收或全不收——全收會把使用者的誤點也學進去，全不收等於這批
    免費標註白拿。

    驗證跟讀取那條完全一樣（同一批管理員、同一份 CSRF），差別只在這條會寫。
    """
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=True)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    face = await _face_internal_request(
        request, "PATCH", f"v1/face/feedback/{quote(feedback_id, safe='')}/review",
        admin=True, json_body={
            "decision": body.get("decision"),
            "decisions": body.get("decisions"),
            "labels": body.get("labels"),
            "note": body.get("note"),
        })
    if face is None:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "FACE_FEEDBACK_UNAVAILABLE",
                              "message": "暫時連不上臉部服務，覆核沒有寫進去，請稍後再試。"}},
        )
    # 上游的 4xx 要原樣傳回去，不要一律翻成 503——「這筆找不到」跟「服務掛了」
    # 是完全不同的處理方式，混成同一個訊息會讓管理員一直重試一筆不存在的資料。
    if not face.is_success:
        try:
            detail = face.json().get("detail") or face.json()
        except Exception:
            detail = {"error": {"code": "FACE_FEEDBACK_ERROR", "message": "覆核沒有寫進去。"}}
        raise HTTPException(status_code=face.status_code, detail=detail)
    return JSONResponse(content=face.json())


@app.delete("/admin-api/members/{email}/media")
async def admin_purge_member_media(email: str, request: Request):
    """刪除這個會員留在臉部與渲染服務的影像。**刪會員之前要先呼叫這一條。**

    為什麼一定要經過 Gateway：那兩個服務認的是 opaque `ownerId`，而它是
    `sha256(SESSION_SECRET + email)` 算出來的——只有 Gateway 有那把金鑰。
    會員資料庫端拿不到、也不該拿到，所以它自己刪不了那些影像。

    為什麼是獨立的一條而不是併進刪會員：刪會員是資料庫端的端點，前端後台直接打它。
    要它反過來呼叫我們，等於多一個跨團隊相依。這條讓後台在刪除前自己先清乾淨，
    順序由呼叫端掌握。

    **回傳每個服務各刪幾筆，而且失敗不會被吞掉**——刪不掉要讓管理員知道，
    不能顯示「已刪除」而實際留著臉部資料。
    """
    claims = require_admin_access(request)
    target = str(email or "").strip().lower()
    if not target or "@" not in target or len(target) > 254:
        raise HTTPException(status_code=400,
                            detail={"error": {"code": "INVALID_REQUEST", "message": "Invalid email."}})
    owner_id = opaque_actor_id(target)

    results, failed = {}, []
    face = await _face_internal_request(request, "DELETE", f"v1/face/users/{owner_id}",
                                        user_id=owner_id, admin=True)
    if face is not None and face.is_success:
        results["face"] = face.json().get("contributions", 0)
    else:
        failed.append("face")
    render = await _render_internal_request(request, "DELETE", f"render/users/{owner_id}",
                                            user_id=owner_id, admin=True)
    if render is not None and render.is_success:
        results["render"] = "deleted"
    else:
        failed.append("render")

    # 稽核一定要記：這是管理員代替使用者刪除臉部資料，而且刪了就回不來。
    record_admin_action(
        "member.purge_media",
        actor_id=opaque_actor_id(str(claims.get("sub") or "")),
        target_ref=owner_id,          # 不記 email，那是個資；owner_id 已足以追蹤
        status_code=200 if not failed else 502,
        request_id=request.headers.get("x-request-id", "")[:128],
        failed_services=",".join(failed),
    )
    if failed:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "MEDIA_PURGE_INCOMPLETE",
                              "message": f"這些服務沒有清除成功：{'、'.join(failed)}。"
                                         f"請重試，成功之前不要刪除會員帳號。",
                              "retryable": True, "details": results}},
        )
    return {"status": "purged", "ownerId": owner_id, "removed": results}



# 渲染服務的 Firestore 集合。改名的話 render/replicate_render_api.py 要一起改。
# 這裡讀它是為了做「儲存空間 ↔ 會員名冊」的對帳（見 admin_member_storage_audit）：
# 那個集合就是 GCS 的索引，兩邊零落差（2026-08-29 一次性對帳確認過），
# 所以查 Firestore 等於查 GCS，而且不需要 google-cloud-storage
# （gateway 的 requirements 只有 firestore）。
RENDER_JOBS_COL = os.getenv("RENDER_JOBS_COLLECTION", "render_jobs")


async def _member_directory_emails(request: Request) -> list[str]:
    """目前會員名冊上的 email。只給對帳用，不回給瀏覽器。"""
    if not MEMBER_DATABASE_URL:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE",
                              "message": "Member directory is unavailable."}},
        )
    headers = with_member_gateway_key({
        "Accept": "application/json",
        "Cookie": require_upstream_member_cookie(request),
    })
    try:
        response = await request.app.state.http_client.get(
            f"{MEMBER_DATABASE_URL}/api/members", headers=headers, timeout=20)
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE",
                              "message": "Member directory is unavailable."}},
        )
    if not response.is_success:
        # 名冊讀不到就**中止**，不要拿一份空名冊去比對——那會讓每一筆儲存資料
        # 都被判成孤兒，畫面上會顯示「全部會員都不見了」，而真相只是這一次讀取失敗。
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "MEMBER_DIRECTORY_UNREADABLE",
                              "message": "讀不到會員名冊，無法對帳（沒有拿空名冊去比，"
                                         "否則會把所有資料誤判成孤兒）。",
                              "retryable": True,
                              "details": {"upstreamStatus": response.status_code}}},
        )
    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "MEMBER_DIRECTORY_UNREADABLE",
                              "message": "會員名冊回的不是 JSON，無法對帳。", "retryable": True}},
        )
    rows = payload.get("items") or payload.get("members") or payload.get("data") or []
    if not isinstance(rows, list):
        rows = []
    emails = []
    for row in rows:
        if isinstance(row, str):
            candidate = row
        elif isinstance(row, dict):
            candidate = row.get("email") or row.get("memberEmail") or row.get("account") or ""
        else:
            continue
        candidate = str(candidate or "").strip().lower()
        if candidate and "@" in candidate:
            emails.append(candidate)
    return emails


@app.get("/admin-api/member-storage-audit")
async def admin_member_storage_audit(request: Request):
    """儲存空間裡有資料、會員名冊上卻沒有這個人——把差額算出來。

    ## 為什麼需要這條

    2026-08-28 會員數從 10 掉到 6，而那些人的渲染圖還在 GCS 裡。當時只能靠人工
    一次性對帳去查，查完就沒有了；下次再發生一樣要重來一次，而且沒有人會主動想到要查。
    這條把那件事變成後台按一顆按鈕就有答案的常備機制。

    ## 它怎麼查

    渲染資料在 GCS，索引在 Firestore 的 `render_jobs`，兩邊零落差（同日對帳確認），
    所以查 Firestore 就等於查 GCS，而且不必把 google-cloud-storage 裝進 gateway。

    每一筆 job 上只有 `ownerId`，那是 `sha256(SESSION_SECRET + email)` 的前 24 碼。
    **這是單向的**：拿到 ownerId 推不回 email。所以對帳只能往「有 email 的那一邊」算——
    把名冊上每個 email 各自雜湊一次，得到一份 ownerId 的集合，再去比對儲存空間裡的
    ownerId。這也是為什麼下面回的孤兒資料**沒有 email 欄位**：不是省略，是算不出來。

    ## 三種歸類

    - `matched`  ownerId 對得上名冊上的某個人。正常。
    - `guest`    `guest_` 開頭，訪客試用留下的，本來就不會在會員名冊上。正常。
    - `orphan`   有資料、不是訪客、名冊上卻沒有對應的人。**這就是要找的差額。**

    孤兒資料能做的事只有「清掉」或「留著」——重建不了，因為 email 回不來。
    畫面上要把這件事講清楚，不要讓管理員以為按個鈕就能把人救回來。
    """
    claims = require_admin_access(request)
    enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    # 先讀名冊。讀不到就整條中止（見 _member_directory_emails）——
    # 順序刻意是名冊在前：Firestore 那邊即使讀成功，沒有名冊也算不出任何結論。
    emails = await _member_directory_emails(request)
    owner_to_member = {opaque_actor_id(email): email for email in emails}

    try:
        rows = await asyncio.to_thread(job_store.all_jobs, RENDER_JOBS_COL)
    except Exception:
        logging.exception("讀取渲染工作紀錄失敗")
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "RENDER_INDEX_UNAVAILABLE",
                              "message": "暫時讀不到渲染紀錄，請稍後再試。", "retryable": True}},
        )

    owners: dict[str, dict] = {}
    for row in rows or []:
        owner_id = str(row.get("ownerId") or "").strip()
        if not owner_id:
            continue
        bucket = owners.setdefault(owner_id, {
            "ownerId": owner_id, "jobs": 0, "retained": 0, "objects": 0,
            "firstSeen": None, "lastSeen": None,
        })
        bucket["jobs"] += 1
        if row.get("retained"):
            bucket["retained"] += 1
        # 妝後圖與妝前圖各算一個物件；妝前圖常常是 None（早期的資料還沒開始存）。
        bucket["objects"] += sum(1 for f in ("objectName", "beforeObjectName") if row.get(f))
        created = row.get("createdAt")
        if created is not None:
            if bucket["firstSeen"] is None or created < bucket["firstSeen"]:
                bucket["firstSeen"] = created
            if bucket["lastSeen"] is None or created > bucket["lastSeen"]:
                bucket["lastSeen"] = created

    orphans, matched, guests = [], 0, 0
    for owner_id, bucket in owners.items():
        if owner_id.startswith("guest_"):
            guests += 1
        elif owner_id in owner_to_member:
            matched += 1
        else:
            orphans.append(bucket)
    orphans.sort(key=lambda b: (-b["jobs"], b["ownerId"]))

    # 名冊上有、但儲存空間裡一筆資料都沒有的人。不是問題（沒渲染過就是沒有），
    # 但兩個數字擺在一起才看得出「6 個會員裡有幾個真的用過」。
    members_without_storage = sum(1 for owner_id in owner_to_member if owner_id not in owners)

    return {
        "status": "ok",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "members": len(owner_to_member),
            "jobs": len(rows or []),
            "owners": len(owners),
            "matchedOwners": matched,
            "guestOwners": guests,
            "orphanOwners": len(orphans),
            "orphanJobs": sum(b["jobs"] for b in orphans),
            "membersWithoutStorage": members_without_storage,
        },
        # ownerId 就是 opaque id 本身，公開它不洩漏 email（單向雜湊），
        # 而管理員需要它才能指名要清哪一筆。
        "orphans": orphans[:200],
        "orphansTruncated": len(orphans) > 200,
        # 講給畫面看的：這件事能做什麼、不能做什麼。寫在回應裡而不是只寫在前端，
        # 是因為之後用 curl 直接打這條的人也需要知道。
        "recoverable": False,
        "note": "ownerId 是 email 的單向雜湊，孤兒資料推不回 email，"
                "因此只能選擇清除或保留，無法重建會員。",
    }

@app.get("/admin-api/product-audit-logs")
async def admin_product_audit_logs(request: Request):
    return await proxy_admin_request(request, "/api/admin/product-audit-logs")


@app.get("/admin-api/admin-actions")
async def admin_actions(request: Request):
    """Gateway 自己記的管理操作紀錄，給後台「最近操作」用。

    跟上面那條 `/admin-api/product-audit-logs` 的差別，也是這條要單獨存在的理由：
    那一條是代理商品後端的稽核表，能不能查得到、記了什麼，都由對方決定。
    這一條讀的是 `record_admin_action()` 一直在寫的 `admin_audit_events` ——
    每一筆經過 Gateway 的商品／會員增改刪都在裡面，包含失敗的那些，
    而且商品後端就算掛了也照樣查得到。管理員誤刪之後要回答「誰、什麼時候、動了哪一筆」，
    靠的是這一份。

    只回雜湊過的 actorId，不回 email——理由見 admin_audit 的模組說明。
    """
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=False)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    try:
        limit = int(request.query_params.get("limit", "100"))
    except ValueError:
        limit = 100
    return JSONResponse(content={"ok": True, "events": recent_admin_actions(limit)})


@app.get("/admin-api/face-feedback")
async def admin_face_feedback(request: Request):
    """使用者對五官判斷做的修正，給管理端做第二次人工檢查。

    為什麼要有人看：這些修正會**直接變成重訓的標籤**，但寫進去之前沒有任何人檢查過。
    使用者可能誤點，也可能自己判斷錯——眉型、唇型這種本來就主觀。一筆錯標籤混進
    訓練集，之後分數變差會很難查回是哪裡來的。

    走 face-basic 的內部路由：BASIC 與 PRO 是兩個部署，但修正存在**同一個 Firestore
    集合**，所以讀其中一個就夠；固定用 basic 的理由跟刪除那條一樣——PRO 不見得有部署。
    """
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=False)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    try:
        limit = max(1, min(int(request.query_params.get("limit", "50")), 200))
    except ValueError:
        limit = 50

    # 直接讀 Firestore，不繞 face-basic。
    #
    # 那一跳是這個畫面最慢的地方：face-basic 的 min-instances 是 0（刻意的，常駐每天
    # 約 NT$246），所以沒人用的時候開後台要先等它冷啟動十幾秒。而這裡要的只是同一個
    # Firestore 集合的內容，gateway 本來就有 job_store 與憑證，跳過去零成本——
    # Firestore 讀 108 筆的費用是四捨五入到零的程度。
    #
    # 寫入（覆核）仍然走 face：那條路徑有 REVIEW_DECISIONS 白名單與文件存在性檢查，
    # 複製到這裡就會變成兩份驗證邏輯，而寫入不頻繁，慢一點無所謂。
    try:
        rows = await asyncio.to_thread(
            job_store.all_jobs, FACE_FEEDBACK_COL, limit=limit,
            order_by="createdAt", descending=True)
    except Exception:
        logging.exception("讀取修正紀錄失敗")
        # 讀不到就明說，不要回空陣列——空陣列會被看成「使用者都沒有修正過」，
        # 那是完全相反的結論。
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "FACE_FEEDBACK_UNAVAILABLE",
                              "message": "暫時讀不到修正紀錄，請稍後再試。"}},
        )

    items = []
    for row in rows:
        predicted = row.get("predicted") or {}
        corrections = row.get("corrections") or {}
        items.append({
            "feedbackId": row.get("feedbackId"),
            "jobId": row.get("jobId"),
            "mode": row.get("mode"),
            "createdAt": row.get("createdAt"),
            "reviewStatus": row.get("reviewStatus") or "pending",
            # 逐部位的決定。摘要（reviewStatus）只夠畫一個狀態標籤，
            # 但畫面上每個部位都要各自顯示採用或退回，靠的是這個。
            "reviewDecisions": row.get("reviewDecisions") or {},
            # corrected 時管理員給的正確類別。訓練匯入用它覆寫使用者的答案。
            "reviewLabels": row.get("reviewLabels") or {},
            "reviewedAt": row.get("reviewedAt"),
            "reviewNote": row.get("reviewNote") or "",
            "predictionConfidence": row.get("predictionConfidence") or {},
            "hasSample": bool(row.get("contributed")),
            # 這兩個欄位畫面上有在用，而這條路徑是後台唯一的資料來源（列表已經改成
            # 直接讀 Firestore、不繞 face），所以漏掉一個就是那個功能整個不會動：
            #   trainingRunId    分辨「已送訓但還沒進批次」與「已經在某一批裡」
            #   samplesDeletedAt 說明影像是真的刪掉了，不是被隱藏起來
            "trainingRunId": row.get("trainingRunId") or "",
            "samplesDeletedAt": row.get("samplesDeletedAt") or "",
            # 這裡**不回任何身分欄位**：文件本來就不存 email 或 ownerId
            # （見 face_feedback.save），這裡也不去別的地方湊。
            "changes": [{"field": f, "predicted": predicted.get(f), "corrected": v}
                        for f, v in corrections.items()],
        })
    return JSONResponse(content={"status": "ok", "count": len(items), "items": items})


@app.get("/admin-api/face-feedback/{feedback_id}/samples")
async def admin_face_feedback_samples(feedback_id: str, request: Request):
    """這一筆修正對應的樣本影像。

    刻意做成另一條端點、由前端點開某一筆時才要：影像即使是 96×96 的 ROI，
    108 筆一次全帶也是幾 MB，而覆核的人一次只看一筆。

    這條走 face：讀 GCS 需要 google-cloud-storage，那個依賴只裝在 face 映像裡
    （gateway 的 requirements 只有 firestore）。慢一點可以接受——它只在
    使用者主動點開時才發生，不像列表是一進畫面就要。
    """
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=False)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    face = await _face_internal_request(
        request, "GET", f"v1/face/feedback/{quote(feedback_id, safe='')}/samples", admin=True)
    if face is None or not face.is_success:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "FACE_SAMPLES_UNAVAILABLE",
                              "message": "暫時讀不到樣本影像，請稍後再試。"}},
        )
    return JSONResponse(content=face.json())


def _training_decisions(row: dict) -> dict[str, str]:
    """把舊的整筆 accepted 與新的逐部位決定統一成欄位 -> 決定。"""
    decisions = row.get("reviewDecisions") or {}
    if decisions:
        return {str(field): str(value) for field, value in decisions.items()}
    if row.get("reviewStatus") == "accepted":
        return {str(field): "accepted" for field in (row.get("corrections") or {})}
    return {}


@app.post("/admin-api/face-training/runs")
async def admin_create_face_training_run(request: Request):
    """把管理員已採用的影像樣本登記成一個可追蹤的 ConvNeXt 訓練批次。

    這個按鈕不假裝在 Cloud Run request 裡直接訓練：它只建立 queued 批次。真正的
    本機訓練腳本以 runId 讀取同一筆資料，完成後回寫 before/after metrics 與 done。
    因此後台能證明「哪些 feedback、哪些部位、哪次訓練」真的有對上，而不是只有一個
    看起來會動的按鈕。
    """
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=True)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    try:
        body = await request.json()
    except Exception:
        body = {}
    raw_ids = body.get("feedbackIds") if isinstance(body, dict) else None
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(status_code=422, detail={"error": {"code": "FEEDBACK_IDS_REQUIRED", "message": "請至少選一筆已採用且有影像的回饋"}})
    if len(raw_ids) > 100:
        raise HTTPException(status_code=422, detail={"error": {"code": "TOO_MANY_FEEDBACK_IDS", "message": "一次最多送 100 筆"}})

    selections: dict[str, dict[str, str]] = {}
    excluded: list[dict] = []
    for raw_id in raw_ids:
        feedback_id = str(raw_id or "").strip()
        job_id = feedback_id[3:] if feedback_id.startswith("FB-") else feedback_id
        if not job_id:
            continue
        row = await asyncio.to_thread(job_store.get, FACE_FEEDBACK_COL, job_id)
        if not row:
            excluded.append({"feedbackId": feedback_id, "reason": "找不到回饋紀錄"})
            continue
        # 已經進過批次的不再收。少了這一道，同一批資料每按一次按鈕就再送一次，
        # 匯入時同一張 ROI 會被重複收進快取，等於偷偷把某些樣本加權。
        if row.get("trainingRunId"):
            excluded.append({"feedbackId": row.get("feedbackId") or feedback_id,
                             "reason": f"已在批次 {row.get('trainingRunId')} 裡"})
            continue
        if not row.get("contributed"):
            excluded.append({"feedbackId": row.get("feedbackId") or feedback_id, "reason": "沒有使用者同意保存的影像"})
            continue
        decisions = _training_decisions(row)
        corrections = row.get("corrections") or {}
        labels = row.get("reviewLabels") or {}
        fields: dict[str, str] = {}
        for field, decision in decisions.items():
            if decision not in {"accepted", "corrected"} or field not in corrections:
                continue
            # 只收 BASIC 那五個部位。側臉鼻型走的是 PRO 那條線，訓練腳本的
            # FIELD_TO_PART 裡沒有它——收進來的話批次建得起來、feedback 也被蓋上
            # trainingRunId，但訓練機對應不到任何部位而讓整批失敗，
            # 而那筆 PRO 標註從此被視為「已經送過」，**永遠不會再進任何訓練集**。
            # 這份清單要跟 training_run_store._TRAINABLE_FIELDS 一致。
            if field not in BASIC_TRAINABLE_FIELDS:
                continue
            label = labels.get(field) if decision == "corrected" else corrections.get(field)
            if isinstance(label, str) and label.strip():
                fields[field] = label.strip()
        if fields:
            selections[row.get("feedbackId") or f"FB-{job_id}"] = fields
        else:
            excluded.append({"feedbackId": row.get("feedbackId") or feedback_id,
                             "reason": "沒有可訓練的部位（側臉鼻型屬於 PRO，不在這個訓練集裡）"})

    if not selections:
        raise HTTPException(status_code=422, detail={"error": {"code": "NO_TRAINABLE_SAMPLES", "message": "選取項目沒有可訓練的已採用影像部位"}, "excluded": excluded})

    run_id = "TR-" + secrets.token_hex(8)
    now = datetime.now(timezone.utc).isoformat()
    run = {
        "runId": run_id,
        "status": "queued",
        "model": "ConvNeXt-Tiny",
        "createdAt": now,
        "queuedAt": now,
        "feedbackIds": sorted(selections),
        "selections": selections,
        "sampleCount": sum(len(fields) for fields in selections.values()),
        "excluded": excluded,
        "source": "admin-face-feedback",
    }
    await asyncio.to_thread(job_store.create, FACE_TRAINING_RUNS_COL, run_id, run)

    # 在每一筆回饋上蓋回批次編號。兩個用途：
    # 一是後台能分辨「採用了但還沒送訓」與「已經在某一批裡」——沒有這個標記，
    # 已經送過的資料每按一次按鈕就會被重送一次；
    # 二是證據鏈可以從任何一筆回饋反查到它進了哪一次訓練，不必反過來翻批次清單。
    #
    # 這一整條端點的 Firestore 呼叫都要走 to_thread：最多 100 筆就是最多 201 次
    # 網路往返，同步做的話整個 gateway 的事件迴圈會被卡住那麼久，其他人的請求
    # 全部一起等——包括正在分析臉的那些。
    def _stamp() -> None:
        for feedback_id in selections:
            job_id = feedback_id[3:] if feedback_id.startswith("FB-") else feedback_id
            try:
                job_store.patch(FACE_FEEDBACK_COL, job_id,
                                {"trainingRunId": run_id, "trainingQueuedAt": now})
            except Exception:
                # 標記失敗不該讓批次消失——批次本身已經寫進去了，那才是要緊的。
                logging.exception("寫入 trainingRunId 失敗 job_id=%s run=%s", job_id, run_id)

    await asyncio.to_thread(_stamp)

    return JSONResponse(status_code=202, content={"status": "queued", **run})


@app.post("/admin-api/face-training/runs/{run_id}/retry")
async def admin_retry_face_training_run(run_id: str, request: Request):
    """把失敗批次以新的 queued 批次重送，保留原批次作為不可變歷史證據。

    一般建立批次會排除已有 trainingRunId 的回饋；失敗批次正好已經有這個欄位，
    所以不能讓前端把原本的 feedbackIds 再送進一般 POST。這條路徑只接受 failed，
    重新檢查樣本後建立新的 run，並用 retryOf／retryRunId 防止連按造成重複訓練。
    """
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=True)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    source_run_id = str(run_id or "").strip()
    source = await asyncio.to_thread(job_store.get, FACE_TRAINING_RUNS_COL, source_run_id)
    if not source:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "FACE_TRAINING_RUN_NOT_FOUND",
                               "message": "找不到這個訓練批次。"}},
        )
    if str(source.get("status") or "") != "failed":
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "TRAINING_RETRY_NOT_ALLOWED",
                               "message": "只有失敗的訓練批次可以重新訓練。"}},
        )

    # 先查 retryOf，再看來源上的 retryRunId。前者可以補救「新批次已建立，
    # 但 Firestore 回寫來源標記短暫失敗」的情況，避免再按一次又排一批。
    #
    # 失敗的重試批次是例外：它不是「已經處理完」，而是使用者要求再給一次機會。
    # 如果只要看到 retryOf 就永遠去重，第一次重試也失敗時，原批次就會被永久鎖死。
    # queued/running/done 繼續去重；failed 則沿著失敗的子批次開下一個新批次。
    retry_source = source
    visited: set[str] = set()
    # 追到整條鏈的尾端，而非只看第一個子批次。缺件、分叉或循環時停止，
    # 不猜哪個批次才是目前有效的，也不建立另一條可能重複訓練的分支。
    while True:
        if source_run_id in visited or len(visited) >= 100:
            raise HTTPException(409, detail={"error": {"code": "TRAINING_RETRY_CHAIN_INVALID", "message": "訓練重試紀錄有循環或鏈過長，請先核對批次紀錄。"}})
        visited.add(source_run_id)
        existing_retries = await asyncio.to_thread(
            job_store.find_by_field, FACE_TRAINING_RUNS_COL, "retryOf", source_run_id, 2)
        previous_retry_id = str(retry_source.get("retryRunId") or "").strip()
        if len(existing_retries) > 1:
            raise HTTPException(409, detail={"error": {"code": "TRAINING_RETRY_CHAIN_INVALID", "message": "同一批次有多筆重試紀錄，請先核對批次紀錄。"}})
        existing_retry = existing_retries[0] if existing_retries else None
        if existing_retry is None and previous_retry_id:
            existing_retry = await asyncio.to_thread(job_store.get, FACE_TRAINING_RUNS_COL, previous_retry_id)
            if existing_retry is None:
                raise HTTPException(409, detail={"error": {"code": "TRAINING_RETRY_RECORD_MISSING", "message": "目前讀不到已建立的重試批次，請重新載入後再試。"}})
        if existing_retry is None:
            break
        child_id = str(existing_retry.get("runId") or "").strip()
        if (not child_id or child_id in visited
                or (previous_retry_id and child_id != previous_retry_id)
                or existing_retry.get("retryOf") != source_run_id):
            raise HTTPException(409, detail={"error": {"code": "TRAINING_RETRY_CHAIN_INVALID", "message": "訓練重試的來源關聯不一致，請先核對批次紀錄。"}})
        if str(existing_retry.get("status") or "queued") != "failed":
            return JSONResponse(status_code=202, content={"status": "queued", **existing_retry, "deduped": True})
        retry_source = existing_retry
        source_run_id = child_id

    raw_selections = retry_source.get("selections")
    if not isinstance(raw_selections, dict) or not raw_selections:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "NO_TRAINABLE_SAMPLES",
                               "message": "這個失敗批次沒有可重新訓練的資料。"}},
        )

    selections: dict[str, dict[str, str]] = {}
    excluded: list[dict] = []
    for raw_feedback_id, raw_fields in raw_selections.items():
        feedback_id = str(raw_feedback_id or "").strip()
        job_id = feedback_id[3:] if feedback_id.startswith("FB-") else feedback_id
        row = await asyncio.to_thread(job_store.get, FACE_FEEDBACK_COL, job_id)
        if not row:
            excluded.append({"feedbackId": feedback_id, "reason": "找不到回饋紀錄"})
            continue
        if not row.get("contributed"):
            excluded.append({"feedbackId": feedback_id, "reason": "沒有使用者同意保存的影像"})
            continue
        current_run_id = str(row.get("trainingRunId") or "").strip()
        if current_run_id and current_run_id != source_run_id:
            excluded.append({"feedbackId": feedback_id,
                             "reason": f"已被其他批次 {current_run_id} 佔用"})
            continue

        fields: dict[str, str] = {}
        if isinstance(raw_fields, dict):
            for raw_field, raw_label in raw_fields.items():
                field = str(raw_field or "").strip()
                label = str(raw_label or "").strip()
                if field in BASIC_TRAINABLE_FIELDS and label:
                    fields[field] = label
        if fields:
            selections[feedback_id] = fields
        else:
            excluded.append({"feedbackId": feedback_id, "reason": "沒有可訓練的部位"})

    if not selections:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "NO_TRAINABLE_SAMPLES",
                               "message": "這個失敗批次目前沒有可重新訓練的影像部位"},
                    "excluded": excluded},
        )

    retry_id = "TR-" + secrets.token_hex(8)
    now = datetime.now(timezone.utc).isoformat()
    retry_run = {
        "runId": retry_id,
        "status": "queued",
        "model": retry_source.get("model") or "ConvNeXt-Tiny",
        "createdAt": now,
        "queuedAt": now,
        "feedbackIds": sorted(selections),
        "selections": selections,
        "sampleCount": sum(len(fields) for fields in selections.values()),
        "excluded": excluded,
        "source": "admin-face-feedback-retry",
        "retryOf": source_run_id,
    }
    await asyncio.to_thread(job_store.create, FACE_TRAINING_RUNS_COL, retry_id, retry_run)

    # 批次本身已經寫入才回寫來源標記；即使這次標記短暫失敗，下一次請求仍會
    # 透過 retryOf 找到已建立的批次，不會因為管理員多按一次而重訓兩次。
    try:
        await asyncio.to_thread(
            job_store.patch, FACE_TRAINING_RUNS_COL, source_run_id,
            {"retryRunId": retry_id, "retriedAt": now},
        )
    except Exception:
        logging.exception("寫入訓練重試標記失敗 source=%s retry=%s", source_run_id, retry_id)

    def _stamp_retry() -> None:
        for feedback_id in selections:
            job_id = feedback_id[3:] if feedback_id.startswith("FB-") else feedback_id
            try:
                job_store.patch(FACE_FEEDBACK_COL, job_id,
                                {"trainingRunId": retry_id, "trainingQueuedAt": now})
            except Exception:
                logging.exception("寫入重試 trainingRunId 失敗 job_id=%s run=%s", job_id, retry_id)

    await asyncio.to_thread(_stamp_retry)
    return JSONResponse(status_code=202, content={"status": "queued", **retry_run})


@app.post("/admin-api/face-training/promotions")
async def admin_create_model_promotion(request: Request):
    """登記一次「把某批次的某些部位換上線」的請求，等訓練機撿走執行。

    Gateway 不換模型，也換不了：模型檔是 111MB 一個、打包進 face 服務的 image，
    換一次要複製檔案、重算 sha256、更新 manifest、重新 build 與部署。那些都需要
    訓練機的檔案系統與 gcloud 認證，Cloud Run 上的這支程式兩者都沒有。

    所以這裡只寫下決定。真正的動作分成兩段：訓練機的 worker 做得到的本機部分
    （複製、類別檢查、manifest），以及需要人明確執行的部署——後者刻意不自動化，
    因為它會動到線上服務。
    """
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        claims = select_account(request, for_write=True)["claims"]
        _require_admin_claims(claims)
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    run_id = str(body.get("runId") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "PROMOTION_RUN_ID_INVALID",
                              "message": "請提供有效的訓練批次編號。"}},
        )

    requested = body.get("parts")
    parts = [str(p).strip() for p in requested] if isinstance(requested, list) else []
    if not parts or [p for p in parts if p not in PROMOTABLE_PARTS]:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "PROMOTION_PARTS_INVALID",
                              "message": "請選擇要換上線的部位。"}},
        )
    # 去重但保留順序：同一個部位送兩次不是錯誤，只是沒有意義。
    parts = list(dict.fromkeys(parts))

    # 同一批次還有沒做完的請求就不要再開一張。連按會讓訓練機重複複製同一組檔案，
    # 而每複製一次就多備份一份 111MB。
    #
    # 查不到就要擋下來，不能當成「沒有在跑」放行。 這裡原本把例外吞成空清單，
    # 於是 Firestore 抖一下，去重就整個消失——而會讓查詢失敗的狀況（額度、權杖、
    # 網路）跟會讓人連按的狀況高度重疊。放行的代價是重跑一次 111MB 的複製與部署，
    # 擋下來的代價只是請他再按一次。
    try:
        existing = await asyncio.to_thread(
            job_store.find_by_field, FACE_MODEL_PROMOTIONS_COL, "runId", run_id, 20)
    except Exception:
        logging.exception("讀取換模型請求失敗 run=%s", run_id)
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "PROMOTION_STORE_UNAVAILABLE",
                              "message": "暫時無法確認這個批次有沒有正在進行的換上線請求，請稍後再試。"}},
        )
    if any(str(row.get("status") or "") in IN_FLIGHT_STATUSES for row in existing):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "PROMOTION_ALREADY_QUEUED",
                              "message": "這個批次已經有一筆換上線請求還沒完成。"}},
        )

    promotion_id = "PM-" + secrets.token_hex(8)
    record = {
        "promotionId": promotion_id,
        "runId": run_id,
        "parts": parts,
        "status": "queued",
        # 記操作者的不可逆 id，不記 email——這張表要能回答「誰換的」，
        # 不需要能回答「他的信箱是什麼」。
        "requestedBy": opaque_actor_id(str(claims.get("sub") or "")),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await asyncio.to_thread(job_store.create, FACE_MODEL_PROMOTIONS_COL,
                                promotion_id, record)
    except Exception:
        logging.exception("建立換模型請求失敗 run=%s", run_id)
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "PROMOTION_STORE_UNAVAILABLE",
                              "message": "暫時無法登記換上線請求，請稍後再試。"}},
        )
    record_admin_action(
        "model_promotion.request",
        actor_id=record["requestedBy"],
        target_ref=promotion_id,
        status_code=201,
        request_id=request.headers.get("x-request-id", "")[:128],
    )
    return JSONResponse(status_code=201, content={"promotion": record})


@app.get("/admin-api/face-training/promotions")
async def admin_model_promotions(request: Request):
    """列出換模型請求與各自走到哪一步，供後台顯示。"""
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=False)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))
    try:
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))
    except (TypeError, ValueError):
        limit = 10
    # 讀不到要說「暫時讀不到」。空清單會被讀成「從來沒換過模型」，
    # 而那正好是這一頁要回答的問題，不能讓故障冒充答案。
    try:
        rows = await asyncio.to_thread(
            job_store.all_jobs, FACE_MODEL_PROMOTIONS_COL, limit=limit,
            order_by="createdAt", descending=True)
    except Exception:
        logging.exception("讀取換模型請求失敗")
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "PROMOTION_STORE_UNAVAILABLE",
                              "message": "暫時讀不到換上線請求，請稍後再試。"}},
        )
    return {"promotions": rows, "promotableParts": list(PROMOTABLE_PARTS)}


@app.post("/admin-api/face-training/deployments")
async def admin_create_deployment(request: Request):
    """登記一次「重新部署後端服務」的請求，等訓練機撿走執行。

    跟換模型同一套「後台下單、本機執行」：建置與部署需要訓練機的 gcloud 認證，
    Cloud Run 上的這支程式沒有。這裡只寫下決定。

    ⚠️ 部署 gateway 會換掉所有 API 的入口。它跟 face 不同——face 換壞了只有臉部
    分析不能用，gateway 換壞了整個網站都連不上。所以前端那顆按鈕要分開確認。
    """
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        claims = select_account(request, for_write=True)["claims"]
        _require_admin_claims(claims)
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    requested = body.get("services")
    services = [str(s).strip().lower() for s in requested] if isinstance(requested, list) else []
    if not services or [s for s in services if s not in DEPLOYABLE_SERVICES]:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "DEPLOY_SERVICES_INVALID",
                              "message": "請選擇要部署的服務。"}},
        )
    services = list(dict.fromkeys(services))

    # 已經有一筆在排隊或執行中就不要再開。兩個部署同時跑會互相覆蓋 revision，
    # 而且沒有人分得出線上最後是哪一次的產物。
    #
    # 跟換模型同樣的理由 fail-closed：查不到就說查不到，不要當成「沒有在跑」。
    try:
        pending = await asyncio.to_thread(
            job_store.all_jobs, FACE_DEPLOYMENTS_COL, limit=50,
            order_by="createdAt", descending=True)
    except Exception:
        logging.exception("讀取部署請求失敗")
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "DEPLOY_STORE_UNAVAILABLE",
                              "message": "暫時無法確認有沒有正在進行的部署，請稍後再試。"}},
        )
    if any(str(row.get("status") or "") in IN_FLIGHT_STATUSES for row in pending):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "DEPLOY_ALREADY_QUEUED",
                              "message": "已經有一筆部署還沒完成，請等它結束。"}},
        )

    deployment_id = "DP-" + secrets.token_hex(8)
    record = {
        "deploymentId": deployment_id,
        "services": services,
        "status": "queued",
        "requestedBy": opaque_actor_id(str(claims.get("sub") or "")),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await asyncio.to_thread(job_store.create, FACE_DEPLOYMENTS_COL,
                                deployment_id, record)
    except Exception:
        logging.exception("建立部署請求失敗")
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "DEPLOY_STORE_UNAVAILABLE",
                              "message": "暫時無法登記部署請求，請稍後再試。"}},
        )
    record_admin_action(
        "service_deployment.request",
        actor_id=record["requestedBy"],
        target_ref=deployment_id,
        status_code=201,
        request_id=request.headers.get("x-request-id", "")[:128],
    )
    return JSONResponse(status_code=201, content={"deployment": record})


@app.get("/admin-api/face-training/deployments")
async def admin_deployments(request: Request):
    """列出部署請求與各自的進度。"""
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=False)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))
    try:
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))
    except (TypeError, ValueError):
        limit = 10
    try:
        rows = await asyncio.to_thread(
            job_store.all_jobs, FACE_DEPLOYMENTS_COL, limit=limit,
            order_by="createdAt", descending=True)
    except Exception:
        logging.exception("讀取部署請求失敗")
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "DEPLOY_STORE_UNAVAILABLE",
                              "message": "暫時讀不到部署請求，請稍後再試。"}},
        )
    return {"deployments": rows, "deployableServices": list(DEPLOYABLE_SERVICES)}


async def _effective_model_baseline(current: dict, runs: list) -> tuple[dict, list]:
    """把佇列裡還沒做完的換上線套到線上分數上，算出「按下去時實際要比的基準」。

    為什麼不能只跟線上比
    ----------------------
    換上線是排隊執行的。佇列裡若已經有一筆要把臉型換成 A，那麼此刻再登記的那一筆
    上線時，臉型的前一手就是 A，不是現在線上的分數。拿線上的去比，畫面會說「+5.2」，
    實際跑起來卻是「-1.4」——然後被 promote_model 用真實數字擋回來。

    這跟 publish_live_model_metrics 修掉的是同一種錯誤，只是換一個來源：那次是基準
    停在換模型之前，這次是基準看不見還沒執行的那幾筆。兩者的症狀一模一樣——按鈕在
    被按之前就已經講錯了。

    同一個部位被多筆佇列覆蓋時，最後一筆贏，因為 worker 就是照建立順序做的。

    回傳 (套用後的基準, 待執行的請求清單)。讀不到佇列時回原本的線上分數並附空清單：
    少了這層修正只是退回舊行為，不該讓整頁掛掉。
    """
    baseline = json.loads(json.dumps(current)) if current else {}
    try:
        promotions = await asyncio.to_thread(
            job_store.all_jobs, FACE_MODEL_PROMOTIONS_COL, limit=50,
            order_by="createdAt", descending=False)
    except Exception:
        logging.exception("讀取換上線佇列失敗，比較基準退回線上分數")
        return baseline, []

    pending = [p for p in promotions if str(p.get("status") or "") in IN_FLIGHT_STATUSES]
    if not pending:
        return baseline, []

    known_runs = {str(r.get("runId") or ""): r for r in runs}
    parts_map = dict(baseline.get("parts") or {})
    for promo in pending:
        run_id = str(promo.get("runId") or "")
        run = known_runs.get(run_id)
        if run is None:
            # 佇列裡的批次不一定落在剛才取回的那幾筆裡（預設只取 5 筆）。
            # 補讀一次；讀不到就跳過這一筆，不要讓它把其他筆的修正也一起丟掉。
            try:
                run = await asyncio.to_thread(job_store.get, FACE_TRAINING_RUNS_COL, run_id)
            except Exception:
                logging.exception("讀取佇列批次失敗 run=%s", run_id)
                run = None
            known_runs[run_id] = run
        after_parts = ((run or {}).get("modelAfter") or {}).get("parts") or {}
        for part in (promo.get("parts") or []):
            key = PART_MODEL_KEYS.get(str(part))
            if key and isinstance(after_parts.get(key), dict):
                parts_map[key] = after_parts[key]
    if parts_map:
        baseline["parts"] = parts_map
    baseline["source"] = "live+queued"
    return baseline, [
        {k: promo.get(k) for k in ("promotionId", "runId", "parts", "status", "createdAt")}
        for promo in pending
    ]


@app.get("/admin-api/face-training/runs")
async def admin_face_training_runs(request: Request):
    """回傳最近五次訓練與最新 ConvNeXt 指標，供後台顯示可驗證的狀態。"""
    enforce_csrf(request)
    if MULTI_SESSION_ENABLED:
        _require_admin_claims(select_account(request, for_write=False)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))
    # 上限 50：後台這一區的用途是看**完整**訓練歷史，而截斷在畫面上看不出來——
    # 少掉的批次不會留下任何痕跡，只會讓「送訓完成」的數字比實際少。
    # 預設維持 5（其他呼叫者只想看最近幾筆），要完整歷史的自己指定。
    limit = 5
    try:
        limit = max(1, min(50, int(request.query_params.get("limit") or 5)))
    except (TypeError, ValueError):
        limit = 5
    # Firestore 掛掉時要說「暫時讀不到」，不能讓它變成沒有處理的 500。
    # 空清單更不行——那會被讀成「一次訓練都沒有跑過」，跟事實相反，
    # 而這一頁存在的理由就是證明訓練跑過。旁邊的回饋清單也是這樣處理的。
    try:
        runs = await asyncio.to_thread(
            job_store.all_jobs, FACE_TRAINING_RUNS_COL, limit=limit,
            order_by="createdAt", descending=True)
        current = await asyncio.to_thread(job_store.get, FACE_MODEL_METRICS_COL, "current") or {}
    except Exception:
        logging.exception("讀取訓練批次失敗")
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "FACE_TRAINING_RUNS_UNAVAILABLE",
                              "message": "暫時讀不到訓練批次，請稍後再試。"}},
        )
    if not current:
        for run in runs:
            if run.get("status") == "done" and run.get("modelAfter"):
                current = {"model": run.get("model", "ConvNeXt-Tiny"), **(run.get("modelAfter") or {})}
                break

    effective, pending_promotions = await _effective_model_baseline(current, runs)

    # 訓練機狀態。挑最近回報的那一台就夠了——實務上只有一台，而「最近一次有人回報
    # 是什麼時候」正是畫面要回答的問題。讀不到不算錯誤：worker 從來沒跑過的時候
    # 這個集合根本不存在，那本身就是有意義的答案（沒有訓練機）。
    worker = None
    try:
        workers = await asyncio.to_thread(
            job_store.all_jobs, FACE_TRAINING_WORKERS_COL, limit=5,
            order_by="lastSeenAt", descending=True)
        worker = workers[0] if workers else None
    except Exception:
        logging.exception("讀取訓練機心跳失敗")

    return JSONResponse(content={
        "status": "ok", "model": "ConvNeXt-Tiny", "runs": runs,
        "recentRuns": runs, "latest": runs[0] if runs else None,
        # currentMetrics 是**線上此刻**的分數，effectiveMetrics 是**下一筆換上線會比到**
        # 的基準（線上疊上佇列）。兩個都給：標題要顯示線上是什麼，而進步幅度要用
        # effective 去算，混用其中一個都會講錯話。佇列是空的時候兩者相同。
        "currentMetrics": current or None,
        "effectiveMetrics": effective or None,
        "pendingPromotions": pending_promotions,
        "worker": worker,
    })


async def proxy_public_product_request(request: Request, path: str):
    if not PRODUCT_DATABASE_URL or not any(pattern.fullmatch(path) for pattern in PUBLIC_PRODUCT_PATHS):
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Route not found."}})
    # 預設只收 GET；要寫入的路徑必須明確列進 PUBLIC_PRODUCT_POST_PATHS。
    # 這個方向是刻意的——見該常數的說明：這整條路徑不需要登入，所以漏列的後果
    # 必須是「被擋下」而不是「被放行」。
    if request.method != ("POST" if path in PUBLIC_PRODUCT_POST_PATHS else "GET"):
        raise HTTPException(status_code=405, detail={"error": {"code": "METHOD_NOT_ALLOWED", "message": "Method not allowed."}})
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}})
    headers = {"Accept": request.headers.get("accept", "application/json")}
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    try:
        response = await request_upstream(
            request.app.state.http_client,
            method=request.method,
            url=f"{PRODUCT_DATABASE_URL}/{path}",
            params=list(request.query_params.multi_items()),
            headers=headers,
            content=body,
            timeout=ADMIN_PROXY_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": {"code": "PRODUCT_UPSTREAM_TIMEOUT", "message": "Product service timed out."}})
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"error": {"code": "PRODUCT_SERVICE_UNAVAILABLE", "message": "Product service is unavailable."}})
    response_headers = {"X-Content-Type-Options": "nosniff"}
    for header in ("content-type", "cache-control", "etag", "retry-after"):
        if response.headers.get(header):
            response_headers[header] = response.headers[header]
    sanitised = upstream_failure_payload(response)
    if sanitised is not None:
        status_code, payload = sanitised
        response_headers["content-type"] = "application/json"
        response_headers.pop("cache-control", None)
        response_headers.pop("etag", None)
        return Response(content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        status_code=status_code, headers=response_headers)
    return Response(content=response.content, status_code=response.status_code, headers=response_headers)


@app.api_route("/product-api/{path:path}", methods=["GET", "POST"])
async def public_product_proxy(path: str, request: Request):
    return await proxy_public_product_request(request, path)


# PUT 是 2026-08-13 加的：會員資料庫的購物車覆蓋寫入只接受 PUT，而這條路由當時沒開
# PUT，於是前端送 POST 被上游擋成 405、改送 PUT 又會被 Gateway 自己擋成 405——兩邊
# 都不通，購物車同步整條是死的。PUT 已在 STATE_CHANGING_METHODS 裡，因此 CSRF 與
# X-Expected-Actor 那兩道防線自動涵蓋它，不需要另外開後門。
@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(service: str, path: str, request: Request):
    upstream = UPSTREAMS.get(service)
    if upstream is None or not is_path_allowed(upstream, path):
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Route not found."}})

    if service == "text-suggestion" and not ALLOW_EXTERNAL_TEXT_UPSTREAM:
        raise HTTPException(status_code=503, detail={"error": {"code": "EXTERNAL_TEXT_UPSTREAM_DISABLED", "message": "External text suggestion is disabled until the trusted service is ready."}})

    if not SESSION_ONLY_MODE:
        require_client_api_key(upstream, request.headers.get("x-api-key", ""))
    # X-Expected-Actor 用來隔離分頁，並在多帳號模式中選擇正確的登入槽位。
    # 單帳號模式仍會驗證此標頭，避免寫入其他帳號。
    selected_sealed = ""
    guest_id = ""
    # 未登入而且帶著有效訪客票券時走試用路徑。有 session 的人一律照會員流程走，
    # 免得登入中的瀏覽器因為多帶了一個標頭就掉進次數受限的分支。
    if GUEST_TRIAL_ENABLED and not request_access_token(request):
        guest_id = read_guest_id(request)
        if not guest_id or not _guest_path_allowed(service, path, request.method):
            # 訪客碰到不開放的服務（會員資料、後台、收藏）時維持原本的 401 契約，
            # 前端才會照舊提示登入，而不是收到一個它不認得的新錯誤碼。
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": "MEMBER_AUTH_REQUIRED", "message": "Member sign-in is required."}},
            )
        if _guest_spends_quota(service, path, request.method):
            guest_trial_guard(guest_id)
        claims = {"sub": "", "role": "guest"}
        acting_owner_id = guest_actor_id(guest_id)
    elif MULTI_SESSION_ENABLED:
        is_write = str(request.method or "").upper() in STATE_CHANGING_METHODS
        account = select_account(request, for_write=is_write)
        claims = account["claims"]
        acting_owner_id = account["actorId"]
        selected_sealed = account["sealed"]
    else:
        claims = require_member_access(request)
        acting_owner_id = opaque_actor_id(str(claims.get("sub") or ""))
        enforce_expected_actor(request, acting_owner_id)
    target_email = _authorize_member_path(claims, path) if service == "member-database" else None
    target_owner_id = opaque_actor_id(target_email) if target_email else acting_owner_id
    pro_member_cookie, pro_rotated_cookie = "", ""
    if service == "face-pro" and request.method == "POST" and path in {"v1/face/jobs/pro", "v1/face/analyze/pro"}:
        pro_member_cookie, pro_rotated_cookie = await require_pro_analysis_access(request, claims, selected_sealed)

    def attach_rotated_member_cookie(target, original_cookie: str, rotated_cookie: str):
        """把輪替過的上游 session 重新封裝進要送回瀏覽器的那個回應。

        PRO 權限預檢會先去會員資料庫查一次，那一次就可能讓上游輪替 session
        （`merge_upstream_cookies`）。輪替之後舊的那份在上游已經作廢，所以**不論這次
        請求最後是成功還是失敗，新的都得封回去**。

        原本只有正常回傳那條路徑會做，逾時（face-pro 的上游 timeout 是 120 秒，PRO
        工作很容易撞到）、502、503 與重新拋出的 HTTPException 全部跳過——瀏覽器於是
        留著一份上游已經換掉的 cookie，下一個請求就被登出，而使用者只看到「渲染逾時」。
        """
        if not rotated_cookie or rotated_cookie == original_cookie:
            return target
        try:
            sealed = seal_member_cookie(rotated_cookie)
        except HTTPException:
            # The upstream work already succeeded.  Failing to refresh the
            # sealed jar must not turn that into an error the caller will
            # retry; the previous cookie stays valid until it expires.
            return target
        if sealed and MULTI_SESSION_ENABLED:
            # 只更新「正在操作的那個帳號」的槽位；這個瀏覽器上其他已登入帳號的
            # 封裝 cookie 必須原封不動保留。
            rebuilt: list[tuple[str, str]] = []
            replaced = False
            for token, slot_sealed in read_session_slots(request):
                slot_claims = _slot_claims(token)
                slot_actor = opaque_actor_id(str(slot_claims.get("sub") or "").strip().lower()) if slot_claims else ""
                if slot_actor == acting_owner_id:
                    rebuilt.append((account["token"], sealed))
                    replaced = True
                else:
                    rebuilt.append((token, slot_sealed))
            if not replaced:
                rebuilt.append((account["token"], sealed))
            set_session_slots(target, rebuilt)
        elif sealed:
            set_session_cookie(target, request_access_token(request), sealed)
        return target

    if pro_rotated_cookie and pro_rotated_cookie != pro_member_cookie:
        # 交給出口的 middleware 去補，而不是在每一個 return 前面各寫一次。這個函式有
        # 五、六個出口（成功、504、502、503、重新拋出的 HTTPException、未預期例外），
        # 逐一補的話下次新增一個出口又會漏掉，而漏掉的症狀是使用者被靜默登出，
        # 極難連回這裡。
        request.state.apply_member_cookie = (
            lambda target: attach_rotated_member_cookie(target, pro_member_cookie, pro_rotated_cookie))
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    # 管理員身分做的寫入（停權、刪帳號、改權限）多過一關 CSRF。一般會員寫自己的資料
    # 不套用：那條路徑已經強制帶 `X-Expected-Actor`（自訂標頭跨站送不出來），再加一層
    # 只會讓還沒更新的用戶端整批寫入失敗，換不到相應的安全性。
    if is_admin and str(request.method or "").upper() in STATE_CHANGING_METHODS:
        enforce_csrf(request)
    # The full member roster is an administrator-only view.  `_authorize_member_path`
    # only guards `api/members/<id>` routes; the bare list path matches nothing
    # there, so without this any signed-in member could read every account.
    if service == "member-database" and MEMBER_LIST_PATH_RE.fullmatch(path) and not is_admin:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "ADMIN_REQUIRED", "message": "Administrator permission is required."}},
        )
    upstream_member_cookie = ""
    if service == "member-database":
        upstream_member_cookie = unseal_member_cookie(selected_sealed) if MULTI_SESSION_ENABLED else require_upstream_member_cookie(request)
    if not upstream.base_url:
        raise HTTPException(status_code=503, detail={"error": {"code": "NOT_CONFIGURED", "message": "Upstream service is not configured."}})

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}})
        except ValueError:
            raise HTTPException(status_code=400, detail={"error": {"code": "BAD_CONTENT_LENGTH", "message": "Invalid Content-Length header."}})

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}})

    try:
        identity_token = ""
        if upstream.requires_cloud_run_iam:
            identity_token = await asyncio.to_thread(TOKEN_CACHE.get, upstream.base_url)
        upstream_headers = build_upstream_headers(request, upstream, identity_token)
        if service == "member-database":
            upstream_headers = with_member_gateway_key(upstream_headers)
        if upstream_member_cookie:
            upstream_headers["Cookie"] = upstream_member_cookie
        if service in {"render-service", "face-basic", "face-pro"}:
            upstream_headers["X-User-ID"] = acting_owner_id

        prefetched_media: list[str] = []
        saved_match = SAVED_LOOK_PATH_RE.fullmatch(path) if service == "member-database" else None
        member_match = MEMBER_PATH_RE.fullmatch(path) if service == "member-database" else None
        if service == "member-database" and request.method == "DELETE" and (saved_match or member_match):
            list_path = f"api/members/{saved_match.group(1) if saved_match else member_match.group(1)}/saved-looks"
            before_delete = await request.app.state.http_client.get(
                f"{upstream.base_url}/{list_path}",
                headers=upstream_headers,
                timeout=20,
            )
            if not before_delete.is_success:
                raise HTTPException(
                    status_code=503,
                    detail={"error": {"code": "MEDIA_OWNERSHIP_LOOKUP_FAILED", "message": "無法確認待刪圖片，請稍後重試。"}},
                )
            try:
                prefetched_media = _saved_media_urls(
                    before_delete.json(),
                    saved_match.group(2) if saved_match and saved_match.group(2) else None,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"error": {"code": "MEDIA_OWNERSHIP_LOOKUP_FAILED", "message": "無法確認待刪圖片，請稍後重試。"}},
                ) from exc

            # Privacy-first deletion: remove private media while the member row
            # still exists and can be retried.  If storage deletion fails, stop
            # before deleting the database row instead of returning a false
            # success and leaving untracked face images behind.
            await _delete_saved_media(request, prefetched_media, target_owner_id, admin=is_admin)
            if member_match:
                render_cleanup = await _render_internal_request(
                    request,
                    "DELETE",
                    f"render/users/{target_owner_id}",
                    user_id=target_owner_id,
                    admin=is_admin,
                )
                if render_cleanup is None or not render_cleanup.is_success:
                    raise HTTPException(
                        status_code=503,
                        detail={"error": {"code": "MEMBER_MEDIA_DELETE_INCOMPLETE", "message": "會員圖片刪除尚未完成，請稍後重試。"}},
                    )
                # 臉部服務也有這個會員的影像：他同意提供的五官裁切（face_contributions）。
                # 跟渲染圖同樣的理由要在刪 row 之前清掉——那些物件靠 ownerId 定位，
                # 而 ownerId 是用 SESSION_SECRET 從 email 推導的。帳號一刪就再也推導不回去，
                # 剩下的是沒有帳號對應、也沒有辦法刪除的臉部資料。
                #
                # 沒開啟貢獻功能時這條會回 0 筆，一樣是成功——不能因為「沒東西可刪」
                # 就當失敗，那會讓所有會員都刪不掉。
                face_cleanup = await _face_internal_request(
                    request,
                    "DELETE",
                    f"v1/face/users/{target_owner_id}",
                    user_id=target_owner_id,
                    admin=is_admin,
                )
                if face_cleanup is None or not face_cleanup.is_success:
                    raise HTTPException(
                        status_code=503,
                        detail={"error": {"code": "MEMBER_MEDIA_DELETE_INCOMPLETE", "message": "會員圖片刪除尚未完成，請稍後重試。"}},
                    )
        response = await request_upstream(
            request.app.state.http_client,
            method=request.method,
            url=f"{upstream.base_url}/{path}",
            params=list(request.query_params.multi_items()),
            headers=upstream_headers,
            content=body,
            timeout=upstream_timeout(service),
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": {"code": "UPSTREAM_TIMEOUT", "message": "Upstream service timed out."}})
    except httpx.HTTPError:
        return JSONResponse(status_code=502, content={"error": {"code": "UPSTREAM_UNAVAILABLE", "message": "Upstream service is unavailable."}})
    except HTTPException:
        raise
    except Exception:
        return JSONResponse(status_code=503, content={"error": {"code": "IDENTITY_TOKEN_UNAVAILABLE", "message": "Service authentication is unavailable."}})

    response_headers = {"X-Content-Type-Options": "nosniff"}
    for header in ("content-type", "cache-control", "retry-after"):
        if response.headers.get(header):
            response_headers[header] = response.headers[header]
    response_content = response.content
    # 上游失敗而且回的不是 JSON（Cloudflare 的 tunnel 錯誤頁就是這樣）時換掉。
    # 底下的稽核與訪客扣次仍然看 response.status_code，也就是上游真正回的那個——
    # 只有送回瀏覽器的那一份被換。
    sanitised = upstream_failure_payload(response)
    if sanitised is not None:
        result_status, sanitised_body = sanitised
        response_content = json.dumps(sanitised_body, ensure_ascii=False).encode("utf-8")
        response_headers["content-type"] = "application/json"
        response_headers.pop("cache-control", None)
    else:
        result_status = response.status_code
    if response.is_success and service == "render-service":
        try:
            response_content = json.dumps(
                _sanitize_render_payload(request, response.json()),
                ensure_ascii=False,
            ).encode("utf-8")
            response_headers["content-type"] = "application/json"
        except ValueError:
            pass
    if response.is_success and service == "member-database" and request.method == "GET" and SAVED_LOOK_PATH_RE.fullmatch(path):
        try:
            response_content = json.dumps(
                await _refresh_saved_look_media(request, response.json(), target_owner_id),
                ensure_ascii=False,
            ).encode("utf-8")
            response_headers["content-type"] = "application/json"
        except ValueError:
            pass

    if response.is_success and service == "member-database":
        saved_match = SAVED_LOOK_PATH_RE.fullmatch(path)
        member_match = MEMBER_PATH_RE.fullmatch(path)
        if request.method == "POST" and saved_match and not saved_match.group(2):
            try:
                submitted = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                submitted = {}
            job_id = _render_job_id_from_url(submitted.get("afterImageUrl"))
            if job_id:
                retained = await _render_internal_request(
                    request,
                    "POST",
                    f"render/jobs/{job_id}/retain",
                    user_id=target_owner_id,
                    admin=is_admin,
                )
                if retained is None or not retained.is_success:
                    await _rollback_saved_look_after_retain_failure(
                        request,
                        upstream,
                        path,
                        response,
                        upstream_headers,
                    )
                    raise HTTPException(
                        status_code=503,
                        detail={"error": {"code": "MEDIA_RETAIN_INCOMPLETE", "message": "妝前與妝後圖片尚未完整保存，請稍後重試。"}},
                    )

    # 管理員對「別人的帳號」做的寫入要留稽核：停權、改權限、刪帳號。
    # 只記雜湊過的 actorId 與同樣雜湊過的對象，不記 email、不記 body——這份紀錄
    # 保存得比原始資料久，它絕不能自己變成第二份會員名冊。
    if (service == "member-database" and is_admin
            and str(request.method or "").upper() in STATE_CHANGING_METHODS
            and target_owner_id != acting_owner_id):
        record_admin_action(
            _audit_action("member", request.method),
            actor_id=acting_owner_id,
            target_ref=target_owner_id,
            status_code=response.status_code,
            # record_admin_action 內部已把 request_id 截到 128，這裡不必再切一次。
            request_id=request.headers.get("x-request-id", ""),
        )

    # 分析確實被受理了才扣訪客的一次，並把剩餘次數回報給前端顯示。
    if guest_id and _guest_spends_quota(service, path, request.method) and response.is_success:
        guest_trial_record(guest_id)
    if guest_id:
        response_headers["X-Guest-Trial-Remaining"] = str(guest_trial_remaining(guest_id))
        response_headers["X-Guest-Trial-Max"] = str(GUEST_TRIAL_MAX_RUNS)

    result = Response(content=response_content, status_code=result_status, headers=response_headers)
    if service == "member-database":
        # 會員資料庫這條的輪替是從**這次上游回應**讀出來的，只有走到這裡才知道，
        # 所以留在成功路徑上處理。PRO 預檢那份是在請求早期就拿到的，已經交給出口的
        # middleware，逾時與錯誤路徑也會補上。
        attach_rotated_member_cookie(
            result, upstream_member_cookie, merge_upstream_cookies(upstream_member_cookie, response))
    return result


if __name__ == "__main__":
    from dev_server_utils import run_dev_server

    run_dev_server(app, "AI Gateway", "AI_GATEWAY", 8015)
