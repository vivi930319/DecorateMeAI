// 正反項測試：分析 job 失敗時，前端要分得出「照片要重拍」與「系統壞了」。
//
// 後端把失敗分成三碼（FACE_IMAGE_UNUSABLE / FACE_ANALYSIS_ERROR /
// PACKAGE_BUILD_FAILED），只有第一種的 message 是寫給使用者看的重拍指引。
// waitForFaceJob 先前只丟 message、丟掉 code，呼叫端因此無從分辨。
//
// 跑法：node face_job_error_check.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const rootDir = __dirname;
const apiSource = fs.readFileSync(path.join(rootDir, 'js', 'api.js'), 'utf8');
const routerSource = fs.readFileSync(path.join(rootDir, 'js', 'router.js'), 'utf8');
const loc = { origin: 'https://decorate-me.web.app', reload() {} };
const mk = m => ({
  setItem: (k, v) => m.set(k, String(v)),
  getItem: k => (m.has(k) ? m.get(k) : null),
  removeItem: k => m.delete(k)
});

const sandbox = {
  console,
  window: { DECORATE_ME_CONFIG: { aiGatewayUrl: '' }, location: loc },
  location: loc,
  URL,
  FormData: class { append() {} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  document: { createElement: () => ({ getContext: () => ({ drawImage() {} }), toBlob: () => {} }) },
  Image: class {},
  localStorage: mk(new Map()),
  sessionStorage: mk(new Map()),
  setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder,
  crypto: require('crypto').webcrypto
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(`${apiSource}; this.Api = Api; this.localizeUserError = localizeUserError;`, sandbox);

const failures = [];
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${name}`);
  if (!ok) {
    console.log(`        得到 ${JSON.stringify(got)}`);
    console.log(`        預期 ${JSON.stringify(want)}`);
    failures.push(name);
  }
}

// router 對照片問題不加「分析失敗：」前綴，其餘才加。這裡照抄那段判斷來驗，
// 順便確認 router.js 真的還是這樣寫的（改了這個檔就會在下面的來源檢查失敗）。
function alertTextFor(err) {
  const photoProblem = err.code === 'FACE_IMAGE_UNUSABLE';
  const raw = photoProblem ? err.message : '分析失敗：' + err.message;
  return sandbox.localizeUserError(raw, err.code || '', 0, null);
}

async function jobFailingWith(error) {
  sandbox.Api.getFaceJob = async () => ({ status: 'failed', jobId: 'j1', error });
  try {
    await sandbox.Api.waitForFaceJob('basic', 'j1', 'tok', () => {});
    return null;
  } catch (e) {
    return e;
  }
}

(async () => {
  console.log('='.repeat(62));
  console.log('正項：分析成功要拿得到結果');
  console.log('='.repeat(62));
  sandbox.Api.getFaceJob = async () => ({ status: 'completed', jobId: 'j1' });
  sandbox.Api.getFaceJobResult = async () => ({ result: { '臉型': '圓形臉' } });
  const ok = await sandbox.Api.waitForFaceJob('basic', 'j1', 'tok', () => {});
  check('完成的 job 回傳結果', ok, { result: { '臉型': '圓形臉' } });

  console.log('');
  console.log('='.repeat(62));
  console.log('反項：三種失敗要分得開');
  console.log('='.repeat(62));

  console.log('\n-- 照片問題：指引原樣顯示，不冠「分析失敗：」--');
  const guidance = '請把頭轉向你的右邊，讓兩邊臉頰一樣大';
  let err = await jobFailingWith({ code: 'FACE_IMAGE_UNUSABLE', message: guidance, retryable: true });
  check('丟出的 code', err.code, 'FACE_IMAGE_UNUSABLE');
  check('丟出的 message', err.message, guidance);
  check('retryable', err.retryable, true);
  check('使用者看到的字', alertTextFor(err), guidance);

  console.log('\n-- 內部錯誤：查表換成單一句子，不要疊字 --');
  err = await jobFailingWith({ code: 'FACE_ANALYSIS_ERROR', message: '臉部分析失敗，請稍後再試', retryable: true });
  check('丟出的 code', err.code, 'FACE_ANALYSIS_ERROR');
  check('使用者看到的字', alertTextFor(err), '臉部分析失敗，請稍後再試。');
  check('沒有「分析失敗：分析失敗」疊字', /分析失敗[：:].*分析失敗/.test(alertTextFor(err)), false);

  console.log('\n-- 封裝失敗：明說不需重拍 --');
  err = await jobFailingWith({ code: 'PACKAGE_BUILD_FAILED', message: '臉部分析已完成，但結果封裝失敗，請稍後再試（不需重拍）。', retryable: true });
  check('丟出的 code', err.code, 'PACKAGE_BUILD_FAILED');
  check('使用者看到的字含「不需重拍」', /不需重拍/.test(alertTextFor(err)), true);

  console.log('\n-- 後端沒給 error 物件時不能炸掉 --');
  err = await jobFailingWith(undefined);
  check('有 fallback 訊息', err.message, '臉部分析 job 失敗');
  check('code 是空字串不是 undefined', err.code, '');

  console.log('\n-- router.js 真的照這個規則寫 --');
  check('router 有讀 err.code',
    routerSource.includes("const photoProblem = err.code === 'FACE_IMAGE_UNUSABLE'"), true);
  check('router 有把 code 傳給 showAlert',
    /showAlert\([\s\S]{0,400}?code: err\.code/.test(routerSource), true);

  console.log('\n-- 同意才上傳照片（介面對使用者的承諾）--');
  let captured = null;
  sandbox.Api._protectedFetch = async (url, opts) => {
    captured = JSON.parse(opts.body);
    return { ok: true, status: 204 };
  };
  const base = {
    mode: 'basic', jobId: 'j9', resultToken: 't', packageId: 'AN-1',
    predicted: { '眼型': '鳳眼' }, corrections: { '眼型': '圓眼' },
    imageDataUrl: 'data:image/png;base64,AAAA'
  };

  await sandbox.Api.sendAnalysisFeedback({ ...base });
  check('未同意時不帶 imageDataUrl', 'imageDataUrl' in captured, false);
  check('未同意時不帶 allowTrainingUse', 'allowTrainingUse' in captured, false);
  check('但修正本身照樣送出', captured.corrections, { '眼型': '圓眼' });

  await sandbox.Api.sendAnalysisFeedback({ ...base, allowTrainingUse: true });
  check('同意時才帶照片', captured.imageDataUrl, base.imageDataUrl);
  check('同意時帶 allowTrainingUse', captured.allowTrainingUse, true);

  await sandbox.Api.sendAnalysisFeedback({ ...base, allowTrainingUse: true, corrections: {} });
  check('沒有修正就不送照片（沒有樣本可存）', 'imageDataUrl' in captured, false);

  await sandbox.Api.sendAnalysisFeedback({ ...base, allowTrainingUse: true, imageDataUrl: '' });
  check('同意但沒有照片時不亂送', 'imageDataUrl' in captured, false);

  console.log('\n-- 介面文案不能宣稱絕不上傳（那樣勾選就變成謊話）--');
  check('文案改成講明預設行為',
    routerSource.includes('預設只送出判斷結果與你的修正，不會上傳你的照片'), true);
  check('舊的絕對承諾已移除',
    routerSource.includes('<strong>這一步不會上傳你的照片</strong>'), false);
  check('勾選預設不打勾', /let allowTraining = false;/.test(routerSource), true);

  console.log('\n-- 刪會員：先清影像，清不掉就不准刪帳號 --');
  const order = [];
  sandbox.Api._protectedFetch = async (url) => {
    order.push('purge');
    return { ok: purgeOk, status: purgeOk ? 200 : 502,
             json: async () => purgeOk ? { removed: { face: 2 } }
                                       : { error: { message: 'render 沒有清除成功' } } };
  };
  sandbox.Api._protectedWrite = async (_x, fn) => { order.push('delete'); return fn(); };
  sandbox.Api._fetchWithRelogin = async () => ({ ok: true, json: async () => ({ member: {} }) });

  let purgeOk = true;
  order.length = 0;
  let p = await sandbox.Api.purgeMemberMedia('v@example.com');
  check('清除成功時回 ok', p.ok, true);
  check('回報刪了幾筆', p.removed, { face: 2 });

  purgeOk = false;
  p = await sandbox.Api.purgeMemberMedia('v@example.com');
  check('清除失敗時回 not ok', p.ok, false);
  check('把上游訊息帶回來', p.error, 'render 沒有清除成功');

  console.log('\n-- 後台真的照這個順序寫 --');
  check('刪除前先呼叫 purgeMemberMedia',
    /const purge = await Api\.purgeMemberMedia\(email\);[\s\S]{0,600}?await Api\.deleteMember\(email\)/.test(routerSource), true);
  check('清除失敗就 return，不往下刪',
    /if \(!purge \|\| !purge\.ok\)[\s\S]{0,500}?return;/.test(routerSource), true);
  check('告訴管理員帳號還在、可以重試',
    routerSource.includes('帳號仍在，可以重試'), true);
  check('確認視窗有提到臉部影像',
    routerSource.includes('以及他上傳的臉部影像都會一併移除'), true);

  console.log('');
  console.log('='.repeat(62));
  if (failures.length) {
    console.log(`失敗 ${failures.length} 項：`);
    failures.forEach(f => console.log(`  - ${f}`));
    process.exit(1);
  }
  console.log('全部通過');
})();
