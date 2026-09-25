// 資料包離開瀏覽器時，只准送白名單裡的欄位——尤其**不准送照片**。
//
// 背景（2026-09-25 盤點）：`analysisPackage` 是前端的本機狀態容器，不是傳輸契約。
// 沒有任何一個後端收到完整資料包，三個端各拿一份不同的子集：
//
//   /recommend-products  analysisPackage 包裝裡的 4 個鍵
//   /render/jobs         faceAnalysis + faceJobId + render.styleId + 3 個簽章欄
//   /suggest             只有 faceAnalysis，完全不送資料包
//
// 而本機那包裡有 `images.front.compressedDataUrl`——使用者的臉部照片 base64。
// 三處白名單散在 js/api.js 兩處與 js/router.js 一處，改一處忘一處不會報錯。
//
// 真的漏出去會怎樣：渲染端對資料包有 **64 KB 上限**（`MAX_ANALYSIS_PACKAGE_CHARS`），
// 超過回 **413 ANALYSIS_PACKAGE_TOO_LARGE**。一張壓縮後的自拍就遠超過那個上限，
// 所以症狀是「渲染整個不能用」，而錯誤訊息完全不會指向「前端多送了一張照片」。
// 推薦端沒有大小上限，所以那邊漏出去更糟：它會**成功**，照片就這樣送出去了。
//
// 這支測試造一個帶照片的資料包，實跑三個路徑，攔下送出的 body 逐一檢查。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');

// 渲染端的上限，跟 render/replicate_render_api.py 的 MAX_ANALYSIS_PACKAGE_CHARS 一致。
// 那邊可用環境變數調大，這裡盯的是預設值——能在預設值下跑才算安全。
const MAX_PACKAGE_CHARS = 64 * 1024;

// 准許離開瀏覽器的欄位。**加欄位請先確認對方真的會讀**，不要因為「順手帶著」就加：
// 送了但沒人讀，下一個人會以為它有作用。
const ALLOWED = {
    products: {
        top: ['analysisPackage', 'limit', 'recommendationOptions'],
        pkg: ['id', 'schemaVersion', 'style', 'faceAnalysis', 'generativeText'],
    },
    render: {
        top: ['image', 'styleId', 'analysisPackage', 'strength'],
        pkg: ['faceAnalysis', 'faceJobId', 'render', 'generativeText'],
    },
    suggest: {
        top: ['faceAnalysis', 'style', 'language', 'userNote'],
        pkg: null,   // 建議端完全不收資料包
    },
};

let failed = 0;
function check(label, ok, hint) {
    if (ok) { console.log(`  PASS ${label}`); return; }
    failed += 1;
    console.error(`  FAIL ${label}${hint ? `\n       ${hint}` : ''}`);
}

// ── 載入 js/api.js，並把送出去的 body 全部攔下來 ─────────────────────────
function loadApi() {
    const src = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8')
        + '\nglobalThis.__Api = Api; globalThis.__AnalysisPackage = AnalysisPackage;';
    const store = { getItem: () => null, setItem() {}, removeItem() {}, key: () => null, length: 0 };
    const el = () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {}, addEventListener() {} });
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, info() {} },
        localStorage: store, sessionStorage: store,
        navigator: { userAgent: 'node', language: 'zh-TW' },
        location: { href: 'https://x/', origin: 'https://x', protocol: 'https:', hostname: 'x', search: '' },
        setTimeout, clearTimeout, setInterval, clearInterval,
        Date, Math, JSON, Object, Array, String, Number, Boolean, RegExp, Promise, Error, Map, Set, Infinity,
        isNaN, isFinite, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
        btoa: (s) => s, atob: (s) => s, URL, URLSearchParams, TextEncoder, TextDecoder,
        crypto: { getRandomValues: (a) => a, randomUUID: () => 'x' },
        AbortController, Headers: class {}, Request: class {}, Response: class {},
        fetch: () => Promise.reject(new Error('測試不該打真的網路')),
        document: {
            getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
            createElement: el, addEventListener() {}, body: { appendChild() {} }, cookie: '',
        },
        addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
        performance: { now: () => 0 }, requestAnimationFrame: (f) => f(),
        Image: class {}, Blob: class {}, FileReader: class {}, OffscreenCanvas: class {},
        CustomEvent: class {}, Event: class {}, alert() {}, confirm: () => true,
        matchMedia: () => ({ matches: false, addListener() {} }),
        screen: { width: 1, height: 1 }, history: { pushState() {} },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.self = sandbox;
    sandbox.top = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    if (!sandbox.__Api) throw new Error('載入 js/api.js 之後拿不到 Api');
    return { Api: sandbox.__Api, AnalysisPackage: sandbox.__AnalysisPackage };
}

