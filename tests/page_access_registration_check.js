// 新增頁面時，權限那兩個地方一定要跟著登記。
//
// 這個坑已經踩過兩次：
//   2026-08-29 新增「關於我們」——一個只是在講品牌故事的頁面，點下去跳
//              「此帳號目前沒有使用此功能的權限，請聯繫管理員」，說得像被停權。
//   2026-09-25 新增「我的化妝包」——同一個症狀，同一個原因。
//
// 原因是 allowedPages 由後台勾選，**新頁面預設不在裡面**。所以每新增一個
// 不需要特權的頁面，都要回 Api.canAccess 加白名單；需要登入的則要進訪客守衛。
//
// 兩者都不會報錯，只會讓使用者看到一個誤導的訊息，所以用測試釘住。
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');
const router = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');

// 不需要後台核可的頁面：canAccess 必須直接放行，否則一般會員會被擋。
const PUBLIC_PAGES = ['products', 'about', 'makeupBag'];

// 需要登入才有意義的頁面：訪客守衛必須攔下來，否則訪客會看到一個存不了東西的畫面。
const LOGIN_REQUIRED = ['favorites', 'history', 'makeupBag'];

let failed = 0;
function check(label, ok, hint) {
  if (ok) { console.log(`  PASS ${label}`); return; }
  failed += 1;
  console.error(`  FAIL ${label}${hint ? `\n       ${hint}` : ''}`);
}

console.log('=== 新頁面的權限登記 ===\n');

// ① canAccess 的白名單
const canAccessBody = (() => {
  const start = api.indexOf('canAccess(page, profile)');
  if (start < 0) throw new Error('找不到 Api.canAccess');
  return api.slice(start, start + 1600);
})();

for (const page of PUBLIC_PAGES) {
  check(
    `canAccess 放行 ${page}`,
    new RegExp(`page === ['"]${page}['"]`).test(canAccessBody),
    `在 js/api.js 的 canAccess 裡加上 page === '${page}'，` +
    '否則一般會員點進去會看到「此帳號目前沒有使用此功能的權限」。',
  );
}

// ② 訪客守衛
const guardBody = (() => {
  const start = router.indexOf('訪客攔截');
  if (start < 0) throw new Error('找不到訪客攔截那段');
  return router.slice(start, start + 800);
})();

for (const page of LOGIN_REQUIRED) {
  check(
    `訪客守衛攔下 ${page}`,
    new RegExp(`\\b${page}\\b`).test(guardBody),
    `在 js/router.js 的訪客攔截清單加上 ${page}，` +
    '否則未登入者會進到一個存不了資料的頁面，以為功能壞掉。',
  );
}

// ③ 頁面本身要註冊在導覽順序與預設權限清單裡，否則 Router.go 走不到
for (const page of PUBLIC_PAGES) {
  if (page === 'about') continue;   // about 不在 NAV_ORDER，由頁尾連結進入
  check(
    `NAV_ORDER 含 ${page}`,
    new RegExp(`'${page}'`).test(router.slice(router.indexOf('NAV_ORDER'), router.indexOf('NAV_ORDER') + 300)),
    `在 js/router.js 的 NAV_ORDER 加上 '${page}'。`,
  );
}

console.log(failed ? `\n${failed} 項未通過` : '\n新頁面權限登記測試通過');
process.exitCode = failed ? 1 : 0;
