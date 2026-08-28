// 每個頁面都要畫得出東西——擋的是「整頁全白」那一類。
//
// 由來（2026-08-29，商品推薦頁整片空白）：
//
//     products(opts) {
//         renderShop(...);                        // 先呼叫
//         const applyShopControls = (list) => {…} // 後宣告
//         function renderShop(filter) {
//             const list = applyShopControls(byCat);   // ← 這裡拋
//         }
//     }
//
// `renderShop` 是函式宣告會提升，所以呼叫得到；但它用到的 `applyShopControls`
// 是 const，還在暫時性死區（TDZ），碰到就拋
// `ReferenceError: Cannot access 'applyShopControls' before initialization`。
//
// 致命的是它**拋在 area.innerHTML 被賦值之前**：那個 div 從頭到尾沒被寫進任何東西，
// 畫面整片全白，連「目前沒有商品資料」的空狀態都不會出現，看起來像後端沒回資料。
// 實際上 API 回 200、1.2 MB、1000+ 件商品。
//
// 現有的守門都擋不住：`node --check` 只看語法（這段語法完全合法）；
// `undefined_names_check.js` 用 eslint `no-undef`，而這裡名字是**存在**的，只是還沒初始化。
// eslint 的 `no-use-before-define` 抓得到，但在這份 codebase 上會報 155 筆，
// 絕大多數是誤報（函式延後執行時先用後宣告是安全的）——那種檢查只會被忽略。
//
// 所以這裡不做靜態分析，直接**把每個頁面方法抓出來跑一次**：
// 未定義的全域用 Proxy 兜底，讓它一路跑到底，看它會不會拋 TDZ、有沒有寫進畫面。
//
// 判定**只認一件事**：拋出 `before initialization` → FAIL。
// TDZ 是語彙層的，Proxy 兜不住也偽造不出來，在這個環境裡出現就是真的會在瀏覽器裡出現。
// 零誤報，所以它叫的時候一定要當真。
//
// 其餘一律只印出來參考，不算失敗：
//   · 其他錯誤（TypeError…）多半是替身沒扮像，不是產品的問題。
//   · 「沒有寫進 innerHTML」**不能**當失敗——實測 analysis()、style()、compare() 都不寫：
//     analysis 的 HTML 本來就在 `pages/analysis.html` 裡，handler 只負責掛事件；
//     compare 沒有分析資料時走 renderAnalysisGate 就提早 return。拿它當紅燈會製造三個
//     長期假警報，而一個會叫但都在亂叫的檢查，比沒有檢查更糟——它會被忽略，
//     然後真的那次也一起被忽略。
//
// 用法：node tests/page_dispatch_tdz_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');

// ── 從 router.js 取出 PageInit 的每個頁面方法 ───────────────────────────────
function matchBrace(text, from) {
    let depth = 0;
    for (let i = text.indexOf('{', from); i < text.length; i++) {
        if (text[i] === '{') depth++;
        else if (text[i] === '}') { depth--; if (depth === 0) return i + 1; }
    }
    return -1;
}

const pageInitAt = src.indexOf('\nconst PageInit = {');
if (pageInitAt < 0) { console.log('找不到 PageInit——router.js 的結構變了，請更新這支檢查'); process.exit(1); }
const pageInitEnd = matchBrace(src, pageInitAt);
const pageInitBody = src.slice(src.indexOf('{', pageInitAt) + 1, pageInitEnd - 1);
const lineOf = (idxInBody) => src.slice(0, pageInitAt).split('\n').length + 1
    + pageInitBody.slice(0, idxInBody).split('\n').length - 1;

