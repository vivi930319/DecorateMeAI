// 五官圖鑑。
//
// 這個功能有三個地方壞掉不會報錯，只會安靜地不動或給出錯的答案：
//
//   1. 分類清單抄第二份 —— api.js 的 AnalysisFeedback.OPTIONS 是送出回饋的依據，
//      圖鑑若自己維護一份，兩邊遲早分岔。2026-08-24 就發生過：OPTIONS 多一個
//      「細長眼」，而模型早把它併進鳳眼，使用者選到就整包被後端退回。
//   2. 改答案自己送出 —— 送出的路徑只能有一條，同意條款、影像上傳說明、_modelRaw
//      比對全長在回饋面板裡，另寫一套等於把那些保護繞過去。
//   3. 浮層沒收乾淨 —— 它掛在 body 上，換頁不會跟著消失，而且 body 的
//      overflow:hidden 解不開的話整頁捲不動，看起來像當掉。
//
// 用法：node tests/feature_atlas_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const atlas = fs.readFileSync(path.join(ROOT, 'js/feature-atlas.js'), 'utf8');
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8');
const router = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'pages/analysis.html'), 'utf8');
const index = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};

console.log('\n=== 1. 分類清單只有一份 ===');
check('圖鑑讀 AnalysisFeedback.OPTIONS', atlas.includes('AnalysisFeedback.OPTIONS[field]'));
// 這一條防的正是 2026-08-24 那個 bug 再來一次
const listLiteral = /OPTIONS\s*[:=]\s*(Object\.freeze\()?\{/.test(atlas)
  || /'眼型'\s*:\s*\[/.test(atlas);
check('圖鑑沒有自己維護一份分類清單', !listLiteral);

console.log('\n=== 2. 眼型的分類要跟線上模型一致 ===');
const eyeLine = (api.match(/'眼型':\s*\[([^\]]*)\]/) || [, ''])[1];
// models/basic_features_roi/eye_shape_classes.json 是 ['下垂眼','圓眼','桃杏眼','鳳眼']
check('眼型不再包含已合併的「細長眼」', !eyeLine.includes('細長眼'), eyeLine.trim());
check('眼型是四類', (eyeLine.match(/'/g) || []).length / 2 === 4, eyeLine.trim());

console.log('\n=== 3. 改答案走回饋面板，不自己送出 ===');
check('去操作 data-af-field 的 select', atlas.includes('[data-af-field='));
check('有觸發 change 事件（不然 router 的處理器不會跑）',
  /dispatchEvent\(new Event\('change'/.test(atlas));
// 自己打 API 就是繞過同意條款那一段
check('沒有自己呼叫送出回饋的 API',
  !/submitFaceFeedback|jobFeedbackPath|\/feedback['"`]/.test(atlas));
check('找不到面板時明說，不靜默失敗', atlas.includes('回饋面板還沒載入'));
// 選項不在清單裡就別送——送了會被後端整包退回
check('選項不在 select 裡會擋下來', atlas.includes('不在目前的可選清單裡'));

console.log('\n=== 4. 浮層的生命週期 ===');
check('換頁會關掉浮層', /FeatureAtlas\.close\(\)/.test(router));
check('關閉時解除 body 的捲動鎖', /document\.body\.style\.overflow = ''/.test(atlas));
check('開啟時鎖住背景捲動', /document\.body\.style\.overflow = 'hidden'/.test(atlas));
check('ESC 可以關', /e\.key === 'Escape'/.test(atlas));
check('點背景可以關', atlas.includes('data-fa-close'));
check('焦點困在浮層裡', /e\.key !== 'Tab'/.test(atlas) && atlas.includes('shiftKey'));
check('關閉後焦點回到原本的格子', atlas.includes('lastFocus.focus()'));

console.log('\n=== 5. 沒有結果時不該開 ===');
// 分析還沒跑完時六格都是「—」，開了只會看到對不上的說明
check('值是「—」或空的就不開', /!current \|\| current === '—'/.test(atlas));

console.log('\n=== 6. 鼻型要顯示 PRO 的側臉結果 ===');
// 直接讀 analysisResult['鼻型'] 會把畫面打回 BASIC 的答案
check('鼻型走 noseDisplayText', /field === '鼻型'[\s\S]{0,140}noseDisplayText/.test(router));

console.log('\n=== 7. 接線 ===');
check('analysis.html 的五格有 data-fa-field',
  (html.match(/data-fa-field=/g) || []).length === 5,
  `${(html.match(/data-fa-field=/g) || []).length} 格`);
// 色彩季型不是 CNN 分類，是色彩計算出來的，沒有分類圖鑑
check('色彩季型沒有被標成可點', !html.includes('data-fa-field="色彩季型"'));
check('index.html 有載入 feature-atlas.js', index.includes('js/feature-atlas.js'));
check('feature-atlas 排在 router 之前',
  index.indexOf('feature-atlas.js') < index.indexOf('js/router.js'));
check('分析頁初始化時 attach', /FeatureAtlas\.attach\(/.test(router));
check('修正套用後會 refresh', /FeatureAtlas\.refresh\(\)/.test(router));

console.log('\n=== 8. 樣式 ===');
check('浮層樣式存在', css.includes('.fa-sheet'));
check('手機是底部 sheet、桌機置中',
  /@media \(min-width:700px\)[\s\S]{0,400}\.fa-layer \{ align-items:center/.test(css));
// 觸控裝置沒有 hover，提示要一直看得到
check('觸控裝置也看得到「看說明」', /@media \(hover:none\)[\s\S]{0,120}\.rmore/.test(css));
check('尊重 prefers-reduced-motion', /prefers-reduced-motion[\s\S]{0,120}\.fa-sheet/.test(css));

console.log('\n=== 9. 圖片版位 ===');
check('先試圖片再退回 SVG', atlas.includes('onerror=') && atlas.includes('data-fb'));
check('檔名有做 URL 編碼（分類是中文）', atlas.includes('encodeURIComponent(name)'));

console.log('\n=== 10. HTML 逃脫 ===');
check('分類名稱有逃脫', /esc\(name\)/.test(atlas));
check('說明文字有逃脫', /esc\(def\.how\)/.test(atlas));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
