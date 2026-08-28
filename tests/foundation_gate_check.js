// 粉底膚色色差 0～2 與替代色 0～5（契約 2026-08-27）的驗收清單。
//
// 這一份的重點是**兩個門檻的比較對象不同**：
//   主推薦   使用者膚色 vs 粉底色號   ΔE00 ≤ 2.0   硬性過濾
//   替代色   主推薦色號 vs 替代色     ΔE00 ≤ 5.0   同品牌同系列
//
// 混為一談的後果很具體：把替代色的數字寫成「與您的膚色…」，
// 使用者會以為那支也通過了膚色檢查，而它根本不必貼近膚色——
// 它的用途是同系列裡明暗不同的選擇。契約 §7 明文禁止這種寫法。
//
// 用法：node tests/foundation_gate_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8');

const cut = (s, sig) => {
    const i = s.indexOf(sig);
    if (i < 0) throw new Error('找不到 ' + sig);
    let d = 0;
    for (let k = s.indexOf('{', i); k < s.length; k++) {
        if (s[k] === '{') d++;
        else if (s[k] === '}') { d--; if (!d) return s.slice(i, k + 1); }
    }
};

const sb = { Router: {}, escapeHtml: (s) => String(s), console,
             AnalysisDraft: { load: () => null } };
vm.createContext(sb);
vm.runInContext(cut(src, 'function hasMatch(node) {') + '\n'
  // 色差與門檻兩句由 foundationSkinLines 統一產生，推薦面板與色號比較區共用；
  // 抽了用它的函式沒抽它，測試會在執行時炸 ReferenceError。
    + cut(src, 'function foundationSkinLines(skin) {') + '\n'
    + cut(src, 'function currentShadeRecommendation() {') + '\n'
    // shadeRecommendationHtml 會呼叫 userSkinRow（把使用者膚色擺在三欄上面）。
    // 抽了前者沒抽相依，測試會在執行時炸 ReferenceError。
    + cut(src, 'function userSkinRow() {') + ';\n'
    + cut(src, 'function shadeRecommendationHtml(p) {') + '\n'
    + cut(src, 'function colorDiffInfo(p) {') + '\n'
    + cut(src, 'function colorDiffEntryHtml(p) {') + '\n'
    + cut(src, 'function recommendationCardHtml(p) {') + '\n'
  // 推薦標籤由 recLabel 統一產生（契約 2026-08-28 §5 改了措辭）。
  // 抽了用它的函式沒抽它，測試會在執行時炸 ReferenceError。
    + cut(src, 'function recLabel(raw) {') + '\n'
    + "const REC_LABEL = '根據臉部分析結果推薦';"
    + "const LEGACY_REC_LABEL = '根據系統演算法推薦';\n"
    + cut(src, 'function recommendationPanelHtml(p) {') + '\n'
    + 'globalThis.__shade = shadeRecommendationHtml;'
    + 'globalThis.__card = recommendationCardHtml;'
    + 'globalThis.__panel = recommendationPanelHtml;', sb);
const shade = sb.__shade, cardFn = sb.__card, panelFn = sb.__panel;

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};

const sr = {
    method: 'lab_lightness_approximation', official: false,
    anchor: { label: '主推薦色號', shadeCode: 'PO-02', matchPercent: 92, anchorDeltaE: 0,
              description: '目前最接近你的膚色明暗與色調。',
              product: { id: 'api-foundations-968',
                         foundationSkinMatch: { deltaE: 1.46, accepted: true,
                                                minInclusive: 0, maxInclusive: 2 } } },
    lighter: { label: '較明亮的替代色', shadeCode: 'PO-03', matchPercent: 41, anchorDeltaE: 4.59,
               description: '適合希望提亮膚色時比較。',
               product: { id: 'api-foundations-969',
                          foundationSkinMatch: { deltaE: 4.59, accepted: false,
                                                 minInclusive: 0, maxInclusive: 2 } } },
    darker: { label: '較深的替代色', shadeCode: 'O-03', matchPercent: 44, anchorDeltaE: 4.27,
              description: '適合近期有日曬時比較。',
              product: { id: 'api-foundations-970',
                         foundationSkinMatch: { deltaE: 4.27, accepted: false,
                                                minInclusive: 0, maxInclusive: 2 } } },
    disclaimer: '不代表品牌定義的淺一階或深一階。',
};
sb.Router.shadeRecommendation = sr;
const out = shade({ id: 'api-foundations-968' });

