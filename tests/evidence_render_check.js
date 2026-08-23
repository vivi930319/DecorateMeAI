// 用**真實的後端回應**驗證前端的推薦依據處理鏈。
//
// 為什麼用真資料而不是自己造：造的資料只能證明「我以為後端會這樣回」。
// 這個專案已經吃過幾次虧——欄位名不同、文案不同、型別不同。
// tests/_live_recommend_sample.json 是直接從線上抓下來的兩種情境（有／無 browLab）。
//
// 用法：node tests/evidence_render_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');

function extract(file, marker) {
  const src = fs.readFileSync(path.join(ROOT, file), 'utf8');
  const start = src.indexOf(marker);
  if (start < 0) throw new Error(`找不到 ${marker}`);
  let depth = 0, i = src.indexOf('{', start), end = -1;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
  }
  return src.slice(start, end);
}

const sandbox = {
  console,
  escapeHtml: s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
};
vm.createContext(sandbox);

// 從 router.js 抽出評分標籤、順序與渲染函式（原封不動）
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
for (const name of ['const SCORE_LABELS = Object.freeze(', 'const SCORE_ORDER = [']) {
  const s = src.indexOf(name);
  const semi = src.indexOf(';', src.indexOf(name === 'const SCORE_ORDER = [' ? ']' : ')', s));
  vm.runInContext(src.slice(s, semi + 1), sandbox);
}
const fnStart = src.indexOf('function recommendationEvidenceHtml');
const fnEnd = src.indexOf('\n}', fnStart) + 2;
vm.runInContext(src.slice(fnStart, fnEnd), sandbox);

// 從 api.js 抽出 _safeMatchReason（掛成獨立函式來測）
const apiSrc = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8');
const sStart = apiSrc.indexOf('    _safeMatchReason(product) {');
let d = 0, j = apiSrc.indexOf('{', sStart), sEnd = -1;
for (; j < apiSrc.length; j++) {
  if (apiSrc[j] === '{') d++;
  else if (apiSrc[j] === '}') { d--; if (d === 0) { sEnd = j + 1; break; } }
}
vm.runInContext('var _obj = { ' + apiSrc.slice(sStart, sEnd) + ' };'
  + 'globalThis.safeReason = p => _obj._safeMatchReason(p);', sandbox);

const live = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/_live_recommend_sample.json'), 'utf8'));
const prods = k => (live[k].analysisPackage?.recommendations?.products) || live[k].products || [];

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};

console.log('\n=== 1. 真實資料含有前端需要的欄位 ===');
const sample = prods('withBrow')[0];
check('後端有回 scoreBreakdown', !!sample.scoreBreakdown, Object.keys(sample.scoreBreakdown || {}).join(','));
check('後端有回 matchedKeywords', Array.isArray(sample.matchedKeywords));
check('後端有回 colorMethod', !!sample.colorMethod, sample.colorMethod);

console.log('\n=== 2. 推薦依據能從真實資料渲染出來 ===');
const html = sandbox.recommendationEvidenceHtml(sample);
check('產生了「查看推薦依據」', html.includes('查看推薦依據'));
check('包含色彩適配', html.includes('色彩適配'));
check('包含風格適配', html.includes('風格適配'));
check('八項分數都渲染出來',
  ['色彩適配', '風格適配', '臉部特徵', '價格符合', '品牌偏好', '個人行為', '供貨狀態', '綜合內容']
    .every(l => html.includes(l)));
const kwProd = prods('withBrow').find(p => (p.matchedKeywords || []).length);
if (kwProd) {
  const h2 = sandbox.recommendationEvidenceHtml(kwProd);
  check('有命中關鍵字時顯示出來', h2.includes('命中關鍵字') && h2.includes(kwProd.matchedKeywords[0]),
    kwProd.matchedKeywords.join(','));
}
check('沒有分數也沒有關鍵字時不佔版面',
  sandbox.recommendationEvidenceHtml({ name: 'x' }) === '');

console.log('\n=== 3. 分數值有被正確帶出（不是寫死的樣板）===');
const sb = sample.scoreBreakdown;
const shown = (html.match(/ev-v">([\d.]+)</g) || []).map(s => s.match(/">([\d.]+)</)[1]);
check('渲染出的數字與後端一致',
  shown.includes(Number(sb.colorScore).toFixed(2)) && shown.includes(Number(sb.styleScore).toFixed(2)),
  `colorScore=${Number(sb.colorScore).toFixed(2)} styleScore=${Number(sb.styleScore).toFixed(2)}`);

console.log('\n=== 4. 眉彩不實文案的導正（契約 §1）===');
const browWith = prods('withBrow').filter(p => p.type === 'eyebrows');
const browNo = prods('noBrow').filter(p => p.type === 'eyebrows');
console.log(`  後端原文（有 browLab）：${browWith[0].matchReason}`);
const fixed = sandbox.safeReason(browWith[0]);
console.log(`  前端導正後：          ${fixed}`);
check('有 browLab 時不再宣稱「您的膚色」', !fixed.includes('您的膚色'));
check('改成指向實際用的眉色', fixed.includes('您的眉色'));

console.log(`  後端原文（無 browLab）：${browNo[0].matchReason}`);
const kept = sandbox.safeReason(browNo[0]);
check('降級文案原封不動（那句「未以膚色比較」是對的，改了會變反話）',
  kept === browNo[0].matchReason, kept);

console.log('\n=== 5. 非眉彩商品不受影響 ===');
const lip = prods('withBrow').find(p => p.type === 'lipsticks');
if (lip) check('唇彩理由原樣保留', sandbox.safeReason(lip) === (lip.matchReason || ''), lip.matchReason);

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
