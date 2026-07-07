// ═══ 共用 UI 片段 ═══
const HEART_SVG = '<span class="pulse"></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.4S3.6 15.6 3.6 9.4C3.6 6.5 5.7 4.7 8 4.7c1.7 0 3.1 1 4 2.4 0.9-1.4 2.3-2.4 4-2.4 2.3 0 4.4 1.8 4.4 4.7 0 6.2-8.4 11-8.4 11z"/></svg>';
const CAT_EN = { '底妝':'FOUNDATION','眼影':'EYESHADOW','眼線/睫毛':'EYES & LASH','唇彩':'LIP COLOR','腮紅':'BLUSH','眉毛彩妝':'BROW','修容':'CONTOUR','打亮':'HIGHLIGHT' };
function phBox(cls, label, src){
    const cap = (cls.indexOf('product-thumb')>-1) ? '' : `<span class="ph-cap">${escapeHtml(label||'')}</span>`;
    const img = src ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(label||'')}" onload="this.classList.add('loaded')">` : '';
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
            if (typeof onDone === 'function') onDone();
        })
        .catch(() => {
            Router.generalProductCatalog = [];
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

function getRecommendedProductCatalog() {
    const fromPackage = Router?.analysisPackage?.recommendations?.products;
    if (Array.isArray(fromPackage) && fromPackage.length) return fromPackage;
    const draft = typeof AnalysisDraft !== 'undefined' ? AnalysisDraft.load() : null;
    const fromDraft = draft?.recommendations?.products;
    return Array.isArray(fromDraft) ? fromDraft : [];
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

function openLookModal(item){
  if(!item) return;
  var old=document.getElementById('lookModal'); if(old) old.remove();
  var advice=item.advice||{};
  var titles={ base:'底妝建議', brow:'眉型建議', eye:'眼妝建議', blush:'腮紅 & 修容', lip:'唇妝建議' };
  var r=item.analysis||{}; var skin=r['膚色']||{};
  var rows=Object.keys(advice).map(function(k){ return '<div class="lm-advice"><b>'+(titles[k]||k)+'</b><p>'+advice[k]+'</p></div>'; }).join('');
  var tags=(item.tags||[]).map(function(t){ return '<span class="analysis-tag">'+t+'</span>'; }).join('');
  var photo = (item.beforeImage && item.renderedImage)
    ? '<div class="lm-compare-photo"><figure><img src="'+item.beforeImage+'" alt="渲染前照片"><figcaption>Before</figcaption></figure><figure><img src="'+item.renderedImage+'" alt="渲染後照片"><figcaption>After</figcaption></figure></div>'
    : (item.renderedImage ? '<img src="'+item.renderedImage+'" alt="">' : '<span>'+(item.style||'Saved Look')+'</span>');
  var ts = item.timestamp ? new Date(item.timestamp).toLocaleString('zh-TW') : '';
  var ov=document.createElement('div'); ov.id='lookModal'; ov.className='look-modal';
  ov.innerHTML='<div class="lm-card" role="dialog" aria-modal="true">'
    +'<button class="lm-close" aria-label="關閉">×</button>'
    +'<div class="lm-photo">'+photo+'</div>'
    +'<div class="lm-body"><div class="lm-kicker">'+(item.title||'Saved Look')+'</div>'
    +'<h2>'+(item.style||'妝容建議')+'</h2><time>'+ts+'</time>'
    +(tags?'<div class="analysis-tags" style="margin-top:14px;">'+tags+'</div>':'')
    +'<div class="lm-summary"><span><em>臉型</em>'+(r['臉型']||'—')+'</span><span><em>眼型</em>'+(r['眼型']||'—')+'</span><span><em>鼻型</em>'+(r['鼻型']||'—')+'</span><span><em>膚色</em>'+(skin['四季型']||skin['膚色分級']||'—')+'</span></div>'
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
        if (checkout && !checkout.disabled) checkout.onclick = () => showToast('結帳功能將由後端購物流程接續');
    };
    render();
    overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };
    document.body.appendChild(overlay);
}

// ═══ 玻璃雙鈕對話框（取代原生 confirm） ═══
function showConfirm(msg, opts){
    opts = opts || {};
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

function saveCurrentLook(){
    if (isGuest()) {
        promptGuestAuth('收藏妝容對比圖');
        return null;
    }
    const record = Router.pendingLook || buildCurrentLookRecord();
    const records = JSON.parse(localStorage.getItem('beautySuggestions') || '[]');
    records.unshift({ ...record, timestamp: new Date().toISOString() });
    localStorage.setItem('beautySuggestions', JSON.stringify(records.slice(0, 20)));
    Router.pendingLook = null;
    Router.pendingLookSaved = true;
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
        var profile = Auth.getProfile() || {};
        if (profile.password && profile.password !== oldP) { showAlert("目前密碼不正確", { type:"error" }); return; }
        Auth.setProfile(Object.assign({}, profile, { password: n1 }));
        close(function(){ showAlert("密碼已更新", { type:"success" }); });
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
<div class="page-header"><h1>妝容對比圖</h1><div class="divider"></div><p>保留 iOS 端的前後對比流程：選擇風格後可按下切換渲染前 / 渲染後效果。</p></div>
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
                    ? '角度偵測 API 尚未啟用，請重啟 BASIC 後端或使用手動擷取。'
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
                setLoadingStatus(`已建立 job：${job.jobId}，等待後端分析`, true);

                const response = await Api.waitForFaceJob(Router.analyzeMode, job.jobId, latestJob => {
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
                    setLoadingStatus(`後端分析中：${latestJob.stage || latestJob.status} ${progress}%`, true);
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
                    ? '無法連接分析服務。請先執行後端資料夾的 start_full_stack_local.bat，並從 http://127.0.0.1:5500 開啟網站。'
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
                    Router.analysisPackage?.faceAnalysis,
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
            const apiCatalog = Array.isArray(Router.generalProductCatalog) ? Router.generalProductCatalog : [];
            const shouldLoadGeneralProducts = !recommended.length && !apiCatalog.length && !Router.generalProductLoading;
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
                    <div class="prod-grid recommended-grid">${recommended.slice(0, 4).map((p, i) => `
                        <div class="prod-card reveal-in" data-rec-pid="${escapeHtml(p.id)}" style="animation-delay:${Math.min(i*0.035,0.2)}s">
                            <div class="pc-imgwrap">${phBox('', p.name, p.img)}</div>
                            <div class="pc-cat">${CAT_EN[p.cat]||p.cat}${p.brand ? ` · ${escapeHtml(p.brand)}` : ''}</div>
                            <div class="pc-name">${escapeHtml(p.name)}</div>
                            <div class="pc-foot"><span class="pc-price">${escapeHtml(p.price)}</span></div>
                        </div>`).join('')}
                    </div>
                </section>` : ''}
                <div class="filter-bar">${chips}</div>
                <div class="prod-count">${isLoadingProducts ? '商品載入中' : `${list.length} 件商品`}</div>`;
            const bindChips = () => {
                area.querySelectorAll('.chip').forEach(ch => ch.onclick = () => renderShop(ch.dataset.filter));
            };
            if (!recommended.length && !Router.productRecommendationLoading && Router.analysisPackage?.faceAnalysis) {
                Router.productRecommendationLoading = true;
                Api.recommendProducts(Router.analysisPackage.faceAnalysis, Router.selectedStyleId)
                    .then(rec => {
                        if (rec?.products?.length) {
                            Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                                recommendations: {
                                    ...(Router.analysisPackage.recommendations || {}),
                                    products: rec.products
                                }
                            });
                            AnalysisDraft.save(Router.analysisPackage);
                            if (Router.currentPage === 'products') renderShop(filter);
                        }
                    })
                    .catch(() => {})
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
            if (!p) return;
            const area = document.getElementById('productsArea');
            // 這批商品每一筆本身就是一個獨立色號（不是一個商品配多組色號），色票只顯示這支商品自己的真實顏色。
            // 商品清單 API 沒有 hex，只有單品詳情 API（/api/product/{type}/{id}）才有，先用清單裡有的，沒有就非同步補抓。
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
            holdBtn.textContent = '查看渲染前';
        };
        const showBefore = () => {
            stage.classList.remove('after');
            stage.classList.add('before');
            setCompareImage('before');
            holdBtn.textContent = '查看渲染後';
        };
        // 改成按下切換（不用長按），目前顯示哪一張就切去另一張
        showBefore();
        holdBtn.onclick = () => {
            if (stage.classList.contains('after')) showBefore();
            else showAfter();
        };
        document.getElementById('compareGoStyleBtn').onclick = () => Router.go('style');

        const renderBtn = document.getElementById('compareRenderBtn');
        const renderStatus = document.getElementById('compareRenderStatus');
        const renderQuotaEl = document.getElementById('compareRenderQuota');
        const refreshRenderQuota = () => {
            if (!renderQuotaEl) return;
            const quotaProfile = Auth.getProfile();
            const remaining = AdminStore.getRemainingRenders(quotaProfile);
            renderQuotaEl.textContent = isGuest()
                ? '訪客無法使用 AI 渲染，請先註冊會員'
                : (remaining === Infinity ? '管理員：渲染次數不限' : `今日剩餘渲染次數：${remaining} / ${AdminStore.getDailyRenderLimit(quotaProfile)}`);
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
                    showAlert(`今日渲染次數已用完（每日 ${AdminStore.getDailyRenderLimit(profile)} 次），升級 VIP 會員可提高至每日 ${AdminStore._vipDailyRenderLimit} 次，請至會員中心申請升級。`, { type: 'error' });
                    return;
                }
                const pkg = Router.analysisPackage;
                const imageDataUrl = pkg?.images?.front?.compressedDataUrl || pkg?.images?.front?.dataUrl || '';
                if (!imageDataUrl) { showAlert('尚未上傳照片，請先完成臉部分析。', { type: 'error' }); return; }
                const prompt = buildRenderPrompt(pkg?.faceAnalysis, Router.selectedStyleId, pkg?.generativeText?.suggestion || '', pkg?.generativeText?.ollamaRenderPromptEn || '');
                if (!prompt) { showAlert('尚未產生妝容建議，請先在風格頁按「確認風格」。', { type: 'error' }); return; }

                // 顯示送出的英文 prompt 讓用戶確認
                const promptPreviewEl = document.getElementById('comparePromptPreview');
                if (promptPreviewEl) { promptPreviewEl.style.display = 'block'; promptPreviewEl.textContent = prompt; }

                renderBtn.disabled = true;
                renderBtn.textContent = '渲染中...';
                renderStatus.style.display = 'block';
                renderStatus.textContent = '正在生成妝容...';

                try {
                    renderStatus.textContent = 'Replicate 生成中，約需 30–60 秒...';
                    const result = await Api.renderMakeup({ imageDataUrl, prompt, strength: 0.35 });
                    AdminStore.recordRenderUsage(profile);
                    refreshRenderQuota();
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
                    setCompareImage('after');
                    renderStatus.textContent = '渲染完成！';
                    setTimeout(() => { renderStatus.style.display = 'none'; }, 3000);
                    showToast('妝容渲染完成');
                } catch (err) {
                    renderStatus.textContent = '渲染失敗：' + err.message;
                    showAlert('妝容生成失敗：' + err.message, { type: 'error' });
                } finally {
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
                        <li>${isVip ? 'PRO 臉部分析已開通' : 'PRO 臉部分析需後台開通'}</li>
                        <li>渲染妝容：${remaining === Infinity ? '不限次數' : `每日 ${AdminStore.getDailyRenderLimit(profile)} 次（今日剩餘 ${remaining} 次）${isVip ? '' : `，升級 VIP 可達每日 ${AdminStore._vipDailyRenderLimit} 次`}`}</li>
                        ${tierProgressLine}
                    </ul>
                    ${pending ? `<div class="tier-pending">升級申請已送出，請等候管理員審核</div>` : ''}
                    </div>
                    ${(!isVip && !isAdminUser) ? `<button class="btn-gold btn-sm" id="profileVipUpgradeBtn" ${pending ? 'disabled' : ''}>${pending ? '審核中' : '申請升級 VIP'}</button>` : ''}
                </div>
            `;
            const upgradeBtn = document.getElementById('profileVipUpgradeBtn');
            if (upgradeBtn) upgradeBtn.onclick = () => {
                if (!profile?.email) { showAlert('訪客身分無法申請升級，請先註冊會員。', { type: 'error' }); return; }
                AdminStore.requestVipUpgrade(profile.email);
                showToast('已送出升級申請，請等候管理員審核');
                PageInit.profile();
            };
        }
        const favEl = document.getElementById('profileFavCount');
        const anEl = document.getElementById('profileAnalyzeCount');
        const suggestionEl = document.getElementById('profileSuggestionCount');
        const pointEl = document.getElementById('profilePointCount');
        const suggestions = (() => {
            try { return JSON.parse(localStorage.getItem('beautySuggestions') || '[]'); } catch (_) { return []; }
        })();
        if (favEl) { favEl.textContent = ALL_PRODUCTS.filter(p => Fav.has(p.id)).length; favEl.classList.add('num-pop'); }
        if (anEl) { anEl.textContent = History.list().length; anEl.classList.add('num-pop'); anEl.style.animationDelay='.1s'; }
        if (suggestionEl) { suggestionEl.textContent = suggestions.length; suggestionEl.classList.add('num-pop'); suggestionEl.style.animationDelay='.16s'; }
        if (pointEl) { pointEl.textContent = MemberRewards.getPoints(profile.email); pointEl.classList.add('num-pop'); pointEl.style.animationDelay='.2s'; }

        const proCard = document.getElementById('profileProCard');
        if (proCard) {
            if (isGuest() || typeof ProSubscription === 'undefined') {
                proCard.innerHTML = '<div class="empty-state compact">登入會員後即可購買 PRO 方案</div>';
            } else {
                const sub = ProSubscription.getSubscription(profile.email);
                const orders = ProSubscription.orders(profile.email);
                const statusLine = sub.active
                    ? `<p>目前方案：<b>${escapeHtml(sub.plan === 'yearly' ? 'PRO 年費方案' : 'PRO 月費方案')}</b>，到期日 ${new Date(sub.expiresAt).toLocaleDateString('zh-TW')}（剩餘 ${sub.daysLeft} 天）</p>`
                    : '<p>目前沒有生效中的付費方案，購買後立即解鎖 PRO 分析與無限渲染。</p>';
                proCard.innerHTML = `
                    <div class="pro-plan-status">${statusLine}</div>
                    <div class="pro-plan-grid">
                        ${ProSubscription.plans.map(plan => `
                            <div class="member-action-card pro-plan-card">
                                <div>
                                    <b>${escapeHtml(plan.name)}</b>
                                    <p>NT$ ${plan.price} / ${plan.days} 天（Demo 付款，不會真的扣款）</p>
                                </div>
                                <button class="btn-gold btn-sm" data-pro-plan="${plan.id}">${sub.active ? '續約' : '立即購買'}</button>
                            </div>
                        `).join('')}
                    </div>
                    <div class="pro-order-history">
                        <h4>訂單紀錄</h4>
                        ${orders.length ? orders.slice(0, 5).map(o => `<div class="point-ledger-row">
                            <span>${escapeHtml(o.planName)}</span>
                            <time>${new Date(o.createdAt).toLocaleString('zh-TW')}</time>
                            <b>NT$ ${o.amount}</b>
                        </div>`).join('') : '<div class="empty-state compact">尚無訂單紀錄</div>'}
                    </div>
                `;
                proCard.querySelectorAll('[data-pro-plan]').forEach(btn => {
                    btn.onclick = () => {
                        const result = ProSubscription.purchase(profile.email, btn.dataset.proPlan);
                        if (!result.ok) { showAlert(result.message, { type: 'error' }); return; }
                        showToast(`付款成功（Demo），PRO 已開通至 ${new Date(result.expiresAt).toLocaleDateString('zh-TW')}`);
                        PageInit.profile();
                    };
                });
            }
        }

        const checkinCard = document.getElementById('profileCheckinCard');
        if (checkinCard) {
            const status = MemberRewards.checkinStatus(profile.email);
            const nextMilestone = MemberRewards.nextStreakMilestone(status.streak);
            const streakLine = status.streak > 0
                ? `目前連續簽到 <b>${status.streak}</b> 天${nextMilestone ? `，再簽 ${nextMilestone - status.streak} 天可拿額外 ${MemberRewards._streakBonusTable[nextMilestone]} 點` : '，已達最高獎勵天數'}`
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
            if (btn) btn.onclick = () => {
                const result = MemberRewards.checkin(profile.email);
                if (!result.ok) { showAlert(result.message, { type:'error' }); return; }
                showToast(result.bonus
                    ? `打卡成功！連續 ${result.streak} 天，獲得 ${result.points} 點（含連續簽到獎勵 ${result.bonus} 點）`
                    : `打卡成功，獲得 ${result.points} 點`);
                PageInit.profile();
            };
        }

        const taskCenter = document.getElementById('profileTaskCenter');
        if (taskCenter) {
            if (isGuest() || typeof Tasks === 'undefined') {
                taskCenter.innerHTML = '<div class="empty-state compact">登入會員後即可查看任務中心</div>';
            } else {
                const tasks = Tasks.status(profile.email);
                const groups = [...new Set(tasks.map(t => t.group))];
                taskCenter.innerHTML = groups.map(group => `
                    <div class="task-group">
                        <h4>${escapeHtml(group)}</h4>
                        ${tasks.filter(t => t.group === group).map(t => `
                            <div class="member-action-card task-row">
                                <div>
                                    <b>${escapeHtml(t.title)}</b>
                                    <p>獎勵 ${t.reward} 點</p>
                                </div>
                                <button class="btn-gold btn-sm" data-task-id="${t.id}" ${(!t.done || t.claimed) ? 'disabled' : ''}>${t.claimed ? '已領取' : (t.done ? '領取獎勵' : '尚未完成')}</button>
                            </div>
                        `).join('')}
                    </div>
                `).join('');
                taskCenter.querySelectorAll('[data-task-id]').forEach(btn => {
                    btn.onclick = () => {
                        const result = Tasks.claim(profile.email, btn.dataset.taskId);
                        if (!result.ok) { showAlert(result.message || '尚未完成這個任務。', { type: 'error' }); return; }
                        showToast(`任務完成，獲得 ${result.reward} 點`);
                        PageInit.profile();
                    };
                });
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
                btn.onclick = () => {
                    const id = btn.dataset.themeId;
                    if (btn.dataset.themeAction === 'redeem') {
                        const result = MemberRewards.redeemTheme(profile.email, id);
                        if (!result.ok) { showAlert(result.message, { type:'error' }); return; }
                        MemberRewards.setActiveTheme(profile.email, id);
                        showToast('已兌換並套用主題');
                    } else {
                        MemberRewards.setActiveTheme(profile.email, id);
                        showToast('已套用主題');
                    }
                    PageInit.profile();
                };
            });
        }

        const ledgerEl = document.getElementById('profilePointLedger');
        if (ledgerEl) {
            const rows = MemberRewards.ledger(profile.email);
            ledgerEl.innerHTML = rows.length ? `<div class="point-ledger">${rows.slice(0, 8).map(row => `<div>
                <span>${escapeHtml(row.reason)}</span>
                <time>${new Date(row.createdAt).toLocaleString('zh-TW')}</time>
                <b class="${row.delta >= 0 ? 'plus' : 'minus'}">${row.delta >= 0 ? '+' : ''}${row.delta}</b>
            </div>`).join('')}</div>` : '<div class="empty-state compact">尚無點數紀錄</div>';
        }
        const suggestionArea = document.getElementById('profileSuggestionArea');
        if (suggestionArea) {
            if (!suggestions.length) {
                suggestionArea.innerHTML = '<div class="empty-state compact">尚未收藏妝容對比圖</div>';
            } else {
                suggestionArea.innerHTML = `<div class="saved-look-grid">${suggestions.slice(0, 6).map((item, index) => `
                    <article class="saved-look-card reveal-in" data-look="${index}" style="animation-delay:${Math.min(index * 0.04, 0.24)}s">
                        <button class="look-del" data-del="${index}" aria-label="刪除此妝容">×</button>
                        <div class="saved-look-photo">
                            ${item.renderedImage
                                ? `<img src="${item.renderedImage}" alt="${item.style || '妝容對比圖'}" onload="this.classList.add('loaded')">`
                                : `<span>${item.style || 'Saved Look'}</span>`
                            }
                        </div>
                        <div class="saved-look-body">
                            <div class="saved-look-kicker">Saved Look</div>
                            <h3>${item.style || '妝容對比圖'}</h3>
                            <p>${formatSavedAdvice(item)}</p>
                            <time>${item.timestamp ? new Date(item.timestamp).toLocaleString('zh-TW') : ''}</time>
                        </div>
                    </article>
                `).join('')}</div>`;
            }
        }
        document.querySelectorAll('#mainContent [data-nav]').forEach(el => el.onclick = () => Router.go(el.dataset.nav));
        var __looks = suggestions;
        document.querySelectorAll('.saved-look-card[data-look]').forEach(function(card){ card.style.cursor='pointer'; card.onclick=function(){ openLookModal(__looks[+card.dataset.look]); }; });
        document.querySelectorAll('.look-del[data-del]').forEach(function(btn){
            btn.onclick = function(e){
                e.stopPropagation();
                var idx = +btn.dataset.del;
                showConfirm("確定要刪除這個收藏的妝容嗎？此動作無法復原。", {
                    title: "刪除妝容對比圖", type: "error", okText: "刪除", cancelText: "保留",
                    onOk: function(){
                        var recs = []; try { recs = JSON.parse(localStorage.getItem("beautySuggestions") || "[]"); } catch(_){}
                        recs.splice(idx, 1);
                        localStorage.setItem("beautySuggestions", JSON.stringify(recs));
                        showToast("已刪除妝容");
                        PageInit.profile();
                    }
                });
            };
        });
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
        const setDbStatus = (text, ok) => { if (dbStatusEl) { dbStatusEl.textContent = text; dbStatusEl.style.color = ok ? '#4E7A5A' : '#A0522D'; } };
        setDbStatus('資料庫載入中…', true);
        Api.fetchAdminMembers().then(list => {
            if (list && list.length) {
                dbMembers = list;
                setDbStatus(`已連接會員資料庫（${list.length} 位會員）`, true);
            } else {
                setDbStatus('資料庫連不上，目前顯示本機 demo 資料', false);
            }
            render();
        });

        const membersFromDb = () => dbMembers.map(m => {
            const localPerm = AdminStore.getPermission(m.email, m);
            return {
                name: m.name,
                email: m.email,
                level: m.level || '一般會員',
                role: m.role || 'member',
                points: m.points ?? null,
                permission: {
                    role: m.role || 'member',
                    status: m.status || 'active',
                    allowedPages: (Array.isArray(m.allowedPages) && m.allowedPages.length) ? m.allowedPages : (localPerm.allowedPages || []),
                    vipRequested: !!localPerm.vipRequested
                }
            };
        });

        const render = () => {
            const keyword = String(searchEl?.value || '').trim().toLowerCase();
            // 只吃真會員資料庫，連不上就明講，不退回 demo 假資料
            if (!dbMembers) {
                rowsEl.innerHTML = '<tr><td colspan="6"><div class="empty-state compact">會員資料庫載入中…連不上時這裡會一直是空的（已停用 demo 假資料）</div></td></tr>';
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
                return `<tr data-admin-email="${escapeHtml(member.email)}">
                    <td>
                        <div class="admin-user">
                            <b>${escapeHtml(member.name || member.email.split('@')[0])}${perm.vipRequested && member.level !== 'VIP會員' ? ' <span class="admin-fail warn">申請升級中</span>' : ''}</b>
                            <span>${escapeHtml(member.email)}</span>
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
                </tr>`;
            }).join('') || '<tr><td colspan="6"><div class="empty-state compact">沒有符合條件的使用者</div></td></tr>';

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
        };

        filters.forEach(btn => {
            btn.onclick = () => {
                filter = btn.dataset.adminFilter || 'all';
                filters.forEach(b => b.classList.toggle('active', b === btn));
                render();
            };
        });
        if (searchEl) searchEl.oninput = render;
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

            if (!dbMembers) { showAlert('會員資料庫連不上，無法儲存（已停用 demo 模式）', { type: 'error' }); return; }
            // 逐筆 PATCH 進資料庫；本機 AdminStore 只當快取鏡射，讓前台其他頁立即反映
            saveBtn.disabled = true;
            const failures = [];
            for (const r of rows) {
                const patch = { role: r.role, allowedPages: r.allowedPages };
                if (r.level) patch.level = r.level;
                const result = await Api.patchMember(r.email, patch);
                if (!result.ok) { failures.push(`${r.email}：${result.error}`); continue; }
                AdminStore.setPermission(r.email, { role: r.role, allowedPages: r.allowedPages });
                if (r.level) {
                    AdminStore.setMemberLevel(r.email, r.level);
                    if (['VIP會員', 'PRO會員'].includes(r.level)) AdminStore.clearVipRequest(r.email);
                }
                const target = dbMembers.find(m => m.email === r.email);
                if (target) { target.role = r.role; target.allowedPages = r.allowedPages; if (r.level) target.level = r.level; }
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
        const submitBtn = document.getElementById('adminProductSubmitBtn');
        const cancelBtn = document.getElementById('adminProductCancelBtn');
        const editingLabel = document.getElementById('adminProductEditingLabel');

        const exitEditMode = () => {
            editingProductId = null;
            productForm.reset();
            productForm.classList.remove('is-editing');
            submitBtn.textContent = '新增產品';
            cancelBtn.style.display = 'none';
        };

        // 商品管理：只吃真商品資料庫（/api/products），不再顯示本機 demo 商品
        let dbProducts = null;
        const ADMIN_PRODUCT_ROWS_LIMIT = 30;
        const CAT_TO_TYPE = { '底妝':'foundations', '眼影':'eyeshadows', '眼線/睫毛':'eyeliner_mascara', '唇彩':'lipsticks', '腮紅':'blushes', '眉毛彩妝':'eyebrows', '修容':'contouring', '打亮':'highlighters' };

        const enterEditMode = (id) => {
            const product = (dbProducts || []).find(p => String(p.id) === String(id));
            if (!product) return;
            editingProductId = id;
            document.getElementById('adminProductName').value = product.name || '';
            document.getElementById('adminProductCategory').value = product.cat || '底妝';
            document.getElementById('adminProductPrice').value = product.price || '';
            document.getElementById('adminProductImg').value = product.img || '';
            document.getElementById('adminProductDesc').value = product.desc || '';
            document.getElementById('adminProductShades').value = product.hex || '';
            productForm.classList.add('is-editing');
            editingLabel.textContent = product.name || id;
            submitBtn.textContent = '更新產品';
            cancelBtn.style.display = '';
            productForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
        };

        const renderProducts = () => {
            const area = document.getElementById('adminProductRows');
            const preview = document.getElementById('adminProductPreview');
            if (!area) return;
            if (!dbProducts) {
                area.innerHTML = '<tr><td colspan="6"><div class="empty-state compact">商品資料庫載入中…</div></td></tr>';
                return;
            }
            if (!dbProducts.length) {
                area.innerHTML = '<tr><td colspan="6"><div class="empty-state compact">商品資料庫連不上或沒有資料（不顯示 demo）</div></td></tr>';
                if (preview) preview.innerHTML = '';
                return;
            }
            const products = dbProducts;
            if (preview) {
                preview.innerHTML = products.slice(0, 8).map((product, index) => `<article class="prod-card admin-preview-card" data-preview-product="${escapeHtml(product.id)}" style="animation-delay:${Math.min(index * 0.025, 0.18)}s">
                    <div class="pc-imgwrap">
                        ${phBox('', product.name, product.img)}
                        <button class="heart-btn pc-heart" type="button" aria-label="收藏預覽">${HEART_SVG}</button>
                    </div>
                    <div class="pc-cat">${escapeHtml(CAT_EN[product.cat] || product.cat)}</div>
                    <div class="pc-name">${escapeHtml(product.name)}</div>
                    <div class="pc-foot"><span class="pc-price">${escapeHtml(product.price)}</span></div>
                </article>`).join('');
            }
            area.innerHTML = products.slice(0, ADMIN_PRODUCT_ROWS_LIMIT).map(product => `<tr class="admin-product-row" data-edit-product="${escapeHtml(product.id)}">
                <td><div class="admin-product-cell">${phBox('product-thumb', product.name, product.img)}<div class="admin-user"><b>${escapeHtml(product.name)}</b><span>DB id: ${escapeHtml(String(product.rawId ?? product.id))}</span></div></div></td>
                <td>${escapeHtml(product.cat)}</td>
                <td>${escapeHtml(product.price)}</td>
                <td><span class="admin-source">商品資料庫</span></td>
                <td><span class="admin-fail ok">已上架</span></td>
                <td><button class="btn-outline btn-sm" type="button" data-edit-btn="${escapeHtml(product.id)}">編輯</button></td>
            </tr>`).join('') + (products.length > ADMIN_PRODUCT_ROWS_LIMIT ? `<tr><td colspan="6"><div class="empty-state compact">僅顯示前 ${ADMIN_PRODUCT_ROWS_LIMIT} 筆，資料庫共 ${products.length} 筆</div></td></tr>` : '');
        };

        Api.listProducts().then(rec => {
            dbProducts = rec?.products || [];
            renderProducts();
        });

        const productRowsEl = document.getElementById('adminProductRows');
        if (productRowsEl) productRowsEl.addEventListener('click', (e) => {
            const trigger = e.target.closest('[data-edit-btn], [data-edit-product]');
            if (!trigger) return;
            const id = trigger.dataset.editBtn || trigger.dataset.editProduct;
            enterEditMode(id);
        });

        if (cancelBtn) cancelBtn.onclick = () => exitEditMode();

        if (productForm) productForm.onsubmit = (e) => {
            e.preventDefault();
            const name = document.getElementById('adminProductName')?.value.trim();
            const cat = document.getElementById('adminProductCategory')?.value;
            const price = document.getElementById('adminProductPrice')?.value.trim();
            const img = document.getElementById('adminProductImg')?.value.trim();
            const desc = document.getElementById('adminProductDesc')?.value.trim();
            const shadesRaw = document.getElementById('adminProductShades')?.value.trim();
            const shadesInput = shadesRaw ? shadesRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
            const shades = shadesInput.filter(c => /^#[0-9a-fA-F]{3,8}$/.test(c));
            if (!name || !cat || !price) {
                showAlert('請完整填寫商品名稱、分類與價格', { type:'error' });
                return;
            }
            if (shades.length !== shadesInput.length) {
                showAlert('色號格式不正確，只接受 Hex 色碼（例如 #3A241C），不合格式的色號已被忽略。', { type:'error' });
                return;
            }
            // 全部走真商品資料庫，不再寫 localStorage demo
            const payload = {
                name, price,
                type: CAT_TO_TYPE[cat] || 'foundations',
                image_url: img || '',
                description: desc || '',
                hex: shades[0] || null
            };
            submitBtn.disabled = true;
            const finish = (result, okMsg) => {
                submitBtn.disabled = false;
                if (!result.ok) {
                    showAlert(`資料庫寫入失敗：${result.error}${result.status === 401 ? '（管理員 session 沒帶上——請確認已用資料庫的 admin 帳號重新登入）' : ''}`, { type: 'error' });
                    return false;
                }
                showToast(okMsg);
                Router.generalProductCatalog = null; // 讓商品頁下次重抓最新清單
                dbProducts = null;
                Api.listProducts().then(rec => { dbProducts = rec?.products || []; renderProducts(); });
                return true;
            };
            if (editingProductId) {
                const target = (dbProducts || []).find(p => String(p.id) === String(editingProductId));
                Api.patchRemoteProduct(target?.rawId, payload).then(result => {
                    if (finish(result, '產品已更新並寫入資料庫')) exitEditMode();
                });
            } else {
                Api.createRemoteProduct(payload).then(result => {
                    if (finish(result, '產品已新增並寫入資料庫')) productForm.reset();
                });
            }
        };
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

    // 頂部導覽
    document.querySelectorAll('.topbar-nav a, .topbar-user').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); Router.go(a.dataset.page); };
    });

    // 判斷登入狀態
    if (Auth.isLoggedIn()) {
        showApp();
    } else {
        showLogin();
    }
    if (Auth.isLoggedIn()) routeFromHash();
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

function showLogin() {
    document.getElementById('app').style.display = 'none';
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
            name: registered.name || member.name || email.split('@')[0],
            email: member.email || email,
            phone: member.phone_number || registered.phone || '',
            age: member.age || registered.age || '',
            level: AdminStore.isAdminProfile({ email }) ? '管理員' : (member.level || registered.level || '一般會員'),
            role: AdminStore.isAdminProfile({ email }) ? 'admin' : (member.role || registered.role || 'member'),
        });
    } catch (err) {
        // 不管是伺服器明確拒絕，還是根本連不上會員資料庫，都不能放行——
        // 沒有真正在資料庫裡的會員，一律不能用登入方式進去，避免有人靠擋網路/竄改 DNS 繞過驗證。
        showAlert(err.networkFailure ? '無法連線到會員資料庫，請稍後再試' : (err.message || '帳號或密碼錯誤'), { type: 'error' });
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
    } catch (_) {
        console.warn('Auth API unavailable, using local OTP simulation.');
    }
    showVerification(email);
}

async function doVerifyOTP() {
    const code = document.getElementById('otpCode').value.trim();
    if (!code) { showAlert('請輸入驗證碼'); return; }
    const pending = Router.pendingRegister;
    if (!pending) { showAlert('註冊資料已過期，請重新註冊', { type:'error', onOk: showRegister }); return; }
    try {
        await Api.verifyOTP(pending.email, code);
    } catch (_) {
        if (code.length < 4) {
            showAlert('驗證碼至少 4 碼');
            return;
        }
    }
    Auth.setProfile({
        name: pending.name,
        phone: pending.phone,
        email: pending.email,
        age: pending.age,
        level: pending.level,
        avatar: pending.avatar,
        password: pending.password
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
    try { await Api.verifyOTP(Router.forgotEmail, code); }
    catch (_) { if (code.length < 4) { showAlert('驗證碼至少 4 碼'); return; } }
    showResetPassword();
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
