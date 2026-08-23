const fs = require('fs');
const path = require('path');
const vm = require('vm');

const rootDir = __dirname;
const apiSource = fs.readFileSync(path.join(rootDir, 'js', 'api.js'), 'utf8');
const routerSource = fs.readFileSync(path.join(rootDir, 'js', 'router.js'), 'utf8');
const makeupContractSource = fs.readFileSync(path.join(rootDir, 'js', 'makeup-contract.js'), 'utf8');
const makeupFlowSource = fs.readFileSync(path.join(rootDir, 'js', 'makeup-flow.js'), 'utf8');
const storage = new Map();
const session = new Map();
const browserLocation = { origin: 'https://decorate-me.web.app', reload() {} };

function makeStorage(map) {
  return {
    setItem(key, value) { map.set(key, String(value)); },
    getItem(key) { return map.has(key) ? map.get(key) : null; },
    removeItem(key) { map.delete(key); }
  };
}

const sandbox = {
  console,
  window: {
    DECORATE_ME_CONFIG: {
      aiGatewayUrl: ''
    },
    location: browserLocation
  },
  location: browserLocation,
  URL,
  FormData: class FormData {
    append() {}
  },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  document: {
    createElement: () => ({
      getContext: () => ({ drawImage() {} }),
      toBlob: () => {}
    })
  },
  Image: class Image {},
  FileReader: class FileReader {},
  File: class File {},
  localStorage: makeStorage(storage),
  sessionStorage: makeStorage(session)
};

vm.createContext(sandbox);
vm.runInContext(`${apiSource}; this.ApiConfig = ApiConfig; this.Api = Api; this.ImagePipeline = ImagePipeline; this.AnalysisPackage = AnalysisPackage; this.Auth = Auth; this.AdminStore = AdminStore; this.Cart = Cart; this.History = History; this.localizeUserError = localizeUserError;`, sandbox);

// ── 使用者錯誤訊息中文化 ────────────────────────────────────
if (sandbox.localizeUserError('Member authentication is unavailable.', 'MEMBER_SERVICE_UNAVAILABLE', 503) !== '會員服務目前無法連線，請稍後再試。') {
  throw new Error('Member authentication errors must be localized to Chinese');
}
if (sandbox.localizeUserError('Unexpected internal provider detail') !== '系統目前無法完成這項操作，請稍後再試。') {
  throw new Error('Unknown English backend errors must not be shown to users');
}
// ── 被限流時要講「還要等多久」──────────────────────────────
// 只說「請稍後再試」的話，使用者不知道要等多久就會一直重試，而每一次重試都把
// 限流視窗往後推。後端一律回 retryAfterSeconds，前端必須把它講出來。
{
  const rateLimited = sandbox.localizeUserError(
    '登入嘗試次數過多，請在 300 秒後再試。', 'LOGIN_RATE_LIMITED', 429, { retryAfterSeconds: 300 }
  );
  if (!rateLimited.includes('5 分鐘')) {
    throw new Error(`Rate limited message must tell the user how long to wait, got: ${rateLimited}`);
  }
  const noHint = sandbox.localizeUserError('Too many requests', 'RATE_LIMITED', 429);
  if (!noHint.includes('請稍後再試')) {
    throw new Error('Rate limited message without a retry hint must still be understandable');
  }
  if (sandbox.formatRetryWait(45) !== '45 秒' || sandbox.formatRetryWait(3600) !== '1 小時') {
    throw new Error('formatRetryWait must round seconds into human units');
  }
}

// ── base64 頭像不落地 ────────────────────────────────────────
// sessionStorage 不會因重新整理而清空，一張 base64 臉留在裡面等於把上一個人的臉
// 交給下一個登入者；而且它會反覆撐大每一次 profile 寫入。
{
  const dataAvatar = 'data:image/png;base64,AAAABBBBCCCC';
  sandbox.Auth.setProfile({ name: '頭像測試', email: 'avatar@example.com', avatar: dataAvatar });
  const storedProfile = session.get('beautyProfile') || '';
  if (storedProfile.includes('base64') || storedProfile.includes('data:image')) {
    throw new Error('base64 avatar must never be written to sessionStorage');
  }
  const storedMembers = storage.get('beautyRegisteredMembers') || '';
  if (storedMembers.includes('data:image')) {
    throw new Error('base64 avatar must never be written to localStorage');
  }
  // 本次 session 內仍看得到（記憶體暫存），SPA 導覽不會讓頭像消失。
  if (sandbox.Auth.getProfile().avatar !== dataAvatar) {
    throw new Error('data-URL avatar should survive in memory for the session');
  }
  // 換成正式網址後，暫存的 base64 要被清掉、網址正常持久化。
  sandbox.Auth.setProfile({ name: '頭像測試', email: 'avatar@example.com', avatar: 'https://cdn.example.com/a.png' });
  if (sandbox.Auth.getProfile().avatar !== 'https://cdn.example.com/a.png') {
    throw new Error('A real avatar URL should be persisted as-is');
  }
}

