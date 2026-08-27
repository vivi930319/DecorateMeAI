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
// 跳過去之後按上一頁回來，看到的要是「重新生成妝容」而不是還停在「渲染中…」


console.log('');
console.log('=== 3b. 等待中與失敗都不要給重試按鈕 ===');
// 放在失敗訊息旁邊的「重新產生」「重新生成」最容易被連按，而失敗多半不是
// 按一次就會好的原因（服務忙碌、額度、上游逾時）——連按只是把同一個錯誤
// 重打好幾次。建議走 Ollama、渲染走 Replicate（一次 60–150 秒且按次計費）。
// 掃的是程式本體，不是連註解一起——那幾行註解正好在解釋
// 「為什麼不能有重試按鈕」，連註解掃的話這段解釋自己會把測試弄紅。
// css_tokens_check 與 recommendation_contract_check 都踩過同一個坑。
const flow = fs.readFileSync(path.join(ROOT, 'js/makeup-flow.js'), 'utf8')
    .split(String.fromCharCode(10))
    .filter(line => !line.trim().startsWith('//'))
    .join(String.fromCharCode(10));
check('建議流程沒有「重新產生」按鈕', !flow.includes('>重新產生<'));
check('渲染流程沒有「重新生成」按鈕', !flow.includes('>重新生成<'));
// 等待中那顆 disabled 的主按鈕也不該在：看起來像主要動作卻按不下去
check('等待中沒有 disabled 的主按鈕',
  !flow.includes('disabled data-next') && !flow.includes('disabled data-result'));
// 失敗仍要有出口，而且要說明原因
check('失敗仍留「上一步」', flow.includes('data-back'));
check('失敗會寫出原因',
  flow.includes('目前無法完成建議') && flow.includes('生成失敗'));

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
