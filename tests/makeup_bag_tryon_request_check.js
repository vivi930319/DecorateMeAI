// 化妝包試妝的建議請求（2026-10-25 規格 v2）：前端只送 candidateKey。
//
// 品牌、名稱、色票由 Gateway 依登入身分讀化妝包、向演算法端查回後交給 Ollama。
// 瀏覽器若自己帶商品資料，等於讓可竄改的內容進到簽章過的渲染指令。
// 這支直接跑 api.js 裡真正的 suggestMakeup，攔下它送出的 body。
//
// 用法：node tests/makeup_bag_tryon_request_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');

// 方法的參數本身是解構（`({ faceAnalysis, ... })`），所以要從簽名結尾的 `) {` 開始數括號。
function cut(signature, bodyStart = '{') {
  const start = src.indexOf(signature);
  if (start < 0) throw new Error(`找不到 ${signature}`);
  let depth = 0;
  for (let i = src.indexOf(bodyStart, start) + bodyStart.length - 1; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (!depth) return src.slice(start, i + 1); }
  }
  throw new Error(`${signature} 括號不對稱`);
}

let pass = 0, fail = 0;
const check = (ok, msg) => { console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${msg}`); ok ? pass++ : fail++; };

function makeApi(reply) {
  const sent = [];
  let relisted = 0;
  const sandbox = {
    console, JSON, Array, Object, Error, Promise,
    MakeupBag: { list: () => { relisted++; return Promise.resolve({ items: [] }); } },
  };
  vm.createContext(sandbox);
  vm.runInContext(`${cut('const MAKEUP_BAG_TRYON_ERRORS = Object.freeze({')});
    globalThis.Api = {
      config: { url: () => '/text-suggestion/suggest' },
      _textSuggestionHeaders: () => ({}),
      _protectedFetch: (url, init) => globalThis.__fetch(url, init),
      ${cut('async suggestMakeup(', ') {')}
    };`, sandbox);
  sandbox.__fetch = (url, init) => {
    sent.push(JSON.parse(init.body));
    return Promise.resolve(reply);
  };
  return { Api: sandbox.Api, sent, relisted: () => relisted };
}

const ok = { ok: true, status: 200, json: () => Promise.resolve({ suggestion: 'x' }) };
const error = (status, code) => ({ ok: false, status, json: () => Promise.resolve({ error: { code, message: 'upstream text' } }) });

(async () => {
  {
    const { Api, sent } = makeApi(ok);
    await Api.suggestMakeup({ faceAnalysis: {}, style: '港風', userNote: '', selectedProducts: ['lipsticks:2734', 'eyeshadows:882'] });
    const body = sent[0];
    check(body.mode === 'makeup_bag', '有選商品 → mode 是 makeup_bag');
    check(JSON.stringify(body.selectedProducts) === '["lipsticks:2734","eyeshadows:882"]', '只送選的 candidateKey');
    check(!('ownedProducts' in body), '不送 ownedProducts（由 Gateway 組）');
  }
  {
    const { Api, sent } = makeApi(ok);
    await Api.suggestMakeup({ faceAnalysis: {}, style: '港風', userNote: '' });
    check(!('mode' in sent[0]) && !('selectedProducts' in sent[0]), '沒走化妝包路線 → 維持原本的請求');
  }
  const cases = [
    ['SELECTED_PRODUCT_NOT_IN_MAKEUP_BAG', 422, '此商品不在目前化妝包中，請重新選擇。'],
    ['SELECTED_PRODUCT_NOT_FOUND', 422, '商品已下架或暫時無法試妝。'],
    ['INVALID_TRYON_SELECTION', 422, '同一部位一次只能選一件商品。'],
    ['PRODUCT_DB_UNAVAILABLE', 502, '商品資料暫時無法讀取，請稍後再試。'],
  ];
  for (const [code, status, text] of cases) {
    const api = makeApi(error(status, code));
    const err = await api.Api.suggestMakeup({ faceAnalysis: {}, style: '港風', selectedProducts: ['lipsticks:1'] })
      .then(() => null, e => e);
    check(err && err.message === text && err.code === code, `${code} → 「${text}」`);
    if (code === 'SELECTED_PRODUCT_NOT_IN_MAKEUP_BAG') check(api.relisted() === 1, '不在化妝包 → 重新整理化妝包');
  }
  {
    const { Api } = makeApi(error(401, 'UNAUTHENTICATED'));
    const err = await Api.suggestMakeup({ faceAnalysis: {}, style: '港風', selectedProducts: ['lipsticks:1'] }).then(() => null, e => e);
    check(err && err.message.includes('重新登入'), '401 UNAUTHENTICATED → 請重新登入');
  }

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
