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
  // 2026-09-29：先看完整示範再看單一部位（tutorAll 在 pins 前）；系統每個功能都要實際做一次
  ids.join(',') === 'intro,goAnalysis,upload,analyze,waitAnalysis,checkResult,tryCorrect,feedback,goStyle,pickPlan,waitAdvice,render,checkLook,tutorAll,pins,saveLook,share,products,addBag,openDetail,favProduct,addCart,openCart,favorites,history,checkin,referral,bag,bagSearch,help,feedbackBox');

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
  // 2026-09-28「做錯要帶回去重做」：問題偵測讀的畫面文字與欄位
  ['分析結果格 .result-grid', analysis, 'class="result-grid"'],
  ['膚色不準提示 #skinReliabilityWarn', analysis, 'id="skinReliabilityWarn"'],
  ['妝後照 .look-portrait-frame', flow, 'class="look-portrait-frame"'],
  ['查看推薦商品 [data-products]', flow, 'data-products>'],
  ['建議失敗的說明文字', flow, '目前無法完成建議'],
  ['建議缺分析的說明文字', flow, '目前沒有臉部分析結果'],
  ['妝後照失敗的說明文字', flow, '生成失敗：'],
  ['分析失敗記下錯誤碼與時間', read('js/router.js'), 'errorCode: err.code || null, failedAt:'],
];
for (const [name, src, needle] of deps) check(`${name} 存在`, src.includes(needle));

