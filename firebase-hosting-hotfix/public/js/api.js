// 無登入 session 時清除所有訪客活動資料，確保每次開新分頁都是乾淨狀態
(function () {
    if (!sessionStorage.getItem('beautyUser')) {
        ['beautyAnalysisDraft', 'beautyFav', 'beautyCart', 'beautyHistory', 'beautySuggestions'].forEach(
            k => localStorage.removeItem(k)
        );
    }
})();

// ═══ API 設定：所有外部服務都走這裡，不直接連 PostgreSQL 或 Ollama 11434 ═══
const RuntimeApiConfig = typeof window !== 'undefined' ? (window.DECORATE_ME_CONFIG || {}) : {};
const PRODUCTION_AI_GATEWAY_URL = 'https://ai-gateway-258021445391.asia-east1.run.app';

function getAiGatewayUrl(runtimeConfig = RuntimeApiConfig) {
    const configured = String(runtimeConfig.aiGatewayUrl || '').trim().replace(/\/$/, '');
    if (configured) return configured;
    if (typeof window === 'undefined' || !window.location) return '';
    const productionHosts = new Set(['decorate-me.web.app', 'decorate-me.firebaseapp.com']);
    return productionHosts.has(window.location.hostname) ? PRODUCTION_AI_GATEWAY_URL : '';
}

const AiGatewayUrl = getAiGatewayUrl();
try { sessionStorage.removeItem('beautyAuthCreds'); } catch (_) {}