const pages = [];
// 頂層方法＝縮排剛好四個空格的 `name(args) {`
const methodRe = /^ {4}([a-zA-Z_$][\w$]*)\s*\(([^)]*)\)\s*\{/gm;
let m;
while ((m = methodRe.exec(pageInitBody)) !== null) {
    const bodyStart = pageInitBody.indexOf('{', m.index + m[0].length - 1);
    const bodyEnd = matchBrace(pageInitBody, m.index + m[0].length - 1);
    if (bodyEnd < 0) continue;
    pages.push({
        name: m[1],
        args: m[2].trim(),
        line: lineOf(m.index),
        body: pageInitBody.slice(bodyStart + 1, bodyEnd - 1)
    });
}

// ── 替身 ───────────────────────────────────────────────────────────────────
// 未定義的名字一律回一個「怎麼用都不會壞」的東西，讓程式一路跑到底。
const anyStub = () => new Proxy(function () {}, {
    get(t, k) {
        if (k === Symbol.toPrimitive) return () => '';
        if (k === Symbol.iterator) return function* () {};
        if (k === 'then' || k === 'catch' || k === 'finally') return undefined;
        return anyStub();
    },
    apply: () => anyStub(),
    construct: () => anyStub(),
    has: () => true
});

function makeElement(store) {
    const el = {
        innerHTML: '', outerHTML: '', textContent: '', value: '', checked: false,
        dataset: {}, style: {}, children: [], parentElement: null,
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        querySelector: () => makeElement(store),
        querySelectorAll: () => [makeElement(store)],
        appendChild(c) { this.children.push(c); return c; },
        insertBefore(c) { this.children.push(c); return c; },
        removeChild() {}, remove() {}, closest: () => null,
        addEventListener() {}, removeEventListener() {}, focus() {}, blur() {}, click() {},
        setAttribute() {}, removeAttribute() {}, getAttribute: () => null,
        hasAttribute: () => false, scrollTo() {}, scrollIntoView() {},
        getBoundingClientRect: () => ({ top: 0, left: 0, width: 100, height: 100, bottom: 0, right: 0 })
    };
    // 寫進去的 HTML 全部記到 store，最後用來判斷「有沒有畫出東西」
    let html = '';
    Object.defineProperty(el, 'innerHTML', {
        get: () => html,
        set: (v) => { html = String(v ?? ''); store.written += html; }
    });
    return el;
}

// 只認訊息，**不要**用 `e instanceof ReferenceError`：錯誤是在 vm context 裡拋的，
// 那裡的 ReferenceError 是另一個 realm 的建構子，instanceof 對主程式的那個永遠是 false。
// 第一版就是這樣寫的，結果對著已知會爆的舊檔案跑出 10/10 PASS——
// 一支永遠不會叫的檢查，比沒有檢查更糟。
const isTdz = (e) => /before initialization/.test(String((e && e.message) || e || ''));

function runPage(page, opts) {
    const store = { written: '' };
    const byId = new Map();
    const getEl = (id) => {
        if (!byId.has(id)) byId.set(id, makeElement(store));
        return byId.get(id);
    };

    // 延後執行的東西同步跑，才驗得到第二段渲染（products 的商品卡就畫在 setTimeout 裡）。
    // 給預算，避免自己排自己造成無限迴圈。
    let budget = 300;
    const runSoon = (fn) => {
        if (typeof fn === 'function' && budget-- > 0) {
            try { fn(); } catch (e) { if (isTdz(e)) throw e; /* 其餘是替身沒扮像 */ }
        }
        return 0;
    };

    const real = {
        console: { log() {}, warn() {}, error() {}, info() {}, debug() {} },
        // 內建物件要放真的。has:()=>true 會把 Math 之類也導向替身，
        // 那樣 Math.min 回替身，slice(0, 替身) 得到空陣列——看起來像沒渲染，
        // 其實是這支檢查自己壞的。
        Math, Number, String, Boolean, Array, Object, JSON, Set, Map, WeakMap, WeakSet,
        Date, RegExp, Promise, Error, TypeError, RangeError, Symbol, Proxy, Reflect,
        isNaN, isFinite, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
        setTimeout: runSoon, requestAnimationFrame: runSoon, queueMicrotask: runSoon,
        setInterval: () => 0, clearTimeout() {}, clearInterval() {}, cancelAnimationFrame() {},
        document: {
            getElementById: getEl,
            querySelector: () => makeElement(store),
            querySelectorAll: () => [makeElement(store)],
            createElement: () => makeElement(store),
            createDocumentFragment: () => makeElement(store),
            body: makeElement(store),
            documentElement: makeElement(store),
            addEventListener() {}, removeEventListener() {}
        },
        location: { hostname: 'decorate-me.web.app', href: 'https://decorate-me.web.app/', protocol: 'https:', hash: '' },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {}, clear() {} },
        sessionStorage: { getItem: () => null, setItem() {}, removeItem() {}, clear() {} }
    };
    real.window = real;
    real.globalThis = real;
    real.self = real;

    // 這幾個是頁面畫圖真的會讀的值，給真的，替身會讓它們靜默走進空清單。
    const products = [
        { id: 'api-lipsticks-1', rawId: 1, cat: '唇彩', apiType: 'lipsticks', name: '測試口紅', brand: 'Za', price: 'NT$350', img: '', score: 0.9 },
        { id: 'api-lipsticks-2', rawId: 2, cat: '唇彩', apiType: 'lipsticks', name: '測試唇釉', brand: 'Za', price: 'NT$420', img: '', score: 0.8 },
        { id: 'api-foundations-3', rawId: 3, cat: '底妝', apiType: 'foundations', name: '測試粉底', brand: 'Kate', price: 'NT$680', img: '', score: 0.7 }
    ];
    real.Router = {
        currentPage: page.name, shopFilter: 'all', shopVisible: 60, shopVisibleFilter: 'all',
        shopBrand: '', shopSort: 'default', shopMinPrice: null, shopMaxPrice: null,
        generalProductCatalog: products, generalProductLoading: false, generalProductError: false,
        productRecommendationLoading: false, productRecommendationError: false,
        analysisPackage: null, selectedStyleId: null,
        go() {}, render() {}
    };

    const sandbox = new Proxy(real, {
        has: () => true,
        get(t, k) {
            if (k in t) return t[k];
            if (k === Symbol.unscopables) return undefined;
            return anyStub();
        },
        set(t, k, v) { t[k] = v; return true; }
    });
    vm.createContext(sandbox);

    let error = null;
    try {
        const wrapped = `(function ${page.name}(${page.args || 'opts'}) {${page.body}\n}).call({}, __opts);`;
        sandbox.__opts = opts;
        vm.runInContext(wrapped, sandbox, { timeout: 10000 });
    } catch (e) {
        error = e;
    }
    return { error, written: store.written };
}

