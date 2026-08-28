// 模型修正複核。
//
// 覆核的單位是「一筆回饋」：後端的 reviewStatus 寫在文件層級，一筆修正裡的三個部位
// 是同一次送出的，沒有辦法只採用其中一個。2026-08-24 從表格改成卡片，因為覆核要先
// 看完一個人的全部修正與影像才有辦法決定，表格把一筆攤成好幾列，得先在腦中拼回同
// 一次分析。
//
// 這裡守的是幾個壞掉不會報錯的地方：舊資料的預設狀態、影像的載入時機、
// 以及送出失敗時畫面要退回去而不是假裝成功。
//
// 用法：node tests/feedback_review_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'pages/admin.html'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8');

// 從真實原始碼抽出 fbRender 與它用到的東西。抄一份到測試裡的話，
// 測到的就是那份抄本，router.js 改壞了也不會有人知道。
const cut = (mark) => {
  const start = src.indexOf(mark);
  if (start < 0) { console.log(`找不到 ${mark}`); process.exit(1); }
  let depth = 0;
  for (let i = src.indexOf('{', start); i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  console.log(`${mark} 括號沒收完`); process.exit(1);
};

let pendingChecked = false;
const sandbox = {
  console,
  escapeHtml: s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  feedbackBody: { innerHTML: '' },
  fbTab: 'pending',
  fbTime: (iso) => (iso ? String(iso).slice(0, 16) : '—'),
};
// 改判下拉的選項來自 api.js 的 AnalysisFeedback.OPTIONS。這裡放一份替身，
// 內容要跟真的一致，否則測不出「清單被抄第二份」那個問題。
sandbox.AnalysisFeedback = { OPTIONS: {
  '臉型': ['圓形臉', '心形臉', '方形臉', '長形臉', '鵝蛋臉'],
  '眉型': ['一字眉', '彎月眉', '挑眉', '落尾眉'],
  '眼型': ['下垂眼', '圓眼', '桃杏眼', '鳳眼'],
  '鼻型': ['寬鼻', '標準鼻'],
  '嘴型': ['厚唇', '微笑唇', '花瓣唇', '薄唇'],
} };
vm.createContext(sandbox);
vm.runInContext(
  cut('const FB_REVIEW_LABEL = {') + ';\n'
  // 卡片標籤與分頁用同一組四態語彙，fbRender 依賴這三個。
  // 抽了 fbRender 沒抽相依，測試會在執行時炸 ReferenceError——那是測試的問題。
  + cut('const FB_BUCKET_LABEL = {') + ';\n'
  + 'const fbRunStatus = new Map();\n'
  + cut('const fbBucket = (item) => {') + ';\n'
  + 'const fbSamples = {};\n'
  + 'const fbSelected = new Set();\n'
  + 'const fbApprovedFields = (it) => (it.changes || []).filter(c => (it.reviewDecisions || {})[c.field] === "accepted").map(c => c.field);\n'
  + 'const fbUpdateTrainButton = () => {};\n'
  // 2026-08-26：影像改成捲到就自動載入，所以 sampleHtml 現在只負責畫外框，
  // 內容交給 sampleInner，抓取由 watchSamples 的 IntersectionObserver 觸發。
  // 這兩個是替身：這支測試檢查的是卡片的結構與跳脫，不是抓取時機。
  + 'let fbTab = "pending";\n'
  + 'const watchSamples = () => {};\n'
  + cut('const sampleInner = (id) => {') + ';\n'
  + cut('const fbOptions = (field, id, current) => {') + ';\n'
  + cut('const sampleHtml = (id, hasSample) => {') + ';\n'
  + cut('const fbRender = (items) => {') + ';\n'
  + 'globalThis.__render = fbRender; globalThis.__samples = fbSamples;', sandbox);
const render = sandbox.__render, samples = sandbox.__samples;

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};

