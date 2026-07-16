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
const ApiConfig = {
    services: {
        faceBasic: {
            baseUrl: RuntimeApiConfig.faceBasicUrl || '',
            apiKey: RuntimeApiConfig.faceApiKey || '',
            analyzePath: '/v1/face/analyze/basic',
            posePath: '/v1/face/pose',
            jobPath: '/v1/face/jobs/basic',
            jobStatusPath: '/v1/face/jobs/{jobId}',
            jobResultPath: '/v1/face/jobs/{jobId}/result'
        },
        facePro: {
            baseUrl: RuntimeApiConfig.faceProUrl || '',
            apiKey: RuntimeApiConfig.faceApiKey || '',
            analyzePath: '/v1/face/analyze/pro',
            jobPath: '/v1/face/jobs/pro',
            jobStatusPath: '/v1/face/jobs/{jobId}',
            jobResultPath: '/v1/face/jobs/{jobId}/result'
        },
        textSuggestion: {
            baseUrl: RuntimeApiConfig.textSuggestionUrl || '',
            apiKey: RuntimeApiConfig.textSuggestionApiKey || '',
            suggestPath: '/suggest'
        },
        render: {
            baseUrl: RuntimeApiConfig.renderUrl || '',
            apiKey: RuntimeApiConfig.renderApiKey || '',
            renderPath: '/render'
        },
        product: {
            baseUrl: RuntimeApiConfig.productUrl || '',
            recommendPath: '/recommend-products',
            listPath: '/api/products'
        },
        crawler: {
            baseUrl: RuntimeApiConfig.crawlerUrl || RuntimeApiConfig.productUrl || '',
            previewPath: '/api/crawler/product-preview'
        },
        memberDatabase: {
            baseUrl: RuntimeApiConfig.memberDatabaseUrl || '',
            loginPath: '/api/login',
            registerPath: '/api/register',
            // 只打正規發碼端點；不要 fallback 到 /api/register，否則會送出只帶 email 的殘缺請求，被後端回 400 MISSING_FIELDS（曾被誤判成 CSRF）
            sendOtpPaths: ['/api/send-otp'],
            verifyOtpPath: '/api/verify-otp'
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

    async _warmRenderService(baseUrl, apiKey) {
        if (!baseUrl) return;
        const headers = {};
        if (apiKey) headers['X-API-Key'] = apiKey;
        try {
            await fetch(`${baseUrl}/health`, {
                method: 'GET',
                headers,
                cache: 'no-store',
            });
        } catch (_) {
            // Ignore warm-up failures and let the real render request surface the actionable error.
        }
    },

    // face-basic / face-pro 的 min-instances 是 0，閒置後容器會縮到零，下一個人按分析就得等冷啟動
    // （mediapipe 載模型特別久）。趁使用者還在選照片、還沒按下按鈕的空檔先打一發 /health 把容器叫醒，
    // 等他真的送出時通常已經是熱的。故意不 await，純背景預熱，失敗也無所謂。
    warmFaceServices() {
        const runtime = getRuntimeApiConfig();
        const apiKey = runtime.faceApiKey || this.config.services.faceBasic.apiKey || '';
        const targets = [
            runtime.faceBasicUrl || this.config.services.faceBasic.baseUrl,
            runtime.faceProUrl || this.config.services.facePro.baseUrl,
        ];
        targets.filter(Boolean).forEach(baseUrl => { this._warmRenderService(baseUrl, apiKey); });
    },

    // 臉部分析服務的 X-API-Key（faceBasic/facePro 共用同一把）；沒設定時回空物件、不影響本機。
    _faceHeaders(service) {
        const key = this.config.services[service]?.apiKey;
        return key ? { 'X-API-Key': key } : {};
    },

    // 後端建 job 時發 resultToken，之後查詢 job 狀態/結果必須帶 X-Job-Token，否則回 403
    _faceJobHeaders(service, resultToken) {
        const headers = { ...this._faceHeaders(service) };
        if (resultToken) headers['X-Job-Token'] = resultToken;
        return headers;
    },

    // 臉部分析
    async detectFacePose(file) {
        const fd = new FormData();
        fd.append('file', file);
        const res = await fetch(this.config.url('faceBasic', 'posePath'), { method: 'POST', body: fd, headers: this._faceHeaders('faceBasic') });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '角度偵測失敗' }));
            throw new Error(err.detail?.error?.message || err.detail || '角度偵測失敗');
        }
        return res.json();
    },

    async createFaceJob(file) {
        const fd = new FormData();
        fd.append('file', file);
        const res = await fetch(this.config.url('faceBasic', 'jobPath'), { method: 'POST', body: fd, headers: this._faceHeaders('faceBasic') });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '伺服器錯誤' }));
            throw new Error(err.detail?.error?.message || err.detail || '建立 BASIC job 失敗');
        }
        return res.json();
    },

    async createFaceProJob(files) {
        const fd = new FormData();
        fd.append('front', files.front);
        for (const role of ['left45', 'right45', 'side']) {
            if (files[role]) fd.append(role, files[role]);
        }
        const res = await fetch(this.config.url('facePro', 'jobPath'), { method: 'POST', body: fd, headers: this._faceHeaders('facePro') });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '伺服器錯誤' }));
            throw new Error(err.detail?.error?.message || err.detail || '建立 PRO job 失敗');
        }
        return res.json();
    },

    async getFaceJob(mode, jobId, resultToken) {
        const service = mode === 'pro' ? 'facePro' : 'faceBasic';
        const res = await fetch(this.config.jobUrl(service, 'jobStatusPath', jobId), { cache: 'no-store', headers: this._faceJobHeaders(service, resultToken) });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '伺服器錯誤' }));
            throw new Error(err.detail?.error?.message || err.detail || '查詢 job 失敗');
        }
        return res.json();
    },

    async getFaceJobResult(mode, jobId, resultToken) {
        const service = mode === 'pro' ? 'facePro' : 'faceBasic';
        const res = await fetch(this.config.jobUrl(service, 'jobResultPath', jobId), { cache: 'no-store', headers: this._faceJobHeaders(service, resultToken) });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '伺服器錯誤' }));
            throw new Error(err.detail?.error?.message || err.detail || '取得 job 結果失敗');
        }
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

    _textSuggestionHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const apiKey = this.config.services.textSuggestion.apiKey;
        if (apiKey) headers['X-API-Key'] = apiKey;
        return headers;
    },

    async suggestMakeup({ analysisPackage, faceAnalysis, style, userNote }) {
        let res;
        try {
            res = await fetch(this.config.url('textSuggestion', 'suggestPath'), {
                method: 'POST',
                headers: this._textSuggestionHeaders(),
                body: JSON.stringify({ analysisPackage, faceAnalysis, style, language: 'zh-TW', userNote }),
            });
        } catch (err) {
            throw new Error('無法連線到建議服務：' + err.message);
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
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
        const runtimeConfig = getRuntimeApiConfig();
        const serviceConfig = {
            ...(this.config.services.render || {}),
            baseUrl: runtimeConfig.renderUrl || this.config.services.render.baseUrl || '',
            apiKey: runtimeConfig.renderApiKey || this.config.services.render.apiKey || '',
        };
        const url = serviceConfig.baseUrl && serviceConfig.renderPath
            ? `${serviceConfig.baseUrl}${serviceConfig.renderPath}`
            : '';
        if (!url) throw new Error('renderUrl 未設定，請聯繫渲染端組員提供 Cloud Run URL');
        const headers = { 'Content-Type': 'application/json' };
        const apiKey = serviceConfig.apiKey;
        if (apiKey) headers['X-API-Key'] = apiKey;
        const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
        if (profile.email) headers['X-User-Email'] = profile.email;
        if (profile.role) headers['X-User-Role'] = profile.role;
        let res;
        try {
            await this._warmRenderService(serviceConfig.baseUrl, apiKey);
            await new Promise(resolve => setTimeout(resolve, 500));
            const requestInit = {
                method: 'POST',
                headers,
                body: JSON.stringify({ image: imageDataUrl, prompt, strength }),
            };
            try {
                res = await fetch(url, requestInit);
            } catch (firstErr) {
                // Cloud Run cold start or transient network hiccups can cause the first browser fetch to fail.
                await new Promise(resolve => setTimeout(resolve, 1500));
                res = await fetch(url, requestInit);
            }
        } catch (err) {
            throw new Error('無法連線到渲染服務：' + err.message);
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (res.status === 401) {
                if (!apiKey) {
                    throw new Error('Render API 需要金鑰，但目前頁面沒有載到 renderApiKey。請重新整理，或檢查 config.local.js / 部署設定。');
                }
                throw new Error('Render API 金鑰驗證失敗。請重新整理頁面後再試，若仍失敗表示目前前端設定的 renderApiKey 與伺服器不一致。');
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
    // （前端送的 prompt 會被後端忽略——renderApiKey 是明文，信任前端 prompt 等於任何人能用我們額度生任意圖）；
    // 輪詢必須帶建立 job 時回的 resultToken（X-Job-Token），不帶會被 403 擋到逾時。
    async renderMakeupAsync({ imageDataUrl, styleId = 'natural', analysisPackage = null, strength = 0.35, onProgress = null }) {
        const runtimeConfig = getRuntimeApiConfig();
        const baseUrl = runtimeConfig.renderUrl || this.config.services.render.baseUrl || '';
        const apiKey = runtimeConfig.renderApiKey || this.config.services.render.apiKey || '';
        if (!baseUrl) throw new Error('renderUrl 未設定，請聯繫渲染端組員提供 Cloud Run URL');

        const headers = { 'Content-Type': 'application/json' };
        if (apiKey) headers['X-API-Key'] = apiKey;
        const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
        if (profile.email) headers['X-User-Email'] = profile.email;
        if (profile.role) headers['X-User-Role'] = profile.role;

        const emit = (p) => { if (typeof onProgress === 'function') onProgress(p); };

        let submitRes;
        try {
            await this._warmRenderService(baseUrl, apiKey);
            const requestInit = {
                method: 'POST',
                headers,
                body: JSON.stringify({ image: imageDataUrl, styleId, analysisPackage, strength }),
            };
            try {
                submitRes = await fetch(`${baseUrl}/render/jobs`, requestInit);
            } catch (firstErr) {
                // 冷啟動或瞬斷時第一次 fetch 可能直接失敗，重試一次
                await new Promise(resolve => setTimeout(resolve, 1500));
                submitRes = await fetch(`${baseUrl}/render/jobs`, requestInit);
            }
        } catch (err) {
            throw new Error('無法連線到渲染服務：' + err.message);
        }

        const submitted = await submitRes.json().catch(() => ({}));
        if (!submitRes.ok) {
            if (submitRes.status === 401) {
                throw new Error('Render API 金鑰驗證失敗。請重新整理頁面後再試。');
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
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, 2000));
            let job;
            try {
                const pollRes = await fetch(pollUrl, { method: 'GET', headers, cache: 'no-store' });
                job = await pollRes.json().catch(() => ({}));
                if (!pollRes.ok) {
                    // 輪詢途中的暫時性錯誤不該直接判死，繼續等下一輪
                    if (pollRes.status === 404) throw new Error('渲染工作不存在或已過期');
                    continue;
                }
            } catch (err) {
                if (err.message === '渲染工作不存在或已過期') throw err;
                continue;  // 網路瞬斷，下一輪再試
            }

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
            hex: /^#[0-9a-fA-F]{3,8}$/.test(product.hex || '') ? product.hex : null,
            tags: product.tags || [],
            source: 'product-api'
        };
    },

    // 單品詳情：只有這支 API 才有真正的 hex/lab/vector，商品清單 API 沒有
    async getProductDetail(apiType, rawId) {
        const baseUrl = this.config.services.product.baseUrl;
        if (!baseUrl || !apiType || rawId == null) return null;
        try {
            const res = await fetch(`${baseUrl}/api/product/${encodeURIComponent(apiType)}/${encodeURIComponent(rawId)}`, { cache: 'no-store' });
            if (!res.ok) return null;
            const data = await res.json();
            if (!data?.success || !data.product) return null;
            const p = data.product;
            return {
                hex: /^#[0-9a-fA-F]{3,8}$/.test(p.hex || '') ? p.hex : null,
                lab: p.lab && typeof p.lab === 'object' ? p.lab : null,
                vector: Array.isArray(p.vector) ? p.vector : null,
                salePageId: p.salepage || null
            };
        } catch (_) {
            return null;
        }
    },

    // 以色找色：用 12 維色彩向量算相似度，回傳同類型的相似色號商品
    async getSimilarColorProducts(apiType, rawId) {
        const baseUrl = this.config.services.product.baseUrl;
        if (!baseUrl || !apiType || rawId == null) return [];
        try {
            const res = await fetch(`${baseUrl}/api/recommend/${encodeURIComponent(apiType)}/${encodeURIComponent(rawId)}`, { cache: 'no-store' });
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

    // 個人化推薦：依賴組員資料庫的登入 session，登入狀態不確定時優雅地回傳空陣列，不影響其他功能
    async getPersonalRecommendations() {
        const baseUrl = this.config.services.product.baseUrl;
        if (!baseUrl) return [];
        try {
            const res = await fetch(`${baseUrl}/api/recommend/personal`, { credentials: 'include', cache: 'no-store' });
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
    async toggleRemoteFavorite(itemId, itemType) {
        const baseUrl = this.config.services.product.baseUrl;
        if (!baseUrl) return null;
        try {
            const res = await fetch(`${baseUrl}/api/favorites/toggle`, {
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
    },

    async listProducts() {
        const url = this.config.url('product', 'listPath');
        if (!url) return { ok: false, products: [] };
        try {
            const res = await fetch(url, { cache: 'no-store' });
            if (!res.ok) return { ok: false, status: res.status, products: [] };
            const data = await res.json();
            return {
                ok: true,
                ...data,
                products: Array.isArray(data.products)
                    ? data.products.map(item => this._normalizeProduct(item)).filter(Boolean)
                    : []
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
            const profile = typeof Auth !== 'undefined' ? (Auth.getProfile() || {}) : {};
            const res = await this._fetchWithRelogin(url, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: sourceUrl,
                    source: 'manual_admin_import',
                    adminId: profile.email || null
                }),
                ...(controller ? { signal: controller.signal } : {})
            });
            if (timeout) clearTimeout(timeout);
            const data = await res.json().catch(() => ({}));
            const payload = data.data || data.product || {};
            if (!res.ok || data.success === false) {
                return {
                    ok: false,
                    status: res.status,
                    code: data?.error?.code || data.code || `HTTP_${res.status}`,
                    error: data?.error?.message || data.message || `HTTP ${res.status}`,
                    detail: data?.error?.detail || ''
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
                    missingFields: Array.isArray(payload.missingFields) ? payload.missingFields : []
                },
                raw: data
            };
        } catch (err) {
            if (timeout) clearTimeout(timeout);
            if (err?.name === 'AbortError') return { ok: false, code: 'FETCH_TIMEOUT', error: '爬蟲服務逾時，請稍後重試' };
            return { ok: false, code: 'NETWORK_ERROR', error: '爬蟲服務連線失敗：' + err.message };
        }
    },

    // ═══ 後台管理：members 讀寫都走管理員 session cookie ═══
    // 不在瀏覽器保存密碼，也不使用密碼自動重登入。若 session 失效，讓畫面
    // 顯示登入逾時並由使用者重新登入；真正的長期登入應由 HttpOnly cookie/refresh
    // token 由會員後端負責，而不是把密碼交給 JavaScript。
    // 保留這個 wrapper 名稱是為了相容既有呼叫點，但不再做 relogin。
    async _fetchWithRelogin(input, init) {
        return fetch(input, init);
    },

    async fetchAdminMembers() {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl) return { ok: false, error: 'memberDatabaseUrl 未設定' };
        const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
        const timeout = controller ? setTimeout(() => controller.abort(), 12000) : null;
        const opts = { credentials: 'include', cache: 'no-store', ...(controller ? { signal: controller.signal } : {}) };
        try {
            let res = await fetch(`${baseUrl}/api/members`, opts);
            if (res.status === 401 && await this._reLogin()) {
                res = await fetch(`${baseUrl}/api/members`, opts);
            }
            if (timeout) clearTimeout(timeout);
            const data = await res.json();
            if (!res.ok) {
                return {
                    ok: false,
                    status: res.status,
                    error: data?.error?.message || `HTTP ${res.status}`
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

    async patchMember(email, patch) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl) return { ok: false, error: 'memberDatabaseUrl 未設定' };
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
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/tasks/${encodeURIComponent(taskId)}/claim`, {
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
    },

    async redeemMemberTheme(email, themeId) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email || !themeId) return { ok: false };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/theme-shop/${encodeURIComponent(themeId)}/redeem`, {
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
    },

    // ═══ 收藏妝容對比圖 saved_looks：跨裝置持久化，走登入 session（本機 localStorage 仍是離線快取，遠端失敗不影響本機） ═══
    _isStorableImageUrl(value) {
        const raw = String(value || '').trim();
        if (!raw || raw.length > 500) return false;
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
        const beforeImageUrl = String(payload?.beforeImageUrl || '').trim();
        const afterImageUrl = String(payload?.afterImageUrl || '').trim();
        if (!payload?.style || !this._isStorableImageUrl(beforeImageUrl) || !this._isStorableImageUrl(afterImageUrl)) {
            return { ok: false, skipped: true, reason: 'IMAGE_URL_REQUIRED' };
        }
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/saved-looks`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    style: String(payload.style).slice(0, 120),
                    beforeImageUrl,
                    afterImageUrl,
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
    },

    async deleteSavedLook(email, id) {
        const baseUrl = this.config.services.memberDatabase.baseUrl;
        if (!baseUrl || !email || id == null) return { ok: false };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/members/${encodeURIComponent(email)}/saved-looks/${encodeURIComponent(id)}`, {
                method: 'DELETE',
                credentials: 'include'
            });
            return { ok: res.ok, status: res.status };
        } catch (_) {
            return { ok: false };
        }
    },

    async patchRemoteProduct(rawId, payload) {
        const baseUrl = this.config.services.product.baseUrl;
        if (!baseUrl) return { ok: false, error: 'productUrl 未設定' };
        if (rawId == null) return { ok: false, error: '找不到這筆商品的資料庫 id' };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/products/${encodeURIComponent(rawId)}`, {
                method: 'PATCH',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, status: res.status, error: data?.error?.message || `HTTP ${res.status}` };
            return { ok: true, product: data.product || data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async createRemoteProduct(payload) {
        const baseUrl = this.config.services.product.baseUrl;
        if (!baseUrl) return { ok: false, error: 'productUrl 未設定' };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/products`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, status: res.status, error: data?.error?.message || `HTTP ${res.status}` };
            return { ok: true, product: data.product || data };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
    },

    async deleteRemoteProduct(rawId) {
        const baseUrl = this.config.services.product.baseUrl;
        if (!baseUrl) return { ok: false, error: 'productUrl 未設定' };
        if (rawId == null) return { ok: false, error: '找不到這筆商品的資料庫 id' };
        try {
            const res = await this._fetchWithRelogin(`${baseUrl}/api/products/${encodeURIComponent(rawId)}`, {
                method: 'DELETE',
                credentials: 'include'
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return { ok: false, status: res.status, error: data?.error?.message || `HTTP ${res.status}` };
            return { ok: true };
        } catch (err) {
            return { ok: false, error: '連線失敗：' + err.message };
        }
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
            const res = await fetch(url, {
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
        let res;
        const doLogin = (withCreds) => fetch(this.config.url('memberDatabase', 'loginPath'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
            ...(withCreds ? { credentials: 'include' } : {})
        });
        try {
            // 優先帶 credentials 讓後端 session cookie 種進來（後台管理端點靠它驗證）；
            // 對方 CORS 若沒開放 credentials 會直接 TypeError，退回無 cookie 模式讓一般登入不受影響。
            try { res = await doLogin(true); }
            catch (_) { res = await doLogin(false); }
        } catch (err) {
            // 真正連不上後端（DNS/斷線/CORS 擋掉），才算「網路失敗」，允許前端 fallback 成本機模擬
            const networkErr = new Error('登入 API 連線失敗：' + err.message);
            networkErr.networkFailure = true;
            throw networkErr;
        }
        if (!res.ok) {
            // 伺服器有回應，只是明確拒絕（帳密錯誤、帳號停權等）——這不是「連不上」，不能被當成 fallback 條件，否則等於帳密驗證形同虛設
            let detail = null;
            try { detail = await res.json(); } catch (_) {}
            const err = new Error(detail?.error?.message || '帳號或密碼錯誤');
            err.networkFailure = false;
            err.status = res.status;
            err.code = detail?.error?.code || null;  // 未註冊 USER_NOT_FOUND / 密碼錯 WRONG_PASSWORD（後端支援時前端據此分流）
            throw err;
        }
        // 清除舊版本可能留下的敏感資料；本版本不保存密碼。
        try { sessionStorage.removeItem('beautyAuthCreds'); } catch (_) {}
        return res.json();
    },

    async register(payload) {
        const body = {
            phone_number: payload.phone,
            name: payload.name,
            email: payload.email,
            password: payload.password,
            age: Number(payload.age)
        };
        const res = await fetch(this.config.url('memberDatabase', 'registerPath'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!res.ok) throw new Error('註冊 API 連線失敗');
        return res.json();
    },

    async sendOTP(email) {
        const memberApi = this.config.services.memberDatabase;
        for (const endpoint of memberApi.sendOtpPaths) {
            try {
                const res = await fetch(`${memberApi.baseUrl}${endpoint}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                if (res.ok) return res.json();
            } catch (_) {
                // 原型階段允許 fallback 到下一個 endpoint 或本地模擬。
            }
        }
        throw new Error('驗證碼 API 連線失敗');
    },

    async verifyOTP(email, otp) {
        const res = await fetch(this.config.url('memberDatabase', 'verifyOtpPath'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, otp })
        });
        if (!res.ok) throw new Error('OTP 驗證 API 連線失敗');
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
    save(pkg) {
        localStorage.setItem(this._key, JSON.stringify(pkg));
    },
    load() {
        return JSON.parse(localStorage.getItem(this._key) || 'null');
    },
    clear() {
        localStorage.removeItem(this._key);
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
    getProfile() {
        let profile = {};
        try { profile = JSON.parse(sessionStorage.getItem('beautyProfile') || '{}') || {}; } catch (_) {}
        if (Object.prototype.hasOwnProperty.call(profile, 'password')) {
            const { password, ...safeProfile } = profile;
            profile = safeProfile;
            try { sessionStorage.setItem('beautyProfile', JSON.stringify(profile)); } catch (_) {}
        }
        return profile;
    },
    setProfile(profile) {
        const safeProfile = { ...(profile || {}) };
        delete safeProfile.password;
        sessionStorage.setItem('beautyProfile', JSON.stringify(safeProfile));
        if (safeProfile?.name) sessionStorage.setItem('beautyUser', safeProfile.name);
        this.saveRegisteredMember(safeProfile);
    },
    isLoggedIn() { return !!this.getUser(); },
    logout() {
        sessionStorage.removeItem('beautyUser');
        sessionStorage.removeItem('beautyProfile');
        sessionStorage.removeItem('beautyAuthCreds');
        location.reload();
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
        return this.isAdminProfile(Auth.getProfile());
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
        { id: 'rose', name: '玫瑰柔霧', cost: 80, swatches: ['#F8E1E4', '#C56B7B', '#5B3A38'], desc: '柔粉色會員介面' },
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
    }
};

// ═══ 購物車模組 ═══
const Cart = {
    _key: 'beautyCart',
    list() {
        try { return JSON.parse(localStorage.getItem(this._key) || '[]'); }
        catch (_) { return []; }
    },
    save(items) { localStorage.setItem(this._key, JSON.stringify(items)); },
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
    count() { return this.list().reduce((sum, item) => sum + item.qty, 0); }
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
