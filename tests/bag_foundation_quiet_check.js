// 化妝包已經有粉底時，不再提醒「資料庫有沒有相近色號」與色差（2026-09-28 使用者要求）。
// 以及「其他○○商品」視窗要全部列出、再標出哪些是化妝包內容，而不是把它們藏起來。
//
// 粉底的色號／色差提醒散在四個地方，少收一個畫面上就還會出現：
//   foundationNoticeHtml（推薦區上方）、colorCompareHtml（膚色對比）、
//   colorDiffInfo（色差說明入口）、recommendationCardHtml 的 headline（「目前商品清單中沒有相近色號」）
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = process.argv[2] || path.join(__dirname, '..');
// 先剝掉整行註解：守門測試用正則掃原始碼，註解裡提到的寫法會被自己抓到
const strip = src => src.replace(/\r\n/g, '\n').replace(/^\s*\/\/.*$/gm, '');
const router = strip(fs.readFileSync(path.join(root, 'js/router.js'), 'utf8'));
const plan = strip(fs.readFileSync(path.join(root, 'js/makeup-plan.js'), 'utf8'));

let failed = 0;
const check = (name, ok) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`); if (!ok) failed += 1; };

// bagHasFoundation 實際跑一次
const start = router.indexOf('function bagHasFoundation()');
const end = router.indexOf('function compareKindOf(p)');
check('找得到 bagHasFoundation 與 isFoundationProduct', start > 0 && end > start);
const box = { MakeupBag: null };
vm.createContext(box);
vm.runInContext(router.slice(start, end) + '\nglobalThis.__has = bagHasFoundation; globalThis.__isF = isFoundationProduct;', box);
const cat = k => ({ foundations: '底妝', lipsticks: '唇彩' })[String(k).split(':')[0]] || '';
box.MakeupBag = { localList: () => ['lipsticks:1'], categoryOf: cat };
check('化妝包沒有粉底 → false', box.__has() === false);
box.MakeupBag = { localList: () => ['lipsticks:1', 'foundations:9'], categoryOf: cat };
check('化妝包有粉底 → true', box.__has() === true);
check('底妝商品判斷', box.__isF({ cat: '底妝' }) && !box.__isF({ cat: '唇彩' }));

check('推薦區上方的粉底提示會收起', /foundationNoticeHtml\(\) \{[\s\S]{0,300}if \(bagHasFoundation\(\)\) return '';/.test(router));
check('膚色對比會收起', /function colorCompareHtml\(p\) \{[\s\S]{0,200}kind === 'skin' && bagHasFoundation\(\)/.test(router));
check('色差入口會收起', /function colorDiffInfo\(p\) \{[\s\S]{0,300}if \(bagHasFoundation\(\)\) return null;/.test(router));
check('卡片標語（沒有相近色號）會收起', /pr\.headline && !\(isFoundationProduct\(p\) && bagHasFoundation\(\)\)/.test(router));

check('其他○○商品：個人化那段不再濾掉化妝包已有的', /items = rec\.products \|\| \[\];/.test(plan));
check('其他○○商品：全部那段不再濾掉化妝包已有的', !/\.filter\(p => !p\.candidateKey \|\| !MakeupBag\.has\(p\.candidateKey\)\)/.test(plan));
check('其他○○商品：化妝包已有的標上「化妝包內容」', /pc-bag-badge">化妝包內容</.test(plan));

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n化妝包粉底與全部列出測試通過');
