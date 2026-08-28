// 登入狀態監看：不要讓人按下按鈕才知道自己已經登出。
//
// 這個功能存在的原因是一個很難自己發現的組合：後台的會員清單是**透過 gateway
// 代理**讀資料庫的，gateway 用它自己的憑證去問，所以使用者的 session 過期時
// 清單照樣讀得出來。但寫入前的守衛檢查的是**使用者的** session。
// 於是畫面看起來一切正常，直到按下儲存才九筆全部失敗——而那時九列都已經改完了。
//
// 2026-08-27 實際發生過一次。
//
// 用法：node tests/session_watch_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8');
const api = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8');

const cut = (sig) => {
    const i = src.indexOf(sig);
    if (i < 0) return '';
    let d = 0;
    for (let k = src.indexOf('{', i); k < src.length; k++) {
        if (src[k] === '{') d++;
        else if (src[k] === '}') { d--; if (!d) return src.slice(i, k + 1); }
    }
    return '';
};

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};

const mod = cut('const SessionWatch = (() => {');

console.log('');
console.log('=== 1. 三個檢查時機都要在 ===');
check('模組存在', Boolean(mod));
// 離開一陣子回來，正是最可能已經過期的時候
check('切回分頁時檢查', mod.includes("visibilitychange") && mod.includes('visibilityState'));
check('定時檢查', /setInterval\(check/.test(mod));
check('啟動時立刻檢查一次', /check\(\);\s*[\r\n]\s*timer = setInterval/.test(mod));
// 兩次輪詢之間也可能過期，送出前是最後一道
check('送出前再確認一次', /const fresh = await Api\.validateSession\(\)/.test(src));

console.log('');
console.log('=== 2. 不要製造噪音 ===');
// 每次檢查都喊的東西會被當成背景噪音，然後真的壞掉那次也被忽略
check('只在狀態改變時回報', /if \(state !== last\)/.test(mod));
// 分頁切換與計時器可能同時觸發
check('不會重疊發出請求', mod.includes('if (checking) return'));
// 留著會在每個頁面持續打 /auth/session
check('離開後台會停止', /SessionWatch\.stop\(\)/.test(src));
check('stop 會清掉計時器與監聽',
  /clearInterval\(timer\)/.test(mod) && /removeEventListener\('visibilitychange'/.test(mod));

console.log('');
console.log('=== 3. 壞掉時的處置 ===');
// 按得下去卻註定失敗的按鈕，等於浪費使用者的時間兩次
check('過期時鎖住儲存按鈕', /save\.disabled = true/.test(src));
check('恢復時解鎖', /save\.disabled = false/.test(src));
check('狀態列說明原因', /登入已過期[\s\S]{0,80}存不進去/.test(src));

console.log('');
console.log('=== 4. 措辭要給對的下一步 ===');
// 401 是登入過期，「請稍後再試」是錯的建議——等下去只會更糟
check('401 有獨立的 reason', api.includes("'SESSION_EXPIRED'"));
check('401 不叫人稍後再試',
  /SESSION_EXPIRED: '[^']*重新登入[^']*'/.test(api)
  && !/SESSION_EXPIRED: '[^']*稍後再試[^']*'/.test(api));
// 使用者最想知道的是「我剛才改的東西有沒有寫進去一半」
check('明講沒有任何一筆被寫入', /沒有任何一筆被寫入/.test(src) || /沒有任何一筆被寫入/.test(api));


console.log('');
console.log('=== 並行的重複讀取要合併 ===');
// 會員中心進頁時 getMemberPoints 被呼叫兩次：一次填餘額、一次畫明細，
// 而同一個回應裡 balance 與 transactions 都有。第二次純粹是浪費，
// 在對方的記錄裡看起來也像我們在重複打人家的服務。
check('有 in-flight 去重', api.includes('_dedupe(key, run)') && api.includes('_inflight: new Map()'));
['getMemberPoints', 'listMemberTasks', 'listSavedLooks', 'listRemoteFavorites'].forEach((n) => {
    check(`${n} 走去重`, api.includes(`this._dedupe(`) && api.includes(`async __${n}(email) {`));
});
// 只合併進行中的請求，不做快取——快取會讓「按重新整理沒有變新」，那更難查
check('結束後清掉 key，不是快取', /_inflight\.delete\(key\)/.test(api));
check('只用在唯讀讀取，寫入不合併',
  !/_dedupe\([^)]*\)\s*=>\s*this\.__(patch|create|delete|toggle|save)/i.test(api));
console.log('');
console.log(`${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
