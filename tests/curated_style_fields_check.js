// 商品的七妝容校對欄位必須被正規化帶下來，而且「不適用」不可以當成風格。
//
// 背景（2026-09-25 盤點發現）：商品端早就把整包妝容校對欄位開放了，
// 抽 200 筆實測 **100% 有值**：
//
//   curatedStyleScores  curatedStyleRankings  curatedStyleTags  finalStyleTags
//   finalStyle1~3       finalScore1~3         curatedStyleEligible
//   reviewReason        styleConfidence       finalColorFamily
//
// 而 js/api.js 的 _normalizeProduct **一個都沒帶**。前端唯一讀的 styleTags
// 是後端寫死的 ["daily"]，跟那七個妝容毫無關係。
//
// 後果全部是靜默的：化妝包搜尋結果看不到「這支適合什麼妝容」、延伸推薦無從篩選、
// 畫面不報錯也不空白——看起來就像後端沒做這件事，實際上是我們沒接。
//
// 另外兩個坑：
//   ① curatedStyleScores 的 key 裡混著「不適用」（抽 200 筆仍有 1 筆）。
//      那不是風格。沒濾掉的話畫面會出現「適合 不適用」。
//   ② 風格名有兩種寫法：五個帶「妝」字（港風妝），Soft Baddie 與 男士白開水
//      沒有。所以「去掉妝字再比對」會漏掉兩個，而漏掉不會報錯。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');

let failed = 0;
function check(label, ok, hint) {
  if (ok) { console.log(`  PASS ${label}`); return; }
  failed += 1;
  console.error(`  FAIL ${label}${hint ? `\n       ${hint}` : ''}`);
}

