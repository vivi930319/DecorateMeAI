// 所有 var(--x) 都要真的有定義。
//
// CSS 對打錯的變數名不會報錯，也不會在主控台留下任何訊息——它只是把那個宣告
// 整條丟掉。2026-08-26 就這樣出過事：粉底色號那一區寫了 background:var(--paper-soft)，
// 而 --paper-soft 從來不存在，於是整塊沒有底色、直接融進頁面背景，
// 看起來像「這個功能沒做」。
//
// 這種錯誤不會被任何既有測試接住：HTML 產得出來、JS 不會炸、版面也沒破，
// 只是顏色不見了。所以要有一支專門掃它。
//
// 用法：node tests/css_tokens_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const css = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8');

// 註解裡會提到變數名（包括上面那段在講 --paper-soft 的說明），
// 掃之前先拿掉，否則解釋 bug 的文字自己會變成 bug。
const code = css.replace(/\/\*[\s\S]*?\*\//g, '');

const defined = new Set();
for (const m of code.matchAll(/(--[A-Za-z0-9-]+)\s*:/g)) defined.add(m[1]);

const used = new Map();          // 變數名 -> 出現次數
for (const m of code.matchAll(/var\(\s*(--[A-Za-z0-9-]+)\s*(,|\))/g)) {
    // var(--x, fallback) 有退路，少定義不會沒有顏色，所以不算問題。
    if (m[2] === ',') continue;
    used.set(m[1], (used.get(m[1]) || 0) + 1);
}

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};

console.log('');
console.log(`=== 掃到 ${defined.size} 個定義、${used.size} 個被使用的變數 ===`);

const missing = [...used.keys()].filter(v => !defined.has(v)).sort();
check('沒有用到未定義的變數', missing.length === 0,
    missing.length ? `未定義：${missing.join('、')}` : '');

// 粉底色號那一區是這次出事的地方，單獨再確認一次它有底色。
const heroBlock = /\.sr-hero\s*\{[^}]*\}/.exec(code);
check('.sr-hero 有 background', Boolean(heroBlock) && /background\s*:/.test(heroBlock[0]));
const scAnchor = /\.sc-anchor\s*\{[^}]*\}/.exec(code);
check('.sc-anchor 有 background', Boolean(scAnchor) && /background\s*:/.test(scAnchor[0]));

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
