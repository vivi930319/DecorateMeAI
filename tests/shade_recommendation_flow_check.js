// 粉底三色階「實際流程接線」回歸檢查。
//
// recommendation_contract_check.js 會執行 shadeRecommendationHtml，確認畫面在
// anchor/lighter/darker 與 null 情境下畫對；這支補測真正載入順序中的兩個流程：
// makeup-flow.js（妝容流程）與 router.js（商品頁補抓／重試）。
// 沒有這層時，UI 函式本身可以全綠，但 active makeup-flow 只保存 products，
// 導致重新整理或換頁後三色階欄位消失。
//
// 用法：node tests/shade_recommendation_flow_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const flow = fs.readFileSync(path.join(ROOT, 'js/makeup-flow.js'), 'utf8').replace(/\r\n/g, '\n');
const router = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');

let pass = 0;
let fail = 0;
const check = (name, condition) => {
    console.log((condition ? '  PASS ' : '  FAIL ') + name);
    condition ? pass++ : fail++;
};

console.log('\n=== 1. API 回應欄位接線 ===');
check('從 analysisPackage.recommendations 讀取回應',
    /data\.analysisPackage\?\.recommendations\s*\|\|\s*data\.recommendations/.test(api));
check('讀取 shadeRecommendation 並正規化',
    /shadeRecommendation:\s*this\._normalizeShadeRecommendation\(rec\.shadeRecommendation\)/.test(api));
check('色階商品使用 imageUrl 進入詳情圖欄位',
    /imgFull:\s*product\.imageUrl\s*\|\|/.test(api));

console.log('\n=== 2. 實際妝容流程保存 ===');
check('makeup-flow 取得 shadeRecommendation',
    /recommended\?\.shadeRecommendation/.test(flow));
check('makeup-flow 以 anchor 作為可保存條件',
    /recommended\?\.shadeRecommendation\?\.anchor/.test(flow));
check('makeup-flow 把 shadeRecommendation 寫回 recommendations',
    /shadeRecommendation:\s*recommended\?\.shadeRecommendation\s*\|\|\s*null/.test(flow));
check('保存後寫入分析草稿',
    /shadeRecommendation:\s*recommended\?\.shadeRecommendation[\s\S]{0,600}AnalysisDraft\.save\(Router\.analysisPackage\)/.test(flow));

console.log('\n=== 3. 商品頁重試與重新整理 ===');
check('商品推薦重試也保存 shadeRecommendation',
    /shadeRecommendation:\s*rec\?\.shadeRecommendation\s*\|\|\s*null/.test(router));
check('詳情頁不自行補抓推薦資料',
    !router.includes('refetchShadeIfMissing') && !router.includes('Router._shadeRefetched'));
check('畫面可還原已保存的後端結果',
    /function currentShadeRecommendation/.test(router)
    && /const draft = typeof AnalysisDraft[^\n]*AnalysisDraft\.load\(\)/.test(router)
    && /return draft\?\.recommendations\?\.shadeRecommendation/.test(router));

console.log('\n=== 4. 色階卡片進入商品詳情 ===');
// 色階 node.product 是另一條正規化路徑，不能只測畫面 HTML 有沒有 data-shade-go；
// 這裡直接驗證它與推薦 products[] 使用同一個穩定商品 id。
function block(text, marker) {
    const start = text.indexOf(marker);
    if (start < 0) throw new Error(`找不到 ${marker}`);
    let depth = 0;
    for (let i = text.indexOf('{', start); i < text.length; i++) {
        if (text[i] === '{') depth++;
        else if (text[i] === '}') {
            depth--;
            if (depth === 0) return text.slice(start, i + 1);
        }
    }
    throw new Error(`${marker} 括號沒收完`);
}
const normalizeSandbox = {};
vm.createContext(normalizeSandbox);
vm.runInContext(`var Api = {
    ${block(api, '    _safeMatchReason(product) {')},
    ${block(api, '    _thumbUrl(raw, px = 400) {')},
    ${block(api, '    _normalizeProduct(product) {')},
    ${block(api, '    _normalizeShadeRecommendation(raw) {')}
};`, normalizeSandbox);
const rawAnchor = { id: 101, type: 'foundations', category: '底妝', name: 'MAC N18' };
const first = normalizeSandbox.Api._normalizeProduct(rawAnchor);
const second = normalizeSandbox.Api._normalizeProduct(first);
check('商品正規化不重複加上 api-foundations 前綴',
    first.id === 'api-foundations-101' && second.id === first.id);
check('正規化後仍保留資料庫 rawId', first.rawId === 101 && second.rawId === 101);
const shade = normalizeSandbox.Api._normalizeShadeRecommendation({
    method: 'official_depth_index',
    anchor: { product: rawAnchor },
    lighter: { product: { id: 100, type: 'foundations', category: '底妝', name: 'MAC N12' } },
});
check('色階推薦的主色與商品清單使用相同 id',
    shade.anchor.product.id === first.id && shade.lighter.product.id === 'api-foundations-100');
check('詳情頁會納入色階回應中的完整商品',
    /const shadeProducts = \[[\s\S]*currentShadeRecommendation\(\)\?\.lighter\?\.product/.test(router));
check('點擊色階直接重畫商品詳情',
    /resetSpaViewport\(\);\s*renderProductDetail\(btn\.dataset\.shadeGo\)/.test(router));
check('詳情頁會納入跨品牌回應中的完整商品',
    /const crossBrandProducts = currentFoundationCrossBrandAlternatives\(\)[\s\S]*const catalog = \[\.\.\.recommended, \.\.\.apiCatalog, \.\.\.shadeProducts, \.\.\.crossBrandProducts\]/.test(router));
check('點擊跨品牌色號直接重畫商品詳情',
    /Router\.shadeReturnTo = id;[\s\S]{0,180}renderProductDetail\(productId\)/.test(router)
    && /btn\.onclick = \(\) => goToCrossBrandProduct\(btn\)/.test(router));
check('品牌選單即時查回的色號會加入詳情候選',
    /Router\.foundationCrossBrandAlternatives = merged\.filter\(item =>/.test(router));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