const ApiConfig = {
    services: {
        faceBasic: {
            baseUrl: AiGatewayUrl ? `${AiGatewayUrl}/face-basic` : (RuntimeApiConfig.faceBasicUrl || 'http://127.0.0.1:8001'),
            apiKey: RuntimeApiConfig.faceApiKey || '',
            analyzePath: '/v1/face/analyze/basic',
            posePath: '/v1/face/pose',
            jobPath: '/v1/face/jobs/basic',
            jobStatusPath: '/v1/face/jobs/{jobId}',
            jobResultPath: '/v1/face/jobs/{jobId}/result',
            healthPath: '/health'
        },
        facePro: {
            baseUrl: AiGatewayUrl ? `${AiGatewayUrl}/face-pro` : (RuntimeApiConfig.faceProUrl || 'http://127.0.0.1:8002'),
            apiKey: RuntimeApiConfig.faceApiKey || '',
            analyzePath: '/v1/face/analyze/pro',
            jobPath: '/v1/face/jobs/pro',
            jobStatusPath: '/v1/face/jobs/{jobId}',
            jobResultPath: '/v1/face/jobs/{jobId}/result',
            healthPath: '/health'
        },
        textSuggestion: {
            baseUrl: RuntimeApiConfig.textSuggestionUrl || 'http://127.0.0.1:8010',
            apiKey: RuntimeApiConfig.textSuggestionApiKey || '',
            suggestPath: '/suggest',
            streamPath: '/suggest/stream',
            healthPath: '/health'
        },
        render: {
            baseUrl: AiGatewayUrl ? `${AiGatewayUrl}/render-service` : (RuntimeApiConfig.renderUrl || ''),
            apiKey: RuntimeApiConfig.renderApiKey || '',
            renderPath: '/render',
            healthPath: '/health'
        },
        product: {
            baseUrl: RuntimeApiConfig.productUrl || '',
            recommendPath: '/recommend-products',
            healthPath: '/health'
        },
        memberDatabase: {
            baseUrl: RuntimeApiConfig.memberDatabaseUrl || '',
            loginPath: '/api/login',
            registerPath: '/api/register',
            sendOtpPaths: ['/api/send-otp', '/api/register'],
            verifyOtpPath: '/api/verify-otp',
            healthPath: '/health'
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

    _aiAccessToken() {
        try { return sessionStorage.getItem('beautyAiAccessToken') || ''; }
        catch (_) { return ''; }
    },

    _withAiAccess(headers = {}) {
        const token = this._aiAccessToken();
        return token ? { ...headers, Authorization: 'Bearer ' + token } : headers;
    },

    async _createAiSession(email, password) {
        const gatewayUrl = getAiGatewayUrl();
        if (!gatewayUrl) return;
        const apiKey = this.config.services.faceBasic?.apiKey || this.config.services.render?.apiKey || '';
        const headers = { 'Content-Type': 'application/json' };
        if (apiKey) headers['X-API-Key'] = apiKey;
        const response = await fetch(gatewayUrl + '/auth/login', {
            method: 'POST',
            headers,
            body: JSON.stringify({ email, password })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.accessToken) throw new Error('AI 安全工作階段建立失敗，請重新登入。');
        sessionStorage.setItem('beautyAiAccessToken', data.accessToken);
    },

    _faceHeaders(service) {
        const key = this.config.services[service]?.apiKey;
        return this._withAiAccess(key ? { 'X-API-Key': key } : {});
    },

    _faceJobHeaders(service, resultToken) {
        const headers = { ...this._faceHeaders(service) };
        if (resultToken) headers['X-Job-Token'] = resultToken;
        return headers;
    },

    _textSuggestionHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const key = this.config.services.textSuggestion?.apiKey;
        if (key) headers['X-API-Key'] = key;
        return headers;
    },

    _renderHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const key = this.config.services.render?.apiKey;
        if (key) headers['X-API-Key'] = key;
        return this._withAiAccess(headers);
    },

    // 臉部分析
    async analyzeFace(file) {
        const fd = new FormData();
        fd.append('file', file);
        const res = await fetch(this.config.url('faceBasic', 'analyzePath'), { method: 'POST', body: fd, headers: this._faceHeaders('faceBasic') });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '伺服器錯誤' }));
            throw new Error(err.detail || '分析失敗');
        }
        const data = await res.json();
        return { data, imageMeta: { front: ImagePipeline.metaFromFile(file, 'front') } };
    },

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

    async analyzeFacePro(files) {
        const fd = new FormData();
        const imageMeta = {};
        fd.append('front', files.front);
        imageMeta.front = ImagePipeline.metaFromFile(files.front, 'front');
        for (const role of ['left45', 'right45', 'side']) {
            if (!files[role]) continue;
            fd.append(role, files[role]);
            imageMeta[role] = ImagePipeline.metaFromFile(files[role], role);
        }

        // PRO 掃描版預留：
        // 未來 webcam 掃描擷取出的 front / left45 / right45 / side Blob，
        // 也包成 File 後送到同一個 API，避免掃描版和檔案上傳版分裂。
        const res = await fetch(this.config.url('facePro', 'analyzePath'), { method: 'POST', body: fd, headers: this._faceHeaders('facePro') });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '伺服器錯誤' }));
            throw new Error(err.detail || '分析失敗');
        }
        const data = await res.json();
        return { data, imageMeta };
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

    async suggestMakeupStream({ analysisPackage, faceAnalysis, style, userNote }, onToken, onDone, onError) {
        const url = this.config.url('textSuggestion', 'streamPath');
        if (!url) { onError('未設定 Ollama URL'); return; }
        let response;
        try {
            response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ analysisPackage, faceAnalysis, style, language: 'zh-TW', userNote }),
            });
        } catch (err) {
            onError('無法連線到建議服務：' + err.message);
            return;
        }
        if (response.status === 404) {
            // 組員尚未更新服務，降回舊版 /suggest
            try {
                const fallbackRes = await fetch(this.config.url('textSuggestion', 'suggestPath'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ analysisPackage, faceAnalysis, style, language: 'zh-TW', userNote }),
                });
                if (!fallbackRes.ok) {
                    const err = await fallbackRes.json().catch(() => ({}));
                    onError(err.detail?.error?.message || `建議服務回傳 HTTP ${fallbackRes.status}`);
                    return;
                }
                const data = await fallbackRes.json();
                onToken(data.suggestion || '');
                onDone({ done: true, suggestion: data.suggestion || '', renderPromptEn: data.renderPromptEn || '' });
            } catch (err) {
                onError('無法連線到建議服務：' + err.message);
            }
            return;
        }
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            onError(err.detail?.error?.message || `建議服務回傳 HTTP ${response.status}`);
            return;
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const evt = JSON.parse(line.slice(6));
                    if (evt.error) { onError(evt.error); return; }
                    if (evt.token) onToken(evt.token);
                    if (evt.done) onDone(evt);
                } catch (_) {}
            }
        }
    },

    async renderMakeup({ imageDataUrl, styleId, strength = 0.45 }) {
        const url = this.config.url('render', 'renderPath');
        if (!url) throw new Error('renderUrl 未設定，請聯繫渲染端組員提供 Cloud Run URL');
        let res;
        try {
            res = await fetch(url, {
                method: 'POST',
                headers: this._renderHeaders(),
                body: JSON.stringify({ image: imageDataUrl, styleId, strength }),
            });
        } catch (err) {
            throw new Error('無法連線到渲染服務：' + err.message);
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data?.error?.message || data?.error || `Render API HTTP ${res.status}`);
        }
        if (data.status !== 'completed' || !data.afterImageUrl) {
            throw new Error(data?.error?.message || data?.error || '妝容渲染失敗');
        }
        return data;
    },

    async recommendProducts(faceAnalysis, styleId) {
        const url = this.config.url('product', 'recommendPath');
        if (!url) return null;
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                faceShape:  faceAnalysis?.faceShape  || null,
                eyeShape:   faceAnalysis?.eyeShape   || null,
                skinTone: {
                    season:  faceAnalysis?.skinTone?.season || null,
                    level:   faceAnalysis?.skinTone?.level  || null,
                    lab:     faceAnalysis?.skinTone?.lab    || null,
                },
                lipLab:     faceAnalysis?.lipLab     || null,
                style:      styleId || null,
            })
        });
        if (!res.ok) return null;
        return res.json();
    },

    async login(email, password) {
        try { sessionStorage.removeItem('beautyAiAccessToken'); } catch (_) {}
        const res = await fetch(this.config.url('memberDatabase', 'loginPath'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        if (!res.ok) throw new Error('登入 API 連線失敗');
        const data = await res.json();
        await this._createAiSession(email, password);
        return data;
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
        members[this._email(profile.email)] = { ...(members[this._email(profile.email)] || {}), ...profile };
        localStorage.setItem(this._membersKey, JSON.stringify(members));
    },
    getUser()  { return sessionStorage.getItem('beautyUser') || ''; },
    getProfile() { return JSON.parse(sessionStorage.getItem('beautyProfile') || '{}'); },
    setProfile(profile) {
        sessionStorage.setItem('beautyProfile', JSON.stringify(profile || {}));
        if (profile?.name) sessionStorage.setItem('beautyUser', profile.name);
        this.saveRegisteredMember(profile);
    },
    setUser(n) {
        sessionStorage.setItem('beautyUser', n);
        const profile = this.getProfile();
        this.setProfile({ ...profile, name: n });
    },
    isLoggedIn() { return !!this.getUser(); },
    logout() {
        sessionStorage.removeItem('beautyUser');
        sessionStorage.removeItem('beautyProfile');
        sessionStorage.removeItem('beautyAiAccessToken');
        location.reload();
    },
};

// ═══ 收藏模組 ═══
const Fav = {
    _key: 'beautyFav',
    list()     { return JSON.parse(localStorage.getItem(this._key) || '[]'); },
    has(id)    { return this.list().includes(id); },
    toggle(id) {
        const arr = this.list();
        const idx = arr.indexOf(id);
        if (idx >= 0) arr.splice(idx, 1); else arr.push(id);
        localStorage.setItem(this._key, JSON.stringify(arr));
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
        const row = items.find(item => item.id === Number(id));
        if (row) row.qty += 1;
        else items.push({ id: Number(id), qty: 1 });
        this.save(items);
        return items;
    },
    change(id, delta) {
        const items = this.list();
        const row = items.find(item => item.id === Number(id));
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