const { Api, AnalysisPackage } = loadApi();

// 攔截所有送出的請求。兩個方法都要攔：推薦端走 _fetchWithRelogin，
// 渲染與建議端走 _protectedFetch。
const sent = [];
const fakeResponse = {
    ok: true, status: 200,
    json: () => Promise.resolve({ ok: true, products: [], analysisPackage: { recommendations: { products: [] } } }),
};
for (const method of ['_fetchWithRelogin', '_protectedFetch']) {
    Api[method] = (url, init) => {
        let body = null;
        try { body = JSON.parse(init?.body ?? 'null'); } catch (_) { body = '(不是 JSON)'; }
        sent.push({ url: String(url), body, raw: init?.body ?? '' });
        return Promise.resolve(fakeResponse);
    };
}
// 渲染端會先去打 /health 暖機，那支不帶資料包，攔掉就好。
Api._warmService = () => Promise.resolve();

// ── 造一個「像真的」的資料包：重點是它**帶著照片** ────────────────────────
// 用 8 萬字元模擬一張壓縮後的自拍。單獨就超過渲染端 64 KB 的上限，
// 所以只要它漏進請求，下面的大小檢查一定會抓到。
const FAKE_PHOTO = 'data:image/jpeg;base64,' + 'A'.repeat(80 * 1024);

const pkg = AnalysisPackage.create({ mode: 'basic', status: 'completed' });
pkg.images = {
    front: { compressedDataUrl: FAKE_PHOTO, dataUrl: FAKE_PHOTO, width: 1200, height: 1600 },
    side: { compressedDataUrl: FAKE_PHOTO },
};
pkg.faceAnalysis = {
    ...pkg.faceAnalysis,
    faceShape: '鵝蛋臉', browShape: '標準眉', eyeShape: '杏眼', lipShape: '標準唇',
    season: '春季',
    // LAB 在資料包裡是**物件** {L, a, b}，臉部分析端就是這樣回的
    // （face/Face_analyzer_BASIC.py:1765："LAB": {"L":…, "a":…, "b":…}）。
    // 送給推薦端時才轉成**陣列** [L, a, b]（契約要求），轉換點是 _labToArrayStrict。
    //
    // 這裡刻意用物件格式，因為要測的是那個轉換真的有發生。
    // 若上游哪天改成直接回陣列：_labToUpperKeys 的 typeof 檢查會放行（陣列也是 object），
    // 但 lab.L / lab.l 都取不到值，於是**靜靜回 null**——膚色永遠送不到推薦端，
    // 所有粉底色號比對被降級，而且沒有任何錯誤訊息。下面的斷言就是守這件事。
    skinTone: { season: '春季', level: 'light', lab: { L: 72.1, a: 12.4, b: 18.9 }, labReliable: true },
    lipLab: { L: 58.2, a: 28.1, b: 12.3 },
    // raw 是臉部分析端的原始回應。**不可以剝掉**：建議服務的 _pick() 拿它當第三層
    // 退路（英文鍵 → 中文鍵 → raw 裡的中文鍵），剝了會讓五官變「未提供」。
    // 但它會長大，所以這支測試盯的是總大小，不是「有沒有 raw」。
    raw: { 臉型: '鵝蛋臉', 眉型: '標準眉', 眼型: '杏眼', 嘴型: '標準唇', 膚色: { 四季型: '春季', LAB: [72.1, 12.4, 18.9] } },
};
pkg.generativeText = {
    ...pkg.generativeText,
    suggestion: '一段中文建議',
    ollamaRenderPromptEn: 'Apply visible Hong Kong retro makeup only.',
    promptSignature: 'deadbeef', promptSignatureVersion: 'hmac-sha256-v1',
    styleTags: ['復古感'], preferredColors: ['磚紅'], avoidTags: ['珠光'],
};
pkg.async = { jobId: 'JOB-123', resultToken: 'TOK-456' };

