// 風格選取狀態與渲染後的導向。
//
// 兩件事都是「使用者不確定剛才那一下有沒有生效」：
//   選了風格卻看不出來選了哪個
//   渲染完停在原頁，要自己去找結果
//
// 用法：node tests/style_and_render_flow_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8');
const compareHtml = fs.readFileSync(path.join(ROOT, 'pages/compare.html'), 'utf8');

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};
// main.css 有壓縮過的區段（.selected{ 沒有空格），所以兩種寫法都要找得到。
const rule = (sel) => {
    let i = css.indexOf(sel + ' {');
    if (i < 0) i = css.indexOf(sel + '{');
    if (i < 0) return '';
    return css.slice(i, css.indexOf('}', i) + 1);
};

console.log('');
console.log('=== 1. 選了哪個風格要一眼看得出來 ===');
// 先前只有 1px 邊框換色加一個 7px 小菱形——卡片本來就有邊框，
// 換個顏色幾乎看不出差別，使用者不確定自己選了沒。
const cardSel = rule('.style-card.selected');
check('風格卡有實心外環', /outline:\s*2px solid/.test(cardSel));
check('風格卡有明確的已選文字', css.includes("content:'✓ 已選擇'"));
const optSel = rule('.makeup-style-option.selected');
check('選風格 Modal 也有外環', /outline:2px solid/.test(optSel));
check('兩處都用主題變數（四套主題才會跟著換）',
  cardSel.includes('var(--gold-deep)') && optSel.includes('var(--gold-deep)'));
// 顏色寫死的話，深色主題上會是玫瑰棕配近黑，等於沒有標記
check('沒有寫死色碼', !/#[0-9a-fA-F]{3,6}/.test(cardSel + optSel));

console.log('');
console.log('=== 2. 四套主題都要定義得到那個顏色 ===');
// rose / jade / noir 各自覆蓋調色盤。少定義一個，那套主題就會繼承 :root 的
// 玫瑰棕，配在近黑底上看不見。
['rose', 'jade', 'noir'].forEach(theme => {
    const i = css.indexOf(`body[data-member-theme="${theme}"] {`);
    const body = i < 0 ? '' : css.slice(i, css.indexOf('\n}', i));
    check(`${theme} 有定義 --gold-deep`, /--gold-deep:/.test(body));
});

console.log('');
console.log('=== 3. 渲染完直接跳轉，不要再按一次 ===');
check('渲染成功後導向對比頁', /PageInit\.suggestion\(\);\s*[\r\n]\s*Router\.go\('compare'\)/.test(src));
// 跳過去之後按上一頁回來，看到的要是「重新生成妝容」而不是還停在「渲染中…」
check('跳轉前先重畫建議頁', src.includes('PageInit.suggestion();'));

console.log('');
console.log('=== 4. 對比頁不能有按不動的按鈕 ===');
// 送使用者過去卻讓他看到一顆死按鈕，比不跳轉更糟
check('沒有死掉的「生成妝容」', !compareHtml.includes('compareRenderBtn'));
check('也沒有它的兩個狀態列',
  !compareHtml.includes('compareRenderQuota') && !compareHtml.includes('compareRenderStatus'));
check('對比頁仍有它真正的功能', compareHtml.includes('compareHoldBtn'));

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
