// 化妝包反推必須走**會員**路徑，不可以走 /product-api。
//
// 2026-09-25：它原本掛在 /product-api/recommend-styles。那條在 Gateway 走的是
// 公開商品代理（proxy_public_product_request），刻意只帶 Accept 與 Content-Type——
// 商品瀏覽不需要登入，所以不轉發任何憑證。
//
// 後果是反推**永遠**看不到使用者是誰：登入與否都一樣回「尚未建立化妝包」，
// 跟化妝包裡有幾件東西無關。而那句話讓人以為是資料問題，一直回去重加商品。
//
// 定案（方案 B）把它搬到 /member-database/api/members/{email}/recommend-styles。
// 會員路徑 Gateway 本來就會轉發 cookie，而且帶 email 還自動享有跨帳號檢查。
//
// 搬回去 = 整條功能再次死掉，而且症狀是誤導的，所以用測試釘住。
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');

function block(signature, span = 2200) {
  const i = api.indexOf(signature);
  if (i < 0) throw new Error(`找不到 ${signature}`);
  return api.slice(i, i + span);
}

let failed = 0;
function check(label, ok, hint) {
  if (ok) { console.log(`  PASS ${label}`); return; }
  failed += 1;
  console.error(`  FAIL ${label}${hint ? `\n       ${hint}` : ''}`);
}

console.log('=== 反推妝容的呼叫路徑 ===\n');

const body = block('async recommendStyles(');

check(
  '用會員服務的 baseUrl',
  /config\.services\.memberDatabase\.baseUrl/.test(body),
  '目前用的不是 memberDatabase。走 product 的話 Gateway 不會轉發會員 cookie，' +
  '反推永遠讀不到使用者的化妝包。',
);

check(
  '路徑是 api/members/{email}/recommend-styles',
  /api\/members\/\$\{encodeURIComponent\(email\)\}\/recommend-styles/.test(body),
  '路徑必須帶 email。那是 Gateway 轉發會員身分、以及跨帳號檢查生效的依據。',
);

check(
  '沒有殘留 /product-api 的呼叫',
  !/\$\{base\}\/recommend-styles/.test(body),
  '看起來還在打公開商品代理那條。',
);

check(
  'email 缺席時擋下來，不要送出無主的請求',
  /if \(!email\)/.test(body),
  '沒有登入身分就送出去，只會拿到一個誤導的「尚未建立化妝包」。',
);

// 不接受 bagId——定案明訂它不是第一期輸入，送了會回 400
check(
  '不送 bagId',
  !/body\.bagId/.test(body),
  'bagId 不是第一期輸入，送了上游會回 400。',
);

console.log(failed ? `\n${failed} 項未通過` : '\n反推路徑測試通過');
process.exitCode = failed ? 1 : 0;