console.log('=== 資料包離開瀏覽器時的白名單 ===\n');
console.log(`  （本機資料包含照片，序列化後 ${Math.round(JSON.stringify(pkg).length / 1024)} KB）\n`);

// ── 逐一實跑 ─────────────────────────────────────────────────────────────
(async () => {
    // ① 商品推薦。簽名是**位置參數** (analysisPackage, styleId, options)，不是物件參數——
    //    傳錯的話 fa 會是 undefined，送出去的 faceAnalysis 每個欄位都是 null，
    //    而上面那些白名單檢查**照樣全過**（空殼也符合白名單）。所以下面加了一條
    //    「不准是空殼」的斷言，否則這支測試會在驗空氣。
    sent.length = 0;
    await Api.recommendProducts(pkg, 'hongKong', { limit: 12 }).catch(() => {});
    audit('products', '商品推薦 /recommend-products');
    assertNotHollow();

    // ② 渲染。呼叫端（router.js）另外組了 renderPackage，這裡直接把**整包**丟進去，
    //    模擬「有人偷懶把 Router.analysisPackage 原封不動傳下來」。
    //    Api.renderMakeupAsync 收到什麼就送什麼，所以這一關是在證明：
    //    一旦呼叫端沒先挑欄位，照片就會外洩——也就是為什麼 renderPackage 必須存在。
    sent.length = 0;
    await Api.renderMakeupAsync({ imageDataUrl: FAKE_PHOTO, styleId: 'hongKong', analysisPackage: pkg })
        .catch(() => {});
    auditRenderPassthrough();

    // ③ 文字建議
    sent.length = 0;
    await Api.suggestMakeup({ faceAnalysis: pkg.faceAnalysis, style: '港風', userNote: '復古感' })
        .catch(() => {});
    audit('suggest', '文字建議 /suggest');

    console.log(failed ? `\n${failed} 項未通過` : '\n資料包傳輸白名單測試通過');
    process.exitCode = failed ? 1 : 0;
})();

function hasPhoto(value) {
    return /data:image\/[a-z+]+;base64,/i.test(JSON.stringify(value ?? null));
}

