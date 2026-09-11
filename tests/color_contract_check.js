// 色彩驗證契約的驗收清單（《前端必接：色彩驗證欄位、色盤商品、圖片不符與三色階現況》
// 2026-09-11）。
//
// 這一份守的是「不可以顯示什麼」多過「要顯示什麼」，理由跟 color_diff_qa_check 一樣：
// 上架 3,981 筆商品裡有 3,313 筆**有 hex 但沒通過官方數值驗證**。照舊邏輯（hex 一有值
// 就畫色塊、標色碼）會把爬來的估計值畫成看起來權威的官方色號，而使用者會抄下那個色碼
// 去店裡對色。唯一的判斷依據是 colorMatchReady，具體訊號是 lab === null。
//
// 用法：node tests/color_contract_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');
const apiSrc = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');

const cut = (sig) => {
    const i = src.indexOf(sig);
    if (i < 0) throw new Error('找不到 ' + sig);
    let d = 0;
    for (let k = src.indexOf('{', i); k < src.length; k++) {
        if (src[k] === '{') d++;
        else if (src[k] === '}') { d--; if (!d) return src.slice(i, k + 1); }
    }
};

const sandbox = { escapeHtml: (s) => String(s ?? ''), console };
vm.createContext(sandbox);
vm.runInContext(
    cut('function colorContract(p) {') + '\n'
    + cut('function productSwatchHtml(p) {') + '\n'
    + cut('function productColorWarningHtml(p) {') + '\n'
    + cut('function productImageState(p) {') + '\n'
    + cut('function isFoundationProduct(p) {') + '\n'
    + 'globalThis.__c = colorContract;'
    + 'globalThis.__sw = productSwatchHtml;'
    + 'globalThis.__warn = productColorWarningHtml;'
    + 'globalThis.__img = productImageState;', sandbox);

const c = sandbox.__c;
const sw = sandbox.__sw;
const warn = sandbox.__warn;
const img = sandbox.__img;

let pass = 0, fail = 0;
const check = (name, cond, extra = '') => {
    console.log(`  ${cond ? 'PASS' : 'FAIL'} ${name}${cond ? '' : '  ' + extra}`);
    cond ? pass++ : fail++;
};

console.log('');
console.log('=== 1. colorMatchReady 是唯一依據，hex 有值不算 ===');
// 商品 1114（MAC 粉底 N12）的實際回應：hex 有值、lab 是 null、colorMatchReady false。
const unverified = { hex: '#c2a386', lab: null, colorMatchReady: false, colorEstimated: true,
                     colorRepresentation: 'single',
                     colorWarning: '色彩尚未完成官方數值驗證；不可視為實體試色結果。' };
check('未驗證 → ready 為 false', c(unverified).ready === false);
check('未驗證 → 色塊仍然畫出來（僅示意）', sw(unverified).includes('#c2a386'));
// 缺欄位一律視為不可比色。舊版商品服務沒有這些欄位，預設 true 會讓那些商品
// 全部被當成已驗證——寧可少標示，不要誤標。
check('完全沒有這些欄位 → 也是 false', c({ hex: '#abcdef' }).ready === false);
check('色塊要標 muted，文案才知道不能寫官方色號',
    sw(unverified).includes('sw-muted'));
check('已驗證 → 不標 muted',
    !sw({ hex: '#c2a386', colorMatchReady: true, colorRepresentation: 'single' }).includes('sw-muted'));

console.log('');
console.log('=== 2. 透明商品不可畫出一塊白色 ===');
// 畫了會變成一塊白色，而白色是一個看起來很具體的顏色。
const transparent = { colorRepresentation: 'transparent', hex: '#ffffff', colorMatchReady: false };
check('不出現色塊', !sw(transparent).includes('sw-single'));
check('改成文字說明', sw(transparent).includes('透明'));

console.log('');
console.log('=== 3. 合成色被退回 → 不顯示任何顏色 ===');
// rejected_synthetic 的 hex 是合成出來的，不是官方值，連示意都不該給。
const rejected = { colorVerificationStatus: 'rejected_synthetic', hex: '#123456',
                   colorRepresentation: 'single', colorMatchReady: false };
check('完全不畫色塊', sw(rejected) === '');

