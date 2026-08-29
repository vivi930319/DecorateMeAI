// 推薦結果的價格／品牌篩選。
//
// 這個篩選只作用在已經拿回來的那批推薦上，所以測試的重點不只是「篩得對」，
// 還有「篩到空的時候有沒有把話講清楚」——使用者很容易把空結果誤讀成
// 「平台沒有這個價位的商品」，而實際上全庫有 1041 件。
//
// 用法：node tests/rec_filter_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');

const MARK = 'const RecFilter = {';
const start = src.indexOf(MARK);
if (start < 0) { console.log('找不到 RecFilter'); process.exit(1); }
let depth = 0, end = -1;
for (let i = src.indexOf('{', start); i < src.length; i++) {
  if (src[i] === '{') depth++;
  else if (src[i] === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
}

const sandbox = {
  console,
  escapeHtml: s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
};
vm.createContext(sandbox);
vm.runInContext(src.slice(start, end) + ';\nglobalThis.__F = RecFilter;', sandbox);
const F = sandbox.__F;

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
  console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
  cond ? pass++ : fail++;
};

console.log('\n=== 1. 價格解析（後端回的是字串不是數字）===');
check('NT$950 -> 950', F.parsePrice('NT$950') === 950);
check('NT$1,200 逗號 -> 1200', F.parsePrice('NT$1,200') === 1200);
check('純數字字串 -> 數字', F.parsePrice('680') === 680);
// 這條最重要：解析不出來必須是 null，不能是 0。
// 回 0 的話商品會落進「400 以下」，看起來有結果，其實是錯的。
check('解析不出來 -> null（不是 0）', F.parsePrice('洽詢') === null, String(F.parsePrice('洽詢')));
check('null / undefined -> null', F.parsePrice(null) === null && F.parsePrice(undefined) === null);

console.log('\n=== 2. 價格區間篩選 ===');
const items = [
  { name: 'A', price: 'NT$176', brand: 'Za' },
  { name: 'B', price: 'NT$425', brand: '3CE' },
  { name: 'C', price: 'NT$950', brand: 'MAC' },
  { name: 'D', price: 'NT$2500', brand: 'YSL' },
  { name: 'E', price: '洽詢', brand: 'MAC' },
];
const names = l => l.map(x => x.name).join('');
F.reset();
check('不限價格 -> 全部', names(F.apply(items)) === 'ABCDE');
F.price = 'p1'; check('400 以下 -> A', names(F.apply(items)) === 'A', names(F.apply(items)));
F.price = 'p2'; check('400–900 -> B', names(F.apply(items)) === 'B', names(F.apply(items)));
F.price = 'p3'; check('900–1500 -> C', names(F.apply(items)) === 'C', names(F.apply(items)));
F.price = 'p4'; check('1500 以上 -> D', names(F.apply(items)) === 'D', names(F.apply(items)));
F.price = 'p1';
check('沒有價格的商品不進任何價格區間', !F.apply(items).some(x => x.name === 'E'));

console.log('\n=== 3. 品牌篩選 ===');
F.reset(); F.brand = 'MAC';
check('只留 MAC', names(F.apply(items)) === 'CE', names(F.apply(items)));
F.brand = '不存在的品牌';
check('不存在的品牌 -> 空', F.apply(items).length === 0);

console.log('\n=== 4. 價格與品牌同時生效 ===');
F.reset(); F.brand = 'MAC'; F.price = 'p3';
check('MAC 且 900–1500 -> C', names(F.apply(items)) === 'C', names(F.apply(items)));
F.brand = 'MAC'; F.price = 'p1';
check('MAC 且 400 以下 -> 空', F.apply(items).length === 0);

console.log('\n=== 5. 品牌選項只列這批有的 ===');
F.reset();
const brands = F.brandsIn(items).map(([b, n]) => `${b}:${n}`);
check('依件數排序且不含全庫其他品牌', brands[0] === 'MAC:2', brands.join(' '));
check('不會列出這批沒有的品牌', !brands.some(b => b.startsWith('NARS')));

