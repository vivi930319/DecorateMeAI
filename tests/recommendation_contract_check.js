// 推薦契約 2026-08-v2 的前端檢查。
//
// 這裡守的是**壞掉不會報錯**的那幾條：措辭違規、技術分數外洩、色階模式標籤互換。
// 它們不會讓程式當掉，只會讓畫面對使用者說錯話——而說錯話這件事沒有例外處理會攔截。
//
// 契約來源：給前端：推薦與 API 串接校對／問題回報文件（2026-08-26）
//
// 用法：node tests/recommendation_contract_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8');

const cut = (mark, text = src) => {
  const start = text.indexOf(mark);
  if (start < 0) { console.log(`找不到 ${mark}`); process.exit(1); }
  let depth = 0;
  for (let i = text.indexOf('{', start); i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}') { depth--; if (depth === 0) return text.slice(start, i + 1); }
  }
  console.log(`${mark} 括號沒收完`); process.exit(1);
};

const sandbox = {
  console,
  escapeHtml: s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  Router: { shadeRecommendation: null },
  Number, Math, Array, String, Boolean, JSON,
};
vm.createContext(sandbox);
vm.runInContext(
  cut('function recommendationCardHtml(p) {') + '\n'
  + cut('function recommendationDetailHtml(p) {') + '\n'
  // recommendationDetailHtml 現在會呼叫色差入口，抽了前者沒抽相依，
  // 測試會在執行時炸 ReferenceError——那是測試的問題，不是程式的。
  + cut('function colorDiffInfo(p) {') + '\n'
  + cut('function colorDiffEntryHtml(p) {') + '\n'
  + cut('function productSourceLinkHtml(p) {') + '\n'
  // hasMatch 是 shadeRecommendationHtml 的相依，抽了後者沒抽它，
  // 測試會在執行時炸 ReferenceError——那是測試的問題，不是程式的。
  + cut('function hasMatch(node) {') + '\n'
  + cut('function shadeRecommendationHtml(p) {') + '\n'
  + 'globalThis.__card = recommendationCardHtml;'
  + 'globalThis.__detail = recommendationDetailHtml;'
  + 'globalThis.__link = productSourceLinkHtml;'
  + 'globalThis.__shade = shadeRecommendationHtml;', sandbox);

const card = sandbox.__card, detail = sandbox.__detail;
const link = sandbox.__link, shade = sandbox.__shade;

let pass = 0, fail = 0;
const check = (name, cond, detailText) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detailText ? `  ${detailText}` : ''));
  cond ? pass++ : fail++;
};

const presentation = {
  systemLabel: '根據系統演算法推薦',
  matchPercent: 95,
  matchLabel: '95% MATCH',
  matchTier: '高度匹配',
  headline: '與你的膚色高度匹配',
  summary: '這款底妝的明暗與色調和你的膚色協調。',
  suitedTraits: ['暖色調膚色', 'medium', '千金妝'],
  reasonTexts: ['理由一', '理由二', '理由三', '理由四'],
  disclaimer: '推薦匹配度是系統用於商品排序的綜合結果，不代表實際上妝效果或準確率保證。',
};

console.log('\n=== 1. 推薦卡的措辭紅線 ===');
let out = card({ recommendationPresentation: presentation });
check('顯示「根據系統演算法推薦」', out.includes('根據系統演算法推薦'));
check('整段沒有「AI 推薦」', !/AI\s*推薦/.test(out));
check('顯示 matchLabel', out.includes('95% MATCH'));
// 少了「推薦匹配度」這四個字，95% MATCH 會被讀成 95% 準確
check('matchLabel 旁邊標示「推薦匹配度」', out.includes('推薦匹配度'));
check('沒有把 MATCH 說成準確率', !out.includes('準確率'));
check('顯示 headline', out.includes('與你的膚色高度匹配'));
check('顯示 suitedTraits', out.includes('暖色調膚色') && out.includes('千金妝'));