// ── 會員姓名與購物車 ─────────────────────────────────────────
sandbox.Auth.setProfile({ name: '測試會員', email: 'USER@example.com', level: '一般會員' });
if (sandbox.Auth.getRegisteredMember('user@example.com')?.name !== '測試會員') {
  throw new Error('Registered member name was not stored by normalized email');
}
if (!sandbox.AdminStore.canAccess('analysis', sandbox.Auth.getProfile())) {
  throw new Error('Default member should be allowed to access analysis');
}
sandbox.AdminStore.setPermission('user@example.com', { allowedPages: ['dashboard', 'profile'] });
if (sandbox.AdminStore.canAccess('analysis', sandbox.Auth.getProfile())) {
  throw new Error('Permission override should block analysis');
}
if (!sandbox.AdminStore.isAdminProfile({ email: 'admin@example.com', role: 'admin' })) {
  throw new Error('Admin profile should trust backend role');
}
if (sandbox.AdminStore.isAdminProfile({ email: 'admin@decorateme.local' })) {
  throw new Error('Admin profile should not trust email naming fallback');
}

// 管理後台只採信後端驗證過的角色。
{
  // 本機 profile 自稱 admin，但沒有任何後端驗過的 session → 一律不是 admin。
  sandbox.Api._clearPinnedSession();
  sandbox.Auth.setProfile({ name: '假管理員', email: 'fake@evil.test', role: 'admin', level: '管理員' });
  if (sandbox.AdminStore.isAdmin()) {
    throw new Error('A self-declared admin profile with no verified session must NOT be admin');
  }
  // pin 一個後端驗過是 member 的 session：即使本機還寫著 admin，也不是 admin。
  sandbox.Api._pinSession({ actorId: 'actor_x', sub: 'fake@evil.test', role: 'member' });
  if (sandbox.AdminStore.isAdmin()) {
    throw new Error('A verified member must NOT be admin even if the local profile claims admin');
  }
  // pin 一個後端驗過是 admin 的 session → 才是 admin。
  sandbox.Api._pinSession({ actorId: 'actor_a', sub: 'admin@example.com', role: 'admin' });
  if (!sandbox.AdminStore.isAdmin()) {
    throw new Error('A backend-verified admin session must be treated as admin');
  }
  sandbox.Api._clearPinnedSession();
  // 清掉 pin 後，回到「非 admin」。
  if (sandbox.AdminStore.isAdmin()) {
    throw new Error('Clearing the session must drop admin');
  }
  sandbox.Auth.setProfile({ name: '測試會員', email: 'USER@example.com', level: '一般會員' });
}
sandbox.Cart.add(1);
sandbox.Cart.add(1);
if (sandbox.Cart.count() !== 2 || sandbox.Cart.list()[0].qty !== 2) throw new Error('Cart quantity accumulation failed');
sandbox.Cart.change(1, -2);
if (sandbox.Cart.count() !== 0 || sandbox.Cart.list().length !== 0) throw new Error('Cart item removal failed');

// ── 服務設定 ────────────────────────────────────────────────
// 爬蟲只寫入暫存表，前端不再需要 crawlerUrl。
const requiredServices = ['faceBasic', 'facePro', 'textSuggestion', 'render', 'product', 'memberDatabase'];
for (const service of requiredServices) {
  if (!sandbox.ApiConfig.services[service]) throw new Error(`Missing service: ${service}`);
}

const basicUrl = sandbox.ApiConfig.url('faceBasic', 'analyzePath');
const proUrl = sandbox.ApiConfig.url('facePro', 'analyzePath');
const suggestionUrl = sandbox.ApiConfig.url('textSuggestion', 'suggestPath');
if (!basicUrl.endsWith('/v1/face/analyze/basic')) throw new Error(`Bad BASIC URL: ${basicUrl}`);
if (!proUrl.endsWith('/v1/face/analyze/pro')) throw new Error(`Bad PRO URL: ${proUrl}`);
if (suggestionUrl !== '/text-suggestion/suggest') throw new Error(`Bad suggestion URL: ${suggestionUrl}`);
if (sandbox.ApiConfig.services.memberDatabase.baseUrl !== '/member-database') throw new Error('Member API must use same-origin Gateway');
if (sandbox.ApiConfig.services.product.baseUrl !== '/product-api') throw new Error('Product API must use same-origin Gateway');
// 後台爬蟲審核功能直接使用 /admin-api。
if (sandbox.ApiConfig.services.crawler) throw new Error('services.crawler 應已移除');
if (sandbox.ApiConfig.services.aiGateway.sessionPath !== '/auth/session') throw new Error('Gateway session validation path missing');