console.log('\n=== 6. 措辭：不能讓人以為是搜尋全庫 ===');
const html = F.html(items);
check('說明「在這 N 件推薦中篩選」', html.includes('在這 5 件推薦中篩選'), '');
check('明講不是搜尋全部商品', html.includes('不是搜尋全部商品'));
check('品牌鈕帶件數', html.includes('rf-n'));
const empty = F.emptyHtml();
check('空結果說「這批推薦中沒有」', empty.includes('這批推薦中沒有符合條件的商品'));
check('空結果不暗示平台沒有這種商品',
  empty.includes('推薦一次只挑出每個品類最適合的幾件'));
check('空結果提供清除篩選', empty.includes('data-rf-reset'));

console.log('\n=== 7. XSS：品牌名來自後端資料 ===');
const evil = [{ name: 'X', price: 'NT$100', brand: '<img src=x onerror=alert(1)>' }];
check('品牌名有跳脫', !F.html(evil).includes('<img src=x'), F.html(evil).slice(-120));

console.log('\n=== 8. 用真實推薦回應驗一次 ===');
const livePath = path.join(ROOT, 'tests/_live_recommend_sample.json');
if (fs.existsSync(livePath)) {
  const live = JSON.parse(fs.readFileSync(livePath, 'utf8'));
  const ps = live.withBrow.analysisPackage?.recommendations?.products || [];
  F.reset();
  check('真實資料全部可解析價格',
    ps.every(p => F.parsePrice(p.price) !== null),
    `${ps.length} 件`);
  const bs = F.brandsIn(ps);
  check('真實資料能列出品牌', bs.length > 0, bs.slice(0, 4).map(([b, n]) => `${b}:${n}`).join(' '));
  F.price = 'p4';
  const pricey = F.apply(ps);
  check('1500 以上的篩選不會爆炸', Array.isArray(pricey), `剩 ${pricey.length} 件`);
  F.reset();
} else {
  console.log('  (略過：沒有 _live_recommend_sample.json)');
}

console.log('\n=== 9. 一般商品頁的品牌／價格／排序 ===');
// 使用者不是只在「推薦」那一區買東西，一般商品頁就是逛街的地方，
// 而逛街本來就會照價格與品牌看。
const shopCss = fs.readFileSync(path.join(ROOT, 'css/main.css'), 'utf8').replace(/\r\n/g, '\n');
check('有品牌下拉', src.includes('data-shop="brand"'));
check('有價格區間', src.includes('data-shop="min"') && src.includes('data-shop="max"'));
check('有排序', src.includes('data-shop="sort"'));
check('有清除條件', src.includes('data-shop="clear"'));
// 線上商品服務的 sort 與 minPrice/maxPrice 實測沒有作用（2026-08-28），
// 送出去只會得到一個沒有篩到的畫面，所以全部在本機做——
// Router.generalProductCatalog 本來就已經是整份清單。
check('在本機套用，不送 API', src.includes('const applyShopControls ='));
// 在 applyShopControls 的**整個區塊**裡找，不要用「從開頭起算 N 個字元內」。
// 原本寫死 700 字元，2026-08-29 在這個函式開頭加了關鍵字搜尋（連同註解十幾行），
// 就把這一行推出範圍而報 FAIL——程式碼沒壞，是斷言在量距離。
// 量距離的斷言會在每次重構時假性失敗，而假性失敗久了就沒有人再相信它。
const shopControlsBlock = (() => {
  const i = src.indexOf('const applyShopControls =');
  if (i < 0) return '';
  let d = 0;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') d++;
    else if (src[k] === '}') { d--; if (!d) return src.slice(i, k + 1); }
  }
  return '';
})();
check('沒有價格的商品不混進價格區間',
  /if \(price ===? null\) return false;/.test(shopControlsBlock));
// 排序時沒價格的排最後，不要因為 NaN 跑到最前面（NaN 的比較結果不可預期）
check('排序時沒價格的排最後', /byPrice[\s\S]{0,240}?if \(x === null\) return 1;/.test(src));
// 換條件要把「已展開幾筆」歸零，否則畫面停在第 60 筆看起來像沒反應
check('換條件後回到第一頁', /data-shop[\s\S]{0,1200}?Router\.shopVisible = SHOP_PAGE_SIZE;/.test(src));
check('筆數說明有篩選過', src.includes('件商品（已從 ${byCat.length} 件篩選）'));
check('控制列有樣式', shopCss.includes('.shop-controls'));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
