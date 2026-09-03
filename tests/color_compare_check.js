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
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');
const apiSrc = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');

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

// 真正的 labToRgb，不是自己重寫一份——顏色換算錯了測試也該紅。
// _normalizeProduct 也一起抽進來：見底下第 5 節，這支測試最重要的一項要靠它。
vm.runInContext('var Api = { '
  + block(apiSrc, '    labToRgb(L, a, b) {') + ',\n'
  + block(apiSrc, '    _safeMatchReason(product) {') + ',\n'
  + block(apiSrc, '    _thumbUrl(raw, px = 400) {') + ',\n'
  + block(apiSrc, '    _normalizeProduct(product) {') + '\n };', sandbox);

vm.runInContext(blockUntil(src, 'const COMPARE_SOURCE = Object.freeze(', '});'), sandbox);
vm.runInContext(block(src, 'function compareKindOf(p) {'), sandbox);
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

// 跟 router.js 的 COMPARE_SOURCE／isFoundationProduct 對齊。這裡列一份是為了讓
// 第 7 節能對真實資料判斷「這件是不是粉底」；兩邊不一致時這支測試會先紅。
const FOUNDATION_TYPES = new Set(['foundations', 'foundation', 'base', '底妝']);

console.log('\n=== 1. 只有粉底做色彩比對 ===');
setPkg();
const foundation = html({ type: 'foundations', lab: [70, 10, 20] });
check('粉底 → 比膚色', foundation.includes('您的膚色') && foundation.includes(rgbOf(...SKIN)));
check('粉底不會拿唇色來比', !foundation.includes(rgbOf(...LIP)));

// 色彩比對只做粉底。其他品類即使帶了 lab 也不顯示色塊——
// 見 COMPARE_SOURCE 的註解：粉底之外的品類，商品色與使用者膚色之間沒有
// 「應該接近」的關係（唇彩、眼影是選色，不是配色），比出來的數字會被讀成
// 「這支適不適合你」，而那不是它的意思。
const lipstick = html({ type: 'lipsticks', lab: [50, 40, 15] });
check('唇彩不比色', lipstick === '', '唇彩是選色不是配色，比出來的 ΔE 會被誤讀');
check('唇彩也不會拿膚色來比', !lipstick.includes(rgbOf(...SKIN)));

for (const t of ['blushes', 'contouring', 'highlighters', 'eyeshadows']) {
  check(`${t} 不比色`, html({ type: t, lab: [70, 10, 20] }) === '');
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
  // 只有粉底會顯示。用真實資料驗這一條，是因為線上商品的 type 欄位不一定正規化過
  // （有中文、有英文、有 apiType 與 type 不一致），而那正是色彩比對最容易漏接的地方。
  const foundations = withLab.filter(p => FOUNDATION_TYPES.has(String(p.apiType || p.type || p.cat || '').toLowerCase()));
  console.log(`     有 lab 的商品 ${withLab.length} 件，其中 ${shown.length} 件顯示色塊`
    + `（粉底 ${foundations.length} 件）`);
  check('顯示色塊的都是粉底', shown.every(p =>
    FOUNDATION_TYPES.has(String(p.apiType || p.type || p.cat || '').toLowerCase())));
  check('眉彩即使有 lab 也不顯示', brows.every(p => html(p) === ''), `${brows.length} 件眉彩`);
} else {
  console.log('  (略過：沒有 _live_recommend_sample.json)');
}

console.log('\n=== 8. 走過 _normalizeProduct 之後仍然顯示 ===');
// 這一節是 2026-08-29 補的，補的是這支測試自己漏掉的那一步。
//
// 使用者回報「粉底液出來的時候沒有膚色色塊」。上面每一項都是綠的，因為它們餵的是
// 手寫的 `{ type: 'foundations', lab: [...] }`——而畫面上的商品**全都經過
// Api._normalizeProduct**，那個函式回的物件裡沒有 `type`，英文 slug 存在 `apiType`。
// colorCompareHtml 當時查的是 `p.type || p.cat`，於是永遠查不到，色塊對每一件真實
// 商品都不顯示，而測試一路綠燈。
//
// 所以這一節一律**先正規化再驗**：測的是使用者真的會看到的那個物件。
setPkg();
const asShipped = (raw) => html(sandbox.Api._normalizeProduct(raw));

const apiFoundation = { id: 915, type: 'foundations', category: '底妝', name: '粉底',
  lab: [75.78, 5.94, 17.45], shadeCode: 'PO-03' };
const shippedFoundation = asShipped(apiFoundation);
check('正規化後的粉底仍然顯示色塊', shippedFoundation !== '');
check('而且比的是膚色', shippedFoundation.includes('您的膚色'));
check('用的是商品自己的 lab', shippedFoundation.includes(rgbOf(75.78, 5.94, 17.45)));

const apiLipstick = { id: 2, type: 'lipsticks', category: '唇彩', name: '唇膏', lab: [45.88, 34, 26] };
const shippedLipstick = asShipped(apiLipstick);
// 正規化過的唇膏一樣不比色。這一條守的是「正規化不能變成繞過限制的後門」——
// 商品經過 asShipped() 之後欄位會補齊，如果 COMPARE_SOURCE 哪天多收了唇彩，
// 這裡會先紅。
check('正規化後的唇膏仍然不比色', shippedLipstick === '');

// 正規化後的物件身上就是沒有 `type`。這一項把那個事實釘住——
// 哪天有人「順手」把 compareKindOf 改回只讀 p.type，這裡會紅。
const normalized = sandbox.Api._normalizeProduct(apiFoundation);
check('正規化後沒有 type 欄位（英文 slug 在 apiType）',
  normalized.type === undefined && normalized.apiType === 'foundations');
check('cat 是中文，單獨拿它查英文表會落空', normalized.cat === '底妝');
check('compareKindOf 認得 apiType', sandbox.compareKindOf(normalized) === 'skin');
// 中文分類也要認得：推薦端有時只給 category 不給 type。
// 中文分類只放行底妝。唇彩回 null 是刻意的：留著中文鍵會讓未正規化的資料
// 從分類名繞過「只比粉底」的限制。
check('中文分類只放行底妝', sandbox.compareKindOf({ cat: '底妝' }) === 'skin'
  && sandbox.compareKindOf({ cat: '唇彩' }) === null);
// 眉彩不能因為新增了中文鍵就被放行——臉部分析端不產出眉色。
check('眉彩仍然沒有對應', !sandbox.compareKindOf({ cat: '眉毛彩妝' })
  && !sandbox.compareKindOf({ apiType: 'eyebrows' }));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
