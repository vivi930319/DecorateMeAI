// 手機版設計稿（LINE_ALBUM_改版_260828，12 張）的結構驗收。
//
// 為什麼要有這一支：2026-08-29 使用者的原話是「你沒有嚴格執行我給你的前端設計」。
// 那不是一次疏忽，是**沒有任何東西在盯**——設計稿是 12 張圖片，實作散在
// index.html、pages/*.html、js/router.js 的備援樣板與 css/main.css 四個地方，
// 少掉一個元件不會有人發現，直到有人拿手機打開那一頁。
//
// ⚠️ 這一支能檢查什麼、不能檢查什麼，要講清楚：
//   能：某個元件在不在、數量對不對、手機斷點有沒有處理、兩份樣板有沒有同步。
//   不能：間距、字級、圖片比例、顏色深淺——那些非得看到畫面才判斷得了。
// 所以它綠燈**不等於**「跟設計稿一模一樣」，只等於「該有的東西都還在」。
//
// 商品頁（圖 5）刻意不在檢查範圍內：使用者明確指定那一頁用我們自己的版本，
// 因為它有搜尋、品牌、價格、排序這些設計稿沒有的功能。
//
// 用法：node tests/mobile_design_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
// 換行一律正規化。跨行的字面比對在 CRLF 下會安靜地恆真或恆假，
// 而恆真的那種等於這支檢查從此不再檢查任何東西（見 member_center_check 的同一段）。
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8').replace(/\r\n/g, '\n');

const index = read('index.html');
const router = read('js/router.js');
const css = read('css/main.css');
const dashboard = read('pages/dashboard.html');
const about = read('pages/about.html');
const analysis = read('pages/analysis.html');
const profile = read('pages/profile.html');

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};
const count = (hay, needle) => hay.split(needle).length - 1;
// 某個選擇器在某個斷點的 @media 區塊裡有沒有被處理。
// 不比對宣告內容——那會變成把 CSS 抄一遍，改個數值就紅。
//
// ⚠️ 同一個斷點在這份 CSS 裡出現很多次，所以要掃過**每一個**，不能只看第一個；
// 而且區塊結尾不能用第一個 `\n}` 判斷——@media 裡的第一條規則就會結束在那裡，
// 於是切出來的範圍只有開頭幾行。這裡改成數大括號，切到真正的區塊結尾。
const inMedia = (query, selector) => {
    const needle = `@media (max-width:${query}px)`;
    for (let i = css.indexOf(needle); i >= 0; i = css.indexOf(needle, i + 1)) {
        let depth = 0, end = -1;
        for (let j = css.indexOf('{', i); j < css.length && j >= 0; j++) {
            if (css[j] === '{') depth++;
            else if (css[j] === '}' && --depth === 0) { end = j; break; }
        }
        if (end > i && css.slice(i, end).includes(selector)) return true;
    }
    return false;
};

console.log('=== 圖 1 登入 ===');
check('編輯式雙欄版面', router.includes('class="auth-editorial"'));
check('品牌側欄有大標與副文', router.includes('class="auth-brand-panel"'));
check('信箱與密碼都是帶圖示的欄位', count(router, 'class="ig-field"') >= 2);
check('忘記密碼靠右', router.includes('class="ig-aside"')
    && router.includes('showForgotPassword()'));
check('登入是整寬主按鈕', /btn-gold btn-full[^>]*onclick="doLoginAction\(\)"/.test(router));
check('有「或」分隔線', router.includes('class="auth-or"'));
check('訪客登入是整寬次按鈕', /btn-outline btn-full[^>]*onclick="doGuestLogin\(\)"/.test(router));
check('底部有註冊入口', router.includes('showRegister()'));

console.log('');
console.log('=== 圖 2 首頁 ===');
check('主視覺有 kicker、標題、副標', dashboard.includes('class="hh-kicker"')
    && dashboard.includes('class="hh-title"') && dashboard.includes('class="hh-sub"'));
