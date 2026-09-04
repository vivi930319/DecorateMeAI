// 後台查看會員收藏時，不需要再提供前台「查看妝容建議」入口。
// 前台自己的收藏仍然保留這個入口，因為它可以帶使用者前往完整建議頁。
//
// 用法：node tests/admin_saved_look_action_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');

let pass = 0;
let fail = 0;
const check = (name, condition, detail = '') => {
    console.log((condition ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    condition ? pass++ : fail++;
};

console.log('\n=== 後台收藏詳情不顯示前台入口 ===');
check('openLookModal 支援後台顯示模式', /function openLookModal\(item, options\)/.test(src));
check('後台模式會隱藏查看妝容建議按鈕',
    /\(!adminView&&beforeSrc&&afterSrc\)\?'<button[^']*lm-open-compare/.test(src));
check('後台模式不會綁定前台建議導覽',
    /if\(!adminView && openCompare\) openCompare\.onclick/.test(src));
check('後台收藏開啟詳情時有傳入後台模式',
    /openLookModal\(item, \{ adminView: true \}\)/.test(src));
check('前台收藏仍可開啟完整妝容建議',
    /openLookModal\(list\[\+card\.dataset\.look\]\)/.test(src));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