// opts 的幾種形狀，把頁面裡的分支多走幾條（不相干的頁面會忽略它們）。
const OPT_CASES = [
    ['預設', {}],
    ['帶 productId', { productId: 'api-lipsticks-1' }],
    ['帶 category', { category: '唇彩' }]
];

let pass = 0, fail = 0;
const notes = [];
console.log('=== 每個頁面都要畫得出東西（不能因為 TDZ 全白）===\n');

for (const page of pages) {
    let tdzHit = null, wroteAny = false, otherErr = null;
    for (const [label, opts] of OPT_CASES) {
        const { error, written } = runPage(page, opts);
        if (written) wroteAny = true;
        if (error && isTdz(error) && !tdzHit) tdzHit = { label, error };
        if (error && !isTdz(error) && !otherErr) otherErr = { label, error };
    }

    const ok = !tdzHit;
    ok ? pass++ : fail++;
    const why = tdzHit ? `TDZ（${tdzHit.label}）：${tdzHit.error.message}` : '';
    console.log(`  ${ok ? 'PASS' : 'FAIL'} ${page.name}()  router.js:${page.line}${why ? '\n       ' + why : ''}`);
    if (ok && !wroteAny) notes.push(`${page.name}(): 沒有寫進 innerHTML（這頁本來就不靠它渲染，僅供參考）`);
    if (ok && otherErr) notes.push(`${page.name}(): ${otherErr.error.constructor.name}: ${otherErr.error.message}`);
}

if (notes.length) {
    console.log('\n  參考（不算失敗，多半是替身沒扮像，不是產品問題）：');
    for (const n of notes.slice(0, 8)) console.log('    · ' + n);
}

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
