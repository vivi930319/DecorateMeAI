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

// 後台「專題展示」：用一次 AI 工作階段說明資料流向——哪些欄位前端看得到、哪些只留在後端。
// 只顯示白名單摘要，照片、Email、權杖、完整分析包與完整提示詞一律不出現。
// 由 adminDemoEnabled 控制開關、adminDemoExpiresAt 控制到期，專題結束後可直接關掉。
function initAdminDemo() {
    const panel = document.getElementById('adminDemoPanel');
    if (!panel || typeof AdminStore === 'undefined' || !AdminStore.isAdmin()) return;
    const featureDefaults = (typeof window !== 'undefined' && window.DECORATE_ME_FEATURES) || {};
    const runtimeConfig = (typeof window !== 'undefined' && window.DECORATE_ME_CONFIG) || {};
    const runtime = { ...featureDefaults, ...runtimeConfig };
    const expiresAt = runtime.adminDemoExpiresAt ? new Date(runtime.adminDemoExpiresAt) : null;
    const enabled = runtime.adminDemoEnabled === true && (!expiresAt || Number.isNaN(expiresAt.getTime()) || Date.now() < expiresAt.getTime());
    if (!enabled) {
        panel.remove();
        return;
    }
    panel.hidden = false;

    // 有真實分析資料就用遮罩後的摘要，否則用示範值，確保沒跑過分析也能展示流程
    const packageData = (typeof Router !== 'undefined' && Router.analysisPackage && typeof Router.analysisPackage === 'object')
        ? Router.analysisPackage : null;
    const face = packageData && typeof packageData.faceAnalysis === 'object' ? packageData.faceAnalysis : {};
    const valueFrom = (keys, fallback) => {
        for (const key of keys) {
            const value = face?.[key] ?? packageData?.[key];
            if (typeof value === 'string' && value.trim()) return value.trim().slice(0, 48);
        }
        return fallback;
    };
    const summary = {
        faceShape: valueFrom(['faceShape', 'face_shape'], 'oval'),
        skinTone: valueFrom(['skinTone', 'skin_tone'], 'medium'),
        undertone: valueFrom(['undertone', 'skinUndertone'], 'warm'),
        styleId: String((packageData?.render && packageData.render.styleId) || packageData?.styleId || 'natural').slice(0, 48)
    };
    const source = document.getElementById('adminDemoSource');
    if (source) source.textContent = packageData ? '本次工作遮罩摘要' : 'Demo 範例資料';
    const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
    const accountName = document.getElementById('adminDemoAccountName');
    const accountEmail = document.getElementById('adminDemoAccountEmail');
    const liveTime = document.getElementById('adminDemoLiveTime');
    if (accountName) accountName.textContent = profile.name || '管理員';
    if (accountEmail) accountEmail.textContent = profile.email || '未取得 Email';
    const paintLiveTime = () => { if (liveTime) liveTime.textContent = `更新時間 ${new Date().toLocaleTimeString('zh-TW', { hour:'2-digit', minute:'2-digit', second:'2-digit' })}`; };
    paintLiveTime();
    if (panel._liveTimeTimer) window.clearInterval(panel._liveTimeTimer);
    panel._liveTimeTimer = window.setInterval(paintLiveTime, 1000);

    const stages = [
        {
            presenterTitle: '步驟 1：照片上傳與安全驗證', presenterNote: '系統先驗證檔案格式與大小，照片只進入私人暫存區，不會公開暴露。',
            stage: 'uploaded', progress: 10, note: '照片已進入私人暫存區。',
            publicData: { jobId: 'JOB-DEMO-7C21', status: 'running', stage: 'uploaded', progress: 10 },
            protectedData: { imageObject: 'temporary/USER-***/JOB-***/input.webp', access: 'worker-only', expiresIn: '24h' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'upload.validated', durationMs: 218 }
        },
        {
            presenterTitle: '步驟 2：AI 臉部特徵分析', presenterNote: '模型辨識臉型、膚色與五官特徵，完整特徵點只保留在受限的後端工作環境。',
            stage: 'face_analysis', progress: 35, note: '模型正在產生結構化臉部特徵。',
            publicData: { jobId: 'JOB-DEMO-7C21', status: 'running', stage: 'face_analysis', progress: 35 },
            protectedData: { analysisPackage: '[完整特徵已隱藏]', landmarks: '[468 points hidden]', access: 'worker-only' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'analysis.running', modelVersion: 'basic-roi-v1' }
        },
        {
            presenterTitle: '步驟 3：產生個人化妝容建議', presenterNote: '分析摘要被轉換成適合使用者的風格與妝容方案，畫面只顯示必要的白名單結果。',
            stage: 'recommendation', progress: 55, note: '分析摘要已轉換為妝容方案。',
            publicData: { faceShape: summary.faceShape, skinTone: summary.skinTone, undertone: summary.undertone, styleId: summary.styleId },
            protectedData: { renderPrompt: '[完整提示詞已隱藏]', promptVersion: 'v3', access: 'worker-only' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'recommendation.completed', durationMs: 1840 }
        },
        {
            presenterTitle: '步驟 4：AI 妝容圖片渲染', presenterNote: '渲染服務依照妝容方案生成結果，同時維持人物身分與原始臉部結構。',
            stage: 'rendering', progress: 78, note: '第三方模型正在產生妝容結果圖。',
            publicData: { jobId: 'JOB-DEMO-7C21', status: 'running', stage: 'rendering', progress: 78 },
            protectedData: { inputObject: 'temporary/USER-***/JOB-***/input.webp', resultObject: null, tokenHash: 'sha256:••••••••' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'render.provider_wait', attempt: 1 }
        },
        {
            presenterTitle: '步驟 5：成果保存與安全存取', presenterNote: '結果完成後保存於私人空間，使用者查看時才取得短效網址，完整流程可追蹤但不記錄敏感內容。',
            stage: 'completed', progress: 100, note: '結果已保存至私人 GCS，查看時才簽發短效網址。',
            publicData: { recordId: 'LOOK-DEMO-19', status: 'completed', styleId: summary.styleId, signedUrlTtl: '10 minutes' },
            protectedData: { resultObject: 'users/USER-***/renders/LOOK-***.webp', temporaryPayload: 'scheduled_for_deletion', bucket: 'private' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'workflow.completed', sensitivePayload: '[not logged]' }
        }
    ];
    const text = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    let currentIndex = 0;
    const render = index => {
        currentIndex = Math.max(0, Math.min(stages.length - 1, index));
        const item = stages[currentIndex] || stages[0];
        text('adminDemoStage', item.stage);
        text('adminDemoProgressText', `${item.progress}%`);
        text('adminDemoStageNote', item.note);
        text('adminDemoPublicData', JSON.stringify(item.publicData, null, 2));
        text('adminDemoProtectedData', JSON.stringify(item.protectedData, null, 2));
        text('adminDemoLogData', JSON.stringify(item.logData, null, 2));
        const bar = document.getElementById('adminDemoProgressBar');
        if (bar) bar.style.width = `${item.progress}%`;
        panel.querySelectorAll('[data-demo-step]').forEach((button, buttonIndex) => {
            button.classList.toggle('active', buttonIndex === currentIndex);
            button.classList.toggle('complete', buttonIndex < currentIndex);
            button.setAttribute('aria-pressed', String(buttonIndex === currentIndex));
        });
    };
    panel.querySelectorAll('[data-demo-step]').forEach(button => {
        button.onclick = () => render(Number(button.dataset.demoStep));
    });
    const restart = document.getElementById('adminDemoRestart');
    if (restart) restart.onclick = () => render(0);
    if (expiresAt && !Number.isNaN(expiresAt.getTime())) {
        text('adminDemoExpiry', `展示功能到期：${expiresAt.toLocaleString('zh-TW')}`);
    } else {
        text('adminDemoExpiry', '展示功能未設定到期時間');
    }
    render(0);
}

