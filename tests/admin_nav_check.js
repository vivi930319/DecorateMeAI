// 管理後台的導覽必須與三個地方一致：
//
//   1. admin.html 的 <button data-admin-section="X">
//   2. admin.html 的 <section data-admin-view="X">
//   3. router.js 的 sectionMeta 白名單
//
// 少任何一邊都不會報錯，只會安靜地壞掉。2026-08-23 就發生過：導覽上有
// 「模型修正複核」，section 也寫好了，但 sectionMeta 漏了 feedback，於是
//     const next = sectionMeta[section] ? section : 'overview';
// 把每一次點擊都轉回營運總覽——那個頁面做完了卻永遠進不去，而且畫面上
// 看起來只是「按了沒反應」。
//
// 用法：node tests/admin_nav_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'pages/admin.html'), 'utf8');
const js = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');

const all = (re, s) => [...s.matchAll(re)].map(m => m[1]);
const buttons = all(/data-admin-section="([^"]+)"/g, html);
const views = all(/data-admin-view="([^"]+)"/g, html);

const metaStart = js.indexOf('const sectionMeta = {');
const metaEnd = js.indexOf('};', metaStart);
const metaSrc = js.slice(metaStart, metaEnd);
const metaKeys = all(/^\s{12}([a-zA-Z_]+):\s*\{/gm, metaSrc);

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};

console.log('\n=== 目前的區塊 ===');
console.log('  導覽按鈕   :', buttons.join(', '));
console.log('  區塊       :', views.join(', '));
console.log('  sectionMeta:', metaKeys.join(', '));

console.log('\n=== 三者必須一致 ===');
const setB = new Set(buttons), setV = new Set(views), setM = new Set(metaKeys);
const missingView = buttons.filter(b => !setV.has(b));
const missingMeta = buttons.filter(b => !setM.has(b));
const orphanView = views.filter(v => !setB.has(v));
const orphanMeta = metaKeys.filter(m => !setB.has(m));

check('每個按鈕都有對應的區塊', missingView.length === 0,
  missingView.length ? `缺少 section: ${missingView.join(', ')}` : '');
// 這條就是 feedback 踩過的坑
check('每個按鈕都在 sectionMeta 白名單裡', missingMeta.length === 0,
  missingMeta.length ? `按了會被踢回 overview: ${missingMeta.join(', ')}` : '');
check('沒有點不到的孤兒區塊', orphanView.length === 0,
  orphanView.length ? `有 section 但沒有按鈕: ${orphanView.join(', ')}` : '');
check('sectionMeta 沒有已移除區塊的殘留', orphanMeta.length === 0,
  orphanMeta.length ? `多餘的項目: ${orphanMeta.join(', ')}` : '');

console.log('\n=== 已移除的區塊不該有殘留 ===');
for (const gone of ['demo', 'crawler']) {
  check(`admin.html 沒有 ${gone}`, !html.includes(`"${gone}"`), '');
}
check('router.js 沒有 initAdminDemo', !js.includes('initAdminDemo'));
check('router.js 沒有 adminStaging', !js.includes('adminStaging'));
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8');
check('api.js 沒有暫存商品的 API 方法', !api.includes('_stagingBase'));

console.log('\n=== 導覽編號要連續 ===');
const idx = all(/<span class="admin-nav-index">(\d+)<\/span>/g, html).map(Number);
check('編號從 01 連續遞增', idx.every((n, i) => n === i + 1), idx.join(','));
check('編號數量等於按鈕數量', idx.length === buttons.length, `${idx.length} vs ${buttons.length}`);

console.log('\n=== 每個 admin 元素都要有 JS 接線 ===');
// 這一節防的是「HTML 做好了、API 也有了，但沒有人把兩邊連起來」。
// 模型修正複核先前就是這樣：畫面、表格、後端端點全都在，router.js 卻一行都沒引用它，
// 點下去完全沒反應——而且不會有任何錯誤訊息，因為根本沒有程式碼在跑。
const ids = all(/\bid="(admin[A-Za-z0-9_]+)"/g, html);
// 被 aria-labelledby 指到的是純標題，存在的目的就是給輔助技術讀，不需要 JS 碰它。
const ariaTargets = new Set(all(/aria-labelledby="([^"]+)"/g, html));
const unwired = ids.filter(id => !js.includes(id) && !ariaTargets.has(id));
check('admin.html 的每個 id 都有被 router.js 使用', unwired.length === 0,
  unwired.length ? `沒有接線: ${unwired.join(', ')}` : `${ids.length} 個 id 全部有接線`);