check('主視覺有行動按鈕', dashboard.includes('class="btn-gold hh-cta"'));
check('主視覺線稿用設計稿原圖', dashboard.includes('assets/brand/home-hero-line.png'));
check('有問候條（月亮那條）', dashboard.includes('class="home-greet"')
    && dashboard.includes('class="hg-moon"'));
// 這兩個出口是 2026-08-29 補的。首頁只列三個風格、四件商品，
// 各自後面都有一整頁；沒有連結的話，清單看起來就是全部庫存。
check('風格靈感有「查看全部」出口', /sh-l[\s\S]{0,120}風格靈感[\s\S]{0,160}sh-link/.test(dashboard));
check('為你精選有「查看更多」出口', /sh-l[\s\S]{0,120}為你精選[\s\S]{0,160}sh-link/.test(dashboard));
check('兩個出口都接得上導航', count(dashboard, 'class="sh-link" data-nav=') === 2);
check('標題列有 gap（窄螢幕不會撞在一起）',
    /\.dash-sec-head \{[^}]*gap:/.test(css));
// 「為你精選」在手機上是橫向滑動的照片牆。
// ⚠️ 這一項**刻意與設計稿不同**：圖 2 畫的是四件並排的方格，2026-08-29 使用者
// 指定改成可以滑的（「01 IG 那種放照片的方式」）。記在這裡是為了讓下一個人
// 知道它不是漏掉，而是被指定改掉的——否則有人會「照設計稿修好」它。
check('為你精選是橫向滑動，不是方格',
    /@media[^{]*\{[\s\S]{0,4000}\.glow-row \{[^}]*display:flex[^}]*overflow-x:auto/.test(css));
check('滑動有貼齊與邊緣出血',
    /\.glow-row \{[^}]*scroll-snap-type:x/.test(css)
    && /\.glow-row \{[^}]*margin-left:-18px/.test(css));
check('卡片固定寬度才滑得動',
    /\.glow-card \{[^}]*flex:0 0 [0-9]/.test(css));
check('出口不換行', /\.dash-sec-head \.sh-link \{[^}]*white-space:nowrap/.test(css));

console.log('');
console.log('=== 圖 3 關於我們 ===');
check('簡介卡有線稿', about.includes('class="ai-art"')
    && about.includes('assets/brand/about-line.png'));
check('特色剛好四張', count(about, 'class="af-card"') === 4);
check('四張都有圖示', count(about, 'class="af-icon"') === 4);
check('會員權益區塊在（依實際狀態填入）', about.includes('id="aboutPremium"'));
check('底部資安條', about.includes('class="about-privacy"'));
// 設計稿圖 3 從頭到尾都是四欄。這一項擋的是「手機放不下所以降成兩欄／一欄」
// 那種自作主張——2026-08-29 發生過兩次，而且兩次都在程式裡留了看起來很合理的理由，
// 所以擋法是「任何 @media 裡都不准把它降欄」，不是只檢查某一個斷點。
check('四欄，任何斷點都不降欄',
    /\.about-features \{[^}]*repeat\(4/.test(css)
    && !/\.about-features \{[^}]*grid-template-columns:repeat\([123],/.test(css));
check('特色圖示用設計稿裁的插圖', ['af-analyze', 'af-style', 'af-shop', 'af-save']
    .every(n => about.includes(`assets/feature/${n}.webp`)
        && fs.existsSync(path.join(ROOT, `assets/feature/${n}.webp`))));

console.log('');
console.log('=== 圖 4 抽屜選單 ===');
check('抽屜有品牌頭', index.includes('class="drawer-head"')
    && index.includes('class="drawer-mark"') && index.includes('class="drawer-brand"'));
check('品牌章是圖片不是字', /drawer-mark[^>]*>\s*<img/.test(index));
check('底部資安卡', index.includes('class="drawer-foot"'));
check('每一項都有圖示', count(index, 'class="nav-ico"') >= 8);
// 設計稿圖 4 的抽屜從**左邊**滑出。線上原本是右上角彈出的深色下拉卡——
// 那是 2026-08-29 早上重建時我自己決定的，不是設計稿。
check('抽屜從左邊滑出，不是右邊',
    /@media[^{]*\{[\s\S]{0,3000}\.topbar-nav \{[^}]*left:0;[^}]*transform:translateX\(-/.test(css));
// 基礎規則裡的抽屜是深色卡（#24191b），手機這一段要蓋成淺色面板。
// 驗的是「手機那一段有給它淺色底」，不是特定寫法——換成別的淺色不該讓這項變紅。
check('抽屜是淺色面板',
    /@media[^{]*\{[\s\S]{0,4000}\.topbar-nav \{[^}]*background:linear-gradient\([^)]*var\(--paper\)/.test(css));
check('漢堡在左邊', /\.topbar-menu-toggle \{[^}]*order:-1/.test(css));
// 抽屜是 .topbar 的子孫，而帶 backdrop-filter 的元素會成為 position:fixed 子孫的
// 包含塊——留著它，抽屜的 top:0／bottom:0 就變成相對於 74px 高的頂欄，
// 整片選單被壓成一條細長條（2026-08-29 使用者回報的「抽屜壞掉」）。
check('手機的頂欄關掉 backdrop-filter（否則抽屜量不到視窗高度）',
    /@media[^{]*760px[^{]*\{[\s\S]{0,600}\.topbar \{[^}]*backdrop-filter:none/.test(css));
// 四個項目的圓形圖示裁自設計稿，不是重畫的線條圖示。
check('抽屜圖示用設計稿裁的插圖',
    ['nav-face', 'nav-history', 'nav-suggestion', 'nav-about']
        .every(n => index.includes(`assets/feature/${n}.webp`)
            && fs.existsSync(path.join(ROOT, `assets/feature/${n}.webp`))));
// 設計稿的抽屜只有四項，因為另外四項在底部 tabbar。兩邊都列就是同一組導覽
// 出現兩次——所以窄螢幕要把 tabbar 那四項從抽屜藏起來。
check('窄螢幕把 tabbar 那四項從抽屜藏起來',
    /@media[^{]*\)\s*\{[\s\S]{0,4000}\.topbar-nav a\[data-page="products"\]/.test(css));

console.log('');
console.log('=== 底部 tabbar（圖 2、6、7、10、11 都有）===');
check('四個項目', count(index, '<a href="#') >= 4 && index.includes('class="tabbar"'));
check('項目與設計稿一致',
    ['#dashboard', '#products', '#favorites', '#profile']
        .every(h => new RegExp(`class="tabbar"[\\s\\S]*?href="${h}"`).test(index)));
check('每項都有圖示與文字', count(index, 'class="tb-icon"') === 4
    && count(index, 'class="tb-label"') === 4);
// 桌機的選單是右上角抽屜，再加一條固定底部列等於同一組導覽出現兩次。
check('只在窄螢幕出現', /\.tabbar \{ display:none/.test(css) && inMedia(760, '.tabbar'));
check('後台不出現', css.includes('body.admin-mode .tabbar { display:none !important; }'));

console.log('');
console.log('=== 圖 6 臉部分析（上傳） ===');
check('BASIC / PRO 兩個切換', analysis.includes('id="basicModeBtn"')
    && analysis.includes('id="proModeBtn"'));
check('PRO 未開通時上鎖', router.includes('lock-badge') && css.includes('.mode-tab.locked'));
check('虛線上傳框', analysis.includes('id="uploadBox"') && analysis.includes('class="upload-hint"'));
check('開啟鏡頭與拍照使用', analysis.includes('id="startCameraBtn"')
    && analysis.includes('id="capturePhotoBtn"'));
check('分析進度列', analysis.includes('id="packageStatus"'));
// 這一頁的五張插圖全部裁自設計稿，一張都不是重畫的近似品。
// 這一組擋的是「重構時順手換回通用線條圖示」——那會讓整頁退回上一版的樣子。
check('標題區有側臉線稿', analysis.includes('assets/feature/analysis-head.webp'));
check('上傳框是雲朵圖不是「＋」', analysis.includes('assets/feature/upload-cloud.webp')
    && !analysis.includes('<div class="upload-icon"><span>＋</span></div>'));
check('兩顆相機按鈕各有圖示', analysis.includes('assets/feature/ico-lens.webp')
    && analysis.includes('assets/feature/ico-camera.webp'));
check('分析進度列有圖示', analysis.includes('assets/feature/ico-progress.webp'));
check('五張插圖檔案都在', ['analysis-head', 'upload-cloud', 'ico-lens', 'ico-camera', 'ico-progress']
    .every(n => fs.existsSync(path.join(ROOT, `assets/feature/${n}.webp`))));
// 備援樣板（router.js 的 fallbacks.analysis）必須帶同一批插圖。
// 它只在 fetch 失敗時出現，平常測不到——掉件的樣子正好是「插圖沒上去」，
// 而且怎麼重新整理都一樣。這個專案已經在會員中心踩過同一個坑。
check('備援樣板也帶著同一批插圖',
    ['analysis-head', 'upload-cloud', 'ico-lens', 'ico-camera', 'ico-progress',
     'face', 'brow', 'eye', 'nose', 'lip', 'season']
        .every(n => router.includes(`assets/feature/${n}.webp`)));
check('備援樣板的上傳框也是雲朵', router.includes('upload-icon has-art')
    && !router.includes('<div class="upload-icon"><span>＋</span></div>'));
// 標題文案也照設計稿（原本是「分析你的臉部訊號」加一段 BASIC/PRO 的解釋）。
check('標題文案照設計稿', analysis.includes('<h1>臉部分析</h1>')
    && analysis.includes('上傳正面照片，分析五官特徵'));
check('開始分析是整寬主按鈕', /btn-gold btn-full" id="analyzeBtn"/.test(analysis));

console.log('');
console.log('=== 圖 7 分析進度與結果 ===');
// 上面那條填充條回答「跑到幾 %」，這一排回答「現在在哪一段、後面還有什麼」。
check('三段式進度存在', analysis.includes('class="analysis-steps"'));
check('剛好三段', count(analysis, '<li data-step=') === 3);
check('三段的名稱照設計稿', ['上傳照片', '生成中', '完成']
    .every(t => analysis.includes(`<span class="as-name">${t}</span>`)));
check('備援樣板也有（fetch 失敗時走那份）', router.includes('class="analysis-steps"')
    && count(router, '<li data-step=') === 3);
check('狀態由既有訊號推導，不是各處手動設定',
    router.includes('const syncAnalysisStep = ()')
    && /setLoadingStatus = \([\s\S]{0,600}syncAnalysisStep\(\)/.test(router));
check('選好照片時第一格會亮（updatePackageStatus 也要同步）',
    /updatePackageStatus = \(\) => \{[\s\S]{0,900}syncAnalysisStep\(\)/.test(router));
check('六格結果', count(analysis, 'class="result-cell"') === 6);
check('六格都上鎖', count(analysis, 'class="rlock"') === 6);
// 六格的插圖直接用設計稿裁出來的（眉毛排線、睫毛、四色圓餅，SVG 湊不出來）。
// 這一項擋的是「重構時順手換回通用線條圖示」——那會讓六格退回六個一樣的圓點。
check('六格都用設計稿的插圖', ['face', 'brow', 'eye', 'nose', 'lip', 'season']
    .every(n => analysis.includes(`assets/feature/${n}.webp`)));
check('插圖檔案都在', ['face', 'brow', 'eye', 'nose', 'lip', 'season']
    .every(n => fs.existsSync(path.join(ROOT, `assets/feature/${n}.webp`))));
check('插圖有解鎖後的狀態（跟鎖頭一起淡入）',
    css.includes('.result-panel.is-ready .result-cell .ricon img'));
check('膚色與唇色各一塊', count(analysis, 'class="skin-box"') === 2);

console.log('');
console.log('=== 圖 8 / 9 建立帳號 ===');
check('有頭貼選擇器', router.includes('class="avatar-picker"'));
check('七個欄位', ['regName', 'regPhone', 'regEmail', 'regAge', 'regPwd', 'regPwd2', 'regReferral']
    .every(id => router.includes(`id="${id}"`)));
check('推薦碼標明選填', router.includes('推薦碼（選填）'));
check('註冊是整寬主按鈕', /btn-gold btn-full" id="regSubmitBtn"/.test(router));
check('底部返回登入', router.includes('已有帳號？返回登入'));
// 密碼欄的顯示鈕由觀察器統一補上，不是每個欄位各寫一次
check('密碼欄會自動長出顯示鈕', router.includes('function enhancePasswordField'));

console.log('');
console.log('=== 圖 10 我的收藏 ===');
check('統計膠囊', router.includes('class="fav-stat"'));
check('卡片有加入購物車鈕', router.includes('class="pc-add"'));
// 收藏頁的愛心是「已收藏」狀態，按下去是移除——所以認的是 data-unfav，
// 不是商品頁那顆用來加入收藏的 data-fav。
check('卡片有愛心，且是移除收藏', /pc-heart fav"[^>]*data-unfav=/.test(router));
// 2026-08-29 決定：下架商品直接不顯示，也不提示。設計稿圖 10 畫的是
// 「12 件收藏 · 4 件已下架」，那一段刻意不照抄。
check('下架商品不列出來（刻意與設計稿不同）',
    router.includes('已下架的商品**不顯示**'));

console.log('');
console.log('=== 圖 11 會員中心 ===');
check('頭貼是按鈕', profile.includes('<button type="button" class="member-avatar"'));
check('更改密碼與登出並排', count(profile, 'class="ma-cell') === 2);
check('四張統計卡', count(profile, 'class="stat-cell"') === 4);
check('統計卡順序照設計稿', (() => {
    const order = ['收藏商品', '分析次數', '收藏妝容', '會員點數'];
    let at = -1;
    return order.every(t => { const i = profile.indexOf(t, at + 1); if (i < 0) return false; at = i; return true; });
})());
check('每張都能點進去', count(profile, 'data-goto=') + count(profile, 'data-scroll=') >= 4);
check('會員等級區塊', profile.includes('<h2>會員等級</h2>'));
check('更換主題區塊', profile.includes('theme-shop') || profile.includes('點數商店'));

console.log('');
console.log('=== 圖 12 忘記密碼 ===');
check('信封徽章', router.includes('class="auth-emblem"'));
check('徽章帶掛鎖（寄的是驗證碼，不是一般通知）',
    router.includes('class="auth-emblem-lock"'));
check('標題下的短線', router.includes('class="auth-rule"'));
check('欄位與登入頁同一套', /forgotEmail[\s\S]{0,200}/.test(router)
    && /class="ig-field"[\s\S]{0,400}id="forgotEmail"/.test(router));
check('垃圾郵件匣提示卡', router.includes('class="auth-hint"')
    && router.includes('垃圾郵件匣'));
check('返回登入是按鈕不是小字連結',
    /btn-outline btn-full" onclick="showLogin\(\)">返回登入/.test(router));
check('有「或」分隔線', /auth-card-centered[\s\S]{0,2400}class="auth-or"/.test(router));

console.log('');
console.log(`${pass}/${pass + fail} passed`);
console.log('※ 這支只驗結構。間距、字級、圖片比例要看畫面，它管不到。');
process.exit(fail ? 1 : 0);
