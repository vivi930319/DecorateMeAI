// 膚色準度相關的拍照與基準流程（2026-09-28）。
//
//   1. 螢幕補光：手機預設開、倒數後才擷取、擷取完才收掉白光、檔名標記、取消不拍
//   2. 補光拍的照片不自動提亮（提亮會把膚色 L* 往上推）
//   3. 分析完的「這張是素顏嗎？加入膚色基準」：新分析開始時要收掉，不能把舊照片加進去
// 這些都在 router.js 的分析頁初始化裡，沒辦法單獨載入，所以用原始碼對照（先去掉註解）。
const fs = require('fs');
const path = require('path');

const root = process.argv[2] || path.join(__dirname, '..');
const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/[^\n]*/g, '$1');
const router = strip(fs.readFileSync(path.join(root, 'js/router.js'), 'utf8'));
const analysis = fs.readFileSync(path.join(root, 'pages/analysis.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'css/main.css'), 'utf8');

let failed = 0;
const check = (name, ok) => { console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`); if (!ok) failed += 1; };
const block = (sig) => {
    const i = router.indexOf(sig);
    if (i < 0) return '';
    let d = 0;
    for (let k = router.indexOf('{', i); k < router.length; k++) {
        if (router[k] === '{') d++;
        else if (router[k] === '}') { d--; if (!d) return router.slice(i, k + 1); }
    }
    return '';
};

console.log('=== 1. 螢幕補光 ===');
check('分析頁有補光開關', analysis.includes('id="screenLightToggle"'));
check('手機（觸控＋窄螢幕）預設開', /pointer: coarse\) and \(max-width: 900px\)/.test(router) && /screenLightToggle\.checked = saved == null \? phone/.test(router));
const light = block('function captureWithScreenLight(stream) {');
check('補光畫面是純白、蓋過所有東西', /\.screen-light \{[^}]*background: #fff/.test(css) && /\.screen-light \{[^}]*z-index: 10200/.test(css));
check('倒數 3 秒讓相機適應白光', /let left = 3/.test(light) && /setInterval\(/.test(light));
check('可以取消', /sl-cancel/.test(light) && /reject\(/.test(light));
const capture = block("document.getElementById('capturePhotoBtn').onclick = async () => {");
check('拍照前先開補光、取消就不拍', /captureWithScreenLight\(Router\.cameraStream\)/.test(capture) && /catch \(_\) \{ return; \}/.test(capture));
check('先擷取畫面，再收掉白光',
    capture.indexOf('ctx.drawImage(video, 0, 0)') > 0 && capture.indexOf('ctx.drawImage(video, 0, 0)') < capture.indexOf('closeLight()', capture.indexOf('ctx.drawImage')));
check('補光照片的檔名有標記', /basic-camera-screenlight\.jpg/.test(capture));

console.log('\n=== 2. 補光照片不自動提亮 ===');
const reg = block('async function bpRegisterFile(role, file) {');
check('自動提亮排除補光照片', /lum < 110 && !\/-screenlight\\\.\/\.test\(file\.name\)/.test(reg));

console.log('\n=== 3. 加入膚色基準的提示 ===');
check('分析結果下方有提示區', analysis.includes('id="skinBaselinePrompt"'));
check('分析完成時帶這次分析的 id', /SkinBaseline\.captureFromAnalysis\(Router\.analysisPackage\.faceAnalysis, analysisId\)/.test(router));
const prompt = block('function paintSkinBaselinePrompt(result, analysisId) {');
check('要使用者確認是素顏才加入', /是素顏，加入基準/.test(prompt) && /有上妝，不要加/.test(prompt) && /SkinBaseline\.addReading\(/.test(prompt));
check('新分析開始時收掉舊提示', /const runId = \+\+analysisRunId;\s*const baselinePrompt = document\.getElementById\('skinBaselinePrompt'\);\s*if \(baselinePrompt\) baselinePrompt\.hidden = true;/.test(router));

if (failed) { console.log(`\n${failed} 項失敗`); process.exit(1); }
console.log('\n膚色拍照與基準流程測試通過');
