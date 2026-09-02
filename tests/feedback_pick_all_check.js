const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '../js/router.js'), 'utf8');
// 取出一個 const 定義的完整原始碼。
//
// 先前是 `const ${name} = ([\\s\\S]*?);`——抓到**第一個分號**就停。單行運算式沒問題，
// 但 fbTrainTargets 是區塊函式，body 裡的 `.map(...);` 會讓片段在中途被切斷，
// 丟進 vm 就是 SyntaxError: Unexpected end of input。那個錯誤看起來像 router.js
// 壞掉，實際上是這裡的擷取規則太窄——而 deploy.ps1 會跑這支，於是部署整個卡住。
//
// 改成掃大括號配對：有 body 的走配對，沒有 body 的走第一個頂層分號。
const expression = name => {
    const start = src.indexOf(`const ${name} = `);
    assert(start >= 0, name);
    let depth = 0;
    let sawBrace = false;
    let i = src.indexOf('=', start) + 1;
    for (; i < src.length; i++) {
        const ch = src[i];
        if (ch === '{') { depth++; sawBrace = true; }
        else if (ch === '}') { depth--; if (sawBrace && depth === 0) { i++; break; } }
        else if (ch === ';' && depth === 0 && !sawBrace) break;
    }
    return src.slice(start, i) + ';';
};
const items = [
    {feedbackId:'pending', hasSample:true},
    {feedbackId:'approved', hasSample:true, reviewStatus:'accepted', changes:[{field:'face'}], reviewDecisions:{face:'accepted'}},
    {feedbackId:'no-image'},
    {feedbackId:'rejected', hasSample:true, reviewStatus:'rejected'},
    {feedbackId:'queued', hasSample:true, trainingRunId:'run'}
];
const context = {fbItems:items, fbSelected:new Set(), fbBucket:it=>it.reviewStatus==='rejected'?'rejected':'pending', fbApprovedFields:it=>it.reviewStatus==='accepted'?['face']:[]};
vm.createContext(context);
vm.runInContext(expression('fbSelectable')+expression('fbTrainable')+expression('fbTrainTargets'), context);
const ids = expr => JSON.parse(vm.runInContext(`JSON.stringify(${expr})`, context));
assert.deepEqual(ids('fbSelectable().map(it=>it.feedbackId)'), ['pending','approved']);
context.fbSelected.add('pending');
assert.deepEqual(ids('fbTrainTargets()'), []);
context.fbSelected.add('approved');
assert.deepEqual(ids('fbTrainTargets()'), ['approved']);
const html=fs.readFileSync(path.join(__dirname,'../pages/admin.html'),'utf8');
assert(html.includes('id="adminFeedbackJumpReview"'));
assert(src.includes("feedbackBody.closest('.acp-deck')"));
console.log('PASS pending images selectable; missing/rejected/queued excluded; unreviewed selection never trains; review shortcut wired');
