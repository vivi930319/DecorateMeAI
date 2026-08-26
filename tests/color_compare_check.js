// 色塊比對：你的顏色 vs 商品顏色。
//
// 這個功能存在的意義是讓使用者自己判斷準不準，所以最嚴重的錯誤不是「不顯示」，
// 而是「顯示了錯的對照」——拿膚色去比唇膏，兩個色塊並排看起來像系統壞了，
// 而使用者無從得知是配對配錯了。品類對應因此是這支測試的重點。
//
// 用法：node tests/color_compare_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
const apiSrc = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8');

// 大括號配對抽取。只計 { }，所以像 Object.freeze({...}) 這種包在小括號裡的
// 會少抽結尾的 ")" —— 那種情況改用 blockUntil 指定結束字串。
function block(text, marker) {
  const s = text.indexOf(marker);
  if (s < 0) throw new Error(`找不到 ${marker}`);
  let d = 0, i = text.indexOf('{', s), e = -1;
  for (; i < text.length; i++) {
    if (text[i] === '{') d++;
    else if (text[i] === '}') { d--; if (d === 0) { e = i + 1; break; } }
  }
  return text.slice(s, e);
}

function blockUntil(text, marker, endMark) {
  const s = text.indexOf(marker);
  if (s < 0) throw new Error(`找不到 ${marker}`);
  const e = text.indexOf(endMark, s);
  if (e < 0) throw new Error(`找不到 ${marker} 的結尾 ${endMark}`);
  return text.slice(s, e + endMark.length);
}

const sandbox = {
  console,
  escapeHtml: s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  Router: { analysisPackage: null },
  Api: null,
};
vm.createContext(sandbox);

// 真正的 labToRgb，不是自己重寫一份——顏色換算錯了測試也該紅
vm.runInContext('var Api = { ' + block(apiSrc, '    labToRgb(L, a, b) {') + ' };', sandbox);

vm.runInContext(blockUntil(src, 'const COMPARE_SOURCE = Object.freeze(', '});'), sandbox);
vm.runInContext(blockUntil(src, 'const COMPARE_LABEL = Object.freeze(', '});'), sandbox);
vm.runInContext(block(src, 'function userLabFor(kind) {'), sandbox);
vm.runInContext(block(src, 'function colorCompareHtml(p) {'), sandbox);
const html = p => sandbox.colorCompareHtml(p);

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};

const SKIN = [65.2, 8.1, 18.4];
const LIP = [55.0, 25.0, 12.0];
const setPkg = (over = {}) => {
  sandbox.Router.analysisPackage = {
    faceAnalysis: {
      skinTone: { lab: { L: SKIN[0], a: SKIN[1], b: SKIN[2] }, labReliable: true },
      lipLab: { L: LIP[0], a: LIP[1], b: LIP[2] },
      ...over,
    },
  };
};
const rgbOf = (L, a, b) => sandbox.Api.labToRgb(L, a, b);

console.log('\n=== 1. 品類要配對到正確的使用者顏色 ===');
setPkg();
const foundation = html({ type: 'foundations', lab: [70, 10, 20] });
check('粉底 → 比膚色', foundation.includes('您的膚色') && foundation.includes(rgbOf(...SKIN)));
check('粉底不會拿唇色來比', !foundation.includes(rgbOf(...LIP)));

const lipstick = html({ type: 'lipsticks', lab: [50, 40, 15] });
check('唇彩 → 比唇色', lipstick.includes('您的唇色') && lipstick.includes(rgbOf(...LIP)));
check('唇彩不會拿膚色來比', !lipstick.includes(rgbOf(...SKIN)));

for (const t of ['blushes', 'contouring', 'highlighters', 'eyeshadows']) {
  check(`${t} → 比膚色`, html({ type: t, lab: [70, 10, 20] }).includes('您的膚色'));
}

console.log('\n=== 2. 眉彩不比色（臉部分析端不產出眉色）===');
check('眉彩不顯示色塊', html({ type: 'eyebrows', lab: [34, 5, 8] }) === '',
  '拿膚色比眉彩是契約明文禁止的');

console.log('\n=== 3. 缺任一邊就不顯示 ===');
check('商品沒有 lab -> 不顯示', html({ type: 'foundations' }) === '');
check('商品 lab 長度錯 -> 不顯示', html({ type: 'foundations', lab: [70, 10] }) === '');
check('商品 lab 含非數字 -> 不顯示', html({ type: 'foundations', lab: [70, 'x', 20] }) === '');
sandbox.Router.analysisPackage = null;
check('沒有分析結果 -> 不顯示', html({ type: 'foundations', lab: [70, 10, 20] }) === '');
setPkg({ lipLab: null });
check('唇彩但沒有唇色資料 -> 不顯示', html({ type: 'lipsticks', lab: [50, 40, 15] }) === '');

console.log('\n=== 4. LAB 兩種格式都要接（分析結果格式不一定）===');
setPkg();
const asObj = html({ type: 'foundations', lab: [70, 10, 20] });
sandbox.Router.analysisPackage = {
  faceAnalysis: { skinTone: { lab: SKIN, labReliable: true }, lipLab: LIP },
};
const asArr = html({ type: 'foundations', lab: [70, 10, 20] });
check('{L,a,b} 與 [L,a,b] 產生相同結果', asObj === asArr && asObj !== '');

console.log('\n=== 5. 膚色不可信時要說出來 ===');
setPkg({ skinTone: { lab: { L: SKIN[0], a: SKIN[1], b: SKIN[2] }, labReliable: false } });
const unreliable = html({ type: 'foundations', lab: [70, 10, 20] });
check('顯示警告', unreliable.includes('膚色取樣可能不準'));
check('仍然顯示色塊（值還是目前最好的估計）', unreliable.includes('cc-dot'));
// 唇色不受膚色可信度影響
setPkg({ skinTone: { lab: { L: SKIN[0], a: SKIN[1], b: SKIN[2] }, labReliable: false } });
check('唇彩不會被膚色的可信度旗標影響',
  !html({ type: 'lipsticks', lab: [50, 40, 15] }).includes('膚色取樣可能不準'));

console.log('\n=== 6. 兩個色塊必須是不同顏色（否則比對沒有意義）===');
setPkg();
const h = html({ type: 'foundations', lab: [40, 20, 30] });
const dots = [...h.matchAll(/background:(rgb\([^)]+\))/g)].map(m => m[1]);
check('產生兩個色塊', dots.length === 2, dots.join(' vs '));
check('兩個顏色不同', dots[0] !== dots[1]);

console.log('\n=== 7. 用真實推薦資料驗一次 ===');
const livePath = path.join(ROOT, 'tests/_live_recommend_sample.json');
if (fs.existsSync(livePath)) {
  setPkg();
  const live = JSON.parse(fs.readFileSync(livePath, 'utf8'));
  const ps = live.withBrow.analysisPackage?.recommendations?.products || [];
  const withLab = ps.filter(p => Array.isArray(p.lab) && p.lab.length === 3);
  const shown = withLab.filter(p => html(p) !== '');
  const brows = ps.filter(p => p.type === 'eyebrows');
  console.log(`     有 lab 的商品 ${withLab.length} 件，其中 ${shown.length} 件顯示色塊`);
  check('有 lab 的非眉彩商品都能顯示',
    shown.length === withLab.filter(p => p.type !== 'eyebrows').length);
  check('眉彩即使有 lab 也不顯示', brows.every(p => html(p) === ''), `${brows.length} 件眉彩`);
} else {
  console.log('  (略過：沒有 _live_recommend_sample.json)');
}

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
