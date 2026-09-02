// 流程被打斷之後，畫面不可以把兩次請求的結果縫在一起。
//
// 實際遇到的狀況：使用者選了「千金」，等待中手滑點到視窗外的空白處，視窗消失；
// 他以為停掉了，改選「男士白開水」重跑；千金那次的回應稍後才回來，於是畫面
// 變成「男士白開水妝容建議 ／ 針對鵝蛋臉骨相，以千金風格打造⋯⋯」——
// 標題是現在選的風格，內文是上一次的結果。
//
// 成因有兩層：
//   1. 進行中的視窗允許點背景關閉，那是一整片沒有提示的可點區域。
//   2. 非同步工作回來時只檢查「畫面上有沒有 journeyModal」，但那個 id 是所有
//      流程視窗共用的，第二次流程開的視窗會讓第一次的檢查照樣通過。
//
// 用法：node tests/journey_interruption_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/makeup-flow.js'), 'utf8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};

// 取出一個函式的內容：從函式標頭找到下一個同縮排的 `    }` 為止。
// 這個檔案是四格縮排的 IIFE，函式都在第一層，所以這樣切足夠準確。
const fnBody = (header) => {
    const start = src.indexOf(header);
    if (start < 0) return '';
    const end = src.indexOf('\n    }\n', start);
    return end < 0 ? src.slice(start) : src.slice(start, end);
};

console.log('');
console.log('=== 1. 進行中的視窗不給「點背景關閉」這個出口 ===');
// 右上角的 ✕ 一律保留：要離開仍然離得開，只是必須是一個明確的動作。
check('journeyShell 讓呼叫端決定能不能點背景關閉',
  /function journeyShell\(kicker, title, body, actions, dismissible = true\)/.test(src));
check('backdrop 監聽被 dismissible 包住',
  /if \(dismissible\) \{\s*\n\s*modal\.addEventListener\('click'/.test(src));
check('產生建議的視窗關掉這個出口',
  /'正在產生妝容建議'[\s\S]{0,400}?data-back>上一步<\/button>', false\)/.test(src));
check('妝容渲染的視窗也關掉',
  /'妝容渲染中'[\s\S]{0,1600}?data-back>上一步<\/button>', false\)/.test(src));
check('✕ 仍然綁著關閉', src.includes(".journey-dialog-close')?.addEventListener('click', removeJourneyModal)"));

console.log('');
console.log('=== 2. 每一次流程都認自己的號碼牌 ===');
check('有號碼牌', /let journeyToken = 0;/.test(src));
check('關掉視窗會讓仍在飛的請求過期',
  /journeyToken \+= 1;/.test(fnBody('    function removeJourneyModal()')));
check('號碼牌要比對「是不是我那一次」，不是「有沒有視窗」',
  /token === journeyToken/.test(fnBody('    function journeyIsCurrent(')));
// 這一條是本檔的重點：舊寫法只問畫面上有沒有 journeyModal，
// 第二次流程開的同名視窗會讓第一次的檢查通過，結果就被接到新流程上。
const staleGuard = (src.match(/if \(!document\.getElementById\('journeyModal'\)\) return;/g) || []).length;
check('建議與渲染都不再用「有沒有視窗」當守門員', staleGuard === 0,
  staleGuard ? `還有 ${staleGuard} 處舊寫法` : '');
const tokenGuard = (src.match(/if \(!journeyIsCurrent\(token\)\) return;/g) || []).length;
check('兩支流程的結果都認號碼牌', tokenGuard >= 2, `找到 ${tokenGuard} 處`);
check('進度計時器也認號碼牌，流程放棄就停',
  /if \(!journeyIsCurrent\(token\)\) \{ clearInterval\(timer\); return; \}/.test(src));

console.log('');
console.log('=== 3. 標題與內文必須出自同一次請求 ===');
// getStyle() 讀的是「現在選中哪張卡」，會隨著使用者重開風格視窗而變；
// 內文卻來自 analysisPackage，是「上一次成功回來的建議」。
check('記下這份建議是哪個風格產生的', /let resultStyleId = null;/.test(src));
check('建議成功時才寫入', /resultStyleId = Router\.selectedStyleId;/.test(src));
check('有一支專門解析「結果的風格」', /function resultStyle\(fallbackStyle\)/.test(src));
// 三處：完成視窗、續作卡片、結果頁標題。
const titled = (src.match(/resultStyle\(style\)\.name/g) || []).length;
check('三處標題都改用結果的風格', titled === 3, `找到 ${titled} 處`);
check('沒有殘留直接用當前選擇當標題的寫法',
  !/escapeHtml\(style\.name\)\}妝容建議/.test(src) && !/\$\{style\.name\}妝容建議`/.test(src));

console.log('');
console.log('=== 4. 不可以動到既有的資料結構與請求 ===');
// 號碼牌與 resultStyleId 只能活在這個檔案裡。一旦寫進 analysisPackage，
// 就會跟著 recommendProducts 送給後端，等於動到契約。
check('號碼牌沒有寫進 analysisPackage', !/journeyToken['"]?\s*:/.test(src));
check('resultStyleId 沒有寫進 analysisPackage', !/resultStyleId['"]?\s*:/.test(src));
check('建議請求的參數沒變',
  /style: style\.name,\s*\n\s*userNote: style\.tags\.join\('、'\)/.test(src));

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
