// 色差解釋 QA（契約 2026-08-26）的驗收清單，逐項釘住。
//
// 這一份的重點是「不能顯示什麼」多過「要顯示什麼」：色差是**視覺距離**，
// 不是命中率。把它說成準確率或「保證適合」，是在給一個這個數字撐不起的承諾，
// 而使用者會照著那句話去買。
//
// 用法：node tests/color_diff_qa_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');
const css = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8').replace(/\r\n/g, '\n');

const cut = (sig) => {
    const i = src.indexOf(sig);
    if (i < 0) throw new Error('找不到 ' + sig);
    let d = 0;
    for (let k = src.indexOf('{', i); k < src.length; k++) {
        if (src[k] === '{') d++;
        else if (src[k] === '}') { d--; if (!d) return src.slice(i, k + 1); }
    }
};

const sandbox = { escapeHtml: (s) => String(s), console };
vm.createContext(sandbox);
vm.runInContext(
    cut('function colorDiffInfo(p) {') + '\n'
    + cut('function colorDiffEntryHtml(p) {') + '\n'
    + 'globalThis.__info = colorDiffInfo; globalThis.__entry = colorDiffEntryHtml;', sandbox);
const info = sandbox.__info, entry = sandbox.__entry;

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};
const make = (cde) => ({ id: 'p1', recommendationPresentation: { colorDifferenceExplanation: cde } });

console.log('');
console.log('=== 1. 什麼時候該出現、什麼時候不該 ===');
check('粉底有色差 → 出現入口',
    entry(make({ value: 2.54, displayValue: '色差 2.5', level: '整體相近' })).includes('data-color-diff'));
// 眼影、腮紅、修容、打亮、眉彩是依妝容風格推薦的，後端一律回 null。
// 對一個不是靠顏色排出來的商品講色差，等於憑空給一個不存在的依據。
check('colorDifferenceExplanation 是 null → 完全隱藏', entry(make(null)) === '');
check('沒有 recommendationPresentation → 完全隱藏', entry({ id: 'p1' }) === '');
check('整個商品是 null → 不炸', entry(null) === '' && info(null) === null);

console.log('');
console.log('=== 2. value 為 0 必須顯示 ===');
// 這是最容易寫錯的一條：色差 0 是「完全相同」，是最好的結果。
// 用 `if (info.value)` 判斷的話，最好的那一筆會是唯一被藏起來的。
check('value: 0 → 仍然顯示', entry(make({ value: 0, displayValue: '色差 0', level: '非常接近' })).includes('data-color-diff'));
check('value: 0 → colorDiffInfo 不回 null', info(make({ value: 0 })) !== null);
check('value 缺少 → 隱藏', info(make({ displayValue: '色差 ?' })) === null);
check('value 是字串 → 隱藏', info(make({ value: '2.5' })) === null);
check('value 是 NaN → 隱藏', info(make({ value: NaN })) === null);

console.log('');
console.log('=== 3. 不得出現的措辭與做法 ===');
const modal = cut('function openColorDiffModal(product) {');
const all = modal + entry(make({ value: 1, displayValue: 'x', level: 'y' }));
check('沒有「準確率」', !all.includes('準確率'));
check('沒有「保證適合」', !all.includes('保證適合'));
check('沒有把色差換算成百分比', !/value\s*\/\s*\d|\*\s*100/.test(modal));
// 後端有 ranges，前端若自己再判一次，兩邊區間遲早不一致——
// 而不一致的樣子是「同一個 4.6，卡片說相近、視窗說有可見差異」。
check('不自行重算 level（不寫死區間數字）',
    !/value\s*[<>]=?\s*(2|5|10)\b/.test(modal));
check('level 直接取後端欄位', modal.includes('info.level'));
check('QA 直接用後端的 question／answer',
    modal.includes('x.question') && modal.includes('x.answer'));

console.log('');
console.log('=== 4. 內容要素 ===');
check('顯示比較對象', modal.includes('comparisonTarget'));
check('顯示 summary', modal.includes('info.summary'));
check('顯示 ranges 表', modal.includes('info.ranges') || modal.includes('ranges.length'));
// 整張表沒有標記的話，讀的人得自己拿數字去對區間——那正是他點進來想避免的事。
check('標出目前落在哪一段', modal.includes('cd-here') && css.includes('.cd-here'));
check('顯示 fullExplanation', modal.includes('fullExplanation'));
// min 與 minExclusive 兩種表示法都要照後端畫，不要自己補一個
check('區間的兩種下界都處理', modal.includes('minExclusive') && modal.includes('r.min'));

console.log('');
console.log('=== 5. 鍵盤與焦點（契約 §8.2）===');
check('Escape 可關閉', /ev\.key === 'Escape'/.test(modal));
check('開啟時焦點移入', modal.includes('closeBtn.focus()'));
check('關閉後焦點歸位', modal.includes('previouslyFocused'));
check('關閉時移除鍵盤監聽', modal.includes("removeEventListener('keydown'"));
check('點背景可關閉', modal.includes('ev.target === ov'));
check('有 aria-modal 與標題關聯',
    modal.includes('aria-modal="true"') && modal.includes('aria-labelledby="cdTitle"'));

console.log('');
console.log('=== 6. 行動版 Bottom Sheet ===');
check('行動版從下方滑上來', /#colorDiffModal\s*\{[^}]*align-items:\s*flex-end/.test(css));

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
