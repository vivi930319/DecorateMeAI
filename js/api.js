// 無登入 session 時清除所有訪客活動資料，確保每次開新分頁都是乾淨狀態
(function () {
    if (!sessionStorage.getItem('beautyUser')) {
        ['beautyAnalysisDraft', 'beautyFav', 'beautyCart', 'beautyHistory', 'beautySuggestions'].forEach(
            k => localStorage.removeItem(k)
        );
    }
})();

// ═══ API 設定：所有外部服務都走這裡，不直接連 PostgreSQL 或 Ollama 11434 ═══
function getRuntimeApiConfig() {
    return typeof window !== 'undefined' ? (window.DECORATE_ME_CONFIG || {}) : {};
}

const RuntimeApiConfig = getRuntimeApiConfig();

// 所有服務的 baseUrl 與金鑰一律由 config.local.js（window.DECORATE_ME_CONFIG）在執行時注入，
// 這裡不寫死任何網址或金鑰，避免機密進版控外洩；未注入時為空字串，url() 會回空、不對外呼叫。
// AI Gateway 代理臉部分析與渲染：瀏覽器不再持有上游長期金鑰（規格書「Admin 商品管理安全 Proxy」§3 禁止），
// 改帶 /auth/login 發的短期 session。Gateway 路由是 /{service}/{path}，所以要帶上服務名當前綴。
//
// 正式站用相對路徑：firebase.json 的 rewrites 已把 /face-basic 等路徑導到 ai-gateway，
// 走同源就不必處理 CORS，Gateway 種的 dm_session（SameSite=Lax）也才送得出去。
// 本機開發沒有 rewrites，可在 config.local.js 設 aiGatewayUrl 指向 Gateway 絕對網址。
// 未設定、又是從 localhost/127.0.0.1 的開發伺服器打開時，預設指向本機 Gateway（8015，
// 見 ai_gateway 的 run_dev_server），讓一鍵啟動腳本零設定就能登入。
// 正式站是從 decorate-me.web.app 開的，命中不了這個判斷，維持同源空字串。
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
    MEMBER_AUTH_REQUIRED: '請先登入會員後再繼續。',
    MEMBER_SESSION_REQUIRED: '請先登入會員後再繼續。',
    MEMBER_AUTH_INVALID: '登入狀態已失效，請重新登入後再繼續。',
    MEMBER_SESSION_INVALID: '登入狀態已失效，請重新登入後再繼續。',
    MEMBER_SESSION_MISSING: '會員登入狀態建立失敗，請稍後再試。',
    MEMBER_SESSION_UNUSABLE: '會員登入狀態無法建立，請稍後再試。',
    MEMBER_SESSION_TOO_LARGE: '會員登入資料異常，請重新登入。',
    MEMBER_SERVICE_UNAVAILABLE: '會員服務目前無法連線，請稍後再試。',
    MEMBER_SERVICE_TIMEOUT: '會員服務回應逾時，請稍後再試。',
    MEMBER_SERVICE_ERROR: '會員服務處理失敗，請稍後再試。',
    MEMBER_SCOPE_FORBIDDEN: '無法存取其他會員的資料。',
    AUTH_NOT_CONFIGURED: '會員驗證服務尚未完成設定，請聯繫管理員。',
    LOGIN_RATE_LIMITED: '登入嘗試次數過多，請稍後再試。',
    MEMBER_SERVICE_RATE_LIMITED: '會員服務目前限制登入頻率，請稍後再試。',
    ADMIN_REQUIRED: '只有管理員可以執行這項操作。',
    ADMIN_SUSPENDED: '管理員帳號目前已停權。',
    ADMIN_PROXY_NOT_CONFIGURED: '管理端服務尚未完成設定。',
    // 點數與兌換：資料庫端只回這三個碼，先前沒收錄，訊息會掉到下面的通用分支去猜。
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
    // 分析成功、只是結果封裝失敗：明確告訴使用者「不需重拍」，否則他會一直換照片，
    // 而問題根本不在照片。
    PACKAGE_BUILD_FAILED: '臉部分析已完成，但結果整理失敗，請稍後再試（不需重拍照片）。',
    RENDER_TIMEOUT: '妝容生成逾時，請稍後再試。',
    RENDER_PROVIDER_ERROR: '妝容生成服務處理失敗，請稍後再試。',
    OLLAMA_UNAVAILABLE: '文字建議服務目前無法連線，請稍後再試。',
    NETWORK_ERROR: '網路連線失敗，請確認網路後再試。',
    FETCH_TIMEOUT: '服務回應逾時，請稍後再試。'
});

// 寫入防線擋下請求時顯示的說明。這些不是後端回的錯誤——請求根本沒送出去——
// 所以另外收在這裡，不混進 USER_ERROR_ZH（那份是後端 error code 對照表）。
const WRITE_BLOCKED_ZH = Object.freeze({
    NO_LOCAL_IDENTITY: '請先登入後再執行這項操作。',
    // 只擋這一次寫入，不清資料也不強制登出——說明要讓人知道「重新登入就好」，
    // 而不是以為系統壞了。
    NO_SESSION_PIN: '這個分頁的登入狀態已失效，請重新登入後再執行這項操作。',
    SESSION_UNAVAILABLE: '目前無法確認登入狀態，為避免寫錯帳號已中止這次操作，請稍後再試。',
    OWNER_MISMATCH: '登入身分已切換成其他帳號，為避免寫錯帳號已中止這次操作，請重新整理後再試。',
    DEFAULT: '無法確認目前的登入身分，這次操作已中止。'
});

// 把秒數講成人看得懂的等待時間。「請在 900 秒後再試」沒有人會去換算。
function formatRetryWait(seconds) {
    const total = Math.max(1, Math.round(Number(seconds) || 0));
    if (total < 60) return `${total} 秒`;
    const minutes = Math.ceil(total / 60);
    if (minutes < 60) return `${minutes} 分鐘`;
    return `${Math.ceil(minutes / 60)} 小時`;
}
if (typeof window !== 'undefined') window.formatRetryWait = formatRetryWait;