console.log('');
console.log('=== 1. 兩個門檻的比較對象不能混 ===');
check('主推薦寫「與您的膚色」', /與您的膚色[^<]*色差 1\.5/.test(out));
check('替代色寫「與主推薦色號」', out.includes('與主推薦色號的色差 4.6'));
check('替代色也標明是跟主推薦比', out.includes('與主推薦色號的色差 4.3'));
// 契約 §7 明文禁止：替代色本來就不必貼近膚色
check('替代色不得寫成與膚色匹配',
  !/較明亮的替代色[\s\S]{0,160}與您的膚色/.test(out)
  && !/較深的替代色[\s\S]{0,160}與您的膚色/.test(out));
// 替代色的 foundationSkinMatch.deltaE 是它跟膚色的色差，不能拿來當 anchorDeltaE
check('替代色不用自己的膚色色差充數',
  /anchorDeltaE/.test(cut(src, 'function shadeRecommendationHtml(p) {')));

console.log('');
console.log('=== 2. 門檻要寫出來 ===');
check('主推薦標示通過 0～2 門檻', out.includes('膚色色差 0～2 推薦門檻'));
// 未通過門檻的不會是主推薦，所以那句話不該出現在別的地方
sb.Router.shadeRecommendation = { ...sr,
    anchor: { ...sr.anchor,
              product: { ...sr.anchor.product,
                         foundationSkinMatch: { deltaE: 2.54, accepted: false,
                                                minInclusive: 0, maxInclusive: 2 } } } };
check('未通過門檻就不寫「通過門檻」',
  !shade({ id: 'api-foundations-968' }).includes('推薦門檻'));

console.log('');
console.log('=== 3. 缺欄位時不要編數字 ===');
sb.Router.shadeRecommendation = { ...sr,
    lighter: { ...sr.lighter, anchorDeltaE: null } };
const noDelta = shade({ id: 'api-foundations-968' });
check('沒有 anchorDeltaE 就不顯示那一行',
  !/較明亮的替代色[\s\S]{0,120}色差/.test(noDelta));
check('但色號本身照常顯示', noDelta.includes('PO-03'));
sb.Router.shadeRecommendation = { ...sr,
    anchor: { ...sr.anchor, product: { id: 'api-foundations-968' } } };
check('沒有 foundationSkinMatch 時不硬寫膚色色差',
  !shade({ id: 'api-foundations-968' }).includes('與您的膚色'));

console.log('');
console.log('=== 4. no_match 的處置（§4、§7）===');
const notice = cut(src, 'foundationNoticeHtml() {');
check('有 no_match 的說明區塊', Boolean(notice));
// 訊息一律用後端的：兩邊各寫一份說法遲早不一致
check('訊息取自後端而不是自己寫', notice.includes('st.message'));
check('matched 時不顯示', /status === 'matched'/.test(notice));
// 最接近的那支確實存在，但它沒通過檢查——放購買按鈕等於把
// 「我們查過了」的信任借給一個沒通過的商品
check('沒有給購買或查看商品的入口',
  !/data-bag|data-shade-go|加入購物|查看商品/.test(notice));
check('樣式存在', css.includes('.rec-foundation-note'));

console.log('');
console.log('=== 4b. closest_available：可以顯示，但不能背書（§5、§7）===');
// 2 < ΔE ≤ 5 的那一件會出現在清單上，但它**沒有通過**膚色門檻。
// 「根據系統演算法推薦」與 MATCH 都是背書，而使用者分不出
// 「系統推薦的」與「系統找到最接近的」差在哪，除非畫面自己講清楚。
const closestProduct = {
    id: 'api-foundations-968',
    showMatchPercent: false,
    foundationSkinMatch: { deltaE: 2.54, accepted: false, displayEligible: true,
                           displayStatus: 'closest_available', displayMaxInclusive: 5 },
    recommendationPresentation: { systemLabel: '根據系統演算法推薦', matchLabel: '78% MATCH',
                                  matchPercent: 78, headline: '很適合你的整體妝容',
                                  summary: '這款底妝…', showMatchPercent: false,
                                  // 真實 API 的粉底都有這一包；沒有它色差入口本來就不該出現
                                  colorDifferenceExplanation: { value: 2.54, displayValue: '色差 2.5',
                                                                level: '整體相近', qa: [], ranges: [] } },
};
const cardOut = cardFn(closestProduct);
const panelOut = panelFn(closestProduct);
check('卡片標成「目前最接近的可比較色號」', cardOut.includes('目前最接近的可比較色號'));
check('卡片不寫「根據系統演算法推薦」', !cardOut.includes('根據系統演算法推薦'));
check('卡片不印 MATCH', !cardOut.includes('MATCH'));
check('卡片說明未達門檻', cardOut.includes('未達正式匹配門檻'));
check('卡片標明比較對象是膚色', cardOut.includes('與您的膚色的色差 2.5'));
check('詳情面板同樣不背書',
  !panelOut.includes('根據系統演算法推薦') && !panelOut.includes('MATCH'));
