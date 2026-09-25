// 反推風格的畫面不可以出現「跟排序矛盾」的數字。
//
// 2026-09-25：卡片上放了「第 N 推薦 · 由 M 件現有商品支持」，而 M 不是排序依據
// （分數才是）。實際畫面長這樣：
//
//   第 1 推薦  Soft Baddie   由 3 件支持
//   第 2 推薦  日雜清透       由 9 件支持   ← 比第 1 名多
//   第 4 推薦  病嬌          由 9 件支持
//
// 排序其實是對的（照 API 回的分數），但「支持」這個詞暗示件數就是理由，
// 數字又不遞減，使用者只會覺得排壞了。
//
// 現在改成：相對強度條（在本次結果內重新縮放，**必然遞減**）＋ 中性的件數描述。
// 這支盯兩件事：強度必須單調遞減、不可以再用因果語氣講件數。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/makeup-plan.js'), 'utf8').replace(/\r\n/g, '\n');

let failed = 0;
function check(label, ok, hint) {
  if (ok) { console.log(`  PASS ${label}`); return; }
  failed += 1;
  console.error(`  FAIL ${label}${hint ? `\n       ${hint}` : ''}`);
}

console.log('=== 反推風格的排序呈現 ===\n');

// ① 不可以用因果語氣描述件數
check(
  '件數不用「支持」這種因果語氣',
  !/件現有商品支持|件商品支持/.test(src),
  '件數不是排序依據，用「支持」會讓使用者以為它是，而件數不遞減時就顯得排壞了。' +
  '改用中性描述，例如「用到你的 N 件商品」。',
);

// ② 強度必須在本次集合內重新縮放，不能直接畫原始 score
check(
  '強度在本次結果內重新縮放',
  /Math\.max\(\.\.\.scores\)/.test(src) && /Math\.min\(\.\.\.scores\)/.test(src),
  '原始 score 是拿全資料集最大值正規化的，實測擠在 0.21~0.28——' +
  '直接畫長條會七個一樣長，等於沒說話。',
);

// ③ 把 strengthPct 抽出來實跑，確認單調遞減
const m = src.match(/const strengthPct = \(row\) => \{[\s\S]*?\n        \};/);
if (!m) throw new Error('找不到 strengthPct');

const sandbox = { Math, Number, console: { log() {} } };
vm.createContext(sandbox);
vm.runInContext(
  `let result = null;
   ${m[0]}
   globalThis.__run = (styles) => { result = { styles }; return styles.map(strengthPct); };`,
  sandbox,
);

const cases = [
  { name: '分數遞減（一般情況）', scores: [0.2767, 0.2299, 0.2182, 0.2086, 0.2086] },
  { name: '分數差距極小', scores: [0.2101, 0.2100, 0.2099] },
  { name: '全部同分', scores: [0.21, 0.21, 0.21] },
  { name: '只有一個風格', scores: [0.25] },
];

for (const c of cases) {
  const widths = sandbox.__run(c.scores.map(score => ({ score })));
  const monotonic = widths.every((w, i) => i === 0 || w <= widths[i - 1]);
  check(
    `${c.name}：強度不遞增  ${JSON.stringify(widths)}`,
    monotonic,
    '強度條比前一名長就會跟名次矛盾，使用者會覺得排序壞了。',
  );
  check(
    `${c.name}：最後一名仍看得見`,
    widths.every(w => w >= 15),
    '長度接近 0 會像「沒有資料」，而不是「相對弱一點」。',
  );
}

console.log(failed ? `\n${failed} 項未通過` : '\n排序呈現測試通過');
process.exitCode = failed ? 1 : 0;