// 白名單檢查對「空殼」是無效的：每個欄位都是 null 也完全符合白名單。
// 所以要另外確認送出去的東西**真的有內容**——否則呼叫方式一改錯，
// 這支測試會繼續全綠，而推薦端收到的是一包 null。
function assertNotHollow() {
    const req = sent.find(r => r.body && typeof r.body === 'object');
    const fa = req?.body?.analysisPackage?.faceAnalysis || {};
    const filled = ['faceShape', 'browShape', 'eyeShape', 'lipShape'].filter(k => fa[k]);
    check(
        '  送出的 faceAnalysis 不是空殼',
        filled.length === 4,
        `只有 ${JSON.stringify(filled)} 有值，其餘是 null。`
        + 'recommendProducts 的簽名是位置參數 (analysisPackage, styleId, options)，'
        + '用物件參數呼叫會讓 fa 變成 undefined——送出去整包都是 null，'
        + '而所有白名單檢查照樣會過（空殼也符合白名單）。',
    );
    check(
        '  送出的 style 不是 null',
        !!req?.body?.analysisPackage?.style,
        'style 是 null 的話推薦端會回 422 UNKNOWN_MAKEUP_STYLE。',
    );
    // 物件 {L,a,b} 進、陣列 [L,a,b] 出。這個轉換壞掉的方式是**靜默的**：
    // _labToUpperKeys 拿不到 .L 就回 null，膚色整個消失，沒有任何錯誤訊息。
    check(
        '  膚色 LAB 轉成陣列送出（物件進、陣列出）',
        Array.isArray(fa?.skinTone?.lab) && fa.skinTone.lab.length === 3
            && fa.skinTone.lab.every(v => typeof v === 'number'),
        `實際 ${JSON.stringify(fa?.skinTone?.lab)}，應該是 [72.1, 12.4, 18.9]。`
        + '資料包裡是物件 {L,a,b}（臉部分析端的格式），契約要求送陣列。'
        + '拿到 null 代表 _labToArrayStrict 沒認出輸入格式——膚色就不會送到推薦端，'
        + '所有粉底色號比對被降級，而且不報錯。',
    );
    check(
        '  嘴唇 LAB 也轉成陣列',
        Array.isArray(fa?.lipLab) && fa.lipLab.length === 3,
        `實際 ${JSON.stringify(fa?.lipLab)}。缺了它唇彩就沒辦法比色號。`,
    );
    check(
        '  labReliable 是 true（樣本的 LAB 是合法的）',
        fa?.skinTone?.labReliable === true,
        `實際 ${JSON.stringify(fa?.skinTone?.labReliable)}。`
        + '樣本用的是合法 LAB [72.1, 12.4, 18.9]，這裡變 false 代表 _isUsableLab '
        + '或 _labToArrayStrict 把好資料判成壞的——那會讓所有使用者的色號比對被降級。',
    );
}

function audit(target, label) {
    const spec = ALLOWED[target];
    const req = sent.find(r => r.body && typeof r.body === 'object');
    if (!req) {
        check(`${label}：有送出請求`, false, '一個請求都沒攔到，測試本身沒跑到該路徑。');
        return;
    }
    console.log(`  ${label}`);

    const extraTop = Object.keys(req.body).filter(k => !spec.top.includes(k));
    check(
        `  頂層欄位都在白名單內`,
        extraTop.length === 0,
        `多了 ${JSON.stringify(extraTop)}。白名單是 ${JSON.stringify(spec.top)}。`
        + '要新增請先確認對方真的會讀——送了沒人讀，下一個人會以為它有作用。',
    );

    // 照片絕對不准出現。建議端與推薦端都沒有任何理由需要它。
    check(
        `  沒有夾帶照片`,
        !hasPhoto(req.body),
        '請求裡出現 data:image base64。推薦端沒有大小上限，所以這種洩漏會**成功送出**，'
        + '不會有任何錯誤訊息——照片就這樣離開瀏覽器了。',
    );

    if (spec.pkg) {
        const p = req.body.analysisPackage;
        check(`  有帶 analysisPackage 包裝`, !!p && typeof p === 'object',
            '推薦端只吃包起來的形狀，扁平送會回 422 INVALID_ANALYSIS_PACKAGE。');
        if (p && typeof p === 'object') {
            const extraPkg = Object.keys(p).filter(k => !spec.pkg.includes(k));
            check(
                `  資料包裡的鍵都在白名單內`,
                extraPkg.length === 0,
                `多了 ${JSON.stringify(extraPkg)}。白名單是 ${JSON.stringify(spec.pkg)}。`
                + `本機那包有 ${Object.keys(pkg).length} 個頂層鍵，只有這幾個該離開瀏覽器。`,
            );
            const size = JSON.stringify(p).length;
            check(
                `  資料包大小 ${Math.round(size / 1024)} KB 在 64 KB 以內`,
                size <= MAX_PACKAGE_CHARS,
                `渲染端超過 ${MAX_PACKAGE_CHARS} 字元會回 413 ANALYSIS_PACKAGE_TOO_LARGE，`
                + '而那個錯誤完全不會指向「前端多送了東西」。',
            );
        }
    } else {
        check(
            `  沒有送 analysisPackage`,
            req.body.analysisPackage === undefined,
            '建議端只讀 faceAnalysis。送資料包等於白送，而且它裡面有照片。',
        );
    }
}

