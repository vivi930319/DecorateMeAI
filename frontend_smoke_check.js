const fs = require('fs');
const path = require('path');
const vm = require('vm');

const rootDir = __dirname;
const apiSource = fs.readFileSync(path.join(rootDir, 'js', 'api.js'), 'utf8');
const storage = new Map();
const session = new Map();

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
    }
  },
  location: { reload() {} },
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
vm.runInContext(`${apiSource}; this.ApiConfig = ApiConfig; this.Api = Api; this.ImagePipeline = ImagePipeline; this.AnalysisPackage = AnalysisPackage; this.Auth = Auth; this.AdminStore = AdminStore; this.Cart = Cart;`, sandbox);

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
sandbox.Cart.add(1);
sandbox.Cart.add(1);
if (sandbox.Cart.count() !== 2 || sandbox.Cart.list()[0].qty !== 2) throw new Error('Cart quantity accumulation failed');
sandbox.Cart.change(1, -2);
if (sandbox.Cart.count() !== 0 || sandbox.Cart.list().length !== 0) throw new Error('Cart item removal failed');

// ── 服務設定 ────────────────────────────────────────────────
const requiredServices = ['faceBasic', 'facePro', 'textSuggestion', 'render', 'product', 'memberDatabase', 'crawler'];
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
if (sandbox.ApiConfig.services.crawler.baseUrl !== '/admin-api') throw new Error('Admin crawler API must use same-origin Gateway');

// ── Api 方法 ─────────────────────────────────────────────────
for (const method of ['createFaceJob', 'createFaceProJob', 'getFaceJob', 'getFaceJobResult', 'waitForFaceJob', 'suggestMakeup', 'previewCrawledProduct']) {
  if (typeof sandbox.Api[method] !== 'function') throw new Error(`Missing Api.${method}`);
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
if (!configExample.includes('allowInsecureOtpBypass: false')) {
  throw new Error('config.local.example.js must keep allowInsecureOtpBypass disabled by default');
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

// ── AnalysisPackage 基本結構 ───────────────────────────────────
const pkg = sandbox.AnalysisPackage.create({ mode: 'basic' });
if (pkg.schemaVersion !== '2026-06-v1') throw new Error('Bad schemaVersion');
if (!pkg.faceAnalysis || !pkg.generativeText || !pkg.render || !pkg.recommendations) {
  throw new Error('analysisPackage missing expected sections');
}
if (!pkg.async || !Object.prototype.hasOwnProperty.call(pkg.async, 'jobId')) {
  throw new Error('analysisPackage async job fields missing');
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

// BASIC 模式下 sidePhotoUsed 應為 null（無 精細分析狀態）
const mappedBasic = sandbox.AnalysisPackage.fromRawFaceAnalysis({ ...mockRaw, '精細分析狀態': null }, 'basic');
if (mappedBasic.sidePhotoUsed !== null) throw new Error(`sidePhotoUsed should be null in BASIC mode, got: ${mappedBasic.sidePhotoUsed}`);
if (mappedBasic.version !== 'BASIC') throw new Error(`version wrong for BASIC mode: ${mappedBasic.version}`);

console.log('frontend smoke check passed');
