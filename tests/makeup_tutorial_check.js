// 妝後照上的上妝示範（js/makeup-tutorial.js）與妝容建議頁的接點。
//
// 守三件事：
//   1. 頁面上六個部位按鈕（makeup-flow.js 的 pinLayout）每一個都有對應的示範步驟——
//      少了對應，按下去會什麼都不畫，看起來像壞掉。
//   2. 示範失敗時，部位按鈕要退回開建議視窗，不能變成沒反應。
//   3. 規格指定的上妝順序與配色沒有被改掉（使用者已在真臉上校正過）。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = process.argv[2] || path.join(__dirname, '..');
const flow = fs.readFileSync(path.join(root, 'js/makeup-flow.js'), 'utf8').replace(/\r\n/g, '\n');
const tutorSrc = fs.readFileSync(path.join(root, 'js/makeup-tutorial.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

let failed = 0;
const check = (name, ok, why = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${ok || !why ? '' : `\n     ${why}`}`);
  if (!ok) failed += 1;
};

const box = { window: {}, document: {} };
box.window = box;
vm.createContext(box);
vm.runInContext(tutorSrc, box);
const STEPS = box.MakeupTutorial && box.MakeupTutorial.STEPS;
check('MakeupTutorial 有匯出 create 與 STEPS', !!(STEPS && typeof box.MakeupTutorial.create === 'function'));

const pinKeys = [...flow.matchAll(/\{\s*key:\s*'([a-z]+)',\s*side:/g)].map(m => m[1]);
check(`抓得到六個部位按鈕（得到 ${pinKeys.join(',')}）`, pinKeys.length === 6);
const parts = new Set(STEPS.map(s => s.part));
const missing = pinKeys.filter(k => !parts.has(k));
check('每個部位按鈕都有示範步驟', !missing.length, `沒有對應的：${missing.join(',')}`);

const order = STEPS.map(s => s.id).join(' → ');
check(`上妝順序照規格（${order}）`,
  order === 'base → brows → eyeshadow-base → eyeshadow-deep → eyeliner → blush → contour → lips');
const color = id => (STEPS.find(s => s.id === id) || {}).color?.join(',');
check('口紅是規格的珊瑚紅 252,79,75', color('lips') === '252,79,75');
check('腮紅是規格的草莓桃粉 255,124,144', color('blush') === '255,124,144');

check('部位按鈕在示範失敗時退回開建議視窗',
  /state === 'error'\) \{ openPartAdviceModal\(part\); return; \}/.test(flow));
check('切到妝前會收起示範', /if \(!isAfter && tutor\) tutor\.hide\(\);/.test(flow));
check('index.html 在 makeup-flow.js 之前載入 makeup-tutorial.js',
  html.indexOf('js/makeup-tutorial.js') > 0 && html.indexOf('js/makeup-tutorial.js') < html.indexOf('js/makeup-flow.js'));
check('MediaPipe 版本有鎖定', /@mediapipe\/face_mesh@\d/.test(tutorSrc));

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n上妝示範測試通過');