// ── 把 js/api.js 真的跑起來，拿到 Api 物件 ───────────────────────────────
// 用實跑而不是正則掃原始碼：這支要驗的是「資料真的有流過來」，
// 掃字串只能證明有寫，不能證明值是對的。
function loadApi() {
  const src = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8') + '\nglobalThis.__Api = Api;';
  const store = { getItem: () => null, setItem() {}, removeItem() {}, key: () => null, length: 0 };
  const el = () => ({ style: {}, dataset: {}, setAttribute() {}, appendChild() {}, addEventListener() {} });
  const sandbox = {
    console: { log() {}, warn() {}, error() {}, info() {} },
    localStorage: store, sessionStorage: store,
    fetch: () => Promise.reject(new Error('測試環境沒有網路')),
    navigator: { userAgent: 'node', language: 'zh-TW' },
    location: { href: 'https://x/', origin: 'https://x', protocol: 'https:', hostname: 'x', search: '' },
    setTimeout, clearTimeout, setInterval, clearInterval,
    Date, Math, JSON, Object, Array, String, Number, Boolean, RegExp, Promise, Error, Map, Set, Infinity,
    isNaN, isFinite, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
    btoa: (s) => s, atob: (s) => s, URL, URLSearchParams, TextEncoder, TextDecoder,
    crypto: { getRandomValues: (a) => a, randomUUID: () => 'x' },
    AbortController, Headers: class {}, Request: class {}, Response: class {},
    document: {
      getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
      createElement: el, addEventListener() {}, body: { appendChild() {} }, cookie: '',
    },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
    performance: { now: () => 0 }, requestAnimationFrame: (f) => f(),
    Image: class {}, Blob: class {}, FileReader: class {}, OffscreenCanvas: class {},
    CustomEvent: class {}, Event: class {}, alert() {}, confirm: () => true,
    matchMedia: () => ({ matches: false, addListener() {} }),
    screen: { width: 1, height: 1 }, history: { pushState() {} },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.top = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  if (!sandbox.__Api) throw new Error('載入 js/api.js 之後拿不到 Api');
  return sandbox.__Api;
}

console.log('=== 商品的七妝容校對欄位 ===\n');

const Api = loadApi();
const IDS = Api.RECOMMEND_STYLE_IDS;

// ① 映射表要蓋到七個 styleId，而且兩種寫法都要通
{
  const covered = new Set(Object.values(Api.STYLE_NAME_TO_ID || {}));
  const missing = IDS.filter((id) => !covered.has(id));
  check(
    '映射表蓋到全部七個風格',
    missing.length === 0,
    `漏掉 ${JSON.stringify(missing)}。漏掉的風格不會報錯，只是那些商品靜靜地對不上。`,
  );
  // 沒有「妝」字的那兩個是實測踩到的：不能用「去掉妝字」這種規則推。
  check(
    '沒有「妝」字的風格名也對得上（Soft Baddie / 男士白開水）',
    Api.styleIdFromName('Soft Baddie') === 'softBaddie'
      && Api.styleIdFromName('男士白開水') === 'mensPlain',
    '商品 API 這兩個名字不帶「妝」字，其餘五個帶。用字串規則推一定會漏這兩個。',
  );
  check(
    '帶「妝」字的寫法也對得上（港風妝）',
    Api.styleIdFromName('港風妝') === 'hongKong',
    '商品 API 實際回的是「港風妝」，不是「港風」。',
  );
}

// ② 「不適用」不可以變成風格
{
  const asStyle = Api.styleIdFromName('不適用');
  check(
    '「不適用」不會被當成風格',
    asStyle === null,
    `styleIdFromName('不適用') 回了 ${JSON.stringify(asStyle)}。`
    + '那不是風格，是「不進七妝容推薦池」。當成風格的話畫面會寫「適合 不適用」。',
  );
}

// ③ 正規化要真的把資料帶下來（拿實測抓到的真實商品當樣本）
const REAL = {
  id: 2813,
  sourceId: 2813,
  type: 'lipsticks',
  name: '輕親雲霧保濕唇膏 - Moving On Up',
  brand: 'MAC',
  candidateKey: 'lipsticks:2813',
  curatedStyleScores: { 日雜清透妝: 4, 港風妝: 5.7, 病嬌妝: 4.4 },
  curatedStyleTags: '港風妝 | 病嬌妝 | 日雜清透妝',
  finalStyleTags: '港風妝 | 病嬌妝 | 日雜清透妝',
  finalStyle1: '港風妝', finalStyle2: '病嬌妝', finalStyle3: '日雜清透妝',
  finalScore1: 5.7, finalScore2: 4.4, finalScore3: 4,
  curatedStyleEligible: true,
  curatedStyleConfidence: 0.8,
  recommendationState: '可推薦',
  curatedReviewReason: '港風妝：色系=紅/玫瑰',
  finalColorFamily: '紅/玫瑰',
  styleTags: ['daily'],
};

{
  const p = Api._normalizeProduct(REAL);
  check(
    '妝容標籤有被帶下來',
    Array.isArray(p.curatedStyleIds) && p.curatedStyleIds.length === 3,
    `curatedStyleIds = ${JSON.stringify(p.curatedStyleIds)}。`
    + '後端 100% 有值，這裡拿不到就是正規化把它丟了——畫面不會報錯，只會顯示不出來。',
  );
  check(
    '解出的是前端 styleId 不是中文名',
    (p.curatedStyleIds || []).every((id) => IDS.includes(id)),
    `curatedStyleIds = ${JSON.stringify(p.curatedStyleIds)}，應該是 ${JSON.stringify(IDS)} 裡的值。`
    + '留著中文名的話，跟 data.js 的 STYLES 比對會全部落空。',
  );
  check(
    '名次照分數遞減',
    (() => {
      const r = p.curatedStyleRankings || [];
      return r.length === 3 && r.every((x, i) => i === 0 || x.score <= r[i - 1].score);
    })(),
    `curatedStyleRankings = ${JSON.stringify(p.curatedStyleRankings)}。`
    + '名次跟分數不一致的話，同一支商品在搜尋結果與反推頁會排出不同順序。',
  );
  check(
    '第一名是分數最高的那個（hongKong 5.7）',
    (p.curatedStyleRankings || [])[0]?.styleId === 'hongKong',
    `實際第一名 ${JSON.stringify((p.curatedStyleRankings || [])[0])}。`,
  );
  check(
    'curatedStyleEligible 有帶下來',
    p.curatedStyleEligible === true,
    `實際 ${JSON.stringify(p.curatedStyleEligible)}。缺了就無法標示「不參與妝容推薦」。`,
  );
  check(
    '校對理由有帶下來',
    typeof p.curatedStyleReason === 'string' && p.curatedStyleReason.length > 0,
    '那是唯一能說明「為什麼算這個風格」的人話，也是 Ollama 生成推薦理由的依據。',
  );
  check(
    '校對色系有帶下來',
    p.finalColorFamily === '紅/玫瑰',
    `實際 ${JSON.stringify(p.finalColorFamily)}。`,
  );
}

// ④ 缺欄位的舊商品不可以被誤標
{
  const bare = Api._normalizeProduct({ id: 1, sourceId: 1, type: 'lipsticks', name: '沒有校對過的商品' });
  check(
    '沒有校對資料時給空陣列，不是 undefined',
    Array.isArray(bare.curatedStyleIds) && bare.curatedStyleIds.length === 0,
    `實際 ${JSON.stringify(bare.curatedStyleIds)}。呼叫端會直接 .length，undefined 會整頁爆掉。`,
  );
  check(
    'curatedStyleEligible 缺欄位時是 null 不是 false',
    bare.curatedStyleEligible === null,
    `實際 ${JSON.stringify(bare.curatedStyleEligible)}。`
    + 'false 會把所有舊資料都標成「不參與推薦」，比不標更誤導。',
  );
}

// ⑤ 混著「不適用」的商品：風格要清空，而且要留下「被排除過」的記號
{
  const excluded = Api._normalizeProduct({
    id: 2, sourceId: 2, type: 'lipsticks', name: '超水感持色水唇膏 - 509 Lil Squirt',
    curatedStyleScores: { 不適用: 3.2 },
    curatedStyleEligible: false,
  });
  check(
    '只有「不適用」的商品解出零個風格',
    excluded.curatedStyleIds.length === 0,
    `實際 ${JSON.stringify(excluded.curatedStyleIds)}。`,
  );
  check(
    '有記下「被排除過」，不是單純沒資料',
    excluded.curatedStyleExcluded === true,
    '「沒校對」跟「校對過但不適用」是兩件事，混在一起就沒辦法分開講。',
  );
  check(
    '「不適用」不算「不認識的風格名」',
    Array.isArray(excluded.curatedStyleUnknown) && excluded.curatedStyleUnknown.length === 0,
    `實際 ${JSON.stringify(excluded.curatedStyleUnknown)}。`
    + '「不適用」是預期會出現的值，把它當成未知會每次都在 console 喊一遍，'
    + '真正該被看到的警告就淹掉了。',
  );
}

// ⑥ 冒出沒見過的風格名時要留下痕跡，不可以靜靜丟掉
//
// 這是最容易出事的一條：哪天商品端加了第八個風格而沒通知前端，
// 若它跟「不適用」一樣被安靜丟掉，症狀會是「那個風格一件商品都推不出來」，
// 而沒有任何地方報錯。這個專案已經有三個長得很像的「第八種風格」
// （日常自然妝／自然裸妝／不適用），正好是會踩到的地方。
{
  const novel = Api._normalizeProduct({
    id: 3, sourceId: 3, type: 'lipsticks', name: '未來才會出現的商品',
    curatedStyleScores: { 港風妝: 5.1, 日常自然妝: 4.8 },
  });
  check(
    '認得的風格照樣解出來',
    novel.curatedStyleIds.includes('hongKong'),
    `實際 ${JSON.stringify(novel.curatedStyleIds)}。一個名字不認識不該連累其他的。`,
  );
  check(
    '不認識的風格名有被記下來',
    Array.isArray(novel.curatedStyleUnknown)
      && novel.curatedStyleUnknown.includes('日常自然妝'),
    `實際 ${JSON.stringify(novel.curatedStyleUnknown)}。`
    + '靜靜丟掉的後果是「那個風格一件商品都推不出來」，而且不會有人發現。',
  );
  check(
    '不認識的風格不算「校對過但不適用」',
    novel.curatedStyleExcluded === false,
    `實際 ${JSON.stringify(novel.curatedStyleExcluded)}。`
    + '兩者意思相反：一個是正常、一個是前端該補對映。混在一起就分不出要不要動手。',
  );
}

// ⑥ 原始分數不可以印在畫面上
//
// 分數是未正規化的原始值（實測 0.0 ~ 11.9）。印出來使用者會當成百分比看，
// 而「5.7」除了讓人誤會之外沒有任何用處。已要求商品端改成同類百分位。
{
  const router = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');
  const start = router.indexOf('function styleChips');
  if (start < 0) throw new Error('找不到 styleChips');
  const body = router.slice(start, router.indexOf('\n}', start));
  check(
    'styleChips 不印分數',
    !/\.score/.test(body),
    '分數是未正規化的原始值（0.0~11.9），印出來會被當成百分比。',
  );
  check(
    'styleChips 不自己重排',
    !/\.sort\(/.test(body),
    '名次由 api.js 排好。這裡再排一次，搜尋結果與反推頁遲早會給出不同順序。',
  );
  check(
    '搜尋結果有呼叫 styleChips',
    /styleChips\(p\)/.test(router),
    '帶下來卻沒顯示，等於白做——而且沒有人會發現，因為畫面不會報錯。',
  );
}

// ⑦ 中文名對映只能有一份
{
  const router = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
  check(
    'router.js 沒有自己再寫一份風格名對映',
    !/['"]港風妝['"]\s*:/.test(router),
    '第二份對映表就是第二個真相來源。這個流程已經因為「同一件事兩個地方各寫一套」吃過虧。',
  );
}

console.log(failed ? `\n${failed} 項未通過` : '\n妝容校對欄位測試通過');
process.exitCode = failed ? 1 : 0;