// 渲染端這一關檢查的是「Api 層照傳」這件事本身。
//
// Api.renderMakeupAsync 不挑欄位，挑欄位的是 router.js 的 renderPackage。
// 所以這裡故意傳整包進去，確認**照片真的會一路送到請求裡**——這就是
// renderPackage 存在的理由。哪天有人把 renderPackage 拿掉直接傳 Router.analysisPackage，
// 這一關的訊息就是他需要看到的那段話。
function auditRenderPassthrough() {
    const req = sent.find(r => r.body && typeof r.body === 'object');
    if (!req) {
        check('渲染 /render/jobs：有送出請求', false, '一個請求都沒攔到。');
        return;
    }
    console.log('  渲染 /render/jobs（Api 層照傳，挑欄位在 router.js）');
    const extraTop = Object.keys(req.body).filter(k => !ALLOWED.render.top.includes(k));
    check(
        '  頂層欄位都在白名單內',
        extraTop.length === 0,
        `多了 ${JSON.stringify(extraTop)}。白名單是 ${JSON.stringify(ALLOWED.render.top)}。`,
    );
    check(
        '  整包直傳時照片確實會外洩（證明 renderPackage 必須存在）',
        hasPhoto(req.body.analysisPackage),
        'Api 層現在會幫忙挑欄位了？那 router.js 的 renderPackage 與這段註解都要一起更新，'
        + '否則兩邊各挑一次，遲早挑出不一樣的結果。',
    );
    const size = JSON.stringify(req.body.analysisPackage).length;
    check(
        '  整包直傳時大小確實會爆掉 64 KB（證明上限是真的擋得到）',
        size > MAX_PACKAGE_CHARS,
        `整包只有 ${Math.round(size / 1024)} KB，沒有超過上限——`
        + '那這支測試的照片樣本太小了，抓不到真正的外洩，要調大 FAKE_PHOTO。',
    );
}

// ── router.js 那份 renderPackage 的靜態檢查 ──────────────────────────────
// 上面驗的是 Api 層；真正挑欄位的是 router.js，那段不能悄悄長出 images。
{
    const router = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');
    const start = router.indexOf('const renderPackage = {');
    if (start < 0) throw new Error('找不到 renderPackage');
    const body = router.slice(start, router.indexOf('\n    };', start));
    console.log('\n  router.js 的 renderPackage');
    check(
        '  沒有把 images 塞進去',
        !/\bimages\b/.test(body),
        '資料包裡的 images 是使用者的臉部照片 base64。渲染端另有 image 欄位送照片，'
        + '資料包再帶一份等於送兩次，而且一定超過 64 KB 上限。',
    );
    check(
        '  沒有整包展開',
        !/\.\.\.pkg\b/.test(body) && !/\.\.\.Router\.analysisPackage/.test(body),
        '用展開運算子就等於整包送，照片會跟著走。要加欄位請逐一列出來。',
    );
    check(
        '  仍然逐一列出欄位（faceAnalysis / faceJobId / render / generativeText）',
        /faceAnalysis:/.test(body) && /faceJobId:/.test(body)
            && /render:/.test(body) && /generativeText:/.test(body),
        '這四個是渲染端真的會讀的（render/replicate_render_api.py 的 _render_inputs）。',
    );
}