console.log('');
console.log('=== 4. 多色盤：官方有幾格就畫幾格 ===');
// CHANEL 四色眼影 202 的實際回應：hex 是 null，四格色值全是 null。
const palette = {
    colorRepresentation: 'palette', hex: null, colorMatchReady: false, paletteComplete: false,
    colorWarning: '色盤尚有格子未取得官方色值。',
    paletteColors: [
        { position: 1, name: '閃閃發光的柔白色調', hex: null, lab: null, role: 'eyeshadow' },
        { position: 2, name: '第二格', hex: '#d8c4b0', lab: [80, 4, 12], role: 'eyeshadow' },
        { position: 3, name: '第三格', hex: null, lab: null, role: 'eyeshadow' },
        { position: 4, name: '第四格', hex: null, lab: null, role: 'eyeshadow' },
    ],
};
const palOut = sw(palette);
// 數 data-pos 而不是 class：`sw-cell-pending` 這個類名裡含有 `sw-cell` 子字串，
// 拿 class 去數會把每個待核對的格子算成兩格（四格會數成七格）。
const cellCount = palOut.split('data-pos=').length - 1;
check('畫出四格', cellCount === 4, `實際 ${cellCount} 格`);
check('格號對回官方 position', palOut.includes('data-pos="4"'));
check('不用單一色塊代表整盤', !palOut.includes('sw-single'));
// 留空白會被當成載入失敗，補預設色則是憑空發明一個官方沒公布的顏色。
check('缺色的格子顯示「待官方核對」', palOut.includes('待官方核對'));
check('有色值的格子照樣上色', palOut.includes('#d8c4b0'));
check('paletteComplete 為 false 時如實回報', c(palette).paletteComplete === false);

console.log('');
console.log('=== 5. 警語直接印後端的，不自己拼 ===');
// 後端 2026-09-11 起依情境回不同文案：透明與完整色盤回 null，所以直接印就對。
check('未驗證 → 印出後端文案', warn(unverified).includes('尚未完成官方數值驗證'));
check('沒有警語 → 不產生空節點', warn({ colorMatchReady: true, colorWarning: null }) === '');
check('透明商品後端回 null → 不印警語', warn({ colorRepresentation: 'transparent' }) === '');

console.log('');
console.log('=== 6. 圖片：空字串比 null 危險 ===');
// `<img src="">` 會讓瀏覽器重新載入當前頁。後端回的是空字串，不是 null。
const mismatch = { imageIdentityStatus: 'mismatch', imageUrl: '', img: '',
                   imageWarning: '圖片所屬色號不符，待官方圖片核對。',
                   paletteImageUrl: 'https://www.chanel.com/x.jpg' };
check('mismatch → src 不得有值', img(mismatch).src === '');
check('mismatch → 帶出後端警語', img(mismatch).warning.includes('色號不符'));
check('mismatch → 有官方色票圖可當備援', img(mismatch).fallback.includes('chanel'));
// not_revalidated 是**正常情況**（尚未重新核對），不可因此隱藏商品或換掉圖。
const normal = { imageIdentityStatus: 'not_revalidated', img: 'https://sdcdn.io/a.png' };
check('not_revalidated → 照常顯示原圖', img(normal).src.includes('sdcdn.io'));
check('not_revalidated → 不算 mismatch', img(normal).mismatch === false);
// 商品真的沒有圖時也要回空字串，不能讓 undefined 流進 src。
check('完全沒有圖 → src 是空字串不是 undefined', img({}).src === '');

console.log('');
console.log('=== 7. 色差與膚色文案受閘門控制 ===');
// 這兩條量的是原始碼接線，因為 colorDiffInfo 與 recommendationPanelHtml 的
// 依賴太多，單獨抽出來跑不起來；而「有沒有接上閘門」正是會被未來的重構弄掉的東西。
check('colorDiffInfo 接上 colorContract 閘門',
    /function colorDiffInfo[\s\S]{0,900}?colorContract\(p\)\.ready/.test(src));
check('膚色文案接上閘門',
    /colorClaimAllowed\s*=\s*colorContract\(p\)\.ready/.test(src));
check('reasonTexts 也濾掉色差句',
    /colorClaimAllowed \|\| !\/色差\|膚色相近/.test(src));

console.log('');
console.log('=== 8. 三色階為 null 是降級不是錯誤 ===');
check('粉底顯示降級提示',
    /shade-rec-empty[\s\S]{0,200}?目前無法提供色號比較/.test(src));
check('非粉底維持不顯示（眼影沒有色階這個概念）',
    /if \(!isFoundationProduct\(p\)\) return '';/.test(src));
check('不跳 error toast',
    !/shadeRecommendation[\s\S]{0,400}?showToast\(.{0,40}錯誤/.test(src));

console.log('');
console.log('=== 9. 正規化器要把欄位帶下來 ===');
// 少帶任何一個，上面所有判斷都會因為「欄位是 undefined」而退回最保守的那一邊——
// 那個失敗是靜默的：畫面看起來只是比較保守，不像漏了欄位。
for (const field of ['colorRepresentation', 'colorVerificationStatus', 'colorMatchReady',
                     'colorEstimated', 'colorWarning', 'paletteColors', 'paletteComplete',
                     'paletteImageUrl', 'imageIdentityStatus', 'imageWarning']) {
    check(`api.js 帶出 ${field}`, new RegExp(`${field}:`).test(apiSrc));
}

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
