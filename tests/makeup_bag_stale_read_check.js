// 化妝包的讀取不能拿過時的伺服器資料蓋掉剛寫進本機的東西。
//
// 加入是「先寫本機、再送伺服器」。若讀取比寫入早送出，伺服器回的是加入前那份；
// 以前 list() 會直接拿它覆蓋本機，剛放進去的商品就從畫面上消失——包裡只有那一件時，
// 化妝包整個看起來是空的（2026-10-24 使用者回報「有時候化妝包沒東西，但我已經存了」）。
//
// 這支直接跑 api.js 裡真正的 MakeupBag 物件，請求由測試控制先後順序。
//
// 用法：node tests/makeup_bag_stale_read_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = process.argv[2] || path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');

function matchBrace(text, from) {
  let depth = 0;
  const open = text.indexOf('{', from);
  for (let i = open; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}') { depth--; if (depth === 0) return i + 1; }
  }
  return -1;
}

function cutBlock(signature) {
  const start = src.indexOf(signature);
  if (start < 0) throw new Error(`找不到 ${signature}`);
  return src.slice(start, matchBrace(src, start));
}

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const reply = (body, status = 200) => ({ ok: status < 400, status, json: () => Promise.resolve(body) });

function makeBag() {
  const store = {};
  const pending = [];
  const sandbox = {
    console, Promise, Set, Map, JSON, String, Number, Array, Object, setTimeout,
    localStorage: {
      getItem: k => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
    },
    Auth: { isLoggedIn: () => true, getProfile: () => ({ email: 'member@example.com' }) },
    MakeupBagApi: {
      shape: 'member', limit: 200,
      base: () => 'https://gw.test',
      paths: () => ({ list: '/bag', add: () => '/bag', remove: k => `/bag/${k}` }),
      normalize: data => (data.items || []).map(r => ({ candidateKey: r.candidateKey, itemId: null, unavailable: false })),
    },
    Api: {
      _normalizeProduct: () => null,
      _fetchWithRelogin(url, opts) {
        const d = deferred();
        pending.push({ method: opts.method, url, resolve: d.resolve });
        return d.promise;
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(`${cutBlock('const MakeupBag = {')};\nglobalThis.MakeupBag = MakeupBag;`, sandbox);
  return { bag: sandbox.MakeupBag, pending };
}

let pass = 0, fail = 0;
const check = (ok, msg) => { if (ok) { pass++; console.log('  ok  ' + msg); } else { fail++; console.log('  FAIL ' + msg); } };

(async () => {
  // 1. 讀取先送出、加入後送出，讀取先回來（伺服器還沒有那件）
  {
    const { bag, pending } = makeBag();
    const listing = bag.list();
    const adding = bag.add('lipsticks:2');
    await tick();
    pending.find(p => p.method === 'GET').resolve(reply({ items: [] }));
    const res = await listing;
    check(bag.has('lipsticks:2'), '寫入途中回來的舊讀取不會蓋掉本機剛加的商品');
    check(res.items.some(i => i.candidateKey === 'lipsticks:2'), '畫面拿到的清單包含剛加的商品');
    pending.find(p => p.method === 'POST').resolve(reply({ created: true }));
    await adding;
    check(bag.has('lipsticks:2'), '加入完成後商品仍在');
  }

  // 2. 讀取送出後，加入整個完成，舊讀取才回來
  {
    const { bag, pending } = makeBag();
    const listing = bag.list();
    const adding = bag.add('blush:5');
    await tick();
    pending.find(p => p.method === 'POST').resolve(reply({ created: true }));
    await adding;
    pending.find(p => p.method === 'GET').resolve(reply({ items: [] }));
    await listing;
    check(bag.has('blush:5'), '寫入已完成但讀取是寫入前送出的，仍保留本機');
    await tick();
    check(pending.filter(p => p.method === 'GET').length === 2, '偵測到過時後會再讀一次伺服器');
  }

  // 3. 沒有任何寫入時，伺服器說了算（換裝置的情境要能被伺服器覆蓋）
  {
    const { bag, pending } = makeBag();
    const listing = bag.list();
    await tick();
    pending[0].resolve(reply({ items: [{ candidateKey: 'eyeliners:9' }] }));
    await listing;
    check(bag.has('eyeliners:9') && bag.count() === 1, '沒有寫入時以伺服器那份為準');
  }

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
