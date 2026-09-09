// 換模型進度條：登記之後要看得出「走到哪一步」。
//
// 這一支存在的理由是一個很安靜的失敗：`Api.fetchModelPromotions()` 在 api.js 裡
// 寫好了，卻**從來沒有被任何地方呼叫過**。按下換上線只跳一個 alert 說
// 「完成後這一頁會顯示已上線」——沒有東西回頭讀狀態，那句話頁面兌現不了。
// 登記完什麼都不會變，隔天再登記一次還是同一句話，於是「到底換上去了沒」
// 永遠沒有答案，而畫面上完全看不出哪裡壞了。
//
// 「函式定義了但沒有人呼叫」語法合法、lint 也不會說話，只有使用者會發現，
// 而他發現的形式是「這個功能好像沒有用」。所以第一項檢查就是它有沒有被呼叫。
//
// 用法：node tests/promotion_progress_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8').replace(/\r\n/g, '\n');
const html = read('pages/admin.html');
const js = read('js/router.js');
const api = read('js/api.js');
const css = read('css/main.css');
// 比對前剝掉 // 註解：上面那些說明本身就寫著舊行為與函式名，
// 直接搜原始碼會被自己的註解判成通過。
const code = js.replace(/^\s*\/\/.*$/gm, '');

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};

console.log('\n=== 狀態真的被讀回來 ===');
check('api.js 提供 fetchModelPromotions', /async fetchModelPromotions/.test(api));
check('router.js 真的呼叫它（先前只定義沒呼叫）', /Api\.fetchModelPromotions\(/.test(code));
check('進後台就開始看', /_watchPromotion\(\)/.test(code));
check('離開後台會停掉輪詢',
  /currentPage === 'admin'[\s\S]{0,120}?stopPromotionWatch\(\)/.test(code));
check('不再進行中就停止輪詢',
  /_renderPromotion\(\)\)\)\s*this\.stopPromotionWatch\(\)/.test(code));
