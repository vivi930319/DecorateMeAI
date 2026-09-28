// 新手實作導覽（js/guided-tour.js）：它框的是**真實畫面上的元素**。
// 有人改了按鈕的 id 或 data 屬性，導覽不會報錯，只會框不到東西、卡在那一步——
// 所以把每一步依賴的選擇器，逐一對照它真正出現的原始檔。
const fs = require('fs');
const path = require('path');

const root = process.argv[2] || path.join(__dirname, '..');
const read = f => fs.readFileSync(path.join(root, f), 'utf8');
const tour = read('js/guided-tour.js');
const index = read('index.html');
const analysis = read('pages/analysis.html');
const flow = read('js/makeup-flow.js');
const plan = read('js/makeup-plan.js');

let failed = 0;
const check = (name, ok) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`); if (!ok) failed += 1; };

const ids = [...tour.matchAll(/\{ id: '([a-zA-Z]+)'/g)].map(m => m[1]);
check(`步驟順序：${ids.join(' → ')}`,
  ids.join(',') === 'intro,goAnalysis,upload,analyze,waitAnalysis,goStyle,pickPlan,waitAdvice,render,pins,tutorAll,products,bag');

// 每一步框的東西都要真的存在
const deps = [
  ['臉部分析的選單連結', index, 'data-page="analysis"'],
  ['手機／下拉選單按鈕', index, 'class="topbar-menu-toggle"'],
  ['會員中心連結（化妝包入口）', index, 'data-page="profile"'],
  ['上傳區 #uploadBox', analysis, 'id="uploadBox"'],
  ['照片預覽 #preview', analysis, 'id="preview"'],
  ['開始分析 #analyzeBtn', analysis, 'id="analyzeBtn"'],
  ['分析進度 #analysisSteps', analysis, 'id="analysisSteps"'],
  ['選擇風格 #goStyleBtn', analysis, 'id="goStyleBtn"'],
  ['規劃方式視窗 #makeupPlanModal', plan, "shell('makeupPlanModal'"],
  ['化妝包推薦視窗 #bagStyleModal', plan, "shell('bagStyleModal'"],
  ['七選一視窗 #makeupStyleModal', flow, "modal.id = 'makeupStyleModal'"],
  ['建議流程視窗 #journeyModal', flow, "modal.id = 'journeyModal'"],
  ['開始渲染 [data-render]', flow, 'data-render>'],
  ['部位標籤 .look-pin', flow, 'class="look-pin '],
  ['上妝示範 [data-tutor-all]', flow, 'data-tutor-all'],
  ['結果頁動作列 .lookbook-actions', flow, 'class="lookbook-actions"'],
];
for (const [name, src, needle] of deps) check(`${name} 存在`, src.includes(needle));

check('聚光燈不擋點擊（使用者要能自己操作）', /\.gt-root \{[^}]*pointer-events: none/.test(read('css/main.css')));
check('層級高過所有視窗（360）', /\.gt-root \{[^}]*z-index: 10050/.test(read('css/main.css')));
check('看不到的元素（收起的抽屜）不當成目標', /checkVisibility\(/.test(tour) && /r\.right <= 0 \|\| r\.left >= window\.innerWidth/.test(tour));
check('進度會存下來、可以接續', /PROGRESS_KEY/.test(tour) && /function resumeIfUnfinished/.test(tour));
check('index.html 在 help-center.js 之前載入 guided-tour.js',
  index.indexOf('js/guided-tour.js') > 0 && index.indexOf('js/guided-tour.js') < index.indexOf('js/help-center.js'));

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n新手實作導覽測試通過');
