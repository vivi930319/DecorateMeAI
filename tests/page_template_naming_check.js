// 頁面檔名必須跟頁面代號一字不差。
//
// Router 用 `fetch('pages/' + key + '.html')` 取模板，key 就是 NAV_ORDER 裡的代號。
// 檔名對不上時 fetch 回 404，程式會**安靜地**掉到 getPageFallback 的備援模板——
// 不報錯、不當機、Console 也看不出異常，只是畫面少了一半。
//
// 2026-09-25：新增「我的化妝包」時檔案取名 makeup-bag.html，而代號是 makeupBag。
// 結果使用者看到的是一個寫著「請用上面的搜尋加入商品」、但上面根本沒有搜尋框的頁面。
//
// ⚠️ 這支**只檢查檔名**。備援模板與正式模板是否同構是另一回事：
// 現行多數備援模板本來就是刻意簡化的（admin 那份尤其明顯），
// 要求它們逐一對齊是另一個題目，不在這裡擋。
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const router = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');

let failed = 0;
function check(label, ok, hint) {
  if (ok) { console.log(`  PASS ${label}`); return; }
  failed += 1;
  console.error(`  FAIL ${label}${hint ? `\n       ${hint}` : ''}`);
}

console.log('=== 頁面模板檔名 ===\n');

// 精確取 NAV_ORDER 的陣列內容，不要用固定長度截字串——
// 截過頭會把後面不相干的字串當成頁面代號（初版就誤抓到 'error'）。
const navStart = router.indexOf('NAV_ORDER');
if (navStart < 0) throw new Error('找不到 NAV_ORDER');
const open = router.indexOf('[', navStart);
const close = router.indexOf(']', open);
if (open < 0 || close < 0) throw new Error('解析不到 NAV_ORDER 的陣列');
const pages = [...router.slice(open, close).matchAll(/'([a-zA-Z]+)'/g)].map(m => m[1]);
if (!pages.length) throw new Error('NAV_ORDER 是空的');

// analysis 由多個子畫面組成，不以自己的檔名取模板。
const NO_TEMPLATE_FILE = new Set(['analysis']);

for (const page of pages) {
  if (NO_TEMPLATE_FILE.has(page)) continue;
  check(
    `pages/${page}.html 存在`,
    fs.existsSync(path.join(ROOT, 'pages', `${page}.html`)),
    `Router 取的是 pages/${page}.html。檔名若用別的寫法（例如 kebab-case 的 ` +
    `${page.replace(/[A-Z]/g, c => '-' + c.toLowerCase())}.html），fetch 會 404 ` +
    '並安靜掉到備援模板：畫面少一半，但不會報錯。',
  );
}

// 反過來也查一次：有檔案卻沒有對應代號，多半是改名改一半。
console.log('');
const known = new Set(pages);
for (const file of fs.readdirSync(path.join(ROOT, 'pages')).filter(f => f.endsWith('.html'))) {
  const key = file.replace(/\.html$/, '');
  if (known.has(key)) continue;
  // ai-render 是渲染頁，由 Router 以別的方式載入，不在 NAV_ORDER。
  if (key === 'ai-render') continue;
  check(
    `pages/${file} 有對應的頁面代號`,
    false,
    `NAV_ORDER 裡沒有 '${key}'。如果這是改名留下的舊檔，請刪掉；` +
    '留著會讓下一個人以為它還在用。',
  );
}

console.log(failed ? `\n${failed} 項未通過` : '\n頁面模板檔名測試通過');
process.exitCode = failed ? 1 : 0;
