// 在 node 裡載入前端的 js/api.js，攔截 fetch，檢查 recommendProducts 實際送出的 body。
// 目的是驗證 2026-08-23 的修改真的到達了「送出去的那一層」——這個專案踩過兩次
// 「上一層補了、下一層漏掉」的坑（labReliable 一次，browLab 現在一次）。
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const FRONT = process.argv[2];
const src = fs.readFileSync(path.join(FRONT, 'js/api.js'), 'utf8');

let captured = null;
const store = () => {
    const m = new Map();
    return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
             removeItem: k => m.delete(k), clear: () => m.clear() };
};

const sandbox = {
    console,
    window: {},
    document: { createElement: () => ({}), currentScript: null },
    sessionStorage: store(),
    localStorage: store(),
    location: { hostname: 'localhost', protocol: 'http:', href: 'http://localhost:8080/' },
    navigator: { userAgent: 'node' },
    AbortController,
    setTimeout, clearTimeout, setInterval, clearInterval,
    fetch: async (url, opts) => {
        captured = { url: String(url), opts };
        // 回一個結構完整的假回應，讓後續讀取路徑也跑到
        const body = {
            success: true,
            analysisPackage: {
                recommendations: {
                    products: [], primary: [], alternates: [],
                    threshold: 0.8, fallbackReasons: [],
                    skinToneLabReliable: true,   // 故意回 true，測前端會不會盲信
                    personalization: { applied: false, interactionCount: 0, behaviorWeight: 0 },
                    coverage: { requested: 8, returned: 0, skipped: {} }
                }
            },
            products: []
        };
        return { ok: true, status: 200, json: async () => body,
                 headers: { get: () => null } };
    },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
try {
    vm.runInContext(src + '\n;globalThis.__Api = (typeof Api !== "undefined") ? Api : null;', sandbox);
} catch (e) {
    console.log('載入 api.js 失敗:', e.message);
    process.exit(1);
}

const Api = sandbox.__Api;
if (!Api) { console.log('取不到 Api 物件'); process.exit(1); }

// 讓 config 指向一個假的推薦端點
Api.config.services.product.baseUrl = 'http://test.local/product-api';
// _fetchWithRelogin 若存在就讓它直接走 fetch，避免 session 那套邏輯干擾
Api._fetchWithRelogin = (u, o) => sandbox.fetch(u, o);

const pkg = (over = {}) => ({
    id: 'AN-1', schemaVersion: '2026-08-v2',
    faceAnalysis: {
        faceShape: '鵝蛋臉', browShape: '柳葉眉', eyeShape: '杏眼', lipShape: '厚唇',
        skinTone: { season: '秋季', level: '中等', lab: { L: 65.2, a: 8.1, b: 18.4 }, labReliable: true },
        lipLab: { L: 55, a: 25, b: 12 },
        ...over.faceAnalysis
    },
    generativeText: { styleTags: ['luxury', 'soft'], preferredColors: ['champagne'], avoidTags: ['smoky'] },
    ...over.top
});

const body = () => JSON.parse(captured.opts.body);

(async () => {
    let pass = 0, fail = 0;
    const check = (name, cond, detail) => {
        console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
        cond ? pass++ : fail++;
    };

    console.log('\n=== 1. 正常 LAB：應照常送出，labReliable=true ===');
    await Api.recommendProducts(pkg(), 'richGirl');
    let b = body();
    check('schemaVersion 有送出', b.analysisPackage.schemaVersion === '2026-08-v2', b.analysisPackage.schemaVersion);
    check('skinTone.lab 是三元素陣列', JSON.stringify(b.analysisPackage.faceAnalysis.skinTone.lab) === '[65.2,8.1,18.4]',
          JSON.stringify(b.analysisPackage.faceAnalysis.skinTone.lab));
    check('labReliable=true', b.analysisPackage.faceAnalysis.skinTone.labReliable === true);
    check('generativeText.styleTags 有送出',
          JSON.stringify(b.analysisPackage.generativeText.styleTags) === '["luxury","soft"]');
    check('generativeText.preferredColors 有送出',
          JSON.stringify(b.analysisPackage.generativeText.preferredColors) === '["champagne"]');
    check('generativeText.avoidTags 有送出',
          JSON.stringify(b.analysisPackage.generativeText.avoidTags) === '["smoky"]');
    check('limit 預設 12', b.limit === 12, String(b.limit));

    console.log('\n=== 2. P1 防禦：壞掉的 LAB ===');
    for (const [name, lab] of [
        ['字串',   'nope'],
        ['缺一軸', { L: 65.2, a: 8.1 }],
        ['null',   null],
        ['超範圍', { L: 999, a: -999, b: 999 }],
    ]) {
        await Api.recommendProducts(pkg({ faceAnalysis: { skinTone: { season: '秋季', level: '中等', lab, labReliable: true } } }), 'richGirl');
        const bb = body();
        const st = bb.analysisPackage.faceAnalysis.skinTone;
        check(`lab=${name} → 送出 labReliable=false`, st.labReliable === false, `lab=${JSON.stringify(st.lab)}`);
        check(`lab=${name} → 不送出壞座標`, st.lab === null, JSON.stringify(st.lab));
    }

    console.log('\n=== 3. P1 防禦：回應盲信檢查 ===');
    const r = await Api.recommendProducts(
        pkg({ faceAnalysis: { skinTone: { season: '秋季', level: '中等', lab: 'nope', labReliable: true } } }), 'richGirl');
    check('後端回 skinToneLabReliable=true，前端仍判定為 false', r.skinToneLabReliable === false, String(r.skinToneLabReliable));
    check('前端自行補上 SKIN_TONE_LAB_UNRELIABLE',
          r.fallbackReasons.some(x => x.code === 'SKIN_TONE_LAB_UNRELIABLE' && x.source === 'frontend'),
          JSON.stringify(r.fallbackReasons));

    console.log('\n=== 4. browLab ===');
    await Api.recommendProducts(pkg({ faceAnalysis: { browLab: { L: 34, a: 5, b: 8 },
        skinTone: { season: '秋季', level: '中等', lab: { L: 65.2, a: 8.1, b: 18.4 }, labReliable: true } } }), 'richGirl');
    b = body();
    check('有 browLab 時送出三元素陣列',
          JSON.stringify(b.analysisPackage.faceAnalysis.browLab) === '[34,5,8]',
          JSON.stringify(b.analysisPackage.faceAnalysis.browLab));
    await Api.recommendProducts(pkg(), 'richGirl');
    b = body();
    check('沒有 browLab 時不送這個鍵（而非送 null）',
          !('browLab' in b.analysisPackage.faceAnalysis));

    console.log('\n=== 5. recommendationOptions 清洗（後端沒驗，前端自己守）===');
    await Api.recommendProducts(pkg(), 'richGirl', {
        limit: 999,
        recommendationOptions: {
            preferredBrands: Array.from({ length: 30 }, (_, i) => `B${i}`),
            avoidedBrands: ['  ', 'MAC', ''],
            pricePreference: { min: 1200, max: 300, mode: 'cheapest' }
        }
    });
    b = body();
    check('limit 999 夾到 50', b.limit === 50, String(b.limit));
    check('preferredBrands 截斷到 20 筆', b.recommendationOptions.preferredBrands.length === 20,
          String(b.recommendationOptions.preferredBrands.length));
    check('avoidedBrands 濾掉空字串', JSON.stringify(b.recommendationOptions.avoidedBrands) === '["MAC"]',
          JSON.stringify(b.recommendationOptions.avoidedBrands));
    check('min>max 被擺正', b.recommendationOptions.pricePreference.min === 300
          && b.recommendationOptions.pricePreference.max === 1200,
          JSON.stringify(b.recommendationOptions.pricePreference));
    check('非白名單 mode 被丟棄', !('mode' in b.recommendationOptions.pricePreference));

    await Api.recommendProducts(pkg(), 'richGirl', { limit: 0 });
    check('limit 0 夾到 1', body().limit === 1, String(body().limit));
    await Api.recommendProducts(pkg(), 'richGirl', { limit: 12.7 });
    check('limit 12.7 截成 12', body().limit === 12, String(body().limit));

    console.log('\n=== 6. 舊呼叫相容（兩個參數）===');
    await Api.recommendProducts(pkg(), 'richGirl');
    check('不帶 options 時沒有 recommendationOptions 鍵', !('recommendationOptions' in body()));

    console.log('\n=== 7. 錯誤回應保留 code/requestId ===');
    sandbox.fetch = async (url, opts) => {
        captured = { url: String(url), opts };
        return { ok: false, status: 422, headers: { get: () => null },
                 json: async () => ({ error: { code: 'INVALID_ANALYSIS_PACKAGE', message: '缺少臉部分析資料包',
                                               requestId: 'req_abc123', retryable: false } }) };
    };
    Api._fetchWithRelogin = (u, o) => sandbox.fetch(u, o);
    const e = await Api.recommendProducts(pkg(), 'richGirl');
    check('保留 error.code', e.code === 'INVALID_ANALYSIS_PACKAGE', e.code);
    check('保留 requestId', e.requestId === 'req_abc123', e.requestId);
    check('422 不標成可重試', e.retryable === false, String(e.retryable));

    sandbox.fetch = async () => ({ ok: false, status: 502, headers: { get: () => null },
                                   json: async () => ({ error: { code: 'PRODUCT_DB_UNAVAILABLE', requestId: 'req_x' } }) });
    Api._fetchWithRelogin = (u, o) => sandbox.fetch(u, o);
    const e2 = await Api.recommendProducts(pkg(), 'richGirl');
    check('502 標成可重試', e2.retryable === true, String(e2.retryable));

    console.log(`\n${pass}/${pass + fail} passed`);
    process.exit(fail ? 1 : 0);
})();
