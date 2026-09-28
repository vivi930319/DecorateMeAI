// 收藏妝容圖的授權、看商品前的提醒，以及分享（2026-09-28 使用者定案）。
//
//   1. 收藏的妝容圖管理員在後台看得到（測試串接穩定性用）——存之前一定要說、一定要勾同意。
//      兩個入口（「收藏這次妝容」視窗、看商品前的提醒）用同一份說明，不能各寫各的。
//   2. 看商品與存圖**獨立**：「只看商品，不收藏」一定走得過去，不是關卡。
//   3. 每個「查看推薦商品」都走同一個提醒，不能有入口繞過。
//   4. 分享的是圖片本身，妝前可以取消。
const fs = require('fs');
const path = require('path');

const root = process.argv[2] || path.join(__dirname, '..');
const strip = src => src.replace(/\r\n/g, '\n').replace(/^\s*\/\/.*$/gm, '');
const router = strip(fs.readFileSync(path.join(root, 'js/router.js'), 'utf8'));
const flow = strip(fs.readFileSync(path.join(root, 'js/makeup-flow.js'), 'utf8'));
const share = strip(fs.readFileSync(path.join(root, 'js/look-share.js'), 'utf8'));
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

let failed = 0;
const check = (name, ok) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`); if (!ok) failed += 1; };

const consent = (router.match(/text: '([^']+)'\s*\+\s*'([^']+)'/) || []).slice(1).join('');
check('授權說明有講「管理員可以在後台看到」', /管理員可以在後台看到/.test(consent));
check('授權說明有講用途是測試串接穩定性', /測試系統串接的穩定性/.test(consent));
check('授權說明有講包含妝前照片', /妝前照片/.test(consent));

const saveModal = router.slice(router.indexOf('function openSaveLookModal()'), router.indexOf('function openProductsWithSaveReminder()'));
check('收藏視窗放了同意勾選', /lookConsentHtml\(\)/.test(saveModal) && /bindLookConsent\(modal, \[confirmBtn\]\)/.test(saveModal));
check('收藏視窗沒勾同意就不存', /if \(!after \|\| !modal\.querySelector\('\[data-look-consent\]'\)\?\.checked\) return;/.test(saveModal));

const reminder = router.slice(router.indexOf('function openProductsWithSaveReminder()'), router.indexOf('function closeProductRecommendationModal()'));
check('看商品前的提醒也用同一份同意', /lookConsentHtml\(\)/.test(reminder));
check('「只看商品，不收藏」直接開商品、不存圖', /data-only-products\]'\)\.onclick = \(\) => \{\s*Router\.lookSaveDeclinedFor = after;\s*close\(\);\s*openProductRecommendationModal\(\);/.test(reminder));
check('「只看商品」按鈕不受同意勾選鎖住', /bindLookConsent\(modal, \[saveBtn\]\)/.test(reminder));
check('收藏時記下同意的版本與時間', /adminReviewConsent: \{ version: LOOK_SAVE_CONSENT\.version/.test(router));

const bypass = (router.match(/onclick="openProductRecommendationModal\(\)"/g) || []).length
  + (flow.match(/\.onclick = openProductRecommendationModal;/g) || []).length;
check(`所有「查看推薦商品」都走提醒（直接開的入口：${bypass}）`, bypass === 0);

check('分享：妝前可以取消', /data-with-before checked/.test(share));
check('分享：手機走系統分享面板並帶圖片檔', /navigator\.share\(data\)/.test(share) && /files: \[file\]/.test(share));
check('分享：Threads 發文連結', /threads\.net\/intent\/post\?text=/.test(share));
check('index.html 在 makeup-flow.js 之前載入 look-share.js',
  html.indexOf('js/look-share.js') > 0 && html.indexOf('js/look-share.js') < html.indexOf('js/makeup-flow.js'));

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n收藏授權與分享測試通過');