console.log('\n=== 模型修正複核的接線 ===');
for (const id of ['adminFeedbackBody', 'adminFeedbackState', 'adminFeedbackSummary', 'adminFeedbackRefresh']) {
  check(`${id} 有被使用`, js.includes(id));
}
check('切到 feedback 會觸發載入', js.includes("next === 'feedback'") && js.includes('_loadFeedbackOnce'));
check('有「重新載入」的處理', js.includes('fbRefresh.onclick'));
check('401/403 導向重新登入而不是顯示連線失敗', js.includes('需要管理員身分才能檢視'));
check('api.js 提供 fetchFaceFeedback',
  fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').includes('async fetchFaceFeedback'));

console.log('\n=== 模型修正複核必須可用 ===');
check('feedback 按鈕存在', setB.has('feedback'));
check('feedback 區塊存在', setV.has('feedback'));
check('feedback 在白名單裡（先前就是漏了這個）', setM.has('feedback'));

console.log('\n=== 商品管理：品牌與價格篩選 ===');
// 2026-08-28 實測線上商品服務：minPrice/maxPrice 完全沒有作用（minPrice=99999
// 仍回全部 68 筆），brand=MAC,YSL 這種逗號多選回 0 筆。所以這兩個條件必須在
// 本機的完整清單上做——送出去只會得到「看起來有篩、其實沒篩」或「篩到空的」。
check('品牌篩選在畫面上', html.includes('id="adminProductBrandFilter"'));
check('價格區間在畫面上',
  html.includes('id="adminProductMinPrice"') && html.includes('id="adminProductMaxPrice"'));
check('過濾在本機做，不送 API', js.includes('const filterAdminProducts ='));
check('沒有把 minPrice 送給 API', !/listProducts\([^)]*minPrice/.test(js));
check('沒有把逗號品牌串送給 API', !/brand:\s*[^,\n]*\.join\(','\)/.test(js));
// 價格抽不出數字的商品在有價格條件時要排除，不能當成 0
check('沒有價格的商品不混進價格區間', js.includes('if (price == null) return false;'));
// 本機再篩過就不能報伺服器的總數
check('筆數跟著篩選走', js.includes('已從 ${dbProducts.length} 筆篩選'));

console.log('\n=== 新增商品時的品牌 ===');
// 純文字輸入會讓「MAC」「Mac」「MAC 」變成三個品牌，而篩選與推薦都是字串比對
check('品牌欄有既有選項可挑', html.includes('list="adminBrandOptions"')
  && html.includes('<datalist id="adminBrandOptions">'));
check('選項從實際清單長出來，不寫死', js.includes('const syncAdminBrandOptions ='));
check('載入完成後同步選項', js.includes('syncAdminBrandOptions(dbProducts)'));

console.log('\n=== 一次性旗標的生命週期 ===');
// 「這一區已經載過了」是**這一次進頁**的事，不是整個 session 的事。
// 每次進後台 pages/admin.html 都重新抓、DOM 整個換掉，但這些旗標掛在 Router 上、
// 跨頁面存活。不重設的話：離開後台再回來，旗標還是 true，資料不會載，
// 待覆核 0、訓練批次「尚未載入」——看起來像資料整批消失。
// 第一次進去正常、第二次才壞，所以特別難重現。
['_feedbackLoaded', '_productAuditLoaded'].forEach((flag) => {
  const re = new RegExp('admin\\(\\) \\{[\\s\\S]{0,1200}?Router\\.' + flag + ' = false;');
  check('進頁時重設 Router.' + flag, re.test(js));
});
check('旗標只在載入成功後才設起來', js.includes('Router._feedbackLoaded = ok !== false;'));

console.log('\n=== 新舊兩版 API 都要正確 ===');
// 舊版對 minPrice/sort 是靜默忽略——送了不報錯也沒效果；新版會回
// appliedFilters 與 facets。寫死任一種都會在另一版上壞掉：
// 假設支援 → 舊版上顯示一份沒篩到的清單；假設不支援 → 新版上白抓整份。
// 所以用回應自己說的來判斷。
check('用回應判斷後端支不支援篩選',
  api.includes('const serverFiltering = !!(data.appliedFilters || data.facets)'));
check('第一次問到之前保守當成不支援', api.includes('productServerFiltering: false'));
check('後端支援時前端不再重複篩',
  js.includes('if (Api.productServerFiltering) return list || [];'));
check('後端支援時才把條件送出去',
  js.includes("baseParams.brand = brands.join(',')")
  && /if \(Api\.productServerFiltering\)[\s\S]{0,400}?baseParams\.minPrice/.test(js));
check('認得 OFFSET_NOT_SUPPORTED', api.includes('OFFSET_NOT_SUPPORTED'));
// 新版粉底會帶完整色號清單，那正是色號比較區一直缺的資料
check('帶入 shades 清單', api.includes('shades: Array.isArray(product.shades)'));
check('帶入 seriesId 與 depthIndex',
  api.includes('seriesId: product.seriesId') && api.includes('depthIndex: Number.isFinite'));
// depthIndexOfficial=false 代表由 Lab 亮度推導，文案不可寫「官方淺一階」
check('記下色階是不是官方的',
  api.includes('depthIndexOfficial: product.depthIndexOfficial === true'));
// 後端已依 depthIndex 排好；前端再排一次遲早會跟後端不一致
check('不重排 shades', !/shades:[\s\S]{0,200}?\.sort\(/.test(api));

console.log('\n=== 完整翻頁（契約 §3.3）===');
// 2169 筆 @ limit=100 需要 22 頁；上限要留得夠
check('翻頁上限足夠載完', /PRODUCT_MAX_PAGES = (\d+)/.test(js)
  && Number(js.match(/PRODUCT_MAX_PAGES = (\d+)/)[1]) >= 22,
  `目前 ${(js.match(/PRODUCT_MAX_PAGES = (\d+)/) || [])[1]}`);
check('去重用完整 id，不是尾端數字', js.includes('p.rawId != null ? `raw:${p.rawId}`'));
check('重複游標會停下來', js.includes('usedCursors.has(next)'));
check('被上限截斷要標成部分載入', js.includes('truncated = true'));
check('部分載入時不報伺服器總數', js.includes('(typeFilter || rec.partial)'));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
