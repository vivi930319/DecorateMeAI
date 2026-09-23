// 選了品牌之後，商品清單要翻完該品牌的所有游標頁。
//
// 正式站 MAC 有 743 筆，Product API 一頁最多 100 筆。只請求一頁的話畫面會顯示
// 前 100 筆、少掉 600 多筆，而且**沒有任何錯誤訊息**——看起來就像資料庫裡只有這些。
//
// 第二件事比分頁本身更容易錯：游標只帶位移、不帶篩選條件。翻頁時如果只送
// { cursor, limit }（一般目錄 loadGeneralProductCatalog 就是這樣送的），後端會把它
// 當成無篩選查詢，從第二頁開始混進其他品牌的商品。所以每一頁都必須重送 brand。
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

function tick() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

(async () => {
  const calls = [];
  let releaseSecond;
  const secondPage = new Promise(resolve => { releaseSecond = resolve; });
  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    Array, Object, Promise, Set, String, Number, Boolean, Math, RegExp, setTimeout,
    Router: {
      shopBrand: 'MAC',
      shopBrandCatalog: null,
      shopBrandLoading: '',
      shopBrandError: false,
      // 品牌下拉選單就是靠這份清單畫出來的。
      productFacets: { brands: ['MAC', 'CHANEL', 'NARS'] },
    },
    Api: {
      listProducts(params) {
        calls.push(params);
        if (calls.length === 1) {
          return Promise.resolve({
            ok: true,
            products: [{ id: 'mac-1', rawId: 1 }],
            total: 743,
            nextCursor: 'cursor-2',
            // 篩選過的回應，facets 只描述被篩出來的那一小撮。
            facets: { brands: ['MAC'] },
          });
        }
        return secondPage;
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(
    'const PRODUCT_API_PAGE_SIZE = 100; const PRODUCT_MAX_PAGES = 50;\n' +
      `${cutBlock('function loadBrandProductCatalog(')}\n` +
      'globalThis.__load = loadBrandProductCatalog;',
    sandbox,
  );

  let callbacks = 0;
  sandbox.__load('MAC', () => { callbacks += 1; });
  await tick();
  await tick();

  if (calls.length !== 2) {
    throw new Error(`第一頁後應繼續請求下一頁，實際請求 ${calls.length} 次`);
  }
  if (calls[0].brand !== 'MAC' || calls[0].limit !== 100) {
    throw new Error(`第一頁應帶 brand 與 limit=100，實際 ${JSON.stringify(calls[0])}`);
  }
  if (calls[1].cursor !== 'cursor-2') {
    throw new Error(`第二頁應帶上一頁的 nextCursor，實際 ${JSON.stringify(calls[1])}`);
  }
  // 這一條是整支測試的重點：掉了 brand 就會從第二頁開始混進別的品牌。
  if (calls[1].brand !== 'MAC') {
    throw new Error(`翻頁時必須重送 brand，游標不帶篩選條件，實際 ${JSON.stringify(calls[1])}`);
  }
  if (callbacks !== 1) throw new Error(`第一頁完成應先回呼一次，實際 ${callbacks} 次`);
  if (sandbox.Router.shopBrandCatalog?.products?.length !== 1) {
    throw new Error('第一頁完成後應先提供目前的品牌清單');
  }
  if (sandbox.Router.shopBrandLoading !== 'MAC') throw new Error('背景補齊期間仍應標示載入中');
  // 品牌查詢的 facets 不能蓋掉全域品牌清單：蓋掉的話下拉選單只會剩「全部品牌」
  // 和剛選的那一個，使用者得先切回「全部品牌」才能挑別的。
  if (sandbox.Router.productFacets?.brands?.length !== 3) {
    throw new Error(
      `品牌查詢不能覆蓋全域品牌清單，實際剩 ${JSON.stringify(sandbox.Router.productFacets?.brands)}`,
    );
  }

  // 第二頁刻意把第一頁那筆再回一次，確認以 rawId 去重。
  releaseSecond({
    ok: true,
    products: [{ id: 'mac-1', rawId: 1 }, { id: 'mac-2', rawId: 2 }],
    total: 743,
    nextCursor: null,
  });
  await tick();
  await tick();

  if (callbacks !== 2) throw new Error(`完整品牌清單完成應再回呼一次，實際 ${callbacks} 次`);
  if (sandbox.Router.shopBrandLoading !== '') throw new Error('完整清單完成後仍標示載入中');
  if (sandbox.Router.shopBrandCatalog?.products?.length !== 2) {
    throw new Error(`重複的 rawId 應去重後合併，實際 ${sandbox.Router.shopBrandCatalog?.products?.length} 筆`);
  }
  if (sandbox.Router.shopBrandError !== false) throw new Error('兩頁都成功不該標示為錯誤');
  console.log('品牌清單分頁測試通過');
})().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
