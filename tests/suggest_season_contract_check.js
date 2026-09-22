// /suggest 請求契約：faceAnalysis 要固定帶一個頂層 season，值只能是四季那四個字串。
//
// 為什麼需要一支測試守它：這個欄位**送錯了不會有任何錯誤訊息**。建議服務收不到季型時
// 照樣回 200、照樣生出一段建議，只是那段建議跟使用者的膚色無關——畫面完全正常，
// 沒有人會發現底妝那段是泛用的。實測缺欄位時它只在 missingFields 裡提一句，
// 而那個欄位前端沒有在看。
//
// 另一半是「不要送特徵與推薦色」：那份對照表由建議服務統一維護。前端如果哪天把
// season 從字串改成帶說明的物件，就會變成兩份定義各自演化，而且一樣沒有錯誤訊息。
// 所以這裡也釘住「它必須是字串或 null」。
//
// 用法：node tests/suggest_season_contract_check.js <web_frontend 路徑>
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('node:assert/strict');

const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const source = fs.readFileSync(path.join(root, 'js/api.js'), 'utf8').replace(/\r\n/g, '\n');

// 把真正的實作切出來跑。抄一份到測試裡的話，api.js 改壞了這裡不會知道。
const start = source.indexOf('const SUGGEST_SEASONS');
assert.notEqual(start, -1, '找不到 SUGGEST_SEASONS');
const tail = source.indexOf('\n};\n', source.indexOf('fromRawFaceAnalysis(', start));
assert.ok(tail > start, '找不到 AnalysisPackage 的結尾');
const slice = source.slice(start, tail + '\n};'.length);

// create() 會去讀 ImagePipeline 的壓縮設定。這支測試不管影像，給一個回 null 的替身，
// 讓 create() 跑得完就好——用 Proxy 而不是列舉欄位，之後那邊多讀一個設定也不會害這裡紅掉。
const sandbox = { ImagePipeline: new Proxy({}, { get: () => null }) };
vm.createContext(sandbox);
vm.runInContext(slice + '\nthis.__pkg = AnalysisPackage; this.__seasons = SUGGEST_SEASONS;', sandbox);
const AnalysisPackage = sandbox.__pkg;
const SEASONS = sandbox.__seasons;

let pass = 0, fail = 0;
const check = (name, cond, detail) => {
    console.log((cond ? '  PASS ' : '  FAIL ') + name + (detail ? `  ${detail}` : ''));
    cond ? pass++ : fail++;
};

const build = (seasonValue) => AnalysisPackage.fromRawFaceAnalysis({
    '臉型': '鵝蛋臉', '眉型': '一字眉', '眼型': '桃杏眼', '鼻型': '標準鼻', '嘴型': '厚唇',
    '膚色': { '四季型': seasonValue, '膚色分級': '自然色' },
}, 'basic');

console.log('');
console.log('/suggest season 契約');

// ① 欄位固定存在——連還沒分析的空包都要有這個鍵。
const empty = AnalysisPackage.create({ mode: 'basic' });
check('create() 的 faceAnalysis 帶有 season 鍵',
    Object.prototype.hasOwnProperty.call(empty.faceAnalysis, 'season'));
check('分析結果的頂層帶有 season 鍵',
    Object.prototype.hasOwnProperty.call(build('秋季'), 'season'));

// ② 四個合法值原樣送出。
check('白名單剛好是四季那四個',
    SEASONS.length === 4 && ['春季', '夏季', '秋季', '冬季'].every(s => SEASONS.includes(s)),
    JSON.stringify(SEASONS));
for (const season of ['春季', '夏季', '秋季', '冬季']) {
    check(`${season} 原樣送出`, build(season).season === season);
}

// ③ 認不得的值一律 null，不要原樣轉送給建議服務讓它自己猜。
//    這裡刻意用十二季型的寫法當樣本——舊資料包裡最可能出現的就是這種。
for (const junk of ['暖秋型', '淺春', 'autumn', '', '   ', null, undefined, 123]) {
    check(`認不得的值 ${JSON.stringify(junk)} → null`, build(junk).season === null);
}

// ④ 只送標籤，不送特徵與推薦色：值必須是字串或 null，不能變成物件。
for (const shape of ['秋季', '暖秋型', null]) {
    const value = build(shape).season;
    check(`${JSON.stringify(shape)} 的結果是字串或 null`,
        value === null || typeof value === 'string', typeof value);
}
const objectish = build({ name: '秋季', colors: ['#aa5533'] }).season;
check('把物件塞進四季型也不會被送出去', objectish === null, JSON.stringify(objectish));

// ⑤ 頂層與巢狀那份不可以分岔——兩邊都會被送到建議服務，說法不一致比缺欄位更難查。
for (const season of ['秋季', '暖秋型']) {
    const built = build(season);
    check(`${season}：頂層與 skinTone.season 一致`,
        built.season === built.skinTone.season,
        `${JSON.stringify(built.season)} vs ${JSON.stringify(built.skinTone.season)}`);
}

console.log('');
console.log(`  ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
