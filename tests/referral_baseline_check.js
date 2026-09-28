// 推薦碼正式版＋粉底妝前膚色基準（2026-09-28）。
//
// 這支載入整份 js/api.js 實際跑，不是掃原始碼：
//   1. 有素顏基準時，/recommend-products 的 skinTone 帶 baselineLab；沒有就不帶這個鍵
//   2. foundationMatchStatus 字串／物件都收成 { status }；頂層與 recommendations 都讀；foundationLabSource 要讀到
//   3. 註冊帶推薦碼時才送 referral_code＋client_fingerprint（sha256:<64hex>），不帶碼時兩個都不送
//   4. 推薦碼即時檢查走 Gateway 公開路由 /auth/referral-validate，不走會員代理
//   5. 舊 Demo（email 雜湊當推薦碼、瀏覽器自己加點）已經不存在
// 以及 router.js 的畫面規則：暫定色號不顯示 ΔE00 與百分比、不因 accepted:false 把粉底卡藏起來。
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const FRONT = process.argv[2] || path.join(__dirname, '..');
const apiSrc = fs.readFileSync(path.join(FRONT, 'js/api.js'), 'utf8');
const routerSrc = fs.readFileSync(path.join(FRONT, 'js/router.js'), 'utf8');

let failures = 0;
const check = (name, ok, detail = '') => {
    console.log(`  ${ok ? 'PASS' : 'FAIL'} ${name}${ok || !detail ? '' : `\n       ${detail}`}`);
    if (!ok) failures++;
};
const stripComments = src => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/[^\n]*/g, '$1');

const store = () => {
    const m = new Map();
    return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
             removeItem: k => m.delete(k), clear: () => m.clear() };
};

const calls = [];
let nextResponse = null;
const sandbox = {
    console, window: {}, document: { createElement: () => ({}), currentScript: null },
    sessionStorage: store(), localStorage: store(),
    location: { hostname: 'localhost', protocol: 'http:', href: 'http://localhost:8080/', origin: 'http://localhost:8080', search: '' },
    navigator: { userAgent: 'node', language: 'zh-TW' },
    screen: { width: 390, height: 844, colorDepth: 24 },
    crypto: globalThis.crypto, TextEncoder, Intl, URLSearchParams,
    AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
    fetch: async (url, opts = {}) => {
        calls.push({ url: String(url), opts });
        const r = nextResponse || { status: 200, body: {} };
        return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body, headers: { get: () => null } };
    },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(apiSrc + `
;globalThis.__x = {
  Api, Auth,
  Referral: typeof Referral !== 'undefined' ? Referral : null,
  SkinBaseline: typeof SkinBaseline !== 'undefined' ? SkinBaseline : null,
  ShareEvents: typeof ShareEvents !== 'undefined' ? ShareEvents : null,
};`, sandbox);
const { Api, Auth, Referral, SkinBaseline, ShareEvents } = sandbox.__x;
Api.config.services.product.baseUrl = 'http://test.local/product-api';
Api.config.services.memberDatabase.baseUrl = 'http://test.local/member-database';
Api.config.services.aiGateway.baseUrl = 'http://test.local';
Api._fetchWithRelogin = (u, o) => sandbox.fetch(u, o);
Auth.getProfile = () => ({ email: 'Member@Test.io' });

const pkg = {
    id: 'AN-1', schemaVersion: '2026-08-v2',
    // 分析結果裡的 LAB 是物件（AnalysisPackage.fromRawFaceAnalysis 的格式）
    faceAnalysis: { faceShape: '鵝蛋臉', skinTone: { season: '秋季', level: '中等', lab: { L: 65.2, a: 8.1, b: 18.4 }, labReliable: true } },
};
const lastBody = () => JSON.parse(calls[calls.length - 1].opts.body);

