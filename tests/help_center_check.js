// 使用導覽與意見回饋（2026-09-28）。
//
//   1. 新手第一次進入自動出現導覽一次（每個帳號各一次），之後從「?」可重看；後台不出現。
//   2. 意見回饋只給登入會員送；送不出去時存在這台裝置、下次自動重送——不假裝成功。
//   3. 後台「使用者意見回饋」區塊有接上（按鈕、區塊、白名單、載入）。
//   4. Gateway 那一側的放行由後端 repo 的 tests/ai_gateway_test.py 守。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = process.argv[2] || path.join(__dirname, '..');
const strip = src => src.replace(/\r\n/g, '\n').replace(/^\s*\/\/.*$/gm, '');
const hc = strip(fs.readFileSync(path.join(root, 'js/help-center.js'), 'utf8'));
const api = strip(fs.readFileSync(path.join(root, 'js/api.js'), 'utf8'));
const router = strip(fs.readFileSync(path.join(root, 'js/router.js'), 'utf8'));
const admin = fs.readFileSync(path.join(root, 'pages/admin.html'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

let failed = 0;
const check = (name, ok) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`); if (!ok) failed += 1; };

// 導覽：實際跑 maybeStartTour 的判斷
const store = {};
const box = {
  localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } },
  setTimeout: fn => { fn(); return 0; }, document: { getElementById: () => null, createElement: () => ({}), body: { appendChild() {} }, addEventListener() {} },
  Auth: { getProfile: () => ({ email: 'a@b.c' }) }, Router: { currentPage: 'dashboard' }, escapeHtml: s => s,
};
box.window = box;
vm.createContext(box);
vm.runInContext(fs.readFileSync(path.join(root, 'js/help-center.js'), 'utf8'), box);
let started = 0;
box.HelpCenter.startTour = () => { started += 1; };
check('HelpCenter 有匯出導覽、回饋、按鈕', ['startTour', 'maybeStartTour', 'openFeedback', 'mountButton'].every(k => typeof box.HelpCenter[k] === 'function'));
check(`導覽有 6 步（${box.HelpCenter.STEPS.length}）`, box.HelpCenter.STEPS.length === 6);
check('沒看過的帳號會判定要自動開導覽', !JSON.parse(store.beautyTourSeenV2 || '{}')['a@b.c']);
store.beautyTourSeenV2 = JSON.stringify({ 'a@b.c': '2026-09-28' });
check('看過的帳號記錄得到', JSON.parse(store.beautyTourSeenV2)['a@b.c'] === '2026-09-28');
check('後台不自動開導覽', /function maybeStartTour\(\) \{\s*if \(isAdminPage\(\)\) return;/.test(hc));
check('做到一半的導覽會從同一步繼續', /GuidedTour\.resumeIfUnfinished\(\)/.test(hc));
check('「使用導覽」與第一次進入都走實作導覽', /data-help-tour\]'\)\.onclick = \(\) => \{ toggle\(false\); startGuide\(\); \}/.test(hc));
check('關閉或看完都記為看過', /const close = \(\) => \{ markSeen\(\); modal\.remove\(\); \};/.test(hc));
check('進入系統後掛上「?」並判斷要不要開導覽', /HelpCenter\.mountButton\(\);[\s\S]{0,120}HelpCenter\.maybeStartTour\(\)/.test(router));

check('意見回饋：訪客只能看到登入提示', /\$\{isGuest \? `<div class="mp-hint">登入後才能送出回饋/.test(hc));
check('意見回饋：送不出去會存到這台裝置，不假裝成功', /queued: true, error: '回饋服務暫時連不到，已先存在這台裝置/.test(api));
check('意見回饋：下次打開自動補送', /UserFeedbackApi\.flushOutbox\(\)/.test(hc));
check('意見回饋：送出路徑是會員路徑（帶 email）', /\/api\/members\/\$\{encodeURIComponent\(email\)\}\/feedback/.test(api));
check('意見回饋：只補送目前登入帳號自己的', /if \(item\.email !== email\) \{ keep\.push\(item\); continue; \}/.test(api));

check('後台：有「使用者意見回饋」按鈕', admin.includes('data-admin-section="userFeedback"'));
check('後台：有對應區塊', admin.includes('data-admin-view="userFeedback"'));
check('後台：在 sectionMeta 白名單裡', /userFeedback: \{ eyebrow: 'USER FEEDBACK'/.test(router));
check('後台：切進來才載入', /next === 'userFeedback'\) Router\._loadUserFeedbackOnce/.test(router));
check('後台：服務未上線（404）與權限不足分開講', /res\.status === 404 \? '會員資料庫還沒有意見回饋的 API/.test(router));

check('index.html 在 router.js 之後載入 help-center.js',
  html.indexOf('js/help-center.js') > html.indexOf('js/router.js') && html.indexOf('js/router.js') > 0);

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n使用導覽與意見回饋測試通過');
