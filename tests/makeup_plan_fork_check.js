// 規劃方式分岔不能把既有的選風格流程包壞。
//
// 這支盯的是三件事，每一件壞掉都不會報錯、只會讓使用者走到錯的地方：
//   1. 沒選過規劃方式時要先問，選過就不再問（每次都問等於多一個沒必要的步驟）
//   2. 選「系統推薦」時要原封不動呼叫舊的視窗（舊流程是已上線的東西）
//   3. 記著要用化妝包、但化妝包是空的時候，要落回舊流程而不是卡住
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/makeup-plan.js'), 'utf8').replace(/\r\n/g, '\n');

function makeSandbox({ plan, bagCount }) {
  const store = new Map();
  if (plan) store.set('beautyMakeupPlan', plan);

  // 模組內部呼叫的是閉包裡的函式，不是 window 上那個，所以替身換不掉。
  // 改成觀察真正看得到的行為：舊視窗有沒有被呼叫、哪一個視窗被建出來。
  const calls = { direct: 0, created: [] };
  const el = () => {
    const node = {
      _id: '', className: '', innerHTML: '',
      setAttribute() {}, remove() {},
      querySelector() { return { onclick: null }; },
      querySelectorAll() { return []; },
    };
    Object.defineProperty(node, 'id', {
      get() { return node._id; },
      set(v) { node._id = v; if (v) calls.created.push(v); },
    });
    return node;
  };

  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    Array, Object, Promise, Set, Map, String, Number, Boolean, Math, JSON, RegExp,
    setTimeout: (fn) => { fn(); return 0; },
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    document: {
      getElementById: () => null,
      createElement: () => el(),
      body: { appendChild() {} },
    },
    STYLES: [{ id: 'hongKong', name: '港風', img: 'a.webp', tags: ['x'] }],
    escapeHtml: (v) => String(v == null ? '' : v),
    Router: { go() {}, selectedStyleId: null },
    Api: { recommendStyles: () => Promise.resolve({ ok: true, styles: [] }) },
    MakeupBag: { count: () => bagCount, localList: () => [] },
    MakeupBagApi: { bagId: null },
  };
  sandbox.window = sandbox;
  // 舊的選風格視窗。makeup-plan.js 必須把它包起來而不是取代掉。
  sandbox.openMakeupStyleModal = () => { calls.direct += 1; };

  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);

  return { sandbox, calls, store };
}

function check(label, actual, expected) {
  if (actual !== expected) throw new Error(`${label}：預期 ${expected}，實際 ${actual}`);
  console.log(`  PASS ${label}`);
}

console.log('=== 規劃方式分岔 ===\n');

// 1. 沒選過 → 先問
{
  const { sandbox, calls } = makeSandbox({ plan: null, bagCount: 3 });
  sandbox.openMakeupStyleModal('hongKong');
  check('沒選過規劃方式時跳出分岔視窗', calls.created.includes('makeupPlanModal'), true);
  check('  此時不該直接開舊視窗', calls.direct, 0);
}

// 2. 選了系統推薦 → 原封不動走舊流程
{
  const { sandbox, calls } = makeSandbox({ plan: 'system', bagCount: 3 });
  sandbox.openMakeupStyleModal('hongKong');
  check('選系統推薦時直接開舊視窗', calls.direct, 1);
  check('  不再問一次規劃方式', calls.created.includes('makeupPlanModal'), false);
}

// 3. 選了化妝包且包裡有東西 → 走反推
{
  const { sandbox, calls } = makeSandbox({ plan: 'makeupBag', bagCount: 5 });
  sandbox.openMakeupStyleModal('hongKong');
  check('選化妝包且有商品時走反推視窗', calls.created.includes('bagStyleModal'), true);
  check('  不走舊視窗', calls.direct, 0);
}

// 4. 記著要用化妝包、但包是空的 → 落回舊流程，不能卡住
{
  const { sandbox, calls } = makeSandbox({ plan: 'makeupBag', bagCount: 0 });
  sandbox.openMakeupStyleModal('hongKong');
  check('化妝包被清空時落回舊流程', calls.direct, 1);
  check('  不會卡在反推視窗', calls.created.includes('bagStyleModal'), false);
}

// 5. 舊視窗必須被保留下來，而不是被取代
{
  const { sandbox } = makeSandbox({ plan: 'system', bagCount: 0 });
  check('舊視窗有被保存成 __openStyleModalDirect',
    typeof sandbox.__openStyleModalDirect, 'function');
  check('  包過之後不是同一個函式', sandbox.openMakeupStyleModal === sandbox.__openStyleModalDirect, false);
}

// 6. 重複載入不可以把包裝再包一層（會變成兩層視窗）
{
  const { sandbox, calls } = makeSandbox({ plan: 'system', bagCount: 0 });
  const first = sandbox.__openStyleModalDirect;
  vm.runInContext(src, sandbox);
  check('重複載入不會重複包裝', sandbox.__openStyleModalDirect === first, true);
  sandbox.openMakeupStyleModal('hongKong');
  check('  仍然只呼叫舊視窗一次', calls.direct, 1);
}

console.log('\n規劃方式分岔測試通過');
