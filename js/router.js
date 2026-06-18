// ═══ 共用 UI 片段 ═══
const HEART_SVG = '<span class="pulse"></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.4S3.6 15.6 3.6 9.4C3.6 6.5 5.7 4.7 8 4.7c1.7 0 3.1 1 4 2.4 0.9-1.4 2.3-2.4 4-2.4 2.3 0 4.4 1.8 4.4 4.7 0 6.2-8.4 11-8.4 11z"/></svg>';
const CAT_EN = { '底妝':'FOUNDATION','眼影':'EYESHADOW','眼線/睫毛':'EYES & LASH','唇彩':'LIP COLOR','腮紅':'BLUSH','眉毛彩妝':'BROW','修容':'CONTOUR','打亮':'HIGHLIGHT' };
function phBox(cls, label, src){
    const cap = (cls.indexOf('product-thumb')>-1) ? '' : `<span class="ph-cap">${label||''}</span>`;
    const img = src ? `<img src="${src}" alt="${label||''}" onload="this.classList.add('loaded')">` : '';
    return `<div class="ph ${cls}">${cap}${img}</div>`;
}

function getFeaturedProducts(limit = 6) {
    const external = Array.isArray(window.HOT_PRODUCTS) ? window.HOT_PRODUCTS : null;
    const stored = (() => {
        try { return JSON.parse(localStorage.getItem('hotProducts') || 'null'); } catch (_) { return null; }
    })();
    const source = Array.isArray(external) ? external : (Array.isArray(stored) ? stored : ALL_PRODUCTS);
    return [...source]
        .sort((a, b) => Number(b.popularity || b.sales || b.views || b.reviews || 0) - Number(a.popularity || a.sales || a.views || a.reviews || 0))
        .slice(0, limit);
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
const NAV_ORDER = ['dashboard','analysis','style','products','favorites','history','compare','suggestion','profile'];
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
    const beforeImage = render.beforeImageUrl || render.beforeImageDataUrl || '';
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
        '<p>「' + featureName + '」需要你的臉部分析結果。完成一次 AI 臉部分析，我們才能依你的五官與膚色，為你打造專屬妝容。</p>',
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
<div class="dash-sec-head"><div class="sh-l"><span class="sh-no">01</span><h2>風格靈感</h2></div><span class="sh-link" data-nav="style">瀏覽全部風格</span></div>
<div class="insp-row" id="dashInsp"></div>
<div class="dash-sec-head"><div class="sh-l"><span class="sh-no">02</span><h2>為你精選</h2></div><span class="sh-link" data-nav="products">查看全部商品</span></div>
<div class="glow-row" id="dashGlow"></div>
<section class="about-sys">
    <div class="as-head">
        <div class="about-headrow"><span class="as-eyebrow-it">About the Atelier</span><h2 class="about-title">OUR BEAUTY<span class="l2">SYSTEM</span></h2></div>
        <span class="bs-link" data-nav="analysis">開始你的美學旅程　→</span>
        <p class="bs-desc">「裝識你的美」是一套以科技與美學打造的個人美妝系統。從 AI 臉部分析解讀你的五官與膚色，到為你量身推薦的妝容風格與美妝逸品 —— 我們相信，最美的樣子，是更認識自己的你。</p>
    </div>
    <div class="as-photo"><img class="as-photo-img" alt="" onload="this.classList.add('loaded')"><div class="as-photo-ph"><div class="demo-mark">❧</div><div class="demo-cap">商品形象照 · Demo</div></div></div>
</section>`,
analysis: `
<div class="page-header"><h1>臉部分析</h1><div class="divider"></div><p>上傳正面照片，AI 為你分析五官特徵</p></div>
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
                <canvas id="cameraCanvas" style="display:none;"></canvas>
            </div>
        </div>
        <div class="mode-panel" id="proPanel">
            <div class="pro-upload-grid pro-two-shot">
                <div class="pro-slot" data-pro-slot="front"><div class="slot-title">正面照</div><div class="slot-file" id="frontFileName">必填</div><input type="file" id="frontInput" accept="image/*" style="display:none;"></div>
                <div class="pro-slot" data-pro-slot="side"><div class="slot-title">側面照</div><div class="slot-file" id="sideFileName">必填</div><input type="file" id="sideInput" accept="image/*" style="display:none;"></div>
            </div>
            <div class="pro-scan-panel">
                <div class="pro-scan-copy"><b>自動掃描拍攝</b><span>看著鏡頭取得正面照，再慢慢轉向側面；系統會依臉部 yaw 角度自動擷取。</span></div>
                <div class="camera-actions"><button class="btn-outline btn-sm" id="startProScanBtn">開始掃描</button><button class="btn-outline btn-sm" id="stopProScanBtn">停止掃描</button></div>
                <div class="camera-box" id="proCameraBox">
                    <video id="proCameraVideo" autoplay playsinline muted></video>
                    <canvas id="proCameraCanvas" style="display:none;"></canvas>
                    <div class="scan-progress" id="proScanProgress"><span data-scan-role="front">正面：待擷取</span><span data-scan-role="side">側面：待擷取</span></div>
                    <div class="scan-hint" id="proScanHint">等待鏡頭啟動</div>
                </div>
            </div>
            <div class="mode-note">45 度多角度採集保留為未來展望；目前 PRO 正式流程採用正面照與單側側面照，降低樣本採集難度。</div>
        </div>
        <img id="preview" alt="preview" style="max-width:100%;margin-top:12px;border:1px solid var(--border);display:none;">
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
<div class="page-header"><h1>妝容對比圖</h1><div class="divider"></div><p>保留 iOS 端的前後對比流程：選擇風格後可按住切換渲染前 / 渲染後效果。</p></div>
<div class="compare-layout">
    <div class="compare-preview" id="comparePreview">
        <div class="ph compare-stage before" id="compareStage"><div class="compare-photo-label" id="comparePhotoLabel">渲染前照片</div></div>
        <button class="compare-hold-btn" id="compareHoldBtn">按住對比</button>
    </div>
    <div class="analysis-section">
        <h3>目前風格</h3>
        <p id="compareStyleName">尚未選擇風格</p>
        <div class="analysis-tags" id="compareStyleTags"></div>
        <button class="btn-outline" id="compareGoStyleBtn">選擇風格</button>
        <button class="btn-gold" id="compareSaveLookBtn" style="margin-top:12px;">收藏妝容對比圖</button>
    </div>
</div>`,
suggestion: `<div class="page-header"><h1>妝容建議</h1><div class="divider"></div><p>依照臉部分析結果與選擇風格，產生妝容建議與可收藏的妝容對比圖。</p></div><div id="suggestionArea"></div>`,
profile: `
<div class="page-header"><span class="eyebrow">Member</span><h1>會員中心</h1><div class="divider"></div></div>
<div class="member-wrap">
    <div class="member-id">
        <div class="member-avatar" id="profileAvatar">✦</div>
        <div class="member-name" id="profileName">訪客</div>
        <div class="member-role">Decorate Me Member</div>
        <div class="member-actions">
            <button class="btn-outline" id="changePwdBtn" style="display:none;">更改密碼</button>
            <button class="btn-outline member-logout" onclick="Auth.logout()">登出帳號</button>
        </div>
    </div>
    <div class="member-stats">
        <div class="stat-cell"><div class="stat-en">Wishlist</div><div class="stat-num" id="profileFavCount">0</div><div class="stat-label">收藏商品</div></div>
        <div class="stat-cell"><div class="stat-en">Analysis</div><div class="stat-num" id="profileAnalyzeCount">0</div><div class="stat-label">分析次數</div></div>
            <div class="stat-cell"><div class="stat-en">Looks</div><div class="stat-num" id="profileSuggestionCount">0</div><div class="stat-label">收藏妝容</div></div>
        <div class="stat-cell stat-link" data-nav="analysis"><div class="stat-en">Start</div><div class="stat-mark">＋</div><div class="stat-label">開始新分析</div></div>
    </div>
</div>
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

    async go(page, opts) {
        opts = opts || {};
        if (!opts.skipLeaveGuard && this.needsLookLeaveGuard(page)) {
            this.promptLookLeave(page, opts);
            return;
        }
        // 訪客攔截：收藏 / 分析紀錄 需登入
        if ((page === "favorites" || page === "history") && isGuest()) {
            promptGuestAuth(page === "favorites" ? "收藏" : "分析紀錄");
            return;
        }
        try {
            if (!opts.fromHash && location.hash !== `#${page}`) {
                history.pushState(null, '', `#${page}`);
            }
            const back = (NAV_ORDER.indexOf(page) > -1 && NAV_ORDER.indexOf(this.currentPage) > -1
                          && NAV_ORDER.indexOf(page) < NAV_ORDER.indexOf(this.currentPage));
            const res = await fetch(`pages/${page}.html?v=20260618-pro-side-scan`, { cache: 'no-store' });
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
            showConfirm('訪客不能收藏妝容對比圖與妝容建議。離開後會清空目前這次妝容暫存。', {
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
        const user = (Auth.getUser && Auth.getUser()) || '訪客';
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

        // Hero · 本週精選風格（取第一個風格）
        const feat = (typeof STYLES !== 'undefined' && STYLES[0]) ? STYLES[0] : null;
        if (feat) {
            const hn = document.getElementById('heroName');
            if (hn) hn.innerHTML = `${feat.name.split(' ')[0]} <em>${(feat.name.split(' ')[1]||'')}</em>`;
            const ht = document.getElementById('heroTags');
            if (ht) ht.innerHTML = feat.tags.map(t => `<span>${t}</span>`).join('');
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

        // 熱銷精選 · 分類標籤（真實 CATEGORIES）
        const cats = document.getElementById('dashCats');
        if (cats && typeof CATEGORIES !== 'undefined') {
            cats.innerHTML = `<span class="bs-cats-label">Categories</span>` +
                `<button class="chip" data-filter="all">全部</button>` +
                CATEGORIES.map(c => `<button class="chip" data-filter="${c.id}">${c.id}</button>`).join('');
            cats.querySelectorAll('.chip').forEach(ch => ch.onclick = () => Router.go('products', { category: ch.dataset.filter }));
        }

        // 首頁商品推薦：保留錯落排版，圖片沿用商品推薦頁同一套 DEMO 佔位。
        const glow = document.getElementById('dashGlow');
        if (glow && typeof ALL_PRODUCTS !== 'undefined') {
            const picks = getFeaturedProducts(6);
            glow.innerHTML = picks.map((p) => `
                <div class="glow-card reveal-in" data-pid="${p.id}">
                    <div class="gc-img">
                        ${phBox('', p.name, p.img)}
                        <button class="heart-btn gc-heart ${Fav.has(p.id)?'fav':''}" data-fav="${p.id}" aria-label="收藏">${HEART_SVG}</button>
                    </div>
                    <div class="gc-meta">
                        <div class="gc-top"><span class="gc-name">${p.name}</span><span class="gc-price">${p.price}</span></div>
                        <div class="gc-rating"><span class="stars">★★★★★</span><span class="gc-rev">${p.reviews || 643} 則評價</span></div>
                    </div>
                </div>`).join('');
            glow.querySelectorAll('.glow-card').forEach(card => {
                card.onclick = (e) => { if (!e.target.closest('.heart-btn')) Router.go('products', { productId: +card.dataset.pid }); };
            });
            glow.querySelectorAll('.gc-heart').forEach(btn => {
                btn.onclick = (e) => {
                    e.stopPropagation();
                    const id = +btn.dataset.fav; const wasFav = Fav.has(id);
                    Fav.toggle(id); btn.classList.toggle('fav', !wasFav);
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
            reader.onload = ev => { preview.src = ev.target.result; preview.style.display = 'block'; };
            reader.readAsDataURL(file);
        };

        const setMode = (mode) => {
            Router.analyzeMode = mode;
            basicModeBtn.classList.toggle('active', mode === 'basic');
            proModeBtn.classList.toggle('active', mode === 'pro');
            basicPanel.classList.toggle('active', mode === 'basic');
            proPanel.classList.toggle('active', mode === 'pro');
            analyzeBtn.textContent = mode === 'basic' ? '開 始 分 析' : '開 始 PRO 分 析';
            setLoadingStatus('等待圖片');
            updatePackageStatus();
        };

        basicModeBtn.onclick = () => setMode('basic');
        proModeBtn.onclick = () => setMode('pro');
        setMode(Router.analyzeMode);

        uploadBox.onclick = () => fileInput.click();
        fileInput.onchange = (e) => {
            const file = e.target.files[0];
            if (!file) return;
            Router.selectedFile = file;
            showPreview(file);
            saveDraft('image-selected');
        };

        document.querySelectorAll('[data-pro-slot]').forEach(slot => {
            const key = slot.dataset.proSlot;
            const input = document.getElementById(`${key}Input`);
            const nameEl = document.getElementById(`${key}FileName`);
            slot.onclick = () => input.click();
            input.onchange = (e) => {
                const file = e.target.files[0];
                if (!file) return;
                Router.proFiles[key] = file;
                nameEl.textContent = file.name;
                if (key === 'front') {
                    Router.selectedFile = file;
                    showPreview(file);
                }
                saveDraft('image-selected');
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
            canvas.getContext('2d').drawImage(video, 0, 0);
            canvas.toBlob(blob => {
                if (!blob) {
                    showAlert('拍照失敗', { type:'error' });
                    return;
                }
                Router.selectedFile = new File([blob], 'basic-camera.jpg', { type: 'image/jpeg' });
                showPreview(Router.selectedFile);
                saveDraft('camera-captured');
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
            canvas.getContext('2d').drawImage(video, 0, 0);
            canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('影格擷取失敗')), 'image/jpeg', 0.9);
        });

        const storeProScanPhoto = (role, blob, pose) => {
            const file = new File([blob], `pro-${role}-${Date.now()}.jpg`, { type: 'image/jpeg' });
            Router.proFiles[role] = file;
            const nameEl = document.getElementById(`${role}FileName`);
            if (nameEl) nameEl.textContent = role === 'front' ? '已自動擷取正面照' : '已自動擷取側面照';
            if (role === 'front') {
                Router.selectedFile = file;
                showPreview(file);
            }
            setProScanStatus(role, `${role === 'front' ? '正面' : '側面'}：已擷取 yaw ${Math.round(pose.yaw || 0)}°`, true);
            saveDraft('camera-captured');
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
                setProScanHint(`目前 yaw ${Math.round(yaw)}° / pitch ${Math.round(pitch)}°，請依提示慢慢轉頭`);
                if (!Router.proFiles.front && Math.abs(yaw) <= 15 && Math.abs(pitch) <= 18) {
                    storeProScanPhoto('front', blob, pose);
                    setProScanHint('正面已完成，請慢慢轉向單側側面');
                } else if (Router.proFiles.front && !Router.proFiles.side && Math.abs(yaw) >= 50) {
                    storeProScanPhoto('side', blob, pose);
                    setProScanHint('側面已完成，可開始 PRO 分析');
                    stopProScan();
                }
            } catch (err) {
                setProScanHint('偵測中：' + err.message);
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
                }
                setProScanStatus('front', Router.proFiles.front ? '正面：已擷取' : '正面：請看鏡頭');
                setProScanStatus('side', Router.proFiles.side ? '側面：已擷取' : '側面：待擷取');
                setProScanHint('請先看著鏡頭，系統會自動擷取正面照');
                if (Router.proScanTimer) clearInterval(Router.proScanTimer);
                Router.proScanTimer = setInterval(scanProFrame, 900);
                setTimeout(scanProFrame, 500);
            } catch (err) {
                showAlert('無法開啟 PRO 掃描：' + err.message, { type:'error' });
            }
        };

        const stopProScanBtn = document.getElementById('stopProScanBtn');
        if (stopProScanBtn) stopProScanBtn.onclick = () => {
            stopProScan();
            setProScanHint('掃描已停止');
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
            const startedAt = Date.now();
            if (!Router.analysisPackage) saveDraft('queued');
            Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                status: 'preparing-image',
                async: { ...Router.analysisPackage.async, startedAt: new Date(startedAt).toISOString(), error: null }
            });
            AnalysisDraft.save(Router.analysisPackage);
            updatePackageStatus();
            setLoadingStatus('原圖送出分析中', true);
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
                showAlert('分析失敗：' + err.message, { type:'error' });
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
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '產生建議中...';
            try {
                const style = STYLES.find(s => s.id === Router.selectedStyleId);
                const pkg = Router.analysisPackage;
                if (!pkg || !Router.analysisResult) {
                    showAlert('目前沒有可用的臉部分析結果，請重新完成臉部分析。', { type:'error' });
                    Router.go('analysis');
                    return;
                }
                const latestAnalysis = getLatestAnalysisResult() || {};
                const response = await Api.suggestMakeup({
                    analysisPackage: pkg,
                    faceAnalysis: pkg?.faceAnalysis || AnalysisPackage.fromRawFaceAnalysis(latestAnalysis, Router.analyzeMode),
                    style: style?.name || '日常自然妝',
                    userNote: style?.tags?.join('、') || ''
                });
                Router.analysisPackage = AnalysisPackage.update(pkg || Router.analysisPackage, {
                    generativeText: {
                        provider: response.provider || 'ollama',
                        prompt: null,
                        suggestion: response.suggestion || null,
                        model: response.model || null,
                        status: response.status || 'completed',
                        error: null,
                        fallbackUsed: !!response.fallbackUsed
                    },
                    recommendations: {
                        ...(pkg?.recommendations || Router.analysisPackage?.recommendations || {}),
                        style: style?.name || null
                    }
                });
                AnalysisDraft.save(Router.analysisPackage);
                Router.pendingLook = buildCurrentLookRecord();
                Router.pendingLookSaved = false;
                renderAnalysisResult(response);
            } catch (err) {
                const pkg = Router.analysisPackage;
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
                renderAnalysisResult(null);
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        };

        function renderAnalysisResult(aiSuggestionResponse) {
            const style = STYLES.find(s => s.id === Router.selectedStyleId);
            const advice = style.advice || defaultAdvice();
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
                <div class="style-intro-card">
                    <h3>${style.name} 妝容介紹</h3>
                    <p>${style.intro || '此風格介紹尚待補充。'}</p>
                    <div class="palette-row">${palette.map(c => `<span style="background:${c}"></span>`).join('')}</div>
                </div>
                <div class="makeup-category-grid">
                    ${MAKEUP_CATEGORIES.map((c,i) => `<div><b>${String(i+1).padStart(2,'0')}</b><span>${c.title}</span></div>`).join('')}
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
                <div class="analysis-section">
                    <h3>專屬妝容建議</h3>
                    ${aiSuggestion ? `
                        <div class="style-intro-card">
                            <h3>AI 文字建議</h3>
                            <p style="white-space:pre-line;">${escapeHtml(aiSuggestion)}</p>
                        </div>
                    ` : ''}
                    <div class="advice-grid">
                        <div><b>底妝建議</b><p>${advice.base}</p></div>
                        <div><b>眉型建議</b><p>${advice.brow}</p></div>
                        <div><b>眼妝建議</b><p>${advice.eye}</p></div>
                        <div><b>腮紅 & 修容</b><p>${advice.blush}</p></div>
                        <div><b>唇妝建議</b><p>${advice.lip}</p></div>
                    </div>
                </div>
                <div style="text-align:center;margin-top:20px;">
                    <button class="btn-outline" onclick="Router.go('compare')" style="margin-right:8px;">查看前後對比</button>
                    <button class="btn-outline" onclick="Router.go('suggestion')" style="margin-right:8px;">查看妝容建議</button>
                    <button class="btn-gold" onclick="Router.go('products')">查看推薦商品 →</button>
                </div>
            `;
        }

        function defaultAdvice() {
            return { base:'清透柔霧底妝', brow:'自然平眉', eye:'柔霧大地色', blush:'甜感腮紅', lip:'紅色系' };
        }

        function escapeHtml(value) {
            return String(value)
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#039;');
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
            const list = filter === 'all' ? ALL_PRODUCTS : ALL_PRODUCTS.filter(p => p.cat === filter);
            const header = `
                <div class="page-header"><span class="eyebrow">Boutique · 選物</span><h1>商品推薦</h1><div class="divider"></div></div>
                <div class="filter-bar">${chips}</div>
                <div class="prod-count">${list.length} 件商品</div>`;
            const bindChips = () => {
                area.querySelectorAll('.chip').forEach(ch => ch.onclick = () => renderShop(ch.dataset.filter));
            };
            // 1) 骨架載入
            area.innerHTML = header + `<div class="prod-grid">` + Array.from({length:Math.min(list.length||4,8)}).map(()=>`
                <div><div class="skel-block" style="width:100%;aspect-ratio:4/5;margin-bottom:15px;"></div>
                <div class="skel-block" style="width:40%;height:10px;margin-bottom:9px;"></div>
                <div class="skel-block" style="width:78%;height:14px;margin-bottom:10px;"></div>
                <div class="skel-block" style="width:30%;height:14px;"></div></div>`).join('') + `</div>`;
            bindChips();
            // 2) 淡入商品卡
            setTimeout(() => {
                if (Router.currentPage !== 'products' || Router.shopFilter !== filter) return;
                area.innerHTML = header + `<div class="prod-grid">` + list.map((p, i) => `
                    <div class="prod-card reveal-in" data-pid="${p.id}" style="animation-delay:${Math.min(i*0.035,0.4)}s">
                        <div class="pc-imgwrap">
                            ${phBox('', p.name, p.img)}
                            <button class="heart-btn pc-heart ${Fav.has(p.id)?'fav':''}" data-fav="${p.id}" aria-label="收藏">${HEART_SVG}</button>
                        </div>
                        <div class="pc-cat">${CAT_EN[p.cat]||p.cat}</div>
                        <div class="pc-name">${p.name}</div>
                        <div class="pc-foot"><span class="pc-price">${p.price}</span></div>
                    </div>`).join('') + `</div>`;
                bindChips();
                area.querySelectorAll('.prod-card').forEach(card => {
                    card.onclick = (e) => { if (!e.target.closest('.heart-btn')) renderProductDetail(+card.dataset.pid); };
                });
                area.querySelectorAll('.pc-heart').forEach(btn => {
                    btn.onclick = (e) => {
                        e.stopPropagation();
                        const id = +btn.dataset.fav;
                        const wasFav = Fav.has(id);
                        Fav.toggle(id);
                        btn.classList.toggle('fav', !wasFav);
                        btn.classList.remove('swap'); void btn.offsetWidth; btn.classList.add('swap');
                        if (!wasFav) showToast('已加入收藏');
                    };
                });
            }, 360);
        }

        function renderProductDetail(id) {
            const p = ALL_PRODUCTS.find(x => x.id === id);
            if (!p) return;
            const area = document.getElementById('productsArea');
            const shades = (p.shades && p.shades.length) ? p.shades : ['#3A241C','#C99070','#B5654A','#9A4E3C','#7C3F30'];
            let related = ALL_PRODUCTS.filter(x => x.cat === p.cat && x.id !== p.id).slice(0,3);
            if (related.length < 3) related = related.concat(ALL_PRODUCTS.filter(x => x.cat !== p.cat && x.id !== p.id).slice(0, 3 - related.length));
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
                        <div class="pd-price-lg">${p.price}</div>
                        <div class="pd-color">
                            <div class="pd-color-label">色號 <span>Shade</span></div>
                            <div class="pd-shades">${shades.map((c,i)=>`<button class="shade ${i===0?'active':''}" data-shade="${i}" style="background:${c}" aria-label="色號 ${i+1}"></button>`).join('')}</div>
                        </div>
                        <div class="pd-actions">
                            <button class="add-bag" data-bag="${p.id}">加入購物袋</button>
                            <button class="heart-btn pd-heart ${Fav.has(p.id)?'fav':''}" data-fav-detail="${p.id}" aria-label="收藏">${HEART_SVG}</button>
                        </div>
                        <div class="pd-desc">商品詳細說明區域。可放入完整描述、使用方式、成分說明等資訊。</div>
                    </div>
                </div>
                <div class="pd-related">
                    <div class="dash-sec-head"><div class="sh-l"><span class="sh-no">❧</span><h2>你可能也喜歡</h2></div><span class="sh-link" onclick="PageInit.products();">查看全部</span></div>
                    <div class="prod-grid">${related.map(r => `
                        <div class="prod-card reveal-in" data-rel="${r.id}">
                            <div class="pc-imgwrap">${phBox('', r.name, r.img)}</div>
                            <div class="pc-cat">${CAT_EN[r.cat]||r.cat}</div>
                            <div class="pc-name">${r.name}</div>
                            <div class="pc-foot"><span class="pc-price">${r.price}</span></div>
                        </div>`).join('')}</div>
                </div>
            `;
            area.querySelectorAll('.shade').forEach(s => s.onclick = () => {
                area.querySelectorAll('.shade').forEach(x => x.classList.remove('active'));
                s.classList.add('active');
            });
            const bag = area.querySelector('[data-bag]');
            if (bag) bag.onclick = () => showToast('已加入購物袋');
            const dBtn = area.querySelector('[data-fav-detail]');
            if (dBtn) dBtn.onclick = () => {
                const wasFav = Fav.has(p.id);
                Fav.toggle(p.id);
                dBtn.classList.toggle('fav', !wasFav);
                dBtn.classList.remove('swap'); void dBtn.offsetWidth; dBtn.classList.add('swap');
                if (!wasFav) showToast('已加入收藏');
            };
            area.querySelectorAll('[data-rel]').forEach(c => c.onclick = () => { window.scrollTo(0,0); renderProductDetail(+c.dataset.rel); });
        }
    },

    favorites() {
        const items = ALL_PRODUCTS.filter(p => Fav.has(p.id));
        const area = document.getElementById('favArea');
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
            card.onclick = (e) => { if (!e.target.closest('.heart-btn')) Router.go('products',{productId:+card.dataset.pid}); };
        });
        area.querySelectorAll('[data-unfav]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                btn.classList.remove('swap'); void btn.offsetWidth; btn.classList.add('swap');
                const card = btn.closest('.prod-card');
                if (card) { card.style.transition='opacity .35s var(--ease), transform .35s var(--ease)'; card.style.opacity='0'; card.style.transform='translateY(10px)'; }
                setTimeout(()=>{ Fav.toggle(+btn.dataset.unfav); PageInit.favorites(); }, 320);
            };
        });
    },

    compare() {
        if (!hasStartedJourney()) { renderAnalysisGate("妝容對比圖"); return; }
        const style = STYLES.find(s => s.id === Router.selectedStyleId);
        const nameEl = document.getElementById('compareStyleName');
        const tagsEl = document.getElementById('compareStyleTags');
        const stage = document.getElementById('compareStage');
        const label = document.getElementById('comparePhotoLabel');
        const holdBtn = document.getElementById('compareHoldBtn');
        Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
        Router.pendingLookSaved = false;

        nameEl.textContent = style ? style.name : '尚未選擇風格';
        tagsEl.innerHTML = style ? style.tags.map(t => `<span class="analysis-tag">${t}</span>`).join('') : '';

        const showAfter = () => {
            stage.classList.remove('before');
            stage.classList.add('after');
            label.textContent = style ? `${style.name} 渲染後照片` : '渲染後照片';
            setCompareImage('after');
        };
        const showBefore = () => {
            stage.classList.remove('after');
            stage.classList.add('before');
            label.textContent = '渲染前照片';
            setCompareImage('before');
        };
        holdBtn.onpointerdown = showAfter;
        holdBtn.onpointerup = showBefore;
        holdBtn.onpointerleave = showBefore;
        holdBtn.onfocus = showAfter;
        holdBtn.onblur = showBefore;
        document.getElementById('compareGoStyleBtn').onclick = () => Router.go('style');
        const saveBtn = document.getElementById('compareSaveLookBtn');
        if (saveBtn) {
            saveBtn.onclick = () => {
                Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
                if (saveCurrentLook()) showToast('已收藏妝容對比圖');
            };
        }

        function setCompareImage(kind) {
            const pkg = Router.analysisPackage || {};
            const render = pkg.render || {};
            const beforeImage = render.beforeImageUrl || render.beforeImageDataUrl || '';
            const afterImage = render.afterImageUrl || render.afterImageDataUrl || render.makeupOutput?.imageUrl || render.makeupOutput?.imageDataUrl || '';
            const image = kind === 'after' ? afterImage : beforeImage;
            stage.classList.toggle('has-render', !!image);
            stage.style.backgroundImage = image ? `url("${image}")` : '';
        }
        setCompareImage('before');
    },

    suggestion() {
        if (!hasStartedJourney()) { renderAnalysisGate("妝容建議"); return; }
        const style = STYLES.find(s => s.id === Router.selectedStyleId) || STYLES[0];
        const advice = style.advice || { base:'清透柔霧底妝', brow:'自然平眉', eye:'柔霧大地色', blush:'甜感腮紅', lip:'紅色系' };
        const r = getLatestAnalysisResult() || {};
        const skin = r['膚色'] || {};
        const pkg = Router.analysisPackage || {};
        const aiSuggestion = pkg.generativeText?.suggestion || '';
        const render = pkg.render || {};
        const makeupOutput = render.makeupOutput || {};
        const renderedImage = render.afterImageUrl || render.afterImageDataUrl || makeupOutput.imageUrl || makeupOutput.imageDataUrl || '';
        const area = document.getElementById('suggestionArea');
        area.innerHTML = `
            <div class="rendered-suggestion-card">
                <div class="rendered-photo-frame">
                    ${renderedImage
                        ? `<img src="${renderedImage}" alt="${style.name} 渲染後妝容照片">`
                        : `<div class="rendered-photo-placeholder">
                            <span>妝後照片</span>
                            <b>${style.name}</b>
                        </div>`
                    }
                </div>
                <div class="rendered-photo-copy">
                    <div class="detail-pill">AI 渲染結果</div>
                    <h3>${style.name} 渲染後妝容照片</h3>
                    <p>${renderedImage ? '這張照片來自目前分析資料包的 AI 渲染結果。' : '渲染端尚未回傳圖片，這裡已先預留照片位置；之後只要把圖片 URL 或 DataURL 寫進分析資料包即可自動顯示。'}</p>
                </div>
            </div>
            <div class="style-intro-card">
                <h3>${style.name} 專屬妝容建議</h3>
                <p style="white-space:pre-line;">${escapeSuggestionText(aiSuggestion || style.intro || '此風格介紹尚待補充。')}</p>
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
                <h3>建議收藏</h3>
                <div class="advice-grid">
                    ${Object.entries(advice).map(([key, text]) => `<div><b>${adviceTitle(key)}</b><p>${text}</p></div>`).join('')}
                </div>
                <button class="btn-gold" id="saveSuggestionBtn" style="margin-top:14px;">收藏妝容對比圖</button>
            </div>
        `;
        Router.pendingLook = Router.pendingLook || buildCurrentLookRecord();
        Router.pendingLookSaved = false;
        document.getElementById('saveSuggestionBtn').onclick = () => {
            if (saveCurrentLook()) showToast('已收藏妝容對比圖');
        };

        function adviceTitle(key) {
            return ({ base:'底妝建議', brow:'眉型建議', eye:'眼妝建議', blush:'腮紅 & 修容', lip:'唇妝建議' })[key] || key;
        }

        function escapeSuggestionText(value) {
            return String(value)
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#039;');
        }
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
        const user = Auth.getUser();
        document.getElementById('profileName').textContent = user || '訪客';
        // 大頭貼：有上傳照片就顯示，否則用名字首字（訪客用 ✦）
        var __av = document.getElementById('profileAvatar');
        if (__av) {
            var __p = Auth.getProfile() || {};
            if (__p.avatar) { __av.classList.add('has-photo'); __av.innerHTML = '<img src="' + __p.avatar + '" alt="' + (user || '會員') + '">'; }
            else { __av.classList.remove('has-photo'); __av.textContent = (user && user !== '訪客') ? user.trim().charAt(0).toUpperCase() : '✦'; }
        }
        const favEl = document.getElementById('profileFavCount');
        const anEl = document.getElementById('profileAnalyzeCount');
        const suggestionEl = document.getElementById('profileSuggestionCount');
        const suggestions = (() => {
            try { return JSON.parse(localStorage.getItem('beautySuggestions') || '[]'); } catch (_) { return []; }
        })();
        if (favEl) { favEl.textContent = ALL_PRODUCTS.filter(p => Fav.has(p.id)).length; favEl.classList.add('num-pop'); }
        if (anEl) { anEl.textContent = History.list().length; anEl.classList.add('num-pop'); anEl.style.animationDelay='.1s'; }
        if (suggestionEl) { suggestionEl.textContent = suggestions.length; suggestionEl.classList.add('num-pop'); suggestionEl.style.animationDelay='.16s'; }
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
    document.getElementById('sidebarUsername').textContent = Auth.getUser();
    const homeUrl = `${location.pathname}${location.search}#dashboard`;
    if (location.hash !== '#dashboard') history.replaceState(null, '', homeUrl);
    Router.go('dashboard');
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
    try {
        const data = await Api.login(email, password);
        const member = data.member || {};
        Auth.setProfile({
            name: member.name || email.split('@')[0],
            email: member.email || email,
            phone: member.phone_number || '',
            age: member.age || '',
            level: member.level || '一般會員',
        });
    } catch (_) {
        Auth.setProfile({ name: email.split('@')[0], email, level: '本地原型會員' });
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

    if (!name || !phone || !email || !age || !password || !confirm) {
        showAlert('請完整填寫所有欄位');
        return;
    }
    if (password !== confirm) {
        showAlert('密碼與確認密碼不一致', { type:'error' });
        return;
    }

    Router.pendingRegister = { name, phone, email, age, password, avatar, level: 'VIP會員' };
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
        avatar: pending.avatar
    });
    Router.pendingRegister = null;
    showAlert('帳號已成功建立', { type:'success', onOk: showApp });
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
    if (profile.email && Router.forgotEmail && profile.email === Router.forgotEmail) {
        Auth.setProfile(Object.assign({}, profile, { password: p1 }));
    }
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

