// 無登入 session 時清除所有訪客活動資料，確保每次開新分頁都是乾淨狀態
(function () {
    if (!sessionStorage.getItem('beautyUser')) {
        ['beautyAnalysisDraft', 'beautyFav', 'beautyCart', 'beautyHistory', 'beautySuggestions'].forEach(
            k => localStorage.removeItem(k)
        );
    }
})();

// API 設定：瀏覽器只呼叫 Gateway，不直接連資料庫或模型服務。
function getRuntimeApiConfig() {
    return typeof window !== 'undefined' ? (window.DECORATE_ME_CONFIG || {}) : {};
}

const RuntimeApiConfig = getRuntimeApiConfig();

// 正式站使用同源路徑與短期 session，本機開發則預設連到 8015 埠。
// 服務網址可由公開設定注入，但長期金鑰只能留在伺服器端。
function _defaultGatewayUrl() {
    const explicit = String(RuntimeApiConfig.aiGatewayUrl || '').trim();
    if (explicit) return explicit;
    try {
        const host = (typeof location !== 'undefined' && location.hostname) || '';
        if (host === 'localhost' || host === '127.0.0.1') {
            const port = String((RuntimeApiConfig.localGatewayPort || 8015));
            return `http://${host}:${port}`;
        }
    } catch (_) {}
    return '';
}
const AI_GATEWAY_URL = _defaultGatewayUrl().replace(/\/+$/, '');
const gatewayService = name => `${AI_GATEWAY_URL}/${name}`;

// 所有使用者看得到的錯誤訊息在前端統一翻成中文。後端仍保留穩定的英文
// error code 供程式判斷，但不把英文 message 或內部服務細節直接丟進彈窗。
const USER_ERROR_ZH = Object.freeze({
    UNAUTHORIZED: '驗證資訊無效，請重新登入後再試。',
    FORBIDDEN: '你沒有執行這項操作的權限。',
    INVALID_CREDENTIALS: '帳號或密碼錯誤，請重新確認。',
    WRONG_PASSWORD: '密碼錯誤，請重新輸入。',
    USER_NOT_FOUND: '找不到這個會員帳號。',
    EMAIL_EXISTS: '這個信箱已經註冊過了。',
    GUEST_TRIAL_EXHAUSTED: '免費體驗次數已用完，註冊會員後可以繼續使用，也才能保存分析結果與妝容圖。',
    GUEST_TICKET_RATE_LIMITED: '免費體驗次數已用完，註冊會員後可以繼續使用。',
    MEMBER_AUTH_REQUIRED: '請先登入會員後再繼續。',
    MEMBER_SESSION_REQUIRED: '請先登入會員後再繼續。',
    MEMBER_AUTH_INVALID: '登入狀態已失效，請重新登入後再繼續。',
    MEMBER_SESSION_INVALID: '登入狀態已失效，請重新登入後再繼續。',
    MEMBER_SESSION_MISSING: '會員登入狀態建立失敗，請稍後再試。',
    MEMBER_SESSION_UNUSABLE: '會員登入狀態無法建立，請稍後再試。',
    // 登入本身有效，但這個帳號在會員資料庫裡查無此人。
    // **不要**寫成「請重新登入」——重登不會好，而那正是 2026-08-29 管理員
    // 每 90 秒被踢出去時看到的那句話，把人指往一個解決不了問題的動作。
    MEMBER_NOT_PROVISIONED: '這個帳號在會員資料庫中不存在，重新登入不會解決，請聯繫資料庫端建立帳號。',
    MEMBER_SESSION_TOO_LARGE: '會員登入資料異常，請重新登入。',
    MEMBER_SERVICE_UNAVAILABLE: '會員服務目前無法連線，請稍後再試。',
    MEMBER_SERVICE_TIMEOUT: '會員服務回應逾時，請稍後再試。',
    MEMBER_SERVICE_ERROR: '會員服務處理失敗，請稍後再試。',
    MEMBER_SCOPE_FORBIDDEN: '無法存取其他會員的資料。',
    AUTH_NOT_CONFIGURED: '會員驗證服務尚未完成設定，請聯繫管理員。',
    LOGIN_RATE_LIMITED: '登入嘗試次數過多，請稍後再試。',
    MEMBER_SERVICE_RATE_LIMITED: '會員服務目前限制登入頻率，請稍後再試。',
    ADMIN_REQUIRED: '只有管理員可以執行這項操作。',
    // 這兩個是唯二會把英文丟到畫面上的（2026-08-28 全表比對）：
    // Gateway 那邊的訊息是英文，前端又沒有對照。
    GUEST_TRIAL_DISABLED: '免費體驗目前沒有開放，請註冊或登入會員後使用。',
    INVALID_REQUEST: '輸入的內容格式不正確，請檢查後再試一次。',
    // 上游不接受這次管理操作。**不要**寫成「請重新登入」——
    // Gateway 已經驗過 session 了，重登不會好（見 PRODUCT_UPSTREAM_REJECTED 的由來）。
    PRODUCT_UPSTREAM_REJECTED: '商品服務不接受這次管理操作（你的登入是有效的），請確認商品服務的連線設定。',
    // 送訓相關：這三個原本靠 Gateway 的中文訊息，列在這裡是為了前端改動時不會漏掉。
    FEEDBACK_IDS_REQUIRED: '請至少選一筆已採用且有影像的回饋。',
    TOO_MANY_FEEDBACK_IDS: '一次最多送 100 筆，請分批送訓。',
    NO_TRAINABLE_SAMPLES: '這些回饋沒有可以拿來訓練的影像樣本。',
    FACE_TRAINING_RUNS_UNAVAILABLE: '暫時讀不到訓練批次，請稍後再按「重新載入」。',
    // 跨分頁登入不同帳號時會出現。講清楚是「換了帳號」而不是「壞了」。
    ACCOUNT_NOT_AVAILABLE: '登入帳號已在其他分頁變更，請重新整理頁面後再操作。',
    EXPECTED_ACTOR_REQUIRED: '無法確認目前分頁的登入身分，請重新整理頁面後再操作。',
    SESSION_OWNER_CHANGED: '這個分頁的登入身分已經變更，請重新整理頁面。',
    CSRF_TOKEN_INVALID: '這次操作的安全驗證失敗，請重新整理頁面後再試。',
    ADMIN_SUSPENDED: '管理員帳號目前已停權。',
    ADMIN_PROXY_NOT_CONFIGURED: '管理端服務尚未完成設定。',
    // 點數與兌換的錯誤碼。
    INSUFFICIENT_POINTS: '點數不足，無法完成這次兌換。',
    ALREADY_OWNED: '你已經擁有這個項目了。',
    INVALID_THEME: '找不到這個主題，請重新整理後再試。',
    INVALID_PRODUCT_ID: '商品識別資料不正確，請重新整理後再試。',
    PRODUCT_UPSTREAM_TIMEOUT: '商品服務回應逾時，請稍後再試。',
    PRODUCT_SERVICE_UNAVAILABLE: '商品服務目前無法連線，請稍後再試。',
    EXTERNAL_TEXT_UPSTREAM_DISABLED: '文字建議服務目前暫停使用，其他功能不受影響。',
    NOT_CONFIGURED: '這項服務尚未完成設定，請聯繫管理員。',
    IDENTITY_TOKEN_UNAVAILABLE: '服務驗證暫時無法使用，請稍後再試。',
    UPSTREAM_TIMEOUT: '後端服務回應逾時，請稍後再試。',
    UPSTREAM_UNAVAILABLE: '後端服務目前無法連線，請稍後再試。',
    PAYLOAD_TOO_LARGE: '上傳的資料過大，請縮小檔案後再試。',
    REQUEST_TOO_LARGE: '上傳的資料過大，請縮小檔案後再試。',
    IMAGE_TOO_LARGE: '圖片檔案過大，請壓縮後再試。',
    INVALID_IMAGE: '圖片格式不正確，請重新選擇圖片。',
    BAD_CONTENT_LENGTH: '上傳資料格式不正確，請重新選擇檔案。',
    NOT_FOUND: '找不到要求的資料。',
    METHOD_NOT_ALLOWED: '目前不支援這項操作。',
    JOB_NOT_FOUND: '工作不存在或已經過期，請重新執行。',
    MEDIA_NOT_FOUND: '找不到這張圖片，可能已被刪除。',
    MEDIA_UNAVAILABLE: '圖片目前無法讀取，請稍後再試。',
    FACE_ANALYSIS_TIMEOUT: '臉部分析逾時，請稍後再試。',
    FACE_ANALYSIS_ERROR: '臉部分析失敗，請稍後再試。',
    // 分析已完成時，提示使用者不必重新拍照。
    PACKAGE_BUILD_FAILED: '臉部分析已完成，但結果整理失敗，請稍後再試（不需重拍照片）。',
    RENDER_TIMEOUT: '妝容生成逾時，請稍後再試。',
    RENDER_PROVIDER_ERROR: '妝容生成服務處理失敗，請稍後再試。',
    // 內容審查擋下來的照片重試不會過——判定是確定性的，同一張圖同一個結果。
    // 跟上面那則分開，因為使用者要做的下一步完全相反：一個是等，一個是換照片。
    RENDER_CONTENT_BLOCKED: '這張照片被 AI 服務的內容審查擋下來了，換一張照片再試一次。同一張照片重試不會成功。',
    OLLAMA_UNAVAILABLE: '文字建議服務目前無法連線，請稍後再試。',
    NETWORK_ERROR: '網路連線失敗，請確認網路後再試。',
    FETCH_TIMEOUT: '服務回應逾時，請稍後再試。'
});

// 寫入請求在前端被擋下時使用這組提示。
const WRITE_BLOCKED_ZH = Object.freeze({
    NO_LOCAL_IDENTITY: '請先登入後再執行這項操作。',
    // 只停止本次寫入，保留本機資料並提示重新登入。
    NO_SESSION_PIN: '這個分頁的登入狀態已失效，請重新登入後再執行這項操作。',
    // 這一條要分兩種情況。先前不論原因都寫「請稍後再試」，
    // 但 401 是**登入已經過期**——等下去只會更糟，正確的動作是重新登入。
    // 給錯的下一步比不給更糟：使用者會照著做，然後再失敗一次。
    SESSION_UNAVAILABLE: '目前無法確認登入狀態，為避免寫錯帳號已中止這次操作，請稍後再試。',
    SESSION_EXPIRED: '登入已過期，這次操作已中止（沒有任何一筆被寫入）。請重新登入後再試一次。',
    OWNER_MISMATCH: '登入身分已切換成其他帳號，為避免寫錯帳號已中止這次操作，請重新整理後再試。',
    DEFAULT: '無法確認目前的登入身分，這次操作已中止。'
});

// 將秒數轉成容易閱讀的等待時間。
function formatRetryWait(seconds) {
    const total = Math.max(1, Math.round(Number(seconds) || 0));
    if (total < 60) return `${total} 秒`;
    const minutes = Math.ceil(total / 60);
    if (minutes < 60) return `${minutes} 分鐘`;
    return `${Math.ceil(minutes / 60)} 小時`;
}
if (typeof window !== 'undefined') window.formatRetryWait = formatRetryWait;

// 優先顯示後端提供的 retryAfterSeconds，缺少時使用一般提示。
function retryWaitSuffix(details) {
    const seconds = Number(details && (details.retryAfterSeconds ?? details.retryAfter)) || 0;
    return seconds > 0 ? `請在 ${formatRetryWait(seconds)}後再試。` : '請稍後再試。';
}

function localizeUserError(message, code = '', status = 0, details = null) {
    const raw = String(message || '').trim();
    // 429 需要顯示等待時間，因此先單獨處理。
    if (status === 429 || /RATE_LIMITED|QUOTA_EXCEEDED/.test(String(code || '').toUpperCase())) {
        const wait = retryWaitSuffix(details);
        const upper = String(code || '').trim().toUpperCase();
        if (upper === 'LOGIN_RATE_LIMITED') return `登入嘗試次數過多，${wait}`;
        if (upper === 'QUOTA_EXCEEDED') return `今日的生成次數已用完，${wait}`;
        return `操作次數過多，${wait}`;
    }
    const explicitCode = String(code || '').trim().toUpperCase();
    // 只有整句都是錯誤碼時才查表，避免誤判一般英文訊息。
    const bareCode = /^[A-Z][A-Z0-9_]{2,}$/.test(raw) ? raw : '';
    const resolvedCode = explicitCode || bareCode;
    if (USER_ERROR_ZH[resolvedCode]) return USER_ERROR_ZH[resolvedCode];

    const exact = {
        'member authentication is unavailable.': '會員服務目前無法連線，請稍後再試。',
        'member authentication failed.': '會員驗證失敗，請稍後再試。',
        'member authentication session could not be established.': '會員登入狀態無法建立，請稍後再試。',
        'member sign-in is required.': '請先登入會員後再繼續。',
        'member session is invalid or expired.': '登入狀態已失效，請重新登入後再繼續。',
        'invalid email or password.': '帳號或密碼錯誤，請重新確認。',
        'too many login attempts.': '登入嘗試次數過多，請稍後再試。',
        'administrator permission is required.': '只有管理員可以執行這項操作。',
        'administrator account is suspended.': '管理員帳號目前已停權。',
        'service authentication is unavailable.': '服務驗證暫時無法使用，請稍後再試。',
        'upstream service is unavailable.': '後端服務目前無法連線，請稍後再試。',
        'upstream service timed out.': '後端服務回應逾時，請稍後再試。',
        'route not found.': '找不到要求的功能。',
        'method not allowed.': '目前不支援這項操作。',
        'request body is too large.': '上傳的資料過大，請縮小檔案後再試。',
        'render image is temporarily unavailable.': '圖片目前無法讀取，請稍後再試。',
        'render image was not found.': '找不到這張圖片，可能已被刪除。',
        'render job not found or expired.': '妝容生成工作不存在或已經過期，請重新執行。',
        'failed to fetch': '網路連線失敗，請確認網路後再試。',
        'page not found': '找不到要求的頁面。'
    };
    if (exact[raw.toLowerCase()]) return exact[raw.toLowerCase()];
    if (status === 401) return '登入狀態已失效，請重新登入後再繼續。';
    if (status === 403) return '你沒有執行這項操作的權限。';
    if (status === 404) return '找不到要求的資料。';
    if (status >= 500) return '系統服務暫時異常，請稍後再試。';

    // 已經含有中文的訊息通常是前端自己撰寫，只替換少量常見英文片段。
    if (/[\u3400-\u9fff]/.test(raw)) {
        return raw
            .replace(/Failed to fetch|NetworkError|Load failed/gi, '網路連線失敗')
            .replace(/Unknown error/gi, '未知錯誤')
            .replace(/Page not found/gi, '找不到頁面');
    }
    // 未收錄的純英文後端訊息不直接顯示，避免把內部實作細節暴露給使用者。
    if (/[A-Za-z]{3}/.test(raw)) return '系統目前無法完成這項操作，請稍後再試。';
    // 先保留後端中文說明，再處理其他 400 類錯誤。
    if (status === 400) return '這項操作無法完成，請確認輸入內容後再試一次。';
    return raw || '系統目前無法完成這項操作，請稍後再試。';
}

if (typeof window !== 'undefined') window.localizeUserError = localizeUserError;

const ApiConfig = {
    services: {
        aiGateway: {
            baseUrl: AI_GATEWAY_URL,
            loginPath: '/auth/login',
            logoutPath: '/auth/logout',
            sessionPath: '/auth/session',
            registerPath: '/auth/register',
            sendOtpPath: '/auth/send-otp',
            forgotPasswordPath: '/auth/forgot-password',
            verifyOtpPath: '/auth/verify-otp',
            configPath: '/public-config'
        },
        faceBasic: {
            baseUrl: gatewayService('face-basic'),
            analyzePath: '/v1/face/analyze/basic',
            posePath: '/v1/face/pose',
            jobPath: '/v1/face/jobs/basic',
            jobStatusPath: '/v1/face/jobs/{jobId}',
            jobResultPath: '/v1/face/jobs/{jobId}/result',
            jobFeedbackPath: '/v1/face/jobs/{jobId}/feedback'
        },
        facePro: {
            baseUrl: gatewayService('face-pro'),
            analyzePath: '/v1/face/analyze/pro',
            jobPath: '/v1/face/jobs/pro',
            jobStatusPath: '/v1/face/jobs/{jobId}',
            jobResultPath: '/v1/face/jobs/{jobId}/result',
            jobFeedbackPath: '/v1/face/jobs/{jobId}/feedback'
        },
        textSuggestion: {
            baseUrl: gatewayService('text-suggestion'),
            suggestPath: '/suggest'
        },
        render: {
            baseUrl: gatewayService('render-service'),
            renderPath: '/render'
        },
        product: {
            baseUrl: gatewayService('product-api'),
            recommendPath: '/recommend-products',
            listPath: '/api/products'
        },
        memberDatabase: {
            baseUrl: gatewayService('member-database')
        }
    },

    url(serviceName, pathKey) {
        const service = this.services[serviceName];
        if (!service) throw new Error(`Unknown API service: ${serviceName}`);
        const path = service[pathKey];
        if (!service.baseUrl || !path) return '';
        return `${service.baseUrl}${path}`;
    },

    jobUrl(serviceName, pathKey, jobId) {
        return this.url(serviceName, pathKey).replace('{jobId}', encodeURIComponent(jobId));
    }
};