// 被限流時，後端一律回 retryAfterSeconds（見 api_errors.rate_limited_error）。
// 沒有秒數就退回「請稍後再試」——寧可講得模糊，也不要編一個數字出來。
function retryWaitSuffix(details) {
    const seconds = Number(details && (details.retryAfterSeconds ?? details.retryAfter)) || 0;
    return seconds > 0 ? `請在 ${formatRetryWait(seconds)}後再試。` : '請稍後再試。';
}

function localizeUserError(message, code = '', status = 0, details = null) {
    const raw = String(message || '').trim();
    // 429 先處理：它的訊息要帶「還要等多久」，所以不能走下面那張固定字串對照表。
    // 使用者拿不到時間就只能一直重試，而每一次重試都讓視窗往後延。
    if (status === 429 || /RATE_LIMITED|QUOTA_EXCEEDED/.test(String(code || '').toUpperCase())) {
        const wait = retryWaitSuffix(details);
        const upper = String(code || '').trim().toUpperCase();
        if (upper === 'LOGIN_RATE_LIMITED') return `登入嘗試次數過多，${wait}`;
        if (upper === 'QUOTA_EXCEEDED') return `今日的生成次數已用完，${wait}`;
        return `操作次數過多，${wait}`;
    }
    const explicitCode = String(code || '').trim().toUpperCase();
    // 只有「整句訊息本身就是一個錯誤碼」時才拿它當碼查表。先前是掃句子裡第一個全大寫的字，
    // 任何夾帶大寫單字的訊息都會被誤判成錯誤碼，查到什麼就顯示什麼 —— 使用者會看到
    // 跟實際錯誤無關的句子（例如兌換點數不足卻顯示「你沒有執行這項操作的權限」）。
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
    // 400 家族（欄位驗證、業務規則擋下）的收尾。刻意放在中文訊息分支「之後」——
    // 放前面會蓋掉後端已經寫好的中文說明，例如把「點數不足」變成一句空話。
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
            verifyOtpPath: '/auth/verify-otp',
            configPath: '/public-config'
        },
        faceBasic: {
            baseUrl: gatewayService('face-basic'),
            analyzePath: '/v1/face/analyze/basic',
            posePath: '/v1/face/pose',
            jobPath: '/v1/face/jobs/basic',
            jobStatusPath: '/v1/face/jobs/{jobId}',
            jobResultPath: '/v1/face/jobs/{jobId}/result'
        },
        facePro: {
            baseUrl: gatewayService('face-pro'),
            analyzePath: '/v1/face/analyze/pro',
            jobPath: '/v1/face/jobs/pro',
            jobStatusPath: '/v1/face/jobs/{jobId}',
            jobResultPath: '/v1/face/jobs/{jobId}/result'
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
        crawler: {
            baseUrl: gatewayService('admin-api'),
            previewPath: '/crawler/product-preview'
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

// ═══ API 串接層 ═══
const Api = {
    config: ApiConfig,
    _sessionAbortController: typeof AbortController === 'function' ? new AbortController() : null,
    _expectedActorKey: 'gatewayExpectedActor',
    _expectedSubjectKey: 'gatewayExpectedSubject',
    // 後端 /auth/session 回的角色。這是**唯一可信**的 role 來源——它來自登入時
    // 由資料庫驗過的會員所簽發的 JWT。本機 profile 的 role/level 是可被竄改的
    // sessionStorage 值，絕不能拿來決定要不要顯示管理後台。與 actor 綁在一起，
    // 換帳號時一起失效。
    _verifiedRoleKey: 'gatewayVerifiedRole',

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

    // 後端驗證過「這個分頁的目前帳號是不是管理員」。管理後台的顯示與進入一律靠這個，
    // 不靠本機 profile。後端本來就會擋掉非管理員的寫入；這道是把「連看都看不到」補上，
    // 不讓一個把本機 role 改成 admin 的帳號晃進管理畫面。
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
            if (url.origin !== window.location.origin) return false;
            return ['/member-database/', '/face-basic/', '/face-pro/', '/render-service/', '/text-suggestion/', '/admin-api/']
                .some(prefix => url.pathname.startsWith(prefix));
        } catch (_) {
            return false;
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

    // 讀 Gateway 發的 CSRF token。它刻意不是 HttpOnly——double-submit 的前提就是
    // 「自己的 JS 讀得到、別的網域讀不到」。讀不到就回空字串，讓後端去拒絕，
    // 不要在前端猜一個值出來。
    _csrfToken() {
        try {
            const jar = String((typeof document !== 'undefined' && document.cookie) || '');
            const hit = jar.split(';').map(part => part.trim()).find(part => part.startsWith('dm_csrf='));
            return hit ? decodeURIComponent(hit.slice('dm_csrf='.length)) : '';
        } catch (_) {
            return '';
        }
    },

    // 所有受保護的寫入都從這裡送出。X-Expected-Actor 只會送到本站 Gateway，
    // 絕不附在第三方網址；缺少分頁綁定身分時直接拒絕，不讓 shared cookie 決定寫入者。
    async _protectedFetch(input, init = {}) {
        if (!this._sessionAbortController) this._resetSessionRequests();
        const method = String(init.method || 'GET').toUpperCase();
        const isWrite = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method);
        const isProtected = this._isProtectedGatewayUrl(input);
        const nextInit = {
            ...init,
            credentials: isProtected ? 'include' : init.credentials,
            headers: this._copyHeaders(init.headers),
            signal: isProtected ? this._sessionSignal(init.signal) : init.signal
        };
        if (isWrite && isProtected) {
            const actorId = this._pinnedActor();
            if (!actorId) {
                // 這個分頁沒有 pin 到身分。擋下這次寫入就夠了——沒有 actor 就不可能
                // 帶著別人的身分寫進去，而「寫錯帳號」正是這道防線唯一要擋的事。
                //
                // 以前這裡還會送 session-owner-changed，於是整個分頁被登出、本機資料
                // 被清空、畫面跳回登入頁。但「沒有 pin」不等於「別人登入了」：重新整理、
                // sessionStorage 被清、伺服器端登入階段結束都會走到這裡，而這些情況
                // 一個證據都沒有。沒有證據就做最重的處置，結果是使用者三不五時被踢出去
                // 並且被告知一個不存在的分頁換了帳號。真正有證據的兩條路（Gateway 回
                // 409、或 validateSession 讀回來的 sub/actorId 與本機對不上）仍然照舊
                // 登出，那兩條才是真的有人換了帳號。
                const error = new Error(WRITE_BLOCKED_ZH.NO_SESSION_PIN);
                error.code = 'EXPECTED_ACTOR_REQUIRED';
                throw error;
            }
            nextInit.headers['X-Expected-Actor'] = actorId;
            // CSRF double-submit：Gateway 登入時發一個非 HttpOnly 的 dm_csrf cookie，
            // 這裡把它讀出來放回標頭。別的網站送得出請求，但讀不到我們網域的 cookie，
            // 補不出這個標頭。只加在同源的 Gateway 寫入上——附到第三方網址等於把
            // token 送給對方，而且會多觸發一次 preflight。
            const csrfToken = this._csrfToken();
            if (csrfToken) nextInit.headers['X-CSRF-Token'] = csrfToken;
        }
        const res = await fetch(input, nextInit);
        if (isProtected && res.status === 401) {
            // 401 同樣不一定是我們的 session 死了。Gateway 會把上游的 401 原樣轉回來——
            // 例如文字建議服務因為缺金鑰而拒絕，那跟會員的登入狀態毫無關係，
            // 卻會害使用者在按下「生成建議」時被登出。只認 Gateway 自己的驗證錯誤碼；
            // 認不出來就不動作，真正失效的 session 會在下一次 /auth/session 被攔下。
            const sessionCodes = [
                'MEMBER_AUTH_REQUIRED', 'MEMBER_SESSION_REQUIRED', 'MEMBER_AUTH_INVALID',
                'MEMBER_SESSION_INVALID', 'MEMBER_SESSION_MISSING', 'UNAUTHORIZED'
            ];
            let code = '';
            try {
                const peek = await res.clone().json();
                code = String(peek?.error?.code || peek?.detail?.error?.code || '').toUpperCase();
            } catch (_) {
                code = '';
            }
            if (sessionCodes.includes(code)) {
                this._notifySessionInvalid('decorate-me:session-expired');
            }
        } else if (isProtected && res.status === 409) {
            // 409 不一定是換帳號。Gateway 在「這個分頁選的帳號已經不在了」時回 409，
            // 但上游的業務衝突（獎勵已經領過、信箱已註冊）也是 409，而且會被原樣透傳。
            // 先前不分青紅皂白就登出，於是「領取一個已經領過的獎勵」＝被踢出去，
            // 而那個狀態其實完全正常。只認 Gateway 自己的錯誤碼。
            const ownerChangeCodes = ['ACCOUNT_NOT_AVAILABLE', 'SESSION_OWNER_CHANGED', 'EXPECTED_ACTOR_REQUIRED'];
            let code = '';
            try {
                const peek = await res.clone().json();
                code = String(peek?.error?.code || peek?.detail?.error?.code || '').toUpperCase();
            } catch (_) {
                code = '';
            }
            if (ownerChangeCodes.includes(code)) {
                this._notifySessionInvalid('decorate-me:session-owner-changed', { reason: 'SESSION_OWNER_CHANGED' });
            }
        }
        return res;
    },

    // 向 Gateway 取得穩定的同源路徑。上游資料庫的真實網址只留在 Cloud Run，
    // 瀏覽器不再直接連 Quick Tunnel，也不會因 tunnel 換址或第三方 cookie 被封鎖而整站失效。
    async bootstrapConfig() {
        const gateway = this.config.services.aiGateway;
        // router.js 用 .finally() 擋住開站流程，所以這裡一定要有逾時。
        // Gateway 若是連得上卻不回應（不是 5xx，是 hang），沒有逾時就永遠不 settle，
        // .finally() 不觸發，整個前端卡在白畫面——比用到舊網址嚴重得多。
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
            this.config.services.crawler.baseUrl = sameOriginGatewayPath(data.crawlerUrl, gatewayService('admin-api'));
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
        try {
            await fetch(`${baseUrl}/health`, {
                method: 'GET',
                headers: this._gatewayHeaders(),
                cache: 'no-store',
            });
        } catch (_) {
            // Ignore warm-up failures and let the real request surface the actionable error.
        }
    },

    // face-basic / face-pro 的 min-instances 是 0，閒置後容器會縮到零，下一個人按分析就得等冷啟動
    // （mediapipe 載模型特別久）。趁使用者還在選照片、還沒按下按鈕的空檔先打一發 /health 把容器叫醒，
    // 等他真的送出時通常已經是熱的。故意不 await，純背景預熱，失敗也無所謂。
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
        // session 過期是最常見且可自行解決的情況，直接給出可行動的指示
        if (res.status === 401 || code === 'MEMBER_AUTH_REQUIRED' || code === 'MEMBER_AUTH_INVALID') {
            return new Error('登入狀態已失效，請重新登入後再試一次。');
        }
        const message = error?.message
            || (typeof data?.detail === 'string' ? data.detail : '')
            || data?.message
            || fallback;
        return new Error(code ? `${message}（${code}）` : message);
    },

    // 後端建 job 時發 resultToken，之後查詢 job 狀態/結果必須帶 X-Job-Token，否則回 403
    _faceJobHeaders(service, resultToken) {
        const headers = { ...this._faceHeaders() };
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
                throw new Error(job.error?.message || '臉部分析 job 失敗');
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
        throw new Error('臉部分析 job 逾時');
    },

    // 2026-07-20 改走 Gateway：原本前端直連公開 tunnel 並自帶 X-API-Key，
    // 那正是《Gateway 安全代理與 Ollama 專題展示說明》明文禁止的「前端直連」。
    // 現在跟臉部分析、渲染一致，只送登入後的短期 session，瀏覽器不再持有任何上游金鑰。
    _textSuggestionHeaders() {
        return this._gatewayHeaders({ 'Content-Type': 'application/json' });
    },

    async suggestMakeup({ analysisPackage, faceAnalysis, style, userNote }) {
        let res;
        try {
            res = await this._protectedFetch(this.config.url('textSuggestion', 'suggestPath'), {
                method: 'POST',
                headers: this._textSuggestionHeaders(),
                body: JSON.stringify({ analysisPackage, faceAnalysis, style, language: 'zh-TW', userNote }),
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
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (res.status === 401) {
                throw new Error('登入狀態已失效，請重新登入後再試一次。');
            }
            throw new Error(data?.error?.message || data?.error || `Render API HTTP ${res.status}`);
        }
        if (data.status !== 'completed' || !data.afterImageUrl) {
            throw new Error(data?.error?.message || data?.error || '妝容渲染失敗');
        }
        if (data.renderQuota && Auth.getProfile) {
            const current = Auth.getProfile() || {};
            Auth.setProfile({ ...current, renderQuota: data.renderQuota });
        }
        return data;
    },

    // 非同步渲染：gpt-image-2 要跑 50~150 秒，同步等會撞 Cloud Run 逾時（實測一堆 504）。
    // 改成送出後拿 jobId、每 2 秒輪詢一次，onProgress 會被餵 1~100 的進度給進度條用。
    // 2026-07-15 對齊後端新接口：前端只送結構化資料（styleId + analysisPackage），prompt 由後端組
    // （前端送的 prompt 會被後端忽略——信任前端 prompt 等於任何人能用我們額度生任意圖）；
    // 輪詢必須帶建立 job 時回的 resultToken（X-Job-Token），不帶會被 403 擋到逾時。
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

        const submitted = await submitRes.json().catch(() => ({}));
        if (!submitRes.ok) {
            if (submitRes.status === 401) {
                throw new Error('登入狀態已失效，請重新登入後再試一次。');
            }
            throw new Error(submitted?.error?.message || submitted?.error || `Render API HTTP ${submitRes.status}`);
        }

        const jobId = submitted.jobId;
        if (!jobId) throw new Error(submitted?.error?.message || '渲染服務沒有回傳 jobId');
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
        // 指數退避：前幾輪維持 2 秒（多數渲染在這段時間內就有進度可回報），之後每輪
        // 乘以 1.5 直到 10 秒封頂。固定 2 秒等於一次渲染要打 75 次，其中大半都是
        // 「還在跑」——那些請求對使用者沒有任何價值，卻是實打實的後端負載與費用。
        const POLL_MIN_MS = 2000;
        const POLL_MAX_MS = 10000;
        let pollDelay = POLL_MIN_MS;
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, pollDelay));
            pollDelay = Math.min(POLL_MAX_MS, Math.round(pollDelay * 1.5));
            let job;
            try {
                const pollRes = await this._protectedFetch(pollUrl, { method: 'GET', headers, cache: 'no-store' });
                job = await pollRes.json().catch(() => ({}));
                if (!pollRes.ok) {
                    // 輪詢途中的暫時性錯誤不該直接判死，繼續等下一輪
                    if (pollRes.status === 404) throw new Error('渲染工作不存在或已過期');
                    // 被限流時就照後端說的時間等，不要繼續照原節奏敲——那只會讓視窗
                    // 一直重新開始。Retry-After 讀不到（跨來源）就退回自己的退避節奏。
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
                throw new Error(job?.error?.message || job?.error || '妝容渲染失敗');
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
        const rawCat = String(product.category || product.cat || product.type || '').trim();
        const tagCat = Array.isArray(product.tags) ? product.tags.find(tag => categoryMap[String(tag).trim()]) : '';
        const cat = categoryMap[rawCat] || categoryMap[tagCat] || product.cat || '底妝';
        const price = product.price == null
            ? ''
            : (String(product.price).startsWith('NT$') ? String(product.price) : `NT$${product.price}`);
        return {
            id: product.id != null ? `api-${rawCat || cat}-${product.id}` : `api-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            rawId: product.id ?? null,
            apiType: rawCat || null, // 原始 type slug（例如 lipsticks），呼叫 /api/product/{type}/{id} 這類單品 API 要用
            cat,
            name: product.name || '推薦商品',
            brand: product.brand || '',
            price,
            img: product.imageUrl || product.image_url || product.image_src || product.img || product.image || '',
            desc: product.matchReason || product.description || product.desc || '',
            matchReason: product.matchReason || '',
            score: product.score ?? null,
            popularity: product.popularity ?? product.sales ?? product.views ?? product.reviews ?? product.favorite_count ?? product.score ?? 0,
            // 推薦端點的 productUrl 實際上是 sale_page_id slug（不是 http 網址），留下來讓前端能跟商品清單比對補圖
            salePageId: product.sale_page_id || product.salePageId
                || ((typeof product.productUrl === 'string' && product.productUrl && !/^https?:/i.test(product.productUrl)) ? product.productUrl : null),
            sourceUrl: product.sourceUrl || product.source_url
                || ((typeof product.productUrl === 'string' && /^https?:/i.test(product.productUrl)) ? product.productUrl : ''),
            // 商品清單 API 的欄位叫 hex_primary，不是 hex。先前只讀 product.hex，
            // 於是每一筆都拿到 undefined、色塊一律不顯示——資料一直都在，只是沒接上。
            hex: (() => {
                const raw = product.hex || product.hex_primary || '';
                return /^#[0-9a-fA-F]{3,8}$/.test(raw) ? raw : null;
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
            source: 'product-api'
        };
    },

    // ═══ 以色找色 ═══
    //
    // 在瀏覽器端算。上游沒有 /api/recommend/{type}/{id}（實測 404，那支從來沒回過資料），
    // 但商品清單 API 每一筆都帶 lab，1041 筆算色差是微秒級，不需要後端也不需要多打請求。
    //
    // 只開放唇彩。其他類別的 hex / lab 是從商品圖抽出來的，眼影與眉筆抓到的多半是
    // 包裝色而不是產品色；全開的話會推出「這支眉筆和那支睫毛膏顏色很像」——比的是包裝盒。
    // 等 盤點清單.csv 的人工色系盤點完成（目前色系欄位 0/1040）再逐類放行。
    SHADE_MATCH_CATEGORIES: Object.freeze(['lipsticks']),

    // CIE94（graphics 係數）。CIE76 只是 Lab 上的歐氏距離，對高彩度的紅色會嚴重高估
    // 色差——而唇彩正好整片集中在高彩度紅粉區，用 CIE76 排出來的順序會偏。
    // CIEDE2000 更準，但它的 hue 角度分段容易寫錯、又難在這裡驗證；CIE94 修掉了彩度
    // 權重、沒有角度不連續的問題，對「同類商品之內排序」已經足夠。
    //
    // 這個公式是不對稱的（sC / sH 取自參考色的彩度），這裡刻意讓 labRef 是使用者
    // 正在看的那支商品，符合「跟這支比起來像不像」的語意。
    _deltaE94(labRef, labOther) {
        const [L1, a1, b1] = labRef;
        const [L2, a2, b2] = labOther;
        const dL = L1 - L2;
        const C1 = Math.hypot(a1, b1);
        const C2 = Math.hypot(a2, b2);
        const dC = C1 - C2;
        const da = a1 - a2;
        const db = b1 - b2;
        // dH² 在數學上非負，但浮點誤差可能讓它變成極小的負數，開根號會得到 NaN
        const dH2 = Math.max(0, da * da + db * db - dC * dC);
        const sC = 1 + 0.045 * C1;
        const sH = 1 + 0.015 * C1;
        return Math.sqrt(dL * dL + (dC / sC) ** 2 + dH2 / (sH * sH));
    },

    // 從已載入的商品清單裡找出色差最小的同類商品。純函式、同步，不打任何 API。
    findSimilarShades(product, catalog, limit = 3) {
        if (!product || !Array.isArray(product.lab)) return [];
        if (!this.SHADE_MATCH_CATEGORIES.includes(String(product.apiType || ''))) return [];
        const list = Array.isArray(catalog) ? catalog : [];
        const seen = new Set([String(product.id)]);
        const scored = [];
        for (const item of list) {
            if (!item || !Array.isArray(item.lab)) continue;
            if (String(item.apiType || '') !== String(product.apiType)) continue;
            const key = String(item.id);
            if (seen.has(key)) continue;   // 清單可能混入推薦來源的重複商品
            seen.add(key);
            scored.push({ ...item, deltaE: this._deltaE94(product.lab, item.lab) });
        }
        scored.sort((a, b) => a.deltaE - b.deltaE);
        return scored.slice(0, Math.max(0, limit));
    },

    // 個人化推薦：依賴組員資料庫的登入 session，登入狀態不確定時優雅地回傳空陣列，不影響其他功能
    async getPersonalRecommendations() {
        const baseUrl = this.config.services.product.baseUrl;
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

    // 伺服器端收藏同步：跨裝置同步用，依賴組員資料庫的登入 session（同上，失敗時不影響本機 Fav）
    //
    // 走 member-database 而不是 product-api。收藏是會員資料，Gateway 也只在
    // member-database 的白名單裡放行 api/favorites/toggle；先前送到 product-api，
    // 被商品白名單（只有 api/products 與 recommend-products）擋掉，一律 404。
    // 上游那條端點其實是好的——不帶 session 直接打會回 401，不是 404。
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

    // 商品管理端點用管理員登入後的 token 驗證，由後端判斷 role=admin。
    //
    // 這裡原本還支援讓管理員手動貼一把 ADMIN_API_KEY，但那把金鑰實際上並不存在：
    // 〈商品搜尋管理與推薦演算法整合規格書 2026-07-17〉§3 約定的是
    // `Authorization: Bearer <admin-token>`，資料庫端也是照這個實作；
    // 手貼金鑰是〈Admin 商品管理安全 Proxy 規格書 2026-07-18〉§1 描述的過渡驗收做法，
    // 該文件同時要求上線後移除，而資料庫端從未提供過這樣一把金鑰。
    // 留著只會讓管理員以為少填了什麼，實際上填什麼都會被回 INVALID_TOKEN。
    _adminProductHeaders(headers = {}) {
        return this._memberHeaders(headers);
    },
    _productApiError(data, status) {
        const error = data?.detail?.error || data?.error || {};
        return {
            status,
            code: error.code || `HTTP_${status}`,
            error: error.message || data?.message || `HTTP ${status}`,
            details: error.details || {},
            retryable: !!error.retryable
        };
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
            return {
                ok: true,
                ...data,
                products: list.map(item => this._normalizeProduct(item)).filter(Boolean),
                total: Number(data.total ?? list.length),
                nextCursor: data.nextCursor ?? null
            };
        } catch (_) {
            return { ok: false, products: [] };
        }
    },

    async previewCrawledProduct(sourceUrl) {
        const service = this.config.services.crawler;
        if (!service?.baseUrl) return { ok: false, code: 'CRAWLER_URL_NOT_CONFIGURED', error: 'crawlerUrl 與 productUrl 都尚未設定' };
        const url = `${service.baseUrl}${service.previewPath}`;
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        const timeout = controller ? setTimeout(() => controller.abort(), 30000) : null;
        try {
            const res = await this._protectedFetch(url, {
                method: 'POST',
                credentials: 'include',
                headers: this._adminProductHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ url: sourceUrl }),
                ...(controller ? { signal: controller.signal } : {})
            });
            if (timeout) clearTimeout(timeout);
            const data = await res.json().catch(() => ({}));
            const payload = data.data || data.product || {};
            if (!res.ok || data.success === false) {
                return {
                    ok: false,
                    status: res.status,
                    ...this._productApiError(data, res.status),
                    detail: data?.detail?.error?.details || data?.error?.detail || ''
                };
            }
            const imageUrls = Array.isArray(payload.imageUrls)
                ? payload.imageUrls.filter(Boolean)
                : [payload.imageUrl || payload.image_url || payload.img].filter(Boolean);
            return {
                ok: true,
                status: data.status || 'ok',
                message: data.message || '',
                product: {
                    sourceUrl: payload.sourceUrl || sourceUrl,
                    sourceSite: payload.sourceSite || '',
                    name: payload.productName || payload.name || '',
                    brand: payload.brand || '',
                    price: payload.price ?? '',
                    currency: payload.currency || '',
                    description: payload.description || payload.desc || '',
                    imageUrls,
                    category: payload.category || payload.type || '',
                    hex: payload.hex || '',
                    specs: payload.specs || {},
                    rawText: payload.rawText || '',
                    missingFields: Array.isArray(payload.missingFields) ? payload.missingFields : [],
                    warnings: Array.isArray(payload.warnings) ? payload.warnings : []
                },
                raw: data
            };
        } catch (err) {
            if (timeout) clearTimeout(timeout);
            if (err?.name === 'AbortError') return { ok: false, code: 'FETCH_TIMEOUT', error: '爬蟲服務逾時，請稍後重試' };
            return { ok: false, code: 'NETWORK_ERROR', error: '爬蟲服務連線失敗：' + err.message };
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
            if (!res.ok) return { ok: false, status: res.status };
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
    // 收藏、刪除、扣點這類會改變資料的動作，必須在送出**之前**先問清楚，
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
        if (!session.ok) return { ok: false, reason: 'SESSION_UNAVAILABLE', status: session.status };
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

    // ═══ 統一的 protected write actor 防線 ═══
    //
    // 每一條會改變資料的請求，送出前都要先確認 cookie 裡的身分就是這個分頁以為的那個人。
    // 這道檢查原本是各寫各的：六個方法各自抄一次 assertSessionOwner + 早退，回傳形狀還有
    // 三種（null／{ok:false}／{ok:false,reason}），而 patchMember 與 deleteMember 整個漏掉——
    // 後台的停權與刪除會員，在 session 被另一個帳號蓋掉時照樣送得出去。
    // 收斂成單一入口之後，「新增一個寫入端點」跟「補上防線」是同一個動作，漏不掉。
    //
    // actor 是「執行這次寫入的人」，不是「被寫入的對象」，兩者不一定相同：
    //   · 會員動自己的資料（簽到、兌換、收藏）—— actor 就是那個 email；
    //   · 後台動別人的資料（停權、刪除）—— actor 是目前登入的管理員，傳 null
    //     由這裡取本機 profile；拿被操作的會員 email 去比對只會把正常的後台操作全擋掉。
    _writeActorEmail() {
        const profile = (typeof Auth !== 'undefined' && Auth.getProfile) ? (Auth.getProfile() || {}) : {};
        return String(profile.email || '').trim().toLowerCase();
    },

    // 擋下時回傳統一形狀：ok:false + blocked:true + 可直接顯示的中文 error。
    // 呼叫端本來就在看 result.ok / result.error，不必為了這道防線多寫分支。
    async _protectedWrite(actorEmail, run) {
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
            return { ok: true, favorites: Array.isArray(data.favorites) ? data.favorites : [] };
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
            return { ok: true, items: Array.isArray(data.items) ? data.items : [] };
        } catch (_) {
            return { ok: false, items: [] };
        }
    },

    // 把整台購物車覆蓋寫回伺服器（POST，last-write-wins）。走 _protectedWrite 沿用
    // 換帳號防線：分頁身分對不上就擋下，不會把 A 的車寫到 B 帳號。背景同步，呼叫端不看回傳。
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
                    method: 'POST',
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

    async patchMember(email, patch) {
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
        });
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
                // 領取失敗最常見的是「已經領過了」（409）。原本直接顯示上游的 message，
                // 而那句話對使用者沒有意義，看起來像系統壞掉——實際上狀態是正常的，
                // 只是這個獎勵今天已經拿過。逐一對應成看得懂的說法。
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
                    // 已經擁有不算失敗：點數先前就扣過了，使用者確實有這個主題。
                    // 回成功，呼叫端才會把解鎖同步到本機並套用 —— 否則會卡在
                    // 「伺服器說你有、本機說你沒有」，怎麼按都套用不上。
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
            return { ok: true, looks: Array.isArray(data.looks) ? data.looks : [] };
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
        // 只有妝後圖是必要條件。它由渲染服務產生，一定有網址（/media/render/<hash>）。
        // 妝前圖是使用者自己上傳的照片，系統裡沒有任何管道能讓它變成網址——Gateway 只有
        // GET /media/render 與 /media/legacy，沒有上傳端點——所以它永遠是 data:base64。
        // 先前連妝前圖一起檢查，等於每一筆收藏都在送出前就被擋掉，而且 skipped 分支是空的，
        // 畫面完全正常卻一筆都沒進資料庫（見 S57）。這裡改成妝前圖沒網址就留空：
        // 既不把 90 萬字元的 base64 塞進 String(500) 欄位，也不因為它丟掉整筆收藏。
        // 原始臉部照片不進伺服器，同時也符合既有的隱私方向。
        const afterImageUrl = String(payload?.afterImageUrl || '').trim();
        const rawBeforeImageUrl = String(payload?.beforeImageUrl || '').trim();
        const beforeImageUrl = this._isStorableImageUrl(rawBeforeImageUrl) ? rawBeforeImageUrl : '';
        if (!payload?.style || !this._isStorableImageUrl(afterImageUrl)) {
            return { ok: false, skipped: true, reason: 'AFTER_IMAGE_URL_REQUIRED' };
        }
        // 資料庫驗證 afterImageUrl 必須是 http(s) URL（INVALID_AFTER_IMAGE_URL），
        // 但 Gateway 刻意回相對路徑——同一條路徑在本機開發與正式站都成立，也塞得進
        // String(500)。存進資料庫前補上目前的 origin：Gateway 的 STABLE_RENDER_URL_RE
        // 是 `(?:https://[^/]+)?/media/render/(...)`，主機前綴本來就是選用的，
        // 所以收藏後的 retain 與日後刪除都照樣解析得到 job id。
        // 注意：本機以 http:// 開發時存進去的網址不符合那個 https 前綴，retain 會失效；
        // 正式站一律 https，不受影響。
        // 兩個欄位用同一套規則。資料庫目前只驗 afterImageUrl，但兩邊存成不同形式
        // 沒有好處，而且哪天它也開始驗 before，這裡就不必再改一次。
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

    async deleteSavedLook(email, id) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email || id == null) return { ok: false };
        return this._protectedWrite(email, async () => {
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
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async searchProductPreview(query) {
        const baseUrl = this.config.services.crawler.baseUrl;
        if (!baseUrl) return { ok: false, error: 'crawlerUrl 未設定' };
        try {
            const res = await this._protectedFetch(`${baseUrl}/crawler/search-preview`, {
                method: 'POST',
                credentials: 'include',
                headers: this._adminProductHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ q: String(query || '').trim() })
            });
            const data = await res.json().catch(() => ({}));
            if (res.status === 404 || res.status === 405) {
                return { ok: true, fallback: true, googleUrl: `https://www.google.com/search?q=${encodeURIComponent(String(query || '').trim())}` };
            }
            if (!res.ok) return { ok: false, ...this._productApiError(data, res.status) };
            return { ok: true, googleUrl: data.googleUrl || data.google_url || '' };
        } catch (err) { return { ok: false, error: '連線失敗：' + err.message }; }
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

    // LAB 物件（{L,a,b} 或 {L,A,B}）轉成推薦端新規格要的陣列 [L, a, b]
    _labToArray(lab) {
        const obj = this._labToUpperKeys(lab);
        if (!obj) return null;
        return [obj.L ?? 0, obj.A ?? 0, obj.B ?? 0];
    },

    // 2026-07-15 起商品推薦端改吃規格書格式：整包 analysisPackage（faceAnalysis 巢狀、lab 用陣列），
    // 回應也改在 analysisPackage.recommendations.products 底下。詳見「演算法端接口規格書_analysis_package商品推薦_2026-07-13.md」。
    async recommendProducts(analysisPackage, styleId) {
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
            const res = await this._fetchWithRelogin(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    analysisPackage: {
                        id:    analysisPackage?.id || null,
                        style: styleId || null,
                        faceAnalysis: {
                            faceShape: fa?.faceShape || null,
                            browShape: fa?.browShape || null,
                            eyeShape:  fa?.eyeShape  || null,
                            lipShape:  fa?.lipShape  || null,
                            skinTone: {
                                season: fa?.skinTone?.season || null,
                                level:  fa?.skinTone?.level  || null,
                                lab:    this._labToArray(fa?.skinTone?.lab),
                            },
                            lipLab: this._labToArray(fa?.lipLab),
                        },
                        ...(suggestion ? { generativeText: { suggestion } } : {}),
                    },
                    limit: 12,
                })
            });
            if (!res.ok) return { ok: false, status: res.status, products: [] };
            const data = await res.json();
            const list = data.analysisPackage?.recommendations?.products
                || data.recommendations?.products
                || data.recommendations
                || data.products
                || [];  // 新格式在 analysisPackage.recommendations.products；相容舊格式
            return {
                ok: true,
                ...data,
                products: Array.isArray(list)
                    ? list.map(item => this._normalizeProduct(item)).filter(Boolean)
                    : []
            };
        } catch (_) {
            return { ok: false, products: [] };
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
        // 原本不管什麼錯都丟「註冊 API 連線失敗」，把後端明確的 EMAIL_EXISTS 也蓋掉了
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
            schemaVersion: '2026-06-v1',
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
        return {
            version: mode === 'pro' ? 'PRO' : 'BASIC',
            faceShape: raw?.['臉型'] || null,
            browShape: raw?.['眉型'] || null,
            eyeShape: raw?.['眼型'] || null,
            noseFront: raw?.['鼻型'] || null,
            noseSide: raw?.['鼻型_側面'] || null,
            lipShape: raw?.['嘴型'] || null,
            skinTone: {
                season: skin['四季型'] || null,
                level: skin['膚色分級'] || null,
                lab: skin['LAB'] || null,
                labSource: skin['LAB來源'] || null
            },
            lipLab: raw?.['嘴唇_LAB'] || null,
            symmetry: sym ? {
                score: sym.score ?? null,
                eyeOpenRatio: sym.eyeOpenRatio ?? null,
                noseDeviation: sym.noseDeviation ?? null,
                mouthSymmetry: sym.mouthSymmetry ?? null
            } : null,
            sidePhotoUsed: proStatusRaw
                ? proStatusRaw['多角度照片']?.startsWith('已接收')
                : null,
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
    // 一張 base64 頭像動輒幾十 KB，先前它跟著整個 profile 被寫進 sessionStorage。
    // sessionStorage 不會因重新整理而清空，等於把使用者的臉留在分頁裡給下一個人；
    // 而且它一路被塞進每一次 setProfile 的 JSON，很容易撐爆配額讓寫入靜靜失敗。
    // 正確的長期做法是上傳到私有物件、只存 object name（待儲存端提供上傳端點）。
    // 在那之前，data: 頭像只留在這個記憶體欄位裡：本次 session 的 SPA 導覽照樣顯示，
    // 但不落地、整頁重新整理後就回到後端提供的頭像網址或預設圖示。
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
        // 記憶體裡有本次 session 暫存的 data: 頭像時補回去，讓 SPA 導覽看得到，
        // 但它從來沒有、也不會進 sessionStorage。
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
        // 列舉清除，不要逐一列名——逐一列名正是先前漏掉 beautyAnalysisDraft 的原因。
        // 那個 key 放的是完整分析資料包，**裡面有使用者上傳的照片**（base64）。
        // sessionStorage 不會因為重新整理而清空，所以同一個分頁的下一個登入者
        // 讀得到前一個人的臉。
        //
        // 之後任何人新增 sessionStorage 的 key，都會自動被這裡帶走，
        // 不必記得回來改這個函式。
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

    // 清掉「這一個帳號」殘留在 localStorage 的 PII——sessionStorage 由 clearSession
    // 處理，但收藏對比圖（beautySuggestions_<email>）帶使用者的臉部照片網址、分析回饋
    // （beautyAnalysisFeedback）帶五官特徵，這些放在 localStorage，登出／換帳號後仍在，
    // 共用裝置的下一個人打開 devtools 就讀得到。**只清當前帳號的鍵，不動其他帳號的收藏。**
    clearAccountLocalPII(email) {
        try {
            const em = String(email || '').trim().toLowerCase();
            if (em) localStorage.removeItem('beautySuggestions_' + em);
            localStorage.removeItem('beautyAnalysisFeedback');
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
        if (this.isVip(p)) return true;
        const permission = this.permissionSnapshot(p);
        if (permission.status === 'suspended') return false;
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
        const quota = this.permissionSnapshot(p).renderQuota;
        if (quota && Number.isFinite(Number(quota.dailyLimit))) return Number(quota.dailyLimit);
        if (this.hasUnlimitedRender(p)) return Infinity;
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
        // 管理後台的顯示與進入，**只**信後端 /auth/session 驗過的角色。
        //
        // 本機 profile 的 role/level 是可被竄改的 sessionStorage 值。實測到一個未通過
        // OTP 的亂碼帳號因為本機 role 被當成 admin 而晃進管理畫面（後端仍擋掉了所有
        // 寫入，但「連看都不該看到」）。這裡不再有「退回本機 profile」的分支——那個
        // 分支本身就是洞：沒有有效 session 的帳號只要把本機 role 改成 admin 就能繞過。
        // 沒有後端驗過的 admin session，就不是 admin。
        // 注意：session pin 與驗證角色的方法在 Api 物件上（不是 Auth）。
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
        { id: 'rose', name: '銀霧', cost: 80, swatches: ['#EEF0F2', '#AEB4BB', '#3E444B'], desc: '鉑金銀灰會員介面' },
        { id: 'jade', name: '青玉光澤', cost: 120, swatches: ['#E6F0EA', '#6A9A7C', '#30483A'], desc: '清透綠色會員介面' },
        { id: 'noir', name: '黑金 PRO', cost: 180, swatches: ['#2F2629', '#D9B66F', '#F7EAD2'], desc: '深色高級會員介面' }
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
    checkin(email) {
        const key = this._email(email);
        if (key === 'guest') return { ok: false, message: '請先登入會員再打卡。' };
        const all = this._load(this._checkinKey, {});
        const prev = all[key] || {};
        if (prev.date === this._today()) return { ok: false, message: '今天已經打卡過了。' };
        const streak = this._isYesterday(prev.date) ? (prev.streak || 0) + 1 : 1;
        all[key] = { date: this._today(), updatedAt: new Date().toISOString(), streak };
        this._save(this._checkinKey, all);
        let balance = this.addPoints(key, 10, '每日打卡', { type: 'daily_checkin', streak });
        const bonus = this._streakBonusTable[streak] || 0;
        if (bonus) balance = this.addPoints(key, bonus, `連續簽到 ${streak} 天獎勵`, { type: 'streak_bonus', streak });
        return { ok: true, points: 10 + bonus, bonus, streak, balance };
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

// ═══ 會員等級擴充：一般／銀卡／金卡由累計點數自動判定；VIP／管理員仍走原本手動核發那套 ═══
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

// ═══ 臉部分析回饋 ═══
//
// 使用者對五官判斷說「準」或「不準」，不準時可以直接選正確答案。
// **這一步不收照片。** 只記模型答了什麼、使用者說什麼，兩者都是短字串。
//
// 為什麼不順便收照片：訓練需要 (影像, 標籤) 成對，只有標籤是訓練不了模型的。
// 收照片就是把「原始臉部照片不進伺服器」這個立場整個翻過來，需要明確告知與同意。
// 所以這裡收的是**弱點訊號**——告訴我們模型在哪些五官、哪些類別上系統性出錯，
// 再由標註者對那些案例好好標。這也避開了自陳資料的老問題：臉型帶審美價值，
// 讓使用者自己選，收到的分布會偏向討喜的類別。
//
// 目前先排在本機。資料庫端的端點還沒有（見給資料庫端清單 TASK 12），
// 端點到位前不寫對接程式——對著不存在的端點講話的程式，這個專案已經有過兩批了。
const AnalysisFeedback = {
    _key: 'beautyAnalysisFeedback',
    // 與 models/basic_features_roi/*_classes.json 一致。順序照模型的類別順序，
    // 不要自己重排——對照 log 與訓練資料都用那個順序。
    OPTIONS: Object.freeze({
        '臉型': ['圓形臉', '心形臉', '方形臉', '長形臉', '鵝蛋臉'],
        '眉型': ['一字眉', '彎月眉', '落尾眉'],
        // 眼型由八類併為六類（2026-07-24 官方分類表）：丹鳳眼併入鳳眼、瞇縫眼併入細長眼。
        // 那兩個類別的圖檔在標註資料夾裡本來就與合併目標逐位元組相同——合併當初是用
        // 複製而非搬移，舊資料夾沒刪，於是同一張臉同時掛在兩個類別底下。
        '眼型': ['細長眼', '桃花眼', '杏仁眼', '圓眼', '鳳眼', '下垂眼'],
        // 窄鼻已併入標準鼻（2026-07-22 重訓）：標註者判斷窄鼻時看的不是鼻翼寬度，
        // 舊的三類模型「標準鼻」召回率只有 0.061，整個類別塌陷進窄鼻。
        '鼻型': ['寬鼻', '標準鼻'],
        '嘴型': ['M型唇', '厚唇', '微笑唇', '花瓣唇', '薄唇'],
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

// ═══ 購物車模組 ═══
//
// 本機 localStorage 是工作副本；登入後每次變更會背景同步整台車回會員資料庫
// （POST /api/members/{email}/cart，last-write-wins），換裝置／換瀏覽器登入時
// 由 syncRemoteCart() 讀回。訪客（沒有 email）維持純本機，不同步。
// 同步全程盡力而為：伺服器連不上時本機購物車照樣能用，不報錯、不擋操作。
const Cart = {
    _key: 'beautyCart',
    _pushTimer: null,
    // 剛登入時設 true：讓 syncRemoteCart 把「登入前的訪客車」與「伺服器車」數量相加合併一次；
    // 其餘情境（重載、換裝置還原）為 false，以伺服器為準直接取代，避免每次載入都相加造成灌水。
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
    count() { return this.list().reduce((sum, item) => sum + item.qty, 0); },

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
        const server = (Array.isArray(serverItems) ? serverItems : [])
            .map(it => ({ id: String(it.id), qty: Math.max(1, parseInt(it.qty, 10) || 1) }))
            .filter(it => it.id);
        if (!sum) { this._setLocal(server); return server; }
        const byId = new Map(server.map(it => [it.id, { ...it }]));
        for (const it of this.list()) {
            const id = String(it.id);
            const qty = Math.max(1, parseInt(it.qty, 10) || 1);
            if (byId.has(id)) byId.get(id).qty += qty;
            else byId.set(id, { id, qty });
        }
        const merged = [...byId.values()];
        this._setLocal(merged);
        return merged;
    }
};

// ═══ 分析紀錄模組 ═══
const History = {
    _key: 'beautyHistory',
    list() { return JSON.parse(localStorage.getItem(this._key) || '[]'); },
    add(record) {
        const arr = this.list();
        arr.unshift({ ...record, timestamp: new Date().toISOString() });
        if (arr.length > 20) arr.length = 20;
        localStorage.setItem(this._key, JSON.stringify(arr));
    }
};
