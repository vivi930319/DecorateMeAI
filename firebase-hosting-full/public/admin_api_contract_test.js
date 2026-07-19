const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, 'js', 'api.js'), 'utf8');
const session = new Map([['memberAccessToken', 'short-lived-member-token']]);
const calls = [];
let responder = async () => ({ ok: true, status: 200, json: async () => ({}) });
const storage = (map = new Map()) => ({
  getItem: key => map.has(key) ? map.get(key) : null,
  setItem: (key, value) => map.set(key, String(value)),
  removeItem: key => map.delete(key)
});
const sandbox = {
  console,
  URL,
  URLSearchParams,
  Headers,
  window: { DECORATE_ME_CONFIG: { productUrl: 'http://product.test', crawlerUrl: 'http://crawler.test' } },
  fetch: async (input, init = {}) => { calls.push({ input, init }); return responder(input, init); },
  sessionStorage: storage(session),
  localStorage: storage(),
  location: { reload() {} },
  document: { createElement: () => ({ getContext: () => ({ drawImage() {} }), toBlob() {} }) },
  FormData: class { append() {} },
  Image: class {},
  FileReader: class {},
  File: class {}
};
vm.createContext(sandbox);
vm.runInContext(`${source}; this.Api = Api; this.Auth = Auth;`, sandbox);
sandbox.Auth.setProfile({ name: '管理員', email: 'admin@example.test', role: 'admin' });

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}
function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  responder = async () => response({ items: [{ id: 'lipsticks:933', type: 'lipsticks', name: '測試唇膏', price: 900, version: 3 }], total: 1, nextCursor: 'next' });
  const list = await sandbox.Api.listProducts({ type: 'lipsticks' });
  assert(list.ok && list.products.length === 1 && list.total === 1 && list.nextCursor === 'next', 'GET /api/products 新版 items 格式失敗');
  assert(String(calls.at(-1).input).includes('type=lipsticks'), '商品列表 query 未傳送');
  const normalizedEyeshadow = sandbox.Api._normalizeProduct({ id: 'eyeshadows:12', type: 'eyeshadows', category: 'çœ¼å½±', name: '測試眼影' });
  const normalizedLiner = sandbox.Api._normalizeProduct({ id: 'eyeliner_mascara:13', type: 'eyeliner_mascara', category: 'çœ¼ç·š/ç«æ¯›', name: '測試眼線' });
  assert(normalizedEyeshadow.cat === '眼影' && normalizedEyeshadow.apiType === 'eyeshadows', '眼影應優先依英文 type 分類');
  assert(normalizedLiner.cat === '眼線/睫毛' && normalizedLiner.apiType === 'eyeliner_mascara', '眼線／睫毛應優先依英文 type 分類');

  responder = async input => {
    const url = new URL(String(input));
    if (url.searchParams.get('cursor') === 'NTA') {
      return response({ items: [{ id: 'eyeshadows:2', type: 'eyeshadows', name: '第二頁' }], total: 2, nextCursor: null });
    }
    return response({ items: [{ id: 'lipsticks:1', type: 'lipsticks', name: '第一頁' }], total: 2, nextCursor: 'NTA' });
  };
  const allProducts = await sandbox.Api.listAllProducts();
  assert(allProducts.ok && allProducts.products.length === 2 && allProducts.pageCount === 2, '商品分頁未自動讀取完整清單');
  assert(calls.slice(-2).some(call => String(call.input).includes('cursor=NTA')), '商品分頁未傳送 nextCursor');

  responder = async () => response({ success: true, status: 'partial', data: { productName: '預覽商品', imageUrls: ['https://example.test/p.jpg'], missingFields: ['brand'], specs: { color: 'red' } } });
  const preview = await sandbox.Api.previewCrawledProduct('https://example.test/p');
  const previewBody = JSON.parse(calls.at(-1).init.body);
  assert(preview.ok && preview.status === 'partial' && preview.product.name === '預覽商品' && preview.product.missingFields[0] === 'brand', '爬蟲 response.data/partial 映射失敗');
  assert(previewBody.source === 'manual_admin_import', '爬蟲 source 未傳送');
  assert(previewBody.adminId === 'admin@example.test', '爬蟲 adminId 未取用目前登入 email');
  assert(calls.at(-1).init.headers.get('Authorization') === 'Bearer short-lived-member-token', 'auth provider 未附加短期 Bearer token');

  responder = async () => response({ product: { id: 'lipsticks:933', version: 4 } });
  const patched = await sandbox.Api.patchRemoteProduct('lipsticks:933', { price: 990, version: 3 });
  assert(patched.ok, 'PATCH 成功回應處理失敗');
  assert(calls.at(-1).init.headers.get('If-Match') === '3', 'PATCH 缺少 If-Match');
  assert(!Object.prototype.hasOwnProperty.call(JSON.parse(calls.at(-1).init.body), 'version'), 'version 不應出現在 PATCH body');

  responder = async () => response({ detail: { error: { code: 'VERSION_CONFLICT', message: 'Product version conflict', details: { currentVersion: 4 } } } }, 409);
  const conflict = await sandbox.Api.patchRemoteProduct('lipsticks:933', { price: 1000, version: 3 });
  assert(!conflict.ok && conflict.code === 'VERSION_CONFLICT' && conflict.details.currentVersion === 4, 'VERSION_CONFLICT 解析失敗');

  responder = async () => response({ product: { id: 'lipsticks:933', type: 'lipsticks', name: '最新商品', version: 4 } });
  const detail = await sandbox.Api.getRemoteProduct('lipsticks:933');
  assert(detail.ok && detail.product.version === 4, 'GET /api/products/{type:id} 映射失敗');
  assert(String(calls.at(-1).input).endsWith('/admin-api/products/lipsticks%3A933'), '商品 id 未正確 URL encode');

  responder = async () => response({ items: [{ action: 'update', productId: 'lipsticks:933' }] });
  const audit = await sandbox.Api.listProductAuditLogs();
  assert(audit.ok && audit.logs.length === 1, 'Audit Log 映射失敗');
  assert(String(calls.at(-1).input).includes('/admin-api/product-audit-logs?limit=100'), 'Audit Log 路徑錯誤');

  sandbox.Api.config.services.memberDatabase.baseUrl = 'http://member.test';
  responder = async () => response({ ok: true, member: { email: 'user+demo@example.test' } });
  const deleted = await sandbox.Api.deleteMember('user+demo@example.test');
  assert(deleted.ok, 'DELETE /api/members/{email} 成功回應處理失敗');
  assert(String(calls.at(-1).input).endsWith('/api/members/user%2Bdemo%40example.test'), '會員 email 未正確 URL encode');
  assert(calls.at(-1).init.method === 'DELETE', '會員刪除未使用 DELETE');
  assert(calls.at(-1).init.headers.Authorization === 'Bearer short-lived-member-token', '會員刪除缺少 Bearer token');
  assert(calls.at(-1).init.credentials === 'include', '會員刪除缺少 session cookie 設定');

  responder = async () => response({ detail: { error: { code: 'ADMIN_REQUIRED', message: '只有管理員可以刪除會員' } } }, 403);
  const deniedDelete = await sandbox.Api.deleteMember('user@example.test');
  assert(!deniedDelete.ok && deniedDelete.status === 403 && deniedDelete.code === 'ADMIN_REQUIRED', '會員刪除錯誤格式解析失敗');
  assert(deniedDelete.error === '只有管理員可以刪除會員', '會員刪除未顯示後端錯誤訊息');

  console.log('admin API contract tests passed');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
