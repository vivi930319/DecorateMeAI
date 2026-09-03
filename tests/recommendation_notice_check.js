// RecommendationNotice 的行為測試。
//
// 它定義在 js/router.js 裡，而 router.js 有 6000 行且滿是 DOM 操作，整份載入
// 不切實際。所以這裡用括號配對把那一段**原封不動**抽出來執行——測的是真正會跑的
// 程式碼，不是複製一份到測試檔裡（那種測試只證明複製品沒錯）。
//
// 用法：node tests/recommendation_notice_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');

const MARK = 'const RecommendationNotice = {';
const start = src.indexOf(MARK);
if (start < 0) { console.log('找不到 RecommendationNotice 定義'); process.exit(1); }
let depth = 0, end = -1;
for (let i = src.indexOf('{', start); i < src.length; i++) {
  if (src[i] === '{') depth++;
  else if (src[i] === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
}
const code = src.slice(start, end) + ';';

let navigated = null, rendered = null;
const sandbox = {
  console,
  escapeHtml: s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  Router: { currentPage: 'products', go: p => { navigated = p; } },
  renderShop: f => { rendered = f; },
};
vm.createContext(sandbox);
vm.runInContext(code + '\nglobalThis.__N = RecommendationNotice;', sandbox);
const N = sandbox.__N;

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};
const ok = (products, extra = {}) => ({ ok: true, products, fallbackReasons: [], ...extra });

console.log('\n=== 1. 降級提示（契約 §4）===');
N.record(ok([{ id: 1 }], {
  fallbackReasons: [{ code: 'BROW_COLOR_UNAVAILABLE', affected: ['eyebrows'] }],
}));
let h = N.html();
check('BROW_COLOR_UNAVAILABLE 有顯示提示', h.includes('眉彩'), h.slice(0, 60));
check('不宣稱「依膚色精準比對」', !/精準|依膚色比對眉/.test(h.replace('不以膚色比對眉彩色號', '')),
  '措辭必須避免暗示做了膚色比色');
check('明確說是依風格排序', h.includes('依風格排序'));

N.record(ok([{ id: 1 }], {
  fallbackReasons: [{ code: 'SKIN_TONE_LAB_UNRELIABLE', affected: ['foundations'] }],
}));
h = N.html();
check('SKIN_TONE_LAB_UNRELIABLE 提到季型與膚色分級',
  h.includes('季型') && h.includes('膚色分級'), h.slice(0, 60));

N.record(ok([{ id: 1 }], { fallbackReasons: [{ code: 'STYLE_KEYWORD_NO_MATCH' }] }));
check('STYLE_KEYWORD_NO_MATCH 有提示', N.html().includes('綜合排序'));

console.log('\n=== 2. 同一個 code 只說一次 ===');
N.record(ok([{ id: 1 }], {
  fallbackReasons: [
    { code: 'BROW_COLOR_UNAVAILABLE', affected: ['eyebrows'] },
    { code: 'BROW_COLOR_UNAVAILABLE', affected: ['eyebrows2'] },
  ],
}));
h = N.html();
check('重複的 code 不重複顯示', (h.match(/眉彩依風格排序/g) || []).length === 1,
  `出現 ${(h.match(/眉彩依風格排序/g) || []).length} 次`);

console.log('\n=== 3. 沒有降級時不佔版面 ===');
N.record(ok([{ id: 1 }]));
check('無 fallbackReasons 時回空字串', N.html() === '', JSON.stringify(N.html()));

console.log('\n=== 4. 錯誤分流（契約 §5）===');
N.record({ ok: false, status: 502, code: 'PRODUCT_DB_UNAVAILABLE', requestId: 'req_abc123def456', retryable: true });
h = N.html();
check('502 顯示錯誤樣式', h.includes('is-error'));
check('502 提供重試按鈕', h.includes('data-rec-retry'));
check('502 顯示 requestId', h.includes('req_abc123de'), h.slice(-90));

N.record({ ok: false, status: 422, code: 'INVALID_ANALYSIS_PACKAGE', requestId: 'req_x', retryable: false });
h = N.html();
check('422 不提供重試按鈕（重試幾次都一樣）', !h.includes('data-rec-retry'));
check('422 請使用者重做臉部分析', h.includes('重新完成臉部分析'), h.slice(0, 70));

N.record({ ok: false, status: 504, code: 'PRODUCT_DB_TIMEOUT', retryable: true });
check('504 提供重試按鈕', N.html().includes('data-rec-retry'));

N.record({ ok: false, code: 'UNKNOWN_MAKEUP_STYLE', retryable: false });
check('UNKNOWN_MAKEUP_STYLE 引導換風格', N.html().includes('換一個風格'));

N.record(null);
h = N.html();
check('null（網路失敗）也有訊息', h.includes('is-error') && h.length > 30);

console.log('\n=== 5. 成功後要清掉上一輪的錯誤 ===');
N.record({ ok: false, code: 'PRODUCT_DB_UNAVAILABLE', retryable: true });
N.record(ok([{ id: 1 }]));
check('成功之後錯誤提示消失', N.html() === '' && N.error === null,
  `error=${JSON.stringify(N.error)}`);

console.log('\n=== 6. 空結果（契約 §4：不可製造假商品）===');
N.record(ok([], { fallbackReasons: [{ code: 'RECOMMENDATION_EMPTY' }] }));
check('標記為空結果', N.isEmpty === true);
check('RECOMMENDATION_EMPTY 不混進降級提示列', !N.html().includes('RECOMMENDATION_EMPTY'));
h = N.emptyHtml();
// 「重新分析」已經從空狀態移除：使用者到這一頁是想看商品，重跑臉部分析
// 不會讓商品變多，只會把人送回起點。home_navigation_check 正在守著它不要回來，
// 所以這裡不能再要求它出現——兩支各守相反的事，就會永遠有一支是紅的。
check('空狀態不再有「重新分析」', !h.includes('data-rec-reanalyze'));
check('空狀態有「瀏覽所有商品」', h.includes('data-rec-browse'));

N.record(ok([]));
check('products 為空也算空結果', N.isEmpty === true);

console.log('\n=== 7. XSS：後端訊息不可直接插入 DOM ===');
N.record({ ok: false, code: 'NOPE_UNKNOWN', requestId: '<img src=x onerror=alert(1)>', retryable: false });
h = N.html();
check('requestId 有跳脫', !h.includes('<img'), h.slice(-80));
N.record(ok([{ id: 1 }], {
  fallbackReasons: [{ code: 'CUSTOM_CODE', message: '<script>alert(1)</script>' }],
}));
h = N.html();
check('未知 code 的 message 有跳脫', !h.includes('<script>'), h.slice(0, 90));

console.log('\n=== 8. clear() ===');
N.record({ ok: false, code: 'PRODUCT_DB_TIMEOUT', retryable: true });
N.clear();
check('clear 之後沒有任何提示', N.html() === '' && !N.isEmpty && !N.error);

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
