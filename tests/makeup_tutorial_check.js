// 妝後照上的上妝示範（js/makeup-tutorial.js）與妝容建議頁的接點。
//
// 守的事：
//   1. 七種妝容各有自己的上妝計畫，而且每個部位按鈕都有對應的示範（或明確說明這個妝不畫）。
//      少了對應，按下去會什麼都不畫，看起來像壞掉。
//   2. 七種不能只是換色：使用者指定的幾個辨識特徵要在（港風紅唇最後上、病嬌下眼影＋下睫毛、
//      韓系臥蠶、日雜 Igari 眼下腮紅、Soft Baddie 眼尾比韓系上揚、男士白開水不畫腮紅）。
//   3. 漫畫塗鴉風的濃度沒有被調回原本那個會被照片吃掉的透明度。
//   4. 示範失敗時部位按鈕退回開建議視窗；建議改放在不擋臉的面板。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = process.argv[2] || path.join(__dirname, '..');
const flow = fs.readFileSync(path.join(root, 'js/makeup-flow.js'), 'utf8').replace(/\r\n/g, '\n');
const tutorSrc = fs.readFileSync(path.join(root, 'js/makeup-tutorial.js'), 'utf8');
const dataSrc = fs.readFileSync(path.join(root, 'js/data.js'), 'utf8');
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
const { PLANS, SKIPPED_PARTS } = box.MakeupTutorial || {};
check('MakeupTutorial 有匯出 create、PLANS', !!(PLANS && typeof box.MakeupTutorial.create === 'function'));

const dataBox = {};
vm.createContext(dataBox);
vm.runInContext(`${dataSrc}\nglobalThis.__ids = STYLES.map(s => s.id);`, dataBox);
const styleIds = dataBox.__ids;
const missingPlans = styleIds.filter(id => !PLANS[id]);
check(`七種妝容都有上妝計畫（${styleIds.join(',')}）`, !missingPlans.length, `缺：${missingPlans.join(',')}`);

const pinKeys = [...flow.matchAll(/\{\s*key:\s*'([a-z]+)',\s*side:/g)].map(m => m[1]);
check(`抓得到六個部位按鈕（${pinKeys.join(',')}）`, pinKeys.length === 6);
for (const id of styleIds) {
  const parts = new Set((PLANS[id] || []).map(s => s.part));
  const skipped = Object.keys((SKIPPED_PARTS || {})[id] || {});
  const gaps = pinKeys.filter(k => !parts.has(k) && !skipped.includes(k));
  check(`${id}：每個部位按鈕都有示範或說明`, !gaps.length, `沒有對應的：${gaps.join(',')}`);
}

const kinds = id => (PLANS[id] || []).map(s => s.kind);
const find = (id, kind) => (PLANS[id] || []).find(s => s.kind === kind) || {};
const hk = PLANS.hongKong || [];
check('港風：紅唇是最後一步，唇緣最後才描清楚', hk.length && hk[hk.length - 1].kind === 'lips' && hk[hk.length - 1].outlineLast === true);
check('病嬌：有下眼影與下睫毛', kinds('yandere').includes('lowerShadow') && kinds('yandere').includes('lashesLow'));
check('韓系：有臥蠶', kinds('koreanClean').includes('aegyo'));
check('日雜：腮紅是 Igari 眼下腮紅', find('japaneseClear', 'blush').mode === 'igari');
check('Soft Baddie 的眼尾比韓系上揚', (find('softBaddie', 'liner').wingUp || 0) > (find('koreanClean', 'liner').wingUp || 0));
check('男士白開水：不畫腮紅，而且有說明', !kinds('mensPlain').includes('blush') && !!SKIPPED_PARTS.mensPlain?.cheeks);
const lipColors = new Set(styleIds.map(id => (find(id, 'lips').color || []).join(',')));
check('七種妝容的唇色各不相同（不是共用一組只換名字）', lipColors.size === styleIds.length);

const tint = Number((tutorSrc.match(/const TINT_A = ([0-9.]+)/) || [])[1]);
check(`漫畫塗鴉風的底色濃度 ≥ 0.35（目前 ${tint}）`, tint >= 0.35, '原規格的 0.23 在照片上會被原本的妝色吃掉。');

check('部位按鈕在示範失敗時退回開建議視窗',
  /state === 'error'\) \{ openPartAdviceModal\(part\); return; \}/.test(flow));
check('部位建議改放在不擋臉的面板（與視窗共用同一份內容）',
  /function partAdviceContent\(/.test(flow) && /look-advice-sheet/.test(flow) && /partAdviceContent\(st\.part\)/.test(flow));
check('示範依這次的妝容', /styleId: resultStyleId \|\| Router\.selectedStyleId/.test(flow));
check('切到妝前會收起示範', /if \(!isAfter && tutor\) tutor\.hide\(\);/.test(flow));
check('index.html 在 makeup-flow.js 之前載入 makeup-tutorial.js',
  html.indexOf('js/makeup-tutorial.js') > 0 && html.indexOf('js/makeup-tutorial.js') < html.indexOf('js/makeup-flow.js'));
check('MediaPipe 版本有鎖定', /@mediapipe\/face_mesh@\d/.test(tutorSrc));

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n上妝示範測試通過');
