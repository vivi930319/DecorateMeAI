// 手機版上妝示範的建議抽屜（2026-09-28 使用者回報「手機點下去看不到妝容建議」）。
//
// 抽屜與底部導覽列都固定在畫面最下面。抽屜層級比導覽列低時，下緣會被蓋住——
// 而「你的○○建議」排在抽屜最下面，於是整段建議剛好看不到，也不會有任何錯誤。
// 這支直接比兩者的 z-index，任何一邊被改動導致順序反過來就會失敗。
const fs = require('fs');
const path = require('path');

const root = process.argv[2] || path.join(__dirname, '..');
const main = fs.readFileSync(path.join(root, 'css/main.css'), 'utf8');
const flow = fs.readFileSync(path.join(root, 'css/makeup-flow.css'), 'utf8');

let failed = 0;
const check = (name, ok, detail = '') => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok ? '' : ` ${detail}`}`); if (!ok) failed += 1; };

// .tabbar 規則裡的 z-index（可能換行寫）
const tabbarRule = [...main.matchAll(/\.tabbar\s*\{([^}]*)\}/g)].map(m => m[1]).find(body => /position\s*:\s*fixed/.test(body)) || '';
const tabZ = Number((tabbarRule.match(/z-index\s*:\s*(\d+)/) || [])[1]);
const sheetZ = Math.max(...[...flow.matchAll(/\.look-advice-sheet\.is-bottom\s*\{([^}]*)\}/g)]
    .map(m => Number((m[1].match(/z-index\s*:\s*(\d+)/) || [])[1]) || 0));

check('找得到底部導覽列的 z-index', Number.isFinite(tabZ), `（讀到 ${tabZ}）`);
check(`手機抽屜（${sheetZ}）蓋得過底部導覽列（${tabZ}）`, sheetZ > tabZ);
check('抽屜打開時收起右下角「?」', /body:has\(\.look-advice-sheet\.is-bottom:not\(\[hidden\]\)\)\s*\.help-fab\s*\{\s*display:\s*none/.test(flow));
check('手機抽屜的控制鈕排成一列三格', /\.look-advice-sheet\.is-bottom \.look-tutor-ctrl\s*\{[^}]*repeat\(3/.test(flow));

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n手機建議抽屜測試通過');
