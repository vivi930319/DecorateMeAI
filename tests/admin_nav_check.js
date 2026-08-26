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

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
