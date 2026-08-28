// 掃出「用到不存在的變數」——這一類錯誤 `node --check` 抓不到，因為語法完全合法。
//
// 由來（2026-08-28，模型訓練批次永遠載不出來）：
//
//     fbSummary.textContent = `…待覆核 ${pending}、已採用 ${accepted}、…`
//
// 覆核分頁從三個變成四個時，桶子改成 pending／training／trained／rejected，
// 但這一行還留著舊的 `accepted`。每次重畫都在這裡拋 ReferenceError，
// 而它拋的位置很殘忍：卡片與計數在它之前就畫完了，畫面看起來完全正常，
// 它之後的每一行卻都沒執行——包括呼叫端下一行的 loadTrainingRuns()。
// 症狀是「訓練批次區永遠停在佔位字」，看起來像後端沒資料；
// 實際上那支 API 從頭到尾沒有被呼叫過一次（Cloud Run 記錄裡一筆都沒有）。
//
// 為什麼用 eslint 而不自己寫：正確判斷一個名字是不是自由變數，要完整的作用域分析
// （參數、解構、catch 綁定、樣板字串裡的運算式、物件鍵…）。自己用正則湊出來的版本
// 我試過，413 個誤報——一個會叫但都在亂叫的檢查，比沒有檢查更糟，因為它會被忽略。
//
// 沒有 eslint 時明確跳過並說出來，不假裝通過。
//
// 用法：node tests/undefined_names_check.js <web_frontend 路徑>
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const JS_DIR = path.join(ROOT, 'js');

// 這兩支不共用主頁面的全域空間：config.local.js 只存在於本機，
// image-worker.js 跑在 Worker 裡（它的 self 不是 window）。
const SEPARATE = new Set(['config.local.js', 'image-worker.js']);

const files = fs.readdirSync(JS_DIR)
    .filter(f => f.endsWith('.js') && !SEPARATE.has(f))
    .sort();

// 頁面上的 <script> 共用同一個全域空間：router.js 用得到 api.js 宣告的 Api。
// eslint 一次只看一個檔案，所以要先把跨檔案的頂層宣告收集起來餵給它。
const globals = {};
const declare = (name) => { globals[name] = 'readonly'; };
for (const f of files) {
    // 不去註解。用正則移除 /* */ 會被程式裡的正則字面值（例如 /^https?:\/\//）
    // 帶偏，一路吃到下一個 */，把中間好幾百行真正的宣告一起刪掉——
    // 收集不到 escapeHtml 這種到處在用的函式，整份報告就變成一堆假警報。
    // 註解裡剛好有頂層 `function X` 的話最多只是多宣告一個名字，無害。
    const src = fs.readFileSync(path.join(JS_DIR, f), 'utf8');
    for (const m of src.matchAll(/^(?:const|let|var)\s+([A-Za-z_$][\w$]*)/gm)) declare(m[1]);
    for (const m of src.matchAll(/^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)/gm)) declare(m[1]);
    for (const m of src.matchAll(/^class\s+([A-Za-z_$][\w$]*)/gm)) declare(m[1]);
    for (const m of src.matchAll(/\bwindow\.([A-Za-z_$][\w$]*)\s*=/g)) declare(m[1]);
}
// 瀏覽器內建。列得寬一點：少一個就多一個假警報，而這份檢查要抓的是
// 「改名沒改到、打錯字」，不是「用了哪些冷門 API」。
`window document navigator location history console
setTimeout clearTimeout setInterval clearInterval queueMicrotask
requestAnimationFrame cancelAnimationFrame requestIdleCallback
fetch Headers Request Response AbortController FormData Blob File FileReader URL URLSearchParams
Image Audio Event CustomEvent MessageChannel BroadcastChannel Worker
MutationObserver IntersectionObserver ResizeObserver PerformanceObserver
localStorage sessionStorage indexedDB caches crypto performance screen matchMedia getComputedStyle
alert confirm prompt atob btoa structuredClone reportError
CSS DOMParser XMLSerializer XMLHttpRequest TextEncoder TextDecoder
HTMLElement HTMLCanvasElement HTMLImageElement HTMLInputElement HTMLVideoElement
Node NodeList Element DocumentFragment DataTransfer
ImageData ImageBitmap createImageBitmap OffscreenCanvas CanvasRenderingContext2D MediaRecorder
AbortSignal`
    .trim().split(/\s+/).forEach(declare);

// index.html 的行內 <script> 也在同一個全域空間裡宣告了幾個函式。
// 它們不在 js/ 底下，掃不到，但 router.js 確實用得到——而且用的時候都有
// `typeof X === 'function'` 擋著（行內腳本可能還沒跑）。列在這裡，
// 不是為了放行，是為了讓真正打錯字的名字不會被這幾個假警報淹掉。
['closeTopbarMenu'].forEach(declare);

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};

console.log('=== 不能用到不存在的名字 ===');

const cfgPath = path.join(os.tmpdir(), `dm-undef-eslint-${process.pid}.mjs`);
fs.writeFileSync(cfgPath, 'export default [{\n'
    + '  languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: '
    + JSON.stringify(globals) + ' },\n'
    + '  rules: { "no-undef": "error" }\n}];\n', 'utf8');

const run = spawnSync('npx', ['--no-install', 'eslint', '--no-config-lookup', '-c', cfgPath,
    ...files.map(f => path.join(JS_DIR, f))],
    { encoding: 'utf8', shell: process.platform === 'win32' });
fs.unlinkSync(cfgPath);

const output = `${run.stdout || ''}${run.stderr || ''}`;
if (run.error || /could not determine executable|not found|Cannot find/i.test(output)) {
    console.log('  SKIP 找不到 eslint，這一項沒有檢查');
    console.log('       安裝方式：npm i -D eslint    （不要因為裝不起來就把這項檢查拿掉）');
    console.log(`\n${pass}/${pass + fail} passed（1 項跳過）`);
    process.exit(0);
}

const problems = output.split('\n').filter(l => /\bno-undef\b/.test(l))
    .map(l => l.trim().replace(/\s+/g, ' '));
check('每個名字都找得到宣告', problems.length === 0,
    problems.length ? '\n    ' + problems.slice(0, 15).join('\n    ')
        + (problems.length > 15 ? `\n    …共 ${problems.length} 處` : '') : '');

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