// API 串接層。
const Api = {
    config: ApiConfig,
    _sessionAbortController: typeof AbortController === 'function' ? new AbortController() : null,
    _expectedActorKey: 'gatewayExpectedActor',
    _expectedSubjectKey: 'gatewayExpectedSubject',
    // 管理員角色只能採信後端驗證過的 session，不能使用可修改的本機資料。
    _verifiedRoleKey: 'gatewayVerifiedRole',
    // 訪客票券。用 localStorage 而不是 sessionStorage——關掉分頁就重新拿一張的話，
    // 三次額度等於沒有上限。
    _guestTicketKey: 'gatewayGuestTicket',
    _guestQuotaKey: 'gatewayGuestQuota',

    // ── 訪客試用 ────────────────────────────────────────────────────────────
    // 未登入的人可以跑完整的「臉部分析 → 妝容渲染」，次數由 Gateway 記帳。
    // 訪客只能體驗，不能存圖：收藏走 member-database，那條路對訪客一律 401。

    guestTicket() {
        try { return String(localStorage.getItem(this._guestTicketKey) || '').trim(); }
        catch (_) { return ''; }
    },

    guestQuota() {
        try { return JSON.parse(localStorage.getItem(this._guestQuotaKey) || 'null') || null; }
        catch (_) { return null; }
    },

    _rememberGuestQuota(remaining, max) {
        const parsedRemaining = Number(remaining);
        const parsedMax = Number(max);
        if (!Number.isFinite(parsedRemaining) || !Number.isFinite(parsedMax)) return;
        try {
            localStorage.setItem(this._guestQuotaKey,
                JSON.stringify({ remaining: parsedRemaining, max: parsedMax }));
        } catch (_) { /* 隱私模式寫不進去；只影響顯示，不影響流程 */ }
    },

    // 取一張票券，已經有就沿用。額度是按票券算的，所以不能每次都換新的。
    async ensureGuestTicket() {
        const existing = this.guestTicket();
        if (existing) return existing;
        if (this._guestTrialUnavailable) return '';
        const base = this.config.services.aiGateway.baseUrl || '';
        try {
            const res = await fetch(`${base}/guest/session`, {
                method: 'POST',
                headers: { 'Accept': 'application/json' },
            });
            if (!res.ok) {
                // 功能沒開就別再問第二次，否則每次分析都多打一個 404。
                if (res.status === 404) this._guestTrialUnavailable = true;
                return '';
            }
            const data = await res.json().catch(() => null);
            const ticket = String(data?.ticket || '').trim();
            if (!ticket) return '';
            try { localStorage.setItem(this._guestTicketKey, ticket); } catch (_) { return ''; }
            this._rememberGuestQuota(data?.remaining, data?.maxRuns);
            return ticket;
        } catch (_) {
            return '';
        }
    },

    // 訪客可以走的路徑。與 Gateway 的 GUEST_ALLOWED_SERVICES 對應——這裡放行了但
    // 後端沒放行只會多一次 401，反過來則會讓使用者看到不必要的「請重新登入」。
    _guestTrialPath(input) {
        try {
            const url = new URL(String(input), window.location.origin);
            // 本機開發時前端在 5500、Gateway 在 8015；兩者不同 origin，
            // 但仍然是同一個受信任的 Gateway。原本只接受同源網址，導致
            // `_protectedFetch` 把本機的臉部分析／渲染請求當成一般外連，
            // 不帶 X-Guest-Ticket，結果工作可能建起來，後續輪詢或圖片讀取卻
            // 回 401/403，畫面就只剩「已完成」但沒有成果圖。
            const gatewayOrigin = new URL(
                this.config?.services?.aiGateway?.baseUrl || window.location.origin,
                window.location.origin,
            ).origin;
            if (url.origin !== window.location.origin && url.origin !== gatewayOrigin) return false;
            return ['/face-basic/', '/render-service/'].some(prefix => url.pathname.startsWith(prefix));
        } catch (_) {
            return false;
        }
    },

    _pinnedActor() {
        try { return String(sessionStorage.getItem(this._expectedActorKey) || '').trim(); }
        catch (_) { return ''; }
    },

    _pinnedSubject() {
        try { return String(sessionStorage.getItem(this._expectedSubjectKey) || '').trim().toLowerCase(); }
        catch (_) { return ''; }
    },

    // 後端驗證過的角色；只有在這個分頁確實有 pin 過 session（actor 存在）時才回。
    verifiedRole() {
        try {
            if (!this._pinnedActor()) return '';
            return String(sessionStorage.getItem(this._verifiedRoleKey) || '').trim().toLowerCase();
        } catch (_) { return ''; }
    },

    // 只有後端確認為管理員的分頁可以顯示與進入後台。
    isVerifiedAdmin() {
        return this.verifiedRole() === 'admin';
    },

    _pinSession(session) {
        const actorId = String(session?.actorId || '').trim();
        const sub = String(session?.sub || '').trim().toLowerCase();
        if (!actorId || !sub) return false;
        try {
            sessionStorage.setItem(this._expectedActorKey, actorId);
            sessionStorage.setItem(this._expectedSubjectKey, sub);
            sessionStorage.setItem(this._verifiedRoleKey, String(session?.role || '').trim().toLowerCase());
            return true;
        } catch (_) {
            return false;
        }
    },

    _clearPinnedSession() {
        try {
            sessionStorage.removeItem(this._expectedActorKey);
            sessionStorage.removeItem(this._expectedSubjectKey);
            sessionStorage.removeItem(this._verifiedRoleKey);
        } catch (_) {}
    },

    _resetSessionRequests() {
        this._sessionAbortController = typeof AbortController === 'function' ? new AbortController() : null;
    },

    _cancelSessionRequests() {
        if (this._sessionAbortController && !this._sessionAbortController.signal.aborted) {
            this._sessionAbortController.abort();
        }
    },

    _sessionSignal(existingSignal) {
        const sessionSignal = this._sessionAbortController?.signal;
        const signals = [existingSignal, sessionSignal].filter(Boolean);
        if (!signals.length) return undefined;
        if (signals.length === 1) return signals[0];
        if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.any === 'function') {
            return AbortSignal.any(signals);
        }
        const combined = new AbortController();
        const abort = () => combined.abort();
        signals.forEach(signal => {
            if (signal.aborted) abort();
            else signal.addEventListener('abort', abort, { once: true });
        });
        return combined.signal;
    },

    _isProtectedGatewayUrl(input) {
        try {
            const url = new URL(String(input), window.location.origin);
            // 正式站是同源路徑；本機開發則是 5500 → 8015 的跨埠 Gateway。
            // 兩種情況都必須套用 credentials、session abort 與票券邏輯。
            const gatewayOrigin = new URL(
                this.config?.services?.aiGateway?.baseUrl || window.location.origin,
                window.location.origin,
            ).origin;
            if (url.origin !== window.location.origin && url.origin !== gatewayOrigin) return false;
            return ['/member-database/', '/face-basic/', '/face-pro/', '/render-service/', '/text-suggestion/', '/admin-api/']
                .some(prefix => url.pathname.startsWith(prefix));
        } catch (_) {
            return false;
        }
    },

    // 只有會員與管理路徑的 401 代表登入可能失效；模型服務的 401 屬於上游錯誤。
    _speaksForMemberSession(input) {
        try {
            const url = new URL(String(input), window.location.origin);
            const gatewayOrigin = new URL(
                this.config?.services?.aiGateway?.baseUrl || window.location.origin,
                window.location.origin,
            ).origin;
            if (url.origin !== window.location.origin && url.origin !== gatewayOrigin) return false;
            return ['/member-database/', '/admin-api/'].some(prefix => url.pathname.startsWith(prefix));
        } catch (_) {
            return false;
        }
    },

    // 讀回應內容裡的錯誤碼。用 clone() 才不會把 body 吃掉——呼叫端還要自己讀一次。
    async _peekErrorCode(res) {
        try {
            const peek = await res.clone().json();
            return String(peek?.error?.code || peek?.detail?.error?.code || '').toUpperCase();
        } catch (_) {
            return '';
        }
    },

    _copyHeaders(headers) {
        const copied = {};
        if (headers && typeof headers.forEach === 'function') {
            headers.forEach((value, key) => { copied[key] = value; });
        } else if (headers && typeof headers === 'object') {
            Object.assign(copied, headers);
        }
        return copied;
    },

    _notifySessionInvalid(type = 'decorate-me:session-owner-changed', detail = {}) {
        if (this._sessionExpiredNotified) return;
        this._sessionExpiredNotified = true;
        this._cancelSessionRequests();
        window.dispatchEvent(new CustomEvent(type, { detail }));
    },

    // 讀取同源 CSRF cookie；缺少時交由後端拒絕請求。
    _csrfToken() {
        try {
            const jar = String((typeof document !== 'undefined' && document.cookie) || '');
            const hit = jar.split(';').map(part => part.trim()).find(part => part.startsWith('dm_csrf='));
            return hit ? decodeURIComponent(hit.slice('dm_csrf='.length)) : '';
        } catch (_) {
            return '';
        }
    },

    // 所有受保護寫入都經過這裡，並只向同源 Gateway 傳送身分標頭。
    async _protectedFetch(input, init = {}) {
        if (!this._sessionAbortController) this._resetSessionRequests();
        const method = String(init.method || 'GET').toUpperCase();
        const isWrite = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
        const isProtected = this._isProtectedGatewayUrl(input);
        const actorId = isProtected ? this._pinnedActor() : '';
        const isGuestRequest = isProtected && !actorId && this._guestTrialPath(input);
        const nextInit = {
            ...init,
            credentials: isProtected ? 'include' : init.credentials,
            headers: this._copyHeaders(init.headers),
            // 訪客的請求不掛會員 session 的 abort controller。那個 controller 是給
            // 「會員 session 失效時，把還在飛的請求全部收掉」用的，而訪客根本沒有會員
            // session——掛上去的後果是：頁面上任何一個會員 API 的 401 都會把訪客
            // 正在跑的臉部分析一起砍掉，畫面顯示「signal is aborted without reason」。
            signal: (isProtected && !isGuestRequest) ? this._sessionSignal(init.signal) : init.signal
        };
        if (isGuestRequest) {
            // 訪客試用：沒有登入身分，但有票券就能跑分析與渲染。讀取也要帶——
            // 輪詢工作狀態、取結果都是 GET，後端一樣要認得這是同一個訪客。
            const ticket = this.guestTicket() || await this.ensureGuestTicket();
            if (ticket) nextInit.headers['X-Guest-Ticket'] = ticket;
        } else if (isWrite && isProtected) {
            if (!actorId) {
                // 分頁缺少綁定身分時只擋下寫入，不直接清除資料或登出。
                const error = new Error(WRITE_BLOCKED_ZH.NO_SESSION_PIN);
                error.code = 'EXPECTED_ACTOR_REQUIRED';
                throw error;
            }
            nextInit.headers['X-Expected-Actor'] = actorId;
            // 將同源 CSRF cookie 放入標頭，讓後端驗證 double-submit token。
            const csrfToken = this._csrfToken();
            if (csrfToken) nextInit.headers['X-CSRF-Token'] = csrfToken;
        }
        const res = await fetch(input, nextInit);
        if (nextInit.headers['X-Guest-Ticket']) {
            this._rememberGuestQuota(
                res.headers.get('X-Guest-Trial-Remaining'),
                res.headers.get('X-Guest-Trial-Max'),
            );
        }
        // 從未登入的分頁收到會員 API 的 401 是**預期結果**，不是「登入失效」。
        // 少了 actorId 這個條件，訪客一進站就會因為背景載入會員資料拿到 401 而觸發
        // 登出流程：abort controller 被 abort、頁面上所有受保護請求連同訪客的臉部分析
        // 一起被砍，而且沒有任何地方會重設那個 controller——之後每一次請求都直接失敗。
        if (isProtected && actorId && res.status === 401 && this._speaksForMemberSession(input)) {
            // 只用會員驗證專用錯誤碼判定登出，避免把上游 401 誤認成 session 失效。
            const sessionCodes = [
                'MEMBER_AUTH_REQUIRED', 'MEMBER_SESSION_REQUIRED', 'MEMBER_AUTH_INVALID',
                'MEMBER_SESSION_INVALID', 'MEMBER_SESSION_MISSING'
            ];
            if (sessionCodes.includes(await this._peekErrorCode(res))) {
                this._notifySessionInvalid('decorate-me:session-expired');
            }
        } else if (isProtected && res.status === 409) {
            // 409 也可能是一般業務衝突，只有指定錯誤碼才代表帳號已切換。
            const ownerChangeCodes = ['ACCOUNT_NOT_AVAILABLE', 'SESSION_OWNER_CHANGED', 'EXPECTED_ACTOR_REQUIRED'];
            if (ownerChangeCodes.includes(await this._peekErrorCode(res))) {
                this._notifySessionInvalid('decorate-me:session-owner-changed', { reason: 'SESSION_OWNER_CHANGED' });
            }
        }
        return res;
    },

    // 從 Gateway 取得同源路徑，不讓瀏覽器直接連上游服務。
    async bootstrapConfig() {
        const gateway = this.config.services.aiGateway;
        // 設定逾時，避免 Gateway 無回應時讓開站流程一直等待。
        const controller = typeof AbortController === 'function' ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(), 4000) : null;
        try {
            const res = await fetch(`${gateway.baseUrl}${gateway.configPath}`, {
                cache: 'no-store',
                signal: controller ? controller.signal : undefined
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const sameOriginGatewayPath = (value, fallback) => {
                const raw = String(value || '').replace(/\/+$/, '');
                return raw.startsWith('/') && !raw.startsWith('//') ? `${gateway.baseUrl}${raw}` : fallback;
            };
            this.config.services.memberDatabase.baseUrl = sameOriginGatewayPath(data.memberDatabaseUrl, gatewayService('member-database'));
            this.config.services.product.baseUrl = sameOriginGatewayPath(data.productUrl, gatewayService('product-api'));
            // crawlerUrl 不再讀取：爬蟲已改為只寫 crawler_staging_products，不與前端直連。
            // /public-config 仍然會回這個欄位，但前端沒有任何地方需要它了。
            return true;
        } catch (err) {
            console.warn('[config] /public-config 讀取失敗，沿用同源 Gateway 路徑：', err && err.message);
            return false;
        } finally {
            if (timer) clearTimeout(timer);
        }
    },

    async _warmService(baseUrl) {
        if (!baseUrl) return;
        const headers = this._gatewayHeaders();
        // 訪客的暖機也要帶票券，否則 Gateway 回 401、冷啟動沒被喚醒，
        // 第一次渲染要多等三十秒以上。這裡不主動領票券——暖機不該是領票的時機。
        if (!this._pinnedActor()) {
            const ticket = this.guestTicket();
            if (ticket) headers['X-Guest-Ticket'] = ticket;
        }
        try {
            await fetch(`${baseUrl}/health`, {
                method: 'GET',
                headers,
                cache: 'no-store',
            });
        } catch (_) {
            // Ignore warm-up failures and let the real request surface the actionable error.
        }
    },

    // 在背景預熱臉部分析服務，縮短第一次分析的等待時間。
    warmFaceServices() {
        [
            this.config.services.faceBasic.baseUrl,
            this.config.services.facePro.baseUrl,
        ].filter(Boolean).forEach(baseUrl => { this._warmService(baseUrl); });
    },

    // 臉部分析與渲染一律走 Gateway，帶登入後的短期 session。Gateway 是 session-only 模式，
    // 上游金鑰只留在伺服器端，瀏覽器不再送 X-API-Key。
    _gatewayHeaders(headers = {}) {
        return { ...headers };
    },
    _faceHeaders() {
        return this._gatewayHeaders();
    },

    // 臉部分析錯誤可能有兩種格式：上游是 {detail:{error:{message}}}，Gateway 是 {error:{code,message}}。
    // 只認其中一種會把真正原因吞掉，變成無法排查的通用訊息。
    async _faceError(res, fallback) {
        const data = await res.json().catch(() => null);
        const error = data?.detail?.error || data?.error || null;
        const code = error?.code || '';
        // 訪客把免費次數用完了。這不是錯誤狀態，訊息要引導註冊而不是叫他重新登入。
        if (code === 'GUEST_TRIAL_EXHAUSTED' || code === 'GUEST_TICKET_RATE_LIMITED') {
            const exhausted = new Error(error?.message || USER_ERROR_ZH[code]);
            exhausted.code = code;
            return exhausted;
        }
        // session 過期是最常見且可自行解決的情況，直接給出可行動的指示
        if (res.status === 401 || code === 'MEMBER_AUTH_REQUIRED' || code === 'MEMBER_AUTH_INVALID') {
            // 訪客沒有登入狀態可以「重新登入」，對他們要說的是先登入。
            if (!this._pinnedActor() && this.guestTicket()) {
                return new Error('免費體驗已結束，請登入或註冊會員後再繼續使用。');
            }
            return new Error('登入狀態已失效，請重新登入後再試一次。');
        }
        const message = error?.message
            || (typeof data?.detail === 'string' ? data.detail : '')
            || data?.message
            || fallback;
        return new Error(code ? `${message}（${code}）` : message);
    },

    // 後端建 job 時發 resultToken，之後查詢 job 狀態/結果必須帶 X-Job-Token，否則回 403
    _faceJobHeaders(service, resultToken, extra = {}) {
        const headers = { ...this._faceHeaders(), ...extra };
        if (resultToken) headers['X-Job-Token'] = resultToken;
        return headers;
    },

    // 臉部分析
    async detectFacePose(file) {
        const fd = new FormData();
        fd.append('file', file);
        const res = await this._protectedFetch(this.config.url('faceBasic', 'posePath'), { method: 'POST', body: fd, headers: this._faceHeaders() });
        if (!res.ok) throw await this._faceError(res, '角度偵測失敗');
        return res.json();
    },

    async createFaceJob(file) {
        const fd = new FormData();
        fd.append('file', file);
        const res = await this._protectedFetch(this.config.url('faceBasic', 'jobPath'), { method: 'POST', body: fd, headers: this._faceHeaders() });
        if (!res.ok) throw await this._faceError(res, '建立 BASIC job 失敗');
        return res.json();
    },

    async createFaceProJob(files) {
        const fd = new FormData();
        fd.append('front', files.front);
        for (const role of ['left45', 'right45', 'side']) {
            if (files[role]) fd.append(role, files[role]);
        }
        const res = await this._protectedFetch(this.config.url('facePro', 'jobPath'), { method: 'POST', body: fd, headers: this._faceHeaders() });
        if (!res.ok) throw await this._faceError(res, '建立 PRO job 失敗');
        return res.json();
    },

    // 將五官修正回傳給分析服務，作為後續模型改善資料。
    // 回傳失敗不影響本次建議與收藏；confirmed 表示使用者是否接受原判斷。
    // allowTrainingUse 為 true 時才會帶 imageDataUrl。預設不帶——「沒同意就不上傳照片」
    // 是靠這裡結構性保證的，不是靠後端自律：沒勾選，照片根本不會離開瀏覽器。
    async sendAnalysisFeedback({ mode, jobId, resultToken, packageId, predicted, corrections,
                                 allowTrainingUse = false, imageDataUrl = '', sideImageDataUrl = '' }) {
        if (!jobId) return { ok: false, reason: 'no-job' };
        const service = mode === 'pro' ? 'facePro' : 'faceBasic';
        const fixes = corrections || {};
        try {
            const res = await this._protectedFetch(this.config.jobUrl(service, 'jobFeedbackPath', jobId), {
                method: 'POST',
                // 使用 job token 確認回饋來自建立該工作的瀏覽器。
                headers: this._faceJobHeaders(service, resultToken, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({
                    packageId: packageId || null,
                    predicted: predicted || {},
                    corrections: fixes,
                    confirmed: Object.keys(fixes).length === 0,
                    // 只有「明確同意」且「真的有修正」時才送照片。沒有修正就沒有值得
                    // 保存的樣本，送了也只是白白多傳一次臉部資料。
                    ...(allowTrainingUse && imageDataUrl && Object.keys(fixes).length
                        ? { allowTrainingUse: true, imageDataUrl }
                        : {}),
                    // 側臉鼻型那顆模型吃的是**整張側臉圖**（線上推論也是），所以正面照
                    // 對它沒有訓練價值。只有在「同意」＋「真的改了側臉鼻型」＋「手上有
                    // 側面照」三者同時成立時才送——同意文案也必須分開講明這一張是整張
                    // 側臉照，不是局部裁切，兩者可辨識性差很多。
                    ...(allowTrainingUse && sideImageDataUrl && fixes['側臉鼻型']
                        ? { allowTrainingUse: true, sideImageDataUrl }
                        : {})
                })
            });
            return { ok: res.ok, status: res.status };
        } catch (_) {
            return { ok: false };
        }
    },

    async getFaceJob(mode, jobId, resultToken) {
        const service = mode === 'pro' ? 'facePro' : 'faceBasic';
        const res = await this._protectedFetch(this.config.jobUrl(service, 'jobStatusPath', jobId), { cache: 'no-store', headers: this._faceJobHeaders(service, resultToken) });
        if (!res.ok) throw await this._faceError(res, '查詢 job 失敗');
        return res.json();
    },

    async getFaceJobResult(mode, jobId, resultToken) {
        const service = mode === 'pro' ? 'facePro' : 'faceBasic';
        const res = await this._protectedFetch(this.config.jobUrl(service, 'jobResultPath', jobId), { cache: 'no-store', headers: this._faceJobHeaders(service, resultToken) });
        if (!res.ok) throw await this._faceError(res, '取得 job 結果失敗');
        return res.json();
    },

    async waitForFaceJob(mode, jobId, resultToken, onProgress) {
        for (let attempt = 0; attempt < 120; attempt++) {
            const job = await this.getFaceJob(mode, jobId, resultToken);
            if (typeof onProgress === 'function') onProgress(job);
            if (job.status === 'completed') {
                return this.getFaceJobResult(mode, jobId, resultToken);
            }
            if (job.status === 'failed') {
                // 失敗碼要跟著丟出去。後端分三種失敗，只有 FACE_IMAGE_UNUSABLE 的 message
                // 是寫給使用者看的重拍指引，另外兩碼是系統錯誤；只丟 message 的話呼叫端
                // 無從分辨，於是指引跟系統錯誤會用同一種語氣顯示。
                const err = new Error(job.error?.message || '臉部分析 job 失敗');
                err.code = job.error?.code || '';
                err.retryable = job.error?.retryable !== false;
                throw err;
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
        throw new Error('臉部分析 job 逾時');
    },

    // 文字建議經由 Gateway 傳送，瀏覽器只使用短期 session。
    _textSuggestionHeaders() {
        return this._gatewayHeaders({ 'Content-Type': 'application/json' });
    },

    // 文字建議只需要 faceAnalysis；不要傳送含有臉部照片的完整資料包。
    async suggestMakeup({ faceAnalysis, style, userNote }) {
        let res;
        try {
            res = await this._protectedFetch(this.config.url('textSuggestion', 'suggestPath'), {
                method: 'POST',
                headers: this._textSuggestionHeaders(),
                body: JSON.stringify({ faceAnalysis, style, language: 'zh-TW', userNote }),
            });
        } catch (err) {
            throw new Error('無法連線到建議服務：' + err.message);
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            const code = err.detail?.error?.code || err.error?.code || '';
            // 外部 Ollama 路徑預設關閉（GATEWAY_ALLOW_EXTERNAL_TEXT_UPSTREAM），
            // Gateway 回的是英文原文，這裡換成使用者看得懂的說明。
            if (code === 'EXTERNAL_TEXT_UPSTREAM_DISABLED') {
                throw new Error('妝容建議服務目前停用中（尚未接上受信任的文字服務），其他功能不受影響。');
            }
            // 401 有兩種完全不同的來源，先前一律當成「上游授權問題」——
            // 於是 session 過期時畫面會寫「與你的登入狀態無關」，那句話正好是反的，
            // 使用者照著它去找服務問題，永遠不會想到只要重新登入。
            //
            //   MEMBER_AUTH_*／MEMBER_SESSION_*  → Gateway 擋的，會員 session 沒了或過期
            //   其他 401                          → 上游（Ollama）拒絕，通常是金鑰設定
            if (res.status === 401) {
                const sessionCodes = [
                    'MEMBER_AUTH_REQUIRED', 'MEMBER_AUTH_INVALID',
                    'MEMBER_SESSION_REQUIRED', 'MEMBER_SESSION_INVALID', 'MEMBER_SESSION_MISSING'
                ];
                if (sessionCodes.includes(code)) {
                    // 不要在訊息裡寫死有效期。它是伺服器端的環境變數
                    // （GATEWAY_SESSION_TTL_SECONDS），2026-08-14 就從 2 小時改成 8 小時——
                    // 訊息裡的數字當天就過期了。寫死的數字沒有人會記得回來改。
                    throw new Error('登入狀態已失效，請重新登入後再產生建議。');
                }
                throw new Error('文字建議服務拒絕了這次請求（HTTP 401）。這是服務端的授權設定問題，與你的登入狀態無關，其他功能可以照常使用。');
            }
            const msg = err.detail?.error?.message
                || err.error?.message
                || err.detail
                || err.message
                || `建議服務回傳 HTTP ${res.status}`;
            throw new Error(msg);
        }
        return res.json();
    },

    async renderMakeup({ imageDataUrl, prompt, strength = 0.45 }) {
        const baseUrl = this.config.services.render.baseUrl;
        const url = `${baseUrl}${this.config.services.render.renderPath}`;
        // 身分改由 Gateway 從 session 認定；X-User-Email／X-User-Role 是瀏覽器可偽造的，
        // Gateway 也不會轉送，所以不再送出（渲染端沒有 email 時會退回以 IP 計算配額）。
        const headers = this._gatewayHeaders({ 'Content-Type': 'application/json' });
        let res;
        try {
            await this._warmService(baseUrl);
            await new Promise(resolve => setTimeout(resolve, 500));
            const requestInit = {
                method: 'POST',
                headers,
                body: JSON.stringify({ image: imageDataUrl, prompt, strength }),
            };
            try {
                res = await this._protectedFetch(url, requestInit);
            } catch (firstErr) {
                // Cloud Run cold start or transient network hiccups can cause the first browser fetch to fail.
                await new Promise(resolve => setTimeout(resolve, 1500));
                res = await this._protectedFetch(url, requestInit);
            }
        } catch (err) {
            throw new Error('無法連線到渲染服務：' + err.message);
        }
        const data = this._normalizeRenderJob(await res.json().catch(() => ({})));
        if (!res.ok) {
            if (res.status === 401) {
                throw new Error('登入狀態已失效，請重新登入後再試一次。');
            }
            throw this._renderApiError(data, res.status, `Render API HTTP ${res.status}`);
        }
        if (data.status !== 'completed' || !data.afterImageUrl) {
            throw this._renderApiError(data, res.status, '妝容渲染失敗');
        }
        if (data.renderQuota && Auth.getProfile) {
            const current = Auth.getProfile() || {};
            Auth.setProfile({ ...current, renderQuota: data.renderQuota });
        }
        return data;
    },

    // 渲染服務正式契約使用 camelCase，但本機代理、舊版服務或測試 stub 可能把
    // 結果包在 result/data/job 裡，或回傳 snake_case。所有消費端先走這個正規化，
    // 這樣「工作已完成」與「畫面有可讀的圖片網址」不會因為回應包裝不同而脫鉤。
    _qualifyRenderMediaUrl(value) {
        const raw = String(value || '').trim();
        if (!raw || !raw.startsWith('/')) return raw;
        try {
            const gatewayBase = this.config?.services?.render?.baseUrl || window.location.origin;
            const gatewayUrl = new URL(gatewayBase, window.location.origin);
            // 正式站前端與 Gateway 同源，保留相對網址讓 cookie／部署路徑照原本方式工作；
            // 本機前端通常在 5500，而 Gateway 在 8015，這時相對網址若不補綴會被
            // 瀏覽器送到 5500/media/render，靜態伺服器當然找不到圖片。
            if (gatewayUrl.origin === window.location.origin) return raw;
            return new URL(raw, gatewayUrl.origin).href;
        } catch (_) {
            return raw;
        }
    },

    _normalizeRenderJob(payload) {
        const root = payload && typeof payload === 'object' ? payload : {};
        const nestedSources = [root.result, root.data, root.job, root.detail]
            .filter(value => value && typeof value === 'object' && !Array.isArray(value));
        const nested = nestedSources.reduce((merged, source) => ({ ...merged, ...source }), {});
        const sources = [root, ...nestedSources];
        const pick = keys => {
            for (const source of sources) {
                for (const key of keys) {
                    if (source[key] != null && String(source[key]).trim() !== '') return source[key];
                }
            }
            return undefined;
        };
        return {
            ...root,
            ...(nested && typeof nested === 'object' ? nested : {}),
            status: pick(['status']) || root.status,
            jobId: pick(['jobId', 'job_id', 'id']) || root.jobId,
            resultToken: pick(['resultToken', 'result_token', 'token']) || root.resultToken,
            progress: pick(['progress', 'percent', 'percentage']) ?? root.progress,
            afterImageUrl: this._qualifyRenderMediaUrl(pick(['afterImageUrl', 'after_image_url', 'afterUrl', 'after_url', 'outputUrl', 'output_url', 'imageUrl', 'image_url'])),
            beforeImageUrl: this._qualifyRenderMediaUrl(pick(['beforeImageUrl', 'before_image_url', 'beforeUrl', 'before_url'])),
            replicateTempUrl: pick(['replicateTempUrl', 'replicate_temp_url']),
            renderPrompt: pick(['renderPrompt', 'render_prompt']),
            promptSource: pick(['promptSource', 'prompt_source']),
            error: pick(['error']) ?? root.error,
        };
    },

    // 渲染服務的錯誤可能來自 Gateway、舊版服務或工作本身；不論外層包法，
    // 都要保留 code／retryAfterSeconds，交給同一套中文錯誤訊息處理，不能把
    // 「Render rate limit exceeded. Try again in 530 seconds.」原樣丟給使用者。
    _renderApiError(payload, status = 0, fallback = '妝容渲染失敗') {
        const detail = payload?.error && typeof payload.error === 'object'
            ? payload.error
            : payload?.detail?.error && typeof payload.detail.error === 'object'
                ? payload.detail.error
                : null;
        const raw = typeof payload?.error === 'string'
            ? payload.error
            : detail?.message || payload?.message || payload?.detail?.message || fallback;
        const code = String(detail?.code || payload?.code || '').trim().toUpperCase();
        const retryMatch = String(raw).match(/(?:in|after)\s+(\d+)\s*seconds?/i);
        const details = detail || retryMatch
            ? { ...(detail || {}), ...(retryMatch && detail?.retryAfterSeconds == null
                ? { retryAfterSeconds: Number(retryMatch[1]) }
                : {}) }
            : null;
        const error = new Error(localizeUserError(raw, code, status, details));
        error.code = code;
        error.status = Number(status) || 0;
        error.retryable = details?.retryable !== false;
        error.details = details || {};
        return error;
    },

    // 渲染時間較長，因此建立工作後以 jobId 輪詢進度。
    // 前端只送結構化資料，prompt 由後端產生；查詢結果時必須附上 job token。
    async renderMakeupAsync({ imageDataUrl, styleId = 'natural', analysisPackage = null, strength = 0.35, onProgress = null }) {
        const baseUrl = this.config.services.render.baseUrl;
        // 同上：身分由 Gateway 依 session 認定，不再送瀏覽器可偽造的 X-User-Email／X-User-Role。
        const headers = this._gatewayHeaders({ 'Content-Type': 'application/json' });

        const emit = (p) => { if (typeof onProgress === 'function') onProgress(p); };

        let submitRes;
        try {
            await this._warmService(baseUrl);
            const requestInit = {
                method: 'POST',
                headers,
                body: JSON.stringify({ image: imageDataUrl, styleId, analysisPackage, strength }),
            };
            try {
                submitRes = await this._protectedFetch(`${baseUrl}/render/jobs`, requestInit);
            } catch (firstErr) {
                // 冷啟動或瞬斷時第一次 fetch 可能直接失敗，重試一次
                await new Promise(resolve => setTimeout(resolve, 1500));
                submitRes = await this._protectedFetch(`${baseUrl}/render/jobs`, requestInit);
            }
        } catch (err) {
            throw new Error('無法連線到渲染服務：' + err.message);
        }

        let submitted = this._normalizeRenderJob(await submitRes.json().catch(() => ({})));
        if (!submitRes.ok) {
            if (submitRes.status === 401) {
                throw new Error('登入狀態已失效，請重新登入後再試一次。');
            }
            // 409 DUPLICATE_IN_PROGRESS：多半是上面那次「冷啟動重試」撞到自己——
            // 第一次 fetch 逾時，但伺服器其實已經把 job 建起來了，重送就撞上後端的
            // 去重保護。這不是失敗，使用者的渲染正在跑，所以接上那個 job 的進度即可。
            // 後端會在 error.details 帶回 jobId 與 resultToken（同一位使用者才撞得到，
            // dedup key 本身含 ownerId），補進 submitted 後，底下的輪詢邏輯原封不動就能用。
            const dup = submitRes.status === 409
                && submitted?.error?.code === 'DUPLICATE_IN_PROGRESS'
                && submitted?.error?.details?.jobId
                ? submitted.error.details
                : null;
            if (dup) {
                submitted = { jobId: dup.jobId, resultToken: dup.resultToken, status: 'running', progress: 1 };
            } else {
                throw this._renderApiError(submitted, submitRes.status, `Render API HTTP ${submitRes.status}`);
            }
        }

        const jobId = submitted.jobId;
        if (!jobId) throw this._renderApiError(submitted, submitRes.status, '渲染服務沒有回傳 jobId');
        emit(submitted.progress || 1);

        // 快取命中時後端會直接回 completed，不用輪詢
        if (submitted.status === 'completed' && submitted.afterImageUrl) {
            emit(100);
            return submitted;
        }

        // 輪詢憑證：只活在這次渲染流程，不落地保存
        if (submitted.resultToken) headers['X-Job-Token'] = submitted.resultToken;
        const pollUrl = `${baseUrl}/render/jobs/${jobId}`;
        const deadline = Date.now() + 5 * 60 * 1000;  // 5 分鐘保險絲，正常 150 秒內一定結束
        // 輪詢間隔逐步增加到 10 秒，減少長時間渲染造成的無效請求。
        const POLL_MIN_MS = 2000;
        const POLL_MAX_MS = 10000;
        let pollDelay = POLL_MIN_MS;
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, pollDelay));
            pollDelay = Math.min(POLL_MAX_MS, Math.round(pollDelay * 1.5));
            let job;
            try {
                const pollRes = await this._protectedFetch(pollUrl, { method: 'GET', headers, cache: 'no-store' });
                job = this._normalizeRenderJob(await pollRes.json().catch(() => ({})));
                if (!pollRes.ok) {
                    // 輪詢途中的暫時性錯誤不該直接判死，繼續等下一輪
                    if (pollRes.status === 404) throw new Error('渲染工作不存在或已過期');
                    // 被限流時依 Retry-After 等待；讀不到時沿用目前退避間隔。
                    if (pollRes.status === 429) {
                        const wait = Number(job?.error?.retryAfterSeconds
                            || pollRes.headers.get('Retry-After')) || 0;
                        if (wait > 0) pollDelay = Math.min(60000, wait * 1000);
                        else pollDelay = Math.min(POLL_MAX_MS, pollDelay * 2);
                    }
                    continue;
                }
            } catch (err) {
                if (err.message === '渲染工作不存在或已過期') throw err;
                continue;  // 網路瞬斷，下一輪再試
            }
            // 這一輪拿到了正常回應：把節奏收回最小間隔，讓接近完成時的回饋維持即時。
            pollDelay = POLL_MIN_MS;

            emit(job.progress || 0);
            if (job.status === 'completed' && job.afterImageUrl) {
                emit(100);
                if (job.renderQuota && Auth.getProfile) {
                    const current = Auth.getProfile() || {};
                    Auth.setProfile({ ...current, renderQuota: job.renderQuota });
                }
                return job;
            }
            if (job.status === 'failed') {
                throw this._renderApiError(job, job?.error?.status || 0, '妝容渲染失敗');
            }
        }
        throw new Error('渲染逾時（超過 5 分鐘）。請稍後再試一次。');
    },

    // 我們的分析結果 LAB 欄位是小寫 {L,a,b}，但 product 服務要求大寫 {L,A,B}，不轉換的話永遠會被判定缺欄位
    _labToUpperKeys(lab) {
        if (!lab || typeof lab !== 'object') return null;
        const L = lab.L ?? lab.l;
        const A = lab.A ?? lab.a;
        const B = lab.B ?? lab.b;
        if (L == null && A == null && B == null) return null;
        return { L, A, B };
    },

    // 眉彩的推薦理由不可以宣稱「與您的膚色匹配」。
    //
    // 契約 §1：眉彩僅使用 browLab／hairLab 比色，絕不以膚色推薦眉彩色號。
    // 2026-08-23 實測：膚色從 L*85 換到 L*38，眉彩 colorScore 都是 0.8520 完全不變——
    // 證明後端**確實是用眉色比的、行為正確**，只是文案寫成「色調與您的膚色幾乎完美匹配」。
    // 做對了事、說錯了話。這句話原樣顯示出去，就是系統對使用者說了一句不實的話。
    //
    // 後端修好之前，前端在這裡把它導正。已回報：
    // 補充文件md檔案/給演算法端_個人化推薦實作差異與改善需求_2026-08-23.md A3
    _safeMatchReason(product) {
        const raw = String(product?.matchReason || '').trim();
        if (!raw) return '';
        const kind = String(product.type || product.coverageCategory || product.category || '');
        const isBrow = /brow/i.test(kind) || kind === '眉毛';
        // colorMethod === 'brow_color_unavailable' 時後端的降級文案本身是正確的
        // （「未以膚色比較眉彩色號」），那句話裡的「膚色」不能動，動了會變成反話。
        const method = product.colorMethod || product.color_method || '';
        if (isBrow && method !== 'brow_color_unavailable' && raw.includes('您的膚色')) {
            return raw.replace(/您的膚色/g, '您的眉色');
        }
        return raw;
    },

    // 商品圖不在我們家：來源是品牌官網（sdcdn.io 63%、za-cosmetics 19%、
    // yslbeauty 13%、laneige 5%）。它們給的是商品頁用的原圖，而清單卡片只顯示
    // 約 200px——2026-08-25 實測一頁 20 張共 5.2 MB、平均 262 KB 一張，
    // 其中 sdcdn.io 單張要 1.2 ~ 5.4 秒。
    //
    // 三個來源自己就支援縮圖參數，換掉即可（同一張 sdcdn.io 圖：
    // width=1080 是 233 KB、width=320 只有 23 KB）。za-cosmetics 是 IIS 靜態檔，
    // 沒有轉檔參數可用，只能原樣送出——它本來就是最快的一個（約 300ms）。
    //
    // 取 400 而不是 200：高解析度螢幕會用 2 倍像素去畫那個 200px 的格子，
    // 給 200 會糊掉。清單用縮圖，原圖留在 imgFull 給詳情頁放大用。
    _thumbUrl(raw, px = 400) {
        const value = String(raw || '').trim();
        // 相對路徑（本機 demo 圖）與 data: 進不了 URL()，也不需要縮圖。
        if (!value || !/^https?:\/\//i.test(value)) return value;
        let url;
        try {
            url = new URL(value);
        } catch {
            return value;
        }
        const host = url.hostname.toLowerCase();
        const set = (pairs) => { Object.entries(pairs).forEach(([k, v]) => url.searchParams.set(k, v)); };
        if (host === 'sdcdn.io' || host.endsWith('.sdcdn.io')) {
            set({ width: px, height: px });
        } else if (host.endsWith('laneige.com')) {
            // Magento 的 media cache：canvas 要跟著改，否則它會把小圖再貼回大畫布。
            set({ width: px, height: px, canvas: `${px}:${px}` });
        } else if (url.pathname.includes('/dw/image/')) {
            // Salesforce Commerce Cloud（YSL 等品牌都是這一套）用 sw/sh。
            set({ sw: px, sh: px });
        } else {
            return value;
        }
        return url.toString();
    },

    // 粉底相鄰色階（契約 2026-08-v2 §5）。
    //
    // 兩種模式的**措辭不能互換**，這是規格裡講得最重的一條：
    //   official_depth_index         品牌官方的由淺至深順序 → 可以說「淺一階／深一階」
    //   lab_lightness_approximation  只是 L* 比較出來的近似 → 只能說「較明亮／較深的替代色」
    //
    // 說錯的後果很具體：使用者以為那是品牌真的相鄰的色號，照著去買會買錯。
    // 所以標籤在這裡就依 method 決定，不讓畫面層自己拼——畫面層拼錯不會有人發現。
    _normalizeShadeRecommendation(raw) {
        if (!raw || typeof raw !== 'object') return null;
        const method = String(raw.method || '').trim();
        // method 與 label 都由推薦後端提供。缺少 method 時不能猜成官方色階，
        // 缺少 label 時也不在前端補一個看似正確的說法。
        const official = method === 'official_depth_index';
        // 契約 §5 送的是 matchScore（0–1），先前這裡只讀 matchPercent（0–100）。
        // 兩個都不接的話，後端做好之後畫面上仍然什麼都不會出現——這個專案
        // 已經踩過兩次同樣的「上一層補了、下一層漏掉」（labReliable、browLab）。
        //
        // 還要擋 null：Number(null) 是 0 而 isFinite(0) 為真，於是「沒有分數」
        // 會被畫成「0% MATCH」——那等於告訴使用者這個色號完全不合，
        // 比不顯示糟得多。所以先判 == null，再判是不是數字。
        const pickMatchPercent = (node) => {
            const asNum = (v) => (v == null || v === '' ? null
                : (Number.isFinite(Number(v)) ? Number(v) : null));
            const pct = asNum(node.matchPercent);
            if (pct != null) return pct;
            const score = asNum(node.matchScore ?? node.match_score);
            // 0–1 才乘 100。有些回傳已經是百分比，乘了會變 9500。
            return score == null ? null : (score <= 1 ? score * 100 : score);
        };
        const pick = (node) => {
            if (!node || typeof node !== 'object') return null;
            const product = node.product ? this._normalizeProduct(node.product) : null;
            return {
                // 顯示文案必須來自後端；前端不依 method 自行產生「淺一階」等字樣。
                label: node.label == null ? '' : String(node.label),
                shadeCode: node.shadeCode ?? node.shade_code
                    ?? product?.shadeCode ?? product?.shadeName ?? '',
                description: String(node.description || ''),
                matchPercent: pickMatchPercent(node),
                // 替代色與**主推薦色號**的色差（契約 2026-08-27 §3）。
                // 不能拿替代色自己的 foundationSkinMatch.deltaE 代替——那是它跟
                // **使用者膚色**的色差，比較對象完全不同。替代色的用途是
                // 「同系列裡明暗不同的選擇」，它本來就不必貼近使用者膚色。
                anchorDeltaE: (node.anchorDeltaE == null || node.anchorDeltaE === '')
                    ? null
                    : (Number.isFinite(Number(node.anchorDeltaE)) ? Number(node.anchorDeltaE) : null),
                product,
            };
        };
        return {
            method,
            official,
            seriesId: raw.seriesId ?? raw.series_id ?? null,
            anchor: pick(raw.anchor),
            lighter: pick(raw.lighter),
            darker: pick(raw.darker),
            disclaimer: String(raw.disclaimer || ''),
        };
    },

    _normalizeProduct(product) {
        if (!product || typeof product !== 'object') return null;
        const categoryMap = {
            base: '底妝',
            foundations: '底妝',
            foundation: '底妝',
            eye: '眼影',
            eyeshadow: '眼影',
            eyeshadows: '眼影',
            eyeliner: '眼線/睫毛',
            eyeliners: '眼線/睫毛',
            mascara: '眼線/睫毛',
            mascaras: '眼線/睫毛',
            eyeliner_mascara: '眼線/睫毛',
            lash: '眼線/睫毛',
            lip: '唇彩',
            lipstick: '唇彩',
            lipsticks: '唇彩',
            lipgloss: '唇彩',
            lipglosses: '唇彩',
            blush: '腮紅',
            blushes: '腮紅',
            brow: '眉毛彩妝',
            eyebrow: '眉毛彩妝',
            eyebrows: '眉毛彩妝',
            contour: '修容',
            contours: '修容',
            contouring: '修容',
            highlight: '打亮',
            highlighter: '打亮',
            highlighters: '打亮'
        };
        // 中文分類名 -> 英文 type slug。/api/product/{type}/{id} 與收藏同步的 item_type
        // 都只吃英文 slug，中文分類名只能拿來顯示與前台篩選。
        const catToSlug = {
            '底妝': 'foundations',
            '眼影': 'eyeshadows',
            '眼線/睫毛': 'eyeliner_mascara',
            '唇彩': 'lipsticks',
            '腮紅': 'blushes',
            '眉毛彩妝': 'eyebrows',
            '修容': 'contouring',
            '打亮': 'highlighters'
        };
        // type 是 API 使用的英文分類；category 是畫面顯示的中文分類。
        // 兩者分開處理，避免未知分類被誤設為底妝。
        const typeSlug = String(product.type || product.apiType || product.item_type || '').trim();
        const rawCategory = String(product.category || product.cat || '').trim();
        const tagCat = Array.isArray(product.tags) ? product.tags.find(tag => categoryMap[String(tag).trim()]) : '';
        // 伺服器給的 slug 原樣保留（不做單複數正規化）：它是拿回去打單品 API 的鍵，改了會打不到。
        const knownSlug = categoryMap[typeSlug] ? typeSlug : (categoryMap[rawCategory] ? rawCategory : '');
        const resolvedCat = categoryMap[knownSlug]
            || (catToSlug[rawCategory] ? rawCategory : '')
            || categoryMap[tagCat]
            || (catToSlug[String(product.cat || '').trim()] ? String(product.cat).trim() : '')
            || '';
        const rawCat = knownSlug || rawCategory || typeSlug;
        const cat = resolvedCat || '底妝';
        // 分類真的認出來了才給 apiType；認不出來時維持 null，不要拿 '底妝' fallback 反推出
        // 一個假的 'foundations' 送去收藏 API。
        const apiType = knownSlug || (resolvedCat ? catToSlug[resolvedCat] : '') || null;
        const price = product.price == null
            ? ''
            : (String(product.price).startsWith('NT$') ? String(product.price) : `NT$${product.price}`);
        const imageUrl = product.imageUrl || product.image_url || product.image_src
            || product.img || product.image || '';
        const matchPercentRaw = product.matchPercent ?? product.match_percent;
        const matchPercent = (matchPercentRaw == null || matchPercentRaw === ''
            || !Number.isFinite(Number(matchPercentRaw))) ? null : Number(matchPercentRaw);
        const recommendationLabel = String(
            product.recommendationLabel ?? product.recommendation_label ?? ''
        ).trim();
        // 色階推薦裡的 product 可能已經先被正規化過一次。若再次套用
        // api-{type}-{id} 會變成 api-foundations-api-foundations-123，
        // 詳情頁就無法用色階卡片的 id 找回這件商品，最後會退回商品清單。
        // 身分鍵必須在任何正規化路徑都保持穩定。
        const idPrefix = `api-${apiType || rawCat || cat}-`;
        const suppliedRawId = product.rawId ?? null;
        const suppliedId = product.id ?? null;
        const alreadyNormalized = suppliedRawId != null
            ? String(suppliedId) === `${idPrefix}${suppliedRawId}`
            : (typeof suppliedId === 'string' && suppliedId.startsWith(idPrefix));
        const rawId = suppliedRawId != null
            ? suppliedRawId
            : (alreadyNormalized ? suppliedId.slice(idPrefix.length) : suppliedId);
        const normalizedId = rawId != null
            ? `${idPrefix}${rawId}`
            : null;
        return {
            // 本機商品 id 固定使用 api-{item_type}-{item_id}，才能和遠端收藏互相對應。
            id: normalizedId || `api-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            rawId,
            // 這件粉底跟使用者膚色的色差與判定（契約 2026-08-27 §3）。
            // 主推薦一定是 accepted:true；替代色可能是 false，那是正常的——
            // 它走的是「與主推薦色號 ΔE ≤ 5」那條規則。
            foundationSkinMatch: (product.foundationSkinMatch
                && typeof product.foundationSkinMatch === 'object')
                ? product.foundationSkinMatch : null,
            // 粉底門檻／校正狀態由推薦後端決定。前端只保存這個狀態，
            // 不從 foundationSkinMatch 或商品色號自行重建 status。
            foundationMatchStatus: (product.foundationMatchStatus
                && typeof product.foundationMatchStatus === 'object')
                ? product.foundationMatchStatus : null,
            apiType, // 原始 type slug（例如 lipsticks），呼叫 /api/product/{type}/{id} 這類單品 API 要用
            cat,
            name: product.name || '推薦商品',
            brand: product.brand || '',
            price,
            // 保留契約欄位 imageUrl；舊版畫面使用 img/imgFull，兩者都留著避免
            // 正規化後三色階或推薦卡只剩圖片縮圖別名可用。
            imageUrl,
            // img 是清單／卡片用的縮圖，imgFull 是原圖（詳情頁放大才需要）。
            // 兩個都留著：只留縮圖會讓詳情頁變糊，只留原圖就是現在這個 5.2 MB。
            img: this._thumbUrl(imageUrl),
            imgFull: product.imageUrl || product.image_url || product.image_src
                || product.img || product.image || '',
            desc: this._safeMatchReason(product) || product.description || product.desc || '',
            matchReason: this._safeMatchReason(product),
            score: product.score ?? null,
            // 新推薦回應直接把這兩個欄位放在商品上；不能只保留舊的 score，
            // 否則腮紅／口紅的色號與推薦契合度會在正規化時消失。
            matchPercent,
            recommendationLabel,
            popularity: product.popularity ?? product.sales ?? product.views ?? product.reviews ?? product.favorite_count ?? product.score ?? 0,
            // 推薦端點的 productUrl 實際上是 sale_page_id slug（不是 http 網址），留下來讓前端能跟商品清單比對補圖
            salePageId: product.sale_page_id || product.salePageId
                || ((typeof product.productUrl === 'string' && product.productUrl && !/^https?:/i.test(product.productUrl)) ? product.productUrl : null),
            // sourceUrl 只接受 http(s) 網址，商品識別字串不能當成連結。
            sourceUrl: [product.sourceUrl, product.source_url, product.productUrl]
                .find(v => typeof v === 'string' && /^https?:\/\//i.test(v)) || '',
            // 商品主色欄位可能是 hex_primary 或舊版 hex，欄位名也可能是駝峰式。
            // 容忍沒有 '#' 前綴的裸 hex（如 "d4a373"）——資料庫實際回傳常是這種，
            // 少了這層寬鬆，詳情頁的色號色塊永遠拿到 null 而不顯示。
            hex: (() => {
                const raw = String(
                    product.hex ?? product.hex_primary ?? product.hexPrimary
                    ?? product.primary_hex ?? product.color_hex ?? product.colorHex ?? ''
                ).trim();
                if (!raw) return null;
                const withHash = raw.startsWith('#') ? raw : `#${raw}`;
                return /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(withHash)
                    ? withHash.toLowerCase()
                    : null;
            })(),
            // CIE L*a*b*，以色找色要用的就是它：ΔE 在這個空間才有感知意義。
            // color_vector / qdrant_vector_12d 是給向量資料庫檢索用的，前 3 維其實就是
            // hex 的正規化 RGB，後 9 維語意未公開，不拿來算相似度。
            lab: Array.isArray(product.lab) && product.lab.length === 3 && product.lab.every(n => Number.isFinite(Number(n)))
                ? product.lab.map(Number)
                : null,
            tags: product.tags || [],
            sku: product.sku || null,
            shadeName: product.shadeName || product.shade_name || null,
            // 同一支粉底的完整色號清單（契約 2026-08-28）。這正是色號比較區
            // 一直缺的那份資料——先前 seriesId 是 null，「同系列」永遠圈不出東西。
            //
            // 已由後端依 depthIndex 排好，前端**不要重排**：排序規則是
            // 「Lab L* 由大到小推導」，前端自己排一次遲早會跟後端不一致，
            // 而不一致的樣子是「同一支粉底在清單頁與詳情頁的色號順序不同」。
            shades: Array.isArray(product.shades) ? product.shades : [],
            shadeCount: Number.isFinite(Number(product.shadeCount))
                ? Number(product.shadeCount) : null,
            seriesId: product.seriesId ?? product.series_id ?? null,
            depthIndex: Number.isFinite(Number(product.depthIndex))
                ? Number(product.depthIndex) : null,
            // 這個色階順序是不是品牌官方的。false 代表由 Lab 亮度推導——
            // 文案必須寫「較明亮／較深的替代色」，不可寫「官方淺一階／深一階」。
            depthIndexOfficial: product.depthIndexOfficial === true,
            shadeOrderSource: product.shadeOrderSource || null,
            // 色號代碼。先前只留 shadeName，而卡片要顯示的是這個——
            // 沒有它的話色號只存在於商品名稱字串裡（「…SPF 48/ PA++ - PO-02」），
            // 使用者得自己從一長串名稱的尾巴去找。
            shadeCode: product.shadeCode || product.shade_code || product.shadeName
                || product.shade_name || null,
            imageUrls: Array.isArray(product.imageUrls) ? product.imageUrls : [],
            status: product.status || 'active',
            reviewStatus: product.reviewStatus ?? product.review_status ?? null,
            inStock: product.inStock ?? product.in_stock ?? true,
            recommendationReady: (product.recommendationReady ?? product.recommendation_ready) == null
                ? null
                : !!(product.recommendationReady ?? product.recommendation_ready),
            dataQualityScore: (product.dataQualityScore ?? product.data_quality_score) == null
                ? null
                : Number(product.dataQualityScore ?? product.data_quality_score),
            version: Number(product.version || 1),
            currency: product.currency || 'TWD',
            styleTags: product.styleTags || product.style_tags || [],
            finishTags: product.finishTags || product.finish_tags || [],
            seasonTags: product.seasonTags || product.season_tags || [],
            occasionTags: product.occasionTags || product.occasion_tags || [],
            featureTags: product.featureTags || product.feature_tags || [],
            avoidTags: product.avoidTags || product.avoid_tags || [],
            coverage: product.coverage || null,
            undertone: product.undertone || null,
            texture: product.texture || null,
            // 新版推薦契約把色階與跨品牌結果綁在每一件商品上。這裡只正規化後端
            // 已回傳的物件，不從一般商品目錄或其他商品補資料。
            shadeRecommendation: product.shadeRecommendation
                ? this._normalizeShadeRecommendation(product.shadeRecommendation) : null,
            foundationCrossBrand: product.foundationCrossBrand
                ? this._normalizeFoundationCrossBrand(product.foundationCrossBrand) : null,

            // ── 推薦依據 ────────────────────────────────────────────────
            // 2026-08-23 補。這些欄位後端一直都有回，但先前在這裡就被丟掉了，
            // 於是畫面上只剩一行 matchReason，使用者看不到「為什麼推薦給我」。
            // 契約與設計文件 §19.10 要求的「查看推薦依據」需要的就是這些。
            // 推薦端整理好的使用者文案（契約 2026-08-v2 §4.3）。
            //
            // 這一包**優先於**前端自己拼的說明：技術分數（matchScore、scoreBreakdown、
            // ΔE）不該由前端翻譯成人話——同一個數字前後端各講一套，使用者看到的
            // 就會是兩種說法。後端已經決定好措辭，前端照著顯示。
            recommendationPresentation: (product.recommendationPresentation
                && typeof product.recommendationPresentation === 'object')
                ? product.recommendationPresentation : null,
            // 後端說這件不該顯示匹配度（契約 2026-08-27 §5）。
            // closest_available 的粉底就是這種：它會出現在清單上，但它**沒有通過**
            // 膚色門檻，印一個 MATCH 百分比等於幫它背書。
            // 只有明確寫 false 才當作要隱藏——欄位不存在的商品維持原本行為。
            showMatchPercent: (product.recommendationPresentation
                && product.recommendationPresentation.showMatchPercent === false) ? false : true,
            matchScore: Number.isFinite(Number(product.matchScore ?? product.score))
                ? Number(product.matchScore ?? product.score) : null,
            matchReasons: Array.isArray(product.matchReasons)
                ? product.matchReasons.filter(reason => reason && typeof reason === 'object')
                    .map(reason => ({
                        code: String(reason.code || '').trim(),
                        priority: Number.isFinite(Number(reason.priority)) ? Number(reason.priority) : null,
                        text: String(reason.text || '').trim(),
                        source: String(reason.source || '').trim(),
                        evidence: reason.evidence && typeof reason.evidence === 'object' ? reason.evidence : null,
                    }))
                    .filter(reason => reason.text)
                : [],
            scoreBreakdown: (product.scoreBreakdown && typeof product.scoreBreakdown === 'object')
                ? product.scoreBreakdown : null,
            matchedKeywords: Array.isArray(product.matchedKeywords) ? product.matchedKeywords
                : (Array.isArray(product.keywordMatches) ? product.keywordMatches : []),
            // 哪一種色差算法算出來的。眉彩在缺色資料時會是 brow_color_unavailable，
            // 那是判斷「這件商品的色彩分數能不能拿來說嘴」的依據。
            colorMethod: product.colorMethod || product.color_method || null,

            source: 'product-api'
        };
    },

    _normalizeFoundationCrossBrand(raw) {
        if (!raw || typeof raw !== 'object') return null;
        const rawItems = Array.isArray(raw.items) ? raw.items
            : (Array.isArray(raw.alternatives) ? raw.alternatives : []);
        return {
            status: String(raw.status || '').trim(),
            anchorCandidateKey: String(raw.anchorCandidateKey || raw.anchor_candidate_key || '').trim(),
            availableTargetBrands: Array.isArray(raw.availableTargetBrands)
                ? [...new Set(raw.availableTargetBrands.map(brand => String(brand ?? '').trim()).filter(Boolean))]
                : [],
            items: rawItems.map(item => {
                if (!item || typeof item !== 'object' || !item.product || typeof item.product !== 'object') return null;
                const product = this._normalizeProduct(item.product);
                if (!product) return null;
                const deltaRaw = item.anchorDeltaE ?? item.anchor_delta_e;
                return {
                    brand: String(item.brand || '').trim(),
                    shadeCode: String(item.shadeCode ?? item.shade_code ?? '').trim(),
                    anchorDeltaE: (deltaRaw == null || deltaRaw === ''
                        || !Number.isFinite(Number(deltaRaw))) ? null : Number(deltaRaw),
                    reason: String(item.reason || '').trim(),
                    product,
                };
            }).filter(item => item && item.brand && item.shadeCode),
            noResultReason: String(raw.noResultReason || raw.no_result_reason || '').trim(),
        };
    },

    // 個人化推薦：依賴組員資料庫的登入 session，登入狀態不確定時優雅地回傳空陣列，不影響其他功能。
    // 這條路由(api/recommend/personal)在 Gateway 是掛在 member-database 上游、需要會員 session；
    // 先前誤用 product.baseUrl 會打到 /product-api/，那邊只放行 api/products 與 recommend-products，
    // 於是永遠回 404、「猜你喜歡」整塊空白。改回 member-database 才打得到。
    async getPersonalRecommendations() {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl) return [];
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/recommend/personal`, { credentials: 'include', cache: 'no-store' });
            if (!res.ok) return [];
            const data = await res.json();
            if (!data?.success || !Array.isArray(data.recommendations)) return [];
            return data.recommendations.map(rec => ({
                ...this._normalizeProduct({
                    id: rec.id, type: rec.type, name: rec.name, brand: rec.brand,
                    price: rec.price, image_url: rec.image_url, description: rec.desc, hex: rec.hex
                }),
                similarity: rec.similarity ?? null
            })).filter(Boolean);
        } catch (_) {
            return [];
        }
    },

    // 收藏屬於會員資料，因此經 member-database 同步；失敗時保留本機收藏。
    async toggleRemoteFavorite(itemId, itemType) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl) return null;
        // 收藏是背景同步，呼叫端不看回傳值；擋下或失敗都一律 null，維持既有契約。
        const result = await this._protectedWrite(this._writeActorEmail(), async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/favorites/toggle`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ item_id: itemId, item_type: itemType })
                });
                if (!res.ok) return null;
                return res.json();
            } catch (_) {
                return null;
            }
        });
        return result?.blocked ? null : result;
    },

    // 商品管理端點使用登入憑證，由後端確認 role=admin。
    _adminProductHeaders(headers = {}) {
        return this._memberHeaders(headers);
    },
    _productApiError(data, status) {
        const error = data?.detail?.error || data?.error || {};
        // `field` 與 `allowed` 是 2026-08-26 商品後端新增的：錯誤直接指出是哪一個
        // 欄位不合格、合法值有哪些。帶著它們，管理員自己就能修；只說「分類無效」
        // 的錯誤，每一次都要回頭找工程師——我方就為了那一句話查了半天。
        const field = typeof error.field === 'string' ? error.field
            : (typeof error.details?.field === 'string' ? error.details.field : '');
        const allowed = Array.isArray(error.allowed) ? error.allowed
            : (Array.isArray(error.details?.allowed) ? error.details.allowed : []);
        // MISSING_FIELDS 會把缺的欄位放在 details.fields（契約 2026-08-28 §7）。
        // 不讀出來的話畫面上只有一句「資料庫寫入失敗」，管理員得逐欄猜。
        // 新版對 offset 回 400 OFFSET_NOT_SUPPORTED（契約 2026-08-28 §3）。
        // 前端本來就只用 cursor，這裡認出來是為了萬一有人加了 offset，
        // 錯誤訊息要直接指出原因，而不是一句 HTTP 400。
        // Gateway 已經確認過管理員 session，是**上游**不接受這次操作
        //（多半是 PRODUCT_DATABASE_URL 指錯服務）。這一句要壓過任何
        // 「請重新登入」的預設文案——使用者才剛登入，重登不會好。
        if (String(error.code || '') === 'PRODUCT_UPSTREAM_REJECTED') {
            return { error: error.message || '商品服務不接受這次管理操作（你的登入是有效的）',
                     status, code: error.code };
        }
        if (String(error.code || '') === 'OFFSET_NOT_SUPPORTED') {
            return { error: 'offset 分頁不支援，請改用 nextCursor', status, code: error.code };
        }
        const missing = Array.isArray(error.details?.fields) ? error.details.fields
            : (Array.isArray(error.fields) ? error.fields : []);
        const base = (error.message || data?.message || `HTTP ${status}`)
            + (missing.length ? `（缺少：${missing.join('、')}）` : '');
        return {
            status,
            code: error.code || `HTTP_${status}`,
            // 合法值直接接在訊息後面。使用者看到的是完整的一句話，
            // 不必再點開什麼才知道該填什麼。
            error: allowed.length ? `${base}：${allowed.join('、')}` : base,
            field,
            allowed,
            details: error.details || {},
            retryable: !!error.retryable
        };
    },

    // 目前這一版商品服務支不支援伺服器端篩選。第一次 listProducts 回來才知道，
    // 在那之前保守當成不支援——本機篩在兩版上都會給出正確結果，只是多算一點；
    // 反過來假設支援，在舊版上會顯示一個「有篩選器但沒篩到」的清單。
    productServerFiltering: false,

    // 主推薦粉底切換品牌時，向同一個 Product Gateway 取該品牌前五個近似色號。
    // productId 優先使用 rawId；前端自己的 api-foundations-* id 不能直接送給後端。
    async listFoundationShadeMatches(productId, targetBrand, limit = 5) {
        const base = this.config.url('product', 'listPath');
        const rawId = String(productId ?? '').trim();
        const brand = String(targetBrand ?? '').trim();
        if (!base || !rawId || !brand) return { ok: false, items: [] };
        const safeLimit = Math.min(5, Math.max(1, Math.trunc(Number(limit) || 5)));
        const query = new URLSearchParams({ targetBrand: brand, limit: String(safeLimit) });
        try {
            const res = await fetch(
                `${base}/${encodeURIComponent(rawId)}/shade-matches?${query}`,
                { cache: 'no-store' }
            );
            if (!res.ok) return { ok: false, status: res.status, items: [] };
            const data = await res.json();
            const items = Array.isArray(data.items) ? data.items : [];
            return {
                ok: true,
                ...data,
                items: items.map(item => {
                    if (!item || typeof item !== 'object') return null;
                    // 新端點把商品資料放在 item.product，舊端點則直接放在 item；
                    // 合併後交給同一個商品正規化器，兩種回應都能畫。
                    const rawProduct = item.product && typeof item.product === 'object'
                        ? { ...item, ...item.product } : item;
                    const product = this._normalizeProduct(rawProduct);
                    if (!product) return null;
                    const deltaRaw = item.shadeMatch?.deltaE
                        ?? item.shade_match?.deltaE
                        ?? item.anchorDeltaE ?? item.anchor_delta_e;
                    return {
                        brand: String(item.brand || product.brand || '').trim(),
                        shadeCode: String(item.shadeCode ?? item.shade_code
                            ?? product.shadeCode ?? product.shadeName ?? '').trim(),
                        anchorDeltaE: (deltaRaw == null || deltaRaw === ''
                            || !Number.isFinite(Number(deltaRaw))) ? null : Number(deltaRaw),
                        product,
                    };
                }).filter(item => item && item.brand),
            };
        } catch (_) {
            return { ok: false, items: [] };
        }
    },

    async listProducts(params = {}) {
        const url = this.config.url('product', 'listPath');
        if (!url) return { ok: false, products: [] };
        try {
            const query = new URLSearchParams();
            Object.entries(params || {}).forEach(([key, value]) => {
                if (value !== '' && value != null) query.set(key, String(value));
            });
            const res = await fetch(`${url}${query.size ? `?${query}` : ''}`, { cache: 'no-store' });
            if (!res.ok) return { ok: false, status: res.status, products: [] };
            const data = await res.json();
            const list = Array.isArray(data.items) ? data.items : (Array.isArray(data.products) ? data.products : []);
            // 這一版的商品服務支不支援伺服器端篩選，用回應自己說的來判斷。
            //
            // 契約 2026-08-28 的新版會回 `appliedFilters` 與 `facets`；舊版兩個都沒有，
            // 而且對 minPrice/sort 是**靜默忽略**——送了不報錯也沒效果。
            // 寫死「用 API 篩」會在舊版上得到一個沒篩到的畫面；寫死「本機篩」則會在
            // 新版上白白把整份清單抓下來。讓回應自己回答，兩版都對。
            //
            // 記在 Api 上而不是回傳值裡：呼叫端要在**送出請求前**就知道能不能交給後端。
            const serverFiltering = !!(data.appliedFilters || data.facets);
            if (serverFiltering !== this.productServerFiltering) {
                this.productServerFiltering = serverFiltering;
            }
            return {
                ok: true,
                ...data,
                serverFiltering,
                facets: data.facets || null,
                appliedFilters: data.appliedFilters || null,
                products: list.map(item => this._normalizeProduct(item)).filter(Boolean),
                total: Number(data.total ?? list.length),
                nextCursor: data.nextCursor ?? null
            };
        } catch (_) {
            return { ok: false, products: [] };
        }
    },

    // ═══ 後台管理：members 讀寫都走 Gateway 的 HttpOnly cookie ═══
    _memberTokenKey: 'memberAccessToken',
    _getMemberAccessToken() {
        return '';
    },
    _rememberMemberAccessToken() {
        try { sessionStorage.removeItem(this._memberTokenKey); } catch (_) {}
    },
    _memberHeaders(headers = {}) {
        return headers;
    },

    // 舊版 token 欄位只保留介面相容性；正式站只使用 HttpOnly cookie，JavaScript 不保存 token。
    _gatewayTokenKey: 'gatewaySessionToken',
    _getGatewaySessionToken() {
        return '';
    },
    _rememberGatewaySessionToken() {
        try { sessionStorage.removeItem(this._gatewayTokenKey); } catch (_) {}
    },

    // 用會員帳密向 Gateway 登入；帳密只送一次，成功後由 HttpOnly cookie 維持會員與 AI session。
    async loginToGateway(email, password) {
        // 同源時 baseUrl 是空字串，直接串接會得到 /auth/login；不能用 config.url()，
        // 它在 baseUrl 為空時會回空字串。
        const gateway = this.config.services.aiGateway;
        const url = `${gateway.baseUrl}${gateway.loginPath}`;
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email, password })
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const detail = data?.detail?.error || data?.error || null;
                const code = detail?.code || `HTTP_${res.status}`;
                const message = detail?.message || '帳號或密碼錯誤';
                return {
                    ok: false,
                    status: res.status,
                    code,
                    // 把整個 error 物件帶進去，被限流時才顯示得出「請在 N 分鐘後再試」。
                    error: localizeUserError(message, code, res.status, detail)
                };
            }
            this._sessionExpiredNotified = false;
            this._resetSessionRequests();
            // 登入回應後立刻由 /auth/session 再確認一次，避免只相信登入 JSON，並把
            // 不含 email 的 actorId 綁在「這一個分頁」的 sessionStorage。
            const session = await this.validateSession();
            const expectedSub = String((data.member && data.member.email) || email || '').trim().toLowerCase();
            if (!session.ok || !session.sub || !session.actorId
                || String(session.sub).trim().toLowerCase() !== expectedSub
                || !this._pinSession(session)) {
                this._clearPinnedSession();
                fetch(`${gateway.baseUrl}${gateway.logoutPath}`, { method: 'POST', credentials: 'include' }).catch(() => null);
                return {
                    ok: false,
                    status: session.status || 409,
                    code: 'SESSION_OWNER_CHANGED',
                    error: '登入身分確認失敗，請重新登入後再試。'
                };
            }
            // 通知其他分頁：這個瀏覽器的登入身分換人了。它們共用同一份 cookie，
            // 不講的話要等到下一次 403 才會發現，而那時可能已經帶著別人的憑證寫過東西。
            try {
                if (typeof BroadcastChannel === 'function') {
                    const channel = new BroadcastChannel('decorate-me-auth');
                    channel.postMessage({ type: 'owner-changed', sub: session.sub });
                    channel.close();
                }
            } catch (_) {}
            return { ok: true, member: data.member || null, expiresAt: data.expiresAt || null, actorId: session.actorId };
        } catch (err) {
            return { ok: false, code: 'NETWORK_ERROR', error: err.message };
        }
    },

    async validateSession() {
        const gateway = this.config.services.aiGateway;
        const controller = typeof AbortController === 'function' ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(), 5000) : null;
        try {
            const res = await fetch(`${gateway.baseUrl}${gateway.sessionPath}`, {
                credentials: 'include',
                cache: 'no-store',
                signal: controller?.signal
            });
            // 帶回 error.code：呼叫端要靠它分辨「該重新登入」與「這個帳號在上游查無此人」。
            // 兩者都是 401，但只有前者重登會好——少了這個碼，SessionWatch 只能看狀態碼，
            // 於是把後者也當成過期，每 90 秒把管理員踢出去一次（2026-08-29）。
            if (!res.ok) {
                const failure = await res.json().catch(() => ({}));
                return { ok: false, status: res.status, code: String(failure?.error?.code || '') };
            }
            // sub 是這個 session 屬於誰。呼叫端要拿它跟本機 profile 比對——admin 與 member
            // 共用同一個 __session cookie，少了這道比對就會拿舊帳號的 email 去打會員 API。
            const data = await res.json().catch(() => ({}));
            this._sessionExpiredNotified = false;
            return {
                ok: true,
                sub: String(data.sub || ''),
                actorId: String(data.actorId || ''),
                role: String(data.role || ''),
                accountStatus: String(data.status || '')
            };
        } catch (err) {
            return { ok: false, status: 0, networkFailure: true, error: err.message };
        } finally {
            if (timer) clearTimeout(timer);
        }
    },

    // 保留 wrapper 名稱相容既有呼叫點；所有會員請求使用同源 HttpOnly cookie。
    // 同一份唯讀資料在同一瞬間被要第二次時，共用第一次的結果。
    //
    // 會員中心進頁時 `getMemberPoints` 被呼叫兩次：一次填「會員點數」那格的餘額，
    // 一次畫點數明細。而同一個回應裡 `balance` 與 `transactions` 都有——
    // 兩次請求拿的是同一包資料，第二次純粹是浪費，在 Cloud Run 記錄裡看起來
    // 也像我們在重複打人家的服務。
    //
    // 只合併**進行中**的請求，不做快取：拿到結果就把 key 清掉，
    // 下一次呼叫仍然會真的去要一次新的。快取會讓「按重新整理沒有變新」，
    // 那是另一種更難查的問題。
    //
    // 只用在唯讀的 GET。寫入不能合併——兩次寫入是兩個意圖。
    _inflight: new Map(),
    _dedupe(key, run) {
        const hit = this._inflight.get(key);
        if (hit) return hit;
        const task = Promise.resolve()
            .then(run)
            .finally(() => { this._inflight.delete(key); });
        this._inflight.set(key, task);
        return task;
    },

    async _fetchWithRelogin(input, init) {
        if (!this._sessionAbortController) this._resetSessionRequests();
        const nextInit = {
            ...(init || {}),
            credentials: 'include',
            headers: this._memberHeaders(init?.headers || {}),
            signal: this._sessionSignal(init?.signal)
        };
        const res = await this._protectedFetch(input, nextInit);
        // 多個會員／管理員區塊會平行載入。Session 過期時只通知一次，
        // 由 Router 統一清除舊畫面與自動刷新，避免同一秒產生大量 401 與重複彈窗。
        if (res.status === 401) return res;
        // 403 有可能是「session 已經換成另一個帳號」。admin 與 member 共用同一個
        // __session cookie，在後台登入會蓋掉會員的 session，而本機 profile 還停在
        // 前一個人，於是每一條會員請求都在跨帳號要資料，資料庫一律回 403。
        //
        // 啟動時已經比對過一次身分，但那只擋得住「開新頁面」；中途在同一個分頁登入
        // 另一個帳號不會重新載入，所以要在這裡補一道。不擋住回應——呼叫端照樣拿到
        // 403 自行處理，這裡只負責在背景確認並通知 Router。
        if (res.status === 403 && !this._sessionExpiredNotified) {
            this._verifySessionOwner();
        }
        return res;
    },

    // 背景確認目前 session 屬於誰，跟本機 profile 不一致就通知 Router 清掉舊身分。
    // 同一時間只跑一次：多個區塊平行載入會同時吃到 403，不必每一條都去問一次。
    async _verifySessionOwner() {
        if (this._sessionOwnerChecking) return;
        this._sessionOwnerChecking = true;
        try {
            const session = await this.validateSession();
            if (!session.ok || !session.sub || !session.actorId) {
                // 上游查無此帳號時**不要**登出：重新登入會拿到一模一樣的結果。
                //
                // 這就是 2026-08-29 管理員被反覆踢出去的那條路徑：某個請求回 403
                // 觸發這裡 → 打 /auth/session → Gateway 拿 sub 去上游查
                // `admin@decoratme.local`（Gateway 端的內建管理員，`.local` 假網域）
                // → 上游 404 → 這裡判定 session 失效 → 跳「登入已過期」回登入頁。
                // 使用者重登、再被踢，而畫面從頭到尾沒說過真正的原因。
                //
                // 留在原地，讓呼叫端顯示那個帳號不存在的訊息；能修這件事的是
                // 資料庫端建帳號，不是使用者再登入一次。
                if (session.code === 'MEMBER_NOT_PROVISIONED') return;
                this._notifySessionInvalid('decorate-me:session-expired');
                return;
            }
            const profile = (typeof Auth !== 'undefined' && Auth.getProfile) ? (Auth.getProfile() || {}) : {};
            const email = String(profile.email || '').trim().toLowerCase();
            const pinnedActor = this._pinnedActor();
            const pinnedSubject = this._pinnedSubject();
            if (email && pinnedActor && pinnedSubject
                && session.sub.trim().toLowerCase() === email
                && session.sub.trim().toLowerCase() === pinnedSubject
                && session.actorId === pinnedActor) return;
            this._notifySessionInvalid('decorate-me:session-owner-changed', {
                sub: session.sub, role: session.role, accountStatus: session.accountStatus
            });
        } catch (_) {
            this._notifySessionInvalid('decorate-me:session-expired');
        } finally {
            this._sessionOwnerChecking = false;
        }
    },

    async fetchAdminMembers() {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl) return { ok: false, error: 'memberDatabaseUrl 未設定' };
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        const timeout = controller ? setTimeout(() => controller.abort(), 12000) : null;
        const opts = { credentials: 'include', cache: 'no-store', ...(controller ? { signal: controller.signal } : {}) };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members`, opts);
            if (timeout) clearTimeout(timeout);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                return {
                    ok: false,
                    status: res.status,
                    error: data?.error?.message
                        || data?.detail?.error?.message
                        || data?.detail?.message
                        || data?.message
                        || `HTTP ${res.status}`
                };
            }
            return {
                ok: true,
                members: Array.isArray(data.members) ? data.members : []
            };
        } catch (err) {
            if (timeout) clearTimeout(timeout);
            if (err?.name === 'AbortError') {
                return {
                    ok: false,
                    error: '讀取會員資料逾時（12 秒）。請確認資料庫 tunnel、CORS 與 admin session 是否正常。'
                };
            }
            return {
                ok: false,
                error: '連線失敗：' + err.message
            };
        }
    },

    // 寫入前確認 cookie 裡的身分就是這個分頁以為的那個人。
    //
    // 被動偵測（收到 403 才查）永遠慢一步：第一個寫入請求已經帶著別人的憑證送出去了。
    // 收藏、刪除、扣點這類會改變資料的動作，必須在送出之前先問清楚，
    // 否則一次誤寫就寫進別人的帳號，事後無法分辨也無法回復。
    //
    // 讀取不套這個檢查——多一次往返換不到等值的保護，讀錯了頂多顯示錯誤，
    // 而那個情況本來就會被 403 偵測接住。
    async assertSessionOwner(email) {
        const expected = String(email || '').trim().toLowerCase();
        if (!expected) return { ok: false, reason: 'NO_LOCAL_IDENTITY' };
        const pinnedActor = this._pinnedActor();
        const pinnedSubject = this._pinnedSubject();
        if (!pinnedActor || !pinnedSubject || pinnedSubject !== expected) {
            return { ok: false, reason: 'SESSION_UNAVAILABLE' };
        }
        const session = await this.validateSession();
        if (!session.ok) {
            // 401 = 伺服器明確說這個 cookie 不算數，也就是登入過期。
            // 其他狀況（逾時、網路失敗）才是「稍後再試」。
            return { ok: false, status: session.status,
                     reason: session.status === 401 ? 'SESSION_EXPIRED' : 'SESSION_UNAVAILABLE' };
        }
        if (!session.sub || !session.actorId) return { ok: false, reason: 'SESSION_UNAVAILABLE', status: session.status };
        if (String(session.sub).trim().toLowerCase() !== expected || session.actorId !== pinnedActor) {
            this._cancelSessionRequests();
            window.dispatchEvent(new CustomEvent('decorate-me:session-owner-changed', {
                detail: { sub: session.sub, role: session.role }
            }));
            return { ok: false, reason: 'OWNER_MISMATCH', sub: session.sub };
        }
        return { ok: true };
    },

    // 所有寫入都先確認 cookie 與目前分頁身分一致，再由統一入口送出。
    // actor 是執行寫入的人，不一定是被操作的會員：
    //   · 會員動自己的資料（簽到、兌換、收藏）—— actor 就是那個 email；
    //   · 後台動別人的資料（停權、刪除）—— actor 是目前登入的管理員，傳 null
    //     由這裡取本機 profile；拿被操作的會員 email 去比對只會把正常的後台操作全擋掉。
    _writeActorEmail() {
        const profile = (typeof Auth !== 'undefined' && Auth.getProfile) ? (Auth.getProfile() || {}) : {};
        return String(profile.email || '').trim().toLowerCase();
    },

    // 擋下時回傳統一形狀：ok:false + blocked:true + 可直接顯示的中文 error。
    // 呼叫端本來就在看 result.ok / result.error，不必為了這道防線多寫分支。
    // 批次寫入時，呼叫端可以先自己驗一次再把 skipAssert 打開。
    //
    // 為什麼需要這個開關：每一次 assertSessionOwner 都會打 /auth/session，
    // 而那條路徑在 gateway 端會去會員資料庫做一次 profile 讀取，**並且重寫
    // session cookie**。存九筆會員權限就是九次驗證、九次 cookie 輪替，
    // 夾在九次 PATCH 中間——cookie 在批次跑到一半被換掉，後面幾筆就拿著
    // 舊的那份，於是「前兩筆成功、後七筆 401」。2026-08-27 實際發生過。
    //
    // 少驗幾次不等於少了保護：批次開始前才剛驗過，而整個迴圈只有幾秒。
    // 真正的保護是「開始之前確認過身分」，不是「每一筆都重新確認」。
    _batchGuard: null,
    async _protectedWrite(actorEmail, run, opts) {
        if (opts && opts.skipAssert) return run();
        const actor = String(actorEmail || '').trim().toLowerCase() || this._writeActorEmail();
        const owner = await this.assertSessionOwner(actor);
        if (owner.ok) return run();
        return {
            ok: false,
            blocked: true,
            reason: owner.reason,
            status: owner.status || 0,
            error: WRITE_BLOCKED_ZH[owner.reason] || WRITE_BLOCKED_ZH.DEFAULT
        };
    },

    // 讀回伺服器上的收藏清單。收藏的寫入（toggleRemoteFavorite）一直都在，
    // 但從來沒有人讀回來，所以換一台裝置登入就看不到自己收藏過的東西——
    // 「跨裝置同步」只做了寫的那一半。
    async listRemoteFavorites(email) {
        return this._dedupe(`favorites:${email}`, () => this.__listRemoteFavorites(email));
    },
    async __listRemoteFavorites(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false, favorites: [] };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/favorites`, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store'
            });
            if (!res.ok) return { ok: false, status: res.status, favorites: [] };
            const data = await res.json().catch(() => ({}));
            const favorites = Array.isArray(data.favorites) ? data.favorites : [];
            // 商品硬刪除之後，收藏那一列還在但商品沒了。資料庫端會把那種標成
            // unavailable（見 docs/對外規格書/資料庫端/
            // 給資料庫端_收藏與購物車標記已下架商品_2026-08-26.md）。
            //
            // **這個判斷只能由後端做。** 前端「查不到商品」有三種原因長得一模一樣：
            // 商品被刪、商品清單還沒載完、商品清單某一頁抓失敗。前端自己猜的話，
            // 只要有一頁沒抓到就會對使用者說「此商品已下架」——而商品好好的。
            //
            // 後端還沒上線這個欄位時，這裡會是空集合，畫面維持原本的行為。
            Fav.setUnavailable(favorites
                .filter(row => row && row.unavailable === true)
                .map(row => `api-${String(row.item_type ?? row.itemType ?? '').trim()}-${row.item_id ?? row.itemId}`));
            return { ok: true, favorites };
        } catch (_) {
            return { ok: false, favorites: [] };
        }
    },

    // 伺服器端購物車：跨裝置同步用，做法與收藏（listRemoteFavorites / toggleRemoteFavorite）
    // 完全一致，靠會員資料庫的登入 session；任何失敗都不影響本機 Cart。
    // GET /api/members/{email}/cart → { items: [ { id, qty } ] }
    async getRemoteCart(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false, items: [] };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/cart`, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store'
            });
            if (!res.ok) return { ok: false, status: res.status, items: [] };
            const data = await res.json().catch(() => ({}));
            // 契約（2026-08-26）回應同時有 `items` 與舊的 `cart`，內容一樣。
            // 兩個都認得：只讀其中一個的話，換成另一種格式的服務就整車不見。
            const rows = Array.isArray(data.items) ? data.items
                : (Array.isArray(data.cart) ? data.cart : []);
            return {
                ok: true,
                items: rows.map(row => ({
                    ...row,
                    // 商品被硬刪除之後，購物車那一列還在但商品沒了。
                    // **只信任 API 這個欄位**——前端自己「查不到商品」有三種原因
                    //（已刪除／清單沒載完／某一頁抓失敗），猜錯就是對使用者說謊。
                    unavailable: row?.unavailable === true,
                })),
            };
        } catch (_) {
            return { ok: false, items: [] };
        }
    },

    // 把整台購物車覆蓋寫回伺服器（PUT，last-write-wins）。走 _protectedWrite 沿用
    // 換帳號防線：分頁身分對不上就擋下，不會把 A 的車寫到 B 帳號。背景同步，呼叫端不看回傳。
    //
    // 動詞是 PUT 不是 POST：資料庫端這條路由只接受 PUT，送 POST 會回 405
    // METHOD_NOT_ALLOWED（2026-08-13 實測：PUT 回 401 需登入＝路由存在，POST 回 405）。
    // 整台車覆蓋本來就是冪等的，PUT 也是比較正確的語意。
    async saveRemoteCart(items) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        const email = this._writeActorEmail();
        if (!baseUrl || !email) return null;
        // 上游還沒實作這個寫入端點（回 405/501）。第一次撞到就記下來，之後整個
        // 分頁生命週期都不再送——否則每次加減數量、每次登入都會再打一次，
        // console 一整排紅字，看起來像壞掉，其實本機購物車一直是好的。
        if (this._cartPushUnsupported) return null;
        const payload = (Array.isArray(items) ? items : [])
            .map(it => ({ id: String(it.id), qty: Math.max(1, parseInt(it.qty, 10) || 1) }))
            .filter(it => it.id);
        const result = await this._protectedWrite(email, async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/cart`, {
                    method: 'PUT',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items: payload })
                });
                if (res.status === 405 || res.status === 501) { this._cartPushUnsupported = true; return null; }
                if (!res.ok) return null;
                return res.json().catch(() => ({}));
            } catch (_) {
                return null;
            }
        });
        return result?.blocked ? null : result;
    },

    // 讀單一會員。身分切換時用它把本機 profile 換成 session 真正屬於的那個人，
    // 不必把使用者登出重來。
    async fetchMember(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}`, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store'
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, status: res.status };
            return { ok: true, member: data.member || data || null };
        } catch (_) {
            return { ok: false };
        }
    },

    async patchMember(email, patch, opts) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl) return { ok: false, error: 'memberDatabaseUrl 未設定' };
        // actor 是操作的人（後台是管理員），不是 email 這個被改的對象——傳 null 取本機 profile。
        return this._protectedWrite(null, async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}`, {
                    method: 'PATCH',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(patch)
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) return { ok: false, status: res.status, error: data?.error?.message || `HTTP ${res.status}` };
                return { ok: true, member: data.member || null };
            } catch (err) {
                return { ok: false, error: '連線失敗：' + err.message };
            }
        }, opts);
    },

    // 刪帳號前先清掉臉部與渲染服務裡的影像。
    //
    // 那兩個服務認的是 opaque ownerId，由 Gateway 用 SESSION_SECRET 從 email 推導，
    // 會員資料庫端算不出來也拿不到那把金鑰——所以它刪會員時清不掉那些圖。
    // 這條要在 deleteMember 之前呼叫：帳號一旦刪掉，就再也對應不回那些影像，
    // 它們會變成刪不掉的孤兒資料。
    async purgeMemberMedia(email) {
        if (!email) return { ok: false, error: 'email 未提供' };
        try {
            const res = await this._protectedFetch(
                `${gatewayService('admin-api')}/members/${encodeURIComponent(email)}/media`,
                { method: 'DELETE', credentials: 'include' }
            );
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                return { ok: false, status: res.status,
                         error: data?.error?.message || `HTTP ${res.status}` };
            }
            return { ok: true, removed: data.removed || {} };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async deleteMember(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false, error: 'memberDatabaseUrl 或 email 未設定' };
        return this._protectedWrite(null, async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}`, {
                    method: 'DELETE',
                    credentials: 'include'
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    return { ok: false, status: res.status, error: data?.error?.message || data?.message || `HTTP ${res.status}` };
                }
                return { ok: true, member: data.member || null };
            } catch (err) {
                return { ok: false, error: '連線失敗：' + err.message };
            }
        });
    },

    // 會員點數：GET /api/members/{email}/points → { balance, lifetime, transactions[] }。
    async getMemberPoints(email) {
        return this._dedupe(`points:${email}`, () => this.__getMemberPoints(email));
    },
    async __getMemberPoints(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false, balance: null };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/points`, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store'
            });
            if (!res.ok) return { ok: false, status: res.status, balance: null };
            const data = await res.json().catch(() => ({}));
            const txns = Array.isArray(data.transactions) ? data.transactions : [];
            // 累積獲得點數 = 所有正向交易加總（只增不減）；沒有明細時退回目前餘額
            const earned = txns.length
                ? txns.reduce((s, t) => s + (Number(t.delta) > 0 ? Number(t.delta) : 0), 0)
                : null;
            return { ok: true, balance: data.balance ?? null, lifetime: data.lifetime ?? earned, earned, transactions: txns };
        } catch (_) {
            return { ok: false, balance: null };
        }
    },

    async getCheckinStatus(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/check-in`, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store'
            });
            if (!res.ok) return { ok: false, status: res.status };
            const data = await res.json().catch(() => ({}));
            return { ok: true, ...data };
        } catch (_) {
            return { ok: false };
        }
    },

    async checkInMember(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false };
        return this._protectedWrite(email, async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/check-in`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) return { ok: false, status: res.status, error: data?.error?.message || data?.message || `HTTP ${res.status}` };
                return { ok: true, ...data };
            } catch (_) {
                return { ok: false };
            }
        });
    },

    async listMemberTasks(email) {
        return this._dedupe(`tasks:${email}`, () => this.__listMemberTasks(email));
    },
    async __listMemberTasks(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false, tasks: [] };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/tasks`, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store'
            });
            if (!res.ok) return { ok: false, status: res.status, tasks: [] };
            const data = await res.json().catch(() => ({}));
            return { ok: true, tasks: Array.isArray(data.tasks) ? data.tasks : [] };
        } catch (_) {
            return { ok: false, tasks: [] };
        }
    },

    async claimMemberTask(email, taskId) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email || !taskId) return { ok: false };
        return this._protectedWrite(email, async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/tasks/${encodeURIComponent(taskId)}/claim`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await res.json().catch(() => ({}));
                // 將「已領取」等常見狀態轉成清楚的中文提示。
                if (!res.ok) {
                    const byStatus = {
                        400: '這個任務還沒完成，現在不能領取。',
                        403: '你沒有領取這個獎勵的權限。',
                        404: '找不到這個任務，請重新整理後再試。',
                        409: '這個獎勵已經領取過了。'
                    };
                    return {
                        ok: false,
                        status: res.status,
                        error: byStatus[res.status] || data?.error?.message || data?.message || `任務領取失敗（HTTP ${res.status}）`
                    };
                }
                return { ok: true, ...data };
            } catch (_) {
                return { ok: false };
            }
        });
    },

    async redeemMemberTheme(email, themeId) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email || !themeId) return { ok: false };
        return this._protectedWrite(email, async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/theme-shop/${encodeURIComponent(themeId)}/redeem`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    const code = data?.error?.code || data?.code || '';
                    // 已擁有主題時視為成功，讓本機補回解鎖狀態。
                    if (/ALREADY_OWNED|already.?owned/i.test(code)) return { ok: true, alreadyOwned: true };
                    return { ok: false, status: res.status, code, error: data?.error?.message || data?.message || `HTTP ${res.status}` };
                }
                return { ok: true, ...data };
            } catch (_) {
                return { ok: false };
            }
        });
    },

    // ═══ 收藏妝容對比圖 saved_looks：跨裝置持久化，走登入 session（本機 localStorage 仍是離線快取，遠端失敗不影響本機） ═══
    _isStorableImageUrl(value) {
        const raw = String(value || '').trim();
        if (!raw || raw.length > 500) return false;
        if (/^\/media\/render\/[0-9a-f]{32}(?:\/before)?$/.test(raw)) return true;
        try {
            const url = new URL(raw);
            return url.protocol === 'https:' || url.protocol === 'http:';
        } catch (_) {
            return false;
        }
    },
    async listSavedLooks(email) {
        return this._dedupe(`saved-looks:${email}`, () => this.__listSavedLooks(email));
    },
    async __listSavedLooks(email) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false, looks: [] };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/saved-looks`, {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store'
            });
            if (!res.ok) return { ok: false, status: res.status, looks: [] };
            const data = await res.json().catch(() => ({}));
            // 相容 looks、items 與裸陣列三種清單回應格式。
            const list = Array.isArray(data) ? data
                : (Array.isArray(data.looks) ? data.looks
                : (Array.isArray(data.items) ? data.items
                : (Array.isArray(data.savedLooks) ? data.savedLooks
                : (Array.isArray(data.saved_looks) ? data.saved_looks : null))));
            if (list === null) {
                // 回了 200 但認不得的形狀：講出來，不要靜靜當成「這個人沒有收藏」。
                console.warn('[saved-looks] 認不得的回應格式，keys =', Object.keys(data || {}));
                return { ok: true, looks: [], unknownShape: true };
            }
            return { ok: true, looks: list };
        } catch (_) {
            return { ok: false, looks: [] };
        }
    },

    async createSavedLook(email, payload) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email) return { ok: false };
        // saved_looks 的 before/after 欄位是 String(500) URL；禁止把 File、Blob
        // 或 data/base64 寫入資料庫。圖片必須先由前端或上傳服務取得 http(s) URL。
        //
        // 妝後圖必須有網址；妝前圖若仍是 base64 就留空，不寫入會員資料庫。
        const afterImageUrl = String(payload?.afterImageUrl || '').trim();
        const rawBeforeImageUrl = String(payload?.beforeImageUrl || '').trim();
        const beforeImageUrl = this._isStorableImageUrl(rawBeforeImageUrl) ? rawBeforeImageUrl : '';
        if (!payload?.style || !this._isStorableImageUrl(afterImageUrl)) {
            return { ok: false, skipped: true, reason: 'AFTER_IMAGE_URL_REQUIRED' };
        }
        // 資料庫需要完整 http(s) 網址，因此替 Gateway 相對路徑補上目前網域。
        const qualify = (value) => value && value.startsWith('/')
            ? new URL(value, window.location.origin).href
            : value;
        const persistedAfterImageUrl = qualify(afterImageUrl);
        const persistedBeforeImageUrl = qualify(beforeImageUrl);
        return this._protectedWrite(email, async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/saved-looks`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        style: String(payload.style).slice(0, 120),
                        beforeImageUrl: persistedBeforeImageUrl,
                        afterImageUrl: persistedAfterImageUrl,
                        analysisSummary: payload.analysisSummary && typeof payload.analysisSummary === 'object'
                            ? payload.analysisSummary
                            : {}
                    })
                });
                if (!res.ok) return { ok: false, status: res.status };
                const look = await res.json().catch(() => ({}));
                return { ok: true, look };
            } catch (_) {
                return { ok: false };
            }
        });
    },

    async deleteSavedLook(email, id, opts) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email || id == null) return { ok: false };
        // 管理員代刪別人的收藏時，要斷言的是「你自己還登入著」，
        // 不是「你就是這筆資料的主人」——後者對管理員必然不成立。
        //
        // 這支同時被兩種人呼叫：會員刪自己的（傳自己的 email，斷言成立），
        // 以及後台刪別人的（傳對方的 email）。第二種先前必然被
        // assertSessionOwner 擋在 SESSION_UNAVAILABLE，run() 從來沒被呼叫，
        // 所以請求連送都沒送出去，而畫面顯示「資料庫刪除失敗，請確認 admin
        // session 與資料庫連線」——兩個都沒有問題，但看的人會往那兩個方向查。
        //
        // 這不會放寬權限：能不能刪別人的收藏由 Gateway 判斷（admin 角色檢查、
        // _authorize_member_path，以及對別人帳號的寫入稽核）。前端這道斷言問的
        // 一直是「你的 session 還有效而且是你的」，不是「你有沒有權限」。
        const actor = (opts && opts.asAdmin) ? this._writeActorEmail() : email;
        return this._protectedWrite(actor, async () => {
            try {
                const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/saved-looks/${encodeURIComponent(id)}`, {
                    method: 'DELETE',
                    credentials: 'include'
                });
                return { ok: res.ok, status: res.status };
            } catch (_) {
                return { ok: false };
            }
        });
    },

    // 使用者對五官判斷做的修正，給管理端第二次人工檢查用。
    // 只有管理員讀得到（Gateway 端驗 admin claims + CSRF + actor 綁定）。
    // 讀不到時 Gateway 回 503 而不是空陣列——空陣列會被誤讀成「沒有人修正過」。
    async fetchFaceFeedback(limit = 50) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        try {
            const res = await this._protectedFetch(
                `${baseUrl}/face-feedback?limit=${encodeURIComponent(limit)}`,
                { credentials: 'include', cache: 'no-store', headers: this._adminProductHeaders() });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, items: Array.isArray(data.items) ? data.items : [] };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    // 管理員對一筆修正下判斷：accepted 進訓練集、rejected 不用，corrected 以 labels 指定新類別。
    //
    // 這條跟 fetchFaceFeedback 是一組的：光讀不寫的話，那個列表只能看，
    // 重訓時仍然分不出哪些修正被認可過——使用者的誤點會跟正確的修正一起被學進去。
    // 覆核一筆修正。可以整筆（decision 是字串），也可以逐部位
    // （decision 是 {部位: 'accepted'|'rejected'|'corrected'}）——管理員很可能覺得
    // 「嘴型改得對、眼型改錯了」，那就該只採用嘴型。
    async reviewFaceFeedback(feedbackId, decision, note = '', labels = null) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        if (!feedbackId) return { ok: false, error: '缺少 feedbackId' };
        const valid = v => v === 'accepted' || v === 'rejected' || v === 'corrected';
        let body;
        if (decision && typeof decision === 'object') {
            const entries = Object.entries(decision);
            if (!entries.length) return { ok: false, error: '沒有要送出的決定' };
            if (!entries.every(([, v]) => valid(v))) {
                return { ok: false, error: '決定只能是 accepted、rejected 或 corrected' };
            }
            body = { decisions: decision, note };
            // corrected 一定要帶標籤，後端會擋沒有標籤的改判——
            // 那種紀錄之後匯入時對不到任何東西。
            if (labels && typeof labels === 'object') body.labels = labels;
        } else {
            if (!valid(decision)) return { ok: false, error: 'decision 只能是 accepted、rejected 或 corrected' };
            body = { decision, note };
        }
        try {
            const res = await this._protectedFetch(
                `${baseUrl}/face-feedback/${encodeURIComponent(feedbackId)}/review`,
                {
                    method: 'PATCH',
                    credentials: 'include',
                    headers: this._adminProductHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify(body),
                });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            // corrected 的管理員標籤是送訓時真正使用的標籤。若只回傳
            // reviewDecisions、不把 reviewLabels 帶回前端，畫面重畫後會把
            // corrected 視為「沒有標籤」，於是這筆回饋會從可送訓清單消失。
            // 後端已驗證過 labels，這裡要完整保留它，讓管理員改判後可以直接
            // 勾選／全選並送進訓練批次。
            return {
                ok: true,
                reviewStatus: data.reviewStatus,
                reviewDecisions: data.reviewDecisions || {},
                reviewLabels: data.reviewLabels || {},
            };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    // 某一筆修正對應的樣本影像。點開那一筆才要——影像即使是 96×96 的 ROI，
    // 108 筆一次全帶也是幾 MB，而覆核的人一次只看一筆。
    async fetchFaceFeedbackSamples(feedbackId) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        if (!feedbackId) return { ok: false, error: '缺少 feedbackId' };
        try {
            const res = await this._protectedFetch(
                `${baseUrl}/face-feedback/${encodeURIComponent(feedbackId)}/samples`,
                { credentials: 'include', cache: 'no-store', headers: this._adminProductHeaders() });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, samples: Array.isArray(data.samples) ? data.samples : [] };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    // 將管理員已採用的回饋登記成可追蹤的 ConvNeXt 訓練批次；實際訓練由後端腳本執行。
    // 換模型上線是「登記」不是「執行」：模型檔在訓練機的檔案系統上，Gateway 跑在
    // Cloud Run 上碰不到它，也沒有部署用的認證。這支只把決定寫進佇列，實際的複製、
    // 類別檢查與 manifest 更新由訓練機的 promotion_worker 做，部署仍要人執行。
    async requestModelPromotion(runId, parts) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        const id = String(runId || '').trim();
        if (!id) return { ok: false, error: '缺少訓練批次編號' };
        if (!Array.isArray(parts) || !parts.length) {
            return { ok: false, error: '請至少選擇一個要換上線的部位' };
        }
        try {
            const res = await this._protectedFetch(`${baseUrl}/face-training/promotions`, {
                method: 'POST', credentials: 'include',
                headers: this._adminProductHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ runId: id, parts }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, ...data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async fetchModelPromotions(limit = 20) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        try {
            const res = await this._protectedFetch(
                `${baseUrl}/face-training/promotions?limit=${encodeURIComponent(limit)}`, {
                credentials: 'include', cache: 'no-store', headers: this._adminProductHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, ...data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async queueFaceTraining(feedbackIds) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        if (!Array.isArray(feedbackIds) || !feedbackIds.length) {
            return { ok: false, error: '請先選擇至少一筆已覆核資料' };
        }
        try {
            const res = await this._protectedFetch(`${baseUrl}/face-training/runs`, {
                method: 'POST', credentials: 'include',
                headers: this._adminProductHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ feedbackIds }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, ...data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    // 失敗批次不能再走一般送訓：原本的 feedback 已經掛了 trainingRunId。
    // 後端會建立一個新的 queued 批次，保留舊批次的失敗原因與歷史證據。
    async retryFaceTraining(runId) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        const id = String(runId || '').trim();
        if (!id) return { ok: false, error: '缺少訓練批次編號' };
        try {
            const res = await this._protectedFetch(
                `${baseUrl}/face-training/runs/${encodeURIComponent(id)}/retry`, {
                method: 'POST', credentials: 'include',
                headers: this._adminProductHeaders({ 'Content-Type': 'application/json' }),
                body: '{}',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, ...data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    // limit 要明講。Gateway 的預設是 5，而後台這一區的用途是**看完整歷史**——
    // 預設值會讓「送訓完成」永遠只數得到最近五批，早期跑過的批次直接消失，
    // 而畫面上不會說它被截斷了。50 是 Gateway 允許的上限。
    async fetchFaceTrainingRuns(limit = 50) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        try {
            const res = await this._protectedFetch(
                `${baseUrl}/face-training/runs?limit=${encodeURIComponent(limit)}`, {
                credentials: 'include', cache: 'no-store', headers: this._adminProductHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, ...data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    // 儲存空間 ↔ 會員名冊對帳。唯讀。
    //
    // 沒有 limit 參數：這條的用途就是「全部算一次」，能截斷的話得到的數字
    // 就不是差額而是抽樣，而抽樣出來的「少了 4 個會員」是會被當真去刪東西的。
    async fetchMemberStorageAudit() {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'admin-api 未設定' };
        try {
            const res = await this._protectedFetch(`${baseUrl}/member-storage-audit`, {
                credentials: 'include', cache: 'no-store', headers: this._adminProductHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, ...data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async patchRemoteProduct(rawId, payload, version) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'productUrl 未設定' };
        if (rawId == null) return { ok: false, error: '找不到這筆商品的資料庫 id' };
        try {
            const headers = this._adminProductHeaders({ 'Content-Type': 'application/json' });
            if (version != null) headers['If-Match'] = String(version);
            const res = await this._protectedFetch(`${baseUrl}/products/${encodeURIComponent(rawId)}`, {
                method: 'PATCH',
                credentials: 'include',
                headers,
                body: JSON.stringify(payload)
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, product: data.product || data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async createRemoteProduct(payload) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'productUrl 未設定' };
        try {
            const res = await this._protectedFetch(`${baseUrl}/products`, {
                method: 'POST',
                credentials: 'include',
                headers: this._adminProductHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(payload)
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, product: data.product || data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async deleteRemoteProduct(rawId) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, error: 'productUrl 未設定' };
        if (rawId == null) return { ok: false, error: '找不到這筆商品的資料庫 id' };
        try {
            const res = await this._protectedFetch(`${baseUrl}/products/${encodeURIComponent(rawId)}`, {
                method: 'DELETE',
                credentials: 'include',
                headers: this._adminProductHeaders()
            });
            const data = await res.json().catch(() => ({}));
            // 重複刪除回 404 PRODUCT_NOT_FOUND，那是冪等成功不是故障：
            // 東西已經不在了，正是我們要的結果。當成錯誤會讓管理員以為刪不掉，
            // 然後再按一次——而每一次都會再收到同一個 404。
            if (res.status === 404 && data?.error?.code === 'PRODUCT_NOT_FOUND') {
                return { ok: true, alreadyDeleted: true, mode: 'hard' };
            }
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            // 後端保證回 mode:"hard"。不是 hard 就代表它退回軟刪除了——
            // 那時候**不能**從畫面上移除商品，否則畫面說刪掉了、資料庫裡還在，
            // 而那正是這次改動要消滅的狀態。
            if (data.mode !== 'hard') {
                return { ok: false, error: '商品後端沒有確認硬刪除（mode 不是 hard），商品可能仍在資料庫裡' };
            }
            return { ok: true, ...data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    // 刪除前先問：這一筆被幾個人收藏、放在幾個購物車裡。
    // 拿不到就回 null——影響數字是「錦上添花」，不該因為它讀不到而擋住刪除。
    async getProductDeleteImpact(rawId) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl || rawId == null) return null;
        try {
            const res = await this._protectedFetch(
                `${baseUrl}/products/${encodeURIComponent(rawId)}/delete-impact`,
                { credentials: 'include', headers: this._adminProductHeaders() });
            if (!res.ok) return null;
            return await res.json().catch(() => null);
        } catch {
            return null;
        }
    },


    async listProductAuditLogs(limit = 100) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, logs: [] };
        try {
            // 走統一的受保護 fetch wrapper：admin-api 是受保護的同源 Gateway 路徑，
            // 由 wrapper 統一帶 credentials、綁定分頁 session signal，並在 401／403
            // 時通知 Router 換帳號，不再讓稽核讀取各自處理一套逾期邏輯。
            const res = await this._fetchWithRelogin(`${baseUrl}/product-audit-logs?limit=${encodeURIComponent(limit)}`, {
                headers: this._adminProductHeaders(), cache: 'no-store'
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, logs: [], ...this._productApiError(data, res.status) };
            return { ok: true, logs: data.items || data.logs || [] };
        } catch (err) { return { ok: false, logs: [], error: '連線失敗：' + err.message }; }
    },

    // Gateway 自己記的管理操作紀錄。跟 listProductAuditLogs 的差別：
    // 那一支是代理商品後端的稽核表（對方記了什麼由對方決定，對方掛掉就查不到），
    // 這一支讀的是 Gateway 每一筆增改刪都會寫的 admin_audit_events，含失敗的操作。
    // 管理員誤刪之後要查「誰、什麼時候、動了哪一筆」，靠的是這一份。
    async listAdminActions(limit = 100) {
        const baseUrl = gatewayService('admin-api');
        if (!baseUrl) return { ok: false, events: [] };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/admin-actions?limit=${encodeURIComponent(limit)}`, {
                headers: this._adminProductHeaders(), cache: 'no-store'
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, events: [], ...this._productApiError(data, res.status) };
            return { ok: true, events: Array.isArray(data.events) ? data.events : [] };
        } catch (err) { return { ok: false, events: [], error: '連線失敗：' + err.message }; }
    },

    // LAB 物件（{L,a,b} 或 {L,A,B}）轉成推薦端新規格要的陣列 [L, a, b]
    _labToArray(lab) {
        const obj = this._labToUpperKeys(lab);
        if (!obj) return null;
        return [obj.L ?? 0, obj.A ?? 0, obj.B ?? 0];
    },

    // 嚴格版：缺任何一軸就回 null，不用 0 補。
    //
    // _labToArray 的 `?? 0` 是給「顯示用」的容錯，但拿去比色號時它很危險：
    // 缺了 L 會變成 L=0（純黑），那不是「沒資料」，是一個看起來完全合法、
    // 卻指向錯誤顏色的座標。推薦端收到後會照算 ΔE00，算出來的色差是假的。
    _labToArrayStrict(lab) {
        const obj = this._labToUpperKeys(lab);
        if (!obj) return null;
        const arr = [obj.L, obj.A, obj.B];
        return arr.every(v => typeof v === 'number' && Number.isFinite(v)) ? arr : null;
    },

    // 這組 LAB 能不能拿去做 CIEDE2000 比色。
    //
    // 這裡只做送出前的輸入邊界檢查，避免把壞座標送進色差計算；推薦結果的
    // skinToneLabReliable 與 fallbackReasons 仍完全以後端回傳為準，前端不補結果。
    _isUsableLab(arr) {
        if (!Array.isArray(arr) || arr.length !== 3) return false;
        const [L, a, b] = arr;
        if (![L, a, b].every(v => typeof v === 'number' && Number.isFinite(v))) return false;
        // CIE L*a*b* 的有效範圍：L* 是 0–100 的亮度；a*/b* 在 8-bit 影像轉換後
        // 實務上落在 ±128 內。超出的值不可能來自一張真實照片。
        return L >= 0 && L <= 100 && Math.abs(a) <= 128 && Math.abs(b) <= 128;
    },

    // 2026-07-15 起商品推薦端改吃規格書格式：整包 analysisPackage（faceAnalysis 巢狀、lab 用陣列），
    // 回應也改在 analysisPackage.recommendations.products 底下。詳見「演算法端接口規格書_analysis_package商品推薦_2026-07-13.md」。
    // 推薦端公告的合法 style ID（《商品推薦 API 串接與校對清單》§2）。
    // 先在前端擋一次是為了省掉一次註定 422 的往返；後端仍會自己驗（實測七個全部可用）。
    RECOMMEND_STYLE_IDS: Object.freeze([
        'softBaddie', 'richGirl', 'hongKong', 'koreanClean',
        'yandere', 'japaneseClear', 'mensPlain'
    ]),

    // 把使用者的偏好整理成契約允許的形狀。
    //
    // 這些上限是文件寫的，但推薦端**沒有驗**（2026-08-23 實測：品牌送 50 筆、
    // mode 送 123 都照樣回 200）。既然後端不擋，前端就得自己守——不是為了保護後端，
    // 是為了讓「送出去的東西」與「文件說好的東西」一致，哪天後端補上驗證時
    // 前端不會突然開始收 400。
    _sanitizeRecommendationOptions(raw) {
        if (!raw || typeof raw !== 'object') return null;
        const out = {};

        const brands = (key) => {
            const list = raw[key];
            if (!Array.isArray(list)) return;
            const cleaned = list
                .map(v => String(v ?? '').trim())
                .filter(Boolean)
                .slice(0, 20);   // §2「品牌陣列各最多 20 筆」
            if (cleaned.length) out[key] = cleaned;
        };
        brands('preferredBrands');
        brands('avoidedBrands');

        const pref = raw.pricePreference;
        if (pref && typeof pref === 'object') {
            const price = {};
            const min = Number(pref.min);
            const max = Number(pref.max);
            const hasMin = Number.isFinite(min) && min >= 0;
            const hasMax = Number.isFinite(max) && max >= 0;
            // 區間反轉是不可能滿足的條件，後端會靜默忽略。與其送出去讓使用者
            // 看到「已套用預算」卻拿到超出預算的商品，不如在這裡就把它擺正。
            if (hasMin && hasMax && min > max) {
                price.min = max; price.max = min;
            } else {
                if (hasMin) price.min = min;
                if (hasMax) price.max = max;
            }
            const mode = String(pref.mode ?? '').trim();
            if (['value', 'low', 'high'].includes(mode)) price.mode = mode;  // §2 白名單
            if (Object.keys(price).length) out.pricePreference = price;
        }

        return Object.keys(out).length ? out : null;
    },

    // options：{ limit?: number, recommendationOptions?: {...} }
    // 第三個參數是 2026-08-23 新增的，舊呼叫（兩個參數）行為完全不變。
    async recommendProducts(analysisPackage, styleId, options = null) {
        const url = this.config.url('product', 'recommendPath');
        if (!url) return { ok: false, products: [] };
        try {
            // 相容舊呼叫：如果傳進來的已經是 faceAnalysis（沒有 faceAnalysis 子欄位但有 faceShape/skinTone），自己包一層
            const fa = analysisPackage?.faceAnalysis
                || ((analysisPackage?.faceShape || analysisPackage?.skinTone) ? analysisPackage : null);
            const suggestion = analysisPackage?.generativeText?.suggestion || null;
            // 統一走受保護 fetch wrapper。recommend-products 在 Gateway 屬公開商品路徑，
            // wrapper 不會加 actor header，但會把這條請求綁進分頁的 session 批次，
            // 換帳號或登出時一併取消，不留背景請求打到舊身分。
            // 送出前先自己驗一次膚色 LAB。壞資料（型別錯、缺一軸、超出色彩空間）
            // 一律當成不可信——理由見 _isUsableLab 的說明。
            const skinLab      = this._labToArrayStrict(fa?.skinTone?.lab);
            const skinLabOk    = this._isUsableLab(skinLab);
            const lipLab       = this._labToArrayStrict(fa?.lipLab);
            // 眉彩色號只能用眉色或髮色比對，絕不能用膚色（契約 §1）。
            // ⚠️ 目前臉部分析端還沒有產出眉色：Face_analyzer_BASIC 只回「膚色」與
            // 「嘴唇_LAB」，沒有眉毛或頭髮的 LAB，所以這裡取到的一定是 null，
            // 推薦端必然回 BROW_COLOR_UNAVAILABLE。先接上是為了讓上游一補就生效，
            // 不必再改前端一次。
            const browLab      = this._labToArrayStrict(fa?.browLab ?? fa?.hairLab);

            const gen = analysisPackage?.generativeText || {};
            const generativeText = {};
            if (suggestion) generativeText.suggestion = suggestion;
            // 這三個欄位會實際影響推薦端的排序（styleTags 命中與否決定
            // STYLE_KEYWORD_NO_MATCH），先前完全沒送出去。
            const strList = (v) => Array.isArray(v)
                ? v.map(x => String(x ?? '').trim()).filter(Boolean) : [];
            if (strList(gen.styleTags).length)       generativeText.styleTags = strList(gen.styleTags);
            if (strList(gen.preferredColors).length) generativeText.preferredColors = strList(gen.preferredColors);
            if (strList(gen.avoidTags).length)       generativeText.avoidTags = strList(gen.avoidTags);

            // §2「limit 必須是 1–50 的整數」。不給就沿用原本的 12。
            const rawLimit = options?.limit;
            const limit = Number.isFinite(rawLimit)
                ? Math.min(50, Math.max(1, Math.trunc(rawLimit)))
                : 12;

            const recOptions = this._sanitizeRecommendationOptions(options?.recommendationOptions);

            const res = await this._fetchWithRelogin(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    analysisPackage: {
                        id:    analysisPackage?.id || null,
                        // 版本協商用。推薦端目前不強制，但少了它，哪天契約再改版
                        // 雙方就沒有任何依據判斷對方是哪一版。
                        schemaVersion: analysisPackage?.schemaVersion || '2026-08-v2',
                        style: styleId || null,
                        faceAnalysis: {
                            faceShape: fa?.faceShape || null,
                            browShape: fa?.browShape || null,
                            eyeShape:  fa?.eyeShape  || null,
                            lipShape:  fa?.lipShape  || null,
                            skinTone: {
                                season: fa?.skinTone?.season || null,
                                level:  fa?.skinTone?.level  || null,
                                // 不可用的 LAB 直接送 null，而不是送一組算不出色差的座標。
                                lab:    skinLabOk ? skinLab : null,
                                // 這支請求是白名單重組，不是把 faceAnalysis 整個送出去。
                                // 先前只在 fromRawFaceAnalysis 補了 labReliable，卻沒補這裡——
                                // 旗標在**下一層**被丟掉，送出去的 body 跟修之前一模一樣，
                                // 推薦端從來沒收到過。缺欄位視為可信，維持既有行為。
                                //
                                // 2026-08-23 追加：LAB 本身不可用時也一律送 false。
                                // 推薦端只認這個旗標，不會自己檢查 lab 是壞的。
                                labReliable: skinLabOk && fa?.skinTone?.labReliable !== false,
                            },
                            lipLab: lipLab,
                            ...(browLab ? { browLab } : {}),
                        },
                        ...(Object.keys(generativeText).length ? { generativeText } : {}),
                    },
                    limit,
                    ...(recOptions ? { recommendationOptions: recOptions } : {}),
                })
            });
            if (!res.ok) {
                // 錯誤碼與 requestId 先前整包被丟掉，於是 §5 的分流處置
                // （400 檢查參數／422 請使用者重做分析／502、504 可重試）
                // 在前端完全無法實作，而且回報後端問題時拿不出 requestId。
                let payload = null;
                try { payload = await res.json(); } catch (_) {}
                const err = payload?.error || null;
                return {
                    ok: false,
                    status: res.status,
                    code: err?.code || '',
                    message: err?.message || '',
                    requestId: err?.requestId || '',
                    // 502／504 是上游暫時不可用，畫面應該給重試按鈕而不是叫使用者重做分析。
                    retryable: err?.retryable === true || res.status === 502 || res.status === 504,
                    products: []
                };
            }
            const data = await res.json();
            // 正式 Gateway 可能把 recommendations 放在 analysisPackage 裡，也可能直接
            // 回在根節點。兩種回應都必須用同一個 recommendation 物件往下讀，否則根節點
            // 的 shadeRecommendation／跨品牌欄位會在這裡被漏掉。
            const recommendation = data.analysisPackage?.recommendations || data.recommendations || data;
            const rec = (recommendation && typeof recommendation === 'object') ? recommendation : {};
            const list = rec.products
                ?? (Array.isArray(data.recommendations) ? data.recommendations : null)
                ?? data.products
                ?? [];  // 新格式在 analysisPackage.recommendations.products；相容根節點格式

            // 推薦服務是膚色可信度與降級狀態的唯一來源。前端不再把自己的輸入檢查
            // 改寫成推薦結果，也不替後端追加 fallbackReasons；後端沒回就代表契約未完成。
            const fallbackReasons = Array.isArray(rec.fallbackReasons) ? [...rec.fallbackReasons] : [];
            const skinToneLabReliable = rec.skinToneLabReliable === true;

            // 同一商品只留一筆。回應同時有 analysisPackage.recommendations.products
            // 與最外層 products（後者是相容舊前端的重複欄位），萬一日後兩邊被合併，
            // 沒有去重就會在畫面上出現兩張一模一樣的卡。
            const seenIds = new Set();
            const products = (Array.isArray(list) ? list : [])
                .map(item => this._normalizeProduct(item))
                .filter(p => {
                    if (!p) return false;
                    const key = String(p.rawId ?? p.id);
                    if (seenIds.has(key)) return false;
                    seenIds.add(key);
                    return true;
                });

            return {
                ok: true,
                ...data,
                skinToneLabReliable,
                fallbackReasons,
                // 粉底的相鄰色階（契約 §5）。null 代表沒有這個區塊，畫面要整個隱藏——
                // 不要自己補商品湊出「淺一階／深一階」，那是編造的。
                shadeRecommendation: this._normalizeShadeRecommendation(rec.shadeRecommendation),
                // 主推薦粉底的跨品牌近似色號；沿用後端排序與色差，不在前端重算。
                foundationCrossBrandAlternatives: (Array.isArray(rec.foundationCrossBrandAlternatives)
                    ? rec.foundationCrossBrandAlternatives : [])
                    .map(item => {
                        if (!item || typeof item !== 'object') return null;
                        const product = item.product ? this._normalizeProduct(item.product) : null;
                        const brand = String(item.brand || product?.brand || '').trim();
                        if (!brand || !product) return null;
                        const deltaRaw = item.anchorDeltaE ?? item.anchor_delta_e;
                        return {
                            brand,
                            shadeCode: String(item.shadeCode ?? item.shade_code
                                ?? product.shadeCode ?? product.shadeName ?? '').trim(),
                            anchorDeltaE: (deltaRaw == null || deltaRaw === ''
                                || !Number.isFinite(Number(deltaRaw))) ? null : Number(deltaRaw),
                            product,
                        };
                    }).filter(Boolean),
                foundationAvailableTargetBrands: Array.isArray(rec.availableTargetBrands)
                    ? [...new Set(rec.availableTargetBrands.map(brand => String(brand ?? '').trim()).filter(Boolean))]
                    : [],
                // 兩組門檻（膚色 0～2、替代色 0～5）與粉底的判定結果。
                // 前端不自己算門檻也不自己放寬——顯示的數字與界線一律以後端為準，
                // 兩邊各判一次遲早會不一致，而不一致的樣子是「卡片說通過、說明說沒通過」。
                colorDifferencePolicy: (rec.colorDifferencePolicy
                    && typeof rec.colorDifferencePolicy === 'object')
                    ? rec.colorDifferencePolicy : null,
                foundationMatchStatus: (rec.foundationMatchStatus
                    && typeof rec.foundationMatchStatus === 'object')
                    ? rec.foundationMatchStatus : null,
                products
            };
        } catch (_) {
            return { ok: false, products: [], code: 'NETWORK_ERROR', retryable: true };
        }
    },

    async login(email, password) {
        const result = await this.loginToGateway(email, password);
        if (!result.ok) {
            const err = new Error(result.error || '帳號或密碼錯誤');
            err.networkFailure = result.code === 'NETWORK_ERROR';
            err.status = result.status || 0;
            err.code = result.code || null;
            throw err;
        }
        try {
            sessionStorage.removeItem('beautyAuthCreds');
            sessionStorage.removeItem('memberAccessToken');
            sessionStorage.removeItem('gatewaySessionToken');
        } catch (_) {}
        return { success: true, member: result.member, expiresAt: result.expiresAt };
    },

    // 把會員資料庫的錯誤回應轉成可顯示的訊息。
    // 重點是「伺服器有回應」與「連不上伺服器」必須分開講：前者代表請求送到了、只是被拒絕，
    // 把它顯示成連線失敗會讓使用者往完全錯誤的方向排查（實際發生過，見 issue #22）。
    async _memberApiError(res, fallback) {
        let data = null;
        try { data = await res.json(); } catch (_) {}
        const error = data?.error || data?.detail?.error || null;
        const code = error?.code || data?.code || '';
        const known = {
            EMAIL_EXISTS: '這個信箱已經註冊過了。若帳號已被停權或刪除，請聯繫管理員，重新註冊不會生效。',
            INVALID_OTP: '驗證碼錯誤，請重新確認。',
            OTP_EXPIRED: '驗證碼已過期，請重新發送。',
            OTP_RATE_LIMITED: '驗證碼發送過於頻繁，請稍後再試。',
            USER_NOT_FOUND: '找不到這個帳號。',
        };
        // 後端有些錯誤的 message 直接等於 code（例如 EMAIL_EXISTS），那種原樣顯示沒有意義
        const raw = error?.message && error.message !== code ? error.message : '';
        const err = new Error(known[code] || raw || data?.message || `${fallback}（HTTP ${res.status}）`);
        err.status = res.status;
        err.code = code;
        return err;
    },

    async register(payload) {
        const body = {
            phone_number: payload.phone,
            name: payload.name,
            email: payload.email,
            password: payload.password,
            age: Number(payload.age)
        };
        let res;
        try {
            const gateway = this.config.services.aiGateway;
            res = await fetch(`${gateway.baseUrl}${gateway.registerPath}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(body)
            });
        } catch (err) {
            throw new Error('無法連線到會員資料庫，請稍後再試。');
        }
        // 保留後端的註冊錯誤，例如信箱已存在。
        if (!res.ok) throw await this._memberApiError(res, '註冊失敗');
        return res.json();
    },

    async sendOTP(email) {
        const gateway = this.config.services.aiGateway;
        try {
            const res = await fetch(`${gateway.baseUrl}${gateway.sendOtpPath}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email })
            });
            if (!res.ok) throw await this._memberApiError(res, '驗證碼寄送失敗');
            return res.json();
        } catch (err) {
            if (err?.status) throw err;
            throw new Error('無法連線到會員服務，請稍後再試。');
        }
    },

    async sendForgotPasswordOTP(email) {
        const gateway = this.config.services.aiGateway;
        try {
            const res = await fetch(`${gateway.baseUrl}${gateway.forgotPasswordPath}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                credentials: 'include', body: JSON.stringify({ email })
            });
            if (!res.ok) throw await this._memberApiError(res, '密碼重設驗證碼寄送失敗');
            return res.json();
        } catch (err) {
            if (err?.status) throw err;
            throw new Error('無法連線到會員服務，請稍後再試。');
        }
    },

    async verifyOTP(email, otp) {
        let res;
        try {
            const gateway = this.config.services.aiGateway;
            res = await fetch(`${gateway.baseUrl}${gateway.verifyOtpPath}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email, otp })
            });
        } catch (err) {
            // fetch 自己拋例外才是真的連不上（DNS、斷線、CORS 被擋）
            throw new Error('無法連線到會員資料庫，請稍後再試。');
        }
        // 驗證碼錯誤是最常見的情況，以前卻顯示成「連線失敗」，使用者只會一直重試同一組錯的碼
        if (!res.ok) throw await this._memberApiError(res, '驗證碼錯誤或已失效，請重新確認。');
        return res.json();
    },

    // LAB → RGB 轉換
    labToRgb(L, a, b) {
        let y = (L + 16) / 116, x = a / 500 + y, z = y - b / 200;
        [x, y, z] = [x, y, z].map(v => { const v3 = v*v*v; return v3 > 0.008856 ? v3 : (v - 16/116) / 7.787; });
        x *= 95.047/100; y *= 1; z *= 108.883/100;
        let r = x*3.2406 + y*-1.5372 + z*-0.4986;
        let g = x*-0.9689 + y*1.8758 + z*0.0415;
        let bl = x*0.0557 + y*-0.2040 + z*1.0570;
        [r, g, bl] = [r, g, bl].map(v => { v = v > 0.0031308 ? 1.055*Math.pow(v,1/2.4)-0.055 : 12.92*v; return Math.max(0,Math.min(255,Math.round(v*255))); });
        return `rgb(${r},${g},${bl})`;
    },

    // LAB → #RRGGBB。給「資料庫沒回 hex_primary、只有 lab」的商品用。
    // 目前商品 API 兩邊都不回 hex（清單連 lab 都沒有，推薦端只有 lab），色塊畫得出來
    // 但色碼文字一直是空的。這裡換算出來的是**近似值**，不是資料庫存的原始色碼，
    // 呼叫端必須標示清楚，不要讓它被當成商品的正式色號抄走。
    labToHex(L, a, b) {
        const matched = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(this.labToRgb(L, a, b) || '');
        if (!matched) return '';
        return '#' + matched.slice(1, 4)
            .map(v => Number(v).toString(16).padStart(2, '0'))
            .join('')
            .toUpperCase();
    }
};

// ═══ 圖片打包：分析 API 吃原圖；只有封裝給生成 / 渲染端時才壓縮 ═══
const ImagePipeline = {
    storageMaxEdge: 1024,
    storageJpegQuality: 0.78,
    workerPath: 'js/image-worker.js',
    workerTimeoutMs: 30000,

    async compressForPackage(file, opts = {}) {
        const role = opts.role || 'front';
        if (!file || !file.type?.startsWith('image/')) {
            return { file, meta: this.metaFromFile(file, role), dataUrl: null };
        }

        if (this.canUseWorker()) {
            try {
                return await this.compressInWorker(file, opts);
            } catch (err) {
                console.warn('Image worker failed, falling back to main thread compression.', err);
            }
        }

        return this.compressOnMainThread(file, opts);
    },

    canUseWorker() {
        return typeof Worker !== 'undefined'
            && typeof OffscreenCanvas !== 'undefined'
            && typeof createImageBitmap !== 'undefined';
    },

    compressInWorker(file, opts = {}) {
        const role = opts.role || 'front';
        const maxEdge = opts.maxEdge || this.storageMaxEdge;
        const quality = opts.quality || this.storageJpegQuality;
        const outputName = this.outputName(file.name, role);
        const requestId = `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

        return new Promise((resolve, reject) => {
            const worker = new Worker(this.workerPath);
            const timer = setTimeout(() => {
                worker.terminate();
                reject(new Error('圖片 Worker 壓縮逾時'));
            }, this.workerTimeoutMs);

            worker.onmessage = (event) => {
                const data = event.data || {};
                if (data.id !== requestId) return;
                clearTimeout(timer);
                worker.terminate();

                if (!data.ok) {
                    reject(new Error(data.error || '圖片 Worker 壓縮失敗'));
                    return;
                }

                const processed = new File([data.blob], outputName, { type: 'image/jpeg' });
                resolve({
                    file: processed,
                    dataUrl: data.dataUrl,
                    meta: {
                        ...this.metaFromFile(file, role, { width: data.originalWidth, height: data.originalHeight }),
                        compressedName: processed.name,
                        compressedType: processed.type,
                        compressedSize: processed.size,
                        compressedWidth: data.compressedWidth,
                        compressedHeight: data.compressedHeight,
                        compressionRatio: file.size ? Number((processed.size / file.size).toFixed(3)) : null,
                        processedBy: 'worker'
                    }
                });
            };

            worker.onerror = (err) => {
                clearTimeout(timer);
                worker.terminate();
                reject(new Error(err.message || '圖片 Worker 發生錯誤'));
            };

            worker.postMessage({ id: requestId, file, role, maxEdge, quality, outputName });
        });
    },

    async compressOnMainThread(file, opts = {}) {
        const role = opts.role || 'front';
        const bitmap = await this.loadImage(file);
        const maxEdge = opts.maxEdge || this.storageMaxEdge;
        const quality = opts.quality || this.storageJpegQuality;
        const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
        const width = Math.max(1, Math.round(bitmap.width * scale));
        const height = Math.max(1, Math.round(bitmap.height * scale));
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        canvas.getContext('2d').drawImage(bitmap, 0, 0, width, height);

        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
        if (!blob) {
            return { file, meta: this.metaFromFile(file, role, { width: bitmap.width, height: bitmap.height }), dataUrl: null };
        }
        const processed = new File([blob], this.outputName(file.name, role), { type: 'image/jpeg' });
        const dataUrl = await this.blobToDataUrl(blob);
        return {
            file: processed,
            dataUrl,
            meta: {
                ...this.metaFromFile(file, role, { width: bitmap.width, height: bitmap.height }),
                compressedName: processed.name,
                compressedType: processed.type,
                compressedSize: processed.size,
                compressedWidth: width,
                compressedHeight: height,
                compressionRatio: file.size ? Number((processed.size / file.size).toFixed(3)) : null,
                processedBy: 'main-thread'
            }
        };
    },

    loadImage(file) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => resolve(img);
            img.onerror = () => reject(new Error('圖片讀取失敗'));
            img.src = URL.createObjectURL(file);
        });
    },

    outputName(name, role) {
        const clean = (name || `${role}.jpg`).replace(/\.[^.]+$/, '');
        return `${clean}-${role}-package.jpg`;
    },

    blobToDataUrl(blob) {
        return new Promise(resolve => {
            const reader = new FileReader();
            reader.onload = ev => resolve(ev.target.result);
            reader.readAsDataURL(blob);
        });
    },

    metaFromFile(file, role, dims) {
        const originalSize = file?.size || 0;
        return {
            role,
            serial: `${role}-${Date.now()}`,
            originalName: file?.name || '',
            originalType: file?.type || '',
            originalSize,
            width: dims?.width || null,
            height: dims?.height || null,
            compressedName: null,
            compressedType: null,
            compressedSize: null,
            compressedWidth: null,
            compressedHeight: null,
            compressionRatio: null,
            processedBy: null
        };
    }
};

// ═══ 分析資料包：預留 BASIC / PRO / 渲染 / 推薦 / 非同步狀態欄位 ═══
const AnalysisPackage = {
    create({ mode, images = {}, status = 'draft' }) {
        const now = new Date().toISOString();
        return {
            // 這個資料包自 2026-08 起帶 labReliable／labReliability，版本號要跟著走，
            // 否則照《給演算法端_膚色可信度旗標接入》的規則，看到 2026-06-v1 的消費端
            // 會判定沒有可信度旗標。目前這個欄位不會離開瀏覽器（送渲染與推薦的都是
            // 白名單重組），所以升版沒有對外風險。
            schemaVersion: '2026-08-v2',
            id: `AN-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            mode,
            client: 'web',
            userId: null,
            status,
            createdAt: now,
            updatedAt: now,
            images,
            faceAnalysis: {
                version: mode === 'pro' ? 'PRO' : 'BASIC',
                faceShape: null,
                browShape: null,
                eyeShape: null,
                noseFront: null,
                noseSide: null,
                lipShape: null,
                skinTone: null,
                lipLab: null,
                symmetry: null,
                sidePhotoUsed: null,
                proStatus: null,
                raw: null
            },
            analysis: {
                basic: null,
                pro: null,
                confidence: {},
                warnings: []
            },
            generativeText: {
                provider: 'pending',
                prompt: null,
                suggestion: null,
                // 文字建議 v4 仍保留兩個給 render service 使用的欄位；
                // 初始資料包也先建立，避免尚未產生建議時欄位消失。
                renderPromptEn: null,
                fluxPromptEn: null,
                model: null,
                status: 'pending',
                error: null
            },
            render: {
                status: 'pending',
                provider: 'pending',
                replicateTempUrl: null,
                afterImageUrl: null,
                afterImageDataUrl: null,
                savedImageId: null,
                error: null,
                beforeImageId: null,
                afterImageId: null,
                styleId: null,
                ollamaPrompt: null,
                makeupOutput: null
            },
            recommendations: {
                style: null,
                products: [],
                tips: [],
                ads: []
            },
            model: {
                faceAnalyzerVersion: mode === 'pro' ? 'PRO' : 'BASIC',
                faceModelConnected: true,
                makeupModelConnected: false
            },
            limits: {
                storageMaxEdge: ImagePipeline.storageMaxEdge,
                storageJpegQuality: ImagePipeline.storageJpegQuality,
                maxDraftCount: 20
            },
            async: {
                jobId: null,
                progress: 0,
                stage: null,
                startedAt: null,
                completedAt: null,
                durationMs: null,
                error: null
            }
        };
    },

    update(pkg, patch) {
        return { ...(pkg || this.create({ mode: 'basic' })), ...patch, updatedAt: new Date().toISOString() };
    },

    fromRawFaceAnalysis(raw, mode) {
        const skin = raw?.['膚色'] || {};
        const proStatusRaw = raw?.['精細分析狀態'] || null;
        const sym = raw?.['臉部對稱性'] || null;
        const sideNose = raw?.['側臉鼻型'] || raw?.['鼻型_側面'] || null;
        return {
            version: mode === 'pro' ? 'PRO' : 'BASIC',
            faceShape: raw?.['臉型'] || null,
            browShape: raw?.['眉型'] || null,
            eyeShape: raw?.['眼型'] || null,
            noseFront: raw?.['鼻型'] || null,
            noseSide: (sideNose && typeof sideNose === 'object') ? (sideNose.label || null) : sideNose,
            lipShape: raw?.['嘴型'] || null,
            skinTone: {
                season: skin['四季型'] || null,
                level: skin['膚色分級'] || null,
                lab: skin['LAB'] || null,
                // PRO 自 2026-08-05 起不再做正面+側面平均，所以後端不會再送 LAB來源。
                // 沒有這個鍵就代表膚色來自正面照，跟後端 analysis_package.py 的預設一致。
                labSource: skin['LAB來源'] || '正面照',
                // 頭髮或陰影蓋住臉頰時膚色會算錯。臉部分析端會標記，但**送去商品推薦的
                // 是這個 JS 建的資料包**，不是後端 analysis_package.py 那份——先前只補了
                // 後端那條路，這裡沒帶，於是旗標從來沒到過推薦端，整個「不可信就別比色號」
                // 的設計在前端這條路上是空的。欄位缺漏時視為可信，維持既有行為。
                labReliable: (skin['可信度'] || {}).reliable !== false,
                labReliability: skin['可信度'] || null
            },
            lipLab: raw?.['嘴唇_LAB'] || null,
            symmetry: sym ? {
                score: sym.score ?? null,
                eyeOpenRatio: sym.eyeOpenRatio ?? null,
                noseDeviation: sym.noseDeviation ?? null,
                mouthSymmetry: sym.mouthSymmetry ?? null
            } : null,
            // 後端有明講的布林就用它。先前是拿「多角度照片」這句**顯示文案**去比前綴，
            // 而那句話會隨功能描述改寫——2026-08-05 它從「已接收，膚色已雙角度平均」
            // 改成「已接收，用於側臉鼻型（膚色僅採正面照）」，只是剛好還以「已接收」
            // 開頭才沒出事。舊後端沒有這個鍵，才退回看文案。
            sidePhotoUsed: typeof raw?.['側面照已使用'] === 'boolean'
                ? raw['側面照已使用']
                : (proStatusRaw ? proStatusRaw['多角度照片']?.startsWith('已接收') : null),
            proStatus: proStatusRaw,
            raw: raw || null
        };
    }
};

// Ollama 有時候會把「第一部分：中文建議」「第二部分：英文渲染指令」黏在同一串文字裡回傳，
// 後端拆分不穩定，偶爾會漏拆。這裡在前端再做一層保護：只要偵測到「第二部分」標記，
// 就把它從中文建議裡切掉，切下來的內容轉去當渲染指令用，不會顯示在建議畫面上。
function splitOllamaTwoPartSuggestion(rawText) {
    const text = String(rawText || '');
    const match = text.match(/(?:^|\n)\s*第[二2]部分[^\n]*\n?/);
    if (!match) return { suggestion: text.trim(), leakedEnglishPart: '' };
    const suggestion = text.slice(0, match.index).trim();
    const leakedEnglishPart = text.slice(match.index + match[0].length).trim();
    return { suggestion, leakedEnglishPart };
}

function buildRenderPrompt(faceAnalysis, styleId, suggestion = '', ollamaRenderPromptEn = '', userCustomPrompt = '') {
    // 只剩兩塊：Ollama 自己生成的妝容指令 + 我們固定的「不要改人物」鎖定句
    const customInstruction = String(userCustomPrompt || '').trim();
    const makeupInstruction = customInstruction || String(ollamaRenderPromptEn || '').trim() || 'Apply natural everyday makeup.';

    // 使用者自己寫的 prompt 通常已經自帶身分鎖，再疊一段 identityLock 會讓「不要改」的句子
    // 壓過妝容指令，gpt-image-2 就乾脆輸出近乎原圖（妝完全上不去）。自訂時原封不動送出。
    if (customInstruction) return customInstruction;

    const identityLock = [
        `Create a photorealistic camera photo edit, not AI art.`,
        `Keep the original photo quality, lens perspective, lighting, shadows, skin texture, pores, fine lines, and natural facial asymmetry.`,
        `Do not change this person's identity or appearance.`,
        `Keep face shape, facial structure, eye shape, nose, lips, skin tone, skin texture, pores, fine lines, wrinkles, and hair completely identical to the original photo.`,
        `Preserve the subject's original gender and biological sex characteristics; do not feminize or masculinize the face, and keep any facial hair, brow thickness, and jawline unchanged.`,
        `Keep the original hairstyle, hair length, and hairline exactly identical; do not add, lengthen, shorten, or restyle the hair.`,
        `Do not smooth, airbrush, whiten, reshape, slim the face, enlarge eyes, alter age, alter ethnicity, or beautify facial features beyond applying makeup.`,
        `Keep the exact same pose, posture, body position, head angle, hand position, gesture, and action as the original photo — do not let the person move, turn, or change stance.`,
        `Keep clothing, background, lighting, camera angle, camera framing, and expression completely identical to the original photo.`,
        `Avoid plastic skin, porcelain skin, doll-like face, CGI, 3D render, illustration, painting, glamour retouch, studio portrait, or beauty filter effects.`,
        `This must be the exact same person in the exact same pose, only wearing makeup — nothing else about the photo should change.`,
    ].join(' ');

    return `${makeupInstruction} ${identityLock}`;
}

const AnalysisDraft = {
    _key: 'beautyAnalysisDraft',
    _ttlMs: 30 * 60 * 1000,
    save(pkg) {
        localStorage.removeItem(this._key);
        sessionStorage.setItem(this._key, JSON.stringify({ expiresAt: Date.now() + this._ttlMs, data: pkg }));
    },
    load() {
        localStorage.removeItem(this._key);
        try {
            const stored = JSON.parse(sessionStorage.getItem(this._key) || 'null');
            if (!stored || Number(stored.expiresAt) <= Date.now()) {
                this.clear();
                return null;
            }
            return stored.data || null;
        } catch (_) {
            this.clear();
            return null;
        }
    },
    clear() {
        localStorage.removeItem(this._key);
        sessionStorage.removeItem(this._key);
    }
};

// ═══ Auth 模組 ═══
const Auth = {
    _membersKey: 'beautyRegisteredMembers',
    _email(email) { return String(email || '').trim().toLowerCase(); },
    getRegisteredMember(email) {
        try {
            const members = JSON.parse(localStorage.getItem(this._membersKey) || '{}');
            return members[this._email(email)] || null;
        } catch (_) { return null; }
    },
    saveRegisteredMember(profile) {
        if (!profile?.email || !profile?.name || profile.name === '訪客') return;
        let members = {};
        try { members = JSON.parse(localStorage.getItem(this._membersKey) || '{}'); } catch (_) {}
        // 不把密碼明碼存進 localStorage（登入一律走 API 驗證，本機不需要留密碼）；順便清掉舊資料殘留的密碼
        const existing = { ...(members[this._email(profile.email)] || {}) };
        delete existing.password;
        const { password, ...safe } = profile;
        members[this._email(profile.email)] = { ...existing, ...safe };
        localStorage.setItem(this._membersKey, JSON.stringify(members));
    },
    getUser()  { return sessionStorage.getItem('beautyUser') || ''; },
    // base64 頭像只保存在記憶體，避免將臉部圖片寫入 sessionStorage。
    _volatileAvatar: '',
    _isPersistableAvatar(value) {
        const v = String(value || '');
        // http(s) 或同源 Gateway 媒體路徑可以存；data: base64 一律不存。
        return !!v && !v.startsWith('data:');
    },
    getProfile() {
        let profile = {};
        try { profile = JSON.parse(sessionStorage.getItem('beautyProfile') || '{}') || {}; } catch (_) {}
        if (Object.prototype.hasOwnProperty.call(profile, 'password')) {
            const { password, ...safeProfile } = profile;
            profile = safeProfile;
            try { sessionStorage.setItem('beautyProfile', JSON.stringify(profile)); } catch (_) {}
        }
        // SPA 導覽時補回暫存頭像，但不寫入瀏覽器儲存空間。
        if (!this._isPersistableAvatar(profile.avatar) && this._volatileAvatar) {
            profile = { ...profile, avatar: this._volatileAvatar };
        }
        return profile;
    },
    setProfile(profile) {
        const safeProfile = { ...(profile || {}) };
        delete safeProfile.password;
        // base64 頭像不落地：留在記憶體，storage 裡只保留可持久化的頭像網址。
        if (Object.prototype.hasOwnProperty.call(safeProfile, 'avatar') && !this._isPersistableAvatar(safeProfile.avatar)) {
            this._volatileAvatar = String(safeProfile.avatar || '');
            delete safeProfile.avatar;
        } else if (this._isPersistableAvatar(safeProfile.avatar)) {
            this._volatileAvatar = '';  // 已有正式網址，清掉暫存的 base64
        }
        sessionStorage.setItem('beautyProfile', JSON.stringify(safeProfile));
        if (safeProfile?.name) sessionStorage.setItem('beautyUser', safeProfile.name);
        this.saveRegisteredMember(safeProfile);
    },
    isLoggedIn() { return !!this.getUser(); },
    clearSession() {
        // 登出時列舉並清除全部 sessionStorage，避免遺漏新增的敏感資料。
        try {
            const keys = [];
            for (let i = 0; i < sessionStorage.length; i++) {
                const key = sessionStorage.key(i);
                if (key) keys.push(key);
            }
            keys.forEach(key => sessionStorage.removeItem(key));
        } catch (_) {
            // 隱私模式等情況可能存取失敗；至少把已知的敏感項目移除
            ['beautyUser', 'beautyProfile', 'beautyAuthCreds', 'beautyAnalysisDraft',
             'memberAccessToken', 'gatewaySessionToken'].forEach(key => {
                try { sessionStorage.removeItem(key); } catch (_) {}
            });
        }
    },

    // 登出時清除目前帳號的臉部資料，以及未分帳號的舊版資料。
    clearAccountLocalPII(email) {
        try {
            const em = String(email || '').trim().toLowerCase();
            if (em) localStorage.removeItem('beautySuggestions_' + em);
            ['beautyAnalysisFeedback', 'beautyHistory', 'beautyFav', 'beautyCart']
                .forEach(key => localStorage.removeItem(key));
            // 純文字分析紀錄按帳號隔離，登出後保留，讓會員再次登入仍能查閱。
            // 照片與分析原始數值不在這個鍵裡；含照片的收藏妝容仍照上方規則清除。
        } catch (_) {}
    },

    logout() {
        const gateway = (typeof Api !== 'undefined' && Api.config?.services?.aiGateway) || { baseUrl: '', logoutPath: '/auth/logout' };
        // profile 還在時先清當前帳號的本機 PII，clearSession 之後 email 就讀不到了
        try { this.clearAccountLocalPII((this.getProfile() || {}).email); } catch (_) {}
        fetch(`${gateway.baseUrl}${gateway.logoutPath}`, { method: 'POST', credentials: 'include' })
            .catch(() => null)
            .finally(() => {
                try {
                    if (typeof BroadcastChannel === 'function') {
                        const channel = new BroadcastChannel('decorate-me-auth');
                        channel.postMessage({ type: 'logged-out' });
                        channel.close();
                    }
                } catch (_) {}
                this.clearSession();
                location.reload();
            });
    },
};

// ═══ Admin 權限原型：之後可改接會員資料庫 API ═══
const AdminStore = {
    _productsKey: 'beautyAdminProducts',
    _overridesKey: 'beautyAdminProductOverrides',
    _defaultPages: ['dashboard', 'analysisBasic', 'style', 'products', 'favorites', 'history', 'compare', 'suggestion', 'profile'],
    _email(email) { return String(email || '').trim().toLowerCase(); },
    _syncCurrentProfile(email, patch) {
        const key = this._email(email);
        const current = Auth.getProfile();
        if (!key || this._email(current?.email) !== key) return;
        Auth.setProfile({ ...current, ...patch });
    },
    _normalizeAllowedPages(profile) {
        const raw = profile?.allowedPages || profile?.permission?.allowedPages;
        if (Array.isArray(raw) && raw.length) return [...new Set(raw)];
        const role = profile?.role || profile?.permission?.role;
        return role === 'admin' ? [...this._defaultPages, 'admin'] : [...this._defaultPages];
    },
    permissionSnapshot(profile) {
        const p = profile || Auth.getProfile() || {};
        return {
            role: p.role || p.permission?.role || 'member',
            status: p.status || p.permission?.status || 'active',
            allowedPages: this._normalizeAllowedPages(p),
            vipRequested: !!(p.vipRequested || p.permission?.vipRequested),
            renderQuota: p.renderQuota || p.permission?.renderQuota || null
        };
    },
    isAdminProfile(profile) {
        return profile?.role === 'admin' || profile?.level === '管理員';
    },
    isVip(profile) {
        return ['VIP會員', 'PRO會員'].includes(profile?.level) || this.isAdminProfile(profile);
    },
    canUseProAnalysis(profile) {
        const p = profile || Auth.getProfile();
        const permission = this.permissionSnapshot(p);
        if (permission.status === 'suspended') return false;
        if (this.isVip(p)) return true;
        return permission.allowedPages.includes('analysisPro');
    },
    _isGuestProfile(profile) {
        const p = profile || Auth.getProfile();
        return !this._email(p?.email);
    },
    hasUnlimitedRender(profile) {
        const p = profile || Auth.getProfile();
        if (this.isAdminProfile(p)) return true;
        const permission = this.permissionSnapshot(p);
        if (permission.status === 'suspended') return false;
        return this.isVip(p) || permission.allowedPages.includes('unlimitedRender');
    },
    getDailyRenderLimit(profile) {
        const p = profile || Auth.getProfile();
        if (this._isGuestProfile(p)) return 0;
        // 權限要排在 renderQuota 前面。
        //
        // 這兩行原本是反的：只要會員資料庫在登入時回了一個 renderQuota.dailyLimit，
        // 第一個 return 就成立，hasUnlimitedRender() 永遠跑不到——於是管理員在後台
        // 把某個帳號改成無限渲染、資料也確實存進資料庫了，重新登入之後畫面上的
        // 每日上限還是原本那個數字，而且沒有任何錯誤可以讓人追。
        //
        // getRemainingRenders 本來就是權限優先，兩者順序相反還會湊出
        // 「剩餘 ∞ 次 / 每日上限 3 次」這種自相矛盾的顯示。
        if (this.hasUnlimitedRender(p)) return Infinity;
        const quota = this.permissionSnapshot(p).renderQuota;
        if (quota && Number.isFinite(Number(quota.dailyLimit))) return Number(quota.dailyLimit);
        return null;
    },
    canRender(profile) {
        const p = profile || Auth.getProfile();
        if (this._isGuestProfile(p)) return false;
        const permission = this.permissionSnapshot(p);
        if (permission.status === 'suspended') return false;
        return true;
    },
    getRemainingRenders(profile) {
        if (this._isGuestProfile(profile)) return 0;
        if (this.hasUnlimitedRender(profile)) return Infinity;
        const quota = this.permissionSnapshot(profile).renderQuota;
        if (quota && Number.isFinite(Number(quota.remaining))) return Math.max(0, Number(quota.remaining));
        return null;
    },
    setMemberLevel(email, level) {
        this._syncCurrentProfile(email, { level });
    },
    isAdmin() {
        // 只採信後端 session 驗證的角色；本機 profile 不能授予管理員權限。
        return typeof Api.isVerifiedAdmin === 'function' && Api.isVerifiedAdmin();
    },
    defaultPermissions(role) {
        const allowedPages = role === 'admin' ? [...this._defaultPages, 'admin'] : [...this._defaultPages];
        return { role: role || 'member', status: 'active', allowedPages };
    },
    getPermission(email, profile) {
        const snapshot = this.permissionSnapshot(profile || (this._email(email) === this._email(Auth.getProfile()?.email) ? Auth.getProfile() : null));
        if (snapshot.allowedPages.length) return snapshot;
        return this.defaultPermissions(this.isAdminProfile(profile || { email }) ? 'admin' : 'member');
    },
    setPermission(email, patch) {
        this._syncCurrentProfile(email, patch);
    },
    failureReason(member) {
        const permission = member?.permission || this.permissionSnapshot(member);
        if (permission.status === 'suspended') return '登入失敗：帳號已停權';
        const blocked = this._defaultPages.filter(page => !['dashboard', 'profile'].includes(page) && !permission.allowedPages.includes(page));
        if (blocked.length) return `功能受限：${blocked.length} 個功能未開啟`;
        return '正常';
    },
    canAccess(page, profile) {
        const p = profile || Auth.getProfile();
        if (this.isAdminProfile(p)) return true;
        const permission = this.permissionSnapshot(p);
        if (permission.status === 'suspended') return false;
        const allowed = permission.allowedPages;
        // 商品推薦是公開瀏覽頁：未登入訪客都看得到，登入會員不該因為後台沒勾「商品」
        // 這一項就被擋在門外（會員反而比訪客受限）。逛商品不需要特別權限。
        //
        // 關於我們同理，而且更純粹：它是一頁介紹，沒有任何會員資料或功能。
        // 2026-08-29 新增這頁時漏了這裡，於是點下去跳「此帳號目前沒有使用此功能的權限，
        // 請聯繫管理員」——一個只是在講品牌故事的頁面，說得像是被停權了。
        // allowedPages 由後台勾選，新頁面預設不在裡面，所以**每新增一個公開頁都要回來加**。
        if (page === 'products' || page === 'about') return true;
        if (page === 'analysis') return allowed.includes('analysisBasic') || allowed.includes('analysisPro') || this.isVip(p);
        return allowed.includes(page);
    },
    listMembers() {
        let members = {};
        try { members = JSON.parse(localStorage.getItem(Auth._membersKey) || '{}'); } catch (_) {}
        const current = Auth.getProfile();
        if (current?.email) members[this._email(current.email)] = { ...(members[this._email(current.email)] || {}), ...current };
        return Object.keys(members).map(email => {
            const profile = { ...members[email], email: members[email].email || email };
            const permission = this.permissionSnapshot(profile);
            return { ...profile, email, permission };
        }).sort((a, b) => String(a.email).localeCompare(String(b.email)));
    },
    listProducts() {
        try { return JSON.parse(localStorage.getItem(this._productsKey) || '[]'); }
        catch (_) { return []; }
    },
    saveProducts(products) {
        localStorage.setItem(this._productsKey, JSON.stringify(products || []));
    },
    addProduct(product) {
        const products = this.listProducts();
        const id = product.id || `admin-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
        const row = {
            id,
            cat: product.cat,
            name: product.name,
            price: product.price,
            img: product.img || '',
            desc: product.desc || '',
            shades: product.shades || [],
            status: product.status || 'active',
            source: 'admin'
        };
        products.unshift(row);
        this.saveProducts(products);
        return row;
    },
    // 內建 demo 商品（js/data.js 的 ALL_PRODUCTS）本身不能改，編輯時把差異存在這裡，讀取時再疊加回去
    getOverrides() {
        try { return JSON.parse(localStorage.getItem(this._overridesKey) || '{}'); }
        catch (_) { return {}; }
    },
    saveOverrides(map) {
        localStorage.setItem(this._overridesKey, JSON.stringify(map || {}));
    },
    updateProduct(id, patch) {
        const products = this.listProducts();
        const idx = products.findIndex(p => String(p.id) === String(id));
        if (idx > -1) {
            products[idx] = { ...products[idx], ...patch };
            this.saveProducts(products);
            return products[idx];
        }
        const overrides = this.getOverrides();
        overrides[id] = { ...(overrides[id] || {}), ...patch };
        this.saveOverrides(overrides);
        return { id, ...overrides[id] };
    }
};

// ═══ 會員點數 / 打卡 / 主題商店 Demo：正式版可改接會員資料庫 API ═══
const MemberRewards = {
    _pointsKey: 'beautyMemberPoints',
    _ledgerKey: 'beautyPointLedger',
    _checkinKey: 'beautyDailyCheckins',
    _themesKey: 'beautyUnlockedThemes',
    _activeThemeKey: 'beautyActiveTheme',
    _email(email) {
        const raw = String(email || Auth.getProfile()?.email || '').trim().toLowerCase();
        return raw || 'guest';
    },
    _today() { return new Date().toISOString().slice(0, 10); },
    _load(key, fallback) {
        try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); }
        catch (_) { return fallback; }
    },
    _save(key, value) { localStorage.setItem(key, JSON.stringify(value)); },
    themes: [
        { id: 'classic', name: '經典奶茶', cost: 0, swatches: ['#F7F0E6', '#C49A62', '#4A3438'], desc: '預設會員中心主題' },
        // id 維持 'rose'：資料庫用它記錄已購買，改了會員就失去已兌換的主題。
        { id: 'rose', name: '銀霧', cost: 80, swatches: ['#0A0D12', '#C6CCD5', '#9AA1AA'], desc: '高級冷銀與精密介面動態' },
        // id 維持 'jade'：只更換顯示名稱，避免既有會員主題資料失效。
        { id: 'jade', name: '動漫風', cost: 120, swatches: ['#DDEEE3', '#FFD873', '#F5B3B7'], desc: '綠色點陣與漫畫描邊介面' },
        { id: 'noir', name: '黑金 PRO', cost: 180, swatches: ['#060607', '#C8A65E', '#71243A'], desc: '黑曜石與香檳金的貴族介面' }
    ],
    getPoints(email) {
        const points = this._load(this._pointsKey, {});
        return Number(points[this._email(email)] || 0);
    },
    setPoints(email, value) {
        const points = this._load(this._pointsKey, {});
        points[this._email(email)] = Math.max(0, Number(value) || 0);
        this._save(this._pointsKey, points);
    },
    _lifetimeKey: 'beautyMemberLifetimePoints',
    // 累計「獲得過」的點數，兌換/扣點不會讓它變少，會員等級門檻用這個算，避免花點數被降級
    getLifetimePoints(email) {
        const lifetime = this._load(this._lifetimeKey, {});
        return Number(lifetime[this._email(email)] || 0);
    },
    addPoints(email, amount, reason, meta) {
        const key = this._email(email);
        const before = this.getPoints(key);
        const delta = Number(amount) || 0;
        this.setPoints(key, before + delta);
        if (delta > 0) {
            const lifetime = this._load(this._lifetimeKey, {});
            lifetime[key] = (lifetime[key] || 0) + delta;
            this._save(this._lifetimeKey, lifetime);
        }
        const ledger = this._load(this._ledgerKey, {});
        const rows = ledger[key] || [];
        rows.unshift({
            id: `pt-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            delta,
            balance: this.getPoints(key),
            reason: reason || '點數異動',
            meta: meta || null,
            createdAt: new Date().toISOString()
        });
        ledger[key] = rows.slice(0, 60);
        this._save(this._ledgerKey, ledger);
        return this.getPoints(key);
    },
    ledger(email) {
        return this._load(this._ledgerKey, {})[this._email(email)] || [];
    },
    // 連續簽到獎勵表：達到第 N 天當天額外加碼（跟每日 +10 疊加，不是取代）
    _streakBonusTable: { 3: 5, 7: 20, 14: 40, 30: 100 },
    _isYesterday(dateStr) {
        if (!dateStr) return false;
        const yesterday = new Date();
        yesterday.setDate(yesterday.getDate() - 1);
        return dateStr === yesterday.toISOString().slice(0, 10);
    },
    nextStreakMilestone(streak) {
        const milestones = Object.keys(this._streakBonusTable).map(Number).sort((a, b) => a - b);
        return milestones.find(m => m > streak) || null;
    },
    checkinStatus(email) {
        const key = this._email(email);
        const all = this._load(this._checkinKey, {});
        const row = all[key] || {};
        // 中斷一天以上，連續天數要斷掉重算，但這裡只讀狀態不寫入，真正斷開發生在下次 checkin()
        const streak = row.date === this._today() || this._isYesterday(row.date) ? (row.streak || 0) : 0;
        return { checkedToday: row.date === this._today(), lastDate: row.date || null, streak };
    },
    // 記下「伺服器說今天打過卡了」，只寫日期與連續天數，**不發點數**。
    //
    // 舊的 checkin() 把「記錄打卡」與「發點數」綁在同一個方法裡，而發點數在前端是被禁的
    // （交接手冊 §6.2「API 失敗時不可在前端自行加點」）。移除它的呼叫端之後沒有人再寫
    // _checkinKey，但 Tasks 的 daily_checkin 判定讀的正是那個鍵——「完成今日打卡」這個
    // 任務因此永遠無法完成，也就永遠領不到獎勵。
    //
    // 拆成這一支：點數一律由伺服器計算並回傳，這裡只鏡射「哪一天打過」這個事實，
    // 讓本機的任務視圖跟伺服器一致。
    recordRemoteCheckin(email, streakFromServer) {
        const key = this._email(email);
        if (key === 'guest') return;
        const all = this._load(this._checkinKey, {});
        const prev = all[key] || {};
        const streak = Number.isFinite(Number(streakFromServer)) && Number(streakFromServer) > 0
            ? Number(streakFromServer)
            : (this._isYesterday(prev.date) ? (prev.streak || 0) + 1 : 1);
        all[key] = { date: this._today(), updatedAt: new Date().toISOString(), streak };
        this._save(this._checkinKey, all);
    },
    unlockedThemes(email) {
        const key = this._email(email);
        const all = this._load(this._themesKey, {});
        const ids = new Set(['classic', ...(all[key] || [])]);
        return Array.from(ids);
    },
    hasTheme(email, themeId) {
        return this.unlockedThemes(email).includes(themeId);
    },
    // 伺服器端兌換成功後，把解鎖狀態同步回本機。
    // 少了這步，setActiveTheme 會因為 hasTheme 不通過而靜默失敗 —— 點數扣了、主題卻套用不上。
    unlockTheme(email, themeId) {
        const key = this._email(email);
        if (key === 'guest' || !themeId) return false;
        const all = this._load(this._themesKey, {});
        const owned = all[key] || [];
        if (!owned.includes(themeId)) {
            all[key] = [...owned, themeId];
            this._save(this._themesKey, all);
        }
        return true;
    },
    redeemTheme(email, themeId) {
        const key = this._email(email);
        if (key === 'guest') return { ok: false, message: '請先登入會員再兌換主題。' };
        const theme = this.themes.find(t => t.id === themeId);
        if (!theme) return { ok: false, message: '找不到這個主題。' };
        if (this.hasTheme(key, themeId)) return { ok: true, already: true, message: '你已經擁有這個主題。' };
        if (this.getPoints(key) < theme.cost) return { ok: false, message: `點數不足，還差 ${theme.cost - this.getPoints(key)} 點。` };
        const all = this._load(this._themesKey, {});
        all[key] = [...(all[key] || []), themeId];
        this._save(this._themesKey, all);
        this.addPoints(key, -theme.cost, `兌換主題：${theme.name}`, { type: 'redeem_theme', themeId });
        return { ok: true, theme };
    },
    getActiveTheme(email) {
        const all = this._load(this._activeThemeKey, {});
        const id = all[this._email(email)] || 'classic';
        return this.hasTheme(email, id) ? id : 'classic';
    },
    setActiveTheme(email, themeId) {
        if (!this.hasTheme(email, themeId)) return false;
        const all = this._load(this._activeThemeKey, {});
        all[this._email(email)] = themeId;
        this._save(this._activeThemeKey, all);
        this.applyActiveTheme(email);
        return true;
    },
    applyActiveTheme(email) {
        if (typeof document === 'undefined') return;
        const themeId = this.getActiveTheme(email);
        document.body.dataset.memberTheme = themeId;
    }
};

// ═══ 推薦碼 Demo：註冊時自動綁定推薦人，完成註冊即發點（防刷留待正式版再補）══
const Referral = {
    _usedKey: 'beautyReferralUsed',
    _rewardPoints: 50,
    _email(email) { return String(email || '').trim().toLowerCase(); },
    _load(key, fallback) {
        try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); }
        catch (_) { return fallback; }
    },
    _save(key, value) { localStorage.setItem(key, JSON.stringify(value)); },
    // 推薦碼是 email 的固定雜湊值，不用額外存表，任何人只要知道 email 就能算出同一組碼
    myCode(email) {
        const key = this._email(email);
        if (!key || key === 'guest') return '';
        let hash = 0;
        for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
        return hash.toString(36).toUpperCase().padStart(6, '0').slice(-6);
    },
    // 反查推薦碼屬於哪個 email：只能在「已知會員」清單裡找，找不到就當作無效碼
    _knownEmails() {
        const emails = new Set();
        try {
            const members = JSON.parse(localStorage.getItem(Auth._membersKey) || '{}');
            Object.keys(members).forEach(e => emails.add(e));
        } catch (_) {}
        const current = Auth.getProfile()?.email;
        if (current) emails.add(this._email(current));
        return Array.from(emails);
    },
    findEmailByCode(code) {
        const target = String(code || '').trim().toUpperCase();
        if (!target) return null;
        return this._knownEmails().find(email => this.myCode(email) === target) || null;
    },
    // 新會員完成註冊（OTP 驗證通過）當下呼叫一次；同一個帳號只會生效一次，擋掉重複套用
    applyReferral(newMemberEmail, code) {
        const newKey = this._email(newMemberEmail);
        if (!code || !newKey) return { ok: false };
        const used = this._load(this._usedKey, {});
        if (used[newKey]) return { ok: false, message: '此帳號已經使用過推薦碼。' };
        const referrerEmail = this.findEmailByCode(code);
        if (!referrerEmail) return { ok: false, message: '推薦碼不存在，註冊仍會成功，但不會發送推薦獎勵。' };
        if (referrerEmail === newKey) return { ok: false, message: '不能使用自己的推薦碼。' };
        used[newKey] = { code: String(code).toUpperCase(), referrerEmail, grantedAt: new Date().toISOString() };
        this._save(this._usedKey, used);
        MemberRewards.addPoints(referrerEmail, this._rewardPoints, '推薦新會員加入獎勵', { type: 'referral', newMemberEmail: newKey });
        return { ok: true, referrerEmail };
    },
    referredBy(email) { return this._load(this._usedKey, {})[this._email(email)] || null; },
    countReferrals(email) {
        const used = this._load(this._usedKey, {});
        const key = this._email(email);
        return Object.values(used).filter(row => row.referrerEmail === key).length;
    }
};

// ═══ PRO 付費解鎖 Demo：不串正式金流，purchase() 直接視為付款成功並自動開通 ═══
const ProSubscription = {
    _subsKey: 'beautyProSubscriptions',
    _ordersKey: 'beautyProOrders',
    _email(email) { return String(email || '').trim().toLowerCase(); },
    _load(key, fallback) {
        try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); }
        catch (_) { return fallback; }
    },
    _save(key, value) { localStorage.setItem(key, JSON.stringify(value)); },
    plans: [
        { id: 'monthly', name: 'PRO 月費方案', days: 30, price: 199 },
        { id: 'yearly', name: 'PRO 年費方案', days: 365, price: 1990 }
    ],
    getSubscription(email) {
        const row = this._load(this._subsKey, {})[this._email(email)];
        if (!row) return { active: false, expiresAt: null, daysLeft: 0, plan: null };
        const expiresAt = new Date(row.expiresAt);
        const active = expiresAt.getTime() > Date.now();
        const daysLeft = active ? Math.ceil((expiresAt.getTime() - Date.now()) / 86400000) : 0;
        return { active, expiresAt: row.expiresAt, daysLeft, plan: row.plan };
    },
    orders(email) {
        return this._load(this._ordersKey, {})[this._email(email)] || [];
    },
    // Demo 付款：呼叫這支就直接視為付款成功，沒有真正的金流串接
    purchase(email, planId) {
        return { ok: false, message: 'PRO / VIP 由你的會員方案決定，無法在此開通。' };
    },
    syncExpiry(email) {
        return this.getSubscription(email);
    }
};

// 會員等級：一般、銀卡與金卡依累計點數判定；VIP 與管理員由後台設定。
const MemberTier = {
    _ladder: [
        { id: 'general', name: '一般會員', min: 0 },
        { id: 'silver', name: '銀卡會員', min: 100 },
        { id: 'gold', name: '金卡會員', min: 300 }
    ],
    tierForPoints(lifetimePoints) {
        let current = this._ladder[0];
        for (const t of this._ladder) if (lifetimePoints >= t.min) current = t;
        return current;
    },
    nextTier(lifetimePoints) {
        return this._ladder.find(t => t.min > lifetimePoints) || null;
    },
    // VIP／管理員優先於銀金卡顯示，兩套判定互不衝突：VIP 是後台手動核發，銀金卡是點數自動累積
    describe(profile) {
        if (typeof AdminStore !== 'undefined') {
            if (AdminStore.isAdminProfile(profile)) return { id: 'admin', name: '管理員', autoTier: false };
            if (AdminStore.isVip(profile)) return { id: 'vip', name: 'PRO / VIP 會員', autoTier: false };
        }
        const lifetime = MemberRewards.getLifetimePoints(profile?.email);
        return { ...this.tierForPoints(lifetime), autoTier: true, lifetime };
    }
};

// ═══ 任務中心 Demo：新手／每日任務，完成條件沿用既有的分析/收藏/打卡/推薦紀錄 ═══
const Tasks = {
    _claimedKey: 'beautyTaskClaims',
    _email(email) { return String(email || '').trim().toLowerCase(); },
    _today() { return new Date().toISOString().slice(0, 10); },
    _load(key, fallback) {
        try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); }
        catch (_) { return fallback; }
    },
    _save(key, value) { localStorage.setItem(key, JSON.stringify(value)); },
    list: [
        { id: 'first_analysis', group: '新手任務', title: '完成第一次臉部分析', reward: 20, daily: false, check: () => (typeof History !== 'undefined' ? History.list().length > 0 : false) },
        { id: 'first_favorite', group: '新手任務', title: '收藏一件商品', reward: 10, daily: false, check: () => (typeof Fav !== 'undefined' ? Fav.list().length > 0 : false) },
        { id: 'first_referral', group: '新手任務', title: '成功推薦一位好友', reward: 20, daily: false, check: email => (typeof Referral !== 'undefined' ? Referral.countReferrals(email) > 0 : false) },
        { id: 'daily_checkin', group: '每日任務', title: '完成今日打卡', reward: 5, daily: true, check: email => MemberRewards.checkinStatus(email).checkedToday }
    ],
    _claimKey(taskId, daily) { return daily ? `${taskId}:${this._today()}` : taskId; },
    claimedMap(email) {
        const all = this._load(this._claimedKey, {});
        return all[this._email(email)] || {};
    },
    status(email) {
        const claimed = this.claimedMap(email);
        return this.list.map(task => {
            const key = this._claimKey(task.id, task.daily);
            return { ...task, done: !!task.check(email), claimed: !!claimed[key] };
        });
    },
    claim(email, taskId) {
        const key = this._email(email);
        const task = this.list.find(t => t.id === taskId);
        if (!task) return { ok: false };
        const claimKey = this._claimKey(taskId, task.daily);
        const all = this._load(this._claimedKey, {});
        const mine = all[key] || {};
        if (mine[claimKey]) return { ok: false, message: '已經領取過了。' };
        if (!task.check(key)) return { ok: false, message: '尚未完成這個任務。' };
        mine[claimKey] = true;
        all[key] = mine;
        this._save(this._claimedKey, all);
        const balance = MemberRewards.addPoints(key, task.reward, `任務獎勵：${task.title}`, { type: 'task_reward', taskId });
        return { ok: true, balance, reward: task.reward };
    }
};

// ═══ 每日使用額度（妝容建議 / 妝容渲染，兩者分開計算）═══
//
// 額度規則（2026-08-14 定案）：
//     訪客        建議 2 次、渲染 2 次
//     一般會員    建議 4 次、渲染 4 次
//     VIP / 管理員  不限
//
// **建議與渲染分開算**：兩者的成本與體感完全不同——建議是本地 Ollama 幾秒鐘，
// 渲染要 60~150 秒且會花 Replicate 的錢。共用一個計數器會讓「多看兩次建議」
// 排擠掉「生成一張妝後圖」，那不是使用者預期的取捨。
//
// ⚠ 這是**前端的額度**，存在 localStorage：使用者清掉就重置。
// 它的用途是體驗上的節流與展示，**不是安全邊界**。真正的防濫用仍然在
// 會員資料庫的 renderQuota 與 Gateway 的速率限制——伺服器回 QUOTA_EXCEEDED 時
// 那個永遠優先，見 _friendlyError 的 429 處理。
const UsageQuota = {
    _key: 'beautyUsageQuota',
    LIMITS: Object.freeze({ guest: 2, member: 4 }),
    KINDS: Object.freeze({ SUGGESTION: 'suggestion', RENDER: 'render' }),

    _today() { return new Date().toISOString().slice(0, 10); },

    // 用 email 當身分；訪客共用一個 'guest' 桶。同一台裝置換帳號時各自計數。
    _identity() {
        const profile = (typeof Auth !== 'undefined' && Auth.getProfile) ? (Auth.getProfile() || {}) : {};
        const email = String(profile.email || '').trim().toLowerCase();
        return email || 'guest';
    },

    _load() {
        try { return JSON.parse(localStorage.getItem(this._key) || '{}'); }
        catch (_) { return {}; }
    },

    limit(kind) {
        if (typeof AdminStore !== 'undefined') {
            const profile = Auth.getProfile();
            // 用 hasUnlimitedRender，不要自己判 admin 與 VIP。
            //
            // 原本這裡只認 isAdminProfile 或 isVip，而那兩個看的都是 profile.level
            // 與 role。後台的「渲染不限次數」勾選寫進的卻是 allowedPages——只有把
            // 等級一起改成 VIP會員 才會連動勾選，單獨勾那一項對這裡完全沒有作用。
            // 於是管理員在後台給了權限、資料也存進資料庫了，那個帳號重新登入之後
            // 還是每天四次，而且畫面上找不到任何線索說明為什麼。
            //
            // hasUnlimitedRender 是這三個條件的唯一定義（admin、VIP、或勾了
            // unlimitedRender），而且它會擋停權帳號。這裡跟著它走，三個地方就
            // 不會再各自對「這個人能渲染幾次」給出不同答案。
            if (AdminStore.hasUnlimitedRender?.(profile)) return Infinity;
        }
        const guest = (typeof isGuest === 'function') ? isGuest() : this._identity() === 'guest';
        return guest ? this.LIMITS.guest : this.LIMITS.member;
    },

    used(kind) {
        const all = this._load();
        const bucket = all[`${this._identity()}|${this._today()}`] || {};
        return Number(bucket[kind] || 0);
    },

    remaining(kind) {
        const limit = this.limit(kind);
        return limit === Infinity ? Infinity : Math.max(0, limit - this.used(kind));
    },

    canUse(kind) { return this.remaining(kind) > 0; },

    // 成功之後才記一次。失敗（服務掛掉、逾時）不該吃掉使用者的額度。
    record(kind) {
        if (this.limit(kind) === Infinity) return;
        const all = this._load();
        const key = `${this._identity()}|${this._today()}`;
        const bucket = all[key] || {};
        bucket[kind] = Number(bucket[kind] || 0) + 1;
        // 只留今天的：這個鍵每天一組，不清掉會無限長大。
        const today = this._today();
        const kept = { [key]: bucket };
        Object.keys(all).forEach(k => { if (k.endsWith(`|${today}`) && k !== key) kept[k] = all[k]; });
        try { localStorage.setItem(this._key, JSON.stringify(kept)); } catch (_) {}
    },
};

// ═══ 收藏模組 ═══
const Fav = {
    _key: 'beautyFav',
    list()     { return JSON.parse(localStorage.getItem(this._key) || '[]'); },
    has(id)    { return this.list().some(x => String(x) === String(id)); },
    // product 是選填的完整商品物件（要有 apiType/rawId 才能同步到組員資料庫）。
    // 本機收藏永遠是可信來源，遠端同步只是盡力而為，失敗也不影響本機功能。
    toggle(id, product) {
        const arr = this.list();
        const idx = arr.findIndex(x => String(x) === String(id));
        const nowFav = idx < 0;
        if (idx >= 0) arr.splice(idx, 1); else arr.push(id);
        localStorage.setItem(this._key, JSON.stringify(arr));
        if (product?.apiType && product?.rawId != null && typeof Auth !== 'undefined' && Auth.isLoggedIn?.() && typeof Api !== 'undefined' && Api.toggleRemoteFavorite) {
            Api.toggleRemoteFavorite(product.rawId, product.apiType).catch(() => {});
        }
        return nowFav;
    },

    // 把伺服器上的收藏併進本機。伺服器存的是 {item_id, item_type}，
    // 對應本機 id 的 `api-{item_type}-{item_id}`——與 _normalizeProduct 產生的格式一致。
    //
    // 只加不刪。本機可能有「遠端寫入失敗」的收藏（toggle 的遠端呼叫是盡力而為、
    // 錯誤被吞掉），砍掉就是靜默丟資料。代價是在 A 裝置取消過的收藏，B 裝置下次
    // 載入會復活一次；比起弄丟收藏，讓使用者再按一次取消是比較輕的錯。
    // 後端說「這幾筆收藏的商品已經不在了」。只記在記憶體裡，不寫 localStorage——
    // 它是伺服器當下的事實，不是這台裝置的設定；商品若重新上架，下次同步就會清掉。
    _unavailable: new Set(),
    setUnavailable(keys) {
        this._unavailable = new Set((keys || []).filter(Boolean));
    },
    isUnavailable(id) {
        return this._unavailable.has(String(id));
    },

    mergeRemote(rows) {
        if (!Array.isArray(rows) || !rows.length) return 0;
        const arr = this.list();
        const seen = new Set(arr.map(String));
        let added = 0;
        for (const row of rows) {
            const type = String(row?.item_type ?? row?.itemType ?? '').trim();
            const id = row?.item_id ?? row?.itemId;
            if (!type || id == null) continue;
            const key = `api-${type}-${id}`;
            if (seen.has(key)) continue;
            seen.add(key);
            arr.push(key);
            added += 1;
        }
        if (added) localStorage.setItem(this._key, JSON.stringify(arr));
        return added;
    }
};

// 臉部分析回饋只記錄文字標籤，不保存照片。
// 回饋可指出模型常出錯的類別，但不能直接當成影像訓練資料。
const AnalysisFeedback = {
    _key: 'beautyAnalysisFeedback',
    // 與 models/basic_features_roi/*_classes.json 一致。順序照模型的類別順序，
    // 不要自己重排——對照 log 與訓練資料都用那個順序。
    OPTIONS: Object.freeze({
        '臉型': ['圓形臉', '心形臉', '方形臉', '長形臉', '鵝蛋臉'],
        // 2026-08-26：補上「挑眉」。它在 08-24 就進了模型（brow_shape_classes.json
        // 是四類），但這裡沒跟著加，所以使用者連把判斷改成挑眉的選項都沒有——
        // 模型最需要回饋的那一類，永遠收不到任何修正。順序照模型的類別順序。
        '眉型': ['一字眉', '彎月眉', '挑眉', '落尾眉'],
        // 選項必須與模型分類表一致，避免送出後端不認得的標籤。
        //
        // 2026-08-24：這裡原本多一個「細長眼」。它在訓練端早就併進鳳眼了
        // （見 prepare_roi_cache.LABEL_ALIASES），線上的 eye_shape_classes.json 是
        // ['下垂眼','圓眼','桃杏眼','鳳眼'] 四類。使用者選到細長眼時，後端 validate()
        // 會把**整包修正**退回，訊息正是「前端選項可能與模型分類表不同步」——
        // 那條訊息就是為這種情況寫的，而它真的發生了。
        '眼型': ['下垂眼', '圓眼', '桃杏眼', '鳳眼'],
        // 窄鼻已合併到標準鼻。
        '鼻型': ['寬鼻', '標準鼻'],
        // M 型唇已合併到花瓣唇。
        '嘴型': ['厚唇', '微笑唇', '花瓣唇', '薄唇'],
        // PRO 側臉鼻型：**另一顆模型、另一套分類法**，跟上面的「鼻型」（正面，兩類）
        // 完全不重疊，兩邊的類別不能互換。只有 PRO 且拿得到側臉結果時才會出現在面板上
        // （renderAnalysisFeedback 依 result 有沒有值來決定顯示哪幾列）。
        // 對照 models/pro_nose_side/nose_shape_side_classes.json；朝天鼻已併入翹鼻。
        '側臉鼻型': ['塌鼻', '直挺鼻', '翹鼻', '蒜頭鼻', '駝峰鼻'],
    }),
    list() {
        try { return JSON.parse(localStorage.getItem(this._key) || '[]'); }
        catch (_) { return []; }
    },
    // 同一個分析包只留一筆：使用者改了又改，最後那次才是他的意思。
    save(packageId, predicted, corrections) {
        const rows = this.list().filter(row => row.packageId !== packageId);
        rows.push({
            packageId: packageId || null,
            predicted: predicted || {},
            corrections: corrections || {},   // 只放使用者實際改過的欄位
            confirmed: Object.keys(corrections || {}).length === 0,
            createdAt: new Date().toISOString(),
        });
        // 上限避免無限成長；端點到位後會改成送出即清除
        localStorage.setItem(this._key, JSON.stringify(rows.slice(-50)));
        return rows.length;
    },
    forPackage(packageId) {
        return this.list().find(row => row.packageId === packageId) || null;
    }
};

// 購物車先存本機；會員登入後再背景同步，訪客則維持本機模式。
const Cart = {
    _key: 'beautyCart',
    _pushTimer: null,
    // 登入時只合併一次訪客購物車，其餘同步以伺服器資料為準。
    _mergeGuestOnce: false,
    list() {
        try { return JSON.parse(localStorage.getItem(this._key) || '[]'); }
        catch (_) { return []; }
    },
    // 只寫本機、不同步：套用伺服器來的權威資料時用，避免又把剛拉回來的東西推回去。
    _setLocal(items) { localStorage.setItem(this._key, JSON.stringify(items)); },
    // 使用者操作造成的變更：寫本機並排程同步回伺服器。
    save(items) { this._setLocal(items); this._schedulePush(); },
    add(id) {
        const items = this.list();
        const row = items.find(item => String(item.id) === String(id));
        if (row) row.qty += 1;
        else items.push({ id, qty: 1 });
        this.save(items);
        return items;
    },
    change(id, delta) {
        const items = this.list();
        const row = items.find(item => String(item.id) === String(id));
        if (row) row.qty = Math.max(0, row.qty + delta);
        this.save(items.filter(item => item.qty > 0));
    },
    // 整筆移除。已下架的商品只剩這個操作——加減數量沒有意義，商品不在了。
    remove(id) {
        this.save(this.list().filter(item => String(item.id) !== String(id)));
    },
    // 只數買得到的。已下架的商品仍留在購物車裡（那是使用者的資料），
    // 但把它們算進「共 N 件」會讓徽章上的數字跟結帳時的數量對不起來，
    // 而那個落差沒有任何地方解釋得了。
    count() {
        return this.list()
            .filter(item => item.unavailable !== true)
            .reduce((sum, item) => sum + item.qty, 0);
    },

    // 只有登入的真實會員才同步；訪客沒有 email，維持純本機。
    _canSync() {
        return typeof Auth !== 'undefined' && Auth.isLoggedIn && Auth.isLoggedIn()
            && !!((Auth.getProfile && Auth.getProfile()) || {}).email
            && typeof Api !== 'undefined' && !!Api.saveRemoteCart;
    },
    // 合併 500ms 內的多次快速加減，只推最後一次整台車，省請求也避免中間態互相覆蓋。
    _schedulePush() {
        if (!this._canSync()) return;
        // 無計時器的環境（如 headless smoke test 沙箱）直接略過背景同步；瀏覽器一定有計時器。
        if (typeof setTimeout !== 'function') return;
        if (typeof clearTimeout === 'function') clearTimeout(this._pushTimer);
        this._pushTimer = setTimeout(() => {
            Api.saveRemoteCart(this.list()).catch(() => {});
        }, 500);
    },
    // 把伺服器購物車併進本機並回傳結果。
    //   sum=true ：同商品數量相加（登入時合併訪客車，見 _mergeGuestOnce）。
    //   sum=false：以伺服器為準直接取代（重載／換裝置還原）。
    mergeServer(serverItems, sum) {
        // unavailable 跟著 id 一起留在本機：畫面要據它停用結帳與商品操作。
        // **不要把這些項目刪掉**——那是使用者自己放進去的東西，要不要移除由她決定。
        const server = (Array.isArray(serverItems) ? serverItems : [])
            .map(it => ({
                id: String(it.id ?? it.item_id ?? ''),
                qty: Math.max(1, parseInt(it.qty, 10) || 1),
                unavailable: it?.unavailable === true,
            }))
            .filter(it => it.id);
        if (!sum) { this._setLocal(server); return server; }
        const byId = new Map(server.map(it => [it.id, { ...it }]));
        for (const it of this.list()) {
            const id = String(it.id);
            const qty = Math.max(1, parseInt(it.qty, 10) || 1);
            if (byId.has(id)) byId.get(id).qty += qty;
            else byId.set(id, { id, qty, unavailable: it?.unavailable === true });
        }
        const merged = [...byId.values()];
        this._setLocal(merged);
        return merged;
    }
};

// 分析紀錄模組。
const History = {
    // 每個帳號分開保存文字摘要，不儲存照片或模型原始數值。
    _legacyKey: 'beautyHistory',
    _accountKey() {
        const p = (typeof Auth !== 'undefined' && Auth.getProfile) ? Auth.getProfile() : null;
        const em = (p && p.email) ? String(p.email).trim().toLowerCase() : 'guest';
        return 'beautyHistory_' + em;
    },
    // 使用白名單挑選可保存欄位，避免新欄位意外被寫入。
    _textOnly(record) {
        const r = record || {};
        const skin = r['膚色'] || {};
        const sideNose = r['側臉鼻型'] || r['鼻型_側面'] || null;
        return {
            analysisPackageId: r.analysisPackageId || null,
            mode: r.mode || r.analyzeMode || null,          // basic / pro
            '臉型': r['臉型'] || null,
            '眉型': r['眉型'] || null,
            '眼型': r['眼型'] || null,
            '鼻型': r['鼻型'] || null,
            '側臉鼻型': (sideNose && typeof sideNose === 'object') ? (sideNose.label || null) : sideNose,
            '嘴型': r['嘴型'] || null,
            '膚色分級': skin['膚色分級'] || null,
            '四季型': skin['四季型'] || null
        };
    },
    list() {
        try {
            const own = JSON.parse(localStorage.getItem(this._accountKey()) || '[]');
            if (own.length) return own;
            // 第一次讀取時將舊版全域紀錄搬到目前帳號。
            const legacy = JSON.parse(localStorage.getItem(this._legacyKey) || '[]');
            if (legacy.length) {
                const migrated = legacy.map(row => ({ ...this._textOnly(row), timestamp: row.timestamp }));
                localStorage.setItem(this._accountKey(), JSON.stringify(migrated));
                localStorage.removeItem(this._legacyKey);
                return migrated;
            }
            return [];
        } catch (_) { return []; }
    },
    add(record) {
        const arr = this.list();
        arr.unshift({ ...this._textOnly(record), timestamp: new Date().toISOString() });
        try {
            localStorage.setItem(this._accountKey(), JSON.stringify(arr));
            return true;
        } catch (err) {
            // 多半是 localStorage 滿了。原本這裡直接吞掉，於是那次分析靜默消失——
            // 使用者以為記錄下來了，回頭看卻沒有，而且沒有任何跡象。
            //
            // 丟掉最舊的幾筆再試一次：留下新的比整批寫不進去好，而且分析紀錄本來
            // 就是愈近期愈有用。真的還是寫不進去才回 false，讓呼叫端知道。
            for (const keep of [Math.floor(arr.length / 2), 20, 5]) {
                try {
                    localStorage.setItem(this._accountKey(), JSON.stringify(arr.slice(0, keep)));
                    console.warn('分析紀錄空間不足，已保留最近', keep, '筆');
                    return true;
                } catch (_) { /* 再縮小 */ }
            }
            console.error('分析紀錄寫入失敗', err);
            return false;
        }
    },
    // 五官修正後同步更新對應的分析紀錄。
    applyCorrections(packageId, corrections) {
        const fields = Object.keys(corrections || {});
        if (!packageId || !fields.length) return;
        const arr = this.list();
        let touched = false;
        arr.forEach(row => {
            if (row.analysisPackageId !== packageId) return;
            fields.forEach(field => { row[field] = corrections[field]; });
            touched = true;
        });
        if (touched) localStorage.setItem(this._accountKey(), JSON.stringify(arr));
    }
};
