// CSS 結構檢查：抓「選擇器清單被切斷」這一類的錯誤。
//
// 由來（2026-08-28，後台整個介面壞掉）：
//
//   body.admin-mode .topbar,
//   body.admin-mode .brand-watermark,
//   body.admin-mode .watermark-stamp { display:none !important; }   ← 宣告在最後一行
//   body.admin-mode .app-shell { background:#f3f5f7; }
//
// 移除浮水印時把最後那一行刪掉，宣告區塊跟著不見，整串選擇器改去接下一條規則：
// 後台不但沒有隱藏那些裝飾，還把它們一起塗成淺灰底。CSS 不會報錯，大括號也依然平衡，
// 只有畫面知道出事了——這正是最花時間的一種壞法。
//
// 用法：node tests/css_structure_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const raw = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8').replace(/\r\n/g, '\n');
// 註解會夾在選擇器之間（合法），先移掉再看結構，否則會被誤判成斷點。
const css = raw.replace(/\/\*[\s\S]*?\*\//g, '');
const lines = css.split('\n');

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};

// 一行是「選擇器清單的一員」而不是「多行屬性值的一段」的判準：
// 屬性值那幾行必定在某個已開啟的 {} 裡面，選擇器則在外面。用大括號深度區分最準。
const dangling = [];
let depth = 0;
for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();
    const atTopLevel = depth <= 0;
    depth += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
    if (!atTopLevel || !trimmed.endsWith(',')) continue;
    // 往下找這串選擇器的宣告區塊；中間只允許其他選擇器行
    let j = i + 1, found = false;
    while (j < lines.length && j < i + 60) {
        const t = lines[j].trim();
        if (t === '' || t.startsWith('}')) break;      // 被切斷了
        if (t.includes('{')) { found = true; break; }  // 正常收尾
        j++;
    }
    if (!found) dangling.push(`第 ${i + 1} 行「${trimmed}」`);
}

console.log('=== 1. 沒有懸空的選擇器清單 ===');
check('每一串以逗號結尾的選擇器都找得到宣告區塊',
    dangling.length === 0, dangling.join('； '));

console.log('');
console.log('=== 2. 大括號平衡 ===');
const open = (css.match(/\{/g) || []).length;
const close = (css.match(/\}/g) || []).length;
check('{ 與 } 數量相同', open === close, `${open} 開 / ${close} 收`);

console.log('');
console.log('=== 3. 後台不能看到美妝站的裝飾層 ===');
// 把每一條規則切成「選擇器清單 → 宣告」，再看某個選擇器落在哪一條規則裡。
// 用字串比對而不是正則：這一份要驗的就是「選擇器接到哪個宣告」，
// 拿一個容易寫錯的正則去驗另一個容易寫錯的東西，錯了也看不出來。
const rules = [];
{
    let buf = '';
    let d = 0;
    for (const ch of css) {
        if (ch === '{') {
            d++;
            if (d === 1) { rules.push({ sel: buf.trim(), body: '' }); buf = ''; continue; }
        } else if (ch === '}') {
            d--;
            if (d === 0) { buf = ''; continue; }
        }
        if (d === 1 && rules.length) rules[rules.length - 1].body += ch;
        else if (d === 0) buf += ch;
    }
}
const ruleFor = (selector) => rules.find(r => r.sel.split(',').some(s => s.trim() === selector));

const mustHide = [
    'body.admin-mode .topbar',
    'body.admin-mode .topbar-menu-backdrop',
    'body.admin-mode .brand-watermark',
    'body.admin-mode .signal-watermark',
    'body.admin-mode .cursor-glow',
];
mustHide.forEach(sel => {
    const rule = ruleFor(sel);
    const hidden = !!rule && rule.body.replace(/\s+/g, '').includes('display:none!important');
    check(`後台隱藏 ${sel.replace('body.admin-mode ', '')}`, hidden,
        rule ? `目前接到：{${rule.body.trim().slice(0, 46)}…}` : '找不到這條規則');
});

// 反面：這幾個不能變成 app-shell 那條背景規則的一員。這正是壞掉時的樣子。
const shellRule = ruleFor('body.admin-mode .app-shell');
check('app-shell 的背景規則沒有夾帶裝飾層選擇器',
    !!shellRule && !mustHide.some(sel => shellRule.sel.includes(sel.replace('body.admin-mode ', ''))),
    shellRule ? shellRule.sel.replace(/\s+/g, ' ').slice(0, 80) : '找不到 app-shell 規則');

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