const item = (over = {}) => ({
  feedbackId: 'FB-JOB-abc', jobId: 'JOB-abc', mode: 'basic',
  createdAt: '2026-08-24T02:00:00+00:00',
  changes: [
    { field: '眉型', predicted: '落尾眉', corrected: '一字眉' },
    { field: '眼型', predicted: '圓眼', corrected: '桃杏眼' },
    { field: '嘴型', predicted: '薄唇', corrected: '厚唇' },
  ],
  ...over,
});
const reset = () => { Object.keys(samples).forEach(k => delete samples[k]); };

console.log('\n=== 1. 一筆一張卡，不是一部位一列 ===');
reset(); render([item()]);
let out = sandbox.feedbackBody.innerHTML;
check('一筆回饋只產生一張卡', (out.match(/<article class="fb-card/g) || []).length === 1,
  `${(out.match(/<article class="fb-card/g) || []).length} 張`);
// 三個部位在同一張卡裡，覆核的人一次看完
check('三個修正都在這張卡裡', (out.match(/class="fb-change /g) || []).length === 3,
  `${(out.match(/class="fb-change /g) || []).length} 列`);
// 逐部位只有「送訓」一顆。退回拿掉了：使用者說錯了就直接從下拉改成正確答案，
// 那比退回有用——退回只是丟掉一張圖，改判會留下一個正確的標籤。
check('每個部位有一顆送訓',
  (out.match(/data-fb-field="[^"]*" data-fb-decision/g) || []).length === 3,
  `${(out.match(/data-fb-field="[^"]*" data-fb-decision/g) || []).length} 顆`);
// 「排除這張」是對照片本身的判定（沒對到臉、戴口罩、糊掉），改判救不回來，
// 而且它是唯一會把影像從 GCS 真的刪掉的動作。
check('底部有整筆快捷', out.includes('全部送訓') && out.includes('排除這張'));
// 管理員改判：使用者說的也不對時的第三個答案，這是雙重驗證的關鍵
check('每個部位都有改判下拉', (out.match(/class="fb-mini fb-fix"/g) || []).length === 3);
check('改判選項來自分類表', out.includes('>一字眉<') && out.includes('>桃杏眼<'));
check('按鈕帶得出 feedbackId', out.includes('data-fb-id="FB-JOB-abc"'));
// data-fb-row 與 data-fb-id 也含 jobId，那是給事件委派用的；
// 要看的是**畫面上顯示**的那一個，它只該在卡片標頭出現一次。
check('顯示出來的 jobId 只有一個',
  (out.match(/class="fb-job">/g) || []).length === 1,
  `${(out.match(/class="fb-job">/g) || []).length} 個`);
check('時間只顯示一次', (out.match(/class="fb-when">/g) || []).length === 1);

console.log('\n=== 2. 狀態決定按鈕能不能按 ===');
reset(); render([item({ reviewStatus: 'accepted', reviewedAt: '2026-08-24T03:00:00+00:00' })]);
out = sandbox.feedbackBody.innerHTML;
check('已採用時顯示「已採用」', out.includes('已採用'));
// class 現在會多帶一個狀態（is-accepted / is-queued），所以不能寫死 class="fb-accept"
check('已採用時「採用」不能再按', /class="fb-accept[^"]*"[^>]*disabled/.test(out));
// 已採用但還沒進批次 → 顯示「待送訓」，而不是看起來還能送的「送訓」
check('已採用未進批次顯示「待送訓」', out.includes('待送訓'));
check('已採用未進批次的卡片標成 awaiting', out.includes('fb-card accepted awaiting'));
check('已採用時「退回」仍可按（要能改判）', !/class="fb-reject"[^>]*disabled/.test(out));
check('已採用時卡片帶上樣式類別', out.includes('fb-card accepted'));
check('顯示覆核時間', out.includes('覆核於'));

reset(); render([item({ reviewStatus: 'rejected' })]);
out = sandbox.feedbackBody.innerHTML;
check('已退回時「退回」不能再按', /class="fb-reject"[^>]*disabled/.test(out));
check('已退回時「採用」仍可按', !/class="fb-accept"[^>]*disabled/.test(out));

console.log('\n=== 3. 舊資料沒有 reviewStatus，一律當待覆核 ===');
// 那 108 筆是在覆核功能上線之前送出的，沒有任何人看過。
// 把它們當成已採用，等於讓沒做過的事看起來像做過了。
reset(); render([item()]);
out = sandbox.feedbackBody.innerHTML;
check('沒有 reviewStatus 顯示「待覆核」', out.includes('待覆核'));
check('沒有 reviewStatus 時兩顆按鈕都能按', !/data-fb-decision="[^"]*"[^>]*disabled/.test(out));

console.log('\n=== 4. 樣本影像：有才給按鈕，點開才載 ===');
reset(); render([item({ hasSample: true })]);
out = sandbox.feedbackBody.innerHTML;
// 影像不必按開，但也不會一進畫面就全抓：卡片留一個插槽，捲到才去拿。
check('有樣本時留下影像插槽', out.includes('data-fb-slot'));
// 還沒抓到之前不該有任何 img，否則 108 筆會一次拉幾 MB
check('還沒抓到就不該有影像', !out.includes('<img'));
reset(); render([item({ hasSample: false })]);
check('沒樣本時說明白，不給按鈕',
  !sandbox.feedbackBody.innerHTML.includes('data-fb-shots')
  && sandbox.feedbackBody.innerHTML.includes('沒有影像可看'));

console.log('\n=== 5. 影像的四種狀態要分得出來 ===');
reset(); samples['FB-JOB-abc'] = 'loading';
render([item({ hasSample: true })]);
check('載入中', sandbox.feedbackBody.innerHTML.includes('載入樣本影像'));

reset(); samples['FB-JOB-abc'] = { error: '讀取失敗' };
render([item({ hasSample: true })]);
check('讀取失敗要說出來', sandbox.feedbackBody.innerHTML.includes('讀取失敗'));

reset(); samples['FB-JOB-abc'] = [];
render([item({ hasSample: true })]);
// 空陣列不是錯誤：使用者沒勾同意就不會有圖，這兩者要分開講
check('沒有影像時解釋原因', sandbox.feedbackBody.innerHTML.includes('沒有勾選同意'));

reset();
samples['FB-JOB-abc'] = [
  { part: 'brow_shape', label: '一字眉', dataUrl: 'data:image/png;base64,AAAA' },
  { part: 'face_shape', label: '鵝蛋臉', skipped: '圖片太大，未載入' },
];
render([item({ hasSample: true })]);
out = sandbox.feedbackBody.innerHTML;
check('有影像時畫出來', out.includes('<img src="data:image/png;base64,AAAA"'));
check('部位與類別都標出來', out.includes('brow_shape') && out.includes('一字眉'));
// 太大的圖跳過，但要讓人知道那裡本來有東西
check('被跳過的圖有交代', out.includes('圖片太大'));
check('抓到之後插槽仍在（重畫時沿用快取）', out.includes('data-fb-slot'));

console.log('\n=== 6. 空狀態要分得出「沒資料」與「都看完了」===');
reset(); pendingChecked = false; render([]);
check('待覆核分頁空了：說都看過了', sandbox.feedbackBody.innerHTML.includes('都看過了'));
render([]);
// 篩選成空的時候說「沒有紀錄」是錯的——實際上有，只是都覆核過了
check('待覆核模式：說都看過了', sandbox.feedbackBody.innerHTML.includes('都看過了'));
pendingChecked = false;

console.log('\n=== 7. 沒有 changes 的紀錄仍要顯示 ===');
reset(); render([item({ changes: [] })]);
// 這種紀錄本身就是資料異常，藏起來只會讓人查不到
check('空 changes 仍出現，並說明沒有修正內容',
  sandbox.feedbackBody.innerHTML.includes('fb-card')
  && sandbox.feedbackBody.innerHTML.includes('沒有修正內容'));

console.log('\n=== 8. HTML 逃脫 ===');
reset();
render([item({ jobId: '<img src=x onerror=alert(1)>', changes: [{ field: '眉型', predicted: 'a', corrected: 'b' }] })]);
check('jobId 有逃脫', !sandbox.feedbackBody.innerHTML.includes('<img src=x'));
reset();
samples['FB-JOB-abc'] = [{ part: '<script>', label: 'x', dataUrl: 'data:image/png;base64,AA' }];
render([item({ hasSample: true })]);
check('樣本的 part 有逃脫', !sandbox.feedbackBody.innerHTML.includes('<script>'));

console.log('\n=== 9. API 這一端 ===');
check('api.js 提供 reviewFaceFeedback', api.includes('async reviewFaceFeedback'));
check('用 PATCH', /reviewFaceFeedback[\s\S]{0,2000}method: 'PATCH'/.test(api));
check('決定只收 accepted/rejected',
  /const valid = v => v === 'accepted' \|\| v === 'rejected'/.test(api));
// 逐部位時每一個值都要驗，只驗第一個等於沒驗
check('逐部位時每個值都驗過', api.includes("entries.every(([, v]) => valid(v))"));
check('api.js 提供 fetchFaceFeedbackSamples', api.includes('async fetchFaceFeedbackSamples'));
check('feedbackId 有做 encodeURIComponent',
  /face-feedback\/\$\{encodeURIComponent/.test(api));

console.log('\n=== 10. 接線 ===');
check('admin.html 用卡片容器而不是表格',
  html.includes('admin-feedback-list') && !/id="adminFeedbackBody"[^>]*>\s*<\/tbody>/.test(html));
// 四個分頁對應四個位置，不是三個覆核決定。
//
// 舊的「已採用」把兩種完全不同的狀態混在一起：已採用但**還沒送進任何批次**的，
// 跟已經在跑的。一百張卡片長一樣，其中只有二十張還需要動作——
// 2026-08-27 使用者因此把已經送過的那批又送了一次。
//
// 現在「待覆核」＝**還需要你動手的**（沒覆核過的 ＋ 覆核了卻還沒送出的），
// 送出之後那一格就會清空。
check('admin.html 有四個分頁',
  ['pending', 'training', 'trained', 'rejected'].every(t => html.includes(`data-fb-tab="${t}"`)));
check('分頁文字是四態語彙',
  ['待覆核', '送訓中', '送訓完成', '退回'].every(t => html.includes(t)));
// 採用但還沒送出的要留在「待覆核」，不然使用者不知道還有二十筆等著送
check('採用但未送出仍算待覆核', /if \(!runId\) return 'pending'/.test(src));
check('批次跑完才算送訓完成', /runState === 'done' \? 'trained' : 'training'/.test(src));
// 查不到批次狀態時當成還在跑：說「完成了」而其實沒有，比反過來糟——
// 前者會讓人以為模型已經更新
check('批次狀態未知時算送訓中', /fbRunStatus\.get\(runId\)/.test(src));
// 每次重畫都會換掉整個容器，逐張綁的處理器會跟著沒掉
check('用事件委派而不是逐張綁定', src.includes("feedbackBody.addEventListener('click'"));
// 影像不再需要按開：卡片捲進畫面就自動抓。要判斷眉型、唇型本來就得看到形狀，
// 每一筆都先點一次等於在每一筆上收一次過路費。
check('影像捲到就自動載入', src.includes('IntersectionObserver') && src.includes('data-fb-slot'));
check('一次最多抓三筆', /sampleActive < 3/.test(src));
check('抓到只換那張卡，不整份重畫', src.includes('paintSamples'));
check('失敗時把按鈕解鎖回原狀',
  src.includes("b.disabled = b.dataset.wasDisabled === '1'"));
// 送出時鎖整張卡：連按兩顆不同的會讓後面那次覆蓋前面那次，而畫面上看不出來
check('送出時鎖住整張卡的按鈕',
  /card \? \[\.\.\.card\.querySelectorAll\('button\[data-fb-decision\]'\)\]/.test(src));
check('切換分頁會重畫', /fbTab = btn\.dataset\.fbTab[\s\S]{0,120}fbRepaint\(\)/.test(src));
// 批次送訓：一筆一筆按會產生一筆一個批次，而每個批次都要從頭重訓一次
// （上一批一個部位就跑了 112 分鐘），且各自隨機切分，數字彼此不能比。
//
// 這顆按鈕曾經只存在於 JS 裡、HTML 沒有它，於是 getElementById 拿到 null、
// onclick 從沒接上——功能看起來寫好了，實際上整條是死的。所以兩邊都要驗。
check('有批次送訓按鈕', html.includes('id="adminFeedbackTrain"'));
check('送訓按鈕在 JS 裡接得到', src.includes("getElementById('adminFeedbackTrain')"));
check('有全選可送訓', html.includes('id="adminFeedbackPickAll"'));
check('卡片可以勾選', src.includes('data-fb-pick'));
check('勾選只改本地不打 API',
  /pick\.checked\) fbSelected\.add/.test(src));
// 全選框要有 indeterminate：勾了一部分卻顯示「沒勾」的話，
// 使用者按下去的第一下是取消，結果比按之前更少。
check('全選框有三態', src.includes('fbPickAll.indeterminate'));
// 送訓不可逆，而且會佔住訓練機數十分鐘到數小時。
check('送訓前先確認', /showConfirm\([\s\S]{0,400}確認送出訓練/.test(src));
check('確認視窗說出筆數', /okText: `送出 \$\{ids\.length\} 筆`/.test(src));
// 三態，不是兩態：先前不論已採用或已進批次，文字都是「送訓」只是變灰，
// 而一顆寫著「送訓」的灰按鈕讀起來仍然是「可以送」——2026-08-27 使用者
// 因此把已經送過的那批又送了一次。
check('未處理時寫「送訓」', src.includes("? '已送訓' : '待送訓') : '送訓'"));
check('已進批次寫「已送訓」', src.includes("'已送訓'"));
check('已採用未進批次寫「待送訓」', src.includes("'待送訓'"));
check('待送訓的卡片有標記', src.includes("' awaiting'") && css.includes('.fb-card.awaiting'));
check('摘要說明已採用的會進重訓', src.includes('import_feedback_samples.py'));
check('卡片樣式存在', css.includes('.fb-card') && css.includes('.fb-shots'));

console.log('');
console.log('=== 可送訓的判定 ===');
// fbBucket 只回 pending／training／trained／rejected，**沒有 accepted**。
// 拿 `fbBucket(it) === 'accepted'` 去過濾，可送訓永遠是 0 筆：
// 按鈕永遠寫「已採用未送訓 0」，全選框因為 all.length === 0 而是 disabled，
// 勾了完全沒有反應——看起來像功能被拿掉，其實是在找一個不存在的值。
// 掃描前先去掉註解：程式裡解釋這個坑的那段註解本身就含有這個字串，
// 不去掉的話這一項會被自己的說明文字命中而永遠失敗。
const srcNoComment = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
check('fbTrainable 不靠 fbBucket 判斷',
  !srcNoComment.includes("fbBucket(it) === 'accepted'"));
check('fbTrainable 直接看 reviewStatus',
  src.includes("it.reviewStatus === 'accepted' || it.reviewStatus === 'partial'"));
check('仍然排除沒有影像與已進批次的',
  src.includes('it.hasSample && !it.trainingRunId'));
check('fbBucket 確實不會回傳 accepted',
  !/const fbBucket[\s\S]{0,900}?return 'accepted'/.test(src));

console.log('');
console.log('=== 送訓動線：按一次就好 ===');
// 先前要按兩次：卡片上按「送訓」只把它標成已採用，還得再回到上面勾一次
// 才會計入「送去訓練」。那兩個動作在使用者眼裡是同一件事。
check('按送訓就直接計入批次', srcNoComment.includes('fbSelected.add(id)')
  && /reviewStatus === 'accepted' \|\| res\.reviewStatus === 'partial'/.test(srcNoComment));
check('沒有影像或已進批次的不自動加入',
  /now\.hasSample && !now\.trainingRunId && fbApprovedFields\(now\)\.length/.test(srcNoComment));
// 批次建立後，那幾筆已經不需要你動手了——留在「待覆核」是錯的分類
check('送出後本機掛上 runId', srcNoComment.includes('hit.trainingRunId = res.runId'));
check('送出後清掉「留在原地」的名單', srcNoComment.includes('fbJustDecided.clear()'));

console.log('');
console.log('=== 用不到的分頁不要留著 ===');
// 停權這個動作 2026-08-27 就拿掉了，篩選分頁留著等於一個永遠篩不出東西的按鈕
check('會員管理沒有「已停權」篩選分頁',
  !html.includes('data-admin-filter="suspended"')
  && !srcNoComment.includes('data-admin-filter="suspended"'));
check('已停權的統計欄位保留（資料庫仍有 status）',
  html.includes('id="adminSuspended"'));

console.log('');
console.log('=== 「0」和「沒載到」必須分得開 ===');
// 這是 2026-08-28 整天誤會的根源：待覆核 0、送訓中 0、送訓完成 0、退回 0，
// 看起來就是「我的紀錄都被刪掉了」——而 Firestore 一筆都沒少（11 筆，只增不減）。
//
// **0 是一個關於資料的宣稱**，意思是「我查過了，一筆都沒有」。
// 還沒查到就寫 0，畫面說的是謊，而且說的正好是最可怕的那一句。
check('分頁計數的初始值不是 0', !/data-fb-count="\w+">0</.test(html));
check('分頁計數初始顯示 —', /data-fb-count="\w+">—</.test(html));
check('備援樣板同步', !/data-fb-count="\w+">0</.test(src));
check('載入失敗時計數退回 —', src.includes("fbCounts.forEach((el) => { el.textContent = '—'; });"));
check('送訓按鈕載入前不報數字', src.includes("if (!fbLoaded) { fbTrain.textContent = '送去訓練'; fbTrain.disabled = true; return; }"));
check('載入成功才認為知道筆數', src.includes('fbLoaded = true;'));
check('失敗後把「知道」關回去', /fbCounts\.forEach[\s\S]{0,120}?fbLoaded = false;/.test(src));

console.log('');
console.log('=== 訓練批次紀錄刪不掉（結構上）===');
// 使用者兩次以為批次被刪掉。實際上整個系統沒有任何刪除路徑：
// Gateway 只有 create 與 all_jobs，訓練機只 patch 狀態與指標。
// 這一項守著那個事實——真的要加刪除功能時，會先在這裡亮紅燈。
check('前端沒有刪除訓練批次的 API', !/delete[A-Za-z]*Training|Training[A-Za-z]*Delete/i.test(api));
check('前端沒有對 runs 送 DELETE',
  !/face-training\/runs[^`'"]*`?,\s*\{\s*method:\s*'DELETE'/i.test(api));

console.log('');
console.log('=== 訓練批次面板不能停在佔位字 ===');
// 只有三種合法畫面：載入中、載到了、失敗（帶原因）。
// 「維持 admin.html 的初始文字」不是其中之一——那讓「還沒開始」「正在跑」
// 「失敗了」三種完全不同的情況長得一模一樣。
check('載入前先蓋掉初始文字', src.includes('訓練批次載入中…'));
check('失敗要說原因', src.includes('訓練批次讀取失敗'));
check('權限不足要講清楚', src.includes('需要管理員身分，請重新登入後按「重新載入」'));
check('渲染炸掉也要說', src.includes('訓練批次顯示失敗'));
check('初始化失敗要顯示在畫面上', src.includes('模型修正複核初始化失敗'));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