// ── 商品分類不可全部掉回底妝 ─────────────────────────────────
// 正式商品 API 同時回英文 type 與中文 category。管理中台的類型下拉必須依
// 英文 slug 篩選，而表格與前台則顯示中文分類。
{
  const lipstick = sandbox.Api._normalizeProduct({ id: 7, type: 'lipsticks', category: '唇彩', name: '測試唇膏' });
  if (lipstick.apiType !== 'lipsticks' || lipstick.cat !== '唇彩' || lipstick.id !== 'api-lipsticks-7') {
    throw new Error(`Lipstick category normalization failed: ${JSON.stringify(lipstick)}`);
  }
  const chineseOnly = sandbox.Api._normalizeProduct({ id: 8, category: '腮紅', name: '測試腮紅' });
  if (chineseOnly.apiType !== 'blushes' || chineseOnly.cat !== '腮紅') {
    throw new Error(`Chinese category normalization failed: ${JSON.stringify(chineseOnly)}`);
  }
  const unknown = sandbox.Api._normalizeProduct({ id: 9, category: '未分類', name: '未知分類' });
  if (unknown.apiType !== null) {
    throw new Error('Unknown products must not receive a fake foundations apiType');
  }
  for (const invariant of [
    "loaded.filter(p => p.apiType === typeFilter || p.cat === TYPE_TO_CAT[typeFilter])",
    "el.onchange = loadAdminProducts",
    "for (let page = 0; page < PRODUCT_MAX_PAGES; page++)"
  ]) {
    if (!routerSource.includes(invariant)) throw new Error(`Admin category filter invariant missing: ${invariant}`);
  }
}

// ── 首頁品牌素材 ─────────────────────────────────────────────
const indexSource = fs.readFileSync(path.join(rootDir, 'index.html'), 'utf8');
const dashboardSource = fs.readFileSync(path.join(rootDir, 'pages', 'dashboard.html'), 'utf8');
for (const assetPath of [
  'assets/brand/decorate-me-round-source.jpg',
  'assets/brand/decorate-me-home.jpg'
]) {
  if (!fs.existsSync(path.join(rootDir, assetPath))) throw new Error(`Missing brand asset: ${assetPath}`);
}
if (!indexSource.includes('decorate-me-round-source.jpg') || !dashboardSource.includes('decorate-me-home.jpg')) {
  throw new Error('Homepage brand assets are not wired into the rendered templates');
}

// ── 正式妝容流程與 Ollama 回傳契約 ──────────────────────────
// 正式站只載入真實 API 流程，不得把 Demo 的 OTP／假回傳帶上線。
for (const asset of ['css/makeup-flow.css', 'js/makeup-contract.js', 'js/makeup-flow.js']) {
  if (!indexSource.includes(asset)) throw new Error(`Production makeup flow asset missing from index.html: ${asset}`);
}
for (const forbidden of ['js/demo-mode.js', 'js/demo-flow.js']) {
  if (indexSource.includes(forbidden)) throw new Error(`Production index must not load ${forbidden}`);
}
if (makeupFlowSource.includes('DecorateDemo') || makeupFlowSource.includes('demo.suggestion')) {
  throw new Error('Production makeup flow must not depend on Demo suggestion data');
}
if (makeupFlowSource.includes("'assets/before.png'") || makeupFlowSource.includes("'assets/after.png'")) {
  throw new Error('Production makeup flow must not fall back to Demo portrait assets');
}
if (routerSource.includes('查看送給圖像模型的英文指令') || routerSource.includes('這次實際下給模型的指令')) {
  throw new Error('English render prompts must not be exposed in the user-facing frontend');
}

const contractSandbox = { window: {} };
vm.createContext(contractSandbox);
vm.runInContext(`${makeupContractSource}; this.Contract = window.MakeupSuggestionContract;`, contractSandbox);
const contract = contractSandbox.Contract;
if (!contract || typeof contract.normalize !== 'function') throw new Error('MakeupSuggestionContract.normalize is missing');

{
  const structured = contract.normalize({
    structured: {
      overall: { summary: '結構化整體建議', palette: ['#112233', '#AABBCC'] },
      parts: {
        base: { label: '底妝', analysis: '底妝分析', steps: ['底妝步驟'], avoid: ['底妝避免'] },
        eyebrow: { label: '眉型', analysis: '眉型分析', steps: ['眉型步驟'], avoid: ['眉型避免'] },
        eyes: { label: '眼妝', analysis: '眼妝分析', steps: ['眼妝步驟'], avoid: ['眼妝避免'] },
        contour: { label: '腮紅修容', analysis: '修容分析', steps: ['修容步驟'], avoid: ['修容避免'] },
        lips: { label: '唇妝', analysis: '唇妝分析', steps: ['唇妝步驟'], avoid: ['唇妝避免'] }
      }
    }
  }, { palette: [] });
  if (structured.source !== 'structured' || structured.parts.brow.steps[0] !== '眉型步驟') {
    throw new Error('Structured Ollama response must map eyebrow → brow without changing content');
  }
}

