// 商品頁不能等完整目錄翻完才第一次呈現。
//
// 正式站的商品 API 目前約 3,800 筆；不帶 limit 會一次回傳 8 MB 以上資料。
// 這支測試確認前端先取 100 筆並回呼畫面，後續游標頁完成後再回呼一次補齊目錄。
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
    Array, Object, Promise, Set, String, Number, Boolean, Math, RegExp,
    Router: {
      generalProductCatalog: null,
      generalProductLoading: false,
      generalProductError: false,
    },
    Api: {
      listProducts(params) {
        calls.push(params);
        if (calls.length === 1) {
          return Promise.resolve({
            ok: true,
            products: [{ id: 'first-page' }],
            total: 101,
            nextCursor: 'cursor-2',
          });
        }
        return secondPage;
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(
    'const PRODUCT_API_PAGE_SIZE = 100; const PRODUCT_MAX_PAGES = 50;\n' +
      `${cutBlock('function productCatalogLoaded()')}\n${cutBlock('function loadGeneralProductCatalog(')}\n` +
      'globalThis.__load = loadGeneralProductCatalog;',
    sandbox,
  );

  let callbacks = 0;
  sandbox.__load(() => { callbacks += 1; });
  await tick();
  await tick();

  if (calls.length !== 2) throw new Error(`第一頁後應立即開始背景第二頁，實際請求 ${calls.length} 次`);
  if (calls[0].limit !== 100) throw new Error(`第一頁應帶 limit=100，實際 ${JSON.stringify(calls[0])}`);
  if (callbacks !== 1) throw new Error(`第一頁完成應先回呼一次，實際 ${callbacks} 次`);
  if (sandbox.Router.generalProductCatalog?.length !== 1) {
    throw new Error('第一頁完成後應先提供目前商品清單');
  }
  if (sandbox.Router.generalProductLoading !== true) throw new Error('背景補齊期間仍應標示載入中');

  releaseSecond({ ok: true, products: [{ id: 'second-page' }], total: 101, nextCursor: null });
  await tick();
  await tick();

  if (callbacks !== 2) throw new Error(`完整目錄完成應再回呼一次，實際 ${callbacks} 次`);
  if (sandbox.Router.generalProductLoading !== false) throw new Error('完整目錄完成後仍標示載入中');
  if (sandbox.Router.generalProductCatalog?.length !== 2) throw new Error('完整目錄缺少背景補齊的商品');
  console.log('商品漸進式載入測試通過');
})().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
