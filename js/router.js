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

    const stages = [
        {
            stage: 'uploaded', progress: 10, note: '照片已進入私人暫存區。',
            publicData: { jobId: 'JOB-DEMO-7C21', status: 'running', stage: 'uploaded', progress: 10 },
            protectedData: { imageObject: 'temporary/USER-***/JOB-***/input.webp', access: 'worker-only', expiresIn: '24h' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'upload.validated', durationMs: 218 }
        },
        {
            stage: 'face_analysis', progress: 35, note: '模型正在產生結構化臉部特徵。',
            publicData: { jobId: 'JOB-DEMO-7C21', status: 'running', stage: 'face_analysis', progress: 35 },
            protectedData: { analysisPackage: '[完整特徵已隱藏]', landmarks: '[468 points hidden]', access: 'worker-only' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'analysis.running', modelVersion: 'basic-roi-v1' }
        },
        {
            stage: 'recommendation', progress: 55, note: '分析摘要已轉換為妝容方案。',
            publicData: { faceShape: summary.faceShape, skinTone: summary.skinTone, undertone: summary.undertone, styleId: summary.styleId },
            protectedData: { renderPrompt: '[完整提示詞已隱藏]', promptVersion: 'v3', access: 'worker-only' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'recommendation.completed', durationMs: 1840 }
        },
        {
            stage: 'rendering', progress: 78, note: '第三方模型正在產生妝容結果圖。',
            publicData: { jobId: 'JOB-DEMO-7C21', status: 'running', stage: 'rendering', progress: 78 },
            protectedData: { inputObject: 'temporary/USER-***/JOB-***/input.webp', resultObject: null, tokenHash: 'sha256:••••••••' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'render.provider_wait', attempt: 1 }
        },
        {
            stage: 'completed', progress: 100, note: '結果已保存至私人 GCS，查看時才簽發短效網址。',
            publicData: { recordId: 'LOOK-DEMO-19', status: 'completed', styleId: summary.styleId, signedUrlTtl: '10 minutes' },
            protectedData: { resultObject: 'users/USER-***/renders/LOOK-***.webp', temporaryPayload: 'scheduled_for_deletion', bucket: 'private' },
            logData: { jobId: 'JOB-DEMO-7C21', event: 'workflow.completed', sensitivePayload: '[not logged]' }
        }
    ];
    const text = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    const render = index => {
        const item = stages[index] || stages[0];
        text('adminDemoStage', item.stage);
        text('adminDemoProgressText', `${item.progress}%`);
        text('adminDemoStageNote', item.note);
        text('adminDemoPublicData', JSON.stringify(item.publicData, null, 2));
        text('adminDemoProtectedData', JSON.stringify(item.protectedData, null, 2));
        text('adminDemoLogData', JSON.stringify(item.logData, null, 2));
        const bar = document.getElementById('adminDemoProgressBar');
        if (bar) bar.style.width = `${item.progress}%`;
        panel.querySelectorAll('[data-demo-step]').forEach((button, buttonIndex) => {
            button.classList.toggle('active', buttonIndex === index);
            button.setAttribute('aria-pressed', String(buttonIndex === index));
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

function loadGeneralProductCatalog(onDone) {
    if (Array.isArray(Router?.generalProductCatalog) && Router.generalProductCatalog.length) {
        if (typeof onDone === 'function') onDone();
        return;
    }
    if (Router?.generalProductLoading) return;
    Router.generalProductLoading = true;
    Api.listProducts()
        .then(rec => {
            Router.generalProductCatalog = rec?.products?.length ? rec.products : [];
            Router.generalProductError = !(rec && rec.ok); // 區分「載入失敗」與「真的沒商品」
            if (typeof onDone === 'function') onDone();
        })
        .catch(() => {
            Router.generalProductCatalog = [];
            Router.generalProductError = true;
            if (typeof onDone === 'function') onDone();
        })
        .finally(() => { Router.generalProductLoading = false; });
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

// 推薦端點目前回的 imageUrl 是空字串（已回報資料庫組），先用全部商品清單裡的同一件商品補圖：
// 優先比對 salePageId（推薦回應的 productUrl slug == 清單的 sale_page_id），再退而比對完整商品名稱。
function fillRecommendedImages(list) {
    const catalog = Array.isArray(Router?.generalProductCatalog) ? Router.generalProductCatalog : [];
    return (Array.isArray(list) ? list : []).map((raw, index) => {
        const p = (raw && typeof raw === 'object') ? raw : {};
        const hit = catalog.find(g => (
            (p.rawId != null && g.rawId != null && String(p.rawId) === String(g.rawId)) ||
            (p.salePageId && g.salePageId && p.salePageId === g.salePageId) ||
            (p.name && g.name && p.name === g.name)
        ));
        const stableId = p.id || hit?.id || (p.rawId != null ? `recommended-${p.rawId}` : `recommended-${index}-${String(p.name || 'product').slice(0, 24)}`);
        return hit
            ? { ...hit, ...p, id: stableId, img: p.img || hit.img, sourceUrl: p.sourceUrl || hit.sourceUrl }
            : { ...p, id: stableId };
    });
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
        msg = localizeUserError(msg, opts.code || '', opts.status || 0);
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
    t.innerHTML = '<span class="check-ring"><svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg></span><span>'+msg+'</span>';
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
    ? '<div class="lm-compare-photo"><figure><img src="'+beforeSrc+'" alt="渲染前照片"><figcaption>Before</figcaption></figure><figure><img src="'+afterSrc+'" alt="渲染後照片"><figcaption>After</figcaption></figure></div>'
    : (afterSrc ? '<img src="'+afterSrc+'" alt="">' : '<span>'+escapeHtml(item.style||'Saved Look')+'</span>');
  var ts = item.timestamp ? new Date(item.timestamp).toLocaleString('zh-TW') : '';
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

function updateAdminNav(){
    const admin = typeof AdminStore !== 'undefined' && AdminStore.isAdmin();
    document.querySelectorAll('[data-admin-link]').forEach(el => {
        el.style.display = admin ? '' : 'none';
    });
    document.body.classList.toggle('admin-mode', admin);
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
    const render = () => {
        const rows = Cart.list().map(item => ({ ...item, product: getProductCatalog().find(p => String(p.id) === String(item.id)) })).filter(item => item.product);
        overlay.innerHTML = `<section class="cart-panel" role="dialog" aria-modal="true" aria-label="購物車">
            <header><div><span>Shopping Bag</span><h2>購物車</h2></div><button class="cart-close" aria-label="關閉購物車">×</button></header>
            <div class="cart-items">${rows.length ? rows.map(item => `<article class="cart-item">
                <div class="cart-thumb">${phBox('', item.product.name, item.product.img)}</div>
                <div class="cart-item-info"><span>${CAT_EN[item.product.cat] || item.product.cat}</span><h3>${item.product.name}</h3><p>${item.product.price}</p></div>
                <div class="cart-qty"><button data-cart-minus="${item.id}" aria-label="減少 ${item.product.name}">−</button><b>${item.qty}</b><button data-cart-plus="${item.id}" aria-label="增加 ${item.product.name}">＋</button></div>
            </article>`).join('') : '<div class="cart-empty">購物車目前是空的</div>'}</div>
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
        msg = localizeUserError(msg, opts.code || '', opts.status || 0);
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
    const beforeImage = pkg.images?.front?.compressedDataUrl
        || render.beforeImageUrl
        || render.beforeImageDataUrl
        || '';
    const renderedImage = render.afterImageUrl || render.afterImageDataUrl || makeupOutput.imageUrl || makeupOutput.imageDataUrl || '';
    return {
        kind: 'compare',
        title: '妝容對比圖',
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
    // 收藏當下重建，確保拿到最新的渲染圖與臉部分析；只有現在抓不到渲染圖時才退回先前的快照
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
            beforeImageUrl: stored.beforeImage || null,
            afterImageUrl: stored.renderedImage || null,
            analysisSummary: {
                faceShape: a.faceShape || a['臉型'] || null,
                eyeShape: a.eyeShape || a['眼型'] || null,
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
                // 妝後圖還沒有永久網址（通常是渲染還沒完成就按了收藏）。只存本機，
                // 但要說出來——這裡先前是空的，雲端沒收到而畫面一切正常，沒人察覺得到。
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
    <div class="as-photo"><img class="as-photo-img" alt="" onload="this.classList.add('loaded')"><div class="as-photo-ph"><div class="demo-mark">❧</div><div class="demo-cap">商品形象照 · Demo</div></div></div>
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
                <div class="upload-hint">正面，光線均勻，效果最佳</div>
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
        <div class="skin-box"><div class="skin-title">膚 色 基 準 · M A C</div><div class="skin-row"><div class="skin-swatch" id="skinSwatch"></div><div><div class="skin-name" id="skinName">—</div><div class="skin-lab" id="skinLab"></div></div></div></div>
        <div class="skin-box"><div class="skin-title">唇 色 原 始 值</div><div class="skin-row"><div class="skin-swatch" id="lipSwatch"></div><div><div class="skin-lab" id="lipLab"></div></div></div></div>
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
history: `<div class="page-header"><span class="eyebrow">Archive</span><h1>分析紀錄</h1><div class="divider"></div></div><div id="historyArea"></div>`,
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
        <button class="btn-outline" id="compareGoStyleBtn">選擇風格</button>
        <button class="btn-gold" id="compareRenderBtn" style="margin-top:12px;">生成妝容</button>
        <div id="compareRenderStatus" style="font-size:12px;color:#888;margin-top:6px;display:none;"></div>
        <button class="btn-outline" id="compareSaveLookBtn" style="margin-top:8px;">收藏妝容對比圖</button>
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
            <label>價格<input id="adminProductPrice" type="text" placeholder="例如：NT$980"></label>
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
        <div class="stat-cell"><div class="stat-en">Wishlist</div><div class="stat-num" id="profileFavCount">0</div><div class="stat-label">收藏商品</div></div>
        <div class="stat-cell"><div class="stat-en">Analysis</div><div class="stat-num" id="profileAnalyzeCount">0</div><div class="stat-label">分析次數</div></div>
        <div class="stat-cell"><div class="stat-en">Looks</div><div class="stat-num" id="profileSuggestionCount">0</div><div class="stat-label">收藏妝容</div></div>
        <div class="stat-cell"><div class="stat-en">Points</div><div class="stat-num" id="profilePointCount">0</div><div class="stat-label">會員點數</div></div>
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
        if (greetEl) greetEl.innerHTML = `${hello}，<span class="accent">${user}</span>`;
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

                const lipLab = data['嘴唇_LAB'] || {};
                document.getElementById('lipLab').textContent = `L ${lipLab.L||0} a ${lipLab.a||0} b ${lipLab.b||0}`;
                document.getElementById('lipSwatch').style.background = Api.labToRgb(lipLab.L||40, lipLab.a||0, lipLab.b||0);

                document.getElementById('goStyleBtn').style.display = 'inline-block';
                History.add({ ...data, analysisPackageId: Router.analysisPackage.id });
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
            fill.style.width = '8%';
            status.textContent = '產生建議中...';
            status.classList.add('active');

            const style = STYLES.find(s => s.id === Router.selectedStyleId);
            const pkg = Router.analysisPackage;

            try {
                if (!pkg || !Router.analysisResult) {
                    showAlert('目前沒有可用的臉部分析結果，請重新完成臉部分析。', { type:'error' });
                    Router.go('analysis');
                    return;
                }
                const latestAnalysis = getLatestAnalysisResult() || {};
                fill.style.width = '45%';
                status.textContent = '等待完整建議中...';
                const response = await Api.suggestMakeup({
                    analysisPackage: pkg,
                    faceAnalysis: pkg?.faceAnalysis || AnalysisPackage.fromRawFaceAnalysis(latestAnalysis, Router.analyzeMode),
                    style: style?.name || '日常自然妝',
                    userNote: style?.tags?.join('、') || ''
                });
                // 防呆：Ollama 有時候會把「第二部分」英文渲染指令漏拆、黏在中文建議尾巴，
                // 這裡先切乾淨，切下來的內容優先當渲染指令用（後端有正確拆出 renderPromptEn 的話，還是以後端的為準）。
                const { suggestion: cleanSuggestion, leakedEnglishPart } = splitOllamaTwoPartSuggestion(response.suggestion);
                const fullText = cleanSuggestion || '';
                const ollamaRenderPromptEn = response.renderPromptEn || leakedEnglishPart || '';

                fill.style.width = '100%';
                status.textContent = '建議已產生';
                setTimeout(() => { bar.style.display = 'none'; fill.style.width = '0'; status.classList.remove('active'); }, 600);

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

                Api.recommendProducts(
                    Router.analysisPackage,
                    Router.selectedStyleId
                ).then(rec => {
                    if (!rec?.products?.length) return;
                    Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                        recommendations: {
                            ...Router.analysisPackage.recommendations,
                            products: rec.products
                        }
                    });
                    AnalysisDraft.save(Router.analysisPackage);
                }).catch(() => {});

                Router.pendingLook = buildCurrentLookRecord();
                Router.pendingLookSaved = false;
                renderAnalysisResult(response);
            } catch (err) {
                bar.style.display = 'none';
                fill.style.width = '0';
                status.textContent = '建議產生失敗';
                status.classList.remove('active');
                if (pkg) {
                    Router.analysisPackage = AnalysisPackage.update(pkg, {
                        generativeText: {
                            ...(pkg.generativeText || {}),
                            status: 'failed',
                            error: err.message
                        }
                    });
                    AnalysisDraft.save(Router.analysisPackage);
                }
                showAlert('妝容建議失敗：' + err.message, { type: 'error' });
                renderAnalysisResult(null);
            } finally {
                startButtonCooldown(btn, 15, originalText);
            }
        };

        function renderAnalysisResult(aiSuggestionResponse) {
            const style = STYLES.find(s => s.id === Router.selectedStyleId);
            const palette = style.palette || ['#D8B69E', '#B97970', '#7C544A'];
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
                <div class="palette-row" style="margin:12px 0;">${palette.map(c => `<span style="background:${c};display:inline-block;width:28px;height:28px;border-radius:50%;margin-right:6px;"></span>`).join('')}</div>
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
                    <button class="btn-gold" onclick="Router.go('products')">查看推薦商品 →</button>
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
            // 個人化推薦區改成「每個美妝大類至少一件」：同類取分數最高的一件，類別依 API 回傳順序（2026-07-15 需求）
            const recommendedByCat = (() => {
                const best = new Map();
                for (const p of recommended) {
                    if (!p?.cat) continue;
                    if (!best.has(p.cat) || (p.score ?? 0) > (best.get(p.cat).score ?? 0)) best.set(p.cat, p);
                }
                return [...best.values()];
            })();
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
                    <div class="prod-grid recommended-grid">${recommendedByCat.slice(0, 8).map((p, i) => `
                        <div class="prod-card reveal-in" data-rec-pid="${escapeHtml(p.id)}" style="animation-delay:${Math.min(i*0.035,0.2)}s">
                            <div class="pc-imgwrap">${phBox('', p.name, p.img)}</div>
                            <div class="pc-cat">${CAT_EN[p.cat]||p.cat}${p.brand ? ` · ${escapeHtml(p.brand)}` : ''}</div>
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
                        <div class="pc-cat">${CAT_EN[p.cat]||p.cat}</div>
                        <div class="pc-name">${p.name}</div>
                        ${p.brand ? `<div class="pc-cat">${escapeHtml(p.brand)}</div>` : ''}
                        <div class="pc-foot"><span class="pc-price">${p.price}</span></div>
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
            // 這批商品每一筆本身就是一個獨立色號（不是一個商品配多組色號），色票只顯示這支商品自己的真實顏色。
            // 清單 API 本來就給 hex_primary 與 lab，不需要再打單品詳情——
            // /api/product/{type}/{id} 在上游根本不存在（實測 404），舊註解說的補抓從來沒成功過。
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
                            <div class="pc-cat">${CAT_EN[r.cat]||r.cat}${r.similarity != null ? ` · ${r.similarity}% 相似` : ''}</div>
                            <div class="pc-name">${r.name}</div>
                            <div class="pc-foot"><span class="pc-price">${r.price}</span></div>
                        </div>`).join('')}</div>
                </div>`;
            area.innerHTML = `
                <div class="pd-top">
                    <a href="#" class="back-link" onclick="PageInit.products({category:'${p.cat}'});return false;">← ${p.cat}</a>
                    <button class="pd-close" aria-label="關閉" onclick="PageInit.products({category:'${p.cat}'});return false;">×</button>
                </div>
                <div class="pd-wrap">
                    <div class="pd-img">${phBox('', p.name, p.img)}</div>
                    <div class="pd-info">
                        <div class="pd-en">${CAT_EN[p.cat]||'BEAUTY'}</div>
                        <div class="pd-name">${p.name}</div>
                        ${p.brand ? `<div class="pd-en">${escapeHtml(p.brand)}</div>` : ''}
                        <div class="pd-price-lg">${p.price}</div>
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

            // 非同步補強：真實色號 + AI 以色找色相似推薦（只有商品 API 來源、且清單本身沒有 hex 時才需要多打一支 API）
            if (p.source === 'product-api' && p.apiType && p.rawId != null) {
                if (!p.hex && typeof Api !== 'undefined' && Api.getProductDetail) {
                    Api.getProductDetail(p.apiType, p.rawId).then(detail => {
                        if (!detail?.hex || Router.currentPage !== 'products') return;
                        const box = document.getElementById('pdColorBox');
                        if (box) box.innerHTML = renderColorBox(detail.hex);
                    }).catch(() => {});
                }
                if (typeof Api !== 'undefined' && Api.getSimilarColorProducts) {
                    Api.getSimilarColorProducts(p.apiType, p.rawId).then(similar => {
                        if (!similar?.length || Router.currentPage !== 'products') return;
                        const box = document.getElementById('pdRelatedBox');
                        if (!box) return;
                        box.innerHTML = renderRelatedGrid(similar.slice(0, 3), 'AI 相似色彩推薦');
                        bindRelatedClicks();
                    }).catch(() => {});
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
        if (!apiCatalog.length && !Router.generalProductLoading) {
            loadGeneralProductCatalog(() => { if (Router.currentPage === 'favorites') PageInit.favorites(); });
        }
        if (!items.length) { area.innerHTML = '<div class="empty-state">目前尚無收藏商品</div>'; return; }
        area.innerHTML = `<div class="prod-count">${items.length} 件收藏</div><div class="prod-grid">` + items.map((p, i) => `
            <div class="prod-card reveal-in" data-pid="${p.id}" style="animation-delay:${Math.min(i*0.035,0.4)}s">
                <div class="pc-imgwrap">
                    ${phBox('', p.name, p.img)}
                    <button class="heart-btn pc-heart fav" data-unfav="${p.id}" aria-label="移除收藏">${HEART_SVG}</button>
                </div>
                <div class="pc-cat">${CAT_EN[p.cat]||p.cat}</div>
                <div class="pc-name">${p.name}</div>
                <div class="pc-foot"><span class="pc-price">${p.price}</span></div>
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

        const renderBtn = document.getElementById('compareRenderBtn');
        const renderStatus = document.getElementById('compareRenderStatus');
        const renderQuotaEl = document.getElementById('compareRenderQuota');
        const refreshRenderQuota = () => {
            if (!renderQuotaEl) return;
            const quotaProfile = Auth.getProfile();
            const remaining = AdminStore.getRemainingRenders(quotaProfile);
            const dailyLimit = AdminStore.getDailyRenderLimit(quotaProfile);
            const resetAt = quotaProfile?.renderQuota?.resetAt;
            if (isGuest()) {
                renderQuotaEl.textContent = '訪客無法使用 AI 渲染，請先註冊會員';
                return;
            }
            if (remaining === Infinity || dailyLimit === Infinity) {
                renderQuotaEl.textContent = 'AI 妝容渲染：無限次';
                return;
            }
            if (remaining != null && dailyLimit != null && resetAt) {
                renderQuotaEl.textContent = `AI 妝容渲染：今天還剩 ${remaining} / ${dailyLimit} 次`;
                return;
            }
            renderQuotaEl.textContent = 'AI 妝容渲染：依你的會員方案提供每日次數';
        };
        refreshRenderQuota();
        if (renderBtn) {
            renderBtn.onclick = async () => {
                const profile = Auth.getProfile();
                if (isGuest()) {
                    promptGuestAuth('AI 渲染妝容');
                    return;
                }
                if (!AdminStore.canRender(profile)) {
                    showAlert('你目前的方案無法使用 AI 妝容渲染。', { type: 'error' });
                    return;
                }
                let pkg = Router.analysisPackage;
                const imageDataUrl = pkg?.images?.front?.compressedDataUrl || pkg?.images?.front?.dataUrl || '';
                if (!imageDataUrl) { showAlert('尚未上傳照片，請先完成臉部分析。', { type: 'error' }); return; }
                // 2026-07-20 移除 renderApiKey 檢查：渲染改走 Gateway（session-only）後，
                // 前端不再持有也不再送 render 金鑰，這個檢查只會平白擋住渲染按鈕。
                // 2026-07-15 對齊後端接口：前端不再自己組 prompt（後端會忽略），只送結構化資料。
                // 只挑後端會讀的兩塊，不整包送——資料包裡有 base64 圖片，整包送 payload 會爆炸。
                const styleId = Router.selectedStyleId || pkg?.render?.styleId || 'natural';
                const renderPackage = {
                    faceAnalysis: pkg?.faceAnalysis || null,
                    render: { styleId }
                };

                renderBtn.disabled = true;
                renderBtn.textContent = '渲染中...';
                renderStatus.style.display = 'block';
                renderStatus.innerHTML = `
                    <div style="margin-bottom:8px;font-weight:600;">AI 正在上妝… <span id="renderProgressPct">1%</span></div>
                    <div style="height:8px;background:rgba(0,0,0,.08);border-radius:999px;overflow:hidden;">
                        <div id="renderProgressBar" style="height:100%;width:1%;border-radius:999px;background:linear-gradient(90deg,#f7b2c9,#c9748f);"></div>
                    </div>
                    <div id="renderProgressHint" style="margin-top:8px;font-size:12px;opacity:.7;">生成中，約需 60–150 秒，請不要關閉頁面</div>
                `;
                const barEl = document.getElementById('renderProgressBar');
                const pctEl = document.getElementById('renderProgressPct');
                const hintEl = document.getElementById('renderProgressHint');

                // 後端每 2 秒才回一次進度，直接套上去會一格一格跳。這裡每 40ms 往目標值推進 1，
                // 把數字補成連續的 1→100，而且只准往前、不准倒退。
                let shownProgress = 1;
                let targetProgress = 1;
                const progressTick = setInterval(() => {
                    if (shownProgress >= targetProgress) return;
                    shownProgress = Math.min(targetProgress, shownProgress + 1);
                    if (barEl) barEl.style.width = shownProgress + '%';
                    if (pctEl) pctEl.textContent = shownProgress + '%';
                }, 40);

                try {
                    const result = await Api.renderMakeupAsync({
                        imageDataUrl,
                        styleId,
                        analysisPackage: renderPackage,
                        onProgress: (p) => { targetProgress = Math.max(targetProgress, p); }
                    });
                    targetProgress = 100;
                    // 顯示後端這次實際下給模型的指令（renderPrompt 由後端組：Ollama 個人化或 styleId 白名單）
                    const promptPreviewEl = document.getElementById('comparePromptPreview');
                    if (promptPreviewEl && result.renderPrompt) {
                        promptPreviewEl.style.display = 'block';
                        promptPreviewEl.textContent = result.renderPrompt;
                    }
                    if (hintEl) hintEl.textContent = '完成！正在載入妝後圖…';
                    // 讓進度條有時間跑完最後那段，不然數字會停在 80 幾就整個消失
                    await new Promise(resolve => setTimeout(resolve, 800));
                    refreshRenderQuota();
                    if (!result.renderQuota && renderQuotaEl) {
                        renderQuotaEl.textContent = '妝容渲染完成！剩餘次數稍後更新。';
                    }
                    Router.analysisPackage = AnalysisPackage.update(pkg, {
                        render: {
                            ...(pkg.render || {}),
                            status: 'completed',
                            provider: 'replicate',
                            afterImageUrl: result.afterImageUrl,
                            replicateTempUrl: result.replicateTempUrl || null,
                            savedImageId: result.savedImageId || null,
                            error: null
                        }
                    });
                    AnalysisDraft.save(Router.analysisPackage);
                    Router.compareBaseline = 'after';  // 渲染完成後，基準改成成果圖：按住看原圖、放開回成果
                    showAfter();
                    renderStatus.textContent = '渲染完成！';
                    setTimeout(() => { renderStatus.style.display = 'none'; }, 3000);
                    showToast('妝容渲染完成');
                } catch (err) {
                    renderStatus.textContent = '渲染失敗：' + err.message;
                    showAlert('妝容生成失敗：' + err.message, { type: 'error' });
                } finally {
                    clearInterval(progressTick);
                    renderBtn.disabled = false;
                    renderBtn.textContent = '生成妝容';
                }
            };
        }

        const saveBtn = document.getElementById('compareSaveLookBtn');
        if (saveBtn) {
            saveBtn.onclick = () => {
                const afterUrl = Router.analysisPackage?.render?.afterImageUrl || '';
                if (afterUrl.includes('replicate.delivery')) {
                    showAlert('妝後圖片目前是臨時網址，收藏後可能日後失效。渲染端更新後將自動改用永久 URL。', {
                        type: 'warning',
                        onOk: () => {
                            Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
                            if (saveCurrentLook()) showToast('已收藏（注意：圖片為臨時網址）');
                        }
                    });
                    return;
                }
                Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
                if (saveCurrentLook()) showToast('已收藏妝容對比圖');
            };
        }

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
        area.innerHTML = `
            <div class="rendered-suggestion-card">
                <div class="rendered-photo-frame">
                    ${displayImage
                        ? `<img src="${displayImage}" alt="${renderedImage ? `${style.name} 渲染後妝容照片` : `${style.name} 原始照片`}">`
                        : `<div class="rendered-photo-placeholder">
                            <span>妝後照片</span>
                            <b>${style.name}</b>
                        </div>`
                    }
                </div>
                <div class="rendered-photo-copy">
                    <div class="detail-pill">妝容結果</div>
                    <h3>${renderedImage ? `${style.name} 渲染後妝容照片` : `${style.name} 原始照片`}</h3>
                    <p>${renderedImage ? '這張照片來自目前分析資料包的妝容結果。' : beforeImage ? '尚未取得妝容圖片，這裡先顯示目前分析資料包內的原始照片。' : '尚未取得妝容圖片。'}</p>
                </div>
            </div>
            <div class="style-intro-card">
                <h3>${style.name} 專屬妝容建議</h3>
                <div class="analysis-tags">${style.tags.map(t => `<span class="analysis-tag">${t}</span>`).join('')}</div>
            </div>
            <div class="analysis-section">
                <h3>五官與膚色摘要</h3>
                <div class="analysis-item"><span class="ai-label">臉型</span><span class="ai-value">${r['臉型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">眼型</span><span class="ai-value">${r['眼型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">鼻型</span><span class="ai-value">${r['鼻型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">膚色</span><span class="ai-value">${skin['膚色分級']||'—'} / ${skin['四季型']||'—'}</span></div>
            </div>
            <div class="analysis-section">
                <h3>妝容建議</h3>
                ${aiSuggestion
                    ? `<div class="advice-grid">${renderMakeupAdviceGrid(aiSuggestion)}</div>`
                    : `<div class="empty-state compact">尚未取得妝容建議，請返回風格頁按「確認風格」。</div>`
                }
                <button class="btn-gold" id="saveSuggestionBtn" style="margin-top:14px;">收藏妝容建議</button>
            </div>
        `;
        Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
        Router.pendingLookSaved = false;
        document.getElementById('saveSuggestionBtn').onclick = () => {
            if (saveCurrentLook()) showToast('已收藏妝容建議');
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
                        <span><em>臉型</em>${r['臉型']||'—'}</span>
                        <span><em>眼型</em>${r['眼型']||'—'}</span>
                        <span><em>鼻型</em>${r['鼻型']||'—'}</span>
                        <span><em>膚色</em>${(r['膚色']&&r['膚色']['四季型'])||'—'}</span>
                    </div>
                    <div class="hist-date">${r.timestamp ? new Date(r.timestamp).toLocaleString('zh-TW') : ''}</div>
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
            if (__p.avatar) { __av.classList.add('has-photo'); __av.innerHTML = '<img src="' + __p.avatar + '" alt="' + (user || '會員') + '">'; }
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
        const favEl = document.getElementById('profileFavCount');
        const anEl = document.getElementById('profileAnalyzeCount');
        const suggestionEl = document.getElementById('profileSuggestionCount');
        const pointEl = document.getElementById('profilePointCount');
        const suggestions = (() => {
            try { return JSON.parse(localStorage.getItem(looksKey()) || '[]'); } catch (_) { return []; }
        })();
        if (favEl) { favEl.textContent = ALL_PRODUCTS.filter(p => Fav.has(p.id)).length; favEl.classList.add('num-pop'); }
        if (anEl) { anEl.textContent = History.list().length; anEl.classList.add('num-pop'); anEl.style.animationDelay='.1s'; }
        if (suggestionEl) { suggestionEl.textContent = suggestions.length; suggestionEl.classList.add('num-pop'); suggestionEl.style.animationDelay='.16s'; }
        if (pointEl) { pointEl.textContent = MemberRewards.getPoints(profile.email); pointEl.classList.add('num-pop'); pointEl.style.animationDelay='.2s'; }
        if (pointEl && !isGuest() && profile.email && Api.getMemberPoints) {
            Api.getMemberPoints(profile.email).then(r => {
                if (!r || !r.ok || r.balance == null) return;
                pointEl.textContent = r.balance;
                if (r.lifetime != null && typeof MemberRewards !== 'undefined') {
                    // 讓會員等級進度也能吃到資料庫的 lifetime；保留 localStorage 只是為了既有 MemberTier 介面。
                    const all = MemberRewards._load(MemberRewards._lifetimeKey, {});
                    all[String(profile.email).trim().toLowerCase()] = Number(r.lifetime) || 0;
                    MemberRewards._save(MemberRewards._lifetimeKey, all);
                }
            }).catch(() => {});
        }

        const checkinCard = document.getElementById('profileCheckinCard');
        if (checkinCard) {
            const paintCheckin = (status, remote) => {
                const nextMilestone = MemberRewards.nextStreakMilestone(Number(status.streak) || 0);
                const streakLine = (Number(status.streak) || 0) > 0
                    ? `目前連續簽到 <b>${Number(status.streak) || 0}</b> 天${nextMilestone ? `，再簽 ${nextMilestone - (Number(status.streak) || 0)} 天可拿額外 ${MemberRewards._streakBonusTable[nextMilestone]} 點` : '，已達最高獎勵天數'}`
                    : '今天開始簽到就能累積連續天數';
                checkinCard.innerHTML = `<div class="member-action-card">
                    <div>
                        <b>${status.checkedToday ? '今天已完成打卡' : '今天還沒打卡'}</b>
                        <p>每日打卡可獲得 10 點；連續簽到 3 / 7 / 14 / 30 天另有加碼獎勵。</p>
                        <p class="checkin-streak">${streakLine}${remote ? '（資料庫同步）' : ''}</p>
                    </div>
                    <button class="btn-gold btn-sm" id="dailyCheckinBtn" ${status.checkedToday || isGuest() ? 'disabled' : ''}>${status.checkedToday ? '已打卡' : '打卡 +10'}</button>
                </div>`;
                const btn = document.getElementById('dailyCheckinBtn');
                if (btn) btn.onclick = async () => {
                    btn.disabled = true;
                    if (!isGuest() && Api.checkInMember) {
                        const remoteResult = await Api.checkInMember(profile.email).catch(() => null);
                        if (remoteResult?.ok) {
                            const gained = remoteResult.awarded ?? remoteResult.points ?? 0;
                            showToast(`打卡成功，獲得 ${gained} 點`);
                            PageInit.profile();
                            return;
                        }
                    }
                    const result = MemberRewards.checkin(profile.email);
                    if (!result.ok) { showAlert(result.message, { type:'error' }); btn.disabled = false; return; }
                    showToast(result.bonus
                        ? `打卡成功！連續 ${result.streak} 天，獲得 ${result.points} 點（含連續簽到獎勵 ${result.bonus} 點）`
                        : `打卡成功，獲得 ${result.points} 點`);
                    PageInit.profile();
                };
            };
            paintCheckin(MemberRewards.checkinStatus(profile.email), false);
            if (!isGuest() && profile.email && Api.getCheckinStatus) {
                Api.getCheckinStatus(profile.email).then(r => {
                    if (!r || !r.ok) return;
                    paintCheckin({
                        checkedToday: !!r.checkedToday,
                        streak: Number(r.streak) || 0
                    }, true);
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
                            claimed: !!t.claimed
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
                                if (!result?.ok) { showAlert(result?.error || '任務領取失敗。', { type: 'error' }); btn.disabled = false; return; }
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
                        <button class="${owned ? 'btn-outline' : 'btn-gold'} btn-sm" data-theme-action="${owned ? 'apply' : 'redeem'}" data-theme-id="${escapeHtml(theme.id)}" ${active ? 'disabled' : ''}>${active ? '使用中' : (owned ? '套用' : '兌換')}</button>
                    </div>
                </article>`;
            }).join('')}</div>`;
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
                                // alreadyOwned：先前兌換過但本機沒記錄到（例如當時套用失敗）。
                                // 伺服器不會重複扣點，這裡等於把狀態補回來，不能再說一次「已兌換」。
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
                const timestamp = escapeHtml(item.timestamp ? new Date(item.timestamp).toLocaleString('zh-TW') : '');
                const expired = String(item.renderedImage || '').includes('replicate.delivery')
                    ? '<span class="saved-look-expire">此圖為舊版臨時網址，可能已失效</span>' : '';
                return `
                <article class="saved-look-card reveal-in" data-look="${index}" style="animation-delay:${Math.min(index * 0.04, 0.24)}s">
                    <button class="look-del" data-del="${index}" aria-label="刪除此妝容">×</button>
                    <div class="saved-look-photo">
                        ${imageSrc
                            ? `<img src="${imageSrc}" alt="${styleLabel}" onload="this.classList.add('loaded')">${expired}`
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
            crawler: { eyebrow: 'CRAWLER IMPORT', title: '商品網址匯入' }
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

        // 資料來源：優先吃組員資料庫 GET /api/members；抓不到才退回本機 demo，並在工具列標明目前模式
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
                            ? `<img src="${afterSrc}" alt="${escapeHtml(item.style || '妝容')}" onload="this.classList.add('loaded')">`
                            : `<span>${escapeHtml(item.style || 'Look')}</span>`}</div>
                        <div class="saved-look-body">
                            <div class="saved-look-kicker">Saved Look · DB</div>
                            <h3>${escapeHtml(item.style || '妝容')}</h3>
                            <p>${escapeHtml(String(summary).slice(0, 72))}</p>
                            <time>${escapeHtml(item.timestamp ? new Date(item.timestamp).toLocaleString('zh-TW') : '')}</time>
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
            document.getElementById('adminProductPrice').value = product.price || '';
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
            const params = {
                q: productSearchQuery.trim(),
                type: document.getElementById('adminProductTypeFilter')?.value || '',
                status: document.getElementById('adminProductStatusFilter')?.value ?? 'active',
                limit: 200
            };
            return Api.listProducts(params).then(rec => {
                if (rec?.ok) {
                    dbProducts = rec.products || [];
                    productResultTotal = Number(rec.total ?? dbProducts.length);
                    dbProductsError = '';
                    productConnectionState = 'ok';
                    setConnectionStatus('adminProductConnection', '正常', 'ok');
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
            const terms = productSearchInput?.value.trim() || '彩妝 商品';
            const result = await Api.searchProductPreview(terms);
            if (result.ok && /^https:\/\//i.test(result.googleUrl || '')) window.open(result.googleUrl, '_blank', 'noopener,noreferrer');
            else showAlert(`Google 搜尋引導失敗：${result.error || '未取得搜尋網址'}`, { type: 'error' });
        };

        const loadProductAuditLogs = async () => {
            const rows = document.getElementById('adminProductAuditRows');
            if (!rows) return;
            rows.innerHTML = '<tr><td colspan="4">讀取中…</td></tr>';
            const result = await Api.listProductAuditLogs(100);
            if (!result.ok) {
                rows.innerHTML = `<tr><td colspan="4">${escapeHtml(result.error || '無法讀取稽核紀錄')}</td></tr>`;
                return;
            }
            rows.innerHTML = result.logs.length ? result.logs.map(log => `<tr><td>${escapeHtml(log.createdAt || log.created_at || log.timestamp || '—')}</td><td>${escapeHtml(log.action || log.operation || '—')}</td><td>${escapeHtml(log.productId || log.product_id || '—')}</td><td>${escapeHtml(log.actorId || log.actor_id || (String(log.actor || '').startsWith('actor_') ? log.actor : '管理員'))}</td></tr>`).join('') : '<tr><td colspan="4">尚無操作紀錄</td></tr>';
        };
        // 管理憑證改用登入 token，進到這頁就直接讀稽核紀錄，不必再等使用者「套用」什麼
        loadProductAuditLogs();
        const auditReload = document.getElementById('adminProductAuditReload');
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
            const price = document.getElementById('adminProductPrice')?.value.trim();
            const img = document.getElementById('adminProductImg')?.value.trim();
            const sourceUrl = document.getElementById('adminProductSourceUrl')?.value.trim();
            const desc = document.getElementById('adminProductDesc')?.value.trim();
            const shadesRaw = document.getElementById('adminProductShades')?.value.trim();
            const shadesInput = shadesRaw ? shadesRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
            const shades = shadesInput.filter(c => /^#[0-9a-fA-F]{3,8}$/.test(c));
            if (!name || !brand || !cat || !price || !img || !sourceUrl) {
                showAlert('請完整填寫商品名稱、品牌、分類、價格、圖片網址與來源網址', { type:'error' });
                return;
            }
            if (shades.length !== shadesInput.length) {
                showAlert('色號格式不正確，只接受 Hex 色碼（例如 #3A241C），不合格式的色號已被忽略。', { type:'error' });
                return;
            }
            // 全部走真商品資料庫，不再寫 localStorage demo
            const payload = {
                name, brand, price: Number(price),
                type: CAT_TO_TYPE[cat] || 'foundations',
                imageUrl: img,
                imageUrls: [img],
                image_url: img,
                description: desc || '',
                sourceUrl,
                source_url: sourceUrl,
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

        const crawlerForm = document.getElementById('adminCrawlerForm');
        const crawlerSubmitBtn = document.getElementById('adminCrawlerSubmitBtn');
        const crawlerMessage = document.getElementById('adminCrawlerMessage');
        const crawlerEmpty = document.getElementById('adminCrawlerEmpty');
        const crawlerResult = document.getElementById('adminCrawlerResult');
        let crawledProduct = null;
        const crawlerErrorLabels = {
            INVALID_URL: '商品網址格式不正確',
            UNSUPPORTED_SITE: '目前尚未支援這個來源網站',
            FETCH_TIMEOUT: '來源網站回應逾時',
            SCRAPE_BLOCKED: '來源網站拒絕爬蟲存取',
            PARSE_FAILED: '商品欄位解析失敗',
            NO_PRODUCT_FOUND: '此網址找不到商品資料',
            CRAWLER_URL_NOT_CONFIGURED: '尚未設定爬蟲服務網址',
            NETWORK_ERROR: '無法連線到爬蟲服務'
        };
        const setCrawlerStatus = (label, state, message = '') => {
            const badge = document.getElementById('adminCrawlerState');
            if (badge) {
                badge.textContent = label;
                badge.className = `admin-crawler-state ${state}`;
            }
            if (crawlerMessage) {
                crawlerMessage.textContent = message;
                crawlerMessage.className = `admin-crawler-message ${state}`;
            }
            const connectionState = state === 'error' ? 'error' : (state === 'loading' || state === 'idle' ? 'idle' : 'ok');
            setConnectionStatus('adminCrawlerConnection', state === 'error' ? '異常' : (connectionState === 'ok' ? '正常' : '待測試'), connectionState);
        };
        const normalizeCrawlerCategory = (value) => {
            const raw = String(value || '').trim();
            if (Object.prototype.hasOwnProperty.call(CAT_TO_TYPE, raw)) return raw;
            return TYPE_TO_CAT[raw.toLowerCase()] || '底妝';
        };
        const formatCrawlerPrice = (value, currency) => {
            if (value == null || value === '') return '';
            if (typeof value === 'number') {
                const formatted = value.toLocaleString('zh-TW');
                return ['TWD', 'NTD', 'NT$'].includes(String(currency || '').toUpperCase()) ? `NT$${formatted}` : `${currency || ''}${formatted}`;
            }
            const text = String(value).trim();
            if (/^(NT\$|TWD)/i.test(text)) return text.replace(/^TWD\s*/i, 'NT$');
            return currency ? `${currency} ${text}` : text;
        };
        const renderCrawlerPreview = (product, responseStatus) => {
            if (!crawlerResult || !crawlerEmpty) return;
            const imageUrl = String(product.imageUrls?.[0] || '');
            const safeImageUrl = /^https?:\/\//i.test(imageUrl) ? imageUrl : '';
            const specs = Object.entries(product.specs || {}).slice(0, 6);
            const missing = product.missingFields || [];
            crawlerEmpty.hidden = true;
            crawlerResult.hidden = false;
            crawlerResult.innerHTML = `
                <article class="admin-crawler-product">
                    <div class="admin-crawler-image">
                        ${safeImageUrl ? `<img src="${escapeHtml(safeImageUrl)}" alt="${escapeHtml(product.name || '商品預覽')}" loading="lazy">` : '<span>無商品圖片</span>'}
                    </div>
                    <div class="admin-crawler-product-body">
                        <div class="admin-crawler-product-meta">
                            <span>${escapeHtml(product.sourceSite || '來源網站')}</span>
                            <b class="${responseStatus === 'partial' ? 'warning' : 'ok'}">${responseStatus === 'partial' ? '部分欄位缺漏' : '擷取完成'}</b>
                        </div>
                        <h3>${escapeHtml(product.name || '未取得商品名稱')}</h3>
                        <p class="admin-crawler-brand">${escapeHtml(product.brand || '未取得品牌')}</p>
                        <strong class="admin-crawler-price">${escapeHtml(formatCrawlerPrice(product.price, product.currency) || '未取得價格')}</strong>
                        <p class="admin-crawler-description">${escapeHtml(product.description || '未取得商品描述')}</p>
                        ${specs.length ? `<dl class="admin-crawler-specs">${specs.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(typeof value === 'object' ? JSON.stringify(value) : value)}</dd></div>`).join('')}</dl>` : ''}
                        ${missing.length ? `<div class="admin-crawler-missing"><span>缺少欄位</span>${missing.map(field => `<b>${escapeHtml(field)}</b>`).join('')}</div>` : ''}
                        <div class="admin-crawler-result-actions">
                            <button class="admin-primary-button" id="adminUseCrawlerResult" type="button">帶入商品表單</button>
                            ${product.sourceUrl ? `<a class="admin-secondary-button" href="${escapeHtml(product.sourceUrl)}" target="_blank" rel="noreferrer">查看來源頁</a>` : ''}
                        </div>
                    </div>
                </article>`;
            const useBtn = document.getElementById('adminUseCrawlerResult');
            if (useBtn) useBtn.onclick = () => {
                exitEditMode();
                document.getElementById('adminProductName').value = product.name || '';
                document.getElementById('adminProductBrand').value = product.brand || '';
                document.getElementById('adminProductCategory').value = normalizeCrawlerCategory(product.category);
                document.getElementById('adminProductPrice').value = formatCrawlerPrice(product.price, product.currency);
                document.getElementById('adminProductImg').value = product.imageUrls?.[0] || '';
                document.getElementById('adminProductSourceUrl').value = product.sourceUrl || '';
                document.getElementById('adminProductDesc').value = product.description || '';
                document.getElementById('adminProductShades').value = /^#[0-9a-fA-F]{3,8}$/.test(product.hex || '') ? product.hex : '';
                setAdminSection('products');
                productForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
                showToast('爬蟲資料已帶入，確認內容後即可新增商品');
            };
        };
        if (crawlerForm) crawlerForm.onsubmit = async (event) => {
            event.preventDefault();
            const input = document.getElementById('adminCrawlerUrl');
            const sourceUrl = String(input?.value || '').trim();
            try {
                const parsed = new URL(sourceUrl);
                if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('invalid protocol');
            } catch (_) {
                setCrawlerStatus('網址錯誤', 'error', '請輸入完整的 http 或 https 商品網址');
                input?.focus();
                return;
            }
            crawlerSubmitBtn.disabled = true;
            crawlerSubmitBtn.textContent = '正在擷取…';
            setCrawlerStatus('擷取中', 'loading', '正在等待爬蟲服務回傳商品資料');
            const result = await Api.previewCrawledProduct(sourceUrl);
            crawlerSubmitBtn.disabled = false;
            crawlerSubmitBtn.textContent = '擷取商品資料';
            if (!result.ok) {
                crawledProduct = null;
                if (crawlerEmpty) crawlerEmpty.hidden = false;
                if (crawlerResult) crawlerResult.hidden = true;
                const label = crawlerErrorLabels[result.code] || result.error || '爬蟲執行失敗';
                setCrawlerStatus('擷取失敗', 'error', `${label}${result.code ? `（${result.code}）` : ''}`);
                return;
            }
            crawledProduct = result.product;
            const partial = result.status === 'partial' || crawledProduct.missingFields.length > 0;
            setCrawlerStatus(partial ? '需要補資料' : '擷取完成', partial ? 'warning' : 'success', partial ? '部分欄位缺漏，可帶入表單後補齊' : '商品資料已建立預覽');
            renderCrawlerPreview(crawledProduct, partial ? 'partial' : 'ok');
        };

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
(function init() {
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
                handleSessionExpired({
                    title: '登入帳號已變更',
                    message: '這個瀏覽器目前登入的是另一個帳號（可能是在後台登入過）。'
                        + '為避免讀到別人的資料，已登出，請重新登入你要使用的帳號。'
                });
            } else if (session.ok) {
                showApp();
                routeFromHash();
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

function showApp() {
    document.getElementById('auth-layer').innerHTML = '';
    document.getElementById('app').style.display = 'block';
    const profile = Auth.getProfile ? (Auth.getProfile() || {}) : {};
    document.getElementById('sidebarUsername').textContent = `${getMemberDisplayName()} · ${getCurrentRoleLabel(profile)}`;
    updateAdminNav();
    updateCartBadge();
    refreshMemberTheme();
    const landing = (typeof AdminStore !== 'undefined' && AdminStore.isAdmin()) ? 'admin' : 'dashboard';
    const homeUrl = `${location.pathname}${location.search}#${landing}`;
    if (location.hash !== `#${landing}`) history.replaceState(null, '', homeUrl);
    Router.go(landing);
}

function handleSessionExpired(options) {
    if (Router._sessionExpiryHandling) return;
    Router._sessionExpiryHandling = true;
    if (typeof Api._cancelSessionRequests === 'function') Api._cancelSessionRequests();
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
    const email = String((Auth.getProfile() || {}).email || '').trim().toLowerCase();
    // 舊版 Gateway 不回 sub。拿不到就不阻擋——寧可維持原本行為，
    // 也不要在 Gateway 還沒換版時把所有人擋在登入頁外面。
    if (!sub || !email) return true;
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
            <div class="auth-card">
                <h2>裝識你的美</h2>
                <p class="subtitle">Log in to continue your beauty journey</p>
                <div class="input-group"><label>電子郵件</label><input type="email" id="loginEmail" placeholder="your@email.com"></div>
                <div class="input-group"><label>密碼</label><input type="password" id="loginPwd" placeholder="••••••••"></div>
                <button class="btn-gold btn-full" onclick="doLoginAction()" style="margin-top:8px;">登　入</button>
                <button class="btn-outline btn-full" onclick="doGuestLogin()" style="margin-top:12px;">訪客登入</button>
                <div style="margin-top:12px;"><span class="auth-link" onclick="showForgotPassword()">忘記密碼？</span></div>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showRegister()">還沒有帳號？立即註冊</span></div>
            </div>
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
                <button class="btn-gold btn-full" onclick="doRegisterAction()" style="margin-top:8px;">註　冊</button>
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
        Auth.setProfile({
            ...registered,
            ...member,
            name: member.name || registered.name || email.split('@')[0],
            email: member.email || email,
            phone: member.phone_number || registered.phone || '',
            age: member.age || registered.age || '',
            level: member.level || registered.level || '一般會員',
            role: member.role || registered.role || 'member',
            status: member.status || registered.status || 'active',
            allowedPages: Array.isArray(member.allowedPages) ? member.allowedPages : (registered.allowedPages || undefined),
            vipRequested: !!(member.vipRequested || registered.vipRequested),
            renderQuota: member.renderQuota || registered.renderQuota || null
        });
        Router._sessionExpiryHandling = false;
        Api._sessionExpiredNotified = false;
    } catch (err) {
        // 不管是伺服器明確拒絕，還是根本連不上會員資料庫，都不能放行——
        // 沒有真正在資料庫裡的會員，一律不能用登入方式進去，避免有人靠擋網路/竄改 DNS 繞過驗證。
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
        // 帳號存在但被停權／刪除（後台的刪除是軟刪除，資料列還在、email 也還被占用）。
        // 這種情況絕對不能引導去註冊 —— 註冊一定會撞 EMAIL_EXISTS，使用者只會看到一個
        // 跟真正原因無關的錯誤，然後卡在原地。
        if (/SUSPEND|DELET|DISABLED|INACTIVE|BLOCK/i.test(err.code || '') || err.status === 403) {
            showAlert('此帳號已被停權或刪除，無法登入。請聯繫管理員處理，重新註冊不會生效。', { type: 'error' });
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
        sessionStorage.removeItem('beautyUser');
        sessionStorage.removeItem('beautyProfile');
        showAlert('此帳號已被停權，請聯繫管理員', { type:'error' });
        return;
    }
    showApp();
}

function doGuestLogin() {
    Auth.setProfile({ name: '訪客', level: '訪客', age: '', phone: '', email: '' });
    showApp();
}

async function doRegisterAction() {
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
    try {
        await Api.register(Router.pendingRegister);
        await Api.sendOTP(email);
    } catch (err) {
        // 信箱已存在時給返回登入的出口，不要讓使用者卡在註冊頁反覆重試同一個必然失敗的動作
        if (err?.code === 'EMAIL_EXISTS') {
            showConfirm(err.message, {
                title: '此信箱已註冊', type: 'error', okText: '返回登入', cancelText: '取消',
                onOk: function(){ showLogin(); }
            });
            return;
        }
        showAlert(err?.message || '註冊或驗證碼發送失敗，請稍後再試', { type:'error' });
        return;
    }
    showVerification(email);
}

async function doVerifyOTP() {
    const code = document.getElementById('otpCode').value.trim();
    if (!code) { showAlert('請輸入驗證碼'); return; }
    const pending = Router.pendingRegister;
    if (!pending) { showAlert('註冊資料已過期，請重新註冊', { type:'error', onOk: showRegister }); return; }
    if (!(await verifyOtpWithOptionalBypass(pending.email, code))) return;

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
    if (!(await verifyOtpWithOptionalBypass(Router.forgotEmail, code))) return;
    showResetPassword();
}

async function verifyOtpWithOptionalBypass(email, code) {
    const allowOtpBypass = !!window.DECORATE_ME_CONFIG?.allowInsecureOtpBypass;
    try {
        await Api.verifyOTP(email, code);
        return true;
    } catch (err) {
        if (!allowOtpBypass) {
            showAlert(err?.message || '驗證碼驗證失敗，請稍後再試', { type:'error' });
            return false;
        }
        if (code.length < 4) {
            showAlert('驗證碼至少 4 碼');
            return false;
        }
        return true;
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
