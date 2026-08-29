// 影像提供同意：畫面上說的範圍，必須跟後端實際存的東西一致。
//
// 這一段寫錯不會有任何錯誤訊息，只會讓使用者在不知情的狀況下交出一張認得出自己的
// 照片。後端的規則是分歧的——face_feedback.py 的 whole_image_parts 指定臉型存整張
// 正面照、側臉鼻型存整張側臉照，其餘部位存部位裁切。
//
// 這份測試原本檢查的是一張「分部位說明範圍」的表格。那個設計 2026-08-25 被拿掉了，
// 原因不是它寫錯——每一行都是真的——而是排版讓人讀成「主要是小裁切，臉型是例外」。
// 實測不是這樣：102 次分析裡有 46 次（45%）存了整張照片，因為臉型正是最多人修正的
// 部位。而且「只有那一小塊」會被讀成「認不出是我」，眼睛裁切並不成立。
//
// 所以現在的契約反過來：不分部位，一句話涵蓋最壞情況。測試跟著改成守這個契約，
// 而且要**主動擋掉舊寫法回來**——低估範圍的措辭比沒有說明更糟。
//
// 用法：node tests/consent_scope_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');
const css = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8').replace(/\r\n/g, '\n');

// 把同意區塊的樣板抽出來當函式跑。抄一份到測試裡的話，router.js 改壞了不會有人知道。
const start = src.indexOf('<div class="af-consent">');
const end = src.indexOf('</div>` : \'\'}', start);
if (start < 0 || end < 0) { console.log('找不到 af-consent 區塊'); process.exit(1); }
const tpl = src.slice(start, end + '</div>'.length);

const sandbox = { corrections: {}, predicted: {}, allowTraining: false, out: '' };
vm.createContext(sandbox);
const render = (corrections, predicted = {}) => {
  sandbox.corrections = corrections;
  sandbox.predicted = predicted;
  vm.runInContext('out = `' + tpl + '`;', sandbox);
  return sandbox.out;
};

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};

console.log('');
console.log('=== 1. 不論改哪個部位，說的都是同一件事 ===');
// 舊設計會依 corrections 變出不同的範圍說明。現在不該有這種分歧：
// 使用者是在勾選的當下做決定的，那時候就該知道最壞情況。
// 只留使用者看得到的字：HTML 註解裡正好寫著「為什麼不能說『只有那一小塊』」，
// 連註解一起掃，那段解釋自己會把測試弄紅。
const visible = (html) => html.replace(/<!--[\s\S]*?-->/g, '');
const onlyBrow = visible(render({ 眉型: '一字眉' }));
const onlyFace = visible(render({ 臉型: '圓形臉' }));
const both     = visible(render({ 眉型: '一字眉', 臉型: '圓形臉' }));
check('改眉型與改臉型看到的文案一致', onlyBrow === onlyFace);
check('改兩個也一樣', onlyFace === both);

console.log('');
console.log('=== 2. 講的是最壞情況，不是平均情況 ===');
check('明說會保存臉部影像', /你的臉部影像會被保存下來/.test(onlyBrow));
check('明說跟改哪個部位無關',
  /不論你修正的是哪一個部位[\s\S]{0,40}你臉上的影像/.test(onlyBrow));
check('說明用途是重新訓練', onlyBrow.includes('重新訓練'));

console.log('');
console.log('=== 3. 擋掉會低估範圍的舊措辭 ===');
// 「只有那一小塊」曾經是文案的一部分。它容易被讀成「認不出是我」，
// 而眼睛裁切並不成立——這句話一旦回來，同意就不再是知情的。
check('沒有「只有那一小塊」', !onlyBrow.includes('只有那一小塊'));
check('沒有分部位的範圍表格',
  !/眉型[\s\S]{0,30}部位裁切/.test(onlyBrow) && !/臉型[\s\S]{0,30}整張正面照/.test(onlyBrow));

console.log('');
console.log('=== 4. 勾選是明確同意，而且可以不勾 ===');
check('核取方塊存在', onlyBrow.includes('afAllowTraining'));
check('標籤是肯定句的同意', /我同意保存上述臉部影像/.test(onlyBrow));
// 不勾也能送出修正：把同意綁成送出的前提，等於用功能換同意。
check('說明不勾也能送出', /不勾選也能送出修正/.test(onlyBrow));

console.log('');
console.log('=== 5. 保存之後怎麼處理，也要在同一個地方講完 ===');
check('說明不會公開、不給第三方', /不會公開[\s\S]{0,20}不會提供給第三方/.test(onlyBrow));
check('說明刪帳號會一併移除', /刪除帳號時一併移除/.test(onlyBrow));
// 這句是對管理員後台那條「排除就真的刪 GCS」的承諾，兩邊要對得上。
check('說明不採用時影像會被刪除', /不採用[\s\S]{0,20}刪除/.test(onlyBrow));

console.log('');
console.log('=== 6. 沒有修正就不該問同意 ===');
// 沒有修正就沒有要存的東西，這時候跳出同意書只會訓練使用者無視它。
// 這個守衛寫在樣板**外面**，抽出來的樣板裡看不到它，所以直接查原始碼。
check('沒有 corrections 時不出現同意區塊',
  /\$\{Object\.keys\(corrections\)\.length \? `\s*<div class="af-consent">/.test(src));

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