// 2026-09-29「滑鼠或滑太快跟不上」：實測舊版捲動中框落後目標中位數 46px、最多 97px。
// 原因是框與小卡一直掛著 0.25 秒的位置過渡，而且只聽 window 的 scroll。
const mainCss = read('css/main.css');
// 只認行首的規則本身：`.gt-root.gt-moving .gt-card { … }` 也含 `.gt-card {`，而那條本來就該有過渡
const ruleOf = (sel) => (mainCss.match(new RegExp('^' + sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}', 'm')) || [])[1] || '';
check('每一格畫面追蹤目標位置（requestAnimationFrame）', /function follow\(\)/.test(tour) && /requestAnimationFrame\(follow\)/.test(tour));
check('聚光框平常沒有位置過渡（捲動時不會一直追）', !/transition/.test(ruleOf('.gt-hole')));
check('說明小卡平常沒有位置過渡', !/transition/.test(ruleOf('.gt-card')));
check('只有換目標時才滑過去（.gt-moving）', /\.gt-root\.gt-moving \.gt-hole \{[^}]*transition/.test(mainCss) && /markMoving\(\)/.test(tour));
check('閃爍不再動 9999px 的遮罩陰影', !/@keyframes gtPulse \{[^}]*9999px/.test(mainCss));
check('停止導覽時取消追蹤、拿掉監聽', /cancelAnimationFrame\(rafId\)/.test(tour) && /removeEventListener\('resize', onResize\)/.test(tour));
check('聚光燈不擋點擊（使用者要能自己操作）', /\.gt-root \{[^}]*pointer-events: none/.test(read('css/main.css')));
check('層級高過所有視窗（360）', /\.gt-root \{[^}]*z-index: 10050/.test(read('css/main.css')));
check('看不到的元素（收起的抽屜）不當成目標', /checkVisibility\(/.test(tour) && /r\.right <= 0 \|\| r\.left >= window\.innerWidth/.test(tour));
check('進度會存下來、可以接續', /PROGRESS_KEY/.test(tour) && /function resumeIfUnfinished/.test(tour));
check('index.html 在 help-center.js 之前載入 guided-tour.js',
  index.indexOf('js/guided-tour.js') > 0 && index.indexOf('js/guided-tour.js') < index.indexOf('js/help-center.js'));

// ── 實際跑一次步驟邏輯：做錯了要被抓到、要能退回去重做 ─────────────────
// 用假的 DOM：querySelector 查一張表，表裡有的元素就當作看得到。
{
  const vm = require('vm');
  const els = {};
  const el = (extra = {}) => ({
    getBoundingClientRect: () => ({ left: 10, top: 100, right: 200, bottom: 160, width: 190, height: 60 }),
    style: {}, textContent: '', getAttribute: () => null, click() { this.clicked = (this.clicked || 0) + 1; },
    classList: { add() {}, remove() {}, contains: () => false }, ...extra,
  });
  const Router = { currentPage: 'analysis', analyzeMode: 'basic', selectedFile: null, analysisPackage: null, go(p) { this.currentPage = p; } };
  const mem = new Map();
  const sb = {
    console, Router, escapeHtml: s => String(s),
    localStorage: { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, String(v)) },
    getComputedStyle: () => ({ visibility: 'visible', display: 'block', opacity: '1' }),
    document: {
      querySelector: s => els[s] || null,
      addEventListener() {}, removeEventListener() {},
      createElement: () => el({ querySelector: () => null, remove() {} }),
      body: { appendChild() {}, classList: { toggle() {}, add() {}, remove() {} } },
    },
    setInterval: () => 0, clearInterval() {}, Date,
  };
  sb.window = sb; sb.innerWidth = 390; sb.innerHeight = 844;
  sb.addEventListener = () => {};
  vm.createContext(sb);
  vm.runInContext(tour, sb);
  const S = Object.fromEntries(sb.GuidedTour.STEPS.map(s => [s.id, s]));
  const STEPS_ALL = () => sb.GuidedTour.STEPS;
  const file = (name, size = 1000, lm = 1) => ({ name, size, lastModified: lm });

  // 上傳：選了照片算完成；按「照片挑錯了」之後，再選同一張（新的 File 物件）不算，換一張才算
  Router.selectedFile = file('a.jpg');
  check('上傳：選了照片就算完成', S.upload.done() === true);
  els['#uploadBox'] = el();
  S.analyze.extra[0].run();
  check('照片挑錯了 → 直接打開選照片的視窗', els['#uploadBox'].clicked === 1);
  Router.selectedFile = file('a.jpg');
  check('再選同一張照片不算完成', S.upload.done() === false);
  Router.selectedFile = file('b.jpg', 2000, 2);
  check('換一張不同的照片才算完成', S.upload.done() === true);

  // 分析失敗：照片問題 → 換照片；服務問題 → 再分析一次（照片不用換）
  Router.analysisPackage = { id: 'P1', status: 'failed', async: { error: '請把頭轉向你的右邊', errorCode: 'FACE_IMAGE_UNUSABLE', failedAt: 't1' } };
  let pb = S.waitAnalysis.problem();
  check('照片不能用：標題講照片、引用分析端的說明', !!pb && /照片沒辦法分析/.test(pb.title) && /轉向你的右邊/.test(pb.text));
  check('照片不能用：主要按鈕是換一張照片', pb && pb.actions.find(a => a.primary).label === '換一張照片');
  Router.analysisPackage = { id: 'P1', status: 'failed', async: { error: 'Failed to fetch', failedAt: 't2' } };
  pb = S.analyze.problem();
  check('服務連不上：講清楚不是照片的問題、主要按鈕是再分析一次',
    !!pb && /不是你的照片有問題/.test(pb.text) && pb.actions.find(a => a.primary).label === '再分析一次');
  check('失敗期間不會被當成完成', S.waitAnalysis.done() === false);

  // 舊的分析結果不算：只認進入「開始分析」之後完成的
  els['#goStyleBtn'] = el();
  S.analyze.onEnter();
  Router.analysisPackage = { id: 'P2', status: 'completed', async: { completedAt: new Date(Date.now() - 60000).toISOString() } };
  check('一分鐘前的舊分析不算這次完成', S.waitAnalysis.done() === false);
  Router.analysisPackage = { id: 'P2', status: 'completed', async: { completedAt: new Date().toISOString() },
    faceAnalysis: { skinTone: { labReliable: false } } };
  check('這次完成的分析才算', S.waitAnalysis.done() === true);

  // 分析成功但膚色不準：提醒重拍，可以選先用這張繼續
  pb = S.checkResult.problem();
  check('膚色不準會提醒重拍', !!pb && /膚色/.test(pb.title) && pb.actions.some(a => /重拍/.test(a.label)));
  pb.actions.find(a => /先用這張/.test(a.label)).run();
  check('選「先用這張繼續」之後不再擋', S.checkResult.problem() === null);
  check('分析完有「照片挑錯了，重新上傳」可以退回', /照片挑錯了/.test(S.checkResult.extra[0].label));

  // 建議、妝後照失敗：讀流程視窗裡的說明文字
  els['#journeyModal .journey-wait-note'] = el({ textContent: '目前無法完成建議：服務忙碌' });
  pb = S.waitAdvice.problem();
  check('妝容建議失敗 → 回上一步重選', !!pb && /服務忙碌/.test(pb.text) && pb.actions[0].label === '回上一步重選');
  els['#journeyModal .journey-wait-note'] = el({ textContent: '目前沒有臉部分析結果，請先回到臉部分析。' });
  check('建議時沒有分析結果 → 回去重新分析', /重新分析/.test(S.waitAdvice.problem().actions[0].label));
  els['#journeyModal .render-estimate b'] = el({ textContent: '生成失敗：上游逾時' });
  pb = S.render.problem();
  check('妝後照失敗 → 回上一步再試，並提醒次數上限', !!pb && /上游逾時/.test(pb.text) && /次數上限/.test(pb.text));
  check('妝後照出來後可以「換個妝容重做」', /換個妝容重做/.test(S.checkLook.extra[0].label));

  // 每一步都要真的做到：部位示範、上妝示範、推薦商品不再給「下一步」直接跳過
  check('部位標籤、上妝示範、推薦商品都要實際按過才算完成',
    ['pins', 'tutorAll', 'products'].every(id => !S[id].manual && typeof S[id].done === 'function'));
  check('問題小卡的按鈕按下後，同一個舊錯誤不會再把人拉回來', /dismissed = pb\.key/.test(tour));

  // 2026-09-29「每個東西都帶她操作」：回饋、收藏、分享、加入化妝包、打開化妝包、「?」都要實際做
  check('看分析結果要實際點開圖鑑（不是按下一步）', !S.checkResult.manual && typeof S.checkResult.done === 'function');
  els['#featureAtlasLayer'] = el({ hidden: false });
  check('點開圖鑑才算完成', S.checkResult.done() === true);
  delete els['#featureAtlasLayer'];
  check('點開圖鑑前不算完成', S.checkResult.done() === false);
  // 回饋：只認進入這一步之後送出的
  const fbRows = {};
  sb.AnalysisFeedback = { forPackage: id => fbRows[id] || null };
  Router.analysisPackage = { id: 'P9', status: 'completed', async: { completedAt: new Date().toISOString() } };
  fbRows.P9 = { createdAt: new Date(Date.now() - 600000).toISOString() };
  check('十分鐘前送過的回饋不算這一步', S.feedback.done() === false);
  fbRows.P9 = { createdAt: new Date(Date.now() + 5000).toISOString() };
  check('這一步送出回饋才算完成', S.feedback.done() === true);
  // 收藏：訪客略過
  sb.isGuest = () => true;
  check('訪客自動略過收藏（訪客不能收藏）', S.saveLook.skip() === true);
  sb.isGuest = () => false;
  Router.pendingLookSaved = false;
  check('會員要真的收藏才算完成', S.saveLook.skip() === false && S.saveLook.done() === false);
  Router.pendingLookSaved = true;
  check('收藏後完成', S.saveLook.done() === true);
  check('分享、加入化妝包、打開化妝包、「?」都不是「下一步」帶過',
    ['share', 'addBag', 'bag', 'help'].every(id => !S[id].manual && typeof S[id].done === 'function'));
  Router.currentPage = 'makeupBag';
  check('打開化妝包頁才算完成', S.bag.done() === true);
  check('最後一步（意見回饋）完成就收尾', S.feedbackBox.last === true && /if \(st\.last\) stop\(true\)/.test(tour));

  // 2026-09-29「每一個功能都帶使用者做」
  check('除了開場，沒有任何一步是「下一步」帶過（checkLook 是確認妝後照，保留）',
    STEPS_ALL().filter(st => st.manual).map(st => st.id).join(',') === 'intro,checkLook');
  // 試一次改判：確認視窗出現過、而且關掉才算
  els['#dmConfirm'] = el();
  check('改判說明視窗還開著 → 還沒完成', S.tryCorrect.done() === false);
  delete els['#dmConfirm'];
  check('看過說明並關掉 → 完成（不必真的改，避免導覽逼使用者送出錯的標註）', S.tryCorrect.done() === true);
  // 會員中心：訪客略過打卡與推薦碼；今天已打過卡也算完成
  sb.isGuest = () => true;
  check('訪客略過打卡、推薦碼', S.checkin.skip() === true && S.referral.skip() === true);
  sb.isGuest = () => false;
  Router.currentPage = 'profile';
  els['#dailyCheckinBtn'] = el({ disabled: true });
  check('今天已經打過卡（按鈕停用）也算完成', S.checkin.done() === true);
  els['#profileReferralCard'] = el({ textContent: '暫時讀不到推薦碼，請稍後再試' });
  check('推薦碼服務讀不到時不卡住（自動略過）', S.referral.skip() === true);
  els['#profileReferralCard'] = el({ textContent: '讀取推薦碼中…' });
  check('推薦碼還在讀取時不略過', S.referral.skip() === false);
  // 化妝包搜尋：真的輸入了才算
  els['#mbSearch'] = el({ value: '' });
  check('化妝包沒輸入不算', S.bagSearch.done() === false);
  els['#mbSearch'] = el({ value: 'MAC' });
  check('化妝包輸入後才算完成', S.bagSearch.done() === true);
  // 「?」在導覽中是藏起來的，只有最後兩步叫出來
  check('導覽中「?」平常藏起來，help／feedbackBox 兩步才出現',
    /body:has\(\.gt-root\):not\(\.gt-show-help\) \.help-fab \{ display: none; \}/.test(mainCss)
    && /classList\.toggle\('gt-show-help', \['help', 'feedbackBox'\]\.includes/.test(tour));
  check('先看完整示範，再看單一部位', ids.indexOf('tutorAll') < ids.indexOf('pins'));
}

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n新手實作導覽測試通過');
