// 後台把商品全部下架之後，商品頁要說「目前沒有商品資料」，不能一直說「商品載入中」。
//
// 由來（2026-08-29，使用者回報「商品從後台被刪掉後會顯示商品載入中，會讓我誤會沒載入」）：
//
// 判斷「要不要載入商品清單」的守衛，五個呼叫端全都寫成看 `.length`：
//
//     if (!apiCatalog.length && !Router.generalProductLoading) loadGeneralProductCatalog(...)
//
// 而 loadGeneralProductCatalog 自己的 early return 也是看 `.length`。於是空清單
// 被當成「還沒載過」：抓完 → 得到 []　→ 重畫 → 守衛又成立 → 再抓一次，無限循環。
// 每一輪都會把 generalProductLoading 設成 true，所以畫面永遠停在「商品載入中」，
// 而那支商品 API 正在被無限重打——使用者只看到轉圈，看不到那一整排請求。
//
// 修法是把 `null`（沒載過／被主動清掉要求重抓）跟 `[]`（載過，就是空的）分開，
// 統一由 productCatalogLoaded() 判斷。
//
// 用法：node tests/product_catalog_empty_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');

function matchBrace(text, from) {
    let depth = 0;
    for (let i = text.indexOf('{', from); i < text.length; i++) {
        if (text[i] === '{') depth++;
        else if (text[i] === '}') { depth--; if (depth === 0) return i + 1; }
    }
    return -1;
}
function cutBlock(sig) {
    const i = src.indexOf(sig);
    if (i < 0) throw new Error('找不到 ' + sig);
    return src.slice(i, matchBrace(src, i));
}

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};

console.log('=== 商品被清空後不能顯示成「載入中」===\n');

// ── 1. productCatalogLoaded 本身 ───────────────────────────────────────────
const loadedFn = cutBlock('function productCatalogLoaded()');
const box = { Router: { generalProductCatalog: null } };
vm.createContext(box);
vm.runInContext(loadedFn + ';globalThis.__f = productCatalogLoaded;', box);
const loaded = box.__f;

box.Router.generalProductCatalog = null;
check('null 代表還沒載過', loaded() === false);
box.Router.generalProductCatalog = [];
check('空陣列代表載過了（只是沒有商品）', loaded() === true);
box.Router.generalProductCatalog = [{ id: 1 }];
check('有商品當然算載過', loaded() === true);

// ── 2. 實際跑 products()，清單載過但是空的 ─────────────────────────────────
const pageInitAt = src.indexOf('\nconst PageInit = {');
const pageInitBody = src.slice(src.indexOf('{', pageInitAt) + 1, matchBrace(src, pageInitAt) - 1);
const m = /^ {4}products\s*\(([^)]*)\)\s*\{/m.exec(pageInitBody);
if (!m) { console.log('找不到 PageInit.products'); process.exit(1); }
const bodyStart = pageInitBody.indexOf('{', m.index + m[0].length - 1);
const productsBody = pageInitBody.slice(bodyStart + 1, matchBrace(pageInitBody, m.index + m[0].length - 1) - 1);

const anyStub = () => new Proxy(function () {}, {
    get(t, k) {
        if (k === Symbol.toPrimitive) return () => '';
        if (k === Symbol.iterator) return function* () {};
        if (k === 'then' || k === 'catch' || k === 'finally') return undefined;
        return anyStub();
    },
    apply: () => anyStub(),
    construct: () => anyStub()
});

let written = '';
const el = {
    querySelectorAll: () => [], querySelector: () => null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false }
};
Object.defineProperty(el, 'innerHTML', { get: () => written, set: (v) => { written = String(v ?? ''); } });

let loadCalls = 0;
const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    Math, Number, String, Boolean, Array, Object, JSON, Set, Map, Date, RegExp,
    Promise, Error, Symbol, isNaN, parseInt, parseFloat,
    setTimeout: (fn) => { try { fn(); } catch (_) {} return 0; },
    document: { getElementById: () => el, createElement: () => el },
    CATEGORIES: [{ id: '唇彩' }, { id: '底妝' }],
    CAT_EN: { '唇彩': 'LIP COLOR', '底妝': 'FOUNDATION' },
    SHOP_PAGE_SIZE: 60, SHOP_ANIMATE_LIMIT: 12, RECOMMENDED_DISPLAY_LIMIT: 8,
    escapeHtml: (s) => String(s ?? ''),
    // ⚠️ 這裡**不要**自己寫一份 productCatalogLoaded。第一版寫了
    //    `() => Array.isArray(...)`，於是 products() 用的是測試自己的判斷，
    //    產品程式碼那一支根本沒被執行——把它改回 .length 注入回歸，
    //    下面三項照樣全 PASS。真正的那一支在 createContext 之後才注入（見下方）。
    loadGeneralProductCatalog: (onDone) => { loadCalls++; if (typeof onDone === 'function') onDone(); },
    Router: {
        currentPage: 'products', shopFilter: 'all', shopVisible: 60, shopVisibleFilter: 'all',
        shopBrand: '', shopSort: 'default', shopMinPrice: null, shopMaxPrice: null, shopQuery: '',
        // 後台把商品全刪光的狀態：載過了，結果是空的
        generalProductCatalog: [],
        generalProductLoading: false,
        generalProductError: false,
        productRecommendationLoading: false,
        analysisPackage: null
    }
};
sandbox.window = sandbox;
const ctx = new Proxy(sandbox, {
    has: () => true,
    get(t, k) { return (k in t) ? t[k] : (k === Symbol.unscopables ? undefined : anyStub()); },
    set(t, k, v) { t[k] = v; return true; }
});
vm.createContext(ctx);
// 把 router.js 裡真正的 productCatalogLoaded 放進來，products() 才是照產品程式碼在判斷。
vm.runInContext(loadedFn, ctx);

let err = null;
try {
    ctx.__opts = {};
    vm.runInContext(`(function products(opts) {${productsBody}\n}).call({}, __opts);`, ctx, { timeout: 10000 });
} catch (e) { err = e; }

check('沒有拋錯', !err, err ? `${err.constructor.name}: ${err.message}` : '');
check('說「目前沒有商品資料」', written.includes('目前沒有商品資料'),
    written.includes('商品載入中') ? '← 目前說的是「商品載入中」' : '');
check('不能說「商品載入中」', !written.includes('商品載入中'));
// 清單已經載過了，不該再要求載一次——那正是無限重打 API 的起點
check('不再重複要求載入', loadCalls === 0, loadCalls ? `被呼叫了 ${loadCalls} 次` : '');

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
