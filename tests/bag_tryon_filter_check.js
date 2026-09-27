// 化妝包路線試妝後的推薦：只推化妝包沒涵蓋的部位。
//
// 2026-09-27 使用者回報：用化妝包試妝後，結果頁的「推薦商品」還在推包裡已經有、
// 而且剛剛才拿來試妝的同類商品。規則改成：
//   · 這個妝容用到的化妝包商品（contributingProducts）所屬的部位 → 不再推
//   · 包裡的粉底不參與風格反推，但不分風格一定用得上 → 底妝也算已涵蓋
//   · 使用者之後改走系統推薦或換了風格 → 回到完整推薦
//
// 另外守住新手難易度的順序（使用者定案）。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
let failed = 0;
const check = (name, ok) => {
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
  if (!ok) failed += 1;
};

// candidateKey 前綴 → 中文分類。這裡用最小對照表當替身；真正的對照在
// api.js 的 _normalizeProduct，那一段由 candidate_key_check 守。
const CAT = { lipsticks: '唇彩', blushes: '腮紅', eyeshadows: '眼影', foundations: '底妝' };
let bag = [];
const sandbox = {
  console,
  Router: { selectedStyleId: null, makeupBagPlan: null },
  MakeupBag: {
    localList: () => bag.slice(),
    count: () => bag.length,
    categoryOf: (k) => CAT[String(k).split(':')[0]] || '',
  },
  STYLES: [],
  setTimeout: () => 0,
  escapeHtml: (v) => String(v == null ? '' : v),
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  document: { getElementById: () => null },
};
sandbox.window = sandbox;
// install() 需要一個 openMakeupStyleModal 才會包；給個替身讓它安靜結束。
sandbox.openMakeupStyleModal = () => {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root, 'js/makeup-plan.js'), 'utf8'), sandbox);
const { BagTryOn, Router } = sandbox;

check('BagTryOn 有匯出到 window', !!BagTryOn);

const products = [
  { id: 1, cat: '唇彩' }, { id: 2, cat: '腮紅' }, { id: 3, cat: '眼影' },
  { id: 4, cat: '底妝' }, { id: 5, cat: '修容' },
];

// 沒走化妝包路線：原樣回傳
Router.selectedStyleId = 'hongKong';
check('不在化妝包路線時不過濾', BagTryOn.filter(products).length === products.length);

// 化妝包有唇彩、腮紅、粉底、一盤不適合港風的眼影；港風用到唇彩與腮紅
bag = ['lipsticks:2813', 'blushes:1', 'foundations:1464', 'eyeshadows:9'];
BagTryOn.record('hongKong', ['lipsticks:2813', 'blushes:1']);
const ids = BagTryOn.filter(products).map(p => p.id).join(',');
check(`只留化妝包沒涵蓋的部位（得到 ${ids}）`, ids === '3,5');
check('沒用到的眼影不算涵蓋——那個部位要由系統推薦補上', ids.includes('3'));
check('包裡的粉底算已涵蓋', !ids.includes('4'));
check('usedKeys 含粉底共 3 件', Router.makeupBagPlan.usedKeys.length === 3);

// contributingProducts 若改成物件陣列也要認得
BagTryOn.record('hongKong', [{ candidateKey: 'lipsticks:2813' }]);
check('contributingProducts 物件形狀也認得', BagTryOn.coveredCats().has('唇彩'));

// 同一類有兩件以上：讓使用者挑這次用哪一件
bag = ['lipsticks:1', 'lipsticks:2', 'lipsticks:3', 'blushes:1', 'foundations:7', 'foundations:8'];
const contributing = ['lipsticks:1', 'lipsticks:2', 'blushes:1'];   // lipsticks:3 不適合這款妝
const multi = BagTryOn.multiCategories(contributing, bag);
const multiDesc = multi.map(([c, ks]) => `${c}:${ks.length}`).join(',');
check(`只列出用得到且同類 ≥2 件的類別（得到 ${multiDesc}）`, multiDesc === '唇彩:2,底妝:2');
check('不適合這款妝的那支不列入選項', !multi.find(([c]) => c === '唇彩')[1].includes('lipsticks:3'));

BagTryOn.record('hongKong', contributing, { 唇彩: 'lipsticks:2', 底妝: 'foundations:8' });
const used = Router.makeupBagPlan.usedKeys.slice().sort().join(',');
check(`挑了之後每類只留那一件（得到 ${used}）`, used === 'blushes:1,foundations:8,lipsticks:2');
check('choices 有記下來', Router.makeupBagPlan.choices.唇彩 === 'lipsticks:2');
check('沒挑的類別不受影響', BagTryOn.usedKeys(contributing, bag, { 唇彩: 'lipsticks:1' }).includes('blushes:1'));

// 換了風格 → 不再套用
Router.selectedStyleId = 'yandere';
check('換風格後回到完整推薦', BagTryOn.filter(products).length === products.length);

// 改走系統推薦 → 清掉
Router.selectedStyleId = 'hongKong';
BagTryOn.clear();
check('clear 之後回到完整推薦', BagTryOn.filter(products).length === products.length);

// ── 新手難易度 ──
const dataSrc = fs.readFileSync(path.join(root, 'js/data.js'), 'utf8');
const dataBox = {};
vm.createContext(dataBox);
vm.runInContext(`${dataSrc}\nglobalThis.__STYLES = STYLES;`, dataBox);
const order = [...dataBox.__STYLES].sort((a, b) => a.difficulty - b.difficulty).map(s => s.id).join(' < ');
const expected = 'mensPlain < japaneseClear < koreanClean < yandere < hongKong < richGirl < softBaddie';
check(`難易度順序（${order}）`, order === expected);
check('難易度 1~7 各一個', dataBox.__STYLES.map(s => s.difficulty).sort().join('') === '1234567');

if (failed) {
  console.log(`\n${failed} 項失敗`);
  process.exit(1);
}
console.log('\n全部通過');