check('登記成功後立刻更新進度',
  /requestModelPromotion\([\s\S]{0,900}?Router\._watchPromotion\(\)/.test(code));

console.log('\n=== 版面只在模型複核區，而且不常駐 ===');
check('進度條在 admin.html', html.includes('id="adminPromotionBar"'));
// 換上線是從這一區按的，狀態就回到這一區看；不要在每個分區都掛一條。
check('放在模型複核區的最上面',
  /data-admin-view="feedback"[\s\S]{0,1500}?id="adminPromotionBar"[\s\S]{0,2500}?admin-console-panel/.test(html));
check('沒有掛在工具列下面（那會每一區都出現）',
  !/<\/header>[\s\S]{0,400}?id="adminPromotionBar"/.test(html));
check('預設隱藏（沒有請求時不佔位）', /id="adminPromotionBar"[^>]*\shidden/.test(html));
check('狀態改變要念出來', /id="adminPromotionBar"[^>]*aria-live="polite"/.test(html));
['adminPromotionHeadline', 'adminPromotionClock', 'adminPromotionRail', 'adminPromotionNote',
 'adminPromotionDetail'].forEach(id => check(`有 ${id}`, html.includes(`id="${id}"`)));

console.log('\n=== 後端印的報告要看得下去 ===');
// promote_model 印出來的是逐行的檢查報告。先前把它塞進 <p> 並用「·」串起來，
// 換行全被吃掉，「臉型 +0.0 / 鼻型 -2.6 / 唇型 +0.0」黏成一段——
// 那份報告最重要的用途（一眼看出是哪個部位擋下來的）就沒了。
check('細節用 <pre> 保留原本的分行', /<pre class="apr-detail"/.test(html));
check('說明不再用「·」串成一段', !/lines\.join\('　·　'\)/.test(code));
check('說明一行一件事', /lines\.join\('\\n'\)/.test(code));
check('.apr-note 保留換行', /\.apr-note \{[^}]*white-space:pre-line/.test(css));
check('.apr-detail 保留換行且會自己捲', /\.apr-detail \{[^}]*white-space:pre-wrap/.test(css)
  && /\.apr-detail \{[^}]*overflow:auto/.test(css));
check('不重複印批次編號', /i === 0 && row\.runId/.test(code));
check('失敗細節不截斷（報告要完整）', !/row\.error[\s\S]{0,40}\.slice\(0, ?\d+\)/.test(code));

console.log('\n=== 融入後台既有的視覺語彙 ===');
// 金色主題那一層改的是 --admin-* token；這裡若寫死色碼，換主題就會有一條
// 顏色對不上的橫幅浮在上面。
check('用 --admin-* token 上色', /\.admin-promotion \{[^}]*var\(--admin-soft\)/.test(css));
check('沿用凹槽的上緣內陰影', /\.admin-promotion \{[^}]*inset 0 3px 7px -3px/.test(css));
check('進行中沿用工具列的脈動', /\.apr-step\.now \.apr-dot \{[^}]*adminPulse/.test(css));
// 只要求窄螢幕有自己的內距，不鎖死數值——鎖死的話調一次留白就會紅，
// 而它報的會是「沒有跟著收窄」，不是實話。
check('窄螢幕有自己的內距', /@media[\s\S]{0,40000}?\.admin-promotion \{ padding:/.test(css));

console.log('\n=== 只說後端真的寫下來的事 ===');
// 這裡的每一項都是「不要重演已經發生過的誤會」。
check('prepared 與 deployed 分得開',
  /prepared:[\s\S]{0,60}尚未部署/.test(js) && /deployed:[\s\S]{0,60}已上線/.test(js));
// 停在「登記」不是快好了，是根本還沒開始。換模型 worker 沒有心跳，
// 前端無從知道訓練機開著沒有，所以只能說出這個前提，不能估時間。
check('等待中要說出「訓練機沒開就不會前進」',
  /status === 'queued'[\s\S]{0,600}?訓練機/.test(js) && /不會自己往前走/.test(js));
// 但「還沒開始」有兩種原因，不能都講成機器沒開。換模型機一次只做一筆——先登記的
// 那筆正在跑時，後面這筆本來就該等，機器好得很。2026-09-09 連按兩次時就踩到：
// 進度條只顯示最新那筆（排隊中），正在部署的那筆被藏起來，畫面於是叫人去開一台
// 其實正忙著的機器。有別筆在跑就要講「你排在誰後面」，那是查得到的事實。
check('有別筆在跑時要說排在後面，而不是說機器沒開',
  /inFlight/.test(js) && /排在它後面/.test(js));
check('排隊訊息要分得出這兩種情況',
  /status === 'queued' && inFlight\.length/.test(js));
check('步驟時間只標後端寫過的那幾步',
  /stamps = \{[\s\S]{0,160}?row\.createdAt[\s\S]{0,160}?row\.claimedAt/.test(code));
// 渲染那條進度條是「依經過時間估算的體感值」，那是刻意的取捨；這一條不是，
// 它報的是狀態機真正的位置，不可以退化成百分比動畫。
check('不編造百分比進度', !/apr[\s\S]{0,400}?(percent|progress\s*=\s*Math|width:\s*\$\{)/i.test(code));
check('讀不到就維持現狀，不用故障蓋掉資訊',
  /if \(!res\.ok\) return this\._promotionActive/.test(code));

console.log('\n=== 換上線：人選部位，數字帶誤差 ===');
// 只看 promoteRun 這一段。別的地方仍然可以用 trainHistoricalBefore 畫「訓練前後對照」，
// 那是另一件事；換上線要比的是「現在線上是什麼」。
const promote = (code.match(/const promoteRun = async[\s\S]*?\n            \};/) || [''])[0];
check('換上線的區段找得到', promote.length > 500, `${promote.length} 字元`);
// 這是這次修的根。拿「這一批訓練前」當基準，換過一次模型就過期，
// 於是按鈕會提供根本換不上去的部位——2026-09-04 那批三個部位就是這樣來的。
check('基準用線上實際分數，不是歷史批次',
  /trainLatestRegisteredMetrics\(\s*\n?\s*fbCurrentMetrics/.test(promote)
  && !/trainHistoricalBefore\(run\)/.test(promote));
check('線上分數有被記下來', /fbCurrentMetrics = data\?\.currentMetrics/.test(code));
check('對話框放得進自訂節點', /opts\.bodyNode/.test(code));
check('逐部位勾選', /promote-picker/.test(promote) && /type = 'checkbox'/.test(promote));
check('只送出勾選的部位',
  /const parts = Array\.from\(picked\)/.test(promote)
  && /requestModelPromotion\(runId, parts\)/.test(promote));
check('沒有勾就不能按', /ok\.disabled = picked\.size === 0/.test(code));
// 預設勾「確實比較好」的；看不出差別的留給人決定，不要替他決定。
check('預設只勾確實比較好的', /verdict === 'better'\)\.map\(/.test(promote));
check('確實比較差的不給勾', /box\.disabled = row\.verdict === 'worse'/.test(promote));

// 誤差要跟 promote_model 的 _diff_margin 同一個算式，
// 否則同一個模型會被前端與訓練端講成不同的話，而且沒有人看得出來。
check('誤差用 1.96 × 合併標準誤', /1\.96 \* Math\.sqrt\(a \* a \+ b \* b\)/.test(code));
check('算不出誤差回 null，不是 0', /Number\.isFinite\(a\)[\s\S]{0,60}return null/.test(code));
check('畫面寫出誤差範圍', /看不出差別（誤差約 ±/.test(js));
check('畫面寫出保留集張數', /保留集 \$\{row\.n/.test(js));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