{
  const legacyText = [
    '1. 整體妝容方向',
    '保留乾淨膚感，腮紅斜掃顴骨並輕修輪廓。',
    '2. 底妝建議',
    '薄擦半霧面底妝，鼻翼局部遮瑕。',
    '3. 眉眼妝建議',
    '眉色使用灰棕色並順著毛流填補。眼尾眼線微微上揚二至三毫米。',
    '4. 唇妝建議',
    '使用低飽和玫瑰色唇彩。',
    '5. 避免事項',
    '避免眉色過黑。避免粗黑下眼線。',
    '6. 總結與建議',
    '整體維持低飽和與乾淨線條。'
  ].join('\n');
  const legacy = contract.normalize({ suggestion: legacyText }, { palette: ['#D8B69E'] });
  if (legacy.source !== 'legacy') throw new Error('Legacy Ollama response must use compatibility mapping');
  if (!legacy.parts.base.steps.some(step => step.includes('半霧面底妝'))) throw new Error('Legacy base advice must come from the returned base section');
  if (!legacy.parts.brow.steps.some(step => step.includes('灰棕色'))) throw new Error('Legacy brow advice must come from returned brow sentences');
  if (!legacy.parts.eyes.steps.some(step => step.includes('眼線'))) throw new Error('Legacy eye advice must come from returned eye sentences');
  if (!legacy.parts.contour.steps.some(step => step.includes('腮紅'))) throw new Error('Legacy contour advice must come from returned contour-related sentences');
  if (!legacy.parts.lips.steps.some(step => step.includes('玫瑰色'))) throw new Error('Legacy lip advice must come from the returned lip section');
}

{
  let rejected = false;
  try { contract.normalize({ suggestion: '' }, { palette: [] }); } catch (error) { rejected = error.code === 'INVALID_SUGGESTION_CONTRACT'; }
  if (!rejected) throw new Error('Missing Ollama content must be rejected instead of replaced with fake advice');
}

// ── 管理中台與會員端外框必須完全分離 ─────────────────────────
// 只有管理員進入 admin 頁面時才隱藏會員介面。
const cssSource = fs.readFileSync(path.join(rootDir, 'css', 'main.css'), 'utf8');
for (const invariant of [
  "const adminMode = admin && activePage === 'admin'",
  'updateAdminNav(page);',
  // showApp() 會還原重新載入前的頁面，所以切外框的參數是 target（管理員時等於 landing）。
  'updateAdminNav(target);'
]) {
  if (!routerSource.includes(invariant)) throw new Error(`Admin/member shell separation missing: ${invariant}`);
}
for (const selector of [
  'body.admin-mode .topbar',
  'body.admin-mode .brand-watermark',
  'body.admin-mode .watermark-stamp'
]) {
  if (!cssSource.includes(selector)) throw new Error(`Admin mode must hide member UI: ${selector}`);
}

// ── 收藏頁每次打開都要重新向會員資料庫同步 ──────────────────
// 收藏頁必須重新同步資料，並區分空清單與同步失敗。
for (const invariant of [
  "if (page === 'favorites') refreshFavoritesPage();",
  "Router.favoriteSyncState = 'loading'",
  "Router.favoriteSyncState = result && result.ok ? 'ready' : 'error'",
  '雲端收藏暫時無法同步'
]) {
  if (!routerSource.includes(invariant)) throw new Error(`Favorites refresh invariant missing: ${invariant}`);
}

// ── Firebase 根頁不可快取舊 index.html ────────────────────────
// 根網址與 index.html 都要停用快取，避免部署後仍顯示舊版外框。
const firebaseConfig = JSON.parse(fs.readFileSync(path.join(rootDir, 'firebase.json'), 'utf8'));
if (!(firebaseConfig?.hosting?.ignore || []).includes('demo_makeup_flow/**')) {
  throw new Error('Firebase Hosting must exclude the local Demo with its mock authentication');
}
if (!(firebaseConfig?.hosting?.ignore || []).includes('config.local.js')) {
  throw new Error('Firebase Hosting must exclude the local-only config.local.js');
}
const hostingHeaders = firebaseConfig?.hosting?.headers || [];
for (const source of ['/', '/index.html']) {
  const rule = hostingHeaders.find(item => item.source === source);
  const cacheValue = rule?.headers?.find(header => String(header.key).toLowerCase() === 'cache-control')?.value || '';
  if (!cacheValue.includes('no-cache') || !cacheValue.includes('no-store')) {
    throw new Error(`Firebase ${source} must not cache an old index.html`);
  }
}

// ── Api 方法 ─────────────────────────────────────────────────
for (const method of ['createFaceJob', 'createFaceProJob', 'getFaceJob', 'getFaceJobResult', 'waitForFaceJob', 'suggestMakeup', 'validateSession',
  // 暫存商品審核（爬蟲改流程後取代 previewCrawledProduct）
  'listStagingProducts', 'reviewStagingProduct', 'importStagingProduct']) {
  if (typeof sandbox.Api[method] !== 'function') throw new Error(`Missing Api.${method}`);
}
if (!routerSource.includes('const session = await Api.validateSession()')) throw new Error('Private pages must validate Gateway session before showApp');
if (!apiSource.includes('this._cancelSessionRequests();')) throw new Error('Expired sessions must cancel protected request batch');

