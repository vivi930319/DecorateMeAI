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

console.log('\n=== 版面在最上方，而且不常駐 ===');
check('進度條在 admin.html', html.includes('id="adminPromotionBar"'));
// 「最上方」是這個需求的重點：登記完人未必留在複核區。
check('放在工具列之後、內容區之前',
  /<\/header>[\s\S]{0,900}?id="adminPromotionBar"[\s\S]{0,1200}?<main class="admin-content">/.test(html));
check('預設隱藏（沒有請求時不佔位）', /id="adminPromotionBar"[^>]*\shidden/.test(html));
check('狀態改變要念出來', /id="adminPromotionBar"[^>]*aria-live="polite"/.test(html));
['adminPromotionHeadline', 'adminPromotionClock', 'adminPromotionRail', 'adminPromotionNote']
  .forEach(id => check(`有 ${id}`, html.includes(`id="${id}"`)));

console.log('\n=== 融入後台既有的視覺語彙 ===');
// 金色主題那一層改的是 --admin-* token；這裡若寫死色碼，換主題就會有一條
// 顏色對不上的橫幅浮在上面。
check('用 --admin-* token 上色', /\.admin-promotion \{[^}]*var\(--admin-soft\)/.test(css));
check('沿用凹槽的上緣內陰影', /\.admin-promotion \{[^}]*inset 0 3px 7px -3px/.test(css));
check('進行中沿用工具列的脈動', /\.apr-step\.now \.apr-dot \{[^}]*adminPulse/.test(css));
check('窄螢幕內距跟著工具列收窄', /\.admin-promotion \{ padding:12px 20px/.test(css));

console.log('\n=== 只說後端真的寫下來的事 ===');
// 這裡的每一項都是「不要重演已經發生過的誤會」。
check('prepared 與 deployed 分得開',
  /prepared:[\s\S]{0,60}尚未部署/.test(js) && /deployed:[\s\S]{0,60}已上線/.test(js));
// 停在「登記」不是快好了，是根本還沒開始。換模型 worker 沒有心跳，
// 前端無從知道訓練機開著沒有，所以只能說出這個前提，不能估時間。
check('等待中要說出「訓練機沒開就不會前進」',
  /status === 'queued'[\s\S]{0,300}?訓練機/.test(js) && /不會自己往前走/.test(js));
check('步驟時間只標後端寫過的那幾步',
  /stamps = \{[\s\S]{0,160}?row\.createdAt[\s\S]{0,160}?row\.claimedAt/.test(code));
// 渲染那條進度條是「依經過時間估算的體感值」，那是刻意的取捨；這一條不是，
// 它報的是狀態機真正的位置，不可以退化成百分比動畫。
check('不編造百分比進度', !/apr[\s\S]{0,400}?(percent|progress\s*=\s*Math|width:\s*\$\{)/i.test(code));
check('讀不到就維持現狀，不用故障蓋掉資訊',
  /if \(!res\.ok\) return this\._promotionActive/.test(code));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