// 會員資料庫的點數紀錄回的是英文代碼（check_in、task_first_analysis…），本機補的紀錄則已經是中文。
// 這裡只翻譯代碼、中文原樣保留；認不出來的代碼也照原樣顯示，不要變成空白或「點數異動」而失去線索。
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

function loadGeneralProductCatalog(onDone) {
    if (Array.isArray(Router?.generalProductCatalog) && Router.generalProductCatalog.length) {
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
// 將英文渲染指令收在可展開區塊，方便專題記錄與複製。
function renderPromptDisclosure(pkg) {
    const gen = pkg?.generativeText || {};
    const ollama = String(gen.ollamaRenderPromptEn || '').trim();
    // 同時顯示模型產生的內容與後端送出的完整指令。
    const full = String(gen.renderPromptEn || '').trim();
    if (!ollama && !full) return '';
    const block = (title, note, text) => text ? `
        <div class="prompt-block">
            <div class="prompt-block-head"><b>${escapeHtml(title)}</b><button class="btn-outline btn-sm" type="button" data-copy-prompt>複製</button></div>
            <p class="prompt-block-note">${escapeHtml(note)}</p>
            <pre class="prompt-text">${escapeHtml(text)}</pre>
        </div>` : '';
    return `
        <details class="prompt-disclosure">
            <summary>查看送給圖像模型的英文指令（供紀錄用）</summary>
            ${block('Ollama 產出的妝容指令', '文字建議服務針對這張臉與這個風格產生的部分。只描述「要上什麼妝」。', ollama)}
            ${block('實際送出的完整 prompt', '上面那段再加上我方固定疊加的 identity lock（要求模型不得改變長相、姿勢、背景）。這才是圖像模型真正收到的內容。', full)}
        </details>`;
}

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
    const cells = { 'r-face': '臉型', 'r-brow': '眉型', 'r-eye': '眼型', 'r-nose': '鼻型', 'r-lip': '嘴型' };
    Object.entries(cells).forEach(([id, field]) => {
        const el = document.getElementById(id);
        if (el && Router.analysisResult[field]) el.textContent = Router.analysisResult[field];
    });
    // 已經排隊等收藏的那筆快照是修正前建的，丟掉讓它重建。
    Router.pendingLook = null;
}

function renderAnalysisFeedback(result, packageId) {
  const box = document.getElementById('analysisFeedback');
  if (!box || typeof AnalysisFeedback === 'undefined') return;
  const fields = Object.keys(AnalysisFeedback.OPTIONS)
    .filter(field => result && result[field] && !String(result[field]).startsWith('無法判斷'));
  if (!fields.length) { box.style.display = 'none'; return; }

  const saved = AnalysisFeedback.forPackage(packageId);
  const corrections = saved ? { ...saved.corrections } : {};
  // predicted 優先使用模型原始輸出，沒有 _modelRaw 時才使用目前結果。
  const raw = (result && typeof result._modelRaw === 'object' && result._modelRaw) || {};
  const predicted = {};
  fields.forEach(field => { predicted[field] = raw[field] || result[field]; });
  // 若後端已套用修正，從目前值與原始值的差異還原回饋面板。
  fields.forEach(field => {
    if (!corrections[field] && predicted[field] && result[field] && result[field] !== predicted[field]) {
      corrections[field] = result[field];
    }
  });

  const draw = () => {
    box.innerHTML = `
      <div class="af-head">
        <b>這些判斷準嗎？</b>
        <p>覺得哪一項不對就改掉，其餘視為正確。你的修正會<strong>立刻套用</strong>到這次的妝容建議與收藏，
           並回報給分析模型作為訓練資料；<strong>這一步不會上傳你的照片</strong>，只送出判斷結果與你的修正。</p>
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
              corrections
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
  var ts = item.timestamp ? formatAnalysisTime(item.timestamp) : '';
  var ov=document.createElement('div'); ov.id='lookModal'; ov.className='look-modal';
  ov.innerHTML='<div class="lm-card" role="dialog" aria-modal="true">'
    +'<button class="lm-close" aria-label="關閉">×</button>'
    +'<div class="lm-photo">'+photo+'</div>'
    +'<div class="lm-body"><div class="lm-kicker">'+escapeHtml(item.title||'Saved Look')+'</div>'
    +'<h2>'+escapeHtml(item.style||'妝容建議')+'</h2><time>'+escapeHtml(ts)+'</time>'
    +(tags?'<div class="analysis-tags" style="margin-top:14px;">'+tags+'</div>':'')
    +'<div class="lm-summary"><span><em>臉型</em>'+escapeHtml(r['臉型']||'—')+'</span><span><em>眼型</em>'+escapeHtml(r['眼型']||'—')+'</span><span><em>鼻型</em>'+escapeHtml(r['鼻型']||'—')+'</span><span><em>膚色</em>'+escapeHtml(skin['四季型']||skin['膚色分級']||'—')+'</span></div>'
    +(rows?'<div class="lm-advice-grid">'+rows+'</div>':'')
    +'</div></div>';
  document.body.appendChild(ov); void ov.offsetWidth; ov.classList.add('show');
  function close(){ ov.classList.remove('show'); setTimeout(function(){ ov.remove(); },350); }
  ov.querySelector('.lm-close').onclick=close;
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
        const rows = Cart.list()
            .map(item => ({ ...item, product: catalog.find(p => String(p.id) === String(item.id)) }))
            .filter(item => item.product);
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
                <div class="cart-thumb">${phBox('', item.product.name, item.product.img)}</div>
                <div class="cart-item-info"><span>${escapeHtml(CAT_EN[item.product.cat] || item.product.cat)}</span><h3>${escapeHtml(item.product.name)}</h3><p>${escapeHtml(item.product.price)}</p></div>
                <div class="cart-qty"><button data-cart-minus="${escapeHtml(item.id)}" aria-label="減少 ${escapeHtml(item.product.name)}">−</button><b>${escapeHtml(item.qty)}</b><button data-cart-plus="${escapeHtml(item.id)}" aria-label="增加 ${escapeHtml(item.product.name)}">＋</button></div>
            </article>`).join('') : `<div class="cart-empty">${emptyMessage}</div>`}</div>
            <footer><span>共 ${Cart.count()} 件商品</span><button class="cart-checkout" ${rows.length ? '' : 'disabled'}>前往結帳</button></footer>
        </section>`;
        overlay.querySelector('.cart-close').onclick = () => overlay.remove();
        overlay.querySelectorAll('[data-cart-minus]').forEach(btn => btn.onclick = () => { Cart.change(btn.dataset.cartMinus, -1); updateCartBadge(); render(); });
        overlay.querySelectorAll('[data-cart-plus]').forEach(btn => btn.onclick = () => { Cart.change(btn.dataset.cartPlus, 1); updateCartBadge(); render(); });
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
    <div class="arch-tagline"><div class="at-text">為你打造的<em>美學旅程</em> · 從臉部分析開始</div><span class="at-cta">開始臉部分析　→</span></div>
</div>
<div class="dash-greet">
    <div class="greet-l">
        <span class="eyebrow">Welcome</span>
        <h1 id="dashGreet">歡迎回來，<span class="accent">訪客</span></h1>
        <div class="greet-actions">
            <span class="btn-outline" data-nav="analysis">開始臉部分析　→</span>
            <div class="tone-scale" title="膚色比對"><div class="swatches"><span style="background:#F1D9C4"></span><span style="background:#E4BE9E"></span><span style="background:#CFA079"></span><span style="background:#A9774F"></span><span style="background:#7C5334"></span></div><em>找到你的專屬色號</em></div>
        </div>
    </div>
    <div class="greet-r"><div class="greet-date" id="dashDate">—</div><div class="greet-meta">Your Beauty Atelier</div></div>
</div>
<section id="dashPersonalSection" style="display:none;">
    <div class="dash-sec-head"><div class="sh-l"><span class="sh-no">AI</span><h2>猜你喜歡</h2></div></div>
    <div class="glow-row" id="dashPersonal"></div>
</section>
<div class="dash-sec-head"><div class="sh-l"><span class="sh-no">01</span><h2>風格靈感</h2></div><span class="sh-link" data-nav="style">瀏覽全部風格</span></div>
<div class="insp-row" id="dashInsp"></div>
<div class="dash-sec-head"><div class="sh-l"><span class="sh-no">02</span><h2>為你精選</h2></div><span class="sh-link" data-nav="products">查看全部商品</span></div>
<div class="glow-row" id="dashGlow"></div>
<section class="about-sys">
    <div class="as-head">
        <div class="about-headrow"><span class="as-eyebrow-it">About the Atelier</span><h2 class="about-title">OUR BEAUTY<span class="l2">SYSTEM</span></h2></div>
        <span class="bs-link" data-nav="analysis">開始你的美學旅程　→</span>
        <p class="bs-desc">「裝識你的美」是一套以科技與美學打造的個人美妝系統。從臉部分析解讀你的五官與膚色，到為你量身推薦的妝容風格與美妝逸品，我們相信，最美的樣子，是更認識自己的你。</p>
    </div>
    <div class="as-photo"><img class="as-photo-img" src="assets/brand/decorate-me-home.jpg" alt="Decorate Me 品牌識別" onload="this.classList.add('loaded')"><div class="as-photo-ph"><div class="demo-mark">❧</div><div class="demo-cap">商品形象照 · Demo</div></div></div>
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
                <div class="pro-scan-copy"><b>自動掃描拍攝</b><span>看著鏡頭取得正面照，再慢慢轉向側面；系統會依臉部 yaw 角度自動擷取。</span></div>
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
        <div class="package-status" id="packageStatus"><b>資料包狀態</b><span>尚未建立</span></div>
        <button class="btn-gold btn-full" id="analyzeBtn" style="margin-top:14px;">開 始 分 析</button>
    </div>
    <div>
        <div class="section-label"><span>NO.02</span>分 析 結 果</div>
        <div class="result-grid">
            <div class="result-cell"><div class="rlabel">臉型</div><div class="rvalue" id="r-face">—</div></div>
            <div class="result-cell"><div class="rlabel">眉型</div><div class="rvalue" id="r-brow">—</div></div>
            <div class="result-cell"><div class="rlabel">眼型</div><div class="rvalue" id="r-eye">—</div></div>
            <div class="result-cell"><div class="rlabel">鼻型</div><div class="rvalue" id="r-nose">—</div></div>
            <div class="result-cell"><div class="rlabel">嘴型</div><div class="rvalue" id="r-lip">—</div></div>
            <div class="result-cell"><div class="rlabel">色彩季型</div><div class="rvalue" id="r-season">—</div></div>
        </div>
        <div class="skin-box"><div class="skin-title">膚 色 基 準 · M A C</div><div class="skin-row"><div class="skin-swatch" id="skinSwatch"></div><div><div class="skin-name" id="skinName">—</div><div class="skin-lab" id="skinLab"></div></div></div><div class="skin-warn" id="skinReliabilityWarn" style="display:none;"></div></div>
        <div class="skin-box"><div class="skin-title">唇 色 原 始 值</div><div class="skin-row"><div class="skin-swatch" id="lipSwatch"></div><div><div class="skin-lab" id="lipLab"></div></div></div></div>
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
        <button class="admin-tab" data-admin-filter="suspended">已停權</button>
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
        <div class="member-avatar" id="profileAvatar">✦</div>
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
<section class="member-tier"><div class="member-section-head"><span>Membership</span><h2>會員等級</h2></div><div id="profileTierCard"></div></section>
<section class="member-tier"><div class="member-section-head"><span>Check-in</span><h2>每日打卡</h2></div><div id="profileCheckinCard"></div></section>
<section class="member-tier"><div class="member-section-head"><span>Theme Shop</span><h2>點數商店</h2></div><div id="profileThemeShop"></div></section>
<section class="member-tier"><div class="member-section-head"><span>Ledger</span><h2>點數紀錄</h2></div><div id="profilePointLedger"></div></section>
<section class="member-suggestions"><div class="member-section-head"><span>Saved Looks</span><h2>已收藏的妝容對比圖</h2></div><div id="profileSuggestionArea"></div></section>`
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
    const prompt = rd.renderPrompt || pkg.generativeText?.renderPromptEn || '';
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
            ${prompt ? `<details class="save-look-prompt"><summary>這次實際下給模型的指令</summary><pre>${escapeHtml(prompt)}</pre></details>` : ''}
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
    modal.innerHTML=`<div class="makeup-style-dialog product-recommendation-dialog"><div class="makeup-style-head"><div><span class="eyebrow">Products</span><h2>個人化商品推薦</h2><p>依照臉部分析與選擇的妝容風格，從現有商品中整理推薦。</p></div><button class="makeup-style-close" type="button" aria-label="關閉">×</button></div><div class="prod-grid recommendation-modal-grid"></div><div class="makeup-style-actions"><button class="btn-outline" type="button" data-close>稍後再看</button><button class="btn-gold" type="button" data-all>查看所有商品</button></div></div>`;
    document.body.appendChild(modal);
    const grid=modal.querySelector('.recommendation-modal-grid');

    // 推薦彈窗與商品頁共用同一份排序、補圖與價格資料。
    const draw=()=>{
        if(!document.getElementById('productRecommendationModal'))return;
        const products=orderRecommendedProducts(getRecommendedProductCatalog());
        if(!products.length){
            grid.classList.remove('prod-grid');
            grid.innerHTML=`<div class="empty-state">${Router.generalProductLoading?'推薦商品載入中...':'推薦商品正在整理中，也可以先查看所有商品。'}</div>`;
            return;
        }
        grid.classList.add('prod-grid');
        grid.innerHTML=products.slice(0,RECOMMENDED_DISPLAY_LIMIT).map((p,i)=>`
            <div class="prod-card reveal-in" data-pid="${escapeHtml(p.id)}" style="animation-delay:${Math.min(i*0.035,0.2)}s">
                <div class="pc-imgwrap">
                    ${phBox('',p.name,p.img)}
                    <button class="heart-btn pc-heart ${Fav.has(p.id)?'fav':''}" data-fav="${escapeHtml(p.id)}" aria-label="收藏">${HEART_SVG}</button>
                </div>
                <div class="pc-cat">${escapeHtml(CAT_EN[p.cat]||p.cat)}${p.brand?` · ${escapeHtml(p.brand)}`:''}</div>
                <div class="pc-name">${escapeHtml(p.name)}</div>
                ${p.matchReason?`<div class="pc-reason">${escapeHtml(p.matchReason)}</div>`:''}
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
    if(!Router.generalProductCatalog?.length)loadGeneralProductCatalog(draw);

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
            if (!rec?.products?.length) return;
            Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                recommendations: { ...Router.analysisPackage.recommendations, products: rec.products }
            });
            AnalysisDraft.save(Router.analysisPackage);
        }).catch(() => {});

        Router.pendingLook = buildCurrentLookRecord();
        Router.pendingLookSaved = false;
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
    if (typeof isGuest === 'function' && isGuest()) return { ok: false, reason: 'guest' };
    const profile = Auth.getProfile();
    if (typeof AdminStore !== 'undefined' && !AdminStore.canRender(profile)) return { ok: false, reason: 'plan' };

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
            const res = await fetch(`pages/${page}.html?v=20260624-brightness`, { cache: 'no-store' });
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
        const dEl = document.getElementById('dashDate');
        if (dEl) {
            const now = new Date();
            const wd = ['日','一','二','三','四','五','六'][now.getDay()];
            dEl.textContent = `${now.getMonth()+1}月 ${now.getDate()}日 · 週${wd}`;
        }

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
            if (!picks.length && !Router.generalProductLoading) {
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

        const setLoadingStatus = (text, active = false) => {
            if (!loadingStatus) return;
            loadingStatus.textContent = text;
            loadingStatus.classList.toggle('active', active);
        };

        const updatePackageStatus = () => {
            if (!packageStatus) return;
            const pkg = Router.analysisPackage;
            packageStatus.classList.toggle('ready', !!pkg);
            packageStatus.querySelector('span').textContent = pkg
                ? `${pkg.mode.toUpperCase()} · ${pkg.status} · ${Object.keys(pkg.images || {}).length} 張`
                : '尚未建立';
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

        const SCAN_HOLD_FRAMES = 2;
        let proScanValidCount = 0;
        let proScanCurrentTarget = '';

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

                const wantFront = !Router.proFiles.front && (absY <= 8 && Math.abs(pitch) <= 12);
                const wantSide  = Router.proFiles.front && !Router.proFiles.side && absY >= SIDE_YAW_MIN;
                const target = wantFront ? 'front' : wantSide ? 'side' : '';

                if (target !== proScanCurrentTarget) {
                    proScanValidCount = 0;
                    proScanCurrentTarget = target;
                }

                if (target) {
                    proScanValidCount++;
                    const label = target === 'front' ? '正面' : faceSide + '側面';
                    if (proScanValidCount < SCAN_HOLD_FRAMES) {
                        setProScanHint(`${label}角度正確，請保持不動… ${proScanValidCount}/${SCAN_HOLD_FRAMES}`);
                    } else {
                        proScanValidCount = 0;
                        proScanCurrentTarget = '';
                        storeProScanPhoto(target, blob, pose);
                        if (target === 'front') {
                            setProScanHint('正面完成。請轉向任一側面，轉好後保持不動，系統會自動擷取，不用再看螢幕');
                        } else {
                            setProScanHint(`${faceSide}側面已完成，可開始 PRO 分析`);
                            stopProScan();
                        }
                    }
                } else {
                    proScanValidCount = 0;
                    proScanCurrentTarget = '';
                    if (!Router.proFiles.front) {
                        setProScanHint('請直視鏡頭，讓臉部置中於橢圓框內');
                    } else {
                        const need = SIDE_YAW_MIN - absY;
                        setProScanHint(need > 0
                            ? `偵測中，再轉約 ${Math.round(need)}° 就到側面，轉好後保持不動即可`
                            : '偵測中，請稍候');
                    }
                }
            } catch (err) {
                proScanValidCount = 0;
                proScanCurrentTarget = '';
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
                setLoadingStatus('正在建立臉部分析 job', true);
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
                    setLoadingStatus(`分析中：${latestJob.stage || latestJob.status} ${progress}%`, true);
                });
                const data = response.result || response.data || response;
                Router.analysisResult = data;
                setLoadingStatus('分析完成，正在壓縮圖片並封裝資料包', true);
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
                setLoadingStatus('資料包已完成：壓縮照片 + 分析 JSON，等待文字建議', false);
                setTimeout(() => { bar.style.display = 'none'; fill.style.width = '0'; }, 400);

                document.getElementById('r-face').textContent = data['臉型'] || '—';
                document.getElementById('r-brow').textContent = data['眉型'] || '—';
                document.getElementById('r-eye').textContent = data['眼型'] || '—';
                document.getElementById('r-nose').textContent = data['鼻型'] || '—';
                document.getElementById('r-lip').textContent = data['嘴型'] || '—';
                document.getElementById('r-season').textContent = data['膚色']?.['四季型'] || '—';

                const skin = data['膚色'] || {}, lab = skin['LAB'] || {};
                document.getElementById('skinName').textContent = skin['膚色分級'] || '—';
                document.getElementById('skinLab').textContent = `L ${lab.L||0} a ${lab.a||0} b ${lab.b||0}`;
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
                document.getElementById('lipLab').textContent = `L ${lipLab.L||0} a ${lipLab.a||0} b ${lipLab.b||0}`;
                document.getElementById('lipSwatch').style.background = Api.labToRgb(lipLab.L||40, lipLab.a||0, lipLab.b||0);

                document.getElementById('goStyleBtn').style.display = 'inline-block';
                History.add({ ...data, analysisPackageId: Router.analysisPackage.id, mode: Router.analyzeMode });
                renderAnalysisFeedback(data, Router.analysisPackage.id);
            } catch (err) {
                bar.style.display = 'none'; fill.style.width = '0';
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                    status: 'failed',
                    async: { ...Router.analysisPackage.async, error: err.message }
                });
                AnalysisDraft.save(Router.analysisPackage);
                updatePackageStatus();
                setLoadingStatus('分析失敗，已保留草稿狀態', false);
                const offline = /Failed to fetch|NetworkError|Load failed/i.test(String(err.message || err));
                showAlert(offline
                    ? '目前無法連接臉部分析服務，請稍後再試。'
                    : '分析失敗：' + err.message, { type:'error' });
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
                    <div class="analysis-item"><span class="ai-label">鼻型</span><span class="ai-value">${r['鼻型']||'—'}</span></div>
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
        if (opts && opts.productId) {
            renderProductDetail(opts.productId);
        } else {
            renderShop((opts && opts.category) || Router.shopFilter || 'all');
        }

        function renderShop(filter) {
            Router.shopFilter = filter;
            const area = document.getElementById('productsArea');
            const cats = CATEGORIES.map(c => c.id);
            const chips = [`<button class="chip ${filter==='all'?'active':''}" data-filter="all">全部<span class="chip-en">All</span></button>`]
                .concat(cats.map(id => `<button class="chip ${filter===id?'active':''}" data-filter="${id}">${id}</button>`)).join('');
            const recommended = getRecommendedProductCatalog();
            // 排列與張數都跟推薦彈窗共用（見 orderRecommendedProducts）：同一份推薦
            // 在兩個地方必須列出同樣的商品。
            const recommendedByCat = orderRecommendedProducts(recommended);
            const apiCatalog = Array.isArray(Router.generalProductCatalog) ? Router.generalProductCatalog : [];
            // 就算已有個人化推薦也要載全部商品清單：下方「全部商品」要靠它，推薦卡缺圖時也要用它補圖
            const shouldLoadGeneralProducts = !apiCatalog.length && !Router.generalProductLoading;
            if (shouldLoadGeneralProducts) {
                loadGeneralProductCatalog(() => {
                    if (Router.currentPage === 'products') renderShop(filter);
                });
            }
            const catalog = apiCatalog;
            const list = filter === 'all' ? catalog : catalog.filter(p => p.cat === filter);
            const isLoadingProducts = Router.generalProductLoading && !apiCatalog.length;
            const header = `
                <div class="page-header"><span class="eyebrow">Boutique · 選物</span><h1>商品推薦</h1><div class="divider"></div></div>
                ${recommended.length ? `<section class="recommended-strip">
                    <div class="dash-sec-head"><div class="sh-l"><span class="sh-no">AI</span><h2>本次個人化推薦</h2></div></div>
                    <div class="prod-grid recommended-grid">${recommendedByCat.slice(0, RECOMMENDED_DISPLAY_LIMIT).map((p, i) => `
                        <div class="prod-card reveal-in" data-rec-pid="${escapeHtml(p.id)}" style="animation-delay:${Math.min(i*0.035,0.2)}s">
                            <div class="pc-imgwrap">${phBox('', p.name, p.img)}</div>
                            <div class="pc-cat">${escapeHtml(CAT_EN[p.cat]||p.cat)}${p.brand ? ` · ${escapeHtml(p.brand)}` : ''}</div>
                            <div class="pc-name">${escapeHtml(p.name)}</div>
                            <div class="pc-foot"><span class="pc-price">${escapeHtml(p.price)}</span></div>
                        </div>`).join('')}
                    </div>
                </section>` : ''}
                ${Router.productRecommendationError && !recommended.length ? '<div class="empty-state compact">個人化推薦暫時無法載入（推薦服務維護中），先為你顯示全部商品。</div>' : ''}
                <div class="filter-bar">${chips}</div>
                <div class="prod-count">${isLoadingProducts ? '商品載入中' : (Router.generalProductError && !list.length ? '商品服務暫時無法載入，請稍後再試' : `${list.length} 件商品`)}</div>`;
            const bindChips = () => {
                area.querySelectorAll('.chip').forEach(ch => ch.onclick = () => renderShop(ch.dataset.filter));
            };
            if (!recommended.length && !Router.productRecommendationLoading && Router.analysisPackage?.faceAnalysis) {
                Router.productRecommendationLoading = true;
                Api.recommendProducts(Router.analysisPackage, Router.selectedStyleId)
                    .then(rec => {
                        if (rec?.products?.length) {
                            Router.productRecommendationError = false;
                            Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                                recommendations: {
                                    ...(Router.analysisPackage.recommendations || {}),
                                    products: rec.products
                                }
                            });
                            AnalysisDraft.save(Router.analysisPackage);
                            if (Router.currentPage === 'products') renderShop(filter);
                        } else if (rec && rec.ok === false) {
                            // 推薦服務打不到（例如 /recommend-products 404）——記錄下來讓畫面顯示提示，不再靜默
                            Router.productRecommendationError = true;
                            if (Router.currentPage === 'products') renderShop(filter);
                        }
                    })
                    .catch(() => { Router.productRecommendationError = true; })
                    .finally(() => { Router.productRecommendationLoading = false; });
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
            setTimeout(() => {
                if (Router.currentPage !== 'products' || Router.shopFilter !== filter) return;
                const content = list.length
                    ? `<div class="prod-grid">` + list.map((p, i) => `
                    <div class="prod-card reveal-in" data-pid="${p.id}" style="animation-delay:${Math.min(i*0.035,0.4)}s">
                        <div class="pc-imgwrap">
                            ${phBox('', p.name, p.img)}
                            <button class="heart-btn pc-heart ${Fav.has(p.id)?'fav':''}" data-fav="${p.id}" aria-label="收藏">${HEART_SVG}</button>
                        </div>
                        <div class="pc-cat">${escapeHtml(CAT_EN[p.cat]||p.cat)}</div>
                        <div class="pc-name">${escapeHtml(p.name)}</div>
                        ${p.brand ? `<div class="pc-cat">${escapeHtml(p.brand)}</div>` : ''}
                        <div class="pc-foot"><span class="pc-price">${escapeHtml(p.price)}</span></div>
                    </div>`).join('') + `</div>`
                    : `<div class="empty-state compact">${isLoadingProducts ? '商品載入中' : '目前沒有商品資料'}</div>`;
                area.innerHTML = header + content;
                bindChips();
                area.querySelectorAll('.prod-card').forEach(card => {
                    card.onclick = (e) => {
                        if (e.target.closest('.heart-btn')) return;
                        renderProductDetail(card.dataset.pid || card.dataset.recPid);
                    };
                });
                area.querySelectorAll('.pc-heart').forEach(btn => {
                    btn.onclick = (e) => {
                        e.stopPropagation();
                        const id = btn.dataset.fav;
                        const wasFav = Fav.has(id);
                        Fav.toggle(id, list.find(x => String(x.id) === String(id)));
                        btn.classList.toggle('fav', !wasFav);
                        btn.classList.remove('swap'); void btn.offsetWidth; btn.classList.add('swap');
                        if (!wasFav) showToast('已加入收藏');
                    };
                });
            }, 360);
        }

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
            const renderColorBox = (hex) => hex
                ? `<div class="pd-color"><div class="pd-color-label">色號 <span>Shade</span></div><div class="pd-shades"><span class="shade active" style="background:${escapeHtml(hex)}" aria-label="商品色號"></span><code style="margin-left:8px;font-size:12px;color:var(--mid);">${escapeHtml(hex)}</code></div></div>`
                : '';
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
            const catToken = String(p.cat || '').replace(/[^a-zA-Z0-9_-]/g, '');
            area.innerHTML = `
                <div class="pd-top">
                    <a href="#" class="back-link" onclick="PageInit.products({category:'${catToken}'});return false;">← ${escapeHtml(p.cat)}</a>
                    <button class="pd-close" aria-label="關閉" onclick="PageInit.products({category:'${catToken}'});return false;">×</button>
                </div>
                <div class="pd-wrap">
                    <div class="pd-img">${phBox('', p.name, p.img)}</div>
                    <div class="pd-info">
                        <div class="pd-en">${CAT_EN[p.cat]||'BEAUTY'}</div>
                        <div class="pd-name">${escapeHtml(p.name)}</div>
                        ${p.brand ? `<div class="pd-en">${escapeHtml(p.brand)}</div>` : ''}
                        <div class="pd-price-lg">${escapeHtml(p.price)}</div>
                        <div id="pdColorBox">${renderColorBox(p.hex)}</div>
                        <div class="pd-actions">
                            <button class="add-bag" data-bag="${p.id}">加入購物袋</button>
                            <button class="heart-btn pd-heart ${Fav.has(p.id)?'fav':''}" data-fav-detail="${p.id}" aria-label="收藏">${HEART_SVG}</button>
                        </div>
                        <div class="pd-desc">${escapeHtml(p.desc || p.matchReason || '商品詳細說明區域。可放入完整描述、使用方式、成分說明等資訊。')}</div>
                    </div>
                </div>
                <div id="pdRelatedBox">${renderRelatedGrid(related, '你可能也喜歡')}</div>
            `;
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
    },

    favorites() {
        // 收藏可能來自 ALL_PRODUCTS demo 資料、真實商品 API、或分析後的個人化推薦，三邊都要查，不然收藏了也看不到。
        const apiCatalog = Array.isArray(Router.generalProductCatalog) ? Router.generalProductCatalog : [];
        const recommended = getRecommendedProductCatalog();
        const combined = [...ALL_PRODUCTS, ...apiCatalog, ...recommended];
        const seenIds = new Set();
        const catalog = combined.filter(p => {
            if (seenIds.has(String(p.id))) return false;
            seenIds.add(String(p.id));
            return true;
        });
        const items = catalog.filter(p => Fav.has(p.id));
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
        if (!apiCatalog.length && !Router.generalProductLoading) {
            loadGeneralProductCatalog(() => { if (Router.currentPage === 'favorites') PageInit.favorites(); });
        }
        if (!items.length) {
            const emptyText = syncState === 'loading' ? '正在讀取收藏商品' : '目前尚無收藏商品';
            area.innerHTML = syncNote + `<div class="empty-state">${emptyText}</div>`;
            bindRetry();
            return;
        }
        area.innerHTML = syncNote + `<div class="prod-count">${items.length} 件收藏</div><div class="prod-grid">` + items.map((p, i) => `
            <div class="prod-card reveal-in" data-pid="${p.id}" style="animation-delay:${Math.min(i*0.035,0.4)}s">
                <div class="pc-imgwrap">
                    ${phBox('', p.name, p.img)}
                    <button class="heart-btn pc-heart fav" data-unfav="${p.id}" aria-label="移除收藏">${HEART_SVG}</button>
                </div>
                <div class="pc-cat">${escapeHtml(CAT_EN[p.cat]||p.cat)}</div>
                <div class="pc-name">${escapeHtml(p.name)}</div>
                <div class="pc-foot"><span class="pc-price">${escapeHtml(p.price)}</span></div>
            </div>
        `).join('') + `</div>`;
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

    compare() {
        if (!hasStartedJourney()) { renderAnalysisGate("妝容對比圖"); return; }
        const style = STYLES.find(s => s.id === Router.selectedStyleId);
        const nameEl = document.getElementById('compareStyleName');
        const tagsEl = document.getElementById('compareStyleTags');
        const stage = document.getElementById('compareStage');
        const holdBtn = document.getElementById('compareHoldBtn');
        Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
        Router.pendingLookSaved = false;

        nameEl.textContent = style ? style.name : '尚未選擇風格';
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

    suggestion() {
        if (!hasStartedJourney()) { renderAnalysisGate("妝容建議"); return; }
        const style = STYLES.find(s => s.id === Router.selectedStyleId) || STYLES[0];
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
                <div class="analysis-item"><span class="ai-label">鼻型</span><span class="ai-value">${r['鼻型']||'—'}</span></div>
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
                ${renderPromptDisclosure(pkg)}
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

        // 英文指令的「複製」：抄到報告裡用。navigator.clipboard 在非 https 或
        // 使用者拒絕權限時會失敗，所以留一條 textarea + execCommand 的退路——
        // 這個功能存在的意義就是讓人複製得到，靜靜失敗等於沒做。
        document.querySelectorAll('[data-copy-prompt]').forEach(btn => {
            btn.onclick = async () => {
                const text = btn.closest('.prompt-block')?.querySelector('.prompt-text')?.textContent || '';
                if (!text) return;
                try {
                    await navigator.clipboard.writeText(text);
                } catch (_) {
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    ta.style.cssText = 'position:fixed;opacity:0';
                    document.body.appendChild(ta);
                    ta.select();
                    try { document.execCommand('copy'); } catch (_) {}
                    ta.remove();
                }
                showToast('已複製英文指令');
            };
        });

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
                // 重畫整頁，不是只換照片。收藏鍵與「重新生成妝容」是建樣板當下依
                // renderedImage 決定要不要輸出的，只換照片的話它們要等下次進頁才出現——
                // 使用者剛渲染完，最想按的那顆卻不在。Step 1 成功時走的也是這條。
                PageInit.suggestion();
                // 按鈕在頁面下方，成果圖在最上面。不捲回去的話使用者按完只看到按鈕變回
                // 「重新生成妝容」，會以為沒反應——他要的東西在他看不到的地方。
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
                    <div class="hist-date">${r.timestamp ? escapeHtml(formatAnalysisTime(r.timestamp)) : ''}${r.mode ? ` · ${escapeHtml(String(r.mode).toUpperCase())}` : ''}</div>
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
            if (__avatarSrc) { __av.classList.add('has-photo'); __av.innerHTML = '<img src="' + __avatarSrc + '" alt="' + escapeHtml(user || '會員') + '">'; }
            else { __av.classList.remove('has-photo'); __av.textContent = (user && user !== '訪客') ? user.trim().charAt(0).toUpperCase() : '✦'; }
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
        document.querySelectorAll('.member-stats [data-scroll]').forEach(btn => {
            btn.onclick = () => {
                const target = document.getElementById(btn.dataset.scroll);
                if (!target) return;
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
        // 收藏數直接讀取 Fav 清單，確保 API 商品也會被計入。
        if (favEl) { favEl.textContent = Fav.list().length; favEl.classList.add('num-pop'); }
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
                        <p class="checkin-streak">${streakLine}${source === 'remote' ? '（資料庫同步）' : '（尚未取得資料庫紀錄）'}</p>
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
                        <time>${createdAt ? new Date(createdAt).toLocaleString('zh-TW') : ''}</time>
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
                const timestamp = escapeHtml(item.timestamp ? formatAnalysisTime(item.timestamp) : '');
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
                        <time>${timestamp}</time>
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
        const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
        const profileNameEl = document.getElementById('adminProfileName');
        const profileEmailEl = document.getElementById('adminProfileEmail');
        if (profileNameEl) profileNameEl.textContent = profile.name || '管理員';
        if (profileEmailEl) profileEmailEl.textContent = profile.email || '—';

        const sectionMeta = {
            overview: { eyebrow: 'ADMIN OVERVIEW', title: '營運總覽' },
            demo: { eyebrow: 'PROJECT DEMONSTRATION', title: '專題展示' },
            members: { eyebrow: 'MEMBER ACCESS', title: '會員與權限管理' },
            products: { eyebrow: 'PRODUCT CATALOG', title: '商品管理' },
            crawler: { eyebrow: 'CRAWLER STAGING', title: '暫存商品審核' }
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
            document.querySelector('.admin-stage')?.scrollTo({ top: 0, behavior: 'smooth' });
        };
        let initialSection = 'overview';
        try { initialSection = sessionStorage.getItem('beautyAdminSection') || 'overview'; } catch (_) {}
        sectionButtons.forEach(btn => { btn.onclick = () => setAdminSection(btn.dataset.adminSection); });
        document.querySelectorAll('[data-admin-jump]').forEach(btn => { btn.onclick = () => setAdminSection(btn.dataset.adminJump); });
        setAdminSection(initialSection);
        initAdminDemo();

        let memberConnectionState = 'pending';
        let productConnectionState = 'pending';
        const updateOverallStatus = () => {
            const el = document.getElementById('adminOverallStatus');
            if (!el) return;
            const states = [memberConnectionState, productConnectionState];
            const failed = states.includes('error');
            const ready = states.every(state => state === 'ok');
            el.className = `admin-sync-status ${failed ? 'error' : (ready ? 'ok' : 'pending')}`;
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
                        <button class="admin-status ${perm.status === 'suspended' ? 'off' : 'on'}" data-admin-status type="button">
                            ${perm.status === 'suspended' ? '已停權' : '啟用中'}
                        </button>
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

            rowsEl.querySelectorAll('[data-admin-status]').forEach(btn => {
                btn.onclick = async () => {
                    const row = btn.closest('[data-admin-email]');
                    const email = row?.dataset.adminEmail;
                    const target = dbMembers.find(m => m.email === email);
                    const nextStatus = (target?.status === 'suspended') ? 'active' : 'suspended';
                    btn.disabled = true;
                    const result = await Api.patchMember(email, { status: nextStatus });
                    btn.disabled = false;
                    if (!result.ok) { showAlert(`停權狀態同步失敗：${result.error}`, { type: 'error' }); return; }
                    if (target) target.status = nextStatus;
                    showToast(nextStatus === 'suspended' ? '已停權（已寫入資料庫）' : '已恢復啟用（已寫入資料庫）');
                    render();
                };
            });

            rowsEl.querySelectorAll('[data-admin-delete]').forEach(btn => {
                btn.onclick = () => {
                    const row = btn.closest('[data-admin-email]');
                    const email = row?.dataset.adminEmail;
                    if (!email || btn.disabled) return;
                    showConfirm(`確定要刪除會員「${email}」嗎？會員資料、點數與收藏關聯可能一併移除，此動作無法復原。`, {
                        title: '刪除會員資料', type: 'error', okText: '刪除會員', cancelText: '保留',
                        onOk: async () => {
                            btn.disabled = true;
                            const result = await Api.deleteMember(email);
                            if (!result || !result.ok) {
                                btn.disabled = false;
                                showAlert(`會員刪除失敗：${result?.error || '請確認會員資料庫連線與管理員權限'}`, { type: 'error' });
                                return;
                            }
                            dbMembers = dbMembers.filter(member => String(member.email).toLowerCase() !== String(email).toLowerCase());
                            delete looksByEmail[email];
                            delete pointsByEmail[email];
                            showToast('會員已從資料庫刪除');
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
            // 逐筆 PATCH 進資料庫；前端不再自行核發權限，只在成功後同步顯示資料庫回傳結果
            saveBtn.disabled = true;
            const failures = [];
            for (const r of rows) {
                const patch = { role: r.role, allowedPages: r.allowedPages };
                if (r.level) patch.level = r.level;
                const result = await Api.patchMember(r.email, patch);
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
            document.getElementById('adminProductStyleTags').value = joinTags(product.styleTags);
            document.getElementById('adminProductFinishTags').value = joinTags(product.finishTags);
            document.getElementById('adminProductSeasonTags').value = joinTags(product.seasonTags);
            document.getElementById('adminProductOccasionTags').value = joinTags(product.occasionTags);
            productForm.classList.add('is-editing');
            editingLabel.textContent = product.name || id;
            createBtn.disabled = true;
            editBtn.disabled = false;
            cancelBtn.style.display = '';
            if (formDeleteBtn) formDeleteBtn.disabled = false;
            productForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
            const products = dbProducts;
            const searchStatus = document.getElementById('adminProductSearchStatus');
            if (searchStatus) {
                searchStatus.textContent = normalizedQuery
                    ? `找到 ${productResultTotal} 筆符合「${productSearchQuery.trim()}」的資料庫商品。`
                    : `目前條件共有 ${productResultTotal} 筆商品。`;
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
            const fetchAllPages = async () => {
                const all = [];
                const seen = new Set();
                const usedCursors = new Set();
                let cursor = null;
                let firstRec = null;
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
                }
                // 迴圈是被 PRODUCT_MAX_PAGES 上限中止、而不是自然翻完的話，同樣是一份
                // 不完整的清單。先前只有「某一頁失敗」那條標了 partial，這條沒標，於是
                // 截斷的結果照樣掛著伺服器回的總數——同一個 bug 換一個分支重演。
                return { ...firstRec, products: all, partial: cursor != null };
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
        if (productSearchClearBtn) productSearchClearBtn.onclick = () => {
            if (productSearchInput) productSearchInput.value = '';
            const type = document.getElementById('adminProductTypeFilter'); if (type) type.value = '';
            const status = document.getElementById('adminProductStatusFilter'); if (status) status.value = 'active';
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
                showConfirm(`確定要停用「${product.name || '這項商品'}」嗎？資料會保留在資料庫與稽核紀錄，但不再出現在上架商品及推薦結果。`, {
                    title: '停用商品',
                    type: 'error',
                    okText: '確認停用',
                    cancelText: '保留',
                    onOk: async () => {
                        deleteTrigger.disabled = true;
                        deleteTrigger.textContent = '停用中';
                        const result = await Api.deleteRemoteProduct(product.rawId ?? product.id);
                        if (!result.ok) {
                            deleteTrigger.disabled = false;
                            deleteTrigger.textContent = '刪除';
                            showAlert(`商品停用失敗：${result.error || '未知錯誤'}${result.status === 401 ? '（登入狀態已失效，請重新登入）' : ''}`, { type: 'error' });
                            return;
                        }
                        if (String(editingProductId) === String(product.id)) exitEditMode();
                        Router.generalProductCatalog = null;
                        showToast('商品已停用並保留稽核紀錄');
                        loadAdminProducts();
                        loadProductAuditLogs();
                    }
                });
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
                styleTags: splitTags(document.getElementById('adminProductStyleTags')?.value),
                finishTags: splitTags(document.getElementById('adminProductFinishTags')?.value),
                seasonTags: splitTags(document.getElementById('adminProductSeasonTags')?.value),
                occasionTags: splitTags(document.getElementById('adminProductOccasionTags')?.value)
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
                    } else {
                        showAlert(`資料庫寫入失敗：${result.error}${result.status === 401 ? '（登入狀態已失效，請重新登入）' : ''}`, { type: 'error' });
                    }
                    return false;
                }
                showToast(okMsg);
                Router.generalProductCatalog = null; // 讓商品頁下次重抓最新清單
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

        // ═══ 暫存商品審核 ═══
        // 爬蟲 2026-07-28 起只寫 crawler_staging_products，不再即時擷取。這一塊是審核那批資料。
        //
        // 商品後端尚未回覆最終路徑。 照規格書 §1 的提案先接起來；對方定案後只要改
        // ai_gateway.py 的 _STAGING_BASE 一行，這裡與 js/api.js 都不必動。
        const stagingList = document.getElementById('adminStagingList');
        if (stagingList) {
            const stagingFilters = document.getElementById('adminStagingFilters');
            const stagingState = document.getElementById('adminStagingState');
            const stagingMessage = document.getElementById('adminStagingMessage');
            const stagingPager = document.getElementById('adminStagingPager');
            const stagingPageInfo = document.getElementById('adminStagingPageInfo');

            // 後端回的是小寫英文狀態碼，中文與配色留在前端——要改字面不必動資料庫。
            const STATUS_ZH = {
                pending: '待審核', approved: '已核准', rejected: '已退回',
                imported: '已匯入', failed: '匯入失敗'
            };
            let filter = 'pending';
            let page = 1;
            const PAGE_SIZE = 20;

            const setState = (text, cls) => {
                if (stagingState) { stagingState.textContent = text; stagingState.className = 'admin-crawler-state ' + cls; }
            };
            const setMessage = (text, cls) => {
                if (stagingMessage) { stagingMessage.textContent = text; stagingMessage.className = 'admin-crawler-message ' + (cls || ''); }
            };

            const drawFilters = () => {
                if (!stagingFilters) return;
                stagingFilters.innerHTML = ['pending', 'approved', 'failed', 'imported', 'rejected', ''].map(value => {
                    const label = value ? STATUS_ZH[value] : '全部';
                    return `<button type="button" class="admin-staging-filter${filter === value ? ' active' : ''}" data-staging-filter="${value}">${label}</button>`;
                }).join('');
                stagingFilters.querySelectorAll('[data-staging-filter]').forEach(btn => {
                    btn.onclick = () => { filter = btn.dataset.stagingFilter; page = 1; load(); };
                });
            };

            const money = (price, currency) => {
                if (price == null || price === '') return '未取得價格';
                const n = Number(price);
                return `${currency || ''} ${Number.isFinite(n) ? n.toLocaleString('zh-TW') : price}`.trim();
            };

            // 清單縮圖優先用 640 的變體，省流量；沒有變體才退回原圖。
            // 只接受 https。規格書 §2.4 要求全部 HTTPS，但那是「請對方遵守」；
            // 混合內容會被瀏覽器擋掉、http 圖片也可能是被竄改的來源，所以這裡自己再擋一次。
            const httpsOnly = (url) => (/^https:\/\//i.test(String(url || '')) ? String(url) : '');
            const thumbOf = (item) => {
                const v = item.imageVariants || {};
                return httpsOnly(v['640']) || httpsOnly(v['320'])
                    || httpsOnly(Array.isArray(item.imageUrls) ? item.imageUrls[0] : '') || '';
            };

            const cardHtml = (item) => {
                const status = String(item.status || '').toLowerCase();
                const thumb = thumbOf(item);
                // 來源網址是爬蟲抓回來的外部內容，直接塞 href 等於讓對方決定點下去會執行什麼。
                const sourceLink = safeExternalUrl(item.sourceUrl);
                return `<article class="admin-staging-card" data-staging-id="${escapeHtml(item.id)}">
                    <div class="admin-staging-thumb">${thumb
                        ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(item.name || '商品圖片')}" loading="lazy">`
                        : '<span>無圖片</span>'}</div>
                    <div class="admin-staging-body">
                        <div class="admin-staging-head">
                            <b>${escapeHtml(item.name || '未取得名稱')}</b>
                            <span class="admin-staging-badge ${escapeHtml(status)}">${escapeHtml(STATUS_ZH[status] || status || '未知')}</span>
                        </div>
                        <p class="admin-staging-meta">${escapeHtml(item.brand || '未取得品牌')} · ${escapeHtml(money(item.price, item.currency))}</p>
                        <p class="admin-staging-meta">${escapeHtml(item.sourceSite || '')} ${escapeHtml(item.sourceProductId || '')} · ${escapeHtml(item.category || '未分類')}</p>
                        ${sourceLink ? `<p class="admin-staging-meta"><a href="${sourceLink}" target="_blank" rel="noopener noreferrer">看原始商品頁 ↗</a></p>` : ''}
                        ${item.failedReason ? `<p class="admin-staging-fail">${escapeHtml(item.failedReason)}</p>` : ''}
                        ${status === 'rejected' && item.reviewReason ? `<p class="admin-staging-meta">退回原因：${escapeHtml(item.reviewReason)}</p>` : ''}
                        ${item.importedProductId ? `<p class="admin-staging-meta">已匯入商品 id：${escapeHtml(item.importedProductId)}</p>` : ''}
                        <div class="admin-staging-actions">
                            ${status === 'pending' ? `
                                <button class="admin-primary-button" type="button" data-staging-act="approved">核准</button>
                                <button class="admin-secondary-button" type="button" data-staging-act="rejected">退回</button>` : ''}
                            ${status === 'approved' ? `
                                <button class="admin-primary-button" type="button" data-staging-act="import">匯入正式商品</button>` : ''}
                        </div>
                    </div>
                </article>`;
            };

            const act = async (id, action, card) => {
                card.querySelectorAll('button').forEach(b => { b.disabled = true; });
                let result;
                if (action === 'import') {
                    result = await Api.importStagingProduct(id);
                } else if (action === 'rejected') {
                    // 退回原因會顯示在清單上，但允許留空。
                    const reason = window.prompt('退回原因（可留空）：');
                    result = await Api.reviewStagingProduct(id, 'rejected', String(reason || '').trim());
                } else {
                    result = await Api.reviewStagingProduct(id, 'approved');
                }
                if (!result || !result.ok) {
                    setMessage(Api._stagingError(result), 'error');
                    card.querySelectorAll('button').forEach(b => { b.disabled = false; });
                    return;
                }
                // 重畫之後這一筆會從目前的篩選消失（狀態變了），沒有訊息的話使用者
                // 只看到它憑空不見，不確定是成功還是壞掉。
                const done = { approved: '已核准', rejected: '已退回', import: '已匯入正式商品' };
                setMessage(done[action] || '已更新', 'success');
                Router._stagingLoaded = false;
                load();
            };

            const load = async () => {
                setState('載入中', 'loading');
                setMessage('');
                stagingList.innerHTML = '<div class="admin-crawler-empty">讀取中…</div>';
                const result = await Api.listStagingProducts({ status: filter, page, pageSize: PAGE_SIZE });
                if (!result.ok) {
                    setState('讀取失敗', 'error');
                    setMessage(Api._stagingError(result), 'error');
                    // 端點還沒上線時這裡會是 404。講清楚是「還沒接上」而不是「壞掉」。
                    stagingList.innerHTML = `<div class="admin-crawler-empty">${escapeHtml(result.error || '讀取失敗')}<br><small>商品後端的暫存商品 API 若尚未上線，這裡會是 404。</small></div>`;
                    if (stagingPager) stagingPager.hidden = true;
                    return;
                }
                setState(`共 ${result.total} 筆`, result.total ? 'success' : 'idle');
                stagingList.innerHTML = result.items.length
                    ? result.items.map(cardHtml).join('')
                    : '<div class="admin-crawler-empty">這個狀態底下沒有資料</div>';
                stagingList.querySelectorAll('[data-staging-id]').forEach(card => {
                    card.querySelectorAll('[data-staging-act]').forEach(btn => {
                        btn.onclick = () => act(card.dataset.stagingId, btn.dataset.stagingAct, card);
                    });
                });
                const pages = Math.max(1, Math.ceil(result.total / PAGE_SIZE));
                if (stagingPager) {
                    stagingPager.hidden = pages <= 1;
                    if (stagingPageInfo) stagingPageInfo.textContent = `第 ${result.page} / ${pages} 頁`;
                    const prev = document.getElementById('adminStagingPrev');
                    const next = document.getElementById('adminStagingNext');
                    if (prev) { prev.disabled = result.page <= 1; prev.onclick = () => { page = result.page - 1; load(); }; }
                    if (next) { next.disabled = result.page >= pages; next.onclick = () => { page = result.page + 1; load(); }; }
                }
            };

            drawFilters();
            const refreshBtn = document.getElementById('adminStagingRefresh');
            if (refreshBtn) refreshBtn.onclick = () => load();

            // 只有真的切到這一節才載入。掛在 PageInit.admin 頂層的話，管理員每次進
            // 管理中台——不管是要看會員還是商品——都會對暫存商品端點打一次請求，
            // 而那個端點還沒上線，等於每次都保證一筆 404。
            Router._loadStagingOnce = () => {
                if (Router._stagingLoaded) return;
                Router._stagingLoaded = true;
                load();
            };
            if (document.querySelector('[data-admin-view="crawler"]:not([hidden])')) Router._loadStagingOnce();
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
                showApp();
                routeFromHash();
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

function showApp() {
    document.getElementById('auth-layer').innerHTML = '';
    document.getElementById('app').style.display = 'block';
    const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
    document.getElementById('sidebarUsername').textContent = `${getMemberDisplayName()} · ${getCurrentRoleLabel(profile)}`;
    updateCartBadge();
    refreshMemberTheme();
    syncRemoteFavorites();
    syncRemoteCart();
    const landing = (typeof AdminStore !== 'undefined' && AdminStore.isAdmin()) ? 'admin' : 'dashboard';
    updateAdminNav(landing);
    const homeUrl = `${location.pathname}${location.search}#${landing}`;
    if (location.hash !== `#${landing}`) history.replaceState(null, '', homeUrl);
    Router.go(landing);
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
