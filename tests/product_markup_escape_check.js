// 商品資料最終來自爬蟲抓的外部網站，塞進 innerHTML 之前一定要跳脫。
//
// 2026-10-24 資安檢查發現首頁「個人推薦」把品牌名直接塞進 HTML，好幾個
// data-* 屬性也直接放商品 id。品牌名裡只要藏一段 <img onerror=...>，
// 就能用登入者（包含管理員）的身分操作。
//
// 這支檢查兩件事：
//   1. router.js 裡把商品 id 放進 data-* 屬性的地方都有包 escapeHtml()
//   2. firebase.json 有 CSP，且擋掉 <object>、<base> 與外部表單送出
//
// 用法：node tests/product_markup_escape_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const js = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
const firebase = JSON.parse(fs.readFileSync(path.join(ROOT, 'firebase.json'), 'utf8'));

let pass = 0, fail = 0;
const check = (ok, msg) => { if (ok) { pass++; console.log('  ok  ' + msg); } else { fail++; console.log('  FAIL ' + msg); } };

const rawIdAttrs = [...js.matchAll(/data-[a-z-]+="\$\{(?:p|product|row\.product)\.id\}"/g)];
check(rawIdAttrs.length === 0, `商品 id 放進 data-* 屬性都有跳脫（沒跳脫的 ${rawIdAttrs.length} 處）`);

const rawBrand = /:\s*\(p\.brand \|\| ''\)\}/.test(js);
check(!rawBrand, '個人推薦卡片的品牌名有跳脫');

const headers = (firebase.hosting.headers || []).find(h => h.source === '**')?.headers || [];
const csp = headers.find(h => h.key === 'Content-Security-Policy')?.value || '';
check(csp.length > 0, 'firebase.json 對所有路徑送出 Content-Security-Policy');
for (const directive of ["object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"]) {
    check(csp.includes(directive), `CSP 含 ${directive}`);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
