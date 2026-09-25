// 正規化後的商品必須帶 candidateKey。
//
// 化妝包整條線都靠它：加入、移除、反推風格、商品卡的「我有」按鈕、
// 延伸推薦的「加入化妝包」。少了它，那些地方全部**安靜地不作用**——
// `p.candidateKey ? ... : ''` 一律走空字串，按鈕根本不會被畫出來；
// `filter(p => p.candidateKey)` 一律篩成空陣列，搜尋永遠「沒有符合的商品」。
//
// 2026-09-25：_normalizeProduct 從頭到尾就沒有這個欄位，而我在六個地方用了它。
// 症狀是「搜尋不到任何商品」，看起來像商品 API 壞了，其實是前端自己把結果濾光。
//
// 也檢查不要組出假鍵：apiType 或 rawId 缺一時要給 null，不能組出 "null:123"——
// 那種鍵過得了格式檢查，但資料庫查不到，會變成「加得進化妝包、卻反推不出東西」。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');

function matchBrace(text, from) {
  let depth = 0;
  const open = text.indexOf('{', from);
  for (let i = open; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}') { depth--; if (depth === 0) return i + 1; }
  }
  return -1;
}

const start = src.indexOf('_normalizeProduct(product) {');
if (start < 0) throw new Error('找不到 _normalizeProduct');
const body = src.slice(start, matchBrace(src, start));

const sandbox = { console: { log() {}, warn() {} }, Date, Math, String, Number, Object, Array, JSON };
vm.createContext(sandbox);
// _normalizeProduct 會呼叫同物件上的幾個小工具。這支測的是 candidateKey 的組法，
// 那些工具原樣回傳就夠了，不必把整個 Api 搬進來。
vm.runInContext(
  `const Api = {
     _thumbUrl: (v) => v || '',
     _isStorableImageUrl: () => true,
     _safeMatchReason: () => '',
     _pickPrice: (p) => p && p.price,
     productServerFiltering: false,
     ${body}
   };
   globalThis.__n = (p) => Api._normalizeProduct(p);`,
  sandbox,
);
const n = sandbox.__n;

let failed = 0;
function check(label, ok, hint) {
  if (ok) { console.log(`  PASS ${label}`); return; }
  failed += 1;
  console.error(`  FAIL ${label}${hint ? `\n       ${hint}` : ''}`);
}

console.log('=== 商品正規化的 candidateKey ===\n');

// ① 後端直接給了就照用
const given = n({ candidateKey: 'lipsticks:3800', type: 'lipsticks', rawId: 3800, name: 'x' });
check('後端給的 candidateKey 原樣保留', given && given.candidateKey === 'lipsticks:3800',
  `實際 ${JSON.stringify(given && given.candidateKey)}`);

// ② 後端沒給就用 apiType 與 rawId 組
const built = n({ type: 'eyeshadows', rawId: 12, name: 'x' });
check('後端沒給時自己組出 {type}:{rawId}', built && built.candidateKey === 'eyeshadows:12',
  `實際 ${JSON.stringify(built && built.candidateKey)}。化妝包的加入、移除、反推全部靠它，` +
  '少了就會安靜失效——按鈕不會出現、搜尋結果被濾光，而且不報錯。');

// ③ 零件缺一就給 null，不要組假鍵
const noRawId = n({ type: 'lipsticks', name: 'x' });
check('缺 rawId 時是 null，不組假鍵',
  noRawId && (noRawId.candidateKey === null || noRawId.candidateKey === undefined ||
    !/null|undefined/.test(String(noRawId.candidateKey))),
  `實際 ${JSON.stringify(noRawId && noRawId.candidateKey)}。` +
  '組出 "null:123" 這種鍵過得了格式檢查但資料庫查不到，' +
  '會變成「加得進化妝包、卻永遠反推不出東西」。');

// ④ recommendationState 要傳下來，搜尋結果才標示得出「不參與推薦」
const state = n({ type: 'lipsticks', rawId: 1, name: 'x', recommendationState: '資料未達推薦條件' });
check('recommendationState 有傳下來',
  state && state.recommendationState === '資料未達推薦條件',
  `實際 ${JSON.stringify(state && state.recommendationState)}。` +
  '化妝包搜尋靠它標示「可以登記，但目前不參與妝容推薦」。');

console.log(failed ? `\n${failed} 項未通過` : '\ncandidateKey 測試通過');
process.exitCode = failed ? 1 : 0;
