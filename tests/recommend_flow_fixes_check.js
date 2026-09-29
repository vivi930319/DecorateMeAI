// 2026-09-29 三個使用者回報：
//   1. 粉底「選擇品牌」整塊不見——推薦端沒回 availableTargetBrands；改用這次已回傳的跨品牌結果當選單
//   2. 不收藏妝容圖 → 進推薦商品 → 點商品是空頁——離開守門又問一次，「不要收藏」清空了整個暫存
//   3. 後台「使用者意見回饋」是空的——回應外層名稱不是 items 時會安靜變成 0 則
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = process.argv[2] || path.join(__dirname, '..');
const router = fs.readFileSync(path.join(root, 'js/router.js'), 'utf8');
const api = fs.readFileSync(path.join(root, 'js/api.js'), 'utf8');

let failed = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ` ${detail}`}`); if (!ok) failed += 1; };
const cut = (src, sig) => {
    const i = src.indexOf(sig);
    if (i < 0) throw new Error('找不到 ' + sig);
    let d = 0;
    // 從簽名結尾那個 { 開始數（參數列裡的解構 { 不算）
    for (let k = sig.endsWith('{') ? i + sig.length - 1 : src.indexOf('{', i); k < src.length; k++) {
        if (src[k] === '{') d++;
        else if (src[k] === '}') { d--; if (!d) return src.slice(i, k + 1); }
    }
};

console.log('=== 1. 粉底品牌選單保底 ===');
{
    const sb = { Router: {}, AnalysisDraft: { load: () => null }, console };
    vm.createContext(sb);
    vm.runInContext(cut(router, 'function currentFoundationCrossBrandAlternatives(product = null) {') + '\n'
        + cut(router, 'function currentFoundationAvailableTargetBrands(product = null) {')
        + '\nglobalThis.__brands = currentFoundationAvailableTargetBrands;', sb);
    const alt = (brand, code) => ({ brand, shadeCode: code, product: { id: code } });
    sb.Router.foundationCrossBrandAlternatives = [alt('NARS', 'FOG'), alt('MAYBELLINE', '03'), alt('NARS', 'MONT'), { brand: 'X', product: null }];
    sb.Router.foundationAvailableTargetBrands = [];
    const got = sb.__brands();
    check('後端沒給清單 → 用已回傳的跨品牌品牌（去重、跳過沒有商品的）', JSON.stringify(got) === '["NARS","MAYBELLINE"]', JSON.stringify(got));
    sb.Router.foundationAvailableTargetBrands = ['DIOR', 'NARS'];
    check('後端有清單時以後端為準', JSON.stringify(sb.__brands()) === '["DIOR","NARS"]');
    sb.Router.foundationAvailableTargetBrands = [];
    sb.Router.foundationCrossBrandAlternatives = [];
    check('兩邊都沒有 → 空（整塊不畫，不編造）', sb.__brands().length === 0);
}

console.log('\n=== 2. 推薦視窗點商品不觸發離開守門 ===');
const modal = cut(router, 'function openProductRecommendationModal(){');
check('點商品帶 skipLeaveGuard', /Router\.go\('products',\{productId:card\.dataset\.pid,skipLeaveGuard:true\}\)/.test(modal));
check('「查看所有商品」帶 skipLeaveGuard', /Router\.go\('products',\{skipLeaveGuard:true\}\)/.test(modal));
{
    const guard = cut(router, 'needsLookLeaveGuard(nextPage) {');
    const sb = { hasStartedJourney: () => true };
    vm.createContext(sb);
    vm.runInContext('globalThis.R = {' + guard + '};', sb);
    const R = Object.assign(sb.R, { leaveGuardOpen: false, pendingLookSaved: false, currentPage: 'suggestion', pendingLook: {},
        analysisPackage: { render: { afterImageUrl: 'https://x/after.png' } } });
    check('沒回答過 → 離開妝容建議頁要問', R.needsLookLeaveGuard('dashboard') === true);
    R.lookSaveDeclinedFor = 'https://x/after.png';
    check('已回答「只看商品，不收藏」→ 同一張圖不再問', R.needsLookLeaveGuard('dashboard') === false);
    R.analysisPackage.render.afterImageUrl = 'https://x/another.png';
    check('換了一張新的妝後圖 → 要重新問', R.needsLookLeaveGuard('dashboard') === true);
}

console.log('\n=== 3. 後台意見回饋的回應格式 ===');
{
    const listAdmin = cut(api, 'async listAdmin({ status = \'\', limit = 100 } = {}) {');
    const run = async body => {
        const sb = { URLSearchParams, String, Number, Array, Object, JSON,
            Api: { _fetchWithRelogin: async () => ({ ok: true, status: 200, json: async () => body }) } };
        vm.createContext(sb);
        vm.runInContext('globalThis.U = { base() { return "http://t"; }, ' + listAdmin + '};', sb);
        return sb.U.listAdmin({});
    };
    (async () => {
        const row = { id: 1, message: 'hi', member_email: 'a@b.c', created_at: '2026-09-28T16:49:45Z' };
        const a = await run({ total: 1, items: [row] });
        const b = await run({ feedback: [row] });
        const c = await run([row]);
        const d = await run({ data: [row], count: 1 });
        check('規格格式 { total, items }', a.items.length === 1 && a.total === 1);
        check('{ feedback: [...] }', b.items.length === 1 && b.total === 1);
        check('純陣列', c.items.length === 1);
        check('{ data: [...] }', d.items.length === 1);
        check('snake_case 欄位也對得上（member_email → memberEmail、created_at → createdAt）',
            b.items[0].memberEmail === 'a@b.c' && b.items[0].createdAt === '2026-09-28T16:49:45Z');

        console.log('\n=== 4. 商品詳情可以加入化妝包 ===');
        check('詳情頁有「＋ 加入化妝包」按鈕', /data-own-detail="\$\{escapeHtml\(p\.candidateKey\)\}"/.test(router));
        check('按鈕走 MakeupBag.add', /MakeupBag\.add\(ownDetail\.dataset\.ownDetail\)/.test(router));

        if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
        console.log('\n推薦流程修正測試通過');
    })().catch(e => { console.log('執行失敗', e); process.exit(1); });
}
