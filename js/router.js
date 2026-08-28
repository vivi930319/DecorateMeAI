// 頁面 HTML（pages/*.html）的快取版本，跟著 router.js 自己的 ?v= 走。
//
// 原本這裡寫死成 `20260624-brightness`：deploy.ps1 只戳 index.html 裡的資源版本，
// 戳不到藏在程式碼裡的這一個。結果是**程式是新的、頁面 HTML 是六月的**——
// 兩邊對不起來的樣子最難查：後台的 CSS 與 JS 都更新了，畫面卻少了側邊分類與
// 模型修正複核，因為瀏覽器拿的是那份舊 admin.html。
//
// 綁在 router.js 的版本上，只要程式有更新，頁面 HTML 一定跟著重新抓。
const PAGE_ASSET_VERSION = (() => {
    try {
        const el = document.querySelector('script[src*="js/router.js"]');
        const m = /[?&]v=([^&"']+)/.exec((el && el.getAttribute('src')) || '');
        if (m) return m[1];
    } catch (_) {}
    return 'dev';
})();

// ═══ 共用 UI 片段 ═══
const HEART_SVG = '<span class="pulse"></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.4S3.6 15.6 3.6 9.4C3.6 6.5 5.7 4.7 8 4.7c1.7 0 3.1 1 4 2.4 0.9-1.4 2.3-2.4 4-2.4 2.3 0 4.4 1.8 4.4 4.7 0 6.2-8.4 11-8.4 11z"/></svg>';
const CAT_EN = { '底妝':'FOUNDATION','眼影':'EYESHADOW','眼線/睫毛':'EYES & LASH','唇彩':'LIP COLOR','腮紅':'BLUSH','眉毛彩妝':'BROW','修容':'CONTOUR','打亮':'HIGHLIGHT' };
function phBox(cls, label, src){
    const cap = (cls.indexOf('product-thumb')>-1) ? '' : `<span class="ph-cap">${escapeHtml(label||'')}</span>`;
    const img = src ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(label||'')}" loading="lazy" decoding="async" onload="this.classList.add('loaded')">` : '';
    return `<div class="ph ${cls}">${cap}${img}</div>`;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

// 後端可能回 ISO 字串、毫秒、Unix 秒數或 Firestore Timestamp。集中轉換，避免分析
// 紀錄顯示 1970、Invalid Date，或不同頁面各自猜一套格式。
function analysisDateValue(value) {
    if (value == null || value === '') return null;
    try {
        if (typeof value?.toDate === 'function') {
            const converted = value.toDate();
            return Number.isNaN(converted?.getTime?.()) ? null : converted;
        }
        if (typeof value === 'object') {
            const seconds = value.seconds ?? value._seconds;
            const nanos = value.nanoseconds ?? value._nanoseconds ?? 0;
            if (Number.isFinite(Number(seconds))) {
                return new Date(Number(seconds) * 1000 + Number(nanos) / 1e6);
            }
        }
        if (typeof value === 'number' || /^\d+(?:\.\d+)?$/.test(String(value).trim())) {
            const number = Number(value);
            if (!Number.isFinite(number)) return null;
            const millis = Math.abs(number) < 1e12 ? number * 1000 : number;
            const converted = new Date(millis);
            return Number.isNaN(converted.getTime()) ? null : converted;
        }
        const converted = new Date(value);
        return Number.isNaN(converted.getTime()) ? null : converted;
    } catch (_) {
        return null;
    }
}

function formatAnalysisTime(value) {
    const converted = analysisDateValue(value);
    return converted ? converted.toLocaleString('zh-TW') : '時間資料無法辨識';
}

// 呼叫完外部 AI 服務（Ollama／Replicate）後，強制冷卻幾秒才能再按，避免使用者短時間內連點造成後端連線壓力
function startButtonCooldown(btn, seconds, idleText) {
    if (!btn) return;
    let remaining = seconds;
    btn.disabled = true;
    btn.textContent = `請稍候 ${remaining} 秒...`;
    const timer = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
            clearInterval(timer);
            btn.disabled = false;
            btn.textContent = idleText;
        } else {
            btn.textContent = `請稍候 ${remaining} 秒...`;
        }
    }, 1000);
}

function normalizeAdviceTitle(title) {
    const raw = String(title || '').replace(/[：:]/g, '').replace(/\s+/g, '');
    if (/整體|方向|總覽/.test(raw)) return '整體妝容方向';
    if (/底妝|粉底|遮瑕|定妝/.test(raw)) return '底妝建議';
    if (/彩妝細節|眉眼|眼妝|眉型|眉毛|眼影|眼線|睫毛/.test(raw)) return '眉眼妝建議';
    if (/腮紅|修容|打亮|輪廓/.test(raw)) return '腮紅修容';
    if (/唇|口紅|唇彩|唇釉/.test(raw)) return '唇妝建議';
    if (/推薦產品|推薦質地|產品質地|產品推薦/.test(raw)) return '推薦產品/質地';
    if (/避免|注意|禁忌|不要/.test(raw)) return '避免事項';
    if (/總結|建議總結/.test(raw)) return '總結與建議';
    return title || '妝容建議';
}

function parseMakeupAdviceSections(text) {
    const clean = String(text || '').replace(/\r/g, '').trim();
    if (!clean) return [];
    const titles = [
        '整體妝容方向', '整體方向', '妝容方向',
        '底妝建議', '底妝',
        '眉眼妝建議', '眉眼建議', '眼妝建議', '眉型建議', '眉毛建議', '彩妝細節',
        '腮紅修容', '腮紅 & 修容', '腮紅建議', '修容建議', '打亮建議',
        '唇妝建議', '唇妝', '唇彩建議',
        '推薦產品/質地', '推薦產品', '推薦質地', '產品推薦',
        '避免事項', '注意事項',
        '總結與建議', '總結', '建議總結'
    ];
    const escaped = titles
        .map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s*'))
        .join('|');
    const pattern = new RegExp(
        String.raw`(?:^|\n)\s*(?:#{1,4}\s*)?(?:[【\[]\s*)?(?:\d+\s*[.、．)]\s*)?(${escaped})(?:\s*[】\]])?\s*[：:]?\s*`,
        'gi'
    );
    const matches = [...clean.matchAll(pattern)];
    if (!matches.length) {
        const chunks = clean.split(/\n{2,}/).map(s => s.trim()).filter(Boolean);
        if (chunks.length >= 3) {
            return chunks.slice(0, 6).map((body, i) => ({
                title: ['整體妝容方向', '底妝建議', '眉眼妝建議', '唇妝建議', '避免事項', '總結與建議'][i] || '妝容建議',
                body
            }));
        }
        return [{ title: '妝容建議', body: clean }];
    }
    return matches.map((m, i) => {
        const start = m.index + m[0].length;
        const end = i + 1 < matches.length ? matches[i + 1].index : clean.length;
        const body = clean.slice(start, end).replace(/^\s*[-•]\s*/, '').trim();
        return { title: normalizeAdviceTitle(m[1]), body };
    }).filter(section => section.body);
}

function renderMakeupAdviceGrid(text) {
    const sections = parseMakeupAdviceSections(text);
    return sections.map(section =>
        `<div><b>${escapeHtml(section.title)}</b><p>${escapeHtml(section.body)}</p></div>`
    ).join('');
}

function getFeaturedProducts(limit = 6) {
    const source = Array.isArray(Router?.generalProductCatalog) ? Router.generalProductCatalog : [];
    const hasPopularity = source.some(product => getProductPopularity(product) > 0);
    if (hasPopularity) {
        return [...source].sort((a, b) => getProductPopularity(b) - getProductPopularity(a)).slice(0, limit);
    }
    // 沒有熱門度資料時（目前商品 API 本身沒有這個欄位），不要直接切前 N 筆——
    // API 回傳常常是同一系列色號排在一起，切前幾筆容易全部擠在同一分類。
    // 改成每個大類先各挑第一項，讓精選商品至少涵蓋多種分類。
    const seenCats = new Set();
    const oneCatPicks = [];
    for (const product of source) {
        if (!product?.cat || seenCats.has(product.cat)) continue;
        seenCats.add(product.cat);
        oneCatPicks.push(product);
        if (oneCatPicks.length >= limit) break;
    }
    if (oneCatPicks.length >= limit) return oneCatPicks;
    // 分類數不夠補滿 limit，用其餘商品照原順序補齊，避免精選數量比預期少
    const pickedIds = new Set(oneCatPicks.map(p => p.id));
    const rest = source.filter(p => !pickedIds.has(p.id));
    return [...oneCatPicks, ...rest].slice(0, limit);
}

function getProductPopularity(product) {
    return Number(product?.popularity || product?.sales || product?.views || product?.reviews || product?.score || 0);
}

// ═══ 登入狀態監看 ═══
//
// 問題：後台的清單是**透過 gateway 代理**讀資料庫的，gateway 用它自己的憑證去問，
// 所以你的 session 過期時清單照樣讀得出來。但寫入前的守衛檢查的是**你的** session。
// 於是畫面看起來一切正常，直到按下儲存才九筆全部失敗——而那時你已經改完九列了。
//
// 所以要主動看，不能等按鈕。三個時機：
//   進頁面      —— 一開始就知道能不能存
//   切回這個分頁 —— 離開一陣子回來，正是最可能已經過期的時候
//   每 90 秒    —— 改到一半過期也接得住
//
// 為什麼是 90 秒不是 10 秒：這支請求只為了問「還在嗎」，問太密是白花往返；
// 而使用者從發現到重新登入本來就要好幾十秒，更快知道並不會更早修好。
//
// 只回報**狀態改變**，不是每次檢查都喊。一直好著就安靜，
// 壞了說一次，修好了再說一次——每次都提醒的東西會被當成背景噪音。
const SessionWatch = (() => {
    const PERIOD_MS = 90000;
    let timer = null, onChange = null, last = null, checking = false;

    async function check() {
        if (checking) return;          // 分頁切換與計時器可能同時觸發
        checking = true;
        try {
            const session = await Api.validateSession();
            const ok = Boolean(session.ok && session.actorId);
            const state = ok ? 'ok' : (session.status === 401 ? 'expired' : 'unknown');
            if (state !== last) {
                last = state;
                if (onChange) onChange(state, session);
            }
        } finally {
            checking = false;
        }
    }

    function onVisible() {
        if (document.visibilityState === 'visible') check();
    }

    return {
        start(handler) {
            this.stop();
            onChange = handler;
            last = null;               // 重新開始時要重新回報一次目前狀態
            check();
            timer = setInterval(check, PERIOD_MS);
            document.addEventListener('visibilitychange', onVisible);
        },
        stop() {
            if (timer) { clearInterval(timer); timer = null; }
            document.removeEventListener('visibilitychange', onVisible);
            onChange = null; last = null;
        },
        // 按下儲存之前可以再問一次，不必等下一次輪詢
        check,
    };
})();

const POINT_REASON_LABELS = {
    check_in: '每日打卡',
    daily_checkin: '每日打卡',
    checkin: '每日打卡',
    referral: '推薦新會員加入獎勵',
    referral_bonus: '推薦新會員加入獎勵',
    signup: '註冊獎勵',
    signup_bonus: '註冊獎勵',
    admin_adjust: '管理員調整',
    admin_adjustment: '管理員調整'
};

// 會員資料庫的任務清單不一定會帶 title／group，只給 taskId（first_analysis 之類）。
// 缺的時候用本機任務定義補成中文，不要把代碼直接顯示給使用者。
function taskMeta(taskId) {
    const id = String(taskId || '').trim().toLowerCase();
    const hit = (typeof Tasks !== 'undefined' ? Tasks.list || [] : [])
        .find(t => String(t.id).toLowerCase() === id);
    if (hit) return { title: hit.title, group: hit.group };
    // 認不出來的代碼：把底線換成空白至少比原樣好讀，仍保留線索方便追查
    return { title: id ? id.replace(/_/g, ' ') : '任務', group: null };
}

function pointReasonLabel(reason) {
    const raw = String(reason || '').trim();
    if (!raw) return '點數異動';
    // 只有純英數底線才視為代碼；中文敘述直接顯示
    if (!/^[a-z0-9_]+$/i.test(raw)) return raw;

    const key = raw.toLowerCase();
    if (POINT_REASON_LABELS[key]) return POINT_REASON_LABELS[key];

    // 連續簽到獎勵：check_in_streak_bonus_3d
    const streak = key.match(/^check_?in_streak_bonus_(\d+)d?$/);
    if (streak) return `連續簽到 ${streak[1]} 天獎勵`;

    // 兌換主題：redeem_theme_rose → 兌換主題：玫瑰柔霧
    const theme = key.match(/^redeem_theme_(.+)$/);
    if (theme) {
        const hit = (typeof MemberRewards !== 'undefined' ? MemberRewards.themes || [] : [])
            .find(t => String(t.id).toLowerCase() === theme[1]);
        return `兌換主題：${hit ? hit.name : theme[1]}`;
    }

    // 任務獎勵：task_first_analysis → 任務獎勵：完成第一次臉部分析
    const task = key.match(/^task_(.+)$/);
    if (task) {
        const hit = (typeof Tasks !== 'undefined' ? Tasks.list || [] : [])
            .find(t => String(t.id).toLowerCase() === task[1]);
        return `任務獎勵：${hit ? hit.title : task[1]}`;
    }

    return raw;
}

// 最多讀取 30 頁，避免後端重複回傳同一個游標時無限請求。
const PRODUCT_MAX_PAGES = 30;

// 商品清單載入過了嗎。
//
// `null` = 還沒載過，或被主動清掉要求重抓（後台改完商品就是這樣強制刷新的）。
// `[]`   = 載過了，只是一件都沒有——後台把商品全下架時的正常結果。
//
// 這兩件事**必須分開**，而用 `.length` 判斷會把它們混成同一件事：
// 空清單被當成「還沒載」，於是每次重畫都再抓一次，而每次抓都會把
// generalProductLoading 設成 true，畫面就永遠停在「商品載入中」。
// 使用者看到的是「一直在載入」，實際上是後端已經回了 200 和一個空陣列，
// 而且那支 API 正在被無限重打。
function productCatalogLoaded() {
    return Array.isArray(Router?.generalProductCatalog);
}

function loadGeneralProductCatalog(onDone) {
    if (productCatalogLoaded()) {
        if (typeof onDone === 'function') onDone();
        return;
    }
    if (Router?.generalProductLoading) return;
    Router.generalProductLoading = true;
    // 第一次不限制筆數；若後端回 nextCursor，再依游標讀取後續頁面。
    (async () => {
        const all = [];
        const seen = new Set();
        const usedCursors = new Set();
        let cursor = null;
        let anyPageOk = false;
        let anyPageFailed = false;
        for (let page = 0; page < PRODUCT_MAX_PAGES; page++) {
            const rec = await Api.listProducts(cursor ? { cursor } : {});
            if (!rec || !rec.ok) { anyPageFailed = true; break; }
            anyPageOk = true;
            for (const p of rec.products || []) {
                // rawId 才是資料庫端的主鍵；id 在缺 rawId 時是隨機生成的，拿來去重會漏掉。
                const key = p.rawId != null ? `raw:${p.rawId}` : `id:${p.id}`;
                if (seen.has(key)) continue;
                seen.add(key);
                all.push(p);
            }
            const next = rec.nextCursor || null;
            // 沒有下一頁、這頁空的、或後端把同一個 cursor 回第二次（等於原地打轉）就停。
            if (!next || !(rec.products || []).length || usedCursors.has(next)) break;
            usedCursors.add(next);
            cursor = next;
        }
        Router.generalProductCatalog = all;
        // 一頁都沒成功才算失敗；中途斷掉是拿到部分清單，不該顯示成「商品服務無法載入」。
        Router.generalProductError = !anyPageOk || (anyPageFailed && !all.length);
    })()
        .catch(() => {
            Router.generalProductCatalog = [];
            Router.generalProductError = true;
        })
        .finally(() => {
            Router.generalProductLoading = false;
            if (typeof onDone === 'function') onDone();
        });
}

function getProductCatalog(){
    const base = Array.isArray(ALL_PRODUCTS) ? ALL_PRODUCTS : [];
    const overrides = (typeof AdminStore !== 'undefined') ? AdminStore.getOverrides() : {};
    const baseWithOverrides = base.map(p => overrides[p.id] ? { ...p, ...overrides[p.id] } : p);
    const adminProducts = (typeof AdminStore !== 'undefined') ? AdminStore.listProducts() : [];
    return [...adminProducts, ...baseWithOverrides].map((product, index) => {
        if (product.img) return product;
        const withImage = { ...product };
        if (typeof demoProductImage === 'function') withImage.img = demoProductImage(withImage, index);
        return withImage;
    });
}

// 用完整商品清單補齊推薦資料。
// 推薦與商品清單使用不同的 rawId，因此改用 salePageId 或完整名稱比對。
function fillRecommendedImages(list) {
    const catalog = Array.isArray(Router?.generalProductCatalog) ? Router.generalProductCatalog : [];
    return (Array.isArray(list) ? list : []).map((raw, index) => {
        const p = (raw && typeof raw === 'object') ? raw : {};
        const hit = catalog.find(g => (
            (p.salePageId && g.salePageId && p.salePageId === g.salePageId) ||
            (p.name && g.name && p.name === g.name)
        ));
        const stableId = p.id || hit?.id || (p.rawId != null ? `recommended-${p.rawId}` : `recommended-${index}-${String(p.name || 'product').slice(0, 24)}`);
        return hit
            ? { ...hit, ...p, id: stableId, img: p.img || hit.img, sourceUrl: p.sourceUrl || hit.sourceUrl }
            : { ...p, id: stableId };
    });
}

// 商品頁與推薦彈窗共用相同的顯示上限。
const RECOMMENDED_DISPLAY_LIMIT = 8;
// 商品頁一次只掛這麼多張卡。整份目錄有一千多筆，全部塞進 innerHTML 會產生約 1.1MB
// 的字串、上萬個節點與同樣數量的進場動畫；iOS Safari 的單分頁記憶體上限比桌機瀏覽器
// 嚴格得多，撐爆時會靜默重載分頁（使用者看到的是「整頁閃白後回到主頁」）。
const SHOP_PAGE_SIZE = 60;
// 只有第一批的前幾張套 reveal-in。動畫會讓每張卡各自成為合成層，數量一多就是純粹的
// 記憶體與 GPU 開銷，而使用者一次也只看得到最上面幾張。
const SHOP_ANIMATE_LIMIT = 12;

// ── 推薦結果的降級與錯誤提示 ──────────────────────────────────────────────
//
// 先前三個呼叫端都只取 rec.products，fallbackReasons 與 error 整包被丟掉，於是
// 後端明確標記的降級（「沒有可靠眉色，眉彩改依風格排序」「膚色取樣不可信，底妝
// 改依季型排序」）在畫面上完全看不到——使用者拿到的是一個沒有任何但書的推薦結果，
// 而契約 §4 正是要求這些情況必須說清楚。錯誤碼同理：502／504 是可重試的暫時故障，
// 422 是要請使用者重做臉部分析，兩者混成一句「載入失敗」就等於沒有分流。
const RecommendationNotice = {
    reasons: [],
    error: null,        // { code, message, requestId, retryable }
    isEmpty: false,
    _retry: null,       // 重試時要重跑的函式

    // 契約 §4 的四個降級碼。措辭的重點是「不要宣稱做了沒做的事」——
    // 尤其 BROW_COLOR_UNAVAILABLE，那條就是為了防止畫面說「眉彩已依膚色精準比對」。
    _REASON_TEXT: {
        BROW_COLOR_UNAVAILABLE: '眉彩依風格排序（不以膚色比對眉彩色號）',
        SKIN_TONE_LAB_UNRELIABLE: '底妝以季型與膚色分級排序，未使用色差比對',
        STYLE_KEYWORD_NO_MATCH: '未命中風格關鍵字，已改用合格商品綜合排序',
    },

    // 契約 §5 的錯誤碼。使用者看得懂的話，且只有真的可以重試的才給重試。
    _ERROR_TEXT: {
        INVALID_REQUEST: '推薦條件有誤，請重新選擇風格後再試。',
        INVALID_ANALYSIS_PACKAGE: '臉部分析資料不完整，請重新完成臉部分析。',
        INVALID_FACE_ANALYSIS: '臉部分析資料不完整，請重新完成臉部分析。',
        UNKNOWN_MAKEUP_STYLE: '這個妝容風格目前無法推薦，請換一個風格。',
        // 401／403 是身分問題，不是推薦壞掉。措辭要指向使用者能做的事。
        UNAUTHENTICATED: '登入狀態已失效，請重新登入後再試。',
        ACCOUNT_SUSPENDED: '這個帳號目前已停權，請聯絡客服。',
        // CSRF 被擋通常是環境設定問題（Origin 不在允許清單），使用者做什麼都沒用，
        // 所以**不給重試按鈕**——讓人一直按只是浪費他的時間。
        CSRF_ORIGIN_REJECTED: '這個來源的請求被安全機制擋下，請回報這個代碼給我們。',
        // 送出的資料裡含個資或影像被後端擋下。這是我們的 bug，不是使用者的錯，
        // 所以不要叫他「檢查輸入」——他沒有輸入任何東西。
        IDENTITY_DATA_NOT_ALLOWED: '推薦請求被安全檢查擋下，請回報這個代碼給我們。',
        PRODUCT_DB_UNAVAILABLE: '商品服務暫時無法使用。',
        PRODUCT_DB_TIMEOUT: '商品查詢逾時。',
        NETWORK_ERROR: '連線不穩，沒能取得推薦商品。',
    },

    // 每次呼叫 recommendProducts 之後都要記一次，包含成功的情況——
    // 成功時要把上一輪的錯誤清掉，否則提示會一直留在畫面上。
    record(rec, retryFn) {
        this._retry = typeof retryFn === 'function' ? retryFn : null;
        if (!rec || rec.ok === false) {
            this.reasons = [];
            this.isEmpty = false;
            this.error = {
                code: rec?.code || 'NETWORK_ERROR',
                requestId: rec?.requestId || '',
                // 502／504 是上游暫時不可用，重試有意義；422 重試幾次都一樣。
                retryable: rec?.retryable === true,
            };
            return;
        }
        this.error = null;
        // 粉底相鄰色階存在 Router 上，讓商品詳情頁畫得出來——它跟著這一次推薦，
        // 不屬於任何單一商品。null 就是「沒有這個區塊」，畫面要整個隱藏。
        Router.shadeRecommendation = rec.shadeRecommendation || null;
        // 粉底門檻的判定結果（契約 2026-08-27 §4）。no_match 時不能拿最接近但
        // 超標的色號硬補——那正是這個門檻要防的事：2.54 的色差上臉看得出來，
        // 而「系統推薦的」這五個字會讓人以為它已經檢查過了。
        this.foundationStatus = (rec.foundationMatchStatus
            && typeof rec.foundationMatchStatus === 'object') ? rec.foundationMatchStatus : null;
        // 契約 §3：personalization 要讓使用者知道有沒有套用個人化、依據多少互動。
        // 後端一直有回這包，先前前端完全沒用——於是「這是依你的使用紀錄推的」還是
        // 「這只是依這次的臉部分析推的」，畫面上分不出來。
        this.personalization = (rec.personalization && typeof rec.personalization === 'object')
            ? rec.personalization : null;
        const list = Array.isArray(rec.fallbackReasons) ? rec.fallbackReasons : [];
        this.reasons = list.filter(r => r && r.code !== 'RECOMMENDATION_EMPTY');
        this.isEmpty = !rec.products?.length
            || list.some(r => r?.code === 'RECOMMENDATION_EMPTY');
    },

    clear() {
        this.reasons = []; this.error = null; this.isEmpty = false; this.personalization = null;
        this.foundationStatus = null;
        Router.shadeRecommendation = null;
    },

    // 這批推薦是依什麼推的。措辭要能區分「只用了這次的臉部分析」與
    // 「已納入你過去的使用紀錄」——兩者對使用者的意義完全不同，
    // 不能都寫成「為您推薦」。
    personalizationHtml() {
        const p = this.personalization;
        if (!p) return '';
        const n = Number(p.interactionCount) || 0;
        if (p.applied === true && n > 0) {
            return `<div class="rec-personal">已納入您先前的 ${n} 筆收藏與試妝紀錄</div>`;
        }
        // 未登入或互動不足時，後端只用這次的臉部分析與風格。說清楚比含糊好：
        // 使用者才知道登入之後結果會更貼近自己。
        return '<div class="rec-personal">依這次的臉部分析與妝容風格推薦（尚未納入使用紀錄）</div>';
    },

    // 粉底沒有色號通過門檻時的說明。
    //
    // 訊息一律用後端給的：門檻與最接近的色差都在那邊算，前端再寫一份說法，
    // 兩邊遲早會不一致——而不一致的樣子是「畫面說 2.5、後端說 2.54」。
    //
    // 這一段刻意**不給任何購買入口**。最接近的那支確實存在，但它沒通過門檻；
    // 放一顆按鈕在旁邊等於把「我們查過了」的信任借給一個沒通過檢查的商品。
    foundationNoticeHtml() {
        const st = this.foundationStatus;
        if (!st || st.status === 'matched' || st.status === 'not_requested') return '';
        const msg = String(st.message || '').trim();
        if (!msg) return '';
        // closest_available 與 no_match 的差別，使用者一定要看得出來：
        //   closest_available  清單上那件是「最接近的」，可以看、可以買，但沒通過門檻
        //   no_match           連最接近的都超過 5，清單上根本沒有粉底
        // 兩者都用後端的訊息，只有補充那句不同——講錯的話，
        // 「沒有相近色號」會被讀成「什麼都沒有」，或反過來。
        const extra = st.status === 'no_match'
            ? '建議重新確認拍攝光線，或到實體通路試色。'
            : st.status === 'closest_available'
                ? '下面那件是目前最接近的，仍建議實際試色。'
                : '';
        return `<div class="rec-foundation-note rfn-${escapeHtml(String(st.status))}">
            <span class="rfn-mark">✦</span>
            <div><p>${escapeHtml(msg)}</p>
            ${extra ? `<p class="rfn-sub">${escapeHtml(extra)}</p>` : ''}</div>
        </div>`;
    },

    // 畫面上方的一條提示。沒有東西要說時回空字串，不佔版面。
    html() {
        if (this.error) {
            const msg = this._ERROR_TEXT[this.error.code] || '推薦商品暫時無法載入。';
            const rid = this.error.requestId
                ? `<span class="rec-note-id">代碼 ${escapeHtml(this.error.requestId.slice(0, 12))}</span>` : '';
            const retry = this.error.retryable
                ? '<button type="button" data-rec-retry="1">重試</button>' : '';
            return `<div class="rec-note is-error">${escapeHtml(msg)}${retry}${rid}</div>`;
        }
        if (!this.reasons.length) return '';
        // 同一個 code 只說一次；後端會針對不同品類各給一筆。
        const seen = new Set();
        const texts = [];
        for (const r of this.reasons) {
            if (!r?.code || seen.has(r.code)) continue;
            seen.add(r.code);
            texts.push(this._REASON_TEXT[r.code] || r.message || '');
        }
        const shown = texts.filter(Boolean);
        if (!shown.length) return '';
        return `<div class="rec-note">${shown.map(t => escapeHtml(t)).join('　·　')}</div>`;
    },

    // 空結果的畫面。契約 §4 說得很直接：不可以製造假商品填版面。
    emptyHtml() {
        return `<div class="empty-state">
            目前沒有符合的商品
            <div class="rec-empty-actions">
                <button type="button" class="btn-outline btn-sm" data-rec-reanalyze="1">重新分析</button>
                <button type="button" class="btn-outline btn-sm" data-rec-browse="1">瀏覽所有商品</button>
            </div>
        </div>`;
    },

    // 提示裡的按鈕。呼叫端在插入 HTML 之後呼叫一次。
    bind(root) {
        if (!root) return;
        const retry = root.querySelector('[data-rec-retry]');
        if (retry) retry.onclick = () => {
            const fn = this._retry;
            this.clear();
            if (fn) fn();
        };
        const again = root.querySelector('[data-rec-reanalyze]');
        if (again) again.onclick = () => Router.go('analysis');
        const browse = root.querySelector('[data-rec-browse]');
        if (browse) browse.onclick = () => {
            // 一律走 Router.go：`renderShop` 是 PageInit.products 裡面的區域函式，
            // 從這裡呼叫得到的是 ReferenceError——按鈕在商品頁上按下去會直接壞掉，
            // 而錯誤只留在 console，畫面上什麼都不會發生。
            // Router.go 進到商品頁本來就會重畫成「全部」。
            Router.go('products');
        };
    },
};

// ── 推薦依據（設計文件 §19.10 的「查看推薦依據」）─────────────────────────
//
// 後端一直都有回 scoreBreakdown 的八項分數與 matchedKeywords，但前端在
// _normalizeProduct 就把它們丟掉了，畫面上只剩一行 matchReason。使用者因此
// 只看得到「推薦這個」，看不到「為什麼」。
//
// 分數標籤刻意避開「準確率」「符合度」這類字眼：matchScore 是排序分數，
// 不是模型準確率，契約 §3 明文禁止那樣稱呼。
const SCORE_LABELS = Object.freeze({
    colorScore: '色彩適配',
    styleScore: '風格適配',
    featureScore: '臉部特徵',
    priceFit: '價格符合',
    brandAffinity: '品牌偏好',
    behaviorScore: '個人行為',
    availabilityScore: '供貨狀態',
    contentScore: '綜合內容',
});
// 顯示順序＝對使用者的意義，不是後端回傳的順序。
const SCORE_ORDER = ['colorScore', 'styleScore', 'featureScore', 'priceFit',
                     'brandAffinity', 'behaviorScore', 'availabilityScore', 'contentScore'];

// ── 推薦結果的價格／品牌篩選 ────────────────────────────────────────────
//
// ⚠️ 這是在**已經拿回來的那批推薦**裡篩選，不是搜尋全部商品。
// 推薦端一次只回 8–12 件，所以選了「400 元以下」很可能一件都不剩——那不代表
// 商品庫沒有這個價位（全庫 1041 件，四分位是 332 / 900 / 1200），只代表這批推薦裡沒有。
// UI 必須把這件事講明白，否則使用者會以為平台沒有便宜的商品。
//
// 要做成真正的推薦條件得後端支援 pricePreference 與 avoidedBrands 的硬過濾，
// 已回報：補充文件md檔案/給演算法端_個人化推薦實作差異與改善需求_2026-08-23.md B2、B3。
const RecFilter = {
    price: 'all',
    brand: 'all',

    // 價格級距依全庫實際分布訂（p25=332、中位=900、p75=1200），不是隨手取整數。
    // 這樣每一段大致對得上四分之一的商品，而不是某一段塞滿、某一段空著。
    PRICE_BANDS: Object.freeze([
        { id: 'all',  label: '不限價格' },
        { id: 'p1',   label: '400 以下',    max: 400 },
        { id: 'p2',   label: '400–900',     min: 400, max: 900 },
        { id: 'p3',   label: '900–1500',    min: 900, max: 1500 },
        { id: 'p4',   label: '1500 以上',   min: 1500 },
    ]),

    // 價格是 "NT$950" 這種字串，不是數字。解析不出來就回 null，
    // 而不是當成 0——當成 0 會讓它落進最低價那一段，看起來像有結果其實是錯的。
    parsePrice(raw) {
        const m = String(raw ?? '').replace(/,/g, '').match(/(\d+(?:\.\d+)?)/);
        return m ? Number(m[1]) : null;
    },

    matches(p) {
        if (this.brand !== 'all' && String(p.brand || '') !== this.brand) return false;
        if (this.price === 'all') return true;
        const band = this.PRICE_BANDS.find(b => b.id === this.price);
        if (!band) return true;
        const v = this.parsePrice(p.price);
        if (v == null) return false;   // 沒有價格就不該出現在價格篩選的結果裡
        if (band.min != null && v < band.min) return false;
        if (band.max != null && v > band.max) return false;
        return true;
    },

    apply(list) {
        return (Array.isArray(list) ? list : []).filter(p => this.matches(p));
    },

    isActive() { return this.price !== 'all' || this.brand !== 'all'; },
    reset() { this.price = 'all'; this.brand = 'all'; },

    // 品牌選項只列這批推薦裡真的有的品牌——列出全部 34 個品牌，
    // 其中 30 個選了都是空結果，那種選單只會浪費使用者的時間。
    brandsIn(list) {
        const c = new Map();
        for (const p of (list || [])) {
            const b = String(p.brand || '').trim();
            if (b) c.set(b, (c.get(b) || 0) + 1);
        }
        return [...c.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    },

    html(list) {
        const brands = this.brandsIn(list);
        const priceChips = this.PRICE_BANDS.map(b =>
            `<button type="button" class="rf-chip ${this.price === b.id ? 'active' : ''}" data-rf-price="${b.id}">${b.label}</button>`
        ).join('');
        const brandChips = [`<button type="button" class="rf-chip ${this.brand === 'all' ? 'active' : ''}" data-rf-brand="all">全部品牌</button>`]
            .concat(brands.map(([b, n]) =>
                `<button type="button" class="rf-chip ${this.brand === b ? 'active' : ''}" data-rf-brand="${escapeHtml(b)}">${escapeHtml(b)}<span class="rf-n">${n}</span></button>`
            )).join('');
        return `<div class="rec-filter">
            <div class="rf-note">在這 ${list.length} 件推薦中篩選<span class="rf-hint">（不是搜尋全部商品）</span></div>
            <div class="rf-row">${priceChips}</div>
            <div class="rf-row">${brandChips}</div>
        </div>`;
    },

    // 篩到沒東西時，要說清楚是「這批推薦裡沒有」而不是「平台沒有」。
    emptyHtml() {
        return `<div class="rf-empty">
            這批推薦中沒有符合條件的商品。<br>
            <span class="rf-hint">推薦一次只挑出每個品類最適合的幾件，換個條件或到下方瀏覽全部商品看看。</span>
            <div class="rec-empty-actions">
                <button type="button" class="btn-outline btn-sm" data-rf-reset="1">清除篩選</button>
            </div>
        </div>`;
    },

    bind(root, redraw) {
        if (!root) return;
        root.querySelectorAll('[data-rf-price]').forEach(el => el.onclick = () => {
            this.price = el.dataset.rfPrice; redraw();
        });
        root.querySelectorAll('[data-rf-brand]').forEach(el => el.onclick = () => {
            this.brand = el.dataset.rfBrand; redraw();
        });
        const reset = root.querySelector('[data-rf-reset]');
        if (reset) reset.onclick = () => { this.reset(); redraw(); };
    },
};

// ── 色塊比對：你的顏色 vs 商品顏色 ──────────────────────────────────────
//
// 分數說「色彩適配 0.66」，但 0.66 是什麼感覺沒有人知道。把兩個顏色並排放，
// 使用者自己一眼就能判斷準不準——這比任何數字都直接，也讓她能不同意系統。
//
// ⚠️ 比對的對象必須依品類選對：粉底比膚色、唇彩比唇色。配錯的話色塊會並排
// 顯示兩個不相干的顏色，看起來像系統算錯了。這個對應與後端實測的行為一致
// （換膚色時眼影 colorScore 會變、唇彩不會變）。
const COMPARE_SOURCE = Object.freeze({
    foundations: 'skin',
    blushes: 'skin',
    contouring: 'skin',
    highlighters: 'skin',
    eyeshadows: 'skin',
    eyeliner_mascara: 'skin',
    lipsticks: 'lip',
    // eyebrows 沒有對應：臉部分析端不產出眉色，拿膚色比是契約明文禁止的。
});

const COMPARE_LABEL = Object.freeze({ skin: '您的膚色', lip: '您的唇色' });

function userLabFor(kind) {
    const fa = Router.analysisPackage?.faceAnalysis;
    if (!fa) return null;
    const raw = kind === 'lip' ? fa.lipLab : fa.skinTone?.lab;
    if (!raw) return null;
    // 分析結果可能是 {L,a,b} 也可能是 [L,a,b]，兩種都要接。
    const arr = Array.isArray(raw)
        ? raw.map(Number)
        : [raw.L ?? raw.l, raw.a ?? raw.A, raw.b ?? raw.B].map(Number);
    return arr.length === 3 && arr.every(Number.isFinite) ? arr : null;
}

function colorCompareHtml(p) {
    const kind = COMPARE_SOURCE[p?.type || p?.cat];
    if (!kind) return '';
    const prodLab = Array.isArray(p.lab) && p.lab.length === 3 && p.lab.every(n => Number.isFinite(Number(n)))
        ? p.lab.map(Number) : null;
    const userLab = userLabFor(kind);
    // 缺任何一邊就不顯示。只放一個色塊沒有比較的意義，還會讓人以為那是「建議色」。
    if (!prodLab || !userLab) return '';

    const userCss = Api.labToRgb(userLab[0], userLab[1], userLab[2]);
    const prodCss = Api.labToRgb(prodLab[0], prodLab[1], prodLab[2]);
    if (!userCss || !prodCss) return '';

    // 膚色取樣不可信時要說出來，否則使用者會拿一個本來就不準的色塊去判斷商品。
    const reliable = Router.analysisPackage?.faceAnalysis?.skinTone?.labReliable !== false;
    const warn = (kind === 'skin' && !reliable)
        ? '<div class="cc-warn">膚色取樣可能不準（臉頰被頭髮或陰影遮住），這個比對僅供參考</div>' : '';

    return `<div class="color-compare">
        <div class="cc-pair">
            <span class="cc-item"><span class="cc-dot" style="background:${userCss}"></span>${COMPARE_LABEL[kind]}</span>
            <span class="cc-vs">對</span>
            <span class="cc-item"><span class="cc-dot" style="background:${prodCss}"></span>商品色</span>
        </div>
        ${warn}
    </div>`;
}

// 推薦標籤只有一個來源。
//
// 契約 2026-08-28 §5 把措辭從「根據系統演算法推薦」改成「根據臉部分析結果推薦」，
// 並要求全站不得再出現舊的那一句。後端可能還在回舊字串（切換不會同一天完成），
// 所以這裡把它映射掉——只認舊的那一句，其他自訂措辭照樣尊重後端。
//
// 為什麼要換：「系統演算法」說的是**我們怎麼算的**，「臉部分析結果」說的是
// **這個推薦根據什麼**。使用者關心的是後者，而前者聽起來像在強調有演算法。
const REC_LABEL = '根據臉部分析結果推薦';
const LEGACY_REC_LABEL = '根據系統演算法推薦';
function recLabel(raw) {
    const text = String(raw || '').trim();
    if (!text || text === LEGACY_REC_LABEL) return REC_LABEL;
    return text;
}

// 唇彩永遠不顯示配對百分比、唇色色差與色差明細（契約 2026-08-28 §5.4）。
//
// 唇彩是依整體妝容風格與臉部特徵推薦的，**不以使用者原始唇色做色差配對**。
// 印一個百分比或色差，等於宣稱做了一件沒做的比對；而使用者分不出那個數字
// 是「跟你的唇色比」還是「跟你的風格比」。
//
// 這推翻了 2026-08-26 的色差 QA 契約（當時唇彩寫的是「比自然唇色」）。
// 兩份契約衝突時以新的為準，舊的那條在這裡失效。
function isLipProduct(p) {
    return String(p?.apiType || '') === 'lipsticks' || String(p?.cat || '') === '唇彩';
}

// 推薦端整理好的使用者文案（契約 2026-08-v2 §4.3）。
//
// 為什麼一律以它為準，不再由前端拼：技術分數（matchScore、scoreBreakdown、ΔE）
// 翻成人話的工作只能有一個地方做。兩邊各翻一次，同一件事就會出現兩種說法，
// 而使用者不知道該信哪一個。後端已經決定好措辭，前端照著顯示。
//
// 契約明訂的三條紅線，都在這裡守住：
//   1. 標籤一律是「根據系統演算法推薦」，**不得寫成「AI 推薦」**
//   2. matchPercent 是排序用的綜合匹配度，**不是準確率**——所以緊接著標示「推薦匹配度」
//   3. deltaE、Jaccard、權重與 scoreBreakdown **不進一般推薦卡**
function recommendationCardHtml(p) {
    const pr = p?.recommendationPresentation;
    if (!pr || typeof pr !== 'object') return '';

    // 沒通過膚色門檻、只是「目前最接近」的粉底（契約 2026-08-27 §5）。
    // 這種商品**不能**寫「根據系統演算法推薦」也不能印 MATCH——
    // 它出現在清單上是因為沒有更好的，不是因為它合格。
    // 兩句話都是背書，而使用者分不出「系統推薦的」與「系統找到最接近的」差在哪，
    // 除非畫面自己講清楚。
    const closest = p?.foundationSkinMatch?.displayStatus === 'closest_available';
    if (closest) {
        const d = p.foundationSkinMatch;
        const de = (d.deltaE == null || !Number.isFinite(Number(d.deltaE)))
            ? null : Number(d.deltaE);
        return `<div class="rec-closest">
            <div class="rec-closest-tag">目前最接近的可比較色號</div>
            ${de != null ? `<div class="rec-closest-de">與您的膚色的色差 ${de.toFixed(1)}</div>` : ''}
            <p class="rec-closest-note">此色號未達正式匹配門檻，實際妝效可能仍有差異，建議實際試色。</p>
        </div>`;
    }

    const parts = [];
    parts.push(`<div class="rec-sys">${escapeHtml(recLabel(pr.systemLabel))}</div>`);
    if (p?.showMatchPercent !== false
        && (pr.matchLabel || Number.isFinite(Number(pr.matchPercent)))) {
        const label = pr.matchLabel || `${Math.round(Number(pr.matchPercent))}% MATCH`;
        // 「推薦匹配度」這四個字是契約要求的，不能省：少了它，95% MATCH
        // 會被讀成「95% 準確」或「95% 會適合」，而那兩個都不是它的意思。
        parts.push(`<div class="rec-match"><b>${escapeHtml(label)}</b><small>推薦匹配度</small></div>`);
    }
    if (pr.headline) parts.push(`<div class="rec-headline">${escapeHtml(pr.headline)}</div>`);
    const traits = Array.isArray(pr.suitedTraits) ? pr.suitedTraits.filter(Boolean).slice(0, 4) : [];
    if (traits.length) {
        parts.push(`<div class="rec-traits">${traits
            .map(t => `<span>${escapeHtml(String(t))}</span>`).join('')}</div>`);
    }
    return parts.join('');
}

// 膚色色差與門檻這兩句只由這裡產生。
//
// 它們原本在推薦面板與色號比較區各寫一次，於是詳情頁上「✦ 根據系統演算法推薦 /
// 84% MATCH / 色差 1.3」整組出現兩遍——同一件事講兩次，第二次不會更有說服力，
// 只會讓人以為那是兩個不同的判斷。
function foundationSkinLines(skin) {
    if (!skin || typeof skin !== 'object') return { matchWord: '', gate: '' };
    // ⚠️ 不能直接 Number()：null 會變成 0，「沒有資料」就成了「色差 0.0」——
    // 那是顏色完全相同，是最有把握的一句話，卻在沒有資料時說出口。
    const d = (skin.deltaE != null && skin.deltaE !== '' && Number.isFinite(Number(skin.deltaE)))
        ? Number(skin.deltaE) : null;
    return {
        matchWord: d == null ? ''
            : d <= 1 ? `與您的膚色非常接近（色差 ${d.toFixed(1)}）`
            : `與您的膚色接近（色差 ${d.toFixed(1)}）`,
        // 門檻寫出來，使用者才知道這個「接近」是照什麼標準說的。
        gate: (skin.accepted === true && Number.isFinite(Number(skin.maxInclusive)))
            ? `這款粉底通過系統設定的膚色色差 ${Number(skin.minInclusive ?? 0)}～${Number(skin.maxInclusive)} 推薦門檻。`
            : ''
    };
}

// 色差解釋的入口（契約 2026-08-26）。
//
// 只有粉底（比膚色）與唇彩（比自然唇色）會有；眼影、腮紅、修容、打亮、眉彩
// 主要依妝容風格推薦，後端一律回 null，前端**不得**顯示色差 QA——
// 對一個不是靠顏色排出來的商品講色差，等於憑空給一個不存在的依據。
function colorDiffInfo(p) {
    const info = p?.recommendationPresentation?.colorDifferenceExplanation;
    if (!info || typeof info !== 'object') return null;
    // ⚠️ 不能用 truthy 判斷 value：色差 0 是「完全相同」，是最好的結果，
    // 而 `if (info.value)` 會把它當成沒有值而整個藏起來。
    return (typeof info.value === 'number' && Number.isFinite(info.value)) ? info : null;
}

function colorDiffEntryHtml(p) {
    const info = colorDiffInfo(p);
    if (!info) return '';
    return `<button type="button" class="cd-entry" data-color-diff="${escapeHtml(String(p.id))}">
        色差是什麼？</button>`;
}

// 色差說明視窗。內容**全部**來自後端，前端不重算等級也不換算成準確率。
//
// 為什麼不自己算 level：後端有 ranges，前端若照著自己判一次，兩邊的區間
// 遲早會不一致——而不一致的樣子是「同一個 4.6，卡片說相近、視窗說有可見差異」。
// 只有一份判斷來源，就不會有這種事。
//
// 也不把色差換算成百分比或「保證適合」：ΔE 是**視覺距離**，不是命中率。
// 說成準確率是在給一個這個數字撐不起的承諾。
function openColorDiffModal(product) {
    const info = colorDiffInfo(product);
    if (!info) return;
    document.getElementById('colorDiffModal')?.remove();

    const qa = Array.isArray(info.qa) ? info.qa.filter(x => x && x.question && x.answer) : [];
    const ranges = Array.isArray(info.ranges) ? info.ranges : [];

    const ov = document.createElement('div');
    ov.id = 'colorDiffModal';
    ov.className = 'sr-overlay';
    ov.innerHTML = `<div class="cd-dialog" role="dialog" aria-modal="true" aria-labelledby="cdTitle">
        <button class="sr-close" type="button" aria-label="關閉">×</button>
        <h3 id="cdTitle">${escapeHtml(String(info.displayValue || ''))}｜${escapeHtml(String(info.level || ''))}</h3>
        ${info.comparisonTarget
            ? `<div class="cd-target">比較對象：${escapeHtml(String(info.comparisonTarget))}</div>` : ''}
        ${info.summary ? `<p class="cd-summary">${escapeHtml(String(info.summary))}</p>` : ''}
        ${info.shortExplanation
            ? `<p class="cd-short">${escapeHtml(String(info.shortExplanation))}</p>` : ''}
        ${ranges.length ? `<table class="cd-ranges"><tbody>${ranges.map(r => {
            // min/max 的表示法有兩種（min 與 minExclusive），照後端給的畫，不自己補。
            const lo = (r.minExclusive != null) ? `大於 ${r.minExclusive}` : `${r.min ?? 0}`;
            const hi = (r.max == null) ? '以上' : `～${r.max}`;
            const cur = String(r.label || '') === String(info.level || '');
            return `<tr${cur ? ' class="cd-here"' : ''}>
                <td class="cd-range">${escapeHtml(lo + hi)}</td>
                <td class="cd-level">${escapeHtml(String(r.label || ''))}</td>
                <td class="cd-note">${escapeHtml(String(r.description || ''))}</td></tr>`;
        }).join('')}</tbody></table>` : ''}
        ${qa.length ? `<div class="cd-qa">${qa.map((x, i) => `
            <details${i === 0 ? ' open' : ''}>
                <summary>${escapeHtml(String(x.question))}</summary>
                <p>${escapeHtml(String(x.answer))}</p>
            </details>`).join('')}</div>` : ''}
        ${info.fullExplanation
            ? `<p class="cd-full">${escapeHtml(String(info.fullExplanation))}</p>` : ''}
    </div>`;
    document.body.appendChild(ov);

    // 焦點：移進來、關掉時還回去。只能用滑鼠關掉的浮層，
    // 對鍵盤操作的人等於卡死整個頁面。
    const previouslyFocused = document.activeElement;
    const closeBtn = ov.querySelector('.sr-close');
    closeBtn.focus();
    const close = () => {
        ov.remove();
        document.removeEventListener('keydown', onKey);
        if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
    };
    const onKey = (ev) => { if (ev.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    closeBtn.onclick = close;
    ov.addEventListener('click', (ev) => { if (ev.target === ov) close(); });
}

// 詳情頁的推薦面板：把卡片版與詳情版收進一個容器。
//
// 為什麼要這一層：先前詳情頁是把 recommendationCardHtml 與 recommendationDetailHtml
// 兩個鬆散的 div 直接疊在商品說明下面，沒有任何容器。結果整段推薦理由讀起來
// 就是幾行灰字，跟上面的商品描述分不開——而這一段正是「為什麼推這個給你」，
// 是整個推薦功能要講的話。
//
// 用跟粉底色號那塊（.sr-hero）同一套視覺語彙：頂端一道流光金線、實心底、
// 匹配度放大。同一個系統講同一件事，不該長成兩種樣子。
function recommendationPanelHtml(p) {
    const pr = p?.recommendationPresentation;
    if (!pr || typeof pr !== 'object') return '';

    // 只是「目前最接近」的粉底，詳情頁也不能給它推薦面板那一套：
    // 大字匹配度、✦ 演算法推薦、適合特質標籤——每一項都是背書，
    // 而它並沒有通過膚色門檻（契約 2026-08-27 §5、§7）。
    const closest = p?.foundationSkinMatch?.displayStatus === 'closest_available';
    if (closest) {
        const d = p.foundationSkinMatch;
        const de = (d.deltaE == null || !Number.isFinite(Number(d.deltaE)))
            ? null : Number(d.deltaE);
        return `<section class="rec-panel rec-panel-closest">
            <div class="rec-panel-head">
                <span class="rec-closest-tag">目前最接近的可比較色號</span>
                ${de != null
                    ? `<div class="rec-closest-de">與您的膚色的色差 ${de.toFixed(1)}</div>` : ''}
            </div>
            <div class="rec-panel-body">
                <p class="rec-summary">此色號未達正式匹配門檻，實際妝效可能仍有明暗或冷暖差異，建議實際試色。</p>
                ${colorDiffEntryHtml(p)}
            </div>
        </section>`;
    }

    const pct = (pr.matchPercent == null || pr.matchPercent === '') ? NaN : Number(pr.matchPercent);
    const hasPct = Number.isFinite(pct) && p?.showMatchPercent !== false;
    const label = (p?.showMatchPercent === false) ? ''
        : (pr.matchLabel || (hasPct ? `${Math.round(pct)}% MATCH` : ''));
    const traits = Array.isArray(pr.suitedTraits) ? pr.suitedTraits.filter(Boolean).slice(0, 4) : [];
    const { matchWord, gate } = foundationSkinLines(p?.foundationSkinMatch);
    // 後端的 reasonTexts 常有一句就是「此色號與您的膚色相近（色差 1.3）」，
    // 而 matchWord 正要說同一件事。兩句並排讀起來像系統把同一個理由算了兩次，
    // 所以 matchWord 在場時濾掉講色差的那幾句，由 matchWord 統一說。
    const reasons = (Array.isArray(pr.reasonTexts) ? pr.reasonTexts.filter(Boolean) : [])
        .filter(r => !(matchWord && String(r).includes('色差')))
        .slice(0, 3);

    return `<section class="rec-panel">
        <div class="rec-panel-head">
            <span class="rec-eyebrow">✦ ${escapeHtml(recLabel(pr.systemLabel))}</span>
            ${label ? `<div class="rec-bigmatch">${escapeHtml(label)}</div>` : ''}
            <div class="rec-bigmatch-sub">推薦匹配度</div>
            ${pr.headline ? `<div class="rec-panel-headline">${escapeHtml(pr.headline)}</div>` : ''}
            ${traits.length ? `<div class="rec-traits">${traits
                .map(t => `<span>${escapeHtml(String(t))}</span>`).join('')}</div>` : ''}
        </div>
        <div class="rec-panel-body">
            ${pr.summary ? `<p class="rec-summary">${escapeHtml(pr.summary)}</p>` : ''}
            ${reasons.length ? `<ul class="rec-reasons">${reasons
                .map(r => `<li>${escapeHtml(String(r))}</li>`).join('')}</ul>` : ''}
            ${matchWord ? `<div class="rec-skinline">${escapeHtml(matchWord)}</div>` : ''}
            ${gate ? `<div class="rec-gate">${escapeHtml(gate)}</div>` : ''}
            ${colorDiffEntryHtml(p)}
            ${pr.disclaimer ? `<p class="rec-disclaimer">${escapeHtml(pr.disclaimer)}</p>` : ''}
        </div>
    </section>`;
}

// 外部商品連結。契約 §8.1 要求 rel="noopener noreferrer"。
//
// 那不是形式：沒有 noopener 的話，被開啟的那一頁可以用 window.opener 把我們這一頁
// 導去任何地方（反向 tabnabbing），而使用者剛才還在這裡輸入過登入資訊。
// noreferrer 順便不把來源網址洩漏給對方站台。
//
// 只接受 http(s)。`javascript:` 開頭的字串放進 href 就是一個可執行的腳本，
// 而商品資料來自爬蟲——那是外部輸入。
function productSourceLinkHtml(p) {
    const raw = String(p?.sourceUrl || p?.productUrl || '').trim();
    if (!/^https?:\/\//i.test(raw)) return '';
    return `<a class="pd-source" href="${escapeHtml(raw)}" target="_blank" rel="noopener noreferrer">查看商品原頁 ↗</a>`;
}

// 粉底相鄰色階（契約 §5）。
//
// 兩種模式的措辭**不能互換**：official_depth_index 是品牌官方的由淺至深順序，
// 可以說「淺一階／深一階」；lab_lightness_approximation 只是用 L* 比出來的近似，
// 只能說「較明亮／較深的替代色」。說錯的後果很具體——使用者以為那是品牌真的
// 相鄰的色號，照著去買會買錯。標籤在 Api._normalizeShadeRecommendation 依 method
// 決定好了，這裡只負責畫。
//
// 三種 null 各自要正確處理：
//   shadeRecommendation 是 null → 整個區塊不出現（不要自己補商品湊出三階）
//   lighter 或 darker 是 null   → 只隱藏那一格（主推薦已經是系列最淺或最深）
// null 與空字串都不是分數。分開判是因為 Number(null) 會變成 0，
// 而 0 是一個看起來很有意義、意思卻完全相反的分數。
function hasMatch(node) {
    const v = node && node.matchPercent;
    return v != null && v !== '' && Number.isFinite(Number(v));
}

// 這一次推薦的粉底相鄰色階。記憶體裡沒有就回草稿——重新整理之後
// Router.analysisPackage 不會被還原（見 3424 附近的說明），
// 而商品清單早就靠 AnalysisDraft.load() 撐過重載，色號沒有理由不一樣。
function currentShadeRecommendation() {
    // ⚠️ 三個來源存的都**已經是正規化過的**（Api.recommendProducts 就正規化了）。
    // 這裡再跑一次 _normalizeShadeRecommendation 的話，product 會被 _normalizeProduct
    // 二次加工，id 從 api-foundations-942 變成 api-底妝-api-foundations-942，
    // 於是那個「只在主推薦那件商品頁顯示」的比對永遠不成立——
    // 修好一個消失問題卻換來另一個。所以原樣回傳，不要再處理一次。
    if (Router.shadeRecommendation) return Router.shadeRecommendation;
    const fromPackage = Router?.analysisPackage?.recommendations?.shadeRecommendation;
    if (fromPackage) return fromPackage;
    const draft = typeof AnalysisDraft !== 'undefined' ? AnalysisDraft.load() : null;
    return draft?.recommendations?.shadeRecommendation || null;
}

// 使用者自己的膚色，擺在三欄上面當比較基準。
//
// 沒有它的話，三個色塊只能互相比——但使用者要回答的問題不是「這三支差多少」，
// 是「哪一支比較像我」。基準不在畫面上，那個問題就答不了。
//
// 取樣被判定不可信時要講出來（頭髮或陰影蓋住臉頰）：拿一個不可信的膚色去比色，
// 比不比還糟，因為使用者會以為自己比對過了。
function userSkinRow() {
    const skin = Router.analysisPackage?.faceAnalysis?.skinTone;
    const lab = skin?.lab;
    if (!Array.isArray(lab) || lab.length !== 3) return '';
    const color = Api.labToRgb(Number(lab[0]), Number(lab[1]), Number(lab[2]));
    if (!color) return '';
    const meta = [skin.season, skin.level].filter(Boolean).join(' · ');
    const bad = skin.labReliable === false;
    return `<div class="sc2-mine${bad ? ' is-unreliable' : ''}">
        <span class="sc2-swatch" aria-hidden="true" style="background:${escapeHtml(String(color))}"></span>
        <span class="sc2-mine-label">你的膚色${meta ? `<em>${escapeHtml(meta)}</em>` : ''}</span>
        ${bad ? '<span class="sc2-mine-warn">這次取樣可能不準（臉頰被遮住），色塊僅供參考</span>' : ''}
    </div>`;
}

function shadeRecommendationHtml(p) {
    const sr = currentShadeRecommendation();
    if (!sr || !sr.anchor) {
        // 這件是通過膚色門檻的粉底，卻沒有相鄰色號可畫——多半是**這台裝置上
        // 沒有這次的分析資料**。色階跟著「套用妝容風格 → 抓推薦」那一次流程來，
        // 而 session 是每台裝置各自獨立的：在電腦做過分析，換手機看同一件商品，
        // 手機這邊什麼都沒有。
        //
        // 默默不顯示是最糟的處理：使用者會以為功能壞了或這支沒有其他色號，
        // 而真正的原因（要先在這台裝置做一次分析）他無從得知。
        if (p?.foundationSkinMatch?.accepted === true) {
            return `<section class="shade-rec shade-rec-empty">
                <p>這台裝置上還沒有這次的臉部分析資料，所以無法比較相鄰色號。
                   完成一次臉部分析並選擇妝容風格之後，這裡會顯示同系列的較亮／較深色號。</p>
            </section>`;
        }
        return '';
    }
    // 只在看的就是主推薦那件商品時顯示，否則會出現在不相干的商品頁上。
    const anchorId = String(sr.anchor.product?.id ?? '');
    if (anchorId && String(p?.id ?? '') !== anchorId) return '';

    const a = sr.anchor;
    const pct = (a.matchPercent == null || a.matchPercent === '') ? NaN : Number(a.matchPercent);
    const hasPct = Number.isFinite(pct);

    // 主推薦的形容詞用**膚色色差**，不是 matchPercent：matchPercent 是綜合排序分數
    //（含風格、關鍵字、行為），拿它說「與你的膚色多接近」是用一個數字回答另一個問題。
    // 契約 2026-08-27 §7 要求主推薦寫的是膚色色差。
    const { matchWord, gate } = foundationSkinLines(a.product?.foundationSkinMatch);

    // 同一頁底下的推薦面板也會印「✦ 根據系統演算法推薦 / N% MATCH / 色差 / 門檻」。
    // 兩塊都印，整組就出現兩遍。這一區的工作是**比較色號**，背書歸推薦面板，
    // 所以推薦面板在場時這裡交出那四行；面板不在（後端沒給 recommendationPresentation）
    // 時才自己撐起來，否則色號比較會變成一排沒有前因後果的色塊。
    const panelCarriesHeader = Boolean(recommendationPanelHtml(p));

    // 三欄並排，而不是「主推薦 ＋ 兩列小字 ＋ 一顆要按的按鈕」。
    //
    // 替代色的用途是**比較**，而比較要看得到才成立。藏在 Modal 後面等於
    // 要求使用者先相信「裡面有東西值得看」才會點——多數人不會點，
    // 於是那兩支色號實際上等於不存在。
    //
    // 主推薦那一欄用底色與陰影抬起來：三欄等重會讓人以為三個都是推薦，
    // 但只有中間那個是。
    const hasVariants = Boolean(sr.lighter || sr.darker);

    const col = (node, kind, label) => {
        if (!node) return '';
        const prod = node.product || {};
        const np = (node.matchPercent == null || node.matchPercent === '')
            ? NaN : Number(node.matchPercent);
        // 每一欄底下那行數字，兩種角色講的是**不同的比較對象**：
        //   主推薦   與使用者膚色的色差（門檻 0～2）
        //   替代色   與主推薦色號的色差（門檻 0～5）
        // 契約 2026-08-27 §7 明文禁止把替代色寫成「與您的膚色高度匹配」——
        // 替代色本來就不必貼近膚色，它的用途是同系列裡明暗不同的選擇。
        // 先前這裡對三欄一律印 matchPercent，那個數字是綜合排序分數，
        // 放在替代色底下會被讀成「這支也很配你的膚色」，而那不是它的意思。
        // ⚠️ 不能直接丟給 Number：Number(null) 是 0，而 isFinite(0) 為真，
        // 於是「沒有色差資料」會被畫成「色差 0.0」——那是「顏色完全相同」，
        // 是最有把握的一句話，卻在完全沒有資料的時候說出口。
        // matchPercent 踩過同一個坑（見 hasMatch），這裡是第二次。
        const num = (v) => (v == null || v === '' || !Number.isFinite(Number(v)))
            ? null : Number(v);
        let metric = '';
        if (kind === 'anchor') {
            const skinDeltaE = num(node.product?.foundationSkinMatch?.deltaE);
            if (skinDeltaE != null) {
                metric = `與您的膚色的色差 ${skinDeltaE.toFixed(1)}`;
            } else if (Number.isFinite(np)) {
                metric = `${Math.round(np)}% MATCH`;
            }
        } else {
            const anchorDeltaE = num(node.anchorDeltaE);
            if (anchorDeltaE != null) {
                metric = `與主推薦色號的色差 ${anchorDeltaE.toFixed(1)}`;
            }
        }
        // 每一欄放一張小圖。色號代碼（PO-03）對使用者不構成任何畫面，
        // 而「比較深淺」本來就是用看的——沒有圖的比較區等於要人憑代碼想像顏色。
        //
        // 整欄可點，不是只有底下一顆小按鈕：目標大得多，而且「點這一格看這支」
        // 比「點那顆按鈕」少一層轉譯。主推薦那一欄不可點——你已經在它的頁面上了。
        const thumb = prod.img
            ? `<img class="sc2-img" src="${escapeHtml(String(prod.img))}"
                 alt="${escapeHtml(String(prod.name || node.shadeCode || ''))}" loading="lazy"
                 onerror="this.style.display='none'">`
            : '<div class="sc2-img sc2-img-none" aria-hidden="true"></div>';
        // 色塊。比較色號本來就是比顏色——只給 PO-03 這種代碼，等於要人憑三個
        // 字元想像那是什麼顏色。商品的 LAB 後端有給，轉成 RGB 直接畫出來。
        const lab = Array.isArray(prod.lab) && prod.lab.length === 3 ? prod.lab : null;
        const swatch = lab
            ? `<span class="sc2-swatch" aria-hidden="true"
                 style="background:${escapeHtml(String(Api.labToRgb(Number(lab[0]), Number(lab[1]), Number(lab[2]))))}"></span>`
            : '';
        const inner = `
            <div class="sc2-label">${escapeHtml(node.label || label)}</div>
            ${thumb}
            <div class="sc2-code">${swatch}${escapeHtml(String(node.shadeCode || '—'))}</div>
            ${metric ? `<div class="sc2-match">${escapeHtml(metric)}</div>` : ''}
            ${node.description ? `<p class="sc2-desc">${escapeHtml(node.description)}</p>` : ''}`;
        return (prod.id && kind !== 'anchor')
            ? `<button type="button" class="sc2-col sc2-${kind}"
                 data-shade-go="${escapeHtml(String(prod.id))}"
                 title="查看 ${escapeHtml(String(node.shadeCode || ''))} 的商品頁">${inner}</button>`
            : `<div class="sc2-col sc2-${kind}">${inner}</div>`;
    };

    // 兩段都可能被讓出去（背書歸推薦面板、色號歸中間那一欄），所以先組再判斷要不要
    // 這個容器——直接印一個空的 sr-hero 會在畫面上留下一塊有內距卻沒東西的空白。
    const heroInner = [
        panelCarriesHeader ? '' : `
            <div class="sr-eyebrow">✦ ${escapeHtml(REC_LABEL)}</div>
            ${hasPct ? `<div class="sr-bigmatch">${Math.round(pct)}% MATCH</div>` : ''}
            ${matchWord ? `<div class="sr-bigmatch-sub">${escapeHtml(matchWord)}</div>` : ''}
            ${gate ? `<div class="sr-gate">${escapeHtml(gate)}</div>` : ''}`,
        // 有並排的三欄時，主推薦的色號由中間那一欄負責——上下各印一次同樣的 PO-02
        // 只是佔位置，還會讓人以為是兩件事。沒有替代色可比時才在這裡印。
        hasVariants ? '' : `
            <div class="sr-anchor-label">${escapeHtml(a.label)}</div>
            <div class="sr-anchor-code">${escapeHtml(String(a.shadeCode || '—'))}</div>
            ${a.description ? `<p class="sr-anchor-desc">${escapeHtml(a.description)}</p>` : ''}`
    ].join('').trim();

    return `<section class="shade-rec">
        ${heroInner ? `<div class="sr-hero">${heroInner}</div>` : ''}
        ${hasVariants ? `
        <div class="sc2-wrap">
            <div class="sc2-head">想比較不同妝效？</div>
            ${userSkinRow()}
            <div class="sc2-row">
                ${col(sr.lighter, 'lighter', '較明亮的替代色')}
                ${col(a, 'anchor', '主推薦色號')}
                ${col(sr.darker, 'darker', '較深的替代色')}
            </div>
        </div>` : ''}
        ${(sr.disclaimer && !panelCarriesHeader)
            ? `<p class="sr-disclaimer">${escapeHtml(sr.disclaimer)}</p>` : ''}
    </section>`;
}

// ⚠️ 技術分數的展開區塊。契約 §4.2 明訂 scoreBreakdown「僅除錯／後台，不給一般使用者」，
// 所以它**已經從三個使用者畫面移除**。函式保留是為了後台除錯時還叫得出來。
function recommendationEvidenceHtml(p) {
    const sb = p?.scoreBreakdown;
    const kws = Array.isArray(p?.matchedKeywords) ? p.matchedKeywords.filter(Boolean) : [];
    if (!sb && !kws.length) return '';

    const rows = [];
    if (sb) {
        for (const key of SCORE_ORDER) {
            const v = sb[key];
            if (!Number.isFinite(Number(v))) continue;
            // 0 分的構面照樣顯示——「這一項沒有加到分」本身就是有用的資訊，
            // 藏起來會讓使用者以為系統沒有考慮它。
            rows.push(`<span class="ev-item"><span class="ev-k">${SCORE_LABELS[key]}</span>`
                + `<span class="ev-v">${Number(v).toFixed(2)}</span></span>`);
        }
    }
    const kwHtml = kws.length
        ? `<div class="ev-kw">命中關鍵字：${kws.map(k => `<em>${escapeHtml(String(k))}</em>`).join('、')}</div>`
        : '';
    if (!rows.length && !kwHtml) return '';

    return `<details class="rec-ev">
        <summary>查看推薦依據</summary>
        <div class="ev-body">${kwHtml}${rows.length ? `<div class="ev-grid">${rows.join('')}</div>` : ''}</div>
    </details>`;
}

// 每個分類先放入最高分商品，再依分數補上其餘推薦。
function orderRecommendedProducts(list) {
    const items = Array.isArray(list) ? list : [];
    const best = new Map();
    for (const p of items) {
        if (!p?.cat) continue;
        if (!best.has(p.cat) || (p.score ?? 0) > (best.get(p.cat).score ?? 0)) best.set(p.cat, p);
    }
    const firsts = [...best.values()];
    const picked = new Set(firsts.map(p => String(p.id)));
    const rest = items.filter(p => !picked.has(String(p.id))).sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    return [...firsts, ...rest];
}

// 將 NT$380、380 元或 1,650 等價格輸入轉成正數；無效輸入回傳 null。
function parsePriceInput(raw) {
    if (raw == null) return null;
    if (typeof raw === 'number') return Number.isFinite(raw) && raw >= 0 ? raw : null;
    // 只留數字、小數點與負號；千分位逗號與 NT$／元／空白都在這一步被丟掉。
    const cleaned = String(raw).replace(/[^\d.-]/g, '');
    if (!cleaned || !/\d/.test(cleaned)) return null;
    const n = Number(cleaned);
    return Number.isFinite(n) && n >= 0 ? n : null;
}

function getRecommendedProductCatalog() {
    const fromPackage = Router?.analysisPackage?.recommendations?.products;
    if (Array.isArray(fromPackage) && fromPackage.length) return fillRecommendedImages(fromPackage);
    const draft = typeof AnalysisDraft !== 'undefined' ? AnalysisDraft.load() : null;
    const fromDraft = draft?.recommendations?.products;
    return Array.isArray(fromDraft) ? fillRecommendedImages(fromDraft) : [];
}

// 把本機收藏清單解析成「真的畫得出來的商品」。收藏可能來自 demo 資料、真實商品 API、
// 或分析後的個人化推薦，三邊都要查，不然收藏了也看不到。
//
// 為什麼要獨立成一支：會員中心的「收藏商品」數字原本直接數 Fav.list()（本機存了幾個 id），
// 收藏頁卻只畫得出查得到的那幾件，於是兩邊對不上——會員中心說 12 件，點進去只有 9 件，
// 沒有任何說明。差額的來源是商品下架，或資料庫重匯後 id 被重編號（見 S68：id 只是匯入時的
// 列號，不是商品的永久身分）。兩個地方共用同一份解析，數字就不可能再分岔。
function resolveFavoriteProducts() {
    const apiCatalog = Array.isArray(Router.generalProductCatalog) ? Router.generalProductCatalog : [];
    const combined = [...ALL_PRODUCTS, ...apiCatalog, ...getRecommendedProductCatalog()];
    const seenIds = new Set();
    const catalog = combined.filter(p => {
        if (seenIds.has(String(p.id))) return false;
        seenIds.add(String(p.id));
        return true;
    });
    const items = catalog.filter(p => Fav.has(p.id));
    // 後端明確說「這件已經不在了」的收藏。
    //
    // 2026-08-13 原本的決定是「查不到就安靜地不顯示，商品重新上架會自己回來」。
    // 商品改成硬刪除之後那個前提不成立了：重新匯入會拿到新的 id，舊收藏永遠對不回去。
    // 使用者會看到收藏莫名其妙少一件，而且永遠不知道少了什麼。
    //
    // 所以現在分成兩種：**後端說已下架的**畫出來（讓使用者知道、可以自己移除），
    // 其餘查不到的維持原本的安靜——因為那些可能只是商品清單還沒載完。
    const shown = new Set(items.map(p => String(p.id)));
    const unavailable = Fav.list()
        .filter(id => !shown.has(String(id)) && Fav.isUnavailable(id))
        .map(id => ({ id: String(id), unavailable: true }));
    return {
        items,
        unavailable,
        // 收藏了、三個來源都查不到、而且後端也沒說它已下架的。多半是商品清單
        // 還沒載完或某一頁抓失敗，所以不對使用者顯示。保留這個數字是為了排查用。
        missingCount: Math.max(0, Fav.list().length - items.length - unavailable.length),
    };
}

// 跟 getProductCatalog 不同：不套用 demoProductImage 預設圖，後台編輯表單要看到的是「真正存的值」
function getRawProduct(id) {
    const adminProducts = (typeof AdminStore !== 'undefined') ? AdminStore.listProducts() : [];
    const found = adminProducts.find(p => String(p.id) === String(id));
    if (found) return found;
    const base = Array.isArray(ALL_PRODUCTS) ? ALL_PRODUCTS : [];
    const baseProduct = base.find(p => String(p.id) === String(id));
    if (!baseProduct) return null;
    const overrides = (typeof AdminStore !== 'undefined') ? AdminStore.getOverrides() : {};
    return overrides[id] ? { ...baseProduct, ...overrides[id] } : baseProduct;
}

// 分類線條 icon（簡潔幾何）
const SVC_ICONS = {
    '底妝':'<svg viewBox="0 0 24 24"><path d="M12 3c3 4 5 6.5 5 9.5A5 5 0 0 1 7 12.5C7 9.5 9 7 12 3z"/></svg>',
    '眼影':'<svg viewBox="0 0 24 24"><rect x="4" y="6" width="16" height="5" rx="1"/><rect x="6" y="13" width="12" height="5" rx="1"/></svg>',
    '眼線/睫毛':'<svg viewBox="0 0 24 24"><path d="M3 12c3-4 6-6 9-6s6 2 9 6c-3 4-6 6-9 6s-6-2-9-6z"/><circle cx="12" cy="12" r="2.4"/></svg>',
    '唇彩':'<svg viewBox="0 0 24 24"><path d="M12 9c-1.5-2-4-2.5-5.5-1.2C5 9 5.5 11 12 15c6.5-4 7-6 5.5-7.2C16 6.5 13.5 7 12 9z"/></svg>',
    '腮紅':'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/></svg>',
    '眉毛彩妝':'<svg viewBox="0 0 24 24"><path d="M4 14c4-5 12-5 16 0"/></svg>',
    '修容':'<svg viewBox="0 0 24 24"><path d="M5 19L19 5M9 5h10v10"/></svg>',
    '打亮':'<svg viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M18 6l-2.5 2.5M8.5 15.5L6 18"/></svg>'
};
const STYLE_ROLE = { softBaddie:'Soft Glam', richGirl:'Quiet Luxury', hongKong:'Retro HK', koreanClean:'Clean Girl', yandere:'Doll Core', japaneseClear:'J-Sheer', mensPlain:'Mens Bare' };

// 頁面順序（判斷轉場方向）
const NAV_ORDER = ['dashboard','analysis','style','products','favorites','history','compare','suggestion','profile','admin'];
const ROUTE_PAGES = new Set(NAV_ORDER);

// 玻璃提示彈窗（取代瀏覽器原生 alert）
function showAlert(msg, opts){
    opts = opts || {};
    if (opts.type === 'error' && typeof localizeUserError === 'function') {
        msg = localizeUserError(msg, opts.code || '', opts.status || 0, opts.detail || null);
    }
    var old = document.getElementById("dmAlert"); if (old) old.remove();
    var ov = document.createElement("div");
    ov.id = "dmAlert"; ov.className = "glass-alert" + (opts.type ? " " + opts.type : "");
    var mark = opts.type === "error" ? "!" : (opts.type === "success" ? "\u2713" : "\u2726");
    ov.innerHTML = '<div class="ga-card" role="alertdialog" aria-modal="true">'
        + '<button class="ga-x" aria-label="關閉">\u00d7</button>'
        + '<div class="ga-mark">' + mark + '</div>'
        + '<p class="ga-msg"></p>'
        + '<button class="btn-gold ga-ok">確定</button></div>';
    ov.querySelector(".ga-msg").textContent = msg;
    document.body.appendChild(ov);
    void ov.offsetWidth; ov.classList.add("show");
    function close(){ ov.classList.remove("show"); setTimeout(function(){ ov.remove(); if (opts.onOk) opts.onOk(); }, 320); }
    ov.querySelector(".ga-ok").onclick = close;
    ov.addEventListener("click", function(e){ if (e.target === ov) close(); });
    document.addEventListener("keydown", function esc(e){ if (e.key === "Escape" || e.key === "Enter"){ close(); document.removeEventListener("keydown", esc); } });
    setTimeout(function(){ var b = ov.querySelector(".ga-ok"); if (b) b.focus(); }, 60);
}

// 成功回饋 toast（模糊+旋轉打勾）
function showToast(msg){
    const old = document.getElementById('dmToast');
    if (old) old.remove();
    const t = document.createElement('div');
    t.id = 'dmToast'; t.className = 'toast-check';
    // msg 可能帶入會員名稱、商品名或後端訊息，一律當純文字處理，不進 HTML 解析。
    t.innerHTML = '<span class="check-ring"><svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg></span><span>'+escapeHtml(msg)+'</span>';
    document.body.appendChild(t);
    void t.offsetWidth; t.classList.add('show');
    setTimeout(()=>{ t.classList.remove('show'); t.style.opacity='0'; setTimeout(()=>t.remove(),500); }, 2400);
}

function lookImageSrc(value){
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    const url = new URL(raw, window.location.href);
    if (url.protocol === 'http:' || url.protocol === 'https:') return escapeHtml(url.href);
    if (url.protocol === 'data:' && /^data:image\/(?:png|jpe?g|webp|gif);base64,/i.test(raw)) return escapeHtml(raw);
  } catch (_) {}
  return '';
}

// 把選到的圖縮成正方形小圖再存。
//
// 不縮的後果是具體的：手機直出的照片是好幾 MB 的 base64，會整包塞進會員資料的
// PATCH body 裡，而頭貼在畫面上只有 96px。同時輸出 JPEG——PNG 的照片會大好幾倍。
//
// 用 cover 裁切（取中間的正方形）而不是整張壓扁：頭貼框本來就是圓的，
// 壓扁的臉會歪。
function readAvatarFile(file, size = 256) {
    return new Promise((resolve, reject) => {
        if (!file) return reject(new Error('沒有選到檔案'));
        if (!/^image\//.test(file.type || '')) return reject(new Error('請選擇圖片檔'));
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => {
            try {
                const w = img.naturalWidth || 1, h = img.naturalHeight || 1;
                const side = Math.min(w, h);
                const cv = document.createElement('canvas');
                cv.width = cv.height = size;
                const ctx = cv.getContext('2d');
                ctx.drawImage(img, (w - side) / 2, (h - side) / 2, side, side, 0, 0, size, size);
                resolve(cv.toDataURL('image/jpeg', 0.82));
            } catch (err) {
                reject(err);
            } finally {
                URL.revokeObjectURL(url);
            }
        };
        img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('這個檔案讀不出圖片')); };
        img.src = url;
    });
}

// 換頭貼。先寫遠端再更新本機——順序反過來的話，PATCH 失敗時畫面已經換了新照片，
// 使用者會以為存好了，下次登入才發現沒有。
let avatarUploading = false;
async function changeProfileAvatar(file) {
    // 上傳中就擋掉後續的點擊。縮圖加一次 PATCH 之間畫面沒有明顯變化，
    // 使用者會以為沒反應而再按一次，於是同一張照片送兩趟。
    if (avatarUploading) return;
    const profile = (Auth.getProfile && Auth.getProfile()) || {};
    const email = profile.email;
    if (!email) { showAlert('訪客無法更換大頭貼，請先登入'); return; }
    const btn = document.getElementById('profileAvatar');
    avatarUploading = true;
    if (btn) { btn.disabled = true; btn.classList.add('is-saving'); }
    try {
        let dataUrl;
        try {
            dataUrl = await readAvatarFile(file);
        } catch (err) {
            showAlert(err.message, { type: 'error' });
            return;
        }
        const res = await Api.patchMember(email, { avatar: dataUrl });
        if (!res.ok) {
            showAlert('大頭貼儲存失敗：' + (res.error || `HTTP ${res.status || '?'}`), { type: 'error' });
            return;
        }
        Auth.setProfile({ ...profile, avatar: dataUrl });
        // PageInit.profile() 會重畫這顆按鈕並重新綁事件，連同 disabled 一起復原，
        // 所以底下的 finally 只需要處理「沒有重畫」的那幾條路徑。
        if (Router.currentPage === 'profile') PageInit.profile();
        showToast('大頭貼已更新');
    } finally {
        avatarUploading = false;
        const cur = document.getElementById('profileAvatar');
        if (cur) { cur.disabled = false; cur.classList.remove('is-saving'); }
    }
}

// 外部連結只接受 http(s)，避免 javascript: 或 data: 內容被執行。
function safeExternalUrl(value){
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    const url = new URL(raw, window.location.href);
    if (url.protocol === 'http:' || url.protocol === 'https:') return escapeHtml(url.href);
  } catch (_) {}
  return '';
}

// 使用者只需修改不準的五官；回饋只記文字，不上傳照片。
// 修正會同步更新畫面、後續建議、渲染資料與分析紀錄。
// predicted 保留模型原始答案，讓使用者改回「判斷正確」時可以還原。
function applyAnalysisCorrections(corrections, predicted) {
    if (!Router.analysisResult) return;
    const fixes = corrections || {};
    const base = predicted || {};
    const fields = [...new Set([...Object.keys(fixes), ...Object.keys(base)])];
    if (!fields.length) return;

    const resolved = {};
    let changed = false;
    fields.forEach(field => {
        const next = Object.prototype.hasOwnProperty.call(fixes, field) ? fixes[field] : base[field];
        if (next == null) return;
        resolved[field] = next;
        if (Router.analysisResult[field] !== next) { Router.analysisResult[field] = next; changed = true; }
    });
    if (!changed) return;
    if (Router.analysisPackage && typeof AnalysisPackage !== 'undefined') {
        // 合併變更後只寫一次草稿，減少含圖片資料包的重複儲存。
        const patch = {
            faceAnalysis: AnalysisPackage.fromRawFaceAnalysis(Router.analysisResult, Router.analyzeMode)
        };
        // 五官被修正後，將舊建議標成過期，等使用者主動重新產生。
        const gt = Router.analysisPackage.generativeText;
        if (gt && gt.suggestion && !gt.stale) patch.generativeText = { ...gt, stale: true };

        Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, patch);
        if (typeof AnalysisDraft !== 'undefined') AnalysisDraft.save(Router.analysisPackage);
    }
    // 分析紀錄是在回饋面板出現之前就寫入的，也要跟著改。
    // 傳 resolved 不傳 corrections：改回「判斷正確」時要能把紀錄退回模型的答案。
    if (typeof History !== 'undefined' && History.applyCorrections) {
        History.applyCorrections(Router.analysisPackage?.id, resolved);
    }
    // 分析頁上那排結果格是一次性寫死的文字，重畫它們，否則使用者剛改完
    // 往上一看還是舊答案，會以為沒有生效。
    // r-nose 不在這張表裡：它可能顯示的是 PRO 側臉鼻型，直接寫 analysisResult['鼻型']
    // 會把它打回 BASIC 的答案。交給 paintNoseCell 統一決定。
    const cells = { 'r-face': '臉型', 'r-brow': '眉型', 'r-eye': '眼型', 'r-lip': '嘴型' };
    Object.entries(cells).forEach(([id, field]) => {
        const el = document.getElementById(id);
        if (el && Router.analysisResult[field]) el.textContent = Router.analysisResult[field];
    });
    paintNoseCell(Router.analysisResult);
    // 圖鑑若正開著，「你的判斷」那個標記還掛在舊答案上，一起重畫。
    if (typeof FeatureAtlas !== 'undefined') FeatureAtlas.refresh();
    // 已經排隊等收藏的那筆快照是修正前建的，丟掉讓它重建。
    Router.pendingLook = null;
}

// 結果區有兩種狀態，差別要看得出來：還沒分析時整區去飽和、壓平、往後退，
// 一眼就知道那些「—」是還沒填的欄位而不是分析失敗；結果進來後才浮起來。
// 用 class 切換而不是逐格改樣式，因為要動的是「整區」的層次，不是個別數值。
function setResultState(ready) {
    const panel = document.getElementById('resultPanel');
    if (!panel) return;
    panel.classList.toggle('is-ready', !!ready);
}

// 一律用同一條規則決定「鼻型要顯示什麼」：有 PRO 側臉結果就用它，沒有才退回 BASIC 正面。
// 妝容建議頁與對比頁的摘要也吃這支，否則分析頁顯示駝峰鼻、下一頁又變回標準鼻。
function noseDisplayText(source) {
    if (!source) return '';
    const rawSide = source['側臉鼻型'] || source['鼻型_側面'] || source.noseSide || null;
    const label = (rawSide && typeof rawSide === 'object') ? rawSide.label : rawSide;
    return String(label || source['鼻型'] || source.noseFront || '').trim();
}

// 鼻型這一格要顯示哪一個答案。
//
// PRO 的側臉鼻型有五類（塌鼻／直挺鼻／翹鼻／蒜頭鼻／駝峰鼻，ConvNeXt-Tiny，見
// models/pro_nose_side/），BASIC 的正面鼻型只有兩類（寬鼻／標準鼻）。這格先前一律顯示
// data['鼻型']，於是使用者跑了 PRO、傳了側面照，畫面上看到的仍然是 BASIC 那兩類
// ——側臉模型的答案被正面的蓋掉，PRO 等於白跑。有側臉結果就以它為準。
//
// 只動「顯示」，不改 data['鼻型'] 本身：底下的回饋面板會把修正送去 face_feedback，
// 而那支只認 PART_TO_FIELD 的五個 BASIC 部位、類別還必須出自 BASIC 的分類表
// （face_feedback.py 的 validate()）。把 PRO 的五類寫進 '鼻型' 會被整包退回。
// 正面的答案與模型自帶的 caveat 收進 title，資訊不會消失。
function paintNoseCell(data) {
    const el = document.getElementById('r-nose');
    if (!el || !data) return;
    const rawSide = data['側臉鼻型'] || data['鼻型_側面'] || null;
    const side = (rawSide && typeof rawSide === 'object')
        ? rawSide
        : (rawSide ? { label: rawSide } : null);
    const label = side && side.label ? String(side.label) : '';
    el.textContent = label || data['鼻型'] || '—';

    const labelEl = el.closest('.result-cell')?.querySelector('.rlabel');
    if (labelEl) labelEl.textContent = label ? '鼻型 · 側臉' : '鼻型';

    if (!label) { el.removeAttribute('title'); return; }
    const notes = [];
    if (side.confidence != null) notes.push(`信心 ${Math.round(Number(side.confidence) * 100)}%`);
    if (data['鼻型']) notes.push(`正面判斷：${data['鼻型']}`);
    if (side.caveat) notes.push(side.caveat);
    el.title = notes.join('｜');
}

function renderAnalysisFeedback(result, packageId) {
  const box = document.getElementById('analysisFeedback');
  if (!box || typeof AnalysisFeedback === 'undefined') return;
  // 側臉鼻型（PRO）在分析結果裡是物件 {label, confidence, classes, caveat}，
  // 其餘五個部位是字串。不統一取值的話，這一格會顯示成 [object Object]，
  // 而且送出去的修正也會是那個字串——後端 validate() 只收類別字串，整包會被退回。
  const valueOf = (source, field) => {
    const value = source ? source[field] : null;
    if (value && typeof value === 'object') return value.label || '';
    return value || '';
  };
  const fields = Object.keys(AnalysisFeedback.OPTIONS)
    .filter(field => valueOf(result, field) && !valueOf(result, field).startsWith('無法判斷'));
  if (!fields.length) { box.style.display = 'none'; return; }

  const saved = AnalysisFeedback.forPackage(packageId);
  const corrections = saved ? { ...saved.corrections } : {};
  // predicted 優先使用模型原始輸出，沒有 _modelRaw 時才使用目前結果。
  const raw = (result && typeof result._modelRaw === 'object' && result._modelRaw) || {};
  const predicted = {};
  fields.forEach(field => { predicted[field] = valueOf(raw, field) || valueOf(result, field); });
  // 若後端已套用修正，從目前值與原始值的差異還原回饋面板。
  fields.forEach(field => {
    const current = valueOf(result, field);
    if (!corrections[field] && predicted[field] && current && current !== predicted[field]) {
      corrections[field] = current;
    }
  });

  let allowTraining = false;

  const draw = () => {
    box.innerHTML = `
      <div class="af-head">
        <b>這些判斷準嗎？</b>
        <p>覺得哪一項不對就改掉，其餘視為正確。你的修正會<strong>立刻套用</strong>到這次的妝容建議與收藏，
           並回報給分析模型作為訓練資料；<strong>預設只送出判斷結果與你的修正，不會上傳你的照片</strong>。</p>
      </div>
      <div class="af-rows">${fields.map(field => {
        const chosen = corrections[field];
        const current = chosen || predicted[field];
        return `<div class="af-row${chosen ? ' changed' : ''}">
          <span class="af-label">${escapeHtml(field)}</span>
          <span class="af-value">${escapeHtml(current)}</span>
          <select class="af-select" data-af-field="${escapeHtml(field)}" aria-label="${escapeHtml(field)}正確答案">
            <option value="">判斷正確</option>
            ${AnalysisFeedback.OPTIONS[field]
              .filter(option => option !== predicted[field])
              .map(option => `<option value="${escapeHtml(option)}"${chosen === option ? ' selected' : ''}>改成 ${escapeHtml(option)}</option>`)
              .join('')}
          </select>
        </div>`;
      }).join('')}</div>
      ${Object.keys(corrections).length ? `
      <div class="af-consent">
        <div class="af-consent-title">臉部影像保存同意</div>
        <!-- 這裡刻意只有一句話，沒有分部位的範圍說明。
             先前有一張表寫「眉眼鼻唇只存那一小塊、臉型存整張」——每一行都是真的，
             但排版讓人讀成「主要是小裁切，臉型是例外」。實測不是這樣：102 次分析裡
             有 46 次（45%）存了整張照片，因為臉型正是最多人修正的部位。
             而且「只有那一小塊」容易被讀成「認不出是我」，眼睛裁切並不成立。
             所以改成一句涵蓋最壞情況的話，不要用細節去換取安心感。 -->
        <p class="af-consent-lead">勾選後，這次分析<strong>你的臉部影像會被保存下來</strong>，
           用於重新訓練五官分類模型。不論你修正的是哪一個部位，保存的都是你臉上的影像。</p>
        <label class="af-consent-check">
          <input type="checkbox" id="afAllowTraining"${allowTraining ? ' checked' : ''}>
          <span>我同意保存上述臉部影像，協助改善模型</span>
        </label>
        <p class="af-consent-note">影像只用於模型訓練，不會公開、不會提供給第三方，
           刪除帳號時一併移除。管理員覆核時若判定這筆修正不採用，影像會一併從儲存空間刪除。
           <strong>不勾選也能送出修正</strong>——你的判斷本身就有用，
           我們會拿它去修正分類，只是沒有影像可以重新訓練。</p>
      </div>` : ''}
      <div class="af-foot">
        <button class="btn-gold btn-sm" id="afSubmit">送出回饋</button>
        <span class="af-note" id="afNote">${saved ? '已送出，可再修改' : ''}</span>
      </div>`;

    box.querySelectorAll('[data-af-field]').forEach(select => {
      select.onchange = () => {
        const field = select.dataset.afField;
        if (select.value) corrections[field] = select.value; else delete corrections[field];
        // 下拉選項立即更新資料包；按下送出時才將回饋傳到後端。
        applyAnalysisCorrections(corrections, predicted);
        draw();
      };
    });
    const consent = document.getElementById('afAllowTraining');
    if (consent) consent.onchange = () => { allowTraining = consent.checked; };
    const submit = document.getElementById('afSubmit');
    if (submit) submit.onclick = () => {
      AnalysisFeedback.save(packageId, predicted, corrections);
      applyAnalysisCorrections(corrections, predicted);
      // 回報給臉部分析服務。訪客沒有 pinned actor，_protectedFetch 會擋下寫入，
      // 送出去也只是被靜默吞掉——乾脆不送，本機那份修正照樣立刻生效。
      if (Api.sendAnalysisFeedback && !(typeof isGuest === 'function' && isGuest())) {
          Api.sendAnalysisFeedback({
              mode: Router.analyzeMode,
              jobId: Router.analysisPackage?.async?.jobId,
              resultToken: Router.analysisPackage?.async?.resultToken,
              packageId,
              predicted,
              corrections,
              allowTrainingUse: allowTraining,
              // 只有勾選時才取照片。沒勾選就連讀都不讀，照片不會離開這個瀏覽器。
              imageDataUrl: allowTraining
                  ? (Router.analysisPackage?.images?.front?.compressedDataUrl
                     || Router.analysisPackage?.images?.front?.dataUrl || '')
                  : '',
              // PRO 才會有側面照。側臉鼻型模型吃整張側臉圖，正面照對它沒有訓練價值。
              sideImageDataUrl: allowTraining
                  ? (Router.analysisPackage?.images?.side?.compressedDataUrl
                     || Router.analysisPackage?.images?.side?.dataUrl || '')
                  : ''
          }).catch(() => {});
      }
      const changed = Object.keys(corrections).length;
      showToast(changed ? `已套用 ${changed} 項修正，之後的建議與收藏都會以你的答案為準` : '已記錄「判斷正確」，謝謝');
      const note = document.getElementById('afNote');
      if (note) note.textContent = '已送出，可再修改';
    };
  };

  draw();
  box.style.display = 'block';
}

// 妝容圖載入失敗時，以文字說明取代破圖。
function markLookImageUnavailable(img){
  if (!img || img.dataset.lookFailed === '1') return;
  img.dataset.lookFailed = '1';
  const holder = img.closest('.saved-look-photo') || img.closest('figure') || img.parentElement;
  if (!holder) return;
  holder.innerHTML = '<span class="saved-look-missing">此妝容圖已過期'
    + '<small>渲染圖只在收藏成功時永久保留</small></span>';
}
if (typeof window !== 'undefined') window.markLookImageUnavailable = markLookImageUnavailable;

function openLookModal(item){
  if(!item) return;
  var old=document.getElementById('lookModal'); if(old) old.remove();
  var advice=item.advice||{};
  var titles={ base:'底妝建議', brow:'眉型建議', eye:'眼妝建議', blush:'腮紅 & 修容', lip:'唇妝建議' };
  var r=item.analysis||{}; var skin=r['膚色']||{};
  var rows=Object.keys(advice).map(function(k){ return '<div class="lm-advice"><b>'+escapeHtml(titles[k]||k)+'</b><p>'+escapeHtml(advice[k])+'</p></div>'; }).join('');
  var tags=(item.tags||[]).map(function(t){ return '<span class="analysis-tag">'+escapeHtml(t)+'</span>'; }).join('');
  var beforeSrc = lookImageSrc(item.beforeImage);
  var afterSrc = lookImageSrc(item.renderedImage);
  var photo = (beforeSrc && afterSrc)
    ? '<div class="lm-compare-photo"><figure><img src="'+beforeSrc+'" alt="渲染前照片" onerror="markLookImageUnavailable(this)"><figcaption>Before</figcaption></figure><figure><img src="'+afterSrc+'" alt="渲染後照片" onerror="markLookImageUnavailable(this)"><figcaption>After</figcaption></figure></div>'
    : (afterSrc ? '<img src="'+afterSrc+'" alt="" onerror="markLookImageUnavailable(this)">' : '<span>'+escapeHtml(item.style||'Saved Look')+'</span>');

  var ov=document.createElement('div'); ov.id='lookModal'; ov.className='look-modal';
  ov.innerHTML='<div class="lm-card" role="dialog" aria-modal="true">'
    +'<button class="lm-close" aria-label="關閉">×</button>'
    +'<div class="lm-photo">'+photo+'</div>'
    +'<div class="lm-body"><div class="lm-kicker">'+escapeHtml(item.title||'Saved Look')+'</div>'
    +'<h2>'+escapeHtml(item.style||'妝容建議')+'</h2>'
    +(tags?'<div class="analysis-tags" style="margin-top:14px;">'+tags+'</div>':'')
    +'<div class="lm-summary"><span><em>臉型</em>'+escapeHtml(r['臉型']||'—')+'</span><span><em>眼型</em>'+escapeHtml(r['眼型']||'—')+'</span><span><em>鼻型</em>'+escapeHtml(r['鼻型']||'—')+'</span><span><em>膚色</em>'+escapeHtml(skin['四季型']||skin['膚色分級']||'—')+'</span></div>'
    +(rows?'<div class="lm-advice-grid">'+rows+'</div>':'')
    // 進 compare 頁看同一套長按對比。
    //
    // 浮層裡這兩張是靜態並排的小圖，而剛渲染完時使用者看到的是全尺寸長按對比——
    // 同一份妝前妝後，兩個地方長得不一樣，會被當成兩個不同的東西。
    // 這裡不把長按互動複製一份進浮層：那等於同一套互動維護兩份，
    // 改一邊忘另一邊。改成把這筆資料交給既有的那一頁。
    +((beforeSrc&&afterSrc)?'<button type="button" class="btn-gold lm-open-compare">查看妝容建議</button>':'')
    +'</div></div>';
  document.body.appendChild(ov); void ov.offsetWidth; ov.classList.add('show');
  function close(){ ov.classList.remove('show'); setTimeout(function(){ ov.remove(); },350); }
  ov.querySelector('.lm-close').onclick=close;
  var openCompare=ov.querySelector('.lm-open-compare');
  if(openCompare) openCompare.onclick=function(){ close(); Router.go('suggestion',{ look:item }); };
  ov.onclick=function(e){ if(e.target===ov) close(); };
  document.addEventListener('keydown', function esc(e){ if(e.key==='Escape'){ close(); document.removeEventListener('keydown',esc); } });
}

// ═══ 訪客判斷 ═══
function isGuest(){
    try { var p = Auth.getProfile() || {}; return !Auth.isLoggedIn() || (p.level || "") === "訪客" || Auth.getUser() === "訪客"; }
    catch (_) { return false; }
}

function getMemberDisplayName(){
    var profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
    return String(profile.name || (Auth.getUser && Auth.getUser()) || '訪客').trim() || '訪客';
}

function getCurrentRoleLabel(profile){
    const p = profile || (Auth.getProfile ? Auth.getProfile() : {});
    if (typeof AdminStore !== 'undefined' && AdminStore.isAdminProfile(p)) return '管理員';
    if ((p.level || '') === '訪客' || (p.name || '') === '訪客') return '訪客';
    if (typeof AdminStore !== 'undefined' && AdminStore.isVip(p)) return 'PRO / VIP 會員';
    return '一般會員';
}

function updateAdminNav(page){
    const admin = typeof AdminStore !== 'undefined' && AdminStore.isAdmin();
    document.querySelectorAll('[data-admin-link]').forEach(el => {
        el.style.display = admin ? '' : 'none';
    });
    // 只有管理員進入 admin 頁面時才切換成後台外框。
    const activePage = page || (typeof Router !== 'undefined' ? Router.currentPage : null);
    const adminMode = admin && activePage === 'admin';
    document.body.classList.toggle('admin-mode', adminMode);
    if (adminMode && typeof closeTopbarMenu === 'function') closeTopbarMenu();
}

function updateCartBadge(){
    const badge = document.getElementById('cartCount');
    if (!badge || typeof Cart === 'undefined') return;
    const count = Cart.count();
    badge.textContent = String(count);
    badge.classList.toggle('has-items', count > 0);
}

function refreshMemberTheme() {
    if (typeof MemberRewards !== 'undefined') MemberRewards.applyActiveTheme(Auth.getProfile()?.email);
}

function showCartPanel(){
    const old = document.getElementById('cartOverlay');
    if (old) old.remove();
    const overlay = document.createElement('div');
    overlay.id = 'cartOverlay';
    overlay.className = 'cart-overlay';
    let catalogLoadAttempted = false;
    const render = () => {
        // 購物車只存 id 與數量，因此要從本機商品、API 清單與推薦資料回查內容。
        const apiCatalog = Array.isArray(Router.generalProductCatalog) ? Router.generalProductCatalog : [];
        const catalog = [...getProductCatalog(), ...apiCatalog, ...getRecommendedProductCatalog()];
        const all = Cart.list()
            .map(item => ({ ...item, product: catalog.find(p => String(p.id) === String(item.id)) }));
        // 商品被硬刪除的那幾筆：資料庫端明確回 unavailable:true（契約 2026-08-26）。
        // 它們**不能被靜默丟掉**——那是使用者自己放進去的東西，要不要移除由她決定。
        // 只信任 API 的欄位，不用「catalog 裡查不到」去猜：查不到有三種原因，
        // 其中兩種（清單沒載完、某一頁抓失敗）猜錯就是對使用者說謊。
        const gone = all.filter(item => item.unavailable === true);
        const rows = all.filter(item => item.product && item.unavailable !== true);
        // 找不到商品內容時先載入清單，避免徽章有數量但購物車空白。
        if (!rows.length && Cart.count() > 0 && !apiCatalog.length
                && !Router.generalProductLoading && !catalogLoadAttempted) {
            catalogLoadAttempted = true;
            loadGeneralProductCatalog(() => { if (document.getElementById('cartOverlay')) render(); });
        }
        const emptyMessage = Cart.count() > 0
            ? (Router.generalProductLoading
                ? '正在載入購物車商品資料…'
                : '商品資料暫時無法載入，請稍後重新開啟購物車。')
            : '購物車目前是空的';
        overlay.innerHTML = `<section class="cart-panel" role="dialog" aria-modal="true" aria-label="購物車">
            <header><div><span>Shopping Bag</span><h2>購物車</h2></div><button class="cart-close" aria-label="關閉購物車">×</button></header>
            <div class="cart-items">${rows.length ? rows.map(item => `<article class="cart-item">
                <button class="cart-thumb" type="button" data-cart-open="${escapeHtml(item.id)}" aria-label="查看 ${escapeHtml(item.product.name)} 的商品詳情">${phBox('', item.product.name, item.product.img)}</button>
                <div class="cart-item-info"><span>${escapeHtml(CAT_EN[item.product.cat] || item.product.cat)}</span><h3>${escapeHtml(item.product.name)}</h3><p>${escapeHtml(item.product.price)}</p></div>
                <div class="cart-qty"><button data-cart-minus="${escapeHtml(item.id)}" aria-label="減少 ${escapeHtml(item.product.name)}">−</button><b>${escapeHtml(item.qty)}</b><button data-cart-plus="${escapeHtml(item.id)}" aria-label="增加 ${escapeHtml(item.product.name)}">＋</button></div>
            </article>`).join('') : (gone.length ? '' : `<div class="cart-empty">${emptyMessage}</div>`)}
            ${gone.map(item => `<article class="cart-item is-gone">
                <div class="cart-thumb cart-gone-thumb" aria-hidden="true">✕</div>
                <div class="cart-item-info"><span>已下架</span><h3>此商品已下架</h3><p>—</p></div>
                <div class="cart-qty"><button data-cart-remove="${escapeHtml(item.id)}">移除</button></div>
            </article>`).join('')}</div>
            ${gone.length ? `<div class="cart-gone-note">有 ${gone.length} 件商品已下架，結帳時不會計入。可以自行移除。</div>` : ''}
            <footer><span>共 ${rows.reduce((n, r) => n + (parseInt(r.qty, 10) || 0), 0)} 件商品</span><button class="cart-checkout" ${rows.length ? '' : 'disabled'}>前往結帳</button></footer>
        </section>`;
        overlay.querySelector('.cart-close').onclick = () => overlay.remove();
        overlay.querySelectorAll('[data-cart-minus]').forEach(btn => btn.onclick = () => { Cart.change(btn.dataset.cartMinus, -1); updateCartBadge(); render(); });
        overlay.querySelectorAll('[data-cart-plus]').forEach(btn => btn.onclick = () => { Cart.change(btn.dataset.cartPlus, 1); updateCartBadge(); render(); });
        // 已下架的只留「移除」。加減數量與查看商品都沒有意義——商品不在了。
        overlay.querySelectorAll('[data-cart-remove]').forEach(btn => btn.onclick = () => {
            Cart.remove(btn.dataset.cartRemove); updateCartBadge(); render();
        });
        // 點縮圖看商品詳情。用 <button> 不是掛 onclick 的 <div>——Tab 到得了、Enter 有作用、
        // 螢幕閱讀器唸得出是按鈕，跟這個檔案裡會員中心那幾張統計卡同一個理由。
        // 要先關掉購物車覆蓋層，否則詳情頁被蓋在後面看不到。
        overlay.querySelectorAll('[data-cart-open]').forEach(btn => btn.onclick = () => {
            const id = btn.dataset.cartOpen;
            overlay.remove();
            Router.go('products', { productId: id });
        });
        const checkout = overlay.querySelector('.cart-checkout');
        if (checkout && !checkout.disabled) checkout.onclick = () => showToast('結帳功能開發中，敬請期待');
    };
    render();
    overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };
    document.body.appendChild(overlay);
}

// ═══ 玻璃雙鈕對話框（取代原生 confirm） ═══
function showConfirm(msg, opts){
    opts = opts || {};
    if (opts.type === 'error' && typeof localizeUserError === 'function') {
        msg = localizeUserError(msg, opts.code || '', opts.status || 0, opts.detail || null);
        if (opts.title && !/[\u3400-\u9fff]/.test(String(opts.title))) {
            opts.title = '操作失敗';
        }
    }
    var old = document.getElementById("dmConfirm"); if (old) old.remove();
    var ov = document.createElement("div");
    ov.id = "dmConfirm"; ov.className = "glass-alert" + (opts.type ? " " + opts.type : "");
    var mark = opts.mark || (opts.type === "error" ? "!" : "\u2726");
    ov.innerHTML = '<div class="ga-card" role="alertdialog" aria-modal="true">'
        + '<button class="ga-x" aria-label="關閉">\u00d7</button>'
        + '<div class="ga-mark">' + mark + '</div>'
        + (opts.title ? '<h3 class="ga-title"></h3>' : '')
        + '<p class="ga-msg"></p>'
        + '<div class="ga-actions">'
        + '<button class="btn-gold ga-ok"></button>'
        + '<button class="ga-cancel"></button>'
        + '</div></div>';
    if (opts.title) ov.querySelector(".ga-title").textContent = opts.title;
    ov.querySelector(".ga-msg").textContent = msg;
    ov.querySelector(".ga-ok").textContent = opts.okText || "確定";
    ov.querySelector(".ga-cancel").textContent = opts.cancelText || "取消";
    document.body.appendChild(ov);
    void ov.offsetWidth; ov.classList.add("show");
    function close(cb){ ov.classList.remove("show"); setTimeout(function(){ ov.remove(); if (cb) cb(); }, 320); }
    ov.querySelector(".ga-ok").onclick = function(){ close(opts.onOk); };
    ov.querySelector(".ga-cancel").onclick = function(){ close(opts.onCancel); };
    var __x = ov.querySelector(".ga-x"); if (__x) __x.onclick = function(){ close(opts.onDismiss); };
    ov.addEventListener("click", function(e){ if (e.target === ov) close(opts.onCancel); });
    document.addEventListener("keydown", function esc(e){ if (e.key === "Escape"){ close(opts.onCancel); document.removeEventListener("keydown", esc); } });
    setTimeout(function(){ var b = ov.querySelector(".ga-ok"); if (b) b.focus(); }, 60);
}

// ═══ 訪客：提示登入或註冊 ═══
function promptGuestAuth(featureName){
    showConfirm("登入會員即可使用「" + featureName + "」功能，立即加入吧。", {
        title: "需要會員身分", okText: "登入", cancelText: "前往註冊",
        onOk: showLogin, onCancel: showRegister
    });
}

// ═══ 是否已開始美學旅程（做過臉部分析） ═══
function hasStartedJourney(){
    try {
        return !!(Router.analysisResult && Router.analysisPackage && Router.analysisPackage.status === "completed" && Router.analysisPackage.faceAnalysis);
    } catch (_) { return false; }
}

function getLatestAnalysisResult(){
    try {
        return Router.analysisResult || null;
    } catch (_) { return null; }
}

function resetCurrentBeautySession(){
    Router.selectedFile = null;
    Router.proFiles = { front: null, left45: null, right45: null, side: null };
    Router.packageImageFiles = {};
    Router.analysisPackage = null;
    Router.analysisResult = null;
    Router.selectedStyleId = null;
    Router.pendingLook = null;
    Router.pendingLookSaved = false;
    if (typeof AnalysisDraft !== "undefined" && AnalysisDraft.clear) AnalysisDraft.clear();
}

// 妝容收藏的 localStorage key 依「登入帳號」分開，避免同一瀏覽器不同帳號互相看到對方的收藏
function looksKey(){
    const p = (typeof Auth !== 'undefined' && Auth.getProfile) ? Auth.getProfile() : null;
    const em = (p && p.email) ? String(p.email).trim().toLowerCase() : 'guest';
    return 'beautySuggestions_' + em;
}

function buildCurrentLookRecord(){
    const style = STYLES.find(s => s.id === Router.selectedStyleId) || STYLES[0];
    const pkg = Router.analysisPackage || {};
    const render = pkg.render || {};
    const makeupOutput = render.makeupOutput || {};
    // 畫面顯示用本機的 data URL：已經在記憶體裡，不必再跟伺服器要一次。
    const beforeImage = pkg.images?.front?.compressedDataUrl
        || render.beforeImageUrl
        || render.beforeImageDataUrl
        || '';
    // 存進資料庫用渲染服務給的 /media/render/<job>/before：data URL 進不了
    // String(500) 欄位，而這條路徑跟妝後圖走同一套擁有者檢查。
    // 顯示用圖片與資料庫保存用網址分開處理。
    const beforeImageForStorage = render.beforeImageUrl || '';
    const renderedImage = render.afterImageUrl || render.afterImageDataUrl || makeupOutput.imageUrl || makeupOutput.imageDataUrl || '';
    return {
        kind: 'compare',
        title: '妝容對比圖',
        beforeImageForStorage,
        style: style?.name || '妝容建議',
        advice: style?.advice || {},
        analysis: Router.analysisResult || {},
        beforeImage,
        renderedImage,
        analysisPackageId: pkg.id || null,
        timestamp: new Date().toISOString()
    };
}

// 後端 saved_looks 一筆 → 本機妝容記錄格式（供跨裝置拉回時重繪用）
function mapRemoteSavedLook(L){
    const summary = (L && (L.analysisSummary || L.analysis_summary)) || {};
    let summaryObj = (summary && typeof summary === 'object') ? summary : {};
    if (typeof summary === 'string') {
        try {
            const parsed = JSON.parse(summary);
            summaryObj = (parsed && typeof parsed === 'object') ? parsed : {};
        } catch (_) {}
    }
    const nested = (summaryObj.raw && typeof summaryObj.raw === 'object') ? summaryObj.raw : {};
    const source = Object.keys(nested).length ? nested : summaryObj;
    const face = source.faceAnalysis || source['臉部分析'] || source;
    const skin = source.skinTone || source['膚色'] || {};
    const pick = (...values) => values.find(value => value !== undefined && value !== null && String(value).trim() !== '') || null;
    const advice = source.generativeText?.suggestion?.advice
        || source.generativeText?.advice
        || source.advice
        || summaryObj.advice
        || {};
    const tags = Array.isArray(source.tags) ? source.tags : (Array.isArray(summaryObj.tags) ? summaryObj.tags : []);
    return {
        kind: 'compare',
        title: '妝容對比圖',
        style: (L && L.style) || '妝容建議',
        advice: advice && typeof advice === 'object' ? advice : {},
        tags,
        summary: summaryObj.summary || summaryObj.text || '',
        analysis: {
            '臉型': pick(summaryObj.faceShape, summaryObj['臉型'], face.faceShape, face['臉型']),
            '眼型': pick(summaryObj.eyeShape, summaryObj['眼型'], face.eyeShape, face['眼型']),
            '鼻型': pick(summaryObj.noseShape, summaryObj['鼻型'], face.noseShape, face['鼻型']),
            '膚色': {
                '四季型': pick(summaryObj.skinSeason, summaryObj['四季型'], skin.season, skin['四季型']),
                '膚色分級': pick(summaryObj.skinTone, summaryObj['膚色分級'], skin.tone, skin['膚色分級'])
            }
        },
        beforeImage: (L && (L.beforeImageUrl || L.before_image_url)) || '',
        renderedImage: (L && (L.afterImageUrl || L.after_image_url)) || '',
        analysisPackageId: null,
        timestamp: (L && (L.createdAt || L.created_at)) || null,
        remoteId: (L && L.id != null) ? L.id : null
    };
}

function saveCurrentLook(){
    if (isGuest()) {
        promptGuestAuth('收藏妝容對比圖');
        return null;
    }
    // 收藏時重建最新資料；無法取得渲染圖時才使用暫存快照。
    const fresh = buildCurrentLookRecord();
    const record = fresh.renderedImage ? fresh : (Router.pendingLook || fresh);
    const stored = { ...record, timestamp: new Date().toISOString() };
    const records = JSON.parse(localStorage.getItem(looksKey()) || '[]');
    records.unshift(stored);
    localStorage.setItem(looksKey(), JSON.stringify(records.slice(0, 20)));
    Router.pendingLook = null;
    Router.pendingLookSaved = true;
    // 盡力同步到後端（跨裝置持久化）；只有渲染後永久網址存在才送，失敗不影響本機收藏
    const em = (typeof Auth !== 'undefined' && Auth.getProfile()) ? Auth.getProfile().email : null;
    if (em) {
        const a = stored.analysis || {};
        Api.createSavedLook(em, {
            style: stored.style || null,
            beforeImageUrl: stored.beforeImageForStorage || null,
            afterImageUrl: stored.renderedImage || null,
            // 收藏需要完整保存臉、眉、眼、鼻、唇與膚色。
            analysisSummary: {
                faceShape: a.faceShape || a['臉型'] || null,
                browShape: a.browShape || a['眉型'] || null,
                eyeShape: a.eyeShape || a['眼型'] || null,
                noseShape: a.noseShape || a['鼻型'] || null,
                lipShape: a.lipShape || a['嘴型'] || null,
                skinSeason: (a.skinTone && a.skinTone.season) || (a['膚色'] && a['膚色']['四季型']) || null
            }
        }).then(r => {
            // 把後端配發的 id 寫回本機該筆，之後刪除才能連動後端
            if (r && r.ok && r.look && r.look.id != null) {
                try {
                    const recs = JSON.parse(localStorage.getItem(looksKey()) || '[]');
                    const hit = recs.find(x => x.timestamp === stored.timestamp);
                    if (hit) { hit.remoteId = r.look.id; localStorage.setItem(looksKey(), JSON.stringify(recs)); }
                } catch (_) {}
                if (typeof showToast === 'function') showToast('已同步到雲端資料庫');
            } else if (r && r.skipped) {
                // 妝後圖沒有永久網址時只存本機，並提示尚未同步。
                if (typeof showToast === 'function') showToast('已收藏到本機；妝容圖尚未產生永久網址，未同步到雲端');
            } else {
                if (typeof showToast === 'function') showToast('雲端同步失敗（已存本機）' + (r && r.status ? `：HTTP ${r.status}` : '，請重整後重試'));
            }
        }).catch(() => {
            if (typeof showToast === 'function') showToast('雲端同步失敗（已存本機）');
        });
    }
    return record;
}

// ═══ 更改密碼（玻璃彈窗） ═══
function showChangePassword(){
    var old = document.getElementById("pwdModal"); if (old) old.remove();
    var ov = document.createElement("div"); ov.id = "pwdModal"; ov.className = "glass-alert pwd-modal";
    var lock = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#7A4A42" stroke-width="1.4" stroke-linecap="round"><rect x="5" y="10.5" width="14" height="9.5" rx="2.2"/><path d="M8 10.5V7.6a4 4 0 0 1 8 0v2.9"/></svg>';
    ov.innerHTML = '<div class="ga-card pwd-card" role="dialog" aria-modal="true">'
        + '<button class="lm-close" aria-label="關閉">\u00d7</button>'
        + '<div class="ga-mark">' + lock + '</div>'
        + '<h3 class="ga-title">更改密碼</h3>'
        + '<p class="ga-sub">為你的帳號設定新的密碼</p>'
        + '<div class="pwd-fields">'
        + '<div class="input-group light"><label>目前密碼</label><input type="password" id="cpOld" placeholder="••••••••"></div>'
        + '<div class="input-group light"><label>新密碼</label><input type="password" id="cpNew" placeholder="至少 6 碼"></div>'
        + '<div class="input-group light"><label>確認新密碼</label><input type="password" id="cpNew2" placeholder="再次輸入新密碼"></div>'
        + '</div>'
        + '<div class="ga-actions"><button class="btn-gold ga-ok">更新密碼</button><button class="ga-cancel">取消</button></div>'
        + '</div>';
    document.body.appendChild(ov); void ov.offsetWidth; ov.classList.add("show");
    function close(cb){ ov.classList.remove("show"); setTimeout(function(){ ov.remove(); if (cb) cb(); }, 320); }
    ov.querySelector(".lm-close").onclick = function(){ close(); };
    ov.querySelector(".ga-cancel").onclick = function(){ close(); };
    ov.addEventListener("click", function(e){ if (e.target === ov) close(); });
    ov.querySelector(".ga-ok").onclick = function(){
        var oldP = ov.querySelector("#cpOld").value, n1 = ov.querySelector("#cpNew").value, n2 = ov.querySelector("#cpNew2").value;
        if (!oldP || !n1 || !n2) { showAlert("請完整填寫三個欄位"); return; }
        if (n1.length < 6) { showAlert("新密碼至少 6 碼"); return; }
        if (n1 !== n2) { showAlert("兩次輸入的新密碼不一致", { type:"error" }); return; }
        // 不再用前端本機資料模擬改密碼，也不把新密碼寫入 sessionStorage。
        // 正式改密碼必須由會員後端提供驗證 old password 的 API。
        close(function(){ showAlert("目前尚未接上會員端改密碼 API，請使用忘記密碼流程。", { type:"error" }); });
    };
    setTimeout(function(){ var i = ov.querySelector("#cpOld"); if (i) i.focus(); }, 80);
}

// ═══ 分析引導閘門：沒有分析紀錄時，引導去臉部分析 ═══
function renderAnalysisGate(featureName){
    var mc = document.getElementById("mainContent");
    if (!mc) return;
    mc.innerHTML = [
        '<div class="analysis-gate">',
        '<span class="ag-kicker">Begin Here</span>',
        '<div class="ag-mark">\u2767</div>',
        '<h2>先完成臉部分析</h2>',
        '<p>「' + featureName + '」需要你的臉部分析結果。完成一次臉部分析後，系統才能依你的五官與膚色，為你整理適合的妝容。</p>',
        '<button class="btn-gold ag-btn">前往臉部分析　→</button>',
        '</div>'
    ].join("");
    var b = mc.querySelector(".ag-btn"); if (b) b.onclick = function(){ Router.go("analysis"); };
}

function getPageFallback(page){
    const fallbacks = {
dashboard: `
<div class="arch-hero" data-nav="analysis">
    <div class="arch-corner">Maison Decorate Me</div>
    <span class="arch-eyebrow">A Platform Created for the Love of Beauty</span>
    <div class="arch-stage"><div class="arch-word-base">裝識你的美</div></div>
    <div class="arch-tagline"><div class="at-text">為你打造的<em>美學旅程</em> · 從臉部分析開始</div></div>
</div>
<div class="dash-greet">
    <div class="greet-l">
        <span class="eyebrow">Welcome</span>
        <h1 id="dashGreet">歡迎回來，<span class="accent">訪客</span></h1>
        <div class="greet-actions">
            <button type="button" class="btn-gold greet-cta" data-nav="analysis" id="dashPrimaryCta">
                <b>看看什麼適合我　→</b><small>只要一張正面照</small></button>
            <button type="button" class="btn-outline greet-cta-alt" data-nav="analysis"
                    id="dashSecondaryCta" hidden>重新分析</button>
            <div class="tone-scale" title="膚色比對"><div class="swatches"><span style="background:#F1D9C4"></span><span style="background:#E4BE9E"></span><span style="background:#CFA079"></span><span style="background:#A9774F"></span><span style="background:#7C5334"></span></div><em>五種膚色基準</em></div>
        </div>
    </div>
    <div class="greet-r"><div class="greet-meta">Your Beauty Atelier</div></div>
</div>
<section id="dashPersonalSection" style="display:none;">
    <div class="dash-sec-head"><div class="sh-l"><span class="sh-no">❧</span><h2>猜你喜歡</h2></div></div>
    <div class="glow-row" id="dashPersonal"></div>
</section>
<div class="dash-sec-head"><div class="sh-l"><span class="sh-no">01</span><h2>風格靈感</h2></div></div>
<div class="insp-row" id="dashInsp"></div>
<div class="dash-sec-head"><div class="sh-l"><span class="sh-no">02</span><h2>為你精選</h2></div></div>
<div class="glow-row" id="dashGlow"></div>
<!-- 四步驟：這套系統實際會發生的事。 品牌那兩句講的是「為什麼」，這裡講「怎麼走」——使用者看完就知道 從臉部分析開始、最後會走到商品，而不是只知道有這些功能。 --><section class="about-sys">
    <div class="as-head">
        <div class="about-headrow"><span class="as-eyebrow-it">About the Atelier</span><h2 class="about-title">OUR BEAUTY<span class="l2">SYSTEM</span></h2></div>
        <span class="bs-link" data-nav="analysis">開始你的美學旅程　→</span>
        <p class="bs-desc"><b>美，不是成為另一個人。</b><br>而是更了解適合自己的樣子。</p>

    </div>
    <div class="as-photo"><img class="as-photo-img" src="assets/brand/decorate-me-home.jpg" alt="Decorate Me 品牌識別" onload="this.classList.add('loaded')"><div class="as-photo-ph"><div class="demo-mark">❧</div><div class="demo-cap">商品形象照 · Demo</div></div></div>

<div class="sys-steps" aria-label="系統流程"><div class="ss-item" data-nav="analysis"><span class="ss-no">01</span><span class="ss-en">ANALYZE</span><span class="ss-zh">臉部分析</span><span class="ss-rule" aria-hidden="true"></span><span class="ss-desc">Understand<br>your features</span></div><div class="ss-item" data-nav="style"><span class="ss-no">02</span><span class="ss-en">DISCOVER</span><span class="ss-zh">專屬推薦</span><span class="ss-rule" aria-hidden="true"></span><span class="ss-desc">Find your<br>perfect look</span></div><div class="ss-item" data-nav="suggestion"><span class="ss-no">03</span><span class="ss-en">TRY ON</span><span class="ss-zh">AI 試妝</span><span class="ss-rule" aria-hidden="true"></span><span class="ss-desc">See your<br>new look</span></div><div class="ss-item" data-nav="products"><span class="ss-no">04</span><span class="ss-en">SHOP</span><span class="ss-zh">商品搭配</span><span class="ss-rule" aria-hidden="true"></span><span class="ss-desc">Complete<br>the look</span></div></div>
</section>`,
analysis: `
<div class="page-header"><h1>臉部分析</h1><div class="divider"></div><p>上傳正面照片，分析五官特徵</p></div>
<div class="analyze-grid">
    <div>
        <div class="section-label"><span>NO.01</span>上 傳 照 片</div>
        <div class="mode-tabs">
            <button class="mode-tab active" id="basicModeBtn" data-mode="basic">BASIC</button>
            <button class="mode-tab" id="proModeBtn" data-mode="pro">PRO</button>
        </div>
        <div class="mode-panel active" id="basicPanel">
            <div class="upload-box" id="uploadBox">
                <div class="upload-icon"><span>＋</span></div>
                <div class="upload-label">選擇照片</div>
                <div class="upload-hint">正面、光線均勻，並把頭髮撥開露出額頭與兩頰</div>
                <input type="file" id="fileInput" accept="image/*" style="display:none;">
            </div>
            <div class="camera-actions">
                <button class="btn-outline btn-sm" id="startCameraBtn">開啟鏡頭</button>
                <button class="btn-outline btn-sm" id="capturePhotoBtn">拍照使用</button>
            </div>
            <div class="camera-box" id="cameraBox">
                <video id="cameraVideo" autoplay playsinline></video>
                <div class="camera-face-guide"></div>
                <canvas id="cameraCanvas" style="display:none;"></canvas>
            </div>
        </div>
        <div class="mode-panel" id="proPanel">
            <div class="pro-upload-grid pro-two-shot">
                <div class="pro-slot" data-pro-slot="front"><div class="slot-title">正面照</div><div class="slot-file" id="frontFileName">必填</div><img class="pro-shot-preview" id="frontPreview" alt="正面照預覽"><button class="pro-retake-btn" data-pro-retake="front" type="button">重拍正面</button><input type="file" id="frontInput" accept="image/*" style="display:none;"></div>
                <div class="pro-slot" data-pro-slot="side"><div class="slot-title">側面照</div><div class="slot-file" id="sideFileName">必填</div><img class="pro-shot-preview" id="sidePreview" alt="側面照預覽"><button class="pro-retake-btn" data-pro-retake="side" type="button">重拍側面</button><input type="file" id="sideInput" accept="image/*" style="display:none;"></div>
            </div>
            <div class="pro-scan-panel">
                <div class="pro-scan-copy"><b>角度輔助拍攝</b><span>系統即時顯示臉部 yaw／pitch 並提示對準與否，<b>由你自己按下擷取</b>；也可以直接用上面兩格上傳現成照片。</span></div>
                <div class="camera-actions"><button class="btn-outline btn-sm" id="startProScanBtn">開始掃描</button><button class="btn-outline btn-sm" id="stopProScanBtn">停止掃描</button></div>
                <div class="camera-actions"><button class="btn-outline btn-sm" id="manualFrontCaptureBtn">手動存正面</button><button class="btn-outline btn-sm" id="manualSideCaptureBtn">手動存側面</button></div>
                <div class="camera-box" id="proCameraBox">
                    <video id="proCameraVideo" autoplay playsinline muted></video>
                    <div class="camera-face-guide" id="proFaceGuide"></div>
                    <canvas id="proCameraCanvas" style="display:none;"></canvas>
                </div>
                <div class="scan-progress" id="proScanProgress"><span data-scan-role="front">正面：待擷取</span><span data-scan-role="side">側面：待擷取</span></div>
                <div class="scan-hint" id="proScanHint">等待鏡頭啟動</div>
                <div class="pro-yaw-display" id="proYawDisplay"></div>
            </div>
            <div class="mode-note">45 度多角度採集保留為未來展望；目前 PRO 正式流程採用正面照與單側側面照，降低樣本採集難度。</div>
        </div>
        <img id="preview" alt="preview" style="max-width:100%;margin-top:12px;border:1px solid var(--border);display:none;">
        <div class="brightness-panel" id="brightnessPanel" style="display:none;">
            <div class="bp-header">
                <span class="bp-title">亮度</span>
                <span class="bp-summary" id="bpSummary"></span>
                <button class="bp-reset" id="bpReset" type="button">重置</button>
            </div>
            <div class="bp-slider-row" id="bpSliderRow">
                <input type="range" id="bpSlider" min="-100" max="100" value="0" step="1" aria-label="亮度調整">
            </div>
            <div class="bp-slider-meta">
                <span class="bp-bound">−100</span>
                <span class="bp-value" id="bpValue">0</span>
                <span class="bp-bound">+100</span>
            </div>
            <div class="bp-status" id="bpStatus"></div>
        </div>
        <div class="loading-bar" id="loadingBar"><div class="fill" id="loadingFill"></div></div>
        <div class="loading-status" id="loadingStatus">等待圖片</div>
        <div class="package-status" id="packageStatus"><b>分析進度</b><span>尚未開始</span></div>
        <button class="btn-gold btn-full" id="analyzeBtn" style="margin-top:14px;">開 始 分 析</button>
    </div>
    <div class="result-panel" id="resultPanel">
        <div class="section-label"><span>NO.02</span>分 析 結 果</div>
        <div class="result-grid">
            <div class="result-cell"><div class="rlabel">臉型</div><div class="rvalue" id="r-face">—</div></div>
            <div class="result-cell"><div class="rlabel">眉型</div><div class="rvalue" id="r-brow">—</div></div>
            <div class="result-cell"><div class="rlabel">眼型</div><div class="rvalue" id="r-eye">—</div></div>
            <div class="result-cell"><div class="rlabel">鼻型</div><div class="rvalue" id="r-nose">—</div></div>
            <div class="result-cell"><div class="rlabel">嘴型</div><div class="rvalue" id="r-lip">—</div></div>
            <div class="result-cell"><div class="rlabel">色彩季型</div><div class="rvalue" id="r-season">—</div></div>
        </div>
        <div class="skin-box"><div class="skin-title">膚 色 基 準 · M A C</div><div class="skin-row"><div class="skin-swatch" id="skinSwatch"></div><div><div class="skin-name" id="skinName">—</div></div></div><div class="skin-warn" id="skinReliabilityWarn" style="display:none;"></div></div>
        <div class="skin-box"><div class="skin-title">唇 色</div><div class="skin-row"><div class="skin-swatch" id="lipSwatch"></div></div></div>
        <div id="analysisFeedback" class="analysis-feedback" style="display:none;"></div>
        <div style="text-align:center;margin-top:20px;"><button class="btn-gold" id="goStyleBtn" style="display:none;">選擇風格 →</button></div>
    </div>
</div>`,
style: `
<div class="page-header"><span class="eyebrow">Style Atelier</span><h1>風格試妝</h1><div class="divider"></div><p>選擇一種妝容風格，為你量身打造</p></div>
<div class="style-grid" id="styleGrid"></div>
<div style="text-align:center;margin-top:20px;"><button class="btn-gold" id="confirmStyleBtn">確認風格 →</button></div>
<div id="styleResultArea"></div>`,
products: `<div id="productsArea"></div>`,
favorites: `<div class="page-header"><span class="eyebrow">Wishlist</span><h1>我的收藏</h1><div class="divider"></div></div><div id="favArea"></div>`,
history: `<div class="page-header"><span class="eyebrow">Archive</span><h1>分析紀錄</h1><div class="divider"></div></div>
<p class="page-note">每一次臉部分析的判斷結果都會留在這裡，只存文字，<strong>不會保留你的照片</strong>。紀錄依帳號分開，最多保留 50 筆。</p>
<div id="historyArea"></div>`,
compare: `
<div class="page-header"><h1>妝容對比圖</h1><div class="divider"></div></div>
<div class="compare-layout">
    <div class="compare-preview" id="comparePreview">
        <div class="ph compare-stage before" id="compareStage"></div>
        <button class="compare-hold-btn" id="compareHoldBtn">查看渲染後</button>
    </div>
    <div class="analysis-section">
        <h3>目前風格</h3>
        <p id="compareStyleName">尚未選擇風格</p>
        <div class="analysis-tags" id="compareStyleTags"></div>
        <p class="compare-viewonly-note">渲染在「妝容建議」頁的 Step 2 進行。這一頁只看圖。</p>
        <button class="btn-outline" id="compareGoStyleBtn">選擇風格</button>
        <button class="btn-gold" id="compareSaveLookBtn" style="margin-top:12px;">收藏妝容對比圖</button>
    </div>
</div>`,
suggestion: `<div class="page-header"><h1>妝容建議</h1><div class="divider"></div><p>依照臉部分析結果與選擇風格，產生妝容建議與可收藏的妝容對比圖。</p></div><div id="suggestionArea"></div>`,
admin: `
<div class="page-header admin-header">
    <h1>管理中台</h1>
    <div class="divider"></div>
</div>

<section class="admin-panel">
    <div class="admin-summary">
        <div><span>全部會員</span><b id="adminTotal">0</b></div>
        <div><span>啟用中</span><b id="adminActive">0</b></div>
        <div><span>已停權</span><b id="adminSuspended">0</b></div>
        <div><span>管理員</span><b id="adminAdmins">0</b></div>
    </div>

    <div class="admin-actions-row">
        <button class="admin-tab active" data-admin-filter="all">全部使用者</button>
        <button class="admin-tab" data-admin-filter="active">啟用中</button>
        <button class="admin-tab" data-admin-filter="admin">管理員</button>
    </div>

    <div class="admin-main">
        <div class="admin-toolbar">
            <label class="admin-search">
                <span>搜尋</span>
                <input id="adminSearch" type="search" placeholder="姓名或 Email">
            </label>
            <button class="btn-gold btn-sm" id="adminSaveBtn" type="button">儲存權限</button>
        </div>

        <div class="admin-table-wrap">
            <table class="admin-table">
                <thead>
                    <tr>
                        <th>使用者</th>
                        <th>角色</th>
                        <th>會員等級</th>
                        <th>狀態</th>
                        <th>失敗原因</th>
                        <th>功能權限</th>
                        <th>資料庫操作</th>
                    </tr>
                </thead>
                <tbody id="adminUserRows"></tbody>
            </table>
        </div>
    </div>
</section>

<section class="admin-products">
    <div class="member-section-head">
        <h2>商品管理</h2>
    </div>
    <div class="admin-product-search-panel">
        <label><span>搜尋資料庫商品</span><input id="adminProductSearch" type="search" placeholder="輸入品牌、商品名稱、分類或關鍵字" autocomplete="off"></label>
        <button class="admin-secondary-button" id="adminProductSearchClearBtn" type="button">清除</button>
        <a class="admin-secondary-button" id="adminProductGoogleSearch" href="https://www.google.com/search?q=%E5%BD%A9%E5%A6%9D+%E5%95%86%E5%93%81" target="_blank" rel="noopener noreferrer">到 Google 找商品</a>
        <p id="adminProductSearchStatus" aria-live="polite">輸入關鍵字即可快速篩選資料庫商品。</p>
    </div>
    <div class="admin-product-grid">
        <form class="admin-product-form" id="adminProductForm">
            <div class="admin-product-form-mode">編輯中：<span id="adminProductEditingLabel"></span></div>
            <label>商品名稱<input id="adminProductName" type="text" placeholder="例如：柔霧粉底液"></label>
            <label>分類
                <select id="adminProductCategory">
                    <option value="底妝">底妝</option>
                    <option value="眼影">眼影</option>
                    <option value="眼線/睫毛">眼線/睫毛</option>
                    <option value="唇彩">唇彩</option>
                    <option value="腮紅">腮紅</option>
                    <option value="眉毛彩妝">眉毛彩妝</option>
                    <option value="修容">修容</option>
                    <option value="打亮">打亮</option>
                </select>
            </label>
            <label>價格<input id="adminProductPrice" type="text" inputmode="decimal" placeholder="只填數字，例如 980"></label>
            <label>圖片網址<input id="adminProductImg" type="text" placeholder="留空則使用預設示意圖"></label>
            <label>商品描述<textarea id="adminProductDesc" placeholder="顯示在前台商品詳情頁的說明文字"></textarea></label>
            <label>色號（用逗號分隔 Hex 色碼）<input id="adminProductShades" type="text" placeholder="例如：#3A241C,#C99070,#B5654A"></label>
            <div class="admin-product-form-actions">
                <button class="btn-gold btn-sm" type="button" id="adminProductCreateBtn">新增商品</button>
                <button class="btn-outline btn-sm" type="button" id="adminProductEditBtn" disabled>儲存編輯</button>
                <button class="admin-danger-button compact" type="button" id="adminProductDeleteBtn" disabled>刪除商品</button>
                <button class="btn-outline btn-sm" type="button" id="adminProductCancelBtn" style="display:none">取消選取</button>
            </div>
        </form>
        <div class="admin-product-manager">
            <div class="admin-table-wrap">
                <table class="admin-table admin-product-table">
                    <thead>
                        <tr>
                            <th>商品</th>
                            <th>分類</th>
                            <th>價格</th>
                            <th>來源</th>
                            <th>狀態</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody id="adminProductRows"></tbody>
                </table>
            </div>
        </div>
        <div class="admin-audit-panel">
            <div class="dash-sec-head">
                <div class="sh-l"><span class="sh-no">LOG</span><h2>最近操作紀錄</h2></div>
                <button class="btn-outline btn-sm" type="button" id="adminAuditReload">重新載入</button>
            </div>
            <p class="admin-audit-note">誰、什麼時候、動了哪一筆商品，含失敗的操作。改錯或誤刪時從這裡找得回來。
               操作者顯示為去識別化代號（同一位管理員的代號固定），紀錄保留 180 天。</p>
            <div class="admin-table-wrap">
                <table class="admin-table admin-audit-table">
                    <thead>
                        <tr><th>時間</th><th>動作</th><th>對象</th><th>結果</th><th>操作者</th></tr>
                    </thead>
                    <tbody id="adminAuditRows"></tbody>
                </table>
            </div>
        </div>
    </div>
</section>`,
profile: `
<div class="page-header"><span class="eyebrow">Member</span><h1>會員中心</h1><div class="divider"></div></div>
<div class="member-wrap">
    <div class="member-id">
        <button type="button" class="member-avatar" id="profileAvatar"
                aria-label="更換大頭貼">✦<span class="ma-edit" aria-hidden="true">更換</span></button>
        <input type="file" id="profileAvatarInput" accept="image/*" style="display:none;">
        <div class="member-name" id="profileName">訪客</div>
        <div class="member-role" id="profileRole">Decorate Me Member</div>
        <div class="member-actions">
            <button class="btn-outline" id="changePwdBtn" style="display:none;">更改密碼</button>
            <button class="btn-outline member-logout" onclick="Auth.logout()">登出帳號</button>
        </div>
    </div>
    <div class="member-stats">
        <!-- 四張卡片都可點：兩張換頁、兩張捲到本頁下方的區塊。
             用 <button> 而不是掛 onclick 的 <div>——鍵盤 Tab 到得了、Enter/空白鍵有作用、
             螢幕閱讀器也唸得出「按鈕」。data-goto 換頁，data-scroll 捲動。 -->
        <button class="stat-cell" type="button" data-goto="favorites" aria-label="查看收藏商品">
            <span class="stat-en">Wishlist</span><span class="stat-num" id="profileFavCount">0</span>
            <span class="stat-label">收藏商品</span><span class="stat-go">查看 &rarr;</span></button>
        <button class="stat-cell" type="button" data-goto="history" aria-label="查看分析文字紀錄">
            <span class="stat-en">Analysis</span><span class="stat-num" id="profileAnalyzeCount">0</span>
            <span class="stat-label">分析次數</span><span class="stat-go">查看 &rarr;</span></button>
        <button class="stat-cell" type="button" data-scroll="profileSuggestionArea" aria-label="捲動到已收藏的妝容">
            <span class="stat-en">Looks</span><span class="stat-num" id="profileSuggestionCount">0</span>
            <span class="stat-label">收藏妝容</span><span class="stat-go">查看 &darr;</span></button>
        <button class="stat-cell" type="button" data-scroll="profilePointLedger" aria-label="捲動到點數紀錄">
            <span class="stat-en">Points</span><span class="stat-num" id="profilePointCount">0</span>
            <span class="stat-label">會員點數</span><span class="stat-go">查看 &darr;</span></button>
    </div>
</div>

<!-- 2026-08-28 拿掉每日打卡。點數機制與這個專案要展示的東西無關，
     而它佔著會員中心最上面那塊，把真正該看的（分析紀錄、妝容收藏）擠下去。 -->


<!-- 分組與 pages/profile.html 一致；那邊改了這裡要跟著改。
     這是 fetch 失敗時的備援，區塊比較少（沒有 PRO、任務中心、推薦好友），
     但分頁的 id 與行為必須一模一樣，否則備援畫面上的分頁按鈕會按不動。 -->
<div class="member-tabs" role="tablist" aria-label="會員中心分頁">
    <button type="button" class="member-tab is-active" role="tab" id="mtab-account" aria-selected="true" aria-controls="mpanel-account" data-mtab="account">帳戶</button>
    <button type="button" class="member-tab" role="tab" id="mtab-points" aria-selected="false" aria-controls="mpanel-points" data-mtab="points">點數與任務</button>
    <button type="button" class="member-tab" role="tab" id="mtab-saved" aria-selected="false" aria-controls="mpanel-saved" data-mtab="saved">我的收藏</button>
</div>

<div class="member-panel" id="mpanel-account" data-mpanel="account" role="tabpanel" aria-labelledby="mtab-account">
<section class="member-tier"><div class="member-section-head"><span>Membership</span><h2>會員等級</h2></div><div id="profileTierCard"></div></section>
</div>
<div class="member-panel" id="mpanel-points" data-mpanel="points" role="tabpanel" aria-labelledby="mtab-points" hidden>
<section class="member-tier"><div class="member-section-head"><span>Theme Shop</span><h2>點數商店</h2></div><div id="profileThemeShop"></div></section>
<section class="member-tier"><div class="member-section-head"><span>Ledger</span><h2>點數紀錄</h2></div><div id="profilePointLedger"></div></section>
</div>
<div class="member-panel" id="mpanel-saved" data-mpanel="saved" role="tabpanel" aria-labelledby="mtab-saved" hidden>
<section class="member-suggestions"><div class="member-section-head"><span>Saved Looks</span><h2>已收藏的妝容對比圖</h2></div><div id="profileSuggestionArea"></div></section>
</div>
`
    };
    return fallbacks[page] || null;
}

// ═══ SPA Router ═══
// 每個 page 是一個 HTML fragment，由 fetch 載入 main-content
let pendingStyleModalSelection = null;
function closeMakeupStyleModal() { document.getElementById('makeupStyleModal')?.classList.remove('open'); }
function openMakeupStyleModal(preselectedStyleId) {
    if (!hasStartedJourney()) { Router.go('analysis'); return; }
    let modal = document.getElementById('makeupStyleModal');
    if (!modal) {
        modal = document.createElement('div'); modal.id = 'makeupStyleModal'; modal.className = 'makeup-style-modal';
        modal.setAttribute('role','dialog'); modal.setAttribute('aria-modal','true'); modal.setAttribute('aria-labelledby','makeupStyleModalTitle'); document.body.appendChild(modal);
    }
    pendingStyleModalSelection = preselectedStyleId || Router.selectedStyleId || null;
    const renderOptions = () => {
        modal.innerHTML = `<div class="makeup-style-dialog"><div class="makeup-style-head"><div><span class="eyebrow">Style</span><h2 id="makeupStyleModalTitle">選擇妝容風格</h2><p>選擇一款風格，接著查看妝容建議。</p></div><button class="makeup-style-close" type="button" aria-label="關閉">×</button></div><div class="makeup-style-grid">${STYLES.map(style=>`<button class="makeup-style-option ${pendingStyleModalSelection===style.id?'selected':''}" type="button" data-style-id="${escapeHtml(style.id)}"><img src="${escapeHtml(style.img)}" alt="${escapeHtml(style.name)}"><span class="makeup-style-option-copy"><b>${escapeHtml(style.name)}</b><small>${style.tags.map(escapeHtml).join(' · ')}</small></span></button>`).join('')}</div><div class="makeup-style-actions"><button class="btn-outline" type="button" data-modal-cancel>稍後再選</button><button class="btn-gold" type="button" data-modal-confirm ${pendingStyleModalSelection?'':'disabled'}>確認風格 →</button></div></div>`;
        modal.querySelectorAll('[data-style-id]').forEach(button=>button.onclick=()=>{pendingStyleModalSelection=button.dataset.styleId;renderOptions();});
        modal.querySelector('.makeup-style-close').onclick=closeMakeupStyleModal; modal.querySelector('[data-modal-cancel]').onclick=closeMakeupStyleModal;
        modal.querySelector('[data-modal-confirm]').onclick=()=>{if(!pendingStyleModalSelection)return;Router.selectedStyleId=pendingStyleModalSelection;closeMakeupStyleModal();Router.go('suggestion');};
    };
    renderOptions(); modal.classList.add('open');
}
// 收藏前顯示妝前／妝後對比、實際渲染指令與圖片保存狀態，確認後才儲存。
function closeSaveLookModal(){ document.getElementById('saveLookModal')?.remove(); }
function openSaveLookModal() {
    if (isGuest()) { promptGuestAuth('收藏妝容對比圖'); return; }
    const pkg = Router.analysisPackage || {};
    const rd = pkg.render || {};
    const mo = rd.makeupOutput || {};
    const before = pkg.images?.front?.compressedDataUrl || rd.beforeImageUrl || rd.beforeImageDataUrl || '';
    const after = rd.afterImageUrl || rd.afterImageDataUrl || mo.imageUrl || mo.imageDataUrl || '';
    const style = STYLES.find(s => s.id === Router.selectedStyleId) || STYLES[0];
    const isTemp = String(after).includes('replicate.delivery');

    const modal = document.createElement('div');
    modal.id = 'saveLookModal';
    modal.className = 'makeup-style-modal open';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.innerHTML = `<div class="makeup-style-dialog save-look-dialog">
        <div class="makeup-style-head">
            <div><span class="eyebrow">Save</span><h2>收藏這組妝容</h2>
            <p>${after
                ? '按住下方按鈕可以看妝前，放開回到妝後。'
                : '還沒有妝後圖，現在收藏只會存下一筆沒有圖片的紀錄。請先回「妝容建議」頁完成 Step 2。'}</p></div>
            <button class="makeup-style-close" type="button" aria-label="關閉">×</button>
        </div>
        <div class="compare-preview">
            <div class="ph compare-stage after" id="saveLookStage">
                <span class="compare-photo-label" id="saveLookLabel">${after ? '妝後' : '妝前'}</span>
            </div>
            <button class="compare-hold-btn" id="saveLookHoldBtn"${after && before ? '' : ' disabled'}>按住看妝前</button>
        </div>
        <div class="save-look-meta">
            <div class="detail-pill">${escapeHtml(style.name)}</div>
            ${isTemp ? `<p class="save-look-warn">妝後圖目前是臨時網址，收藏後可能日後失效。渲染端改用永久網址後就不會有這個問題。</p>` : ''}
        </div>
        <div class="makeup-style-actions">
            <button class="btn-outline" type="button" data-cancel>取消</button>
            <button class="btn-gold" type="button" data-confirm${after ? '' : ' disabled'}>確認收藏</button>
        </div>
    </div>`;
    document.body.appendChild(modal);

    const stage = modal.querySelector('#saveLookStage');
    const label = modal.querySelector('#saveLookLabel');
    const paint = (kind) => {
        const img = kind === 'before' ? before : after;
        stage.classList.toggle('after', kind !== 'before');
        stage.classList.toggle('before', kind === 'before');
        stage.classList.toggle('has-render', !!img);
        stage.style.backgroundImage = img ? `url("${img}")` : '';
        stage.style.backgroundSize = img ? 'contain' : '';
        stage.style.backgroundPosition = img ? 'center' : '';
        stage.style.backgroundRepeat = img ? 'no-repeat' : '';
        label.textContent = kind === 'before' ? '妝前' : '妝後';
    };
    paint(after ? 'after' : 'before');

    // 按住看妝前、放開回妝後——沿用妝容對比圖頁那套手勢，含鍵盤與手機的處理。
    const holdBtn = modal.querySelector('#saveLookHoldBtn');
    const press = (e) => { if (e?.preventDefault) e.preventDefault(); if (after && before) paint('before'); };
    const release = () => paint(after ? 'after' : 'before');
    holdBtn.style.touchAction = 'none';
    holdBtn.style.userSelect = 'none';
    holdBtn.onpointerdown = press;
    holdBtn.onpointerup = release;
    holdBtn.onpointerleave = release;
    holdBtn.onpointercancel = release;
    holdBtn.oncontextmenu = (e) => e.preventDefault();
    holdBtn.onkeydown = (e) => { if (e.key === ' ' || e.key === 'Enter') press(e); };
    holdBtn.onkeyup = (e) => { if (e.key === ' ' || e.key === 'Enter') release(); };

    modal.querySelector('.makeup-style-close').onclick = closeSaveLookModal;
    modal.querySelector('[data-cancel]').onclick = closeSaveLookModal;
    // 沒有妝後圖就不讓存。這道守在視窗裡而不是各個按鈕上，因為入口有兩個
    // （妝容建議頁的 Step 2、妝容對比圖頁），守在按鈕上就得守兩次、漏一次就破功。
    modal.querySelector('[data-confirm]').onclick = () => {
        if (!after) return;
        closeSaveLookModal();
        if (saveCurrentLook()) showToast('已收藏妝容對比圖');
    };
    modal.onclick = (e) => { if (e.target === modal) closeSaveLookModal(); };
}

function closeProductRecommendationModal(){document.getElementById('productRecommendationModal')?.remove();}
function openProductRecommendationModal(){
    const modal=document.createElement('div');
    modal.id='productRecommendationModal';modal.className='makeup-style-modal open';modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');
    // 膚色色塊放在推薦視窗的標題區：粉底液是最需要對照膚色的品項，而商品端目前
    // 沒有色碼（見《給資料庫端_商品顏色資料遺失回報》），系統無法自動比對。
    // 把使用者自己量到的膚色擺在推薦旁邊，至少讓他用眼睛比。
    // 值來自 analysisPackage.faceAnalysis.skinTone，沒有分析結果就整塊不出現。
    const skinTone = Router.analysisPackage?.faceAnalysis?.skinTone;
    const skinLab = Array.isArray(skinTone?.lab) && skinTone.lab.length === 3 ? skinTone.lab.map(Number) : null;
    const skinRow = skinLab ? `<div class="reco-skin-row">
        <span class="reco-skin-swatch" style="background:${escapeHtml(Api.labToRgb(skinLab[0], skinLab[1], skinLab[2]))}" aria-label="你的膚色"></span>
        <span class="reco-skin-text">你的膚色${[skinTone.season, skinTone.level].filter(Boolean).length ? ' · ' + escapeHtml([skinTone.season, skinTone.level].filter(Boolean).join(' / ')) : ''}</span>
        ${skinTone.labReliable === false ? '<span class="reco-skin-warn">取樣可信度不足，僅供參考</span>' : ''}
    </div>` : '';
    modal.innerHTML=`<div class="makeup-style-dialog product-recommendation-dialog"><div class="makeup-style-head"><div><span class="eyebrow">Products</span><h2>個人化商品推薦</h2><p>依照臉部分析與選擇的妝容風格，從現有商品中整理推薦。</p>${skinRow}</div><button class="makeup-style-close" type="button" aria-label="關閉">×</button></div><div class="prod-grid recommendation-modal-grid"></div><div class="makeup-style-actions"><button class="btn-outline" type="button" data-close>稍後再看</button><button class="btn-gold" type="button" data-all>查看所有商品</button></div></div>`;
    document.body.appendChild(modal);
    const grid=modal.querySelector('.recommendation-modal-grid');

    // 推薦彈窗與商品頁共用同一份排序、補圖與價格資料。
    const draw=()=>{
        if(!document.getElementById('productRecommendationModal'))return;
        const products=orderRecommendedProducts(getRecommendedProductCatalog());
        if(!products.length){
            grid.classList.remove('prod-grid');
            // 載入中／後端回報空結果／單純還沒整理好，是三種不同的狀況，
            // 用同一句話帶過會讓使用者不知道要等、要重試、還是這裡本來就沒有東西。
            grid.innerHTML = Router.generalProductLoading
                ? '<div class="empty-state">推薦商品載入中...</div>'
                : (RecommendationNotice.error || RecommendationNotice.isEmpty
                    ? RecommendationNotice.html() + RecommendationNotice.emptyHtml()
                    : '<div class="empty-state">推薦商品正在整理中，也可以先查看所有商品。</div>');
            RecommendationNotice.bind(grid);
            return;
        }
        grid.classList.add('prod-grid');
        // 有商品時，降級提示放在列表上方——契約 §4 要求這些但書要跟商品一起看得到，
        // 而不是只在完全沒有商品時才出現。
        //
        // 提示要插在 grid 的**外面**：grid 本身是 display:grid 的容器，
        // 把提示塞進去它會變成其中一個格子，跟商品卡排在一起。
        const holder = grid.parentNode;
        holder.querySelectorAll('[data-rec-holder]').forEach(n => n.remove());
        const noticeHtml = RecommendationNotice.html();
        if (noticeHtml && holder) {
            const box = document.createElement('div');
            box.setAttribute('data-rec-holder', '1');
            box.innerHTML = noticeHtml;
            holder.insertBefore(box, grid);
            RecommendationNotice.bind(box);
        }
        grid.innerHTML=products.slice(0,RECOMMENDED_DISPLAY_LIMIT).map((p,i)=>`
            <div class="prod-card reveal-in" data-pid="${escapeHtml(p.id)}" style="animation-delay:${Math.min(i*0.035,0.2)}s">
                <div class="pc-imgwrap">
                    ${phBox('',p.name,p.img)}
                    <button class="heart-btn pc-heart ${Fav.has(p.id)?'fav':''}" data-fav="${escapeHtml(p.id)}" aria-label="收藏">${HEART_SVG}</button>
                </div>
                <div class="pc-cat">${escapeHtml(CAT_EN[p.cat]||p.cat)}${p.brand?` · ${escapeHtml(p.brand)}`:''}</div>
                <div class="pc-name">${escapeHtml(p.name)}</div>
                ${(!p.recommendationPresentation?.headline && p.matchReason)?`<div class="pc-reason">${escapeHtml(p.matchReason)}</div>`:''}
                ${colorCompareHtml(p)}
                ${recommendationCardHtml(p)}
                <div class="pc-foot"><span class="pc-price">${escapeHtml(p.price)}</span></div>
            </div>`).join('');
        grid.querySelectorAll('.prod-card').forEach(card=>{
            card.onclick=e=>{
                if(e.target.closest('.heart-btn'))return;
                closeProductRecommendationModal();
                Router.go('products',{productId:card.dataset.pid});
            };
        });
        grid.querySelectorAll('.pc-heart').forEach(btn=>{
            btn.onclick=e=>{
                e.stopPropagation();
                const id=btn.dataset.fav,wasFav=Fav.has(id);
                Fav.toggle(id,products.find(x=>String(x.id)===String(id)));
                btn.classList.toggle('fav',!wasFav);
                btn.classList.remove('swap');void btn.offsetWidth;btn.classList.add('swap');
                if(!wasFav)showToast('已加入收藏');
            };
        });
    };
    draw();
    // 商品清單尚未載入時，先載入後再補齊推薦圖片與價格。
    if(!productCatalogLoaded())loadGeneralProductCatalog(draw);

    modal.querySelector('.makeup-style-close').onclick=closeProductRecommendationModal;
    modal.querySelector('[data-close]').onclick=closeProductRecommendationModal;
    modal.querySelector('[data-all]').onclick=()=>{closeProductRecommendationModal();Router.go('products');};
    modal.onclick=e=>{if(e.target===modal)closeProductRecommendationModal();};
}

// 產生妝容建議的核心流程：呼叫 Api.suggestMakeup、切掉 Ollama 偶爾漏拆黏在中文尾巴的
// 英文渲染指令、把結果寫回 analysisPackage 並存草稿，順便在背景要推薦商品。
// 這裡刻意完全不碰 DOM —— 風格試妝頁和妝容建議頁都用同一份，各自畫自己的進度條，
// 進度用 onProgress(百分比, 文字) 回報，要畫在哪裡由呼叫端決定。
async function runMakeupSuggestion(onProgress) {
    const notify = typeof onProgress === 'function' ? onProgress : () => {};
    const style = STYLES.find(s => s.id === Router.selectedStyleId);
    const pkg = Router.analysisPackage;
    // 沒有臉部分析就沒有東西可以建議：回報給呼叫端決定怎麼帶路，不在這裡跳頁。
    if (!pkg || !Router.analysisResult) return { ok: false, missingAnalysis: true };
    // 建議與渲染的額度分開算：訪客各 2 次、會員各 4 次（見 UsageQuota）。
    if (typeof UsageQuota !== 'undefined' && !UsageQuota.canUse(UsageQuota.KINDS.SUGGESTION)) {
        return { ok: false, quotaExceeded: true, kind: 'suggestion',
                 limit: UsageQuota.limit(UsageQuota.KINDS.SUGGESTION) };
    }
    try {
        const latestAnalysis = getLatestAnalysisResult() || {};
        notify(45, '等待完整建議中...');
        // 不傳 analysisPackage：它含使用者臉部照片的 base64，而建議服務只讀 faceAnalysis。
        const response = await Api.suggestMakeup({
            faceAnalysis: pkg?.faceAnalysis || AnalysisPackage.fromRawFaceAnalysis(latestAnalysis, Router.analyzeMode),
            style: style?.name || '日常自然妝',
            userNote: style?.tags?.join('、') || ''
        });
        const { suggestion: cleanSuggestion, leakedEnglishPart } = splitOllamaTwoPartSuggestion(response.suggestion);
        const fullText = cleanSuggestion || '';
        const ollamaRenderPromptEn = response.renderPromptEn || leakedEnglishPart || '';
        notify(100, '建議已產生');

        Router.analysisPackage = AnalysisPackage.update(pkg || Router.analysisPackage, {
            generativeText: {
                provider: 'ollama',
                prompt: null,
                suggestion: fullText || null,
                model: null,
                status: 'completed',
                error: null,
                fallbackUsed: false,
                ollamaRenderPromptEn: ollamaRenderPromptEn || null,
                renderPromptEn: buildRenderPrompt(
                    pkg?.faceAnalysis || Router.analysisPackage?.faceAnalysis,
                    Router.selectedStyleId,
                    fullText,
                    ollamaRenderPromptEn
                )
            },
            recommendations: {
                ...(pkg?.recommendations || Router.analysisPackage?.recommendations || {}),
                style: style?.name || null
            }
        });
        AnalysisDraft.save(Router.analysisPackage);

        Api.recommendProducts(Router.analysisPackage, Router.selectedStyleId).then(rec => {
            // 成功與失敗都要記：成功時要把上一輪殘留的錯誤提示清掉。
            RecommendationNotice.record(rec);
            if (!rec?.products?.length) return;
            Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                recommendations: {
                    ...Router.analysisPackage.recommendations,
                    products: rec.products,
                    // 粉底相鄰色階也要跟著存。先前它只活在 Router.shadeRecommendation
                    // 這個記憶體變數裡，而重新整理之後沒有任何地方還原它——
                    // 於是使用者重載一次，整個色號區塊就從商品頁上消失，
                    // 看起來像功能壞掉。商品清單早就有草稿 fallback，這裡照同一個模式。
                    shadeRecommendation: rec.shadeRecommendation || null,
                }
            });
            AnalysisDraft.save(Router.analysisPackage);
        }).catch(() => RecommendationNotice.record(null));

        Router.pendingLook = buildCurrentLookRecord();
        Router.pendingLookSaved = false;
        // 成功之後才記一次額度。服務掛掉或逾時不該吃掉使用者的次數。
        if (typeof UsageQuota !== 'undefined') UsageQuota.record(UsageQuota.KINDS.SUGGESTION);
        return { ok: true, response };
    } catch (err) {
        if (pkg) {
            Router.analysisPackage = AnalysisPackage.update(pkg, {
                generativeText: { ...(pkg.generativeText || {}), status: 'failed', error: err.message }
            });
            AnalysisDraft.save(Router.analysisPackage);
        }
        return { ok: false, error: err };
    }
}

// 產生妝後圖的核心流程：權限與照片檢查、呼叫 Api.renderMakeupAsync、把結果寫回
// analysisPackage 並存草稿。完全不碰 DOM，進度用 onProgress 回報，畫在哪由呼叫端決定。
// 擋下來的原因用 reason 回報，讓呼叫端決定要跳註冊、跳分析還是只顯示訊息。
//
// 將渲染條件與結果寫回邏輯集中處理，避免和畫面程式混在一起。
async function runMakeupRender(onProgress) {
    const notify = typeof onProgress === 'function' ? onProgress : () => {};
    const profile = Auth.getProfile();
    // 2026-08-14：訪客從「完全不能渲染」改成每天 2 次，會員 4 次，
    // 而且與妝容建議分開計算（見 UsageQuota 的說明）。
    if (typeof UsageQuota !== 'undefined' && !UsageQuota.canUse(UsageQuota.KINDS.RENDER)) {
        return { ok: false, reason: 'quota', kind: 'render', limit: UsageQuota.limit(UsageQuota.KINDS.RENDER) };
    }
    // 訪客現在有額度了，所以不再直接擋；但被停權或方案不允許的會員仍然擋。
    if (!(typeof isGuest === 'function' && isGuest())
        && typeof AdminStore !== 'undefined' && !AdminStore.canRender(profile)) {
        return { ok: false, reason: 'plan' };
    }

    const pkg = Router.analysisPackage;
    const imageDataUrl = pkg?.images?.front?.compressedDataUrl || pkg?.images?.front?.dataUrl || '';
    if (!imageDataUrl) return { ok: false, reason: 'no-photo' };

    // 只挑後端會讀的幾塊，不整包送——資料包裡有 base64 圖片，整包送 payload 會爆炸。
    //
    // 不要送 generativeText。渲染端「刻意忽略」資料包裡的 renderPromptEn——
    // 那是前端送的、可以被竄改，而照著它渲染等於讓任何人拿我們的額度生成任意圖片。
    // 要下給模型的 prompt 由渲染端自己向文字建議服務取得
    // （replicate_render.py build_personalized_render_prompt，只吃 styleId 與 faceAnalysis）。
    // 送了不會有作用，只會讓下一個人以為它有用。
    //
    // faceJobId 是給重訓用的：臉部分析那端存標註但不存照片，渲染這端存照片。
    // 兩邊 job id 不同，不帶這個就永遠 join 不起來，標註也就接不回它對應的那張臉。
    const styleId = Router.selectedStyleId || pkg?.render?.styleId || 'natural';
    const renderPackage = {
        faceAnalysis: pkg?.faceAnalysis || null,
        faceJobId: pkg?.async?.jobId || null,
        render: { styleId }
    };

    try {
        const result = await Api.renderMakeupAsync({
            imageDataUrl,
            styleId,
            analysisPackage: renderPackage,
            onProgress: p => notify(p)
        });
        Router.analysisPackage = AnalysisPackage.update(pkg, {
            render: {
                ...(pkg.render || {}),
                status: 'completed',
                provider: 'replicate',
                afterImageUrl: result.afterImageUrl,
                // 妝前圖的 Gateway 路徑。少了這行，buildCurrentLookRecord 讀到的
                // render.beforeImageUrl 永遠是 undefined，收藏就存不到妝前圖。
                beforeImageUrl: result.beforeImageUrl || null,
                replicateTempUrl: result.replicateTempUrl || null,
                savedImageId: result.savedImageId || null,
                // 保存後端實際送出的指令，供收藏視窗顯示。
                renderPrompt: result.renderPrompt || null,
                error: null
            }
        });
        AnalysisDraft.save(Router.analysisPackage);
        // 成功才記額度：渲染要 60~150 秒，失敗或逾時卻扣次數會讓人很火大。
        if (typeof UsageQuota !== 'undefined') UsageQuota.record(UsageQuota.KINDS.RENDER);
        return { ok: true, result };
    } catch (err) {
        return { ok: false, error: err };
    }
}

// 渲染配額要顯示的那一句。訪客、無限次、剩餘次數、方案未定四種講法集中在這裡，
// 呼叫端只負責塞進自己的元素。
function renderQuotaText() {
    if (typeof isGuest === 'function' && isGuest()) return '訪客無法使用 AI 渲染，請先註冊會員';
    const profile = Auth.getProfile();
    const remaining = AdminStore.getRemainingRenders(profile);
    const dailyLimit = AdminStore.getDailyRenderLimit(profile);
    const resetAt = profile?.renderQuota?.resetAt;
    if (remaining === Infinity || dailyLimit === Infinity) return 'AI 妝容渲染：無限次';
    if (remaining != null && dailyLimit != null && resetAt) return `AI 妝容渲染：今天還剩 ${remaining} / ${dailyLimit} 次`;
    return 'AI 妝容渲染：依你的會員方案提供每日次數';
}

// runMakeupSuggestion 失敗時的共用處置：沒有分析結果就帶他去分析頁，其餘顯示原因。
//
// 回傳的是「發生了什麼」，不是「我處理掉了嗎」：
//   'navigated' —— 已經把使用者帶去別頁，呼叫端什麼都不必做（畫面馬上就要被換掉）
//   'failed'    —— 留在原頁，呼叫端該收拾自己的進度條與狀態字
//   ''          —— 沒有失敗
// 回傳明確原因，讓呼叫端知道該跳頁或只清除進度狀態。
function handleSuggestionFailure(result) {
    if (result.missingAnalysis) {
        showAlert('目前沒有可用的臉部分析結果，請重新完成臉部分析。', { type:'error' });
        Router.go('analysis');
        return 'navigated';
    }
    if (result.quotaExceeded) {
        const limit = result.limit;
        showAlert(`今天的妝容建議次數已用完（每天 ${limit} 次）。`
            + (isGuest() ? '註冊成為會員可以有更多次數，明天也會重置。' : '明天會重置。'),
            { type: 'error' });
        return 'failed';
    }
    if (!result.ok) {
        showAlert('妝容建議失敗：' + result.error.message, { type: 'error' });
        return 'failed';
    }
    return '';
}

// 兩個頁面共用同一組風格色票與預設顏色。
function paletteRowHtml(style) {
    const palette = (style && style.palette) || ['#D8B69E', '#B97970', '#7C544A'];
    return `<div class="palette-row" style="margin:12px 0;">${palette
        .map(c => `<span style="background:${c};display:inline-block;width:28px;height:28px;border-radius:50%;margin-right:6px;"></span>`)
        .join('')}</div>`;
}

// 被 runMakeupRender 擋下來時要對使用者說什麼、帶他去哪。回傳「我處理掉了嗎」，
// 讓呼叫端用一個 if 就能分開「被擋下」與「真的失敗」兩種結果。
function handleRenderBlocked(reason) {
    if (reason === 'quota') {
        const limit = (typeof UsageQuota !== 'undefined') ? UsageQuota.limit(UsageQuota.KINDS.RENDER) : 0;
        showAlert(`今天的妝容渲染次數已用完（每天 ${limit} 次）。`
            + (isGuest() ? '註冊成為會員可以有更多次數，明天也會重置。' : '明天會重置。'),
            { type: 'error' });
        return true;
    }
    if (reason === 'guest') { promptGuestAuth('AI 渲染妝容'); return true; }
    if (reason === 'plan') { showAlert('你目前的方案無法使用 AI 妝容渲染。', { type: 'error' }); return true; }
    if (reason === 'no-photo') { showAlert('尚未上傳照片，請先完成臉部分析。', { type: 'error' }); return true; }
    return false;
}

const Router = {
    currentPage: null,
    analysisResult: null,
    selectedFile: null,
    analyzeMode: 'basic',
    analysisPackage: null,
    packageImageFiles: {},
    proFiles: { front: null, left45: null, right45: null, side: null },
    cameraStream: null,
    proCameraStream: null,
    proScanTimer: null,
    selectedStyleId: null,
    pendingLook: null,
    pendingLookSaved: false,
    leaveGuardOpen: false,
    pendingRegister: null,
    prefillRegister: null,
    latestRenderedAfter: false,
    currentCategory: null,
    productRecommendationLoading: false,
    generalProductCatalog: null,
    generalProductLoading: false,
    favoriteSyncState: 'idle',

    stopAnalysisCameras() {
        if (this.proScanTimer) clearInterval(this.proScanTimer);
        this.proScanTimer = null;
        this.proScanBusy = false;
        [this.cameraStream, this.proCameraStream].forEach(stream => {
            if (stream) stream.getTracks().forEach(track => track.stop());
        });
        this.cameraStream = null;
        this.proCameraStream = null;
    },

    async go(page, opts) {
        opts = opts || {};
        // 換頁前先收掉五官圖鑑的浮層。它是掛在 body 上的，不跟著頁面內容換掉——
        // 留著的話會浮在下一頁上，而且 body 的 overflow:hidden 也解不開，整頁捲不動。
        if (typeof FeatureAtlas !== 'undefined') FeatureAtlas.close();
        // 離開後台就不用再看了，留著會在每個頁面持續打 /auth/session
        if (typeof SessionWatch !== 'undefined') SessionWatch.stop();
        // 分析完成後，選擇風格會開啟彈窗並直接前往妝容建議。
        if (page === 'style' && hasStartedJourney()) { openMakeupStyleModal(opts.styleId); return; }
        const adminSession = typeof AdminStore !== 'undefined' && Auth.isLoggedIn() && AdminStore.isAdmin();
        if (adminSession && page !== 'admin') page = 'admin';
        if (!opts.skipLeaveGuard && this.needsLookLeaveGuard(page)) {
            this.promptLookLeave(page, opts);
            return;
        }
        if (page === 'admin' && (typeof AdminStore === 'undefined' || !AdminStore.isAdmin())) {
            showAlert('只有管理員可以進入管理中台', { type: 'error' });
            return;
        }
        if (typeof AdminStore !== 'undefined' && Auth.isLoggedIn() && page !== 'admin' && !AdminStore.canAccess(page)) {
            showAlert('此帳號目前沒有使用此功能的權限，請聯繫管理員', { type: 'error' });
            return;
        }
        // fetch 頁面前就先切換外框，避免管理頁載入期間短暫露出會員購物車與會員列。
        updateAdminNav(page);
        // 一進分析頁就先把 face 服務叫醒（不等它回來）。使用者接下來還要選照片、對鏡頭，
        // 這幾十秒剛好夠 Cloud Run 冷啟動跑完，等他按下分析時容器已經是熱的。
        if (page === 'analysis' && typeof Api !== 'undefined' && Api.warmFaceServices) {
            Api.warmFaceServices();
        }

        // 訪客攔截：收藏 / 分析紀錄 需登入
        if ((page === "favorites" || page === "history") && isGuest()) {
            promptGuestAuth(page === "favorites" ? "收藏" : "分析紀錄");
            return;
        }
        if (this.currentPage === 'analysis' && page !== 'analysis') this.stopAnalysisCameras();
        try {
            if (!opts.fromHash && location.hash !== `#${page}`) {
                history.pushState(null, '', `#${page}`);
            }
            const back = (NAV_ORDER.indexOf(page) > -1 && NAV_ORDER.indexOf(this.currentPage) > -1
                          && NAV_ORDER.indexOf(page) < NAV_ORDER.indexOf(this.currentPage));
            const res = await fetch(`pages/${page}.html?v=${PAGE_ASSET_VERSION}`, { cache: 'no-store' });
            if (!res.ok) throw new Error('Page not found');
            const html = await res.text();
            const mc = document.getElementById('mainContent');
            mc.innerHTML = html;
            // 頁面轉場 · side-by-side
            mc.classList.remove('page-enter','page-back');
            void mc.offsetWidth;
            mc.classList.add(back ? 'page-back' : 'page-enter');
            this.currentPage = page;
            // 更新導覽 active
            document.querySelectorAll('.topbar-nav a').forEach(a => {
                a.classList.toggle('active', a.dataset.page === page);
            });
            updateAdminNav();
            refreshMemberTheme();
            // 手機：把目前頁的藥丸捲到可見
            const navEl = document.querySelector('.topbar-nav');
            const activeEl = navEl && navEl.querySelector('a.active');
            if (navEl && activeEl && navEl.scrollWidth > navEl.clientWidth) {
                navEl.scrollTo({ left: Math.max(0, activeEl.offsetLeft - 16), behavior: 'smooth' });
            }
            // 頁面初始化
            if (typeof PageInit[page] === 'function') PageInit[page](opts);
            // 每次進入收藏頁都重新同步，讓短暫連線失敗後仍可重試。
            if (page === 'favorites') refreshFavoritesPage();
        } catch (e) {
            const fallback = getPageFallback(page);
            if (fallback) {
                const mc = document.getElementById('mainContent');
                mc.innerHTML = fallback;
                mc.classList.remove('page-enter','page-back');
                void mc.offsetWidth;
                mc.classList.add('page-enter');
                this.currentPage = page;
                document.querySelectorAll('.topbar-nav a').forEach(a => {
                    a.classList.toggle('active', a.dataset.page === page);
                });
                updateAdminNav();
                refreshMemberTheme();
                if (typeof PageInit[page] === 'function') PageInit[page](opts);
                if (page === 'favorites') refreshFavoritesPage();
                return;
            }
            document.getElementById('mainContent').innerHTML = `<div class="empty-state">頁面載入失敗</div>`;
        }
    },

    needsLookLeaveGuard(nextPage) {
        if (this.leaveGuardOpen) return false;
        if (this.pendingLookSaved) return false;
        if (nextPage === this.currentPage) return false;
        if (this.currentPage !== 'suggestion' && this.currentPage !== 'compare') return false;
        return !!(this.pendingLook || hasStartedJourney());
    },

    promptLookLeave(nextPage, opts) {
        this.leaveGuardOpen = true;
        if (isGuest()) {
            showConfirm('訪客不能收藏妝容建議與妝容對比圖。離開後會清空目前這次妝容暫存。', {
                title: '需要會員身分',
                okText: '登入',
                cancelText: '直接離開',
                onOk: () => {
                    this.leaveGuardOpen = false;
                    showLogin();
                },
                onCancel: () => {
                    resetCurrentBeautySession();
                    this.leaveGuardOpen = false;
                    this.go(nextPage, { ...opts, skipLeaveGuard: true });
                },
                onDismiss: () => { this.leaveGuardOpen = false; }
            });
            return;
        }
        showConfirm('離開前要收藏這張妝容對比圖嗎？不收藏會清空目前這次妝容暫存。', {
            title: '收藏妝容對比圖',
            okText: '收藏',
            cancelText: '不要收藏',
            onOk: () => {
                if (saveCurrentLook()) showToast('已收藏妝容對比圖');
                this.leaveGuardOpen = false;
                this.go(nextPage, { ...opts, skipLeaveGuard: true });
            },
            onCancel: () => {
                resetCurrentBeautySession();
                this.leaveGuardOpen = false;
                this.go(nextPage, { ...opts, skipLeaveGuard: true });
            },
            onDismiss: () => { this.leaveGuardOpen = false; }
        });
    }
};

// ═══ 每頁的初始化邏輯 ═══
const PageInit = {
    dashboard() {
        // 問候語 + 日期
        const user = getMemberDisplayName();
        const hr = new Date().getHours();
        const hello = hr < 5 ? '夜深了' : hr < 11 ? '早安' : hr < 14 ? '午安' : hr < 18 ? '下午好' : '晚安';
        const greetEl = document.getElementById('dashGreet');
        // user 是會員自己設定的名稱，會員可把它設成 HTML／script，這裡一律轉義。
        if (greetEl) greetEl.innerHTML = `${hello}，<span class="accent">${escapeHtml(user)}</span>`;
        // 回訪不換按鈕：主按鈕一律「看看什麼適合我」。
        // 換成「看我的分析結果」會讓首頁的主要動作依狀態變成兩種東西，
        // 而使用者記得的是「首頁那顆金色按鈕」——它每次帶去不同地方，就記不住。
        // AI 猜你喜歡：依賴組員資料庫的登入 session，訪客或沒有推薦結果時整塊保持隱藏，不影響其他版位。
        const personalSection = document.getElementById('dashPersonalSection');
        const personalArea = document.getElementById('dashPersonal');
        if (personalSection && personalArea && !isGuest() && typeof Api !== 'undefined' && Api.getPersonalRecommendations) {
            Api.getPersonalRecommendations().then(picks => {
                if (!picks?.length || Router.currentPage !== 'dashboard') return;
                personalSection.style.display = '';
                personalArea.innerHTML = picks.map(p => `
                    <div class="glow-card reveal-in" data-pid="${p.id}">
                        <div class="gc-img">${phBox('', p.name, p.img)}</div>
                        <div class="gc-meta">
                            <div class="gc-top"><span class="gc-name">${escapeHtml(p.name)}</span><span class="gc-price">${escapeHtml(p.price)}</span></div>
                            <div class="gc-rating"><span class="stars">★★★★★</span><span class="gc-rev">${p.similarity != null ? `契合度 ${p.similarity}%` : (p.brand || '')}</span></div>
                        </div>
                    </div>`).join('');
                personalArea.querySelectorAll('.glow-card[data-pid]').forEach(card => {
                    card.onclick = () => Router.go('products', { productId: card.dataset.pid });
                });
            }).catch(() => {});
        }

        // 風格靈感 · 人像卡橫排（真實 STYLES）
        const insp = document.getElementById('dashInsp');
        if (insp && typeof STYLES !== 'undefined') {
            insp.innerHTML = STYLES.map((s, i) => `
                <div class="insp-card" data-style="${s.id}">
                    <div class="insp-visual">
                        ${phBox('', s.name, s.img)}
                        <span class="inum">${String(i+1).padStart(2,'0')}</span>
                    </div>
                    <div class="insp-body">
                        <div class="iname">${s.name}</div>
                        <div class="irole">${STYLE_ROLE[s.id] || 'Signature Look'}</div>
                        <div class="itags">${s.tags.slice(0,2).map(t => `<span>${t}</span>`).join('')}</div>
                    </div>
                </div>`).join('');
            insp.querySelectorAll('.insp-card').forEach(c => c.onclick = () => Router.go('style', { styleId: c.dataset.style }));
        }

        // 首頁商品推薦：與商品頁共用商品 API 真資料；若無熱門度欄位，照 API 回傳前幾筆顯示。
        const glow = document.getElementById('dashGlow');
        if (glow) {
            const picks = getFeaturedProducts(6);
            // 守衛看的是「載過沒有」，不是「有沒有東西」。用 picks.length 的話，
            // 商品全下架後 loadGeneralProductCatalog 會立刻同步回呼、重畫 dashboard、
            // 再次進到這裡——每一輪都是同步的，堆疊直接爆掉。
            if (!picks.length && !productCatalogLoaded() && !Router.generalProductLoading) {
                loadGeneralProductCatalog(() => {
                    if (Router.currentPage === 'dashboard') PageInit.dashboard();
                });
            }
            if (!picks.length) {
                glow.innerHTML = Router.generalProductLoading
                    ? Array.from({ length: 4 }).map(() => `
                        <div class="glow-card">
                            <div class="gc-img"><div class="skel-block" style="width:100%;height:100%;"></div></div>
                            <div class="skel-block" style="width:72%;height:16px;margin-bottom:10px;"></div>
                            <div class="skel-block" style="width:38%;height:12px;"></div>
                        </div>`).join('')
                    : '<div class="empty-state compact">目前沒有商品資料</div>';
            } else {
                glow.innerHTML = picks.map((p) => `
                <div class="glow-card reveal-in" data-pid="${p.id}">
                    <div class="gc-img">
                        ${phBox('', p.name, p.img)}
                        <button class="heart-btn gc-heart ${Fav.has(p.id)?'fav':''}" data-fav="${p.id}" aria-label="收藏">${HEART_SVG}</button>
                    </div>
                    <div class="gc-meta">
                        <div class="gc-top"><span class="gc-name">${escapeHtml(p.name)}</span><span class="gc-price">${escapeHtml(p.price)}</span></div>
                        <div class="gc-rating"><span class="stars">★★★★★</span><span class="gc-rev">${p.brand ? escapeHtml(p.brand) : (p.score != null ? `推薦分數 ${Math.round(p.score)}` : '商品資料庫')}</span></div>
                    </div>
                </div>`).join('');
            }
            glow.querySelectorAll('.glow-card[data-pid]').forEach(card => {
                card.onclick = (e) => { if (!e.target.closest('.heart-btn')) Router.go('products', { productId: card.dataset.pid }); };
            });
            glow.querySelectorAll('.gc-heart').forEach(btn => {
                btn.onclick = (e) => {
                    e.stopPropagation();
                    const id = btn.dataset.fav; const wasFav = Fav.has(id);
                    Fav.toggle(id, picks.find(x => String(x.id) === String(id))); btn.classList.toggle('fav', !wasFav);
                    btn.classList.remove('swap'); void btn.offsetWidth; btn.classList.add('swap');
                    if (!wasFav) showToast('已加入收藏');
                };
            });
        }

        // 導航（hero / feat-card / sh-link / greet-actions）
        document.querySelectorAll('[data-nav]').forEach(el => {
            el.classList.add('shine-edge');
            el.onclick = () => Router.go(el.dataset.nav);
        });
    },

    analysis() {
        // 五官圖鑑：把結果那幾格變成可點，點開看分類說明。
        // 目前值一律現查 Router.analysisResult，不快照——使用者在圖鑑裡改完之後
        // 那個值就變了，快照會讓「你的判斷」標記留在舊答案上。
        // 鼻型要走 noseDisplayText：PRO 有側臉結果時顯示的是另一套分類。
        if (typeof FeatureAtlas !== 'undefined') {
            FeatureAtlas.attach(field => {
                const r = Router.analysisResult || {};
                if (field === '鼻型') return (typeof noseDisplayText === 'function' ? noseDisplayText(r) : r['鼻型']) || '';
                return r[field] || '';
            });
        }
        const fileInput = document.getElementById('fileInput');
        const uploadBox = document.getElementById('uploadBox');
        const preview = document.getElementById('preview');
        const analyzeBtn = document.getElementById('analyzeBtn');
        const bar = document.getElementById('loadingBar');
        const fill = document.getElementById('loadingFill');
        const loadingStatus = document.getElementById('loadingStatus');
        const packageStatus = document.getElementById('packageStatus');
        const basicPanel = document.getElementById('basicPanel');
        const proPanel = document.getElementById('proPanel');
        const basicModeBtn = document.getElementById('basicModeBtn');
        const proModeBtn = document.getElementById('proModeBtn');

        Router.analyzeMode = Router.analyzeMode || 'basic';
        Router.selectedFile = null;
        Router.proFiles = { front: null, left45: null, right45: null, side: null };
        Router.packageImageFiles = {};
        Router.analysisPackage = null;
        Router.analysisResult = null;
        if (typeof AnalysisDraft !== 'undefined' && AnalysisDraft.clear) AnalysisDraft.clear();
        // 進頁一律灰階。上面剛把 analysisResult 清成 null，而頁面的 HTML 也是重新
        // 插入的，六格都是「—」——這時若還顯示成「已完成」的立體樣式，就是拿
        // 完成的外觀去包一組空值。
        //
        // ⚠️ 這一行必須在上面那串清除**之後**。放在前面的話讀到的是上一次的
        // analysisResult，於是剛進頁面就升起一塊全是「—」的結果區。
        setResultState(false);

        const setLoadingStatus = (text, active = false) => {
            if (!loadingStatus) return;
            loadingStatus.textContent = text;
            loadingStatus.classList.toggle('active', active);
        };

        const updatePackageStatus = () => {
            if (!packageStatus) return;
            const pkg = Router.analysisPackage;
            packageStatus.classList.toggle('ready', !!pkg);
            // 這一行是給使用者看的，不是給我們除錯的：`status` 是內部代碼
            // （draft／completed／failed），照原樣印出來對使用者沒有意義。
            const statusText = { draft: '進行中', completed: '已完成', failed: '失敗' }[pkg?.status] || '進行中';
            packageStatus.querySelector('span').textContent = pkg
                ? `${pkg.mode.toUpperCase()} · ${statusText} · ${Object.keys(pkg.images || {}).length} 張照片`
                : '尚未開始';
        };

        const fileMeta = (file, role) => ({
            role,
            serial: `${role}-${Date.now()}`,
            originalName: file.name,
            originalType: file.type,
            originalSize: file.size,
            compressedSize: null,
            width: null,
            height: null,
            compressedWidth: null,
            compressedHeight: null,
            compressionRatio: null
        });

        const compressImagesForPackage = async () => {
            const files = Router.analyzeMode === 'basic'
                ? { front: Router.selectedFile }
                : Router.proFiles;
            const images = {};
            Router.packageImageFiles = {};
            for (const [role, file] of Object.entries(files)) {
                if (!file) continue;
                const compressed = await ImagePipeline.compressForPackage(file, { role });
                Router.packageImageFiles[role] = compressed.file;
                images[role] = {
                    ...compressed.meta,
                    compressedDataUrl: compressed.dataUrl && compressed.dataUrl.length < 900000 ? compressed.dataUrl : null
                };
            }
            return images;
        };

        const saveDraft = (status = 'draft') => {
            const images = {};
            if (Router.analyzeMode === 'basic' && Router.selectedFile) {
                images.front = fileMeta(Router.selectedFile, 'front');
            }
            if (Router.analyzeMode === 'pro') {
                Object.entries(Router.proFiles).forEach(([role, file]) => {
                    if (file) images[role] = fileMeta(file, role);
                });
            }
            Router.analysisPackage = AnalysisPackage.create({ mode: Router.analyzeMode, images, status });
            AnalysisDraft.save(Router.analysisPackage);
            updatePackageStatus();
        };

        const showPreview = (file) => {
            const reader = new FileReader();
            reader.onload = ev => {
                preview.src = ev.target.result;
                preview.style.display = 'block';
                uploadBox.classList.add('has-preview');
                preview.title = '點擊更換照片';
                preview.onclick = () => fileInput.click();
            };
            reader.readAsDataURL(file);
        };

        // ─── 提亮控制 ───
        const bpPanel    = document.getElementById('brightnessPanel');
        const bpSlider   = document.getElementById('bpSlider');
        const bpValue    = document.getElementById('bpValue');
        const bpSummary  = document.getElementById('bpSummary');
        const bpStatus   = document.getElementById('bpStatus');
        const bpOriginals = { basic: null, front: null, side: null };
        const bpLuminance = { basic: null, front: null, side: null };
        let bpApplyVersion = 0;
        let bpSliderTimer = null;

        async function bpDetectLuminance(file) {
            return new Promise(resolve => {
                const img = new Image();
                const url = URL.createObjectURL(file);
                img.onload = () => {
                    const s = Math.min(1, 80 / Math.max(img.naturalWidth || 1, img.naturalHeight || 1));
                    const w = Math.max(1, Math.round(img.naturalWidth * s));
                    const h = Math.max(1, Math.round(img.naturalHeight * s));
                    const cv = document.createElement('canvas');
                    cv.width = w; cv.height = h;
                    cv.getContext('2d').drawImage(img, 0, 0, w, h);
                    URL.revokeObjectURL(url);
                    const d = cv.getContext('2d').getImageData(0, 0, w, h).data;
                    let sum = 0;
                    for (let i = 0; i < d.length; i += 4)
                        sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
                    resolve(sum / (d.length / 4));
                };
                img.onerror = () => { URL.revokeObjectURL(url); resolve(128); };
                img.src = url;
            });
        }

        function bpSmoothstep(edge0, edge1, x) {
            const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
            return t * t * (3 - 2 * t);
        }

        function bpTransform(file, sliderValue) {
            if (!file || Math.abs(sliderValue) < 1) return Promise.resolve(file);
            return new Promise((resolve, reject) => {
                const img = new Image();
                const url = URL.createObjectURL(file);
                img.onload = () => {
                    const scale = Math.min(1, 2400 / Math.max(img.naturalWidth || 1, img.naturalHeight || 1));
                    const cv = document.createElement('canvas');
                    cv.width  = Math.max(1, Math.round(img.naturalWidth  * scale));
                    cv.height = Math.max(1, Math.round(img.naturalHeight * scale));
                    const ctx = cv.getContext('2d');
                    ctx.drawImage(img, 0, 0, cv.width, cv.height);
                    URL.revokeObjectURL(url);

                    const id = ctx.getImageData(0, 0, cv.width, cv.height);
                    const d = id.data;
                    const val = Math.max(-100, Math.min(100, sliderValue)) / 100;
                    for (let i = 0; i < d.length; i += 4) {
                        const r = d[i], g = d[i + 1], b = d[i + 2];
                        const y = 0.299 * r + 0.587 * g + 0.114 * b;
                        const yn = y / 255;
                        let targetY;

                        if (val > 0) {
                            const shadowWeight = 1 - bpSmoothstep(0.32, 0.86, yn);
                            const midWeight = Math.sin(Math.PI * Math.min(1, Math.max(0, yn)));
                            const highlightProtect = bpSmoothstep(0.64, 0.96, yn);
                            const sat = (Math.max(r, g, b) - Math.min(r, g, b)) / 255;
                            const whiteProtect = (1 - sat) * bpSmoothstep(0.72, 0.98, yn);
                            const lift = val * (58 * shadowWeight + 24 * midWeight) * (1 - 0.88 * highlightProtect) * (1 - 0.70 * whiteProtect);
                            targetY = Math.min(246, y + lift);
                        } else {
                            const darken = -val;
                            const shadowProtect = 1 - bpSmoothstep(0.05, 0.30, yn);
                            targetY = Math.max(5, y - darken * (42 + 28 * yn) * (1 - 0.45 * shadowProtect));
                        }

                        const ratio = y > 1 ? targetY / y : 1;
                        d[i]     = Math.max(0, Math.min(255, Math.round(r * ratio)));
                        d[i + 1] = Math.max(0, Math.min(255, Math.round(g * ratio)));
                        d[i + 2] = Math.max(0, Math.min(255, Math.round(b * ratio)));
                    }
                    ctx.putImageData(id, 0, 0);

                    cv.toBlob(blob => {
                        if (!blob) { reject(new Error('照片提亮失敗')); return; }
                        const base = file.name.replace(/\.[^.]+$/, '') || 'photo';
                        resolve(new File([blob], `${base}-brightened.jpg`, { type: 'image/jpeg' }));
                    }, 'image/jpeg', 0.97);
                };
                img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('無法讀取照片')); };
                img.src = url;
            });
        }

        const bpActiveRoles = () => Router.analyzeMode === 'basic'
            ? (bpOriginals.basic ? ['basic'] : [])
            : ['front', 'side'].filter(role => bpOriginals[role]);

        // sliderValue：-100~+100 直接傳給 bpTransform
        const bpFactorFor = () => Number(bpSlider.value);

        function bpRefreshPanel() {
            const roles = bpActiveRoles();
            bpPanel.style.display = roles.length ? 'block' : 'none';
            if (!roles.length) return;
            const val = Number(bpSlider.value);
            bpValue.textContent = val > 0 ? `+${val}` : `${val}`;
            bpValue.className = `bp-value${val > 0 ? ' pos' : val < 0 ? ' neg' : ''}`;
            const names = Router.analyzeMode === 'basic' ? 'BASIC' : `PRO ${roles.length} 張`;
            bpSummary.textContent = names;
            bpStatus.textContent = val === 0
                ? '使用原圖'
                : val > 0 ? `已提亮，照片分析將使用處理後圖片` : `已調暗，照片分析將使用處理後圖片`;
        }

        async function bpApplyMode() {
            const version = ++bpApplyVersion;
            const roles = bpActiveRoles();
            if (!roles.length) return;
            bpStatus.textContent = '正在處理照片…';
            try {
                const factor = bpFactorFor();
                const processed = await Promise.all(roles.map(async role => [
                    role,
                    await bpTransform(bpOriginals[role], factor)
                ]));
                if (version !== bpApplyVersion) return;
                processed.forEach(([role, file]) => {
                    if (Router.analyzeMode === 'basic' && role === 'basic') {
                        Router.selectedFile = file;
                    } else {
                        Router.proFiles[role] = file;
                        if (role === 'front') Router.selectedFile = file;
                        updateProShotPreview(role);
                    }
                });
                if (Router.selectedFile) showPreview(Router.selectedFile);
                saveDraft('image-selected');
                bpRefreshPanel();
            } catch (err) {
                if (version !== bpApplyVersion) return;
                bpStatus.textContent = '提亮失敗，已保留原圖。';
                showAlert('照片提亮失敗：' + err.message, { type:'error' });
            }
        }

        async function bpRegisterFile(role, file) {
            bpOriginals[role] = file;
            const lum = await bpDetectLuminance(file);
            bpLuminance[role] = lum;
            // 首次上傳且滑桿在 0 時，自動建議提亮值（暗部照片）
            if (Number(bpSlider.value) === 0 && lum < 110) {
                bpSlider.value = Math.min(50, Math.round((110 - lum) / 2));
            }
            bpRefreshPanel();
            await bpApplyMode();
        }

        document.getElementById('bpReset').onclick = async () => {
            bpSlider.value = 0;
            bpRefreshPanel();
            await bpApplyMode();
        };

        bpSlider.oninput = () => {
            bpRefreshPanel();
            clearTimeout(bpSliderTimer);
            bpSliderTimer = setTimeout(bpApplyMode, 150);
        };

        const updateProShotPreview = (role) => {
            const file = Router.proFiles[role];
            const slot = document.querySelector(`[data-pro-slot="${role}"]`);
            const img = document.getElementById(`${role}Preview`);
            const nameEl = document.getElementById(`${role}FileName`);
            if (!slot || !img || !nameEl) return;
            if (img.dataset.objectUrl) {
                URL.revokeObjectURL(img.dataset.objectUrl);
                img.dataset.objectUrl = '';
            }
            slot.classList.toggle('has-photo', !!file);
            if (!file) {
                img.removeAttribute('src');
                nameEl.textContent = '必填';
                return;
            }
            const url = URL.createObjectURL(file);
            img.dataset.objectUrl = url;
            img.src = url;
        };

        const clearProShot = (role) => {
            Router.proFiles[role] = null;
            bpOriginals[role] = null;
            bpLuminance[role] = null;
            if (role === 'front') Router.selectedFile = null;
            updateProShotPreview(role);
            setProScanStatus(role, role === 'front' ? '正面：待擷取' : '側面：待擷取', false);
            saveDraft('image-selected');
            bpRefreshPanel();
        };

        const isProUnlocked = AdminStore.canUseProAnalysis(Auth.getProfile());
        proModeBtn.classList.toggle('locked', !isProUnlocked);
        if (!isProUnlocked) {
            proModeBtn.innerHTML = 'PRO <span class="lock-badge">🔒</span>';
            proModeBtn.title = 'PRO 分析為 VIP 會員專屬功能';
        }

        const setMode = (mode) => {
            if (mode === 'pro' && !isProUnlocked) {
                showAlert('PRO 臉部分析為 VIP 會員專屬功能，請聯繫管理員升級帳號', { type: 'error' });
                return;
            }
            Router.analyzeMode = mode;
            basicModeBtn.classList.toggle('active', mode === 'basic');
            proModeBtn.classList.toggle('active', mode === 'pro');
            basicPanel.classList.toggle('active', mode === 'basic');
            proPanel.classList.toggle('active', mode === 'pro');
            uploadBox.classList.remove('has-preview');
            preview.style.display = 'none';
            preview.removeAttribute('src');
            preview.onclick = null;
            bpRefreshPanel();
            analyzeBtn.textContent = mode === 'basic' ? '開 始 分 析' : '開 始 PRO 分 析';
            setLoadingStatus('等待圖片');
            updatePackageStatus();
        };

        basicModeBtn.onclick = () => setMode('basic');
        proModeBtn.onclick = () => setMode('pro');
        setMode((Router.analyzeMode === 'pro' && !isProUnlocked) ? 'basic' : Router.analyzeMode);

        uploadBox.onclick = () => fileInput.click();
        fileInput.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            Router.selectedFile = file;
            showPreview(file);
            saveDraft('image-selected');
            await bpRegisterFile('basic', file);
        };

        document.querySelectorAll('[data-pro-slot]').forEach(slot => {
            const key = slot.dataset.proSlot;
            const input = document.getElementById(`${key}Input`);
            const nameEl = document.getElementById(`${key}FileName`);
            slot.onclick = () => input.click();
            input.onchange = async (e) => {
                const file = e.target.files[0];
                if (!file) return;
                Router.proFiles[key] = file;
                nameEl.textContent = file.name;
                if (key === 'front') {
                    Router.selectedFile = file;
                    showPreview(file);
                }
                updateProShotPreview(key);
                saveDraft('image-selected');
                await bpRegisterFile(key, file);
            };
        });

        document.querySelectorAll('[data-pro-retake]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const role = btn.dataset.proRetake;
                clearProShot(role);
                setProScanHint(role === 'front' ? '已清除正面照，請重新拍正面' : '已清除側面照，請重新拍側面');
            };
        });

        document.getElementById('startCameraBtn').onclick = async () => {
            try {
                if (Router.cameraStream) return;
                Router.cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
                const video = document.getElementById('cameraVideo');
                video.srcObject = Router.cameraStream;
                document.getElementById('cameraBox').classList.add('active');
            } catch (err) {
                showAlert('無法開啟鏡頭：' + err.message, { type:'error' });
            }
        };

        document.getElementById('capturePhotoBtn').onclick = () => {
            const video = document.getElementById('cameraVideo');
            if (!Router.cameraStream || !video.videoWidth) {
                showAlert('請先開啟鏡頭');
                return;
            }
            const canvas = document.getElementById('cameraCanvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#fff';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(video, 0, 0);
            canvas.toBlob(async blob => {
                if (!blob) {
                    showAlert('拍照失敗', { type:'error' });
                    return;
                }
                Router.selectedFile = new File([blob], 'basic-camera.jpg', { type: 'image/jpeg' });
                showPreview(Router.selectedFile);
                saveDraft('camera-captured');
                await bpRegisterFile('basic', Router.selectedFile);
                Router.cameraStream.getTracks().forEach(track => track.stop());
                Router.cameraStream = null;
                document.getElementById('cameraBox').classList.remove('active');
            }, 'image/jpeg', 0.92);
        };

        const setProScanStatus = (role, text, done = false) => {
            const el = document.querySelector(`[data-scan-role="${role}"]`);
            if (!el) return;
            el.textContent = text;
            el.classList.toggle('done', done);
        };

        const setProScanHint = (text) => {
            const hint = document.getElementById('proScanHint');
            if (hint) hint.textContent = text;
        };

        const stopProScan = () => {
            if (Router.proScanTimer) {
                clearInterval(Router.proScanTimer);
                Router.proScanTimer = null;
            }
            if (Router.proCameraStream) {
                Router.proCameraStream.getTracks().forEach(track => track.stop());
                Router.proCameraStream = null;
            }
            const box = document.getElementById('proCameraBox');
            if (box) box.classList.remove('active');
            const yawEl = document.getElementById('proYawDisplay');
            if (yawEl) yawEl.textContent = '';
        };

        const captureProFrameBlob = () => new Promise((resolve, reject) => {
            const video = document.getElementById('proCameraVideo');
            if (!Router.proCameraStream || !video || !video.videoWidth) {
                reject(new Error('鏡頭尚未就緒'));
                return;
            }
            const canvas = document.getElementById('proCameraCanvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#fff';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(video, 0, 0);
            canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('影格擷取失敗')), 'image/jpeg', 0.9);
        });

        const storeProScanPhoto = async (role, blob, pose = {}) => {
            const file = new File([blob], `pro-${role}-${Date.now()}.jpg`, { type: 'image/jpeg' });
            Router.proFiles[role] = file;
            const nameEl = document.getElementById(`${role}FileName`);
            const auto = pose && typeof pose.yaw !== 'undefined';
            if (nameEl) nameEl.textContent = role === 'front'
                ? (auto ? '已自動擷取正面照' : '已手動擷取正面照')
                : (auto ? '已自動擷取側面照' : '已手動擷取側面照');
            if (role === 'front') {
                Router.selectedFile = file;
                showPreview(file);
            }
            updateProShotPreview(role);
            setProScanStatus(role, auto
                ? `${role === 'front' ? '正面' : '側面'}：已擷取 yaw ${Math.round(pose.yaw || 0)}°`
                : `${role === 'front' ? '正面' : '側面'}：已手動擷取`, true);
            saveDraft('camera-captured');
            await bpRegisterFile(role, file);
        };

        // SCAN_HOLD_FRAMES／proScanValidCount／proScanCurrentTarget 是自動擷取用的
        // 連續幀計數，2026-08-14 拿掉自動擷取後一併移除，不留無人使用的狀態。
        const SIDE_YAW_MIN = 35;

        const setYawDisplay = (text) => {
            const el = document.getElementById('proYawDisplay');
            if (el) el.textContent = text;
        };

        const scanProFrame = async () => {
            if (Router.proScanBusy) return;
            if (Router.proFiles.front && Router.proFiles.side) {
                setProScanHint('正面與側面已完成，可開始 PRO 分析');
                stopProScan();
                return;
            }
            Router.proScanBusy = true;
            try {
                const blob = await captureProFrameBlob();
                const pose = await Api.detectFacePose(new File([blob], 'pose-frame.jpg', { type: 'image/jpeg' }));
                const yaw = Number(pose.yaw || 0);
                const pitch = Number(pose.pitch || 0);
                const role = pose.captureRole || '';
                // pose.side: "left"（yaw<0，左臉朝鏡頭）或 "right"（yaw>0，右臉朝鏡頭）
                const faceSide = pose.side === 'left' ? '左臉' : '右臉';
                const absY = Math.abs(yaw);

                // ── yaw 數字顯示（不用箭頭，避免鏡像相機方向混亂） ──
                if (!Router.proFiles.front) {
                    const frontGuide = absY <= 3 ? '✓ 正面對準' : `偏移 ${Math.round(absY)}°`;
                    setYawDisplay(`yaw ${Math.round(yaw)}°  pitch ${Math.round(pitch)}°  ${frontGuide}`);
                } else {
                    const sideGuide = absY >= SIDE_YAW_MIN
                        ? `✓ ${faceSide}對準`
                        : (absY > 3 ? `${faceSide} 差 ${Math.round(SIDE_YAW_MIN - absY)}°` : '請轉向任一側面');
                    setYawDisplay(`yaw ${Math.round(yaw)}°  pitch ${Math.round(pitch)}°  ${sideGuide}`);
                }

                // 自動擷取已移除（2026-08-14）。這個迴圈現在只負責**顯示角度與提示**，
                // 不再自己按快門。
                //
                // 為什麼拿掉：自動擷取的判定是「yaw/pitch 落在範圍內且連續 N 幀」，
                // 但那只保證「角度數字在範圍內」，不保證那一幀拍得好——眨眼、動到、
                // 對焦沒跟上都照樣觸發，而且使用者當下不在看螢幕（提示語自己都寫著
                // 「不用再看螢幕」），拍壞了也不知道。實測結果是擷取到的照片品質不穩。
                //
                // 現在改成：系統只告訴你角度對不對，**由你自己按「手動存正面／側面」**。
                // 那兩顆按鈕本來就存在，過去只是被自動流程搶先。
                const frontReady = absY <= 8 && Math.abs(pitch) <= 12;
                const sideReady = absY >= SIDE_YAW_MIN;
                if (!Router.proFiles.front) {
                    setProScanHint(frontReady
                        ? '✓ 正面角度正確，按「手動存正面」擷取'
                        : '請直視鏡頭，讓臉部置中於橢圓框內');
                } else if (!Router.proFiles.side) {
                    const need = SIDE_YAW_MIN - absY;
                    setProScanHint(sideReady
                        ? `✓ ${faceSide}側面角度正確，按「手動存側面」擷取`
                        : `再轉約 ${Math.max(1, Math.round(need))}° 就到側面`);
                } else {
                    setProScanHint('正面與側面都已擷取，可開始 PRO 分析');
                }
            } catch (err) {
                const msg = String(err.message || err);
                setProScanHint(msg.includes('404')
                    ? '角度偵測暫時無法使用，請改用手動擷取。'
                    : '偵測中：' + msg);
            } finally {
                Router.proScanBusy = false;
            }
        };

        const startProScanBtn = document.getElementById('startProScanBtn');
        if (startProScanBtn) startProScanBtn.onclick = async () => {
            try {
                if (Router.analyzeMode !== 'pro') setMode('pro');
                if (!Router.proCameraStream) {
                    Router.proCameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
                    const video = document.getElementById('proCameraVideo');
                    video.srcObject = Router.proCameraStream;
                    document.getElementById('proCameraBox').classList.add('active');
                    try { await video.play(); } catch (_) {}
                }
                setProScanStatus('front', Router.proFiles.front ? '正面：已擷取' : '正面：請看鏡頭');
                setProScanStatus('side', Router.proFiles.side ? '側面：已擷取' : '側面：待擷取');
                setProScanHint(Router.proFiles.front
                    ? '已保留正面照，請慢慢轉向側面，系統會自動擷取側面照'
                    : '請先看著鏡頭，系統會自動擷取正面照');
                if (Router.proScanTimer) clearInterval(Router.proScanTimer);
                Router.proScanTimer = setInterval(scanProFrame, 400);
                setTimeout(scanProFrame, 250);
            } catch (err) {
                showAlert('無法開啟 PRO 掃描：' + err.message, { type:'error' });
            }
        };

        const stopProScanBtn = document.getElementById('stopProScanBtn');
        if (stopProScanBtn) stopProScanBtn.onclick = () => {
            stopProScan();
            setProScanHint('掃描已停止');
        };

        const manualFrontCaptureBtn = document.getElementById('manualFrontCaptureBtn');
        if (manualFrontCaptureBtn) manualFrontCaptureBtn.onclick = async () => {
            try {
                const blob = await captureProFrameBlob();
                storeProScanPhoto('front', blob, {});
                setProScanHint('已手動存入正面照，請轉向側面後存側面照');
            } catch (err) {
                showAlert('手動擷取正面失敗：' + err.message, { type:'error' });
            }
        };

        const manualSideCaptureBtn = document.getElementById('manualSideCaptureBtn');
        if (manualSideCaptureBtn) manualSideCaptureBtn.onclick = async () => {
            try {
                const blob = await captureProFrameBlob();
                storeProScanPhoto('side', blob, {});
                setProScanHint('已手動存入側面照，可開始 PRO 分析');
                if (Router.proFiles.front && Router.proFiles.side) stopProScan();
            } catch (err) {
                showAlert('手動擷取側面失敗：' + err.message, { type:'error' });
            }
        };

        analyzeBtn.onclick = async () => {
            setResultState(false);
            if (Router.analyzeMode === 'basic' && !Router.selectedFile) {
                showAlert('請先選擇照片或拍照');
                return;
            }
            if (Router.analyzeMode === 'pro' && (!Router.proFiles.front || !Router.proFiles.side)) {
                showAlert('PRO 分析需要正面照與側面照');
                return;
            }

            // 確保任何未完成的亮度調整都已套用，再把調色後的照片送往後端
            if (bpSliderTimer) {
                clearTimeout(bpSliderTimer);
                bpSliderTimer = null;
                await bpApplyMode();
            }

            const startedAt = Date.now();
            if (!Router.analysisPackage) saveDraft('queued');
            Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                status: 'preparing-image',
                async: { ...Router.analysisPackage.async, startedAt: new Date(startedAt).toISOString(), error: null }
            });
            AnalysisDraft.save(Router.analysisPackage);
            updatePackageStatus();
            const brightnessApplied = Number(bpSlider?.value || 0) !== 0;
            setLoadingStatus(brightnessApplied ? '調色後照片送出分析中' : '照片送出分析中', true);
            bar.style.display = 'block'; fill.style.width = '30%';
            try {
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, { status: 'analyzing' });
                AnalysisDraft.save(Router.analysisPackage);
                updatePackageStatus();
                setLoadingStatus('正在準備分析', true);
                fill.style.width = '45%';
                const job = Router.analyzeMode === 'basic'
                    ? await Api.createFaceJob(Router.selectedFile)
                    : await Api.createFaceProJob(Router.proFiles);
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                    status: 'queued',
                    async: {
                        ...Router.analysisPackage.async,
                        jobId: job.jobId,
                        // 建 job 時才拿得到，之後查 job 一律要它（X-Job-Token，沒帶會 403）。
                        // 回饋是使用者看完分析、想了一下才送的，中間會經過好幾次重繪，
                        // 所以要放進資料包帶著走——不存的話那一支就沒有東西可以證明
                        // 「這個 job 是我的」。
                        //
                        // 注意：只在同一個分頁的這一輪有效。草稿雖然寫進 sessionStorage，
                        // 但重新整理後沒有任何地方用 AnalysisDraft.load() 還原
                        // Router.analysisPackage，所以重整之後回饋就送不出去了。
                        resultToken: job.resultToken || null,
                        progress: job.progress || 0,
                        stage: job.stage || 'upload'
                    }
                });
                AnalysisDraft.save(Router.analysisPackage);
                updatePackageStatus();
                setLoadingStatus('已送出照片，等待分析…', true);

                const response = await Api.waitForFaceJob(Router.analyzeMode, job.jobId, job.resultToken, latestJob => {
                    const progress = Number(latestJob.progress || 0);
                    fill.style.width = `${Math.max(45, Math.min(88, 45 + progress * 0.4))}%`;
                    Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                        status: latestJob.status === 'processing' ? 'analyzing' : latestJob.status,
                        async: {
                            ...Router.analysisPackage.async,
                            jobId: latestJob.jobId,
                            progress,
                            stage: latestJob.stage || null,
                            error: latestJob.error?.message || null
                        }
                    });
                    AnalysisDraft.save(Router.analysisPackage);
                    updatePackageStatus();
                    setLoadingStatus(`分析中 ${progress}%`, true);
                });
                const data = response.result || response.data || response;
                Router.analysisResult = data;
                // 拿到結果就先記下來，不要等畫面畫完。
                //
                // 這一段後面有十幾個 document.getElementById(...).textContent = ...，
                // 任何一個元素不存在就整段拋例外 —— 分析其實成功了，卻既沒寫進紀錄、
                // 畫面又顯示「分析失敗」。紀錄是這次分析的成果，畫面只是呈現，
                // 呈現壞掉不該讓成果跟著消失。
                History.add({ ...data, analysisPackageId: Router.analysisPackage.id, mode: Router.analyzeMode });
                setLoadingStatus('分析完成，正在整理結果', true);
                const packagedImages = await compressImagesForPackage();
                const completedAt = Date.now();
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                    status: 'completed',
                    images: packagedImages,
                    faceAnalysis: AnalysisPackage.fromRawFaceAnalysis(data, Router.analyzeMode),
                    analysis: {
                        ...Router.analysisPackage.analysis,
                        [Router.analyzeMode]: data
                    },
                    generativeText: {
                        ...Router.analysisPackage.generativeText,
                        prompt: null,
                        suggestion: null,
                        status: 'ready-for-text-ai'
                    },
                    render: {
                        ...Router.analysisPackage.render,
                        status: 'pending',
                        provider: 'replicate',
                        beforeImageDataUrl: packagedImages.front?.compressedDataUrl || null,
                        beforeImageId: packagedImages.front?.serial || null,
                        styleId: Router.selectedStyleId
                    },
                    async: {
                        ...Router.analysisPackage.async,
                        completedAt: new Date(completedAt).toISOString(),
                        durationMs: completedAt - startedAt,
                        error: null
                    }
                });
                AnalysisDraft.save(Router.analysisPackage);
                updatePackageStatus();
                fill.style.width = '100%';
                setLoadingStatus('分析完成', false);
                setTimeout(() => { bar.style.display = 'none'; fill.style.width = '0'; }, 400);

                document.getElementById('r-face').textContent = data['臉型'] || '—';
                document.getElementById('r-brow').textContent = data['眉型'] || '—';
                document.getElementById('r-eye').textContent = data['眼型'] || '—';
                paintNoseCell(data);
                document.getElementById('r-lip').textContent = data['嘴型'] || '—';
                document.getElementById('r-season').textContent = data['膚色']?.['四季型'] || '—';
                setResultState(true);

                const skin = data['膚色'] || {}, lab = skin['LAB'] || {};
                document.getElementById('skinName').textContent = skin['膚色分級'] || '—';
                // LAB 數值不對使用者顯示：那是色彩科學的座標，色塊本身已經表達了顏色。
                //（值仍在 analysisPackage 裡，推薦端與渲染端照常使用。）
                document.getElementById('skinSwatch').style.background = Api.labToRgb(lab.L||50, lab.a||0, lab.b||0);

                // 膚色不可靠時顯示重拍提示；舊版後端沒有旗標時視為可靠。
                const skinWarn = document.getElementById('skinReliabilityWarn');
                if (skinWarn) {
                    const rel = skin['可信度'] || {};
                    const unreliable = rel.reliable === false;
                    skinWarn.style.display = unreliable ? '' : 'none';
                    skinWarn.textContent = unreliable
                        ? (rel.hint || '臉頰被頭髮或陰影遮住，膚色可能不準；把頭髮撥到耳後、在均勻光線下重拍會更準確。')
                        : '';
                }

                const lipLab = data['嘴唇_LAB'] || {};
                // 同上：唇色 LAB 不顯示，只留色塊。
                document.getElementById('lipSwatch').style.background = Api.labToRgb(lipLab.L||40, lipLab.a||0, lipLab.b||0);

                document.getElementById('goStyleBtn').style.display = 'inline-block';
                renderAnalysisFeedback(data, Router.analysisPackage.id);
            } catch (err) {
                bar.style.display = 'none'; fill.style.width = '0';
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                    status: 'failed',
                    async: { ...Router.analysisPackage.async, error: err.message }
                });
                AnalysisDraft.save(Router.analysisPackage);
                updatePackageStatus();
                setLoadingStatus('分析失敗，你的照片與進度已保留', false);
                const offline = /Failed to fetch|NetworkError|Load failed/i.test(String(err.message || err));
                // 照片問題的 message 本身就是可行動的重拍指引（「請把頭轉向你的右邊」）。
                // 冠上「分析失敗：」會把它講成系統壞掉，使用者反而不知道該做什麼。
                // 其餘錯誤才需要那個前綴；把 code 一起傳給 showAlert，讓它查表把
                // 「分析失敗：臉部分析失敗，請稍後再試」這種疊字換成單一句子。
                const photoProblem = err.code === 'FACE_IMAGE_UNUSABLE';
                showAlert(offline
                    ? '目前無法連接臉部分析服務，請稍後再試。'
                    : (photoProblem ? err.message : '分析失敗：' + err.message),
                    { type:'error', code: err.code || '' });
            }
        };

        document.getElementById('goStyleBtn').onclick = () => Router.go('style');
        updatePackageStatus();
    },

    style(opts) {
        if (!hasStartedJourney()) { renderAnalysisGate("風格試妝"); return; }
        const grid = document.getElementById('styleGrid');
        const renderGrid = () => {
            grid.innerHTML = STYLES.map(s => `
                <div class="style-card ${Router.selectedStyleId===s.id?'selected':''}" data-sid="${s.id}">
                    <div class="sc-visual">${phBox('', s.name, s.img)}</div>
                    <div class="sc-name">${s.name}</div>
                    <div class="sc-tags">${s.tags.map(t=>`<span class="sc-tag">${t}</span>`).join('')}</div>
                </div>
            `).join('');
            grid.querySelectorAll('.style-card').forEach(card => {
                card.onclick = () => {
                    const nextStyleId = card.dataset.sid;
                    if (Router.selectedStyleId && Router.selectedStyleId !== nextStyleId && hasStartedJourney()) {
                        showConfirm('要沿用目前這張臉部分析照片套用到新的妝容風格嗎？', {
                            title: '沿用目前照片',
                            okText: '沿用',
                            cancelText: '不要',
                            onOk: () => {
                                Router.selectedStyleId = nextStyleId;
                                Router.pendingLook = null;
                                Router.pendingLookSaved = false;
                                renderGrid();
                            },
                            onCancel: () => {
                                resetCurrentBeautySession();
                                renderAnalysisGate('風格試妝');
                            }
                        });
                        return;
                    }
                    Router.selectedStyleId = nextStyleId;
                    renderGrid();
                };
            });
        };
        renderGrid();

        // 從首頁風格靈感點進來：直接選定並顯示該妝容介紹
        if (opts && opts.styleId && STYLES.some(s => s.id === opts.styleId)) {
            Router.selectedStyleId = opts.styleId;
            renderGrid();
            renderAnalysisResult(null);
        }

        document.getElementById('confirmStyleBtn').onclick = async () => {
            if (!Router.selectedStyleId) { showAlert('請先選擇風格'); return; }
            const btn = document.getElementById('confirmStyleBtn');
            const bar = document.getElementById('suggestionBar');
            const fill = document.getElementById('suggestionFill');
            const status = document.getElementById('suggestionStatus');

            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '產生建議中...';

            bar.style.display = 'block';
            status.classList.add('active');
            const paint = (pct, text) => { fill.style.width = `${pct}%`; status.textContent = text; };
            paint(8, '產生建議中...');

            try {
                const result = await runMakeupSuggestion(paint);
                const failure = handleSuggestionFailure(result);
                if (failure === 'failed') {
                    bar.style.display = 'none';
                    fill.style.width = '0';
                    status.textContent = '建議產生失敗';
                    status.classList.remove('active');
                    renderAnalysisResult(null);
                    return;
                }
                if (failure) return;
                setTimeout(() => { bar.style.display = 'none'; fill.style.width = '0'; status.classList.remove('active'); }, 600);
                // 先把結果區填好再跳：使用者從合併頁返回這一頁時不會看到空白。
                renderAnalysisResult(result.response);
                Router.go('suggestion');
            } finally {
                startButtonCooldown(btn, 15, originalText);
            }
        };

        function renderAnalysisResult(aiSuggestionResponse) {
            const style = STYLES.find(s => s.id === Router.selectedStyleId);
            const r = Router.analysisResult || {};
            const skin = r['膚色'] || {};
            const savedSuggestion = Router.analysisPackage?.generativeText?.suggestion;
            const aiSuggestion = aiSuggestionResponse?.suggestion || savedSuggestion || '';
            const container = document.getElementById('styleResultArea');
            container.innerHTML = `
                <h2 class="makeup-guide-title">${style.name}<span>妝容分析指南</span></h2>
                <div class="analysis-tags" style="justify-content:center;">
                    ${style.tags.map(t=>`<span class="analysis-tag">${t}</span>`).join('')}
                </div>
                ${paletteRowHtml(style)}
                <div class="analysis-section">
                    <h3>五官與膚色分析</h3>
                    <div class="analysis-item"><span class="ai-label">臉型</span><span class="ai-value">${r['臉型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">眉型</span><span class="ai-value">${r['眉型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">眼型</span><span class="ai-value">${r['眼型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">鼻型</span><span class="ai-value">${noseDisplayText(r)||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">嘴型</span><span class="ai-value">${r['嘴型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">膚色</span><span class="ai-value">${skin['膚色分級']||'—'} / ${skin['四季型']||'—'}</span></div>
                </div>
                <div class="analysis-section">
                    <h3>專屬妝容建議</h3>
                    ${aiSuggestion
                        ? `<div class="advice-grid">${renderMakeupAdviceGrid(aiSuggestion)}</div>`
                        : `<div class="empty-state compact">尚未取得妝容建議，請按上方「確認風格」產生個人化建議。</div>`
                    }
                </div>
                <div style="text-align:center;margin-top:20px;">
                    <button class="btn-outline" onclick="Router.go('compare')" style="margin-right:8px;">查看前後對比</button>
                    <button class="btn-outline" onclick="Router.go('suggestion')" style="margin-right:8px;">查看妝容建議</button>
                    <button class="btn-gold" onclick="openProductRecommendationModal()">查看推薦商品 →</button>
                </div>
            `;
        }

    },

    products(opts) {
        // 一般瀏覽也要有品牌、價格與排序——使用者不是只在「推薦」那一區買東西，
        // 一般商品頁就是逛街的地方，而逛街本來就會照價格與品牌看。
        //
        // 全部在本機做：`Router.generalProductCatalog` 已經是整份清單
        //（loadGeneralProductCatalog 會翻頁到底），而線上商品服務的 `sort` 與
        // `minPrice`/`maxPrice` 實測沒有作用（2026-08-28），送出去只會得到
        // 一個沒有篩到的畫面。
        const shopPriceOf = (p) => {
            const n = Number(String(p?.price ?? '').replace(/[^0-9.]/g, ''));
            return Number.isFinite(n) ? n : null;
        };
        const applyShopControls = (list) => {
            // 後端支援伺服器端篩選時就不要再篩一次。
            //
            // 兩邊都篩不會錯，但會讓「為什麼這件沒出現」變成兩個地方要查；
            // 而且後端篩的是**全部商品**，本機篩的只是已載入的那些——
            // 兩者結果不同時，重複套用會把後端的正確結果再切一刀。
            // 關鍵字**一律**在本機篩，而且要在伺服器端篩選的 early return 之前。
            //
            // 商品 API 沒有關鍵字參數（listProducts 只送 cursor），所以這個條件
            // 後端從來收不到。放到 return 之後的話，等哪天後端開始回 appliedFilters／facets，
            // productServerFiltering 變成 true，搜尋就會安靜地整個失效——
            // 使用者打字、清單不動，而畫面上沒有任何東西說明為什麼。
            const q = String(Router.shopQuery || '').trim().toLowerCase();
            let base = list || [];
            if (q) {
                base = base.filter((p) => {
                    // 名稱、品牌、色號都比對：使用者記得的可能是「RUBY WOO」也可能是「MAC」，
                    // 或是櫃上抄下來的那組色號。
                    const hay = [p?.name, p?.brand, p?.shadeCode, CAT_EN[p?.cat], p?.cat]
                        .map(v => String(v ?? '').toLowerCase());
                    return hay.some(v => v.includes(q));
                });
            }
            if (Api.productServerFiltering) return base;
            const brand = Router.shopBrand || '';
            const min = Router.shopMinPrice, max = Router.shopMaxPrice;
            let rows = base.filter((p) => {
                if (brand && String(p.brand || '') !== brand) return false;
                if (min == null && max == null) return true;
                const price = shopPriceOf(p);
                // 沒有價格的商品在有價格條件時排除：當成 0 會讓它永遠落在最低價以上。
                if (price == null) return false;
                if (min != null && price < min) return false;
                if (max != null && price > max) return false;
                return true;
            });
            const sort = Router.shopSort || 'default';
            const byPrice = (dir) => (a, b) => {
                const x = shopPriceOf(a), y = shopPriceOf(b);
                if (x === null && y === null) return 0;
                if (x === null) return 1;      // 沒價格的排最後，不要因為 NaN 跑到最前面
                if (y === null) return -1;
                return dir * (x - y);
            };
            if (sort === 'price_asc') rows = [...rows].sort(byPrice(1));
            else if (sort === 'price_desc') rows = [...rows].sort(byPrice(-1));
            else if (sort === 'name_asc') rows = [...rows].sort((a, b) =>
                String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hant'));
            return rows;
        };

        function renderShop(filter) {
            Router.shopFilter = filter;
            const area = document.getElementById('productsArea');
            const cats = CATEGORIES.map(c => c.id);
            const chips = [`<button class="chip ${filter==='all'?'active':''}" data-filter="all">全部<span class="chip-en">All</span></button>`]
                .concat(cats.map(id => `<button class="chip ${filter===id?'active':''}" data-filter="${id}">${id}</button>`)).join('');
            const recommended = getRecommendedProductCatalog();
            // 排列與張數都跟推薦彈窗共用（見 orderRecommendedProducts）：同一份推薦
            // 在兩個地方必須列出同樣的商品。
            const recommendedAll = orderRecommendedProducts(recommended);
            // 篩選只作用在這批推薦上，不會回頭跟後端要更多商品（後端目前也不支援）。
            const recommendedByCat = RecFilter.apply(recommendedAll);
            const apiCatalog = Array.isArray(Router.generalProductCatalog) ? Router.generalProductCatalog : [];
            // 就算已有個人化推薦也要載全部商品清單：下方「全部商品」要靠它，推薦卡缺圖時也要用它補圖
            const shouldLoadGeneralProducts = !productCatalogLoaded() && !Router.generalProductLoading;
            if (shouldLoadGeneralProducts) {
                loadGeneralProductCatalog(() => {
                    if (Router.currentPage === 'products') renderShop(filter);
                });
            }
            const catalog = apiCatalog;
            const byCat = filter === 'all' ? catalog : catalog.filter(p => p.cat === filter);
            const list = applyShopControls(byCat);
            // 切換分類等於換一份清單，已展開的筆數要跟著歸零。
            if (Router.shopVisibleFilter !== filter || !Router.shopVisible) {
                Router.shopVisibleFilter = filter;
                Router.shopVisible = SHOP_PAGE_SIZE;
            }
            const visible = Math.min(Router.shopVisible, list.length);
            // 「載入中」是還沒載過才算。清單載過了但是空的（後台把商品全下架），
            // 那是結果不是過程，要顯示「目前沒有商品資料」——講成載入中會讓人一直等。
            const isLoadingProducts = Router.generalProductLoading && !productCatalogLoaded();
            const header = `
                <div class="page-header"><span class="eyebrow">Boutique · 選物</span><h1>商品推薦</h1><div class="divider"></div></div>
                ${recommended.length ? `<section class="recommended-strip">
                    <div class="dash-sec-head"><div class="sh-l"><span class="sh-no">❧</span><h2>本次個人化推薦</h2></div></div>
                    ${RecommendationNotice.personalizationHtml()}
                    ${RecommendationNotice.foundationNoticeHtml()}
                    ${RecFilter.html(recommendedAll)}
                    ${!recommendedByCat.length ? RecFilter.emptyHtml() : ''}
                    <div class="prod-grid recommended-grid">${recommendedByCat.slice(0, RECOMMENDED_DISPLAY_LIMIT).map((p, i) => `
                        <div class="prod-card reveal-in" data-rec-pid="${escapeHtml(p.id)}" style="animation-delay:${Math.min(i*0.035,0.2)}s">
                            <div class="pc-imgwrap">${phBox('', p.name, p.img)}</div>
                            <div class="pc-cat">${escapeHtml(CAT_EN[p.cat]||p.cat)}${p.brand ? ` · ${escapeHtml(p.brand)}` : ''}</div>
                            <div class="pc-name">${escapeHtml(p.name)}</div>
                            <!-- 色號單獨拉出來。它是使用者實際要記住、要拿去櫃上問的那個字串，
                                 而在名稱裡它只是結尾的四個字元（「…SPF 48/ PA++ - PO-02」）。
                                 詳情頁早就有「色號 Shade」那一格，卡片沒有——但看清單的時候
                                 才是最需要它的時候：要比較好幾支。 -->
                            ${p.shadeCode ? `<div class="pc-shade"><span>色號</span><b>${escapeHtml(String(p.shadeCode))}</b></div>` : ''}
                            ${(!p.recommendationPresentation?.headline && p.matchReason) ? `<div class="pc-reason">${escapeHtml(p.matchReason)}</div>` : ''}
                            ${colorCompareHtml(p)}
                            ${recommendationCardHtml(p)}
                            <div class="pc-foot"><span class="pc-price">${escapeHtml(p.price)}</span></div>
                        </div>`).join('')}
                    </div>
                </section>` : ''}
                ${RecommendationNotice.html()}
                ${RecommendationNotice.isEmpty && !recommended.length && !Router.productRecommendationLoading
                    ? RecommendationNotice.emptyHtml() : ''}
                <div class="shop-controls">
                    <label class="sc-search"><span>搜尋</span><span class="sc-search-box">
                        <svg class="sc-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21"/></svg>
                        <input type="search" data-shop="q" placeholder="商品、品牌或色號"
                            autocomplete="off" value="${escapeHtml(Router.shopQuery || '')}">
                    </span></label>
                    <label><span>品牌</span><select data-shop="brand">
                        <option value="">全部品牌</option>
                        ${[...new Set(byCat.map(p => String(p.brand || '')).filter(Boolean))].sort()
                            .map(b => `<option value="${escapeHtml(b)}"${Router.shopBrand === b ? ' selected' : ''}>${escapeHtml(b)}</option>`).join('')}
                    </select></label>
                    <label><span>價格</span><span class="sc-range">
                        <input type="number" min="0" step="1" placeholder="最低" inputmode="numeric"
                            data-shop="min" value="${Router.shopMinPrice ?? ''}">
                        <i>–</i>
                        <input type="number" min="0" step="1" placeholder="最高" inputmode="numeric"
                            data-shop="max" value="${Router.shopMaxPrice ?? ''}">
                    </span></label>
                    <label><span>排序</span><select data-shop="sort">
                        <option value="default"${(Router.shopSort||'default') === 'default' ? ' selected' : ''}>推薦排序</option>
                        <option value="price_asc"${Router.shopSort === 'price_asc' ? ' selected' : ''}>價格：低到高</option>
                        <option value="price_desc"${Router.shopSort === 'price_desc' ? ' selected' : ''}>價格：高到低</option>
                        <option value="name_asc"${Router.shopSort === 'name_asc' ? ' selected' : ''}>名稱：A 到 Z</option>
                    </select></label>
                    ${(Router.shopBrand || Router.shopMinPrice != null || Router.shopMaxPrice != null
                        || String(Router.shopQuery || '').trim()
                        || (Router.shopSort && Router.shopSort !== 'default'))
                        ? '<button type="button" class="sc-clear" data-shop="clear">清除條件</button>' : ''}
                </div>
                <div class="filter-bar">${chips}</div>
                <div class="prod-count">${isLoadingProducts ? '商品載入中'
                    : (Router.generalProductError && !list.length ? '商品服務暫時無法載入，請稍後再試'
                    : (list.length !== byCat.length
                        ? `${list.length} 件商品（已從 ${byCat.length} 件篩選）`
                        : `${list.length} 件商品`))}</div>`;
            const bindChips = () => {
                area.querySelectorAll('.chip').forEach(ch => ch.onclick = () => renderShop(ch.dataset.filter));
                // 篩選與排序。改條件時把「已展開幾筆」歸零——不歸零的話換完條件
                // 還停在第 60 筆，畫面看起來像沒反應。
                const num = (v) => (v === '' || v == null || !Number.isFinite(Number(v))) ? null : Number(v);
                area.querySelectorAll('[data-shop]').forEach((el) => {
                    const kind = el.dataset.shop;
                    const apply = () => {
                        if (kind === 'brand') Router.shopBrand = el.value;
                        else if (kind === 'sort') Router.shopSort = el.value;
                        else if (kind === 'min') Router.shopMinPrice = num(el.value);
                        else if (kind === 'max') Router.shopMaxPrice = num(el.value);
                        else if (kind === 'q') Router.shopQuery = el.value;
                        else if (kind === 'clear') {
                            Router.shopBrand = '';
                            Router.shopSort = 'default';
                            Router.shopMinPrice = null;
                            Router.shopMaxPrice = null;
                            Router.shopQuery = '';
                        }
                        Router.shopVisible = SHOP_PAGE_SIZE;
                        renderShop(Router.shopFilter);
                    };
                    if (kind === 'clear') el.onclick = apply;
                    else if (kind === 'q') {
                        // 邊打邊篩，但不是每個字都重畫一次整頁——1040 件商品重畫三次
                        // 的成本會讓輸入卡住。計時器掛在 Router 上而不是這裡：
                        // 每次 renderShop 都會重建這個閉包，區域變數的 clearTimeout
                        // 會清到一個已經沒人認得的計時器，等於沒有 debounce。
                        el.oninput = () => {
                            Router.shopQuery = el.value;
                            Router._shopSearchAt = Date.now();
                            clearTimeout(Router._shopSearchTimer);
                            Router._shopSearchTimer = setTimeout(apply, 250);
                        };
                        // Enter 立即套用，不等計時器：按下去沒反應會讓人以為壞了。
                        el.onkeydown = (e) => {
                            if (e.key !== 'Enter') return;
                            e.preventDefault();
                            clearTimeout(Router._shopSearchTimer);
                            Router.shopQuery = el.value;
                            Router._shopSearchAt = Date.now();
                            apply();
                        };
                    }
                    else el.onchange = apply;
                });
                // 重畫會把輸入框整個換掉，游標跟著消失——連打兩個字就會發現
                // 第二個字打不進去。所以重畫後要把焦點與游標位置放回去。
                //
                // 只在「剛剛真的在打字」時還原（1.5 秒內）：不加這個條件的話，
                // 搜尋框有值時去點分類 chip，焦點會被搶回搜尋框，手機還會彈出鍵盤。
                if (Date.now() - (Router._shopSearchAt || 0) < 1500) {
                    const q = area.querySelector('[data-shop="q"]');
                    if (q) {
                        q.focus();
                        const end = q.value.length;
                        // search 型別在部分瀏覽器不支援 setSelectionRange，失敗不能擋住渲染。
                        try { q.setSelectionRange(end, end); } catch (_) {}
                    }
                }
                // 提示列的「重試」與空狀態的兩顆按鈕。跟 chip 一起綁，因為
                // 每次 renderShop 都會重畫 area，事件必須跟著重新掛上。
                RecommendationNotice.bind(area);
                // 價格／品牌篩選：改變條件就重畫整個商品頁（保留目前的分類 filter）。
                RecFilter.bind(area, () => renderShop(filter));
            };
            if (!recommended.length && !Router.productRecommendationLoading && Router.analysisPackage?.faceAnalysis) {
                Router.productRecommendationLoading = true;
                // 重試就是把同一段再跑一次；把它包成具名函式交給提示列的「重試」按鈕。
                const runRecommend = () => {
                    Router.productRecommendationLoading = true;
                    Api.recommendProducts(Router.analysisPackage, Router.selectedStyleId)
                        .then(rec => {
                            RecommendationNotice.record(rec, runRecommend);
                            if (rec?.products?.length) {
                                Router.productRecommendationError = false;
                                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                                    recommendations: {
                                        ...(Router.analysisPackage.recommendations || {}),
                                        products: rec.products
                                    }
                                });
                                AnalysisDraft.save(Router.analysisPackage);
                            } else if (rec && rec.ok === false) {
                                // 推薦服務打不到（例如 /recommend-products 404）——記錄下來讓畫面顯示提示，不再靜默
                                Router.productRecommendationError = true;
                            }
                            if (Router.currentPage === 'products') renderShop(filter);
                        })
                        .catch(() => {
                            Router.productRecommendationError = true;
                            RecommendationNotice.record(null, runRecommend);
                            if (Router.currentPage === 'products') renderShop(filter);
                        })
                        .finally(() => { Router.productRecommendationLoading = false; });
                };
                runRecommend();
            }
            // 1) API 載入中只顯示骨架，不再用前端假商品補畫面
            area.innerHTML = header + (isLoadingProducts
                ? `<div class="prod-grid">` + Array.from({length:8}).map(()=>`
                    <div><div class="skel-block" style="width:100%;aspect-ratio:1/1;margin-bottom:15px;"></div>
                    <div class="skel-block" style="width:40%;height:10px;margin-bottom:9px;"></div>
                    <div class="skel-block" style="width:78%;height:14px;margin-bottom:10px;"></div>
                    <div class="skel-block" style="width:30%;height:14px;"></div></div>`).join('') + `</div>`
                : '');
            bindChips();
            // 2) 淡入商品卡
            const cardHtml = (p, i) => {
                // 進場動畫只給最前面幾張，其餘直接以最終狀態掛上去。
                const animated = i < SHOP_ANIMATE_LIMIT;
                return `
                    <div class="prod-card${animated ? ' reveal-in' : ''}" data-pid="${escapeHtml(p.id)}"${animated ? ` style="animation-delay:${Math.min(i*0.035,0.4)}s"` : ''}>
                        <div class="pc-imgwrap">
                            ${phBox('', p.name, p.img)}
                            <button class="heart-btn pc-heart ${Fav.has(p.id)?'fav':''}" data-fav="${escapeHtml(p.id)}" aria-label="收藏">${HEART_SVG}</button>
                        </div>
                        <div class="pc-cat">${escapeHtml(CAT_EN[p.cat]||p.cat)}</div>
                        <div class="pc-name">${escapeHtml(p.name)}</div>
                        ${p.brand ? `<div class="pc-cat">${escapeHtml(p.brand)}</div>` : ''}
                        <div class="pc-foot"><span class="pc-price">${escapeHtml(p.price)}</span></div>
                    </div>`;
            };
            // 卡片事件逐批綁定：載入更多時只綁新加進來的那批，已經在畫面上的不重綁。
            const bindCards = (nodes) => {
                nodes.forEach(card => {
                    if (!card.classList || !card.classList.contains('prod-card')) return;
                    card.onclick = (e) => {
                        if (e.target.closest('.heart-btn')) return;
                        renderProductDetail(card.dataset.pid || card.dataset.recPid);
                    };
                    const heart = card.querySelector('.pc-heart');
                    if (!heart) return;
                    heart.onclick = (e) => {
                        e.stopPropagation();
                        const id = heart.dataset.fav;
                        const wasFav = Fav.has(id);
                        Fav.toggle(id, list.find(x => String(x.id) === String(id)));
                        heart.classList.toggle('fav', !wasFav);
                        heart.classList.remove('swap'); void heart.offsetWidth; heart.classList.add('swap');
                        if (!wasFav) showToast('已加入收藏');
                    };
                });
            };
            const moreBarHtml = (shown) => shown >= list.length
                ? ''
                : `<div class="shop-more"><button class="btn-outline" id="shopMoreBtn" type="button">載入更多商品（已顯示 ${shown} / ${list.length}）</button></div>`;
            const bindMore = () => {
                const btn = document.getElementById('shopMoreBtn');
                if (!btn) return;
                btn.onclick = () => {
                    const grid = document.getElementById('shopGrid');
                    if (!grid) return;
                    const from = Router.shopVisible;
                    const to = Math.min(from + SHOP_PAGE_SIZE, list.length);
                    Router.shopVisible = to;
                    // 只把新增的這批接到現有 grid 後面，不重建整個清單：重建會丟掉捲動位置，
                    // 也會把已經解碼好的圖片全部作廢重來。
                    const holder = document.createElement('div');
                    holder.innerHTML = list.slice(from, to).map((p, i) => cardHtml(p, from + i)).join('');
                    const added = Array.from(holder.children);
                    added.forEach(node => grid.appendChild(node));
                    bindCards(added);
                    const bar = btn.parentElement;
                    if (to >= list.length) { bar.remove(); return; }
                    btn.textContent = `載入更多商品（已顯示 ${to} / ${list.length}）`;
                };
            };
            setTimeout(() => {
                if (Router.currentPage !== 'products' || Router.shopFilter !== filter) return;
                const content = list.length
                    ? `<div class="prod-grid" id="shopGrid">` + list.slice(0, visible).map(cardHtml).join('') + `</div>` + moreBarHtml(visible)
                    // 空清單有三種原因，要講對是哪一種。都寫成「目前沒有商品資料」的話，
                    // 搜尋沒中的人會以為是平台沒貨，而不是自己的關鍵字沒對上——
                    // 全庫有一千多件，那句話會把他直接勸退。
                    : `<div class="empty-state compact">${
                        isLoadingProducts ? '商品載入中'
                        : (String(Router.shopQuery || '').trim()
                            ? `找不到符合「${escapeHtml(String(Router.shopQuery).trim())}」的商品，換個關鍵字或清除條件再試試`
                            : '目前沒有商品資料')}</div>`;
                area.innerHTML = header + content;
                bindChips();
                bindCards(Array.from(area.querySelectorAll('.prod-card')));
                bindMore();
            }, 360);
        }

        // 色階資料掉了就自己補回來，不要要求使用者重跑一次流程。
        //
        // shadeRecommendation 只在「套用妝容風格 → 抓推薦」那一次流程裡拿到。
        // 重新整理之後記憶體沒了；而在「把它存進資料包」這個修正上線之前建立的
        // session，草稿裡也沒有那個欄位——那些分頁會一直看不到色階比較，
        // 直到使用者自己重新走一次流程，而他不會知道要那樣做。
        //
        // 有分析資料就能重新問一次。只補一次（_shadeRefetched 這個旗標），
        // 失敗也安靜收掉：這是補救，不是主要路徑，不該讓商品頁因此出錯。
        let _shadeRefetching = false;
        const refetchShadeIfMissing = (onDone) => {
            if (_shadeRefetching || Router._shadeRefetched) return false;
            if (currentShadeRecommendation()) return false;
            const pkg = Router.analysisPackage;
            if (!pkg?.faceAnalysis || !Router.selectedStyleId) return false;
            _shadeRefetching = true;
            Router._shadeRefetched = true;
            Api.recommendProducts(pkg, Router.selectedStyleId).then(rec => {
                if (rec?.shadeRecommendation) {
                    RecommendationNotice.record(rec);
                    onDone();
                }
            }).catch(() => {}).finally(() => { _shadeRefetching = false; });
            return true;
        };

        function renderProductDetail(id) {
            const recommended = getRecommendedProductCatalog();
            const apiCatalog = Array.isArray(Router.generalProductCatalog) ? Router.generalProductCatalog : [];
            const catalog = [...recommended, ...apiCatalog];
            const p = catalog.find(x => String(x.id) === String(id));
            if (!p) {
                showAlert('這筆推薦商品的識別資料不完整，已重新載入商品清單，請稍後再試。', { type: 'error' });
                Router.generalProductCatalog = null;
                loadGeneralProductCatalog(() => {
                    if (Router.currentPage === 'products') renderShop(Router.shopFilter || 'all');
                });
                return;
            }
            const area = document.getElementById('productsArea');
            // 每筆商品代表一個色號，直接使用清單提供的 hex_primary 與 Lab。
            let related = catalog.filter(x => x.cat === p.cat && String(x.id) !== String(p.id)).slice(0,3);
            if (related.length < 3) related = related.concat(catalog.filter(x => x.cat !== p.cat && String(x.id) !== String(p.id)).slice(0, 3 - related.length));
            // 色號圈圈：優先用商品 hex；沒有 hex 就用 CIELAB 換算(推薦端以色找色一定帶 lab)。
            // 這樣即使資料庫商品沒填 hex，只要有 lab 就畫得出色號圈圈。
            //
            // 色碼文字（2026-08-13）：商品 API 目前兩邊都不回 hex_primary，只有推薦端帶 lab，
            // 所以「只在有真 hex 時才附上」等於永遠不附。改成沒有原始 hex 時印出由 lab 換算的
            // 近似值，並用 `≈` 與 title 標明它是換算來的——沒有色碼可看，比看到一個標好
            // 「近似」的色碼更沒用。資料庫把 hex_primary 補回來後，這裡會自動改用原始值。
            // 顏色只認**商品端給的原始色碼**（`hex`／`hex_primary`／…，六種寫法在
            // Api._normalizeProduct 都吃）。2026-08-14 決定：不再用 CIELAB 換算的近似值。
            //
            // 為什麼拿掉：換算出來的顏色是我們算的，不是商品的正式色號。使用者看到色塊
            // 會當成「這就是這支的顏色」，但那是從色度值推回螢幕 RGB 的估計，跟包裝上的
            // 色號不保證一致——在美妝情境下，一個看起來很篤定卻不保證正確的顏色，
            // 比沒有顏色更糟。
            //
            // 欄位與轉換函式都留著（`Api.labToRgb` / `Api.labToHex` 仍在）：
            // 等資料庫端把 `hex_primary` 補回來（見《給資料庫端_商品顏色資料遺失回報》），
            // `p.hex` 一有值，色塊與色碼就會自動出現，這裡不必再改。
            const swatchColor = p.hex || null;
            // 色名：資料庫的 shade_name 從頭到尾都是空的（`給資料庫端_商品資料現況與需求_2026-07-20.md`
            // §2.4 已經問過），但**色名一直都在商品名稱裡**——實測 100/100 筆都是
            // 「商品名 - 色名」的格式（例：「Za 午後花園柔霧唇膏 - 櫻桃陷阱」）。
            // 所以名稱尾巴就是目前唯一拿得到色號的地方；等資料庫回填 shade_name 後
            // 會自動改用正式欄位。分隔符認「空白 + 破折號 + 空白」，不能只認 '-'，
            // 否則像「Twenty-Fun」這種色名本身含連字號的會被從中間切斷。
            const shadeFromName = (() => {
                const parts = String(p.name || '').split(/\s[-－—]\s/);
                return parts.length > 1 ? parts[parts.length - 1].trim() : '';
            })();
            const shadeName = String(p.shadeName || p.shade_name || '').trim() || shadeFromName;
            // color 與 hexLabel 只會在商品端真的給了色碼時有值；沒有就只顯示色名。
            const renderColorBox = (color, hexLabel, shade) => (color || shade)
                ? `<div class="pd-color"><div class="pd-color-label">色號 <span>Shade</span></div><div class="pd-shades">`
                  + (color ? `<span class="shade active" style="background:${escapeHtml(color)}" aria-label="商品色號"></span>` : '')
                  + (shade ? `<span style="margin-left:${color ? '10px' : '0'};font-family:var(--cjk);font-size:13.5px;color:var(--ink-2);">${escapeHtml(shade)}</span>` : '')
                  + (hexLabel ? `<code style="margin-left:8px;font-size:12px;color:var(--mid);">${escapeHtml(hexLabel)}</code>` : '')
                  + `</div></div>`
                : '';
            // 「你的膚色」對照：把使用者自己量到的膚色放在商品旁邊，讓他自己比。
            //
            // 為什麼值得做：商品端目前沒有色碼（見《給資料庫端_商品顏色資料遺失回報》），
            // 系統沒辦法幫使用者算「這支適不適合你」。但**使用者自己的膚色是有的**，
            // 把它擺在商品照片旁邊，至少讓人用眼睛比——這比什麼都不給有用得多。
            //
            // 兩件事一定要誠實標示，否則這個區塊會變成誤導：
            //   1. 這是**你的膚色**，不是商品顏色，也不是系統的推薦結論
            //   2. 取樣被判定不可信時（頭髮或陰影蓋住臉頰）要講出來，
            //      不可信的膚色拿去比色，比不比還糟
            const renderSkinCompare = () => {
                const skin = Router.analysisPackage?.faceAnalysis?.skinTone;
                const lab = skin?.lab;
                if (!Array.isArray(lab) || lab.length !== 3) return '';
                const color = Api.labToRgb(Number(lab[0]), Number(lab[1]), Number(lab[2]));
                const meta = [skin.season, skin.level].filter(Boolean).join(' · ');
                const unreliable = skin.labReliable === false;
                return `<div class="pd-color" style="margin-top:10px;">`
                    + `<div class="pd-color-label">你的膚色 <span>Your Skin</span></div>`
                    + `<div class="pd-shades">`
                    + `<span class="shade active" style="background:${escapeHtml(color)}" aria-label="你的膚色"></span>`
                    + (meta ? `<span style="margin-left:10px;font-family:var(--cjk);font-size:13.5px;color:var(--ink-2);">${escapeHtml(meta)}</span>` : '')
                    + `</div>`
                    + (unreliable
                        ? `<p style="margin:6px 0 0;font-size:12px;color:var(--mid);">這次的膚色取樣被判定不可信（臉頰可能被頭髮或陰影蓋住），僅供參考。</p>`
                        : '')
                    + `</div>`;
            };
            const renderRelatedGrid = (items, heading) => `
                <div class="pd-related">
                    <div class="dash-sec-head"><div class="sh-l"><span class="sh-no">❧</span><h2>${escapeHtml(heading)}</h2></div><span class="sh-link" onclick="PageInit.products();">查看全部</span></div>
                    <div class="prod-grid">${items.map(r => `
                        <div class="prod-card reveal-in" data-rel="${r.id}">
                            <div class="pc-imgwrap">${phBox('', r.name, r.img)}</div>
                            <div class="pc-cat">${escapeHtml(CAT_EN[r.cat]||r.cat)}${r.similarity != null ? ` · ${escapeHtml(r.similarity)}% 相似` : ''}</div>
                            <div class="pc-name">${escapeHtml(r.name)}</div>
                            <div class="pc-foot"><span class="pc-price">${escapeHtml(r.price)}</span></div>
                        </div>`).join('')}</div>
                </div>`;
            // 分類 key 進 onclick 的 JS 字串裡：escapeHtml 沒用——HTML 解析器會把 &#039;
            // 還原成 '，在行內事件處理器仍會跳出字串執行。分類本來就是英數 key，這裡先
            // 收斂成安全字元集，斷掉這條 JS 注入面；顯示文字另外走 escapeHtml。
            // 先前這裡把分類收斂成 [a-zA-Z0-9_-] 再塞進 onclick 字串裡。
            // 收斂本身是對的（行內事件處理器不能放未經處理的字串），但分類是**中文**
            // ——「底妝」被整串濾掉，變成空字串，於是返回一律掉回「全部商品」。
            // 改成 data 屬性 ＋ 事件綁定：值不進 JS 字串，所以不必閹割它，
            // 中文分類也留得住。
            const catToken = String(p.cat || '').replace(/[^a-zA-Z0-9_-]/g, '');   // 仍供舊呼叫點使用
            // 從色階比較點進來的話，返回要回到那支主推薦粉底。
            // 只認一次：回去之後就清掉，否則之後從別處進到同一件商品，
            // 返回還是會跳到那支粉底——那時候使用者早就不在比較的脈絡裡了。
            const backToShade = (Router.shadeReturnTo && Router.shadeReturnTo !== id)
                ? Router.shadeReturnTo : '';
            area.innerHTML = `
                <div class="pd-top">
                    ${backToShade
                        ? `<a href="#" class="back-link" data-back-shade="${escapeHtml(backToShade)}">← 回到粉底色號比較</a>
                           <button class="pd-close" aria-label="關閉" data-back-shade="${escapeHtml(backToShade)}">×</button>`
                        : `<a href="#" class="back-link" data-back-cat="${escapeHtml(String(p.cat || ''))}">← ${escapeHtml(p.cat)}</a>
                           <button class="pd-close" aria-label="關閉" data-back-cat="${escapeHtml(String(p.cat || ''))}">×</button>`}
                </div>
                <div class="pd-wrap">
                    <!-- 詳情頁是唯一要看清楚商品的地方，用原圖；清單一律用 img 的縮圖版本。 -->
                    <div class="pd-img">${phBox('', p.name, p.imgFull || p.img)}</div>
                    <div class="pd-info">
                        <div class="pd-en">${CAT_EN[p.cat]||'BEAUTY'}</div>
                        <div class="pd-name">${escapeHtml(p.name)}</div>
                        ${p.brand ? `<div class="pd-en">${escapeHtml(p.brand)}</div>` : ''}
                        <div class="pd-price-lg">${escapeHtml(p.price)}</div>
                        <div id="pdColorBox">${renderColorBox(swatchColor, p.hex || '', shadeName)}${renderSkinCompare()}</div>
                        <!-- 鄰近色號緊接在「色號」那一格底下。
                             先前它排在整頁最後、連「查看商品原頁」都在它上面——
                             使用者看著自己的色號時，最想知道的就是旁邊還有哪幾支，
                             那個問題不該要捲到頁尾才回答得到。 -->
                        ${shadeRecommendationHtml(p)}
                        <div class="pd-actions">
                            <button class="add-bag" data-bag="${p.id}">加入購物袋</button>
                            <button class="heart-btn pd-heart ${Fav.has(p.id)?'fav':''}" data-fav-detail="${p.id}" aria-label="收藏">${HEART_SVG}</button>
                        </div>
                        <div class="pd-desc">${escapeHtml(p.desc || p.matchReason || '商品詳細說明區域。可放入完整描述、使用方式、成分說明等資訊。')}</div>
                        ${colorCompareHtml(p)}
                        ${recommendationPanelHtml(p)}
                        ${productSourceLinkHtml(p)}
                    </div>
                </div>
                <div id="pdRelatedBox">${renderRelatedGrid(related, '你可能也喜歡')}</div>
            `;
            // 三張色號卡都要打得開（契約 §8.2 的檢查項）。用委派：整個區塊
            // 是重新渲染出來的，逐張綁會在下一次重畫時全部失效。
            // 三欄並排之後不再需要 Modal——要比較的東西已經全部看得到了。
            // 每一欄的「查看商品」直接跳到那支色號的商品頁。
            area.querySelectorAll('[data-back-cat]').forEach(el => {
                el.onclick = (ev) => {
                    ev.preventDefault();
                    // 回到**這個商品所屬的分類**，不是全部商品。
                    PageInit.products({ category: el.dataset.backCat || 'all' });
                };
            });
            area.querySelectorAll('[data-back-shade]').forEach(el => {
                el.onclick = (ev) => {
                    ev.preventDefault();
                    const target = el.dataset.backShade;
                    Router.shadeReturnTo = '';   // 用過就清掉，只認這一次
                    window.scrollTo(0, 0);
                    renderProductDetail(target);
                };
            });
            area.querySelectorAll('[data-shade-go]').forEach(btn => {
                // 記住是從哪一支粉底的色階比較點進來的。
                // 返回應該回到那支粉底，而不是回到整個分類清單——
                // 使用者是在「比較三個色號」這件事情中間，回到清單等於把他丟出這個脈絡。
                btn.onclick = () => {
                    Router.shadeReturnTo = id;
                    Router.go('products', { productId: btn.dataset.shadeGo });
                };
            });
            // 這件是粉底、通過了膚色門檻，卻沒有色階區塊——那多半是資料掉了，
            // 不是後端沒給。補一次再重畫。
            if (p.foundationSkinMatch?.accepted === true) {
                refetchShadeIfMissing(() => {
                    if (Router.currentPage === 'products') renderProductDetail(id);
                });
            }
            // 色差說明。找的是「正在看的這件商品」，不是任何一件——
            // 同一頁上相關商品也可能帶著色差，開錯那件會解釋到別人的數字。
            area.querySelectorAll('[data-color-diff]').forEach(btn => {
                btn.onclick = () => openColorDiffModal(p);
            });
            const bag = area.querySelector('[data-bag]');
            if (bag) bag.onclick = () => {
                Cart.add(p.id);
                updateCartBadge();
                showToast('已加入購物車');
            };
            const dBtn = area.querySelector('[data-fav-detail]');
            if (dBtn) dBtn.onclick = () => {
                const wasFav = Fav.has(p.id);
                Fav.toggle(p.id, p);
                dBtn.classList.toggle('fav', !wasFav);
                dBtn.classList.remove('swap'); void dBtn.offsetWidth; dBtn.classList.add('swap');
                if (!wasFav) showToast('已加入收藏');
            };
            const bindRelatedClicks = () => {
                area.querySelectorAll('[data-rel]').forEach(c => c.onclick = () => { window.scrollTo(0,0); renderProductDetail(c.dataset.rel); });
            };
            bindRelatedClicks();

            // 以色找色：在本機用 lab 算色差，不打 API（上游那支端點不存在，見 Api.findSimilarShades）。
            // 標題不再叫「AI 相似色彩推薦」——這是 CIE94 色差公式，不是模型，叫它 AI 是騙人的。
            if (typeof Api !== 'undefined' && Api.findSimilarShades) {
                const similar = Api.findSimilarShades(p, apiCatalog, 3);
                if (similar.length) {
                    const box = document.getElementById('pdRelatedBox');
                    if (box) {
                        box.innerHTML = renderRelatedGrid(similar, '相似色號');
                        bindRelatedClicks();
                    }
                }
            }
        }

        // 分派放在最後：這個方法裡的 renderShop / renderProductDetail 是函式宣告
        // （會提升），但它們用到的 applyShopControls、shopPriceOf、
        // refetchShadeIfMissing 是 const。在原本的位置先呼叫，會在 const 初始化前
        // 讀到它們，拋 ReferenceError: Cannot access ... before initialization——
        // 而錯誤發生在 area.innerHTML 賦值之前，所以整個商品頁是全白的，
        // 連「目前沒有商品資料」都不會出現。語法檢查抓不到，這是執行期的 TDZ。
        if (opts && opts.productId) {
            renderProductDetail(opts.productId);
        } else {
            renderShop((opts && opts.category) || Router.shopFilter || 'all');
        }
    },

    favorites() {
        // 三個來源的解析與「查不到的件數」跟會員中心共用 resolveFavoriteProducts()，
        // 否則兩邊各算各的就會再次分岔。
        const apiCatalog = Array.isArray(Router.generalProductCatalog) ? Router.generalProductCatalog : [];
        const { items, unavailable } = resolveFavoriteProducts();
        const area = document.getElementById('favArea');
        if (!area) return;
        const syncState = Router.favoriteSyncState || 'idle';
        const syncNote = syncState === 'loading'
            ? '<div class="fav-sync-note">正在同步會員收藏…</div>'
            : (syncState === 'error'
                ? '<div class="fav-sync-note is-error">雲端收藏暫時無法同步，目前顯示這台裝置上的資料。<button type="button" data-fav-retry>重新同步</button></div>'
                : '');
        const bindRetry = () => {
            const retry = area.querySelector('[data-fav-retry]');
            if (retry) retry.onclick = refreshFavoritesPage;
        };
        if (!productCatalogLoaded() && !Router.generalProductLoading) {
            loadGeneralProductCatalog(() => { if (Router.currentPage === 'favorites') PageInit.favorites(); });
        }
        // 「另有 N 件查不到資料」那行說明**刻意不顯示**（2026-08-13 決定）：對使用者來說，
        // 一件他從沒察覺自己失去的收藏，講出來只會製造疑慮，而他也無法做任何處理。
        // 查不到的收藏仍留在 Fav 清單裡（resolveFavoriteProducts 不會刪它們），商品重新
        // 上架就會自己回來；會員中心的數字也一律只數畫得出來的件數，兩邊因此一致。
        if (!items.length && !unavailable.length) {
            const emptyText = syncState === 'loading' ? '正在讀取收藏商品' : '目前尚無收藏商品';
            area.innerHTML = syncNote + `<div class="empty-state">${emptyText}</div>`;
            bindRetry();
            return;
        }
        // 已下架的排在後面：使用者要先看到還買得到的那些。
        const goneCards = unavailable.map(p => `
            <div class="prod-card is-gone" data-gone-pid="${escapeHtml(p.id)}">
                <div class="pc-imgwrap">
                    <div class="pc-gone-mark">✕</div>
                    <button class="heart-btn pc-heart fav" data-unfav="${escapeHtml(p.id)}" aria-label="移除收藏">${HEART_SVG}</button>
                </div>
                <div class="pc-cat">已下架</div>
                <div class="pc-name">此商品已下架</div>
                <div class="pc-foot"><span class="pc-price">—</span></div>
            </div>`).join('');
        area.innerHTML = syncNote + `<div class="prod-count">${items.length} 件收藏${
            unavailable.length ? `　·　${unavailable.length} 件已下架` : ''}</div><div class="prod-grid">` + items.map((p, i) => `
            <div class="prod-card reveal-in" data-pid="${p.id}" style="animation-delay:${Math.min(i*0.035,0.4)}s">
                <div class="pc-imgwrap">
                    ${phBox('', p.name, p.img)}
                    <button class="heart-btn pc-heart fav" data-unfav="${p.id}" aria-label="移除收藏">${HEART_SVG}</button>
                </div>
                <div class="pc-cat">${escapeHtml(CAT_EN[p.cat]||p.cat)}</div>
                <div class="pc-name">${escapeHtml(p.name)}</div>
                <div class="pc-foot"><span class="pc-price">${escapeHtml(p.price)}</span></div>
            </div>
        `).join('') + goneCards + `</div>`;
        area.querySelectorAll('.prod-card').forEach(card => {
            card.onclick = (e) => { if (!e.target.closest('.heart-btn')) Router.go('products',{productId:card.dataset.pid}); };
        });
        area.querySelectorAll('[data-unfav]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                btn.classList.remove('swap'); void btn.offsetWidth; btn.classList.add('swap');
                const card = btn.closest('.prod-card');
                if (card) { card.style.transition='opacity .35s var(--ease), transform .35s var(--ease)'; card.style.opacity='0'; card.style.transform='translateY(10px)'; }
                const product = items.find(x => String(x.id) === String(btn.dataset.unfav));
                setTimeout(()=>{ Fav.toggle(btn.dataset.unfav, product); PageInit.favorites(); }, 320);
            };
        });
        bindRetry();
    },

    compare(opts) {
        // 帶著一筆歷史收藏進來（從會員中心的「查看完整對比」）。
        //
        // ⚠️ 這一筆**只用於顯示**，不寫進 Router.analysisPackage。
        // 使用者可能正在做一次新的分析，看一眼舊收藏不該把那次洗掉——
        // 而 analysisPackage 是渲染、推薦、回饋共用的那份，覆寫它會一路影響到
        // 「這次的推薦」與「這張臉的回饋」，症狀不會出現在這一頁。
        const look = (opts && opts.look && typeof opts.look === 'object') ? opts.look : null;
        Router.viewingLook = look;
        // 看歷史收藏不需要做過分析——那筆資料本身就完整。
        if (!look && !hasStartedJourney()) { renderAnalysisGate("妝容對比圖"); return; }
        const style = look
            ? (STYLES.find(x => x.name === look.style) || null)
            : STYLES.find(s => s.id === Router.selectedStyleId);
        const nameEl = document.getElementById('compareStyleName');
        const tagsEl = document.getElementById('compareStyleTags');
        const stage = document.getElementById('compareStage');
        const holdBtn = document.getElementById('compareHoldBtn');
        if (!look) {
            Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
            Router.pendingLookSaved = false;
        }

        nameEl.textContent = look ? (look.style || '妝容建議')
            : (style ? style.name : '尚未選擇風格');
        tagsEl.innerHTML = style ? style.tags.map(t => `<span class="analysis-tag">${t}</span>`).join('') : '';

        const showAfter = () => {
            stage.classList.remove('before');
            stage.classList.add('after');
            setCompareImage('after');
        };
        const showBefore = () => {
            stage.classList.remove('after');
            stage.classList.add('before');
            setCompareImage('before');
        };

        // iOS 式長按對比：放開時停在「基準」那張，按住時看另一張。
        // 基準在渲染完成後會變成妝後圖（成果），所以實際體感是「按住看原圖、放開回成果」。
        // 按鈕文字固定不動——狀態是暫態的，跟著改只會閃爍。
        const hasAfterImage = () => {
            const render = (Router.analysisPackage || {}).render || {};
            return !!(render.afterImageUrl || render.afterImageDataUrl
                || render.makeupOutput?.imageUrl || render.makeupOutput?.imageDataUrl);
        };
        const showBaseline = () => { Router.compareBaseline === 'after' ? showAfter() : showBefore(); };
        const pressHold = (e) => {
            if (e && e.preventDefault) e.preventDefault();
            // 還沒渲染就按住只會看到空白，讓人以為壞掉——直接講清楚
            if (!hasAfterImage()) { showToast('還沒有妝後圖，請先按「生成妝容」'); return; }
            Router.compareBaseline === 'after' ? showBefore() : showAfter();
        };
        const releaseHold = () => showBaseline();

        Router.compareBaseline = hasAfterImage() ? 'after' : 'before';
        showBaseline();
        holdBtn.textContent = '按住對比';
        holdBtn.style.touchAction = 'none';      // 不讓瀏覽器把長按當成捲動／縮放手勢
        holdBtn.style.userSelect = 'none';       // 長按不要選取到按鈕文字
        holdBtn.onpointerdown = pressHold;
        holdBtn.onpointerup = releaseHold;
        holdBtn.onpointerleave = releaseHold;    // 手指滑出按鈕就當放開，不然會卡在對比狀態
        holdBtn.onpointercancel = releaseHold;
        holdBtn.oncontextmenu = (e) => e.preventDefault();  // 手機長按預設會跳系統選單
        // 鍵盤操作：按住空白鍵／Enter 看另一張，放開回基準
        holdBtn.onkeydown = (e) => { if (e.key === ' ' || e.key === 'Enter') pressHold(e); };
        holdBtn.onkeyup = (e) => { if (e.key === ' ' || e.key === 'Enter') releaseHold(); };
        document.getElementById('compareGoStyleBtn').onclick = () => Router.go('style');

        // 收藏一律走同一個確認視窗。臨時網址警告與 renderPrompt 預覽都在那裡，
        // 兩邊各寫一份，遲早會有一邊漏掉警告。
        const saveBtn = document.getElementById('compareSaveLookBtn');
        if (saveBtn) saveBtn.onclick = openSaveLookModal;

        function setCompareImage(kind) {
            // 看歷史收藏時用那一筆的圖，不要去讀當前分析——
            // 兩者可能是不同的臉，混起來會顯示成別人的妝前配自己的妝後。
            const viewing = Router.viewingLook;
            if (viewing) {
                const image = kind === 'after'
                    ? lookImageSrc(viewing.renderedImage)
                    : lookImageSrc(viewing.beforeImage);
                stage.classList.toggle('has-render', !!image);
                if (image) {
                    stage.style.backgroundImage = `url("${image}")`;
                    stage.style.backgroundSize = 'contain';
                    stage.style.backgroundPosition = 'center';
                    stage.style.backgroundRepeat = 'no-repeat';
                } else {
                    stage.style.backgroundImage = '';
                }
                return;
            }
            const pkg = Router.analysisPackage || {};
            const render = pkg.render || {};
            const beforeImage = pkg.images?.front?.compressedDataUrl
                || render.beforeImageUrl
                || render.beforeImageDataUrl
                || '';
            const afterImage = render.afterImageUrl || render.afterImageDataUrl || render.makeupOutput?.imageUrl || render.makeupOutput?.imageDataUrl || '';
            const image = kind === 'after' ? afterImage : beforeImage;
            stage.classList.toggle('has-render', !!image);
            if (image) {
                stage.style.backgroundImage    = `url("${image}")`;
                stage.style.backgroundSize     = 'contain';
                stage.style.backgroundPosition = 'center';
                stage.style.backgroundRepeat   = 'no-repeat';
            } else {
                stage.style.backgroundImage    = '';
                stage.style.backgroundSize     = '';
                stage.style.backgroundPosition = '';
                stage.style.backgroundRepeat   = '';
            }
        }
        setCompareImage('before');
    },

    suggestion(opts) {
        if (!hasStartedJourney()) { renderAnalysisGate("妝容建議"); return; }
        // 從會員中心點一筆收藏進來時，顯示那一筆而不是當前這次分析。
        //
        // ⚠️ 只用於顯示，不寫回 Router.analysisPackage——那份是渲染、推薦、
        // 回饋共用的，覆寫它會讓「看一眼舊收藏」把使用者正在做的新分析洗掉，
        // 而症狀會出現在別的頁面上。
        const viewLook = (opts && opts.look && typeof opts.look === 'object') ? opts.look : null;
        Router.viewingLook = viewLook;
        const style = viewLook
            ? (STYLES.find(x => x.name === viewLook.style) || STYLES[0])
            : (STYLES.find(s => s.id === Router.selectedStyleId) || STYLES[0]);
        const r = getLatestAnalysisResult() || {};
        const skin = r['膚色'] || {};
        const pkg = Router.analysisPackage || {};
        const aiSuggestion = pkg.generativeText?.suggestion || '';
        const render = pkg.render || {};
        const makeupOutput = render.makeupOutput || {};
        const beforeImage = pkg.images?.front?.compressedDataUrl
            || render.beforeImageUrl
            || render.beforeImageDataUrl
            || '';
        const renderedImage = render.afterImageUrl || render.afterImageDataUrl || makeupOutput.imageUrl || makeupOutput.imageDataUrl || '';
        const displayImage = renderedImage || beforeImage;
        const area = document.getElementById('suggestionArea');
        if (!area) return;
        area.innerHTML = `
            <div class="compare-layout">
                <div class="compare-preview">
                    <div class="ph compare-stage ${renderedImage ? 'after' : 'before'}" id="suggestionStage">
                        <span class="compare-photo-label" id="suggestionPhotoLabel">${renderedImage ? '妝後' : '妝前'}</span>
                    </div>
                    <button class="compare-hold-btn" id="suggestionToggleBtn"${renderedImage ? '' : ' disabled'}>看妝前</button>
                </div>
                <div class="analysis-section">
                    <div class="detail-pill">妝容結果</div>
                    <h3 id="suggestionPhotoTitle">${renderedImage ? `${style.name} 渲染後妝容照片` : `${style.name} 原始照片`}</h3>
                    <p id="suggestionPhotoNote">${renderedImage ? '這張照片來自目前分析資料包的妝容結果。' : beforeImage ? '尚未取得妝容圖片，這裡先顯示目前分析資料包內的原始照片。' : '尚未取得妝容圖片。'}</p>
                </div>
            </div>
            <div class="style-intro-card">
                <h3>${style.name} 專屬妝容建議</h3>
                <div class="analysis-tags">${style.tags.map(t => `<span class="analysis-tag">${t}</span>`).join('')}</div>
                ${paletteRowHtml(style)}
            </div>
            <div class="analysis-section">
                <h3>五官與膚色分析</h3>
                <div class="analysis-item"><span class="ai-label">臉型</span><span class="ai-value">${r['臉型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">眉型</span><span class="ai-value">${r['眉型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">眼型</span><span class="ai-value">${r['眼型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">鼻型</span><span class="ai-value">${noseDisplayText(r)||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">嘴型</span><span class="ai-value">${r['嘴型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">膚色</span><span class="ai-value">${skin['膚色分級']||'—'} / ${skin['四季型']||'—'}</span></div>
            </div>
            <div class="step-panel${aiSuggestion ? ' done' : ''}">
                <span class="eyebrow">Step 1 · Personalized text</span>
                <h3>${aiSuggestion ? `${style.name} 專屬妝容建議` : '先生成 Ollama 個人化建議'}</h3>
                <p class="step-note">系統會把本次臉部分析與「${style.name}」一起送給文字建議服務，為你個人產生建議。這一步只產生文字，不會產生圖片。</p>
                ${pkg.generativeText?.stale
                    ? `<p class="step-stale">你在產生這份建議之後修改過臉部分析。下面這份是用修改前的五官跑出來的，按「重新生成建議」就會換成你的答案。</p>`
                    : ''}
                ${aiSuggestion ? `<div class="advice-grid">${renderMakeupAdviceGrid(aiSuggestion)}</div>` : ''}
                <div class="step-actions">
                    <button class="btn-gold" id="genSuggestionBtn">${aiSuggestion ? '重新生成建議' : '生成 Ollama 建議'}</button>
                </div>
                <div class="step-state" id="suggestionState">${aiSuggestion ? 'DONE' : 'READY'}</div>
            </div>
            <div class="step-panel">
                <span class="eyebrow">Step 2 · Makeup render</span>
                <h3>生成妝容渲染圖</h3>
                <div class="step-actions">
                    <button class="btn-gold" id="suggestionRenderBtn">${renderedImage ? '重新生成妝容' : '生成妝容'}</button>
                    ${renderedImage ? `<button class="btn-outline" id="saveSuggestionBtn">收藏妝容對比圖</button>` : ''}
                </div>
                <div class="suggestion-render-quota" id="suggestionRenderQuota"></div>
                <div class="suggestion-render-status" id="suggestionRenderStatus" style="display:none;"></div>
            </div>
            <div class="suggestion-footer-actions">
                <button class="btn-outline" onclick="Router.go('compare')">查看前後對比</button>
                <button class="btn-gold" onclick="openProductRecommendationModal()">查看推薦商品 →</button>
            </div>
        `;
        Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
        Router.pendingLookSaved = false;
        // 收藏鍵只有在建議已經產生時才存在（Step 1 還沒跑就沒有東西可收藏）。
        const saveBtn = document.getElementById('saveSuggestionBtn');
        if (saveBtn) saveBtn.onclick = openSaveLookModal;

        // Step 1：就地產生 Ollama 建議，不換頁——換走的話使用者就看不到自己在哪一步了。
        const genBtn = document.getElementById('genSuggestionBtn');
        const stateEl = document.getElementById('suggestionState');
        genBtn.onclick = async () => {
            const original = genBtn.textContent;
            genBtn.disabled = true;
            genBtn.textContent = '產生建議中...';
            try {
                const result = await runMakeupSuggestion((pct, text) => {
                    if (stateEl) stateEl.textContent = `${text} ${pct}%`;
                });
                const failure = handleSuggestionFailure(result);
                if (failure === 'failed' && stateEl) stateEl.textContent = 'FAILED';
                if (failure) return;
                showToast('妝容建議已產生');
                PageInit.suggestion();   // 重畫：Step 1 轉成 DONE，Step 2 跟著解鎖
            } finally {
                genBtn.disabled = false;
                genBtn.textContent = original;
            }
        };

        // 妝前／妝後切換。圖片來源與妝容對比圖頁同一組，但這裡是單純的按鈕點擊切換
        // ——對比圖頁那個是「按住看另一張」，在這一頁沒有照片並排，按住看不出所以然。
        // 沒有妝後圖時按鈕停用，切過去只會是空白。
        const stage = document.getElementById('suggestionStage');
        const photoLabel = document.getElementById('suggestionPhotoLabel');
        const photoTitle = document.getElementById('suggestionPhotoTitle');
        const photoNote = document.getElementById('suggestionPhotoNote');
        const toggleBtn = document.getElementById('suggestionToggleBtn');
        const renderBtn = document.getElementById('suggestionRenderBtn');
        const renderStatus = document.getElementById('suggestionRenderStatus');
        const quotaEl = document.getElementById('suggestionRenderQuota');

        const photoSources = () => {
            // 看歷史收藏時用那一筆的圖。混用會顯示成別人的妝前配自己的妝後。
            if (viewLook) {
                return {
                    before: lookImageSrc(viewLook.beforeImage) || '',
                    after: lookImageSrc(viewLook.renderedImage) || '',
                };
            }
            const p = Router.analysisPackage || {};
            const rd = p.render || {};
            const mo = rd.makeupOutput || {};
            return {
                before: p.images?.front?.compressedDataUrl || rd.beforeImageUrl || rd.beforeImageDataUrl || '',
                after: rd.afterImageUrl || rd.afterImageDataUrl || mo.imageUrl || mo.imageDataUrl || ''
            };
        };
        let photoView = photoSources().after ? 'after' : 'before';
        const paintPhoto = () => {
            const imgs = photoSources();
            const isAfter = photoView === 'after';
            const showing = isAfter ? imgs.after : imgs.before;
            // 跟妝容對比圖頁同一套：圖片走 background-image，沒有圖時讓 class 的漸層底露出來。
            stage.classList.toggle('after', isAfter);
            stage.classList.toggle('before', !isAfter);
            stage.classList.toggle('has-render', !!showing);
            if (showing) {
                stage.style.backgroundImage = `url("${showing}")`;
                stage.style.backgroundSize = 'contain';
                stage.style.backgroundPosition = 'center';
                stage.style.backgroundRepeat = 'no-repeat';
            } else {
                stage.style.backgroundImage = '';
                stage.style.backgroundSize = '';
                stage.style.backgroundPosition = '';
                stage.style.backgroundRepeat = '';
            }
            photoLabel.textContent = isAfter ? '妝後' : '妝前';
            photoTitle.textContent = `${style.name} ${isAfter ? '渲染後妝容照片' : '原始照片'}`;
            photoNote.textContent = isAfter
                ? '這張照片來自目前分析資料包的妝容結果。'
                : (imgs.before ? '這是你這次臉部分析使用的原始照片。' : '尚未取得照片。');
            toggleBtn.disabled = !imgs.after;
            toggleBtn.textContent = isAfter ? '看妝前' : '看妝後';
        };
        toggleBtn.onclick = () => { photoView = photoView === 'after' ? 'before' : 'after'; paintPhoto(); };
        paintPhoto();

        quotaEl.textContent = renderQuotaText();

        // 生成妝容：沒有這顆按鈕，使用者拿到文字建議後就沒有下一步，流程在這裡斷掉。
        renderBtn.onclick = async () => {
            const originalText = renderBtn.textContent;
            renderBtn.disabled = true;
            renderBtn.textContent = '渲染中...';
            renderStatus.style.display = 'block';
            renderStatus.innerHTML = `
                <div class="srs-line">AI 正在上妝… <span id="suggestionRenderPct">1%</span></div>
                <div class="srs-track"><div class="srs-bar" id="suggestionRenderBar"></div></div>
                <div class="srs-hint">生成中，約需 60–150 秒，請不要關閉頁面</div>`;
            const barEl = document.getElementById('suggestionRenderBar');
            const pctEl = document.getElementById('suggestionRenderPct');
            // 後端每 2 秒才回一次進度，直接套上去會一格一格跳；每 40ms 推進 1，只准往前。
            let shown = 1, target = 1;
            const tick = setInterval(() => {
                if (shown >= target) return;
                shown = Math.min(target, shown + 1);
                if (barEl) barEl.style.width = shown + '%';
                if (pctEl) pctEl.textContent = shown + '%';
            }, 40);
            try {
                const outcome = await runMakeupRender(p => { target = Math.max(target, p); });
                if (!outcome.ok && handleRenderBlocked(outcome.reason)) { renderStatus.style.display = 'none'; return; }
                if (!outcome.ok) {
                    renderStatus.textContent = '渲染失敗：' + outcome.error.message;
                    showAlert('妝容生成失敗：' + outcome.error.message, { type: 'error' });
                    return;
                }
                target = 100;
                await new Promise(resolve => setTimeout(resolve, 800));
                // 渲染端會回這次實際用的 prompt 來源。'style_allowlist' 代表建議服務沒接上、
                // 用的是 styleId 的固定句子——妝會比較泛用。不講的話使用者只會覺得
                // 「怎麼跟我選的風格沒關係」，而且沒有任何線索。
                showToast(outcome.result?.promptSource === 'style_allowlist'
                    ? '妝容渲染完成（本次使用通用指令，未取得個人化建議）'
                    : '妝容渲染完成');
                // 重畫整頁再捲到成果圖。收藏鍵與「重新生成妝容」是建樣板當下依
                // renderedImage 決定要不要輸出的，只換照片的話它們要等下次進頁才出現——
                // 使用者剛渲染完，最想按的那顆卻不在。
                PageInit.suggestion();
                document.getElementById('suggestionStage')
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } finally {
                clearInterval(tick);
                renderBtn.disabled = false;
                renderBtn.textContent = originalText;
            }
        };

    },

    history() {
        const records = History.list();
        const area = document.getElementById('historyArea');
        if (!records.length) { area.innerHTML = '<div class="empty-state">尚無分析紀錄</div>'; return; }
        area.innerHTML = '<div class="hist-list">' + records.map((r, i) => `
            <div class="hist-item reveal-in" style="animation-delay:${Math.min(i*0.04,0.4)}s">
                <div class="hist-no">${String(i+1).padStart(2,'0')}</div>
                <div class="hist-body">
                    <div class="hist-traits">
                        <span><em>臉型</em>${escapeHtml(r['臉型']||'—')}</span>
                        <span><em>眉型</em>${escapeHtml(r['眉型']||'—')}</span>
                        <span><em>眼型</em>${escapeHtml(r['眼型']||'—')}</span>
                        <span><em>鼻型</em>${escapeHtml(r['鼻型']||'—')}</span>
                        ${r['側臉鼻型'] ? `<span><em>側臉鼻型</em>${escapeHtml(r['側臉鼻型'])}</span>` : ''}
                        <span><em>嘴型</em>${escapeHtml(r['嘴型']||'—')}</span>
                        <span><em>膚色</em>${escapeHtml([r['膚色分級'], r['四季型']].filter(Boolean).join(' / ') || '—')}</span>
                    </div>
                    <div class="hist-date">${r.mode ? escapeHtml(String(r.mode).toUpperCase()) : ''}</div>
                </div>
            </div>
        `).join('') + '</div>';
    },

    profile() {
        const user = getMemberDisplayName();
        const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
        if (typeof ProSubscription !== 'undefined' && profile?.email) ProSubscription.syncExpiry(profile.email);
        document.getElementById('profileName').textContent = user || '訪客';
        const roleEl = document.getElementById('profileRole');
        if (roleEl) roleEl.textContent = getCurrentRoleLabel(profile);
        // 大頭貼：有上傳照片就顯示，否則用名字首字（訪客用 ✦）
        var __av = document.getElementById('profileAvatar');
        if (__av) {
            var __p = profile;
            // 大頭貼網址與名稱都可能是會員自訂內容：網址只接受 http(s)／data:image，
            // 名稱進 alt 屬性一律轉義，避免用 " 跳脫屬性後注入 onerror 之類的事件。
            var __avatarSrc = lookImageSrc(__p.avatar);
            const __edit = '<span class="ma-edit" aria-hidden="true">更換</span>';
            if (__avatarSrc) { __av.classList.add('has-photo'); __av.innerHTML = '<img src="' + __avatarSrc + '" alt="' + escapeHtml(user || '會員') + '">' + __edit; }
            else { __av.classList.remove('has-photo'); __av.innerHTML = escapeHtml((user && user !== '訪客') ? user.trim().charAt(0).toUpperCase() : '✦') + __edit; }
            // 換頭貼。訪客沒有 email，改了也沒有地方存，所以直接關掉入口——
            // 讓它看起來能按、按了才說不行，是多繞一圈才給同一個答案。
            const __avInput = document.getElementById('profileAvatarInput');
            const __canEdit = !!profile.email;
            __av.disabled = !__canEdit;
            __av.classList.toggle('is-readonly', !__canEdit);
            if (__canEdit && __avInput) {
                __av.onclick = () => { __avInput.value = ''; __avInput.click(); };
                __avInput.onchange = (ev) => {
                    const f = ev.target.files && ev.target.files[0];
                    if (f) changeProfileAvatar(f);
                };
            }
        }
        const tierCard = document.getElementById('profileTierCard');
        if (tierCard) {
            const isVip = AdminStore.isVip(profile);
            const isAdminUser = AdminStore.isAdminProfile(profile);
            const permission = profile?.email ? AdminStore.getPermission(profile.email, profile) : null;
            const pending = !!permission?.vipRequested && !isVip;
            const remaining = AdminStore.getRemainingRenders(profile);
            const dailyLimit = AdminStore.getDailyRenderLimit(profile);
            const resetAt = profile?.renderQuota?.resetAt;
            const renderQuotaLine = remaining === Infinity || dailyLimit === Infinity
                ? 'AI 妝容渲染：無限次'
                : (remaining != null && dailyLimit != null && resetAt
                    ? `AI 妝容渲染：每日 ${dailyLimit} 次（今天還剩 ${remaining} 次）`
                    : 'AI 妝容渲染：依你的會員方案提供每日次數');
            const tier = (typeof MemberTier !== 'undefined') ? MemberTier.describe(profile) : { name: isVip ? 'PRO / VIP 會員' : '一般會員', autoTier: false };
            const nextTier = tier.autoTier ? MemberTier.nextTier(tier.lifetime) : null;
            const tierProgressLine = nextTier
                ? `<li>距離「${nextTier.name}」還差 ${nextTier.min - tier.lifetime} 點累計點數</li>`
                : (tier.autoTier ? `<li>已達目前等級制度的最高等級</li>` : '');
            tierCard.innerHTML = `
                <div class="tier-card">
                    <div>
                    <span class="tier-badge ${isVip ? 'vip' : 'general'}">${tier.name}</span>
                    <ul class="tier-benefits">
                        <li>BASIC 臉部分析</li>
                        <li>${isVip ? 'PRO 臉部分析（已開通）' : 'PRO 臉部分析（升級 VIP 解鎖）'}</li>
                        <li>${renderQuotaLine}</li>
                        ${tierProgressLine}
                    </ul>
                    ${pending ? `<div class="tier-pending">你的 VIP 升級申請審核中</div>` : ''}
                    </div>
                </div>
            `;
        }
        // ── 統計卡導覽：兩張換頁、兩張捲到本頁下方 ──
        // 捲動後把目標區塊高亮一下，否則使用者只看到畫面動了，不知道該看哪裡。
        document.querySelectorAll('.member-stats [data-goto]').forEach(btn => {
            btn.onclick = () => Router.go(btn.dataset.goto);
        });
        // 分頁切換。用 hidden 而不是 display:none，因為 hidden 也把內容從
        // 無障礙樹與 Tab 順序裡拿掉——只是視覺上藏起來的話，鍵盤還是會走進
        // 看不見的按鈕裡。
        const showMemberTab = (key) => {
            document.querySelectorAll('.member-tab').forEach(t => {
                const on = t.dataset.mtab === key;
                t.classList.toggle('is-active', on);
                t.setAttribute('aria-selected', on ? 'true' : 'false');
            });
            document.querySelectorAll('.member-panel').forEach(pl => {
                pl.hidden = pl.dataset.mpanel !== key;
            });
        };
        document.querySelectorAll('.member-tab').forEach(t => {
            t.onclick = () => showMemberTab(t.dataset.mtab);
        });

        document.querySelectorAll('.member-stats [data-scroll]').forEach(btn => {
            btn.onclick = () => {
                const target = document.getElementById(btn.dataset.scroll);
                if (!target) return;
                // 目標可能在沒開啟的分頁裡。先切過去再捲——否則捲到一個
                // hidden 的元素上，畫面完全沒有反應，而按鈕看起來壞了。
                const panel = target.closest('.member-panel');
                if (panel && panel.hidden) showMemberTab(panel.dataset.mpanel);
                const section = target.closest('section') || target;
                section.scrollIntoView({ behavior: 'smooth', block: 'start' });
                section.classList.remove('section-flash');
                void section.offsetWidth;          // 重新觸發動畫，連按兩次也看得到
                section.classList.add('section-flash');
            };
        });

        const favEl = document.getElementById('profileFavCount');
        const anEl = document.getElementById('profileAnalyzeCount');
        const suggestionEl = document.getElementById('profileSuggestionCount');
        const pointEl = document.getElementById('profilePointCount');
        const suggestions = (() => {
            try { return JSON.parse(localStorage.getItem(looksKey()) || '[]'); } catch (_) { return []; }
        })();
        // 收藏數要跟收藏頁「實際畫得出來的件數」一致，所以數的是 resolveFavoriteProducts()
        // 解析後的結果，不是 Fav.list()（本機存了幾個 id）。差額是已下架或 id 被重編號的
        // 商品，收藏頁把它們另外用一行說明交代，這裡就不該再把它們算進主要數字。
        const paintFavCount = () => {
            if (favEl) favEl.textContent = resolveFavoriteProducts().items.length;
        };
        if (favEl) { paintFavCount(); favEl.classList.add('num-pop'); }
        // 商品目錄還沒載進來時，能對上的件數會偏少，載完要重畫一次。
        if (favEl && !productCatalogLoaded() && !Router.generalProductLoading) {
            loadGeneralProductCatalog(() => { if (Router.currentPage === 'profile') paintFavCount(); });
        }
        // 只讀本機 Fav 清單，換裝置或本次 session 還沒同步時會顯示 0 或過時數字，
        // 跟收藏頁對不上。主動同步一次遠端收藏，回來後把數字更新成跟收藏頁一致。
        if (favEl && !isGuest()) {
            syncRemoteFavorites().then(() => {
                if (Router.currentPage === 'profile') paintFavCount();
            });
        }
        if (anEl) { anEl.textContent = History.list().length; anEl.classList.add('num-pop'); anEl.style.animationDelay='.1s'; }
        if (suggestionEl) { suggestionEl.textContent = suggestions.length; suggestionEl.classList.add('num-pop'); suggestionEl.style.animationDelay='.16s'; }
        if (pointEl) { pointEl.textContent = MemberRewards.getPoints(profile.email); pointEl.classList.add('num-pop'); pointEl.style.animationDelay='.2s'; }
        // 先顯示本機點數；遠端失敗時標示為「本機」，避免誤認為已同步。
        const pointLabelEl = pointEl ? pointEl.parentElement?.querySelector('.stat-label') : null;
        const markPointsUnsynced = () => { if (pointLabelEl) pointLabelEl.textContent = '會員點數（本機）'; };
        if (pointEl && !isGuest() && profile.email && Api.getMemberPoints) {
            Api.getMemberPoints(profile.email).then(r => {
                if (!r || !r.ok || r.balance == null) { markPointsUnsynced(); return; }
                pointEl.textContent = r.balance;
                if (r.lifetime != null && typeof MemberRewards !== 'undefined') {
                    // 讓會員等級進度也能吃到資料庫的 lifetime；保留 localStorage 只是為了既有 MemberTier 介面。
                    const all = MemberRewards._load(MemberRewards._lifetimeKey, {});
                    all[String(profile.email).trim().toLowerCase()] = Number(r.lifetime) || 0;
                    MemberRewards._save(MemberRewards._lifetimeKey, all);
                }
            }).catch(() => { markPointsUnsynced(); });
        }

        const checkinCard = document.getElementById('profileCheckinCard');
        if (checkinCard) {
            // 打卡失敗要講清楚是哪一種失敗，使用者才知道該重新登入還是回報給我們。
            const checkinFailureMessage = (result) => {
                if (!result) return '打卡失敗：連不上會員資料庫，請稍後再試。';
                if (result.status === 401) return '打卡失敗：登入狀態已失效，請重新登入後再打卡。';
                if (result.status === 404) return '打卡失敗：會員資料庫尚未提供打卡功能，這一次沒有記錄到。已回報給資料庫端。';
                return `打卡失敗：${result.error || '會員資料庫沒有接受這次打卡'}，這一次沒有記錄到。`;
            };
            // source: 'remote' = 讀到資料庫紀錄；'unknown' = 還沒讀到（載入中或讀取失敗）。
            // 不再有 'local' 這個狀態——本機 localStorage 不是點數的真相來源。
            const paintCheckin = (status, source) => {
                const nextMilestone = MemberRewards.nextStreakMilestone(Number(status.streak) || 0);
                const streakLine = (Number(status.streak) || 0) > 0
                    ? `目前連續簽到 <b>${Number(status.streak) || 0}</b> 天${nextMilestone ? `，再簽 ${nextMilestone - (Number(status.streak) || 0)} 天可拿額外 ${MemberRewards._streakBonusTable[nextMilestone]} 點` : '，已達最高獎勵天數'}`
                    : '今天開始簽到就能累積連續天數';
                checkinCard.innerHTML = `<div class="member-action-card">
                    <div>
                        <b>${status.checkedToday ? '今天已完成打卡' : '今天還沒打卡'}</b>
                        <p>每日打卡可獲得 10 點；連續簽到 3 / 7 / 14 / 30 天另有加碼獎勵。</p>
                        <p class="checkin-streak">${streakLine}</p>
                    </div>
                    <button class="btn-gold btn-sm" id="dailyCheckinBtn" ${status.checkedToday || isGuest() ? 'disabled' : ''}>${status.checkedToday ? '已打卡' : '打卡 +10'}</button>
                </div>`;
                const btn = document.getElementById('dailyCheckinBtn');
                if (btn) btn.onclick = async () => {
                    btn.disabled = true;
                    // 打卡必須成功寫入會員資料庫，失敗時不使用本機點數假裝成功。
                    const remoteResult = (!isGuest() && Api.checkInMember)
                        ? await Api.checkInMember(profile.email).catch(() => null)
                        : null;
                    if (remoteResult?.ok) {
                        const gained = remoteResult.awarded ?? remoteResult.points ?? 0;
                        // 只鏡射「今天打過卡」這個事實，點數由伺服器算。任務中心的
                        // daily_checkin 判定讀的是這份本機紀錄，不寫的話那個任務永遠不會完成。
                        MemberRewards.recordRemoteCheckin(profile.email, remoteResult.streak);
                        showToast(`打卡成功，獲得 ${gained} 點`);
                        PageInit.profile();
                        return;
                    }
                    // 按鈕不停用：資料庫端修好之後，不必重新整理就能直接再試一次。
                    btn.disabled = false;
                    showAlert(checkinFailureMessage(remoteResult), { type: 'error' });
                };
            };
            // 初始顯示未打卡，等資料庫回覆後再更新狀態。
            paintCheckin({ checkedToday: false, streak: 0 }, 'unknown');
            if (!isGuest() && profile.email && Api.getCheckinStatus) {
                Api.getCheckinStatus(profile.email).then(r => {
                    if (!r || !r.ok) return;
                    paintCheckin({
                        checkedToday: !!r.checkedToday,
                        streak: Number(r.streak) || 0
                    }, 'remote');
                }).catch(() => {});
            }
        }

        const taskCenter = document.getElementById('profileTaskCenter');
        if (taskCenter) {
            if (isGuest() || typeof Tasks === 'undefined') {
                taskCenter.innerHTML = '<div class="empty-state compact">登入會員後即可查看任務中心</div>';
            } else {
                // 本機任務狀態會先畫一次，資料庫的狀態晚一步覆蓋。中間那段空窗期如果按得下去，
                // 走的是 Tasks.claim() 的 localStorage 路徑：點數加在瀏覽器裡、toast 說領取成功，
                // 然後遠端資料一到就把畫面蓋回去，看起來就是「點了沒加上去」。
                // pending 為真時整批按鈕先鎖住，等資料庫回應再開。
                const paintTasks = (tasks, remote, pending) => {
                    const normalized = tasks.map(t => {
                        const id = t.id || t.taskId;
                        const meta = taskMeta(id);
                        return {
                            id,
                            // 後端沒給中文名稱時用本機定義，避免畫面出現 first_analysis 這種代碼
                            group: t.group || meta.group || (t.daily ? '每日任務' : '任務'),
                            title: t.title || t.name || meta.title,
                            reward: t.reward ?? 0,
                            done: t.done !== false,
                            // 資料庫端的「已領取」欄位名稱不保證是 claimed；認不出來就會一直
                            // 顯示「領取獎勵」，按下去換來 409「這個獎勵已經領取過了」。
                            // 常見幾種寫法都接受，避免卡在按鈕文字不會變。
                            // 用 || 不用 ??：後端如果同時給了 claimed:false 和 claimed_at，
                            // ?? 會停在 false 而看不到後面那個真正的證據。
                            claimed: !!(t.claimed || t.is_claimed || t.claimedAt || t.claimed_at
                                || (typeof t.status === 'string' && t.status.toLowerCase() === 'claimed'))
                        };
                    }).filter(t => t.id);
                    const groups = [...new Set(normalized.map(t => t.group))];
                    taskCenter.innerHTML = groups.map(group => `
                        <div class="task-group">
                            <h4>${escapeHtml(group)}${remote ? ' <span style="font-size:12px;color:#7A4A42;">DB</span>' : ''}</h4>
                            ${normalized.filter(t => t.group === group).map(t => `
                                <div class="member-action-card task-row">
                                    <div>
                                        <b>${escapeHtml(t.title)}</b>
                                        <p>獎勵 ${t.reward} 點</p>
                                    </div>
                                    <button class="btn-gold btn-sm" data-task-id="${escapeHtml(t.id)}" data-task-remote="${remote ? '1' : '0'}" ${(pending || !t.done || t.claimed) ? 'disabled' : ''}>${t.claimed ? '已領取' : (pending ? '讀取中…' : (t.done ? '領取獎勵' : '尚未完成'))}</button>
                                </div>
                            `).join('')}
                        </div>
                    `).join('');
                    taskCenter.querySelectorAll('[data-task-id]').forEach(btn => {
                        btn.onclick = async () => {
                            btn.disabled = true;
                            if (btn.dataset.taskRemote === '1' && Api.claimMemberTask) {
                                const result = await Api.claimMemberTask(profile.email, btn.dataset.taskId).catch(() => null);
                                if (!result?.ok) {
                                    showAlert(result?.error || '任務領取失敗。', { type: 'error' });
                                    // 409 代表伺服器上已經是「已領取」，畫面卻還顯示可領——
                                    // 重畫一次讓兩邊一致，否則使用者會一直按同一顆按鈕。
                                    if (result?.status === 409) { PageInit.profile(); return; }
                                    btn.disabled = false;
                                    return;
                                }
                                showToast(`任務完成，獲得 ${result.awarded ?? result.reward ?? 0} 點`);
                                PageInit.profile();
                                return;
                            }
                            const result = Tasks.claim(profile.email, btn.dataset.taskId);
                            if (!result.ok) { showAlert(result.message || '尚未完成這個任務。', { type: 'error' }); btn.disabled = false; return; }
                            showToast(`任務完成，獲得 ${result.reward} 點`);
                            PageInit.profile();
                        };
                    });
                };
                const tasksComingFromDatabase = !!(profile.email && Api.listMemberTasks);
                paintTasks(Tasks.status(profile.email), false, tasksComingFromDatabase);
                if (tasksComingFromDatabase) {
                    Api.listMemberTasks(profile.email).then(r => {
                        // 資料庫沒回任務時解鎖本機清單，否則按鈕會永遠停在「讀取中…」。
                        if (!r || !r.ok || !r.tasks.length) return paintTasks(Tasks.status(profile.email), false, false);
                        paintTasks(r.tasks, true, false);
                    }).catch(() => paintTasks(Tasks.status(profile.email), false, false));
                }
            }
        }

        const referralCard = document.getElementById('profileReferralCard');
        if (referralCard) {
            if (isGuest() || typeof Referral === 'undefined') {
                referralCard.innerHTML = '<div class="empty-state compact">登入會員後即可產生你的專屬推薦碼</div>';
            } else {
                const code = Referral.myCode(profile.email);
                const count = Referral.countReferrals(profile.email);
                referralCard.innerHTML = `<div class="member-action-card">
                    <div>
                        <b>你的推薦碼：<span id="myReferralCode">${escapeHtml(code)}</span></b>
                        <p>朋友註冊時填入這組碼，驗證完成後你會獲得 ${Referral._rewardPoints} 點；已成功推薦 ${count} 人。</p>
                    </div>
                    <button class="btn-outline btn-sm" id="copyReferralBtn">複製推薦碼</button>
                </div>`;
                const copyBtn = document.getElementById('copyReferralBtn');
                if (copyBtn) copyBtn.onclick = () => {
                    navigator.clipboard?.writeText(code).then(() => showToast('推薦碼已複製')).catch(() => showToast('複製失敗，請手動選取'));
                };
            }
        }

        const themeShop = document.getElementById('profileThemeShop');
        if (themeShop) {
            const activeTheme = MemberRewards.getActiveTheme(profile.email);
            themeShop.innerHTML = `<div class="theme-shop-grid">${MemberRewards.themes.map(theme => {
                const owned = MemberRewards.hasTheme(profile.email, theme.id);
                const active = activeTheme === theme.id;
                return `<article class="theme-card ${active ? 'active' : ''}">
                    <div class="theme-swatches">${theme.swatches.map(c => `<span style="background:${escapeHtml(c)}"></span>`).join('')}</div>
                    <h3>${escapeHtml(theme.name)}</h3>
                    <p>${escapeHtml(theme.desc)}</p>
                    <div class="theme-card-foot">
                        <b>${theme.cost ? `${theme.cost} 點` : '免費'}</b>
                        <span class="theme-card-btns">
                            <button class="btn-outline btn-sm theme-peek" type="button" data-theme-peek="${escapeHtml(theme.id)}"
                                    aria-label="按住預覽${escapeHtml(theme.name)}">按住預覽</button>
                            <button class="${owned ? 'btn-outline' : 'btn-gold'} btn-sm" data-theme-action="${owned ? 'apply' : 'redeem'}" data-theme-id="${escapeHtml(theme.id)}" ${active ? 'disabled' : ''}>${active ? '使用中' : (owned ? '套用' : '兌換')}</button>
                        </span>
                    </div>
                </article>`;
            }).join('')}</div>`;
            // ── 按住預覽：只改 body 的 data-memberTheme，放開就還原 ──
            //
            // 主題的套用機制就是 document.body.dataset.memberTheme（見 MemberRewards.applyActiveTheme），
            // 所以預覽不需要碰點數、不寫 localStorage、也不呼叫任何 API——
            // 純粹是視覺上的暫時替換，放開手就回到目前真正在用的那個。
            //
            // 還原對象存在變數而不是每次重讀：預覽期間如果有別的程式改了 dataset，
            // 重讀會把「預覽中的值」當成原值還原，主題就永久變成預覽的那個了。
            const restoreTheme = () => {
                document.body.dataset.memberTheme = activeTheme || '';
                themeShop.querySelectorAll('.theme-peek.peeking').forEach(b => b.classList.remove('peeking'));
            };
            themeShop.querySelectorAll('[data-theme-peek]').forEach(btn => {
                const start = (e) => {
                    if (e?.preventDefault) e.preventDefault();
                    document.body.dataset.memberTheme = btn.dataset.themePeek;
                    btn.classList.add('peeking');
                };
                btn.style.touchAction = 'none';      // 手機上按住不要變成捲動
                btn.onpointerdown = start;
                btn.onpointerup = restoreTheme;
                btn.onpointerleave = restoreTheme;
                btn.onpointercancel = restoreTheme;
                btn.onblur = restoreTheme;           // Tab 離開也要還原
                btn.oncontextmenu = (e) => e.preventDefault();   // 長按不要跳出選單
                // 鍵盤：Enter/空白鍵按著預覽，放開還原
                btn.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') start(e); };
                btn.onkeyup = (e) => { if (e.key === 'Enter' || e.key === ' ') restoreTheme(); };
            });
            // 離開會員頁時一定要還原，否則預覽中換頁會把預覽主題留在畫面上。
            window.addEventListener('hashchange', restoreTheme, { once: true });

            themeShop.querySelectorAll('[data-theme-id]').forEach(btn => {
                btn.onclick = async () => {
                    const id = btn.dataset.themeId;
                    if (btn.dataset.themeAction === 'redeem') {
                        btn.disabled = true;
                        if (!isGuest() && Api.redeemMemberTheme) {
                            const remote = await Api.redeemMemberTheme(profile.email, id).catch(() => null);
                            if (remote?.ok) {
                                // 先把伺服器端的解鎖同步到本機，setActiveTheme 才會通過 hasTheme 檢查。
                                // 少了這行會變成「點數扣了、主題套不上」，而且畫面還是報成功。
                                MemberRewards.unlockTheme(profile.email, id);
                                const applied = MemberRewards.setActiveTheme(profile.email, id);
                                // alreadyOwned 表示伺服器已兌換，只需補回本機解鎖狀態。
                                showToast(
                                    !applied ? '套用失敗，請重新整理後再試一次'
                                    : remote.alreadyOwned ? '你已擁有這個主題，已為你套用（未重複扣點）'
                                    : '已兌換並套用主題'
                                );
                                PageInit.profile();
                                return;
                            }
                            if (remote?.error) {
                                showAlert(remote.error, { type:'error' });
                                btn.disabled = false;
                                return;
                            }
                        }
                        const result = MemberRewards.redeemTheme(profile.email, id);
                        if (!result.ok) { showAlert(result.message, { type:'error' }); btn.disabled = false; return; }
                        const applied = MemberRewards.setActiveTheme(profile.email, id);
                        showToast(applied ? '已兌換並套用主題' : '已兌換，但套用失敗，請重新整理後再套用一次');
                    } else {
                        // 套用既有主題也可能失敗（例如本機解鎖紀錄遺失），不要一律報成功
                        const applied = MemberRewards.setActiveTheme(profile.email, id);
                        if (!applied) { showAlert('這個主題尚未解鎖，請先兌換。', { type:'error' }); btn.disabled = false; return; }
                        showToast('已套用主題');
                    }
                    PageInit.profile();
                };
            });
        }

        const ledgerEl = document.getElementById('profilePointLedger');
        if (ledgerEl) {
            const paintLedger = (rows) => {
                ledgerEl.innerHTML = rows.length ? `<div class="point-ledger">${rows.slice(0, 8).map(row => {
                    const createdAt = row.created_at || row.createdAt || row.time || row.timestamp;
                    return `<div>
                        <span>${escapeHtml(pointReasonLabel(row.reason || row.description))}</span>

                        <b class="${Number(row.delta) >= 0 ? 'plus' : 'minus'}">${Number(row.delta) >= 0 ? '+' : ''}${Number(row.delta) || 0}</b>
                    </div>`;
                }).join('')}</div>` : '<div class="empty-state compact">尚無點數紀錄</div>';
            };
            paintLedger(MemberRewards.ledger(profile.email));
            if (!isGuest() && profile.email && Api.getMemberPoints) {
                Api.getMemberPoints(profile.email).then(r => {
                    if (!r || !r.ok || !Array.isArray(r.transactions)) return;
                    paintLedger(r.transactions);
                }).catch(() => {});
            }
        }
        const paintSavedLooks = (list) => {
            const area = document.getElementById('profileSuggestionArea');
            const countEl = document.getElementById('profileSuggestionCount');
            if (countEl) countEl.textContent = list.length;
            if (!area) return;
            if (!list.length) {
                area.innerHTML = '<div class="empty-state compact">尚未收藏妝容對比圖</div>';
                return;
            }
            area.innerHTML = `<div class="saved-look-grid">${list.map((item, index) => {
                const imageSrc = lookImageSrc(item.renderedImage);
                const styleLabel = escapeHtml(item.style || '妝容對比圖');
                const summary = escapeHtml(formatSavedAdvice(item));

                const expired = String(item.renderedImage || '').includes('replicate.delivery')
                    ? '<span class="saved-look-expire">此圖為舊版臨時網址，可能已失效</span>' : '';
                return `
                <article class="saved-look-card reveal-in" data-look="${index}" style="animation-delay:${Math.min(index * 0.04, 0.24)}s">
                    <button class="look-del" data-del="${index}" aria-label="刪除此妝容">×</button>
                    <div class="saved-look-photo">
                        ${imageSrc
                            ? `<img src="${imageSrc}" alt="${styleLabel}" onload="this.classList.add('loaded')" onerror="markLookImageUnavailable(this)">${expired}`
                            : `<span>${styleLabel}</span>`
                        }
                    </div>
                    <div class="saved-look-body">
                        <div class="saved-look-kicker">${item.remoteId != null ? 'Saved Look · DB' : 'Saved Look · 本機快取'}</div>
                        <h3>${styleLabel}</h3>
                        <p>${summary}</p>

                    </div>
                </article>`;
            }).join('')}</div>`;
            area.querySelectorAll('.saved-look-card[data-look]').forEach(function(card){ card.style.cursor='pointer'; card.onclick=function(){ openLookModal(list[+card.dataset.look]); }; });
            area.querySelectorAll('.look-del[data-del]').forEach(function(btn){
                btn.onclick = function(e){
                    e.stopPropagation();
                    var idx = +btn.dataset.del;
                    showConfirm("確定要刪除這個收藏的妝容嗎？此動作無法復原。", {
                        title: "刪除妝容對比圖", type: "error", okText: "刪除", cancelText: "保留",
                        onOk: function(){
                            var recs = []; try { recs = JSON.parse(localStorage.getItem(looksKey()) || "[]"); } catch(_){}
                            var removed = recs[idx];
                            // 已同步的收藏先刪資料庫，成功後才刪本機快取，避免兩邊狀態不一致
                            var em = (typeof Auth !== 'undefined' && Auth.getProfile()) ? Auth.getProfile().email : null;
                            var deleteRemote = (em && removed && removed.remoteId != null && Api.deleteSavedLook)
                                ? Api.deleteSavedLook(em, removed.remoteId)
                                : Promise.resolve({ ok: true });
                            deleteRemote.then(function(result){
                                if (!result || !result.ok) {
                                    showAlert("資料庫刪除失敗，本機收藏尚未刪除。請確認登入狀態與會員資料庫連線後再試。", { type: "error" });
                                    return;
                                }
                                recs.splice(idx, 1);
                                localStorage.setItem(looksKey(), JSON.stringify(recs));
                                showToast(removed && removed.remoteId != null ? "妝容已從資料庫與本機刪除" : "已刪除本機收藏（此筆尚未同步資料庫）");
                                paintSavedLooks(recs);
                            }).catch(function(){
                                showAlert("資料庫刪除失敗，本機收藏尚未刪除。請稍後再試。", { type: "error" });
                            });
                        }
                    });
                };
            });
        };
        paintSavedLooks(suggestions);
        document.querySelectorAll('#mainContent [data-nav]').forEach(el => el.onclick = () => Router.go(el.dataset.nav));
        // 背景從後端拉最新收藏（跨裝置）；成功就與本機未同步的收藏合併、覆蓋快取並重繪
        if (!isGuest()) {
            const __em = (typeof Auth !== 'undefined' && Auth.getProfile()) ? Auth.getProfile().email : null;
            if (__em) {
                Api.listSavedLooks(__em).then(r => {
                    if (!r || !r.ok) return;
                    const remote = r.looks.map(mapRemoteSavedLook);
                    let localAll = [];
                    try { localAll = JSON.parse(localStorage.getItem(looksKey()) || '[]'); } catch (_) {}
                    // 本機已同步的筆（有 remoteId）資訊較完整（含完整臉部分析與風格），優先保留，不被後端摘要版覆蓋
                    const localByRemote = {};
                    localAll.forEach(x => { if (x.remoteId != null) localByRemote[x.remoteId] = x; });
                    // DB 回傳的影像網址可能是剛更新的短效 Signed URL；保留本機補充欄位，
                    // 但影像與遠端狀態一律以資料庫最新值為準。
                    const fromRemote = remote.map(rm => (rm.remoteId != null && localByRemote[rm.remoteId])
                        ? { ...localByRemote[rm.remoteId], ...rm }
                        : rm);
                    const remoteIds = new Set(remote.map(rm => String(rm.remoteId)));
                    const localOnly = localAll.filter(x => x.remoteId == null || !remoteIds.has(String(x.remoteId)));
                    const merged = fromRemote.concat(localOnly).sort((a, b) => String(b.timestamp || '').localeCompare(String(a.timestamp || '')));
                    localStorage.setItem(looksKey(), JSON.stringify(merged.slice(0, 20)));
                    if (Router.currentPage === 'profile') paintSavedLooks(merged);
                });
            }
        }
        // 更改密碼：訪客隱藏
        var __cpBtn = document.getElementById("changePwdBtn");
        if (__cpBtn) {
            if (isGuest()) { __cpBtn.style.display = "none"; }
            else { __cpBtn.style.display = ""; __cpBtn.onclick = showChangePassword; }
        }

        function formatSavedAdvice(item) {
            const advice = item.advice || {};
            const text = advice.lip || advice.eye || advice.base || item.suggestion || '';
            return String(text || '已收藏此妝容對比圖，之後可回到會員中心查看完整搭配。').slice(0, 72);
        }
    },
    admin() {
        if (typeof AdminStore === 'undefined' || !AdminStore.isAdmin()) {
            Router.go('dashboard');
            return;
        }
        // 「這一區已經載過了」是**這一次進頁**的事，不是整個 session 的事。
        //
        // 每次進後台，pages/admin.html 都會重新抓、mainContent.innerHTML 整個換掉，
        // 所以 DOM 是全新的空表格。而 Router._feedbackLoaded 掛在 Router 上、跨頁面
        // 存活——離開後台再回來，旗標還是 true，於是 loadAdminFeedback 不會被呼叫：
        // 待覆核 0、送訓中 0、訓練批次「尚未載入」，看起來像資料整批消失。
        //
        // 第一次進去看起來正常，第二次才壞，所以特別難重現。
        Router._feedbackLoaded = false;
        Router._productAuditLoaded = false;

        const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
        const profileNameEl = document.getElementById('adminProfileName');
        const profileEmailEl = document.getElementById('adminProfileEmail');
        if (profileNameEl) profileNameEl.textContent = profile.name || '管理員';
        if (profileEmailEl) profileEmailEl.textContent = profile.email || '—';

        // ⚠️ 這張表是 setAdminSection 的白名單：`sectionMeta[section] ? section : 'overview'`。
        // 少列一個區塊，那顆按鈕就會安靜地把人踢回營運總覽，而且不會有任何錯誤訊息。
        // feedback 先前就是這樣——導覽上有「模型修正複核」，點下去卻永遠回到總覽，
        // 那個頁面等於做了但進不去。新增區塊時務必同步加進這裡。
        const sectionMeta = {
            overview: { eyebrow: 'ADMIN OVERVIEW', title: '營運總覽' },
            members: { eyebrow: 'MEMBER ACCESS', title: '會員與權限管理' },
            products: { eyebrow: 'PRODUCT CATALOG', title: '商品管理' },
            feedback: { eyebrow: 'MODEL CORRECTION REVIEW', title: '模型修正複核' }
        };
        const sectionButtons = Array.from(document.querySelectorAll('[data-admin-section]'));
        const sectionViews = Array.from(document.querySelectorAll('[data-admin-view]'));
        const setAdminSection = (section) => {
            const next = sectionMeta[section] ? section : 'overview';
            sectionButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.adminSection === next));
            sectionViews.forEach(view => {
                const active = view.dataset.adminView === next;
                view.classList.toggle('active', active);
                view.hidden = !active;
            });
            const meta = sectionMeta[next];
            const eyebrow = document.getElementById('adminSectionEyebrow');
            const title = document.getElementById('adminSectionTitle');
            if (eyebrow) eyebrow.textContent = meta.eyebrow;
            if (title) title.textContent = meta.title;
            try { sessionStorage.setItem('beautyAdminSection', next); } catch (_) {}
            // 切進來才載入，避免每次開後台都去打一次不一定會看的資料。
            if (next === 'feedback') Router._loadFeedbackOnce?.();
            if (next === 'products') Router._loadProductAuditOnce?.();
            document.querySelector('.admin-stage')?.scrollTo({ top: 0, behavior: 'smooth' });
        };
        let initialSection = 'overview';
        try { initialSection = sessionStorage.getItem('beautyAdminSection') || 'overview'; } catch (_) {}
        sectionButtons.forEach(btn => { btn.onclick = () => setAdminSection(btn.dataset.adminSection); });
        document.querySelectorAll('[data-admin-jump]').forEach(btn => { btn.onclick = () => setAdminSection(btn.dataset.adminJump); });
        setAdminSection(initialSection);

        let memberConnectionState = 'pending';
        let productConnectionState = 'pending';
        const updateOverallStatus = () => {
            const el = document.getElementById('adminOverallStatus');
            if (!el) return;
            const states = [memberConnectionState, productConnectionState];
            const failed = states.includes('error');
            const ready = states.every(state => state === 'ok');
            el.className = `admin-sync-status ${failed ? 'error' : (ready ? 'ok' : 'pending')}`;
            // 這一行是**後台**的服務狀態，管理員要靠它知道會員資料庫與商品服務都連得上。
            // 2026-08-28 一度把它改成「正常時不顯示」，那是把使用者端「拿掉資料庫同步字樣」
            // 的要求套錯了地方——那個要求指的是會員中心，不是這裡。
            // 對管理員來說「資料已同步」是有意義的：它回答「我現在看到的數字可不可信」。
            el.innerHTML = `<i></i>${failed ? '部分服務異常' : (ready ? '資料已同步' : '資料同步中')}`;
            if (ready) {
                const sync = document.getElementById('adminLastSync');
                if (sync) sync.textContent = `最近同步 ${new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`;
            }
        };
        const setConnectionStatus = (id, text, state) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.textContent = text;
            el.className = state;
        };
        const rowsEl = document.getElementById('adminUserRows');
        const searchEl = document.getElementById('adminSearch');
        const filters = document.querySelectorAll('[data-admin-filter]');
        const pageLabels = {
            analysisBasic: 'BASIC 分析',
            analysisPro: 'PRO 分析',
            unlimitedRender: '渲染不限次數',
            style: '風格試妝',
            products: '商品推薦',
            favorites: '收藏',
            history: '紀錄',
            compare: '對比圖',
            suggestion: '妝容建議'
        };
        let filter = 'all';

        // 優先讀取會員資料庫，失敗時使用本機示範資料並標示來源。
        let dbMembers = null;
        let dbMembersError = '';
        let dbMembersLoading = true;
        // 每位會員的妝容收藏（saved_looks）：undefined=還沒抓、null=抓失敗、陣列=實際收藏。用來在後台即時看資料庫寫入狀況
        const looksByEmail = {};
        const lookCountLabel = (email) => {
            const v = looksByEmail[email];
            if (v === undefined) return '…';
            if (v === null) return '—';
            return String(v.length);
        };
        // 每位會員的點數：undefined=還沒抓、null=抓失敗、物件={balance,earned}
        const pointsByEmail = {};
        const pointsLabel = (email) => {
            const v = pointsByEmail[email];
            if (v === undefined) return '…';
            if (v === null || v.balance == null) return '—';
            return String(v.balance);
        };
        const dbStatusEl = (() => {
            const toolbar = document.querySelector('.admin-toolbar');
            if (!toolbar) return null;
            let el = document.getElementById('adminDbStatus');
            if (!el) {
                el = document.createElement('span');
                el.id = 'adminDbStatus';
                el.style.cssText = 'font-size:12px;letter-spacing:.06em;margin-left:auto;margin-right:12px;';
                toolbar.insertBefore(el, document.getElementById('adminSaveBtn'));
            }
            return el;
        })();
        const setDbStatus = (text, ok) => {
            const loading = /載入中/.test(String(text));
            memberConnectionState = loading ? 'pending' : (ok ? 'ok' : 'error');
            if (dbStatusEl) {
                dbStatusEl.textContent = text;
                dbStatusEl.className = `admin-inline-status ${memberConnectionState}`;
            }
            setConnectionStatus('adminMemberConnection', loading ? '連線中' : (ok ? '正常' : '異常'), memberConnectionState);
            updateOverallStatus();
        };
        const ensureReloadBtn = (() => {
            let btn = document.getElementById('adminReloadBtn');
            if (!btn) {
                btn = document.createElement('button');
                btn.id = 'adminReloadBtn';
                btn.type = 'button';
                btn.className = 'btn-outline btn-sm';
                btn.textContent = '重新讀取';
                const save = document.getElementById('adminSaveBtn');
                if (save && save.parentNode) save.parentNode.insertBefore(btn, save);
            }
            return btn;
        })();
        const classifyMemberLoadError = (result) => {
            if (result?.status === 401 || result?.status === 403) {
                return '請重新登入 admin 帳號；若仍失敗，請確認會員 API 的 Bearer token／session 驗證';
            }
            if (/credentials|cors|failed to fetch|networkerror|load failed/i.test(String(result?.error || ''))) {
                return '請確認後端已回 Access-Control-Allow-Credentials，且 cookie 為 SameSite=None; Secure';
            }
            // 422 幾乎都是 members 表裡有 email 欄位不合格式的資料，讓上游的回應驗證整批擋下
            // （issue #31）。先前這種情況會落到最後那句「請確認 admin session、CORS 與 cookie」，
            // 把管理員導向完全錯誤的方向——session 和 CORS 都是好的，壞的是資料。
            if (result?.status === 422) {
                return '資料庫回 422：members 表裡有欄位格式不合法的資料（多半是 email），整批因此讀不出來。'
                     + '這不是登入或連線問題，請資料庫端清理該筆資料';
            }
            if (result && result.ok === false) {
                return '請確認 members API 有回合法 JSON，且 response body 內包含 members[]';
            }
            return '請確認 admin session、CORS 與 cookie 設定';
        };
        // 進頁面就先確認自己的登入還有效。
        //
        // 為什麼不能只靠讀取的 401：會員清單是**透過 gateway 代理**讀資料庫的，
        // gateway 用它自己的憑證去問，所以你的 session 過期時清單照樣讀得出來。
        // 但寫入前的守衛檢查的是**你的** session——於是畫面看起來一切正常，
        // 直到按下儲存才九筆全部失敗。
        //
        // 使用者已經改完九列才知道要重新登入，那些改動也沒地方留。
        // 早三十秒講，成本是一次往返；晚三十秒講，成本是重做一遍。
        // 交給 SessionWatch 持續看，不是只在進頁面看一次——
        // 使用者可能是改到一半才過期的，那時清單早就讀完了。
        const watchAdminSession = () => {
            SessionWatch.start((state) => {
                const save = document.getElementById('adminSaveBtn');
                if (state === 'ok') {
                    if (save) { save.disabled = false; save.title = ''; }
                    setDbStatus('', true);
                    return;
                }
                const why = state === 'expired'
                    ? '登入已過期。清單還讀得到是因為它由伺服器代為查詢，但現在存不進去。'
                    : '目前連不上登入驗證，存檔可能會失敗。';
                setDbStatus(`${why} 請重新登入後再修改權限。`, false);
                // 把儲存鎖起來，而不是讓它按下去再一次失敗九筆。
                // 按得下去卻註定失敗的按鈕，等於在浪費使用者的時間兩次。
                if (save) { save.disabled = true; save.title = why; }
            });
        };

        const loadAdminMembers = () => {
            dbMembersLoading = true;
            dbMembersError = '';
            setDbStatus('會員資料庫載入中…', true);
            if (ensureReloadBtn) ensureReloadBtn.disabled = true;
            render();
            Api.fetchAdminMembers().then(result => {
                dbMembersLoading = false;
            if (result?.ok) {
                dbMembers = result.members || [];
                dbMembersError = '';
                setDbStatus('', true);
                loadAllSavedLooks();
                // 清單讀到了不代表你還登著。這一步才會發現。
                watchAdminSession();
            } else {
                dbMembers = null;
                dbMembersError = result?.error || '未知錯誤';
                const hint = classifyMemberLoadError(result);
                setDbStatus(`會員資料庫讀取失敗：${dbMembersError}。${hint}`, false);
                // 401 = 後端已拒絕目前的管理員憑證。清除前端殘留狀態再登入，
                // 避免畫面仍顯示已登入、API 卻持續使用失效 token/session。
                if (result?.status === 401) handleSessionExpired();
            }
                if (ensureReloadBtn) ensureReloadBtn.disabled = false;
            render();
        });
        };

        const membersFromDb = () => dbMembers.map(m => {
            return {
                name: m.name,
                email: m.email,
                level: m.level || '一般會員',
                role: m.role || 'member',
                points: m.points ?? null,
                permission: {
                    role: m.role || 'member',
                    status: m.status || 'active',
                    allowedPages: (Array.isArray(m.allowedPages) && m.allowedPages.length) ? m.allowedPages : AdminStore.defaultPermissions(m.role).allowedPages,
                    vipRequested: !!(m.vipRequested || m.permission?.vipRequested)
                }
            };
        });

        const render = () => {
            const keyword = String(searchEl?.value || '').trim().toLowerCase();
            // 只吃真會員資料庫，連不上就明講，不退回 demo 假資料
            if (!dbMembers) {
                const message = dbMembersLoading
                    ? '會員資料庫載入中…'
                    : `會員資料庫目前無法讀取。${escapeHtml(dbMembersError || '請確認 admin session、CORS 與 cookie 設定。')}（已停用 demo 假資料）`;
                rowsEl.innerHTML = `<tr><td colspan="7"><div class="empty-state compact">${message}</div></td></tr>`;
                ['adminTotal','adminActive','adminSuspended','adminAdmins'].forEach(id => { const el = document.getElementById(id); if (el) el.textContent = '—'; });
                return;
            }
            let members = membersFromDb();
            const total = members.length;
            const active = members.filter(m => m.permission.status !== 'suspended').length;
            const suspended = members.filter(m => m.permission.status === 'suspended').length;
            const admins = members.filter(m => m.permission.role === 'admin' || AdminStore.isAdminProfile(m)).length;
            const setText = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = String(value); };
            setText('adminTotal', total);
            setText('adminActive', active);
            setText('adminSuspended', suspended);
            setText('adminAdmins', admins);

            members = members.filter(member => {
                const isAdmin = member.permission.role === 'admin' || AdminStore.isAdminProfile(member);
                if (filter === 'active' && member.permission.status === 'suspended') return false;
                if (filter === 'suspended' && member.permission.status !== 'suspended') return false;
                if (filter === 'admin' && !isAdmin) return false;
                if (!keyword) return true;
                return String(member.name || '').toLowerCase().includes(keyword) || String(member.email || '').toLowerCase().includes(keyword);
            });

            rowsEl.innerHTML = members.map(member => {
                const perm = member.permission || AdminStore.defaultPermissions();
                const allowed = new Set(perm.allowedPages || []);
                const isCurrentAdmin = String(member.email || '').trim().toLowerCase() === String(Auth.getProfile()?.email || '').trim().toLowerCase();
                return `<tr data-admin-email="${escapeHtml(member.email)}">
                    <td>
                        <div class="admin-user">
                            <b>${escapeHtml(member.name || member.email.split('@')[0])}${perm.vipRequested && member.level !== 'VIP會員' ? ' <span class="admin-fail warn">申請升級中</span>' : ''}</b>
                            <span>${escapeHtml(member.email)}</span>
                            <span class="admin-look-count" data-look-email="${escapeHtml(member.email)}" style="margin-top:4px;font-size:12px;color:#7A4A42;cursor:pointer;text-decoration:underline dotted;" title="點開看這位會員的妝容收藏（從資料庫即時抓）">妝容收藏：${lookCountLabel(member.email)}</span>
                            <span style="margin-top:2px;font-size:12px;color:#7A4A42;" title="會員目前點數餘額">點數：${member.points != null ? member.points : pointsLabel(member.email)}</span>
                        </div>
                    </td>
                    <td>
                        <select class="admin-select" data-admin-role>
                            <option value="member" ${perm.role !== 'admin' ? 'selected' : ''}>一般使用者</option>
                            <option value="admin" ${perm.role === 'admin' ? 'selected' : ''}>管理員</option>
                        </select>
                    </td>
                    <td>
                        <select class="admin-select" data-admin-level ${AdminStore.isAdminProfile(member) ? 'disabled' : ''}>
                            <option value="一般會員" ${!['VIP會員','PRO會員'].includes(member.level) ? 'selected' : ''}>一般會員</option>
                            <option value="VIP會員" ${member.level === 'VIP會員' ? 'selected' : ''}>VIP會員（可用 PRO）</option>
                            <option value="PRO會員" ${member.level === 'PRO會員' ? 'selected' : ''}>PRO會員（展示開通）</option>
                        </select>
                    </td>
                    <td>
                        <!-- 2026-08-27 拿掉按鈕，改成純顯示：停權這個動作沒有在用。
                             欄位保留是因為資料庫端仍然有 status 欄，真的出現停權的會員時
                             畫面上要看得出來——拿掉顯示會讓一個被停權的帳號看起來正常。 -->
                        <span class="admin-status ${perm.status === 'suspended' ? 'off' : 'on'}">
                            ${perm.status === 'suspended' ? '已停權' : '啟用中'}
                        </span>
                    </td>
                    <td><span class="admin-fail ${AdminStore.failureReason(member) === '正常' ? 'ok' : 'warn'}">${escapeHtml(AdminStore.failureReason(member))}</span></td>
                    <td>
                        <div class="admin-perms">
                            ${Object.keys(pageLabels).map(page => {
                                const checked = allowed.has(page) || (['analysisPro', 'unlimitedRender'].includes(page) && AdminStore.isVip(member));
                                return `<label><input type="checkbox" data-admin-page="${page}" ${checked ? 'checked' : ''}>${pageLabels[page]}</label>`;
                            }).join('')}
                        </div>
                    </td>
                    <td>
                        <div class="admin-member-actions">
                            <button class="admin-danger-button compact" data-admin-delete type="button" ${isCurrentAdmin ? 'disabled title="不能刪除目前登入中的管理員帳號"' : ''}>刪除會員</button>
                        </div>
                    </td>
                </tr>`;
            }).join('') || '<tr><td colspan="7"><div class="empty-state compact">沒有符合條件的使用者</div></td></tr>';

            rowsEl.querySelectorAll('[data-admin-delete]').forEach(btn => {
                btn.onclick = () => {
                    const row = btn.closest('[data-admin-email]');
                    const email = row?.dataset.adminEmail;
                    if (!email || btn.disabled) return;
                    showConfirm(`確定要刪除會員「${email}」嗎？會員資料、點數、收藏關聯，以及他上傳的臉部影像都會一併移除，此動作無法復原。`, {
                        title: '刪除會員資料', type: 'error', okText: '刪除會員', cancelText: '保留',
                        onOk: async () => {
                            btn.disabled = true;
                            // 影像清除由 Gateway 在轉發刪除前自己做掉，這裡不必先呼叫。
                            //
                            // 曾經在這裡先打一次清除端點，但那樣「先清後刪」是靠呼叫端自律——
                            // 任何繞過這個按鈕的刪除都會留下孤兒影像。改成 Gateway 保證之後，
                            // 順序變成結構上的，繞不過去；在這裡再做一次只是把同一個保證
                            // 放到兩個地方，遲早有一邊被改壞而沒人發現。
                            const result = await Api.deleteMember(email);
                            if (!result || !result.ok) {
                                btn.disabled = false;
                                showAlert(`會員刪除失敗：${result?.error || '請確認會員資料庫連線與管理員權限'}`, { type: 'error' });
                                return;
                            }
                            dbMembers = dbMembers.filter(member => String(member.email).toLowerCase() !== String(email).toLowerCase());
                            delete looksByEmail[email];
                            delete pointsByEmail[email];
                            showToast('會員已刪除，臉部與渲染影像已一併清除');
                            render();
                        }
                    });
                };
            });

            // 等級下拉連動權限：選 VIP／PRO 會員時，即時自動勾選「PRO 分析」「渲染不限次數」；改回一般會員則取消勾選（實際寫入仍以「儲存權限」為準）
            rowsEl.querySelectorAll('[data-admin-level]').forEach(sel => {
                sel.onchange = () => {
                    const row = sel.closest('[data-admin-email]');
                    if (!row) return;
                    const isVipTier = ['VIP會員', 'PRO會員'].includes(sel.value);
                    ['analysisPro', 'unlimitedRender'].forEach(page => {
                        const box = row.querySelector(`[data-admin-page="${page}"]`);
                        if (box) box.checked = isVipTier;
                    });
                };
            });

            // 妝容收藏數：點開看該會員的收藏縮圖（從資料庫即時抓）
            rowsEl.querySelectorAll('.admin-look-count[data-look-email]').forEach(function(el){
                el.onclick = function(){ openMemberLooksModal(el.dataset.lookEmail); };
            });
        };

        // 背景逐會員抓 saved_looks 與點數，抓完重繪（demo 時後台可即時看到資料庫寫入）
        const loadAllSavedLooks = () => {
            if (!Array.isArray(dbMembers) || !dbMembers.length) return;
            Promise.all(dbMembers.map(m => Promise.all([
                Api.listSavedLooks(m.email)
                    .then(r => { looksByEmail[m.email] = (r && r.ok) ? r.looks : null; })
                    .catch(() => { looksByEmail[m.email] = null; }),
                Api.getMemberPoints(m.email)
                    .then(r => { pointsByEmail[m.email] = (r && r.ok) ? { balance: r.balance, earned: r.earned } : null; })
                    .catch(() => { pointsByEmail[m.email] = null; })
            ]))).then(() => { if (Router.currentPage === 'admin') render(); });
        };

        // 後台收藏 modal：沿用前台的收藏卡片與妝前／妝後詳情版面，並提供資料庫刪除
        const openMemberLooksModal = (email) => {
            const looks = looksByEmail[email];
            const old = document.getElementById('adminLooksModal'); if (old) old.remove();
            const ov = document.createElement('div'); ov.id = 'adminLooksModal'; ov.className = 'glass-alert';
            const records = Array.isArray(looks) ? looks.map(mapRemoteSavedLook) : [];
            const body = records.length
                ? `<div class="saved-look-grid">${records.map((item, index) => {
                    const afterSrc = lookImageSrc(item.renderedImage);
                    const summary = item.summary || '已保存妝容對比圖，可點開查看完整妝前／妝後結果。';
                    return `<article class="saved-look-card" data-admin-look-index="${index}" style="cursor:pointer;">
                        <button class="look-del" data-admin-del-look="${index}" aria-label="從資料庫刪除此妝容">×</button>
                        <div class="saved-look-photo">${afterSrc
                            ? `<img src="${afterSrc}" alt="${escapeHtml(item.style || '妝容')}" onload="this.classList.add('loaded')" onerror="markLookImageUnavailable(this)">`
                            : `<span>${escapeHtml(item.style || 'Look')}</span>`}</div>
                        <div class="saved-look-body">
                            <div class="saved-look-kicker">Saved Look · DB</div>
                            <h3>${escapeHtml(item.style || '妝容')}</h3>
                            <p>${escapeHtml(String(summary).slice(0, 72))}</p>
                            <time>${escapeHtml(item.timestamp ? formatAnalysisTime(item.timestamp) : '')}</time>
                        </div>
                    </article>`;
                }).join('')}</div>`
                : (looks === null
                    ? '<div class="empty-state compact">讀取這位會員的收藏失敗（請確認 admin session 與資料庫連線）</div>'
                    : '<div class="empty-state compact">這位會員目前沒有收藏妝容</div>');
            ov.innerHTML = `<div class="ga-card admin-looks-dialog" role="dialog" aria-modal="true">
                <button class="lm-close" aria-label="關閉">×</button>
                <h3 class="ga-title">妝容收藏（資料庫即時）</h3>
                <p class="ga-sub">${escapeHtml(email)}</p>
                ${body}
            </div>`;
            document.body.appendChild(ov); void ov.offsetWidth; ov.classList.add('show');
            const close = () => { ov.classList.remove('show'); setTimeout(() => ov.remove(), 300); };
            ov.querySelector('.lm-close').onclick = close;
            ov.addEventListener('click', e => { if (e.target === ov) close(); });
            ov.querySelectorAll('[data-admin-look-index]').forEach(card => {
                card.onclick = () => {
                    const index = Number(card.dataset.adminLookIndex);
                    const item = records[index];
                    if (!item) return;
                    ov.remove();
                    openLookModal(item);
                };
            });
            ov.querySelectorAll('[data-admin-del-look]').forEach(button => {
                button.onclick = event => {
                    event.stopPropagation();
                    const index = Number(button.dataset.adminDelLook);
                    const target = Array.isArray(looks) ? looks[index] : null;
                    if (!target || target.id == null) return;
                    showConfirm('確定要從資料庫刪除這筆會員妝容對比圖嗎？此動作無法復原。', {
                        title: '刪除資料庫收藏', type: 'error', okText: '刪除', cancelText: '保留',
                        onOk: async () => {
                            button.disabled = true;
                            const result = await Api.deleteSavedLook(email, target.id);
                            if (!result || !result.ok) {
                                button.disabled = false;
                                showAlert('資料庫刪除失敗，這筆妝容仍然保留。請確認 admin session 與資料庫連線。', { type: 'error' });
                                return;
                            }
                            looksByEmail[email] = looks.filter((_, i) => i !== index);
                            showToast('妝容已從資料庫刪除');
                            ov.remove();
                            render();
                            openMemberLooksModal(email);
                        }
                    });
                };
            });
        };

        // render 為 const，必須等它初始化後才能呼叫 loadAdminMembers（內部會呼叫 render），否則觸發 TDZ「Cannot access 'render' before initialization」
        if (ensureReloadBtn) ensureReloadBtn.onclick = loadAdminMembers;
        loadAdminMembers();

        // 後台自動刷新：切回這個分頁 / 視窗重新取得焦點時自動重抓會員與收藏數，不用手按「重新讀取」
        Router._reloadAdmin = loadAdminMembers;
        if (!Router._adminAutoRefreshBound) {
            Router._adminAutoRefreshBound = true;
            let lastAutoReload = 0;
            const autoReload = () => {
                if (Router.currentPage !== 'admin' || typeof Router._reloadAdmin !== 'function') return;
                const now = Date.now();
                if (now - lastAutoReload < 3000) return; // 3 秒內只刷一次，避免快速切分頁猛打資料庫
                lastAutoReload = now;
                Router._reloadAdmin();
            };
            window.addEventListener('focus', autoReload);
            document.addEventListener('visibilitychange', () => { if (!document.hidden) autoReload(); });
        }

        filters.forEach(btn => {
            btn.onclick = () => {
                filter = btn.dataset.adminFilter || 'all';
                filters.forEach(b => b.classList.toggle('active', b === btn));
                render();
            };
        });
        if (searchEl) {
            let searchTimer = null;
            searchEl.oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(render, 200); };
        }
        const saveBtn = document.getElementById('adminSaveBtn');
        if (saveBtn) saveBtn.onclick = async () => {
            const rows = Array.from(rowsEl.querySelectorAll('[data-admin-email]')).map(row => {
                const email = row.dataset.adminEmail;
                const role = row.querySelector('[data-admin-role]')?.value || 'member';
                const levelSelect = row.querySelector('[data-admin-level]');
                const allowedPages = Array.from(row.querySelectorAll('[data-admin-page]:checked')).map(input => input.dataset.adminPage);
                if (!allowedPages.includes('dashboard')) allowedPages.unshift('dashboard');
                if (!allowedPages.includes('profile')) allowedPages.push('profile');
                if (role === 'admin' && !allowedPages.includes('admin')) allowedPages.push('admin');
                // VIP 會員自動連動勾選 PRO 分析、無限渲染權限，管理員也還是能單獨手動勾給非 VIP 會員
                if (levelSelect && !levelSelect.disabled && ['VIP會員', 'PRO會員'].includes(levelSelect.value)) {
                    ['analysisPro', 'unlimitedRender'].forEach(p => { if (!allowedPages.includes(p)) allowedPages.push(p); });
                }
                return { email, role, allowedPages, level: (levelSelect && !levelSelect.disabled) ? levelSelect.value : null };
            });

            if (!dbMembers) { showAlert(`會員資料庫無法讀取，無法儲存：${dbMembersError || '請確認 admin session、CORS 與 cookie 設定'}`, { type: 'error' }); return; }
            // 送出前再確認一次。輪詢是每 90 秒，剛好卡在兩次之間過期的話，
            // 這裡是最後一道——而且成本只有一次往返，換掉的是九筆全錯。
            const fresh = await Api.validateSession();
            if (!fresh.ok || !fresh.actorId) {
                showAlert(fresh.status === 401
                    ? '登入已過期，這次沒有任何一筆被寫入。請重新登入後再儲存一次。'
                    : '目前無法確認登入狀態，這次沒有任何一筆被寫入，請稍後再試。',
                    { title: '尚未儲存', type: 'error' });
                SessionWatch.check();
                return;
            }
            // 逐筆 PATCH 進資料庫；前端不再自行核發權限，只在成功後同步顯示資料庫回傳結果
            saveBtn.disabled = true;
            const failures = [];
            for (const r of rows) {
                const patch = { role: r.role, allowedPages: r.allowedPages };
                if (r.level) patch.level = r.level;
                // skipAssert：整批開始前才剛驗過身分（上面那段 validateSession）。
                // 逐筆再驗的話，每一筆都會打一次 /auth/session，而那條路徑會
                // **重寫 session cookie**——cookie 在批次中途被換掉，後面幾筆
                // 就拿著舊的那份而 401。2026-08-27 的「前兩筆成功、後七筆失敗」
                // 就是這樣來的，而使用者只是在改權限而已。
                const result = await Api.patchMember(r.email, patch, { skipAssert: true });
                if (!result.ok) { failures.push(`${r.email}：${result.error}`); continue; }
                const target = dbMembers.find(m => m.email === r.email);
                const memberFromServer = result.member || {};
                if (target) {
                    target.role = memberFromServer.role || r.role;
                    target.allowedPages = memberFromServer.allowedPages || r.allowedPages;
                    target.status = memberFromServer.status || target.status;
                    target.vipRequested = !!(memberFromServer.vipRequested || memberFromServer.permission?.vipRequested);
                    if (r.level) target.level = memberFromServer.level || r.level;
                }
                if ((Auth.getProfile()?.email || '').toLowerCase() === String(r.email || '').toLowerCase()) {
                    Auth.setProfile({
                        ...(Auth.getProfile() || {}),
                        ...(memberFromServer.email ? memberFromServer : patch)
                    });
                }
            }
            saveBtn.disabled = false;
            if (failures.length) {
                showAlert(`有 ${failures.length} 筆沒寫進資料庫：\n${failures.join('\n')}\n（401 = 管理員 session 沒帶上，請用資料庫的 admin 帳號重新登入）`, { type: 'error' });
            } else {
                showToast(`權限已更新並寫入資料庫（${rows.length} 筆）`);
            }
            updateAdminNav();
            render();
        };
        let editingProductId = null;
        const productForm = document.getElementById('adminProductForm');
        const createBtn = document.getElementById('adminProductCreateBtn');
        const editBtn = document.getElementById('adminProductEditBtn');
        const cancelBtn = document.getElementById('adminProductCancelBtn');
        const formDeleteBtn = document.getElementById('adminProductDeleteBtn');
        const editingLabel = document.getElementById('adminProductEditingLabel');

        const exitEditMode = () => {
            editingProductId = null;
            productForm.reset();
            productForm.classList.remove('is-editing');
            createBtn.disabled = false;
            editBtn.disabled = true;
            cancelBtn.style.display = 'none';
            if (formDeleteBtn) formDeleteBtn.disabled = true;
        };

        // 商品管理：只吃真商品資料庫（/api/products），不再顯示本機 demo 商品
        let dbProducts = null;
        let dbProductsError = '';
        let productSearchQuery = '';
        let productSearchTimer = null;
        let productResultTotal = 0;
        const CAT_TO_TYPE = { '底妝':'foundations', '眼影':'eyeshadows', '眼線/睫毛':'eyeliner_mascara', '唇彩':'lipsticks', '腮紅':'blushes', '眉毛彩妝':'eyebrows', '修容':'contouring', '打亮':'highlighters' };
        const TYPE_TO_CAT = Object.fromEntries(Object.entries(CAT_TO_TYPE).map(([cat, type]) => [type, cat]));
        const splitTags = value => String(value || '').split(',').map(tag => tag.trim()).filter(Boolean);
        const joinTags = value => Array.isArray(value) ? value.join(', ') : '';
        const PRODUCT_STATUS_LABELS = { active: '上架中', draft: '草稿', inactive: '已停用', deleted: '已刪除' };

        const enterEditMode = (id) => {
            const product = (dbProducts || []).find(p => String(p.id) === String(id));
            if (!product) return;
            editingProductId = id;
            document.getElementById('adminProductName').value = product.name || '';
            document.getElementById('adminProductBrand').value = product.brand || '';
            document.getElementById('adminProductSku').value = product.sku || '';
            document.getElementById('adminProductShadeName').value = product.shadeName || '';
            document.getElementById('adminProductCategory').value = product.cat || '底妝';
            // 填數字，不是顯示字串。product.price 經過 _normalizeProduct 之後是 "NT$400"，
            // 而送出時做的是 Number(...)——直接把顯示字串填回去，等於這個欄位預設就帶著
            // 一個存檔會變成 null 的值。
            document.getElementById('adminProductPrice').value = parsePriceInput(product.price) ?? '';
            document.getElementById('adminProductImg').value = product.img || '';
            document.getElementById('adminProductSourceUrl').value = product.sourceUrl || '';
            document.getElementById('adminProductDesc').value = product.desc || '';
            document.getElementById('adminProductShades').value = product.hex || '';
            document.getElementById('adminProductStatus').value = product.status || 'active';
            document.getElementById('adminProductReviewStatus').value = product.reviewStatus || 'pending';
            document.getElementById('adminProductInStock').checked = product.inStock !== false;
            // 只回填 API 真的有的標籤。風格／妝效／場合三個欄位已經移除
            // （商品 API 沒有那些欄位，見 admin.html 的說明）。
            document.getElementById('adminProductSeasonTags').value = joinTags(product.seasonTags);
            productForm.classList.add('is-editing');
            editingLabel.textContent = product.name || id;
            createBtn.disabled = true;
            editBtn.disabled = false;
            cancelBtn.style.display = '';
            if (formDeleteBtn) formDeleteBtn.disabled = false;
            productForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
        };

        // 商品清單的排序。預設最新在上：新增或編輯完之後，最想確認的就是那一筆。
        //
        // 「最新」用 id 遞減。商品 API 的 25 個欄位裡**沒有 createdAt 也沒有 updatedAt**
        // （2026-08-26 實測，清單與單品都一樣），而 id 是遞增的主鍵，所以它是目前
        // 唯一可用的時間代理。代價是**編輯過的商品不會浮上來**——那要等後端補 updatedAt。
        //
        // 排序在前端做而不是交給 API：清單本來就已經全部抓回本機了（fetchAllPages），
        // 為了換個順序再打一次網路不划算，而且切換排序會有明顯延遲。
        // 品牌與價格在本機過濾，不送 API。
        //
        // 實測 2026-08-28 的線上商品服務：`minPrice`/`maxPrice` 完全沒有作用
        // （minPrice=99999 仍回全部 68 筆），`brand=MAC,YSL` 這種逗號多選回 0 筆。
        // 送出去會得到一個「看起來有篩、其實沒篩」或「篩到空的」畫面——
        // 兩種都比不做更糟，因為管理員無從發現。
        //
        // 清單本來就整份抓回本機了（fetchAllPages 會翻到 nextCursor 為 null），
        // 所以在這裡過濾是準的。⚠️ 但只有在「完整載入」時才準：
        // rec.partial 為真時清單不完整，過濾與排序的結果也就不完整，畫面要講出來。
        // 後台只篩品牌。價格區間拿掉了：這裡是「找某一件商品」的地方，
        // 找法是名稱、品牌、分類——不會有人用價格區間找要編輯哪一筆。
        // 一般商品頁那邊的價格篩選留著，那裡是逛街。
        const adminBrandFilter = () => document.getElementById('adminProductBrandFilter')?.value || '';
        const filterAdminProducts = (list) => {
            // 後端支援時交給後端，前端不再重複套用。
            if (Api.productServerFiltering) return list || [];
            const brand = adminBrandFilter();
            if (!brand) return list || [];
            return (list || []).filter(p => String(p.brand || '') === brand);
        };

        // 品牌下拉的選項從實際載到的清單長出來，不寫死。
        // 寫死的話新品牌進資料庫後會篩不到，而畫面上看不出少了選項。
        const syncAdminBrandOptions = (list) => {
            const brands = [...new Set((list || []).map(p => String(p.brand || '')).filter(Boolean))].sort();
            const el = document.getElementById('adminProductBrandFilter');
            if (el) {
                // 重畫時保住目前選的那一個：清單是每次載入完才長出來的，
                // 不保留的話管理員選了品牌、按重新載入就被打回「全部品牌」。
                const picked = el.value;
                el.innerHTML = '<option value="">全部品牌</option>'
                    + brands.map(b =>
                        `<option value="${escapeHtml(b)}"${picked === b ? ' selected' : ''}>${escapeHtml(b)}</option>`
                    ).join('');
            }
            // 新增／編輯商品時的品牌欄也用同一份清單。
            // 「MAC」「Mac」「MAC 」會變成三個品牌，而篩選與推薦都是字串比對——
            // 分家之後畫面上看不出來，只會發現某些商品怎麼篩都篩不到。
            const dl = document.getElementById('adminBrandOptions');
            if (dl) {
                dl.innerHTML = brands.map(b => `<option value="${escapeHtml(b)}"></option>`).join('');
            }
        };

        const sortAdminProducts = (list) => {
            const rows = [...(list || [])];
            const mode = document.getElementById('adminProductSort')?.value || 'newest';
            // 價格是 "NT$377" 這種字串，比大小前要先抽出數字；抽不出來的排到最後，
            // 不要讓它們因為 NaN 而跑到最前面（NaN 的比較結果不可預期）。
            const priceOf = (p) => {
                const n = Number(String(p.price ?? '').replace(/[^0-9.]/g, ''));
                return Number.isFinite(n) ? n : null;
            };
            const byPrice = (dir) => (a, b) => {
                const x = priceOf(a), y = priceOf(b);
                if (x === null && y === null) return 0;
                if (x === null) return 1;
                if (y === null) return -1;
                return dir * (x - y);
            };
            const idOf = (p) => Number(p.rawId ?? p.id) || 0;
            switch (mode) {
                case 'oldest': return rows.sort((a, b) => idOf(a) - idOf(b));
                case 'name': return rows.sort((a, b) =>
                    String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hant'));
                case 'price-desc': return rows.sort(byPrice(-1));
                case 'price-asc': return rows.sort(byPrice(1));
                default: return rows.sort((a, b) => idOf(b) - idOf(a));
            }
        };

        const renderProducts = () => {
            const area = document.getElementById('adminProductRows');
            if (!area) return;
            if (!dbProducts) {
                area.innerHTML = '<tr><td colspan="6"><div class="empty-state compact">商品資料庫載入中…</div></td></tr>';
                return;
            }
            if (!dbProducts.length) {
                const message = dbProductsError || '商品資料庫目前沒有資料';
                area.innerHTML = `<tr><td colspan="6"><div class="empty-state compact">${escapeHtml(message)}</div></td></tr>`;
                return;
            }
            const normalizedQuery = productSearchQuery.trim().toLowerCase();
            const filtered = filterAdminProducts(dbProducts);
            const products = sortAdminProducts(filtered);
            const searchStatus = document.getElementById('adminProductSearchStatus');
            if (searchStatus) {
                // 本機再過濾過就不能報伺服器的總數——那個數字描述的是沒有套品牌與
                // 價格條件的清單，掛在一份 30 筆的表格上會讓人以為還有 1000 筆沒顯示。
                const narrowed = filtered.length !== (dbProducts || []).length;
                const shown = narrowed
                    ? `${filtered.length} 筆（已從 ${dbProducts.length} 筆篩選）`
                    : `${productResultTotal} 筆`;
                searchStatus.textContent = normalizedQuery
                    ? `找到 ${shown}符合「${productSearchQuery.trim()}」的資料庫商品。`
                    : `目前條件共有 ${shown}商品。`;
            }
            if (!products.length) {
                area.innerHTML = `<tr><td colspan="6"><div class="empty-state compact">資料庫沒有符合「${escapeHtml(productSearchQuery.trim())}」的商品，可使用上方 Google 搜尋找來源頁，再交由爬蟲匯入。</div></td></tr>`;
                return;
            }
            area.innerHTML = products.map(product => `<tr class="admin-product-row" data-edit-product="${escapeHtml(product.id)}">
                <td><div class="admin-product-cell">${phBox('product-thumb', product.name, product.img)}<div class="admin-user"><b>${escapeHtml(product.name)}</b><span>${escapeHtml(product.brand || '未填品牌')} · ${escapeHtml(product.shadeName || '未填色號')}</span><span>DB id: ${escapeHtml(String(product.rawId ?? product.id))} · v${escapeHtml(product.version)}</span></div></div></td>
                <td>${escapeHtml(product.cat)}</td>
                <td>${escapeHtml(product.price)}</td>
                <td><span class="admin-source">商品資料庫</span></td>
                <td><span class="admin-fail ${product.status === 'active' ? 'ok' : ''}">${escapeHtml(PRODUCT_STATUS_LABELS[product.status] || product.status)}</span><br><small>${product.reviewStatus == null ? '審核狀態未提供' : (product.reviewStatus === 'approved' ? '已審核' : product.reviewStatus === 'rejected' ? '已退回' : '待審核')} · ${product.recommendationReady == null ? '推薦資格尚未計算' : (product.recommendationReady ? '可推薦' : '不可推薦')} · ${product.dataQualityScore == null ? '品質分數尚未提供' : `品質 ${escapeHtml(product.dataQualityScore)}`}</small></td>
                <td><div class="admin-product-actions">
                    <button class="admin-secondary-button compact" type="button" data-edit-btn="${escapeHtml(product.id)}">編輯</button>
                    <button class="admin-danger-button compact" type="button" data-delete-product="${escapeHtml(product.id)}">刪除</button>
                </div></td>
            </tr>`).join('');
        };

        const loadAdminProducts = () => {
            const reloadBtn = document.getElementById('adminReloadProductsBtn');
            if (reloadBtn) reloadBtn.disabled = true;
            dbProducts = null;
            dbProductsError = '';
            productConnectionState = 'pending';
            setConnectionStatus('adminProductConnection', '連線中', 'pending');
            updateOverallStatus();
            renderProducts();
            // 後端每頁最多 100 筆且類型篩選尚未生效，因此前端自行翻頁並再次篩選。
            const typeFilter = document.getElementById('adminProductTypeFilter')?.value || '';
            const baseParams = {
                q: productSearchQuery.trim(),
                type: typeFilter,
                status: document.getElementById('adminProductStatusFilter')?.value ?? 'active',
                limit: 100
            };
            // 後端支援時把品牌與價格一起送出去，讓它篩全部商品而不是只篩這一頁。
            // 舊版對這些參數是靜默忽略的，送了會得到一份沒篩到的清單，
            // 所以要等回應說它支援（appliedFilters／facets）之後才送。
            if (Api.productServerFiltering) {
                const brand = adminBrandFilter();
                if (brand) baseParams.brand = brand;
            }
            const fetchAllPages = async () => {
                const all = [];
                const seen = new Set();
                const usedCursors = new Set();
                let cursor = null;
                let firstRec = null;
                // 「還有下一頁但頁數用完了」才算截斷。
                //
                // 先前是用 `partial: cursor != null` 判斷，那是錯的：迴圈靠 `if (!next) break`
                // 收尾，跳出時 cursor 還留著**上一頁**的游標，不會變回 null。於是只要商品
                // 超過一頁（100 筆），正常載完也會被標成「部分載入」並跳出重試提示——
                // 而 1041 筆商品每次都會翻頁，所以每次都誤報。2026-08-24 修。
                let truncated = false;
                for (let page = 0; page < PRODUCT_MAX_PAGES; page++) {
                    const rec = await Api.listProducts(cursor ? { ...baseParams, cursor } : baseParams);
                    // 中途某一頁失敗：前面撈到的仍然有用，但**不能假裝撈完了**。
                    // 標成 partial，下面才不會把伺服器回的總數（例如 1041）掛在一份
                    // 只有 300 筆的清單上——那正是「後台看不到所有商品」的原樣重現，
                    // 而且這次連個提示都沒有。
                    if (!rec?.ok) return firstRec ? { ...firstRec, products: all, partial: true } : rec;
                    if (!firstRec) firstRec = rec;
                    for (const p of rec.products || []) {
                        const key = p.rawId != null ? `raw:${p.rawId}` : `id:${p.id}`;
                        if (seen.has(key)) continue;
                        seen.add(key);
                        all.push(p);
                    }
                    const next = rec.nextCursor || null;
                    // 沒有下一頁、這頁空的、或後端把同一個 cursor 回第二次就停，避免無限翻頁。
                    if (!next || !(rec.products || []).length || usedCursors.has(next)) break;
                    usedCursors.add(next);
                    cursor = next;
                    // 還有下一頁，但這是最後一圈——真的被上限截斷了。
                    if (page === PRODUCT_MAX_PAGES - 1) truncated = true;
                }
                // 迴圈是被 PRODUCT_MAX_PAGES 上限中止、而不是自然翻完的話，同樣是一份
                // 不完整的清單。先前只有「某一頁失敗」那條標了 partial，這條沒標，於是
                // 截斷的結果照樣掛著伺服器回的總數——同一個 bug 換一個分支重演。
                return { ...firstRec, products: all, partial: truncated };
            };
            return fetchAllPages().then(rec => {
                if (rec?.ok) {
                    const loaded = rec.products || [];
                    dbProducts = typeFilter
                        ? loaded.filter(p => p.apiType === typeFilter || p.cat === TYPE_TO_CAT[typeFilter])
                        : loaded;
                    // 伺服器的 total 是「忽略 type 之後的總數」，套了前端類型過濾就不能拿來當筆數。
                    // 翻頁中途失敗（partial）時同理：那個總數描述的是完整清單，掛在一份不完整的
                    // 清單上會讓管理員以為全部都在這裡了。這種時候只報實際載到的筆數並標明。
                    productResultTotal = (typeFilter || rec.partial)
                        ? dbProducts.length
                        : Number(rec.total ?? dbProducts.length);
                    dbProductsError = rec.partial
                        ? `商品清單只載入了部分資料（${dbProducts.length} 筆），請按重新載入再試一次。`
                        : '';
                    syncAdminBrandOptions(dbProducts);
                    productConnectionState = rec.partial ? 'error' : 'ok';
                    setConnectionStatus('adminProductConnection', rec.partial ? '部分載入' : '正常', rec.partial ? 'error' : 'ok');
                    const total = document.getElementById('adminProductTotal');
                    if (total) total.textContent = String(productResultTotal);
                } else {
                    dbProducts = [];
                    dbProductsError = rec?.status ? `商品資料庫讀取失敗（HTTP ${rec.status}）` : '商品資料庫無法連線';
                    productConnectionState = 'error';
                    setConnectionStatus('adminProductConnection', '異常', 'error');
                    const total = document.getElementById('adminProductTotal');
                    if (total) total.textContent = '—';
                }
                if (reloadBtn) reloadBtn.disabled = false;
                updateOverallStatus();
                renderProducts();
                return rec;
            });
        };
        const productReloadBtn = document.getElementById('adminReloadProductsBtn');
        if (productReloadBtn) productReloadBtn.onclick = loadAdminProducts;
        const productSearchInput = document.getElementById('adminProductSearch');
        const productSearchClearBtn = document.getElementById('adminProductSearchClearBtn');
        const productGoogleSearch = document.getElementById('adminProductGoogleSearch');
        const updateProductSearch = () => {
            productSearchQuery = productSearchInput?.value || '';
            if (productGoogleSearch) {
                const terms = productSearchQuery.trim() || '彩妝 商品';
                productGoogleSearch.href = `https://www.google.com/search?q=${encodeURIComponent(`${terms} 彩妝 商品`)}`;
            }
            clearTimeout(productSearchTimer);
            productSearchTimer = setTimeout(loadAdminProducts, 250);
        };
        if (productSearchInput) productSearchInput.oninput = updateProductSearch;
        ['adminProductTypeFilter', 'adminProductStatusFilter'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.onchange = loadAdminProducts;
        });
        // 排序只重畫，不重新抓：清單已經在本機了（見 sortAdminProducts 的說明）。
        const sortSelect = document.getElementById('adminProductSort');
        if (sortSelect) sortSelect.onchange = renderProducts;
        // 品牌與價格是本機過濾，不必重打 API——換條件只要重畫。
        const brandFilterEl = document.getElementById('adminProductBrandFilter');
        // 後端支援伺服器端篩選時要重打一次 API（它篩的是全部商品）；
        // 不支援時只要在本機重畫。
        if (brandFilterEl) brandFilterEl.onchange = () => {
            if (Api.productServerFiltering) loadAdminProducts();
            else renderProducts();
        };
        if (productSearchClearBtn) productSearchClearBtn.onclick = () => {
            if (productSearchInput) productSearchInput.value = '';
            const type = document.getElementById('adminProductTypeFilter'); if (type) type.value = '';
            const status = document.getElementById('adminProductStatusFilter'); if (status) status.value = 'active';
            const brand = document.getElementById('adminProductBrandFilter');
            if (brand) brand.value = '';
            updateProductSearch();
            productSearchInput?.focus();
        };
        if (productGoogleSearch) productGoogleSearch.onclick = async event => {
            event.preventDefault();
            // 爬蟲的 /crawler/search-preview 已下線，這裡本來就有「拿不到就退回 Google」
            // 的路徑，現在直接組網址。經 Api 繞一圈只是把一行字串組裝包成非同步呼叫，
            // 而且那個失敗分支永遠不會走到。
            const terms = productSearchInput?.value.trim() || '彩妝 商品';
            window.open(`https://www.google.com/search?q=${encodeURIComponent(terms)}`, '_blank', 'noopener,noreferrer');
        };

        // 動作代號 -> 看得懂的中文。認不得的就原樣顯示，不要猜。
        const AUDIT_ACTION_TEXT = {
            'product.create': '新增商品', 'product.update': '編輯商品', 'product.delete': '刪除商品',
            'member.create': '新增會員', 'member.update': '編輯會員', 'member.delete': '刪除會員'
        };
        // targetRef 是上游路徑（例如 /api/products/406），管理員要看的是那個編號。
        const auditTarget = (ref) => {
            const s = String(ref || '');
            const m = s.match(/\/([^/]+)\/?$/);
            return m && /^\d+$/.test(m[1]) ? `#${m[1]}` : (s || '—');
        };
        const auditTime = (iso) => {
            const d = new Date(iso);
            return Number.isNaN(d.getTime()) ? (iso || '—')
                : d.toLocaleString('zh-TW', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit' });
        };

        const loadProductAuditLogs = async () => {
            const rows = document.getElementById('adminAuditRows');
            if (!rows) return;
            rows.innerHTML = '<tr><td colspan="5">讀取中…</td></tr>';
            // 讀 Gateway 自己記的那一份，不是商品後端的稽核表：後者能不能查、記了什麼
            // 由對方決定，而且對方掛掉就查不到——誤刪之後最需要它的時候正好查不到。
            const result = await Api.listAdminActions(100);
            if (!result.ok) {
                rows.innerHTML = `<tr><td colspan="5">${escapeHtml(result.error || '無法讀取操作紀錄')}</td></tr>`;
                return;
            }
            if (!result.events.length) { rows.innerHTML = '<tr><td colspan="5">尚無操作紀錄</td></tr>'; return; }
            rows.innerHTML = result.events.map(ev => {
                const failed = ev.outcome !== 'success';
                return `<tr class="${failed ? 'audit-failed' : ''}">
                    <td>${escapeHtml(auditTime(ev.at))}</td>
                    <td>${escapeHtml(AUDIT_ACTION_TEXT[ev.action] || ev.action || '—')}</td>
                    <td>${escapeHtml(auditTarget(ev.targetRef))}</td>
                    <td>${failed ? `失敗 ${escapeHtml(String(ev.statusCode || ''))}` : '成功'}</td>
                    <td><code>${escapeHtml(String(ev.actorId || '—').slice(0, 14))}</code></td>
                </tr>`;
            }).join('');
        };
        // 管理憑證改用登入 token，進到這頁就直接讀操作紀錄，不必再等使用者「套用」什麼
        loadProductAuditLogs();
        const auditReload = document.getElementById('adminAuditReload');
        if (auditReload) auditReload.onclick = loadProductAuditLogs;
        loadAdminProducts();

        const productRowsEl = document.getElementById('adminProductRows');
        if (productRowsEl) productRowsEl.addEventListener('click', (e) => {
            const deleteTrigger = e.target.closest('[data-delete-product]');
            if (deleteTrigger) {
                e.stopPropagation();
                const id = deleteTrigger.dataset.deleteProduct;
                const product = (dbProducts || []).find(p => String(p.id) === String(id));
                if (!product) return;
                // 2026-08-26 起商品後端改成硬刪除：資料列會從資料庫實體移除，不可復原。
                // 所以確認文案必須說「永久刪除」——先前寫「停用、資料會保留」，
                // 那句話現在是錯的，而在不可逆的動作上寫錯話是最糟的一種錯。
                (async () => {
                    deleteTrigger.disabled = true;
                    deleteTrigger.textContent = '查詢影響';
                    // 先問這一筆被幾個人收藏。拿不到就用通用警語，不擋刪除。
                    const impact = await Api.getProductDeleteImpact(product.rawId ?? product.id);
                    deleteTrigger.disabled = false;
                    deleteTrigger.textContent = '刪除';
                    const detail = impact
                        ? `\n\n${impact.favorites ?? 0} 筆收藏與 ${impact.cartItems ?? 0} 筆購物車項目會保留，但顯示「此商品已下架」。`
                          + `\n${impact.recommendationRecords ?? 0} 筆推薦／試妝歷史會保留。`
                        : '';
                    showConfirm(`確定要永久刪除「${product.name || '這項商品'}」嗎？\n\n此操作不可復原。${detail}`, {
                        title: '永久刪除商品',
                        type: 'error',
                        okText: '永久刪除',
                        cancelText: '取消',
                        onOk: async () => {
                            deleteTrigger.disabled = true;
                            deleteTrigger.textContent = '刪除中';
                            const result = await Api.deleteRemoteProduct(product.rawId ?? product.id);
                            if (!result.ok) {
                                deleteTrigger.disabled = false;
                                deleteTrigger.textContent = '刪除';
                                showAlert(`商品刪除失敗：${result.error || '未知錯誤'}${(result.status === 401 && result.code !== 'PRODUCT_UPSTREAM_REJECTED') ? '（登入狀態已失效，請重新登入）' : ''}`, { type: 'error' });
                                return;
                            }
                            if (String(editingProductId) === String(product.id)) exitEditMode();
                            Router.generalProductCatalog = null;
                            // 只有後端確認 mode:"hard" 才會走到這裡（見 deleteRemoteProduct）。
                            showAlert(result.alreadyDeleted
                                ? '這項商品已經不在資料庫裡了。'
                                : `商品已永久刪除。${(result.preserved?.favorites ?? 0)} 筆收藏會顯示為已下架。`,
                                { type: 'success' });
                            loadAdminProducts();
                            loadProductAuditLogs();
                        }
                    });
                })();
                return;
            }
            const trigger = e.target.closest('[data-edit-btn], [data-edit-product]');
            if (!trigger) return;
            const id = trigger.dataset.editBtn || trigger.dataset.editProduct;
            enterEditMode(id);
        });

        if (cancelBtn) cancelBtn.onclick = () => exitEditMode();
        if (createBtn) createBtn.onclick = () => {
            if (!editingProductId) productForm.requestSubmit();
        };
        if (editBtn) editBtn.onclick = () => {
            if (editingProductId) productForm.requestSubmit();
        };
        if (formDeleteBtn) formDeleteBtn.onclick = () => {
            if (!editingProductId) return;
            const rowDeleteBtn = [...document.querySelectorAll('[data-delete-product]')]
                .find(button => String(button.dataset.deleteProduct) === String(editingProductId));
            if (rowDeleteBtn) rowDeleteBtn.click();
        };

        if (productForm) productForm.onsubmit = (e) => {
            e.preventDefault();
            const name = document.getElementById('adminProductName')?.value.trim();
            const brand = document.getElementById('adminProductBrand')?.value.trim();
            const sku = document.getElementById('adminProductSku')?.value.trim();
            const shadeName = document.getElementById('adminProductShadeName')?.value.trim();
            const cat = document.getElementById('adminProductCategory')?.value;
            const priceRaw = document.getElementById('adminProductPrice')?.value.trim();
            const price = parsePriceInput(priceRaw);
            const img = document.getElementById('adminProductImg')?.value.trim();
            const sourceUrl = document.getElementById('adminProductSourceUrl')?.value.trim();
            const desc = document.getElementById('adminProductDesc')?.value.trim();
            const shadesRaw = document.getElementById('adminProductShades')?.value.trim();
            const shadesInput = shadesRaw ? shadesRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
            const shades = shadesInput.filter(c => /^#[0-9a-fA-F]{3,8}$/.test(c));
            // 來源網址不再是必填：手動建立的商品本來就沒有來源頁，逼人填一個等於逼人亂編。
            // 爬蟲匯入的商品仍然帶著抓到的來源（隱藏欄位），照樣會一起送出去。
            // 來源網址可填但不強制。
            //
            // 兩份契約對它的說法不一致：2026-08-28 的必要欄位表列它為必填，
            // 但同一份的新增範例寫 `"sourceUrl": null`。前端不替後端決定——
            // 留白就送 null，由後端回它的判斷；真的必填時錯誤訊息會指出來
            // （我們已經會顯示 error.details.fields）。
            //
            // 它先前是 type="hidden"，管理員根本填不到，這才是要修的部分。
            if (!name || !brand || !cat || !priceRaw || !img) {
                showAlert('請完整填寫商品名稱、品牌、分類、價格與圖片網址', { type:'error' });
                return;
            }
            // 無效價格在送出前顯示錯誤，避免 NaN 被轉成 null。
            if (price === null) {
                showAlert(`價格只能填數字（例如 980），目前填的是「${priceRaw}」。`, { type:'error' });
                return;
            }
            if (shades.length !== shadesInput.length) {
                showAlert('色號格式不正確，只接受 Hex 色碼（例如 #3A241C），不合格式的色號已被忽略。', { type:'error' });
                return;
            }
            // 編輯既有商品時，分類欄若沒被動過就沿用它原本的 type，不要從 cat 反推。
            //
            // _normalizeProduct 認不出分類時 cat 會落到 '底妝' 而 apiType 維持 null；
            // 編輯表單照著 cat 預選「底妝」，存檔再用 CAT_TO_TYPE[cat] || 'foundations'
            // 換回英文——一個原本是眼影的商品，只因為管理員改了價格，type 就被靜默改寫成
            // foundations。管理員沒有碰分類，我們就不該替他決定分類。
            // 兩個網址都要是 http(s) 絕對網址。相對路徑或 `javascript:` 會被上游擋成 400，
            // 而那個錯誤訊息不會說是哪一欄。
            // 只驗有填的那些：來源網址留白是允許的，但填了就必須是完整網址。
            const badUrl = [['圖片網址', img], ['來源網址', sourceUrl]]
                .filter(([, v]) => String(v || '').trim())
                .find(([, v]) => !/^https?:\/\//i.test(String(v)));
            if (badUrl) {
                showAlert(`${badUrl[0]}要填完整網址，必須以 http:// 或 https:// 開頭。`, { type:'error' });
                return;
            }
            const editing = editingProductId
                ? (dbProducts || []).find(p => String(p.id) === String(editingProductId))
                : null;
            const categoryUntouched = editing && cat === (editing.cat || '底妝');
            const resolvedType = (categoryUntouched && editing.apiType)
                ? editing.apiType
                : CAT_TO_TYPE[cat];
            if (!resolvedType) {
                showAlert('這件商品的分類無法判定，請先從分類下拉選單選一個正確的分類再儲存。', { type:'error' });
                return;
            }
            // 全部走真商品資料庫，不再寫 localStorage demo
            const payload = {
                name, brand, price,
                type: resolvedType,
                // 一起送中文分類。商品 API 回傳的每一筆都同時有 `category`（中文）與
                // `type`（英文 slug），但這裡先前只送 type——如果上游驗的是 category，
                // 那就是「沒送」而不是「送錯」，錯誤訊息會是「分類無效」。
                // 2026-08-26 實測新增回 400「資料庫寫入失敗：分類無效」，這是最可能的成因。
                // 詳見 docs/對外規格書/商品與推薦/給商品後端_新增商品分類無效_問題回報_2026-08-26.md
                category: cat,
                imageUrl: img,
                imageUrls: [img],
                image_url: img,
                description: desc || '',
                // 沒有來源就送 null，不要送空字串——上游對 source_url 有 URL 格式驗證時，
                // "" 會被當成格式錯誤而擋下整筆新增，null 才是「這個商品沒有來源頁」。
                sourceUrl: sourceUrl || null,
                source_url: sourceUrl || null,
                sku: sku || null,
                shadeName: shadeName || null,
                hex: shades[0] || null,
                status: document.getElementById('adminProductStatus')?.value || 'active',
                reviewStatus: document.getElementById('adminProductReviewStatus')?.value || 'approved',
                inStock: document.getElementById('adminProductInStock')?.checked !== false,
                currency: 'TWD',
                // 只送 API 真的有的標籤欄位。styleTags / finishTags / occasionTags
                // 在商品 API 的 25 個欄位裡都不存在，送過去只會被丟掉——
                // 而「送了但沒存」比「沒送」更難查，因為前端看起來一切正常。
                seasonTags: splitTags(document.getElementById('adminProductSeasonTags')?.value)
            };
            const actionBtn = editingProductId ? editBtn : createBtn;
            actionBtn.disabled = true;
            const finish = (result, okMsg) => {
                actionBtn.disabled = false;
                if (!result.ok) {
                    if (result.code === 'VERSION_CONFLICT') {
                        showAlert('這筆商品已被其他人更新，系統會重新載入最新版本，請確認後再編輯。', { type: 'error' });
                        exitEditMode();
                        loadAdminProducts();
                    } else if (result.code === 'PRODUCT_ALREADY_EXISTS') {
                        showAlert('資料庫已有相同來源／SKU／色號的商品，請改用編輯功能。', { type: 'error' });
                    } else if (result.code === 'INVALID_CATEGORY') {
                        // 後端會指出是哪一個欄位（type 或 category）與合法值。
                        // 把焦點移到那一欄，人才知道要改哪裡——只丟一句錯誤訊息，
                        // 表單有十個欄位，他得自己猜。
                        const el = document.getElementById(
                            result.field === 'category' ? 'adminProductCategory' : 'adminProductCategory');
                        showAlert(result.error, { type: 'error', onOk: () => el?.focus() });
                    } else {
                        // 把**實際送出的分類值**一起說出來。
                        // 「類別無效」這四個字沒有指向任何東西：管理員不知道問題出在
                        // 中文的 category 還是英文的 type，也不知道送出去的到底是什麼。
                        // 帶著這兩個值，這一句就能直接轉給商品後端，不必再來回問一輪。
                        const sent = `（送出的 type=「${payload.type}」、category=「${payload.category}」）`;
                        const needsDetail = /類別|分類|category|type/i.test(String(result.error || ''));
                        showAlert(`資料庫寫入失敗：${result.error}${needsDetail ? sent : ''}`
                            + `${(result.status === 401 && result.code !== 'PRODUCT_UPSTREAM_REJECTED') ? '（登入狀態已失效，請重新登入）' : ''}`, { type: 'error' });
                    }
                    return false;
                }
                // 新增與編輯都用對話框確認，不只是一個會自己消失的 toast。
                // 寫進資料庫是不可逆的動作，而 toast 幾秒後就沒了——
                // 人離開座位再回來，會分不出「成功了」與「根本沒送出」。
                // showAlert 只認得 type 與 onOk，沒有 title 這個選項——
                // 傳了會被安靜忽略，所以標題要寫進訊息本身。
                showAlert(okMsg, { type: 'success' });
                Router.generalProductCatalog = null; // 讓商品頁下次重抓最新清單
                // 排序回到「最新在上」，讓剛動過的那一筆直接出現在第一列。
                const sortEl = document.getElementById('adminProductSort');
                if (sortEl && !editingProductId) sortEl.value = 'newest';
                loadAdminProducts();
                loadProductAuditLogs();
                return true;
            };
            if (editingProductId) {
                const target = (dbProducts || []).find(p => String(p.id) === String(editingProductId));
                delete payload.type;
                Api.patchRemoteProduct(target?.rawId, payload, target?.version).then(result => {
                    if (finish(result, '產品已更新並寫入資料庫')) exitEditMode();
                });
            } else {
                Api.createRemoteProduct(payload).then(result => {
                    if (finish(result, '產品已新增並寫入資料庫')) productForm.reset();
                });
            }
        };

        // ═══ 模型修正複核 ═══
        // 使用者按「這判斷不準」改過的每一筆，攤開讓管理員第二次檢查。
        //
        // 這些修正會直接變成重訓的標籤，而寫進去之前沒有任何人看過——使用者可能誤點，
        // 也可能自己判斷錯（眉型、唇型本來就主觀）。一筆錯的標籤進了訓練集，
        // 之後分數變差很難查回是哪來的。
        //
        // 後端不回任何身分欄位（見 face_feedback.py 的 list_feedback 說明），
        // 所以這張表只有「模型答什麼、使用者改成什麼」，沒有誰改的。
        const feedbackBody = document.getElementById('adminFeedbackBody');
        if (feedbackBody) {
          // 這一段接近九百行，中間任何一個例外都會讓後面的事件綁定**整批不執行**：
          // 畫面看起來是完整的，但「全選可送訓」「送去訓練」按下去毫無反應，
          // 訓練批次也停在初始佔位字上——看起來像功能被拿掉了，其實是初始化半路死掉。
          // 例外只留在 console 的話，使用者回報的永遠是「按了沒反應」，
          // 而那句話沒有指向任何一行程式。所以把它接住並寫到畫面上。
          try {
            const fbState = document.getElementById('adminFeedbackState');
            const fbSummary = document.getElementById('adminFeedbackSummary');
            const fbRefresh = document.getElementById('adminFeedbackRefresh');
            const fbTabButtons = Array.from(document.querySelectorAll('[data-fb-tab]'));
            const fbCounts = Array.from(document.querySelectorAll('[data-fb-count]'));
            let fbTab = 'pending';
            const fbTrain = document.getElementById('adminFeedbackTrain');
            const fbPickAll = document.getElementById('adminFeedbackPickAll');
            const fbTrainingPanel = document.getElementById('adminFeedbackTraining');
            const fbCurrentScore = document.getElementById('adminFeedbackCurrentScore');
            const fbRuns = document.getElementById('adminFeedbackRuns');
            const FB_HINT = '使用者修正過的五官判斷。每一筆都會成為重訓的標籤，請逐筆確認合理再採用。';

            const fbSetState = (text, cls) => {
                if (!fbState) return;
                fbState.textContent = text;
                fbState.className = `admin-crawler-state ${cls}`;
            };
            const fbTime = (iso) => {
                if (!iso) return '—';
                const d = new Date(iso);
                if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
                const p = (n) => String(n).padStart(2, '0');
                return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
            };

            // 這一批回饋的原始資料。留著才能在切換「只看待覆核」或改完某一筆之後
            // 重畫，而不必再打一次 API——重打會讓剛按下的那一筆閃一下才更新。
            let fbItems = [];
            const fbSelected = new Set();

            // 卡片右上角那個標籤。跟分頁是同一組語彙，不然同一筆在分頁叫「送訓中」、
            // 卡片上叫「已採用」，看的人得自己在腦中對應。
            const FB_BUCKET_LABEL = {
                pending: '待覆核',
                training: '送訓中',
                trained: '送訓完成',
                rejected: '退回',
            };
            const FB_REVIEW_LABEL = {
                accepted: '已採用',
                rejected: '已退回',
                partial: '部分採用',
                pending: '待覆核',
            };

            const fbApprovedFields = (it) => {
                const decisions = it.reviewDecisions || {};
                const changes = Array.isArray(it.changes) ? it.changes : [];
                return changes.filter(c => decisions[c.field] === 'accepted'
                    || (decisions[c.field] === 'corrected' && (it.reviewLabels || {})[c.field]))
                    .map(c => c.field);
            };

            // 採用過、有影像、而且還沒進過任何批次的那些。
            //
            // 「採用」跟「送去訓練」本來就是同一件事——採用的意思就是「這個標註可以拿去
            // 訓練」。所以按鈕預設就對準這一堆，不必再勾一次；勾選只是想單獨送某幾筆時
            // 才用得到。已經有 trainingRunId 的不再列入，否則每按一次就重送一遍舊資料。
            // 可以送訓的：已採用（或部分採用）、有影像、還沒進過任何批次、而且真的有
            // 被採用的部位。
            //
            // ⚠️ 不能用 `fbBucket(it) === 'accepted'` 判斷——fbBucket **不會**回傳
            // 'accepted'。它只回 pending／training／trained／rejected 四種，
            // 而「已採用但還沒送出」被歸在 pending（因為那還需要你動手）。
            // 拿一個永遠不成立的條件去過濾，結果是可送訓永遠 0 筆：
            // 按鈕永遠寫「已採用未送訓 0」，全選框因為 all.length === 0 而是 disabled，
            // 勾了完全沒有反應——看起來像功能壞了，其實是這一行在找一個不存在的值。
            const fbTrainable = () => fbItems.filter(it =>
                (it.reviewStatus === 'accepted' || it.reviewStatus === 'partial')
                && it.hasSample && !it.trainingRunId && fbApprovedFields(it).length);

            const fbTrainTargets = () => (fbSelected.size
                ? [...fbSelected]
                : fbTrainable().map(it => it.feedbackId || it.jobId));

            // 全選框的三態：全勾打勾、全空清掉、勾一部分顯示 indeterminate。
            // 少了中間那個狀態，勾兩筆時全選框看起來像「沒勾」，
            // 直覺會再按一下想全選，實際上那一下是取消——按了反而更少。
            const fbSyncPickAll = () => {
                if (!fbPickAll) return;
                const all = fbTrainable().map(it => it.feedbackId || it.jobId);
                const picked = all.filter(id => fbSelected.has(id)).length;
                fbPickAll.disabled = all.length === 0;
                fbPickAll.checked = all.length > 0 && picked === all.length;
                fbPickAll.indeterminate = picked > 0 && picked < all.length;
            };

            // 還沒載到資料之前，按鈕不要說出任何數字——同上，0 是一個宣稱。
            let fbLoaded = false;
            const fbUpdateTrainButton = () => {
                // 掛在這裡而不是逐一去補呼叫點：按鈕文字與全選框說的是同一件事
                // （現在會送出哪幾筆），兩者分開更新遲早會有一邊忘了跟上。
                fbSyncPickAll();
                if (!fbTrain) return;
                // 還沒載到就不要報數字。「已採用未送訓 0」是一個關於資料的宣稱，
                // 而這時候我們什麼都還不知道。
                if (!fbLoaded) { fbTrain.textContent = '送去訓練'; fbTrain.disabled = true; return; }
                const n = fbTrainTargets().length;
                fbTrain.textContent = fbSelected.size
                    ? `送去訓練（已選 ${n}）`
                    : `送去訓練（已採用未送訓 ${n}）`;
                fbTrain.disabled = n === 0;
                fbTrain.title = fbSelected.size
                    ? '只送出你勾選的這幾筆'
                    : '把所有已採用、有影像、還沒送過訓練的修正送出成一個批次';
            };

            // 覆核的單位是「一筆回饋」，不是單一部位：後端的 reviewStatus 寫在文件層級，
            // 一筆修正裡的三個部位是同一次送出的，沒有辦法只採用其中一個。
            //
            // 2026-08-24 從表格改成卡片：一筆一張卡，那個人的所有修正、樣本影像、
            // 覆核按鈕都在同一張裡。表格把一筆攤成好幾列，覆核的人得先在腦中把它們
            // 拼回同一次分析才有辦法判斷，而判斷本來就該一次看完再決定。
            //
            // 影像點開才載：ROI 雖小，108 筆一次全帶仍是幾 MB，而一次只看一筆。
            const fbSamples = {};   // feedbackId -> 'loading' | 陣列 | {error}

            // 管理員改判：使用者說的也不對時，給第三個答案。
            // 這是雙重驗證的關鍵——管理員看得到影像，使用者是憑印象改的，
            // 少了這個選項遇到兩邊都錯就只能整筆退回，等於丟掉一張最貴的樣本
            //（有影像、有人看過）。
            const fbOptions = (field, id, current) => {
                const opts = (typeof AnalysisFeedback !== 'undefined'
                    && AnalysisFeedback.OPTIONS[field]) || [];
                if (!opts.length) return '';
                return `<select class="fb-mini fb-fix" data-fb-id="${escapeHtml(id)}"
                    data-fb-field="${escapeHtml(field)}" title="兩邊都不對？改成正確的類別"
                    aria-label="${escapeHtml(field)}改判">
                  <option value="">改判…</option>
                  ${opts.map(o => `<option value="${escapeHtml(o)}"${
                    o === current ? ' selected' : ''}>${escapeHtml(o)}</option>`).join('')}
                </select>`;
            };

            // 影像的內容。狀態有四種：還沒抓、抓取中、抓到了、抓失敗。
            const sampleInner = (id) => {
                const st = fbSamples[id];
                if (st === undefined) return '<div class="fb-shots is-loading">影像準備中…</div>';
                if (st === 'loading') return '<div class="fb-shots is-loading">載入樣本影像…</div>';
                if (st && st.error) return `<div class="fb-shots is-error">${escapeHtml(st.error)}</div>`;
                if (!st.length) return '<div class="fb-shots is-empty">這一筆沒有影像（使用者沒有勾選同意提供）。</div>';
                return `<div class="fb-shots">${st.map(sp => sp.dataUrl
                    ? `<figure><img src="${sp.dataUrl}" alt="${escapeHtml(sp.part)} 樣本" loading="lazy">
                         <figcaption>${escapeHtml(sp.part)}<br><b>${escapeHtml(sp.label)}</b></figcaption></figure>`
                    : `<figure class="is-skipped"><div class="fb-skip">${escapeHtml(sp.skipped || '未載入')}</div>
                         <figcaption>${escapeHtml(sp.part)}</figcaption></figure>`).join('')}</div>`;
            };

            // 影像一律顯示，不必按開。要判斷眉型、唇型改得對不對，本來就得看到形狀；
            // 每一筆都先點一次「看樣本影像」，等於在每一筆上多收一次過路費。
            //
            // 但也不能一進畫面就把 100 多筆的圖全抓下來——那是好幾 MB，而且多數還沒捲到。
            // 折衷是捲到哪抓到哪：卡片進入視窗（含前方 300px）才去抓那一筆。
            const sampleHtml = (id, hasSample) => {
                if (!hasSample) return '';
                return `<div class="fb-shots-slot" data-fb-slot="${escapeHtml(id)}">${sampleInner(id)}</div>`;
            };

            // 抓到之後只換那一張卡片裡的影像區，不重畫整份清單：
            // 每抓到一筆就整份重畫的話，正在捲動的畫面會不斷跳掉。
            const paintSamples = (id) => {
                const slot = feedbackBody.querySelector(`[data-fb-slot="${CSS.escape(id)}"]`);
                if (slot) slot.innerHTML = sampleInner(id);
            };

            // 同時最多抓三筆。不限制的話，一次捲過去會同時送出十幾個請求，
            // 每個都可能回幾百 KB 的 data URL，反而讓最該先看到的那一筆最慢到。
            const sampleQueue = [];
            let sampleActive = 0;
            const pumpSamples = () => {
                while (sampleActive < 3 && sampleQueue.length) {
                    const id = sampleQueue.shift();
                    sampleActive += 1;
                    fbSamples[id] = 'loading';
                    paintSamples(id);
                    Api.fetchFaceFeedbackSamples(id).then((res) => {
                        fbSamples[id] = res.ok ? res.samples : { error: res.error || '讀取失敗' };
                    }).catch((err) => {
                        fbSamples[id] = { error: (err && err.message) || '讀取失敗' };
                    }).then(() => {
                        paintSamples(id);
                        sampleActive -= 1;
                        pumpSamples();
                    });
                }
            };

            let sampleObserver = null;
            const watchSamples = () => {
                if (sampleObserver) sampleObserver.disconnect();
                if (typeof IntersectionObserver !== 'function') {
                    // 舊瀏覽器沒有這個 API：那就全部排隊抓，慢一點但看得到。
                    feedbackBody.querySelectorAll('[data-fb-slot]').forEach((el) => {
                        if (fbSamples[el.dataset.fbSlot] === undefined) sampleQueue.push(el.dataset.fbSlot);
                    });
                    pumpSamples();
                    return;
                }
                sampleObserver = new IntersectionObserver((entries) => {
                    entries.forEach((entry) => {
                        if (!entry.isIntersecting) return;
                        const id = entry.target.dataset.fbSlot;
                        sampleObserver.unobserve(entry.target);
                        if (fbSamples[id] === undefined && !sampleQueue.includes(id)) {
                            sampleQueue.push(id);
                            pumpSamples();
                        }
                    });
                }, { rootMargin: '300px 0px' });
                feedbackBody.querySelectorAll('[data-fb-slot]').forEach(el => sampleObserver.observe(el));
            };

            const fbRender = (items) => {
                if (!items.length) {
                    // 三個分頁的「空」代表三件不同的事，訊息要跟著分頁走，
                    // 否則在「已退回」看到「都看過了」會讓人以為自己站錯頁。
                    const emptyText = {
                        pending: '沒有待覆核的紀錄——都看過了。',
                        accepted: '還沒有採用過任何修正。採用之後它們會出現在這裡，並成為下一次訓練的標籤。',
                        rejected: '沒有退回的紀錄。退回的修正不會進訓練集，樣本影像也會一併刪除。',
                    };
                    feedbackBody.innerHTML = `<div class="admin-empty">${escapeHtml(emptyText[fbTab] || '目前沒有使用者修正紀錄。')}</div>`;
                    fbUpdateTrainButton();
                    return 0;
                }
                feedbackBody.innerHTML = items.map(it => {
                    const changes = Array.isArray(it.changes) ? it.changes : [];
                    const status = it.reviewStatus || 'pending';
                    const id = it.feedbackId || it.jobId || '';
                    const decisions = it.reviewDecisions || {};
                    const decided = changes.filter(c => decisions[c.field]).length;
                    const approvedFields = fbApprovedFields(it);
                    const selectable = Boolean(it.hasSample && approvedFields.length);
                    return `
                    <!-- awaiting：已採用但還沒進任何批次。這一類在畫面上要跟「已送訓」分得開，
                         否則一百張卡片長一樣，而其中只有二十張還需要動作。 -->
                    <article class="fb-card ${escapeHtml(status)}${status === 'accepted' && !it.trainingRunId ? ' awaiting' : ''}" data-fb-row="${escapeHtml(id)}">
                      <header class="fb-card-head">
                        <div>
                          <!-- 勾選框只出現在「可以送訓」的卡片上（已採用、有影像、
                               還沒進過批次）。不能送的不給勾，是為了讓「勾了 N 筆」
                               跟「會送出 N 筆」永遠是同一個數字——勾得到卻送不出去，
                               按鈕上的數字就開始說謊。 -->
                          ${selectable ? `<label class="fb-pick" title="選進這次的訓練批次">
                            <input type="checkbox" data-fb-pick="${escapeHtml(id)}"${fbSelected.has(id) ? ' checked' : ''}>
                          </label>` : ''}
                          <span class="fb-when">${escapeHtml(fbTime(it.createdAt))}</span>
                          <span class="fb-mode">${escapeHtml(String(it.mode || '—').toUpperCase())}</span>
                          <span class="fb-job">${escapeHtml(it.jobId || '—')}</span>
                        </div>
                        <span class="fb-review-state">${escapeHtml(FB_BUCKET_LABEL[fbBucket(it)] || status)}${
                          changes.length ? ` <em>${decided}/${changes.length}</em>` : ''}</span>
                      </header>
                      <!-- 兩個結果要在卡片上看得到，否則管理員無從確認自己按下去的事真的發生了：
                           送過訓練的要顯示是哪一批，退回的要顯示影像已經真的刪掉。 -->
                      ${it.trainingRunId ? `<div class="fb-trace fb-trace-run">已進訓練批次 <code>${escapeHtml(it.trainingRunId)}</code></div>` : ''}
                      ${it.samplesDeletedAt ? `<div class="fb-trace fb-trace-del">樣本影像已於 ${escapeHtml(fbTime(it.samplesDeletedAt))} 從儲存空間刪除</div>` : ''}
                      <div class="fb-changes">${changes.length ? changes.map(c => {
                        // 每個部位各自決定：管理員可能覺得嘴型改得對、眼型改錯了。
                        // 整筆一個狀態等於逼人在「全收一個錯的」與「連對的一起丟掉」之間選。
                        const fd = decisions[c.field] || '';
                        // 這裡曾經每一列都印「ConvNeXt 信心」。它幾乎永遠是「—」
                        // （predictionConfidence 多數紀錄根本沒有這個欄位），
                        // 而覆核靠的是看影像，不是看模型有多有把握——
                        // 一個常態顯示「沒有值」的欄位，只是在每一列上收一次視線。
                        return `
                        <div class="fb-change ${fd ? 'decided ' + escapeHtml(fd) : ''}">
                          <span class="fb-field">${escapeHtml(c.field || '—')}</span>
                          <span class="fb-was">${escapeHtml(c.predicted ?? '—')}</span>
                          <span class="fb-arrow" aria-hidden="true">→</span>
                          <span class="fb-now">${escapeHtml(c.corrected ?? '—')}</span>
                          <span class="fb-one">
                            <!-- 三態，不是兩態。
                                 先前不論已採用、已進批次，按鈕文字都是「送訓」，只是變灰——
                                 而一顆寫著「送訓」的灰按鈕讀起來仍然是「可以送」，
                                 於是已經送過的還會被再送一次。文字要跟著狀態走。 -->
                            <button type="button" class="fb-mini fb-accept${fd === 'accepted' ? (it.trainingRunId ? ' is-queued' : ' is-accepted') : ''}"
                              data-fb-id="${escapeHtml(id)}"
                              data-fb-field="${escapeHtml(c.field)}" data-fb-decision="accepted"
                              ${fd === 'accepted' ? 'disabled' : ''}
                              title="${fd === 'accepted'
                                ? (it.trainingRunId ? '這個部位已經收進批次 ' + escapeHtml(it.trainingRunId) : '已採用，等待送出下一個訓練批次')
                                : '使用者說的對，這個部位收進下一次訓練'}"
                              >${fd === 'accepted' ? (it.trainingRunId ? '已送訓' : '待送訓') : '送訓'}</button>
                            <!-- 這裡沒有「退回」：使用者說錯了就直接從右邊的選單改成正確答案，
                                 那比退回有用——退回只是丟掉一張圖，改判會留下一個正確的標籤。 -->
                            ${fbOptions(c.field, id, decisions[c.field] === 'corrected'
                              ? (it.reviewLabels || {})[c.field] : '')}
                          </span>
                        </div>`;
                      }).join('') : '<div class="fb-change fb-none">這一筆沒有修正內容</div>'}
                      </div>
                      ${sampleHtml(id, it.hasSample)}
                      <footer class="fb-card-foot">
                        <span class="fb-foot-left">
                          ${it.hasSample ? '' : '<span class="fb-no-sample">沒有影像可看</span>'}
                          ${it.reviewedAt ? `<span class="fb-reviewed-at">覆核於 ${escapeHtml(fbTime(it.reviewedAt))}</span>` : ''}
                        </span>
                        <span class="fb-review-buttons">
                          <button type="button" class="fb-accept${status === 'accepted' ? (it.trainingRunId ? ' is-queued' : ' is-accepted') : ''}"
                            data-fb-id="${escapeHtml(id)}"
                            data-fb-decision="accepted" ${status === 'accepted' ? 'disabled' : ''}
                            >${status === 'accepted' ? (it.trainingRunId ? '已送訓' : '待送訓') : '全部送訓'}</button>
                          <!-- 排除這張 = 整筆 rejected。留著它不是為了否定使用者的判斷（那用改判），
                               而是為了**照片本身不能用**的情況：沒對到臉、戴口罩、糊掉。
                               那種照片改判也救不回來，而它是唯一會把影像從 GCS 真的刪掉的動作。 -->
                          <button type="button" class="fb-reject" data-fb-id="${escapeHtml(id)}"
                            data-fb-decision="rejected" ${status === 'rejected' ? 'disabled' : ''}
                            title="照片不能用（沒對到臉、戴口罩、糊掉）。影像會從儲存空間刪除">排除這張</button>
                        </span>
                      </footer>
                    </article>`;
                }).join('');
                // 每次重畫都要重新掛觀察器：舊的那些節點已經被 innerHTML 換掉了。
                watchSamples();
                fbUpdateTrainButton();
                return items.length;
            };

            // 分頁歸屬。partial（只採用了部分部位）歸在「已送訓」而不是待覆核：
            // 它已經有東西進了訓練批次，再放回待辦會讓人以為那些部位還沒處理。
            // 批次 id → 批次狀態。loadTrainingRuns 拿到資料後填進來，
            // 讓每一筆回饋知道自己那一批跑完了沒。
            const fbRunStatus = new Map();

            // 四個分頁對應四個**還在進行中的位置**，不是三個覆核決定。
            //
            // 先前是 待覆核／已採用／已排除，而「已採用」把兩種完全不同的狀態混在一起：
            // 已經採用但**還沒送進任何批次**的，跟已經在跑的。一百張卡片長一樣，
            // 其中只有二十張還需要動作——2026-08-27 因此把已經送過的又送了一次。
            //
            // 現在「待覆核」的定義是**還需要你動手的**：沒覆核過的，加上覆核了卻還沒送出的。
            // 送出之後那一格就會清空，這正是使用者要的行為。
            const fbBucket = (item) => {
                const status = item.reviewStatus || 'pending';
                if (status === 'rejected') return 'rejected';
                if (status === 'accepted' || status === 'partial') {
                    const runId = item.trainingRunId;
                    if (!runId) return 'pending';        // 採用了但還沒送出 → 仍然要你動手
                    const runState = fbRunStatus.get(runId);
                    // 查不到那一批的狀態時當成還在跑：說「完成了」而其實沒有，
                    // 比說「還在跑」而其實跑完了糟——前者會讓人以為模型已經更新。
                    return runState === 'done' ? 'trained' : 'training';
                }
                return 'pending';
            };
            // 剛剛在這個分頁上處理過的那幾筆。
            //
            // 沒有它的話，按下「送訓」的瞬間卡片就會跳到「已送訓」分頁——
            // 從待覆核清單上消失。連續處理十筆的時候，畫面每按一次就重排一次，
            // 手指還停在原地，下一張卡已經捲上來了，很容易誤按。
            //
            // 所以處理過的留在原地（狀態標籤會變），直到切換分頁或重新載入才歸位。
            const fbJustDecided = new Set();

            const fbVisible = () => fbItems.filter(it =>
                fbBucket(it) === fbTab || fbJustDecided.has(it.feedbackId || it.jobId));

            const fbRepaint = () => {
                [...fbSelected].forEach(id => {
                    const item = fbItems.find(it => (it.feedbackId || it.jobId) === id);
                    if (!item || !item.hasSample || !fbApprovedFields(item).length) fbSelected.delete(id);
                });
                const n = fbRender(fbVisible());
                const pending = fbItems.filter(it => fbBucket(it) === 'pending').length;
                const training = fbItems.filter(it => fbBucket(it) === 'training').length;
                const trained = fbItems.filter(it => fbBucket(it) === 'trained').length;
                const rejected = fbItems.filter(it => fbBucket(it) === 'rejected').length;
                const bucketCounts = { pending, training, trained, rejected };
                fbCounts.forEach((el) => { el.textContent = String(bucketCounts[el.dataset.fbCount] ?? 0); });
                fbTabButtons.forEach((btn) => {
                    btn.setAttribute('aria-selected', String(btn.dataset.fbTab === fbTab));
                });
                fbSetState(pending ? `${pending} 筆待覆核` : (fbItems.length ? '全部已覆核' : '沒有資料'),
                    pending ? 'loading' : (fbItems.length ? 'success' : 'idle'));
                if (fbSummary) {
                    // ⚠️ 這裡只能用上面算出來的四個桶。分頁從三個變四個之後，這一行還留著
                    // 舊的 `accepted`，而它已經不存在了——每次重畫都在這裡拋 ReferenceError。
                    //
                    // 拋在這個位置特別難查：卡片與計數在它之前就畫完了，畫面看起來正常，
                    // 但它之後的每一行都沒執行，包括呼叫端下一行的 loadTrainingRuns()。
                    // 症狀因此是「訓練批次永遠載不出來」，而錯誤只留在 console。
                    fbSummary.textContent = fbItems.length
                        // 講清楚採用的那些會怎麼被用掉：這是唯一會改到訓練集的動作。
                        ? `${FB_HINT}（共 ${fbItems.length} 筆／待覆核 ${pending}、送訓中 ${training}、`
                          + `送訓完成 ${trained}、已退回 ${rejected}；`
                          + `已採用的會被 training/import_feedback_samples.py 收進下一次重訓）`
                        : '目前沒有使用者修正紀錄。等有人按過「這判斷不準」之後，紀錄會出現在這裡。';
                }
                return n;
            };

            const TRAIN_PART_ZH = {
                face_shape: '臉型', brow_shape: '眉型', eye_shape: '眼型',
                nose_shape: '鼻型', lip_shape: '唇型',
            };
            const TRAIN_STATUS_ZH = {
                queued: '已登記', running: '訓練中', done: '已完成', failed: '失敗',
            };

            // read_model_metrics() 回的是 { architecture, parts: { 部位: {...} } }，
            // 但更早的紀錄是把部位直接攤在最上層。兩種都要讀得出來，否則舊批次會
            // 顯示成「沒有指標」——那不是事實，而且正好是最該拿來對照的那幾筆。
            const trainParts = (metrics) => {
                if (!metrics || typeof metrics !== 'object') return {};
                const parts = metrics.parts && typeof metrics.parts === 'object' ? metrics.parts : metrics;
                return Object.fromEntries(Object.entries(parts).filter(([key, value]) =>
                    TRAIN_PART_ZH[key] && value && typeof value === 'object'));
            };
            const trainMacro = (entry) => {
                const raw = Number(entry?.macroAccuracy ?? entry?.accuracy);
                return Number.isFinite(raw) ? raw : null;
            };
            const trainPct = (value) => `${(value * 100).toFixed(1)}%`;

            // 訓練前後對照。只列出兩邊都有數字的部位——單邊有值算不出差距，
            // 硬是把缺的那邊當 0 會憑空生出一個 +65% 的假進步。
            const trainDeltaHtml = (before, after) => {
                const b = trainParts(before);
                const a = trainParts(after);
                const rows = Object.keys(TRAIN_PART_ZH).map((part) => {
                    const mb = trainMacro(b[part]);
                    const ma = trainMacro(a[part]);
                    if (mb == null && ma == null) return '';
                    if (mb == null || ma == null) {
                        const only = ma == null ? mb : ma;
                        return `<div class="atb-delta-row"><span>${escapeHtml(TRAIN_PART_ZH[part])}</span>`
                            + `<span class="atb-delta-only">${escapeHtml(trainPct(only))}（僅單邊有紀錄）</span></div>`;
                    }
                    const diff = ma - mb;
                    const dir = diff > 0.0005 ? 'up' : (diff < -0.0005 ? 'down' : 'flat');
                    const arrow = dir === 'up' ? '↑' : (dir === 'down' ? '↓' : '→');
                    return `<div class="atb-delta-row"><span>${escapeHtml(TRAIN_PART_ZH[part])}</span>`
                        + `<span class="atb-delta-nums">${escapeHtml(trainPct(mb))} <i>${arrow}</i> ${escapeHtml(trainPct(ma))}`
                        + `<b class="atb-${dir}">${diff >= 0 ? '+' : ''}${(diff * 100).toFixed(1)}</b></span></div>`;
                }).filter(Boolean).join('');
                return rows || '';
            };

            // 這個批次送了哪些部位、各幾張。selections 的形狀是
            // { "FB-xxx": { "眉型": "落尾眉", ... } }，中文欄位名就是使用者改的那一項。
            const trainFieldChips = (run) => {
                const counts = {};
                Object.values(run?.selections || {}).forEach((fields) => {
                    Object.keys(fields || {}).forEach((field) => {
                        counts[field] = (counts[field] || 0) + 1;
                    });
                });
                const chips = Object.entries(counts).sort((x, y) => y[1] - x[1]);
                return chips.length
                    ? chips.map(([field, n]) => `<span class="atb-chip">${escapeHtml(field)} ${n}</span>`).join('')
                    : '';
            };

            const trainDuration = (run) => {
                if (!run?.startedAt || !run?.finishedAt) return '';
                const ms = new Date(run.finishedAt) - new Date(run.startedAt);
                if (!Number.isFinite(ms) || ms <= 0) return '';
                const min = Math.floor(ms / 60000);
                const sec = Math.round((ms % 60000) / 1000);
                return min ? `${min} 分 ${sec} 秒` : `${sec} 秒`;
            };

            const renderTrainingRuns = (data) => {
                if (fbTrainingPanel) fbTrainingPanel.hidden = false;
                const currentParts = trainParts(data?.currentMetrics);
                const currentEntries = Object.entries(currentParts)
                    .map(([part, value]) => [part, trainMacro(value)])
                    .filter(([, macro]) => macro != null);
                if (fbCurrentScore) {
                    fbCurrentScore.textContent = currentEntries.length
                        ? `線上模型：${currentEntries.map(([part, macro]) => `${TRAIN_PART_ZH[part]} ${trainPct(macro)}`).join('／')}`
                        : '尚無已登記的線上模型指標';
                }
                const runs = Array.isArray(data?.runs) ? data.runs : [];
                if (!fbRuns) return;
                // 訓練機狀態放在批次清單的最前面：所有「為什麼還沒開始」的問題，
                // 答案都在這一行。
                const worker = trainWorkerInfo(data?.worker);
                const workerHtml = `<div class="atb-worker atb-worker-${worker.online ? 'on' : 'off'}">`
                    + `<i></i><span>${escapeHtml(worker.text)}</span>`
                    + `<button type="button" class="atb-recheck" data-worker-recheck>重新檢查</button></div>`
                    + (worker.hint ? `<div class="atb-worker-hint">${escapeHtml(worker.hint)}</div>` : '');
                if (!runs.length) {
                    fbRuns.innerHTML = workerHtml + '<div class="atb-empty">還沒有任何訓練批次。'
                        + '在下面的清單勾選已採用的修正，按「送去訓練」就會建立第一筆。</div>';
                    return;
                }
                // 委派到容器上，重畫之後不必重掛。鍵盤也要能開——卡片是 role="button"，
                // 只認滑鼠的話那個角色就是在說謊。
                if (!fbRuns.dataset.bound) {
                    fbRuns.dataset.bound = '1';
                    const openFromEvent = (ev) => {
                        // 「重新檢查」要先攔下來：它長在同一個容器裡，
                        // 不擋的話點它會順便去開下面那張卡片的進度視窗。
                        const recheck = ev.target.closest('[data-worker-recheck]');
                        if (recheck) {
                            recheck.disabled = true;
                            recheck.textContent = '檢查中…';
                            loadTrainingRuns();
                            return;
                        }
                        const card = ev.target.closest('[data-atb-run]');
                        if (card && card.dataset.atbRun) openTrainingProgress(card.dataset.atbRun);
                    };
                    fbRuns.addEventListener('click', openFromEvent);
                    fbRuns.addEventListener('keydown', (ev) => {
                        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openFromEvent(ev); }
                    });
                }
                fbRuns.innerHTML = workerHtml + runs.map((run) => {
                    const status = String(run.status || 'queued');
                    const statusZh = TRAIN_STATUS_ZH[status] || status;
                    const delta = trainDeltaHtml(run.modelBefore, run.modelAfter);
                    const chips = trainFieldChips(run);
                    const excluded = Array.isArray(run.excluded) ? run.excluded : [];
                    const duration = trainDuration(run);
                    // 時間鏈刻意分三格顯示：建立是後台寫的，開始與完成是訓練腳本寫的。
                    // 一個只有「建立」有時間的批次，就是還沒有人真的去訓練——這件事要一眼看得出來。
                    // 整張卡可以點開進度視窗。訓練跑好幾分鐘，人會想中途回來看一眼，
                    // 而批次編號本身就是那個視窗要追的東西。
                    return `
                        <article class="atb-run atb-${escapeHtml(status)}" role="button" tabindex="0"
                                 data-atb-run="${escapeHtml(run.runId || '')}"
                                 title="點開看這個批次的進度">
                            <header class="atb-run-head">
                                <b>${escapeHtml(run.runId || '—')}</b>
                                <span class="atb-badge atb-badge-${escapeHtml(status)}">${escapeHtml(statusZh)}</span>
                                <span class="atb-model">${escapeHtml(run.model || 'ConvNeXt-Tiny')}</span>
                            </header>
                            <div class="atb-steps">
                                <div class="atb-step"><span>建立（後台）</span><b>${escapeHtml(fbTime(run.createdAt))}</b></div>
                                <div class="atb-step ${run.startedAt ? '' : 'atb-step-wait'}"><span>開始訓練（腳本）</span><b>${escapeHtml(fbTime(run.startedAt))}</b></div>
                                <div class="atb-step ${run.finishedAt ? '' : 'atb-step-wait'}"><span>訓練完成（腳本）</span><b>${escapeHtml(fbTime(run.finishedAt))}${duration ? `　${escapeHtml(duration)}` : ''}</b></div>
                            </div>
                            <div class="atb-samples">
                                <span>送出 <b>${escapeHtml(String(run.sampleCount ?? 0))}</b> 個部位標註，來自
                                    <b>${escapeHtml(String((run.feedbackIds || []).length))}</b> 筆使用者修正</span>
                                ${chips ? `<div class="atb-chips">${chips}</div>` : ''}
                            </div>
                            ${delta ? `<div class="atb-delta"><span class="atb-delta-title">訓練前 → 訓練後（按人切分 macro）</span>${delta}</div>`
                                : `<div class="atb-pending">${escapeHtml(status === 'done'
                                    ? '這次沒有回寫指標'
                                    : '尚未有訓練前後指標——要等本機訓練腳本帶著這個批次編號跑完才會出現。')}</div>`}
                            ${excluded.length ? `<details class="atb-excluded"><summary>${excluded.length} 筆未納入</summary><ul>`
                                + excluded.map(item => `<li>${escapeHtml(item.feedbackId || '—')}：${escapeHtml(item.reason || '未說明')}</li>`).join('')
                                + '</ul></details>' : ''}
                        </article>`;
                }).join('');
            };

            // 這一塊只有三種合法的畫面：載入中、載到了、失敗（帶原因）。
            //
            // 沒有第四種「維持原本那句佔位字」。2026-08-28 就卡在那裡：畫面一直寫著
            // 「尚未載入訓練批次。」與「目前指標載入中…」，那是 admin.html 的初始文字，
            // 看不出是還沒開始、正在跑、還是失敗了——三種情況的處理方式完全不同，
            // 而畫面對三種都給同一句話。
            //
            // 所以：進來先蓋掉佔位字，任何離開路徑都必須留下一句說明。
            const loadTrainingRuns = async () => {
                if (fbRuns && !fbRuns.dataset.painted) fbRuns.textContent = '訓練批次載入中…';
                if (fbCurrentScore && !fbCurrentScore.dataset.painted) {
                    fbCurrentScore.textContent = '線上模型指標載入中…';
                }
                let res;
                try {
                    res = await Api.fetchFaceTrainingRuns();
                } catch (err) {
                    // Api 那層已經包過 try/catch，走到這裡代表是它自己壞了。
                    // 吞掉的話畫面就永遠停在「載入中」，而那是在說謊。
                    if (fbRuns) fbRuns.textContent = `訓練批次讀取失敗：${err && err.message || err}`;
                    if (fbCurrentScore) fbCurrentScore.textContent = '線上模型指標讀取失敗';
                    return;
                }
                // 每一筆回饋要知道自己那一批跑完了沒，分頁才分得出「送訓中」與「送訓完成」。
                if (Array.isArray(res?.runs)) {
                    fbRunStatus.clear();
                    res.runs.forEach(r => { if (r && r.runId) fbRunStatus.set(r.runId, r.status); });
                    // 狀態可能剛從 running 變 done，卡片要跟著換分頁
                    if (fbItems.length) fbRepaint();
                }
                if (res.ok) {
                    try {
                        renderTrainingRuns(res);
                        if (fbRuns) fbRuns.dataset.painted = '1';
                        if (fbCurrentScore) fbCurrentScore.dataset.painted = '1';
                    } catch (err) {
                        // 畫的時候炸掉，畫面會停在「載入中」而資料其實已經拿到了。
                        if (fbRuns) fbRuns.textContent = `訓練批次顯示失敗：${err && err.message || err}`;
                    }
                    return;
                }
                const why = (res.status === 401 || res.status === 403)
                    ? '需要管理員身分，請重新登入後按「重新載入」'
                    : (res.error || `HTTP ${res.status || '未知錯誤'}`);
                if (fbRuns) fbRuns.textContent = `訓練批次讀取失敗：${why}`;
                if (fbCurrentScore) fbCurrentScore.textContent = `線上模型指標讀取失敗：${why}`;
            };

            // 訓練機在不在線。這是「批次還在排隊」唯一有意義的解釋來源：
            // 沒有這個資訊，管理員按下按鈕看到「已排隊」會以為系統壞了，
            // 但實際上只是他的電腦沒開——那兩件事的處理方式完全不同。
            const WORKER_ONLINE_MS = 90 * 1000;
            const trainWorkerInfo = (worker) => {
                const seen = worker?.lastSeenAt ? new Date(worker.lastSeenAt).getTime() : 0;
                const age = seen ? Date.now() - seen : Infinity;
                const online = Number.isFinite(age) && age < WORKER_ONLINE_MS;
                const ago = !Number.isFinite(age) ? ''
                    : age < 60000 ? '剛剛' : `${Math.floor(age / 60000)} 分鐘前`;
                const state = { idle: '待命中', training: '訓練中', offline: '已停止' }[worker?.state] || worker?.state || '';
                // 離線時要寫出「該做什麼」，不是只說「已停止」。
                //
                // 這個面板不能啟動訓練機——後台在瀏覽器裡、講話對象是 Cloud Run，
                // 而 Cloud Run 打不進本機網路。做一顆按不動的「啟動」按鈕比沒有更糟：
                // 出事時你會按它，然後以為自己處理過了。
                //
                // 所以這裡給的是「可以自己做的三件事」。看門狗每 5 分鐘會拉一次，
                // 所以「程式死掉」這個原因已經不需要人管；剩下的都是機器層面的，
                // 只有坐在那台電腦前面的人能處理。
                const hint = !seen
                    ? '訓練機從未回報過。請在那台電腦上執行 tools/setup_training_task.ps1 建立排程。'
                    : '訓練機超過 15 分鐘沒有回報。看門狗每 5 分鐘會自動拉一次，'
                      + '所以多半不是程式死掉，而是那台電腦關機、睡著或沒有登入。'
                      + '請確認它開著並且已登入；批次不會遺失，會等訓練機回來。';
                return {
                    online,
                    text: !seen
                        ? '訓練機從未回報過'
                        : `訓練機 ${worker.workerId || 'local'}：${ago}回報${state ? `（${state}）` : ''}`,
                    hint: online ? '' : hint,
                    // 排隊中的批次在訓練機離線時最需要被看到：那才是「現在有東西卡住」。
                    queued: 0,
                };
            };

            // 按下「送去訓練」之後的追蹤對話框。
            //
            // 為什麼要輪詢而不是直接回報結果：訓練發生在另一台機器上，需要好幾分鐘，
            // HTTP 回應不可能等那麼久。所以按鈕只能回「已登記」，真正的結論要追。
            //
            // 三種結局都要說得出口——完成、失敗（附原因）、以及**還沒開始**（訓練機沒開）。
            // 少了第三種，沒開電腦就會被顯示成一直轉圈，看起來像壞掉。
            let trainingPollTimer = null;
            const openTrainingProgress = (runId) => {
                if (!runId) return;
                document.getElementById('trainingProgressOverlay')?.remove();
                const overlay = document.createElement('div');
                overlay.id = 'trainingProgressOverlay';
                overlay.className = 'tp-overlay';
                overlay.innerHTML = `
                    <div class="tp-dialog" role="dialog" aria-modal="true" aria-labelledby="tpTitle">
                        <div class="tp-head">
                            <h3 id="tpTitle">送去訓練</h3>
                            <button class="tp-close" type="button" aria-label="關閉">×</button>
                        </div>
                        <div class="tp-body" id="tpBody"><div class="tp-line">建立中…</div></div>
                        <div class="tp-foot"><code>${escapeHtml(runId)}</code></div>
                    </div>`;
                document.body.appendChild(overlay);

                const stop = () => {
                    if (trainingPollTimer) { clearTimeout(trainingPollTimer); trainingPollTimer = null; }
                };
                const close = () => { stop(); overlay.remove(); loadTrainingRuns(); };
                overlay.querySelector('.tp-close').onclick = close;
                overlay.onclick = (e) => { if (e.target === overlay) close(); };

                const body = overlay.querySelector('#tpBody');
                const started = Date.now();
                const poll = async () => {
                    const res = await Api.fetchFaceTrainingRuns();
                    if (!res.ok) {
                        body.innerHTML = `<div class="tp-line tp-bad">讀不到訓練狀態：${escapeHtml(res.error || '未知錯誤')}</div>`
                            + '<div class="tp-hint">批次已經建立，不會因為這個畫面關掉而消失。稍後可以在上方的批次紀錄看結果。</div>';
                        return;
                    }
                    renderTrainingRuns(res);
                    const run = (res.runs || []).find(r => r.runId === runId);
                    const worker = trainWorkerInfo(res.worker);
                    if (!run) {
                        body.innerHTML = `<div class="tp-line">批次已建立，正在等待紀錄同步…</div>`;
                        trainingPollTimer = setTimeout(poll, 4000);
                        return;
                    }
                    const status = String(run.status || 'queued');
                    if (status === 'done') {
                        const delta = trainDeltaHtml(run.modelBefore, run.modelAfter);
                        body.innerHTML = '<div class="tp-line tp-good">訓練完成</div>'
                            + `<div class="tp-hint">共 ${escapeHtml(String(run.sampleCount ?? 0))} 個部位標註，`
                            + `耗時 ${escapeHtml(trainDuration(run) || '—')}。</div>`
                            + (delta ? `<div class="tp-delta">${delta}</div>` : '')
                            + '<div class="tp-hint">模型已產出在訓練機上，<b>還沒有換上線</b>——要不要換是另一個決定。</div>';
                        stop();
                        return;
                    }
                    if (status === 'failed') {
                        body.innerHTML = '<div class="tp-line tp-bad">訓練失敗</div>'
                            + `<pre class="tp-error">${escapeHtml(run.error || '沒有取得錯誤訊息')}</pre>`
                            + '<div class="tp-hint">修正之後可以重新勾選同一批資料再送一次。</div>';
                        stop();
                        return;
                    }
                    if (status === 'running') {
                        const mins = Math.floor((Date.now() - new Date(run.startedAt || started).getTime()) / 60000);
                        body.innerHTML = '<div class="tp-line tp-busy">訓練中…</div>'
                            + `<div class="tp-hint">${escapeHtml(worker.text)}${mins ? `　已經 ${mins} 分鐘` : ''}。`
                            + '關掉這個視窗不會中斷訓練。</div>';
                    } else {
                        body.innerHTML = '<div class="tp-line tp-busy">已排入佇列</div>'
                            + `<div class="tp-hint tp-${worker.online ? 'good' : 'warn'}">${escapeHtml(worker.text)}</div>`
                            + `<div class="tp-hint">${worker.online
                                ? '訓練機在線，通常幾秒內就會開始。'
                                : '訓練機目前沒有在跑。<b>批次不會消失</b>——等你的電腦開機並執行 <code>python tools/training_worker.py</code>，它就會自動接手。'}</div>`;
                    }
                    trainingPollTimer = setTimeout(poll, 4000);
                };
                poll();
            };

            const loadAdminFeedback = async () => {
                if (fbRefresh) fbRefresh.disabled = true;
                fbSetState('載入中', 'loading');
                feedbackBody.innerHTML = '<div class="admin-empty">載入中…</div>';
                try {
                    const res = await Api.fetchFaceFeedback(100);
                    if (!res.ok) {
                        fbSetState('讀取失敗', 'error');
                        // 401/403 要講「重新登入」，其他錯誤講原因——兩者的下一步完全不同
                        const needLogin = res.status === 401 || res.status === 403;
                        if (fbSummary) {
                            fbSummary.textContent = needLogin
                                ? '需要管理員身分才能檢視，請重新登入後再試。'
                                : `讀取失敗：${res.error || '未知錯誤'}`;
                        }
                        feedbackBody.innerHTML =
                            `<div class="admin-empty">${escapeHtml(needLogin ? '未取得管理員權限' : (res.error || '讀取失敗'))}</div>`;
                        // 四個分頁的數字退回「—」。
                        //
                        // 這是這一整天最要緊的一條：**0 是一個關於資料的宣稱**，
                        // 意思是「我查過了，一筆都沒有」。沒載到卻寫 0，畫面就在說謊，
                        // 而它說的正好是最可怕的那句——「你的紀錄都不見了」。
                        // 使用者因此以為批次被刪掉了，實際上 Firestore 一筆都沒少。
                        fbCounts.forEach((el) => { el.textContent = '—'; });
                        fbLoaded = false;
                        // 回傳成敗，讓 _loadFeedbackOnce 知道這次能不能算「載過了」。
                        return false;
                    }
                    fbItems = Array.isArray(res.items) ? res.items : [];
                    fbLoaded = true;      // 到這裡才真的知道有幾筆
                    // 兩件獨立的事，不要讓其中一件的失敗連坐另一件。
                    // 2026-08-28：fbRepaint 用到一個不存在的變數而拋錯，
                    // 於是同一個 try 裡的 loadTrainingRuns() 從此沒被呼叫過一次——
                    // 訓練批次區永遠停在佔位字，而畫面上其他部分看起來完全正常。
                    try {
                        fbRepaint();
                    } catch (err) {
                        console.error('[admin] fbRepaint failed', err);
                        if (fbSummary) fbSummary.textContent = `清單重畫失敗：${err && err.message || err}`;
                    }
                    loadTrainingRuns();
                    return true;
                } finally {
                    if (fbRefresh) fbRefresh.disabled = false;
                }
            };

            // 採用／退回。用事件委派而不是逐列綁定：每次重畫都會換掉整個 tbody，
            // 逐列綁的處理器會跟著沒掉，得在每次 render 之後再綁一次——那正是這種
            // 表格最容易漏掉的一步。
            // 改判的下拉走 change。跟按鈕共用同一條送出路徑，
            // 差別只在多帶一個 labels——兩套送出邏輯遲早會分岔。
            feedbackBody.addEventListener('change', async (ev) => {
                // 勾選：只改本地的集合與按鈕文字，不打任何 API。
                // 勾選不是一個決定，是在「挑這次要送誰」——真正的決定是按下送去訓練。
                const pick = ev.target.closest('[data-fb-pick]');
                if (pick) {
                    const pid = pick.dataset.fbPick;
                    if (pick.checked) fbSelected.add(pid); else fbSelected.delete(pid);
                    fbUpdateTrainButton();
                    return;
                }
                const sel = ev.target.closest('.fb-fix');
                if (!sel || !sel.value) return;
                const id = sel.dataset.fbId, field = sel.dataset.fbField, label = sel.value;
                const card = sel.closest('.fb-card');
                const controls = card ? [...card.querySelectorAll('button[data-fb-decision], .fb-fix')] : [sel];
                controls.forEach(b => { b.dataset.wasDisabled = b.disabled ? '1' : ''; b.disabled = true; });
                const res = await Api.reviewFaceFeedback(id, { [field]: 'corrected' }, '', { [field]: label });
                if (!res.ok) {
                    controls.forEach(b => { b.disabled = b.dataset.wasDisabled === '1'; });
                    sel.value = '';
                    if (fbSummary) {
                        fbSummary.textContent = (res.status === 401 || res.status === 403)
                            ? '需要管理員身分才能覆核，請重新登入後再試。'
                            : `改判沒有寫進去：${res.error || '未知錯誤'}`;
                    }
                    return;
                }
                const hit = fbItems.find(it => (it.feedbackId || it.jobId) === id);
                if (hit) {
                    hit.reviewStatus = res.reviewStatus;
                    hit.reviewDecisions = res.reviewDecisions;
                    hit.reviewLabels = res.reviewLabels || {};
                    hit.reviewedAt = new Date().toISOString();
                }
                fbJustDecided.add(id);   // 留在原地，不要從清單上消失
                fbRepaint();
            });

            feedbackBody.addEventListener('click', async (ev) => {
                // 影像不再需要按開：卡片捲進畫面時 watchSamples() 會自己去抓。
                // 抓過的留在 fbSamples 裡，重畫時直接沿用——影像不會變，
                // 而且每次重打都要等 face-basic 冷啟動。
                const btn = ev.target.closest('[data-fb-decision]');
                if (!btn || btn.disabled) return;
                const id = btn.dataset.fbId;
                const decision = btn.dataset.fbDecision;
                const field = btn.dataset.fbField || '';   // 有這個就是只決定一個部位
                if (!id) return;

                const card = btn.closest('.fb-card');
                // 送出時把整張卡的按鈕都鎖住：連按兩顆不同的會讓後面那次覆蓋前面那次，
                // 而畫面上看不出發生了什麼。
                const buttons = card ? [...card.querySelectorAll('button[data-fb-decision]')] : [btn];
                buttons.forEach(b => { b.dataset.wasDisabled = b.disabled ? '1' : ''; b.disabled = true; });
                const stateEl = card?.querySelector('.fb-review-state');
                const before = stateEl?.innerHTML;
                if (stateEl) stateEl.textContent = '送出中…';

                const payload = field ? { [field]: decision } : decision;
                const res = await Api.reviewFaceFeedback(id, payload);
                if (!res.ok) {
                    // 失敗要把畫面改回去。留著「送出中」會讓人以為還在跑，
                    // 直接顯示新狀態則是騙人——後端根本沒收到。
                    if (stateEl && before != null) stateEl.innerHTML = before;
                    buttons.forEach(b => { b.disabled = b.dataset.wasDisabled === '1'; });
                    const needLogin = res.status === 401 || res.status === 403;
                    if (fbSummary) {
                        fbSummary.textContent = needLogin
                            ? '需要管理員身分才能覆核，請重新登入後再試。'
                            : `覆核沒有寫進去：${res.error || '未知錯誤'}`;
                    }
                    return;
                }
                // 本機同步同一筆的狀態再重畫，不重打 API。後端回的 reviewDecisions
                // 是合併過的完整結果，直接用它，不要自己在前端拼——拼錯的話畫面會
                // 顯示成功但下次載入又變回去。
                const hit = fbItems.find(it => (it.feedbackId || it.jobId) === id);
                if (hit) {
                    hit.reviewStatus = res.reviewStatus;
                    hit.reviewDecisions = res.reviewDecisions;
                    hit.reviewedAt = new Date().toISOString();
                }
                // 按下「送訓」就等於「這一筆我要送」——直接放進批次，不必再回頭勾一次。
                //
                // 先前要按兩次：卡片上按「送訓」只是把它標成已採用，還要再到上面勾一次
                // 才會計入「送去訓練」。那兩個動作在使用者眼裡是同一件事，
                // 而中間那一步沒有任何畫面在提醒。
                //
                // 只在「真的可以送」的時候加入：沒有影像、已經進過批次的不算，
                // 否則批次裡會出現訓練機拿不到資料的項目。
                if (res.reviewStatus === 'accepted' || res.reviewStatus === 'partial') {
                    const now = fbItems.find(it => (it.feedbackId || it.jobId) === id);
                    if (now && now.hasSample && !now.trainingRunId && fbApprovedFields(now).length) {
                        fbSelected.add(id);
                    }
                }
                fbJustDecided.add(id);   // 留在原地，不要從清單上消失
                fbRepaint();
            });

            if (fbPickAll) fbPickAll.onchange = () => {
                const all = fbTrainable().map(it => it.feedbackId || it.jobId);
                if (fbPickAll.checked) all.forEach(id => fbSelected.add(id));
                else all.forEach(id => fbSelected.delete(id));
                fbRepaint();
            };

            const fbSubmitTraining = async (ids) => {
                fbTrain.disabled = true;
                fbTrain.textContent = '登記中…';
                const res = await Api.queueFaceTraining(ids);
                if (!res.ok) {
                    fbTrain.textContent = `送訓失敗：${res.error || '未知錯誤'}`;
                    setTimeout(fbUpdateTrainButton, 2200);
                    return;
                }
                fbSelected.clear();
                // 送進批次的那幾筆本機先掛上 runId，讓它們立刻離開「待覆核」。
                //
                // 不掛的話它們會留在待覆核，看起來像沒送出去——而「待覆核」的意思是
                // **還需要你動手**，它們已經不是了。後端回的 runId 就是那一批的 id，
                // 下次重新載入時後端會給同一個值，所以這不是在前端編故事。
                //
                // fbJustDecided 也要清掉：那是「剛處理過、暫時留在原地不要跳走」的名單，
                // 批次都建好了還留著，卡片就會賴在待覆核不走。
                if (res.runId) ids.forEach(id => {
                    const hit = fbItems.find(it => (it.feedbackId || it.jobId) === id);
                    if (hit && !hit.trainingRunId) hit.trainingRunId = res.runId;
                });
                fbJustDecided.clear();
                fbRepaint();
                loadTrainingRuns();
                // 建立批次只是開始。真正要讓人知道的是「這次訓練成功了沒有」，
                // 所以按下去之後開一個對話框，把後續狀態追到有結論為止。
                openTrainingProgress(res.runId);
            };

            if (fbTrain) fbTrain.onclick = () => {
                const ids = fbTrainTargets();
                if (!ids.length) return;
                // 送訓不可逆：批次一建立訓練機就會撈走，而每一批都是**從頭重訓一次**
                // ——上一批只有一個部位也跑了 112 分鐘。按錯的代價不是多按一次，
                // 是佔住訓練機兩小時。所以問一次，並且把筆數講出來：
                // 勾選狀態可能早就捲出視野了，按鈕上的數字是唯一的線索。
                showConfirm(
                    `要把 ${ids.length} 筆修正送去訓練嗎？`
                    + (fbSelected.size ? '（你勾選的那幾筆）' : '（所有已採用、有影像、還沒送過的）')
                    + ' 送出後會建立一個訓練批次，訓練機會從頭重訓一次，需要數十分鐘到數小時。',
                    {
                        title: '確認送出訓練',
                        okText: `送出 ${ids.length} 筆`,
                        cancelText: '再看看',
                        onOk: () => fbSubmitTraining(ids),
                    });
            };

            // 切分頁時把勾選清空：勾選是為了「送去訓練」，而那個動作只對待覆核／
            // 已採用的資料有意義。留著看不見的勾選，按鈕上的數字就會對不上畫面。
            fbTabButtons.forEach((btn) => {
                btn.onclick = () => {
                    if (fbTab === btn.dataset.fbTab) return;
                    fbTab = btn.dataset.fbTab;
                    fbSelected.clear();
                    fbRepaint();
                };
            });
            if (fbRefresh) fbRefresh.onclick = loadAdminFeedback;
            // 切到這個區塊才載入，而且只自動載一次；之後要更新按「重新載入」。
            // 只在**載成功**之後才算「載過了」。
            //
            // 先前是一進來就把旗標設起來，於是第一次失敗（最常見的是登入還沒完成、
            // 後端回 401）之後就再也不會自己重試——切走再切回來、重新整理都沒用，
            // 因為旗標還在。而畫面上看到的是一個空的訓練批次區，
            // 沒有任何線索說「那次載入失敗了，再按一次就好」。
            Router._loadFeedbackOnce = async () => {
                if (Router._feedbackLoaded) return;
                const ok = await loadAdminFeedback();
                Router._feedbackLoaded = ok !== false;
            };
            if (document.querySelector('[data-admin-view="feedback"]:not([hidden])')) {
                Router._loadFeedbackOnce();
            }
          } catch (err) {
            const box = document.getElementById('adminFeedbackSummary')
                     || document.getElementById('adminFeedbackState')
                     || feedbackBody;
            if (box) {
                box.textContent = `模型修正複核初始化失敗：${err && err.message || err}`
                    + '（這一區的按鈕會沒有反應，請把這行訊息回報）';
            }
            console.error('[admin] feedback init failed', err);
          }
        }

        // ═══ 商品操作紀錄 ═══
        // 與模型修正複核同一種情況：畫面、表格、API 方法全都在，就是沒有人把它們接起來，
        // 按「重新載入」完全沒反應。既然是同一個模式，一起補完。
        const auditRows = document.getElementById('adminProductAuditRows');
        if (auditRows) {
            const auditBtn = document.getElementById('adminProductAuditReload');
            const auditTime = (iso) => {
                if (!iso) return '—';
                const d = new Date(iso);
                if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
                const p = (n) => String(n).padStart(2, '0');
                return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
            };
            const loadProductAudit = async () => {
                if (auditBtn) auditBtn.disabled = true;
                auditRows.innerHTML = '<tr><td colspan="4" class="admin-empty">載入中…</td></tr>';
                try {
                    const res = await Api.listProductAuditLogs(100);
                    if (!res.ok) {
                        const needLogin = res.status === 401 || res.status === 403;
                        auditRows.innerHTML =
                            `<tr><td colspan="4" class="admin-empty">${escapeHtml(needLogin ? '需要管理員身分才能檢視，請重新登入。' : (res.error || '讀取失敗'))}</td></tr>`;
                        return;
                    }
                    const logs = res.logs || [];
                    if (!logs.length) {
                        auditRows.innerHTML = '<tr><td colspan="4" class="admin-empty">目前沒有商品操作紀錄。</td></tr>';
                        return;
                    }
                    auditRows.innerHTML = logs.map(l => `
                        <tr>
                            <td>${escapeHtml(auditTime(l.createdAt || l.created_at || l.timestamp))}</td>
                            <td>${escapeHtml(l.action || l.operation || '—')}</td>
                            <td class="fb-job">${escapeHtml(String(l.productId ?? l.product_id ?? '—'))}</td>
                            <td>${escapeHtml(l.actor || l.operator || l.adminEmail || '—')}</td>
                        </tr>`).join('');
                } finally {
                    if (auditBtn) auditBtn.disabled = false;
                }
            };
            if (auditBtn) auditBtn.onclick = loadProductAudit;
            // 跟著商品管理區塊一起載入：使用者切到那一頁就是要看商品相關的東西。
            Router._loadProductAuditOnce = () => {
                if (Router._productAuditLoaded) return;
                Router._productAuditLoaded = true;
                loadProductAudit();
            };
        }

        const refreshAllBtn = document.getElementById('adminRefreshAllBtn');
        if (refreshAllBtn) refreshAllBtn.onclick = () => {
            loadAdminMembers();
            loadAdminProducts();
        };
        updateOverallStatus();
        render();
        renderProducts();
    }
};

// ═══ 初始化 ═══
// 密碼欄位的顯示／隱藏切換。打錯密碼卻看不到自己打了什麼，是登入失敗最沒必要的一種。
//
// 用觀察器而不是在每個渲染點各加一次：密碼欄散在登入、註冊、修改密碼、重設密碼四處
// 共八個，逐一加等於以後每多一個欄位就要記得回來補，而漏掉的那個不會有人發現——
// 它只是安靜地沒有切換鈕。這裡改成看到就補，含之後動態插進來的。
function enhancePasswordField(input) {
    if (!input || input.dataset.pwToggle) return;
    const group = input.closest('.input-group');
    if (!group) return;
    input.dataset.pwToggle = '1';
    group.classList.add('has-pw-toggle');

    const btn = document.createElement('button');
    btn.type = 'button';          // 不寫的話它在表單裡預設是 submit，按一下就送出
    btn.className = 'pw-toggle';
    btn.textContent = '顯示';
    btn.setAttribute('aria-label', '顯示密碼');
    btn.setAttribute('aria-pressed', 'false');
    btn.onclick = () => {
        const reveal = input.type === 'password';
        input.type = reveal ? 'text' : 'password';
        btn.textContent = reveal ? '隱藏' : '顯示';
        btn.setAttribute('aria-label', reveal ? '隱藏密碼' : '顯示密碼');
        btn.setAttribute('aria-pressed', String(reveal));
        // 切換後游標會被丟到開頭，使用者得再點一次才能接著打。補回尾端。
        input.focus();
        try { input.setSelectionRange(input.value.length, input.value.length); } catch (_) {}
    };
    group.appendChild(btn);
}

function watchPasswordFields() {
    const scan = (node) => {
        if (!node || node.nodeType !== 1) return;
        if (node.matches && node.matches('input[type="password"]')) enhancePasswordField(node);
        if (node.querySelectorAll) node.querySelectorAll('input[type="password"]').forEach(enhancePasswordField);
    };
    scan(document.body);
    if (typeof MutationObserver !== 'function') return;
    new MutationObserver(records => {
        records.forEach(record => record.addedNodes.forEach(scan));
    }).observe(document.body, { childList: true, subtree: true });
}

(function init() {
    watchPasswordFields();
    const routeFromHash = () => {
        const page = location.hash.replace(/^#/, '');
        if (ROUTE_PAGES.has(page) && Router.currentPage !== page) Router.go(page, { fromHash: true });
    };

    document.addEventListener('click', (e) => {
        const pageLink = e.target.closest('[data-page]');
        if (!pageLink) return;
        const page = pageLink.dataset.page;
        if (!page) return;
        e.preventDefault();
        Router.go(page);
    });
    window.addEventListener('hashchange', routeFromHash);
    window.addEventListener('decorate-me:session-expired', handleSessionExpired);
    // Cookie 由同一網域的分頁共用，因此另一分頁登入可能改變目前 session。
    // 只有 Gateway 或 session 驗證確認帳號不同時才停止請求並清除敏感資料。
    window.addEventListener('decorate-me:session-owner-changed', (event) => {
        const reason = (event && event.detail && event.detail.reason) || '';
        if (reason === 'EXPECTED_ACTOR_REQUIRED') {
            // 分頁沒有登入狀態時，要求使用者重新登入。
            handleSessionExpired({
                title: '登入狀態已失效',
                message: '這個分頁目前沒有可用的登入狀態，可能是登入階段已結束或分頁資料被清除。'
                    + '為避免把資料寫到錯誤的帳號，已停止動作並清除本機資料，請重新登入。'
            });
            return;
        }
        // 憑證屬於另一個帳號：不再把人踢出去，改成跟著切過去。
        // adoptSessionOwner() 自己會在認不出身分時退回登出。
        adoptSessionOwner();
    });

    // 一個分頁登出或換帳號時通知其他分頁，不必等它們自己撞到 403 才發現。
    // 不支援 BroadcastChannel 時，改由 API 錯誤被動偵測帳號變更。
    if (typeof BroadcastChannel === 'function') {
        try {
            Router._authChannel = new BroadcastChannel('decorate-me-auth');
            Router._authChannel.onmessage = (event) => {
                if (!event || !event.data || !['owner-changed', 'logged-out'].includes(event.data.type)) return;
                const mine = String((Auth.getProfile() || {}).email || '').trim().toLowerCase();
                // 只有「換成別人」才要擋；同一個帳號在別的分頁重新登入不影響這裡。
                if (event.data.type === 'owner-changed'
                    && (!mine || String(event.data.sub || '').trim().toLowerCase() === mine)) return;
                window.dispatchEvent(new CustomEvent('decorate-me:session-owner-changed'));
            };
        } catch (_) {}
    }

    // 頂部導覽
    document.querySelectorAll('.topbar-nav a, .topbar-user').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); Router.go(a.dataset.page); };
    });

    // 先向 Gateway 取得資料庫網址，再開始任何會打 API 的流程。
    // 資料庫網址由 Gateway 統一發布，前端不再寫死（見 issue #23）；取不到就沿用內建值，
    // 所以這裡不需要擋住畫面，失敗只代表用舊網址，不會讓前端整個起不來。
    Api.bootstrapConfig().finally(async () => {
        if (Auth.isLoggedIn()) {
            const session = await Api.validateSession();
            if (session.ok && !sessionOwnerMatchesProfile(session)) {
                // 跟中途換帳號走同一套處理：接受 session 的身分，不要把人踢掉。
                window.dispatchEvent(new CustomEvent('decorate-me:session-owner-changed', {
                    detail: { sub: session.sub }
                }));
            } else if (session.ok && Api._pinSession(session)) {
                // 把重新載入前停留的頁面交給 showApp 還原；它會自己驗證與正規化 hash。
                showApp(location.hash.replace(/^#/, ''));
            } else if (session.ok) {
                handleSessionExpired({ message: '無法安全保存這個分頁的登入身分，請重新登入後再繼續。' });
            } else if (session.status === 401) {
                handleSessionExpired();
            } else {
                showLogin();
                showAlert('目前無法確認登入狀態，請稍後重新登入。', { title: '連線暫時不可用', type: 'error' });
            }
        } else {
            showLogin();
        }
    });
})();

// 把伺服器上的收藏拉回本機。除了登入啟動，每次進收藏頁也會重新同步；
// 這樣登入當下若網路短暫失敗，使用者不必整個登出重來。
let remoteFavoritesSyncPromise = null;
function syncRemoteFavorites() {
    const profile = (typeof Auth !== 'undefined' && Auth.getProfile) ? (Auth.getProfile() || {}) : {};
    if (!profile.email || (typeof isGuest === 'function' && isGuest())) return Promise.resolve({ ok: false, skipped: true });
    if (typeof Api === 'undefined' || !Api.listRemoteFavorites || typeof Fav === 'undefined') return Promise.resolve({ ok: false, skipped: true });
    if (remoteFavoritesSyncPromise) return remoteFavoritesSyncPromise;
    remoteFavoritesSyncPromise = Api.listRemoteFavorites(profile.email).then(result => {
        if (!result || !result.ok) return result || { ok: false };
        const added = Fav.mergeRemote(result.favorites);
        return { ...result, added };
    }).catch(() => ({ ok: false })).finally(() => {
        remoteFavoritesSyncPromise = null;
    });
    return remoteFavoritesSyncPromise;
}

function refreshFavoritesPage() {
    if (Router.currentPage !== 'favorites') return;
    Router.favoriteSyncState = 'loading';
    PageInit.favorites();
    syncRemoteFavorites().then(result => {
        if (Router.currentPage !== 'favorites') return;
        Router.favoriteSyncState = result && result.ok ? 'ready' : 'error';
        PageInit.favorites();
    });
}

// 把伺服器上的購物車同步回本機。與 syncRemoteFavorites 同一套：登入與啟動各跑一次。
// Cart._mergeGuestOnce 為 true（剛登入）時，把登入前的訪客車與伺服器車數量相加合併一次，
// 並把結果推回伺服器讓其他裝置也拿到；否則以伺服器為準直接取代（重載／換裝置還原）。
// 失敗不提示：本機購物車照樣能用，這只是補齊，不是必要條件。
function syncRemoteCart() {
    const profile = (typeof Auth !== 'undefined' && Auth.getProfile) ? (Auth.getProfile() || {}) : {};
    if (!profile.email || (typeof isGuest === 'function' && isGuest())) return;
    if (typeof Api === 'undefined' || !Api.getRemoteCart || typeof Cart === 'undefined') return;
    const sum = !!Cart._mergeGuestOnce;
    Cart._mergeGuestOnce = false;
    Api.getRemoteCart(profile.email).then(result => {
        if (!result || !result.ok) return;
        const merged = Cart.mergeServer(result.items, sum);
        // 兩邊都是空的就沒有東西要寫回去。少了這個判斷，每次登入都會送一份
        // {"items":[]}：伺服器上本來就沒有的東西再覆蓋一次，白費一個請求。
        // 而且這是 last-write-wins——時序一旦不對，這份空清單是真的會把
        // 伺服器上的購物車蓋掉的。使用者自己把車清空時走的是 _schedulePush，
        // 那條該送的還是會送。
        if (sum && (merged.length || result.items.length)) Api.saveRemoteCart(merged).catch(() => {});
        updateCartBadge();
    }).catch(() => {});
}

// preferredPage：重新載入時要回到的頁面（由呼叫端從 location.hash 取得）。
// 舊版一律把 hash 蓋成 #dashboard，於是任何一次重新載入——包含 iOS Safari 在記憶體
// 不足時自動重載分頁——都會把人丟回主頁，而緊接在呼叫端後面的 routeFromHash() 讀到
// 的已經是被蓋掉的值，等於沒有作用。登入流程不帶參數，照樣落在 landing。
function showApp(preferredPage) {
    document.getElementById('auth-layer').innerHTML = '';
    document.getElementById('app').style.display = 'block';
    const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
    document.getElementById('sidebarUsername').textContent = `${getMemberDisplayName()} · ${getCurrentRoleLabel(profile)}`;
    updateCartBadge();
    refreshMemberTheme();
    syncRemoteFavorites();
    syncRemoteCart();
    const landing = (typeof AdminStore !== 'undefined' && AdminStore.isAdmin()) ? 'admin' : 'dashboard';
    // 管理員一律進後台（Router.go 內另有一道相同的守衛）；其餘情況才還原原本那一頁。
    const wanted = String(preferredPage || '').replace(/^#/, '');
    const target = (landing === 'admin' || !ROUTE_PAGES.has(wanted)) ? landing : wanted;
    updateAdminNav(target);
    const targetUrl = `${location.pathname}${location.search}#${target}`;
    if (location.hash !== `#${target}`) history.replaceState(null, '', targetUrl);
    // Router.go 有自己的守衛（訪客的收藏／分析紀錄、權限不足）會直接 return 不換頁。
    // 還原 hash 時撞上守衛就會停在空白畫面，所以沒有渲染成任何一頁就退回 landing。
    Promise.resolve(Router.go(target)).then(() => {
        if (Router.currentPage) return;
        const homeUrl = `${location.pathname}${location.search}#${landing}`;
        if (location.hash !== `#${landing}`) history.replaceState(null, '', homeUrl);
        Router.go(landing);
    });
}

// 帳號切換時採用已通過 Gateway 驗證的 session，並先清除上一個帳號的本機資料。
// 無法確認新帳號時維持登出，不猜測使用者身分。
async function adoptSessionOwner() {
    if (Router._ownerAdoptInProgress) return;
    Router._ownerAdoptInProgress = true;
    try {
        // 事件有時帶著 sub（來自 _verifySessionOwner），跨分頁廣播那條沒有。
        // 一律自己再問一次 /auth/session，只信第一手證據。
        const session = await Api.validateSession().catch(() => null);
        const nextEmail = String(session?.sub || '').trim().toLowerCase();
        if (!session || !session.ok || !nextEmail || !session.actorId || !Api._pinSession(session)) {
            handleSessionExpired({
                title: '登入狀態已失效',
                message: '無法確認目前的登入身分。為避免把資料寫到錯誤的帳號，已清除本機資料，請重新登入。'
            });
            return;
        }

        const prevEmail = String((Auth.getProfile() || {}).email || '').trim().toLowerCase();
        // 同一個人（例如在別的分頁重新登入自己）：重新 pin 過就好，不必驚動使用者。
        if (prevEmail && prevEmail === nextEmail) {
            Api._sessionExpiredNotified = false;
            Api._resetSessionRequests();
            return;
        }

        try { if (prevEmail && Auth.clearAccountLocalPII) Auth.clearAccountLocalPII(prevEmail); } catch (_) {}
        resetCurrentBeautySession();
        Api._sessionExpiredNotified = false;
        Api._resetSessionRequests();

        // 換上 cookie 真正屬於的那個人。讀不到會員資料也不要卡住——session 已經
        // 給了 email 與角色，先用那組把畫面撐起來，其餘欄位下次載入自然補齊。
        const fetched = await Api.fetchMember(nextEmail).catch(() => null);
        const member = (fetched && fetched.ok && fetched.member) ? fetched.member : {};
        Auth.setProfile({ ...member, email: nextEmail, role: session.role || member.role || 'member' });

        const nameEl = document.getElementById('sidebarUsername');
        if (nameEl) nameEl.textContent = `${getMemberDisplayName()} · ${getCurrentRoleLabel(Auth.getProfile() || {})}`;
        updateAdminNav();
        refreshMemberTheme();
        updateCartBadge();
        syncRemoteFavorites();
        syncRemoteCart();
        showToast(`已切換為 ${getMemberDisplayName()}`);
        Router.go(Router.currentPage || 'dashboard', { skipLeaveGuard: true });
    } finally {
        Router._ownerAdoptInProgress = false;
    }
}

function handleSessionExpired(options) {
    if (Router._sessionExpiryHandling) return;
    Router._sessionExpiryHandling = true;
    if (typeof Api._cancelSessionRequests === 'function') Api._cancelSessionRequests();
    resetCurrentBeautySession();
    // 換帳號／過期時，也清掉離開帳號殘留在 localStorage 的 PII（收藏臉圖、分析回饋）。
    // 必須在 clearSession 之前做，之後就讀不到 email 了；只清當前帳號。
    try { if (Auth.clearAccountLocalPII) Auth.clearAccountLocalPII((Auth.getProfile() || {}).email); } catch (_) {}
    if (typeof Auth.clearSession === 'function') Auth.clearSession();
    Router.currentPage = null;
    Router._reloadAdmin = null;
    showLogin();
    // options 只在身分不一致時帶入；當作事件處理器直接註冊時，收到的是 Event 物件，
    // 不能拿它的欄位當訊息用，所以這裡只認純物件。
    const custom = (options && typeof options === 'object' && !(options instanceof Event)) ? options : {};
    showAlert(custom.message || '登入狀態已失效，已停止背景資料載入。請重新登入後再繼續。', {
        title: custom.title || '登入已過期',
        type: 'error',
        onOk: function(){ document.getElementById('loginEmail')?.focus(); }
    });
}

// Gateway 的 admin 與 member 登入共用同一個 __session cookie，所以在後台登入會蓋掉
// 會員的 session，而 localStorage 的 profile 還停在前一個帳號。此時每一條會員 API
// 都在跨帳號請求，資料庫回 403，畫面上看起來像權限壞掉、點數不同步、打卡沒加上去
// ——四個症狀其實是同一個原因（見 S57）。
//
// Gateway 現在會在 /auth/session 回 sub，這裡比對出不一致就當作登入失效處理。
function sessionOwnerMatchesProfile(session) {
    const sub = String((session && session.sub) || '').trim().toLowerCase();
    const actorId = String((session && session.actorId) || '').trim();
    const email = String((Auth.getProfile() || {}).email || '').trim().toLowerCase();
    // 私人頁面缺少任何一段身分證據都不放行，避免部署空窗或舊快取造成跨帳號資料載入。
    if (!sub || !actorId || !email) return false;
    return sub === email;
}

function showLogin() {
    Router.currentPage = null;
    Router._reloadAdmin = null;
    document.body.classList.remove('admin-mode');
    document.getElementById('app').style.display = 'none';
    if (location.hash) history.replaceState(null, '', `${location.pathname}${location.search}`);
    document.getElementById('auth-layer').innerHTML = `
        <div class="auth-overlay">
            <section class="auth-editorial" aria-label="Decorate Me 登入">
              <div class="auth-brand-panel"><span class="auth-kicker">DECORATE ME</span><h1>裝識<br>你的美</h1><p>從臉部分析開始，保存每一次妝容建議、收藏與專屬風格。</p></div>
              <div class="auth-form-panel"><div class="auth-card"><span class="auth-kicker">會員登入</span><h2>歡迎回來</h2><p class="auth-description">登入後同步分析紀錄、收藏商品與會員主題。</p>
                <div class="input-group"><label>電子郵件</label><input type="email" id="loginEmail" placeholder="your@email.com"></div>
                <div class="input-group"><label>密碼</label><input type="password" id="loginPwd" placeholder="••••••••"></div>
                <button class="btn-gold btn-full" onclick="doLoginAction()" style="margin-top:8px;">登　入</button>
                <button class="btn-outline btn-full" onclick="doGuestLogin()" style="margin-top:12px;">訪客登入</button>
                <div style="margin-top:12px;"><span class="auth-link" onclick="showForgotPassword()">忘記密碼？</span></div>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showRegister()">還沒有帳號？立即註冊</span></div>
              </div></div>
            </section>
        </div>
    `;
}

function showRegister() {
    document.getElementById('auth-layer').innerHTML = `
        <div class="auth-overlay">
            <div class="auth-card auth-card-wide">
                <h2>建立帳號</h2>
                <p class="subtitle">Create your beauty profile</p>
                <div class="avatar-picker" onclick="document.getElementById('regAvatar').click()">
                    <img id="regAvatarPreview" alt="">
                    <span id="regAvatarIcon">👤</span>
                    <b>📷</b>
                    <input type="file" id="regAvatar" accept="image/*" style="display:none;" onchange="previewRegisterAvatar(event)">
                </div>
                <div class="input-group"><label>使用者名稱</label><input type="text" id="regName" placeholder="你的名字"></div>
                <div class="input-group"><label>電話號碼</label><input type="tel" id="regPhone" placeholder="0912345678"></div>
                <div class="input-group"><label>電子郵件</label><input type="email" id="regEmail" placeholder="your@email.com"></div>
                <div class="input-group"><label>年齡</label><input type="number" id="regAge" placeholder="20"></div>
                <div class="input-group"><label>密碼</label><input type="password" id="regPwd" placeholder="••••••••"></div>
                <div class="input-group"><label>確認密碼</label><input type="password" id="regPwd2" placeholder="••••••••"></div>
                <div class="input-group"><label>推薦碼（選填）</label><input type="text" id="regReferral" placeholder="朋友的推薦碼"></div>
                <button class="btn-gold btn-full" id="regSubmitBtn" onclick="doRegisterAction()" style="margin-top:8px;">註　冊</button>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showLogin()">已有帳號？返回登入</span></div>
            </div>
        </div>
    `;
    // 從登入失敗「去註冊」帶過來的帳密：自動填入 email 與密碼（含確認），使用者只要補其他欄位
    const pf = Router.prefillRegister;
    if (pf) {
        Router.prefillRegister = null;
        const e = document.getElementById('regEmail'); if (e && pf.email) e.value = pf.email;
        const p = document.getElementById('regPwd'); if (p && pf.password) p.value = pf.password;
        const p2 = document.getElementById('regPwd2'); if (p2 && pf.password) p2.value = pf.password;
    }
}

function showVerification(email) {
    const masked = maskEmail(email);
    document.getElementById('auth-layer').innerHTML = `
        <div class="auth-overlay">
            <div class="auth-card">
                <h2>驗證信箱</h2>
                <p class="subtitle">已將驗證碼發送至<br>${masked}</p>
                <div class="input-group"><label>驗證碼</label><input type="text" id="otpCode" placeholder="請輸入驗證碼"></div>
                <button class="btn-gold btn-full" onclick="doVerifyOTP()" style="margin-top:8px;">驗　證</button>
                <button class="btn-outline btn-full" onclick="resendOTP()" style="margin-top:12px;">重新發送驗證碼</button>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showRegister()">回上一頁</span></div>
            </div>
        </div>
    `;
}

function showForgotPassword() {
    document.getElementById('auth-layer').innerHTML = `
        <div class="auth-overlay">
            <div class="auth-card">
                <h2>忘記密碼</h2>
                <p class="subtitle">輸入信箱以接收驗證碼</p>
                <div class="input-group"><label>電子郵件</label><input type="email" id="forgotEmail" placeholder="your@email.com"></div>
                <button class="btn-gold btn-full" onclick="sendForgotOTP()">發送驗證碼</button>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showLogin()">返回登入</span></div>
            </div>
        </div>
    `;
}

async function doLoginAction() {
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPwd').value;
    if (!email || !password) { showAlert('請輸入帳號密碼'); return; }

    const registered = Auth.getRegisteredMember(email) || {};
    try {
        const data = await Api.login(email, password);
        const member = data.member || {};
        // 登入資料以後端為準；只有後端缺少欄位時才補上本機註冊資料。
        const fromServer = (key, localValue, fallback) =>
            Object.prototype.hasOwnProperty.call(member, key) ? member[key] : (localValue !== undefined ? localValue : fallback);
        Auth.setProfile({
            // 後端回的其他欄位（會員 id、點數等）照收；只有身分欄位改用 fromServer，
            // 不再把整包本機 registered 攤平當底。
            ...member,
            name: fromServer('name', registered.name, email.split('@')[0]) || email.split('@')[0],
            email: member.email || email,
            phone: fromServer('phone_number', registered.phone, ''),
            age: fromServer('age', registered.age, ''),
            level: fromServer('level', registered.level, '一般會員'),
            role: fromServer('role', registered.role, 'member'),
            status: fromServer('status', registered.status, 'active'),
            allowedPages: Array.isArray(member.allowedPages) ? member.allowedPages : (registered.allowedPages || undefined),
            vipRequested: !!(Object.prototype.hasOwnProperty.call(member, 'vipRequested') ? member.vipRequested : registered.vipRequested),
            renderQuota: Object.prototype.hasOwnProperty.call(member, 'renderQuota') ? member.renderQuota : (registered.renderQuota || null)
        });
        Router._sessionExpiryHandling = false;
        Api._sessionExpiredNotified = false;
    } catch (err) {
        // 伺服器拒絕或會員資料庫無法連線時都不允許登入。
        if (err.networkFailure) {
            showAlert('無法連線到會員資料庫，請稍後再試', { type: 'error' });
            return;
        }
        // 後端有回 code 就精準分流：未註冊 → 引導註冊；密碼錯 → 重新輸入 / 忘記密碼
        if (err.code === 'USER_NOT_FOUND') {
            showConfirm('此帳號尚未註冊。要用剛才輸入的資料直接去註冊嗎？', {
                title: '尚未註冊', type: 'error', okText: '去註冊', cancelText: '取消',
                onOk: function(){ Router.prefillRegister = { email: email, password: password }; showRegister(); }
            });
            return;
        }
        if (err.code === 'WRONG_PASSWORD') {
            showConfirm('密碼錯誤。請重新輸入，或前往「忘記密碼」重設。', {
                title: '密碼錯誤', type: 'error', okText: '重新輸入', cancelText: '忘記密碼',
                onCancel: function(){ if (typeof showForgotPassword === 'function') showForgotPassword(); }
            });
            return;
        }
        // 已停權或軟刪除的帳號應提示聯絡管理員，不能引導重新註冊。
        if (/SUSPEND|DELET|DISABLED|INACTIVE|BLOCK/i.test(err.code || '') || err.status === 403) {
            showAlert('此帳號已被停權或刪除，無法登入。請聯繫管理員處理，重新註冊不會生效。', { type: 'error' });
            return;
        }
        // 被限流：訊息已經帶了「請在 N 分鐘後再試」（後端回 retryAfterSeconds）。
        // 這裡不能走下面那個對話框——它會提供「忘記密碼」，把「請稍等」誤導成「你密碼錯了」，
        // 而每一次重試都會把限流視窗往後推。
        if (err.status === 429 || /RATE_LIMITED/i.test(err.code || '')) {
            // 兩種來源：Gateway 自己的限流（LOGIN_RATE_LIMITED）或會員資料庫的限流
            // （MEMBER_SERVICE_RATE_LIMITED）。訊息已由後端帶等待時間，直接顯示即可。
            showAlert(err.message || '登入頻率過高，請稍後再試。', { type: 'error' });
            return;
        }
        // 其餘未分類的錯誤：只顯示原因，不預設「你還沒註冊」。
        // 舊版一律提供「去註冊」捷徑，等於把所有登入失敗都猜成未註冊，是上面那個問題的根源。
        showConfirm(err.message || '帳號或密碼錯誤，請重新確認。', {
            title: '登入失敗',
            type: 'error',
            okText: '重新輸入',
            cancelText: '忘記密碼',
            onCancel: function(){ if (typeof showForgotPassword === 'function') showForgotPassword(); }
        });
        return;
    }
    if (AdminStore.getPermission(email, Auth.getProfile()).status === 'suspended') {
        // 走 clearSession 而不是自己挑兩個 key 刪。停權的帳號同樣不該把分析資料包
        // （含照片）留在分頁裡給下一個人，而手動列名一定會漏掉之後新增的東西。
        Auth.clearSession();
        showAlert('此帳號已被停權，請聯繫管理員', { type:'error' });
        return;
    }
    // 剛登入：讓 syncRemoteCart 把登入前的訪客購物車與伺服器車數量相加合併一次。
    if (typeof Cart !== 'undefined') Cart._mergeGuestOnce = true;
    showApp();
}

function doGuestLogin() {
    Auth.setProfile({ name: '訪客', level: '訪客', age: '', phone: '', email: '' });
    showApp();
}

// 寄送驗證碼期間鎖定註冊按鈕，避免重複建立帳號。
let registerInFlight = false;

async function doRegisterAction() {
    if (registerInFlight) return;
    const name = document.getElementById('regName').value.trim();
    const phone = document.getElementById('regPhone').value.trim();
    const email = document.getElementById('regEmail').value.trim();
    const age = document.getElementById('regAge').value.trim();
    const password = document.getElementById('regPwd').value;
    const confirm = document.getElementById('regPwd2').value;
    const avatar = document.getElementById('regAvatarPreview').src || '';
    const referralCode = document.getElementById('regReferral')?.value.trim() || '';

    if (!name || !phone || !email || !age || !password || !confirm) {
        showAlert('請完整填寫所有欄位');
        return;
    }
    if (password !== confirm) {
        showAlert('密碼與確認密碼不一致', { type:'error' });
        return;
    }

    Router.pendingRegister = { name, phone, email, age, password, avatar, referralCode, level: '一般會員' };
    const submitBtn = document.getElementById('regSubmitBtn');
    const submitLabel = submitBtn ? submitBtn.textContent : '';
    registerInFlight = true;
    if (submitBtn) {
        submitBtn.disabled = true;
        // 講清楚在等什麼。只是把按鈕變灰，使用者仍然會以為當掉而去重整頁面——
        // 重整同樣會走到「已註冊但沒收到碼」那個死路。
        submitBtn.textContent = '寄送驗證碼中…';
    }
    try {
        // 2026-07-27 後端改版：註冊本身就會寄出驗證碼（回 202、`otpSent: true`、
        // `registrationPending: true`），會員要驗證成功之後才真的建立。這裡再呼叫一次
        // sendOTP 會寄出第二封，使用者手上兩組碼卻只有一組有效，還多燒一次寄信配額。
        // 保留 else 分支是為了相容還沒更新的後端：沒有回報寄出就自己補一次。
        const registered = await Api.register(Router.pendingRegister);
        if (!registered || registered.otpSent !== true) {
            await Api.sendOTP(email);
        }
    } catch (err) {
        // 信箱已存在：最常見的成因不是「真的註冊過」，而是上一次註冊成功但驗證碼沒收到。
        // 只給「返回登入」等於把人推進死路——未驗證的帳號登入會被擋，他又不能重新註冊。
        // 所以主要出口是重寄驗證碼，返回登入退居次要。
        if (err?.code === 'EMAIL_EXISTS') {
            showConfirm(err.message, {
                title: '此信箱已註冊', type: 'error',
                okText: '重寄驗證碼', cancelText: '返回登入',
                onOk: async function () {
                    try {
                        await Api.sendOTP(email);
                    } catch (resendErr) {
                        showAlert(resendErr?.message || '驗證碼寄送失敗，請稍後再試', { type: 'error' });
                        return;
                    }
                    showVerification(email);
                },
                onCancel: function () { showLogin(); }
            });
            return;
        }
        showAlert(err?.message || '註冊或驗證碼發送失敗，請稍後再試', { type:'error' });
        return;
    } finally {
        registerInFlight = false;
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = submitLabel;
        }
    }
    showVerification(email);
}

async function doVerifyOTP() {
    const code = document.getElementById('otpCode').value.trim();
    if (!code) { showAlert('請輸入驗證碼'); return; }
    const pending = Router.pendingRegister;
    if (!pending) { showAlert('註冊資料已過期，請重新註冊', { type:'error', onOk: showRegister }); return; }
    if (!(await verifyOtp(pending.email, code))) return;

    // 以後端為準：驗證碼過了之後，一定要用後端 login 拿到 session 才算真的登入。
    // 假的／不存在的 email 驗不過、或後端沒把帳號設為已驗證，login 就會失敗、進不了 app，
    // 不再像以前那樣「前端自己 setProfile 直接進去」而繞過後端的帳號驗證。
    let member = {};
    try {
        const data = await Api.login(pending.email, pending.password);
        member = data.member || {};
    } catch (err) {
        if (err.networkFailure) {
            showAlert('無法連線到會員資料庫，請稍後再試', { type:'error' });
            return;
        }
        showAlert('驗證碼正確，但帳號登入未通過，請確認帳號已完成驗證後重新登入', { type:'error', onOk: showLogin });
        return;
    }

    Auth.setProfile({
        ...member,
        name: member.name || pending.name,
        phone: member.phone_number || pending.phone,
        email: member.email || pending.email,
        age: member.age || pending.age,
        level: member.level || pending.level,
        role: member.role || 'member',
        status: member.status || 'active',
        avatar: pending.avatar,
        renderQuota: member.renderQuota || null
    });
    const referralResult = (typeof Referral !== 'undefined' && pending.referralCode)
        ? Referral.applyReferral(pending.email, pending.referralCode)
        : { ok: false };
    Router.pendingRegister = null;
    // 剛註冊登入：同上，把註冊前的訪客購物車與（通常為空的）伺服器車合併一次。
    if (typeof Cart !== 'undefined') Cart._mergeGuestOnce = true;
    showAlert(
        referralResult.ok ? '帳號已成功建立，推薦碼已套用' : '帳號已成功建立',
        { type:'success', onOk: showApp }
    );
}

async function resendOTP() {
    const email = Router.pendingRegister?.email;
    if (!email) return;
    try { await Api.sendOTP(email); } catch (_) {}
    showToast('驗證碼已重新發送');
}

async function sendForgotOTP() {
    const email = document.getElementById('forgotEmail').value.trim();
    if (!email) { showAlert('請輸入 Email'); return; }
    try { await Api.sendOTP(email); } catch (_) {}
    Router.forgotEmail = email;
    showToast('驗證碼已發送');
    showForgotVerify(email);
}

function showForgotVerify(email){
    var masked = maskEmail(email);
    document.getElementById('auth-layer').innerHTML = [
        '<div class="auth-overlay"><div class="auth-card">',
        '<h2>驗證信箱</h2>',
        '<p class="subtitle">已將驗證碼發送至<br>' + masked + '</p>',
        '<div class="input-group"><label>驗證碼</label><input type="text" id="forgotOtp" placeholder="請輸入驗證碼"></div>',
        '<button class="btn-gold btn-full" onclick="doVerifyForgotOTP()" style="margin-top:8px;">驗　證</button>',
        '<button class="btn-outline btn-full" onclick="resendForgotOTP()" style="margin-top:12px;">重新發送驗證碼</button>',
        '<div style="margin-top:16px;"><span class="auth-link" onclick="showForgotPassword()">回上一頁</span></div>',
        '</div></div>'
    ].join('');
    setTimeout(function(){ var i=document.getElementById('forgotOtp'); if(i) i.focus(); }, 80);
}

async function doVerifyForgotOTP(){
    var code = document.getElementById('forgotOtp').value.trim();
    if (!code) { showAlert('請輸入驗證碼'); return; }
    if (!(await verifyOtp(Router.forgotEmail, code))) return;
    showResetPassword();
}

// 驗證碼一律以後端結果為準，前端不提供略過驗證的開關。
async function verifyOtp(email, code) {
    try {
        await Api.verifyOTP(email, code);
        return true;
    } catch (err) {
        showAlert(err?.message || '驗證碼驗證失敗，請稍後再試', { type: 'error' });
        return false;
    }
}

async function resendForgotOTP(){
    if (!Router.forgotEmail) return;
    try { await Api.sendOTP(Router.forgotEmail); } catch (_) {}
    showToast('驗證碼已重新發送');
}

function showResetPassword(){
    document.getElementById('auth-layer').innerHTML = [
        '<div class="auth-overlay"><div class="auth-card">',
        '<h2>設定新密碼</h2>',
        '<p class="subtitle">為你的帳號建立新的密碼</p>',
        '<div class="input-group"><label>新密碼</label><input type="password" id="resetPwd" placeholder="至少 6 碼"></div>',
        '<div class="input-group"><label>確認新密碼</label><input type="password" id="resetPwd2" placeholder="再次輸入新密碼"></div>',
        '<button class="btn-gold btn-full" onclick="doResetPassword()" style="margin-top:8px;">更新密碼</button>',
        '<div style="margin-top:16px;"><span class="auth-link" onclick="showLogin()">返回登入</span></div>',
        '</div></div>'
    ].join('');
    setTimeout(function(){ var i=document.getElementById('resetPwd'); if(i) i.focus(); }, 80);
}

function doResetPassword(){
    var p1 = document.getElementById('resetPwd').value, p2 = document.getElementById('resetPwd2').value;
    if (!p1 || !p2) { showAlert('請填寫新密碼'); return; }
    if (p1.length < 6) { showAlert('新密碼至少 6 碼'); return; }
    if (p1 !== p2) { showAlert('兩次輸入的新密碼不一致', { type:"error" }); return; }
    var profile = Auth.getProfile() || {};
    var base = (profile.email === Router.forgotEmail) ? profile : { email: Router.forgotEmail };
    Auth.setProfile(Object.assign({}, base, { password: p1 }));
    Router.forgotEmail = null;
    showAlert('密碼已更新，請使用新密碼登入', { type:"success", onOk: showLogin });
}

function previewRegisterAvatar(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
        const img = document.getElementById('regAvatarPreview');
        img.src = ev.target.result;
        img.style.display = 'block';
        document.getElementById('regAvatarIcon').style.display = 'none';
    };
    reader.readAsDataURL(file);
}

function maskEmail(email) {
    const [name, domain] = email.split('@');
    if (!name || !domain || name.length <= 3) return email;
    return `${name.slice(0, 3)}******@${domain}`;
}
