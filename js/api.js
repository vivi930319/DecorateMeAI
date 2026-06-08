// ═══ API 串接層 ═══
const Api = {
    BASIC_ENDPOINT: 'http://127.0.0.1:8001/analyze',
    PRO_ENDPOINT: 'http://127.0.0.1:8002/analyze-pro',
    AUTH_BASE: 'https://vegetation-arguments-final-inspiration.trycloudflare.com',

    // 臉部分析
    async analyzeFace(file) {
        const fd = new FormData();
        fd.append('file', file);
        const res = await fetch(this.BASIC_ENDPOINT, { method: 'POST', body: fd });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '伺服器錯誤' }));
            throw new Error(err.detail || '分析失敗');
        }
        const data = await res.json();
        return { data, imageMeta: { front: ImagePipeline.metaFromFile(file, 'front') } };
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
        const res = await fetch(this.PRO_ENDPOINT, { method: 'POST', body: fd });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: '伺服器錯誤' }));
            throw new Error(err.detail || '分析失敗');
        }
        const data = await res.json();
        return { data, imageMeta };
    },

    async login(email, password) {
        const res = await fetch(`${this.AUTH_BASE}/api/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        if (!res.ok) throw new Error('登入 API 連線失敗');
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
        const res = await fetch(`${this.AUTH_BASE}/api/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!res.ok) throw new Error('註冊 API 連線失敗');
        return res.json();
    },

    async sendOTP(email) {
        for (const endpoint of ['/api/send-otp', '/api/register']) {
            try {
                const res = await fetch(`${this.AUTH_BASE}${endpoint}`, {
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
        const res = await fetch(`${this.AUTH_BASE}/api/verify-otp`, {
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

    async compressForPackage(file, opts = {}) {
        const role = opts.role || 'front';
        if (!file || !file.type?.startsWith('image/')) {
            return { file, meta: this.metaFromFile(file, role), dataUrl: null };
        }

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
                compressionRatio: file.size ? Number((processed.size / file.size).toFixed(3)) : null
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
            compressionRatio: null
        };
    }
};

// ═══ 分析資料包：預留 BASIC / PRO / 渲染 / 推薦 / 非同步狀態欄位 ═══
const AnalysisPackage = {
    create({ mode, images = {}, status = 'draft' }) {
        const now = new Date().toISOString();
        return {
            schemaVersion: '2026-06-basic-pro',
            id: `AN-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            mode,
            status,
            createdAt: now,
            updatedAt: now,
            images,
            analysis: {
                basic: null,
                pro: null,
                confidence: {},
                warnings: []
            },
            generativeText: {
                prompt: null,
                suggestion: null,
                model: null,
                status: 'pending'
            },
            render: {
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
                startedAt: null,
                completedAt: null,
                durationMs: null,
                error: null
            }
        };
    },

    update(pkg, patch) {
        return { ...(pkg || this.create({ mode: 'basic' })), ...patch, updatedAt: new Date().toISOString() };
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
    getUser()  { return localStorage.getItem('beautyUser') || ''; },
    getProfile() { return JSON.parse(localStorage.getItem('beautyProfile') || '{}'); },
    setProfile(profile) {
        localStorage.setItem('beautyProfile', JSON.stringify(profile || {}));
        if (profile?.name) localStorage.setItem('beautyUser', profile.name);
    },
    setUser(n) {
        localStorage.setItem('beautyUser', n);
        const profile = this.getProfile();
        this.setProfile({ ...profile, name: n });
    },
    isLoggedIn() { return !!this.getUser(); },
    logout() {
        localStorage.removeItem('beautyUser');
        localStorage.removeItem('beautyProfile');
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