// ── XSS 與外部 URL scheme 防線（item 7）──────────────────────────
// 會員與爬蟲資料進入 HTML 前必須轉義，外部網址也要驗證協定。
if (!routerSource.includes('escapeHtml(msg)')) throw new Error('showToast must escape its message (XSS)');
if (!routerSource.includes('<span class="accent">${escapeHtml(user)}</span>')) throw new Error('Dashboard greeting must escape the member name (XSS)');
if (!routerSource.includes('function safeExternalUrl(')) throw new Error('External links must be scheme-validated via safeExternalUrl');
if (/href="\$\{escapeHtml\(product\.sourceUrl\)\}"/.test(routerSource)) throw new Error('Crawler source URL must be scheme-validated, not merely HTML-escaped');
if (routerSource.includes("__av.innerHTML = '<img src=\"' + __p.avatar")) throw new Error('Avatar image URL must be validated via lookImageSrc, not inserted raw');

// ── protected write actor 防線 ────────────────────────────────
// 所有寫入都由 _protectedWrite 驗證目前分頁身分。
let checkProtectedWriteActor;
{
  // assertSessionOwner 只能由統一寫入入口呼叫。
  const ownerCalls = apiSource.match(/this\.assertSessionOwner\(/g) || [];
  if (ownerCalls.length !== 1) {
    throw new Error(`Write guard must funnel through _protectedWrite; found ${ownerCalls.length} direct assertSessionOwner call sites`);
  }
  for (const method of ['_protectedWrite', '_writeActorEmail', 'assertSessionOwner']) {
    if (typeof sandbox.Api[method] !== 'function') throw new Error(`Missing Api.${method}`);
  }

  const events = [];
  sandbox.window.dispatchEvent = (event) => { events.push(event); return true; };
  sandbox.CustomEvent = class CustomEvent {
    constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
  };

  let fetchCalls = [];
  sandbox.fetch = async (url, init) => {
    fetchCalls.push({ url: String(url), method: (init || {}).method || 'GET', headers: { ...((init || {}).headers || {}) } });
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  };

  const realValidateSession = sandbox.Api.validateSession;
  const stubSession = (session) => { sandbox.Api.validateSession = async () => session; };

  sandbox.Auth.setProfile({ name: '測試會員', email: 'owner@example.com', level: '一般會員' });
  sandbox.Api._pinSession({ sub: 'owner@example.com', actorId: 'actor_owner_tab' });

  const run = async () => {
    // 1) session 屬於其他帳號時，必須在送出前阻擋。
    stubSession({ ok: true, sub: 'someone-else@example.com', actorId: 'actor_other_tab', role: 'member' });
    fetchCalls = [];
    const blocked = await sandbox.Api.checkInMember('owner@example.com');
    if (blocked.ok !== false || blocked.blocked !== true) {
      throw new Error(`Mismatched session must block member writes: ${JSON.stringify(blocked)}`);
    }
    if (blocked.reason !== 'OWNER_MISMATCH') throw new Error(`Blocked write must report OWNER_MISMATCH, got ${blocked.reason}`);
    if (!/登入身分已切換/.test(blocked.error || '')) {
      throw new Error(`Blocked write must carry a displayable Chinese reason, got: ${blocked.error}`);
    }
    if (fetchCalls.length !== 0) {
      throw new Error(`Blocked write must not reach the network, but sent: ${JSON.stringify(fetchCalls)}`);
    }
    if (!events.some(e => e.type === 'decorate-me:session-owner-changed')) {
      throw new Error('Owner mismatch must notify the Router');
    }

    // 2) 後台寫入者是目前登入的管理員，不是被操作的會員。
    fetchCalls = [];
    const blockedPatch = await sandbox.Api.patchMember('victim@example.com', { status: 'suspended' });
    if (blockedPatch.ok !== false || blockedPatch.blocked !== true) {
      throw new Error(`Admin patchMember must be guarded by the write actor line: ${JSON.stringify(blockedPatch)}`);
    }
    const blockedDelete = await sandbox.Api.deleteMember('victim@example.com');
    if (blockedDelete.ok !== false || blockedDelete.blocked !== true) {
      throw new Error(`Admin deleteMember must be guarded by the write actor line: ${JSON.stringify(blockedDelete)}`);
    }
    if (fetchCalls.length !== 0) {
      throw new Error(`Blocked admin writes must not reach the network, but sent: ${JSON.stringify(fetchCalls)}`);
    }

    // 3) 無法確認 session（Gateway 連不上）時同樣不放行——寧可失敗，也不要寫錯帳號
    stubSession({ ok: false, status: 0 });
    fetchCalls = [];
    const unavailable = await sandbox.Api.deleteSavedLook('owner@example.com', 7);
    if (unavailable.ok !== false || unavailable.reason !== 'SESSION_UNAVAILABLE') {
      throw new Error(`Unverifiable session must block writes: ${JSON.stringify(unavailable)}`);
    }
    if (fetchCalls.length !== 0) throw new Error('Unverifiable session must not reach the network');

    // 4) 身分相符（含大小寫差異）就正常放行，請求要真的送出去
    stubSession({ ok: true, sub: 'Owner@Example.com', actorId: 'actor_owner_tab', role: 'member' });
    fetchCalls = [];
    const allowed = await sandbox.Api.checkInMember('owner@example.com');
    if (allowed.ok !== true) throw new Error(`Matching session must allow the write: ${JSON.stringify(allowed)}`);
    if (fetchCalls.length !== 1 || fetchCalls[0].method !== 'POST') {
      throw new Error(`Allowed write must issue exactly one POST, got: ${JSON.stringify(fetchCalls)}`);
    }
    if (!fetchCalls[0].url.endsWith('/api/members/owner%40example.com/check-in')) {
      throw new Error(`Allowed write hit the wrong URL: ${fetchCalls[0].url}`);
    }
    if (fetchCalls[0].headers['X-Expected-Actor'] !== 'actor_owner_tab') {
      throw new Error(`Allowed write must carry the pinned opaque actor: ${JSON.stringify(fetchCalls[0])}`);
    }

    // 5) 缺 sub／actorId 或本分頁沒有綁定 actor 時一律 fail closed。
    stubSession({ ok: true, sub: 'owner@example.com', actorId: '' });
    fetchCalls = [];
    const missingActor = await sandbox.Api.checkInMember('owner@example.com');
    if (missingActor.ok !== false || missingActor.reason !== 'SESSION_UNAVAILABLE' || fetchCalls.length !== 0) {
      throw new Error(`Missing actor evidence must block writes: ${JSON.stringify(missingActor)}`);
    }

    // 6) opaque actor 絕不能被附到第三方網址。
    fetchCalls = [];
    await sandbox.Api._protectedFetch('https://example.com/collect', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    if (fetchCalls.length !== 1 || fetchCalls[0].headers['X-Expected-Actor']) {
      throw new Error(`Third-party requests must not receive X-Expected-Actor: ${JSON.stringify(fetchCalls)}`);
    }

    // 7) Gateway 自己的 409（帳號已不在這個瀏覽器上）要立即通知 Router，
    //    不能等下一個操作才發現換帳號。
    sandbox.Api._sessionExpiredNotified = false;
    events.length = 0;
    const ownerChange409 = { error: { code: 'ACCOUNT_NOT_AVAILABLE' } };
    sandbox.fetch = async () => ({
      ok: false, status: 409,
      json: async () => ownerChange409,
      clone: () => ({ json: async () => ownerChange409 })
    });
    await sandbox.Api._protectedFetch('/member-database/api/favorites/toggle', { method: 'POST' });
    if (!events.some(e => e.type === 'decorate-me:session-owner-changed')) {
      throw new Error('Gateway 409 must notify the Router of a changed session owner');
    }

    // 8) 上游的業務衝突也是 409（獎勵已領過、信箱已註冊），而且會被原樣透傳。
    //    那種 409 不可以把人登出——狀態是正常的，只是這次操作不成立。
    sandbox.Api._sessionExpiredNotified = false;
    events.length = 0;
    const business409 = { error: { code: 'ALREADY_CLAIMED' } };
    sandbox.fetch = async () => ({
      ok: false, status: 409,
      json: async () => business409,
      clone: () => ({ json: async () => business409 })
    });
    await sandbox.Api._protectedFetch('/member-database/api/members/a%40b.c/tasks/daily_checkin/claim', { method: 'POST' });
    if (events.some(e => e.type === 'decorate-me:session-owner-changed')) {
      throw new Error('A business 409 must not log the member out');
    }
  };

  checkProtectedWriteActor = async () => {
    try {
      await run();
    } finally {
      // 後面的檢查共用同一個 sandbox，收尾時把動過的東西還原
      sandbox.Api.validateSession = realValidateSession;
      sandbox.fetch = async () => ({ ok: true, json: async () => ({}) });
      sandbox.Auth.setProfile({ name: '測試會員', email: 'USER@example.com', level: '一般會員' });
    }
  };
}

// ── ImagePipeline ─────────────────────────────────────────────
for (const method of ['compressForPackage', 'compressInWorker', 'compressOnMainThread', 'canUseWorker']) {
  if (typeof sandbox.ImagePipeline[method] !== 'function') throw new Error(`Missing ImagePipeline.${method}`);
}
if (sandbox.ImagePipeline.workerPath !== 'js/image-worker.js') {
  throw new Error(`Bad image worker path: ${sandbox.ImagePipeline.workerPath}`);
}

// ── 本機設定安全預設 ─────────────────────────────────────────
const configExample = fs.readFileSync(path.join(rootDir, 'config.local.example.js'), 'utf8');

// OTP 不得有任何前端繞過路徑或長度判斷捷徑。
if (/DECORATE_ME_CONFIG\?\.allowInsecureOtpBypass|allowOtpBypass/.test(routerSource)) {
  throw new Error('router.js must not read an OTP bypass flag');
}
if (/catch[\s\S]{0,400}?code\.length\s*[<>]=?\s*\d[\s\S]{0,200}?return true/.test(routerSource)) {
  throw new Error('OTP verification must not fall back to a length check');
}
for (const forbidden of ['faceApiKey', 'renderApiKey', 'textSuggestionApiKey', 'trycloudflare.com']) {
  if (configExample.includes(forbidden)) throw new Error(`config.local.example.js must not contain ${forbidden}`);
}
if (apiSource.includes("sessionStorage.setItem(this._gatewayTokenKey")) throw new Error('Gateway token must not be stored in sessionStorage');
if (apiSource.includes("sessionStorage.setItem(this._memberTokenKey")) throw new Error('Member token must not be stored in sessionStorage');
const gitignore = fs.readFileSync(path.join(rootDir, '.gitignore'), 'utf8');
if (!gitignore.includes('config.local.js')) {
  throw new Error('.gitignore must exclude config.local.js');
}

// ── 登出清當前帳號的 localStorage PII，不動其他帳號（item 5）─────────────
{
  if (typeof sandbox.Auth.clearAccountLocalPII !== 'function') {
    throw new Error('Auth.clearAccountLocalPII must exist to clear per-account PII on logout');
  }
  sandbox.localStorage.setItem('beautySuggestions_owner@example.com', '[{"before":"face-photo-url"}]');
  sandbox.localStorage.setItem('beautySuggestions_other@example.com', '[{"before":"someone-else"}]');
  sandbox.localStorage.setItem('beautyAnalysisFeedback', '[{"faceShape":"oval"}]');
  sandbox.localStorage.setItem('beautyHistory_owner@example.com', '[{"臉型":"鵝蛋臉","timestamp":"2026-07-31T00:00:00Z"}]');
  sandbox.Auth.clearAccountLocalPII('Owner@Example.com'); // 大小寫不同也要清到
  if (sandbox.localStorage.getItem('beautySuggestions_owner@example.com') !== null) {
    throw new Error('Logout must clear the current account saved-look PII (contains face photo URLs)');
  }
  if (sandbox.localStorage.getItem('beautyAnalysisFeedback') !== null) {
    throw new Error('Logout must clear the analysis feedback PII');
  }
  if (sandbox.localStorage.getItem('beautyHistory_owner@example.com') === null) {
    throw new Error('Logout must preserve the current account text-only analysis history');
  }
  if (sandbox.localStorage.getItem('beautySuggestions_other@example.com') === null) {
    throw new Error('Logout must NOT touch another account persisted favorites');
  }
}

// 分析紀錄只保存文字，不寫入照片或模型原始值。
{
  const textOnly = sandbox.History._textOnly({
    '臉型': '鵝蛋臉',
    '側臉鼻型': { label: '翹鼻', confidence: 0.72 },
    photo: 'data:image/jpeg;base64,SECRET',
    _modelRaw: { '臉型': '圓形臉' },
  });
  const serialized = JSON.stringify(textOnly);
  if (serialized.includes('data:image') || serialized.includes('_modelRaw')) {
    throw new Error('Analysis history must not retain photos or raw model payloads');
  }
  if (textOnly['側臉鼻型'] !== '翹鼻') {
    throw new Error('Analysis history must retain the PRO side-nose text label');
  }
}

// ── AnalysisPackage 基本結構 ───────────────────────────────────
const pkg = sandbox.AnalysisPackage.create({ mode: 'basic' });
if (pkg.schemaVersion !== '2026-08-v2') throw new Error('Bad schemaVersion');
if (!pkg.faceAnalysis || !pkg.generativeText || !pkg.render || !pkg.recommendations) {
  throw new Error('analysisPackage missing expected sections');
}
if (!pkg.async || !Object.prototype.hasOwnProperty.call(pkg.async, 'jobId')) {
  throw new Error('analysisPackage async job fields missing');
}

// 分析時間統一轉換，並支援 Firestore seconds。
if (!routerSource.includes('function formatAnalysisTime(value)') ||
    !routerSource.includes('value.seconds ?? value._seconds') ||
    /hist-date[^\n]+new Date\(r\.timestamp\)/.test(routerSource)) {
  throw new Error('Analysis history must use the normalized timestamp formatter');
}

// ── faceAnalysis schema 欄位完整性 ────────────────────────────
const fa = pkg.faceAnalysis;
const requiredFaFields = [
  'faceShape', 'browShape', 'eyeShape', 'noseFront', 'noseSide',
  'lipShape', 'skinTone', 'lipLab', 'symmetry', 'sidePhotoUsed', 'proStatus', 'raw'
];
for (const field of requiredFaFields) {
  if (!Object.prototype.hasOwnProperty.call(fa, field)) {
    throw new Error(`faceAnalysis schema missing field: '${field}'`);
  }
}
// BASIC create() 時這幾個欄位應為 null
for (const f of ['noseSide', 'symmetry', 'sidePhotoUsed', 'proStatus']) {
  if (fa[f] !== null) throw new Error(`faceAnalysis.${f} should be null in BASIC create(), got: ${JSON.stringify(fa[f])}`);
}
// skinTone 在 create() 為 null（初始模板），結構驗證在 fromRawFaceAnalysis 區塊做

// ── fromRawFaceAnalysis 映射驗證 ──────────────────────────────
const mockRaw = {
  '臉型': '鵝蛋臉',
  '眉型': '彎月眉',
  '眼型': '桃花眼',
  '鼻型': '標準鼻',
  '鼻型_側面': null,
  '嘴型': '微笑唇',
  '膚色': {
    '四季型': 'spring',
    '膚色分級': '白皙',
    'LAB': { L: 70.12, a: 10.34, b: 14.56 },
    'LAB來源': '正面+側面平均',
  },
  '嘴唇_LAB': { L: 40, a: 20, b: 10 },
  '臉部對稱性': {
    score: 82,
    eyeOpenRatio: 0.95,
    noseDeviation: 0.02,
    mouthSymmetry: 0.98,
  },
  '精細分析狀態': {
    '多角度照片': '已接收，膚色已雙角度平均',
    '臉部對稱性': '已計算',
    '鼻型精細分類': '需 70-90° 側面輪廓照',
  },
};

const mapped = sandbox.AnalysisPackage.fromRawFaceAnalysis(mockRaw, 'pro');

// 基本欄位
if (mapped.faceShape !== '鵝蛋臉') throw new Error(`faceShape mapping wrong: ${mapped.faceShape}`);
if (mapped.lipShape !== '微笑唇') throw new Error(`lipShape mapping wrong: ${mapped.lipShape}`);
if (mapped.version !== 'PRO') throw new Error(`version wrong for PRO mode: ${mapped.version}`);

// 對稱性映射
if (!mapped.symmetry) throw new Error('fromRawFaceAnalysis: symmetry is null/undefined');
if (mapped.symmetry.score !== 82) throw new Error(`symmetry.score wrong: ${mapped.symmetry.score}`);
if (mapped.symmetry.eyeOpenRatio !== 0.95) throw new Error(`symmetry.eyeOpenRatio wrong: ${mapped.symmetry.eyeOpenRatio}`);
if (mapped.symmetry.noseDeviation !== 0.02) throw new Error(`symmetry.noseDeviation wrong: ${mapped.symmetry.noseDeviation}`);
if (mapped.symmetry.mouthSymmetry !== 0.98) throw new Error(`symmetry.mouthSymmetry wrong: ${mapped.symmetry.mouthSymmetry}`);

// sidePhotoUsed：'已接收，膚色已雙角度平均'.startsWith('已接收') → true
if (mapped.sidePhotoUsed !== true) throw new Error(`sidePhotoUsed should be true, got: ${mapped.sidePhotoUsed}`);

// proStatus 結構
if (!mapped.proStatus || !mapped.proStatus['多角度照片']) {
  throw new Error(`proStatus mapping wrong: ${JSON.stringify(mapped.proStatus)}`);
}

// skinTone 結構含 labSource
const st = mapped.skinTone;
if (!st ||
    !Object.prototype.hasOwnProperty.call(st, 'season') ||
    !Object.prototype.hasOwnProperty.call(st, 'level') ||
    !Object.prototype.hasOwnProperty.call(st, 'lab') ||
    !Object.prototype.hasOwnProperty.call(st, 'labSource')) {
  throw new Error(`skinTone missing fields: ${JSON.stringify(st)}`);
}
if (st.labSource !== '正面+側面平均') {
  throw new Error(`skinTone.labSource wrong: ${st.labSource}`);
}

// lipLab
if (!mapped.lipLab || mapped.lipLab.L !== 40) throw new Error(`lipLab mapping wrong: ${JSON.stringify(mapped.lipLab)}`);

// noseSide（此測試中為 null）
if (mapped.noseSide !== null) throw new Error(`noseSide should be null, got: ${mapped.noseSide}`);
const mappedSideNose = sandbox.AnalysisPackage.fromRawFaceAnalysis({
  ...mockRaw,
  '側臉鼻型': { label: '翹鼻', confidence: 0.72, caveat: '僅供參考' },
}, 'pro');
if (mappedSideNose.noseSide !== '翹鼻') {
  throw new Error(`noseSide object mapping wrong: ${JSON.stringify(mappedSideNose.noseSide)}`);
}

// BASIC 模式下 sidePhotoUsed 應為 null（無 精細分析狀態）
const mappedBasic = sandbox.AnalysisPackage.fromRawFaceAnalysis({ ...mockRaw, '精細分析狀態': null }, 'basic');
if (mappedBasic.sidePhotoUsed !== null) throw new Error(`sidePhotoUsed should be null in BASIC mode, got: ${mappedBasic.sidePhotoUsed}`);
if (mappedBasic.version !== 'BASIC') throw new Error(`version wrong for BASIC mode: ${mappedBasic.version}`);

checkProtectedWriteActor()
  .then(() => { console.log('frontend smoke check passed'); })
  .catch(err => {
    console.error(err && err.message ? err.message : err);
    process.exit(1);
  });
