// 會員中心與登入畫面的驗收清單（2026-08-28）。
//
// 這一份盯的是三件容易在改版時安靜壞掉的事：
//   1. 會員中心的分頁：pages/profile.html 與 router.js 的備援樣板是兩份，
//      改一邊沒改另一邊，備援畫面上的分頁就按不動——而備援只在 fetch 失敗時
//      才出現，平常測不到。
//   2. 頭貼必須是可聚焦的按鈕，且訪客不能按（沒有 email 就沒有地方存）。
//   3. 分析結果區在沒有結果時要是灰的，而判斷狀態的那行必須在清空之後。
//
// 用法：node tests/member_center_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
// 讀進來就把換行統一成 \n。
//
// 2026-08-29 補的。起因是「狀態判斷在 analysisResult 清空之後」那一項突然變成
// FAIL，而那段程式碼一個字都沒改——router.js 的換行在某次編輯後變成 CRLF，
// 而那項比對的是含 `\n` 的跨行字面字串，於是永遠對不上。
//
// 危險的不是這次的誤報，是它反過來的形狀：**跨行的字面比對在 CRLF 下會安靜地
// 恆真或恆假**，看斷言寫成 includes 還是 !includes。恆真的那種等於這項檢查
// 從此不再檢查任何東西，而畫面上一直是綠的。tests/ 底下每一支都補了同一行。
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8').replace(/\r\n/g, '\n');
const router = read('js/router.js');
const css = read('css/main.css');
const profile = read('pages/profile.html');
const index = read('index.html');
// 掃描時把註解拿掉：這些檢查會誤中自己的說明文字。
//
// `/*` 前面必須不是字母、數字或引號，否則 `accept="image/*"` 會被當成註解開頭。
// router.js 裡有兩處那樣的 input（fileInput 與 profileAvatarInput），而 `*/` 只有
// 三處——非貪婪匹配會從 image/* 一路吃到幾千行後的下一個 `*/`，刪掉 23% 的檔案，
// 連同會員中心的備援樣板。症狀是「備援樣板少了分頁」，看起來像樣板沒同步，
// 實際上是這一行的正則太寬。
const noComment = (s) => s.replace(/(?<![\w"'])\/\*[\s\S]*?\*\//g, '')
                          .replace(/^\s*\/\/.*$/gm, '')
                          .replace(/<!--[\s\S]*?-->/g, '');
const routerCode = noComment(router);
const cssCode = noComment(css);
const profileCode = noComment(profile);

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};
const count = (hay, needle) => hay.split(needle).length - 1;

console.log('=== 1. 會員中心分頁：兩份樣板要一致 ===');
const tabKeys = ['account', 'points', 'saved'];
tabKeys.forEach(k => {
    check(`profile.html 有 ${k} 分頁`, profileCode.includes(`data-mtab="${k}"`)
        && profileCode.includes(`data-mpanel="${k}"`));
    check(`備援樣板有 ${k} 分頁`, count(routerCode, `data-mtab="${k}"`) >= 1
        && count(routerCode, `data-mpanel="${k}"`) >= 1);
});
// 預設開第一個分頁，其餘 hidden——三個都開或三個都關都是壞掉
const openPanels = (profileCode.match(/<div class="member-panel"[^>]*>/g) || [])
    .filter(t => !t.includes('hidden'));
check('只有一個分頁預設打開', openPanels.length === 1, `打開 ${openPanels.length} 個`);
check('預設打開的是「帳戶」', openPanels[0] && openPanels[0].includes('account'));
// aria-selected 要跟 is-active 一致，否則螢幕閱讀器唸的跟看到的不同
const tabs = profileCode.match(/<button[^>]*data-mtab="[^"]*"[^>]*>/g) || [];
check('aria-selected 與 is-active 一致',
    tabs.every(t => t.includes('is-active') === t.includes('aria-selected="true"')));
check('切換用 hidden 而不是只改 class', routerCode.includes('pl.hidden = pl.dataset.mpanel'));
// 統計卡會捲到別的分頁裡的區塊——不先切過去的話，捲動完全沒有反應
check('捲動前先切到目標分頁', routerCode.includes("target.closest('.member-panel')")
    && routerCode.includes('showMemberTab(panel.dataset.mpanel)'));
// 逐個標題點名，而不是數 <section> 的數量。
//
// 原本寫的是「member-tier 剛好 6 個」。2026-08-29 把「每日打卡」還原之後變成 7 個，
// 這一項就 FAIL 了——但**一個區塊都沒有掉**，是刻意加了一個。在「東西變多」時也會
// 紅的檢查，會養成把它改掉的習慣，而那正是它該擋住的那次改動的偽裝。
//
// 點名之後，少了哪一塊會直接說出是哪一塊，多了一塊不算失敗。
const MEMBER_BLOCKS = ['會員等級', 'PRO 付費解鎖（Demo）', '每日打卡', '任務中心',
                       '推薦好友', '點數商店', '已收藏的妝容對比圖'];
MEMBER_BLOCKS.forEach(title => {
    check(`區塊還在：${title}`, profileCode.includes(`<h2>${title}</h2>`));
});
// 每一塊都要真的包在區塊容器裡，不是散在頁面上。
check('區塊數量與點名一致（沒有多出無名區塊）',
    count(profileCode, '<section class="member-tier">')
    + count(profileCode, '<section class="member-suggestions">') === MEMBER_BLOCKS.length,
    `${count(profileCode, '<section class="member-tier">')} + ${count(profileCode, '<section class="member-suggestions">')}`);

console.log('');
console.log('=== 2. 大頭貼 ===');
check('頭貼是 button 不是 div', profileCode.includes('<button type="button" class="member-avatar"'));
check('備援樣板同步', routerCode.includes('<button type="button" class="member-avatar"'));
check('有檔案輸入', profileCode.includes('id="profileAvatarInput"')
    && routerCode.includes('id="profileAvatarInput"'));
check('訪客不能按（沒有 email 就 disabled）', routerCode.includes('__canEdit = !!profile.email')
    && routerCode.includes('__av.disabled = !__canEdit'));
check('先寫遠端再更新本機', (() => {
    const i = routerCode.indexOf('Api.patchMember(email, { avatar: dataUrl })');
    const j = routerCode.indexOf('Auth.setProfile({ ...profile, avatar: dataUrl })');
    return i > 0 && j > i;
})());
check('上傳中擋掉重複點擊', routerCode.includes('if (avatarUploading) return;'));
check('鎖一定會解開（用 finally）', /finally\s*\{[\s\S]*?avatarUploading = false/.test(routerCode));
check('縮圖後才上傳', routerCode.includes("cv.toDataURL('image/jpeg'")
    && routerCode.includes('function readAvatarFile'));
check('取中間正方形而不是壓扁', routerCode.includes('(w - side) / 2, (h - side) / 2, side, side'));
check('鍵盤聚焦看得到', cssCode.includes('.member-avatar:focus-visible'));

console.log('');
console.log('=== 3. 分析結果區的兩種狀態 ===');
check('有狀態容器', profileCode !== null && read('pages/analysis.html').includes('class="result-panel"'));
check('備援樣板同步', routerCode.includes('<div class="result-panel" id="resultPanel">'));
// 灰階程度 2026-08-29 從 grayscale(1)+opacity .55 降到 .55/.9：手機上原本糊到
// 連「臉型」兩個字都讀不出來，而設計稿圖 7 的鎖定態是清楚的——靠右上角那把鎖
// 說「還沒解鎖」，不是靠把畫面弄暗。所以這裡驗的是「有做灰階處理」，
// 不是特定數值；數值調整不該讓這一項變紅。
check('沒結果時灰階', /\.result-panel:not\(\.is-ready\) \{[^}]*grayscale\(/.test(cssCode));
check('有結果時抬起', cssCode.includes('.result-panel.is-ready .result-grid')
    && /\.result-panel\.is-ready \.result-grid \{[^}]*box-shadow/.test(cssCode));
check('尊重 prefers-reduced-motion', /prefers-reduced-motion[\s\S]{0,400}\.result-panel/.test(cssCode));
// 這是實際踩過的坑：判斷寫在清空之前，會在剛進頁面時把一堆「—」畫成已完成的樣子
check('狀態判斷在 analysisResult 清空之後', (() => {
    const clear = routerCode.indexOf('Router.analysisResult = null;\n        if (typeof AnalysisDraft');
    const set = routerCode.indexOf('setResultState(false);', clear);
    return clear > 0 && set > clear && set - clear < 400;
})(), '進頁一律灰階');
check('分析完成才抬起', routerCode.includes('setResultState(true)'));
check('重跑分析退回灰階', /analyzeBtn\.onclick[\s\S]{0,120}setResultState\(false\)/.test(routerCode));
check('沒結果時不邀請點擊', cssCode.includes('.result-panel:not(.is-ready) .result-cell[data-fa-field] .rmore'));

console.log('');
console.log('=== 4. 登入畫面 ===');
check('欄位置中', cssCode.includes('.auth-form-panel .input-group { text-align:center; }'));
check('標籤不再與上方同一套字', /\.auth-form-panel \.input-group label \{[^}]*text-transform:none/.test(cssCode));
check('標籤改用中文字體', /\.auth-form-panel \.input-group label \{[^}]*var\(--cjk\)/.test(cssCode));
// 密碼欄的顯示鈕是絕對定位的，只給單邊內距會把置中的文字推歪
check('密碼欄兩側內距對稱',
    /\.auth-form-panel \.input-group\.has-pw-toggle input \{[^}]*padding-left:52px[^}]*padding-right:52px/.test(cssCode));

console.log('');
console.log('=== 5. 不再有永遠旋轉的圈 ===');
check('index.html 沒有旋轉元素', !noComment(index).includes('goldCursorFlow'));
check('CSS 沒有殘留選擇器', !cssCode.includes('gold-cursor-flow'));
check('動畫本身已移除', !cssCode.includes('goldFlowSpin'));
check('柔光留著（那個不會動）', cssCode.includes('.cursor-glow'));

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