console.log('\n=== 2. 技術分數不得進推薦卡 ===');
const withScores = {
  recommendationPresentation: presentation,
  scoreBreakdown: { color: 0.93, style: 0.51 },
  matchScore: 0.95,
  matchedKeywords: ['champagne'],
};
out = card(withScores);
check('卡片沒有 scoreBreakdown 的數字', !out.includes('0.93') && !out.includes('0.51'));
check('卡片沒有 ΔE / deltaE', !/ΔE|deltaE/i.test(out));
check('卡片沒有原始 matchScore', !out.includes('0.95'));
check('router.js 沒有任何地方把技術證據畫進畫面',
  !/\$\{recommendationEvidenceHtml\(/.test(src));

console.log('\n=== 3. 詳情頁的完整文案 ===');
out = detail({ recommendationPresentation: presentation });
check('顯示 summary', out.includes('這款底妝的明暗'));
// 契約規定 reasonTexts 最多三項
check('reasonTexts 最多三項', out.includes('理由三') && !out.includes('理由四'));
check('顯示 disclaimer', out.includes('不代表實際上妝效果'));
check('沒有 presentation 時回空字串', detail({}) === '');
check('沒有 presentation 時卡片也回空字串', card({}) === '');

console.log('\n=== 4. 外部連結的安全屬性 ===');
out = link({ sourceUrl: 'https://example.com/p/1' });
check('有 rel="noopener noreferrer"', out.includes('rel="noopener noreferrer"'));
check('有 target="_blank"', out.includes('target="_blank"'));
check('javascript: 開頭一律不產生連結', link({ sourceUrl: 'javascript:alert(1)' }) === '');
check('非 http(s) 不產生連結', link({ sourceUrl: 'ftp://x/y' }) === '');
check('沒有網址就不產生連結', link({}) === '');

console.log('\n=== 5. 粉底色階：兩種模式的措辭不能互換 ===');
const anchorProduct = { id: 'api-foundations-1', name: '測試粉底' };
const official = {
  method: 'official_depth_index', official: true,
  anchor: { label: '主推薦色號', shadeCode: 'N20', product: anchorProduct, matchPercent: 95 },
  lighter: { label: '淺一階', shadeCode: 'N10', product: {} },
  darker: { label: '深一階', shadeCode: 'N30', product: {} },
  disclaimer: '色階依同品牌同系列的正式深淺順序提供。',
};
sandbox.Router.shadeRecommendation = official;
out = shade({ id: 'api-foundations-1' });
check('官方色階顯示「淺一階」「深一階」', out.includes('淺一階') && out.includes('深一階'));
check('顯示主推薦色號', out.includes('N20'));
check('顯示 disclaimer', out.includes('色階依同品牌同系列'));

// 版面：主推薦是主角，上下階是配角。三張等大並排會讓人以為三個都在推薦，
// 但只有中間那個是——另外兩個是「想比較的話可以看看」。
check('有演算法推薦的標示', out.includes('根據系統演算法推薦'));
check('主推薦有大字匹配度', /sr-bigmatch">95% MATCH/.test(out));
check('有「想比較不同妝效？」', out.includes('想比較不同妝效？'));
check('有完整比較按鈕', out.includes('data-shade-compare')
  && out.includes('查看三個色號的完整比較'));
// 上下階用 sr-alt 小列，不是跟主推薦一樣的卡片
check('替代色是小列不是等大卡片',
  out.includes('sr-alt') && !/class="sr-card sr-anchor"/.test(out));

// 匹配度的形容詞要跟著數字走。寫死「高度匹配」的話，62% 時畫面會用
// 很有把握的語氣說一件沒把握的事，而使用者是照這句話決定要不要買。
sandbox.Router.shadeRecommendation = {
  ...official, anchor: { ...official.anchor, matchPercent: 95 } };
check('95% → 高度匹配', shade({ id: 'api-foundations-1' }).includes('高度匹配'));
sandbox.Router.shadeRecommendation = {
  ...official, anchor: { ...official.anchor, matchPercent: 62 } };
out = shade({ id: 'api-foundations-1' });
check('62% → 不說高度匹配', !out.includes('高度匹配'));
check('62% → 說大致相符', out.includes('大致相符'));
sandbox.Router.shadeRecommendation = {
  ...official, anchor: { ...official.anchor, matchPercent: 41 } };
out = shade({ id: 'api-foundations-1' });
check('41% → 建議先試色', out.includes('建議先試色'));
// 沒有分數就整段不出現，不要自己編一個
sandbox.Router.shadeRecommendation = {
  ...official, anchor: { ...official.anchor, matchPercent: null } };
out = shade({ id: 'api-foundations-1' });
check('沒有 matchPercent → 不顯示匹配度', !out.includes('MATCH') && !out.includes('匹配'));

sandbox.Router.shadeRecommendation = official;
out = shade({ id: 'api-foundations-1' });

const approx = {
  method: 'lab_lightness_approximation', official: false,
  anchor: { label: '主推薦色號', shadeCode: 'A1', product: anchorProduct },
  lighter: { label: '較明亮的替代色', shadeCode: 'A0', product: {} },
  darker: { label: '較深的替代色', shadeCode: 'A2', product: {} },
  disclaimer: '此為依明度推估的替代色。',
};
sandbox.Router.shadeRecommendation = approx;
out = shade({ id: 'api-foundations-1' });
// 這是契約裡講得最重的一條：降級模式冒充官方色階，使用者照著買會買錯
check('降級模式顯示「較明亮／較深的替代色」',
  out.includes('較明亮的替代色') && out.includes('較深的替代色'));
check('降級模式**不得**出現「淺一階」', !out.includes('淺一階'));
check('降級模式**不得**出現「深一階」', !out.includes('深一階'));

console.log('\n=== 6. 三種 null 都不能把畫面弄壞 ===');
sandbox.Router.shadeRecommendation = null;
check('shadeRecommendation 是 null → 整個區塊不出現', shade({ id: 'x' }) === '');
sandbox.Router.shadeRecommendation = { ...official, lighter: null };
out = shade({ id: 'api-foundations-1' });
check('lighter 是 null → 只少那一格，其餘照常', !out.includes('淺一階') && out.includes('深一階'));
sandbox.Router.shadeRecommendation = { ...official, lighter: null, darker: null };
out = shade({ id: 'api-foundations-1' });
// 只有主推薦時不給比較按鈕：按開一個只有一欄的比較視窗是空動作
check('沒有替代色 → 不出現比較按鈕', !out.includes('data-shade-compare'));
check('沒有替代色 → 主推薦照常顯示', out.includes('N20'));
sandbox.Router.shadeRecommendation = { ...official, darker: null };
out = shade({ id: 'api-foundations-1' });
check('darker 是 null → 只少那一格', !out.includes('深一階') && out.includes('淺一階'));
sandbox.Router.shadeRecommendation = official;
check('不是主推薦那件商品時不顯示', shade({ id: 'api-lipsticks-9' }) === '');

console.log('\n=== 7. 接線與樣式 ===');
check('色號卡可以點開 Modal', /data-shade-kind=/.test(src) && /openShadeModal\(/.test(src));
check('Modal 有關閉按鈕', /class="sr-close"/.test(src));
check('Modal 支援 Escape 關閉', /e\.key === 'Escape'/.test(src));
check('Modal 有焦點鎖（Tab 不會跑到浮層後面）', /e\.key !== 'Tab'/.test(src));
check('關閉後把焦點還回去', /previouslyFocused/.test(src));
check('api.js 依 method 決定標籤，不讓畫面層自己拼', /_normalizeShadeRecommendation/.test(api));
check('api.js 對推薦商品去重', /seenIds/.test(api));
check('樣式存在', css.includes('.rec-match') && css.includes('.shade-rec'));

console.log('\n=== 8. 新增的錯誤碼 ===');
for (const code of ['UNAUTHENTICATED', 'ACCOUNT_SUSPENDED', 'CSRF_ORIGIN_REJECTED',
                    'INVALID_FACE_ANALYSIS', 'IDENTITY_DATA_NOT_ALLOWED']) {
  check(`${code} 有對應文案`, src.includes(code + ':'));
}

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