check('詳情面板仍給色差說明入口', panelOut.includes('data-color-diff'));
// showMatchPercent 只在後端明確給 false 時才隱藏，其他商品維持原本行為
const normalOut = cardFn({ id: 'p9',
    recommendationPresentation: { systemLabel: '根據系統演算法推薦',
                                  matchLabel: '82% MATCH', matchPercent: 82 } });
check('一般商品照常顯示 MATCH', normalOut.includes('82% MATCH'));

console.log('');
console.log('=== 4c. 色號要出現在卡片上 ===');
// 色號是使用者實際要記住、要拿去櫃上問的那個字串。先前它只存在於商品名稱
// 結尾（「…SPF 48/ PA++ - PO-02」），要自己從一長串裡找。詳情頁早就有
// 「色號 Shade」那一格，卡片沒有——但看清單比較好幾支時才是最需要它的時候。
check('api 保留 shadeCode', api.includes('shadeCode: product.shadeCode'));
// 後端沒給 shadeCode 時退回 shadeName，兩個都沒有才不顯示
check('shadeCode 缺少時退回 shadeName',
  /shadeCode: product\.shadeCode[\s\S]{0,140}shadeName/.test(api));
check('卡片會畫色號', src.includes('class="pc-shade"'));
// 眼影腮紅那些後端沒給色號，不能因此留一個空欄位
check('沒有色號就整格不出現', /\$\{p\.shadeCode \? /.test(src));
check('色號樣式存在', css.includes('.pc-shade'));

console.log('');
console.log('=== 4d. 比較色號要看得到顏色 ===');
// 只給 PO-03 這種代碼，等於要人憑三個字元想像那是什麼顏色。
// 而使用者要回答的問題不是「這三支差多少」，是「哪一支比較像我」——
// 基準不在畫面上，那個問題就答不了。
const shadeSrc = cut(src, 'function shadeRecommendationHtml(p) {');
check('每一欄都畫色塊', shadeSrc.includes('sc2-swatch') && shadeSrc.includes('labToRgb'));
check('沒有 lab 就不畫色塊，不用預設色', /const lab = Array\.isArray\(prod\.lab\)/.test(shadeSrc));
const skinRow = cut(src, 'function userSkinRow() {');
check('三欄上面有使用者自己的膚色', Boolean(skinRow) && shadeSrc.includes('userSkinRow()'));
check('膚色缺 lab 時整列不出現', /if \(!Array\.isArray\(lab\) \|\| lab\.length !== 3\) return ''/.test(skinRow));
// 拿一個不可信的膚色去比色，比不比還糟——使用者會以為自己比對過了
check('取樣不可信要講出來', skinRow.includes('labReliable === false') && skinRow.includes('僅供參考'));
check('色塊樣式存在', css.includes('.sc2-swatch') && css.includes('.sc2-mine'));

console.log('');
console.log('=== 5. api 層要把新欄位帶過來 ===');
check('帶 anchorDeltaE', api.includes('anchorDeltaE:'));
check('帶 foundationSkinMatch', api.includes('foundationSkinMatch:'));
check('帶 colorDifferencePolicy', api.includes('colorDifferencePolicy:'));
check('帶 foundationMatchStatus', api.includes('foundationMatchStatus:'));
check('帶 showMatchPercent', api.includes('showMatchPercent:'));
// 欄位不存在的商品要維持原本行為，只有明確 false 才隱藏
check('showMatchPercent 只認明確的 false',
  api.includes("showMatchPercent === false) ? false : true"));
// 門檻一律以後端為準，前端不自己算也不自己放寬
check('前端不自己寫死門檻數字',
  !/deltaE\s*[<>]=?\s*2(\.0)?\b/.test(src));

console.log('');
console.log('=== 6. 詳情頁不得把同一組背書印兩次 ===');
// 推薦面板與色號比較區原本各印一次「✦ 根據系統演算法推薦 / N% MATCH / 色差 / 門檻」。
// 同一件事講兩次不會更有說服力，只會讓人以為那是兩個各自算出來的判斷。
const mergedProduct = {
  id: 'api-foundations-968',
  recommendationPresentation: {
    systemLabel: '根據系統演算法推薦', matchPercent: 84,
    headline: '很適合你的整體妝容', suitedTraits: ['春季', '白皙自然色', '千金妝'],
    summary: '這款底妝的明暗與色調和你的膚色協調。',
    reasonTexts: ['此色號與您的膚色相近（色差 1.3）', '色調與你的四季型一致'],
    disclaimer: '推薦匹配度是系統用於商品排序的綜合結果。',
  },
  foundationSkinMatch: { deltaE: 1.3, accepted: true, minInclusive: 0, maxInclusive: 2 },
};
const mergedPanel = panelFn(mergedProduct);
// 合併與否取決於**同一個商品物件**有沒有 recommendationPresentation：
// 有，色號比較區就把表頭讓給推薦面板。用上面那個沒有 presentation 的 out 來比，
// 測的是另一種情況。
// 前面幾組測試把 Router.shadeRecommendation 換成各種殘缺版本試探邊界，
// 這裡要的是完整資料，先放回原本那份，否則量到的是別人留下的狀態。
sb.Router.shadeRecommendation = sr;
const mergedShade = shade(mergedProduct);
const both = mergedPanel + mergedShade;
const times = (hay, needle) => hay.split(needle).length - 1;
  // 契約 2026-08-28 §5 把措辭從「根據系統演算法推薦」改成「根據臉部分析結果推薦」，
  // 並要求全站不得再出現舊的那一句。後端可能還在回舊字串，前端用 recLabel 映射掉。
check('✦ 推薦標示全頁只有一次', times(both, '根據臉部分析結果推薦') === 1,
  `出現 ${times(both, '根據臉部分析結果推薦')} 次`);
check('全站不再出現舊措辭', !both.includes('根據系統演算法推薦'));
check('% MATCH 全頁只有一次', times(both, '% MATCH') === 1,
  `出現 ${times(both, '% MATCH')} 次`);
// 「與您的膚色」在合併後仍會出現兩次，而那兩次不是重複：
//   推薦面板  「與您的膚色接近（色差 1.3）」——結論
//   主推薦欄  「與您的膚色的色差 1.3」——標示這一欄的數字是跟什麼比的
// 後者不能拿掉：三欄並排的意義就在於 1.3 / 4.7 / 4.6 放在一起看，
// 而契約 §7 要求主推薦與替代色的比較對象在畫面上分得出來。
// 會重複的是**結論句**，所以量的是結論句。
check('膚色結論句只有一次', times(both, '與您的膚色接近（色差') === 1,
  `出現 ${times(both, '與您的膚色接近（色差')} 次`);
check('主推薦欄仍標明比較對象', mergedShade.includes('與您的膚色的色差'));
check('替代色欄比的是主推薦色號', mergedShade.includes('與主推薦色號的色差'));
check('門檻句只有一次', times(both, '推薦門檻') === 1);
check('色差門檻落在推薦面板裡', mergedPanel.includes('rec-gate') && mergedPanel.includes('rec-skinline'));
// 後端的 reasonTexts 常有一句就是在講色差，與 matchWord 同義
check('同義的理由句被濾掉', !mergedPanel.includes('此色號與您的膚色相近'));
check('其他理由句照留', mergedPanel.includes('色調與你的四季型一致'));
// 推薦面板不在（後端沒給 recommendationPresentation）時，比較區要自己撐起來
// Router.shadeRecommendation 是模組層共用的，前面測試已經設好；
// 沒有推薦面板時（p 不帶 presentation），比較區要自己撐起表頭。
check('沒有推薦面板時比較區自己印',
  out.includes('根據臉部分析結果推薦') && out.includes('與您的膚色'));
check('讓出表頭時不留空的 sr-hero', !/<div class="sr-hero">\s*<\/div>/.test(mergedShade));
check('讓出表頭後三欄比較還在', mergedShade.includes('sc2-row')
  && mergedShade.includes('主推薦色號'));

console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