(async () => {
    console.log('\n=== 1. 妝前膚色基準 → baselineLab ===');
    check('SkinBaseline／Referral／ShareEvents 都存在', !!(SkinBaseline && Referral && ShareEvents));

    nextResponse = { status: 404, body: {} };
    await SkinBaseline.load(true);
    nextResponse = { status: 200, body: { analysisPackage: { recommendations: { products: [] } } } };
    await Api.recommendProducts(pkg, 'hongKong');
    const noBase = lastBody().analysisPackage.faceAnalysis.skinTone;
    check('沒有基準時不帶 baselineLab 這個鍵', !('baselineLab' in noBase), JSON.stringify(noBase));
    check('lab 仍是這次照片的值', JSON.stringify(noBase.lab) === '[65.2,8.1,18.4]');

    nextResponse = { status: 200, body: { lab: [79.697576, 5.577632, 16.616094] } };
    await SkinBaseline.load(true);
    check('GET 用小寫 email 路徑', /\/api\/members\/member%40test\.io\/skin-baseline$/.test(calls[calls.length - 1].url),
        calls[calls.length - 1].url);
    nextResponse = { status: 200, body: { analysisPackage: { recommendations: { products: [] } } } };
    await Api.recommendProducts(pkg, 'hongKong');
    const withBase = lastBody().analysisPackage.faceAnalysis.skinTone;
    check('有基準時帶 baselineLab', JSON.stringify(withBase.baselineLab) === '[79.697576,5.577632,16.616094]', JSON.stringify(withBase));
    check('baselineLab 不取代 lab', JSON.stringify(withBase.lab) === '[65.2,8.1,18.4]');

    // 換帳號：不能把上一個人的基準送出去
    Auth.getProfile = () => ({ email: 'other@test.io' });
    await Api.recommendProducts(pkg, 'hongKong');
    check('換帳號後不帶上一個人的基準', !('baselineLab' in lastBody().analysisPackage.faceAnalysis.skinTone));
    Auth.getProfile = () => ({ email: 'Member@Test.io' });

    // 已有基準時分析完成不覆蓋
    const before = calls.length;
    const cap = await SkinBaseline.captureFromAnalysis({ skinTone: { lab: [50, 10, 10], labReliable: true } });
    check('已有基準時分析完成不覆蓋', !cap.created && !calls.slice(before).some(c => c.opts.method === 'PUT'));

    // 沒有基準＋可信 LAB → PUT；不可信 → 不 PUT
    Auth.getProfile = () => ({ email: 'fresh@test.io' });
    nextResponse = { status: 404, body: {} };
    const bad = await SkinBaseline.captureFromAnalysis({ skinTone: { lab: [50, 10, 10], labReliable: false } });
    check('LAB 不可信時不建立基準', !bad.created && !calls.some(c => c.opts.method === 'PUT'));
    const seq = [{ status: 404, body: {} }, { status: 200, body: { ok: true } }];
    const realFetch = sandbox.fetch;
    sandbox.fetch = async (u, o) => { nextResponse = seq.shift() || { status: 200, body: {} }; return realFetch(u, o); };
    // 分析結果是物件格式，送出去要轉成規格書的陣列
    const made = await SkinBaseline.captureFromAnalysis({ skinTone: { lab: { L: 61.5, a: 9.2, b: 17.1 }, labReliable: true } });
    sandbox.fetch = realFetch;
    const put = calls.filter(c => c.opts.method === 'PUT').pop();
    check('沒有基準時建立（PUT {lab:[…]}）', made.created && put && put.opts.body === '{"lab":[61.5,9.2,17.1]}', put && put.opts.body);
    Auth.getProfile = () => ({ email: 'Member@Test.io' });

    // 訪客不讀不寫
    Auth.getProfile = () => ({ email: 'guest' });
    const guestCalls = calls.length;
    await SkinBaseline.load(true);
    check('訪客不打基準 API', calls.length === guestCalls);
    Auth.getProfile = () => ({ email: 'Member@Test.io' });

    console.log('\n=== 1b. 多張素顏取中位數 ===');
    // 伺服器還不支援 readings：清單存這台裝置，只送中位數 {lab}
    Auth.getProfile = () => ({ email: 'multi@test.io' });
    const seqM = [{ status: 404, body: {} }];
    const fetchM = sandbox.fetch;
    sandbox.fetch = async (u, o) => { nextResponse = seqM.shift() || { status: 200, body: {} }; return fetchM(u, o); };
    const c1 = await SkinBaseline.captureFromAnalysis({ skinTone: { lab: { L: 60, a: 10, b: 15 }, labReliable: true } }, 'AN-A');
    check('第一筆自動建立', c1.created && SkinBaseline.count() === 1);
    const putsBefore = calls.filter(c => c.opts.method === 'PUT').length;
    const c2 = await SkinBaseline.captureFromAnalysis({ skinTone: { lab: { L: 70, a: 12, b: 20 }, labReliable: true } }, 'AN-B');
    check('第二次分析不自動加入，只回 canAdd 讓畫面問「是素顏嗎」',
        !c2.created && c2.canAdd === true && calls.filter(c => c.opts.method === 'PUT').length === putsBefore);
    const r2 = await SkinBaseline.addReading({ L: 70, a: 12, b: 20 }, 'AN-B');
    const r3 = await SkinBaseline.addReading([64, 30, 16], 'AN-C');
    const lastPut = JSON.parse(calls.filter(c => c.opts.method === 'PUT').pop().opts.body);
    check('三筆取各軸中位數', r3.ok && r3.count === 3 && JSON.stringify(lastPut.lab) === '[64,12,16]', JSON.stringify(lastPut));
    check('伺服器不支援清單時只送 {lab}', !('readings' in lastPut));
    check('清單存在這台裝置', JSON.parse(sandbox.localStorage.getItem('beautySkinReadings:multi@test.io')).length === 3);
    check('推薦用的是中位數', JSON.stringify(SkinBaseline.current()) === '[64,12,16]');
    const dup = await SkinBaseline.addReading({ L: 99, a: 0, b: 0 }, 'AN-C');
    check('同一次分析不重複加入', dup.duplicate === true && SkinBaseline.count() === 3);
    const c4 = await SkinBaseline.captureFromAnalysis({ skinTone: { lab: { L: 64, a: 30, b: 16 }, labReliable: true } }, 'AN-C');
    check('已加入過的那次分析不再詢問', c4.canAdd === false);
    for (const [i, L] of [61, 62, 63].entries()) await SkinBaseline.addReading([L, 11, 17], `AN-X${i}`);
    check('最多保留 5 筆（最舊的丟掉）', SkinBaseline.count() === 5
        && !SkinBaseline._cache.readings.some(r => r.analysisId === 'AN-A'));
    sandbox.fetch = fetchM;

    // 伺服器支援 readings：整份清單送上去
    Auth.getProfile = () => ({ email: 'srv@test.io' });
    nextResponse = { status: 200, body: { lab: [60, 10, 15], readings: [{ lab: [60, 10, 15], at: 't0' }] } };
    await SkinBaseline.load(true);
    nextResponse = { status: 200, body: {} };
    await SkinBaseline.addReading([62, 11, 16], 'AN-S');
    const srvPut = JSON.parse(calls.filter(c => c.opts.method === 'PUT').pop().opts.body);
    check('伺服器有 readings 時整份清單一起送', Array.isArray(srvPut.readings) && srvPut.readings.length === 2
        && JSON.stringify(srvPut.lab) === '[61,10.5,15.5]', JSON.stringify(srvPut));
    Auth.getProfile = () => ({ email: 'Member@Test.io' });

    console.log('\n=== 2. 粉底狀態與比色來源 ===');
    nextResponse = { status: 200, body: {
        foundationMatchStatus: 'baseline_fallback', foundationLabSource: 'current_analysis',
        analysisPackage: { recommendations: { products: [] } },
    } };
    let rec = await Api.recommendProducts(pkg, 'hongKong');
    check('頂層字串狀態 → { status }', rec.foundationMatchStatus && rec.foundationMatchStatus.status === 'baseline_fallback',
        JSON.stringify(rec.foundationMatchStatus));
    check('頂層 foundationLabSource 讀得到', rec.foundationLabSource === 'current_analysis');
    nextResponse = { status: 200, body: { analysisPackage: { recommendations: {
        products: [], foundationMatchStatus: { status: 'closest_available', rawSkinDeltaE: 2.7 },
        foundationLabSource: 'before_makeup_baseline',
    } } } };
    rec = await Api.recommendProducts(pkg, 'hongKong');
    check('recommendations 裡的物件狀態原樣保留', rec.foundationMatchStatus.rawSkinDeltaE === 2.7);
    check('recommendations 裡的 foundationLabSource 讀得到', rec.foundationLabSource === 'before_makeup_baseline');
    const prod = Api._normalizeProduct({ id: 7, type: 'foundations', name: 'X', foundationMatchStatus: 'matched' });
    check('商品層的字串狀態也轉成物件', prod.foundationMatchStatus && prod.foundationMatchStatus.status === 'matched');

    console.log('\n=== 3. 註冊帶推薦碼 ===');
    const regBody = () => JSON.parse(calls.filter(c => /\/auth\/register$/.test(c.url)).pop().opts.body);
    nextResponse = { status: 202, body: { otpSent: true, referral: { applied: true } } };
    const reg = await Api.register({ name: 'A', phone: '0912', email: 'n@t.io', password: 'x', age: 20, referralCode: 'K7P3XM' });
    const b1 = regBody();
    check('送出 referral_code', b1.referral_code === 'K7P3XM');
    check('送出 client_fingerprint（sha256:<64hex>）', /^sha256:[0-9a-f]{64}$/.test(b1.client_fingerprint || ''), b1.client_fingerprint);
    check('回應的 referral 原樣交回給畫面', reg.referral && reg.referral.applied === true);
    const fp2 = await Referral.fingerprint();
    check('同一台裝置指紋穩定', fp2 === b1.client_fingerprint);
    await Api.register({ name: 'A', phone: '0912', email: 'n2@t.io', password: 'x', age: 20, referralCode: '' });
    const b2 = regBody();
    check('沒填推薦碼就兩個欄位都不送', !('referral_code' in b2) && !('client_fingerprint' in b2), JSON.stringify(b2));
    check('推薦碼正規化（去空白、轉大寫、只留英數）', Referral.normalizeCode(' k7p-3xm ') === 'K7P3XM');
    check('reason 有中文說明', /不存在/.test(Referral.reasonText('INVALID_CODE')) && /自己/.test(Referral.reasonText('SELF_REFERRAL')));

    console.log('\n=== 4. 推薦碼即時檢查 ===');
    nextResponse = { status: 200, body: { valid: true } };
    const v = await Referral.validate('k7p3xm');
    const vc = calls[calls.length - 1];
    check('走 Gateway 公開路由 /auth/referral-validate', vc.url === 'http://test.local/auth/referral-validate?code=K7P3XM', vc.url);
    check('valid:true 讀得到', v.ok && v.valid === true);
    nextResponse = { status: 429, body: {} };
    check('429 回報 rateLimited（不是「無效」）', (await Referral.validate('ABC')).rateLimited === true);
    const n = calls.length;
    await Referral.validate('  ');
    check('空白碼不打 API', calls.length === n);

    console.log('\n=== 5. 舊 Demo 已移除 ===');
    const apiCode = stripComments(apiSrc);
    check('沒有 myCode／applyReferral／countReferrals', !/myCode\s*\(|applyReferral\s*\(|countReferrals\s*\(/.test(apiCode));
    check('沒有 beautyReferralUsed 本機記帳', !/beautyReferralUsed/.test(apiCode));
    const routerCode = stripComments(routerSrc);
    check('router 不再呼叫 Demo 函式', !/Referral\.(myCode|applyReferral|countReferrals|_rewardPoints)/.test(routerCode));

    console.log('\n=== 6. 分享任務回報 ===');
    nextResponse = { status: 200, body: { pointsAwarded: 5 } };
    const s1 = await ShareEvents.record('ig_story', 'hongKong');
    const sc = calls[calls.length - 1];
    check('POST /api/members/{email}/share-events', sc.opts.method === 'POST' && /\/api\/members\/member%40test\.io\/share-events$/.test(sc.url), sc.url);
    check('只送 platform 與 styleId', sc.opts.body === '{"platform":"ig_story","styleId":"hongKong"}', sc.opts.body);
    check('回應的 pointsAwarded 讀得到', s1.pointsAwarded === 5);
    const m = calls.length;
    await ShareEvents.record('facebook');
    check('不認得的平台不送', calls.length === m);
    Auth.getProfile = () => ({ email: 'guest' });
    await ShareEvents.record('threads');
    check('訪客不送', calls.length === m);
    Auth.getProfile = () => ({ email: 'Member@Test.io' });
    const shareSrc = stripComments(fs.readFileSync(path.join(FRONT, 'js/look-share.js'), 'utf8'));
    check('分享卡四個出口都有回報', ['ig_story', 'threads', 'download'].every(k => shareSrc.includes(`'${k}'`))
        && /reportShare\(format === 'story' \? 'ig_story' : 'ig_post'\)/.test(shareSrc));
    check('取消分享（AbortError）不回報：回報在 await share() 之後、catch 之前',
        /else await navigator\.share\([\s\S]{0,80}?\);\s*reportShare\(/.test(shareSrc));

    console.log('\n=== 7. 粉底畫面規則（router.js） ===');
    const cut = (sig) => {
        const i = routerSrc.indexOf(sig);
        if (i < 0) throw new Error('找不到 ' + sig);
        let d = 0;
        for (let k = routerSrc.indexOf('{', i); k < routerSrc.length; k++) {
            if (routerSrc[k] === '{') d++;
            else if (routerSrc[k] === '}') { d--; if (!d) return routerSrc.slice(i, k + 1); }
        }
    };
    const ui = { escapeHtml: s => String(s), Router: {}, Api, SkinBaseline: undefined, isGuest: () => false, console };
    vm.createContext(ui);
    vm.runInContext([
        'function currentFoundationMatchStatus(product = null) {', 'function foundationStatusMessage(status) {',
        'function foundationStatusRawDeltaE(status) {', 'function foundationIsProvisional(product = null) {',
        'function currentFoundationLabSource() {', 'function foundationLabSourceLine() {',
        'function canCreateBaselineFromCurrent() {', 'function foundationStatusHtml(product = null) {',
    ].map(cut).join('\n') + '\nglobalThis.__html = foundationStatusHtml;', ui);
    const html = (status, src) => { ui.Router.foundationMatchStatus = status; ui.Router.foundationLabSource = src || null; return ui.__html(null); };
    const fb = html({ status: 'baseline_fallback', rawSkinDeltaE: 3.1 });
    check('baseline_fallback 標「暫定色號」', /暫定色號/.test(fb));
    check('baseline_fallback 提示建立素顏基準', /素顏基準/.test(fb));
    check('baseline_fallback 不顯示 ΔE00 或百分比', !/ΔE|%|3\.1/.test(fb), fb);
    const ca = html({ status: 'closest_available', rawSkinDeltaE: 2.73 }, 'before_makeup_baseline');
    check('closest_available 顯示「目前最接近」與實際 ΔE00', /目前最接近/.test(ca) && /ΔE00 2\.73/.test(ca));
    check('closest_available 不宣稱精準匹配', /不是精準匹配/.test(ca) && !/最適合你/.test(ca));
    check('比色依據：妝前基準', /妝前素顏膚色基準/.test(ca));
    check('matched 顯示比色依據', /這次照片的膚色/.test(html({ status: 'matched' }, 'current_analysis')));

    const panel = cut('function recommendationPanelHtml(p) {');
    check('推薦面板在暫定色號時不算百分比', /hasPct = Number\.isFinite\(pct\) && !provisional/.test(panel));
    check('推薦卡在暫定色號時不印百分比', /matchPercent != null && !provisional/.test(cut('function recommendationCardHtml(p) {')));
    check('色差入口在暫定色號時關閉', /foundationIsProvisional\(p\)\) return null/.test(cut('function colorDiffInfo(p) {')));

    // 規格書：不論哪種狀態，有合格候選就要畫粉底卡；不得因 foundationSkinMatch.accepted === false 隱藏
    const allCode = ['js/router.js', 'js/makeup-flow.js', 'js/makeup-plan.js']
        .map(f => stripComments(fs.readFileSync(path.join(FRONT, f), 'utf8'))).join('\n');
    check('沒有用 foundationSkinMatch.accepted 過濾或隱藏卡片',
        !/foundationSkinMatch\??\.accepted/.test(allCode));

    console.log(failures ? `\n${failures} 項失敗` : '\n全部通過');
    process.exit(failures ? 1 : 0);
})().catch(e => { console.log('執行失敗:', e && e.stack || e); process.exit(1); });
