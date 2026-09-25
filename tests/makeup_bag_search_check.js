// 化妝包的搜尋必須把關鍵字送給伺服器，不能抓一批回來自己篩。
//
// 2026-09-25：初版寫成 listProducts({ limit: 40 }) 再本機比對關鍵字。
// 那只搜尋了目錄最前面 40 筆——全站 3,897 筆的 1%。所以除非要找的東西剛好
// 排在最前面，否則永遠顯示「沒有符合的商品」，而且不會報錯，
// 看起來就像資料庫裡真的沒有那個商品。
//
// 伺服器支援 q（實測 q=唇膏 讓 total 從 3897 降到 930），而且可以跟
// recommendationState 疊加。注意 q 不會出現在回應的 appliedFilters 裡，
// 所以只看那個欄位會以為它不支援。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');

function matchBrace(text, from) {
  let depth = 0;
  const open = text.indexOf('{', from);
  for (let i = open; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}') { depth--; if (depth === 0) return i + 1; }
  }
  return -1;
}

function cutBlock(signature) {
  const start = src.indexOf(signature);
  if (start < 0) throw new Error(`找不到 ${signature}`);
  return src.slice(start, matchBrace(src, start));
}

const tick = () => new Promise(r => setTimeout(r, 0));

(async () => {
  const calls = [];
  const el = () => ({
    value: '', innerHTML: '', dataset: {}, textContent: '',
    onclick: null, oninput: null, onchange: null,
    querySelector: () => null, querySelectorAll: () => [],
  });
  const nodes = {
    mbArea: el(), mbSearch: el(), mbBrand: el(), mbResults: el(), mbCount: el(), mbImport: el(),
  };

  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    Array, Object, Promise, Set, Map, String, Number, Boolean, Math, JSON, RegExp,
    setTimeout: (fn) => { fn(); return 0; }, clearTimeout() {},
    document: { getElementById: (id) => nodes[id] || null },
    escapeHtml: (v) => String(v == null ? '' : v),
    phBox: () => '',
    showToast() {},
    CAT_EN: {},
    Router: { currentPage: 'makeupBag', generalProductCatalog: [], generalProductLoading: false },
    MakeupBagApi: { limit: 200 },
    MakeupBag: {
      localList: () => [], _asItems: () => [], has: () => false,
      list: () => Promise.resolve({ ok: true, items: [] }),
      add: () => Promise.resolve({ ok: true }),
    },
    Fav: { list: () => [] },
    Cart: { list: () => [] },
    productCatalogLoaded: () => true,
    loadGeneralProductCatalog() {},
    loadProductFacets: (cb) => cb && cb(),
    productFacetBrands: () => [],
    Api: {
      listProducts(params) { calls.push(params); return Promise.resolve({ ok: true, products: [] }); },
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(
    `const PageInit = {};\n${cutBlock('makeupBag() {').replace(/^makeupBag\(\)/, 'function makeupBag()')}\n` +
      'globalThis.__run = makeupBag;',
    sandbox,
  );

  sandbox.__run();
  await tick();

  // 觸發搜尋
  nodes.mbSearch.value = '唇膏';
  if (typeof nodes.mbSearch.oninput !== 'function') throw new Error('搜尋框沒有綁 oninput');
  nodes.mbSearch.oninput();
  await tick();
  await tick();

  const search = calls.find(c => c && Object.prototype.hasOwnProperty.call(c, 'q'));
  if (!search) {
    throw new Error(
      '搜尋沒有把關鍵字送給伺服器。\n' +
      '       實際送出的參數：' + JSON.stringify(calls) + '\n' +
      '       只抓一批回來本機篩，等於只搜尋了目錄最前面那幾筆——找不到時畫面\n' +
      '       會說「沒有符合的商品」，看起來像資料庫裡沒有，但其實只是沒搜到。',
    );
  }
  console.log('  PASS 關鍵字送給伺服器  q=' + JSON.stringify(search.q));

  // 搜尋**不可以**限定可推薦。
  //
  // 初版加了 recommendationState: '可推薦'，理由是「加了不能參與反推的東西是浪費」。
  // 那個理由錯了：化妝包記的是「我有什麼」，不是「系統推薦什麼」。使用者手上那支
  // 粉底剛好還沒校對完，不該因此查不到——他只會覺得這系統連他天天用的東西都沒有。
  // 實測 q=nc15 共 15 筆，其中 5 筆是「資料未達推薦條件」，而那 5 筆正是熱賣色號。
  if (search.recommendationState !== undefined) {
    throw new Error(
      [
        `搜尋不該限定 recommendationState，實際 ${JSON.stringify(search.recommendationState)}。`,
        '       化妝包是「我有什麼」，不是「系統推薦什麼」。未校對完的商品照樣要查得到，',
        '       只是在結果列標示「可以登記，但目前不參與妝容推薦」。',
      ].join('\n'),
    );
  }
  console.log('  PASS 搜尋涵蓋全部商品，不限可推薦');

  // 品牌篩選要跟關鍵字一起送，不是二選一
  nodes.mbBrand.value = 'MAC';
  nodes.mbBrand.onchange();
  await tick();
  await tick();
  const withBrand = calls[calls.length - 1];
  if (withBrand.brand !== 'MAC' || !withBrand.q) {
    throw new Error(`品牌與關鍵字要一起送，實際 ${JSON.stringify(withBrand)}`);
  }
  console.log('  PASS 品牌與關鍵字一起送');

  console.log('\n化妝包搜尋測試通過');
})().catch(error => {
  console.error('  FAIL ' + error.message);
  process.exitCode = 1;
});
